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

try:
    import celpy  # noqa: F401
    HAVE_CEL = True
except ImportError:
    HAVE_CEL = False

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

    def test_the_virtual_farms_tunnel_now_matches_greenlights_on_average(self):
        """It ran +3.1 °C at night against GreenLight's +1.4; its defaults are now fitted
        to it (sim/physics.FILMS)."""
        spring = self.r["spring"]
        farm, thermic = spring["virtual farm"], spring["GreenLight, thermic film"]
        self.assertAlmostEqual(farm["all"]["mean_gain"], thermic["all"]["mean_gain"], delta=0.5)
        self.assertAlmostEqual(farm["mean_day_excess_c"], thermic["mean_day_excess_c"], delta=1.0)
        self.assertGreater(thermic["all"]["mean_gain"] - spring["GreenLight, clear film"]["all"]["mean_gain"], 0.8)

    def test_knowing_the_sky_it_can_be_colder_inside_than_out_under_clear_film(self):
        """Without the sky, rain its only sign of cloud, the virtual tunnel is never colder
        inside than out. Given the sky's long-wave, under clear film it is on most of the
        nights GreenLight is, though by less; under IR film the sky barely matters."""
        spring = self.r["spring"]
        self.assertGreater(spring["virtual farm"]["all"]["min_gain"], 0.5)
        clear = spring["virtual farm, sky known, clear film"]
        self.assertLess(clear["all"]["min_gain"], 0.0)
        self.assertLess(clear["clear"]["mean_gain"], 0.2, "clear nights hold almost no heat")
        self.assertGreater(spring["GreenLight, clear film"]["all"]["min_gain"], -1.5)
        self.assertLess(spring["GreenLight, clear film"]["all"]["min_gain"], clear["all"]["min_gain"],
                        "GreenLight's inversions are the deeper")
        self.assertAlmostEqual(spring["virtual farm, sky known"]["all"]["mean_gain"],
                               spring["GreenLight, thermic film"]["all"]["mean_gain"], delta=0.2)

    def test_the_film_decides_how_many_frosts_get_in(self):
        spring = self.r["spring"]
        self.assertEqual(spring["virtual farm"]["frost_nights_outside"], 6)
        self.assertLessEqual(spring["GreenLight, thermic film"]["frost_nights_inside"], 1)
        self.assertGreaterEqual(spring["GreenLight, clear film"]["frost_nights_inside"], 4)
        self.assertLess(spring["GreenLight, clear film"]["clear"]["min_gain"], 0.0,
                        "under clear film a clear night can be colder inside than out")

    def test_the_hottest_july_hour_and_the_cost_of_fitting_the_nights(self):
        """The two films agree on the hottest hour within a degree. The virtual tunnel,
        fitted mainly to the nights, runs some three degrees cooler at the peak — a cost
        recorded here so that a heat warning is not built on it unexamined."""
        july = self.r["july"]
        thermic, clear = (july[f"GreenLight, {c} film"]["hottest_inside_c"] for c in ("thermic", "clear"))
        self.assertLess(abs(thermic - clear), 1.0)
        gap = thermic - july["virtual farm"]["hottest_inside_c"]
        self.assertTrue(2.0 < gap < 4.5, gap)


