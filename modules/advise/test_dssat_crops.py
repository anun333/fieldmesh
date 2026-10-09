# SPDX-License-Identifier: AGPL-3.0-or-later
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


class SorghumTest(unittest.TestCase):
    ECO = {"TBASE": 8.0, "TOPT": 34.0, "ROPT": 34.0, "GDDE": 6.0}
    CUL = {"P1": 360.0, "P2": 102.0, "P2O": 12.5, "P2R": 0.0, "PANTH": 617.5, "P3": 152.5,
           "P4": 81.5, "P5": 540.0, "PHINT": 49.0}
    days = MaizeTest.days

    def test_the_stages_by_hand(self):
        # 20 thermal units a day at 28 °C. Emergence at 50 + 6 x 5 = 80 (day 3); juvenile
        # 360 more (day 21); panicle initiation P2 = 102 later (day 27); flag leaf after
        # PANTH − P3 = 465 (day 51, 15 over); anthesis at P3 = 152.5 (day 58); grain fill
        # from P3 + P4 = 234 (day 62, 1 over); P5 = 540 (day 89); maturity the next day.
        r = D.develop_sorghum(self.CUL, self.ECO, self.days(28.0), 0, 35.0)
        self.assertEqual((r["flower"], r["maturity"]), (58, 90))

    def test_long_days_hold_back_a_sensitive_cultivar(self):
        neutral = D.develop_sorghum(self.CUL, self.ECO, self.days(28.0), 0, 35.0)
        sensitive = D.develop_sorghum({**self.CUL, "P2O": 12.8, "P2R": 1800.0}, self.ECO,
                                      self.days(28.0), 0, 35.0)
        self.assertGreater(sensitive["flower"] or 999, neutral["flower"] + 30)

    def test_columns(self):
        line = ("IB0001 RIO                  . IB0001 430.0 102.0 11.60  24.0 617.5 152.5  81.5 "
                "540.0 49.00    .0   6.0")
        (c,) = D.parse_sorghum_cul(line)
        self.assertEqual((c["name"], c["P1"], c["P2O"], c["P2R"], c["PANTH"], c["P5"], c["PHINT"]),
                         ("RIO", 430.0, 11.6, 24.0, 617.5, 540.0, 49.0))
        e = D.parse_sorghum_eco("IB0002 West Africa        11.0  34.0  34.0   6.0   3.8  0.85 3.000 0.200   1.0 6000.")
        self.assertEqual(e["IB0002"], {"TBASE": 11.0, "TOPT": 34.0, "ROPT": 34.0, "GDDE": 6.0})


class MilletTest(unittest.TestCase):
    ECO = {"TBASE": 10.0, "TOPT": 34.0, "ROPT": 34.0, "DJTI": 68.0, "GDDE": 6.0}
    CUL = {"P1": 120.0, "P2O": 20.0, "P2R": 125.0, "P5": 360.0, "PHINT": 43.0}
    days = MaizeTest.days

    def test_the_stages_by_hand(self):
        # 18 a day at 28 °C. Emergence at 45 + 30 = 75 (day 4, 15 over); juvenile to 120
        # (day 10, at 123); 18/68 of the index a day reaches 1 on day 14, at 195, so
        # P3 = 370 + 0.135 x 195 = 396.3, counted from that day's 18 (day 36, 17.7 over);
        # anthesis at 50 (day 38); grain fill from 150 (day 44, 11.7 over); P5 first met
        # on day 64, P5 + 90 on days 69 and 70; maturity on day 71.
        r = D.develop_millet(self.CUL, self.ECO, self.days(28.0), 0, 35.0)
        self.assertEqual((r["flower"], r["maturity"]), (38, 71))

    def test_long_days_hold_back_a_sensitive_variety(self):
        neutral = D.develop_millet(self.CUL, self.ECO, self.days(28.0), 0, 35.0)
        sensitive = D.develop_millet({**self.CUL, "P2O": 12.0, "P2R": 900.0}, self.ECO,
                                     self.days(28.0), 0, 35.0)
        self.assertGreater(sensitive["flower"] or 999, neutral["flower"] + 20)

    def test_columns(self):
        (c,) = D.parse_millet_cul("990001 NORTH VARIETY        . IB0001 120.0 12.00 125.0 360.0  2.00  0.50 43.00  1.00  11.0")
        self.assertEqual((c["P1"], c["P2O"], c["P2R"], c["P5"], c["PHINT"]), (120.0, 12.0, 125.0, 360.0, 43.0))
        e = D.parse_millet_eco("IB0001 GENERIC            10.0 34.0  34.0  68.0   6.0   4.0  0.85")
        self.assertEqual(e["IB0001"], {"TBASE": 10.0, "TOPT": 34.0, "ROPT": 34.0, "DJTI": 68.0, "GDDE": 6.0})


