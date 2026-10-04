import numpy as np
from metpy.calc import dewpoint_from_specific_humidity
from metpy.units import units

from hailday import indices as ix

P = np.array([1000, 925, 850, 700, 500, 300], float)


def test_bulk_shear_synthetic_profile():
    # u rises linearly 2 m/s per km from 5 m/s at 10 m; v constant. Levels at 1..9 km.
    z = np.array([1000, 2000, 3000, 4000, 5000, 7000, 9000], float)
    u = 5 + 2 * (z - 10) / 1000
    ok = np.ones_like(z, bool)
    uu, zz = ix.with_surface(u, z, ok, 5.0, 10.0)
    vv, _ = ix.with_surface(np.full_like(z, 3.0), z, ok, 3.0, 10.0)
    u6, v6 = ix.interp_at_height(uu, zz, 6000.0), ix.interp_at_height(vv, zz, 6000.0)
    assert np.isclose(ix.bulk_shear(5.0, 3.0, u6, v6), 2 * 5.99, atol=1e-6)


def test_lapse_rate_700_500():
    # 700 hPa at 3000 m / 5 C, 500 hPa at 5600 m / -15 C -> 20 K over 2.6 km.
    assert np.isclose(ix.lapse_rate(278.15, 258.15, 3000.0, 5600.0), 20 / 2.6)


def test_freezing_level_interpolation_and_edge_cases():
    t = np.array([[290.0, 280.0, 270.0, 260.0],     # crosses 273.15 between 1 and 2 km
                  [270.0, 265.0, 260.0, 250.0],     # surface already below freezing -> 0
                  [300.0, 295.0, 290.0, 285.0]])    # never crosses -> NaN
    z = np.tile([0.0, 1000.0, 2000.0, 3000.0], (3, 1))
    h = ix.crossing_height(t, z, 273.15)
    assert np.isclose(h[0], 1000 + 6.85 / 10 * 1000)
    assert h[1] == 0.0 and np.isnan(h[2])
    # Lowest crossing wins when an inversion re-crosses higher up.
    t2 = np.array([[276.0, 272.0, 275.0, 270.0]])
    assert np.isclose(ix.crossing_height(t2, z[:1], 273.15)[0], 2.85 / 4 * 1000)


def test_ship_hand_computed():
    # MUCAPE 2000, mr 12 g/kg, LR 7.5, T500 -15, shear 20, FZL 3000 -> no scaling clauses apply.
    expected = 2000 * 12 * 7.5 * 15 * 20 / 42e6  # = 1.2857
    assert np.isclose(ix.ship(2000.0, 12.0, 7.5, -15.0, 20.0, 3000.0), expected)
    # Clauses: shear clamped to 27, mr clamped to 11, CAPE < 1300, LR < 5.8, FZL < 2400.
    s = ix.ship(1000.0, 8.0, 5.0, -10.0, 35.0, 2000.0)
    base = 1000 * 11 * 5.0 * 10 * 27 / 42e6
    assert np.isclose(s, base * (1000 / 1300) * (5.0 / 5.8) * (2000 / 2400))
    # T500 warmer than -5.5 C is capped.
    assert np.isclose(ix.ship(2000.0, 12.0, 7.5, -2.0, 20.0, 3000.0),
                      2000 * 12 * 7.5 * 5.5 * 20 / 42e6)


def test_underground_masking():
    # Surface at 840 hPa: 1000/925 hPa are below terrain; 850 hPa has z >= 0 but p > sp.
    zagl = np.array([[-1000.0, -400.0, 300.0, 1900.0, 4500.0, 8000.0]])
    ok = ix.valid_levels(P, np.array([840.0]), zagl)
    assert ok.tolist() == [[False, False, False, True, True, True]]
    q = np.array([[0.020, 0.018, 0.012, 0.006, 0.002, 0.0005]])
    assert np.isclose(ix.at_level_or_lowest(q, ok, 2)[0], 0.006)          # 850 masked -> 700
    tt, zz = ix.with_surface(np.array([[300, 296, 290, 278, 258, 230.0]]), zagl, ok, 285.0, 2.0)
    assert np.all(np.diff(zz) >= 0) and tt[0, 1] == 285.0
    # Freezing level found between 700 and 500 hPa, not in underground warm levels.
    h = ix.crossing_height(tt, zz, 273.15)[0]
    assert 1900 < h < 4500


def test_dewpoint_and_wet_bulb():
    p, q = np.array([850.0, 700.0]), np.array([0.010, 0.004])
    td = ix.dewpoint_from_q(p, q)
    ref = dewpoint_from_specific_humidity(p * units.hPa, q * units("kg/kg")).to("K").magnitude
    assert np.allclose(td, ref)
    # Wet bulb lies between dewpoint and temperature; equals T at saturation.
    t = np.array([295.0, 280.0])
    tw = ix.wet_bulb(t, q, p)
    assert np.all((tw > td) & (tw < t))
    qs = ix.q_from_dewpoint(np.array([280.0]), np.array([700.0]))
    assert np.isclose(ix.wet_bulb(np.array([280.0]), qs, np.array([700.0]))[0], 280.0, atol=0.05)
