"""Write small synthetic fixture files that match the pipeline's output schemas.

Fixtures are for developing the dashboard only. The app uses them only when HAILDAY_FIXTURES=1 and the real
file is missing, and it labels every fixture-backed panel as such.

Run:  .venv/bin/python app/fixtures/make_fixtures.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RNG = np.random.default_rng(42)


def _write(rel, obj):
    p = HERE / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1))


def _rel(n_bins=10, sharp=1.0):
    out = []
    for k in range(n_bins):
        mid = (k + 0.5) / n_bins
        n = int(400 * np.exp(-4 * mid)) + 3
        obs = float(np.clip(mid + (0.5 - mid) * (1 - sharp) * 0.6 + RNG.normal(0, 0.03), 0, 1))
        out.append({"bin_mid": round(mid, 3), "n": n, "forecast": round(mid * 0.95, 3), "observed": round(obs, 3)})
    return out


def backtest():
    base = 168 / 2601
    models = {
        "climatology": dict(auc=0.62, brier=0.059, cutoff=0.08, hits=60, misses=108, false_alarms=500, sharp=0.2),
        "single_index": dict(auc=0.74, brier=0.055, cutoff=0.12, hits=95, misses=73, false_alarms=420, sharp=0.6),
        "hailday": dict(auc=0.83, brier=0.049, cutoff=0.15, hits=118, misses=50, false_alarms=310, sharp=0.9),
    }
    out = {}
    for k, m in models.items():
        h, mi, fa = m["hits"], m["misses"], m["false_alarms"]
        out[k] = {"auc": m["auc"], "brier": m["brier"], "base_rate": round(base, 4), "cutoff": m["cutoff"],
                  "hits": h, "misses": mi, "false_alarms": fa, "pod": round(h / (h + mi), 3),
                  "far": round(fa / (h + fa), 3), "csi": round(h / (h + mi + fa), 3),
                  "reliability": _rel(sharp=m["sharp"])}
    out["_meta"] = {"source": "era5", "years": [2006, 2022], "n_days": 2601, "n_severe": 168,
                    "features": ["cape_max", "cin_min", "shear_0_6km", "wmaxshear", "ship", "wbz_height",
                                 "lapse_700_500", "pwat"]}
    _write("backtest_era5.json", out)


def oof():
    dates = pd.date_range("2006-05-01", "2022-09-30", freq="D")
    dates = dates[dates.month.isin([5, 6, 7, 8, 9])]
    n = len(dates)
    severe = RNG.random(n) < 0.065
    z = RNG.normal(0, 1, n) + 1.6 * severe
    p_h = 1 / (1 + np.exp(-(z * 1.2 - 3.2)))
    p_s = 1 / (1 + np.exp(-(z * 0.7 + RNG.normal(0, 0.6, n) - 3.0)))
    clim = pd.Series(dates.month).map({5: 0.03, 6: 0.09, 7: 0.10, 8: 0.07, 9: 0.02}).to_numpy()
    df = pd.DataFrame({"date": dates, "year": dates.year, "severe": severe.astype(int),
                       "p_climatology": clim, "p_single_index": p_s, "p_hailday": p_h})
    df.to_parquet(HERE / "oof_era5.parquet", index=False)


def dollars():
    never = 4_000_000_000.0
    perfect = 18_000_000.0
    rows = []
    for policy, share, prot, hp in [("never", 0.0, 0, 0), ("always", -0.9, 9_000_000, 1000),
                                    ("climatology", 0.08, 2_100_000, 380), ("single_index", 0.21, 1_400_000, 520),
                                    ("hailday", 0.37, 900_000, 610), ("oracle_day", 0.71, 300_000, 1000)]:
        val = share * (never - perfect)
        rows.append({"policy": policy, "total_cost": never - val, "protections": prot, "hits": 1000,
                     "hits_protected": hp, "value_vs_never": val, "share_of_perfect_value": share})
    _write("dollar_backtest_era5.json", {"attrs": {"n_days": 918, "n_cells": 23000, "value_at_risk": 4_000_000,
                                                   "protect_cost": 4000, "size_mm": 30}, "rows": rows})


def _hit_rates(assets):
    try:
        z = np.load(ROOT / "data/processed/mesh_hit_rates.npz")
        lats, lons, p = z["lats"], z["lons"], z["p_hit_30"]
        return [float(p[np.abs(lats - a.latitude).argmin(), np.abs(lons - a.longitude).argmin()])
                for a in assets.itertuples()]
    except Exception:
        return list(RNG.uniform(0.01, 0.06, len(assets)))


def scores():
    a = pd.read_csv(ROOT / "data/assets.csv")
    phit = _hit_rates(a)
    days = {
        "2024-08-05": dict(p=0.72, pc=0.09, ps=0.31, obs_ne=True),
        "2020-06-13": dict(p=0.58, pc=0.10, ps=0.44, obs_ne=True),
        "2021-08-19": dict(p=0.04, pc=0.07, ps=0.06, obs_ne=False),
    }
    feats = {
        "2024-08-05": [("cape_max", 2350, "J/kg, top 5% of summer mornings"), ("shear_0_6km", 21.0, "m/s, organised storms"),
                       ("wbz_height", 2.6, "km AGL, hail survives the fall"), ("cin_min", -45, "J/kg, weak cap")],
        "2020-06-13": [("cape_max", 1900, "J/kg"), ("shear_0_6km", 24.0, "m/s"), ("wbz_height", 2.4, "km AGL")],
        "2021-08-19": [("cape_max", 180, "J/kg, stable"), ("shear_0_6km", 8.0, "m/s, weak")],
    }
    for d, s in days.items():
        rows = []
        for r, ph in zip(a.itertuples(), phit):
            pa = s["p"] * ph
            ne = r.latitude > 51.06
            obs = int(RNG.integers(30, 70)) if (s["obs_ne"] and ne and RNG.random() < 0.6) else int(RNG.integers(0, 12))
            rows.append({"asset_id": r.asset_id, "name": r.name, "category": r.category,
                         "latitude": r.latitude, "longitude": r.longitude, "p_hit_given_day": round(ph, 5),
                         "p_asset": round(pa, 5), "protect": bool(pa * r.value_at_risk >= r.protect_cost),
                         "expected_loss": round(pa * r.value_at_risk, 2), "value_at_risk": int(r.value_at_risk),
                         "protect_cost": int(r.protect_cost), "observed_mesh_mm": obs})
        _write(f"scores/{d}.json", {
            "date": d, "source": "era5", "p_day": s["p"], "p_day_climatology": s["pc"],
            "p_day_single_index": s["ps"], "state_day": "PREPARE" if s["p"] >= 0.3 else "MONITOR",
            "top_features": [{"name": n, "value": v, "note": t} for n, v, t in feats[d]], "assets": rows})


def nowcast():
    a = pd.read_csv(ROOT / "data/assets.csv")
    lats = np.round(np.arange(51.30, 50.80, -0.01), 3)
    lons = np.round(np.arange(-114.40, -113.70, 0.01), 3)
    issues = pd.date_range("2024-08-06T00:00Z", "2024-08-06T01:30Z", freq="10min")
    iso = [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in issues]
    leads = [0, 10, 20, 30, 45]
    # one storm moving east-northeast across north Calgary at ~45 km/h
    lat0, lon0, u, v = 51.17, -114.30, 40.0, 12.0
    kx, ky = 111.0 * np.cos(np.radians(51.05)), 111.0

    def centre(t_min):
        return lat0 + v * t_min / 60 / ky, lon0 + u * t_min / 60 / kx

    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    obs = np.zeros((len(issues), len(lats), len(lons)), np.int16)
    fc = np.zeros((len(issues), len(leads), len(lats), len(lons)), np.uint8)
    storms = []
    for i, t in enumerate(issues):
        tm = (t - issues[0]).total_seconds() / 60
        cy, cx = centre(tm)
        d2 = ((LA - cy) * ky) ** 2 + ((LO - cx) * kx) ** 2
        obs[i] = np.clip(65 * np.exp(-d2 / (2 * 4.0 ** 2)), 0, None).astype(np.int16)
        for j, L in enumerate(leads):
            fy, fx = centre(tm + L)
            d2f = ((LA - fy) * ky) ** 2 + ((LO - fx) * kx) ** 2
            sig = 4.0 + 0.12 * L
            fc[i, j] = np.clip(100 * (0.9 - 0.005 * L) * np.exp(-d2f / (2 * sig ** 2)), 0, 100).astype(np.uint8)
        storms.append({"issue_time": iso[i], "storm_id": "S1", "lat": round(cy, 4), "lon": round(cx, 4),
                       "u_kmh": u, "v_kmh": v, "area_km2": 180.0, "max_mesh_mm": int(obs[i].max()),
                       "max_posh": 0.9, "echo_top50_km": 11.5})
    assets_out, per = [], {"nowcast": {}, "persistence": {}, "mesh_only": {}}
    caught = {"nowcast": [], "persistence": [], "mesh_only": []}
    for r in a.itertuples():
        yi, xi = np.abs(lats - r.latitude).argmin(), np.abs(lons - r.longitude).argmin()
        series = obs[:, yi, xi]
        first = next((iso[i] for i in range(len(iso)) if series[i] >= 30), None)
        tl = []
        for i in range(len(iso)):
            p30 = float(fc[i, :, yi, xi].max()) / 100
            state = "TRIGGER" if p30 >= 0.5 else "ARM" if p30 >= 0.2 else "CLEAR"
            lead_hit = next((L for j, L in enumerate(leads) if fc[i, j, yi, xi] >= 50), None)
            arr = None if lead_hit is None else (issues[i] + pd.Timedelta(minutes=lead_hit))
            fmt = (lambda x: None if x is None else x.strftime("%Y-%m-%dT%H:%M:%SZ"))
            tl.append({"issue_time": iso[i], "state": state, "p20": round(min(1, p30 * 1.2), 3), "p30": round(p30, 3),
                       "p50": round(p30 * 0.4, 3), "arrival_earliest": fmt(arr and arr - pd.Timedelta(minutes=5)),
                       "arrival_likely": fmt(arr), "arrival_latest": fmt(arr and arr + pd.Timedelta(minutes=10)),
                       "ev_trigger": round(p30 * r.value_at_risk, 0)})
        assets_out.append({"asset_id": r.asset_id, "name": r.name, "category": r.category, "lat": r.latitude,
                           "lon": r.longitude, "timeline": tl,
                           "observed": {"first_ge30_time": first, "max_mesh_mm": int(series.max())}})
        fa = next((x["issue_time"] for x in tl if x["state"] in ("ARM", "TRIGGER")), None)
        ft = next((x["issue_time"] for x in tl if x["state"] == "TRIGGER"), None)
        lead = None
        if first and ft:
            lead = (pd.Timestamp(first) - pd.Timestamp(ft)).total_seconds() / 60
        per["nowcast"][r.asset_id] = {"first_arm": fa, "first_trigger": ft, "lead_min": lead}
        if first:
            caught["nowcast"].append(lead if lead is not None and lead >= 0 else None)
        # persistence / mesh-only: alert only once hail is already overhead (lead ~0 or 10 min)
        per["persistence"][r.asset_id] = {"first_arm": first, "first_trigger": first, "lead_min": 10.0 if first else None}
        per["mesh_only"][r.asset_id] = {"first_arm": first, "first_trigger": first, "lead_min": 0.0 if first else None}
        if first:
            caught["persistence"].append(10.0)
            caught["mesh_only"].append(0.0)
    n_hit = len(caught["nowcast"])
    ev = {}
    for k in per:
        leads_ok = [x for x in caught[k] if x is not None]
        ev[k] = {"hits_caught": len(leads_ok), "hits_total": n_hit,
                 "median_lead_min": float(np.median(leads_ok)) if leads_ok else None,
                 "false_alarms": {"nowcast": 2, "persistence": 1, "mesh_only": 0}[k], "per_asset": per[k]}
    rel_npz = "replay_2024-08-05_fields.npz"
    _write("nowcast/replay_2024-08-05.json", {
        "event": "2024-08-05 north Calgary hailstorm (SYNTHETIC FIXTURE)", "window_utc": [iso[0], iso[-1]],
        "issue_times": iso, "leads_min": leads, "grid": {"npz": rel_npz, "lats": lats.tolist(), "lons": lons.tolist()},
        "storms": storms, "assets": assets_out, "evaluation": ev,
        "thresholds": {"arm_p30": 0.2, "trigger_p30": 0.5, "hit_mm": 30},
        "notes": ["Synthetic fixture for UI development; not real MRMS data."]})
    np.savez_compressed(HERE / "nowcast" / rel_npz, issue_times=np.array(iso), obs_mesh=obs, fcst_p30=fc)


if __name__ == "__main__":
    backtest(); oof(); dollars(); scores(); nowcast()
    print("fixtures written to", HERE)
