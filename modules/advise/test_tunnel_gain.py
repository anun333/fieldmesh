# SPDX-License-Identifier: AGPL-3.0-or-later
"""A tunnel's gain, recovered from a synthetic tunnel whose gain is known.

The synthetic tunnel: inside = outside + a night gain that shrinks on colder nights
(3 °C on a mild night, 1.5 °C on a hard one, as a clear cold sky radiates heat away)
+ a day gain proportional to sunshine, which overheats it when the sides stay shut."""
import datetime as dt
import math
import os
import random
import sys
import unittest

import tunnel_gain as T

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "sim"))
import physics  # noqa: E402  the virtual farm's ground truth


def synthetic(days=365, seed=1):
    rng = random.Random(seed)
    start = dt.datetime(2024, 1, 1)
    inside, outside = [], []
    for d in range(days):
        season = -math.cos(2 * math.pi * (d - 15) / 365)          # cold in January
        mean = 14 + 11 * season + rng.gauss(0, 3)
        for h in range(24):
            t = start + dt.timedelta(days=d, hours=h)
            o = mean + 6 * math.sin(2 * math.pi * (h - 8) / 24)
            sun = max(0.0, math.sin(math.pi * (h - 6) / 12)) if 6 <= h <= 18 else 0.0
            night_gain = 3.0 if o > 0 else 1.5
            i = o + (night_gain if sun == 0 else 0.0) + 14 * sun
            outside.append((t, round(o, 1)))
            inside.append((t, round(i, 1)))
    return inside, outside


class GainTest(unittest.TestCase):
    def setUp(self):
        self.a = T.analyse(*synthetic())

    def test_the_cold_night_gain_is_recovered_and_errs_cold(self):
        self.assertAlmostEqual(self.a["winter_gain_c"], 1.5, delta=0.3)
        self.assertLessEqual(self.a["winter_gain_c"], 3.0)

    def test_gain_is_smaller_on_colder_nights(self):
        g = self.a["gain_by_outside_night"]
        self.assertGreater(g["above 5 °C"]["median_c"], g["below −5 °C"]["median_c"])

    def test_the_season_is_longer_inside(self):
        self.assertGreater(self.a["median_extension_days"], 0)

    def test_overheating_is_counted(self):
        self.assertGreater(self.a["hours_over_limit"], 0)
        self.assertGreater(self.a["fastest_rise_c_per_h"], 2.0)

    def test_nights_run_from_evening_to_morning(self):
        series = [(dt.datetime(2024, 1, 1, 20), 5.0), (dt.datetime(2024, 1, 2, 4), -3.0),
                  (dt.datetime(2024, 1, 2, 12), 9.0)]
        self.assertEqual(T.nightly_minima(series), {dt.date(2024, 1, 1): -3.0})


class SimulatorTest(unittest.TestCase):
    """A year of the virtual farm's tunnel (sim/physics.py), sampled hourly the way a
    logger would: the tool must recover the gain the physics was given, without being
    told it."""

    @classmethod
    def setUpClass(cls):
        def year(tunnel):
            world = physics.World(start=dt.datetime(2025, 1, 1, tzinfo=physics.UTC),
                                  climate=physics.Climate(seed=3, mean_temp_c=8.0, annual_swing_c=12.0),
                                  tunnels=[tunnel])
            inside, outside = [], []
            for i, truth in enumerate(world.run(days=365)):
                if i % 12 == 0:
                    t = truth.when.replace(tzinfo=None)
                    inside.append((t, truth.tunnel_temp[tunnel.name]))
                    outside.append((t, truth.weather.air_temp_c))
            return T.analyse(inside, outside)
        cls.tunnel = physics.Tunnel("hoop")
        cls.vented = year(cls.tunnel)
        cls.shut = year(physics.Tunnel("shut", vent_at_c=None))

    def test_recovers_the_clear_cold_night_gain(self):
        self.assertAlmostEqual(self.vented["winter_gain_c"], self.tunnel.cold_night_gain_c, delta=0.5)

    def test_the_figure_errs_cold(self):
        mild = self.vented["gain_by_outside_night"]["above 5 °C"]["median_c"]
        self.assertLess(self.vented["winter_gain_c"], mild)
        self.assertAlmostEqual(mild, self.tunnel.night_gain_c, delta=0.5)

    def test_measured_season_extension(self):
        self.assertGreater(self.vented["median_extension_days"], 7)

    def test_venting_is_what_keeps_it_from_cooking(self):
        self.assertGreater(self.shut["hours_over_limit"], 10 * max(1.0, self.vented["hours_over_limit"]))


if __name__ == "__main__":
    unittest.main()
