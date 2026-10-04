"""Join labels with a feature source into the shared training frame.

Shared schema: date, year, doy_sin, doy_cos, severe (labels; NaN outside label years), then features.
`year` is kept for CV grouping only and is never a model input.
"""
import numpy as np
import pandas as pd

from hailday.config import PROCESSED

ID_COLS = ["date", "year", "severe"]


def add_calendar(df: pd.DataFrame) -> pd.DataFrame:
    doy = df["date"].dt.dayofyear
    df["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    df["year"] = df["date"].dt.year
    return df


def from_openmeteo() -> pd.DataFrame:
    from hailday.openmeteo import CACHE, daily_features

    hourly = pd.concat(pd.read_parquet(p) for p in sorted(CACHE.glob("*.parquet")))
    # Box statistics are taken across the 3x3 points inside daily_features (mean/max per hour).
    return daily_features(hourly)


def from_era5(rebuild: bool = False) -> pd.DataFrame:
    """ERA5 box max/mean indices at 12 and 18 UTC (hailday/era5.py); builds the parquet if absent."""
    from hailday.era5 import OUT, build_all

    df = build_all() if rebuild or not OUT.exists() else pd.read_parquet(OUT)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df


def build(source: str) -> pd.DataFrame:
    feats = {"openmeteo": from_openmeteo, "era5": from_era5}[source]()
    labels = pd.read_parquet(PROCESSED / "labels.parquet")[["date", "severe"]]
    df = add_calendar(feats.merge(labels, on="date", how="left"))
    cols = ID_COLS + [c for c in df.columns if c not in ID_COLS]
    df = df[cols].sort_values("date").reset_index(drop=True)
    df.to_parquet(PROCESSED / f"features_{source}.parquet", index=False)
    return df


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in ID_COLS]
