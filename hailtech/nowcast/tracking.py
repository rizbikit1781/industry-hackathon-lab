"""Hail-cell segmentation and frame-to-frame tracking (causal: only past frames are ever used).

Cell = connected component of (POSH >= seg_posh) | (MESH >= seg_mesh_mm), closed with a 3x3 kernel,
area >= min_area_px. Matching: previous footprint shifted by its motion overlapping the new cell,
else predicted-centroid distance <= max_match_km. Motion: least-squares centroid velocity over the
last `motion_frames` positions (needs >= 3); fallback: local cross-correlation of reflectivity
(or MESH) between the current frame and the frame `xcorr_lag_frames` back.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

KM_PER_DEG = 111.32


def grid_km(lats: np.ndarray, lons: np.ndarray) -> tuple[float, float]:
    """(km per row step, km per column step) for a regular lat/lon grid."""
    dlat = abs(float(lats[1] - lats[0])) if len(lats) > 1 else 0.01
    dlon = abs(float(lons[1] - lons[0])) if len(lons) > 1 else 0.01
    return KM_PER_DEG * dlat, KM_PER_DEG * dlon * np.cos(np.deg2rad(float(np.mean(lats))))


@dataclass
class Cell:
    mask: np.ndarray            # bool [y, x]
    cy: float                   # MESH-weighted centroid, pixel row
    cx: float
    area_px: int
    max_mesh: float
    max_posh: float
    max_et50: float
    foot: np.ndarray            # float32 [y, x] MESH inside the mask, 0 elsewhere


def segment(mesh, posh=None, et50=None, seg_mesh_mm=10.0, seg_posh=30.0, min_area_px=5) -> list[Cell]:
    m = np.nan_to_num(mesh, nan=0.0)
    p = np.zeros_like(m) if posh is None else np.nan_to_num(posh, nan=0.0)
    e = np.zeros_like(m) if et50 is None else np.nan_to_num(et50, nan=0.0)
    mask = (m >= seg_mesh_mm) | (p >= seg_posh)
    mask = ndimage.binary_closing(mask, structure=np.ones((3, 3)), border_value=0) | mask
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    cells = []
    for k, sl in enumerate(ndimage.find_objects(lab), start=1):
        if sl is None:
            continue
        sub = lab[sl] == k
        area = int(sub.sum())
        if area < min_area_px:
            continue
        full = np.zeros(mask.shape, bool)
        full[sl] = sub
        w = m[full] + 1.0
        yy, xx = np.nonzero(full)
        cells.append(Cell(full, float((yy * w).sum() / w.sum()), float((xx * w).sum() / w.sum()), area,
                          float(m[full].max()), float(p[full].max()), float(e[full].max()),
                          np.where(full, m, 0.0).astype(np.float32)))
    return cells


def shift2d(a: np.ndarray, dy: int, dx: int, fill=0):
    """Integer translation with fill (no wrap-around)."""
    out = np.full_like(a, fill)
    H, W = a.shape
    if abs(dy) >= H or abs(dx) >= W:
        return out
    ys, yd = (slice(0, H - dy), slice(dy, H)) if dy >= 0 else (slice(-dy, H), slice(0, H + dy))
    xs, xd = (slice(0, W - dx), slice(dx, W)) if dx >= 0 else (slice(-dx, W), slice(0, W + dx))
    out[yd, xd] = a[ys, xs]
    return out


def xcorr_motion(prev: np.ndarray, cur: np.ndarray, cy: float, cx: float, half=40, max_shift=15):
    """Displacement (dy, dx) in pixels from prev to cur in a window around (cy, cx), by brute-force
    normalised cross-correlation over integer shifts. Returns None if no signal."""
    H, W = cur.shape
    y0, y1 = max(0, int(cy) - half), min(H, int(cy) + half + 1)
    x0, x1 = max(0, int(cx) - half), min(W, int(cx) + half + 1)
    a = np.nan_to_num(prev[y0:y1, x0:x1], nan=0.0)
    b = np.nan_to_num(cur[y0:y1, x0:x1], nan=0.0)
    if a.max() <= 0 or b.max() <= 0:
        return None
    best, arg = -np.inf, None
    for dy in range(-max_shift, max_shift + 1):
        for dx in range(-max_shift, max_shift + 1):
            s = shift2d(a, dy, dx)
            num = float((s * b).sum())
            den = float(np.sqrt((s * s).sum() * (b * b).sum())) or 1.0
            score = num / den - 1e-4 * (dy * dy + dx * dx)  # tiny preference for small shifts
            if score > best:
                best, arg = score, (dy, dx)
    return arg


@dataclass
class Track:
    storm_id: str
    parent: str | None
    times: list = field(default_factory=list)      # minutes since tracker epoch
    ys: list = field(default_factory=list)
    xs: list = field(default_factory=list)
    cell: Cell | None = None
    vy: float = 0.0                                  # pixels / minute (row direction, +south)
    vx: float = 0.0                                  # pixels / minute (+east)
    motion_src: str = "none"
    missed: int = 0

    @property
    def active(self):
        return self.missed == 0 and self.cell is not None


class Tracker:
    """Feed frames in time order with `update`; read `tracks` for the current state."""

    def __init__(self, lats, lons, seg_mesh_mm=10.0, seg_posh=30.0, min_area_px=5, motion_frames=6,
                 max_match_km=12.0, max_speed_kmh=120.0, xcorr_lag_frames=5, max_missed=2):
        self.kmy, self.kmx = grid_km(lats, lons)
        self.seg = dict(seg_mesh_mm=seg_mesh_mm, seg_posh=seg_posh, min_area_px=min_area_px)
        self.motion_frames, self.max_match_km = motion_frames, max_match_km
        self.max_speed_kmh, self.lag, self.max_missed = max_speed_kmh, xcorr_lag_frames, max_missed
        self.tracks: list[Track] = []
        self.history: list[tuple[float, np.ndarray]] = []   # (t_min, motion field) last `lag` frames
        self._next = 1
        self.last_time = None

    def _new_id(self):
        sid = f"S{self._next:03d}"
        self._next += 1
        return sid

    def _clamp(self, vy, vx):
        kmh = 60 * np.hypot(vy * self.kmy, vx * self.kmx)
        if kmh > self.max_speed_kmh:
            f = self.max_speed_kmh / kmh
            vy, vx = vy * f, vx * f
        return vy, vx

    def update(self, t_min: float, mesh, posh=None, et50=None, refl=None):
        cells = segment(mesh, posh, et50, **self.seg)
        motion_field = refl if refl is not None and np.isfinite(refl).any() else mesh
        motion_field = np.clip(np.nan_to_num(motion_field, nan=0.0) - (30.0 if motion_field is refl else 0.0), 0, None)
        prev_field = self.history[0] if len(self.history) >= self.lag else None

        live = [tr for tr in self.tracks if tr.missed <= self.max_missed and tr.cell is not None]
        # candidate pairs scored by overlap of the motion-shifted previous footprint, then distance
        pairs = []
        for i, tr in enumerate(live):
            dt = t_min - tr.times[-1]
            py, px = tr.ys[-1] + tr.vy * dt, tr.xs[-1] + tr.vx * dt
            shifted = shift2d(tr.cell.mask, int(round(tr.vy * dt)), int(round(tr.vx * dt)), False)
            for j, c in enumerate(cells):
                d_km = np.hypot((c.cy - py) * self.kmy, (c.cx - px) * self.kmx)
                ov = int((shifted & c.mask).sum())
                if ov > 0 or d_km <= self.max_match_km:
                    pairs.append((-ov, d_km, i, j))
        pairs.sort()
        used_t, used_c, parent_of = set(), set(), {}
        for _, _, i, j in pairs:
            if i in used_t:
                if j not in used_c:
                    parent_of.setdefault(j, live[i].storm_id)   # split: child records lineage
                continue
            if j in used_c:
                continue
            used_t.add(i)
            used_c.add(j)
            tr, c = live[i], cells[j]
            tr.times.append(t_min); tr.ys.append(c.cy); tr.xs.append(c.cx)
            tr.cell, tr.missed = c, 0
        for i, tr in enumerate(live):
            if i not in used_t:
                tr.missed += 1
        for j, c in enumerate(cells):
            if j in used_c:
                continue
            tr = Track(self._new_id(), parent_of.get(j), [t_min], [c.cy], [c.cx], c)
            self.tracks.append(tr)

        # motion estimates
        for tr in self.tracks:
            if not tr.active or tr.times[-1] != t_min:
                continue
            n = min(self.motion_frames, len(tr.times))
            if n >= 3 and tr.times[-1] - tr.times[-n] > 0:
                t = np.array(tr.times[-n:]) - tr.times[-1]
                vy = np.polyfit(t, np.array(tr.ys[-n:]), 1)[0]
                vx = np.polyfit(t, np.array(tr.xs[-n:]), 1)[0]
                tr.vy, tr.vx = self._clamp(vy, vx)
                tr.motion_src = "centroid_lsq"
            elif prev_field is not None:
                d = xcorr_motion(prev_field[1], motion_field, tr.cell.cy, tr.cell.cx)
                if d is not None:
                    lag = t_min - prev_field[0]
                    tr.vy, tr.vx = self._clamp(d[0] / lag, d[1] / lag)
                    tr.motion_src = "xcorr"
        self.tracks = [tr for tr in self.tracks if tr.missed <= self.max_missed]
        self.history.append((t_min, motion_field))
        if len(self.history) > self.lag:
            self.history.pop(0)
        self.last_time = t_min
        return [tr for tr in self.tracks if tr.active]

    def velocity_kmh(self, tr: Track) -> tuple[float, float]:
        """(u east, v north) km/h. Rows run north->south, so v = -vy."""
        return 60 * tr.vx * self.kmx, -60 * tr.vy * self.kmy
