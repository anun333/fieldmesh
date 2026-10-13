#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A crop's clock in degree-days: a day's degree-days, the farm's normal year, and how far
through its curve a crop is in a warm year, a cool one and a normal one."""
from __future__ import annotations

import datetime as _dt
import unittest

import thermal as T

PLANTED = _dt.date(2026, 5, 1)


def record(years, tmin, tmax):
    """`{date: (tmin, tmax)}`, the same every day of `years`."""
    out = {}
    for y in years:
        d = _dt.date(y, 1, 1)
        while d.year == y:
            out[d] = (tmin, tmax)
            d += _dt.timedelta(days=1)
    return out


class TestADaysDegreeDays(unittest.TestCase):
    """Paredes et al. (2025a), Eq. 2."""

    def test_the_mean_less_the_base_held_under_the_upper_threshold(self):
        self.assertEqual(T.gdd(10.0, 20.0, 8.0, 30.0), 7.0)
        self.assertEqual(T.gdd(2.0, 10.0, 8.0, 30.0), 0.0)        # mean 6, under the base
        self.assertEqual(T.gdd(26.0, 40.0, 8.0, 30.0), 22.0)      # mean 33, held at 30

    def test_the_thresholds_are_the_reviews(self):
        self.assertEqual(T.THRESHOLDS["tomato"], (8.0, 30.0))
        self.assertEqual(T.THRESHOLDS["lettuce"], (4.0, 28.0))
        self.assertEqual(len(T.THRESHOLDS), 20)


class TestTheNormalYear(unittest.TestCase):

    def test_each_day_is_the_mean_of_its_years(self):
        past = {**record([2020], 10.0, 20.0), **record([2021], 14.0, 24.0)}
        normal = T.Normal(past)
        self.assertAlmostEqual(normal.gdd(_dt.date(2026, 6, 1), 8.0, 30.0), 9.0)
        self.assertAlmostEqual(T.Normal(past, without=2021).gdd(_dt.date(2026, 6, 1), 8.0, 30.0),
                               7.0)

    def test_the_first_of_march_is_one_day_in_every_year(self):
        self.assertEqual(T._day_index(_dt.date(2024, 3, 1)), T._day_index(_dt.date(2025, 3, 1)))
        self.assertEqual(T._day_index(_dt.date(2024, 2, 29)), 59)


class TestTheCropsClock(unittest.TestCase):
    """Tomatoes (base 8, upper 30) sown on 1 May, in a normal year of 8 degree-days a day
    (a mean of 16 °C)."""

    normal = T.Normal(record(range(2010, 2020), 11.0, 21.0))

    def clock(self, tmin, tmax, days=40, missing=()):
        actual = {PLANTED + _dt.timedelta(days=n): (tmin, tmax) for n in range(days)}
        for n in missing:
            actual[PLANTED + _dt.timedelta(days=n)] = None
        return T.growing_days("tomato", PLANTED, PLANTED + _dt.timedelta(days=days), actual,
                              self.normal)

    def test_a_normal_year_keeps_the_calendar(self):
        c = self.clock(11.0, 21.0)
        self.assertEqual(c[PLANTED], 0.0)
        self.assertAlmostEqual(c[PLANTED + _dt.timedelta(days=30)], 30.0, places=6)

    def test_a_warm_year_runs_ahead_and_a_cool_one_behind(self):
        warm = self.clock(13.0, 23.0)        # 10 a day: a quarter more than normal
        cool = self.clock(9.0, 19.0)         # 6 a day: a quarter less
        self.assertAlmostEqual(warm[PLANTED + _dt.timedelta(days=30)], 37.5, places=6)
        self.assertAlmostEqual(cool[PLANTED + _dt.timedelta(days=30)], 22.5, places=6)

    def test_a_day_the_station_missed_counts_as_a_normal_one(self):
        c = self.clock(13.0, 23.0, missing=range(10, 20))
        self.assertAlmostEqual(c[PLANTED + _dt.timedelta(days=30)], 20 * 1.25 + 10, places=6)

    def test_a_cold_spell_still_moves_the_crop_on(self):
        cold = self.clock(0.0, 6.0)          # under the base: nothing but the floor
        self.assertGreater(cold[PLANTED + _dt.timedelta(days=30)], 0.0)
        self.assertLess(cold[PLANTED + _dt.timedelta(days=30)], 1.0)


if __name__ == "__main__":
    unittest.main()
