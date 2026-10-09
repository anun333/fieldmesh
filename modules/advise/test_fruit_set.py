# SPDX-License-Identifier: AGPL-3.0-or-later
"""Heat at fruit set: counted only when both the days and the nights stay hot."""
import datetime as _dt
import unittest

import fruit_set as F

TOMATO = F.RULES["Solanum lycopersicum"]


def days(n, tmax, tmin, start=_dt.date(2020, 7, 1)):
    return [(start + _dt.timedelta(days=i), {"T2M_MAX": tmax, "T2M_MIN": tmin}) for i in range(n)]


class HeatDaysTest(unittest.TestCase):
    def test_hot_days_with_cool_nights_do_not_count(self):
        """The study's stress held the nights at 26 °C; Tennessee's summer nights do not."""
        r = F.heat_days(days(60, 35.0, 22.0), TOMATO)
        self.assertEqual((r["days_8_in_10"], r["warmest_night_mean_c"]), (0, 22.0))

    def test_a_chronic_heat_wave_counts_after_its_first_ten_days(self):
        r = F.heat_days(days(40, 33.0, 27.0), TOMATO)
        self.assertEqual(r["days_8_in_10"], 30)


if __name__ == "__main__":
    unittest.main()
