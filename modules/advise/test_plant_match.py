# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plants against a site, on cases whose answer is known."""
import unittest

import plant_match as T

SITE = {"lat": 35.06, "lon": -86.59,
        "climate": {"frost_free_days_8_in_10": 207, "mean_annual_extreme_min_f": 11.0,
                    "annual_rain_in": 54.2,
                    "monthly": [{"mean_max_c": x} for x in
                                (8, 11, 16, 21, 25, 29, 32, 32, 29, 23, 16, 10)]},
        "soil": {"topsoil_ph": 6.2, "topsoil_texture": "loamy",
                 "drainage": "moderately well drained", "topsoil_ec_ds_per_m": 0.1}}


def plant(category="vegetable", cycle="annual", name="x"):
    return {"category": category, "cycle": cycle, "common_name": name, "scientific_name": name}


def chars(**kw):
    base = {"plants_symbol": "X", "match": "exact"}
    base.update(kw)
    return base


class JudgeTest(unittest.TestCase):
    def test_a_plant_that_fits_suits(self):
        j = T.judge(plant(), chars(**{"Frost Free Days, Minimum": "90", "pH, Minimum": "5.5",
                                      "pH, Maximum": "7.5", "Precipitation, Minimum": "20",
                                      "Precipitation, Maximum": "60"}), SITE)
        self.assertEqual(j["verdict"], "suits")

    def test_a_short_season_rules_out(self):
        j = T.judge(plant(), chars(**{"Frost Free Days, Minimum": "290"}), SITE)
        self.assertEqual(j["verdict"], "unsuited")
        self.assertIn("season", j["rules_out"][0])

    def test_a_season_a_little_short_is_a_caution(self):
        """White clover: PLANTS lists 250 frost-free days; Tennessee pastures have 207."""
        j = T.judge(plant(cycle="perennial"), chars(**{"Frost Free Days, Minimum": "250",
                                                      "Temperature, Minimum (°F)": "22"}), SITE)
        self.assertEqual(j["verdict"], "suits, with cautions")
        self.assertEqual(len(j["caution"]), 2)

    def test_an_implausible_season_on_an_annual_is_not_used(self):
        """Buckwheat, an annual, carries 365 frost-free days in PLANTS."""
        j = T.judge(plant(cycle="annual"), chars(**{"Frost Free Days, Minimum": "365"}), SITE)
        self.assertEqual(j["verdict"], "suits, with cautions")
        self.assertIn("implausible", j["caution"][0])

    def test_a_perennial_grown_as_an_annual_gets_a_caution_not_a_verdict(self):
        """Eggplant: 365 frost-free days from its perennial range."""
        j = T.judge(plant(cycle="perennial grown as annual"),
                    chars(**{"Frost Free Days, Minimum": "365"}), SITE)
        self.assertEqual(j["verdict"], "suits, with cautions")
        self.assertIn("time to harvest", j["caution"][0])

    def test_a_true_perennial_with_a_long_season_is_still_ruled_out(self):
        j = T.judge(plant(cycle="perennial"), chars(**{"Frost Free Days, Minimum": "365"}), SITE)
        self.assertEqual(j["verdict"], "unsuited")

    def test_winter_rules_out_only_perennials(self):
        cold = chars(**{"Temperature, Minimum (°F)": "28"})
        self.assertEqual(T.judge(plant(cycle="perennial"), cold, SITE)["verdict"], "unsuited")
        self.assertEqual(T.judge(plant(cycle="annual"), cold, SITE)["verdict"], "suits",
                         "an annual does not have to live through the winter")

    def test_a_winter_low_near_the_limit_is_a_caution(self):
        j = T.judge(plant(cycle="perennial"), chars(**{"Temperature, Minimum (°F)": "8"}), SITE)
        self.assertEqual(j["verdict"], "suits, with cautions")

    def test_dry_is_fixable_and_wet_is_a_caution(self):
        j = T.judge(plant(), chars(**{"Precipitation, Minimum": "60"}), SITE)
        self.assertEqual(j["verdict"], "suits, with water")
        j = T.judge(plant(), chars(**{"Precipitation, Maximum": "30"}), SITE)
        self.assertEqual(j["verdict"], "suits, with cautions")

    def test_ph_says_which_way_to_fix_it(self):
        j = T.judge(plant(), chars(**{"pH, Minimum": "4.5", "pH, Maximum": "5.5"}), SITE)
        self.assertIn("sulfur", j["fixable"][0])

    def test_a_plant_listed_invasive_in_the_sites_state_is_refused(self):
        """Paulownia: on the list as timber, and invasive in neighbouring states."""
        site = {**SITE, "soil": {**SITE["soil"], "state": "NC"}}
        j = T.judge(plant(category="timber", cycle="perennial"), chars(us_listed_states="AL;CT;NC;WI"), site)
        self.assertEqual(j["verdict"], "do not plant (invasive here)")
        site = {**SITE, "soil": {**SITE["soil"], "state": "TN"}}
        j = T.judge(plant(category="timber", cycle="perennial"), chars(us_listed_states="AL;CT;NC;WI"), site)
        self.assertEqual(j["verdict"], "suits, with cautions")
        self.assertIn("4 US state(s)", j["caution"][0])

    def test_a_federal_listing_is_refused_in_any_state(self):
        site = {**SITE, "soil": {**SITE["soil"], "state": "TN"}}
        j = T.judge(plant(), chars(us_listed_states="United States"), site)
        self.assertEqual(j["verdict"], "do not plant (invasive here)")

    def test_invasives_are_refused_first(self):
        j = T.judge(plant(category="invasive: do not plant (US)"), chars(), SITE)
        self.assertEqual(j["verdict"], "do not plant (invasive)")

    def test_no_characteristics_is_said_plainly(self):
        self.assertTrue(T.judge(plant(), None, SITE)["verdict"].startswith("no data"))
        j = T.judge(plant(), chars(match="exact; no characteristics"), SITE)
        self.assertTrue(j["verdict"].startswith("no data"))