class CscerTest(unittest.TestCase):
    def test_rye_reads_like_wheat(self):
        """RYCER048 is in the wheat and barley format, so rye runs on the same port."""
        (c,) = D.parse_cscer_cul("JR2020 Palazzo              . JKWR10    17   178   755    23    32   5.1    85")
        self.assertEqual((c["name"], c["code"], c["eco"], c["P1V"], c["P1D"], c["P5"]),
                         ("Palazzo", "JR2020", "JKWR10", 17.0, 178.0, 755.0))

    SPE = {"PGERM": 10.0, "PEMRG": 8.0, "P0": 0.0, "P6": 200.0, "PPFPE": 1.0, "PPTHR": 20.0,
           "PPEND": 2.0, "TKUH": -6.0, "HDUR": 10.0, "TRGEM": (1, 26, 50, 60), "TRDV1": (0, 26, 50, 60),
           "TRDV2": (0, 30, 50, 60), "TRVRN": (-5, 0, 7, 15), "TRHAR": (-5, 0, 5, 10)}
    ECO = {"P1": 100.0, "P2FR1": 0.25, "P2": 100.0, "P3": 100.0, "P4FR1": 0.25, "P4FR2": 0.1,
           "P4": 100.0, "VEFF": 0.0, "TKFH": -20.0}
    CUL = {"P1V": 0.0, "P1D": 0.0, "P5": 200.0, "PHINT": 95.0}
    days = MaizeTest.days

    def test_tfac4(self):
        self.assertEqual(D.tfac4((0, 26, 50, 60), 13), (0.5, 13.0))
        self.assertEqual(D.tfac4((0, 26, 50, 60), 40), (1.0, 26.0))
        self.assertEqual(D.tfac4((0, 26, 50, 60), 55)[0], 0.5)
        self.assertEqual(D.tfac4((0, 26, 50, 60), -3), (0.0, 0.0))

    def test_the_stages_by_hand(self):
        # 20 units a day at 20 °C, from the second day (the vernalization factor starts at
        # 0). Thresholds 100/200/300/400/600: anthesis a quarter into phase 4, at 325
        # (day 17); maturity at the end of phase 5, 600 (day 30).
        r = D.develop_cscer(self.CUL, self.ECO, self.SPE, self.days(20.0), 0, 35.0)
        self.assertEqual((r["flower"], r["maturity"]), (17, 30))

    def test_a_winter_wheat_needs_its_cold(self):
        cul = {**self.CUL, "P1V": 50.0}
        eco = {**self.ECO, "VEFF": 1.0}
        self.assertIsNone(D.develop_cscer(cul, eco, self.SPE, self.days(20.0), 0, 35.0)["maturity"],
                          "never vernalized at 20 °C")
        cold_then_warm = self.days(5.0, 60) + [(d + dt.timedelta(days=60), v) for d, v in self.days(20.0, 200)]
        self.assertIsNotNone(D.develop_cscer(cul, eco, self.SPE, cold_then_warm, 0, 35.0)["maturity"])

    def test_hardened_wheat_survives_what_kills_an_unhardened_one(self):
        start = dt.date(2020, 10, 1)
        def season(first_c, n_first):
            temps = [first_c] * n_first + [-14.0] * 3 + [12.0] * 250
            return [(start + dt.timedelta(days=i), {"T2M_MIN": t, "T2M_MAX": t}) for i, t in enumerate(temps)]
        cul = {**self.CUL, "P1V": 30.0}
        eco = {**self.ECO, "VEFF": 1.0}
        warm = D.develop_cscer(cul, eco, self.SPE, season(12.0, 20), 0, 35.0)    # no hardening
        # At 6 °C it emerges in nine days (5 germination units a day against 10 + 8 x 4)
        # and hardens 0.8 of a day a day, fully within the 40; at 12 °C it never hardens.
        hard = D.develop_cscer(cul, eco, self.SPE, season(6.0, 40), 0, 35.0)
        cannot_harden = D.develop_cscer(cul, {**eco, "TKFH": -6.0}, self.SPE, season(6.0, 40), 0, 35.0)
        self.assertTrue(warm["winter_killed"])
        self.assertFalse(hard["winter_killed"])
        self.assertTrue(cannot_harden["winter_killed"], "the same season, without hardening, kills")

    def test_a_freeze_after_boot_ends_it_and_before_does_not(self):
        # Constant 20 °C reaches boot (300 units) on day 16 and anthesis on day 17.
        def with_freeze(day):
            days = self.days(20.0)
            d, v = days[day]
            days[day] = (d, {**v, "T2M_MIN": -3.0})
            return D.develop_cscer(self.CUL, self.ECO, self.SPE, days, 0, 35.0)
        self.assertTrue(with_freeze(20)["frozen_in_head"])
        early = with_freeze(8)
        self.assertFalse(early["frozen_in_head"])
        self.assertIsNotNone(early["maturity"])

    def test_heat_while_it_flowers_ends_it(self):
        hot = D.develop_cscer(self.CUL, self.ECO, self.SPE,
                              [(d, {**v, "T2M_MAX": 33.0, "T2M_MIN": 7.0}) for d, v in self.days(20.0)],
                              0, 35.0)
        self.assertTrue(hot["heat_at_anthesis"])
        self.assertIsNone(hot["maturity"])

    def test_columns(self):
        (c,) = D.parse_cscer_cul("KZ0001 North KAZAK1           DFAULT    10   120   670    16    42   2.0    90")
        self.assertEqual((c["name"], c["eco"], c["P1V"], c["P1D"], c["P5"], c["PHINT"]),
                         ("North KAZAK1", "DFAULT", 10.0, 120.0, 670.0, 90.0))
        (c,) = D.parse_cscer_cul("IB0488 NEWTON             1,6 USWH01 48.45 73.50 505.0 35.42 22.60  0.78 95.00  ")
        self.assertEqual((c["eco"], c["P1V"]), ("USWH01", 48.45))


