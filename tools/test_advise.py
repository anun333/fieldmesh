# SPDX-License-Identifier: Apache-2.0
"""The advisor's report, rendered offline from a synthetic site, in two languages."""
import unittest

import advise as A

SITE = {"lat": 35.06445, "lon": -86.59137,
        "climate": {"koppen": "Cfa", "annual_mean_c": 15.4, "annual_rain_mm": 1376.0,
                    "hardiness_zone": "8a", "last_spring_frost_median": "Mar 31",
                    "first_fall_frost_median": "Nov 03", "frost_free_days_8_in_10": 207,
                    "growing_degree_days_c": 2774.0, "chill_hours_est": 1592.0,
                    "trend": {"mean_c_change": 0.5},
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


if __name__ == "__main__":
    unittest.main()
