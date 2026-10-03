"""Daily crew routing: OR-Tools VRP with skills, shift time, ticket capacity, drop penalties
(prize-collecting) and a plan-stability penalty.

Jobs are solved per skill (sidewalk -> bylaw, roads/pathway -> roads), so skill matching is exact.
Travel = haversine x 1.3 road factor at 30 km/h. Units: metres for cost, minutes for time.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .dedupe import haversine_m

ROAD_FACTOR = 1.3
SPEED_M_PER_MIN = 30_000 / 60
SKILL_OF = {
    "Bylaw - Snow and Ice on Sidewalk": "bylaw",
    "Roads - Snow and Ice Control": "roads",
    "Roads - Pathway Snow and Ice Concerns": "roads",
}
SERVICE_MIN = {"bylaw": 10, "roads": 20}      # per ticket (inspection / treatment)
PEN_SCALE = 100_000                            # metres of driving one unit of value is worth
STABILITY_M = 3_000                            # metres-equivalent cost of moving a job to another crew


@dataclass
class Crew:
    id: str
    skill: str
    depot_lat: float
    depot_lon: float
    shift_min: int = 480
    capacity: int = 20                         # tickets per day (calibrated in sim)


@dataclass
class Plan:
    routes: dict = field(default_factory=dict)        # crew_id -> [job_id, ...]
    dropped: list = field(default_factory=list)
    km: float = 0.0
    served_value: float = 0.0
    crew_minutes: dict = field(default_factory=dict)
    crew_km: dict = field(default_factory=dict)
    eta_min: dict = field(default_factory=dict)       # job_id -> arrival minute in shift
    solve_s: float = 0.0

    def assignment(self) -> dict:
        return {j: c for c, js in self.routes.items() for j in js}

    def to_dict(self):
        return {"routes": self.routes, "dropped": self.dropped, "km": round(self.km, 2),
                "served_value": round(self.served_value, 3), "crew_minutes": self.crew_minutes,
                "crew_km": self.crew_km, "eta_min": self.eta_min, "solve_s": round(self.solve_s, 2)}


def _dist_matrix(lat, lon):
    lat, lon = np.asarray(lat), np.asarray(lon)
    d = haversine_m(lat[:, None], lon[:, None], lat[None, :], lon[None, :]) * ROAD_FACTOR
    return np.rint(d).astype(np.int64)


def route_stats(order_latlon, depot, service_min_list):
    """Minutes and metres for a fixed order (used by FIFO and for deltas)."""
    pts = [depot] + list(order_latlon) + [depot]
    lat = np.array([p[0] for p in pts])
    lon = np.array([p[1] for p in pts])
    seg = haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:]) * ROAD_FACTOR
    minutes = seg.sum() / SPEED_M_PER_MIN + sum(service_min_list)
    return float(minutes), float(seg.sum())


def _solve_skill(jobs: pd.DataFrame, crews: list[Crew], prev: dict | None, time_limit_s: float,
                 pen_scale: float, stability_m: float, initial_routes: dict | None) -> Plan:
    plan = Plan()
    if not crews:
        plan.dropped = jobs["job_id"].tolist()
        return plan
    if jobs.empty:
        plan.routes = {c.id: [] for c in crews}
        return plan
    V, N = len(crews), len(jobs)
    lat = np.r_[[c.depot_lat for c in crews], jobs["lat"].to_numpy()]
    lon = np.r_[[c.depot_lon for c in crews], jobs["lon"].to_numpy()]
    D = _dist_matrix(lat, lon)
    svc = np.r_[np.zeros(V), jobs["service_min"].to_numpy()].astype(np.int64)
    T = np.rint(D / SPEED_M_PER_MIN).astype(np.int64) + svc[:, None]     # service at from-node
    demand = np.r_[np.zeros(V), jobs["n_tickets"].to_numpy()].astype(np.int64)
    job_ids = jobs["job_id"].tolist()

    mgr = pywrapcp.RoutingIndexManager(V + N, V, list(range(V)), list(range(V)))
    rm = pywrapcp.RoutingModel(mgr)
    crew_idx = {c.id: k for k, c in enumerate(crews)}

    # arc costs (per vehicle when stability applies)
    prev = prev or {}
    moved_cols = np.zeros((V, V + N), dtype=np.int64)
    if prev and stability_m > 0:
        for n, jid in enumerate(job_ids):
            pc = prev.get(jid)
            if pc in crew_idx:
                for k in range(V):
                    if k != crew_idx[pc]:
                        moved_cols[k, V + n] = int(stability_m)
    if moved_cols.any():
        for k in range(V):
            M = (D + moved_cols[k][None, :]).tolist()
            cb = rm.RegisterTransitMatrix(M)
            rm.SetArcCostEvaluatorOfVehicle(cb, k)
    else:
        cb = rm.RegisterTransitMatrix(D.tolist())
        rm.SetArcCostEvaluatorOfAllVehicles(cb)

    t_cb = rm.RegisterTransitMatrix(T.tolist())
    rm.AddDimensionWithVehicleCapacity(t_cb, 0, [c.shift_min for c in crews], True, "time")
    d_cb = rm.RegisterUnaryTransitVector(demand.tolist())
    rm.AddDimensionWithVehicleCapacity(d_cb, 0, [c.capacity for c in crews], True, "load")

    vals = jobs["value"].to_numpy()
    for n in range(N):
        rm.AddDisjunction([mgr.NodeToIndex(V + n)], int(max(1, vals[n] * pen_scale)))

    p = pywrapcp.DefaultRoutingSearchParameters()
    p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    p.time_limit.FromMilliseconds(int(time_limit_s * 1000))

    t0 = time.time()
    sol = None
    if initial_routes:
        pos = {jid: V + n for n, jid in enumerate(job_ids)}
        routes = [[mgr.NodeToIndex(pos[j]) for j in initial_routes.get(c.id, []) if j in pos]
                  for c in crews]
        rm.CloseModelWithParameters(p)
        init = rm.ReadAssignmentFromRoutes(routes, True)
        if init is not None:
            sol = rm.SolveFromAssignmentWithParameters(init, p)
    if sol is None:
        sol = rm.SolveWithParameters(p)
    plan.solve_s = time.time() - t0
    if sol is None:
        plan.routes = {c.id: [] for c in crews}
        plan.dropped = job_ids
        return plan

    tdim = rm.GetDimensionOrDie("time")
    served = set()
    for k, c in enumerate(crews):
        idx = rm.Start(k)
        route, metres = [], 0
        while not rm.IsEnd(idx):
            nxt = sol.Value(rm.NextVar(idx))
            node = mgr.IndexToNode(idx)
            if node >= V:
                jid = job_ids[node - V]
                route.append(jid)
                plan.eta_min[jid] = int(sol.Min(tdim.CumulVar(idx)))
                served.add(node - V)
            metres += D[node, mgr.IndexToNode(nxt)]
            idx = nxt
        plan.routes[c.id] = route
        plan.crew_minutes[c.id] = int(sol.Min(tdim.CumulVar(idx)))
        plan.crew_km[c.id] = round(metres / 1000, 2)
        plan.km += metres / 1000
    plan.dropped = [job_ids[n] for n in range(N) if n not in served]
    plan.served_value = float(sum(vals[n] for n in served))
    return plan


def _merge(a: Plan, b: Plan) -> Plan:
    out = Plan()
    for p in (a, b):
        out.routes.update(p.routes)
        out.dropped += p.dropped
        out.km += p.km
        out.served_value += p.served_value
        out.crew_minutes.update(p.crew_minutes)
        out.crew_km.update(p.crew_km)
        out.eta_min.update(p.eta_min)
        out.solve_s += p.solve_s
    return out


def plan_day(jobs: pd.DataFrame, crews: list[Crew], prev_assignment: dict | None = None,
             time_limit_s: float = 10, pen_scale: float = PEN_SCALE,
             stability_m: float = STABILITY_M, max_candidates_factor: float = 2.0,
             initial_routes: dict | None = None) -> Plan:
    """Solve one day. `jobs` needs job_id, lat, lon, skill, n_tickets, service_min, value.

    To keep the VRP small, each skill only considers its highest-value jobs up to
    `max_candidates_factor` x the skill's ticket capacity (plus any previously assigned job).
    """
    plan = Plan()
    for skill in ("bylaw", "roads"):
        cs = [c for c in crews if c.skill == skill]
        js = jobs[jobs["skill"] == skill].sort_values("value", ascending=False)
        cap = sum(c.capacity for c in cs)
        keep = js["n_tickets"].cumsum() <= max_candidates_factor * max(cap, 1)
        if prev_assignment:
            keep |= js["job_id"].isin(list(prev_assignment))
        if initial_routes:
            keep |= js["job_id"].isin([j for r in initial_routes.values() for j in r])
        cand, rest = js[keep], js[~keep]
        p = _solve_skill(cand, cs, prev_assignment, time_limit_s, pen_scale, stability_m,
                         initial_routes)
        p.dropped += rest["job_id"].tolist()
        plan = _merge(plan, p)
    return plan


def jobs_moved(old: Plan, new: Plan) -> int:
    """Jobs that were planned in `old` and are now on a different crew or dropped."""
    a, b = old.assignment(), new.assignment()
    return sum(1 for j, c in a.items() if j in b and b[j] != c) + \
        sum(1 for j in a if j not in b)


def insert_job(plan: Plan, job: dict, jobs: pd.DataFrame, crews: list[Crew],
               time_limit_s: float = 2.0, stability_m: float = 20_000) -> dict:
    """Insert a new job into an existing plan with a strong stability penalty.

    Returns the crew, position (0-based), job it follows, delta minutes on that crew's shift,
    and the new plan. The current routes plus a cheapest insertion are the warm start.
    """
    jobs2 = pd.concat([jobs, pd.DataFrame([job])], ignore_index=True)
    jdx = jobs2.set_index("job_id")
    skill_crews = [c for c in crews if c.skill == job["skill"]]
    # cheapest feasible insertion as warm start
    best = None
    for c in skill_crews:
        r = plan.routes.get(c.id, [])
        for pos in range(len(r) + 1):
            order = r[:pos] + [job["job_id"]] + r[pos:]
            ll = [(jdx.at[j, "lat"], jdx.at[j, "lon"]) for j in order]
            sv = [jdx.at[j, "service_min"] for j in order]
            mins, _ = route_stats(ll, (c.depot_lat, c.depot_lon), sv)
            load = sum(jdx.at[j, "n_tickets"] for j in order)
            if mins <= c.shift_min and load <= c.capacity and (best is None or mins < best[0]):
                best = (mins, c.id, pos)
    init = {k: list(v) for k, v in plan.routes.items()}
    if best:
        init[best[1]].insert(best[2], job["job_id"])
    prev = plan.assignment()
    planned = jobs2[jobs2["job_id"].isin(list(prev) + [job["job_id"]])]
    t0 = time.time()
    new = plan_day(planned, crews, prev_assignment=prev, time_limit_s=time_limit_s,
                   stability_m=stability_m, max_candidates_factor=10, initial_routes=init)
    solve_s = time.time() - t0
    crew_id = new.assignment().get(job["job_id"])
    if crew_id is None:
        return {"inserted": False, "crew_id": None, "position": None, "inserted_after": None,
                "delta_min": 0.0, "jobs_moved": jobs_moved(plan, new), "plan": new,
                "solve_s": round(solve_s, 2)}
    route = new.routes[crew_id]
    pos = route.index(job["job_id"])
    c = next(c for c in crews if c.id == crew_id)

    def mins(r):
        ll = [(jdx.at[j, "lat"], jdx.at[j, "lon"]) for j in r]
        return route_stats(ll, (c.depot_lat, c.depot_lon), [jdx.at[j, "service_min"] for j in r])[0]

    delta = mins(route) - mins(plan.routes.get(crew_id, []))
    return {"inserted": True, "crew_id": crew_id, "position": pos,
            "inserted_after": route[pos - 1] if pos > 0 else "depot",
            "delta_min": round(delta, 1), "eta_min": new.eta_min.get(job["job_id"]),
            "jobs_moved": jobs_moved(plan, new), "plan": new, "solve_s": round(solve_s, 2)}
