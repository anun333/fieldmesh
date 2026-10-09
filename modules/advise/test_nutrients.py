# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manure against harvests, checked against the handbook's own worked example."""
import unittest

import nutrients as N


class RemovalTest(unittest.TestCase):
    def setUp(self):
        self.crops = N.crop_table()

    def test_the_handbooks_corn_grain_example(self):
        # AWMFH 6-18: 130 bu at 56 lb = 7,280 lb; 1.61% N = 117 lb, 0.28% P = 20 lb P,
        # 0.40% K = 29 lb K — P and K given here as the oxides.
        r = N.removal(self.crops["corn"], 130, "bu")
        self.assertAlmostEqual(r["n"], 117.2, places=1)
        self.assertAlmostEqual(r["p2o5"] / N.P_TO_P2O5, 20.4, places=1)
        self.assertAlmostEqual(r["k2o"] / N.K_TO_K2O, 29.1, places=1)

    def test_silage_is_weighed_wet_and_reckoned_dry(self):
        # 22 wet tons at the table's 7 dry in 20 wet = 15,400 lb dry; 1.10% N = 169 lb,
        # the handbook's own figure for its 22-ton example.
        r = N.removal(self.crops["corn silage"], 22, "tons")
        self.assertAlmostEqual(r["n"], 169.4, places=1)

    def test_a_crop_with_no_bushel_weight_says_so(self):
        with self.assertRaises(ValueError):
            N.removal(self.crops["alfalfa"], 4, "bu")


class BalanceTest(unittest.TestCase):
    def test_supply_from_animal_units(self):
        # 20,000 broilers at 4.5 lb = 90 animal units x 0.63 lb TKN x 365 days.
        s = N.manure_supply(N.manure_table()["broiler litter"], 20000, 4.5)
        self.assertAlmostEqual(s["n"], 90 * 0.63 * 365)

    def test_a_high_phosphorus_soil_holds_the_plan_to_phosphate(self):
        animals = [("broiler litter", 20000, 4.5)]
        crops = [("bermudagrass", 5, "tons", 60)]
        by_n = N.balance(animals, crops)
        by_p = N.balance(animals, crops, "high")
        self.assertEqual((by_n["limit"], by_p["limit"]), ("n", "p2o5"))
        self.assertGreater(by_p["acres_needed"], by_n["acres_needed"],
                           "litter carries more phosphate than grass removes")

    def test_the_organic_interval_follows_soil_contact(self):
        text = N.render(N.balance([], [("carrots", 13, "tons", 1), ("wheat", 40, "bu", 1)]),
                        organic=True)
        self.assertIn("carrots: 120 days", text)
        self.assertIn("wheat: 90 days", text)

    def test_spanish_groups_thousands_with_a_point(self):
        text = N.render(N.balance([("broiler litter", 20000, 4.5)], [("bermudagrass", 5, "tons", 60)]),
                        language="es")
        self.assertIn("20.696 lb de nitrógeno", text)


if __name__ == "__main__":
    unittest.main()
