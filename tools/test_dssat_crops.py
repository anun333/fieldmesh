# SPDX-License-Identifier: Apache-2.0
"""The ported DSSAT pieces, against hand-worked values and DSSAT's own file layouts."""
import datetime as dt
import math
import unittest

import dssat_crops as D

# Lines from DSSAT's own files (tomato and guar), laid out exactly as there.
ECO = ("@ECO#  ECONAME.......... MG TM THVAR PL-EM EM-V1 V1-JU JU-R0  PM06  PM09 LNGSH R7-R8 FL-VS TRIFL RWDTH RHGHT R1PPO OPTBI SLOBI\n"
       "TM0001 SEMI-DETERMINATE  01 01   0.0   6.0  22.0   0.0  05.0   .55  0.75  39.0   0.0 24.50  0.45   1.0   1.0  .000  00.0  .000  10.0\n")
CUL = ("@VAR#  VRNAME.......... EXPNO   ECO#  CSDL PPSEN EM-FL FL-SH FL-SD SD-PM FL-LF\n"
       "999991 MINIMA               . DFAULT 12.33  0.00  24.4   2.2  19.0 45.00 47.00\n"
       "IB1111 Guar-Kinman          . GY0331 13.59 0.249  14.5   8.0  12.0 63.00 60.00\n")


class CurvTest(unittest.TestCase):
    def test_lin(self):
        self.assertEqual(D.curv("LIN", 7, 22, 28, 48, 5), 0.0)
        self.assertAlmostEqual(D.curv("LIN", 7, 22, 28, 48, 14.5), 0.5)
        self.assertEqual(D.curv("LIN", 7, 22, 28, 48, 25), 1.0)
        self.assertAlmostEqual(D.curv("LIN", 7, 22, 28, 48, 38), 0.5)

    def test_sin_uses_dssats_pi(self):
        pi = 22 / 7
        self.assertAlmostEqual(D.curv("SIN", 10, 30, 32, 55, 20),
                               0.5 * (1 + math.cos(2 * pi * (20 - 30) / 40)))
        self.assertEqual(D.curv("SIN", 10, 30, 32, 55, 31), 1.0)

    def test_short_day_curve(self):
        """INL: full rate at or below the critical day length, falling to THVAR."""
        self.assertEqual(D.curv("INL", 1.0, 12.0, 16.0, 0.2, 11.0), 1.0)
        self.assertAlmostEqual(D.curv("INL", 1.0, 12.0, 16.0, 0.2, 14.0), 0.6)
        self.assertEqual(D.curv("INL", 1.0, 12.0, 16.0, 0.2, 17.0), 0.2)

    def test_long_day_curve(self):
        self.assertEqual(D.curv("LON", 1.0, 14.0, 10.0, 0.3, 15.0), 1.0)
        self.assertEqual(D.curv("LON", 1.0, 14.0, 10.0, 0.3, 9.0), 0.3)


class ParseTest(unittest.TestCase):
    def test_ecotype_by_dssats_format(self):
        e = D.parse_eco(ECO)["TM0001"]
        self.assertEqual((e["THVAR"], e["PL-EM"], e["EM-V1"], e["V1-JU"], e["JU-R0"]),
                         (0.0, 6.0, 22.0, 0.0, 5.0))

    def test_cultivar_columns_and_the_minima_row_skipped(self):
        culs = D.parse_cul(CUL)
        self.assertEqual(len(culs), 1)
        c = culs[0]
        self.assertEqual((c["eco"], c["CSDL"], c["PPSEN"], c["EM-FL"], c["FL-SD"], c["SD-PM"]),
                         ("GY0331", 13.59, 0.249, 14.5, 12.0, 63.0))

    def test_thresholds(self):
        cul = {"CSDL": 13.59, "PPSEN": 0.249, "EM-FL": 14.5, "FL-SD": 12.0, "SD-PM": 63.0}
        eco = {"THVAR": 0.0, "PL-EM": 4.0, "V1-JU": 0.0, "JU-R0": 5.0, "R1PPO": 0.324}
        th = D.thresholds(cul, eco)
        self.assertEqual(th["phthrs"][5], 9.5, "EM-FL less V1-JU and JU-R0")
        self.assertAlmostEqual(th["cldl"], 13.59 + 1 / 0.249)


