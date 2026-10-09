# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plant names by language: which source wins, and what is refused."""
import unittest

import plant_names as N

PLANTS = [{"scientific_name": "Zea mays", "common_name": "Maize (corn)"},
          {"scientific_name": "Pyrus communis", "common_name": "Pear"},
          {"scientific_name": "Malus domestica", "common_name": "Apple"},
          {"scientific_name": "Ilex paraguariensis", "common_name": "Yerba mate"},
          {"scientific_name": "Trifolium repens", "common_name": "White clover"}]
AGRO = [{"name": "Zea mays", "c": "c1", "prod": "p_maize", "p_en": "maize", "p_es": "Maíz"},
        {"name": "Zea mays", "c": "c1", "prod": "p_sweet", "p_en": "sweet corn", "p_es": "Maíz dulce"},
        {"name": "Zea mays", "c": "c1", "prod": "p_straw", "p_en": "maize straw", "p_es": "Barba del maíz"},
        {"name": "Pyrus communis", "c": "c2", "prod": "p_pears", "p_en": "pears", "p_es": "Pera"}]
WIKI = [{"name": "Malus domestica", "item": "Q158657", "kind": "label", "lang": "es", "value": "Malus domestica"},
        {"name": "Malus domestica", "item": "Q158657", "kind": "source_of", "lang": "es", "value": "manzana"},
        {"name": "Ilex paraguariensis", "item": "Q1", "kind": "label", "lang": "es", "value": "Ilex paraguayensis"},
        {"name": "Trifolium repens", "item": "Q2", "kind": "common", "lang": "es", "value": "Trébol blanco",
         "rank": "http://wikiba.se/ontology#PreferredRank"},
        {"name": "Trifolium repens", "item": "Q2", "kind": "common", "lang": "es", "value": "chupamieles",
         "rank": "http://wikiba.se/ontology#NormalRank"}]


class ChooseTest(unittest.TestCase):
    def setUp(self):
        self.es = N.choose(PLANTS, AGRO, WIKI, "es")

    def test_the_product_named_like_the_plant_wins_among_several(self):
        self.assertEqual(self.es["Zea mays"][:2], ("Maíz", "AGROVOC (CC BY 4.0)"))

    def test_a_single_product_is_taken_even_by_another_number(self):
        self.assertEqual(self.es["Pyrus communis"][0], "Pera")

    def test_wikidata_fills_in_where_agrovoc_has_nothing(self):
        self.assertEqual(self.es["Malus domestica"][:2], ("Manzana", "Wikidata (CC0)"))
        self.assertEqual(self.es["Trifolium repens"][0], "Trébol blanco", "the preferred one")

    def test_a_synonym_is_not_a_common_name(self):
        self.assertNotIn("Ilex paraguariensis", self.es)


if __name__ == "__main__":
    unittest.main()
