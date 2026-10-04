"""Build features (optional), run the leave-one-year-out backtest, fit the final model.

Usage: python scripts/train.py --source openmeteo [--build] [--fast]
"""
import argparse
import json
import sys
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hailday import features  # noqa: E402
from hailday.config import MODELS, PROCESSED  # noqa: E402
from hailday.model import CalibratedHailDay, backtest  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--source", default="openmeteo", choices=["openmeteo", "era5"])
ap.add_argument("--build", action="store_true", help="rebuild features_<source>.parquet first")
ap.add_argument("--fast", action="store_true", help="skip isotonic calibration (quick look)")
args = ap.parse_args()

path = PROCESSED / f"features_{args.source}.parquet"
df = features.build(args.source) if args.build or not path.exists() else pd.read_parquet(path)
nan = df[features.feature_columns(df)].isna().sum().sum()
print(f"features: {len(df)} days x {len(features.feature_columns(df))} cols, NaN cells {nan}")

results, oof = backtest(df, args.source, fast=args.fast)
meta = results["_meta"]
print(f"backtest {meta['years'][0]}-{meta['years'][-1]}, {meta['n_days']} days, {meta['n_severe']} severe")
print(f"{'policy':14s} {'AUC':>6s} {'Brier':>7s} {'POD':>5s} {'FAR':>5s} {'CSI':>5s} {'cutoff':>7s}")
for name in ("climatology", "single_index", "hailday"):
    r = results[name]
    print(f"{name:14s} {r['auc']:6.3f} {r['brier']:7.4f} {r['pod']:5.2f} {r['far']:5.2f} {r['csi']:5.2f} {r['cutoff']:7.3f}")

suffix = "_fast" if args.fast else ""
(PROCESSED / f"backtest_{args.source}{suffix}.json").write_text(json.dumps(results, indent=2))
oof.to_parquet(PROCESSED / f"oof_{args.source}{suffix}.parquet", index=False)

if not args.fast:
    lab = df[df["severe"].notna()]
    MODELS.mkdir(exist_ok=True)
    lab = lab.assign(severe=lab["severe"].astype(int))
    joblib.dump({"model": CalibratedHailDay(meta["features"]).fit(lab), "features": meta["features"],
                 "cutoff": results["hailday"]["cutoff"]},
                MODELS / f"hailday_{args.source}.joblib")
    print(f"saved models/hailday_{args.source}.joblib")
