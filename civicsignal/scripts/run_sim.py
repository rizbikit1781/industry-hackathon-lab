"""Replay the storm week under FIFO, CivicSignal (optimized) and CivicSignal + disruption.

Run:  .venv/bin/python scripts/run_sim.py [--time-limit 2] [--no-sweep]
Writes data/results.json (read by the dashboard) and prints the metrics table.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from civicsignal import dedupe, features, roads, sim  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--time-limit", type=float, default=2.0, help="OR-Tools seconds per skill per solve")
ap.add_argument("--no-sweep", action="store_true")
ap.add_argument("--quiet", action="store_true")
args = ap.parse_args()

T0 = time.time()
print(f"Routing: {roads.method()} (winter speed factor {roads.WINTER_SPEED_FACTOR})")
tickets = sim.load_tickets()
cap = sim.calibrate_capacity()
crews = sim.make_crews(cap, tickets)
print("Capacity calibration (median real daily closures, storm week):")
for s, c in cap.items():
    print(f"  {s}: median {c['median_daily_closures']:.0f}/day -> {c['crews']} crews x "
          f"{c['tickets_per_crew']} = {c['daily_capacity']}/day   (real daily: {c['daily_closures']})")

DISRUPTION = [{"day": 2, "crews_out": 0.3}, {"day": 6, "surge": True}]
results = {}
for name, pol, dis in [("fifo", "fifo", None), ("optimized", "optimized", None),
                       ("optimized_disruption", "optimized", DISRUPTION)]:
    print(f"\n== {name}")
    t0 = time.time()
    results[name] = sim.run(pol, tickets, crews, disruption=dis, time_limit_s=args.time_limit,
                            verbose=not args.quiet)
    print(f"  ({time.time() - t0:.1f}s)")

rows = {k: v["metrics"] for k, v in results.items()}
table = pd.DataFrame(rows)
pd.set_option("display.width", 160)
print("\n=== Metrics (storm-week tickets requested Nov 25 - Dec 1, 2025) ===")
print(table.to_string())
for r in results["optimized_disruption"]["replans"]:
    print("replan:", r)

extra = {"generated_s": round(time.time() - T0, 1)}
print("\nDedupe validation vs City 'Duplicate (Closed)' labels (sidewalk, Nov 2025 - Mar 2026):")
v = pd.read_csv(sim.DATA / "tickets_winter_sidewalk.csv", parse_dates=["requested_date", "closed_date"])
extra["dedupe_validation"] = dedupe.validate(v, 50, 2)
print(json.dumps(extra["dedupe_validation"], indent=1))
pv = features.ped_proxy_validation()
extra["ped_proxy_validation"] = pv
print(f"\nPedestrian proxy vs real count sites: Spearman {pv['spearman']:.3f} "
      f"(n={pv['n_sites']}, p={pv['p_value']:.2f})")
if not args.no_sweep:
    sw = sim.sweep(tickets, crews, day_index=0, time_limit_s=args.time_limit)
    extra["sweep"] = sw
    print("\nLambda sweep (day 1):")
    print(pd.DataFrame(sw["lambda_curve"]).to_string(index=False))
    print(pd.DataFrame(sw["presets"]).to_string(index=False))
    print("\nPriority-weight sweep (full week, optimized, 1 s/solve):")
    extra["priority_sweep"] = sim.priority_sweep(tickets, crews)
    print(pd.DataFrame(extra["priority_sweep"]).to_string(index=False))

sim.export(results, crews, cap, extra)
roads.save_cache()          # keep matrix rows for job points first seen in this run
print(f"\nwrote data/results.json  total {time.time() - T0:.1f}s")
