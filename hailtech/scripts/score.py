"""Combine stages: Stage-1 day probabilities -> MESH-day recalibration -> per-asset decisions.

Writes (data/processed):
  stage1_<source>.parquet          date, p_climatology, p_single_index, p_hailday (+ *_mesh recalibrated)
  dollar_backtest_<source>.json    every MESH cell in the label box as an asset, 2020–2025
  scores/<date>.json               dashboard briefing cards for the demo dates

Stage-1 scores are honest everywhere: out-of-fold for 2006–2022, and the final model (trained on
2006–2022 only) for 2023–2025. The Platt map from ICHD-day probability to MESH-day probability is
fitted leaving the scored year out.

Usage: python scripts/score.py --source openmeteo [--dates 2024-08-05 2020-06-13 2021-07-20]
"""
import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hailday.assets import cell_day_probabilities, dollar_backtest, rates_leave_year_out, score_assets  # noqa: E402
from hailday.value import relative_value  # noqa: E402
from hailday.config import ASSETS_CSV, MODELS, PROCESSED  # noqa: E402
from hailday.features import feature_columns  # noqa: E402
from hailday.mesh import Mesh  # noqa: E402
from hailday.model import SINGLE_INDEX, climatology, single_index  # noqa: E402

POLICIES = ("climatology", "single_index", "hailday")


def stage1_scores(source: str) -> pd.DataFrame:
    feats = pd.read_parquet(PROCESSED / f"features_{source}.parquet")
    oof = pd.read_parquet(PROCESSED / f"oof_{source}.parquet")
    lab = feats[feats["severe"].notna()].assign(severe=lambda d: d["severe"].astype(int))
    new = feats[feats["severe"].isna()]
    bundle = joblib.load(MODELS / f"hailday_{source}.joblib")
    _, clim = climatology(lab, new)
    _, single = single_index(SINGLE_INDEX[source])(lab, new)
    later = pd.DataFrame({"date": new["date"], "p_climatology": clim, "p_single_index": single,
                          "p_hailday": bundle["model"].predict(new)})
    return pd.concat([oof.drop(columns=["year", "severe"]), later]).sort_values("date").reset_index(drop=True)


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))[:, None]


def recalibrate_to_mesh(s1: pd.DataFrame, mesh: Mesh) -> pd.DataFrame:
    """Platt map P(ICHD hail day) -> P(MESH hail day), leave-one-year-out over the MESH years."""
    regional = pd.Series(mesh.regional_days(), index=mesh.dates)[mesh.valid]
    both = s1.set_index("date").join(regional.rename("mesh_day"), how="inner")
    out = s1.copy()
    for pol in POLICIES:
        col = f"p_{pol}_mesh"
        out[col] = np.nan
        for yr in both.index.year.unique():
            tr = both[both.index.year != yr]
            lr = LogisticRegression(C=1e6).fit(logit(tr[f"p_{pol}"].to_numpy()), tr["mesh_day"].astype(int))
            m = out["date"].dt.year == yr
            out.loc[m, col] = lr.predict_proba(logit(out.loc[m, f"p_{pol}"].to_numpy()))[:, 1]
    return out


