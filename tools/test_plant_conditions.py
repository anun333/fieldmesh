# SPDX-License-Identifier: Apache-2.0
"""Name matching against USDA PLANTS, offline."""
import unittest

import plant_conditions as T


class NameTest(unittest.TestCase):

    def test_a_search_result_is_read_without_its_authors(self):
        self.assertEqual(T.name_of("<i>Zea mays</i> L."), "zea mays")
        self.assertEqual(T.name_of("<i>Zea mays</i> L. ssp. <i>everta</i> (Sturtev.) Zhuk."),
                         "zea mays subsp. everta")
        self.assertEqual(T.name_of("<i>Beta vulgaris</i> L. var. <i>cicla</i> L."),
                         "beta vulgaris var. cicla")
        self.assertEqual(T.name_of("<i>Rheum rhaponticum</i> L. f."), "rheum rhaponticum",
                         "an author's 'f.' is not a rank")
        self.assertEqual(T.name_of("<i>Mentha ×piperita</i> L. (pro sp.) [<i>aquatica × spicata</i>]"),
                         "mentha piperita", "a hybrid's parentage is not part of its name")

    def test_hybrid_signs_and_rank_words_compare_equal(self):
        self.assertEqual(T.normalise("Mentha × piperita"), T.normalise("Mentha ×piperita"))
        self.assertEqual(T.normalise("Zea mays ssp. everta"), "zea mays subsp. everta")

    def test_what_to_try(self):
        self.assertEqual(T.candidates("Zea mays"), ["zea mays"])
        self.assertEqual(T.candidates("Apium graveolens var. dulce"),
                         ["apium graveolens var. dulce", "apium graveolens"])
        self.assertEqual(T.candidates("Beta vulgaris subsp. vulgaris (Cicla group)"),
                         ["beta vulgaris subsp. vulgaris", "beta vulgaris"])
        self.assertEqual(T.candidates("Rubus subg. Rubus"), ["rubus"])


if __name__ == "__main__":
    unittest.main()
