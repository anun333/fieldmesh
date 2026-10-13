#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""openSenseMap's soil probes into a log: six hours of a real SMT50, and a real LSE01 whose
conductivity declares a unit it cannot be in."""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import log as L  # noqa: E402
import opensensemap_collect as O  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402

with open(os.path.join(HERE, "fixtures", "opensensemap-soil.json"), encoding="utf-8") as h:
    FIXTURE = json.load(h)
SMT50, LSE01 = FIXTURE["boxes"]["smt50"], FIXTURE["boxes"]["lse01"]
RECEIVED = _dt.datetime(2026, 10, 13, 12, tzinfo=_dt.timezone.utc)


class TestOpenSenseMap(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="fm-osem-")
        self.path = os.path.join(self.dir, "farm.jsonl")

    def test_a_smt50s_soil_water_and_temperature_land_as_raw_series(self):
        out = O.collect(self.path, SMT50, FIXTURE["data"], depth_m=0.10, received_at=RECEIVED)
        self.assertEqual(out["refused"], [])
        self.assertEqual(sorted(out["series"]), [
            "Krupunder Grund 62 (openSenseMap): soil temperature",
            "Krupunder Grund 62 (openSenseMap): soil water"])
        kept = len(O.thinned(FIXTURE["data"]["5e5ad22de8fdda001b0bb5b0"], 600.0))
        self.assertTrue(33 <= kept <= 36, "about a reading each 10 minutes for six hours")
        self.assertEqual({n: v[0] for n, v in out["series"].items()},
                         {n: kept for n in out["series"]})
        state = P.state_from_log(L.Log(self.path))
        by_term = {ds.observed_property: ds for ds in state.datastreams.values()}
        self.assertEqual((by_term[V.SOIL_WATER].unit, by_term[V.SOIL_TEMPERATURE].unit),
                         ("%", "Cel"))
        water = by_term[V.SOIL_WATER]
        self.assertEqual(state.installation_of(water.sensor, RECEIVED).depth_m, 0.10)
        self.assertEqual(state.devices[water.sensor].manufacturer, "TRUEBNER")
        good = [o for o in state.live_observations_of(water.id)
                if state.quality_as_of(o.id, RECEIVED)[0].name == "GOOD"]
        self.assertEqual(len(good), kept, "a healthy probe passes the checks")
        self.assertTrue(all(o.provenance["licence"] == "ODC-PDDL-1.0"
                            for o in state.live_observations_of(water.id)))

    def test_again_it_adds_nothing(self):
        O.collect(self.path, SMT50, FIXTURE["data"], received_at=RECEIVED)
        again = O.collect(self.path, SMT50, FIXTURE["data"], received_at=RECEIVED)
        kept = len(O.thinned(FIXTURE["data"]["5e5ad22de8fdda001b0bb5b0"], 600.0))
        self.assertEqual({n: v for n, v in again["series"].items()},
                         {n: (0, kept) for n in again["series"]})

    def test_a_conductivity_in_ohms_is_left_out_not_guessed(self):
        found, refused = O.soil_series(LSE01)
        self.assertEqual(sorted(w for _, _, _, w in found), ["soil temperature", "soil water"])
        self.assertEqual([t for t, _ in refused], ["Leitfähigkeit"])
        self.assertIn("'Ohm'", refused[0][1])


if __name__ == "__main__":
    unittest.main()
