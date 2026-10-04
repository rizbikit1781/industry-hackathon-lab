"""Rolling-horizon replay of the Nov 25 - Dec 1, 2025 storm week.

Every morning the open set = tickets requested on or before that day (real arrivals) that no
policy has served yet. Policies share the same crews, ticket capacity and shift length.

- fifo:      oldest ticket first, nearest crew (road metres from depot), each crew drives
             nearest-neighbour order on road metres.
All policies use the same road-network distances and times (roads.matrix).
- optimized: risk priority + OR-Tools VRP (solver.plan_day).
- optimized + disruption: day 3 (Nov 27) 30% of crews go out after the morning plan -> replan;
  day 7 (Dec 1) the day's real arrivals land mid-day as a surge -> replan. Both replans use the
  stability penalty and report jobs moved.
"""
from __future__ import annotations

import json
import time
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

from . import risk as R
from . import features as F
from . import roads
from .dedupe import assign_clusters
from .solver import SERVICE_MIN, SKILL_OF, Crew, Plan, jobs_moved, plan_day, PEN_SCALE

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DAYS = pd.date_range("2025-11-25", "2025-12-01", freq="D")
JOBS_PER_CREW = {"bylaw": 20, "roads": 12}      # tickets / crew / day (assumption; crews calibrated)
CHUNK = {"bylaw": 4, "roads": 3}                 # max tickets bundled into one stop


# ---------------------------------------------------------------- data

def load_tickets(weights: dict | None = None) -> pd.DataFrame:
    t = pd.read_csv(DATA / "tickets_storm_week.csv", parse_dates=["requested_date", "closed_date"])
    t = t.dropna(subset=["latitude", "longitude"]).copy()
    t["skill"] = t["service_name"].map(SKILL_OF)
    t = R.score_tickets(t, weights)
    t["in_week"] = t["requested_date"] >= DAYS[0]
    # warm start: prior-week tickets still open on the first morning (real closed_date)
    t["warm"] = (~t["in_week"]) & (t["closed_date"].isna() | (t["closed_date"] >= DAYS[0]))
    t = t[t["in_week"] | t["warm"]].reset_index(drop=True)
    # high-risk = top quartile of static exposure among storm-week tickets, within each skill
    t["high_risk"] = False
    for s, g in t[t["in_week"]].groupby("skill"):
        thr = g["exposure"].quantile(0.75)
        t.loc[g.index, "high_risk"] = g["exposure"] >= thr
    return t


def calibrate_capacity(all_tickets: pd.DataFrame | None = None) -> dict:
    """Median real daily closures per skill over the storm week -> crews x tickets/crew."""
    if all_tickets is None:
        all_tickets = pd.read_csv(DATA / "tickets_storm_week.csv",
                                  parse_dates=["requested_date", "closed_date"])
    a = all_tickets.copy()
    a["skill"] = a["service_name"].map(SKILL_OF)
    a = a[a["closed_date"].between(DAYS[0], DAYS[-1])]
    daily = a.groupby(["skill", "closed_date"]).size().unstack(0).reindex(DAYS).fillna(0)
    out = {}
    for s in ("bylaw", "roads"):
        med = float(daily[s].median())
        n = max(1, int(round(med / JOBS_PER_CREW[s])))
        out[s] = {"median_daily_closures": med, "daily_closures": daily[s].astype(int).tolist(),
                  "crews": n, "tickets_per_crew": JOBS_PER_CREW[s],
                  "daily_capacity": n * JOBS_PER_CREW[s]}
    return out


def make_crews(cap: dict, tickets: pd.DataFrame) -> list[Crew]:
    """Depots at the centroid of each city sector's community representative points (assumption:
    real district-office locations are not published). Crews are spread over sectors in order of
    that skill's ticket volume."""
    comm = pd.read_csv(DATA / "community_features.csv", index_col=0)
    sect = comm.groupby("sector")[["rep_lat", "rep_lon"]].mean()
    tk = tickets[tickets["in_week"]].join(comm[["sector"]], on="comm_code")
    crews = []
    for s in ("bylaw", "roads"):
        order = tk[tk["skill"] == s]["sector"].value_counts().index.tolist()
        order += [x for x in sect.index if x not in order]
        for i in range(cap[s]["crews"]):
            sec = order[i % len(order)]
            crews.append(Crew(id=f"{s[0].upper()}{i + 1:02d}", skill=s,
                              depot_lat=float(sect.at[sec, "rep_lat"]),
                              depot_lon=float(sect.at[sec, "rep_lon"]),
                              shift_min=480, capacity=cap[s]["tickets_per_crew"]))
    return crews