class TestTheFrostWatchInputs(unittest.TestCase):
    """Q28 step 2: a forecast's cloud becomes the sky the tunnel radiates to."""

    def test_cloud_raises_the_sky_toward_a_black_body(self):
        import frostwatch as F
        clear, overcast = F.sky_longwave(0.0, 80.0, 0.0), F.sky_longwave(0.0, 80.0, 1.0)
        self.assertAlmostEqual(overcast, T.SIGMA * 273.15 ** 4, places=6)
        self.assertTrue(0.65 < clear / overcast < 0.8, clear / overcast)

    def test_the_sun_is_where_it_should_be(self):
        import frostwatch as F
        equinox_noon = _dt.datetime(2026, 3, 21, 17, 46, tzinfo=UTC)
        self.assertAlmostEqual(F.solar_elevation(equinox_noon, 35.06, -86.59), 55.0, delta=1.5)
        self.assertEqual(F.sky_shortwave(_dt.datetime(2026, 1, 10, 3, tzinfo=UTC), 35.06, -86.59, 0), 0.0)
        noon = _dt.datetime(2026, 6, 21, 17, 30, tzinfo=UTC)
        self.assertGreater(F.sky_shortwave(noon, 35.06, -86.59, 0.0),
                           2 * F.sky_shortwave(noon, 35.06, -86.59, 1.0))

    def test_a_three_hourly_forecast_becomes_hourly_weather(self):
        import frostwatch as F
        t0 = _dt.datetime(2026, 1, 10, 0, tzinfo=UTC)
        pts = lambda a, b: [(t0, a), (t0 + 3 * F.HOUR, b)]
        hours = F.forecast_hours({"t_c": pts(3.0, 0.0), "rh_pct": pts(60.0, 90.0),
                                  "wind_m_s": pts(2.0, 1.0), "cloud": pts(0.0, 1.0)},
                                 lat=35.06, lon=-86.59)
        self.assertEqual([h.t for h in hours], [3.0, 2.0, 1.0, 0.0])
        self.assertLess(hours[0].lw, hours[-1].lw, "clearing to overcast warms the sky")

    def test_the_warm_up_starts_from_the_weeks_before_not_a_glasshouse(self):
        import frostwatch as F
        start = _dt.datetime(2026, 1, 20, tzinfo=UTC)
        observed = [T.Hour(start - k * F.HOUR, 2.0 if k <= 7 * 24 else 8.0, 80, 2, 0, 250, 0, 98)
                    for k in range(1, 40 * 24)]
        init = F.initial_state(observed, start, deep_c=16.0)
        self.assertAlmostEqual(init["tAir"], 2.0)
        self.assertAlmostEqual(init["tSo1"], 2.0)
        self.assertTrue(2.0 < init["tSo3"] < 8.0)
        self.assertEqual(init["tSo5"], 16.0)

    def test_tonights_weather_comes_from_the_forecast_log(self):
        """Live, the warm-up and the night both come from the collected forecasts: each
        hour the latest issue for it (Q26), in the units NWS gives."""
        import frostwatch as F
        sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
        import fixtures as FX
        from model import Datastream, DatastreamKind
        from project import State
        from ids import uuid7
        state = State()
        t0 = _dt.datetime(2026, 1, 10, 0, tzinfo=UTC)
        cf = "http://vocab.nerc.ac.uk/standard_name/"
        streams = {}
        for prop, unit, value in (("air_temperature", "Cel", 1.0), ("relative_humidity", "%", 80.0),
                                  ("wind_speed", "km/h", 7.2), ("cloud_area_fraction", "%", 25.0)):
            ds = Datastream(uuid7(), uuid7(), uuid7(), cf + prop + "/", uuid7(),
                            DatastreamKind.FORECAST, unit, expected_interval=3600.0, max_latency=3600.0)
            state.add(ds)
            streams[prop] = ds
            for h in range(-36, 15):
                when = t0 + h * F.HOUR
                state.add(FX.observation(ds, result=value, measured_at=when, received_at=when - 3 * F.HOUR,
                                         issued_at=when - 3 * F.HOUR, seq=h + 40))
        hours = F.live_weather(state, t0 - 36 * F.HOUR, t0 + 14 * F.HOUR, lat=35.06, lon=-86.59)
        self.assertEqual(len(hours), 51)
        self.assertAlmostEqual(hours[0].wind, 2.0)            # 7.2 km/h
        self.assertAlmostEqual(hours[0].t, 1.0)
        self.assertLess(hours[0].lw, T.SIGMA * 274.15 ** 4)  # a quarter cloud, not overcast
        no_cloud = State()
        for prop, ds in streams.items():
            if prop != "cloud_area_fraction":
                no_cloud.add(ds)
        with self.assertRaisesRegex(ValueError, "cloud_area_fraction"):
            F.live_weather(no_cloud, t0, t0 + F.HOUR, lat=35.06, lon=-86.59)

    @unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
    def test_the_rule_warns_and_says_so_in_two_languages(self):
        import frostwatch as F
        sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
        import rules as R
        at = _dt.datetime(2026, 1, 10, 0, tzinfo=UTC)
        rule = F.covered_frost_watch(0.0)
        cold = F.judge(rule, {"inside_low_c": -1.4, "outside_low_c": -3.0, "cover": "thermic"}, at, {})
        mild = F.judge(rule, {"inside_low_c": 1.2, "outside_low_c": -2.0, "cover": "thermic"}, at, {})
        self.assertEqual((cold["alert"], mild["alert"]), (True, False))
        self.assertIn("-1.4", R.render(cold, "en"))
        self.assertIn("túnel", R.render(cold, "es"))
        self.assertFalse(F.judge(rule, None, at, {})["alert"], "no forecast, no warning")


