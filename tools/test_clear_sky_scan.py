#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The clear-sky check on a year of a reference station's sunshine: NOAA's Climate
Reference Network at Crossville, Tennessee, 2024 (`tools/clear_sky_scan.py`)."""
from __future__ import annotations

import os
import unittest

import clear_sky_scan as S

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "uscrn-crossville-2024-solar.csv.gz")


class TestOnAReferenceStation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = S.scan(S.read(FIXTURE), S.CROSSVILLE)

    def test_a_healthy_year_raises_nothing(self):
        self.assertGreater(self.r["hours"], 8700)
        self.assertEqual(self.r["clean"], {"hourly": 0, "moment": 0})

    def test_a_clock_on_local_time_read_as_utc_is_caught_every_day(self):
        self.assertGreaterEqual(self.r["clock_lst"]["days"], self.r["sunny_days"])

    def test_a_clock_an_hour_out_is_caught_most_weeks(self):
        """An hour moves the sunrise less than the margin on cloudy mornings; on a sunny
        one it shows. 219 of 366 days."""
        self.assertGreater(self.r["clock_hour"]["days"], 200)

    def test_light_in_lux_sent_as_watts_is_caught_every_day(self):
        self.assertEqual(self.r["lux"]["days"], 365)

    def test_a_sensor_thirty_percent_high_is_only_sometimes_caught(self):
        """The check is a ceiling, not a calibration: only clear hours near the top of
        the sky show a 30% gain. A calibration needs clear days compared over weeks."""
        self.assertGreater(self.r["gain"]["days"], 30)
        self.assertLess(self.r["gain"]["days"], self.r["sunny_days"] / 2)


if __name__ == "__main__":
    unittest.main()
