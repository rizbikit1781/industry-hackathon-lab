"""Risk features from real Open Calgary layers, precomputed on a ~200 m city grid.

Point features (schools, hospitals/clinics, child care, seniors' residences, traffic, pedestrian
proxy) are computed per grid cell. Community-level features (census age shares, Equity Index)
are joined by community / Community Service Area polygon.

Historical 311 tickets only carry a community centrepoint, so a historical ticket gets its
community's *area-average* exposure. A live (voice) ticket with a real lat/lon gets its cell.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape
from sklearn.neighbors import BallTree

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LAYERS = DATA / "layers"
CELL_M = 200.0
EARTH_R = 6_371_000.0

POINT_FEATURES = ["school", "hospital", "seniors_res", "childcare", "traffic", "ped"]
COMMUNITY_FEATURES = ["seniors_share", "seniors75_share", "children_share",
                      "lim_65", "no_english", "transit_work", "equity_seniors"]
EQUITY_ATTRS = {"lim_65": "LIM-AT 65+ years", "no_english": "No English Knowledge",
                "transit_work": "Transit to work", "equity_seniors": "Seniors"}


def _tree(lat, lon):
    return BallTree(np.radians(np.c_[lat, lon]), metric="haversine")


def _nearest_m(tree, lat, lon):
    d, _ = tree.query(np.radians(np.c_[lat, lon]), k=1)
    return d[:, 0] * EARTH_R


def _count_within(tree, lat, lon, r_m):
    return tree.query_radius(np.radians(np.c_[lat, lon]), r=r_m / EARTH_R, count_only=True)


def _pct(x):
    """Percentile rank 0-1 (ties averaged)."""
    s = pd.Series(x, dtype=float)
    return s.rank(pct=True, method="average").fillna(0).to_numpy()


def load_geojson(name):
    gj = json.loads((LAYERS / name).read_text())
    geoms = [shape(f["geometry"]) for f in gj["features"]]
    props = pd.DataFrame([f["properties"] for f in gj["features"]])
    return geoms, props


def seniors_residences() -> pd.DataFrame | None:
    p = DATA / "seniors_residences.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if not {"lat", "lon"} <= set(df.columns):
        return None
    df = df.dropna(subset=["lat", "lon"])
    return df if len(df) else None


# ---------------------------------------------------------------- point-feature engine

class PointLayers:
    """Holds BallTrees for every point layer; evaluates point features at arbitrary lat/lon."""

    def __init__(self):
        sch = pd.read_csv(LAYERS / "schools.csv").dropna(subset=["lat", "lon"])
        elem = sch[sch["elem"].eq("Y")]
        self.t_elem = _tree(elem.lat, elem.lon)
        self.t_school = _tree(sch.lat, sch.lon)
        cs = pd.read_csv(LAYERS / "community_services.csv")
        hosp = cs[cs["type"].isin(["Hospital", "PHS Clinic"])].dropna(subset=["lat", "lon"])
        self.hospitals = hosp
        self.t_hosp = _tree(hosp.lat, hosp.lon)
        cc = pd.read_csv(LAYERS / "childcare.csv").dropna(subset=["lat", "lon"])
        self.t_child = _tree(cc.lat, cc.lon)
        sr = seniors_residences()
        self.t_sen = _tree(sr.lat, sr.lon) if sr is not None else None
        ts = pd.read_csv(LAYERS / "transit_stops.csv").dropna(subset=["lat", "lon"])
        self.t_transit = _tree(ts.lat, ts.lon)
        cw = pd.read_csv(LAYERS / "crosswalks.csv").dropna(subset=["lat", "lon"])
        self.t_cross = _tree(cw.lat, cw.lon)
        # traffic: densify segments every ~20 m into a vertex tree with the segment's volume
        gj = json.loads((LAYERS / "traffic_2024.geojson").read_text())
        pts, vols = [], []
        for f in gj["features"]:
            g = shape(f["geometry"])
            v = f["properties"]["volume"]
            if v <= 0 or g.is_empty:
                continue
            for line in getattr(g, "geoms", [g]):
                n = max(2, int(line.length / 0.00025))            # ~20 m in degrees
                for p in shapely.line_interpolate_point(line, np.linspace(0, 1, n), normalized=True):
                    pts.append((p.y, p.x))
                    vols.append(v)
        pts = np.array(pts)
        self.t_traffic = _tree(pts[:, 0], pts[:, 1])
        logv = np.log(np.array(vols))
        self.traffic_pct = _pct(logv)                            # percentile of log(volume)

    def evaluate(self, lat, lon) -> pd.DataFrame:
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        d_elem = _nearest_m(self.t_elem, lat, lon)
        d_sch = _nearest_m(self.t_school, lat, lon)
        school = np.maximum(np.exp(-d_elem / 250), 0.6 * np.exp(-d_sch / 250))
        hospital = np.exp(-_nearest_m(self.t_hosp, lat, lon) / 400)
        childcare = np.exp(-_nearest_m(self.t_child, lat, lon) / 200)
        seniors_res = (np.exp(-_nearest_m(self.t_sen, lat, lon) / 250)
                       if self.t_sen is not None else np.zeros_like(lat))
        d, i = self.t_traffic.query(np.radians(np.c_[lat, lon]), k=1)
        d_m = d[:, 0] * EARTH_R
        traffic = np.where(d_m <= 60, self.traffic_pct[i[:, 0]], 0.0)
        n_transit = _count_within(self.t_transit, lat, lon, 300)
        n_cross = _count_within(self.t_cross, lat, lon, 150)
        return pd.DataFrame({"school": school, "hospital": hospital, "seniors_res": seniors_res,
                             "childcare": childcare, "traffic": traffic,
                             "n_transit_300m": n_transit, "n_cross_150m": n_cross})


@lru_cache(maxsize=1)
def point_layers() -> PointLayers:
    return PointLayers()


# ---------------------------------------------------------------- community-level

def census_features() -> pd.DataFrame:
    c = pd.read_csv(LAYERS / "census_2019.csv")
    c["pop"] = c["males"] + c["females"]
    p = c.pivot_table(index="code", columns="age_range", values="pop", aggfunc="sum").fillna(0)
    tot = p.sum(axis=1)
    out = pd.DataFrame({
        "population_2019": tot,
        "share_65p": (p.get("65-74", 0) + p.get("75+", 0)) / tot.replace(0, np.nan),
        "share_75p": p.get("75+", 0) / tot.replace(0, np.nan),
        "share_0_14": (p.get("0-4", 0) + p.get("5-14", 0)) / tot.replace(0, np.nan),
    })
    out = out[out["population_2019"] >= 100]                    # drop industrial/near-empty codes
    out["seniors_share"] = _pct(out["share_65p"])
    out["seniors75_share"] = _pct(out["share_75p"])
    out["children_share"] = _pct(out["share_0_14"])
    out.index.name = "comm_code"
    return out


def equity_features() -> pd.DataFrame:
    e = pd.read_csv(LAYERS / "equity.csv")
    e["value"] = pd.to_numeric(e["value"], errors="coerce")
    out = {}
    for col, attr in EQUITY_ATTRS.items():
        s = e[e["attribute"] == attr].set_index("area_id")["value"]
        out[col] = pd.Series(_pct(s), index=s.index)
    df = pd.DataFrame(out)
    df.index.name = "csa_id"
    return df


# ---------------------------------------------------------------- grid build

def build_grid(cell_m: float = CELL_M) -> tuple[pd.DataFrame, pd.DataFrame]:
    comm_geoms, comm_props = load_geojson("communities.geojson")
    csa_geoms, csa_props = load_geojson("equity_csa.geojson")
    union_bounds = np.array([g.bounds for g in comm_geoms])
    minx, miny = union_bounds[:, 0].min(), union_bounds[:, 1].min()
    maxx, maxy = union_bounds[:, 2].max(), union_bounds[:, 3].max()
    dlat = cell_m / 111_320
    dlon = cell_m / (111_320 * np.cos(np.radians((miny + maxy) / 2)))
    lats = np.arange(miny + dlat / 2, maxy, dlat)
    lons = np.arange(minx + dlon / 2, maxx, dlon)
    LON, LAT = np.meshgrid(lons, lats)
    grid = pd.DataFrame({"lat": LAT.ravel(), "lon": LON.ravel(),
                         "row": np.repeat(np.arange(len(lats)), len(lons)),
                         "col": np.tile(np.arange(len(lons)), len(lats))})
    # community + CSA membership via point-in-polygon
    grid["comm_code"] = None
    for g, code in zip(comm_geoms, comm_props["comm_code"]):
        m = shapely.contains_xy(g, grid["lon"].to_numpy(), grid["lat"].to_numpy())
        grid.loc[m, "comm_code"] = code
    grid["csa_id"] = None
    for g, aid in zip(csa_geoms, csa_props["area_id"]):
        m = shapely.contains_xy(g, grid["lon"].to_numpy(), grid["lat"].to_numpy())
        grid.loc[m, "csa_id"] = aid
    grid = grid[grid["comm_code"].notna()].reset_index(drop=True)

    pl = point_layers()
    pf = pl.evaluate(grid["lat"], grid["lon"])
    grid = pd.concat([grid, pf], axis=1)
    grid["ped"] = 0.5 * _pct(grid["n_transit_300m"]) + 0.5 * _pct(grid["n_cross_150m"])

    cen = census_features()
    eq = equity_features()
    grid = grid.join(cen[["seniors_share", "seniors75_share", "children_share"]], on="comm_code")
    grid = grid.join(eq, on="csa_id")
    # communities absent from the 2019 census (built after 2019) get the city median: neutral
    for c in COMMUNITY_FEATURES:
        grid[c] = grid[c].fillna(0.5)

    meta = {"minx": minx, "miny": miny, "dlat": dlat, "dlon": dlon,
            "nrows": len(lats), "ncols": len(lons), "cell_m": cell_m}
    grid.attrs["meta"] = meta

    # community area-average table (what a historical, centrepoint-only ticket gets)
    comm = grid.groupby("comm_code")[POINT_FEATURES + COMMUNITY_FEATURES].mean()
    comm = comm.join(comm_props.set_index("comm_code")[["name", "sector"]])
    reps = {code: g.representative_point() for g, code in zip(comm_geoms, comm_props["comm_code"])}
    comm["rep_lat"] = [reps[c].y for c in comm.index]
    comm["rep_lon"] = [reps[c].x for c in comm.index]
    comm = comm.join(cen[["population_2019", "share_65p", "share_75p", "share_0_14"]])
    return grid, comm


def save_grid():
    grid, comm = build_grid()
    grid.to_parquet(DATA / "features_by_cell.parquet")
    (DATA / "features_grid_meta.json").write_text(json.dumps(grid.attrs["meta"]))
    comm.to_csv(DATA / "community_features.csv")
    return grid, comm


@lru_cache(maxsize=1)
def load_grid():
    p = DATA / "features_by_cell.parquet"
    if not p.exists():
        save_grid()
    grid = pd.read_parquet(p)
    meta = json.loads((DATA / "features_grid_meta.json").read_text())
    comm = pd.read_csv(DATA / "community_features.csv", index_col=0)
    key = {(r, c): i for i, (r, c) in enumerate(zip(grid["row"], grid["col"]))}
    return grid, comm, meta, key


def features_at(lat: float, lon: float) -> dict:
    """Millisecond lookup for a live ticket: the grid cell containing (lat, lon)."""
    grid, comm, meta, key = load_grid()
    r = int((lat - meta["miny"]) / meta["dlat"])
    c = int((lon - meta["minx"]) / meta["dlon"])
    i = key.get((r, c))
    if i is None:                                             # outside city cells: nearest cell
        d = (grid["lat"] - lat) ** 2 + ((grid["lon"] - lon) * 0.63) ** 2
        i = int(d.idxmin())
    row = grid.iloc[i]
    out = {k: float(row[k]) for k in POINT_FEATURES + COMMUNITY_FEATURES}
    out["comm_code"] = row["comm_code"]
    return out


def ticket_features(tickets: pd.DataFrame) -> pd.DataFrame:
    """Features for historical tickets: community area-average by comm_code."""
    _, comm, _, _ = load_grid()
    cols = POINT_FEATURES + COMMUNITY_FEATURES
    f = tickets[["comm_code"]].join(comm[cols], on="comm_code")
    for c in cols:
        f[c] = f[c].fillna(comm[c].median())
    return f[cols]


def ped_proxy_validation() -> dict:
    """Spearman of pedestrian proxy (at the real count sites) vs measured average daily peds."""
    from scipy.stats import spearmanr
    grid, *_ = load_grid()
    locs = pd.read_csv(LAYERS / "ped_locations.csv")
    counts = pd.read_csv(LAYERS / "ped_counts.csv")
    norm = lambda s: s.str.lower().str.replace(r"\bstreet\b", "st", regex=True).str.strip()
    counts["key"], locs["key"] = norm(counts["monitoring_location"]), norm(locs["monitoring_location"])
    df = counts.merge(locs[["key", "lat", "lon"]], on="key")
    pl = point_layers()
    pf = pl.evaluate(df["lat"], df["lon"])
    # same percentile scale as the grid
    tr = np.searchsorted(np.sort(grid["n_transit_300m"]), pf["n_transit_300m"], side="right") / len(grid)
    cr = np.searchsorted(np.sort(grid["n_cross_150m"]), pf["n_cross_150m"], side="right") / len(grid)
    df["ped_proxy"] = 0.5 * tr + 0.5 * cr
    df["n_transit_300m"] = pf["n_transit_300m"].to_numpy()
    df["n_cross_150m"] = pf["n_cross_150m"].to_numpy()
    rho, p = spearmanr(df["ped_proxy"], df["avg_daily_peds"])
    rho_t, _ = spearmanr(df["n_transit_300m"], df["avg_daily_peds"])
    rho_c, _ = spearmanr(df["n_cross_150m"], df["avg_daily_peds"])
    return {"n_sites": int(len(df)), "spearman": float(rho), "p_value": float(p),
            "spearman_transit_only": float(rho_t), "spearman_crosswalk_only": float(rho_c),
            "sites": df[["monitoring_location", "avg_daily_peds", "ped_proxy",
                         "n_transit_300m", "n_cross_150m"]].round(3).to_dict("records")}