def build_jobs(open_t: pd.DataFrame, day: pd.Timestamp, dyn_weights=None,
               expo_weight: float | None = None) -> tuple[pd.DataFrame, dict]:
    """Cluster open tickets (same service, within 50 m -> on public data: same community
    centrepoint), then bundle each cluster oldest-first into stops of <= CHUNK tickets."""
    t = open_t.copy()
    t["cluster"] = assign_clusters(t, eps_m=50, days=10_000).to_numpy()
    t["report_count"] = t.groupby("cluster")["service_request_id"].transform("size")
    t["days_open"] = (day - t["requested_date"]).dt.days
    t["priority"] = R.priority(t["exposure"], t["report_count"], t["days_open"],
                               dyn_weights, expo_weight)
    rows, members = [], {}
    for cl, g in t.sort_values(["requested_date", "service_request_id"]).groupby("cluster", sort=False):
        skill = g["skill"].iat[0]
        for k in range(0, len(g), CHUNK[skill]):
            ch = g.iloc[k:k + CHUNK[skill]]
            jid = f"{day:%m%d}-{zlib.crc32(cl.encode()) % 10**6:06d}-{k // CHUNK[skill]}"
            members[jid] = ch["service_request_id"].tolist()
            rows.append({"job_id": jid, "skill": skill, "service_name": ch["service_name"].iat[0],
                         "comm_code": ch["comm_code"].iat[0], "lat": ch["latitude"].mean(),
                         "lon": ch["longitude"].mean(), "n_tickets": len(ch),
                         "service_min": SERVICE_MIN[skill] * len(ch),
                         "value": float(ch["priority"].sum()),
                         "priority": float(ch["priority"].mean()),
                         "exposure": float(ch["exposure"].mean()),
                         "n_high_risk": int(ch["high_risk"].sum()),
                         "report_count": int(ch["report_count"].iat[0]),
                         "oldest": ch["requested_date"].min().strftime("%Y-%m-%d"),
                         "reason": ch["reason"].iat[0]})
    return pd.DataFrame(rows), members


# ---------------------------------------------------------------- policies

def fifo_day(open_t: pd.DataFrame, crews: list[Crew]) -> tuple[Plan, dict, list]:
    """Oldest-first assignment to the nearest crew with remaining capacity; NN sequencing;
    tickets that don't fit the shift stay open. Returns plan, members (stop -> tickets), served."""
    t = open_t.sort_values(["requested_date", "service_request_id"])
    plan, members, served = Plan(), {}, []
    for skill in ("bylaw", "roads"):
        cs = [c for c in crews if c.skill == skill]
        if not cs:
            continue
        tt = t[t["skill"] == skill].head(sum(c.capacity for c in cs))
        V = len(cs)
        lat = np.r_[[c.depot_lat for c in cs], tt["latitude"].to_numpy(float)]
        lon = np.r_[[c.depot_lon for c in cs], tt["longitude"].to_numpy(float)]
        Mm, Mt = roads.matrix(lat, lon)            # road metres / minutes, row = from
        sids = tt["service_request_id"].tolist()
        load = {c.id: [] for c in cs}
        for i in range(len(tt)):
            for k in np.argsort(Mm[:V, V + i], kind="stable"):
                c = cs[k]
                if len(load[c.id]) < c.capacity:
                    load[c.id].append(V + i)
                    break
        for k_c, c in enumerate(cs):
            todo, pos, mins, metres, route = list(load[c.id]), k_c, 0.0, 0.0, []
            while todo:
                dd = Mm[pos, todo]
                k = int(np.argmin(dd))
                x = todo[k]
                need = Mt[pos, x] + Mt[x, k_c] + SERVICE_MIN[skill]
                if mins + need > c.shift_min:
                    todo.pop(k)                      # doesn't fit today; stays open
                    continue
                mins += Mt[pos, x] + SERVICE_MIN[skill]
                metres += Mm[pos, x]
                pos = x
                sid = sids[x - V]
                route.append(sid)
                members[sid] = [sid]
                plan.eta_min[sid] = int(mins - SERVICE_MIN[skill])
                served.append(sid)
                todo.pop(k)
            metres += Mm[pos, k_c]
            mins += Mt[pos, k_c]
            plan.routes[c.id] = route
            plan.crew_minutes[c.id] = int(mins)
            plan.crew_km[c.id] = round(metres / 1000, 2)
            plan.km += metres / 1000
    return plan, members, served


