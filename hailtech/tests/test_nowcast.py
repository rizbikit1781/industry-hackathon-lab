import numpy as np
import pandas as pd

from nowcast.advect import advect
from nowcast.decide import (ALL_CLEAR, ARM, CANCEL, DEGRADED, MONITOR, TRIGGER, WATCH, AssetMachine, Thresholds,
                            ev_fires)
from nowcast.mrms import Frames
from nowcast.replay import run_replay
from nowcast.tracking import Tracker, segment, shift2d

LATS = np.round(51.3 - 0.01 * np.arange(60), 4)     # descending, like MRMS
LONS = np.round(-114.4 + 0.01 * np.arange(80), 4)


def blob(cy, cx, r=4, peak=45.0, shape=(60, 80)):
    yy, xx = np.mgrid[: shape[0], : shape[1]]
    d = np.hypot(yy - cy, xx - cx)
    return np.where(d <= r, peak * (1 - 0.5 * d / r), 0.0).astype(np.float32)


def test_segment_synthetic_blob():
    mesh = blob(20, 30) + blob(45, 65, r=0.5, peak=40)   # one-pixel speck below min area
    cells = segment(mesh, min_area_px=5)
    assert len(cells) == 1
    c = cells[0]
    assert abs(c.cy - 20) < 0.5 and abs(c.cx - 30) < 0.5
    assert c.max_mesh == mesh.max() and c.area_px > 40


def test_motion_recovered_from_translated_blob():
    tr = Tracker(LATS, LONS)
    vy, vx = 0.5, 1.0                                    # px / min (south-east)
    for k in range(8):
        t = 2.0 * k
        tr.update(t, blob(15 + vy * t, 15 + vx * t))
    active = [t for t in tr.tracks if t.active]
    assert len(active) == 1 and active[0].storm_id == "S001"   # one lineage, never re-born
    assert abs(active[0].vy - vy) < 0.1 and abs(active[0].vx - vx) < 0.1
    u, v = tr.velocity_kmh(active[0])
    assert u > 0 and v < 0                                # eastward, southward


def test_xcorr_fallback_for_young_cell():
    tr = Tracker(LATS, LONS, xcorr_lag_frames=2)
    field = lambda t: blob(20 + 0.5 * t, 20 + 1.0 * t, r=6)
    # reflectivity-like background exists before the hail cell appears
    for k, t in enumerate([0.0, 2.0, 4.0]):
        refl = 30 + field(t)
        mesh = field(t) if k == 2 else np.zeros_like(refl)
        tr.update(t, mesh, refl=refl)
    young = [t for t in tr.tracks if t.active][0]
    assert young.motion_src == "xcorr"
    assert abs(young.vx - 1.0) < 0.3 and abs(young.vy - 0.5) < 0.3


def test_advect_moves_footprint():
    tr = Tracker(LATS, LONS)
    for k in range(5):
        tr.update(2.0 * k, blob(20, 10 + 2.0 * k))       # 1 px/min east
    fc = advect([t for t in tr.tracks if t.active], (60, 80), [0, 20], offset_min=0.0)
    p = fc.prob(30.0)
    assert p[0, 20, 18] == 1.0                           # current position
    assert p[1, 20, 38] > 0 and p[1, 20, 18] == 0.0     # 20 px east after 20 min
    yy, xx = np.nonzero(p[1])
    w = p[1][yy, xx]
    assert abs((xx * w).sum() / w.sum() - 38) < 1 and abs((yy * w).sum() / w.sum() - 20) < 1
    assert p[1].max() < 1.0                              # ensemble spreads the footprint


def test_shift2d_no_wrap():
    a = np.zeros((5, 5)); a[0, 0] = 1
    assert shift2d(a, -1, 0).sum() == 0 and shift2d(a, 2, 3)[2, 3] == 1


