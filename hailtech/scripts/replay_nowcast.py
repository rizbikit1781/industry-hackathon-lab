"""Replay the 0-90 min hail nowcast (0-45 min ARM/TRIGGER + 45-90 min WATCH tier) for one event and write the dashboard contract files.

    python scripts/replay_nowcast.py                      # 5 Aug 2024 (22:00-04:00 UTC)
    python scripts/replay_nowcast.py --event 2025-08-04 --start "2025-08-04 18:00" --end "2025-08-05 03:00"

Writes /Users/caelan/code/hackathon/hailday/data/processed/nowcast/replay_<event>.json and
replay_<event>_fields.npz (override the directory with --out).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hailday.config import ASSETS_CSV  # noqa: E402
from nowcast.decide import Thresholds  # noqa: E402
from nowcast.mrms import LATENCY, NOWCAST_BOX, load_window  # noqa: E402
from nowcast.replay import run_replay  # noqa: E402

OUT = Path("/Users/caelan/code/hackathon/hailday/data/processed/nowcast")
SPINUP = pd.Timedelta(minutes=30)     # frames before the window warm up the tracker
VERIFY = pd.Timedelta(minutes=50)     # frames after the window score the last +45 min forecasts

NOTES = [
    "Rules + advection, no ML: hail cells = POSH>=30% or MESH>=10 mm components (>=5 px); each cell's "
    "current MESH footprint is translated along its motion with constant intensity (no growth/decay, "
    "no new-cell initiation).",
    "Motion: least-squares centroid velocity over the last <=8 distinct frames (MRMS re-stamped repeats are skipped) (>=3 needed); younger cells use local "
    "cross-correlation of composite reflectivity over 10 min.",
    "Uncertainty: 25-member ensemble (5 speed x 5 direction). Up to 45 min the spread is speed +/-20 % and "
    "direction +/-15 deg; beyond 45 min it grows linearly to +/-30 % and +/-25 deg at 90 min. ARM/TRIGGER and "
    "fcst_p30 at leads <= 45 min use only the 9 core members (speed x{0.8,1.0,1.2}, direction {-15,0,+15} deg; "
    "multiples of 1/9), so they are identical to the earlier 45-min nowcast; fcst_p30 at 60-90 min uses all 25.",
    "Asset probability p_s = fraction of (core) members whose forecast MESH >= s mm touches the asset's 1 km "
    "buffer at any 5-min lead in 0-45 min. Arrival times are ISO UTC (issue + lead) where the member fraction > 0.1; "
    "null when no member arrives.",
    "Truth = MRMS instantaneous MESH >= 30 mm at the asset's nearest 0.01 deg pixel at any 2-min frame in the "
    "window. MESH runs high against ground reports; 30 mm MESH is a proxy for damaging ground hail.",
    "No future data: at each issue only frames with available_time = valid_time + 2 min <= issue time are used "
    "(MRMS files land on S3 ~50 s after valid time). Verification uses the full record.",
    "A warning 'catches' a hit only if an ARM/TRIGGER episode is active at the last issue at or before onset; "
    "lead = onset - episode start. False alarm = asset warned but never observed >= 30 mm in the window.",
    "UPDATE is not emitted as a state: an ARM/TRIGGER entry with changed p30/arrival is the update. "
    "MONITOR here means 'no nowcast action' (the day-ahead layer owns MONITOR/PREPARE).",
    "EV rule uses value_at_risk / protect_cost from data/assets.csv (assumptions, not site data); with "
    "C/L ~ 1/2000 it fires at almost any P, so it is gated at P >= ev_min_p (2 of 9 members).",
    "WATCH ('Storm approaching'): p30_watch = fraction of all 25 members hitting the 1 km buffer at any lead in "
    "45-90 min; WATCH when p30_watch >= 0.2 and ARM/TRIGGER do not fire; back to MONITOR after 3 consecutive "
    "issues with p30_watch < 0.1. ARM/TRIGGER take precedence and never step down to WATCH. watch_arrival_earliest "
    "is the earliest arrival over 0-90 min (all members). Evaluation 'nowcast_watch' counts WATCH/ARM/TRIGGER "
    "episodes as warnings; 'nowcast' (ARM/TRIGGER only) is unchanged. Constant-intensity extrapolation is less "
    "reliable at 60-90 min: storms turn, split, grow or die.",
    "obs_mesh in the npz is the newest frame available at each issue (-1 = missing); fcst_p30 is percent.",
    "Protective task: latest_feasible_start = earliest forecast arrival - task_duration_min - 5 min margin "
    "(task durations are category ASSUMPTIONS in data/assets.csv); in WATCH the 0-90 min earliest arrival is "
    "used (task_arrival_source). task_window_status: NOT_NEEDED (no WATCH/ARM/TRIGGER or no arrival window), FEASIBLE, TIGHT (<10 min slack), MISSED (latest start passed), "
    "BLOCKED_UNSAFE (arrival <= 15 min away or observed MESH > 0 within 10 km = lightning proxy, per ECCC "
    "lightning guidance: shelter, do not go outside).",
    "Safe working window (task.safe_minutes): first alert (first WATCH or ARM in the episode covering onset) -> "
    "first BLOCKED_UNSAFE at/after it (else -> onset). task_fits: yes if >= task duration, partly if > 0, else no. "
    "safe_minutes_arm_only / task_fits_arm_only are the same measure starting at the first ARM. "
    "observed.nearest_ge30_km = distance from the site to the nearest MESH >= 30 mm pixel in the window.",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="2024-08-05")
    ap.add_argument("--start", default="2024-08-05 22:00")
    ap.add_argument("--end", default="2024-08-06 04:00")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    t_start = time.time()
    th = Thresholds()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    print(f"loading MRMS {start - SPINUP} .. {end + VERIFY} box {NOWCAST_BOX}", flush=True)
    frames = load_window(start - SPINUP, end + VERIFY)
    print(f"  {len(frames.valid_times)} frames, grid {len(frames.lats)}x{len(frames.lons)} "
          f"({time.time() - t_start:.0f}s)", flush=True)
    assets = pd.read_csv(ASSETS_CSV)
    issues = pd.date_range(start, end, freq=f"{th.issue_every_min}min")
    result, arrays, diag = run_replay(frames, assets, issues, th, event=args.event, window=(start, end))
    for i, k in enumerate(diag["used_frame"]):   # belt and braces: no frame from the future
        assert k is None or frames.available_times[k] <= issues[i]
    result["notes"] = NOTES + [f"Latency assumption {LATENCY}; {len(frames.valid_times)} MRMS frames; "
                               f"runtime {time.time() - t_start:.0f}s."]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"replay_{args.event}.json").write_text(json.dumps(result, indent=1))
    np.savez_compressed(out / f"replay_{args.event}_fields.npz", **arrays)

    print(f"\n{args.event}: {len(issues)} issues, {len(result['storms'])} storm-issue rows")
    print(f"{'policy':12s} {'hits':>7s} {'med lead':>9s} {'false':>6s} {'false trig':>10s}  grid CSI/FSS@30min")
    for pol, ev in result["evaluation"].items():
        g = ev.get("grid_30min", {})
        print(f"{pol:12s} {ev['hits_caught']:>3d}/{ev['hits_total']:<3d} {str(ev['median_lead_min']):>9s} "
              f"{ev['false_alarms']:>6d} {ev['false_triggers']:>10d}  {g.get('csi')}/{g.get('fss_9px_mean')}  "
              f"p>=10%: {ev.get('grid_30min_p10', {}).get('csi')}/{ev.get('grid_30min_p10', {}).get('fss_9px_mean')}")
    print("\nper asset (nowcast | persistence | mesh_only lead min; observed max / first >=30):")
    for a in result["assets"]:
        aid = a["asset_id"]
        leads = [result["evaluation"][p]["per_asset"][aid]["lead_min"] for p in ("nowcast", "persistence", "mesh_only")]
        print(f"  {aid} {a['name'][:34]:34s} {str(leads):24s} max {a['observed']['max_mesh_mm']:5.0f} "
              f"first {a['observed']['first_ge30_time']}  arm {result['evaluation']['nowcast']['per_asset'][aid]['first_arm']}")
    print("\nprotective task (latest start = earliest arrival - task - margin; warned or hit sites):")
    print(f"  {'id':5s} {'site':30s} {'task':>4s} {'first ARM':>9s} {'lead':>5s} {'fc lead':>7s} {'slack':>6s} "
          f"{'status at ARM':15s} {'feasible':8s} first BLOCKED")
    for a in result["assets"]:
        tk = a.get("task") or {}
        if not tk.get("first_arm") and not a["observed"]["first_ge30_time"]:
            continue
        f = lambda v: "-" if v is None else f"{v:.0f}"
        print(f"  {a['asset_id']:5s} {a['name'][:30]:30s} {f(tk.get('task_duration_min')):>4s} "
              f"{(tk.get('first_arm') or '-')[11:16]:>9s} {f(tk.get('observed_lead_min')):>5s} "
              f"{f(tk.get('forecast_lead_at_first_arm_min')):>7s} {f(tk.get('slack_at_first_arm_min')):>6s} "
              f"{str(tk.get('status_at_first_arm')):15s} {'yes' if tk.get('feasible') else 'no':8s} "
              f"{(tk.get('first_blocked_issue') or '-')[11:16]}")
    print("\nWATCH tier (times UTC; MDT = UTC-6). Sites with hail or any alert:")
    print(f"  {'id':5s} {'site':30s} {'1st WATCH':>9s} {'1st ARM':>8s} {'onset':>6s} {'W lead':>6s} {'safe':>5s} "
          f"{'safeARM':>7s} {'task':>4s} {'fits':6s} {'fitsARM':7s} {'max':>4s} {'near30km':>8s}")
    for a in result["assets"]:
        tk, ob = a.get("task") or {}, a["observed"]
        pa = result["evaluation"]["nowcast_watch"]["per_asset"][a["asset_id"]]
        if not (pa.get("first_arm") or ob["first_ge30_time"]):
            continue
        hm = lambda v: (v or "-")[11:16] or "-"
        f = lambda v: "-" if v is None else f"{v:.0f}"
        print(f"  {a['asset_id']:5s} {a['name'][:30]:30s} {hm(pa.get('first_watch')):>9s} "
              f"{hm(result['evaluation']['nowcast']['per_asset'][a['asset_id']]['first_arm']):>8s} "
              f"{hm(ob['first_ge30_time']):>6s} {f(tk.get('watch_lead_min')):>6s} {f(tk.get('safe_minutes')):>5s} "
              f"{f(tk.get('safe_minutes_arm_only')):>7s} {f(tk.get('task_duration_min')):>4s} "
              f"{str(tk.get('task_fits')):6s} {str(tk.get('task_fits_arm_only')):7s} {ob['max_mesh_mm']:4.0f} "
              f"{f(ob.get('nearest_ge30_km')):>8s}")
    print(f"\nwrote {out}/replay_{args.event}.json  runtime {time.time() - t_start:.0f}s")


if __name__ == "__main__":
    main()
