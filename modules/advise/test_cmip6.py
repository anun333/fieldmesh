# SPDX-License-Identifier: AGPL-3.0-or-later
"""Monthly CMIP6 changes, and the delta method applied by month and time of day."""
import datetime as _dt
import unittest
from unittest import mock

import cmip6 as C


class ShiftTest(unittest.TestCase):
    def test_days_and_nights_and_rain_move_by_their_own_month(self):
        monthly = {m: {"tmax": 1.0, "tmin": 2.0, "rain": 1.1} for m in range(1, 13)}
        monthly[7] = {"tmax": 3.0, "tmin": 1.0, "rain": 0.5}
        days = [(_dt.date(2001, 1, 15), {"T2M_MAX": 10.0, "T2M_MIN": 0.0, "T2M": 5.0, "PRECTOTCORR": 10.0}),
                (_dt.date(2001, 7, 15), {"T2M_MAX": 32.0, "T2M_MIN": 20.0, "T2M": 26.0, "PRECTOTCORR": 4.0})]
        out = C.shift_monthly(days, monthly)
        self.assertEqual(out[0][1], {"T2M_MAX": 11.0, "T2M_MIN": 2.0, "T2M": 6.5, "PRECTOTCORR": 11.0})
        self.assertEqual(out[1][1], {"T2M_MAX": 35.0, "T2M_MIN": 21.0, "T2M": 28.0, "PRECTOTCORR": 2.0})
        self.assertEqual(days[0][1]["T2M_MAX"], 10.0, "the original weather is untouched")


class DeltasTest(unittest.TestCase):
    def test_the_median_of_the_models_month_by_month(self):
        warming = {"A": 1.0, "B": 2.0, "C": 4.0}

        def fake(model, scenario, variable, year, lat, lon, cache):
            base = {"tasmax": 300.0, "tasmin": 290.0, "pr": 1e-5}[variable]
            if scenario != "historical":
                base = base * 1.2 if variable == "pr" else base + warming[model]
            return [(m, base) for m in range(1, 13)]

        with mock.patch.object(C, "point_year", fake):
            d = C.deltas(35.0, -86.6, "/nonexistent", models=("A", "B", "C"), workers=1)
        self.assertAlmostEqual(d["median"][7]["tmax"], 2.0)
        self.assertAlmostEqual(d["median"][1]["rain"], 1.2)
        self.assertEqual(d["per_model"]["C"][3]["tmin"], 4.0)


if __name__ == "__main__":
    unittest.main()
