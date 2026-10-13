#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Field capacity read off a bed's retention curve, from a tension sensor beside a probe."""
import math
import random
import unittest

import retention as RT


def silt_loam(kpa: float) -> float:
    """Van Genuchten's curve with Carsel and Parrish's (1988) mean silt loam: θr 0.067,
    θs 0.45, α 0.02 per cm, n 1.41. At 33 kPa it holds 0.239."""
    h_cm = kpa * 10.197
    m = 1.0 - 1.0 / 1.41
    return 0.067 + (0.45 - 0.067) / (1.0 + (0.02 * h_cm) ** 1.41) ** m


def drying(lo, hi, n=48):
    """Tensions from `lo` to `hi` kPa, as a bed dries between waterings."""
    return [lo * (hi / lo) ** (k / (n - 1)) for k in range(n)]


class TestRetention(unittest.TestCase):

    def test_the_curve_through_10_to_60_kpa_gives_its_water_at_33(self):
        found = RT.capacity_from_tension([(t, silt_loam(t)) for t in drying(10.0, 60.0)])
        self.assertAlmostEqual(silt_loam(33.0), 0.239, places=3)
        self.assertAlmostEqual(found["field_capacity"], silt_loam(33.0), delta=0.005)
        self.assertEqual(found["pairs"], 48)

    def test_with_a_probes_noise_still_within_a_hundredth(self):
        rng = random.Random(1)
        pairs = [(t, silt_loam(t) + rng.gauss(0.0, 0.005)) for t in drying(10.0, 60.0, 96)]
        self.assertAlmostEqual(RT.capacity_from_tension(pairs)["field_capacity"],
                               silt_loam(33.0), delta=0.01)

    def test_a_bed_kept_wet_has_not_shown_where_33_kpa_is(self):
        self.assertIsNone(RT.capacity_from_tension([(t, silt_loam(t)) for t in drying(10.0, 19.0)]))
        self.assertIsNone(RT.capacity_from_tension([(t, silt_loam(t)) for t in drying(10.0, 20.0)]),
                          "a span of two, but 33 kPa is past half again the driest seen")

    def test_too_few_points_or_a_curve_that_does_not_dry(self):
        self.assertIsNone(RT.capacity_from_tension([(t, silt_loam(t)) for t in drying(10.0, 60.0, 12)]))
        self.assertIsNone(RT.capacity_from_tension([(t, 0.2 + 0.001 * t) for t in drying(10.0, 60.0)]))

    def test_readings_outside_the_watermarks_calibration_are_left_out(self):
        pairs = [(t, silt_loam(t)) for t in drying(10.0, 60.0)] + [(5.0, 0.9), (150.0, 0.0)]
        self.assertEqual(RT.capacity_from_tension(pairs)["pairs"], 48)


if __name__ == "__main__":
    unittest.main()
