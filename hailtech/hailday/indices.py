"""Vectorised convective indices on pressure-level profiles.

Conventions: profile arrays have the level axis LAST, ordered bottom-up (highest pressure
first). Heights are metres above ground level (AGL). Temperatures in K unless named *_c.
Everything broadcasts over arbitrary leading (time, lat, lon) axes; no per-profile loops.

Underground handling: a level is valid only if p <= surface pressure AND its height AGL >= 0.
`with_surface` prepends the screen-level value as level 0 and overwrites invalid levels with
that same surface value/height, so each profile stays monotonic in height and every
interpolation starts from the real surface.
"""
import numpy as np
from metpy.calc import dewpoint_from_specific_humidity
from metpy.units import units

G = 9.80665
CP = 1004.0       # J/kg/K, dry air
LV = 2.501e6      # J/kg, latent heat of vaporisation
EPS = 0.622


def valid_levels(p_hpa, sp_hpa, z_agl):
    """True where the level is above ground (p <= sp and z_agl >= 0). p_hpa (L,), sp_hpa (...), z_agl (..., L)."""
    return (p_hpa <= sp_hpa[..., None]) & (z_agl >= 0)


def with_surface(values, z_agl, valid, surf_value, surf_z):
    """Prepend the surface value at height surf_z and replace invalid levels by it. Returns (vals, z)."""
    sv = np.broadcast_to(np.asarray(surf_value, float), values.shape[:-1])[..., None]
    sz = np.broadcast_to(np.asarray(surf_z, float), values.shape[:-1])[..., None]
    v = np.where(valid, values, sv)
    z = np.where(valid, z_agl, sz)
    return np.concatenate([sv, v], axis=-1), np.concatenate([sz, z], axis=-1)


def interp_at_height(values, z, target):
    """Linear interpolation of values at height `target` along a non-decreasing z profile.

    NaN where target lies outside the profile. Ties (duplicated surface levels) take the upper value.
    """
    target = np.broadcast_to(np.asarray(target, float), z.shape[:-1])
    n = z.shape[-1]
    k = np.clip((z < target[..., None]).sum(-1), 1, n - 1)[..., None]
    z0, z1 = np.take_along_axis(z, k - 1, -1)[..., 0], np.take_along_axis(z, k, -1)[..., 0]
    v0, v1 = np.take_along_axis(values, k - 1, -1)[..., 0], np.take_along_axis(values, k, -1)[..., 0]
    dz = z1 - z0
    w = np.divide(target - z0, dz, out=np.ones_like(dz), where=dz > 0)
    out = v0 + w * (v1 - v0)
    return np.where((target < z[..., 0]) | (target > z[..., -1]), np.nan, out)


def crossing_height(t, z, threshold):
    """Height of the lowest level where t first falls from > threshold to <= threshold (going up).

    Returns 0 where the bottom of the profile is already <= threshold, NaN if never crossed.
    Linear interpolation of z in t between the bracketing levels.
    """
    a, b = t[..., :-1], t[..., 1:]
    cross = (a > threshold) & (b <= threshold)
    k = np.argmax(cross, axis=-1)[..., None]
    ta, tb = np.take_along_axis(a, k, -1)[..., 0], np.take_along_axis(b, k, -1)[..., 0]
    za, zb = np.take_along_axis(z[..., :-1], k, -1)[..., 0], np.take_along_axis(z[..., 1:], k, -1)[..., 0]
    with np.errstate(divide="ignore", invalid="ignore"):  # non-crossing columns are masked below
        h = za + (ta - threshold) / (ta - tb) * (zb - za)
    h = np.where(cross.any(-1), h, np.nan)
    return np.where(t[..., 0] <= threshold, 0.0, h)


def lowest_valid(values, valid):
    """Value at the lowest above-ground level of each profile."""
    k = np.argmax(valid, axis=-1)[..., None]
    return np.take_along_axis(values, k, -1)[..., 0]


def at_level_or_lowest(values, valid, idx):
    """values[..., idx] where that level is above ground, else the lowest above-ground level."""
    return np.where(valid[..., idx], values[..., idx], lowest_valid(values, valid))


def bulk_shear(u_bot, v_bot, u_top, v_top):
    return np.hypot(u_top - u_bot, v_top - v_bot)


def lapse_rate(t_lo, t_hi, z_lo, z_hi):
    """Environmental lapse rate in K/km (positive when temperature falls with height)."""
    return (t_lo - t_hi) / (z_hi - z_lo) * 1000.0


def mixing_ratio(q):
    return q / (1.0 - q)


def q_from_dewpoint(td_k, p_hpa):
    """Specific humidity from dewpoint (Bolton 1980 saturation vapour pressure)."""
    e = sat_vapour_pressure(td_k)
    return EPS * e / (p_hpa - (1 - EPS) * e)


def sat_vapour_pressure(t_k):
    """Bolton (1980) saturation vapour pressure over water, hPa."""
    tc = t_k - 273.15
    return 6.112 * np.exp(17.67 * tc / (tc + 243.5))


def dewpoint_from_q(p_hpa, q):
    """Dewpoint (K) from pressure and specific humidity via MetPy (Bolton inverse, vectorised)."""
    q = np.clip(q, 1e-7, None)
    td = dewpoint_from_specific_humidity(np.asarray(p_hpa, float) * units.hPa, q * units("kg/kg"))
    return td.to("K").magnitude


def wet_bulb(t_k, q, p_hpa, iters=6):
    """Isobaric (psychrometric) wet-bulb temperature, K, solved by Newton iteration.

    Solves cp (T - Tw) = Lv (ws(Tw, p) - w). This replaces MetPy's per-element
    `wet_bulb_temperature` (~0.6 ms/element; parcel-to-LCL then moist adiabat down); the two
    agree to a few tenths of a K for tropospheric conditions. Fully vectorised.
    """
    t_k, p = np.asarray(t_k, float), np.asarray(p_hpa, float)
    w = mixing_ratio(np.clip(q, 0, None))
    tw = t_k - 5.0
    for _ in range(iters):
        tc = tw - 273.15
        es = sat_vapour_pressure(tw)
        ws = EPS * es / (p - es)
        dws = ws * p / (p - es) * 17.67 * 243.5 / (tc + 243.5) ** 2
        f = CP * (t_k - tw) - LV * (ws - w)
        df = -CP - LV * dws
        tw = np.minimum(tw - f / df, t_k)
    return tw


def ship(mucape, mu_mr_gkg, lr75, t500_c, shear06, frz_agl):
    """Significant Hail Parameter per SPC (spc.noaa.gov/exper/soundings/help/ship.html).

    SHIP = MUCAPE * MUmr * LR75 * (-T500) * shear06 / 42e6, with SPC's clauses:
    shear06 clamped to [7, 27] m/s; MU mixing ratio clamped to [11, 13.6] g/kg;
    T500 capped at -5.5 C; then scaled by MUCAPE/1300 if MUCAPE < 1300,
    by LR75/5.8 if LR75 < 5.8, and by FZL/2400 if freezing level < 2400 m.
    """
    shr = np.clip(shear06, 7.0, 27.0)
    mr = np.clip(mu_mr_gkg, 11.0, 13.6)
    t5 = np.minimum(t500_c, -5.5)
    s = mucape * mr * lr75 * (-t5) * shr / 42e6
    s = np.where(mucape < 1300, s * mucape / 1300, s)
    s = np.where(lr75 < 5.8, s * lr75 / 5.8, s)
    s = np.where(frz_agl < 2400, s * frz_agl / 2400, s)
    return s
