# SPDX-License-Identifier: AGPL-3.0-or-later
"""The module's own housekeeping: its data manifest, its language packs, its stamp."""
import os
import re
import unittest

import module

HERE = os.path.dirname(os.path.abspath(__file__))
module.register_packs()
import i18n  # noqa: E402  (after register, so the merged packs load)


class ManifestTest(unittest.TestCase):
    def test_every_data_file_is_listed_and_unchanged(self):
        self.assertEqual(module.manifest_problems(), [])

    def test_every_row_says_where_it_came_from_and_under_what_licence(self):
        for row in module.manifest():
            with self.subTest(file=row["file"]):
                self.assertTrue(row["source"].strip())
                self.assertRegex(row["licence"], r"^(CC0-1\.0|CC-BY-4\.0|BSD-3-Clause|LicenseRef-PD-USGov)$")
                self.assertRegex(row["retrieved"], r"^\d{4}-\d{2}-\d{2}$")


class PacksTest(unittest.TestCase):
    def test_the_module_packs_are_sound_in_every_language(self):
        for tag in i18n.available():
            with self.subTest(tag=tag):
                self.assertEqual(i18n.check_pack(tag), [])

    def test_every_key_the_code_names_exists(self):
        source = i18n.load("en").strings
        named = set()
        for name in os.listdir(HERE):
            if name.endswith(".py") and not name.startswith("test_"):
                with open(os.path.join(HERE, name), encoding="utf-8") as h:
                    text = h.read()
                # Whole keys only: a prefix completed at run time ("advise.why.texture_" +
                # word) or tested with startswith is not a key.
                named |= {m.group(1) for m in re.finditer(r'(?<!startswith\()"(advise\.[a-z0-9_.]+[a-z0-9])"(?!\s*\+)', text)}
        self.assertTrue(named)
        self.assertEqual(sorted(k for k in named if k not in source), [])

    def test_a_module_cannot_shadow_layer_zero(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "en.json"), "w") as h:
                json.dump({"strings": {"check.range.above": "hijacked"}}, h)
            with self.assertRaises(ValueError):
                i18n.register(d, "check")
            self.assertEqual(i18n.english("check.range.above", value=1, max=0), "1 above max 0",
                             "refused, and layer zero's string unchanged")


class StampTest(unittest.TestCase):
    def test_a_report_says_what_made_it(self):
        import advise
        text = advise.stamp(advise.Report("es"))
        self.assertIn(module.VERSION, text)
        self.assertIn(module.data_version(), text)
        self.assertIn("Hecho con", text)


if __name__ == "__main__":
    unittest.main()
