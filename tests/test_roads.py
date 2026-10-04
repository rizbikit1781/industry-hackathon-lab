import numpy as np
import pytest

from civicsignal import roads
from civicsignal.dedupe import haversine_m


@pytest.fixture
def toy(tmp_path):
    """Triangle A, B, C of one-way edges A->B->C->A: B to A must go round via C."""
    lat = np.array([51.000, 51.000, 51.005])
    lon = np.array([-114.000, -113.990, -113.995])
    # directed edges sorted by (u, v): A->B, B->C, C->A
    U, V = np.array([0, 1, 2]), np.array([1, 2, 0])
    L = haversine_m(lat[U], lon[U], lat[V], lon[V])
    T = L / (50_000 / 3600)                                      # 50 km/h, seconds
    geoms = [np.array([[lon[u], lat[u]], [lon[v], lat[v]]]) for u, v in zip(U, V)]
    p = tmp_path / "toy.npz"
    np.savez(p, node_lat=lat, node_lon=lon, indptr=np.r_[0, np.cumsum(np.bincount(U, minlength=3))],
             indices=V.astype(np.int32), length_m=L.astype(np.float32),
             travel_time_s=T.astype(np.float32), geom_ptr=np.r_[0, np.cumsum([len(g) for g in geoms])],
             geom_xy=np.vstack(geoms))
    return roads.RoadNetwork(p, cache=None), lat, lon, L


def test_one_way_makes_matrix_asymmetric(toy):
    net, lat, lon, L = toy
    m, t = net.matrix(lat[:2], lon[:2])
    assert m[0, 1] == pytest.approx(L[0], rel=1e-3)               # A->B direct
    assert m[1, 0] == pytest.approx(L[1] + L[2], rel=1e-3)        # B->A must go round via C
    assert t[1, 0] > t[0, 1] > 0
    # winter factor applied to OSM travel time
    assert t[0, 1] == pytest.approx(L[0] / (50_000 / 60) / roads.WINTER_SPEED_FACTOR, rel=1e-3)
    # adding a point later (one row + column) gives the same numbers
    m3, _ = net.matrix(lat, lon)
    assert m3[1, 0] == pytest.approx(m[1, 0]) and len(net.nodes) == 3


def test_path_follows_directed_edges(toy):
    net, lat, lon, _ = toy
    p = net.path([lat[1], lat[0]], [lon[1], lon[0]])              # B -> A goes via C
    assert p[0] == [lon[1], lat[1]] and p[-1] == [lon[0], lat[0]]
    assert [lon[2], lat[2]] in p


def test_fallback_without_road_cache(monkeypatch):
    monkeypatch.setattr(roads, "_NET", None)
    monkeypatch.setattr(roads, "_LOADED", True)
    lat, lon = [51.05, 51.06], [-114.07, -114.09]
    m, t = roads.matrix(lat, lon)
    hv = haversine_m(lat[0], lon[0], lat[1], lon[1]) * roads.ROAD_FACTOR
    assert m[0, 1] == pytest.approx(hv) and m[1, 0] == pytest.approx(hv)
    assert t[0, 1] == pytest.approx(hv / roads.SPEED_M_PER_MIN)
    assert roads.path(lat, lon) == [[-114.07, 51.05], [-114.09, 51.06]]
    assert roads.method() == "haversine_fallback"


@pytest.mark.skipif(not roads.GRAPH_NPZ.exists(), reason="run scripts/build_roads.py")
def test_real_calgary_network():
    net = roads.RoadNetwork(cache=None)
    lat, lon = [51.0447, 51.0607, 50.95], [-114.0719, -114.1035, -114.0]
    m, t = net.matrix(lat, lon)
    hv = haversine_m(np.array(lat)[:, None], np.array(lon)[:, None],
                     np.array(lat)[None], np.array(lon)[None])
    off = ~np.eye(3, dtype=bool)
    assert (m[off] >= hv[off]).all() and (m[off] < 3 * hv[off]).all()
    assert (t[off] > 0).all()
    p = net.path(lat, lon)
    assert len(p) > 20
    assert haversine_m(p[0][1], p[0][0], lat[0], lon[0]) < 1
    assert haversine_m(p[-1][1], p[-1][0], lat[-1], lon[-1]) < 1
    # every vertex is near the road network or a stop (no long straight jumps off-road)
    seg = haversine_m(np.array(p)[:-1, 1], np.array(p)[:-1, 0], np.array(p)[1:, 1], np.array(p)[1:, 0])
    assert seg.max() < 2_000
