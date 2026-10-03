import pandas as pd

from civicsignal import dedupe


def _t(rows):
    return pd.DataFrame([{"service_request_id": f"T{i}", "service_name": s, "latitude": la,
                          "longitude": lo, "requested_date": pd.Timestamp(d), "comm_code": "X",
                          "status_description": st}
                         for i, (s, la, lo, d, st) in enumerate(rows)])

SVC = "Bylaw - Snow and Ice on Sidewalk"


def test_merges_pair_within_50m_2days():
    # ~30 m apart, 1 day apart
    t = _t([(SVC, 51.0500, -114.0700, "2025-11-25", "Closed"),
            (SVC, 51.05027, -114.0700, "2025-11-26", "Duplicate (Closed)")])
    jobs = dedupe.cluster(t)
    assert len(jobs) == 1 and jobs.iloc[0]["report_count"] == 2


def test_does_not_merge_500m_apart():
    t = _t([(SVC, 51.0500, -114.0700, "2025-11-25", "Closed"),
            (SVC, 51.0545, -114.0700, "2025-11-25", "Closed")])
    assert len(dedupe.cluster(t)) == 2


def test_does_not_merge_outside_time_window():
    t = _t([(SVC, 51.0500, -114.0700, "2025-11-20", "Closed"),
            (SVC, 51.0500, -114.0700, "2025-11-25", "Closed")])
    assert len(dedupe.cluster(t)) == 2


def test_does_not_merge_across_services():
    t = _t([(SVC, 51.0500, -114.0700, "2025-11-25", "Closed"),
            ("Roads - Snow and Ice Control", 51.0500, -114.0700, "2025-11-25", "Closed")])
    assert len(dedupe.cluster(t)) == 2


def test_validate_scores_labels():
    t = _t([(SVC, 51.0500, -114.0700, "2025-11-25", "Closed"),
            (SVC, 51.05027, -114.0700, "2025-11-26", "Duplicate (Closed)"),
            (SVC, 51.1000, -114.0700, "2025-11-26", "Closed")])
    t["location_type"] = "Address"
    r = dedupe.validate(t)
    assert r["recall"] == 1.0 and r["precision"] == 1.0
