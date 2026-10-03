"""Neighbourhood Smoke-and-Hail Flag System
================================================

This is the direct answer to the case's actual challenge (see README.md):

    "Flag neighbourhoods for smoke, hail, or both. Beat a lazy rule
    (downtown only, or 'city average is smoky -> flag everyone'). Then
    change the air cutoff or the hail weight and show which communities
    flip."

Pipeline (PLAN -> SCORE -> REVISE):
  1. PLAN   - load the bundled air-quality seed (3 real Calgary AQHI
              stations) and the neighbourhood table (92 communities +
              hail_track). Assign each community its NEAREST station by
              straight-line (haversine) distance - a sensor is not a
              neighbourhood.
  2. SCORE  - one-line flag rule per community:
                  smoke  = nearest_station_aqhi >= aqhi_cutoff
                  hail   = hail_track_weight    >= hail_cutoff
                  flag   = "both"/"smoke"/"hail"/"none"
              Compare the flagged list against two NAMED LAZY BASELINES:
                  (a) downtown-only   -> flag sector == CENTRE, always
                  (b) city-mean       -> flag EVERY community if the
                                          city-wide mean AQHI clears the
                                          cutoff, otherwise flag NONE
              Ground truth proxy: hail_track high/medium communities are
              the real-world-reported north/airport storm corridor from
              5 Aug 2024 - a baseline that can't even find that corridor
              (downtown) or that flags everyone/no-one (city-mean) is the
              "lazy rule" we need to beat.
  3. REVISE - sweep the AQHI cutoff and the hail weight; report exactly
              which communities flip flag status at each step, so a
              supervisor can see the rule move, not just a single number.

Outputs: console PLAN/SCORE/REVISE trace + flag_system_results.png
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

AQ_CSV = Path(__file__).parent / "data" / "calgary_air_quality_seed.csv"
NEIGH_CSV = Path(__file__).parent / "data" / "neighbourhoods_hail_scenario.csv"
OUT_PNG = Path(__file__).parent / "flag_system_results.png"

# hail_track is a 3-band label; convert to a 0-1 "exposure weight" so it can
# be swept on the same 0-1 scale as the smoke/AQHI side of the rule.
TRACK_WEIGHT = {"high": 1.0, "medium": 0.5, "low": 0.0}

DEFAULT_AQHI_CUTOFF = 5.0   # AQHI scale is ~1 (low) to 7+ (high risk)
DEFAULT_HAIL_CUTOFF = 0.75  # only "high" (1.0) clears this by default


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    aq = pd.read_csv(AQ_CSV, parse_dates=["readingdate"])
    neigh = pd.read_csv(NEIGH_CSV)
    return aq, neigh


def latest_station_aqhi(aq: pd.DataFrame) -> pd.DataFrame:
    """Most recent Air Quality Health Index reading per station (the 'is it
    smoky right now' signal a dispatcher would actually look at)."""
    aqhi = aq[aq["parameter"] == "Air Quality Health Index"].copy()
    latest_idx = aqhi.groupby("station_name")["readingdate"].idxmax()
    latest = aqhi.loc[latest_idx, ["station_name", "readingdate", "value", "latitude", "longitude"]]
    return latest.rename(columns={"value": "aqhi", "latitude": "station_lat", "longitude": "station_lon"})


def assign_nearest_station(neigh: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    neigh = neigh.copy()
    names, dists, aqhis = [], [], []
    for _, row in neigh.iterrows():
        best_name, best_d, best_aqhi = None, float("inf"), None
        for _, s in stations.iterrows():
            d = haversine_km(row["latitude"], row["longitude"], s["station_lat"], s["station_lon"])
            if d < best_d:
                best_d, best_name, best_aqhi = d, s["station_name"], s["aqhi"]
        names.append(best_name)
        dists.append(best_d)
        aqhis.append(best_aqhi)
    neigh["nearest_station"] = names
    neigh["station_km"] = dists
    neigh["station_aqhi"] = aqhis
    return neigh


def flag_rule(aqhi: float, hail_weight: float, aqhi_cutoff: float, hail_cutoff: float) -> str:
    """The one-line rule the README asks for."""
    smoke, hail = aqhi >= aqhi_cutoff, hail_weight >= hail_cutoff
    return "both" if smoke and hail else "smoke" if smoke else "hail" if hail else "none"


def apply_agent_rule(neigh: pd.DataFrame, aqhi_cutoff: float, hail_cutoff: float) -> pd.DataFrame:
    neigh = neigh.copy()
    neigh["track_weight"] = neigh["hail_track"].map(TRACK_WEIGHT)
    neigh["flag"] = [
        flag_rule(a, w, aqhi_cutoff, hail_cutoff)
        for a, w in zip(neigh["station_aqhi"], neigh["track_weight"])
    ]
    return neigh


def apply_downtown_only_baseline(neigh: pd.DataFrame) -> pd.Series:
    """Lazy rule #1: only ever flag the city-centre communities, regardless
    of what the air or the hail path actually did."""
    return neigh["sector"].eq("CENTRE").map({True: "flagged", False: "none"})


def apply_city_mean_baseline(neigh: pd.DataFrame, stations: pd.DataFrame, aqhi_cutoff: float) -> pd.Series:
    """Lazy rule #2: collapse all stations to one city-wide number; if that
    single number clears the cutoff, flag EVERY community, otherwise flag
    none - zero spatial differentiation either way."""
    city_mean = stations["aqhi"].mean()
    flag_everyone = city_mean >= aqhi_cutoff
    return pd.Series(["flagged" if flag_everyone else "none"] * len(neigh), index=neigh.index)


def score_against_ground_truth(flag_col: pd.Series, neigh: pd.DataFrame) -> dict:
    """Ground-truth proxy: communities on the real reported 5-Aug-2024
    north/airport hail corridor (hail_track in {high, medium}). A flag list
    is useful if it (a) catches most of that corridor (recall) while (b)
    staying short enough that a supervisor could actually act on it
    (flagged / total)."""
    is_true_risk = neigh["hail_track"].isin(["high", "medium"])
    is_flagged = flag_col.ne("none")
    n_flagged = int(is_flagged.sum())
    recall = float((is_flagged & is_true_risk).sum() / is_true_risk.sum()) if is_true_risk.sum() else float("nan")
    precision = float((is_flagged & is_true_risk).sum() / n_flagged) if n_flagged else float("nan")
    return {"n_flagged": n_flagged, "pct_flagged": n_flagged / len(neigh), "recall": recall, "precision": precision}


def main() -> None:
    print("=" * 88)
    print("STEP 1 - PLAN: load bundled air + neighbourhood seeds, assign nearest station")
    aq, neigh_raw = load_data()
    stations = latest_station_aqhi(aq)
    print(stations[["station_name", "readingdate", "aqhi"]].to_string(index=False))
    neigh = assign_nearest_station(neigh_raw, stations)
    print(f"\n{len(neigh)} communities assigned to {stations['station_name'].nunique()} stations "
          f"(median distance to nearest station = {neigh['station_km'].median():.1f} km)")

    print("\nSTEP 2 - SCORE: one-line rule vs two lazy baselines "
          f"(AQHI cutoff={DEFAULT_AQHI_CUTOFF}, hail cutoff={DEFAULT_HAIL_CUTOFF})")
    agent = apply_agent_rule(neigh, DEFAULT_AQHI_CUTOFF, DEFAULT_HAIL_CUTOFF)
    downtown_flag = apply_downtown_only_baseline(neigh)
    city_mean_flag = apply_city_mean_baseline(neigh, stations, DEFAULT_AQHI_CUTOFF)

    agent_score = score_against_ground_truth(agent["flag"], neigh)
    downtown_score = score_against_ground_truth(downtown_flag, neigh)
    citymean_score = score_against_ground_truth(city_mean_flag, neigh)

    summary = pd.DataFrame(
        [
            {"rule": "Agent (nearest station + hail_track)", **agent_score},
            {"rule": "Lazy: downtown-only", **downtown_score},
            {"rule": "Lazy: city-mean flag-everyone/none", **citymean_score},
        ]
    )
    print(summary.to_string(index=False))
    print(f"\n  Ground truth = the {int(neigh['hail_track'].isin(['high', 'medium']).sum())} communities "
          f"on the real reported Aug-2024 north/airport corridor (hail_track high/medium).")
    print("  Downtown-only misses most of that corridor because the real storm was NORTH, not downtown.")
    print("  City-mean either floods the list with all 92 communities or produces an empty list - "
          "no neighbourhood ever gets singled out either way.")

    print(f"\n  Flag counts by category (agent rule): {agent['flag'].value_counts().to_dict()}")

    print("\nSTEP 3 - REVISE: sweep the AQHI cutoff and hail weight - which communities flip?")
    aqhi_sweep = [3.0, 4.0, 5.0, 6.0]
    hail_sweep = [0.4, 0.75, 1.0]  # 0.4 catches medium+high, 0.75/1.0 catch only high

    flips_records = []
    prev_flags = None
    for cutoff in aqhi_sweep:
        tmp = apply_agent_rule(neigh, cutoff, DEFAULT_HAIL_CUTOFF)
        n_flagged = int(tmp["flag"].ne("none").sum())
        if prev_flags is not None:
            flipped = neigh.loc[tmp["flag"].ne(prev_flags), "community_name"].tolist()
            print(f"  AQHI cutoff -> {cutoff:>3.1f}: {n_flagged:>3d}/{len(neigh)} flagged "
                  f"({len(flipped)} flipped vs previous cutoff)"
                  + (f" e.g. {', '.join(flipped[:6])}" if flipped else ""))
            flips_records.append({"sweep": "AQHI cutoff", "value": cutoff, "n_flagged": n_flagged, "n_flipped": len(flipped)})
        else:
            print(f"  AQHI cutoff -> {cutoff:>3.1f}: {n_flagged:>3d}/{len(neigh)} flagged (baseline)")
            flips_records.append({"sweep": "AQHI cutoff", "value": cutoff, "n_flagged": n_flagged, "n_flipped": 0})
        prev_flags = tmp["flag"]

    prev_flags = None
    for weight in hail_sweep:
        tmp = apply_agent_rule(neigh, DEFAULT_AQHI_CUTOFF, weight)
        n_flagged = int(tmp["flag"].ne("none").sum())
        if prev_flags is not None:
            flipped = neigh.loc[tmp["flag"].ne(prev_flags), "community_name"].tolist()
            print(f"  Hail cutoff -> {weight:>4.2f}: {n_flagged:>3d}/{len(neigh)} flagged "
                  f"({len(flipped)} flipped vs previous cutoff)"
                  + (f" e.g. {', '.join(flipped[:6])}" if flipped else ""))
            flips_records.append({"sweep": "Hail weight cutoff", "value": weight, "n_flagged": n_flagged, "n_flipped": len(flipped)})
        else:
            print(f"  Hail cutoff -> {weight:>4.2f}: {n_flagged:>3d}/{len(neigh)} flagged (baseline)")
            flips_records.append({"sweep": "Hail weight cutoff", "value": weight, "n_flagged": n_flagged, "n_flipped": 0})
        prev_flags = tmp["flag"]

    flips = pd.DataFrame(flips_records)
    plot(neigh, agent, summary, flips, OUT_PNG)


def plot(neigh: pd.DataFrame, agent: pd.DataFrame, summary: pd.DataFrame, flips: pd.DataFrame, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))

    # 1. Map-like scatter: all communities, colored by flag status
    color_map = {"both": "crimson", "smoke": "purple", "hail": "orange", "none": "lightgray"}
    for flag_val, color in color_map.items():
        sub = neigh[agent["flag"] == flag_val]
        axes[0].scatter(sub["longitude"], sub["latitude"], c=color, label=flag_val, s=35, edgecolors="black", linewidths=0.3)
    axes[0].set_title("Agent flags (nearest station + hail_track)")
    axes[0].set_xlabel("Longitude")
    axes[0].set_ylabel("Latitude")
    axes[0].legend(fontsize=8)

    # 2. Agent vs lazy baselines: flagged count + recall of real corridor
    x = np.arange(len(summary))
    axes[1].bar(x - 0.2, summary["n_flagged"], width=0.4, label="# flagged", color="steelblue")
    ax2 = axes[1].twinx()
    ax2.bar(x + 0.2, summary["recall"] * 100, width=0.4, label="% corridor recall", color="darkorange")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(["Agent", "Downtown\nonly", "City-mean"], fontsize=8)
    axes[1].set_ylabel("# communities flagged")
    ax2.set_ylabel("% of real corridor caught")
    axes[1].set_title("Agent vs lazy baselines")
    lines1, labels1 = axes[1].get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    axes[1].legend(lines1 + lines2, labels1 + labels2, fontsize=7, loc="upper right")

    # 3. Sensitivity sweep: flagged count and flip count per cutoff step
    aqhi_rows = flips[flips["sweep"] == "AQHI cutoff"]
    hail_rows = flips[flips["sweep"] == "Hail weight cutoff"]
    axes[2].plot(aqhi_rows["value"], aqhi_rows["n_flagged"], marker="o", label="AQHI sweep: # flagged")
    axes[2].bar(aqhi_rows["value"], aqhi_rows["n_flipped"], width=0.3, alpha=0.4, label="AQHI sweep: # flipped", color="gold")
    axes[2].set_xlabel("AQHI cutoff")
    axes[2].set_ylabel("Communities")
    axes[2].set_title("Cutoff sensitivity (AQHI sweep shown)")
    axes[2].legend(fontsize=7)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"\nSaved chart -> {out_path}")


if __name__ == "__main__":
    main()
