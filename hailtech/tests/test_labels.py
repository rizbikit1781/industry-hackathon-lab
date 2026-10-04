import pandas as pd

from hailday.labels import daily_labels, load_reports


def test_utc_report_after_midnight_belongs_to_previous_local_day():
    reports = load_reports()
    late = reports[reports["utc"].dt.hour < 6].iloc[0]
    assert late["local_date"] == (late["utc"] - pd.Timedelta(hours=6)).date()


def test_severe_day_count_matches_reference():
    labels = daily_labels(load_reports())
    # hail-sme-report.md computed 170 severe days for this box from the same CSV.
    assert 160 <= labels["severe"].sum() <= 180
    assert labels.loc[labels["year"] == 2005, "severe"].sum() <= 2
    assert set(labels["date"].dt.month) == {5, 6, 7, 8, 9}
