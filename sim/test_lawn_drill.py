#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The lawn drill: a timer, spray heads and the add-ons a home system can take, on
McAllister Farm's recorded summers of 2012 (a drought) and 2013 (the wettest of thirty)."""
from __future__ import annotations

import datetime as _dt
import os
import unittest

import lawn_drill as L
import physics as ph

HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE: dict = {}


def summer(year: int, policy: str, soil: str, soil_set: float = L.SOIL_SET_SHARE) -> dict:
    key = (year, policy, soil, soil_set)
    if key not in _CACHE:
        climate = ph.RecordedClimate.from_csv(
            os.path.join(HERE, "data", f"mcallister-{year}-summer.csv"), seed=1)
        _CACHE[key] = L.run(policy, soil, climate,
                            _dt.datetime(year, 6, 1, tzinfo=_dt.timezone.utc),
                            baseline=L.summer_baseline(climate), soil_set=soil_set)
    return _CACHE[key]


class TestTheAddOns(unittest.TestCase):

    def test_a_rain_sensor_skips_the_waterings_after_rain_and_costs_the_lawn_nothing(self):
        timer, sensor = summer(2013, "timer", "native"), summer(2013, "rain_sensor", "native")
        self.assertGreater(sensor["bypassed"], 5)
        self.assertLess(sensor["applied_mm"], 0.8 * timer["applied_mm"])
        self.assertEqual(sensor["stressed_h"], 0.0)

    def test_short_runs_or_rotary_nozzles_keep_spray_water_on_the_lawn(self):
        """Spray heads at 40 mm an hour outrun the silt loam once its surface is wet;
        three runs an hour apart, or nozzles at 15 mm an hour, do not."""
        self.assertGreater(summer(2013, "timer", "native")["runoff_mm"], 5.0)
        self.assertLess(summer(2013, "cycle_soak", "native")["runoff_mm"], 1.0)
        self.assertLess(summer(2013, "rotary", "native")["runoff_mm"], 1.0)

    def test_watering_by_the_weather_saves_a_third_without_drying_the_lawn(self):
        for year in (2012, 2013):
            for soil in L.SOILS:
                timer, weather = summer(year, "timer", soil), summer(year, "weather", soil)
                self.assertLess(weather["applied_mm"], 0.75 * timer["applied_mm"])
                self.assertLessEqual(weather["stressed_h"], timer["stressed_h"])

    def test_a_soil_sensor_set_low_starves_a_silt_loam_lawn(self):
        """AE437's automatic set point, 50 to 75% of the reading a day after a soaking,
        was tested on Florida's sands. In a silt loam that holds 0.30 and gives up its
        last water at 0.12, the middle of that range waits for the lawn to be dry."""
        low = summer(2012, "soil_sensor", "native", 0.625)
        high = summer(2012, "soil_sensor", "native", 0.85)
        self.assertGreater(low["stressed_h"], 200, "over a week of the summer")
        self.assertLess(high["stressed_h"], 0.5 * low["stressed_h"])

    def test_one_soak_calibrates_a_perched_yard_too_wet_and_it_floods(self):
        """Calibrated a day after a soaking, the yard's topsoil still holds water perched
        on the clay: the sensor's "full" is near saturation, the probe never reads it
        again, and an on-demand controller runs every cycle it may, every morning."""
        r = summer(2013, "on_demand", "yard")
        self.assertGreater(r["full"], ph.SANDY_LOAM["field_capacity"] + 0.1)
        self.assertGreater(r["applied_mm"], summer(2013, "timer", "yard")["applied_mm"])

    def test_every_policy_is_known_and_a_soil_is_one_of_two(self):
        with self.assertRaises(ValueError):
            L.lawn("clay")
        with self.assertRaises(ValueError):
            summer(2013, "hose", "native")


if __name__ == "__main__":
    unittest.main()
