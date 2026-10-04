"""ERA5 (CDS) season files -> per-day convective-environment features.

Inputs (scripts/request_era5.py): data/raw/era5/{sl,pl}_<YYYY>.nc (May-Sep), 2006-2022 + 2024 over
FEATURE_BOX. pl files are 12 UTC only (t, u, v, z, q on 925-250 hPa, no RH), so only 12 UTC is used, plus orography.nc. Output: one row per date (UTC date of the 12 UTC analysis,
= 06 MDT the same day) with box max and box mean over all 13x15 grid points of every index,
named `<index>_<max|mean>_12`. Written to data/processed/era5_daily.parquet.

Approximations (documented for the report):
- CAPE is ERA5 `cape`, which the IFS computes as a most-unstable-style CAPE; no parcel CAPE is
  recomputed (MetPy parcel CAPE ~6 ms/profile x 1.2 M profiles is too slow).
- SHIP uses `cape` as MUCAPE and the max mixing ratio in the lowest 100 hPa above ground
  (surface included) as the MU parcel mixing ratio.
- Wet-bulb is the isobaric psychrometric wet-bulb (Newton iteration, see indices.wet_bulb).
- Profiles start at the screen level (2 m T/q, 10 m wind) and use the 16 pressure levels (925-250 hPa) above
  ground; levels with p > sp or z < terrain are masked.
"""
import time

import numpy as np
import pandas as pd
import xarray as xr
from joblib import Parallel, delayed

from hailday import indices as ix
from hailday.config import MONTHS, PROCESSED, RAW

DIR = RAW / "era5"
OUT = PROCESSED / "era5_daily.parquet"
# Pressure levels were requested for 2006-2022 and 2024 only (12 UTC); 2023/2025 have no pl file.
YEARS = [*range(2006, 2023), 2024]
HOURS = (12,)  # 06 MDT forecast state; 18 UTC in sl files is ignored
CACHE = PROCESSED / "era5_years"


def _tidy(ds: xr.Dataset) -> xr.Dataset:
    ds = ds.drop_vars([v for v in ("number", "expver") if v in ds.coords and v not in ds.dims])
    if "expver" in ds.dims:  # ERA5/ERA5T mix in recent months: take the first non-missing
        ds = ds.bfill("expver").isel(expver=0)
    if "valid_time" in ds.dims:
        ds = ds.rename({"valid_time": "time"})
    return ds


def load_orography() -> xr.DataArray:
    o = _tidy(xr.open_dataset(DIR / "orography.nc"))
    return (o["z"].squeeze(drop=True) / ix.G).rename("orog").load()


def _open_pair(sl_path, pl_path) -> xr.Dataset:
    sl = _tidy(xr.open_dataset(sl_path))
    pl = _tidy(xr.open_dataset(pl_path)).sortby("pressure_level", ascending=False)  # bottom-up
    return xr.merge([sl, pl], join="inner").load()


def load_year(year: int) -> xr.Dataset:
    """Single-level and pressure-level fields for one May-Sep season at 12 UTC, merged on (time, lat, lon)."""
    ds = _open_pair(DIR / f"sl_{year}.nc", DIR / f"pl_{year}.nc")
    return ds.sel(time=ds["time"].dt.hour.isin(HOURS))


def load_month(year: int, month: int) -> xr.Dataset:
    """One month, from the per-year file (current layout) or a legacy per-month file pair."""
    legacy = DIR / f"sl_{year}_{month:02d}.nc", DIR / f"pl_{year}_{month:02d}.nc"
    if all(_complete(f) for f in legacy):
        return _open_pair(*legacy)
    ds = load_year(year)
    return ds.sel(time=ds["time"].dt.month == month)


