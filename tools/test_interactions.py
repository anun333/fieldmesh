# SPDX-License-Identifier: Apache-2.0
"""Interaction records from PLANTS fields, GloBI and the curated list."""
import unittest

import interactions as T


class RecordsTest(unittest.TestCase):
    def test_plants_fields_become_records(self):
        plants = [{"scientific_name": "Medicago sativa", "common_name": "Alfalfa"}]
        chars = [{"scientific_name": "Medicago sativa", "Bloat": "High",
                  "Nitrogen Fixation": "High", "Toxicity": "None",
                  "Palatable Graze Animal": "High"}]
        rows = T.records(plants, chars, None)
        mechanisms = {r["mechanism"] for r in rows if r["source"].startswith("USDA")}
        self.assertEqual(mechanisms, {"bloat", "nitrogen fixation", "palatable forage"})
        self.assertTrue(all(r["subject"] == "Alfalfa (Medicago sativa)"
                            for r in rows if r["source"].startswith("USDA")))

    def test_globi_bees_become_records_and_none_without_records(self):
        plants = [{"scientific_name": "Cucurbita pepo", "common_name": "Squash"},
                  {"scientific_name": "Zea mays", "common_name": "Maize"}]
        globi = [{"scientific_name": "Cucurbita pepo", "bee_records": "40", "bee_taxa": "12",
                  "managed_bees_recorded": "Apis mellifera; Peponapis pruinosa", "top_bees": ""},
                 {"scientific_name": "Zea mays", "bee_records": "0", "bee_taxa": "0"}]
        rows = [r for r in T.records(plants, [], globi) if r["source"].startswith("GloBI")]
        self.assertEqual(len(rows), 1)
        self.assertIn("Peponapis", rows[0]["object"])

    def test_curated_rows_are_marked_to_cite(self):
        rows = [r for r in T.records([], [], None) if r["source"].startswith("curated")]
        self.assertEqual(len(rows), len(T.CURATED))
        self.assertTrue(all(r["source"] == "curated — to cite" for r in rows))


if __name__ == "__main__":
    unittest.main()
