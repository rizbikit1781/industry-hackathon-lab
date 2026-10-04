"""Fetch Open-Meteo surface history for the 3x3 feature grid, May–Sep 2006–2025."""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hailday.openmeteo import fetch_year, grid_points  # noqa: E402

YEARS = range(2006, 2026)

if __name__ == "__main__":
    jobs = [(lat, lon, y) for lat, lon in grid_points() for y in YEARS]
    with ThreadPoolExecutor(max_workers=1) as pool:
        frames = list(pool.map(lambda j: fetch_year(*j), jobs))
    print(f"fetched {len(frames)} point-years, {sum(len(f) for f in frames)} hourly rows")
