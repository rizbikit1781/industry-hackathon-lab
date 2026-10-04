"""ICHD hail reports -> one row per local (MDT) day in the label box, May–Sep."""
import pandas as pd

from hailday.config import ICHD_CSV, LABEL_BOX, LABEL_YEARS, MONTHS, PROCESSED, SEVERE_MM, TZ


def load_reports(path=ICHD_CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["utc"] = pd.to_datetime(df["Start Time"], format="%m/%d/%Y %H:%M").dt.tz_localize("UTC")
    df["local_date"] = df["utc"].dt.tz_convert(TZ).dt.date
    df["diameter_mm"] = pd.to_numeric(df["Hail Diameter (mm)"], errors="coerce")
    lat0, lat1, lon0, lon1 = LABEL_BOX
    inside = df["Latitude"].between(lat0, lat1) & df["Longitude"].between(lon0, lon1)
    return df[(df["Province Code"].str.strip() == "AB") & inside].copy()


def daily_labels(reports: pd.DataFrame) -> pd.DataFrame:
    days = pd.DataFrame({"date": pd.date_range(f"{LABEL_YEARS.start}-01-01", f"{LABEL_YEARS.stop - 1}-12-31")})
    days = days[days["date"].dt.month.isin(MONTHS)]
    agg = (
        reports.assign(date=pd.to_datetime(reports["local_date"]))
        .groupby("date")
        .agg(n_reports=("diameter_mm", "size"), max_mm=("diameter_mm", "max"))
        .reset_index()
    )
    out = days.merge(agg, on="date", how="left")
    out["n_reports"] = out["n_reports"].fillna(0).astype(int)
    out["severe"] = (out["max_mm"] >= SEVERE_MM).astype(int)
    out["year"] = out["date"].dt.year
    out["doy"] = out["date"].dt.dayofyear
    return out[["date", "year", "doy", "n_reports", "max_mm", "severe"]]


def build() -> pd.DataFrame:
    labels = daily_labels(load_reports())
    PROCESSED.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(PROCESSED / "labels.parquet", index=False)
    return labels


if __name__ == "__main__":
    lab = build()
    print(f"days {len(lab)}, severe days {lab['severe'].sum()}, any-hail days {(lab['n_reports'] > 0).sum()}")
    print(lab.groupby("year")["severe"].sum().to_string())
