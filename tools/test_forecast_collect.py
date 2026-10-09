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

    def test_a_chance_of_rain_is_collected_as_a_probability_of_its_event(self):
        """NWS's probability of precipitation: the chance of 0.254 mm in each hour (Q26)."""
        with open(os.path.join(HERE, "fixtures", "nws-gridpoint-HUN-62-57-pop.json"),
                  encoding="utf-8") as h:
            run = FS.nws_run(json.load(h))
        self.assertEqual(run.units["precipitation_probability"], "%")
        self.assertEqual(run.events["precipitation_probability"]["threshold"], 0.254)
        C.collect(self.path, run, "nws", {"precipitation_probability"})
        state = P.state_from_log(L.Log(self.path))
        self.assertEqual(state.validate(), [])
        [ds_id] = state.entities_named("NWS forecast: precipitation probability")
        ds = state.datastreams[ds_id]
        self.assertEqual((ds.unit, ds.probability_of["comparison"]), ("%", "ge"))
        self.assertTrue(all(0 <= o.result <= 100 for o in state.observations_of(ds_id)))

    def test_scoring_a_collection_against_a_station(self):
        import datetime as dt
        import forecast_score as SC
        import nbm_verify as N
        C.collect(self.path, self.run, "nws")
        size = os.path.getsize(self.path)
        state = P.state_from_log(L.Log(self.path))
        (fc_id,) = state.entities_named("NWS forecast: air temperature")
        fc = state.datastreams[fc_id]
        # A station reading 1 °F under every forecast hour.
        station = [(o.measured_at, o.result * 9 / 5 + 32 - 1.0) for o in state.observations_of(fc_id)]
        raw = SC.with_station(state, fc_id, station)
        s = N.score(state, raw, fc)
        self.assertAlmostEqual(s["by_lead_day"][0]["bias_c"], 5 / 9, places=6)
        self.assertEqual(os.path.getsize(self.path), size, "the station is added in memory only")


if __name__ == "__main__":
    unittest.main()
