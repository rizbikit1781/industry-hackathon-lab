"""Landmark geocoding: local name index + mocked Nominatim fallback (no network in tests)."""
import pytest

from civicsignal import landmarks as L
from civicsignal.ingest import DATA

pytestmark = pytest.mark.skipif(not (DATA / "layers" / "schools.csv").exists(), reason="run pull_data.py")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real HTTP call fails the test; Nominatim cache starts empty."""
    def boom(*a, **k):
        raise AssertionError("network call in tests")
    monkeypatch.setattr(L.requests, "get", boom)
    L._cache.clear()
    monkeypatch.setattr(L, "_last", [0.0])


def match(q):
    r = L.resolve(q, use_network=False)
    assert r["status"] == "match", (q, r)
    return r["match"]


def test_university_of_calgary_bus_loop():
    for q in ["bus loop at the University of Calgary", "the bus loop at U of C",
              "heavy snowpack in front of the bus loop at the University of Calgary"]:
        m = match(q)
        assert m["name"].startswith("University of Calgary") and m["type"] == "post-secondary"
        assert abs(m["lat"] - 51.0789) < 0.005 and abs(m["lon"] + 114.1306) < 0.005
        assert m["score"] >= L.MATCH_MIN


def test_hospitals():
    assert match("Foothills hospital")["name"] == "Foothills Hospital"
    assert match("Foothills Medical Centre")["type"] == "hospital"
    assert match("Peter Lougheed hospital")["name"] == "Peter Lougheed Medical Centre"
    assert match("Rocky View hospital")["name"] == "Rockyview General Hospital"


def test_lrt_station_by_name():
    for q in ["Brentwood station", "Brentwood LRT", "Brentwood C-Train station"]:
        m = match(q)
        assert m["name"] == "Brentwood Station" and m["type"] == "transit station"
        assert abs(m["lat"] - 51.0866) < 0.01


def test_mount_royal_is_ambiguous_but_mru_is_not():
    # Documented rule: "Mount Royal" alone matches Mount Royal School and Mount Royal University
    # equally well -> ambiguous (agent asks). Saying "university" or "MRU" picks the university.
    r = L.resolve("Mount Royal", use_network=False)
    assert r["status"] == "ambiguous"
    names = [c["name"] for c in r["candidates"]]
    assert "Mount Royal University" in names and "Mount Royal School" in names
    assert match("MRU")["name"] == "Mount Royal University"
    assert match("Mount Royal University")["name"] == "Mount Royal University"


def test_gibberish_and_filler_only_give_no_match():
    assert L.resolve("flurble wimbo zzq", use_network=False) == {"status": "none"}
    assert L.resolve("the bus loop", use_network=False) == {"status": "none"}
    assert L.resolve("", use_network=False) == {"status": "none"}


class FakeResp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_nominatim_fallback_bounded_and_cached(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params)
        assert "SnowTech" in headers["User-Agent"] and timeout <= 3
        assert params["bounded"] == 1 and params["countrycodes"] == "ca" and params["limit"] == 3
        return FakeResp([{"lat": "45.5", "lon": "-73.6", "name": "Chinook Centre Montreal"},   # outside
                         {"lat": "50.99797", "lon": "-114.07359", "name": "Chinook Centre",
                          "type": "mall"}])
    monkeypatch.setattr(L.requests, "get", fake_get)
    r = L.resolve("near Chinook mall")
    assert r["status"] == "match" and r["match"]["name"] == "Chinook Centre"
    assert r["match"]["source"] == "nominatim" and calls[0]["q"] == "chinook mall"
    L.resolve("near Chinook mall")
    assert len(calls) == 1                     # cached


def test_nominatim_network_failure_is_no_match(monkeypatch):
    def down(*a, **k):
        raise L.requests.ConnectionError("offline")
    monkeypatch.setattr(L.requests, "get", down)
    assert L.resolve("Chinook mall") == {"status": "none"}
