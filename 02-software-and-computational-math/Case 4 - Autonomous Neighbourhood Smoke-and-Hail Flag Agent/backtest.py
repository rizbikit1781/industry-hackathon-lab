"""Historical backtest: did the atmosphere really look hail-favorable before
the actual 5 August 2024 Calgary hailstorm (~$3.3B insured loss, ~130,000
claims, north-city/airport corridor)?

Open-Meteo's forecast API only keeps ~3 months of CAPE history, so it cannot
reach back to 2024 (see agent.py's docstring). This script instead pulls
REAL radiosonde (weather balloon) observations from the Iowa State Mesonet
RAOB archive - the same raw data meteorologists actually used that week -
for Stony Plain/Edmonton (station CWSE, WMO 71119), the nearest station to
Calgary that regularly launches balloons (~280 km north; Calgary itself has
no upper-air station, which is itself a useful fact for your pitch: this is
exactly the kind of "nearest station" data gap your agent already has to
reason around for its ground-level AQHI readings).

For each sounding we compute REAL values (not the live agent's simplified
proxy terms) with MetPy's standard atmospheric-science routines:
  - surface-based CAPE/CIN (parcel theory, not a lookup)
  - 700-500 hPa lapse rate (from actual reported heights)
  - 850-500 hPa bulk wind shear (from actual reported winds)
  - 500 hPa temperature
  - near-surface mixing ratio

...then run the exact same Hail Formation Index (HFI) formula used in
agent.py, to check whether the formula - fed real pre-storm atmospheric
data - would have flagged 5 Aug 2024 and NOT flagged an ordinary, storm-free
summer day.

HYBRID "MODIFIED SOUNDING" METHOD
----------------------------------
A raw 06Z (6am MDT) balloon sounding is taken *before* the day's heating, so
CAPE reads near zero every day - that's not a bug, mornings are always
stable. A raw 00Z (6pm MDT) sounding is taken *after* a storm has already
fired, so on event days it often reads artificially LOW too, because the
storm has already consumed (released) the instability that caused it. Real
forecasters handle this with a "modified/forecast sounding": take the
morning profile aloft (which is a good proxy for the synoptic-scale air
mass overhead) and replace just the near-surface temperature/dewpoint with
the day's *actual observed* afternoon surface heating - the one quantity
that is genuinely local and cannot come from a balloon 280 km away. We
fetch that real surface heating/moisture from Open-Meteo's ERA5 historical
archive for Calgary's own coordinates (confirmed to carry real temperature
and dewpoint that far back, even though it lacks derived CAPE), then
recompute CAPE on this hybrid profile with MetPy. This is standard
operational practice for exactly this "no upper-air station nearby"
situation, and lets the surface term in HFI reflect Calgary, not Edmonton.
"""
from __future__ import annotations

from pathlib import Path

import metpy.calc as mpcalc
import numpy as np
import pandas as pd
import requests
from metpy.units import units

STATION = "CWSE"  # Stony Plain / Edmonton, AB - nearest regular radiosonde site to Calgary
CALGARY_LAT, CALGARY_LON = 51.05, -114.07
OUT_PNG = Path(__file__).parent / "backtest_results.png"

# (label, calendar date, morning-sounding ISO timestamp UTC (06Z = ~midnight MDT
# .. actually 12Z = ~6am MDT, used for the profile ALOFT), is this the real event?)
CASES = [
    ("5 Aug 2024 - day of the storm", "2024-08-05", "2024-08-05T12:00Z", True),
    ("4 Aug 2024 - day before", "2024-08-04", "2024-08-04T12:00Z", False),
    ("15 Jul 2024 - ordinary summer day", "2024-07-15", "2024-07-15T12:00Z", False),
    ("2 Sep 2024 - ordinary summer day", "2024-09-02", "2024-09-02T12:00Z", False),
]


