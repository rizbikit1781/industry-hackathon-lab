"""Download NOAA MRMS MESH daily maxima (May–Sep 2020–2025) and crop to the feature box.

Output: data/processed/mesh_daily.npz with
  dates: local MDT dates (datetime64[D])
  mesh:  int16 [day, lat, lon], mm; -1 = covered, no hail; -3 = no radar coverage; -9 = file missing
  lats, lons: 1-D cell centres
"""
import gzip
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pygrib
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hailday.config import (  # noqa: E402
    FEATURE_BOX, MESH_IASTATE_DIR, MESH_OUTAGE, MESH_URL, MESH_YEARS, MONTHS, PROCESSED, RAW,
)

CACHE = RAW / "mesh"
MISSING = -9


def local_days():
    for y in MESH_YEARS:
        d = date(y, MONTHS.start, 1)
        while d.month in MONTHS:
            yield d
            d += timedelta(days=1)


def fetch(day: date) -> Path | None:
    """File stamped 06 UTC on day+1 holds the 24 h max for MDT day `day`."""
    stamp = day + timedelta(days=1)
    out = CACHE / f"{stamp:%Y%m%d}.grib2.gz"
    if out.exists() and out.stat().st_size > 0:
        return out
    for url in (MESH_URL.format(d=stamp), iastate_url(stamp)):
        if url is None:
            continue
        try:
            r = requests.get(url, timeout=60)
        except requests.RequestException:
            continue
        if r.ok and r.content[:2] == b"\x1f\x8b":
            out.write_bytes(r.content)
            return out
    return None


def iastate_url(stamp: date) -> str | None:
    """Earliest file in the Iowa State directory for `stamp` (names carry irregular minutes)."""
    base = MESH_IASTATE_DIR.format(d=stamp)
    try:
        html = requests.get(base, timeout=60).text
    except requests.RequestException:
        return None
    names = sorted(set(re.findall(r'href="([^"]*1440min[^"]*\.grib2\.gz)"', html)))
    return base + names[0] if names else None


def crop(path: Path):
    lat0, lat1, lon0, lon1 = FEATURE_BOX
    with tempfile.NamedTemporaryFile(suffix=".grib2") as tmp:
        tmp.write(gzip.decompress(path.read_bytes()))
        tmp.flush()
        grb = pygrib.open(tmp.name).message(1)
        vals, lats, lons = grb.data(lat1=lat0, lat2=lat1, lon1=lon0 % 360, lon2=lon1 % 360)
    return vals, lats, lons


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    days = list(local_days())
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(fetch, days))
    got = sum(p is not None for p in paths)
    print(f"downloaded {got}/{len(days)} days")

    first = next(p for p in paths if p is not None)
    _, lats, lons = crop(first)
    lat_1d, lon_1d = lats[:, 0], lons[0, :] - 360
    cube = np.full((len(days), len(lat_1d), len(lon_1d)), MISSING, dtype=np.int16)
    for i, (d, p) in enumerate(zip(days, paths)):
        if p is None or MESH_OUTAGE[0] <= d <= MESH_OUTAGE[1]:
            continue
        vals, _, _ = crop(p)
        cube[i] = np.rint(np.asarray(vals, dtype=float)).astype(np.int16)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        PROCESSED / "mesh_daily.npz",
        dates=np.array(days, dtype="datetime64[D]"), mesh=cube, lats=lat_1d, lons=lon_1d,
    )
    valid = (cube != MISSING).any(axis=(1, 2)).sum()
    print(f"grid {cube.shape[1]}x{cube.shape[2]}, valid days {valid}, outage-masked {MESH_OUTAGE}")
    i = days.index(date(2024, 8, 5))
    print(f"2024-08-05 max MESH in box: {cube[i].max()} mm")


if __name__ == "__main__":
    main()
