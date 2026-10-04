"""Latest feasible start for each site's protective task, and the outdoor-safety gate.

    latest_feasible_start = conservative_arrival_start - task_duration - margin

conservative_arrival_start is the forecast's *earliest* arrival (first lead where > arrival_p of members
hit the site). Status at each issue time:

  NOT_NEEDED      no nowcast action (state not WATCH/ARM/TRIGGER) or no forecast arrival window
  BLOCKED_UNSAFE  outdoor work is never recommended once the storm is near: forecast earliest arrival
                  <= unsafe_arrival_min away, or observed MESH > 0 within lightning_radius_km of the site
                  (lightning proxy; ECCC: when thunder roars, go indoors). Message: shelter, do not go outside.
  MISSED          latest_feasible_start is already in the past (slack < 0)
  TIGHT           0 <= slack < tight_slack_min
  FEASIBLE        slack >= tight_slack_min

In WATCH the earliest arrival comes from the extended 0-90 min ensemble (ARM/TRIGGER keep the 0-45 min one).
The safety gate (BLOCKED_UNSAFE) is identical in every state.

Safe working window (per site, `summarize_asset`): from the first alert (first WATCH or ARM, whichever comes
first, in the warning episode that covers onset) to the first BLOCKED_UNSAFE at or after it; if the site is never
blocked, up to the observed onset. task_fits: "yes" if safe_minutes >= task duration, "partly" if 0 < safe_minutes
< duration, "no" otherwise (no alert before onset, or blocked straight away); None for sites without observed hail.

Task durations are category ASSUMPTIONS (data/assets.csv task_duration_min overrides them).
"""
from __future__ import annotations

import math

import pandas as pd

NOT_NEEDED, FEASIBLE, TIGHT, MISSED, BLOCKED = "NOT_NEEDED", "FEASIBLE", "TIGHT", "MISSED", "BLOCKED_UNSAFE"
STATUSES = (NOT_NEEDED, FEASIBLE, TIGHT, MISSED, BLOCKED)
DOABLE = {FEASIBLE, TIGHT}

# ASSUMPTION: minutes to complete the protective task, by asset category (not site data)
TASK_DEFAULTS = {
    "dealer": (45, "ASSUMPTION: move/cover ~300 vehicles into service bays / under covers"),
    "rental_lot": (30, "ASSUMPTION: move rental fleet into covered bays / cover"),
    "airport_parking": (20, "ASSUMPTION: notify customers, open covered parking levels"),
    "fleet_lot": (30, "ASSUMPTION: move fleet vehicles indoors / cover"),
    "rv_storage": (20, "ASSUMPTION: notify owners to cover or move units"),
    "transit": (25, "ASSUMPTION: move LRVs from outdoor storage to covered tracks"),
    "nursery_greenhouse": (20, "ASSUMPTION: close vents, cover stock"),
    "solar": (10, "ASSUMPTION: stow trackers to hail-stow angle"),
}
DEFAULT_TASK = (30, "ASSUMPTION: generic protective task")

SHELTER_MSG = "Shelter now - do not go outside. Hail/lightning is near; outdoor protective work is not safe."


def task_for(category, duration=None, note=None):
    """(duration_min, note): CSV values when present, else the category default."""
    d, n = TASK_DEFAULTS.get(str(category), DEFAULT_TASK)
    try:
        if duration is not None and not (isinstance(duration, float) and math.isnan(duration)):
            d = float(duration)
    except (TypeError, ValueError):
        pass
    if isinstance(note, str) and note.strip():
        n = note
    return float(d), n


def task_window(active: bool, earliest_lead_min, duration_min: float, near_mesh_mm: float, th):
    """-> (latest_start_lead_min or None, slack_min or None, status).

    earliest_lead_min: forecast earliest arrival as minutes after the issue time (None = no window).
    Leads are relative to the issue time, so slack = latest_start_lead_min.
    """
    if earliest_lead_min is None:
        return None, None, NOT_NEEDED
    latest = float(earliest_lead_min) - duration_min - th.task_margin_min
    slack = latest
    if not active:
        return latest, slack, NOT_NEEDED
    if earliest_lead_min <= th.unsafe_arrival_min or (near_mesh_mm is not None and near_mesh_mm > 0):
        return latest, slack, BLOCKED
    if slack < 0:
        return latest, slack, MISSED
    if slack < th.tight_slack_min:
        return latest, slack, TIGHT
    return latest, slack, FEASIBLE