def _served_from(plan: Plan, members: dict) -> list:
    return [s for js in plan.routes.values() for j in js for s in members[j]]


def run(policy: str, tickets: pd.DataFrame, crews: list[Crew], disruption: list | None = None,
        time_limit_s: float = 5, pen_scale: float = PEN_SCALE, dyn_weights=None,
        expo_weight: float | None = None, days=DAYS, verbose: bool = True) -> dict:
    t = tickets.copy()
    t["served_day"] = pd.NaT
    t["served_by"] = None
    disruption = {d["day"]: d for d in (disruption or [])}
    out_days, replans = [], []
    for di, day in enumerate(days):
        known = t["requested_date"] <= day
        open_mask = known & t["served_day"].isna()
        dis = disruption.get(di)
        day_crews = list(crews)
        info = {"day": day.strftime("%Y-%m-%d"), "open_morning": int(open_mask.sum()),
                "arrivals": int((t["requested_date"] == day).sum())}
        t0 = time.time()
        if policy == "fifo":
            plan, members, _ = fifo_day(t[open_mask], day_crews)
            jobs = None
        else:
            if dis and dis.get("surge"):
                # morning plan only sees tickets up to yesterday; today's arrivals land mid-day
                morning_mask = (t["requested_date"] < day) & t["served_day"].isna()
                mjobs, mmembers = build_jobs(t[morning_mask], day, dyn_weights, expo_weight)
                morning = plan_day(mjobs, day_crews, time_limit_s=time_limit_s, pen_scale=pen_scale)
            jobs, members = build_jobs(t[open_mask], day, dyn_weights, expo_weight)
            if dis and dis.get("surge"):
                # map morning stops onto the full job set by identical member lists
                key = {tuple(v): k for k, v in members.items()}
                remap = {j: key.get(tuple(mmembers[j])) for js in morning.routes.values() for j in js}
                prev = {remap[j]: c for j, c in morning.assignment().items() if remap.get(j)}
                init = {c: [remap[j] for j in r if remap.get(j)] for c, r in morning.routes.items()}
                morning_m = Plan(routes=init)
                t1 = time.time()
                plan = plan_day(jobs, day_crews, prev_assignment=prev, time_limit_s=time_limit_s,
                                pen_scale=pen_scale, initial_routes=init)
                replans.append(_replan_record("surge", day, morning_m, plan, t, members,
                                              time.time() - t1, n_new=info["arrivals"]))
            else:
                plan = plan_day(jobs, day_crews, time_limit_s=time_limit_s, pen_scale=pen_scale)
            if dis and dis.get("crews_out"):
                n_out = int(round(dis["crews_out"] * len(crews)))
                # take crews out proportionally per skill
                out_ids = []
                for s in ("bylaw", "roads"):
                    cs = [c for c in crews if c.skill == s]
                    out_ids += [c.id for c in cs[:int(round(dis["crews_out"] * len(cs)))]]
                remaining = [c for c in crews if c.id not in out_ids]
                t1 = time.time()
                new = plan_day(jobs, remaining, prev_assignment=plan.assignment(),
                               time_limit_s=time_limit_s, pen_scale=pen_scale,
                               initial_routes={c.id: plan.routes.get(c.id, []) for c in remaining})
                replans.append(_replan_record("crews_out", day, plan, new, t, members,
                                              time.time() - t1, crews_out=out_ids))
                plan = new
                day_crews = remaining
        served = _served_from(plan, members)
        t.loc[t["service_request_id"].isin(served), "served_day"] = day
        a = plan.assignment()
        for j, c in a.items():
            t.loc[t["service_request_id"].isin(members[j]), "served_by"] = c
        info.update({"served": len(served), "km": round(plan.km, 1),
                     "stops": int(sum(len(r) for r in plan.routes.values())),
                     "solve_s": round(time.time() - t0, 2),
                     "high_risk_served": int(t[t["service_request_id"].isin(served)]["high_risk"].sum()),
                     "crews_active": len(day_crews)})
        out_days.append({"info": info, "plan": plan, "members": members, "jobs": jobs})
        if verbose:
            print(f"  [{policy}] {info}")
    return {"policy": policy, "tickets": t, "days": out_days, "replans": replans,
            "metrics": metrics(t, out_days, replans)}


