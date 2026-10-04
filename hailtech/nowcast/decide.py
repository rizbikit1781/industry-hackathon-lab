"""Per-asset nowcast decision: probabilities, arrival window, EV rule and the ARM/TRIGGER state machine.

The day-ahead model owns MONITOR/PREPARE. This layer starts every asset in MONITOR and owns
WATCH, ARM, TRIGGER, CANCEL, ALL_CLEAR and DATA_DEGRADED.

  WATCH      "Storm approaching" (earlier, softer than ARM): p30_watch >= watch_p30, where p30_watch is the
             fraction of the widened 25-member ensemble hitting the site at any lead in
             [watch_min_lead, watch_max_lead] (45-90 min), and neither ARM nor TRIGGER fires. Back to MONITOR
             after n_low consecutive issues with p30_watch < watch_exit_p30. ARM/TRIGGER rules (on the 0-45 min,
             9-member p30) are unchanged and take precedence; an ARM/TRIGGER episode never steps down to WATCH.

  ARM        p30 >= arm_p30, or the EV rule fires while arrival is still > trigger_ev_max_lead away
  TRIGGER    p30 >= trigger_p30, or the EV rule fires with earliest arrival <= trigger_ev_max_lead
             (the deploy window), or p30 >= arm_p30 with likely arrival < arm_min_lead
  CANCEL     from ARM after n_low consecutive issues with p30 < exit_p30 (hysteresis); then MONITOR
  ALL_CLEAR  from TRIGGER after n_low consecutive low issues; then MONITOR (TRIGGER is latched)
  DATA_DEGRADED  newest MESH frame older than stale_min at the issue time (level is kept underneath)

EV rule: P * (L_unprotected - L_protected) > C_activation + (1 - P) * C_false, applied only when
P >= ev_min_p so a single ensemble member cannot fire it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from nowcast.tracking import grid_km

MONITOR, ARM, TRIGGER, CANCEL, ALL_CLEAR, DEGRADED = (
    "MONITOR", "ARM", "TRIGGER", "CANCEL", "ALL_CLEAR", "DATA_DEGRADED")
WATCH = "WATCH"
ACTIVE = {ARM, TRIGGER}                 # ARM-based warning (unchanged; the "nowcast" evaluation)
WARNED = {WATCH, ARM, TRIGGER}          # any alert to the site (the "nowcast_watch" evaluation)


@dataclass(frozen=True)
class Thresholds:
    # segmentation / tracking
    seg_mesh_mm: float = 10.0
    seg_posh: float = 30.0
    min_area_px: int = 5
    motion_frames: int = 8
    # ensemble
    speed_pert: float = 0.20
    dir_pert_deg: float = 15.0
    leads_min: tuple = (0, 10, 20, 30, 45, 60, 75, 90)   # output leads
    step_min: float = 5.0                         # internal lead step for asset sampling
    max_lead_min: float = 45.0                    # ARM/TRIGGER horizon (p30 uses leads <= this, core 9 members)
    # extended ensemble for WATCH: spread constant to max_lead_min, then linear to the max at watch_max_lead_min
    n_speed: int = 5
    n_dir: int = 5
    speed_pert_max: float = 0.30
    dir_pert_max_deg: float = 25.0
    # asset sampling and truth
    buffer_km: float = 1.0
    sizes_mm: tuple = (20, 30, 50)
    truth_mm: float = 30.0
    # state machine
    arm_p30: float = 0.3
    arm_min_lead: float = 10.0
    trigger_p30: float = 0.6
    trigger_ev_max_lead: float = 20.0             # EV fires TRIGGER only inside the deploy window
    exit_p30: float = 0.1
    n_low: int = 3
    watch_p30: float = 0.2                        # WATCH: p30 over leads [watch_min_lead, watch_max_lead]
    watch_exit_p30: float = 0.1                   # "low" update for WATCH hysteresis (n_low of them -> MONITOR)
    watch_min_lead_min: float = 45.0
    watch_max_lead_min: float = 90.0
    arrival_p: float = 0.1
    stale_min: float = 10.0
    # economics
    protected_loss_frac: float = 0.1
    ev_min_p: float = 0.15
    # task feasibility / outdoor safety (nowcast/feasibility.py)
    task_margin_min: float = 5.0                  # latest start = earliest arrival - task - margin
    tight_slack_min: float = 10.0                 # slack below this is TIGHT
    unsafe_arrival_min: float = 15.0              # no outdoor work once arrival is this close
    lightning_radius_km: float = 10.0             # observed MESH > 0 within this radius = lightning proxy
    # replay
    issue_every_min: int = 6
    latency_min: int = 2

    def as_dict(self):
        d = asdict(self)
        return {k: list(v) if isinstance(v, tuple) else v for k, v in d.items()}


def asset_masks(lats, lons, asset_latlon, buffer_km=1.0):
    """bool [asset, y, x]: pixels within buffer_km of each asset (always includes the nearest pixel)."""
    kmy, kmx = grid_km(lats, lons)
    Y, X = np.meshgrid(lats, lons, indexing="ij")
    out = np.zeros((len(asset_latlon), len(lats), len(lons)), bool)
    for a, (la, lo) in enumerate(asset_latlon):
        d = np.hypot((Y - la) / abs(lats[1] - lats[0]) * kmy, (X - lo) / abs(lons[1] - lons[0]) * kmx)
        out[a] = d <= buffer_km
        out[a, np.abs(lats - la).argmin(), np.abs(lons - lo).argmin()] = True
    return out


def asset_lead_probs(fields: np.ndarray, masks: np.ndarray, thr: float) -> np.ndarray:
    """fields [member, lead, y, x] -> per-member hit [asset, member, lead] (bool)."""
    m = fields.shape[0]
    flat = fields.reshape(m, fields.shape[1], -1)
    out = np.zeros((masks.shape[0], m, fields.shape[1]), bool)
    for a in range(masks.shape[0]):
        idx = np.flatnonzero(masks[a])
        out[a] = flat[:, :, idx].max(axis=2) >= thr
    return out


def summarize(hits: np.ndarray, leads: np.ndarray, arrival_p: float):
    """hits [member, lead] -> (p_any, earliest, likely, latest) with leads in minutes or None.

    p_any = fraction of members that hit the asset at any lead <= max lead.
    Arrival window: leads where the member fraction exceeds arrival_p; likely = first argmax.
    """
    p_any = float(hits.any(axis=1).mean())
    frac = hits.mean(axis=0)
    ok = np.flatnonzero(frac > arrival_p)
    if len(ok) == 0:
        return p_any, None, None, None
    return p_any, float(leads[ok[0]]), float(leads[int(np.argmax(frac))]), float(leads[ok[-1]])


def ev_fires(p, value_at_risk, protect_cost, th: Thresholds):
    if p < th.ev_min_p:
        return False
    unprot, prot = value_at_risk, th.protected_loss_frac * value_at_risk
    return p * (unprot - prot) > protect_cost + (1 - p) * protect_cost


class AssetMachine:
    """One asset's state across issue times."""

    def __init__(self, th: Thresholds):
        self.th = th
        self.level = MONITOR        # MONITOR / WATCH / ARM / TRIGGER
        self.low = 0

    def step(self, p30: float, arrival_likely, ev: bool, stale: bool, arrival_earliest=None,
             p30_watch: float = 0.0) -> str:
        th = self.th
        if stale:
            return DEGRADED
        earliest = arrival_likely if arrival_earliest is None else arrival_earliest
        ev_now = ev and earliest is not None and earliest <= th.trigger_ev_max_lead
        trig = p30 >= th.trigger_p30 or ev_now or (
            p30 >= th.arm_p30 and arrival_likely is not None and arrival_likely < th.arm_min_lead)
        arm = p30 >= th.arm_p30 or ev
        if trig:
            self.level, self.low = TRIGGER, 0
            return TRIGGER
        if self.level in (MONITOR, WATCH):
            if arm:
                self.level, self.low = ARM, 0
                return ARM
            if self.level == MONITOR:
                if p30_watch >= th.watch_p30:
                    self.level, self.low = WATCH, 0
                    return WATCH
                return MONITOR
            # WATCH: hysteresis on the way down, straight back to MONITOR (no CANCEL message)
            self.low = self.low + 1 if p30_watch < th.watch_exit_p30 else 0
            if self.low >= th.n_low:
                self.level, self.low = MONITOR, 0
                return MONITOR
            return WATCH
        # ARM or TRIGGER: hysteresis on the way down
        if p30 < th.exit_p30:
            self.low += 1
        else:
            self.low = 0
        if self.low >= th.n_low:
            out = CANCEL if self.level == ARM else ALL_CLEAR
            self.level, self.low = MONITOR, 0
            return out
        return self.level