def test_state_machine_transitions():
    th = Thresholds()
    m = AssetMachine(th)
    assert m.step(0.0, None, False, False) == MONITOR
    assert m.step(0.33, 30, False, False) == ARM
    assert m.step(0.33, 25, False, False) == ARM
    # three low updates cancel an ARM, then back to MONITOR
    assert [m.step(0.0, None, False, False) for _ in range(3)] == [ARM, ARM, CANCEL]
    assert m.step(0.0, None, False, False) == MONITOR
    # imminent arrival goes straight to TRIGGER; TRIGGER is latched through a moderate dip
    assert m.step(0.33, 5, False, False) == TRIGGER
    assert m.step(0.2, 20, False, False) == TRIGGER
    assert m.step(0.0, None, False, True) == DEGRADED
    assert m.level == TRIGGER
    assert [m.step(0.05, None, False, False) for _ in range(3)] == [TRIGGER, TRIGGER, ALL_CLEAR]
    # hysteresis: a value between exit and arm thresholds resets the low counter
    m2 = AssetMachine(th)
    m2.step(0.4, 30, False, False)
    seq = [m2.step(p, None, False, False) for p in (0.0, 0.0, 0.2, 0.0, 0.0, 0.0)]
    assert seq == [ARM, ARM, ARM, ARM, ARM, CANCEL]
    # EV rule below the probability thresholds: ARM while hail is far, TRIGGER inside the deploy window
    m3 = AssetMachine(th)
    assert m3.step(0.22, 35, True, False, arrival_earliest=30) == ARM
    assert m3.step(0.22, 25, True, False, arrival_earliest=15) == TRIGGER


def test_ev_rule():
    th = Thresholds()
    assert ev_fires(0.22, 8e6, 4000, th)
    assert not ev_fires(0.11, 8e6, 4000, th)            # below the single-member gate
    assert not ev_fires(0.5, 1000, 4000, th)            # cheap asset, expensive action


def synthetic_frames(n=60, vx=0.6):
    times = pd.date_range("2024-08-05 23:00", periods=n, freq="2min")
    mesh = np.zeros((n, 60, 80), np.float32)
    for k in range(n):
        t = 2.0 * k
        mesh[k] = blob(30, 5 + vx * t, r=5, peak=50)
    return Frames(times, LATS, LONS, {"mesh": mesh, "posh": mesh * 2})


ASSETS = pd.DataFrame({"asset_id": ["X1", "X2"], "name": ["east", "north"], "category": ["dealer", "dealer"],
                       "latitude": [LATS[30], LATS[5]], "longitude": [LONS[60], LONS[40]],
                       "value_at_risk": [8e6, 8e6], "protect_cost": [4000, 4000]})


def test_replay_no_future_data_and_warns_ahead():
    f = synthetic_frames()
    issues = pd.date_range("2024-08-05 23:06", "2024-08-06 00:54", freq="6min")
    res, arrays, diag = run_replay(f, ASSETS, issues, event="synthetic", window=(issues[0], issues[-1]))
    for i, k in enumerate(diag["used_frame"]):
        assert k is not None and f.available_times[k] <= issues[i]
    # perturbing frames that were not yet available must not change any earlier issue
    cut = 25
    g = synthetic_frames()
    g.fields["mesh"][cut:] = 0
    g.fields["posh"][cut:] = 0
    res2, _, _ = run_replay(g, ASSETS, issues, event="synthetic", window=(issues[0], issues[-1]))
    early = [i for i, t in enumerate(issues) if t < f.available_times[cut]]
    assert early
    for a in range(len(ASSETS)):
        for i in early:
            assert res["assets"][a]["timeline"][i] == res2["assets"][a]["timeline"][i]
    # the eastbound cell hits X1, which is warned before onset; X2 is never hit nor warned
    ev = res["evaluation"]["nowcast"]
    assert ev["hits_total"] == 1 and ev["hits_caught"] == 1 and ev["per_asset"]["X1"]["lead_min"] >= 10
    assert ev["false_alarms"] == 0
    assert res["evaluation"]["mesh_only"]["per_asset"]["X1"]["lead_min"] in (None, 0) or \
        res["evaluation"]["mesh_only"]["per_asset"]["X1"]["lead_min"] < ev["per_asset"]["X1"]["lead_min"]
    assert res["evaluation"]["nowcast_watch"]["hits_caught"] == 1
    assert res["evaluation"]["nowcast_watch"]["per_asset"]["X1"]["lead_min"] >= ev["per_asset"]["X1"]["lead_min"]
    assert arrays["fcst_p30"].shape == (len(issues), 8, 60, 80) and arrays["fcst_p30"].dtype == np.uint8


def test_stale_data_degrades():
    f = synthetic_frames(n=10)
    issues = pd.date_range("2024-08-05 23:06", periods=8, freq="6min")
    res, _, _ = run_replay(f, ASSETS, issues, event="synthetic")
    states = [e["state"] for e in res["assets"][0]["timeline"]]
    assert states[-1] == DEGRADED and states[0] != DEGRADED


