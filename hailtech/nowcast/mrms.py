"""Fetch, cache and crop NOAA MRMS 2-min products from the public AWS bucket.

Files: https://noaa-mrms-pds.s3.amazonaws.com/CONUS/<PRODUCT>/<YYYYMMDD>/MRMS_<PRODUCT>_<YYYYMMDD>-<HHMMSS>.grib2.gz
The seconds in the filename vary (e.g. -013041), so files are found through the bucket listing.

Values: -999/-99 missing, -3 out of coverage -> NaN; -1 / 0 "no hail / no echo" -> 0 (hail products).
Each frame records `valid_time` (from the filename) and `available_time` = valid_time + LATENCY, the
earliest moment a real-time system could have used it (files land on S3 ~50 s after valid time).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com"
# Shared absolute cache (gitignored in the main repo), so every worktree reuses the downloads.
CACHE = Path(os.environ.get("HAILDAY_MRMS_CACHE", "/Users/caelan/code/hackathon/hailday/data/raw/mrms"))
LATENCY = timedelta(minutes=2)
CADENCE_MIN = 2

# (lat_min, lat_max, lon_min, lon_max): Calgary plus ~30 km upstream (W/NW) for tracking.
NOWCAST_BOX = (50.5, 51.7, -115.2, -113.3)

PRODUCTS = {
    "mesh": "MESH_00.50",                              # mm
    "posh": "POSH_00.50",                              # %
    "et50": "EchoTop_50_00.50",                        # km
    "refl": "MergedReflectivityQCComposite_00.50",     # dBZ
}
HAIL_PRODUCTS = {"mesh", "posh", "et50"}
_KEY_RE = re.compile(r"_(\d{8})-(\d{6})\.grib2\.gz$")


def list_keys(product: str, day: pd.Timestamp) -> list[tuple[pd.Timestamp, str]]:
    """[(valid_time UTC, key)] for one UTC day. Listing cached as JSON (past days never change)."""
    ymd = f"{day:%Y%m%d}"
    cache = CACHE / product / ymd / "_listing.json"
    if cache.exists():
        keys = json.loads(cache.read_text())
    else:
        keys, token = [], None
        while True:
            params = {"list-type": "2", "prefix": f"CONUS/{product}/{ymd}/"}
            if token:
                params["continuation-token"] = token
            r = requests.get(BUCKET + "/", params=params, timeout=60)
            r.raise_for_status()
            keys += re.findall(r"<Key>([^<]+)</Key>", r.text)
            m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", r.text)
            if not m:
                break
            token = m.group(1)
        cache.parent.mkdir(parents=True, exist_ok=True)
        if day.normalize() < pd.Timestamp.now(tz="UTC").tz_localize(None).normalize():
            cache.write_text(json.dumps(keys))
    out = []
    for k in keys:
        m = _KEY_RE.search(k)
        if m:
            out.append((pd.Timestamp(m.group(1) + m.group(2)), k))
    return out


def fetch(key: str) -> Path:
    """Download one .grib2.gz into the cache (idempotent)."""
    _, product, ymd, name = key.split("/")
    path = CACHE / product / ymd / name
    if path.exists() and path.stat().st_size > 100:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            r = requests.get(f"{BUCKET}/{key}", timeout=60)
            r.raise_for_status()
            if r.content[:2] != b"\x1f\x8b":
                raise ValueError(f"not gzip: {key}")
            tmp = path.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(path)
            return path
        except Exception:
            if attempt == 2:
                raise
    return path


def _crop_index(grb, box):
    lat0 = grb["latitudeOfFirstGridPointInDegrees"]
    lon0 = grb["longitudeOfFirstGridPointInDegrees"]
    dlat = grb["jDirectionIncrementInDegrees"]
    dlon = grb["iDirectionIncrementInDegrees"]
    lat_min, lat_max, lon_min, lon_max = box
    i0 = int(round((lat0 - lat_max) / dlat))
    i1 = int(round((lat0 - lat_min) / dlat)) + 1
    j0 = int(round((lon_min % 360 - lon0) / dlon))
    j1 = int(round((lon_max % 360 - lon0) / dlon)) + 1
    lats = lat0 - dlat * np.arange(i0, i1)
    lons = lon0 + dlon * np.arange(j0, j1) - 360.0
    return slice(i0, i1), slice(j0, j1), lats, lons


def read_crop(path: Path, box=NOWCAST_BOX, hail=True):
    """-> (float32 [y, x] with NaN for missing/no coverage, lats desc, lons). Cropped result cached as .npy."""
    tag = "_".join(f"{v:g}" for v in box)
    npy = path.with_name(path.name.replace(".grib2.gz", f".crop_{tag}.npz"))
    if npy.exists():
        z = np.load(npy)
        return z["a"], z["lats"], z["lons"]
    import pygrib  # local import: tests do not need it

    raw = gzip.decompress(path.read_bytes())
    with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as f:
        f.write(raw)
        tmp = f.name
    try:
        g = pygrib.open(tmp)
        grb = g[1]
        si, sj, lats, lons = _crop_index(grb, box)
        a = np.asarray(grb.values[si, sj], dtype=np.float32)
        g.close()
    finally:
        os.unlink(tmp)
    if hail:
        a[a <= -2] = np.nan            # -3 no coverage, -99 / -999 missing
        a[a < 0] = 0.0                 # -1 = covered, no hail
    else:
        a[a <= -90] = np.nan           # reflectivity: -99 no coverage, -999 missing
    np.savez_compressed(npy, a=a, lats=lats.astype(np.float64), lons=lons.astype(np.float64))
    return a, lats, lons


@dataclass
class Frames:
    """Aligned MRMS frames. Arrays are [t, y, x] float32, NaN = missing. Times are naive UTC."""
    valid_times: pd.DatetimeIndex
    lats: np.ndarray
    lons: np.ndarray
    fields: dict = field(default_factory=dict)
    latency: timedelta = LATENCY

    @property
    def available_times(self) -> pd.DatetimeIndex:
        return self.valid_times + self.latency

    def __getitem__(self, name):
        return self.fields[name]

    def upto(self, k: int) -> "Frames":
        """Frames 0..k-1 only (views). Used to make the no-future-data guarantee structural."""
        return Frames(self.valid_times[:k], self.lats, self.lons,
                      {n: a[:k] for n, a in self.fields.items()}, self.latency)


def load_window(start, end, products=tuple(PRODUCTS), box=NOWCAST_BOX, workers=8, verbose=True) -> Frames:
    """Fetch + crop every 2-min frame with valid time in [start, end] (naive UTC) and align products.

    Times are aligned on the MESH frames (rounded to the 2-min cadence). A product missing at a frame
    is NaN for that frame.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    days = pd.date_range(start.normalize(), end.normalize(), freq="D")
    per_product = {}
    for name in products:
        keys = [kv for d in days for kv in list_keys(PRODUCTS[name], d) if start <= kv[0] <= end]
        per_product[name] = {t.round(f"{CADENCE_MIN}min"): k for t, k in keys}

    times = sorted(per_product["mesh"])
    tset = set(times)
    jobs = [(name, t, k) for name, d in per_product.items() for t, k in d.items() if t in tset]

    def work(job):
        name, t, k = job
        return name, t, read_crop(fetch(k), box, hail=name in HAIL_PRODUCTS)

    results = {}
    with ThreadPoolExecutor(workers) as ex:
        for n, (name, t, out) in enumerate(ex.map(work, jobs)):
            results[(name, t)] = out
            if verbose and n % 100 == 0:
                print(f"  mrms {n}/{len(jobs)}", flush=True)
    any_out = next(iter(results.values()))
    lats, lons = any_out[1], any_out[2]
    shape = (len(times), len(lats), len(lons))
    fields = {}
    for name in products:
        arr = np.full(shape, np.nan, dtype=np.float32)
        for i, t in enumerate(times):
            if (name, t) in results:
                arr[i] = results[(name, t)][0]
        fields[name] = arr
    return Frames(pd.DatetimeIndex(times), lats, lons, fields)