class RiceTest(unittest.TestCase):
    CUL = {"P1": 200.0, "P2R": 0.0, "P5": 400.0, "P2O": 12.0, "PHINT": 83.0, "TCLDP": 15.0}
    days = MaizeTest.days

    def test_the_stages_by_hand(self):
        # 19 a day at 28 °C, nothing on the sowing day. P8 = 150 e^(−0.055 x 28) = 32.2 met
        # on day 2 (5.8 over); emergence at 10 x 3 + 20 = 50 on day 5 (12.8 over); juvenile
        # to 200 on day 15, at 202.8; 19/136 of the index a day reaches 1 on day 23, at
        # 354.8, so P3 = 5.5 x 83 + 0.135 x 354.8 = 504.4: heading on day 50 (8.6 over);
        # grain fill from 120 on day 56 (2.6 over); 90% of P5 = 360 on day 75; maturity on
        # day 77.
        r = D.develop_rice(self.CUL, self.days(28.0), 0, 35.0)
        self.assertEqual((r["flower"], r["maturity"]), (50, 77))

    def test_long_days_hold_back_a_sensitive_variety(self):
        neutral = D.develop_rice(self.CUL, self.days(28.0), 0, 35.0)
        sensitive = D.develop_rice({**self.CUL, "P2R": 300.0}, self.days(28.0), 0, 35.0)
        self.assertGreater(sensitive["flower"], neutral["flower"] + 10)

    def test_too_cold_to_germinate(self):
        self.assertIsNone(D.develop_rice(self.CUL, self.days(8.0), 0, 35.0)["maturity"])

    def test_development_slows_above_the_optimum(self):
        self.assertAlmostEqual(D.rice_dtt(28, 28, 20, 12, 12), 19.0)
        self.assertLess(D.rice_dtt(40, 40, 20, 12, 12), D.rice_dtt(33, 33, 20, 12, 12))

    def test_a_transplanted_crop_fills_its_tillers_longer(self):
        # Juvenile ends on day 15, before transplanting on day 25, so the shock changes
        # nothing; grain fill from day 56 (2.6 over) runs to P5 + 40 = 440 on day 80,
        # three days after the direct-seeded crop's 77.
        r = D.develop_rice(self.CUL, self.days(28.0), 0, 35.0, transplant_age=25)
        self.assertEqual((r["flower"], r["maturity"]), (50, 80))

    def test_the_shock_lengthens_a_juvenile_seedling(self):
        # P1 600: at transplanting on day 25 the seedling has 12.8 + 20 x 19 = 392.8 since
        # emergence, so P1 becomes 600 + 25 + 0.4 x 392.8 = 782.1 (under 1.75 P1): the
        # juvenile phase ends on day 46 instead of 36, and heading follows ten days later.
        cul = {**self.CUL, "P1": 600.0}
        direct = D.develop_rice(cul, self.days(28.0), 0, 35.0)
        moved = D.develop_rice(cul, self.days(28.0), 0, 35.0, transplant_age=25)
        self.assertGreaterEqual(moved["flower"] - direct["flower"], 10)

    def test_columns(self):
        (c,) = D.parse_rice_cul("IB0003 IR 36                . IB0001 556.8 53.88 373.4 12.87 68.00 0.023  1.00 83.00  31.3  15.0  15.0  0.00  0.00  25.0")
        self.assertEqual((c["name"], c["P1"], c["P2R"], c["P5"], c["P2O"], c["PHINT"], c["TCLDP"]),
                         ("IR 36", 556.8, 53.88, 373.4, 12.87, 83.0, 15.0))


