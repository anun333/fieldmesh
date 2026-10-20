# SPDX-License-Identifier: Apache-2.0
"""The time-series model as an optional source (`tsfm.py`): its inputs read from the farm's
state, its receipt, and its licence asked for. A stand-in model, so neither Timestral nor
NumPy is needed: each probe forecast to move as its first neighbour does, in a fixed band."""
import datetime as dt
import unittest
from uuid import UUID

import fixtures as FX
import tsfm as TS
import vocab as V
from ids import uuid7
from model import Installation
from project import State

UTC = dt.timezone.utc
HOUR = dt.timedelta(hours=1)
T0 = dt.datetime(2026, 7, 1, tzinfo=UTC)


class FakeModel:
    """The probe moves as its first neighbour has since the context's end; a band of
    0.02 either side."""
    repo, weights, package = "stand-in", "0000000", "test"
    levels = (0.01, 0.1, 0.5, 0.9, 0.99)

    def __init__(self):
        self.calls = []

    def forecast(self, target, covariates, horizon):
        self.calls.append((target, covariates, horizon))
        last = next(v for v in reversed(target) if v is not None)
        n, out = len(target), []
        for h in range(horizon):
            m = last
            if covariates and covariates[0][n - 1] is not None and covariates[0][n + h] is not None:
                m = last + covariates[0][n + h] - covariates[0][n - 1]
            out.append([m - 0.02, m - 0.01, m, m + 0.01, m + 0.02])
        return out, self.levels


def probe(state, feature, depth, values, start=T0):
    """A probe installed in `feature` at `depth`, its hourly readings `values` from `start`."""
    raw = FX.raw_datastream(unit="1", observed_property=V.SOIL_WATER, feature=feature)
    ds = FX.derived_datastream(raw, unit="cm3/cm3")
    cal = FX.calibration(raw.sensor)
    for rec in (raw, ds, cal, Installation(uuid7(), raw.sensor, feature, start - 24 * HOUR, depth_m=depth)):
        state.add(rec)
    for h, v in enumerate(values):
        if v is not None:
            state.add(FX.observation(ds, result=v, measured_at=start + h * HOUR, calibration=cal.id, seq=h))
    return ds


class TestTheModelsInputs(unittest.TestCase):
    def test_the_licence_is_asked_for_before_anything_is_loaded(self):
        with self.assertRaises(TS.LicenceNotAccepted) as e:
            TS.load()
        self.assertIn("$20 million", str(e.exception))

    def test_a_series_hour_by_hour_its_gaps_none(self):
        s, bed = State(), uuid7()
        ds = probe(s, bed, 0.10, [0.30, None, 0.28, 0.27])
        self.assertEqual(TS.hourly(s, ds.id, T0, 5, T0 + 10 * HOUR), [0.30, None, 0.28, 0.27, None])
        self.assertEqual(TS.hourly(s, ds.id, T0, 4, T0 + 1 * HOUR), [0.30, None, None, None],
                         "not what came after the moment asked about")

    def test_a_beds_probes_shallowest_first_and_their_last_good_hour(self):
        s, bed = State(), uuid7()
        deep = probe(s, bed, 0.30, [0.3] * 5)
        top = probe(s, bed, 0.10, [0.3] * 3)
        probe(s, uuid7(), 0.10, [0.3] * 5)
        self.assertEqual([(p.id, d) for p, d in TS.soil_probes(s, bed, T0 + 5 * HOUR)],
                         [(top.id, 0.10), (deep.id, 0.30)])
        self.assertEqual(TS.last_good(s, top.id, T0 + 10 * HOUR, 24), T0 + 2 * HOUR)
        self.assertIsNone(TS.last_good(s, top.id, T0 + 10 * HOUR, 6))

    def test_a_run_and_its_receipt(self):
        """The forecast from the context's end, and a receipt: the model, the series and
        hours, a hash of the inputs, and how far each input moved it."""
        s, bed = State(), uuid7()
        top = probe(s, bed, 0.05, [0.30 - 0.001 * h for h in range(60)])
        mid = probe(s, bed, 0.10, [0.28 - 0.001 * h for h in range(40)])
        model = FakeModel()
        end = T0 + 40 * HOUR
        forecast, receipt = TS.run(model, s, mid.id, {"probe at 5 cm": top.id}, end, 20,
                                   T0 + 60 * HOUR, context_h=40)
        self.assertEqual(forecast.hours[0], end)
        self.assertAlmostEqual(forecast.median[10], 0.28 - 0.001 * 39 - 0.001 * 11, places=9)
        self.assertAlmostEqual(forecast.at(0.99)[0] - forecast.at(0.01)[0], 0.04, places=12)
        self.assertEqual(receipt["model"], "stand-in")
        self.assertEqual(receipt["covariates"], {"probe at 5 cm": str(top.id)})
        self.assertEqual(receipt["context"], [T0.isoformat(), end.isoformat()])
        self.assertGreater(receipt["moved_by"]["probe at 5 cm"], 0.0)
        again = TS.run(model, s, mid.id, {"probe at 5 cm": top.id}, end, 20, T0 + 60 * HOUR,
                       context_h=40)[1]
        self.assertEqual(again["inputs_sha256"], receipt["inputs_sha256"], "the same inputs, the same hash")
        UUID(receipt["target"])


if __name__ == "__main__":
    unittest.main()
