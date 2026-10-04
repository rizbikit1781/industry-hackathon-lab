"""Relative economic value (Richardson 2000) of a probabilistic forecast across cost/loss ratios.

For a user with cost/loss ratio a = C / (avoided loss), acting when p >= a, expense per case is
  E_fcst = a * (hits + false_alarms) / N + misses / N
Reference points: climatology-only E_clim = min(a, s) (always act or never act, s = base rate),
perfect knowledge E_perf = a * s.  V = (E_clim - E_fcst) / (E_clim - E_perf); 1 = perfect, 0 = no
better than the best fixed policy, negative = worse. Probabilities must be calibrated for p >= a
to be the right rule, which is why Stage 1 is isotonic- and Platt-calibrated.
"""
import numpy as np


def relative_value(p: np.ndarray, y: np.ndarray, alphas: np.ndarray) -> np.ndarray:
    p, y = np.ravel(p), np.ravel(y).astype(bool)
    n, s = y.size, y.mean()
    order = np.argsort(-p)
    p_sorted, y_sorted = p[order], y[order]
    cum_hits = np.cumsum(y_sorted)
    out = []
    for a in alphas:
        k = np.searchsorted(-p_sorted, -a, side="right")  # number of cases with p >= a
        hits = cum_hits[k - 1] if k else 0
        e_fcst = a * k / n + (y.sum() - hits) / n
        e_clim, e_perf = min(a, s), a * s
        out.append((e_clim - e_fcst) / (e_clim - e_perf))
    return np.array(out)
