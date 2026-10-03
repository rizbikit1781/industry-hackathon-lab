"""Duplicate clustering: DBSCAN (haversine, precomputed sparse) with a time window, per service.

A pair of tickets is linked when they share `service_name`, are within `eps_m` metres and within
`days` days of each other. DBSCAN with min_samples=1 on that sparse graph = connected components,
so each cluster becomes one job.

Caveat measured in `validate()`: the public 311 feed publishes every snow/ice ticket at its
*community centrepoint*, not the address. So on historical data "within 50 m" means "same
community", and the clusters are community work packages, not true duplicates.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree

EARTH_R = 6_371_000.0


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


def _labels_one_service(df: pd.DataFrame, eps_m: float, days: int) -> np.ndarray:
    n = len(df)
    if n == 0:
        return np.array([], dtype=int)
    X = np.radians(df[["lat", "lon"]].to_numpy())
    day = (df["requested_date"] - df["requested_date"].min()).dt.days.to_numpy()
    tree = BallTree(X, metric="haversine")
    rows, cols, vals = [], [], []
    # query per day so the candidate set stays small even when many tickets share a point
    for d in np.unique(day):
        q = np.where(day == d)[0]
        ind, dist = tree.query_radius(X[q], r=eps_m / EARTH_R, return_distance=True)
        for i, nb, ds in zip(q, ind, dist):
            keep = np.abs(day[nb] - d) <= days
            nb, ds = nb[keep], ds[keep]
            rows.extend([i] * len(nb))
            cols.extend(nb.tolist())
            vals.extend((ds * EARTH_R + 1e-6).tolist())   # explicit tiny value: 0 m is still a link
    D = coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()
    return DBSCAN(eps=eps_m + 1e-3, min_samples=1, metric="precomputed").fit_predict(D)


def assign_clusters(tickets: pd.DataFrame, eps_m: float = 50, days: int = 2) -> pd.Series:
    """Cluster label per ticket (string `service|n`), NaN-location tickets get their own label."""
    t = tickets.rename(columns={"latitude": "lat", "longitude": "lon"})
    labels = pd.Series(index=t.index, dtype=object)
    for svc, g in t.groupby("service_name"):
        ok = g.dropna(subset=["lat", "lon"])
        lab = _labels_one_service(ok, eps_m, days)
        labels.loc[ok.index] = [f"{svc}|{x}" for x in lab]
        for i in g.index.difference(ok.index):
            labels.loc[i] = f"{svc}|solo{i}"
    return labels


def cluster(tickets: pd.DataFrame, eps_m: float = 50, days: int = 2) -> pd.DataFrame:
    """Return one row per job: report_count, first requested_date, centroid, members."""
    t = tickets.copy()
    t["cluster"] = assign_clusters(t, eps_m, days)
    t = t.rename(columns={"latitude": "lat", "longitude": "lon"})
    jobs = (t.sort_values(["requested_date", "service_request_id"])
             .groupby("cluster", sort=False)
             .agg(service_name=("service_name", "first"),
                  comm_code=("comm_code", lambda s: s.mode().iat[0] if s.notna().any() else None),
                  first_requested=("requested_date", "min"),
                  report_count=("service_request_id", "size"),
                  lat=("lat", "mean"), lon=("lon", "mean"),
                  members=("service_request_id", list))
             .reset_index())
    return jobs


def validate(tickets: pd.DataFrame, eps_m: float = 50, days: int = 2) -> dict:
    """Score predicted duplicates against the City's `Duplicate (...)` status labels.

    Predicted duplicate = any cluster member that is not the earliest report in its cluster.
    """
    t = tickets.dropna(subset=["latitude", "longitude"]).copy()
    t["cluster"] = assign_clusters(t, eps_m, days)
    t = t.sort_values(["requested_date", "service_request_id"])
    t["pred_dup"] = t.duplicated("cluster", keep="first")
    t["true_dup"] = t["status_description"].fillna("").str.startswith("Duplicate")
    tp = int((t.pred_dup & t.true_dup).sum())
    pred, true = int(t.pred_dup.sum()), int(t.true_dup.sum())
    base = true / len(t)
    precision = tp / pred if pred else 0.0
    return {
        "eps_m": eps_m, "days": days, "tickets": int(len(t)),
        "city_duplicates": true, "predicted_duplicates": pred, "true_positives": tp,
        "recall": tp / true if true else 0.0, "precision": precision,
        "base_rate": base, "lift_over_random": precision / base if base else 0.0,
        "distinct_points": int(t[["latitude", "longitude"]].drop_duplicates().shape[0]),
        "pct_community_centrepoint": float((t["location_type"] == "Community Centrepoint").mean()),
    }


def find_duplicate(jobs: pd.DataFrame, lat: float, lon: float, service_name: str,
                   eps_m: float = 50) -> str | None:
    """Live check for a new (voice) ticket: nearest open job of the same service within eps_m."""
    j = jobs[jobs["service_name"] == service_name]
    if j.empty:
        return None
    d = haversine_m(lat, lon, j["lat"].to_numpy(), j["lon"].to_numpy())
    i = int(np.argmin(d))
    return str(j.iloc[i]["job_id"]) if d[i] <= eps_m else None
