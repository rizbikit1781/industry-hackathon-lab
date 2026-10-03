"""One-shot ingest from Open Calgary. Writes data/tickets_*.csv and data/layers/*.

Run:  .venv/bin/python scripts/pull_data.py [--skip-existing]
"""
import json
import shutil
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from civicsignal import ingest as I  # noqa: E402

SKIP = "--skip-existing" in sys.argv
I.DATA.mkdir(exist_ok=True)
I.LAYERS.mkdir(parents=True, exist_ok=True)
I.RAW.mkdir(parents=True, exist_ok=True)
report = {}


def step(name, path, fn):
    path = Path(path)
    if SKIP and path.exists() and path.stat().st_size > 0:
        print(f"[skip] {name}")
        report[name] = {"status": "existing", "path": str(path.relative_to(I.ROOT))}
        return
    try:
        info = fn(path) or {}
        report[name] = {"status": "ok", "path": str(path.relative_to(I.ROOT)), **info}
        print(f"[ok]   {name}: {info}")
    except Exception as e:  # record gaps, don't stop the pull
        traceback.print_exc()
        report[name] = {"status": "FAILED", "error": repr(e)}
        print(f"[FAIL] {name}: {e}")


def w_csv(df, path):
    df.to_csv(path, index=False)
    return {"rows": int(len(df))}


def w_json(obj, path):
    path.write_text(json.dumps(obj))
    return {"features": len(obj.get("features", []))}


step("tickets_storm_week", I.DATA / "tickets_storm_week.csv",
     lambda p: w_csv(I.pull_tickets(I.WARM_START, I.STORM_END), p))
step("tickets_validation", I.DATA / "tickets_winter_sidewalk.csv",
     lambda p: w_csv(I.pull_tickets(I.VALID_START, I.VALID_END, [I.SNOW_SERVICES[0]]), p))
step("poles", I.DATA / "poles.csv", lambda p: w_csv(I.pull_poles(), p))
step("census", I.LAYERS / "census_2019.csv", lambda p: w_csv(I.pull_census(), p))


def _equity(p):
    df, gj = I.pull_equity()
    (I.LAYERS / "equity_csa.geojson").write_text(json.dumps(gj))
    return {**w_csv(df, p), "csa_polygons": len(gj["features"])}


step("equity", I.LAYERS / "equity.csv", _equity)
step("schools", I.LAYERS / "schools.csv", lambda p: w_csv(I.pull_points("schools"), p))
step("community_services", I.LAYERS / "community_services.csv",
     lambda p: w_csv(I.pull_points("community_services"), p))
step("transit_stops", I.LAYERS / "transit_stops.csv",
     lambda p: w_csv(I.pull_points("transit_stops", {"$where": "status='ACTIVE'"}), p))
step("crosswalks", I.LAYERS / "crosswalks.csv", lambda p: w_csv(I.pull_points("crosswalks"), p))
step("ped_locations", I.LAYERS / "ped_locations.csv", lambda p: w_csv(I.pull_points("ped_locations"), p))
step("ped_counts", I.LAYERS / "ped_counts.csv", lambda p: w_csv(I.pull_ped_counts(), p))
step("traffic", I.LAYERS / "traffic_2024.geojson", lambda p: w_json(I.pull_traffic(), p))
step("boundaries", I.LAYERS / "communities.geojson", lambda p: w_json(I.pull_boundaries(), p))


def _childcare(p):
    df, stats = I.pull_childcare()
    return {**w_csv(df, p), **stats}


step("childcare", I.LAYERS / "childcare.csv", _childcare)


def _intersections(p):
    cw = pd.read_csv(I.LAYERS / "crosswalks.csv")
    return w_csv(I.build_intersections(cw), p)


step("intersections", I.DATA / "intersections.csv", _intersections)

# Seniors' residences: no open layer. Copy the researched hand-list if present.
src = I.ROOT.parent / "research" / "seniors_residences.csv"
dst = I.DATA / "seniors_residences.csv"
if src.exists() and not dst.exists():
    shutil.copy(src, dst)
report["seniors_residences"] = {"status": "hand-listed" if dst.exists() else "MISSING (feature weight -> 0)"}

(I.DATA / "ingest_report.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
