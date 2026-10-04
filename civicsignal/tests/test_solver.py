import pandas as pd

from civicsignal.solver import Crew, insert_job, plan_day


def _jobs(n, skill, base=(51.05, -114.07), n_tickets=1, svc=10):
    return pd.DataFrame([{"job_id": f"{skill}{i}", "skill": skill, "lat": base[0] + 0.004 * (i % 5),
                          "lon": base[1] + 0.006 * (i // 5), "n_tickets": n_tickets,
                          "service_min": svc * n_tickets, "value": 1.0 + i * 0.01}
                         for i in range(n)])


def test_respects_ticket_capacity_and_shift():
    jobs = _jobs(30, "bylaw")
    crews = [Crew("B1", "bylaw", 51.05, -114.07, shift_min=120, capacity=8),
             Crew("B2", "bylaw", 51.05, -114.07, shift_min=480, capacity=5)]
    p = plan_day(jobs, crews, time_limit_s=1)
    assert len(p.routes["B1"]) <= 8 and len(p.routes["B2"]) <= 5
    assert p.crew_minutes["B1"] <= 120 and p.crew_minutes["B2"] <= 480
    assert len(p.dropped) >= 30 - 13


def test_skill_matching():
    jobs = pd.concat([_jobs(5, "bylaw"), _jobs(5, "roads", svc=20)], ignore_index=True)
    crews = [Crew("B1", "bylaw", 51.05, -114.07), Crew("R1", "roads", 51.05, -114.07)]
    p = plan_day(jobs, crews, time_limit_s=1)
    assert all(j.startswith("bylaw") for j in p.routes["B1"])
    assert all(j.startswith("roads") for j in p.routes["R1"])
    assert len(p.routes["B1"]) == 5 and len(p.routes["R1"]) == 5


def test_no_crew_of_skill_drops_jobs():
    jobs = _jobs(3, "roads", svc=20)
    p = plan_day(jobs, [Crew("B1", "bylaw", 51.05, -114.07)], time_limit_s=1)
    assert sorted(p.dropped) == sorted(jobs["job_id"])


def test_insert_job_returns_position_and_delta():
    jobs = _jobs(10, "bylaw")
    crews = [Crew("B1", "bylaw", 51.05, -114.07, capacity=20),
             Crew("B2", "bylaw", 51.07, -114.10, capacity=20)]
    p = plan_day(jobs, crews, time_limit_s=1)
    new = {"job_id": "NEW", "skill": "bylaw", "lat": 51.052, "lon": -114.072, "n_tickets": 1,
           "service_min": 10, "value": 2.0}
    r = insert_job(p, new, jobs, crews, time_limit_s=1)
    assert r["inserted"] and r["crew_id"] in ("B1", "B2")
    assert isinstance(r["position"], int) and r["delta_min"] > 0
    assert r["inserted_after"] is not None
