# SPDX-License-Identifier: Apache-2.0
"""A real station into a log: twelve hours of McAllister Farm's SCAN station, as NRCS
published them (public domain), read the way the live collector reads them."""
import datetime as _dt
import json
import os
import sys
import tempfile
import unittest

import scan_collect as S

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import log as L  # noqa: E402
import project as P  # noqa: E402
from model import evidence_problems  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "awdb-2075-TN-SCAN.json")
UTC = _dt.timezone.utc


class CollectTest(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE, encoding="utf-8") as h:
            doc = json.load(h)
        self.station, self.data = doc["station"], doc["data"]
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "farm.jsonl")

    def tearDown(self):
        self.dir.cleanup()

    def test_every_sensor_becomes_a_series_with_its_depth(self):
        report = S.collect(self.path, self.station, self.data, None)
        self.assertEqual(len(report), 13)
        state = P.state_from_log(L.Log(self.path))
        self.assertEqual(state.validate(), [])
        [ds] = state.entities_named("McAllister Farm SCAN: soil water at 5 cm")
        install = state.installation_of(state.datastreams[ds].sensor,
                                        _dt.datetime(2026, 10, 8, tzinfo=UTC))
        self.assertAlmostEqual(install.depth_m, 0.0508)

    def test_hours_are_the_stations_standard_time(self):
        S.collect(self.path, self.station, self.data, None)
        state = P.state_from_log(L.Log(self.path))
        [ds] = state.entities_named("McAllister Farm SCAN: air temperature")
        first = min(o.measured_at for o in state.observations_of(ds))
        self.assertEqual(first, _dt.datetime(2026, 10, 8, 6, 0, tzinfo=UTC), "00:00 at UTC-6")

    def test_twice_is_once_and_every_reading_is_judged(self):
        first = S.collect(self.path, self.station, self.data, None)
        again = S.collect(self.path, self.station, self.data, None)
        self.assertTrue(all(n > 0 for n, _ in first.values()))
        self.assertTrue(all(n == 0 and a > 0 for n, a in again.values()))
        state = P.state_from_log(L.Log(self.path))
        self.assertEqual(len(state.assertions), len(state.observations))
        self.assertTrue(all(not evidence_problems(a) for a in state.assertions))

    def test_an_unknown_unit_is_refused(self):
        bad = json.loads(json.dumps(self.data))
        bad[0]["data"][0]["stationElement"]["storedUnitCode"] = "degC"
        with self.assertRaises(ValueError):
            S.series_of(bad)


if __name__ == "__main__":
    unittest.main()
