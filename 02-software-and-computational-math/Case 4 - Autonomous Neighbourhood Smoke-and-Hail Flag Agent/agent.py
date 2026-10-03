"""Autonomous Neighbourhood Hail-Formation Flag Agent
=======================================================

The bundled case data's `hail_track` column is a STATIC SCENARIO LABEL
(high/medium/low) hand-drawn from news coverage of the 5 Aug 2024 storm -
it is exposure history, not a live hail-formation forecast. This version
adds the missing physics layer: it pulls REAL atmospheric parameters and
computes a transparent "Hail Formation Index" (HFI) inspired by the
Storm Prediction Center's Significant Hail Parameter (SHIP), then
combines that live formation risk with the bundled neighbourhood exposure
layer to answer two different questions at once:

  - "Is the atmosphere primed for hail today?"      -> HFI (physics)
  - "If it hails, which neighbourhoods get hit?"    -> hail_track (geography)

  1. PLAN   - fetch live/recent hourly CAPE, deep-layer wind shear, 700-500mb
              lapse rate, 500mb temperature, and low-level moisture for
              Calgary from Open-Meteo's free forecast API (no key needed),
              and compute HFI for every hour.
  2. SCORE  - compare the HFI-based day-flag against a NAMED NAIVE BASELINE
              ("flag any day with CAPE > 0", i.e. "any instability at all
              means hail risk") - show the naive rule over-flags almost
              every summer day while HFI discriminates.
  3. REVISE - sweep the HFI threshold and report how the flagged-day count
              changes; combine today's HFI with each neighbourhood's
              hail_track exposure weight to produce a ranked "who gets the
              flag today" list.

IMPORTANT - read before you present this:
  - HFI here is a SIMPLIFIED, transparent proxy inspired by SHIP's known
    ingredients (CAPE, moisture, lapse rate, mid-level cold air, deep
    shear). It is NOT a verbatim reproduction of the SPC's exact
    (proprietary-ish, multiply-clause) SHIP constants - do not present it
    as the official formula to a meteorologist judge. Say "inspired by".
  - Shear is approximated from 850mb-500mb winds (roughly 0-4 km here,
    since Calgary sits ~1049 m above sea level), not a true 0-6 km AGL
    shear - note this if asked.
  - For real historical backtesting (e.g. the actual 5 Aug 2024 storm),
    pull archived radiosonde soundings (University of Wyoming / Iowa
    State IEM upper-air archives) and compute CAPE/shear from the raw
    profile - Open-Meteo's historical archive does not carry CAPE that
    far back. Treat that as a stretch goal during the hackathon.

Outputs:
  - console report (plan -> score -> revise trace)
  - results.png: HFI time series, baseline-vs-agent flag counts, today's
    ranked neighbourhood risk list
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import requests

NEIGH_CSV = Path(__file__).parent / "data" / "neighbourhoods_hail_scenario.csv"
OUT_PNG = Path(__file__).parent / "results.png"

PAST_DAYS = 14
FORECAST_DAYS = 3
TRACK_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.2}

# Demo/what-if override: set to a number (e.g. 3.2) to pitch "what the agent
# would flag if HFI reaches a severe-storm value", instead of whatever HFI
# happens to be on judging day. Set back to None to use the live value.
DEMO_HFI_OVERRIDE: float | None = None

# HFI risk bands (our own documented scale - tune these during the "revise" step)
HFI_BANDS = [(1.0, "Low"), (2.5, "Marginal"), (4.5, "Elevated"), (float("inf"), "High")]


def fetch_atmos(lat: float, lon: float) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(
            [
                "cape",
                "convective_inhibition",
                "freezing_level_height",
                "dew_point_2m",
                "temperature_2m",
                "surface_pressure",
                "wind_speed_850hPa",
                "wind_direction_850hPa",
                "wind_speed_500hPa",
                "wind_direction_500hPa",
                "temperature_700hPa",
                "temperature_500hPa",
            ]
        ),
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
        "timezone": "America/Edmonton",
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
    r.raise_for_status()
    h = r.json()["hourly"]
    return pd.DataFrame(h).assign(time=lambda d: pd.to_datetime(d["time"]))


def mixing_ratio_gkg(dewpoint_c: pd.Series, pressure_hpa: pd.Series) -> pd.Series:
    """Saturation mixing ratio at the dew point (g/kg) - standard Magnus-form approximation."""
    e = 6.112 * np.exp(17.67 * dewpoint_c / (dewpoint_c + 243.5))
    return 621.97 * e / (pressure_hpa - e)


def wind_to_uv(speed_kmh: pd.Series, dir_deg: pd.Series) -> tuple[pd.Series, pd.Series]:
    speed_ms = speed_kmh / 3.6
    rad = np.radians(dir_deg)
    u = -speed_ms * np.sin(rad)
    v = -speed_ms * np.cos(rad)
    return u, v


def hail_formation_index(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["mixr_gkg"] = mixing_ratio_gkg(df["dew_point_2m"], df["surface_pressure"])
    df["lapse_700_500"] = (df["temperature_700hPa"] - df["temperature_500hPa"]) / 2.5  # approx 2.5 km thickness

    u850, v850 = wind_to_uv(df["wind_speed_850hPa"], df["wind_direction_850hPa"])
    u500, v500 = wind_to_uv(df["wind_speed_500hPa"], df["wind_direction_500hPa"])
    df["shear_ms"] = np.sqrt((u500 - u850) ** 2 + (v500 - v850) ** 2)

    cape_term = np.clip(df["cape"] / 1500, 0, 2.0)
    shear_term = np.clip(df["shear_ms"] / 20, 0.3, 1.5)
    cold_aloft_term = np.clip((-5 - df["temperature_500hPa"]) / 10, 0.3, 2.0)  # colder 500mb -> bigger term
    moisture_term = np.clip(df["mixr_gkg"] / 12, 0.5, 1.3)

    df["hfi"] = cape_term * shear_term * cold_aloft_term * moisture_term
    return df


def band(hfi: float) -> str:
    for limit, name in HFI_BANDS:
        if hfi < limit:
            return name
    return "High"


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = df["time"].dt.date
    agg = df.groupby("date").agg(
        hfi_max=("hfi", "max"),
        cape_max=("cape", "max"),
        freezing_level_min=("freezing_level_height", "min"),
    ).reset_index()
    agg["risk_band"] = agg["hfi_max"].map(band)
    return agg


def calibration_check() -> None:
    """Sanity-check the HFI formula against textbook atmospheric soundings,
    since we cannot fetch real historical CAPE for past severe-hail dates
    (Open-Meteo's archive API does not carry CAPE that far back - see the
    module docstring). This proves the formula moves the right direction
    before we trust it on live data.
    """
    scenarios = pd.DataFrame(
        [
            # name,                  cape,  shear_ms, t500_c, mixr_gkg
            ("Classic severe-hail day", 2500, 25, -20, 12.5),
            ("Marginal thunderstorm day", 800, 12, -14, 10.0),
            ("Calm / stable day", 50, 5, -2, 6.0),
        ],
        columns=["scenario", "cape", "shear_ms", "t500", "mixr_gkg"],
    )
    cape_term = np.clip(scenarios["cape"] / 1500, 0, 2.0)
    shear_term = np.clip(scenarios["shear_ms"] / 20, 0.3, 1.5)
    cold_aloft_term = np.clip((-5 - scenarios["t500"]) / 10, 0.3, 2.0)
    moisture_term = np.clip(scenarios["mixr_gkg"] / 12, 0.5, 1.3)
    scenarios["hfi"] = cape_term * shear_term * cold_aloft_term * moisture_term
    scenarios["risk_band"] = scenarios["hfi"].map(band)

    print("STEP 0 - CALIBRATE: sanity-check HFI against textbook soundings")
    print(scenarios[["scenario", "cape", "shear_ms", "t500", "mixr_gkg", "hfi", "risk_band"]].to_string(index=False))
    print()


def main() -> None:
    calibration_check()
    neigh = pd.read_csv(NEIGH_CSV)
    lat, lon = neigh["latitude"].mean(), neigh["longitude"].mean()

    print("=" * 78)
    print(f"STEP 1 - PLAN: pulling live/recent atmospheric data for Calgary "
          f"({lat:.3f}, {lon:.3f}) from Open-Meteo")
    raw = fetch_atmos(lat, lon)
    scored = hail_formation_index(raw)
    daily = daily_summary(scored)
    print(daily.tail(PAST_DAYS + FORECAST_DAYS).to_string(index=False))

    print("\nSTEP 2 - SCORE vs naive baseline ('flag any day with CAPE > 0 at all')")
    naive_flag_days = int((daily["cape_max"] > 0).sum())
    for thresh in [1.0, 2.5, 4.5]:
        n = int((daily["hfi_max"] >= thresh).sum())
        print(f"         HFI >= {thresh:>3}: {n} / {len(daily)} days flagged")
    agent_thresh = 2.5
    agent_flag_days = int((daily["hfi_max"] >= agent_thresh).sum())
    print(f"         Naive (CAPE>0) flags {naive_flag_days}/{len(daily)} days - "
          f"agent (HFI>={agent_thresh}) flags {agent_flag_days}/{len(daily)} days")

    print(f"\nSTEP 3 - REVISE: today's combined formation x exposure ranking (threshold={agent_thresh})")
    today_hfi = float(daily.iloc[-FORECAST_DAYS - 1]["hfi_max"]) if len(daily) > FORECAST_DAYS else float(daily["hfi_max"].iloc[-1])
    if DEMO_HFI_OVERRIDE is not None:
        print(f"         [DEMO MODE] overriding live HFI={today_hfi:.2f} with what-if value={DEMO_HFI_OVERRIDE}")
        today_hfi = DEMO_HFI_OVERRIDE
    today_band = band(today_hfi)
    print(f"         Latest observed-day HFI = {today_hfi:.2f} ({today_band})")

    neigh["track_weight"] = neigh["hail_track"].map(TRACK_WEIGHT)
    neigh["combined_risk"] = today_hfi * neigh["track_weight"]
    ranked = neigh.sort_values("combined_risk", ascending=False)
    top = ranked[["community_name", "hail_track", "combined_risk"]].head(10)
    print("\n         Top 10 neighbourhoods flagged today (formation x exposure):")
    print(top.to_string(index=False))

    plot(daily, ranked, agent_thresh, OUT_PNG)


def plot(daily: pd.DataFrame, ranked: pd.DataFrame, agent_thresh: float, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(17, 5))

    # 1. HFI time series with threshold lines
    axes[0].plot(pd.to_datetime(daily["date"]), daily["hfi_max"], marker="o", markersize=3)
    axes[0].axhline(1.0, color="gold", linestyle="--", linewidth=1, label="Marginal")
    axes[0].axhline(2.5, color="orange", linestyle="--", linewidth=1, label="Elevated")
    axes[0].axhline(4.5, color="red", linestyle="--", linewidth=1, label="High")
    axes[0].set_title("Daily max Hail Formation Index (HFI)")
    axes[0].set_ylabel("HFI")
    axes[0].legend(fontsize=8)
    axes[0].tick_params(axis="x", rotation=45)

    # 2. Naive baseline vs agent flagged-day counts
    naive_n = int((daily["cape_max"] > 0).sum())
    agent_n = int((daily["hfi_max"] >= agent_thresh).sum())
    axes[1].bar(["Naive\n(CAPE > 0)", f"Agent\n(HFI >= {agent_thresh})"], [naive_n, agent_n],
                color=["steelblue", "darkorange"])
    axes[1].set_ylabel("Days flagged")
    axes[1].set_title(f"Flagged days out of {len(daily)}")

    # 3. Top neighbourhoods today
    top = ranked.head(12).iloc[::-1]
    colors = top["hail_track"].map({"high": "crimson", "medium": "orange", "low": "gray"})
    axes[2].barh(top["community_name"], top["combined_risk"], color=colors)
    axes[2].set_xlabel("Combined risk (HFI x exposure weight)")
    axes[2].set_title("Top neighbourhoods flagged today")
    axes[2].tick_params(axis="y", labelsize=7)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"\nSaved chart -> {out_path}")


if __name__ == "__main__":
    main()
