"""Independent check of the 5 Aug 2024 nowcast against Northern Hail Project damage contours.

    python scripts/validate_nhp.py            # downloads the layer once to data/raw/nhp/
    python scripts/validate_nhp.py --refresh  # re-download

The NHP contours are ground damage surveys (Threshold < Minor < Moderate < Severe), independent of the
radar (MRMS MESH) truth used by the replay. Used for validation only, never for training or tuning.
Source: Northern Hail Project (Western University), NHP_August2024_DamageContours, licensed CC BY-NC 4.0.

Writes data/processed/nowcast/nhp_validation_2024-08-05.json.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import requests
from shapely.geometry import Point, shape
from shapely.ops import transform

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SERVICE = ("https://services.arcgis.com/rGKxabTU9mcXMw7k/ArcGIS/rest/services/"
           "NHP_August2024_DamageContours/FeatureServer")
QUERY = SERVICE + "/0/query?where=1%3D1&outFields=*&f=geojson&outSR=4326"
CACHE = ROOT / "data/raw/nhp/NHP_August2024_DamageContours.geojson"
REPLAY = ROOT / "data/processed/nowcast/replay_2024-08-05.json"
OUT = ROOT / "data/processed/nowcast/nhp_validation_2024-08-05.json"
GRADES = ["Threshold", "Minor", "Moderate", "Severe"]          # increasing damage
LICENCE = "CC BY-NC 4.0"
CITATION = ("Northern Hail Project (Western University), 'NHP_August2024_DamageContours' ground damage survey "
            "of the 5 Aug 2024 Calgary hailstorm, NHP Open Data (nhp-open-data-site-westernu.hub.arcgis.com), "
            "licensed CC BY-NC 4.0. Used for independent validation only.")


def fetch(refresh=False) -> dict:
    if refresh or not CACHE.exists():
        r = requests.get(QUERY, timeout=60)
        r.raise_for_status()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(r.text)
    return json.loads(CACHE.read_text())


def local_km(lat0, lon0):
    """Equirectangular projection to km around (lat0, lon0) - accurate to <0.1 % over a city."""
    kx = 111.32 * np.cos(np.radians(lat0))
    return lambda x, y, z=None: ((np.asarray(x) - lon0) * kx, (np.asarray(y) - lat0) * 110.57)


def grade_sites(gj: dict, sites):
    """sites: [(asset_id, lat, lon)] -> {asset_id: (grade or None, dist_km to nearest contour of any grade,
    {grade: dist_km})}. Grade = most severe contour containing the point (contours nest)."""
    feats = [(f["properties"].get("DamageType"), shape(f["geometry"])) for f in gj.get("features", [])
             if f.get("geometry")]
    lat0 = np.mean([s[1] for s in sites]); lon0 = np.mean([s[2] for s in sites])
    proj = local_km(lat0, lon0)
    polys = [(g, transform(proj, geom)) for g, geom in feats]
    out = {}
    for aid, la, lo in sites:
        p = transform(proj, Point(lo, la))
        inside = [g for g, poly in polys if poly.covers(p)]
        grade = max(inside, key=GRADES.index) if inside else None
        by = {}
        for g, poly in polys:
            d = poly.distance(p)
            by[g] = min(by.get(g, np.inf), d)
        out[aid] = (grade, round(float(min(by.values())), 2) if by else None,
                    {g: round(float(by[g]), 2) for g in GRADES if g in by})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    gj = fetch(args.refresh)
    rp = json.loads(REPLAY.read_text())
    per = rp["evaluation"]["nowcast"]["per_asset"]
    truth = rp["thresholds"].get("truth_mm", 30.0)
    sites = [(a["asset_id"], a["lat"], a["lon"]) for a in rp["assets"]]
    graded = grade_sites(gj, sites)

    rows = []
    for a in rp["assets"]:
        aid = a["asset_id"]
        g, d, by = graded[aid]
        mx = (a.get("observed") or {}).get("max_mesh_mm")
        rows.append({"asset_id": aid, "name": a["name"], "category": a["category"], "nhp_grade": g or "none",
                     "dist_km": d, "dist_km_by_grade": by, "warned": per[aid]["first_arm"] is not None,
                     "first_arm": per[aid]["first_arm"], "lead_min": per[aid]["lead_min"],
                     "max_mesh_mm": mx, "mesh_hit": mx is not None and mx >= truth})

    def xtab(key):
        t = {}
        for r in rows:
            k = ("warned" if r[key] else "not_warned") if key == "warned" else ("mesh_hit" if r[key] else "no_mesh_hit")
            t.setdefault(r["nhp_grade"], {}).setdefault(k, 0)
            t[r["nhp_grade"]][k] += 1
        return {g: t[g] for g in GRADES[::-1] + ["none"] if g in t}

    damaged = lambda r: r["nhp_grade"] != "none"
    fa = [r for r in rows if r["warned"] and not r["mesh_hit"]]
    summary = {
        "n_assets": len(rows), "n_polygons": len(gj.get("features", [])),
        "grade_counts": {g: sum(r["nhp_grade"] == g for r in rows) for g in GRADES[::-1] + ["none"]},
        "xtab_grade_vs_warned": xtab("warned"),
        "xtab_grade_vs_mesh_hit": xtab("mesh_hit"),
        # treating "inside any NHP damage contour" as an independent truth
        "nhp_truth": {
            "damaged_sites": sum(map(damaged, rows)),
            "warned_and_damaged": sum(r["warned"] and damaged(r) for r in rows),
            "warned_not_damaged": sum(r["warned"] and not damaged(r) for r in rows),
            "damaged_not_warned": sum(damaged(r) and not r["warned"] for r in rows),
            "mesh_hit_and_damaged": sum(r["mesh_hit"] and damaged(r) for r in rows),
            "mesh_hit_not_damaged": sum(r["mesh_hit"] and not damaged(r) for r in rows),
            "damaged_not_mesh_hit": sum(damaged(r) and not r["mesh_hit"] for r in rows),
        },
        "mesh_false_alarms": [{"asset_id": r["asset_id"], "name": r["name"], "nhp_grade": r["nhp_grade"],
                               "dist_km": r["dist_km"]} for r in fa],
        "mesh_false_alarms_inside_contours": sum(damaged(r) for r in fa),
    }
    n_in = summary["mesh_false_alarms_inside_contours"]
    summary["verdict"] = (
        f"{n_in} of {len(fa)} MESH-truth false alarms lie inside an NHP damage contour"
        + (" - MESH-at-pixel truth undercounted damage there." if n_in else
           " - the NHP survey does not rescue them; they remain false alarms against ground damage too.")
        + " Caveat: 'none' near 114.04-113.97 W (airport/industrial gap between the NW and NE survey swaths) "
          "likely means not surveyed. Nearest-contour distances: " + ", ".join(f"{r['asset_id']} {r['dist_km']} km" for r in fa) + ".")
    res = {"event": "2024-08-05", "source": {"name": "Northern Hail Project - NHP_August2024_DamageContours",
                                             "url": SERVICE, "query": QUERY, "citation": CITATION},
           "licence": LICENCE, "cache": str(CACHE.relative_to(ROOT)),
           "notes": ["Grade = most severe NHP damage contour containing the site point (contours nest).",
                     "dist_km = distance from the site to the nearest contour of any grade (0 = inside).",
                     "warned = nowcast ARM/TRIGGER at any issue (first_arm not null); mesh_hit = observed "
                     f"MRMS MESH >= {truth:.0f} mm at the site pixel in the window.",
                     "NHP contours are a post-event ground survey and coarser than site scale; validation only.",
                     "Coverage caveat: the contours are residential siding/window surveys. The NW swath ends at "
                     "~114.036 W and the NE swath starts at ~113.97 W with straight edges; the airport / Deerfoot "
                     "industrial corridor between them (where the 7 MESH-hit sites sit) appears unsurveyed, so "
                     "'none' there means 'not surveyed', not 'no damage'."],
           "assets": rows, "summary": summary}
    OUT.write_text(json.dumps(res, indent=1))

    print(f"NHP damage contours: {len(gj.get('features', []))} polygons ({LICENCE}; validation only)\n")
    print(f"{'id':5s} {'site':32s} {'NHP grade':10s} {'dist km':>7s} {'warned':>6s} {'first ARM':>9s} "
          f"{'MESH max':>8s} {'hit':>4s}")
    for r in rows:
        print(f"{r['asset_id']:5s} {r['name'][:32]:32s} {r['nhp_grade']:10s} {r['dist_km']:7.2f} "
              f"{'Y' if r['warned'] else '-':>6s} {(r['first_arm'] or '-')[11:16]:>9s} "
              f"{r['max_mesh_mm'] or 0:8.0f} {'Y' if r['mesh_hit'] else '-':>4s}")
    print("\ngrade vs warned :", json.dumps(summary["xtab_grade_vs_warned"]))
    print("grade vs MESH>=30:", json.dumps(summary["xtab_grade_vs_mesh_hit"]))
    print("NHP-as-truth    :", json.dumps(summary["nhp_truth"]))
    print("\n" + summary["verdict"])
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
