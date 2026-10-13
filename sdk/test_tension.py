# SPDX-License-Identifier: Apache-2.0
"""The Watermark's calibration, as Shock et al. (1998) give it."""
import unittest

import tension as T


class TestWatermark(unittest.TestCase):

    def test_shock_et_al_at_six_kilohms_and_20_degrees(self):
        """(4.093 + 3.213 × 6) / (1 − 0.009733 × 6 − 0.01205 × 20) = 33.36 kPa: about the
        tension soil holds water at, at field capacity."""
        self.assertAlmostEqual(T.watermark_kpa(6.0, 20.0), 33.36, places=2)

    def test_warmer_soil_reads_drier_at_the_same_resistance(self):
        """Resistance falls as the soil warms, so the same resistance in warmer soil means
        drier soil."""
        self.assertGreater(T.watermark_kpa(6.0, 30.0), T.watermark_kpa(6.0, 10.0))

    def test_outside_the_calibrated_10_to_75_kpa_it_says_nothing(self):
        self.assertIsNone(T.watermark_kpa(1.0, 20.0))         # about 9.7 kPa: too wet to vouch for
        self.assertIsNone(T.watermark_kpa(20.0, 20.0))        # far past 75 kPa
        self.assertIsNone(T.watermark_kpa(0.0, 20.0))
        self.assertIsNotNone(T.watermark_kpa(2.0, 20.0))


if __name__ == "__main__":
    unittest.main()
