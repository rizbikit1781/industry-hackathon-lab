"""Policies and leave-one-year-out backtest for the regional P(hail day) model.

A policy maps (train, test) -> (honest scores on train, scores on test). Cutoffs are chosen
on the train scores only, so no test year influences its own operating point.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from hailday.features import feature_columns
from hailday.metrics import best_csi_cutoff, reliability, summary

SINGLE_INDEX = {"era5": "wmaxshear_max_12", "openmeteo": "dew_point_2m_max_12"}


def climatology(train, test):
    rate = train.groupby(train["date"].dt.month)["severe"].mean()
    score = lambda d: d["date"].dt.month.map(rate).fillna(train["severe"].mean()).to_numpy()
    return score(train), score(test)


def single_index(col):
    def policy(train, test):
        # Map the raw index to a probability by its empirical hit rate in training deciles.
        bins = np.unique(np.quantile(train[col].dropna(), np.linspace(0, 1, 11)))
        tr = pd.cut(train[col], bins, include_lowest=True)
        rate = train.groupby(tr, observed=False)["severe"].mean()

        def score(d):
            b = pd.cut(d[col].clip(bins[0], bins[-1]), bins, include_lowest=True)
            return b.map(rate).astype(float).fillna(train["severe"].mean()).to_numpy()
        return score(train), score(test)
    return policy


def fit_hailday(train, cols, seed=0):
    X, y = train[cols], train["severe"].to_numpy()
    w = np.where(y == 1, (y == 0).sum() / max(y.sum(), 1), 1.0)
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                         min_samples_leaf=30, l2_regularization=1.0, random_state=seed)
    clf.fit(X, y, sample_weight=w)
    return clf


class CalibratedHailDay:
    """Boosted trees + isotonic map fitted on inner leave-one-year-out scores (no in-sample leakage)."""

    def __init__(self, cols):
        self.cols = cols

    def fit(self, train):
        raw = np.zeros(len(train))
        for yr in train["year"].unique():
            m = (train["year"] == yr).to_numpy()
            raw[m] = fit_hailday(train[~m], self.cols).predict_proba(train.loc[m, self.cols])[:, 1]
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(raw, train["severe"])
        self.train_oof = self.iso.predict(raw)  # honest training scores, used to pick the cutoff
        self.clf = fit_hailday(train, self.cols)
        return self

    def predict(self, df):
        return self.iso.predict(self.clf.predict_proba(df[self.cols])[:, 1])


def hailday(cols):
    def policy(train, test):
        model = CalibratedHailDay(cols).fit(train)
        # In-sample tree scores are overconfident; the inner-LOYO scores are the honest train scores.
        return model.train_oof, model.predict(test)
    return policy


def backtest(df: pd.DataFrame, source: str, fast: bool = False) -> dict:
    lab = df[df["severe"].notna()].copy()
    lab["severe"] = lab["severe"].astype(int)
    cols = feature_columns(lab)
    policies = {"climatology": climatology, "single_index": single_index(SINGLE_INDEX[source]),
                "hailday": hailday(cols)}
    years = sorted(lab["year"].unique())
    oof = {k: np.zeros(len(lab)) for k in policies}
    cut = {k: [] for k in policies}
    for yr in years:
        test_m = (lab["year"] == yr).to_numpy()
        train, test = lab[~test_m], lab[test_m]
        for name, pol in policies.items():
            if fast and name == "hailday":
                # Quick look: raw boosted scores, cutoff from (overconfident) train scores.
                clf = fit_hailday(train, cols)
                p_tr, oof[name][test_m] = (clf.predict_proba(d[cols])[:, 1] for d in (train, test))
            else:
                p_tr, oof[name][test_m] = pol(train, test)
            cut[name].append(best_csi_cutoff(train["severe"], p_tr))
    y = lab["severe"].to_numpy()
    results = {name: {**summary(y, oof[name], float(np.median(cut[name]))),
                      "reliability": reliability(y, oof[name])} for name in policies}
    results["_meta"] = {"source": source, "years": [int(v) for v in years], "n_days": int(len(lab)),
                        "n_severe": int(y.sum()), "features": cols}
    lab = lab.assign(**{f"p_{k}": v for k, v in oof.items()})
    return results, lab[["date", "year", "severe"] + [f"p_{k}" for k in policies]]
