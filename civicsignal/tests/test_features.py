"""Smoke tests on the real layers (skipped if scripts/pull_data.py has not been run)."""
import pytest

from civicsignal import features as F

pytestmark = pytest.mark.skipif(not (F.LAYERS / "schools.csv").exists(), reason="run pull_data.py")


def test_foothills_hospital_scores_high():
    f = F.features_at(51.0650, -114.1330)          # beside Foothills Medical Centre
    assert f["hospital"] > 0.5


def test_seniors_heavy_community_scores_high():
    _, comm, _, _ = F.load_grid()
    assert comm.loc["VAR", "seniors_share"] > 0.8  # Varsity: 23.5% aged 65+ (2019 census)


def test_ped_proxy_validation_runs():
    v = F.ped_proxy_validation()
    assert v["n_sites"] >= 10 and -1 <= v["spearman"] <= 1
