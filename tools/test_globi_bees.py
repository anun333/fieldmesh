# SPDX-License-Identifier: Apache-2.0
"""GloBI bee summaries, offline."""
import unittest

import globi_bees as T


class GlobiTest(unittest.TestCase):
    def test_query_names(self):
        self.assertEqual(T.query_name("Cucurbita pepo"), "Cucurbita pepo")
        self.assertEqual(T.query_name("Mentha × piperita"), "Mentha piperita")
        self.assertEqual(T.query_name("Beta vulgaris subsp. vulgaris (Cicla group)"), "Beta vulgaris")
        self.assertEqual(T.query_name("Rubus subg. Rubus"), "Rubus")
        self.assertEqual(T.query_name("× Triticosecale"), "Triticosecale")

    def test_only_bees_visiting_or_pollinating_are_kept(self):
        doc = {"columns": ["source_taxon_name", "source_taxon_path", "interaction_type",
                           "target_taxon_name", "study_title"],
               "data": [["Apis mellifera", "Insecta | Hymenoptera | Apidae | Apis", "visitsFlowersOf", "Cucurbita pepo", "Study A"],
                        ["Peponapis pruinosa", "Insecta | Hymenoptera | Apidae", "pollinates", "Cucurbita pepo", "Study B"],
                        ["Acalymma vittatum", "Insecta | Coleoptera | Chrysomelidae", "eats", "Cucurbita pepo", "Study C"],
                        ["Apis mellifera", "Insecta | Hymenoptera | Apidae | Apis", "hasHost", "Cucurbita pepo", "Study D"]]}
        summary, studies = T.summarise(doc)
        self.assertEqual(summary["bee_records"], 2)
        self.assertEqual(summary["managed_bees_recorded"], "Apis mellifera; Peponapis pruinosa")
        self.assertEqual(studies, {"Study A", "Study B"})


if __name__ == "__main__":
    unittest.main()
