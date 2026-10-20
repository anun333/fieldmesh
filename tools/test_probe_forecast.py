# SPDX-License-Identifier: Apache-2.0
"""Forecasting each silent soil probe into the farm's log (`probe_forecast.py`), with a
stand-in model (`sdk/test_tsfm.py`): neither Timestral nor NumPy needed."""
import contextlib
import datetime as dt
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import log as L  # noqa: E402
import probe_forecast as PF  # noqa: E402
import test_tsfm as T  # noqa: E402
from ids import uuid7  # noqa: E402
from model import DatastreamKind  # noqa: E402
from project import State  # noqa: E402

HOUR = dt.timedelta(hours=1)


class TestASilentProbeForecast(unittest.TestCase):
    def setUp(self):
        self.state, self.bed, self.log = State(), uuid7(), L.Log()
        self.top = T.probe(self.state, self.bed, 0.05, [0.30 - 0.001 * h for h in range(61)])
        self.mid = T.probe(self.state, self.bed, 0.10, [0.28 - 0.001 * h for h in range(41)])
        self.deep = T.probe(self.state, self.bed, 0.20, [0.32 - 0.0005 * h for h in range(61)])
        self.at = T.T0 + 60 * HOUR

    def test_the_silent_probe_is_forecast_on_a_datastream_at_its_depth(self):
        done = PF.forecast_silent(self.log, self.state, T.FakeModel(), self.at, ahead_h=24)
        self.assertEqual([p for p, _, _ in done], [self.mid.id])
        [name] = [e for e in self.state.entities_named(PF.stream_name(self.mid))]
        ds = self.state.datastreams[name]
        self.assertIs(ds.kind, DatastreamKind.FORECAST)
        inst = self.state.installation_of(ds.sensor, self.at)
        self.assertEqual((inst.feature, inst.depth_m), (self.bed, 0.10))
        live = self.state.forecast(ds.id, self.at, self.at + HOUR, as_of=self.at)
        self.assertAlmostEqual(live[0].result, 0.28 - 0.001 * 40 - 0.001 * 20, places=9)
        self.assertEqual(live[0].provenance["source"], "tools/probe_forecast.py")
        self.assertIn("probe at 5 cm", live[0].provenance["moved_by"])

    def test_a_second_run_finds_its_datastream_again(self):
        PF.forecast_silent(self.log, self.state, T.FakeModel(), self.at)
        PF.forecast_silent(self.log, self.state, T.FakeModel(), self.at + HOUR)
        self.assertEqual(len(self.state.entities_named(PF.stream_name(self.mid))), 1)

    def test_nothing_without_a_neighbour_reading_or_a_silence_too_long(self):
        self.assertEqual(PF.forecast_silent(self.log, self.state, T.FakeModel(), self.at + 200 * HOUR), [])
        self.assertEqual(PF.forecast_silent(self.log, self.state, T.FakeModel(), T.T0 + 41 * HOUR), [],
                         "not silent long enough")

    def test_without_the_licence_accepted_it_runs_nothing(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(PF.main(["/nonexistent.jsonl"]), 2)
        self.assertIn("$20 million", err.getvalue())


if __name__ == "__main__":
    unittest.main()
