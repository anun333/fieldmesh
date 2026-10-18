#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reference ET from a farm's own station (FAO-56 Penman–Monteith), and a station's day
read out of the log."""
from __future__ import annotations

import datetime as _dt
import math
import unittest

import eto as E
import fixtures as fx
import log as L
import project as P
import vocab as V
from ids import uuid7
from model import Assertor, QualityAssertion, QualityFlag, Usable

UTC = _dt.timezone.utc


class TestFao56(unittest.TestCase):

    def test_example_18_brussels_6_july(self):
        """FAO-56 Example 18: 3.88 mm, with u2 2.078 m/s from 10 km/h at 10 m, and Ra
        41.09 MJ m-2."""
        u2 = E.u2_from(10.0 / 3.6, 10.0)
        self.assertAlmostEqual(u2, 2.078, places=3)
        self.assertAlmostEqual(E.ra_daily(50.8, 187), 41.09, delta=0.02)
        eto, estimated = E.eto_daily(12.3, 21.5, lat=50.8, elevation_m=100.0,
                                     day_of_year=187, rs=22.07, rh_max=84.0, rh_min=63.0,
                                     u2=u2)
        self.assertAlmostEqual(eto, 3.88, delta=0.02)
        self.assertEqual(estimated, ())

    def test_each_missing_sensor_is_replaced_and_named(self):
        full, _ = E.eto_daily(12.3, 21.5, lat=50.8, elevation_m=100.0, day_of_year=187,
                              rs=22.07, rh_mean=73.5, u2=2.078)
        bare, estimated = E.eto_daily(12.3, 21.5, lat=50.8, elevation_m=100.0,
                                      day_of_year=187)
        self.assertEqual(set(estimated), {"sunshine", "humidity", "wind"})
        self.assertGreater(bare, 0.0)
        self.assertLess(abs(bare - full), 1.5, "the stand-ins are rough, not wild")

    def test_hargreaves_radiation_is_eq_50(self):
        _, estimated = E.eto_daily(12.3, 21.5, lat=50.8, elevation_m=100.0, day_of_year=187,
                                   rh_mean=73.5, u2=2.0)
        self.assertEqual(estimated, ("sunshine",))
        rs = 0.16 * math.sqrt(21.5 - 12.3) * E.ra_daily(50.8, 187)
        with_rs, _ = E.eto_daily(12.3, 21.5, lat=50.8, elevation_m=100.0, day_of_year=187,
                                 rs=rs, rh_mean=73.5, u2=2.0)
        without, _ = E.eto_daily(12.3, 21.5, lat=50.8, elevation_m=100.0, day_of_year=187,
                                 rh_mean=73.5, u2=2.0)
        self.assertAlmostEqual(with_rs, without, places=9)


class TestADayFromTheLog(unittest.TestCase):
    """A station in Tennessee: its local day runs 05:00 to 05:00 UTC in summer."""

    def setUp(self):
        self.log = L.Log()
        self.ds = {}
        for name, prop, unit in (("air", V.AIR_TEMPERATURE, "[degF]"),
                                 ("rh", V.RELATIVE_HUMIDITY, "%"),
                                 ("sun", V.SOLAR_RADIATION, "W/m2"),
                                 ("wind", V.WIND_SPEED, "km/h"),
                                 ("rain", V.PRECIPITATION_DEPTH, "mm")):
            ds = fx.raw_datastream(unit=unit, observed_property=prop)
            self.log.append_record(ds)
            self.ds[name] = ds
        self.day = _dt.date(2026, 7, 6)
        start = _dt.datetime(2026, 7, 6, 5, tzinfo=UTC)
        self.observations = []
        for h in range(24):
            when = start + _dt.timedelta(hours=h, minutes=30)
            values = {"air": 68.0 + 18.0 * math.sin(math.pi * h / 24.0), "rh": 70.0,
                      "sun": 250.0, "wind": 7.2, "rain": 1.0 if h in (2, 3) else 0.0}
            for name, value in values.items():
                o = fx.observation(self.ds[name], result=value, measured_at=when, seq=h)
                self.log.append_record(o)
                self.observations.append((name, h, o))
        self.station = E.Station(lat=36.0, elevation_m=250.0, timezone="America/Chicago",
                                 air_temperature=self.ds["air"].id,
                                 relative_humidity=self.ds["rh"].id,
                                 solar_radiation=self.ds["sun"].id,
                                 wind_speed=self.ds["wind"].id, wind_height_m=2.0,
                                 precipitation=self.ds["rain"].id)
        self.at = _dt.datetime(2026, 7, 7, 9, tzinfo=UTC)

    def test_each_series_in_fao_56s_units(self):
        s = E.day_summary(P.state_from_log(self.log), self.station, self.day, self.at)
        self.assertAlmostEqual(s["tmin"], 20.0, places=6)          # 68 F
        self.assertAlmostEqual(s["tmax"], (68.0 + 18.0 * math.sin(math.pi * 12 / 24) - 32) * 5 / 9,
                               places=6)
        self.assertAlmostEqual(s["rs"], 250.0 * 0.0864, places=6)
        self.assertAlmostEqual(s["u2"], 2.0, places=6)
        self.assertEqual(s["rain"], 2.0)

    def test_a_flagged_reading_does_not_count(self):
        [(_, _, hottest)] = [x for x in self.observations if x[0] == "air" and x[1] == 12]
        self.log.append_record(QualityAssertion(
            id=uuid7(), observation=hottest.id, flags=frozenset({QualityFlag.OUT_OF_RANGE}),
            usable=Usable.BAD, check="foundation", check_version="1",
            threshold_version=None, asserted_at=self.at - _dt.timedelta(hours=1),
            assertor=Assertor.FOUNDATION, supersedes=None, note=None,
            evidence={"checks_run": ["range"], "fired": {"range": "x"}}))
        s = E.day_summary(P.state_from_log(self.log), self.station, self.day, self.at)
        self.assertLess(s["tmax"], 30.0)

    def test_a_day_the_air_temperature_does_not_cover_is_no_day(self):
        early = _dt.datetime(2026, 7, 6, 17, tzinfo=UTC)
        self.assertIsNone(E.day_summary(P.state_from_log(self.log), self.station, self.day, early))
        self.assertIsNone(E.eto_for_day(P.state_from_log(self.log), self.station,
                                        _dt.date(2026, 7, 9), self.at))

    def test_the_daily_temperatures_alone_match_the_days_summary(self):
        state = P.state_from_log(self.log)
        got = E.daily_temperatures(state, self.station, self.day - _dt.timedelta(days=1),
                                   self.day + _dt.timedelta(days=1), self.at)
        s = E.day_summary(state, self.station, self.day, self.at)
        self.assertEqual(got[self.day], (s["tmin"], s["tmax"]))
        self.assertIsNone(got[self.day - _dt.timedelta(days=1)])
        self.assertIsNone(got[self.day + _dt.timedelta(days=1)])

    def test_the_days_reference_et(self):
        eto, rain, estimated = E.eto_for_day(P.state_from_log(self.log), self.station,
                                             self.day, self.at)
        self.assertGreater(eto, 2.0)
        self.assertLess(eto, 8.0)
        self.assertEqual((rain, estimated), (2.0, ()))

    def test_with_no_anemometer_the_sites_monthly_normal_stands_in(self):
        """`Station.wind_normal`: the month's mean wind at the site, not FAO-56's 2 m/s;
        the station's own wind, where it has some, is used before either."""
        import dataclasses
        state = P.state_from_log(self.log)
        measured = E.eto_for_day(state, self.station, self.day, self.at)
        calm = dataclasses.replace(self.station, wind_speed=None)
        guessed = E.eto_for_day(state, calm, self.day, self.at)
        normal = [2.0] * 12
        normal[6] = 2.0                                  # July's normal: the measured 2 m/s
        local = E.eto_for_day(state, dataclasses.replace(calm, wind_normal=tuple(normal)),
                              self.day, self.at)
        self.assertEqual(guessed[2], ("wind",))
        self.assertEqual(local[2], ("wind normal",))
        self.assertAlmostEqual(local[0], measured[0], places=9)
        normal[6] = 4.0
        windy = E.eto_for_day(state, dataclasses.replace(calm, wind_normal=tuple(normal)),
                              self.day, self.at)
        self.assertNotAlmostEqual(windy[0], local[0], places=3)
        kept = E.eto_for_day(state, dataclasses.replace(self.station, wind_normal=tuple(normal)),
                             self.day, self.at)
        self.assertEqual(kept, measured)


if __name__ == "__main__":
    unittest.main()
