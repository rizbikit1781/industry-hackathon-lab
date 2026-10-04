"""FastAPI decision engine: voice-ticket intake, disruption replans, plan, metrics, briefings.

Run:  .venv/bin/uvicorn civicsignal.api:app --port 8000
State is in memory, seeded with the City's *real* open snow/ice queue on the morning of
CIVICSIGNAL_DAY (default 2025-11-26): tickets requested on or before that day whose real
closed_date is on/after it.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import replace
from itertools import count

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sklearn.neighbors import BallTree

from . import features as F
from . import ingest as I
from . import risk as R
from . import sim
from .dedupe import find_duplicate
from .solver import SERVICE_MIN, SKILL_OF, Plan, insert_job, jobs_moved, plan_day

EARTH_R = 6_371_000.0
DEMO_DAY = pd.Timestamp(os.environ.get("CIVICSIGNAL_DAY", "2025-11-26"))
SOLVE_S = float(os.environ.get("CIVICSIGNAL_SOLVE_S", "2"))
# Tickets per crew held back from the morning plan for same-day (voice) reports.
RESERVE = int(os.environ.get("CIVICSIGNAL_RESERVE", "2"))
INSERT_S = float(os.environ.get("CIVICSIGNAL_INSERT_S", "1.5"))

SERVICE_ALIASES = {
    "sidewalk": "Bylaw - Snow and Ice on Sidewalk", "bylaw": "Bylaw - Snow and Ice on Sidewalk",
    "road": "Roads - Snow and Ice Control", "roads": "Roads - Snow and Ice Control",
    "street": "Roads - Snow and Ice Control",
    "pathway": "Roads - Pathway Snow and Ice Concerns", "path": "Roads - Pathway Snow and Ice Concerns",
}


class TicketIn(BaseModel):
    service_name: str = Field(..., description="311 service name or alias: sidewalk | road | pathway")
    lat: float | None = None
    lon: float | None = None
    intersection: str | None = Field(None, description="e.g. '17 AV SW & 37 ST SW'")
    address: str | None = Field(None, description="Calgary street address, e.g. '2915 26 AV SE'")
    description: str | None = None
    hazard_notes: str | None = None
    source: str = "voice"


class DisruptionIn(BaseModel):
    crews_out: int | None = Field(None, description="Number of crews unavailable (0 restores all)")
    skill: str | None = Field(None, description="bylaw | roads; default proportional to both")
    surge: bool = Field(False, description="Load the next day's real 311 arrivals as a mid-day surge")


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.tickets = sim.load_tickets()
        raw = pd.read_csv(sim.DATA / "tickets_storm_week.csv", parse_dates=["requested_date", "closed_date"])
        self.cap = sim.calibrate_capacity(raw)
        self.crews_all = sim.make_crews(self.cap, self.tickets)
        self.crews = list(self.crews_all)
        self.day = DEMO_DAY
        t = self.tickets
        self.open = t[(t["requested_date"] <= self.day) &
                      (t["closed_date"].isna() | (t["closed_date"] >= self.day))].copy()
        self.surge_day = self.day
        self.voice_jobs: list[dict] = []
        self.ids = count(1)
        self.comm = pd.read_csv(sim.DATA / "community_features.csv", index_col=0)
        poles = pd.read_csv(sim.DATA / "poles.csv", dtype={"streetlight_id": str})
        self.poles = poles
        self.pole_tree = BallTree(np.radians(poles[["lat", "lon"]].to_numpy()), metric="haversine")
        ix = pd.read_csv(sim.DATA / "intersections.csv")
        self.ix = ix
        self.ix_tree = BallTree(np.radians(ix[["lat", "lon"]].to_numpy()), metric="haversine")
        self._parcel = None
        self.log: list[dict] = []
        self.rebuild(replan=True)

    # ---------------------------------------------------------- planning
    def rebuild(self, replan: bool, prev: dict | None = None, init: dict | None = None):
        jobs, members = sim.build_jobs(self.open, self.day)
        if self.voice_jobs:
            jobs = pd.concat([jobs, pd.DataFrame(self.voice_jobs)], ignore_index=True)
            members.update({v["job_id"]: [v["job_id"]] for v in self.voice_jobs})
        self.jobs, self.members = jobs, members
        if replan:
            t0 = time.time()
            self.plan = plan_day(jobs, self.planning_crews(), prev_assignment=prev,
                                 time_limit_s=SOLVE_S, initial_routes=init)
            self.last_solve_s = time.time() - t0

    def planning_crews(self):
        """Crews as the planner sees them: capacity minus the same-day reserve."""
        return [replace(c, capacity=max(1, c.capacity - RESERVE)) for c in self.crews]

    def high_risk_planned(self, plan: Plan) -> int:
        hr = set(self.open.loc[self.open["high_risk"], "service_request_id"])
        return sum(1 for js in plan.routes.values() for j in js
                   for s in self.members.get(j, []) if s in hr)

    # ---------------------------------------------------------- lookups
    def parcel(self):
        if self._parcel is None:
            self._parcel = I.load_parcel_index()
        return self._parcel

    @staticmethod
    def _norm_street(x: str) -> str:
        x = x.upper().replace(".", " ")
        x = re.sub(r"\bSTREET\b", "ST", x)
        x = re.sub(r"\bAVENUE\b|\bAV\b", "AVE", x)
        x = re.sub(r"\bTRAIL\b", "TR", x)
        x = re.sub(r"\bDRIVE\b", "DR", x)
        x = re.sub(r"\bROAD\b", "RD", x)
        x = re.sub(r"\bBOULEVARD\b", "BLVD", x)
        x = re.sub(r"\b(\d+)(ST|ND|RD|TH)\b", r"\1", x)
        return re.sub(r"\s+", " ", x).strip()

    def geocode_intersection(self, s: str):
        parts = [self._norm_street(p) for p in re.split(r"&|\bAND\b|\bAT\b|/", s.upper()) if p.strip()]
        if len(parts) != 2:
            return None
        names = self.ix["intersection"].str.upper()
        pat = lambda p: r"(^|& )" + re.escape(p) + r"( &|$)"
        m = names.str.contains(pat(parts[0])) & names.str.contains(pat(parts[1]))
        if not m.any():   # looser: allow a missing quadrant suffix
            m = names.str.contains(r"\b" + re.escape(parts[0]) + r"\b") & \
                names.str.contains(r"\b" + re.escape(parts[1]) + r"\b")
        if not m.any():
            return None
        r = self.ix[m].sort_values("n_crosswalks", ascending=False).iloc[0]
        return float(r["lat"]), float(r["lon"]), r["intersection"]

    def nearest_pole(self, lat, lon):
        d, i = self.pole_tree.query(np.radians([[lat, lon]]), k=1)
        return str(self.poles.iloc[i[0, 0]]["streetlight_id"]), float(d[0, 0] * EARTH_R)

    def nearest_intersection(self, lat, lon):
        d, i = self.ix_tree.query(np.radians([[lat, lon]]), k=1)
        return self.ix.iloc[i[0, 0]]["intersection"], float(d[0, 0] * EARTH_R)

    def rank_of(self, job_id):
        pr = self.jobs.set_index("job_id")["priority"]
        r = int((pr > pr[job_id]).sum()) + 1
        return r, float((pr <= pr[job_id]).mean())


def check_key(x_civicsignal_key: str | None = Header(None)):
    """Shared-secret header for webhook callers; enforced only when CIVICSIGNAL_KEY is set."""
    want = os.environ.get("CIVICSIGNAL_KEY")
    if want and x_civicsignal_key != want:
        raise HTTPException(401, "bad or missing X-CivicSignal-Key")


STATE: State | None = None
app = FastAPI(title="CivicSignal decision engine", version="0.1")


def S() -> State:
    global STATE
    if STATE is None:
        STATE = State()
    return STATE


@app.on_event("startup")
def _startup():
    S()
    threading.Thread(target=lambda: S().parcel(), daemon=True).start()   # warm address index


@app.get("/health")
def health():
    s = S()
    return {"ok": True, "day": s.day.strftime("%Y-%m-%d"), "open_tickets": int(len(s.open)),
            "jobs": int(len(s.jobs)), "crews": len(s.crews)}


@app.post("/tickets", dependencies=[Depends(check_key)])
def create_ticket(body: TicketIn):
    t_start = time.time()
    s = S()
    svc = SERVICE_ALIASES.get(body.service_name.strip().lower(), body.service_name)
    if svc not in SKILL_OF:
        raise HTTPException(422, f"unknown service_name; use one of {sorted(SERVICE_ALIASES)}")
    lat, lon, matched = body.lat, body.lon, None
    if lat is None or lon is None:
        if body.intersection:
            g = s.geocode_intersection(body.intersection)
            if g:
                lat, lon, matched = g
        if (lat is None) and body.address:
            key = I.normalize_address(body.address)
            hit = s.parcel().get(key)
            if hit:
                lat, lon, matched = hit[0], hit[1], key
    if lat is None or lon is None:
        raise HTTPException(422, "location required: lat/lon, a known intersection, or an address")
    if not (50.8 < lat < 51.25 and -114.35 < lon < -113.85):
        raise HTTPException(422, "location is outside Calgary")
    skill = SKILL_OF[svc]
    f = F.features_at(lat, lon)
    fdf = pd.DataFrame([f])
    expo = float(R.exposure(fdf).iat[0])
    hazards = R.caller_hazards(body.hazard_notes)
    reason = R.reasons(fdf)[0]
    if hazards:
        reason = "caller reports " + ", ".join(hazards) + "; " + reason
    pole_id, pole_d = s.nearest_pole(lat, lon)
    near_ix, _ = s.nearest_intersection(lat, lon)
    community = s.comm["name"].get(f["comm_code"], f["comm_code"])
    with s.lock:
        dup = find_duplicate(s.jobs, lat, lon, svc, eps_m=50)
        if dup is not None:
            k = s.jobs.index[s.jobs["job_id"] == dup][0]
            s.jobs.at[k, "report_count"] += 1
            pr = float(R.priority([s.jobs.at[k, "exposure"]], [s.jobs.at[k, "report_count"]], [0])[0])
            pr = R.with_caller_hazards(pr, hazards)
            s.jobs.at[k, "priority"] = max(pr, s.jobs.at[k, "priority"])
            for v in s.voice_jobs:
                if v["job_id"] == dup:
                    v["report_count"] = int(s.jobs.at[k, "report_count"])
                    v["priority"] = float(s.jobs.at[k, "priority"])
            rank, pct = s.rank_of(dup)
            crew = s.plan.assignment().get(dup)
            out = {"job_id": dup, "duplicate_of": dup, "risk_rank": rank, "risk_percentile": round(pct, 3),
                   "reports_at_location": int(s.jobs.at[k, "report_count"]), "crew_id": crew,
                   "inserted_after_stop": None, "delta_min": 0.0, "nearest_pole_id": pole_id,
                   "community": community, "reason": reason}
        else:
            jid = f"V{next(s.ids):03d}"
            pr = R.with_caller_hazards(float(R.priority([expo], [1], [0])[0]), hazards)
            job = {"job_id": jid, "skill": skill, "service_name": svc, "comm_code": f["comm_code"],
                   "lat": lat, "lon": lon, "n_tickets": 1, "service_min": SERVICE_MIN[skill],
                   "value": pr, "priority": pr, "exposure": expo, "n_high_risk": 0,
                   "report_count": 1, "oldest": s.day.strftime("%Y-%m-%d"), "reason": reason,
                   "source": body.source, "description": body.description}
            res = insert_job(s.plan, job, s.jobs, s.crews, time_limit_s=INSERT_S)
            s.voice_jobs.append(job)
            s.jobs = pd.concat([s.jobs, pd.DataFrame([job])], ignore_index=True)
            s.members[jid] = [jid]
            # keep other crews' routes; adopt the re-solved routes
            s.plan = res["plan"]
            rank, pct = s.rank_of(jid)
            out = {"job_id": jid, "duplicate_of": None, "risk_rank": rank, "risk_percentile": round(pct, 3),
                   "crew_id": res["crew_id"], "inserted": res["inserted"],
                   "inserted_after_stop": res["inserted_after"], "position": res["position"],
                   "delta_min": res["delta_min"], "eta_min": res.get("eta_min"),
                   "jobs_moved": res["jobs_moved"], "nearest_pole_id": pole_id,
                   "community": community, "reason": reason}
    out.update({"lat": round(lat, 6), "lon": round(lon, 6), "comm_code": f["comm_code"],
                "pole_distance_m": round(pole_d, 1), "exposure": round(expo, 3),
                "nearest_intersection": near_ix, "matched_location": matched,
                "read_back": f"{svc.split(' - ')[1]} near {near_ix.title()} in {str(community).title()}",
                "elapsed_s": round(time.time() - t_start, 2)})
    s.log.append({"t": time.time(), **{k: out[k] for k in ("job_id", "duplicate_of", "crew_id", "delta_min")}})
    return out


@app.post("/disruption", dependencies=[Depends(check_key)])
def disruption(body: DisruptionIn):
    s = S()
    with s.lock:
        old = s.plan
        hr_before = s.high_risk_planned(old)
        t0 = time.time()
        if body.surge:
            nxt = s.surge_day + pd.Timedelta(days=1)
            new_t = s.tickets[s.tickets["requested_date"] == nxt]
            if new_t.empty:
                raise HTTPException(409, "no further real arrivals in the replay window")
            s.surge_day = nxt
            old_members = dict(s.members)
            s.open = pd.concat([s.open, new_t])
            s.rebuild(replan=False)
            key = {tuple(v): k for k, v in s.members.items()}
            remap = {j: key.get(tuple(old_members[j])) for j in old.assignment()}
            prev = {remap[j]: c for j, c in old.assignment().items() if remap.get(j)}
            init = {c: [remap[j] for j in r if remap.get(j)] for c, r in old.routes.items()
                    if c in {x.id for x in s.crews}}
            old = Plan(routes=init)
            s.plan = plan_day(s.jobs, s.planning_crews(), prev_assignment=prev,
                              time_limit_s=SOLVE_S, initial_routes=init)
            extra = {"new_tickets": int(len(new_t)), "surge_date": nxt.strftime("%Y-%m-%d")}
        elif body.crews_out is not None:
            pool = [c for c in s.crews_all if body.skill in (None, c.skill)]
            n = max(0, min(int(body.crews_out), len(pool)))
            if body.skill:
                out_ids = [c.id for c in pool[:n]]
            else:   # proportional
                out_ids = []
                for sk in ("bylaw", "roads"):
                    cs = [c for c in s.crews_all if c.skill == sk]
                    out_ids += [c.id for c in cs[:int(round(n * len(cs) / len(s.crews_all)))]]
            s.crews = [c for c in s.crews_all if c.id not in out_ids]
            s.plan = plan_day(s.jobs, s.planning_crews(), prev_assignment=old.assignment(),
                              time_limit_s=SOLVE_S,
                              initial_routes={c.id: old.routes.get(c.id, []) for c in s.crews})
            extra = {"crews_out": out_ids, "crews_active": len(s.crews)}
        else:
            raise HTTPException(422, "send crews_out:int or surge:true")
        secs = time.time() - t0
        hr_after = s.high_risk_planned(s.plan)
        hr_total = int(s.open["high_risk"].sum())
    return {"jobs_moved": jobs_moved(old, s.plan), "replan_s": round(secs, 2),
            "high_risk_planned_before": hr_before, "high_risk_planned_after": hr_after,
            "high_risk_open": hr_total,
            "high_risk_coverage": round(hr_after / max(hr_total, 1), 3), **extra}


@app.get("/plan")
def get_plan():
    s = S()
    crew_by = {c.id: c for c in s.crews_all}
    jdx = s.jobs.set_index("job_id")
    a = s.plan.assignment()
    routes = []
    for cid, js in s.plan.routes.items():
        c = crew_by[cid]
        routes.append({"crew": cid, "skill": c.skill, "stops": js,
                       "path": [[c.depot_lon, c.depot_lat]] +
                               [[float(jdx.at[j, "lon"]), float(jdx.at[j, "lat"])] for j in js] +
                               [[c.depot_lon, c.depot_lat]],
                       "minutes": s.plan.crew_minutes.get(cid), "km": s.plan.crew_km.get(cid)})
    jobs = s.jobs.assign(crew=s.jobs["job_id"].map(a), eta_min=s.jobs["job_id"].map(s.plan.eta_min))
    cols = ["job_id", "skill", "service_name", "comm_code", "lat", "lon", "n_tickets", "priority",
            "exposure", "report_count", "reason", "crew", "eta_min"]
    return {"day": s.day.strftime("%Y-%m-%d"), "crews": [c.__dict__ for c in s.crews],
            "routes": routes, "km": round(s.plan.km, 1),
            "jobs": json.loads(jobs[cols].to_json(orient="records")),
            "voice_jobs": [v["job_id"] for v in s.voice_jobs]}


@app.get("/metrics")
def get_metrics():
    s = S()
    p = sim.DATA / "results.json"
    replay = {}
    if p.exists():
        r = json.loads(p.read_text())
        replay = {k: v["metrics"] for k, v in r["policies"].items()}
    planned = sum(s.jobs.set_index("job_id").loc[js, "n_tickets"].sum()
                  for js in s.plan.routes.values() if js)
    return {"replay": replay,
            "live": {"day": s.day.strftime("%Y-%m-%d"), "open_tickets": int(len(s.open)) + len(s.voice_jobs),
                     "tickets_planned_today": int(planned), "km": round(s.plan.km, 1),
                     "high_risk_planned": s.high_risk_planned(s.plan),
                     "voice_tickets": len(s.voice_jobs), "crews_active": len(s.crews)}}


@app.get("/briefing/{crew_id}", response_class=PlainTextResponse)
def briefing(crew_id: str):
    s = S()
    cid = crew_id.upper()
    if cid not in s.plan.routes:
        raise HTTPException(404, f"unknown or inactive crew {crew_id}")
    js = s.plan.routes[cid]
    c = next(c for c in s.crews_all if c.id == cid)
    jdx = s.jobs.set_index("job_id")
    if not js:
        return f"Unit {cid}: no stops assigned today. Stand by for dispatch."
    n_t = int(jdx.loc[js, "n_tickets"].sum())
    mins = s.plan.crew_minutes.get(cid, 0)
    kind = "inspections" if c.skill == "bylaw" else "treatments"
    lines = [f"Unit {cid}. {len(js)} stops, {n_t} {kind}, about {mins / 60:.1f} hours "
             f"and {s.plan.crew_km.get(cid, 0):.0f} kilometres."]
    groups = []                                   # consecutive stops in one community -> one line
    for j in js:
        r = jdx.loc[j]
        if groups and groups[-1]["comm"] == r["comm_code"]:
            groups[-1]["n"] += int(r["n_tickets"])
            groups[-1]["stops"] += 1
        else:
            groups.append({"comm": r["comm_code"], "n": int(r["n_tickets"]), "stops": 1, "job": j})
    for k, g in enumerate(groups[:3]):
        r = jdx.loc[g["job"]]
        name = str(s.comm["name"].get(g["comm"], g["comm"])).title() if isinstance(g["comm"], str) else "the area"
        ixn, _ = s.nearest_intersection(r["lat"], r["lon"])
        lead = "Start" if k == 0 else "Then"
        lines.append(f"{lead} in {name}, near {ixn.title()}: {g['n']} "
                     f"{'report' if g['n'] == 1 else 'reports'}, because {r['reason']}.")
    if len(groups) > 3:
        rest = sum(g["stops"] for g in groups[3:])
        lines.append(f"Then {rest} more stop{'s' if rest > 1 else ''} on your tablet.")
    voice = [j for j in js if j.startswith("V")]
    if voice:
        lines.append(f"Includes {len(voice)} new resident report{'s' if len(voice) > 1 else ''} from the voice line.")
    return " ".join(lines)