SEASON_OK = {"dssat_crop": "Dry Bean", "cultivars": "30", "cultivars_maturing_8_in_10": "30",
             "best_matures_before_frost": "1.0", "best_days_to_maturity": "75",
             "longest_days_to_maturity": "107", "planting": "1 week after last frost"}
SEASON_FAIL = {"dssat_crop": "Pigeonpea", "cultivars": "3", "cultivars_maturing_8_in_10": "0",
               "best_matures_before_frost": "0.0", "best_days_to_maturity": "",
               "longest_days_to_maturity": "", "planting": "1 week after last frost"}


class CropModelTest(unittest.TestCase):
    def test_a_crop_plants_knows_nothing_about_gets_a_verdict(self):
        self.assertEqual(T.judge(plant(), None, SITE, SEASON_OK)["verdict"], "suits (crop model)")
        j = T.judge(plant(), None, SITE, SEASON_FAIL)
        self.assertEqual(j["verdict"], "unsuited")
        self.assertIn("crop model", j["rules_out"][0])

    def test_the_crop_model_outranks_plants_on_the_season(self):
        """PLANTS says 365 frost-free days; the model ran thirty Tennessee seasons."""
        j = T.judge(plant(cycle="perennial"), chars(**{"Frost Free Days, Minimum": "365"}), SITE, SEASON_OK)
        self.assertEqual(j["verdict"], "suits")

    def test_without_a_model_plants_still_decides(self):
        self.assertEqual(T.judge(plant(), None, SITE)["verdict"], "no data (not in USDA PLANTS)")


class PaddyTest(unittest.TestCase):
    def test_rice_s_season_fits_but_the_flood_is_a_caution(self):
        rice = {**plant(category="cereal", name="Rice"), "scientific_name": "Oryza sativa"}
        j = T.judge(rice, None, SITE, SEASON_OK)
        self.assertEqual(j["verdict"], "suits, with cautions")
        self.assertTrue(any("flooded" in c for c in j["caution"]))
        self.assertEqual(T.judge(plant(), None, SITE, SEASON_OK)["verdict"], "suits (crop model)")


class CoverTest(unittest.TestCase):
    def test_a_tunnel_lengthens_the_season(self):
        need = chars(**{"Frost Free Days, Minimum": "290"})
        self.assertEqual(T.judge(plant(), need, SITE)["verdict"], "unsuited")
        tunnel = T.under_cover(SITE, "high-tunnel")
        self.assertEqual(tunnel["climate"]["frost_free_days_8_in_10"], 235)
        self.assertEqual(T.judge(plant(), need, tunnel)["verdict"], "suits, with cautions")

    def test_rain_stops_mattering_under_cover(self):
        wet = chars(**{"Precipitation, Maximum": "30"})
        self.assertEqual(T.judge(plant(), wet, SITE)["verdict"], "suits, with cautions")
        self.assertEqual(T.judge(plant(), wet, T.under_cover(SITE, "high-tunnel"))["verdict"], "suits")

    def test_only_what_is_grown_under_cover_is_judged_there(self):
        tunnel = T.under_cover(SITE, "high-tunnel")
        self.assertEqual(T.judge(plant(category="timber", cycle="perennial"), chars(), tunnel)["verdict"],
                         "not grown under cover")
        self.assertEqual(T.judge(plant(category="vegetable"), chars(), tunnel)["verdict"], "suits")

    def test_the_winter_low_moves_only_by_a_measured_gain(self):
        self.assertEqual(T.under_cover(SITE, "high-tunnel")["climate"]["mean_annual_extreme_min_f"], 11.0)
        self.assertEqual(T.under_cover(SITE, "high-tunnel", 6.0)["climate"]["mean_annual_extreme_min_f"], 17.0)
        self.assertEqual(SITE["climate"]["frost_free_days_8_in_10"], 207, "the open site is untouched")


class CalendarTest(unittest.TestCase):
    def test_bloom_months_shift_in_the_south(self):
        self.assertEqual(T.bloom_months("Early Spring", False), [3])
        self.assertEqual(T.bloom_months("Early Spring", True), [9])

    def test_hunger_gaps_are_flight_months_with_nothing_in_flower(self):
        rows = [{"verdict": "suits", "bloom": "Spring", "common_name": "a"},
                {"verdict": "suits", "bloom": "Summer", "common_name": "b"},
                {"verdict": "unsuited", "bloom": "Fall", "common_name": "c"}]
        cal = T.calendar(rows, SITE)
        self.assertEqual(cal["hunger_gaps"], ["Feb", "Sep", "Oct", "Nov", "Dec"])
        self.assertNotIn("Jan", cal["bee_flight_months"], "too cold to fly")


if __name__ == "__main__":
    unittest.main()