def daily_indices(sl: xr.Dataset, pl: xr.Dataset, oro: xr.DataArray) -> pd.DataFrame:
    """Grid-point indices at each analysis hour, reduced to box max/mean per date and hour."""
    pl = pl.sortby("pressure_level", ascending=False)
    oro = oro.reindex_like(sl[["latitude", "longitude"]], method="nearest", tolerance=0.01)
    dims = ("time", "latitude", "longitude")
    a = lambda ds, n: ds[n].transpose(*dims).values.astype(np.float64)
    lv = lambda n: pl[n].transpose(*dims, "pressure_level").values.astype(np.float64)

    p = pl["pressure_level"].values.astype(np.float64)                  # hPa, (L,)
    h = oro.values.astype(np.float64)                                   # m, (lat, lon)
    sp = a(sl, "sp") / 100.0
    t2, d2, u10, v10 = a(sl, "t2m"), a(sl, "d2m"), a(sl, "u10"), a(sl, "v10")
    cape = np.nan_to_num(a(sl, "cape"), nan=0.0)
    t, u, v, q = lv("t"), lv("u"), lv("v"), lv("q")
    zagl = lv("z") / ix.G - h[None, :, :, None]
    ok = ix.valid_levels(p, sp, zagl)
    q2 = ix.q_from_dewpoint(d2, sp)
    pp = np.broadcast_to(p, t.shape)
    il = {lev: int(np.flatnonzero(p == lev)[0]) for lev in (925, 850, 700, 500)}

    out = {}
    out["cape"] = cape
    out["cin"] = np.nan_to_num(a(sl, "cin"), nan=0.0)          # NaN = no CIN (no buoyant parcel)
    for n in ("tcwv", "blh"):
        out[n] = a(sl, n)
    out["t2m"], out["d2m"] = t2 - 273.15, d2 - 273.15
    out["dpd2m"] = t2 - d2
    # ERA5 deg0l is documented as height above the surface already; no orography subtraction.
    out["deg0l"] = a(sl, "deg0l")

    # Winds: 0-6 km bulk shear from 10 m to 6 km AGL.
    uu, zu = ix.with_surface(u, zagl, ok, u10, 10.0)
    vv, _ = ix.with_surface(v, zagl, ok, v10, 10.0)
    out["shear06"] = ix.bulk_shear(u10, v10, ix.interp_at_height(uu, zu, 6000.0), ix.interp_at_height(vv, zu, 6000.0))
    u925, v925 = ix.at_level_or_lowest(u, ok, il[925]), ix.at_level_or_lowest(v, ok, il[925])
    out["shear925_500"] = ix.bulk_shear(u925, v925, u[..., il[500]], v[..., il[500]])
    out["wmaxshear"] = np.sqrt(2 * cape) * out["shear06"]
    for lev in (700, 500):
        out[f"u{lev}"], out[f"v{lev}"] = u[..., il[lev]], v[..., il[lev]]

    # Thermodynamics.
    z7, z5 = zagl[..., il[700]], zagl[..., il[500]]
    t7, t5 = t[..., il[700]], t[..., il[500]]
    out["lr75"] = ix.lapse_rate(t7, t5, z7, z5)
    out["t500"], out["t700"] = t5 - 273.15, t7 - 273.15
    out["q850"] = ix.at_level_or_lowest(q, ok, il[850]) * 1000.0
    low = ok & (pp >= sp[..., None] - 100.0)
    mr_low = np.where(low, ix.mixing_ratio(q), -np.inf).max(-1)
    out["mumr"] = np.maximum(mr_low, ix.mixing_ratio(q2)) * 1000.0
    td = ix.dewpoint_from_q(pp, q)
    for lev in (700, 500):
        out[f"dpd{lev}"] = t[..., il[lev]] - td[..., il[lev]]
    # K-index and Total Totals: native ERA5 fields when present, else from the pressure levels
    # using the standard fixed 850/700/500 hPa definition (ERA5 extrapolates 850 hPa below terrain).
    t8, td8, td7 = t[..., il[850]], td[..., il[850]], td[..., il[700]]
    out["kx"] = a(sl, "kx") if "kx" in sl else (t8 - t5) + (td8 - 273.15) - (t7 - td7)
    out["totalx"] = a(sl, "totalx") if "totalx" in sl else t8 + td8 - 2 * t5

    tt, zt = ix.with_surface(t, zagl, ok, t2, 2.0)
    for name, thr in (("frz_agl", 0.0), ("m10_agl", -10.0), ("m30_agl", -30.0)):
        out[name] = ix.crossing_height(tt, zt, 273.15 + thr)
    out["hgz_depth"] = out["m30_agl"] - out["m10_agl"]

    # Wet-bulb zero: only levels at or below 500 hPa are needed (WBZ is ~2-4 km AGL here).
    top = il[500] + 1
    tw = ix.wet_bulb(t[..., :top], q[..., :top], pp[..., :top])
    tw2 = ix.wet_bulb(t2, q2, sp)
    tww, zw = ix.with_surface(tw, zagl[..., :top], ok[..., :top], tw2, 2.0)
    out["wbz_agl"] = ix.crossing_height(tww, zw, 273.15)

    out["ship"] = ix.ship(cape, out["mumr"], out["lr75"], out["t500"], out["shear06"], out["frz_agl"])

    # Reduce over the box: one row per (date, hour), then widen by hour.
    times = pd.DatetimeIndex(sl["time"].values)
    rows = {"date": times.normalize(), "hour": times.hour}
    for n, arr in out.items():
        flat = arr.reshape(arr.shape[0], -1)
        rows[f"{n}_max"] = np.nanmax(flat, axis=1)
        rows[f"{n}_mean"] = np.nanmean(flat, axis=1)
    df = pd.DataFrame(rows)
    df = df[df["hour"].isin(HOURS)]
    wide = df.pivot(index="date", columns="hour")
    wide.columns = [f"{c}_{hr}" for c, hr in wide.columns]
    return wide.reset_index()


def _complete(path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def available_years() -> tuple[list[int], list[int]]:
    """Years whose sl and pl season files have both landed, and those still missing."""
    have = [y for y in YEARS if _complete(DIR / f"sl_{y}.nc") and _complete(DIR / f"pl_{y}.nc")]
    return have, [y for y in YEARS if y not in have]


def _one(year, oro):
    """Per-year features, cached as parquet and recomputed only when an input file is newer."""
    out = CACHE / f"{year}.parquet"
    src = max((DIR / f"{k}_{year}.nc").stat().st_mtime for k in ("sl", "pl"))
    if out.exists() and out.stat().st_mtime > src:
        return pd.read_parquet(out)
    ds = load_year(year)
    df = daily_indices(ds, ds, oro)
    df.to_parquet(out, index=False)
    return df


def build_all(n_jobs: int = -1, verbose: bool = True) -> pd.DataFrame:
    """Rebuild era5_daily.parquet from every year whose sl+pl pair has landed (safe to re-run as years arrive)."""
    have, missing = available_years()
    if not have:
        raise FileNotFoundError(f"no complete ERA5 year pairs (sl_<YYYY>.nc + pl_<YYYY>.nc) in {DIR}")
    t0 = time.time()
    oro = load_orography()
    CACHE.mkdir(parents=True, exist_ok=True)
    parts = Parallel(n_jobs=n_jobs)(delayed(_one)(y, oro) for y in have)
    df = pd.concat(parts, ignore_index=True).sort_values("date").reset_index(drop=True)
    df = df[df["date"].dt.month.isin(list(MONTHS))]
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    if verbose:
        print(f"era5: {len(have)} years -> {len(df)} days x {df.shape[1] - 1} cols in {time.time() - t0:.1f}s")
        if missing:
            print(f"era5: years missing: {missing}")
    return df


if __name__ == "__main__":
    build_all()
