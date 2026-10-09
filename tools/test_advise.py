# SPDX-License-Identifier: Apache-2.0
"""The advisor's report, rendered offline from a synthetic site, in two languages."""
import unittest

import advise as A

SITE = {"lat": 35.06445, "lon": -86.59137,
        "climate": {"koppen": "Cfa", "annual_mean_c": 15.4, "annual_rain_mm": 1376.0,
                    "hardiness_zone": "8a", "last_spring_frost_median": "Mar 31",
                    "first_fall_frost_median": "Nov 03", "frost_free_days_8_in_10": 207,
                    "growing_degree_days_c": 2774.0, "chill_hours_est": 1592.0, "chill_hours_8_in_10": 1400.0,
                    "trend": {"mean_c_change": 0.5}, "days_over_35c": 12.8,
                    "heat_stress_days_dairy_est": {"low": 96.0, "high": 172.0}},
        "soil": {"map_unit": "Dickson silt loam", "drainage": "Moderately well drained",
                 "slope_pct": 4.0, "topsoil_ph": 6.2, "topsoil_organic_matter_pct": 2.8},
        "erosion": {"times_tolerable_if_bare": 26.0}}
SEASON = {"cultivars_maturing_8_in_10": "4", "cultivars": "4", "best_days_to_maturity": "120",
          "longest_days_to_maturity": "131", "sowing_windows_8_in_10": "Apr 09–Jul 02"}
ROWS = [
    {"common_name": "Tomato", "scientific_name": "Solanum lycopersicum", "verdict": "suits (crop model)",
     "_season": SEASON, "_keys": []},
    {"common_name": "Barley", "scientific_name": "Hordeum vulgare", "verdict": "suits, with pH",
     "_keys": [("fixable", "advise.why.ph_lime", {"ph": 6.2, "need": 6.5})]},
    {"common_name": "Kudzu", "scientific_name": "Pueraria montana", "verdict": "do not plant (invasive)", "_keys": []},
]
CAL = {"bee_flight_months": ["Mar", "Apr"], "hunger_gaps": ["Sep"]}


class ReportTest(unittest.TestCase):
    def test_english(self):
        text = A.render(SITE, ROWS, CAL, "en", "2026-10-08")
        self.assertIn("Last spring frost around March 31", text)
        self.assertIn("Sow April 9 to July 2.", text)
        self.assertIn("needs 6.5 or more — lime", text)
        self.assertIn("about 26 times", text)
        self.assertIn("Kudzu", text)

    def test_spanish(self):
        text = A.render(SITE, ROWS, CAL, "es", "2026-10-08")
        self.assertIn("hacia el 31 de marzo", text)
        self.assertIn("Sembrar del 9 de abril al 2 de julio.", text)
        self.assertIn("encalar", text)
        self.assertIn("6,2", text, "the pack's decimal comma")
        self.assertNotIn("Last spring frost", text)

    def test_a_window_all_year_is_said_so(self):
        self.assertEqual(A.Report("en").windows("Jan 01–Dec 31"), "any time of year")

    def test_a_language_without_a_pack_falls_back_to_english(self):
        self.assertIn("March 31", A.render(SITE, ROWS, CAL, "sw", "2026-10-08"))


class FutureTest(unittest.TestCase):
    def setUp(self):
        import copy
        self.site2 = copy.deepcopy(SITE)
        c = self.site2["climate"]
        c.update(frost_free_days_8_in_10=213, chill_hours_est=1445.0, chill_hours_8_in_10=1000.0,
                 days_over_35c=21.0)
        self.rows2 = copy.deepcopy(ROWS)
        self.rows2[0]["_season"] = dict(SEASON, sowing_windows_8_in_10="Mar 26–Jul 02")
        self.rows2[1]["verdict"] = "not suited (pH)"

    def test_the_numbers_and_the_changes(self):
        text = A.render_future(SITE, ROWS, self.site2, self.rows2, "en", "2050s", 1.0, 0.0, "a test")
        self.assertIn("# The same farm, 2050s", text)
        self.assertIn("Frost-free days (8 years in 10): 207 → 213", text)
        self.assertIn("Chill hours: 1592 → 1445", text)
        self.assertIn("Days over 35 °C: 13 → 21", text, "both rounded to whole days")
        self.assertIn("No longer suits (1)", text)
        self.assertIn("Barley", text.split("No longer suits")[1])
        self.assertIn("Newly suits (0)", text)
        self.assertIn("sow April 9 to July 2 → March 26 to July 2", text)

    def test_spanish(self):
        text = A.render_future(SITE, ROWS, self.site2, self.rows2, "es", "2050", 1.0, 0.0, "prueba")
        self.assertIn("La misma finca, 2050", text)
        self.assertIn("+1,0 °C", text)
        self.assertIn("Deja de adaptarse (1)", text)