class DevelopTest(unittest.TestCase):
    def test_constant_optimal_weather_takes_exactly_the_photothermal_days(self):
        """At an optimal temperature with day-neutral response, a photothermal day is a
        calendar day."""
        spe = {"temps": {1: (7, 22, 28, 48), 2: (7, 22, 28, 48), 3: (7, 22, 28, 48)},
               "phases": {j: {"daylength": "NON", "temperature": "LIN", "row": 1} for j in D.PATH}}
        th = {"phthrs": {1: 5, 3: 0, 4: 5, 5: 10, 8: 20, 10: 40}, "csdl": 12, "cldl": 1e9,
              "thvar": 0, "r1ppo": 0}
        start = dt.date(2020, 5, 1)
        days = [(start + dt.timedelta(days=i), {"T2M_MIN": 24.0, "T2M_MAX": 26.0}) for i in range(200)]
        r = D.develop(spe, th, days, 0, 35.0)
        self.assertEqual(r["flower"], 19)        # 5 + 0 + 5 + 10 days, counted from 0
        self.assertEqual(r["maturity"], 79)      # + 20 + 40

    def test_frost_stops_it(self):
        spe = {"temps": {1: (7, 22, 28, 48), 2: (7, 22, 28, 48), 3: (7, 22, 28, 48)},
               "phases": {j: {"daylength": "NON", "temperature": "LIN", "row": 1} for j in D.PATH}}
        th = {"phthrs": {1: 5, 3: 0, 4: 5, 5: 10, 8: 20, 10: 40}, "csdl": 12, "cldl": 1e9,
              "thvar": 0, "r1ppo": 0}
        days = [(dt.date(2020, 5, 1) + dt.timedelta(days=i), {"T2M_MIN": 24.0, "T2M_MAX": 26.0})
                for i in range(200)]
        self.assertIsNone(D.develop(spe, th, days, 0, 35.0, stop=50)["maturity"])

    def test_civil_day_length_is_longer_than_sunrise_to_sunset(self):
        self.assertGreater(D.civil_day_length(35, 172), 15.0)
        self.assertLess(D.civil_day_length(35, 172), 15.6)


class MaizeTest(unittest.TestCase):
    ECO = {"TBASE": 8.0, "TOPT": 34.0, "P2O": 12.5, "DJTI": 4.0, "GDDE": 6.0, "DSGFT": 170.0}
    CUL = {"P1": 160.0, "P2": 0.75, "P5": 780.0, "PHINT": 49.0}

    def test_thermal_time(self):
        self.assertEqual(D.maize_dtt(2, 7, 20, 12, 12, 8, 34), 0.0, "below base all day")
        self.assertEqual(D.maize_dtt(20, 30, 20, 12, 12, 8, 34), 17.0, "mean less base")
        self.assertEqual(D.maize_dtt(35, 40, 20, 12, 12, 8, 34), 26.0, "capped at the optimum")
        self.assertGreater(D.maize_dtt(4, 20, 20, 12, 12, 8, 34), 0.0, "sine when crossing the base")

    def days(self, temp, n=300, srad=20.0):
        start = dt.date(2020, 5, 1)
        return [(start + dt.timedelta(days=i), {"T2M_MIN": temp, "T2M_MAX": temp,
                                                "ALLSKY_SFC_SW_DWN": srad}) for i in range(n)]

    def test_it_silks_then_matures(self):
        r = D.develop_maize(self.CUL, self.ECO, self.days(28.0), 0, 35.0)
        self.assertIsNotNone(r["flower"])
        self.assertGreater(r["maturity"], r["flower"])
        # 20 thermal units a day at 28 °C: P5 = 780 after silking is 39 days.
        self.assertEqual(r["maturity"] - r["flower"], 39)

    def test_a_longer_season_hybrid_matures_later(self):
        early = D.develop_maize(self.CUL, self.ECO, self.days(28.0), 0, 35.0)
        late = D.develop_maize({**self.CUL, "P5": 950.0}, self.ECO, self.days(28.0), 0, 35.0)
        self.assertGreater(late["maturity"], early["maturity"])

    def test_cold_stops_it(self):
        self.assertIsNone(D.develop_maize(self.CUL, self.ECO, self.days(6.0), 0, 35.0)["maturity"])


if __name__ == "__main__":
    unittest.main()