def fetch_calgary_afternoon_surface(date: str) -> dict:
    """Real ERA5 reanalysis surface temp/dewpoint for Calgary (archive API keeps
    these far back, unlike the derived CAPE/lifted_index fields). Returns the
    day's peak-heating hour values to modify the morning balloon profile with."""
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": CALGARY_LAT, "longitude": CALGARY_LON,
            "start_date": date, "end_date": date,
            "hourly": "temperature_2m,dew_point_2m",
            "timezone": "America/Edmonton",
        },
        timeout=30,
    )
    r.raise_for_status()
    hourly = r.json()["hourly"]
    temps = hourly["temperature_2m"]
    dews = hourly["dew_point_2m"]
    i_max = int(np.argmax(temps))
    return {"surface_temp_c": temps[i_max], "surface_dewpoint_c": dews[i_max], "hour": hourly["time"][i_max]}


def fetch_profile(ts: str) -> pd.DataFrame:
    r = requests.get(
        "https://mesonet.agron.iastate.edu/json/raob.py",
        params={"station": STATION, "ts": ts},
        timeout=30,
    )
    r.raise_for_status()
    profile = r.json()["profiles"][0]["profile"]
    df = pd.DataFrame(profile).rename(
        columns={"pres": "pressure_hpa", "hght": "height_m", "tmpc": "temp_c", "dwpc": "dewpoint_c",
                 "drct": "wind_dir", "sknt": "wind_kt"}
    )
    return df.sort_values("pressure_hpa", ascending=False).reset_index(drop=True)


def nearest_level(df: pd.DataFrame, target_hpa: float, col: str):
    sub = df.dropna(subset=[col])
    idx = (sub["pressure_hpa"] - target_hpa).abs().idxmin()
    return sub.loc[idx]


def build_modified_profile(df: pd.DataFrame, surface: dict) -> pd.DataFrame:
    """Replace the balloon's own (pre-heating, 6am) surface temp/dewpoint with
    Calgary's real observed afternoon peak-heating values, keeping everything
    aloft from the actual regional sounding unchanged. Levels at/below the new
    warmer surface are dropped (they'd be unphysical - cooler air sitting below
    a warmer surface), matching the standard manual "modified sounding" technique."""
    thermo = df.dropna(subset=["temp_c", "dewpoint_c"]).reset_index(drop=True)
    sfc_row = thermo.iloc[0].copy()
    sfc_row["temp_c"] = surface["surface_temp_c"]
    sfc_row["dewpoint_c"] = surface["surface_dewpoint_c"]
    aloft = thermo[thermo["temp_c"] < surface["surface_temp_c"]].reset_index(drop=True)
    modified = pd.concat([pd.DataFrame([sfc_row]), aloft], ignore_index=True)
    return modified.sort_values("pressure_hpa", ascending=False).reset_index(drop=True)


def compute_real_parameters(df: pd.DataFrame, surface: dict | None = None) -> dict:
    lapse_source = df  # lapse rate / shear / T500 always come from the real regional sounding aloft
    thermo = df.dropna(subset=["temp_c", "dewpoint_c"]).reset_index(drop=True)
    if surface is not None:
        thermo = build_modified_profile(df, surface)
    p = thermo["pressure_hpa"].to_numpy() * units.hPa
    t = thermo["temp_c"].to_numpy() * units.degC
    td = thermo["dewpoint_c"].to_numpy() * units.degC

    try:
        sbcape, sbcin = mpcalc.surface_based_cape_cin(p, t, td)
        cape_val = float(sbcape.to("J/kg").magnitude)
    except Exception as exc:  # pragma: no cover - sounding data can be too sparse near the surface
        cape_val = float("nan")
        print(f"         (CAPE calc failed: {exc})")

    row700 = nearest_level(df, 700, "temp_c")
    row500 = nearest_level(df, 500, "temp_c")
    lapse = (row700["temp_c"] - row500["temp_c"]) / ((row500["height_m"] - row700["height_m"]) / 1000.0)

    w850 = nearest_level(df, 850, "wind_kt")
    w500 = nearest_level(df, 500, "wind_kt")
    u850, v850 = mpcalc.wind_components(w850["wind_kt"] * units.knot, w850["wind_dir"] * units.deg)
    u500, v500 = mpcalc.wind_components(w500["wind_kt"] * units.knot, w500["wind_dir"] * units.deg)
    shear_ms = float(np.hypot((u500 - u850).to("m/s").magnitude, (v500 - v850).to("m/s").magnitude))

    sfc = thermo.iloc[0]
    e = 6.112 * np.exp(17.67 * sfc["dewpoint_c"] / (sfc["dewpoint_c"] + 243.5))
    mixr = 621.97 * e / (sfc["pressure_hpa"] - e)

    return {
        "cape": cape_val,
        "lapse_700_500": float(lapse),
        "t500": float(row500["temp_c"]),
        "shear_ms": shear_ms,
        "mixr_gkg": float(mixr),
    }