CHILL = [{"crop": "peach", "cultivar": "Lowchill", "chill_hours": "<300"},
         {"crop": "peach", "cultivar": "Mid", "chill_hours": "828 ± 139"},
         {"crop": "peach", "cultivar": "Mid", "chill_hours": "1200"},          # a second study, higher
         {"crop": "peach", "cultivar": "Open", "chill_hours": "> 1100"},
         {"crop": "cherry (sweet or sour)", "cultivar": "Bing", "chill_hours": "1000–1100"},
         {"crop": "almond", "cultivar": "Lluch", "chill_hours": "-"}]


class ChillTest(unittest.TestCase):
    def test_the_top_of_a_requirement(self):
        self.assertEqual(A.need_upper("1015–1105"), 1105)
        self.assertEqual(A.need_upper("354 - 507"), 507)
        self.assertEqual(A.need_upper("828 ± 139"), 967)
        self.assertEqual(A.need_upper("<300"), 300)
        self.assertIsNone(A.need_upper("> 1100"), "open-ended: unknown, not counted")
        self.assertIsNone(A.need_upper("-"))
        self.assertEqual(A.need_upper("142.3"), 142.3)

    def test_fit_holds_each_cultivar_to_its_highest(self):
        self.assertEqual(A.chill_fit(CHILL, 1150), [("peach", 2, 1), ("cherry", 1, 1)])
        self.assertEqual(A.chill_fit(CHILL, 1250), [("peach", 2, 2), ("cherry", 1, 1)])

    def test_the_report_section_in_two_languages(self):
        en = A.render(SITE, ROWS, CAL, "en", "2026-10-08", CHILL)
        self.assertIn("## Stone fruit by winter chill", en)
        self.assertIn("at least 1400 chill hours", en)
        self.assertIn("at least 1500 chill hours", A.render(SITE, ROWS, CAL, "en", "2026-10-08", CHILL, None, 1500.0))
        self.assertIn("- Peach: 2 of 2 cultivars", en)
        es = A.render(SITE, ROWS, CAL, "es", "2026-10-08", CHILL)
        self.assertIn("- Melocotonero: 2 de 2 variedades", es)

    def test_bloom_and_frost_lines(self):
        bloom = {"peach": {"estimates": 3, "bloom_early": 140, "bloom_median": 145, "bloom_late": 150,
                           "frost_in_10": 2, "unmet": 0},
                 "almond": {"estimates": 2, "bloom_early": 100, "bloom_median": 110, "bloom_late": 120,
                            "frost_in_10": 8, "unmet": 1}}
        en = A.render(SITE, ROWS, CAL, "en", "2026-10-08", CHILL, bloom)
        self.assertIn("- Peach: blooms March 21 to March 31 (median March 26); frost after bloom in 2 years of 10.", en)
        self.assertIn("For 1 of its 2 estimates, chill falls short", en)
        es = A.render(SITE, ROWS, CAL, "es", "2026-10-08", CHILL, bloom)
        self.assertIn("- Melocotonero: florece del 21 de marzo al 31 de marzo (mediana 26 de marzo)", es)

    def test_the_future_counts_the_loss(self):
        import copy
        site2 = copy.deepcopy(SITE)
        site2["climate"]["chill_hours_8_in_10"] = 1000.0
        text = A.render_future(SITE, ROWS, site2, ROWS, "en", "2050s", 1.0, 0.0, "x", CHILL)
        self.assertIn("- Cherry: cultivars getting their chill 1 → 0 of 1", text)
        self.assertIn("- Peach: cultivars getting their chill 2 → 1 of 2", text)


if __name__ == "__main__":
    unittest.main()
