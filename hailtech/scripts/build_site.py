"""Build the HailTech product page (site/index.html) from the computed outputs.

Everything the page shows comes from files the pipeline wrote: the 5 Aug 2024 nowcast replay,
the ECCC warning timeline, the morning score card, the backtest and the asset list. Re-run after
any retrain:  .venv/bin/python scripts/build_site.py [--source era5]
"""
import argparse
import base64
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import data  # noqa: E402  (app/data.py loaders; streamlit caching degrades to memory outside a server)
import page_story as ps  # noqa: E402  (single source for the alert wording and per-site logic)

EVENT = "2024-08-05"
# Map window: Cochrane (storm origin) to east Calgary, Airdrie to south Calgary.
LAT0, LAT1, LON0, LON1 = 50.84, 51.30, -114.55, -113.80
OUT = ROOT / "site" / "index.html"
TEMPLATE = ROOT / "site" / "template.html"

# Hail colours by size (mm), shared by the map and the legend.
RAMP = [(5, (186, 196, 210, 110)), (20, (242, 201, 76, 200)), (30, (240, 138, 36, 220)),
        (40, (217, 52, 43, 230)), (50, (176, 36, 122, 240))]
STATUS = {"ALL_CLEAR": 0, "ARM": 1, "TRIGGER": 2, "BLOCKED_UNSAFE": 3, "HIT": 4, "WATCH": 5}