def hfi_from_params(p: dict) -> float:
    """Same formula as agent.py's hail_formation_index(), applied to real sounding-derived inputs."""
    cape_term = np.clip(p["cape"] / 1500, 0, 2.0)
    shear_term = np.clip(p["shear_ms"] / 20, 0.3, 1.5)
    cold_aloft_term = np.clip((-5 - p["t500"]) / 10, 0.3, 2.0)
    moisture_term = np.clip(p["mixr_gkg"] / 12, 0.5, 1.3)
    return float(cape_term * shear_term * cold_aloft_term * moisture_term)


def band(hfi: float) -> str:
    if hfi < 1.0:
        return "Low"
    if hfi < 2.5:
        return "Marginal"
    if hfi < 4.5:
        return "Elevated"
    return "High"


def main() -> None:
    print("=" * 78)
    print(f"HISTORICAL BACKTEST - hybrid soundings: regional balloon ({STATION}, Stony Plain/Edmonton) "
          "aloft + Calgary's own real observed afternoon surface heating")
    print()
    rows = []
    for label, date, ts, is_event in CASES:
        try:
            df = fetch_profile(ts)
            surface = fetch_calgary_afternoon_surface(date)
            params = compute_real_parameters(df, surface=surface)
            hfi = hfi_from_params(params)
            rows.append({"label": label, "is_event": is_event, **params, "hfi": hfi, "band": band(hfi)})
            print(f"{label:38s} sfc={surface['surface_temp_c']:>4.1f}C/{surface['surface_dewpoint_c']:>4.1f}C "
                  f"(Calgary {surface['hour']})  CAPE={params['cape']:>7.0f} J/kg  shear={params['shear_ms']:>5.1f} m/s  "
                  f"T500={params['t500']:>6.1f}C  lapse={params['lapse_700_500']:>4.1f} C/km  "
                  f"HFI={hfi:>5.2f} ({band(hfi)})")
        except Exception as exc:
            print(f"{label:38s} FAILED to fetch/compute: {exc}")

    result = pd.DataFrame(rows)
    if result.empty:
        print("\nNo soundings could be retrieved - check network access to mesonet.agron.iastate.edu.")
        return

    event_hfi = result.loc[result["is_event"], "hfi"]
    other_hfi = result.loc[~result["is_event"], "hfi"]
    print("\nRESULT:")
    if len(event_hfi) and event_hfi.iloc[0] >= 2.5 and (other_hfi < 2.5).all():
        print("  The HFI formula, fed REAL pre-storm radiosonde data, flags 5 Aug 2024 as "
          f"{result.loc[result['is_event'], 'band'].iloc[0]} while every ordinary day tested stays below "
          "the Elevated threshold. This is a genuine historical validation of the live agent's methodology.")
    else:
        print("  Mixed result - see table above. Report this honestly: the nearest sounding is ~280 km from "
              "Calgary, which is a real spatial-representativeness limitation worth stating in your pitch.")

    plot(result, OUT_PNG)


def plot(result: pd.DataFrame, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["crimson" if e else "steelblue" for e in result["is_event"]]
    ax.bar(result["label"], result["hfi"], color=colors)
    ax.axhline(1.0, color="gold", linestyle="--", linewidth=1, label="Marginal")
    ax.axhline(2.5, color="orange", linestyle="--", linewidth=1, label="Elevated")
    ax.axhline(4.5, color="red", linestyle="--", linewidth=1, label="High")
    ax.set_ylabel("HFI (from real radiosonde data)")
    ax.set_title("Backtest: HFI on the actual 5 Aug 2024 storm vs. ordinary days")
    ax.tick_params(axis="x", rotation=20, labelsize=8)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"\nSaved chart -> {out_path}")


if __name__ == "__main__":
    main()
