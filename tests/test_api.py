"""End-to-end API check on the real data (skipped if data has not been pulled)."""
import time

import pytest

from civicsignal import features as F

pytestmark = pytest.mark.skipif(not (F.DATA / "poles.csv").exists(), reason="run pull_data.py")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from civicsignal.api import app
    with TestClient(app) as c:
        yield c


def test_ticket_insertion_under_5s(client):
    t0 = time.time()
    r = client.post("/tickets", json={"service_name": "sidewalk", "lat": 51.0607, "lon": -114.1035})
    assert r.status_code == 200 and time.time() - t0 < 5
    j = r.json()
    assert j["inserted"] and j["delta_min"] > 0 and j["nearest_pole_id"]
    r2 = client.post("/tickets", json={"service_name": "sidewalk", "lat": 51.06072, "lon": -114.10352})
    assert r2.json()["duplicate_of"] == j["job_id"]


def test_caller_hazards_raise_rank(client):
    loc = {"service_name": "sidewalk", "lat": 51.0378, "lon": -114.1412}
    plain = client.post("/tickets", json=loc).json()
    flagged = client.post("/tickets", json={**loc, "lat": 51.0400,
                                            "hazard_notes": "walker user, next to a bus stop"}).json()
    assert flagged["risk_rank"] < plain["risk_rank"]
    assert flagged["reason"].startswith("caller reports mobility aid user, bus stop/transit")


def test_caller_hazard_words_are_whole_words():
    from civicsignal import risk as R
    assert R.caller_hazards("after the snowfall, outside a business") == []
    assert R.caller_hazards("my mom fell near the seniors home") == ["near seniors' residence", "recent fall"]


def test_rejects_missing_location(client):
    assert client.post("/tickets", json={"service_name": "sidewalk"}).status_code == 422


def test_disruption_and_briefing(client):
    r = client.post("/disruption", json={"crews_out": 3}).json()
    assert "jobs_moved" in r and r["crews_active"] == 14
    crew = client.get("/plan").json()["crews"][0]["id"]
    assert client.get(f"/briefing/{crew}").text.startswith(f"Unit {crew}")
