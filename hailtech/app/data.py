"""File loaders for the dashboard. Every loader returns None (never raises) when its file is missing or unreadable.

Resolution order for a relative path under data/processed:
  1. the real file in data/processed/
  2. the fixture in app/fixtures/, only when HAILDAY_FIXTURES=1
Pages call `used_fixtures()` to label fixture-backed panels.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

APP = Path(__file__).resolve().parent
ROOT = APP.parent
DATA = ROOT / "data"
PROCESSED = Path(os.environ.get("HAILDAY_PROCESSED", DATA / "processed"))
FIXTURES = APP / "fixtures"
ASSETS_CSV = DATA / "assets.csv"
COMMUNITIES_CSV = DATA / "neighbourhoods_hail_scenario.csv"
SOURCES = ("era5", "openmeteo")


def fixtures_enabled() -> bool:
    return os.environ.get("HAILDAY_FIXTURES", "").strip().lower() in ("1", "true", "yes")


def _fixture_log() -> set:
    return st.session_state.setdefault("_fixture_files", set())


def used_fixtures() -> list[str]:
    return sorted(_fixture_log())


def resolve(rel: str) -> Path | None:
    real = PROCESSED / rel
    if real.is_file():
        return real
    if fixtures_enabled():
        fx = FIXTURES / rel
        if fx.is_file():
            _fixture_log().add(rel)
            return fx
    return None


def is_fixture(path: Path | None) -> bool:
    return path is not None and FIXTURES in path.parents


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


# ---------- cached raw readers (keyed on path + mtime so a re-run pipeline shows up without restart) ----------

@st.cache_data(show_spinner=False)
def _read_json(path: str, _mt: float):
    with open(path) as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def _read_parquet(path: str, _mt: float):
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def _read_csv(path: str, _mt: float):
    return pd.read_csv(path)


@st.cache_resource(show_spinner=False, max_entries=4)
def _read_npz(path: str, _mt: float) -> dict:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def _safe(fn, p: Path | None):
    if p is None:
        return None
    try:
        return fn(str(p), _mtime(p))
    except Exception:
        return None


def load_json(rel: str):
    return _safe(_read_json, resolve(rel))


# ---------- public loaders ----------

def available_sources(prefix: str, ext: str) -> list[str]:
    return [s for s in SOURCES if resolve(f"{prefix}_{s}.{ext}") is not None]


def backtest(source: str):
    d = load_json(f"backtest_{source}.json")
    return d if isinstance(d, dict) else None


def oof(source: str):
    return _safe(_read_parquet, resolve(f"oof_{source}.parquet"))


def dollar_backtest(source: str):
    d = load_json(f"dollar_backtest_{source}.json")
    return d if isinstance(d, dict) and isinstance(d.get("rows"), list) else None


def value_curve(source: str):
    d = load_json(f"value_curve_{source}.json")
    return d if isinstance(d, dict) and isinstance(d.get("curves"), dict) and d.get("alphas") else None


def _dated(dirname: str, pattern: str, strip_prefix: str = "", strip_suffix: str = ".json") -> list[str]:
    names = set()
    dirs = [PROCESSED / dirname] + ([FIXTURES / dirname] if fixtures_enabled() else [])
    for d in dirs:
        if d.is_dir():
            for p in d.glob(pattern):
                n = p.name
                if n.startswith(strip_prefix) and n.endswith(strip_suffix):
                    core = n[len(strip_prefix):len(n) - len(strip_suffix)]
                    if len(core) == 10 and core[4] == "-" and core[7] == "-":
                        names.add(core)
    return sorted(names, reverse=True)


def score_dates() -> list[str]:
    return _dated("scores", "*.json")


def scores(date: str):
    d = load_json(f"scores/{date}.json")
    if not isinstance(d, dict) or "p_day" not in d:
        return None
    return d


def replay_dates() -> list[str]:
    return _dated("nowcast", "replay_*.json", strip_prefix="replay_")


def replay(date: str):
    rel = f"nowcast/replay_{date}.json"
    p = resolve(rel)
    d = _safe(_read_json, p)
    if not isinstance(d, dict) or not d.get("issue_times"):
        return None, None
    fields = None
    grid = d.get("grid") or {}
    npz_name = grid.get("npz") or f"replay_{date}_fields.npz"
    cand = [p.parent / Path(npz_name).name, p.parent / npz_name]
    for c in cand:
        if c.is_file():
            fields = _safe(_read_npz, c)
            break
    return d, fields


def assets_csv():
    return _safe(_read_csv, ASSETS_CSV if ASSETS_CSV.is_file() else None)


def communities():
    return _safe(_read_csv, COMMUNITIES_CSV if COMMUNITIES_CSV.is_file() else None)


@st.cache_data(show_spinner=False)
def _exposure_from_hitrates(path: str, _mt: float, comm_path: str, _cmt: float):
    z = np.load(path)
    lats, lons, p = z["lats"], z["lons"], z["p_hit_30"]
    c = pd.read_csv(comm_path)
    iy = np.abs(lats[None, :] - c["latitude"].to_numpy()[:, None]).argmin(1)
    ix = np.abs(lons[None, :] - c["longitude"].to_numpy()[:, None]).argmin(1)
    raw = p[iy, ix]
    lo, hi = float(np.nanmin(raw)), float(np.nanmax(raw))
    expo = (raw - lo) / (hi - lo) if hi > lo else np.zeros_like(raw)
    return pd.DataFrame({"community_name": c["community_name"], "latitude": c["latitude"],
                         "longitude": c["longitude"], "exposure": expo, "p_hit_30": raw})


def exposure():
    """Returns (df, how) where how describes the source, or (None, None)."""
    p = resolve("exposure.parquet")
    df = _safe(_read_parquet, p)
    if df is not None and {"community_name", "latitude", "longitude", "exposure"} <= set(df.columns):
        return df, ("fixture exposure.parquet" if is_fixture(p) else "exposure.parquet")
    h = resolve("mesh_hit_rates.npz")
    if h is None or not COMMUNITIES_CSV.is_file():
        return None, None
    try:
        df = _exposure_from_hitrates(str(h), _mtime(h), str(COMMUNITIES_CSV), _mtime(COMMUNITIES_CSV))
    except Exception:
        return None, None
    return df, "MESH >= 30 mm hit rate at community centroid (mesh_hit_rates.npz), min-max scaled"


def to_mdt(ts) -> pd.Timestamp | None:
    """ISO string (UTC if naive) -> America/Edmonton timestamp, or None."""
    if ts is None or (isinstance(ts, float) and np.isnan(ts)):
        return None
    try:
        t = pd.Timestamp(ts)
    except Exception:
        return None
    if t is pd.NaT:
        return None
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert("America/Edmonton")


def hhmm(ts) -> str:
    t = to_mdt(ts)
    return "-" if t is None else t.strftime("%H:%M")
