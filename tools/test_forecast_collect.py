# SPDX-License-Identifier: Apache-2.0
"""Collecting runs into a log file: declared once, found again by name, idempotent."""
import json
import os
import sys
import tempfile
import unittest

import forecast_collect as C
import forecast_sources as FS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import log as L  # noqa: E402
import project as P  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "nws-gridpoint-HUN-62-57.json")


class CollectTest(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE, encoding="utf-8") as h:
            self.run = FS.nws_run(json.load(h))
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "farm.jsonl")

    def tearDown(self):
        self.dir.cleanup()

    def test_twice_is_once(self):
        first = C.collect(self.path, self.run, "nws")
        again = C.collect(self.path, self.run, "nws")
        self.assertTrue(all(w > 0 and a == 0 for w, a in first.values()))
        self.assertTrue(all(w == 0 and a > 0 for w, a in again.values()))
        state = P.state_from_log(L.Log(self.path))
        self.assertEqual(len(state.datastreams), 4, "found again by name, not declared twice")
        self.assertEqual(state.validate(), [])
        self.assertEqual(len(state.entities_named("NWS forecast: air temperature")), 1)


if __name__ == "__main__":
    unittest.main()
