"""Calgary road-network routing: distance/time matrices and road-following polylines.

The drivable network comes from OpenStreetMap via osmnx (`scripts/build_roads.py`), stored as a
compact npz under `data/roads/` (directed edges, so one-way streets are respected). Shortest
paths use `scipy.sparse.csgraph.dijkstra` on a CSR matrix of edge travel times.

- Paths are the *fastest* route on OSM free-flow speeds (osmnx `add_edge_speeds`: posted
  maxspeed, else the mean for that highway type), slowed by one explicit winter factor
  (`WINTER_SPEED_FACTOR`). The metres reported are the length of that same fastest path.
- Each point is snapped to its nearest graph node (BallTree, haversine). The snap distance is
  added to the metres and to the minutes at walking speed (`SNAP_SPEED_M_PER_MIN`): historical
  311 points are community centrepoints, often in a park.
- Matrices are cached per graph node. A new point (e.g. a voice ticket) costs one forward
  Dijkstra (its row) and one Dijkstra on the reversed graph (its column).
- If the road cache is missing, everything falls back to the old model, haversine x
  `ROAD_FACTOR` at `SPEED_M_PER_MIN`, with a logged warning, so tests pass on a fresh clone.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra, reconstruct_path
from sklearn.neighbors import BallTree

from .dedupe import EARTH_R, haversine_m

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
ROADS_DIR = ROOT / "data" / "roads"
GRAPH_NPZ = ROADS_DIR / "calgary_drive.npz"
CACHE_NPZ = ROADS_DIR / "matrix_cache.npz"

# Fallback model (the pre-road-network method).
ROAD_FACTOR = 1.3
SPEED_M_PER_MIN = 30_000 / 60

# The one winter assumption: crews drive at 80% of OSM free-flow speed on snow and ice.
WINTER_SPEED_FACTOR = 0.8
# Snap leg (point <-> nearest drivable node) is covered at walking speed, 5 km/h.
SNAP_SPEED_M_PER_MIN = 5_000 / 60
_CHUNK = 64                    # Dijkstra sources per batch (memory: CHUNK x nodes x 8 bytes)
_PRED_CACHE_MAX = 1500         # predecessor rows kept for polylines (int32, ~150 KB each)


class RoadNetwork:
    def __init__(self, path: Path = GRAPH_NPZ, cache: Path | None = CACHE_NPZ):
        z = np.load(path)
        self.lat, self.lon = z["node_lat"].astype(float), z["node_lon"].astype(float)
        self.n = len(self.lat)
        indptr, indices = z["indptr"], z["indices"]
        self.indptr, self.indices = indptr, indices
        self.length_m = z["length_m"].astype(float)
        minutes = z["travel_time_s"].astype(float) / 60.0 / WINTER_SPEED_FACTOR
        # scipy treats stored zeros as edges, but keep weights strictly positive anyway
        self.Gt = csr_matrix((np.maximum(minutes, 1e-4), indices, indptr), shape=(self.n, self.n))
        self.Gm = csr_matrix((np.maximum(self.length_m, 1e-2), indices, indptr), shape=(self.n, self.n))
        self.Rt = self.Gt.T.tocsr()
        self.Rm = self.Gm.T.tocsr()
        self.geom_ptr, self.geom_xy = z["geom_ptr"], z["geom_xy"]
        self.signature = np.array([self.n, len(indices), round(float(self.length_m.sum()))])
        self.tree = BallTree(np.radians(np.c_[self.lat, self.lon]), metric="haversine")
        self.lock = threading.RLock()
        self.nodes = np.zeros(0, dtype=np.int64)      # registered nodes, in matrix order
        self.pos: dict[int, int] = {}
        self.Mt = np.zeros((0, 0))                    # minutes between registered nodes
        self.Mm = np.zeros((0, 0))                    # metres along the same fastest path
        self.pred: dict[int, np.ndarray] = {}
        self.cache_path = cache
        if cache is not None and Path(cache).exists():
            c = np.load(cache)
            if np.array_equal(c["signature"], self.signature):
                self.nodes, self.Mt, self.Mm = c["nodes"].astype(np.int64), c["Mt"], c["Mm"]
                self.pos = {int(v): i for i, v in enumerate(self.nodes)}

    # ------------------------------------------------------------------ snapping
    def snap(self, lats, lons):
        X = np.radians(np.c_[np.asarray(lats, float), np.asarray(lons, float)])
        d, i = self.tree.query(X, k=1)
        return i[:, 0].astype(np.int64), d[:, 0] * EARTH_R

    # ------------------------------------------------------------------ registry
    def _tree_metres(self, Gm, pred_row, src):
        """Metres along the shortest-time tree (pred_row) from src."""
        tree = reconstruct_path(Gm, pred_row, directed=True)
        return dijkstra(tree, directed=True, indices=int(src))

    def _sweep(self, Gt, Gm, srcs):
        t, p = dijkstra(Gt, directed=True, indices=srcs, return_predecessors=True)
        m = np.vstack([self._tree_metres(Gm, p[r], s) for r, s in enumerate(srcs)])
        return t, m, p

    def register(self, nodes) -> None:
        """Add rows+columns for graph nodes not yet in the cached matrix."""
        with self.lock:
            new = [int(v) for v in dict.fromkeys(np.asarray(nodes).tolist()) if int(v) not in self.pos]
            if not new:
                return
            new = np.array(new, dtype=np.int64)
            K, n = len(self.nodes), len(new)
            allnodes = np.r_[self.nodes, new]
            Mt = np.full((K + n, K + n), np.inf)
            Mm = np.full((K + n, K + n), np.inf)
            Mt[:K, :K], Mm[:K, :K] = self.Mt, self.Mm
            for a in range(0, n, _CHUNK):
                src = new[a:a + _CHUNK]
                rows = slice(K + a, K + a + len(src))
                ft, fm, fp = self._sweep(self.Gt, self.Gm, src)        # src -> every node
                bt, bm, _ = self._sweep(self.Rt, self.Rm, src)         # every node -> src
                Mt[rows, :], Mm[rows, :] = ft[:, allnodes], fm[:, allnodes]
                Mt[:, rows], Mm[:, rows] = bt[:, allnodes].T, bm[:, allnodes].T
                for r, s in enumerate(src):
                    self._keep_pred(int(s), fp[r])
            self.nodes, self.Mt, self.Mm = allnodes, Mt, Mm
            self.pos = {int(v): i for i, v in enumerate(allnodes)}

    def _keep_pred(self, s, row):
        if len(self.pred) >= _PRED_CACHE_MAX:
            self.pred.pop(next(iter(self.pred)))
        self.pred[s] = row.astype(np.int32)

    def save_cache(self, path: Path | None = None) -> None:
        path = Path(path or self.cache_path or CACHE_NPZ)
        with self.lock:
            np.savez_compressed(path, signature=self.signature, nodes=self.nodes,
                                Mt=self.Mt.astype(np.float32), Mm=self.Mm.astype(np.float32))

    # ------------------------------------------------------------------ public
    def matrix(self, lats, lons):
        lats, lons = np.asarray(lats, float), np.asarray(lons, float)
        nodes, snap_m = self.snap(lats, lons)
        self.register(nodes)
        with self.lock:
            idx = np.array([self.pos[int(v)] for v in nodes], dtype=np.int64)
            Mm = self.Mm[np.ix_(idx, idx)].astype(float)
            Mt = self.Mt[np.ix_(idx, idx)].astype(float)
        snap = snap_m[:, None] + snap_m[None, :]
        metres = Mm + snap
        minutes = Mt + snap / SNAP_SPEED_M_PER_MIN
        # same node (or identical point): walk/drive the straight line instead
        same = nodes[:, None] == nodes[None, :]
        if same.any():
            hv = haversine_m(lats[:, None], lons[:, None], lats[None, :], lons[None, :])
            metres = np.where(same, hv, metres)
            minutes = np.where(same, hv / SNAP_SPEED_M_PER_MIN, minutes)
        bad = ~np.isfinite(metres) | ~np.isfinite(minutes)
        if bad.any():   # unreachable (should not happen: graph is one strongly connected piece)
            hv = haversine_m(lats[:, None], lons[:, None], lats[None, :], lons[None, :]) * ROAD_FACTOR
            metres = np.where(bad, hv * 2, metres)
            minutes = np.where(bad, hv * 2 / SPEED_M_PER_MIN, minutes)
        np.fill_diagonal(metres, 0.0)
        np.fill_diagonal(minutes, 0.0)
        return metres, minutes

    def _preds(self, srcs):
        with self.lock:
            out = {s: self.pred[s] for s in srcs if s in self.pred}
        miss = [s for s in dict.fromkeys(srcs) if s not in out]
        for a in range(0, len(miss), _CHUNK):
            src = np.array(miss[a:a + _CHUNK])
            _, p = dijkstra(self.Gt, directed=True, indices=src, return_predecessors=True)
            with self.lock:
                for r, s in enumerate(src):
                    out[int(s)] = p[r].astype(np.int32)
                    self._keep_pred(int(s), p[r])
        return out

    def _edge_xy(self, u, v):
        lo, hi = self.indptr[u], self.indptr[u + 1]
        k = lo + int(np.searchsorted(self.indices[lo:hi], v))
        return self.geom_xy[self.geom_ptr[k]:self.geom_ptr[k + 1]]

    def node_path(self, s, t, pred_row):
        out = [t]
        while out[-1] != s:
            p = int(pred_row[out[-1]])
            if p < 0:
                return None
            out.append(p)
        return out[::-1]

    def path(self, lats, lons):
        lats, lons = np.asarray(lats, float), np.asarray(lons, float)
        if len(lats) == 0:
            return []
        nodes, _ = self.snap(lats, lons)
        preds = self._preds([int(v) for v in nodes[:-1]])
        pts = [[float(lons[0]), float(lats[0])]]
        for i in range(len(nodes) - 1):
            s, t = int(nodes[i]), int(nodes[i + 1])
            nl = self.node_path(s, t, preds[s]) if s != t else [s]
            if nl is None:                       # unreachable: straight segment
                pts.append([float(lons[i + 1]), float(lats[i + 1])])
                continue
            pts.append([float(self.lon[s]), float(self.lat[s])])
            for u, v in zip(nl[:-1], nl[1:]):
                pts.extend(self._edge_xy(u, v)[1:].tolist())
            pts.append([float(lons[i + 1]), float(lats[i + 1])])
        # drop consecutive duplicates
        clean = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - clean[-1][0]) > 1e-7 or abs(p[1] - clean[-1][1]) > 1e-7:
                clean.append(p)
        return clean


# ---------------------------------------------------------------------- module API

_NET: RoadNetwork | None = None
_LOADED = False
_LOAD_LOCK = threading.Lock()


def network() -> RoadNetwork | None:
    """The road network, or None (fallback) if the cache is missing or disabled
    (CIVICSIGNAL_ROADS=0)."""
    global _NET, _LOADED
    if not _LOADED:
        with _LOAD_LOCK:
            if not _LOADED:
                if os.environ.get("CIVICSIGNAL_ROADS", "1") == "0":
                    log.warning("CIVICSIGNAL_ROADS=0: using haversine x %.1f fallback", ROAD_FACTOR)
                elif not GRAPH_NPZ.exists():
                    log.warning("road network %s missing (run scripts/build_roads.py); "
                                "falling back to haversine x %.1f at %.0f km/h",
                                GRAPH_NPZ, ROAD_FACTOR, SPEED_M_PER_MIN * 60 / 1000)
                else:
                    _NET = RoadNetwork()
                _LOADED = True
    return _NET


def set_network(net: RoadNetwork | None) -> None:
    """Override the network (tests: None forces the fallback)."""
    global _NET, _LOADED
    _NET, _LOADED = net, True


def method() -> str:
    return "osm_road_network" if network() is not None else "haversine_fallback"


def matrix(lats, lons):
    """(metres[n, n], minutes[n, n]) between points; row = from, column = to."""
    net = network()
    if net is not None:
        return net.matrix(lats, lons)
    lat, lon = np.asarray(lats, float), np.asarray(lons, float)
    d = haversine_m(lat[:, None], lon[:, None], lat[None, :], lon[None, :]) * ROAD_FACTOR
    return d, d / SPEED_M_PER_MIN


def path(lats, lons, simplify_deg: float = 0.0) -> list:
    """[[lon, lat], ...] polyline (GeoJSON order) through the ordered points, following roads.
    `simplify_deg` > 0 applies Douglas-Peucker (shapely) and rounds to 6 decimals, for JSON."""
    net = network()
    pts = net.path(lats, lons) if net is not None else \
        [[float(x), float(y)] for y, x in zip(lats, lons)]
    if simplify_deg > 0 and len(pts) > 2:
        from shapely.geometry import LineString
        pts = [[round(x, 6), round(y, 6)] for x, y in
               LineString(pts).simplify(simplify_deg, preserve_topology=False).coords]
    return pts


GEOMETRY_SIMPLIFY_DEG = 2e-5    # ~2 m: keeps street shape, trims JSON size


def save_cache() -> None:
    net = network()
    if net is not None:
        net.save_cache()
