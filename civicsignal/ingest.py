"""Open Calgary (Socrata) ingest: storm-week 311 tickets, validation tickets, asset and risk layers.

Every layer here is pulled from https://data.calgary.ca. Nothing is synthesized. The only
hand-assembled file is data/seniors_residences.csv (no open layer exists); see README.
"""
from __future__ import annotations

import ast
import io
import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = "https://data.calgary.ca/resource/{id}.{fmt}"
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LAYERS = DATA / "layers"
RAW = DATA / "raw"

SNOW_SERVICES = [
    "Bylaw - Snow and Ice on Sidewalk",
    "Roads - Snow and Ice Control",
    "Roads - Pathway Snow and Ice Concerns",
]
STORM_START, STORM_END = "2025-11-25", "2025-12-01"
WARM_START = "2025-11-18"
VALID_START, VALID_END = "2025-11-01", "2026-03-31"

TICKET_FIELDS = [
    "service_request_id", "requested_date", "closed_date", "status_description", "source",
    "service_name", "agency_responsible", "comm_code", "comm_name", "location_type",
    "longitude", "latitude",
]

# dataset ids
DS = {
    "tickets": "iahh-g8bj",
    "poles": "vt3t-jpfj",
    "census": "vsk6-ghca",
    "equity": "7g5f-dkmi",
    "schools": "fd9t-tdn2",
    "community_services": "x34e-bcjz",
    "childcare": "qdxh-qngy",
    "traffic": "cauu-7hnw",
    "transit_stops": "muzh-c9qc",
    "crosswalks": "hxgg-rpad",
    "ped_counts": "pede-tz7g",
    "ped_locations": "uwis-xpm2",
    "boundaries": "surr-xmvs",
    "parcel_address": "9zvu-p8uz",
}