def png(rgba: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def colour(mm: np.ndarray) -> np.ndarray:
    out = np.zeros(mm.shape + (4,), np.uint8)
    for lo, rgba in RAMP:
        out[mm >= lo] = rgba
    return out


def trail(mm: np.ndarray) -> np.ndarray:
    out = np.zeros(mm.shape + (4,), np.uint8)
    out[mm >= 20] = (120, 96, 80, 70)
    out[mm >= 30] = (120, 80, 70, 110)
    return out


def frames(rp, fields):
    obs = fields["obs_mesh"].astype(float)
    lats, lons = ps.grid_axes(rp, fields, obs.shape[1], obs.shape[2])
    ys = np.where((lats >= LAT0) & (lats <= LAT1))[0]
    xs = np.where((lons >= LON0) & (lons <= LON1))[0]
    crop = obs[:, ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    if lats[0] < lats[-1]:  # images draw north-up
        crop = crop[:, ::-1, :]
    cum = np.maximum.accumulate(np.where(crop < 0, 0, crop), axis=0)
    cur = [png(colour(f)) if (f >= 5).any() else None for f in crop]
    tr = [png(trail(c)) if (c >= 20).any() else None for c in cum]
    box = [float(lons[xs.min()]), float(lats[ys].min()), float(lons[xs.max()]), float(lats[ys].max())]
    return cur, tr, box


def basemap():
    bd = json.loads((ROOT / "data/basemap/city_boundary.geojson").read_text())
    rings = []
    for f in bd["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            ring = poly[0][::4]
            rings.append([[round(x, 4), round(y, 4)] for x, y in ring])
    roads = {}
    for seg in json.loads((ROOT / "data/basemap/roads.json").read_text()):
        coords = (seg.get("the_geom") or {}).get("coordinates") or []
        if seg.get("name") and coords:
            roads.setdefault(seg["name"].title(), []).append([[round(x, 4), round(y, 4)] for x, y in coords])
    return {"city": rings, "roads": roads}


def sites(rp, issues, fields):
    thr = ps.truth_mm(rp)
    per = ((rp.get("evaluation") or {}).get("nowcast") or {}).get("per_asset") or {}
    out = []
    for a in ps._assets(rp):
        p = per.get(a.get("asset_id")) or {}
        task = a.get("task") or {}
        first = task.get("first_alert") or p.get("first_arm")
        warned, hit = bool(first), ps.hit_time(a, thr) is not None
        group = "hit" if hit and warned else "missed" if hit else "false" if warned else "clear"
        status = [STATUS.get(ps.site_status(a, t, thr), 0) for t in issues]
        mx = float((a.get("observed") or {}).get("max_mesh_mm") or 0)
        row = {"id": a["asset_id"], "name": ps.short(a.get("name")),
               "type": ps.CATEGORY.get(a.get("category"), str(a.get("category"))),
               "lat": a["lat"], "lon": a["lon"], "group": group, "status": status,
               "hail_mm": round(mx), "hail_words": ps.size_words(mx) if mx >= 5 else "little or no hail",
               "warned_at": ps.clock(first) if warned else None}
        if group == "hit":
            job = task.get("task_duration_min")
            lead = task.get("alert_lead_min", p.get("lead_min"))
            blocked = task.get("first_blocked_issue")
            safe = task.get("safe_minutes")
            if safe is None:
                safe = ps._mins_between(first, blocked) if blocked else lead
            row.update(lead=lead, job=job, safe=safe, inside_at=ps.clock(blocked) if blocked else None,
                       safe_arm_only=task.get("safe_minutes_arm_only"),
                       finish=task.get("task_fits") or (("yes" if safe >= job else "partly" if safe >= job / 2 else "no")
                                                        if job and safe is not None else None))
        if group == "false":
            near = ps._nearest_hail_km(a, rp, fields)
            row["near_km"] = round(near) if near is not None else None
        out.append(row)
    return out


def feed(rp, issues):
    items = ps.build_feed(rp, ps.eccc_warnings(EVENT), data.scores(EVENT))
    times = [data.to_mdt(t) for t in issues]
    out = []
    for it in items:
        idx = next((i for i, t in enumerate(times) if t >= it.t), len(times) - 1) if it.t >= times[0] else -1
        out.append({"t": ps.clock(it.t), "i": idx, "text": it.text, "official": it.official,
                    "who": it.who, "kind": "morning" if it.order == -1 else "official" if it.official else "site"})
    return out


def proof(source: str):
    path = ROOT / f"data/processed/backtest_{source}.json"
    if not path.exists():
        return None
    bt = json.loads(path.read_text())

    def pr(k):
        r = bt[k]
        flagged = r["hits"] + r["false_alarms"]
        return {"caught": r["pod"], "precision": r["hits"] / flagged if flagged else 0.0, "hits": r["hits"],
                "flagged": flagged}
    meta = bt["_meta"]
    return {"source": source, "years": f"{meta['years'][0]}–{meta['years'][-1]}", "summers": len(meta["years"]),
            "days": meta["n_days"], "hail_days": meta["n_severe"], "base_rate": bt["climatology"]["base_rate"],
            "hailtech": pr("hailday"), "rule": pr("single_index"), "calendar": pr("climatology")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None, help="era5 or openmeteo (default: era5 if built)")
    args = ap.parse_args()
    source = args.source or ("era5" if (ROOT / "data/processed/backtest_era5.json").exists() else "openmeteo")

    rp, fields = data.replay(EVENT)
    issues = rp["issue_times"]
    cur, tr, box = frames(rp, fields)
    ev = rp.get("evaluation") or {}
    nc = ev.get("nowcast_watch") or ev.get("nowcast") or {}
    sc = data.scores(EVENT) or {}
    payload = {
        "event": EVENT, "times": [ps.clock(t) for t in issues], "box": box,
        "view": [LON0, LAT0, LON1, LAT1], "frames": cur, "trail": tr, "ramp": RAMP,
        "basemap": basemap(), "sites": sites(rp, issues, fields), "feed": feed(rp, issues),
        "numbers": {"caught": nc.get("hits_caught"), "hit_total": nc.get("hits_total"),
                    "lead": nc.get("median_lead_min"), "false": nc.get("false_alarms")},
        "morning": {"p": sc.get("p_day"), "odds": ps.odds(sc.get("p_day")), "source": sc.get("source")},
        "proof": proof(source),
    }
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", json.dumps(payload, separators=(",", ":")))
    OUT.write_text(html)
    kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT.relative_to(ROOT)} ({kb:.0f} KB), {len(issues)} frames, {len(payload['sites'])} sites, "
          f"{len(payload['feed'])} feed items, proof from {source}")


if __name__ == "__main__":
    main()
