"""Download ERA5 (Copernicus CDS) for the feature box, one request per dataset-year (May–Sep).

Needs ~/.cdsapirc (url + Personal Access Token) and both dataset licences accepted.
All variables are instantaneous, so each request returns one NetCDF (no zip).
CDS limits queued requests per dataset, so at most PER_DATASET run at once and throttled
submissions are retried. Queue time (~10-20 min) is per request, so requests are as large as CDS
allows: single levels one per year; pressure levels two per year (May-Jul, Aug-Sep), merged.
Output: data/raw/era5/{sl,pl}_<YYYY>.nc  (+ orography.nc once). Re-runs skip finished files.
"""
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cdsapi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hailday.config import FEATURE_BOX, MONTHS, RAW  # noqa: E402

OUT = RAW / "era5"
YEARS = [*range(2006, 2023), 2024]  # training summers + the 5 Aug 2024 demo (trimmed for CDS queue time)
HOURS = ["12:00"]  # 06 MDT forecast state (18 UTC noon update dropped: CDS queue ~20 min per request)
lat0, lat1, lon0, lon1 = FEATURE_BOX
AREA = [lat1, lon0, lat0, lon1]  # N, W, S, E
DAYS = [f"{d:02d}" for d in range(1, 32)]
PER_DATASET = 2
SLOTS = {"sl": threading.Semaphore(PER_DATASET), "pl": threading.Semaphore(PER_DATASET)}

SINGLE = [
    "convective_available_potential_energy", "convective_inhibition", "k_index", "total_totals_index",
    "zero_degree_level", "total_column_water_vapour", "boundary_layer_height", "2m_temperature",
    "2m_dewpoint_temperature", "10m_u_component_of_wind", "10m_v_component_of_wind", "surface_pressure",
]
PRESSURE = ["temperature", "u_component_of_wind", "v_component_of_wind", "geopotential", "specific_humidity"]
# 1000-950 hPa are below ground across nearly all of the box; 16 levels keep a year in one request.
LEVELS = ["925", "900", "875", "850", "825", "800", "775", "750", "700", "650", "600", "550", "500",
          "400", "300", "250"]


PL_CHUNKS = [(5, 6, 7), (8, 9)]  # NetCDF requests >~10k items are rejected; ~7.4k and ~4.9k pass


def request(kind: str, year: int, months: tuple | None = None):
    tag = "" if months is None else "_" + "".join(f"{m:02d}" for m in months)
    target = OUT / f"{kind}_{year}{tag}.nc"
    if target.exists() and target.stat().st_size > 0:
        return target, "cached"
    months = list(MONTHS) if months is None else list(months)
    req = {"product_type": ["reanalysis"], "year": [str(year)], "month": [f"{m:02d}" for m in months], "day": DAYS,
           "time": HOURS, "area": AREA, "data_format": "netcdf", "download_format": "unarchived"}
    if kind == "sl":
        dataset, req["variable"] = "reanalysis-era5-single-levels", SINGLE
    else:
        dataset, req["variable"], req["pressure_level"] = "reanalysis-era5-pressure-levels", PRESSURE, LEVELS
    tmp = target.with_suffix(".part")
    with SLOTS[kind]:
        while True:
            try:
                cdsapi.Client(quiet=True).retrieve(dataset, req, str(tmp))
                break
            except Exception as e:
                if "temporarily limited" not in str(e):
                    raise
                time.sleep(60)
    if zipfile.is_zipfile(tmp):
        raise RuntimeError(f"{target.name}: CDS returned a zip; split step types")
    tmp.rename(target)
    return target, "downloaded"


def pressure_year(year: int):
    """Fetch the five pressure-level months for a year, then merge them into pl_<year>.nc."""
    import xarray as xr

    target = OUT / f"pl_{year}.nc"
    if target.exists() and target.stat().st_size > 0:
        return target, "cached"
    parts = [request("pl", year, chunk)[0] for chunk in PL_CHUNKS]
    dss = [xr.open_dataset(pt).load() for pt in parts]  # small files; no dask needed
    xr.concat(dss, dim="valid_time").sortby("valid_time").to_netcdf(target.with_suffix(".part"))
    for d in dss:
        d.close()
    target.with_suffix(".part").rename(target)
    for part in parts:
        part.unlink()
    return target, "downloaded+merged"


def orography():
    target = OUT / "orography.nc"
    if not target.exists():
        cdsapi.Client(quiet=True).retrieve("reanalysis-era5-single-levels", {
            "product_type": ["reanalysis"], "variable": ["geopotential"], "year": ["2024"], "month": ["07"],
            "day": ["01"], "time": ["00:00"], "area": AREA, "data_format": "netcdf",
            "download_format": "unarchived"}, str(target))
    return target


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    orography()
    # Most-recent-first for the 5 Aug 2024 demo, then label years.
    order = sorted(YEARS, key=lambda y: (y != 2024, -y))
    jobs = [(k, y) for y in order for k in ("pl", "sl")]  # interleave so both datasets queue
    done = failed = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(request if k == "sl" else lambda _k, y: pressure_year(y), k, y): (k, y)
                for k, y in jobs}
        for f in as_completed(futs):
            try:
                path, how = f.result()
                done += 1
                print(f"[{done + failed}/{len(jobs)}] {path.name} {how}", flush=True)
            except Exception as e:  # keep going; re-run picks up the gaps
                failed += 1
                print(f"[{done + failed}/{len(jobs)}] FAIL {futs[f]}: {str(e).splitlines()[-1][:160]}", flush=True)
    print(f"done {done}, failed {failed}")
