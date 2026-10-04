"""Fixed study constants. Values come from hail-sme-report.md and hackathon-strategy.md v3."""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
MODELS = ROOT / "models"

ICHD_URL = "https://zenodo.org/api/records/8015925/files/integrated_canadian_hail_db.csv/content"
ICHD_CSV = RAW / "hail.csv"
COMMUNITIES_CSV = DATA / "neighbourhoods_hail_scenario.csv"
ASSETS_CSV = DATA / "assets.csv"

# (lat_min, lat_max, lon_min, lon_max)
LABEL_BOX = (50.4, 51.7, -114.9, -113.2)    # Cochrane–Strathmore, Airdrie–High River
FEATURE_BOX = (49.5, 52.5, -115.5, -112.0)  # adds the foothills initiation zone upstream

LABEL_YEARS = range(2006, 2023)   # ICHD v1.0.0 covers 2005–2022; 2005 dropped (1 severe day, incomplete)
CASE_YEARS = range(2023, 2026)    # outside ICHD; blind case studies (5 Aug 2024)
MONTHS = range(5, 10)             # May–Sep

SEVERE_MM = 20.0                  # ECCC severe-hail threshold
TZ = "America/Edmonton"
MORNING_UTC = 12                  # 06 MDT: the forecast state
NOON_UTC = 18                     # 12 MDT: the update

# NOAA MRMS MESH (public domain). The 1440-min max stamped 06 UTC on day D+1 covers MDT day D.
MESH_URL = (
    "https://noaa-mrms-pds.s3.amazonaws.com/CONUS/MESH_Max_1440min_00.50/"
    "{d:%Y%m%d}/MRMS_MESH_Max_1440min_00.50_{d:%Y%m%d}-060000.grib2.gz"
)
MESH_YEARS = range(2020, 2026)    # AWS archive starts 2020-10-14; 2020 summer comes from Iowa State
# Iowa State 2020 files are named MRMS_Max_1440min_00.50_<D+1>-12xxxx (24 h ending ~12 UTC,
# i.e. 06 MDT D to 06 MDT D+1). Still spans every afternoon storm on day D.
MESH_IASTATE_DIR = "https://mtarchive.geol.iastate.edu/{d:%Y/%m/%d}/mrms/ncep/MESH_Max_1440min/"
MESH_SIZES_MM = (20, 30, 50)
# Canadian radar feed to MRMS was down; MESH over Calgary is unreliable in this window.
MESH_OUTAGE = (date(2023, 6, 5), date(2023, 11, 28))
