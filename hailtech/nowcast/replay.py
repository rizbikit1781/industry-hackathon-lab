"""Causal replay: at each issue time use only frames with available_time <= issue time.

Frames are fed to the tracker in order and the loop pointer only moves forward, so a forecast can
never see a later frame. `used_frame` records the newest frame behind every issue (tested).
Verification (truth, +30 min grid scores) uses the full record and is computed separately.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nowcast.advect import advect, core_index, members_norm, spread_fn
from nowcast.decide import (ACTIVE, ARM, DEGRADED, MONITOR, TRIGGER, WARNED, WATCH, AssetMachine, Thresholds,
                            asset_lead_probs, asset_masks, ev_fires, summarize)
from nowcast.feasibility import message as task_message, summarize_asset, task_for, task_window
from nowcast.mrms import Frames
from nowcast.tracking import Tracker, grid_km

MIN_VALID_FRAC = 0.5   # a MESH frame with less finite coverage than this is treated as missing


def iso(t):
    return None if t is None or pd.isna(t) else pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nearest(lats, lons, la, lo):
    return int(np.abs(lats - la).argmin()), int(np.abs(lons - lo).argmin())


def fss(fcst: np.ndarray, obs: np.ndarray, n=9):
    """Fractions skill score of two binary fields with an n x n neighbourhood."""
    from scipy.ndimage import uniform_filter
    pf = uniform_filter(fcst.astype(float), n, mode="constant")
    po = uniform_filter(obs.astype(float), n, mode="constant")
    ref = (pf ** 2).sum() + (po ** 2).sum()
    return None if ref == 0 else float(1 - ((pf - po) ** 2).sum() / ref)


def run_replay(frames: Frames, assets: pd.DataFrame, issue_times, th: Thresholds = Thresholds(),
               event: str = "", window=None):
    """Returns (result dict in the output-contract shape, npz arrays dict, diagnostics dict)."""
    issue_times = pd.DatetimeIndex(issue_times)
    window = window or (issue_times[0], issue_times[-1])
    lats, lons = frames.lats, frames.lons
    H, W = len(lats), len(lons)
    kmy, kmx = grid_km(lats, lons)
    internal = np.arange(0, max(th.max_lead_min, th.watch_max_lead_min) + 1e-6, th.step_min)
    out_idx = [int(np.argmin(np.abs(internal - L))) for L in th.leads_min]
    n_arm = int((internal <= th.max_lead_min + 1e-6).sum())          # ARM/TRIGGER leads (0-45 min)
    wlead = (internal >= th.watch_min_lead_min - 1e-6) & (internal <= th.watch_max_lead_min + 1e-6)
    ens = members_norm(th.n_speed, th.n_dir)
    core = core_index(ens)                                           # the original 3 x 3 members
    spread = spread_fn(th.speed_pert, th.dir_pert_deg, th.speed_pert_max, th.dir_pert_max_deg,
                       grow_from=th.max_lead_min, grow_to=th.watch_max_lead_min)
    short = (internal <= th.max_lead_min + 1e-6)[:, None, None]

    latlon = list(zip(assets["latitude"], assets["longitude"]))
    masks = asset_masks(lats, lons, latlon, th.buffer_km)
    pix = [_nearest(lats, lons, la, lo) for la, lo in latlon]
    near_masks = asset_masks(lats, lons, latlon, th.lightning_radius_km)
    tasks = [task_for(r.get("category"), r.get("task_duration_min"), r.get("task_note"))
             for r in assets.to_dict("records")]
    mesh = frames["mesh"]
    posh, et50 = frames.fields.get("posh"), frames.fields.get("et50")
    refl = frames.fields.get("refl")
    avail = frames.available_times
    good = np.isfinite(mesh).reshape(len(mesh), -1).mean(axis=1) >= MIN_VALID_FRAC

    tracker = Tracker(lats, lons, th.seg_mesh_mm, th.seg_posh, th.min_area_px, th.motion_frames)
    t0 = frames.valid_times[0] if len(frames.valid_times) else issue_times[0]
    machines = {p: [AssetMachine(th) for _ in latlon] for p in ("nowcast", "persistence")}
    timelines = {p: [[] for _ in latlon] for p in ("nowcast", "persistence", "mesh_only")}
    levels = {p: [[] for _ in latlon] for p in ("nowcast", "persistence", "mesh_only", "nowcast_watch")}
    storms, used_frame = [], []
    obs_f = np.full((len(issue_times), H, W), -1, np.int16)
    p30_f = np.zeros((len(issue_times), len(th.leads_min), H, W), np.uint8)
    p30_persist_f = np.zeros_like(p30_f)

    k, newest = 0, None
    for i, issue in enumerate(issue_times):
        while k < len(mesh) and avail[k] <= issue:
            # MRMS re-stamps the last volume when no new radar scan arrived (~40 % of frames here);
            # a repeat carries no new information and would bias centroid velocities toward zero,
            # so it is skipped and the data age keeps counting from the original frame.
            # (An all-zero field legitimately repeats, so only fields with hail count as repeats.)
            repeat = (newest is not None and np.nanmax(mesh[k], initial=0) > 0
                      and np.array_equal(mesh[k], mesh[newest], equal_nan=True))
            if good[k] and not repeat:
                tmin = (frames.valid_times[k] - t0).total_seconds() / 60
                tracker.update(tmin, mesh[k], None if posh is None else posh[k],
                               None if et50 is None else et50[k], None if refl is None else refl[k])
                newest = k
            k += 1
        used_frame.append(newest)
        stale = newest is None or (issue - frames.valid_times[newest]).total_seconds() / 60 > th.stale_min
        active = [tr for tr in tracker.tracks if tr.active] if newest is not None else []
        offset = 0.0 if newest is None else (issue - frames.valid_times[newest]).total_seconds() / 60
        fc = advect(active, (H, W), internal, offset, ens, km=(kmy, kmx), spread=spread)
        fp = advect(active, (H, W), internal, offset, motion=False)
        if newest is not None:
            obs_f[i] = np.nan_to_num(mesh[newest], nan=-1).clip(-1, 32767).astype(np.int16)
        # leads <= 45 min: the original 9 core members (unchanged); 60-90 min: all members, widened spread
        ge = fc.fields >= 30.0
        pgrid = np.where(short, ge[core].mean(axis=0), ge.mean(axis=0))
        p30_f[i] = np.round(100 * pgrid[out_idx]).astype(np.uint8)
        p30_persist_f[i] = np.round(100 * fp.prob(30.0)[out_idx]).astype(np.uint8)

        for tr in active:
            u, v = tracker.velocity_kmh(tr)
            c = tr.cell
            storms.append({
                "issue_time": iso(issue), "storm_id": tr.storm_id,
                "lat": round(float(np.interp(c.cy, np.arange(H), lats)), 4),
                "lon": round(float(np.interp(c.cx, np.arange(W), lons)), 4),
                "u_kmh": round(float(u), 1), "v_kmh": round(float(v), 1),
                "area_km2": round(c.area_px * kmy * kmx, 1), "max_mesh_mm": round(c.max_mesh, 1),
                "max_posh": round(c.max_posh, 1), "echo_top50_km": round(c.max_et50, 2),
                "parent_id": tr.parent, "motion_src": tr.motion_src})

        near = [None if newest is None else float(np.nan_to_num(mesh[newest][near_masks[a]], nan=0).max())
                for a in range(len(latlon))]
        for pol, f in (("nowcast", fc), ("persistence", fp)):
            hits = {s: asset_lead_probs(f.fields, masks, s) for s in th.sizes_mm}
            cm = core if pol == "nowcast" else [0]
            for a, row in enumerate(assets.itertuples()):
                # ARM/TRIGGER inputs: core members, leads 0-45 min (identical to the 45-min nowcast)
                p = {s: summarize(hits[s][a][cm][:, :n_arm], internal[:n_arm], th.arrival_p) for s in th.sizes_mm}
                p30, ear, lik, lat = p[30]
                # WATCH inputs: all members, leads 45-90 min; extended arrival window over 0-90 min
                p30w = float(hits[30][a][:, wlead].any(axis=1).mean())
                _, ear_x, _, _ = summarize(hits[30][a], internal, th.arrival_p)
                ev = ev_fires(p30, row.value_at_risk, row.protect_cost, th)
                m = machines[pol][a]
                state = m.step(p30, lik, ev, stale, arrival_earliest=ear, p30_watch=p30w)
                lvl = m.level if state == DEGRADED else state
                levels[pol][a].append(lvl if lvl in ACTIVE else MONITOR)
                if pol == "nowcast":
                    levels["nowcast_watch"][a].append(lvl if lvl in WARNED else MONITOR)
                at = lambda L: None if L is None else iso(issue + pd.Timedelta(minutes=L))
                dur = tasks[a][0]
                t_ear = ear_x if state == WATCH else ear
                lfs, slack, tstat = task_window(state in WARNED, t_ear, dur, near[a], th)
                timelines[pol][a].append({
                    "issue_time": iso(issue), "state": state,
                    "p20": round(p[20][0], 3), "p30": round(p30, 3), "p50": round(p[50][0], 3),
                    "arrival_earliest": at(ear), "arrival_likely": at(lik), "arrival_latest": at(lat),
                    "ev_trigger": bool(ev),
                    "arrival_earliest_lead_min": ear,
                    "latest_feasible_start": at(lfs), "task_slack_min": slack,
                    "task_window_status": tstat, "task_message": task_message(tstat, at(lfs), dur),
                    "near_mesh_max_mm": None if near[a] is None else round(near[a], 1),
                    "p30_watch": round(p30w, 3),
                    "watch_arrival_earliest": at(ear_x), "watch_arrival_earliest_lead_min": ear_x,
                    "task_arrival_source": "watch_0_90" if state == WATCH else "nowcast_0_45"})
        # MESH-only baseline: ARM only while observed MESH at the asset pixel >= 20 mm now
        for a, (y, x) in enumerate(pix):
            now = -1.0 if newest is None else float(np.nan_to_num(mesh[newest, y, x], nan=-1))
            st = DEGRADED if stale else (ARM if now >= 20 else MONITOR)
            levels["mesh_only"][a].append(ARM if now >= 20 else MONITOR)
            timelines["mesh_only"][a].append({"issue_time": iso(issue), "state": st})

    # ---- verification (uses the whole record; never fed back into forecasts) ----
    w0, w1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    in_win = (frames.valid_times >= w0) & (frames.valid_times <= w1) & good
    observed = []
    swath = (np.nan_to_num(mesh[in_win], nan=-1).max(axis=0) >= th.truth_mm) if in_win.any() else np.zeros((H, W), bool)
    sy, sx = np.nonzero(swath)
    for a, (y, x) in enumerate(pix):
        series = np.nan_to_num(mesh[in_win, y, x], nan=-1)
        tv = frames.valid_times[in_win]
        ge = np.flatnonzero(series >= th.truth_mm)
        observed.append({"first_ge30_time": iso(tv[ge[0]]) if len(ge) else None,
                         "max_mesh_mm": float(series.max()) if len(series) else None,
                         # distance to the nearest pixel with MESH >= 30 mm at any time in the window
                         "nearest_ge30_km": round(float(np.hypot((sy - y) * kmy, (sx - x) * kmx).min()), 1)
                         if len(sy) else None})

    ids = assets["asset_id"].tolist()
    evaluation = {pol: evaluate(issue_times, levels[pol], observed, ids, th)
                  for pol in ("nowcast", "persistence", "mesh_only")}
    evaluation["nowcast_watch"] = evaluate(issue_times, levels["nowcast_watch"], observed, ids, th, warn=WARNED)
    for pol, arr in (("nowcast", p30_f), ("persistence", p30_persist_f)):
        lead_i = th.leads_min.index(30)
        evaluation[pol]["grid_30min"] = grid_scores(frames, good, issue_times, arr, th, lead_i, p_cut=50)
        evaluation[pol]["grid_30min_p10"] = grid_scores(frames, good, issue_times, arr, th, lead_i, p_cut=10)

    assets_out = []
    for a, row in enumerate(assets.itertuples()):
        assets_out.append({"asset_id": row.asset_id, "name": row.name, "category": row.category,
                           "lat": float(row.latitude), "lon": float(row.longitude),
                           "timeline": timelines["nowcast"][a], "observed": observed[a],
                           "task": summarize_asset(timelines["nowcast"][a],
                                                   evaluation["nowcast"]["per_asset"].get(row.asset_id),
                                                   *tasks[a],
                                                   watch_eval=evaluation["nowcast_watch"]["per_asset"].get(row.asset_id),
                                                   onset_iso=observed[a]["first_ge30_time"])})
    result = {
        "event": event, "window_utc": [iso(w0), iso(w1)],
        "issue_times": [iso(t) for t in issue_times], "leads_min": list(th.leads_min),
        "grid": {"npz": f"replay_{event}_fields.npz", "lats": [round(float(v), 4) for v in lats],
                 "lons": [round(float(v), 4) for v in lons]},
        "storms": storms, "assets": assets_out, "evaluation": evaluation, "thresholds": th.as_dict(),
    }
    arrays = {"issue_times": np.array([iso(t) for t in issue_times]), "obs_mesh": obs_f, "fcst_p30": p30_f}
    diag = {"used_frame": used_frame, "timelines": timelines, "p30_persistence": p30_persist_f,
            "frame_valid_times": frames.valid_times, "frame_available_times": avail}
    return result, arrays, diag


def _episodes(issue_times, lv, warn=ACTIVE):
    """[(start_idx, end_idx)] runs of warning levels (ARM/TRIGGER by default)."""
    eps, s = [], None
    for i, l in enumerate(lv + [MONITOR]):
        if l in warn and s is None:
            s = i
        elif l not in warn and s is not None:
            eps.append((s, i - 1))
            s = None
    return eps


def evaluate(issue_times, levels, observed, ids, th: Thresholds, warn=ACTIVE):
    """A truth asset is caught when a warning episode (ARM/TRIGGER; with warn=WARNED also WATCH) is active
    at the last issue time at or before the first observed MESH >= 30 mm; lead = onset - episode start.
    With WATCH in `warn`, per_asset also carries first_watch (first WATCH in the catching episode, else the
    first WATCH of the replay); `first_arm` then means the first alert of the episode (WATCH or ARM)."""
    per, leads, trig_leads, caught, total, fa, ftrig = {}, [], [], 0, 0, 0, 0
    step = pd.Timedelta(minutes=th.issue_every_min)
    for a, aid in enumerate(ids):
        lv = levels[a]
        eps = _episodes(issue_times, lv, warn)
        onset = observed[a]["first_ge30_time"]
        first_any = eps[0][0] if eps else None
        trig = [i for i, l in enumerate(lv) if l == TRIGGER]
        rec = {"first_arm": iso(issue_times[first_any]) if first_any is not None else None,
               "first_trigger": iso(issue_times[trig[0]]) if trig else None, "lead_min": None}
        if onset is not None:
            total += 1
            on = pd.Timestamp(onset.rstrip("Z"))
            for s, e in eps:
                if issue_times[s] <= on <= issue_times[e] + step:
                    caught += 1
                    lead = (on - issue_times[s]).total_seconds() / 60
                    leads.append(lead)
                    tr_in = [i for i in trig if s <= i <= e]
                    rec = {"first_arm": iso(issue_times[s]),
                           "first_trigger": iso(issue_times[tr_in[0]]) if tr_in else None,
                           "lead_min": round(lead, 1)}
                    if WATCH in warn:
                        w_in = [i for i in range(s, e + 1) if lv[i] == WATCH]
                        rec["first_watch"] = iso(issue_times[w_in[0]]) if w_in else None
                    if tr_in and issue_times[tr_in[0]] <= on:
                        trig_leads.append((on - issue_times[tr_in[0]]).total_seconds() / 60)
                    break
        else:
            fa += bool(eps)
            ftrig += bool(trig)
        if WATCH in warn and "first_watch" not in rec:
            w_all = [i for i, l in enumerate(lv) if l == WATCH]
            rec["first_watch"] = iso(issue_times[w_all[0]]) if w_all else None
        per[aid] = rec
    return {"hits_caught": caught, "hits_total": total,
            "median_lead_min": float(np.median(leads)) if leads else None,
            "false_alarms": fa, "false_triggers": ftrig,
            "triggered_before_onset": len(trig_leads),
            "median_trigger_lead_min": float(np.median(trig_leads)) if trig_leads else None,
            "per_asset": per}


def grid_scores(frames: Frames, good, issue_times, p30, th: Thresholds, out_idx_lead: int, p_cut=50):
    """Forecast P(>=30 mm) at +30 min >= p_cut % vs observed MESH >= 30 mm at issue + 30 min."""
    vt = frames.valid_times
    hits = misses = fas = 0
    fss_vals = []
    for i, issue in enumerate(issue_times):
        target = issue + pd.Timedelta(minutes=th.leads_min[out_idx_lead])
        j = int(np.abs((vt - target).total_seconds()).argmin()) if len(vt) else -1
        if j < 0 or abs((vt[j] - target).total_seconds()) > 120 or not good[j]:
            continue
        obs = np.nan_to_num(frames["mesh"][j], nan=0) >= th.truth_mm
        fc = p30[i, out_idx_lead] >= p_cut
        if not obs.any() and not fc.any():
            continue
        hits += int((fc & obs).sum()); misses += int((~fc & obs).sum()); fas += int((fc & ~obs).sum())
        v = fss(fc, obs)
        if v is not None:
            fss_vals.append(v)
    csi = hits / (hits + misses + fas) if hits + misses + fas else None
    return {"lead_min": th.leads_min[out_idx_lead], "p_cut_pct": p_cut, "hits_px": hits, "misses_px": misses,
            "false_alarms_px": fas, "csi": None if csi is None else round(csi, 3),
            "pod": round(hits / (hits + misses), 3) if hits + misses else None,
            "fss_9px_mean": round(float(np.mean(fss_vals)), 3) if fss_vals else None,
            "n_issues_scored": len(fss_vals)}