def _replan_record(kind, day, old: Plan, new: Plan, t, members, secs, **kw):
    hr = set(t.loc[t["high_risk"], "service_request_id"])

    def hr_planned(p):
        return sum(1 for js in p.routes.values() for j in js for s in members.get(j, []) if s in hr)
    return {"kind": kind, "day": day.strftime("%Y-%m-%d"), "jobs_moved": jobs_moved(old, new),
            "jobs_before": sum(len(r) for r in old.routes.values()),
            "high_risk_planned_before": hr_planned(old), "high_risk_planned_after": hr_planned(new),
            "replan_s": round(secs, 2), **kw}


def metrics(t: pd.DataFrame, days: list, replans: list) -> dict:
    w = t[t["in_week"]].copy()
    last = DAYS[-1]
    w["wait"] = (w["served_day"] - w["requested_date"]).dt.days
    cens = (last + pd.Timedelta(days=1) - w["requested_date"]).dt.days
    w["wait_c"] = w["wait"].fillna(cens)
    hr = w[w["high_risk"]]
    within = lambda d: float((d["wait"] <= 1).mean())         # served by end of next day
    stops = sum(d["info"]["stops"] for d in days)
    served = int(w["served_day"].notna().sum()) + int(t[~t["in_week"]]["served_day"].notna().sum())
    return {
        "high_risk_within_48h": within(hr),
        "all_within_48h": within(w),
        "high_risk_served": float(hr["served_day"].notna().mean()),
        "low_risk_served": float(w[w["exposure"] <= w["exposure"].quantile(0.25)]["served_day"].notna().mean()),
        "p90_days_to_service": float(np.percentile(w["wait_c"], 90)),
        "p90_days_high_risk": float(np.percentile(hr["wait_c"], 90)),
        "median_days_to_service": float(np.median(w["wait_c"])),
        "tickets_served": served,
        "backlog_end": int(t["served_day"].isna().sum()),
        "total_km": float(sum(d["info"]["km"] for d in days)),
        "km_per_ticket": float(sum(d["info"]["km"] for d in days) / max(served, 1)),
        "stops": int(stops),
        "stops_consolidated": int(served - stops),
        "jobs_moved_per_replan": (float(np.mean([r["jobs_moved"] for r in replans]))
                                  if replans else None),
        "replan_s_max": max((r["replan_s"] for r in replans), default=None),
    }


# ---------------------------------------------------------------- export for UI

