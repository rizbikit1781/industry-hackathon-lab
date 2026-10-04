"""Decision layer: P(asset hit today) = P(regional hail day) x P(hit | hail day); protect if P*L >= C.

Dollar backtest treats every MESH cell in the label box as an asset (2020–2025, MESH >= HIT_MM is a hit).
Per-cell hit rates are recomputed leaving the scored year out, so no day is scored with rates it built.
"""
import numpy as np
import pandas as pd

from hailday.config import ASSETS_CSV
from hailday.mesh import HIT_MM, Mesh, conditional_hit_rate


def protect(p_asset, value_at_risk, protect_cost):
    return p_asset * value_at_risk >= protect_cost


def rates_leave_year_out(mesh: Mesh, size_mm=HIT_MM) -> dict[int, np.ndarray]:
    years = mesh.dates.year
    return {int(y): conditional_hit_rate(mesh, size_mm, day_mask=(years != y)) for y in np.unique(years)}


def score_assets(p_day: float, date: pd.Timestamp, mesh: Mesh, rates: np.ndarray, assets=None) -> pd.DataFrame:
    a = (pd.read_csv(ASSETS_CSV) if assets is None else assets).copy()
    ij = [mesh.cell(r.latitude, r.longitude) for r in a.itertuples()]
    a["p_hit_given_day"] = [rates[i, j] for i, j in ij]
    a["p_asset"] = p_day * a["p_hit_given_day"]
    a["protect"] = protect(a["p_asset"], a["value_at_risk"], a["protect_cost"])
    a["expected_loss"] = a["p_asset"] * a["value_at_risk"]
    if date in mesh.dates:
        d = mesh.dates.get_loc(date)
        a["observed_mesh_mm"] = [int(mesh.cube[d, i, j]) for i, j in ij]
    return a


def dollar_backtest(mesh: Mesh, p_day: pd.Series, policies: dict[str, pd.Series], value_at_risk: float,
                    protect_cost: float, size_mm=HIT_MM, avoided_fraction: float = 1.0) -> pd.DataFrame:
    """Every label-box cell is a generic asset with the given L and C.

    avoided_fraction: share of L an action prevents on a hit day (1.0 = full protection; the
    day-ahead readiness action uses less, since it only enables the nowcast-triggered response).
    Acting is worth it when P * avoided_fraction * L >= C.

    p_day / policies: Series indexed by date with P(regional hail day) per policy.
    Returns one row per policy with total cost, losses avoided, protections, and value vs perfect knowledge.
    """
    box = mesh.label_box_mask()
    rates_by_year = rates_leave_year_out(mesh, size_mm)
    days = [k for k, d in enumerate(mesh.dates) if mesh.valid[k] and d in p_day.index]
    hits = np.stack([mesh.cube[k][box] >= size_mm for k in days])                      # [day, cell]
    rates = np.stack([rates_by_year[int(mesh.dates[k].year)][box] for k in days])       # [day, cell]
    n_cells = hits.shape[1]
    rows = []
    kept = 1.0 - avoided_fraction
    never_cost = hits.sum() * value_at_risk
    perfect_cost = hits.sum() * (protect_cost + kept * value_at_risk)
    for name, series in {"never": None, "always": None, **policies}.items():
        if name == "never":
            act = np.zeros_like(hits)
        elif name == "always":
            act = np.ones_like(hits)
        else:
            p = series.reindex([mesh.dates[k] for k in days]).to_numpy()[:, None] * rates
            act = protect(p, avoided_fraction * value_at_risk, protect_cost)
        cost = (act.sum() * protect_cost + (hits & ~act).sum() * value_at_risk
                + (hits & act).sum() * kept * value_at_risk)
        rows.append({"policy": name, "total_cost": float(cost), "protections": int(act.sum()),
                     "hits": int(hits.sum()), "hits_protected": int((hits & act).sum()),
                     "value_vs_never": float(never_cost - cost),
                     "share_of_perfect_value": float((never_cost - cost) / (never_cost - perfect_cost))})
    out = pd.DataFrame(rows)
    out.attrs.update(n_days=len(days), n_cells=int(n_cells), value_at_risk=value_at_risk,
                     protect_cost=protect_cost, size_mm=size_mm, avoided_fraction=avoided_fraction)
    return out


def cell_day_probabilities(mesh: Mesh, policies: dict[str, pd.Series], size_mm=HIT_MM):
    """Flattened (label-box cell x valid day) truth and per-policy P(asset hit) = P(day) x P(hit | day).

    Hit rates are leave-year-out, matching dollar_backtest.
    """
    box = mesh.label_box_mask()
    rates_by_year = rates_leave_year_out(mesh, size_mm)
    common = set.intersection(*(set(s.index) for s in policies.values()))
    days = [k for k, d in enumerate(mesh.dates) if mesh.valid[k] and d in common]
    y = np.stack([mesh.cube[k][box] >= size_mm for k in days])
    rates = np.stack([rates_by_year[int(mesh.dates[k].year)][box] for k in days])
    dates = [mesh.dates[k] for k in days]
    probs = {name: s.reindex(dates).to_numpy()[:, None] * rates for name, s in policies.items()}
    return y, probs