def top_features(feats: pd.DataFrame, date: pd.Timestamp, cols, k=6):
    z = (feats[cols] - feats[cols].mean()) / feats[cols].std()
    row = z[feats["date"] == date].iloc[0].dropna()
    raw = feats.loc[feats["date"] == date, cols].iloc[0]
    return [{"name": c, "value": round(float(raw[c]), 2), "note": f"{row[c]:+.1f} sd vs all days"}
            for c in row.abs().sort_values(ascending=False).index[:k]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="openmeteo")
    ap.add_argument("--dates", nargs="*", default=["2024-08-05", "2020-06-13", "2021-07-20"])
    args = ap.parse_args()

    mesh = Mesh.load()
    s1 = recalibrate_to_mesh(stage1_scores(args.source), mesh)
    s1.to_parquet(PROCESSED / f"stage1_{args.source}.parquet", index=False)

    assets = pd.read_csv(ASSETS_CSV)
    # Day-ahead PREPARE buys readiness, not protection (user decision, Sat Oct 3): cheap action that
    # lets the nowcast-triggered response save part of the loss. Both values are labelled assumptions.
    L = float(assets["value_at_risk"].median())
    C = float(assets["readiness_cost"].median())
    avoided = float(assets["readiness_avoided_fraction"].median())
    idx = s1.set_index("date")
    policies = {p: idx[f"p_{p}_mesh"] for p in POLICIES}
    regional = pd.Series(mesh.regional_days().astype(float), index=mesh.dates)
    policies["oracle_day"] = regional
    bt = dollar_backtest(mesh, idx["p_hailday_mesh"], policies, L, C, avoided_fraction=avoided)
    (PROCESSED / f"dollar_backtest_{args.source}.json").write_text(
        json.dumps({"attrs": bt.attrs, "rows": bt.to_dict("records")}, indent=2))
    print(bt.to_string(index=False))

    # Relative economic value across cost/loss ratios (user decision: no single $ figure to defend).
    y, probs = cell_day_probabilities(mesh, policies)
    alphas = np.logspace(-5, -1, 41)
    curves = {name: relative_value(p, y, alphas).tolist() for name, p in probs.items()}
    cats = assets.groupby("category").agg(L=("value_at_risk", "median"), C=("protect_cost", "median"),
                                          R=("readiness_cost", "median"), f=("readiness_avoided_fraction", "median"))
    markers = {c: {"readiness_alpha": float(r.R / (r.f * r.L)), "protect_alpha": float(r.C / r.L)}
               for c, r in cats.iterrows()}
    (PROCESSED / f"value_curve_{args.source}.json").write_text(json.dumps(
        {"alphas": alphas.tolist(), "base_rate": float(y.mean()), "n_cell_days": int(y.size),
         "curves": curves, "category_alphas": markers,
         "note": "V = 1 perfect, 0 = best of always/never, <0 worse. Cell-day level, label box, 2020-2025 MESH >= 30 mm."},
        indent=2))
    for name, v in curves.items():
        best = int(np.nanargmax(v))
        pos = [a for a, x in zip(alphas, v) if x > 0]
        span = f"{min(pos):.1e}-{max(pos):.1e}" if pos else "none"
        print(f"REV {name:13s} peak {v[best]:.3f} at C/L={alphas[best]:.1e}; V>0 for C/L in {span}")

    feats = pd.read_parquet(PROCESSED / f"features_{args.source}.parquet")
    cols = feature_columns(feats)
    rates = rates_leave_year_out(mesh)
    cutoff = joblib.load(MODELS / f"hailday_{args.source}.joblib")["cutoff"]
    (PROCESSED / "scores").mkdir(exist_ok=True)
    for d in args.dates:
        date = pd.Timestamp(d)
        r = idx.loc[date]
        yr_rates = rates.get(date.year, next(iter(rates.values())))
        a = score_assets(float(r["p_hailday_mesh"]), date, mesh, yr_rates, assets)
        # Day-ahead action is readiness (standby crew, customer heads-up), not protection.
        a["ready"] = a["p_asset"] * a["readiness_avoided_fraction"] * a["value_at_risk"] >= a["readiness_cost"]
        card = {
            "date": d, "source": args.source,
            "p_day": float(r["p_hailday"]), "p_day_mesh": float(r["p_hailday_mesh"]),
            "p_day_climatology": float(r["p_climatology"]), "p_day_single_index": float(r["p_single_index"]),
            "state_day": "PREPARE" if r["p_hailday"] >= cutoff else "MONITOR", "cutoff": cutoff,
            "in_training_years": bool(2006 <= date.year <= 2022),
            "top_features": top_features(feats, date, cols),
            "assets": a.rename(columns={}).replace({np.nan: None}).to_dict("records"),
        }
        (PROCESSED / "scores" / f"{d}.json").write_text(json.dumps(card, indent=2, default=str))
        print(f"{d}: P(day)={card['p_day']:.3f} (MESH-day {card['p_day_mesh']:.3f}), "
              f"clim {card['p_day_climatology']:.3f}, single {card['p_day_single_index']:.3f}, "
              f"{card['state_day']}, assets protected {int(a['protect'].sum())}/{len(a)}")


if __name__ == "__main__":
    main()