class TestTheFrostWatchSeason(unittest.TestCase):
    """The 2025-26 season at McAllister Farm, from the saved nights (covered_backtest.py)."""

    def summary(self, cover):
        import covered_backtest as B
        return B.summary(cover), B.read(cover)

    def test_a_tennessee_winter_gets_into_an_unheated_tunnel(self):
        s, rows = self.summary("thermic")
        inside = sum(r["twin_inside_low_actual_c"] <= -2.2 for r in rows)
        outside = sum(r["station_outside_low_c"] <= -2.2 for r in rows)
        self.assertEqual(s["nights"], 194)
        self.assertGreaterEqual(inside, 0.7 * outside, (inside, outside))

    def test_under_ir_film_the_watch_misses_nothing_and_spares_some_warnings(self):
        s, _ = self.summary("thermic")
        self.assertEqual(s["covered_crop_watch"]["damaging_missed"], 0)
        self.assertGreaterEqual(s["spared_by_the_twin"], 5)

    def test_the_forecast_twin_runs_warm_so_clear_film_needs_a_margin(self):
        import covered_backtest as B
        import frostwatch as F
        s, rows = self.summary("clear")
        self.assertGreater(s["inside_low_forecast_bias_c"], 0.5)
        self.assertEqual(s["covered_crop_watch"]["damaging_missed"], 1, "at 0 °C")
        warn = F.WARN_BY_COVER["clear"]
        missed = [r for r in rows if r["twin_inside_low_actual_c"] <= B.DAMAGE_C
                  and r["twin_inside_low_forecast_c"] > warn]
        self.assertEqual(missed, [], "at the clear film's own threshold")


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestTheTwinAgainstTheSensor(unittest.TestCase):
    """Q28 step 3, on the spring of 2025: GreenLight's saved run as the twin, and the
    virtual farm's tunnel, lit by the measured sunshine, as the sensor, with faults put
    in. Two models of one tunnel never agree; the check learns how far apart they
    usually are and says when they part company."""

    @classmethod
    def setUpClass(cls):
        import twin_check as K
        cls.K = K
        cls.hours = T.read_hours(C.data(C.PERIODS["spring"]))
        cls.twin = C.read_inside(C.greenlight_file("spring", "thermic"))
        d = lambda m, day, h=12: _dt.datetime(2025, m, day, h, tzinfo=UTC)
        cls.faults = [("offset", d(3, 20), d(3, 23), 4.0), ("sun", d(3, 28), d(4, 2), 8.0),
                      ("sides", d(4, 8, 0), d(4, 10, 0), None), ("outside", d(4, 16), d(4, 18, 0), None)]

    def test_a_sound_sensor_raises_nothing_in_seven_weeks(self):
        r = self.K.backtest(self.K.sensor_series(self.hours), self.twin, [], lon=C.LON)
        self.assertEqual(r["false"], [])
        self.assertGreater(r["clean_days"], 45)

    def test_each_fault_is_said_within_a_day_and_nothing_else_is(self):
        sensor = self.K.sensor_series(self.hours, faults=self.faults)
        r = self.K.backtest(sensor, self.twin, self.faults, lon=C.LON)
        caught = {f["kind"]: f["caught_after_h"] for f in r["faults"]}
        self.assertEqual(set(caught), {"offset", "sun", "sides", "outside"})
        self.assertTrue(all(h is not None and h <= 24 for h in caught.values()), caught)
        self.assertEqual(r["false"], [])

    def test_a_small_offset_is_not_its_to_see(self):
        """Two models of a tunnel differ by one or two degrees, so a sensor that reads
        1.5 °C high is a second sensor's to catch, not the twin's."""
        d = lambda m, day: _dt.datetime(2025, m, day, 12, tzinfo=UTC)
        faults = [("offset", d(3, 20), d(3, 27), 1.5)]
        r = self.K.backtest(self.K.sensor_series(self.hours, faults=faults), self.twin, faults, lon=C.LON)
        self.assertIsNone(r["faults"][0]["caught_after_h"])

    def test_it_waits_for_a_week_of_calibration_and_says_so_in_two_languages(self):
        import rules as R
        from ids import uuid7
        from model import Label
        from project import State
        start = self.hours[0].when
        sensor = self.K.sensor_series(self.hours, faults=[("outside", start + 20 * self.K.DAY,
                                                           start + 22 * self.K.DAY, None)])
        short = self.K.calibrate(sensor, self.twin, start, start + 3 * self.K.DAY, lon=C.LON)
        self.assertFalse(short.ok())
        cal = self.K.calibrate(sensor, self.twin, start, start + 14 * self.K.DAY, lon=C.LON)
        # At night a tunnel is barely warmer than outside, so the first sunny hours say it.
        at = start + 20 * self.K.DAY
        while at < start + 22 * self.K.DAY:
            ctx, _ = self.K.context(sensor, self.twin, cal, at, lon=C.LON)
            d = R.judge(self.K.rule(), ctx, {}, at)
            if d["alert"]:
                break
            at += self.K.HOUR
        self.assertTrue(d["alert"])
        self.assertLess(d["context"]["delta_c"], 0, "outside is colder than the tunnel by day")
        tunnel = uuid7()
        d["subject"] = str(tunnel)
        state = State()
        state.add(Label(uuid7(), tunnel, "invernadero", at, language="es"))
        self.assertIn("El sensor de aire de invernadero y el gemelo discrepan", R.render(d, "es", state))


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
                         "if this passes, GreenLight has fixed gamma upstream (davkat1/GreenLight#23) "
                         "and FORMULAS can go")


if __name__ == "__main__":
    unittest.main()
