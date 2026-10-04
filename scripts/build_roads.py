"""Build the Calgary drivable road network cache used by civicsignal/roads.py.

Run:  .venv/bin/python scripts/build_roads.py [--refresh] [--no-matrix]

1. Downloads the OSM drive network for Calgary with osmnx (graph_from_place; falls back to a
   bbox lat 50.84-51.22, lon -114.32 to -113.85), keeps the largest strongly connected
   component, adds edge speeds (posted maxspeed, else per-highway-type mean) and travel times.
   The raw graph is kept as data/roads/calgary_drive_raw.graphml (reused unless --refresh).
2. Writes data/roads/calgary_drive.npz: directed CSR (one-way streets respected; for parallel
   edges the fastest is kept), edge length/travel time and edge geometry for polylines.
3. Precomputes the matrix cache (data/roads/matrix_cache.npz) for every historical 311 point
   and crew depot, so the 7-day replay does not run Dijkstra for them again.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from civicsignal import roads  # noqa: E402

RAW = roads.ROADS_DIR / "calgary_drive_raw.graphml"
BBOX = (-114.32, 50.84, -113.85, 51.22)          # left, bottom, right, top


def download(refresh: bool):
    import osmnx as ox
    if RAW.exists() and not refresh:
        print(f"loading {RAW}")
        return ox.load_graphml(RAW)
    t0 = time.time()
    try:
        G = ox.graph_from_place("Calgary, Alberta, Canada", network_type="drive")
    except Exception as e:  # noqa: BLE001
        print(f"place query failed ({e}); using bbox {BBOX}")
        G = ox.graph_from_bbox(BBOX, network_type="drive")
    print(f"downloaded {len(G):,} nodes, {G.number_of_edges():,} edges in {time.time() - t0:.0f}s")
    ox.save_graphml(G, RAW)
    return G


def to_npz(G, out: Path):
    import osmnx as ox
    G = ox.truncate.largest_component(G, strongly=True)
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    ids = list(G.nodes)
    ix = {n: i for i, n in enumerate(ids)}
    lat = np.array([G.nodes[n]["y"] for n in ids])
    lon = np.array([G.nodes[n]["x"] for n in ids])
    U, V, L, T, geoms = [], [], [], [], []
    for u, v, d in G.edges(data=True):
        U.append(ix[u]); V.append(ix[v])
        L.append(float(d["length"])); T.append(float(d["travel_time"]))
        if "geometry" in d:
            geoms.append(np.asarray(d["geometry"].coords, dtype=float))
        else:
            geoms.append(np.array([[lon[ix[u]], lat[ix[u]]], [lon[ix[v]], lat[ix[v]]]]))
    U, V, L, T = map(np.asarray, (U, V, L, T))
    # sort by (u, v, travel time) and keep the fastest of parallel edges
    order = np.lexsort((T, V, U))
    keep = order[np.r_[True, (np.diff(U[order]) != 0) | (np.diff(V[order]) != 0)]]
    U, V, L, T = U[keep], V[keep], L[keep], T[keep]
    geoms = [geoms[k] for k in keep]
    indptr = np.r_[0, np.cumsum(np.bincount(U, minlength=len(ids)))]
    geom_ptr = np.r_[0, np.cumsum([len(g) for g in geoms])]
    geom_xy = np.vstack(geoms)
    np.savez_compressed(out, node_lat=lat, node_lon=lon, indptr=indptr.astype(np.int64),
                        indices=V.astype(np.int32), length_m=L.astype(np.float32),
                        travel_time_s=T.astype(np.float32), geom_ptr=geom_ptr.astype(np.int64),
                        geom_xy=geom_xy.astype(np.float64))
    print(f"wrote {out}: {len(ids):,} nodes, {len(U):,} directed edges, "
          f"{L.sum() / 1000:,.0f} km of directed road")


def precompute():
    from civicsignal import sim
    tickets = sim.load_tickets()
    crews = sim.make_crews(sim.calibrate_capacity(), tickets)
    lat = np.r_[[c.depot_lat for c in crews], tickets["latitude"].to_numpy()]
    lon = np.r_[[c.depot_lon for c in crews], tickets["longitude"].to_numpy()]
    if roads.CACHE_NPZ.exists():
        roads.CACHE_NPZ.unlink()
    roads.set_network(roads.RoadNetwork(cache=None))
    net = roads.network()
    nodes, _ = net.snap(lat, lon)
    t0 = time.time()
    net.register(nodes)
    net.save_cache()
    print(f"matrix cache: {len(net.nodes)} nodes in {time.time() - t0:.0f}s -> {roads.CACHE_NPZ}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download from OSM")
    ap.add_argument("--no-matrix", action="store_true", help="skip the historical matrix cache")
    a = ap.parse_args()
    T0 = time.time()
    roads.ROADS_DIR.mkdir(parents=True, exist_ok=True)
    to_npz(download(a.refresh), roads.GRAPH_NPZ)
    if not a.no_matrix:
        precompute()
    print(f"done in {time.time() - T0:.0f}s")