def test_task_window_status():
    from nowcast.feasibility import (BLOCKED, FEASIBLE, MISSED, NOT_NEEDED, TIGHT, summarize_asset, task_for,
                                     task_window)
    th = Thresholds()
    # latest start = earliest arrival - duration - 5 min margin; slack is relative to the issue time
    assert task_window(True, 45, 20, 0.0, th) == (20.0, 20.0, FEASIBLE)
    assert task_window(True, 30, 10, 0.0, th)[2] == FEASIBLE          # slack exactly 10 -> FEASIBLE
    assert task_window(True, 30, 20, 0.0, th) == (5.0, 5.0, TIGHT)
    assert task_window(True, 45, 45, 0.0, th) == (-5.0, -5.0, MISSED)
    # safety gate wins: arrival <= 15 min away, or observed hail within 10 km (lightning proxy)
    assert task_window(True, 15, 5, 0.0, th)[2] == BLOCKED
    assert task_window(True, 45, 10, 3.0, th)[2] == BLOCKED
    assert task_window(True, 10, 45, 0.0, th)[2] == BLOCKED           # blocked beats missed
    # no action or no arrival window -> not needed; latest start null without a window
    assert task_window(True, None, 20, 0.0, th) == (None, None, NOT_NEEDED)
    assert task_window(False, 30, 20, 50.0, th)[2] == NOT_NEEDED
    # category defaults vs CSV override
    assert task_for("dealer")[0] == 45 and task_for("solar")[0] == 10
    assert task_for("dealer", 12.0, "custom")[0] == 12.0 and task_for("dealer", float("nan"))[0] == 45
    tl = [{"issue_time": "t0", "task_window_status": NOT_NEEDED},
          {"issue_time": "t1", "task_window_status": TIGHT, "task_slack_min": 5.0, "arrival_earliest_lead_min": 30},
          {"issue_time": "t2", "task_window_status": BLOCKED}]
    s = summarize_asset(tl, {"first_arm": "t1", "lead_min": 40.0}, 20.0, "n")
    assert s["feasible"] and s["slack_at_first_arm_min"] == 5.0 and s["first_blocked_issue"] == "t2"


def test_replay_timeline_has_task_fields():
    f = synthetic_frames()
    issues = pd.date_range("2024-08-05 23:06", "2024-08-06 00:54", freq="6min")
    res, _, _ = run_replay(f, ASSETS, issues, event="synthetic", window=(issues[0], issues[-1]))
    from nowcast.feasibility import STATUSES
    for a in res["assets"]:
        assert a["task"]["task_duration_min"] == 45
        for e in a["timeline"]:
            assert e["task_window_status"] in STATUSES
            basis = e["watch_arrival_earliest"] if e["state"] == "WATCH" else e["arrival_earliest"]
            assert (e["latest_feasible_start"] is None) == (basis is None)
    # the hit site sees the cell coming: at some point the storm is near and outdoor work is blocked
    assert any(e["task_window_status"] == "BLOCKED_UNSAFE" for e in res["assets"][0]["timeline"])


def test_core_members_match_original_ensemble():
    from nowcast.advect import core_index, members, members_norm, spread_fn
    norm = members_norm(5, 5)
    core = core_index(norm)
    sp = spread_fn()
    for L in (0, 30, 45):
        s, d = sp(L)
        got = [(1 + norm[i][0] * s, norm[i][1] * d) for i in core]
        assert np.allclose(got, members())
    s90, d90 = sp(90)
    assert abs(s90 - 0.30) < 1e-9 and abs(np.rad2deg(d90) - 25) < 1e-9
    s675, _ = sp(67.5)
    assert abs(s675 - 0.25) < 1e-9


def test_watch_state_machine():
    th = Thresholds()
    m = AssetMachine(th)
    assert m.step(0.0, None, False, False, p30_watch=0.12) == MONITOR
    assert m.step(0.0, None, False, False, p30_watch=0.24) == WATCH
    # hysteresis: a value between exit and entry keeps WATCH and resets the low counter
    assert [m.step(0.0, None, False, False, p30_watch=p) for p in (0.0, 0.0, 0.15, 0.0, 0.0)] == [WATCH] * 5
    assert m.step(0.0, None, False, False, p30_watch=0.0) == MONITOR      # third low update in a row
    assert m.level == MONITOR
    # WATCH escalates to ARM on the unchanged ARM rule; ARM never steps down to WATCH
    m2 = AssetMachine(th)
    assert m2.step(0.0, None, False, False, p30_watch=0.4) == WATCH
    assert m2.step(0.33, 30, False, False, p30_watch=0.4) == ARM
    assert [m2.step(0.0, None, False, False, p30_watch=0.4) for _ in range(3)] == [ARM, ARM, CANCEL]
    assert m2.step(0.0, None, False, False, p30_watch=0.4) == WATCH        # re-enters WATCH from MONITOR
    # stale data degrades but keeps the level underneath
    assert m2.step(0.0, None, False, True, p30_watch=0.4) == DEGRADED and m2.level == WATCH


