"""Open-Meteo archive (surface ERA5) fetch and per-day surface features.

The archive has no CAPE or pressure levels (verified), so these are fallback features
that let the model train before the CDS ERA5 request lands.
"""
import time

import numpy as np
import pandas as pd
import requests

from hailday.config import FEATURE_BOX, MONTHS, RAW, TZ

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
HOURLY = [
    "temperature_2m", "dew_point_2m", "surface_pressure", "wind_speed_10m", "wind_direction_10m",
    "wind_speed_100m", "wind_direction_100m", "boundary_layer_height", "precipitation", "shortwave_radiation",
]
CACHE = RAW / "openmeteo"


def grid_points():
    """3x3 points spanning the feature box (corners, mid-edges, centre)."""
    lat0, lat1, lon0, lon1 = FEATURE_BOX
    lats = np.linspace(lat0 + 0.5, lat1 - 0.5, 3)
    lons = np.linspace(lon0 + 0.5, lon1 - 0.5, 3)
    return [(round(a, 2), round(o, 2)) for a in lats for o in lons]


def fetch_year(lat: float, lon: float, year: int) -> pd.DataFrame:
    out = CACHE / f"{lat}_{lon}_{year}.parquet"
    if out.exists():
        return pd.read_parquet(out)
    # Start one day early so day-before features exist for 1 May.
    params = {
        "latitude": lat, "longitude": lon, "timezone": TZ, "hourly": ",".join(HOURLY),
        "start_date": f"{year}-{MONTHS.start - 1:02d}-28", "end_date": f"{year}-{MONTHS.stop - 1:02d}-30",
    }
    while True:  # free tier is weighted (~11 calls per request here); wait out 429s
        r = requests.get(ARCHIVE, params=params, timeout=120)
        if r.status_code != 429:
            r.raise_for_status()
            break
        time.sleep(65)
    h = r.json()["hourly"]
    df = pd.DataFrame(h).assign(time=lambda d: pd.to_datetime(d["time"]), lat=lat, lon=lon)
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def daily_features(hourly: pd.DataFrame) -> pd.DataFrame:
    """Per local day: morning-state values (box mean/max over points) plus antecedent conditions."""
    h = hourly.copy()
    h["date"] = h["time"].dt.normalize()
    h["hour"] = h["time"].dt.hour
    for k in ("10m", "100m"):
        rad = np.deg2rad(h[f"wind_direction_{k}"])
        h[f"u_{k}"] = -h[f"wind_speed_{k}"] * np.sin(rad)
        h[f"v_{k}"] = -h[f"wind_speed_{k}"] * np.cos(rad)

    snap_cols = ["temperature_2m", "dew_point_2m", "surface_pressure", "u_10m", "v_10m", "u_100m", "v_100m",
                 "boundary_layer_height"]
    feats = []
    for hour, tag in ((6, "06"), (12, "12")):
        s = h[h["hour"] == hour].groupby("date")[snap_cols].agg(["mean", "max"])
        s.columns = [f"{c}_{a}_{tag}" for c, a in s.columns]
        feats.append(s)
    f = pd.concat(feats, axis=1)
    f["dewpoint_depression_12"] = f["temperature_2m_mean_12"] - f["dew_point_2m_mean_12"]
    f["pressure_tendency_06_12"] = f["surface_pressure_mean_12"] - f["surface_pressure_mean_06"]
    f["shear_proxy_12"] = np.hypot(f["u_100m_mean_12"] - f["u_10m_mean_12"], f["v_100m_mean_12"] - f["v_10m_mean_12"])

    day = h.groupby("date").agg(tmax=("temperature_2m", "max"), precip=("precipitation", "sum"),
                                sw=("shortwave_radiation", "sum"))
    night = h[h["hour"] <= 6].groupby("date")["dew_point_2m"].min().rename("overnight_min_td")
    day = day.join(night)
    f["prev_tmax"] = day["tmax"].shift(1)
    f["prev_precip"] = day["precip"].shift(1)
    f["precip_3d"] = day["precip"].shift(1).rolling(3, min_periods=1).sum()
    f["prev_sw"] = day["sw"].shift(1)
    f["overnight_min_td"] = day["overnight_min_td"]
    f = f.reset_index()
    return f[f["date"].dt.month.isin(MONTHS)]
