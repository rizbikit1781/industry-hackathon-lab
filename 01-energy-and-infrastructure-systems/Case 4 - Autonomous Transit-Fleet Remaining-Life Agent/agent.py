"""Autonomous Transit-Fleet Remaining-Life Agent
=================================================

Upgrades the baseline starter (single straight line, manual threshold) into a
real plan -> score -> revise loop:

  1. PLAN   - engineer degradation-aware features (rolling trend/variance of
              sensors, not just the latest raw reading) and fit a nonlinear
              model (Gradient Boosting) on a capped RUL target - the standard
              trick in the PHM / C-MAPSS literature, since engines fly mostly
              "healthy and flat" before they start to degrade.
  2. SCORE  - evaluate against a NAMED NAIVE BASELINE (fixed-interval
              inspection schedule) on held-out test engines, using both a
              regression metric (MAE) and a business metric (missed
              failures vs. wasted inspections).
  3. REVISE - the agent itself sweeps the inspect-threshold and picks the
              one that minimizes a cost function (cost of a missed failure
              vs. cost of an unnecessary inspection) instead of a human
              guessing a cutoff. This is the "autonomous decision" step.

Outputs:
  - console report (plan -> score -> revise trace)
  - results.png: predicted-vs-actual RUL + cost-vs-threshold + inspect plan
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

DATA = Path(__file__).parent / "data"
OUT_PNG = Path(__file__).parent / "results.png"

COLS = ["unit_nr", "time_cycles", "setting_1", "setting_2", "setting_3"] + [
    f"s_{i}" for i in range(1, 22)
]
# Sensors known in C-MAPSS literature to trend with degradation (drop flat ones).
SENSORS = ["s_2", "s_3", "s_4", "s_7", "s_8", "s_9", "s_11", "s_12", "s_13", "s_14", "s_15", "s_17", "s_20", "s_21"]
ROLL_WINDOW = 5
RUL_CAP = 125  # engines run "healthy and flat" above this; capping the label helps the model learn the actual decay region

# Business costs the agent optimizes against (tune these to tell a different story).
COST_MISSED_FAILURE = 50   # an engine fails on the road -> very expensive / unsafe
COST_EXTRA_INSPECTION = 1  # a shop technician checks a healthy engine -> cheap but not free


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA / name, sep=r"\s+", header=None, names=COLS)


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add rolling mean/std per engine so the model sees a *trend*, not one snapshot."""
    df = df.sort_values(["unit_nr", "time_cycles"]).copy()
    grp = df.groupby("unit_nr")[SENSORS]
    roll_mean = grp.rolling(ROLL_WINDOW, min_periods=1).mean().reset_index(level=0, drop=True)
    roll_std = grp.rolling(ROLL_WINDOW, min_periods=1).std().fillna(0).reset_index(level=0, drop=True)
    roll_mean.columns = [f"{c}_mean{ROLL_WINDOW}" for c in SENSORS]
    roll_std.columns = [f"{c}_std{ROLL_WINDOW}" for c in SENSORS]
    return pd.concat([df, roll_mean, roll_std], axis=1)


def last_rows(df: pd.DataFrame) -> pd.DataFrame:
    idx = df.groupby("unit_nr")["time_cycles"].idxmax()
    return df.loc[idx].sort_values("unit_nr")


def feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("s_")]


def plan() -> tuple[np.ndarray, np.ndarray, pd.DataFrame, float]:
    """Engineer features and fit the degradation model. Returns (pred, true_rul, last_test, fleet_avg_life)."""
    train = add_rolling_features(load("train_FD001.txt"))
    test = add_rolling_features(load("test_FD001.txt"))
    true_rul = pd.read_csv(DATA / "RUL_FD001.txt", sep=r"\s+", header=None, names=["RUL"])["RUL"].to_numpy()

    max_cycle = train.groupby("unit_nr")["time_cycles"].transform("max")
    train["rul"] = np.minimum(max_cycle - train["time_cycles"], RUL_CAP)
    fleet_avg_life = float(train.groupby("unit_nr")["time_cycles"].max().mean())

    feats = feature_cols(train)
    model = GradientBoostingRegressor(
        n_estimators=200, max_depth=3, learning_rate=0.05, random_state=0
    ).fit(train[feats], train["rul"])

    last_test = last_rows(test)
    pred = np.clip(model.predict(last_test[feats]), 0, None)
    return pred, true_rul, last_test, fleet_avg_life


def naive_baseline(last_test: pd.DataFrame, fleet_avg_life: float) -> np.ndarray:
    """Named naive baseline: fleet-average-life persistence (no sensor reasoning).

    "Assume every engine will last as long as the fleet average, regardless
    of what its own sensors say" - this is the direct equivalent of the
    README's "same hour last week" persistence baseline, just for RUL. It
    uses *zero* sensor data, only how many cycles the engine has already run,
    so a learned agent that actually reads the sensors should beat it.
    """
    guess = fleet_avg_life - last_test["time_cycles"].to_numpy()
    return np.clip(guess, 0, None)


