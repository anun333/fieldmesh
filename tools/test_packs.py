#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The language-pack tool a contributor runs."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import packs


class TestPacksTool(unittest.TestCase):

    def setUp(self):
        self.real = packs.i18n.PACK_DIR
        self.dir = tempfile.mkdtemp()
        for name in os.listdir(self.real):
            shutil.copy(os.path.join(self.real, name), self.dir)
        packs.i18n.PACK_DIR = self.dir
        packs.i18n._CACHE.clear()

    def tearDown(self):
        packs.i18n.PACK_DIR = self.real
        packs.i18n._CACHE.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_quietly(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = packs.main(list(argv))
        return code, out.getvalue()

    def test_the_shipped_packs_report_sound(self):
        code, out = self.run_quietly()
        self.assertEqual(code, 0, out)
        self.assertIn("español", out)

    def test_new_writes_a_complete_empty_scaffold(self):
        code, _ = self.run_quietly("new", "sw", "--name", "Swahili",
                                   "--native", "Kiswahili")
        self.assertEqual(code, 0)
        with open(os.path.join(self.dir, "sw.json"), encoding="utf-8") as handle:
            doc = json.load(handle)
        packs.i18n._CACHE.clear()
        self.assertEqual(set(doc["strings"]), set(packs.i18n.load("en").strings))

    def test_new_never_overwrites_a_translation(self):
        """Someone's month of work is one mistyped command away otherwise."""
        code, out = self.run_quietly("new", "es", "--name", "x", "--native", "x")
        self.assertEqual(code, 1)
        self.assertIn("not overwriting", out)

    def test_an_unsound_pack_fails_the_report(self):
        path = os.path.join(self.dir, "zz.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"_meta": {"language": "zz", "status": "draft", "note": "t"},
                       "strings": {"check.range.above": "{value} > {maxx}"}}, handle)
        packs.i18n._CACHE.clear()
        code, out = self.run_quietly()
        self.assertEqual(code, 1)
        self.assertIn("zz", out)


if __name__ == "__main__":
    unittest.main()
