"""Explainable risk score per ticket / job.

risk = weighted mean of 0-1 features (weights are POLICY INPUTS, not learned). The model ranks
exposure (who is likely to be on that ice); it does not predict falls.

- `exposure` = static features only (layers + census + equity). Used to define "high-risk"
  (top quartile) for the metrics, so the label does not depend on any policy's choices.
- `priority` = exposure plus report pressure and age, used by the optimizer each day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import features as F

DEFAULT_WEIGHTS = {
    # people exposure (census 2019 + Equity Index 2021)
    "seniors_share": 1.0, "seniors75_share": 1.0, "children_share": 0.5,
    "lim_65": 0.75, "no_english": 0.25, "transit_work": 0.5,
    # place exposure (point layers)
    "school": 1.0, "hospital": 1.0, "seniors_res": 1.0, "childcare": 0.5,
    "traffic": 0.75, "ped": 0.75,
}
# Policy defaults chosen from the priority sweep in scripts/run_sim.py (see README): exposure
# counts 3x, age stays in as an anti-starvation term.
DYNAMIC_WEIGHTS = {"report_pressure": 0.5, "age": 1.0}
EXPO_WEIGHT = 3.0

LABELS = {
    "seniors_share": "high 65+ share", "seniors75_share": "high 75+ share",
    "children_share": "many children", "lim_65": "low-income seniors",
    "no_english": "no-English households", "transit_work": "transit commuters",
    "school": "near a school", "hospital": "near hospital/clinic",
    "seniors_res": "near seniors' residence", "childcare": "near child care",
    "traffic": "busy road", "ped": "pedestrian activity",
    "report_pressure": "multiple reports", "age": "open several days",
}


def effective_weights(weights: dict | None = None) -> dict:
    w = dict(DEFAULT_WEIGHTS if weights is None else weights)
    if F.seniors_residences() is None:          # no residences file -> feature carries no weight
        w["seniors_res"] = 0.0
    return w


def exposure(feat: pd.DataFrame, weights: dict | None = None) -> pd.Series:
    w = effective_weights(weights)
    cols = [c for c in w if w[c] > 0]
    tot = sum(w[c] for c in cols)
    return sum(feat[c] * w[c] for c in cols) / tot


def dynamic_terms(report_count, days_open) -> pd.DataFrame:
    rc = np.asarray(report_count, float)
    age = np.clip(np.asarray(days_open, float), 0, 14)
    return pd.DataFrame({"report_pressure": np.log1p(rc - 1) / np.log1p(20),   # 1 report -> 0
                         "age": age / 14})


def priority(expo, report_count, days_open, dyn_weights: dict | None = None, expo_weight=None):
    dw = DYNAMIC_WEIGHTS if dyn_weights is None else dyn_weights
    expo_weight = EXPO_WEIGHT if expo_weight is None else expo_weight
    d = dynamic_terms(report_count, days_open)
    num = expo_weight * np.asarray(expo) + sum(dw[k] * d[k].to_numpy() for k in dw)
    return num / (expo_weight + sum(dw.values()))


def reasons(feat: pd.DataFrame, weights: dict | None = None, top: int = 3,
            extra: pd.DataFrame | None = None) -> list[str]:
    """Name the top contributing features (weight x value) for each row."""
    w = effective_weights(weights)
    cols = [c for c in w if w[c] > 0]
    contrib = pd.DataFrame({c: feat[c].to_numpy() * w[c] for c in cols}, index=feat.index)
    if extra is not None:
        for c in extra.columns:
            contrib[c] = extra[c].to_numpy() * DYNAMIC_WEIGHTS.get(c, 1.0)
    out = []
    for _, r in contrib.iterrows():
        top_c = r.sort_values(ascending=False)
        top_c = top_c[top_c > 0.15].head(top)
        out.append(", ".join(LABELS[c] for c in top_c.index) or "baseline exposure")
    return out


def score_tickets(tickets: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    """Attach features, exposure and reason to historical tickets (community area-average)."""
    feat = F.ticket_features(tickets)
    out = tickets.copy()
    for c in feat.columns:
        out[c] = feat[c].to_numpy()
    out["exposure"] = exposure(feat, weights).to_numpy()
    out["reason"] = reasons(feat, weights)
    return out


PRESETS = {
    "default": None,
    "seniors_first": {**DEFAULT_WEIGHTS, "seniors_share": 2, "seniors75_share": 2, "lim_65": 1.5,
                      "seniors_res": 2},
    "children_first": {**DEFAULT_WEIGHTS, "children_share": 2, "school": 2, "childcare": 1.5},
    "mobility_first": {**DEFAULT_WEIGHTS, "traffic": 2, "ped": 2, "transit_work": 1.5},
    "equity_first": {**DEFAULT_WEIGHTS, "lim_65": 2, "no_english": 1.5, "transit_work": 1.5},
    "places_only": {k: (v if k in F.POINT_FEATURES else 0.0) for k, v in DEFAULT_WEIGHTS.items()},
    "people_only": {k: (v if k in F.COMMUNITY_FEATURES else 0.0) for k, v in DEFAULT_WEIGHTS.items()},
}