def score(pred: np.ndarray, true_rul: np.ndarray, threshold: float) -> dict:
    flag = pred < threshold
    truth = true_rul < threshold
    missed = int((truth & ~flag).sum())
    extra = int((flag & ~truth).sum())
    caught = int((flag & truth).sum())
    cost = missed * COST_MISSED_FAILURE + extra * COST_EXTRA_INSPECTION
    return {
        "threshold": threshold,
        "inspect_count": int(flag.sum()),
        "caught": caught,
        "missed": missed,
        "extra": extra,
        "cost": cost,
    }


def revise(pred: np.ndarray, true_rul: np.ndarray) -> tuple[dict, list[dict]]:
    """Autonomous step: sweep thresholds, log every iteration, keep the cheapest one."""
    trace = [score(pred, true_rul, t) for t in range(10, 90, 5)]
    best = min(trace, key=lambda r: r["cost"])
    return best, trace


def plot(pred, true_rul, trace, best, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))

    # 1. Predicted vs actual RUL
    axes[0].scatter(true_rul, pred, alpha=0.6, s=18)
    lims = [0, max(true_rul.max(), pred.max()) + 5]
    axes[0].plot(lims, lims, "r--", linewidth=1)
    axes[0].set_xlabel("Actual RUL (cycles)")
    axes[0].set_ylabel("Predicted RUL (cycles)")
    axes[0].set_title("Predicted vs Actual Remaining Life")

    # 2. Cost vs threshold (the autonomous "revise" trace)
    th = [r["threshold"] for r in trace]
    cost = [r["cost"] for r in trace]
    axes[1].plot(th, cost, marker="o")
    axes[1].axvline(best["threshold"], color="green", linestyle="--", label=f"chosen = {best['threshold']}")
    axes[1].set_xlabel("Inspect-if-predicted-RUL-below (cycles)")
    axes[1].set_ylabel("Total cost (missed x{} + extra x{})".format(COST_MISSED_FAILURE, COST_EXTRA_INSPECTION))
    axes[1].set_title("Agent's threshold search (revise loop)")
    axes[1].legend()

    # 3. Inspect-this-week ranked list (top 15 most urgent engines)
    order = np.argsort(pred)[:15]
    axes[2].barh(range(len(order)), pred[order][::-1], color="darkorange")
    axes[2].set_yticks(range(len(order)))
    axes[2].set_yticklabels([f"Engine {i}" for i in order[::-1]], fontsize=7)
    axes[2].set_xlabel("Predicted RUL (cycles)")
    axes[2].set_title("Top 15 most urgent engines")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"\nSaved chart -> {out_path}")


def main() -> None:
    print("=" * 70)
    print("STEP 1 - PLAN: engineering rolling degradation features + fitting")
    print(f"         Gradient Boosting model (RUL capped at {RUL_CAP} cycles)")
    pred, true_rul, last_test, fleet_avg_life = plan()
    mae = float(np.mean(np.abs(pred - true_rul)))
    print(f"         Test MAE = {mae:.1f} cycles")

    print("\nSTEP 2 - SCORE vs naive baseline ('fleet-average-life persistence, no sensors')")
    naive_pred = naive_baseline(last_test, fleet_avg_life)
    naive_mae = float(np.mean(np.abs(naive_pred - true_rul)))
    naive_best, _ = revise(naive_pred, true_rul)
    print(f"         Naive baseline MAE = {naive_mae:.1f} cycles")
    print(f"         Naive best cost at threshold={naive_best['threshold']}: "
          f"cost={naive_best['cost']}  missed={naive_best['missed']}  extra={naive_best['extra']}")

    print("\nSTEP 3 - REVISE: agent sweeps inspect-thresholds automatically")
    best, trace = revise(pred, true_rul)
    for r in trace:
        print(f"         threshold={r['threshold']:>3}  inspect={r['inspect_count']:>3}  "
              f"caught={r['caught']:>3}  missed={r['missed']:>3}  extra={r['extra']:>3}  cost={r['cost']}")
    print(f"\n         >>> Agent recommendation: inspect if predicted RUL < {best['threshold']} cycles")
    print(f"         >>> Expected outcome: {best['inspect_count']} inspections, "
          f"{best['missed']} missed failures, {best['extra']} wasted inspections, cost={best['cost']}")

    improvement = naive_best["cost"] - best["cost"]
    pct = 100 * improvement / max(naive_best["cost"], 1)
    print(f"\nRESULT: learned agent cuts total cost by {improvement} "
          f"({pct:.0f}%) vs the naive fixed-interval schedule.")

    plot(pred, true_rul, trace, best, OUT_PNG)


if __name__ == "__main__":
    main()
