"""Verification metrics for a probabilistic binary forecast."""
import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score


def contingency(y, yhat):
    y, yhat = np.asarray(y, bool), np.asarray(yhat, bool)
    hits = int((y & yhat).sum())
    misses = int((y & ~yhat).sum())
    false_alarms = int((~y & yhat).sum())
    pod = hits / (hits + misses) if hits + misses else 0.0
    far = false_alarms / (hits + false_alarms) if hits + false_alarms else 0.0
    csi = hits / (hits + misses + false_alarms) if hits + misses + false_alarms else 0.0
    return {"hits": hits, "misses": misses, "false_alarms": false_alarms, "pod": pod, "far": far, "csi": csi}


def best_csi_cutoff(y, p):
    grid = np.unique(np.quantile(p, np.linspace(0.5, 0.995, 120)))
    scores = [contingency(y, p >= c)["csi"] for c in grid]
    return float(grid[int(np.argmax(scores))])


def reliability(y, p, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.any():
            out.append({"bin_mid": float((edges[b] + edges[b + 1]) / 2), "n": int(m.sum()),
                        "forecast": float(np.mean(p[m])), "observed": float(np.mean(np.asarray(y)[m]))})
    return out


def summary(y, p, cutoff):
    y, p = np.asarray(y), np.asarray(p)
    return {"auc": float(roc_auc_score(y, p)), "brier": float(brier_score_loss(y, p)),
            "base_rate": float(y.mean()), "cutoff": cutoff, **contingency(y, p >= cutoff)}
