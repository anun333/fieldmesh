# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bloom from chill then heat, and frost after it, worked by hand."""
import datetime as dt
import unittest

import fruit_bloom as F


class UnitsTest(unittest.TestCase):
    def test_growing_degree_hours(self):
        self.assertEqual(F.gdh_weight(4.0), 0.0)
        self.assertAlmostEqual(F.gdh_weight(14.5), 10.5)          # halfway up: half of 21
        self.assertAlmostEqual(F.gdh_weight(25.0), 21.0)          # the optimum
        self.assertAlmostEqual(F.gdh_weight(30.5), 21.0 * (1 - 2 ** -0.5))
        self.assertAlmostEqual(F.gdh_weight(36.0), 0.0)
        self.assertEqual(F.gdh_weight(40.0), 0.0)

    def test_a_requirement_s_middle(self):
        self.assertEqual(F.central("1000–1100"), 1050.0)
        self.assertEqual(F.central("828 ± 139"), 828.0)
        self.assertEqual(F.central("<300"), 300.0)
        self.assertIsNone(F.central("> 1100"))
        self.assertIsNone(F.central("Very high"))


class BloomTest(unittest.TestCase):
    def days(self, frost_on=None):
        start = dt.date(2019, 11, 1)
        out = []
        for i in range(300):
            t = 5.0 if i < 10 else 14.5
            v = {"T2M_MIN": t, "T2M_MAX": t}
            if i == frost_on:
                v["T2M_MIN"] = -3.0
            out.append((start + dt.timedelta(days=i), v))
        return out

    def test_by_hand(self):
        # 24 chill hours a day at 5 °C meets 240 on day 9; heat counts from day 10, at
        # 10.5 x 24 = 252 a day, and 500 is met on day 11: bloom.
        days = self.days()
        i, frost, met = F.bloom(F.daily_units(days), days, 0, 240.0, 500.0)
        self.assertEqual((i, frost, met), (11, False, True))

    def test_frost_within_two_weeks_of_bloom_counts(self):
        for frost_on, expected in ((20, True), (30, False)):
            days = self.days(frost_on)
            self.assertEqual(F.bloom(F.daily_units(days), days, 0, 240.0, 500.0)[1], expected, frost_on)

    def test_chill_met_after_march_is_a_short_winter(self):
        start = dt.date(2019, 11, 1)
        days = [(start + dt.timedelta(days=i), {"T2M_MIN": 5.0, "T2M_MAX": 5.0}) for i in range(300)]
        units = F.daily_units(days)
        # 24 hours a day: 3600 hours is met on day 149 (in time), 3700 on day 154 (late).
        self.assertTrue(F.bloom(units, days, 0, 3600.0, 10 ** 6)[2] is True)
        self.assertTrue(F.bloom(units, days, 0, 3700.0, 10 ** 6)[2] is False)

    def test_chill_never_met(self):
        days = self.days()
        self.assertEqual(F.bloom(F.daily_units(days), days, 0, 10 ** 6, 500.0), (None, False, False))

    def test_dates_count_from_the_season_start(self):
        self.assertEqual(F.as_date(0), "Nov 01")
        self.assertEqual(F.as_date(145), "Mar 26")
        self.assertEqual(F.as_date(0, north=False), "May 01")


if __name__ == "__main__":
    unittest.main()
