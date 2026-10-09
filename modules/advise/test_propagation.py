# SPDX-License-Identifier: AGPL-3.0-or-later
"""The propagation calendar, from a site's frost dates and the methods PLANTS lists."""
import unittest

import propagation as G

SITE = {"climate": {"last_spring_frost_median": "Mar 31", "first_fall_frost_median": "Nov 03",
                    "hardiness_zone": "7a"}}


class WindowsTest(unittest.TestCase):
    def test_windows_hang_on_the_frost_dates(self):
        w = G.windows(SITE)
        self.assertEqual(w["seed_cold"][0], ("Nov 03", "Dec 01"), "after the first fall frost")
        self.assertEqual(w["bare_root"][0], ("Feb 17", "Apr 14"), "dormant, around the last frost")
        self.assertEqual(w["cuttings"], [("Nov 03", "Feb 17")], "across the new year")
        self.assertEqual(w["sprigs"], [("Apr 14", "Aug 25")], "warm soil, ten weeks before frost")

    def test_fall_bare_root_only_where_winters_are_mild(self):
        cold = {"climate": dict(SITE["climate"], hardiness_zone="5b")}
        self.assertEqual(len(G.windows(SITE)["bare_root"]), 2)
        self.assertEqual(len(G.windows(cold)["bare_root"]), 1)

    def test_methods_follow_plants_fields(self):
        chars = {"Propagated by Seed": "Yes", "Cold Stratification Required": "Yes",
                 "Propagated by Bare Root": "Yes", "Propagated by Sod": "Yes", "Propagated by Sprigs": "Yes"}
        self.assertEqual(G.methods_of(chars), ["seed_cold", "bare_root", "sprigs"])
        self.assertEqual(G.methods_of(None), [])

    def test_the_calendar_lists_each_plant_and_window(self):
        plants = [{"scientific_name": "Quercus alba", "common_name": "White oak"}]
        chars = [{"scientific_name": "Quercus alba", "Propagated by Seed": "Yes",
                  "Cold Stratification Required": "Yes"}]
        rows = G.calendar(plants, chars, SITE)
        self.assertEqual([(r["method"], r["from"]) for r in rows],
                         [("seed_cold", "Nov 03"), ("seed_cold", "Mar 31")])


class ReportTest(unittest.TestCase):
    def test_the_section_keeps_fall_sowing_first(self):
        import advise as A
        import test_advise as T
        prop = G.calendar([{"scientific_name": "Quercus alba", "common_name": "White oak"}],
                          [{"scientific_name": "Quercus alba", "Propagated by Seed": "Yes",
                            "Cold Stratification Required": "Yes"}], SITE)
        text = A.render(T.SITE, T.ROWS, T.CAL, "en", "2026-10-09", propagation=prop)
        self.assertIn("sow outdoors November 3 to December 1; March 31 to April 21", text)


if __name__ == "__main__":
    unittest.main()
