"""Autonomous 311 Work-Order Dispatch Agent
=============================================

Reframes "who should 311 send next" as what it actually is: a constrained
combinatorial optimization problem (a multiple-knapsack / assignment
problem - NP-hard in general), not a sorted list.

  1. PLAN   - cluster tickets into geographic crew zones with K-Means
              (so a crew's jobs are close together, not scattered across
              the city), score each ticket with an aging-aware priority
              (safety type weight + capped age bonus so old low-priority
              tickets are not starved forever), then solve an Integer
              Linear Program (ILP) with PuLP/CBC that maximizes total
              priority served subject to per-crew capacity and zone
              affinity - a real solver, not a greedy sort.
  2. SCORE  - compare total priority captured, safety-ticket capture rate,
              and jobs served against the NAMED NAIVE BASELINE ("oldest
              ticket first", i.e. FIFO, ignoring type/zone).
  3. REVISE - apply ONE disruption (a crew calls in sick -> that crew's
              capacity drops to 0, OR a blizzard -> ice/snow priority
              spikes and total capacity is cut) and RE-SOLVE the ILP.
              Report how many jobs moved crew, how many were dropped, and
              how the optimized plan degrades more gracefully than FIFO.

Outputs:
  - console report (plan -> score -> revise trace)
  - results.png: priority captured before/after, crew map, safety capture
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pulp
from sklearn.cluster import KMeans

DATA = Path(__file__).parent / "data" / "311_dispatch_sample.csv"
OUT_PNG = Path(__file__).parent / "results.png"

CREWS = 8
JOBS_PER_CREW = 5
ZONE_BONUS = 4.0          # reward for assigning a job inside its crew's own geographic zone
AGE_CAP_DAYS = 30         # age bonus stops growing after this many days (prevents runaway starvation weighting)
TODAY = pd.Timestamp("2026-08-27")  # "now" for this sample (latest date in the bundled CSV)


def priority_weight(service_name: str) -> int:
    n = service_name.lower()
    if "pothole" in n or "ice" in n or "snow" in n:
        return 3  # safety-critical
    if "streetlight" in n or "sign" in n:
        return 2
    return 1


def load_and_score() -> pd.DataFrame:
    df = pd.read_csv(DATA, parse_dates=["requested_date"])
    df = df.dropna(subset=["longitude", "latitude"]).reset_index(drop=True)
    df["priority"] = df["service_name"].map(priority_weight)
    age_days = (TODAY - df["requested_date"]).dt.days.clip(lower=0)
    df["age_bonus"] = np.minimum(age_days, AGE_CAP_DAYS) / AGE_CAP_DAYS  # 0..1
    df["score"] = df["priority"] * 10 + df["age_bonus"] * 5  # safety type dominates, age breaks ties / prevents starving
    return df


def assign_zones(df: pd.DataFrame, n_crews: int) -> np.ndarray:
    """K-Means over (lon, lat): each crew 'owns' a geographic zone of the city."""
    km = KMeans(n_clusters=n_crews, n_init=10, random_state=0)
    return km.fit_predict(df[["longitude", "latitude"]])


def solve_ilp(df: pd.DataFrame, capacity: list[int]) -> pd.Series:
    """Maximize total score served, subject to per-crew capacity, with a
    bonus for keeping a crew inside its own zone (fewer cross-town drives).
    Returns a Series of crew id per ticket index, or -1 if left unserved.
    """
    n_crews = len(capacity)
    prob = pulp.LpProblem("dispatch", pulp.LpMaximize)
    x = {
        (i, c): pulp.LpVariable(f"x_{i}_{c}", cat="Binary")
        for i in df.index
        for c in range(n_crews)
        if capacity[c] > 0
    }

    prob += pulp.lpSum(
        x[(i, c)] * (row.score + (ZONE_BONUS if row.zone == c else 0))
        for i, row in df.iterrows()
        for c in range(n_crews)
        if (i, c) in x
    )

    for i in df.index:
        prob += pulp.lpSum(x[(i, c)] for c in range(n_crews) if (i, c) in x) <= 1

    for c in range(n_crews):
        if capacity[c] > 0:
            prob += pulp.lpSum(x[(i, c)] for i in df.index if (i, c) in x) <= capacity[c]

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    assigned = pd.Series(-1, index=df.index)
    for (i, c), var in x.items():
        if var.value() == 1:
            assigned.loc[i] = c
    return assigned


def fifo_baseline(df: pd.DataFrame, capacity: list[int]) -> pd.Series:
    """Named naive baseline: oldest ticket first, round-robin crews, ignore type/zone."""
    order = df.sort_values("requested_date").index.tolist()
    assigned = pd.Series(-1, index=df.index)
    remaining = list(capacity)
    c = 0
    for i in order:
        tries = 0
        while remaining[c] <= 0 and tries < len(remaining):
            c = (c + 1) % len(remaining)
            tries += 1
        if remaining[c] <= 0:
            continue
        assigned.loc[i] = c
        remaining[c] -= 1
        c = (c + 1) % len(remaining)
    return assigned


def report(name: str, df: pd.DataFrame, assigned: pd.Series) -> dict:
    served = assigned[assigned >= 0]
    served_df = df.loc[served.index]
    total_score = float(served_df["score"].sum())
    safety_total = int((df["priority"] == 3).sum())
    safety_served = int((served_df["priority"] == 3).sum())
    out = {
        "name": name,
        "served": len(served),
        "total_score": total_score,
        "safety_served": safety_served,
        "safety_total": safety_total,
        "safety_rate": safety_served / max(safety_total, 1),
    }
    print(
        f"{name:34s} served={out['served']:>4}  total_score={out['total_score']:>7.1f}  "
        f"safety_caught={out['safety_served']:>3}/{out['safety_total']:<3} ({100*out['safety_rate']:.0f}%)"
    )
    return out


def plot(df, zone, normal_ilp, normal_fifo, disrupt_ilp, disrupt_fifo, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # 1. Crew zones (K-Means) colored map of all tickets
    sc = axes[0].scatter(df["longitude"], df["latitude"], c=zone, cmap="tab10", s=14)
    axes[0].set_title("K-Means crew zones (geography)")
    axes[0].set_xlabel("longitude")
    axes[0].set_ylabel("latitude")

    # 2. Total priority score captured: FIFO vs optimized, normal vs disrupted
    labels = ["Normal day", "Disrupted day"]
    fifo_scores = [normal_fifo["total_score"], disrupt_fifo["total_score"]]
    ilp_scores = [normal_ilp["total_score"], disrupt_ilp["total_score"]]
    xpos = np.arange(len(labels))
    width = 0.35
    axes[1].bar(xpos - width / 2, fifo_scores, width, label="FIFO baseline")
    axes[1].bar(xpos + width / 2, ilp_scores, width, label="Optimized (ILP)")
    axes[1].set_xticks(xpos)
    axes[1].set_xticklabels(labels)
    axes[1].set_ylabel("Total priority score served")
    axes[1].set_title("Priority captured: baseline vs optimized")
    axes[1].legend()

    # 3. Safety-ticket capture rate
    fifo_rate = [100 * normal_fifo["safety_rate"], 100 * disrupt_fifo["safety_rate"]]
    ilp_rate = [100 * normal_ilp["safety_rate"], 100 * disrupt_ilp["safety_rate"]]
    axes[2].bar(xpos - width / 2, fifo_rate, width, label="FIFO baseline")
    axes[2].bar(xpos + width / 2, ilp_rate, width, label="Optimized (ILP)")
    axes[2].set_xticks(xpos)
    axes[2].set_xticklabels(labels)
    axes[2].set_ylabel("% safety tickets served (pothole/ice/snow)")
    axes[2].set_title("Safety capture rate")
    axes[2].legend()
    axes[2].set_ylim(0, 105)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"\nSaved chart -> {out_path}")


def main() -> None:
    print("=" * 78)
    print("STEP 1 - PLAN: K-Means crew zones + aging-aware priority + ILP assignment")
    df = load_and_score()
    df["zone"] = assign_zones(df, CREWS)
    capacity = [JOBS_PER_CREW] * CREWS
    print(f"         {len(df)} tickets, {CREWS} crews x {JOBS_PER_CREW} jobs/crew = {sum(capacity)} slots")

    normal_ilp_assign = solve_ilp(df, capacity)
    normal_fifo_assign = fifo_baseline(df, capacity)

    print("\nSTEP 2 - SCORE vs naive baseline ('oldest ticket first, FIFO')")
    normal_ilp = report("Optimized (ILP) - normal day", df, normal_ilp_assign)
    normal_fifo = report("FIFO baseline - normal day", df, normal_fifo_assign)

    print("\nSTEP 3 - REVISE: disruption = one crew calls in sick (capacity -> 0)")
    sick_crew = 0
    disrupt_capacity = capacity.copy()
    disrupt_capacity[sick_crew] = 0
    disrupt_ilp_assign = solve_ilp(df, disrupt_capacity)
    disrupt_fifo_assign = fifo_baseline(df, disrupt_capacity)

    disrupt_ilp = report("Optimized (ILP) - crew sick", df, disrupt_ilp_assign)
    disrupt_fifo = report("FIFO baseline - crew sick", df, disrupt_fifo_assign)

    moved_ilp = int((normal_ilp_assign != disrupt_ilp_assign).sum())
    moved_fifo = int((normal_fifo_assign != disrupt_fifo_assign).sum())
    print(f"\n         Jobs that changed crew/dropped after disruption: "
          f"optimized={moved_ilp}  FIFO={moved_fifo}")

    ilp_gain = 100 * (normal_ilp["total_score"] - normal_fifo["total_score"]) / max(normal_fifo["total_score"], 1)
    disrupt_gain = 100 * (disrupt_ilp["total_score"] - disrupt_fifo["total_score"]) / max(disrupt_fifo["total_score"], 1)
    print(f"\nRESULT: optimized agent captures {ilp_gain:.0f}% more priority than FIFO on a normal day, "
          f"and {disrupt_gain:.0f}% more after a crew goes down.")

    plot(df, df["zone"], normal_ilp, normal_fifo, disrupt_ilp, disrupt_fifo, OUT_PNG)


if __name__ == "__main__":
    main()