def socrata(dataset: str, params: dict | None = None, fmt: str = "json", page: int = 50000,
            max_rows: int | None = None, retries: int = 4):
    """Page through a Socrata resource with $limit/$offset. Returns list[dict] (json) or DataFrame (csv)."""
    params = dict(params or {})
    if "$group" not in params:
        params.setdefault("$order", ":id")
    out, offset = [], 0
    while True:
        p = {**params, "$limit": page, "$offset": offset}
        for attempt in range(retries):
            try:
                r = requests.get(BASE.format(id=dataset, fmt=fmt), params=p, timeout=180)
                r.raise_for_status()
                break
            except requests.RequestException:
                if attempt == retries - 1:
                    raise
                time.sleep(2 * (attempt + 1))
        if fmt == "json":
            chunk = r.json()
            n = len(chunk)
        else:
            chunk = pd.read_csv(io.StringIO(r.text), dtype=str)
            n = len(chunk)
        out.append(chunk)
        offset += n
        if n < page or (max_rows and offset >= max_rows):
            break
    if fmt == "json":
        return [row for c in out for row in c]
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _point_lonlat(v):
    """Parse a Socrata point (dict, dict-string, or WKT) to (lon, lat)."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return (np.nan, np.nan)
    if isinstance(v, str):
        if v.startswith("POINT"):
            lon, lat = re.findall(r"[-\d.]+", v)[:2]
            return float(lon), float(lat)
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            v = ast.literal_eval(v)
    c = v.get("coordinates")
    return float(c[0]), float(c[1])


def _with_point(rows: list[dict], key: str = "point") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    ll = df[key].map(_point_lonlat)
    df["lon"] = [x[0] for x in ll]
    df["lat"] = [x[1] for x in ll]
    return df.drop(columns=[key] + [c for c in df.columns if c.startswith(":@")])


def _in_list(vals):
    return "(" + ",".join("'" + v.replace("'", "''") + "'" for v in vals) + ")"


# ---------------------------------------------------------------- tickets

def pull_tickets(start: str, end: str, services=SNOW_SERVICES) -> pd.DataFrame:
    where = (f"requested_date between '{start}T00:00:00' and '{end}T23:59:59' "
             f"and service_name in {_in_list(services)}")
    rows = socrata(DS["tickets"], {"$select": ",".join(TICKET_FIELDS), "$where": where})
    df = pd.DataFrame(rows)
    for c in TICKET_FIELDS:
        if c not in df:
            df[c] = None
    df = df[TICKET_FIELDS].copy()
    df["requested_date"] = pd.to_datetime(df["requested_date"]).dt.normalize()
    df["closed_date"] = pd.to_datetime(df["closed_date"]).dt.normalize()
    df["latitude"] = pd.to_numeric(df["latitude"])
    df["longitude"] = pd.to_numeric(df["longitude"])
    return df.sort_values(["requested_date", "service_request_id"]).reset_index(drop=True)


# ---------------------------------------------------------------- layers

def pull_poles() -> pd.DataFrame:
    df = socrata(DS["poles"], {"$select": "streetlight_id,latitude,longitude"}, fmt="csv")
    df["lat"] = pd.to_numeric(df.pop("latitude"))
    df["lon"] = pd.to_numeric(df.pop("longitude"))
    return df.dropna()


def pull_census() -> pd.DataFrame:
    rows = socrata(DS["census"], {"$where": "year='2019'"})
    df = pd.DataFrame(rows)
    for c in ("males", "females"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df


def pull_equity() -> tuple[pd.DataFrame, dict]:
    """Equity Index rows for Community Service Areas (CSA) + their polygons as GeoJSON."""
    rows = socrata(DS["equity"], {"$where": "area_type='CSA'"})
    feats, seen = [], set()
    for r in rows:
        if r["area_id"] not in seen and r.get("multipolygon"):
            seen.add(r["area_id"])
            feats.append({"type": "Feature", "properties": {"area_id": r["area_id"]},
                          "geometry": r["multipolygon"]})
    df = pd.DataFrame(rows).drop(columns=["multipolygon"], errors="ignore")
    df = df[[c for c in df.columns if not c.startswith(":@")]]
    return df, {"type": "FeatureCollection", "features": feats}


def pull_points(key: str, params: dict | None = None) -> pd.DataFrame:
    return _with_point(socrata(DS[key], params or {}))


def pull_traffic() -> dict:
    rows = socrata(DS["traffic"])
    feats = []
    for r in rows:
        g = r.get("multilinestring")
        if isinstance(g, str):
            g = ast.literal_eval(g)
        feats.append({"type": "Feature", "geometry": g,
                      "properties": {"section_name": r.get("section_name"),
                                     "volume": float(r.get("volume") or 0), "year": r.get("year")}})
    return {"type": "FeatureCollection", "features": feats}


def pull_boundaries() -> dict:
    rows = socrata(DS["boundaries"])
    feats = []
    for r in rows:
        g = r.get("multipolygon")
        if isinstance(g, str):
            g = ast.literal_eval(g)
        props = {k: r.get(k) for k in ("comm_code", "name", "sector", "class", "srg", "comm_structure")}
        feats.append({"type": "Feature", "geometry": g, "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def pull_ped_counts() -> pd.DataFrame:
    """Average daily pedestrian count per monitoring location (all directions summed per day)."""
    rows = socrata(DS["ped_counts"], {
        "$select": "monitoring_location,date,sum(total) as total",
        "$where": "user_type='Peds'",
        "$group": "monitoring_location,date",
        "$order": "monitoring_location,date",
    })
    df = pd.DataFrame(rows)
    df["total"] = pd.to_numeric(df["total"])
    agg = df.groupby("monitoring_location")["total"].agg(["mean", "count"]).reset_index()
    return agg.rename(columns={"mean": "avg_daily_peds", "count": "n_days"})


# ---------------------------------------------------------------- geocoding via City parcel addresses

_ABBR = {
    "AVENUE": "AV", "AVE": "AV", "STREET": "ST", "DRIVE": "DR", "ROAD": "RD", "BOULEVARD": "BV",
    "BLVD": "BV", "CRESCENT": "CR", "CRES": "CR", "PLACE": "PL", "COURT": "CO", "CRT": "CO",
    "CT": "CO", "TRAIL": "TR", "WAY": "WY", "CLOSE": "CL", "GATE": "GA", "HEIGHTS": "HT",
    "HILL": "HL", "TERRACE": "TC", "MANOR": "MR", "LANE": "LN", "PARK": "PA", "SQUARE": "SQ",
    "CIRCLE": "CI", "COMMON": "CM", "GREEN": "GR", "GROVE": "GV", "VIEW": "VW", "POINT": "PT",
    "RISE": "RI", "LINK": "LI", "PARKWAY": "PY", "ROW": "RO", "MEWS": "ME", "HIGHWAY": "HI",
    "MOUNT": "MT", "BAY": "BA", "GARDENS": "GD", "LANDING": "LD", "PATH": "PH", "CENTRE": "CE",
    "COVE": "CV", "WALK": "WK", "PLAZA": "PZ", "PROMENADE": "PR", "PARADE": "PR", "PASSAGE": "PS",
    "VILLAS": "VI", "ISLAND": "IS", "CAPE": "CA", "ALLEY": "AL", "HEATH": "HE",
}


def normalize_address(a: str) -> str | None:
    """Normalize a free-form Calgary street address to the parcel-address key style."""
    if not isinstance(a, str):
        return None
    a = a.upper().strip()
    a = re.sub(r"CALGARY\s*,?\s*A(B|LBERTA).*$", "", a)       # trailing city/postal
    a = re.sub(r"[.#]", " ", a)
    if "," in a:                                              # "150, 2915 26 AVE SE" -> unit first
        parts = [p.strip() for p in a.split(",") if p.strip()]
        num_parts = [p for p in parts if re.match(r"^\d+\s+\S", p) or re.match(r"^\d+\s*-\s*\S", p)]
        a = num_parts[-1] if num_parts else parts[0]
    a = re.sub(r"^(UNIT|SUITE|BAY)\s*\S+\s+", "", a)
    a = re.sub(r"^\d+[A-Z]?-(?=\d+\s)", "", a)                # "101-1234 X ST" -> "1234 X ST"
    a = re.sub(r"^(\d+)\s*-\s*", r"\1 ", a)                   # "1507 - 19 AVENUE" -> "1507 19 AVENUE"
    a = re.sub(r"\b(\d+)(ST|ND|RD|TH)\b", r"\1", a)
    toks = a.split()
    toks = [_ABBR.get(t, t) for t in toks]
    a = " ".join(toks)
    return re.sub(r"\s+", " ", a).strip()


def load_parcel_index() -> dict:
    path = RAW / "parcel_address.csv"
    if not path.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        df = socrata(DS["parcel_address"], {"$select": "address,latitude,longitude"}, fmt="csv")
        df.to_csv(path, index=False)
    df = pd.read_csv(path, dtype={"address": str})
    df = df.dropna()
    df["key"] = df["address"].map(normalize_address)
    g = df.groupby("key")[["latitude", "longitude"]].mean()
    return {k: (r.latitude, r.longitude) for k, r in g.iterrows()}


def geocode_addresses(addresses: pd.Series, index: dict | None = None) -> pd.DataFrame:
    index = index if index is not None else load_parcel_index()
    keys = addresses.map(normalize_address)
    # fallback: drop a trailing house-number letter ("1520B NORTHMOUNT DR NW")
    keys = keys.map(lambda k: k if (k in index or not isinstance(k, str))
                    else re.sub(r"^(\d+)[A-Z]\b", r"\1", k))
    lat = keys.map(lambda k: index.get(k, (np.nan, np.nan))[0])
    lon = keys.map(lambda k: index.get(k, (np.nan, np.nan))[1])
    return pd.DataFrame({"addr_key": keys, "lat": lat, "lon": lon})


def pull_childcare(index: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Licensed child-care programs (latest record per program), geocoded via City parcel addresses.

    `qdxh-qngy` has no coordinates; only street addresses. We match them to the City's own
    Parcel Address layer (`9zvu-p8uz`). Unmatched programs are dropped and counted.
    """
    rows = socrata(DS["childcare"], {
        "$select": "program_name,type_of_program,program_address,capacity,max(inspection_date) as last_insp",
        "$group": "program_name,type_of_program,program_address,capacity",
    })
    df = pd.DataFrame(rows)
    df["last_insp"] = pd.to_datetime(df["last_insp"])
    df = df[df["last_insp"] >= "2022-01-01"]
    df = df.sort_values("last_insp").drop_duplicates(["program_name", "program_address"], keep="last")
    geo = geocode_addresses(df["program_address"], index)
    df = pd.concat([df.reset_index(drop=True), geo.reset_index(drop=True)], axis=1)
    stats = {"programs": int(len(df)), "geocoded": int(df["lat"].notna().sum())}
    return df.dropna(subset=["lat"]), stats


def build_intersections(crosswalks: pd.DataFrame) -> pd.DataFrame:
    """Intersection lookup derived from the City crosswalk inventory (real cross-street pairs)."""
    c = crosswalks.dropna(subset=["cross_street_name1", "cross_street_name2"]).copy()
    a, b = c["cross_street_name1"].str.strip(), c["cross_street_name2"].str.strip()
    c["intersection"] = np.where(a < b, a + " & " + b, b + " & " + a)
    g = c.groupby("intersection").agg(lat=("lat", "mean"), lon=("lon", "mean"),
                                      n_crosswalks=("lat", "size")).reset_index()
    return g.sort_values("n_crosswalks", ascending=False)
