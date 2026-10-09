# SPDX-License-Identifier: Apache-2.0
"""Watering by the clock, the forecast and the soil, on the bundled wet summer."""
import datetime as dt
import unittest

import irrigation_drill as D
import physics as ph

UTC = dt.timezone.utc


class WaterAccountsTest(unittest.TestCase):
    def test_a_bed_accounts_for_its_water(self):
        b = D.bed()
        start = b.stored_mm
        weather = ph.Weather(air_temp_c=25.0, relative_humidity=60.0, rain_mm=3.0, et0_mm=0.05, raining=True)
        for _ in range(500):
            b.step(weather)
        rain = 3.0 * 500
        self.assertAlmostEqual(start + rain, b.stored_mm + b.et_mm + b.drained_mm + b.runoff_mm, places=6)
        self.assertGreater(b.runoff_mm, 0.0, "a saturated bed sheds the rest")


class SummerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = D.season(D.SUMMER, dt.datetime(2013, 6, 1, tzinfo=UTC), 30)

    def test_the_timer_waters_on_schedule(self):
        self.assertAlmostEqual(self.r["timer"]["applied_mm"], 15 * D.DOSE_MM, places=6)

    def test_skipping_on_forecast_rain_saves_water_without_stress(self):
        t, s = self.r["timer"], self.r["rain_skip"]
        self.assertGreater(s["skipped"], 0)
        self.assertLess(s["applied_mm"], t["applied_mm"])
        self.assertLess(s["drained_mm"], t["drained_mm"])
        self.assertLessEqual(s["stressed_h"], t["stressed_h"] + 1.0)

    def test_the_soil_rule_waters_least_in_a_wet_summer(self):
        self.assertLess(self.r["soil"]["applied_mm"], self.r["rain_skip"]["applied_mm"])

    def test_every_policy_sees_the_same_rain(self):
        rains = {round(v["rain_mm"], 6) for v in self.r.values()}
        self.assertEqual(len(rains), 1)


if __name__ == "__main__":
    unittest.main()
