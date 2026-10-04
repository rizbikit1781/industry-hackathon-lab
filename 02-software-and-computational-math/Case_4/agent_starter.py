"""Neighbourhood flags: downtown-only vs hail track (hail data only, for now)."""
from pathlib import Path

import pandas as pd

NEIGH = Path(__file__).parent / "data" / "neighbourhoods_hail_scenario.csv"

HAIL_W = {"high": 3.0, "medium": 1.5, "low": 0.0}
DOWNTOWN = {
    "DOWNTOWN COMMERCIAL CORE",
    "DOWNTOWN EAST VILLAGE",
    "DOWNTOWN WEST END",
    "EAU CLAIRE",
    "CHINATOWN",
    "BELTLINE",
}


def main():
    df = pd.read_csv(NEIGH)

    df["hail_w"] = df["hail_track"].map(HAIL_W)
    df["baseline_downtown"] = df["community_name"].str.upper().isin(DOWNTOWN)
    # Naive ops rule: flag every neighbourhood regardless of hail risk.
    df["baseline_citywide"] = True
    # v1: only the named high-risk hail path.
    df["flag_v1"] = df["hail_track"] == "high"
    # v2: high-risk path plus adjacent medium-risk communities.
    df["flag_v2"] = df["hail_track"].isin(["high", "medium"])

    print(f"Baseline downtown-only flags:      {int(df['baseline_downtown'].sum())}")
    print(f"Baseline citywide (flag everyone): {int(df['baseline_citywide'].sum())}")
    print(f"v1 hail high only:                 {int(df['flag_v1'].sum())}")
    print(f"v2 hail high or medium:             {int(df['flag_v2'].sum())}")
    flipped = int((df["flag_v1"] != df["flag_v2"]).sum())
    print(f"Communities that flipped:          {flipped}")
    show = df.loc[df["flag_v1"], ["community_name", "hail_track", "hail_w"]]
    print(show.sort_values(["hail_track"], ascending=[True]).head(12).to_string(index=False))


if __name__ == "__main__":
    main()
