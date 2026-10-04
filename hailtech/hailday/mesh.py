"""Stage 2: per-cell P(asset hit | regional hail day) from NOAA MRMS MESH, 2020–2025.

A regional hail day is any MESH cell in LABEL_BOX >= SEVERE_MM. A cell is hit when its
MESH >= `size_mm` (30 mm by default: MESH runs hot against ground reports).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter

from hailday.config import LABEL_BOX, PROCESSED, SEVERE_MM

MISSING = -9
HIT_MM = 30
SMOOTH_CELLS = 3  # ~3 km at 0.01°


@dataclass
class Mesh:
    dates: pd.DatetimeIndex
    cube: np.ndarray   # int16 [day, lat, lon], mm
    lats: np.ndarray   # descending
    lons: np.ndarray

    @classmethod
    def load(cls, path=PROCESSED / "mesh_daily.npz"):
        z = np.load(path)
        return cls(pd.to_datetime(z["dates"]), z["mesh"], z["lats"], z["lons"])

    @property
    def valid(self):
        return (self.cube != MISSING).any(axis=(1, 2))

    def label_box_mask(self):
        lat0, lat1, lon0, lon1 = LABEL_BOX
        return np.outer((self.lats >= lat0) & (self.lats <= lat1), (self.lons >= lon0) & (self.lons <= lon1))

    def regional_days(self):
        box = self.label_box_mask()
        return self.valid & (self.cube[:, box] >= SEVERE_MM).any(axis=1)

    def cell(self, lat, lon):
        return int(np.abs(self.lats - lat).argmin()), int(np.abs(self.lons - lon).argmin())


def conditional_hit_rate(mesh: Mesh, size_mm=HIT_MM, day_mask=None) -> np.ndarray:
    """Smoothed fraction of regional hail days on which each cell reached size_mm."""
    days = mesh.regional_days() if day_mask is None else (mesh.regional_days() & day_mask)
    hits = (mesh.cube[days] >= size_mm).sum(axis=0).astype(float)
    n = max(int(days.sum()), 1)
    return gaussian_filter(hits, SMOOTH_CELLS, mode="nearest") / n


def build(sizes=(20, 30, 50)):
    mesh = Mesh.load()
    rates = {f"p_hit_{s}": conditional_hit_rate(mesh, s) for s in sizes}
    np.savez_compressed(PROCESSED / "mesh_hit_rates.npz", lats=mesh.lats, lons=mesh.lons,
                        n_regional_days=int(mesh.regional_days().sum()), **rates)
    return mesh, rates


if __name__ == "__main__":
    mesh, rates = build()
    box = mesh.label_box_mask()
    print(f"regional MESH days: {mesh.regional_days().sum()} of {mesh.valid.sum()} valid")
    for k, r in rates.items():
        print(f"{k}: label-box mean {r[box].mean():.3f}, max {r[box].max():.3f}")