LONS_WIDE = np.round(-114.4 + 0.01 * np.arange(240), 4)


def ellipse(cy, cx, ry, rx, peak=50.0, shape=(60, 240)):
    yy, xx = np.mgrid[: shape[0], : shape[1]]
    d = np.hypot((yy - cy) / ry, (xx - cx) / rx)
    return np.where(d <= 1, peak * (1 - 0.5 * d), 0.0).astype(np.float32)   # >= 30 mm inside d <= 0.8


def wide_frames(ry, rx, n=12, x0=10.0):
    """Eastbound storm at 1 px/min (0.01 deg ~ 0.7 km at 51 N -> ~42 km/h) on a 60 x 240 grid."""
    times = pd.date_range("2024-08-05 23:00", periods=n, freq="2min")
    mesh = np.stack([ellipse(30, x0 + 2.0 * k, ry, rx) for k in range(n)])
    return Frames(times, LATS, LONS_WIDE, {"mesh": mesh, "posh": mesh * 2})


def _state_at(minutes_out, ry=20, rx=8):
    """Timeline entry at one issue for a site whose 1 km buffer the >= 30 mm core edge reaches in
    `minutes_out` minutes at the storm's own speed (constant intensity)."""
    f = wide_frames(ry, rx)
    issue = pd.Timestamp("2024-08-05 23:20")              # newest usable frame 23:18
    xc = 10.0 + 18.0                                      # core centre at 23:18
    dx = 2.0 + minutes_out + 0.8 * rx + 1.4               # latency shift + travel + core half-width + buffer
    assets = pd.DataFrame({"asset_id": ["W"], "name": ["w"], "category": ["dealer"],
                           "latitude": [LATS[30]], "longitude": [LONS_WIDE[int(round(xc + dx))]],
                           "value_at_risk": [8e6], "protect_cost": [4000]})
    res, _, _ = run_replay(f, assets, [issue], event="synthetic")
    return res["assets"][0]["timeline"][0]


def test_watch_fires_70_min_out_not_120():
    # a storm ~30 km across (N-S) with a ~11 km wide hail core, moving east at ~42 km/h
    e = _state_at(70)
    assert e["state"] == WATCH and e["p30"] == 0.0 and e["p30_watch"] >= 0.2
    assert 45 <= e["watch_arrival_earliest_lead_min"] <= 90 and e["arrival_earliest"] is None
    assert e["task_arrival_source"] == "watch_0_90" and e["task_window_status"] != "NOT_NEEDED"
    far = _state_at(120)                                  # beyond 90 min even for the +30 % speed member
    assert far["state"] == MONITOR and far["p30_watch"] == 0.0


def test_watch_misses_compact_cell_at_70_min():
    # documented limitation: a compact ~6 km hail core 70 min out is hit only by the centre-direction
    # members once the direction spread is ~+/-20 deg, so p30_watch stays below 0.2
    e = _state_at(70, ry=5, rx=5)
    assert e["state"] == MONITOR and 0 < e["p30_watch"] < 0.2


def test_watch_summary_safe_window():
    from nowcast.feasibility import BLOCKED, FEASIBLE, NOT_NEEDED, summarize_asset
    tl = [{"issue_time": "2024-08-06T01:12:00Z", "task_window_status": FEASIBLE},
          {"issue_time": "2024-08-06T01:30:00Z", "task_window_status": FEASIBLE},
          {"issue_time": "2024-08-06T01:48:00Z", "task_window_status": BLOCKED},
          {"issue_time": "2024-08-06T02:30:00Z", "task_window_status": NOT_NEEDED}]
    arm = {"first_arm": "2024-08-06T01:30:00Z", "lead_min": 40.0}
    watch = {"first_arm": "2024-08-06T01:12:00Z", "first_watch": "2024-08-06T01:12:00Z", "lead_min": 58.0}
    s = summarize_asset(tl, arm, 30.0, "n", watch_eval=watch, onset_iso="2024-08-06T02:10:00Z")
    assert s["first_watch"] == "2024-08-06T01:12:00Z" and s["watch_lead_min"] == 58.0
    assert s["safe_minutes"] == 36.0 and s["task_fits"] == "yes"
    assert s["safe_minutes_arm_only"] == 18.0 and s["task_fits_arm_only"] == "partly"
    # no observed hail -> fits is not scored
    assert summarize_asset(tl, arm, 30.0, "n", watch_eval=watch)["task_fits"] is None
