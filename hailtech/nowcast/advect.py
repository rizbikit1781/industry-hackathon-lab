"""Advect each tracked cell's current MESH footprint along its motion; speed/direction ensemble.

Member m translates every cell by v * f_m rotated by theta_m, with f in {1-s, 1, 1+s} and
theta in {-d, 0, +d} (s = 20 %, d = 15 deg by default). Intensity is held constant (no growth/decay).

Lead-dependent spread (`spread=`): members are normalised (a, b) in [-1, 1] and at lead L the member
uses f = 1 + a * s(L), theta = b * d(L). `spread_fn` keeps s, d at their base values up to `grow_from`
minutes, then grows them linearly to (s_max, d_max) at `grow_to`. With a 5 x 5 grid the members with
a, b in {-1, 0, 1} reproduce the original 3 x 3 ensemble exactly at every lead <= grow_from.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nowcast.tracking import Track, shift2d


def members(speed_pert=0.2, dir_pert_deg=15.0, n_speed=3, n_dir=3):
    fs = np.linspace(1 - speed_pert, 1 + speed_pert, n_speed) if n_speed > 1 else np.array([1.0])
    ths = np.deg2rad(np.linspace(-dir_pert_deg, dir_pert_deg, n_dir)) if n_dir > 1 else np.array([0.0])
    return [(float(f), float(th)) for f in fs for th in ths]


def members_norm(n_speed=5, n_dir=5):
    """Normalised (a, b) grid in [-1, 1]^2, speed-major order like `members`."""
    a = np.linspace(-1, 1, n_speed) if n_speed > 1 else np.array([0.0])
    b = np.linspace(-1, 1, n_dir) if n_dir > 1 else np.array([0.0])
    return [(float(x), float(y)) for x in a for y in b]


def core_index(norm_members) -> list[int]:
    """Indices of the members with a, b in {-1, 0, 1}: the original 3 x 3 ensemble."""
    return [i for i, (a, b) in enumerate(norm_members) if a in (-1.0, 0.0, 1.0) and b in (-1.0, 0.0, 1.0)]


def spread_fn(speed_pert=0.2, dir_pert_deg=15.0, speed_pert_max=0.3, dir_pert_max_deg=25.0,
              grow_from=45.0, grow_to=90.0):
    """L (min) -> (speed fraction, direction radians): constant to grow_from, linear to the max at grow_to."""
    def f(L):
        w = 0.0 if L <= grow_from else min(1.0, (L - grow_from) / max(grow_to - grow_from, 1e-9))
        return (speed_pert + w * (speed_pert_max - speed_pert),
                np.deg2rad(dir_pert_deg + w * (dir_pert_max_deg - dir_pert_deg)))
    return f


@dataclass
class Forecast:
    leads: np.ndarray        # minutes after issue time
    fields: np.ndarray       # float32 [member, lead, y, x] forecast MESH (mm)
    offset_min: float        # issue time minus the valid time of the newest frame used

    def prob(self, thr: float) -> np.ndarray:
        """P(MESH >= thr) [lead, y, x] as member fraction."""
        return (self.fields >= thr).mean(axis=0)


def advect(tracks: list[Track], shape, leads_min, offset_min: float, ens=None, motion=True,
           km=(1.0, 1.0), spread=None) -> Forecast:
    """Forecast MESH at issue_time + lead for each lead, from cell footprints at the newest frame.

    offset_min: minutes between the newest frame's valid time and the issue time (data latency),
    so lead 0 is already displaced by v * offset. motion=False gives the persistence baseline.
    km: (km per row, km per column); the direction perturbation is applied in km space.
    spread: optional L -> (speed fraction, direction rad); then `ens` holds normalised (a, b) members
    (see `members_norm`) and the perturbation grows with lead.
    """
    if not motion:
        ens, spread = [(0.0, 0.0)], None
    ens = (members_norm() if spread is not None else members()) if ens is None else ens
    leads = np.asarray(leads_min, dtype=float)
    out = np.zeros((len(ens), len(leads)) + tuple(shape), dtype=np.float32)
    for tr in tracks:
        foot = tr.cell.foot
        ex, sy = tr.vx * km[1], tr.vy * km[0]
        for m, (f0, th0) in enumerate(ens):
            for k, L in enumerate(leads):
                if spread is None:
                    f, th = f0, th0
                else:
                    sp, dr = spread(L)
                    f, th = 1.0 + f0 * sp, th0 * dr
                # rotate (east, south) km/min by th; positive th turns the motion counter-clockwise
                vx = f * (ex * np.cos(th) + sy * np.sin(th)) / km[1]
                vy = f * (-ex * np.sin(th) + sy * np.cos(th)) / km[0]
                dt = L + offset_min
                s = shift2d(foot, int(round(vy * dt)), int(round(vx * dt)))
                np.maximum(out[m, k], s, out=out[m, k])
    return Forecast(leads, out, offset_min)

