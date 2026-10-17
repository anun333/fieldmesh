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



class ControllersTest(unittest.TestCase):
    """What the free irrigation controllers do, on the same weather (irrigation-projects.md)."""

    def test_reference_et_matches_fao56_example_18(self):
        """Uccle, 6 July: 21.5 / 12.3 °C, RH 84 and 63 %, 22.07 MJ, wind 2.078 m/s, 100 m
        above the sea at 50° 48' N gives 3.9 mm; from the mean humidity, within a tenth."""
        e = ph.fao56_eto(12.3, 21.5, (84 + 63) / 2, 22.07, 187, 50.8, 100.0, wind_m_s=2.078)
        self.assertAlmostEqual(e, 3.9, delta=0.15)

    def test_zimmerman_from_its_documented_baselines(self):
        day = lambda c, rh, mm: {"T2M": c, "RH2M": rh, "PRECTOTCORR": mm}
        self.assertAlmostEqual(D.zimmerman_scale(day(21.111, 30.0, 0.0)), 100.0, places=1)
        self.assertAlmostEqual(D.zimmerman_scale(day(21.111, 30.0, 12.7)), 0.0, places=1,
                               msg="half an inch of rain cancels the day")
        self.assertEqual(D.zimmerman_scale(day(40.0, 5.0, 0.0)), 200.0, "held at 200")

    def test_pyfao56s_saved_schedule_waters_the_bed_without_a_probe(self):
        """On the simulator of 2026-10-16, whose crop uses its whole demand until half its
        water is gone and about a fifth more than FAO-56's balance counts, the schedule
        left the bed short 10 hours in June; never, on the earlier one."""
        r = D.season(D.SUMMER, dt.datetime(2013, 6, 1, tzinfo=UTC), 92, policies=("timer", "pyfao56"))
        self.assertGreater(r["pyfao56"]["applied_mm"], 0.0)
        self.assertLess(r["pyfao56"]["applied_mm"], r["timer"]["applied_mm"])
        self.assertLess(r["pyfao56"]["stressed_h"], 12.0)

    def test_each_controller_waters_less_than_the_timer_on_a_wet_summer(self):
        r = D.season(D.SUMMER, dt.datetime(2013, 6, 1, tzinfo=UTC), 30, policies=("timer",) + D.CONTROLLERS)
        for policy in D.CONTROLLERS:
            self.assertLess(r[policy]["applied_mm"], r["timer"]["applied_mm"], policy)
            self.assertLessEqual(r[policy]["stressed_h"], 12.0 if policy == "pyfao56" else 0.0,
                                 policy)


if __name__ == "__main__":
    unittest.main()
