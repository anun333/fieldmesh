# SPDX-License-Identifier: Apache-2.0
"""The site profile's arithmetic, against values that are known."""
import datetime as dt
import math
import unittest

import site_profile as T


class SunTest(unittest.TestCase):
    def test_day_length(self):
        self.assertAlmostEqual(T.day_length_h(0, 172), 12.0, delta=0.1)
        self.assertAlmostEqual(T.day_length_h(35, 81), 12.0, delta=0.2)     # equinox
        self.assertGreater(T.day_length_h(35, 172), 14.2)                    # June, Tennessee
        self.assertLess(T.day_length_h(35, 172), 14.8)
        self.assertEqual(T.day_length_h(80, 172), 24.0)
        self.assertEqual(T.day_length_h(80, 355), 0.0)


class TemperatureTest(unittest.TestCase):
    def test_hours_below(self):
        self.assertEqual(T.hours_below(0, 5, 7.2), 24.0)
        self.assertEqual(T.hours_below(10, 20, 7.2), 0.0)
        self.assertAlmostEqual(T.hours_below(2.2, 12.2, 7.2), 12.0)

    def test_chill_hours_skip_hours_below_freezing(self):
        days = [(dt.date(2019, 11, 1) + dt.timedelta(days=i), {"T2M": -5.0, "T2M_MAX": -1.0, "T2M_MIN": -9.0,
                                                                "PRECTOTCORR": 1.0, "RH2M": 70.0})
                for i in range(800)]
        self.assertEqual(T.climate(days, 35.0)["chill_hours_est"], 0, "a frozen winter gives no chill")

    def test_growing_degree_days_86_50(self):
        self.assertEqual(T.gdd(5, 9), 0.0)
        self.assertEqual(T.gdd(15, 25), 10.0)
        self.assertEqual(T.gdd(20, 40), 15.0, "maximum capped at 30")
        self.assertEqual(T.gdd(5, 20), 5.0, "minimum floored at 10")

    def test_hardiness_zone(self):
        # Zone 7 is 0 to 10 °F: 7a below 5 °F, 7b above; zone 8 starts at 10 °F.
        self.assertEqual(T.hardiness_zone((2 - 32) * 5 / 9), "7a")
        self.assertEqual(T.hardiness_zone((7 - 32) * 5 / 9), "7b")
        self.assertEqual(T.hardiness_zone((12 - 32) * 5 / 9), "8a")
        self.assertEqual(T.hardiness_zone((-25 - 32) * 5 / 9), "4b")

    def test_thi(self):
        self.assertAlmostEqual(T.thi(25, 50), 71.78, delta=0.01)   # 77 - 0.275 x 19


class KoppenTest(unittest.TestCase):
    def test_nashville_is_humid_subtropical(self):
        temps = [3, 5, 10, 15, 20, 24, 26, 26, 22, 16, 10, 5]
        precs = [100, 110, 120, 115, 125, 100, 105, 85, 90, 75, 105, 115]
        self.assertEqual(T.koppen(temps, precs, 36), "Cfa")

    def test_phoenix_is_hot_desert(self):
        temps = [13, 15, 18, 22, 27, 32, 35, 34, 31, 24, 17, 13]
        precs = [23, 23, 25, 7, 3, 1, 26, 27, 16, 15, 17, 23]
        self.assertEqual(T.koppen(temps, precs, 33), "BWh")

    def test_singapore_is_rainforest(self):
        self.assertEqual(T.koppen([27] * 12, [240, 160, 180, 160, 170, 140, 150, 150, 140, 160, 250, 270], 1), "Af")

    def test_minneapolis_is_humid_continental(self):
        temps = [-9, -6, 1, 9, 16, 21, 24, 22, 17, 10, 1, -7]
        precs = [23, 20, 46, 70, 95, 110, 105, 110, 80, 65, 45, 30]
        self.assertEqual(T.koppen(temps, precs, 45), "Dfa")


class ErosionTest(unittest.TestCase):
    def test_rainfall_factor_is_continuous_at_850_mm(self):
        self.assertAlmostEqual(T.rainfall_erosivity(850), T.rainfall_erosivity(850.001), delta=5)

    def test_ls_at_the_standard_plot(self):
        """9% slope, 22.13 m: LS is 1 by definition of the unit plot (within the fit)."""
        self.assertAlmostEqual(T.ls_factor(9.0), 1.0, delta=0.1)
        self.assertLess(T.ls_factor(2.0), T.ls_factor(9.0))


class DaysTest(unittest.TestCase):
    def test_fill_values_are_dropped(self):
        doc = {"properties": {"parameter": {"T2M": {"20200101": 1.0, "20200102": -999.0},
                                            "RH2M": {"20200101": 50.0, "20200102": 60.0}}}}
        days = T.days_of(doc)
        self.assertEqual(days[0], (dt.date(2020, 1, 1), {"T2M": 1.0, "RH2M": 50.0}))
        self.assertEqual(days[1][1], {"RH2M": 60.0})


class ShiftTest(unittest.TestCase):
    def test_delta_method(self):
        days = [(dt.date(2020, 1, 1), {"T2M": 1.0, "T2M_MAX": 5.0, "T2M_MIN": -2.0, "PRECTOTCORR": 10.0, "RH2M": 80.0})]
        (d, v), = T.shift(days, 1.5, -10)
        self.assertEqual((v["T2M"], v["T2M_MAX"], v["T2M_MIN"]), (2.5, 6.5, -0.5))
        self.assertAlmostEqual(v["PRECTOTCORR"], 9.0)
        self.assertEqual(v["RH2M"], 80.0)
        self.assertEqual(days[0][1]["T2M"], 1.0, "the original is untouched")


if __name__ == "__main__":
    unittest.main()