class WindowTest(unittest.TestCase):
    def test_a_lone_week_is_not_a_window(self):
        swept = [(1, 0.0), (8, 0.9), (15, 0.0), (22, 0.9), (29, 0.9), (36, 0.0)]
        self.assertEqual(D.windows(swept), [("Jan 22", "Jan 29")])

    def test_representatives_come_from_what_matures(self):
        runners = [(n, n, "", 0, None) for n in "abcde"]
        results = [{"code": "a", "matures_before_frost": 1.0, "days_to_maturity": 150},
                   {"code": "b", "matures_before_frost": 0.0, "days_to_maturity": None},   # never flowers
                   {"code": "c", "matures_before_frost": 0.9, "days_to_maturity": 100},
                   {"code": "d", "matures_before_frost": 0.9, "days_to_maturity": 120},
                   {"code": "e", "matures_before_frost": 0.5, "days_to_maturity": 90}]
        picks = [r[1] for r in D.representatives(runners, lambda r: 0, results)]
        self.assertEqual(picks, ["c", "d", "a"])

    def test_runs_of_good_weeks(self):
        swept = [(1, 0.0), (8, 0.9), (15, 0.9), (22, 0.5), (29, 0.85)]
        self.assertEqual(D.windows(swept), [("Jan 08", "Jan 15")])
        self.assertEqual(D.windows(swept, min_sowings=1), [("Jan 08", "Jan 15"), ("Jan 29", "Jan 29")])

    def test_a_window_across_the_new_year_is_joined(self):
        swept = [(1, 0.9), (8, 0.0), (358, 0.9)]
        self.assertEqual(D.windows(swept), [("Dec 24", "Jan 01")])

    def test_freeze_thresholds_are_read_from_the_live_line(self):
        spe = D.parse_spe("*TOMATO SPECIES COEFFICIENTS: CRGRO048 MODEL\n"
                          "!  0.90  0.15  0.06 -9.00 -9.00        SENRTE,SENRT2,SENDAY,FREEZ1,FREEZ2\n"
                          "  1.00  0.02  0.02 -2.22 -5.00        SENRTE,SENRT2,SENDAY,FREEZ1,FREEZ2\n"
                          "!*PHENOLOGY PARAMETERS\n  7.0  22.0  28.0  48.0              1 VEG\n")
        self.assertEqual(spe["freeze"], (-2.22, -5.0))


if __name__ == "__main__":
    unittest.main()