def export(results: dict, crews: list[Crew], cap: dict, extra: dict, path=DATA / "results.json"):
    comm = pd.read_csv(DATA / "community_features.csv", index_col=0)
    out = {"days": [d.strftime("%Y-%m-%d") for d in DAYS], "capacity": cap,
           "routing": {"method": roads.method(), "winter_speed_factor": roads.WINTER_SPEED_FACTOR,
                       "geometry": "road-following [lon, lat] polyline per route (key 'geometry'); "
                                   "'path' is depot -> stops -> depot"},
           "crews": [c.__dict__ for c in crews], "policies": {}, **extra}
    for name, res in results.items():
        t = res["tickets"].set_index("service_request_id")
        pol = {"metrics": res["metrics"], "replans": res["replans"], "daily": []}
        for d in res["days"]:
            plan, members = d["plan"], d["members"]
            crew_by_id = {c.id: c for c in crews}
            routes = []
            for cid, js in plan.routes.items():
                c = crew_by_id[cid]
                pts = [[c.depot_lon, c.depot_lat]]
                for j in js:
                    s = members[j][0]
                    pts.append([float(t.at[s, "longitude"]), float(t.at[s, "latitude"])])
                pts.append([c.depot_lon, c.depot_lat])
                geom = roads.path([p[1] for p in pts], [p[0] for p in pts],
                                  simplify_deg=roads.GEOMETRY_SIMPLIFY_DEG) if js else []
                routes.append({"crew": cid, "skill": c.skill, "path": pts, "geometry": geom,
                               "stops": len(js),
                               "km": plan.crew_km.get(cid), "minutes": plan.crew_minutes.get(cid)})
            # open-ticket markers aggregated per (community, skill) for the map
            day = pd.Timestamp(d["info"]["day"])
            vis = res["tickets"][(res["tickets"]["requested_date"] <= day)]
            vis = vis[vis["served_day"].isna() | (vis["served_day"] >= day)]
            vis = vis.assign(served_today=vis["served_day"].eq(day))
            g = vis.groupby(["comm_code", "skill"]).agg(
                lat=("latitude", "first"), lon=("longitude", "first"), open=("service_request_id", "size"),
                served_today=("served_today", "sum"), exposure=("exposure", "mean"),
                high_risk=("high_risk", "sum"), reason=("reason", "first")).reset_index()
            g["name"] = g["comm_code"].map(comm["name"])
            pol["daily"].append({"info": d["info"], "routes": routes,
                                 "markers": g.round(4).to_dict("records")})
        out["policies"][name] = pol
    Path(path).write_text(json.dumps(out, default=str))
    return out


# ---------------------------------------------------------------- sweep

def sweep(tickets: pd.DataFrame, crews: list[Crew], day_index: int = 0,
          pen_scales=(2_000, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000),
          time_limit_s: float = 4) -> dict:
    """Policy knob sweep on one day: lambda (metres of driving one unit of priority is worth)
    vs high-risk tickets planned and km. Plus feature-weight presets: overlap of each preset's
    high-risk set with the default one."""
    day = DAYS[day_index]
    open_t = tickets[tickets["requested_date"] <= day]
    jobs, members = build_jobs(open_t, day)
    hr = set(tickets.loc[tickets["high_risk"], "service_request_id"])
    curve = []
    for ps in pen_scales:
        p = plan_day(jobs, crews, time_limit_s=time_limit_s, pen_scale=ps)
        served = _served_from(p, members)
        curve.append({"pen_scale": ps, "km": round(p.km, 1), "tickets": len(served),
                      "high_risk": sum(1 for s in served if s in hr)})
    base = tickets[tickets["in_week"]]
    feat = base[F.POINT_FEATURES + F.COMMUNITY_FEATURES]
    presets = []
    d_top = set(base.loc[base["high_risk"], "service_request_id"])
    for name, w in R.PRESETS.items():
        e = R.exposure(feat, w)
        top = set()
        for _, g in base.assign(e=e).groupby("skill"):          # same per-skill quartile as default
            top |= set(g.loc[g["e"] >= g["e"].quantile(0.75), "service_request_id"])
        presets.append({"preset": name, "jaccard_with_default_top25": round(
            len(top & d_top) / max(len(top | d_top), 1), 3)})
    return {"day": day.strftime("%Y-%m-%d"), "lambda_curve": curve, "presets": presets}


PRIORITY_GRID = [(1, {"report_pressure": 1, "age": 1}), (2, {"report_pressure": 1, "age": 1}),
                 (3, {"report_pressure": 0.5, "age": 1}), (4, {"report_pressure": 0.5, "age": 0.5})]


def priority_sweep(tickets, crews, time_limit_s: float = 1.0) -> list:
    """Full-week replays over priority-weight settings: the 'agent adjusts its own rule' table."""
    out = []
    for ew, dw in PRIORITY_GRID:
        m = run("optimized", tickets, crews, time_limit_s=time_limit_s, expo_weight=ew,
                dyn_weights=dw, verbose=False)["metrics"]
        out.append({"exposure_w": ew, **{f"{k}_w": v for k, v in dw.items()},
                    **{k: round(m[k], 3) for k in ("high_risk_within_48h", "all_within_48h",
                                                   "high_risk_served", "low_risk_served",
                                                   "p90_days_to_service", "total_km")}})
    return out
