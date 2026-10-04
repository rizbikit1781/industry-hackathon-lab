import numpy as np
import pandas as pd

from hailday.assets import dollar_backtest, protect
from hailday.mesh import Mesh


def test_cost_loss_rule():
    assert protect(0.001, 8e6, 4000)          # 8,000 >= 4,000
    assert not protect(0.0001, 8e6, 4000)     # 800 < 4,000


def tiny_mesh():
    dates = pd.to_datetime(["2021-07-01", "2021-07-02", "2022-07-01", "2022-07-02"])
    cube = np.full((4, 3, 3), -1, dtype=np.int16)
    cube[0, 1, 1] = 40     # one hit on 2021-07-01
    cube[2, 0, 0] = 35     # one hit on 2022-07-01
    return Mesh(dates, cube, lats=np.array([51.2, 51.1, 51.0]), lons=np.array([-114.2, -114.1, -114.0]))


def test_backtest_bounds():
    m = tiny_mesh()
    p = pd.Series([1.0, 0.0, 1.0, 0.0], index=m.dates)
    bt = dollar_backtest(m, p, {"oracle": p}, value_at_risk=1e6, protect_cost=1.0).set_index("policy")
    assert bt.loc["never", "share_of_perfect_value"] == 0
    assert bt.loc["oracle", "total_cost"] <= bt.loc["never", "total_cost"]
    assert bt.loc["always", "hits_protected"] == bt.loc["always", "hits"]