def message(status: str, latest_iso=None, duration_min=None) -> str:
    if status == BLOCKED:
        return SHELTER_MSG
    if status == MISSED:
        return "Too late to start the outdoor task safely before hail; protect people, not property."
    if status == TIGHT:
        return f"Start the {duration_min:.0f}-min task now (latest start {latest_iso})."
    if status == FEASIBLE:
        return f"Task fits: start by {latest_iso} ({duration_min:.0f} min + margin)."
    return ""


def _ts(s):
    return None if s is None else pd.Timestamp(str(s).rstrip("Z"))


def _minutes(a, b):
    return None if a is None or b is None else round((_ts(b) - _ts(a)).total_seconds() / 60, 1)


def fits(safe_min, duration_min):
    if safe_min is None or safe_min <= 0:
        return "no"
    return "yes" if safe_min >= duration_min else "partly"


def safe_window(timeline: list, alert_iso, onset_iso):
    """(first BLOCKED_UNSAFE issue at/after the alert, safe minutes alert -> blocked, else alert -> onset)."""
    if alert_iso is None:
        return None, None
    t0 = _ts(alert_iso)
    blocked = next((e["issue_time"] for e in timeline if e.get("task_window_status") == BLOCKED
                    and _ts(e["issue_time"]) >= t0), None)
    if blocked is not None and (onset_iso is None or _ts(blocked) <= _ts(onset_iso)):
        return blocked, _minutes(alert_iso, blocked)
    return blocked, _minutes(alert_iso, onset_iso)


def watch_summary(timeline: list, watch_eval: dict | None, arm_eval: dict | None, onset_iso, duration_min):
    """WATCH-tier fields: first_watch, watch_lead_min, first_alert, safe_minutes, task_fits (+ ARM-only baseline)."""
    first_alert = watch_eval.get("first_arm") if watch_eval else None   # start of the WATCH/ARM/TRIGGER episode
    first_watch = watch_eval.get("first_watch") if watch_eval else None
    first_arm = arm_eval.get("first_arm") if arm_eval else None
    if onset_iso is not None:   # only alerts at or before onset count as notice
        first_alert = first_alert if first_alert and _ts(first_alert) <= _ts(onset_iso) else None
        first_watch = first_watch if first_watch and _ts(first_watch) <= _ts(onset_iso) else None
        first_arm = first_arm if first_arm and _ts(first_arm) <= _ts(onset_iso) else None
    blocked, safe = safe_window(timeline, first_alert, onset_iso)
    blocked_arm, safe_arm = safe_window(timeline, first_arm, onset_iso)
    hit = onset_iso is not None
    return {
        "first_watch": first_watch, "first_alert": first_alert,
        "watch_lead_min": _minutes(first_watch, onset_iso),
        "alert_lead_min": _minutes(first_alert, onset_iso),
        "first_blocked_after_alert": blocked,
        "safe_minutes": safe, "task_fits": fits(safe, duration_min) if hit else None,
        "safe_minutes_arm_only": safe_arm, "task_fits_arm_only": fits(safe_arm, duration_min) if hit else None,
    }


def summarize_asset(timeline: list, per_asset_eval: dict, duration_min: float, note: str,
                    watch_eval: dict | None = None, onset_iso=None) -> dict:
    """Per-site summary: lead at first ARM, task duration, slack at first ARM, whether the task was feasible,
    plus the WATCH-tier safe working window (see module docstring)."""
    first = per_asset_eval.get("first_arm") if per_asset_eval else None
    row = next((e for e in timeline if e.get("issue_time") == first), None) if first else None
    doable = [e for e in timeline if e.get("task_window_status") in DOABLE]
    return {
        "task_duration_min": duration_min, "task_note": note,
        "first_arm": first,
        "observed_lead_min": per_asset_eval.get("lead_min") if per_asset_eval else None,
        "forecast_lead_at_first_arm_min": None if row is None else row.get("arrival_earliest_lead_min"),
        "latest_feasible_start_at_first_arm": None if row is None else row.get("latest_feasible_start"),
        "slack_at_first_arm_min": None if row is None else row.get("task_slack_min"),
        "status_at_first_arm": None if row is None else row.get("task_window_status"),
        "feasible": bool(doable),
        "first_feasible_issue": doable[0]["issue_time"] if doable else None,
        "first_blocked_issue": next((e["issue_time"] for e in timeline
                                     if e.get("task_window_status") == BLOCKED), None),
        **watch_summary(timeline, watch_eval, per_asset_eval, onset_iso, duration_min),
    }
