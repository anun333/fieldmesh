#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hoop-house twin (Q28): the weather GreenLight is given, the tunnel it is configured
as, and the comparison with the virtual farm's tunnel. GreenLight itself runs only in
this module's environment; the tests that need it skip without it."""
from __future__ import annotations

import csv
import datetime as _dt
import io
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import twin as T  # noqa: E402
import tunnel_compare as C  # noqa: E402

try:
    import greenlight  # noqa: F401
    HAVE_GREENLIGHT = True
except ImportError:
    HAVE_GREENLIGHT = False

UTC = _dt.timezone.utc


class TestWeather(unittest.TestCase):
    def test_power_irradiance_is_mj_per_hour_and_converted(self):
        hours = T.read_hours(C.data(C.PERIODS["spring"]))
        self.assertEqual(len(hours), 61 * 24)
        noon = max(h.sw for h in hours)
        self.assertTrue(800 < noon < 1100, noon)          # W m-2, not MJ h-1
        self.assertTrue(all(150 < h.lw < 500 for h in hours))

    def test_the_derived_quantities_are_physical(self):
        self.assertAlmostEqual(T.vapour_pressure(20.0, 100.0), 2338, delta=5)
        self.assertAlmostEqual(T.sky_temperature(T.SIGMA * 273.15 ** 4), 0.0, places=6)
        self.assertAlmostEqual(T.co2_mg_m3(0.0, 101.325, 420.0), 824.6, delta=1)

    def test_the_weather_file_is_in_greenlights_shape(self):
        hours = T.read_hours(C.data(C.PERIODS["july"]))[:30]
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "w.csv")
            T.greenlight_weather(hours, path, soil_c=16.0, elevation_m=243.0)
            with open(path, encoding="utf-8") as h:
                rows = list(csv.reader(h))
            self.assertEqual(rows[0], ["Time", "tOut", "vpOut", "co2Out", "wind", "tSky", "tSoOut",
                                       "iGlob", "dayRadSum", "isDay", "isDaySmooth", "hElevation"])
            self.assertEqual(rows[2][0], "s")
            self.assertEqual([int(r[0]) for r in rows[3:6]], [0, 3600, 7200])
            self.assertEqual(len(rows), 3 + 30)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestTheTunnel(unittest.TestCase):
    def test_each_film_conserves_its_long_wave(self):
        for name, film in T.COVERS.items():
            self.assertAlmostEqual(film["tauRfFir"] + film["epsRfFir"] + film["rhoRfFir"], 1.0, msg=name)

    def test_the_definition_is_an_unheated_unenriched_tunnel_with_the_gamma_fix(self):
        d = T.tunnel_definition("clear")
        design, control = d["Tunnel design"], d["Tunnel control"]
        self.assertEqual(design["pBoil"]["definition"], "0.0")
        self.assertEqual(design["phiExtCo2"]["definition"], "0.0")
        self.assertEqual(design["aRoof"]["definition"], "0.0")
        self.assertEqual(design["tauRfFir"]["definition"], "0.7")
        self.assertEqual(control["uThScr"]["definition"], "0")
        self.assertIn("min(1, j25LeafMax / j25CanMax)", d["Tunnel formulas"]["gamma"]["definition"])


class TestTheComparison(unittest.TestCase):
    """What step 1 found, from GreenLight's saved runs, so it reruns without GreenLight."""

    @classmethod
    def setUpClass(cls):
        cls.r = C.compare()

    def test_the_virtual_farms_tunnel_is_warmer_at_night_than_either_film(self):
        spring = self.r["spring"]
        farm = spring["virtual farm"]["all"]["mean_gain"]
        thermic = spring["GreenLight, thermic film"]["all"]["mean_gain"]
        clear = spring["GreenLight, clear film"]["all"]["mean_gain"]
        self.assertGreater(farm - thermic, 1.0)
        self.assertGreater(thermic - clear, 0.8)

    def test_the_film_decides_how_many_frosts_get_in(self):
        spring = self.r["spring"]
        self.assertEqual(spring["virtual farm"]["frost_nights_outside"], 6)
        self.assertLessEqual(spring["GreenLight, thermic film"]["frost_nights_inside"], 1)
        self.assertGreaterEqual(spring["GreenLight, clear film"]["frost_nights_inside"], 4)
        self.assertLess(spring["GreenLight, clear film"]["clear"]["min_gain"], 0.0,
                        "under clear film a clear night can be colder inside than out")

    def test_the_hottest_july_hour_agrees_within_two_degrees(self):
        july = self.r["july"]
        hottest = [v["hottest_inside_c"] for v in july.values()]
        self.assertLess(max(hottest) - min(hottest), 2.0)


@unittest.skipUnless(HAVE_GREENLIGHT, "GreenLight runs in this module's environment (requirements.txt)")
class TestGreenLightAsATunnel(unittest.TestCase):
    def run_days(self, days, *, fix):
        hours = T.read_hours(C.data(C.PERIODS["spring"]))[:int(days * 24) + 2]
        saved = dict(T.FORMULAS)
        if not fix:
            T.FORMULAS.clear()
        d = tempfile.mkdtemp()
        try:
            w = os.path.join(d, "w.csv")
            T.greenlight_weather(hours, w, soil_c=C.SOIL_C, elevation_m=C.ELEVATION_M)
            buf = io.StringIO()
            import contextlib
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                T.run_greenlight(w, days, os.path.join(d, "o.csv"), cover="thermic")
            return "Simulation failed" not in buf.getvalue()
        finally:
            T.FORMULAS.clear()
            T.FORMULAS.update(saved)
            shutil.rmtree(d, ignore_errors=True)

    def test_it_runs_a_tunnel_through_sunrise_only_with_the_compensation_point_fixed(self):
        self.assertTrue(self.run_days(2, fix=True))
        self.assertFalse(self.run_days(1, fix=False),
                         "if this passes, GreenLight has fixed gamma upstream and FORMULAS can go")


if __name__ == "__main__":
    unittest.main()
