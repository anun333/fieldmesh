# SPDX-License-Identifier: Apache-2.0
"""Forecasts as input data (Q26): two times, many runs, the latest issue lives."""
import datetime as dt
import json
import random
import unittest

import codec
import fixtures as F
import forecast as FC
import project as P
import sensorthings as ST
import vocab as V
from ids import uuid7
from log import Log
from model import ClockQuality, Datastream, DatastreamKind, Observation

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 4, 6, 0, 0, tzinfo=UTC)
HOUR = dt.timedelta(hours=1)


def forecast_datastream(**kw) -> Datastream:
    return Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(), feature=uuid7(),
                      observed_property=V.AIR_TEMPERATURE, unit="Cel",
                      kind=DatastreamKind.FORECAST, expected_interval=6 * 3600.0,
                      max_latency=3600.0, **kw)


def run(ds, issued, values, *, n=None):
    """Observations for one issue, hour by hour from `issued`."""
    return [Observation(id=uuid7(), datastream=ds.id, measured_at=issued + i * HOUR,
                        measured_at_uncertainty=1800.0, received_at=issued,
                        result=v, clock_quality=ClockQuality.NETWORK, issued_at=issued)
            for i, v in enumerate(values)]


class ModelTest(unittest.TestCase):
    def test_a_forecast_says_when_it_was_issued(self):
        ds = forecast_datastream()
        obs = run(ds, T0, [5.0])[0]
        obs.validate_against(ds)
        bare = Observation(id=uuid7(), datastream=ds.id, measured_at=T0, measured_at_uncertainty=1800.0,
                           received_at=T0, result=5.0, clock_quality=ClockQuality.NETWORK)
        with self.assertRaises(ValueError):
            bare.validate_against(ds)

    def test_a_measurement_has_no_issue_time(self):
        raw = F.raw_datastream()
        obs = Observation(id=uuid7(), datastream=raw.id, measured_at=T0, measured_at_uncertainty=1.0,
                          received_at=T0, result=0.2, clock_quality=ClockQuality.GPS, issued_at=T0)
        with self.assertRaises(ValueError):
            obs.validate_against(raw)

    def test_a_forecast_derives_from_nothing_on_the_farm(self):
        with self.assertRaises(ValueError):
            forecast_datastream(derived_from=uuid7())


class LiveTest(unittest.TestCase):
    def setUp(self):
        self.ds = forecast_datastream()
        self.early = run(self.ds, T0, [5.0, 4.0, 3.0, 2.0])
        self.late = run(self.ds, T0 + 2 * HOUR, [-1.0, -2.0])     # covers hours 2 and 3 again

    def state(self, rows):
        s = P.State()
        s.add(self.ds)
        for r in rows:
            s.add(r)
        return s

    def test_the_latest_issue_is_live_in_any_order(self):
        for rows in (self.early + self.late, self.late + self.early):
            s = self.state(rows)
            live = s.forecast(self.ds.id, T0, T0 + 4 * HOUR)
            self.assertEqual([o.result for o in live], [5.0, 4.0, -1.0, -2.0])
            self.assertEqual(len(s.live_observations(strict=True)), 4, "no clash raised")
            self.assertEqual(len(s.observations_of(self.ds.id)), 6, "every run is kept")

    def test_the_module_projection_agrees(self):
        live = P.live_observations(self.late + self.early, strict=True)
        self.assertEqual(sorted(o.result for o in live.values()), [-2.0, -1.0, 4.0, 5.0])

    def test_health_is_the_latest_issue_not_the_furthest_valid_time(self):
        s = self.state(self.early)
        self.assertEqual(s.health_of(self.ds.id, T0 + dt.timedelta(hours=5)), P.Health.OK)
        long_after = T0 + dt.timedelta(days=2)
        self.assertEqual(s.health_of(self.ds.id, long_after), P.Health.STALE,
                         "a source that went quiet is stale, though its last hour lies ahead")


class CodecTest(unittest.TestCase):
    def test_round_trip(self):
        ds = forecast_datastream()
        obs = run(ds, T0, [5.0])[0]
        back = codec.load(json.loads(json.dumps(codec.dump(obs))))
        self.assertEqual(back.issued_at, T0)

    def test_a_measurement_line_is_unchanged(self):
        line = codec.dump(F.observation(F.raw_datastream()))
        self.assertNotIn("issued_at", line, "logs written before Q26 read and write the same")


class SensorThingsTest(unittest.TestCase):
    def test_result_time_is_the_issue(self):
        ds = forecast_datastream()
        s = P.State()
        s.add(ds)
        obs = run(ds, T0, [5.0])[0]
        s.add(obs)
        doc = ST.Service(s).observation(obs)
        self.assertEqual(doc["resultTime"], "2026-04-06T00:00:00Z")
        self.assertIn("2026-04-06T00:00:00Z", doc["phenomenonTime"])


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.ds = forecast_datastream()
        self.state = P.State()
        self.state.add(self.ds)
        self.log = Log()
        self.log.append_record(self.ds)

    def values(self, issued, temps):
        return [(issued + i * HOUR, t) for i, t in enumerate(temps)]

    def test_idempotent(self):
        first = FC.ingest(self.log, self.state, self.ds.id, T0, self.values(T0, [5, 4, 3]),
                          uncertainty_s=1800, received_at=T0)
        again = FC.ingest(self.log, self.state, self.ds.id, T0, self.values(T0, [5, 4, 3]),
                          uncertainty_s=1800, received_at=T0)
        self.assertEqual((first.written, again.written, again.already_present), (3, 0, 3))

    def test_a_late_run_is_kept_but_not_live(self):
        newer = T0 + 6 * HOUR
        FC.ingest(self.log, self.state, self.ds.id, newer, self.values(newer, [1, 1]),
                  uncertainty_s=1800, received_at=newer)
        r = FC.ingest(self.log, self.state, self.ds.id, T0, self.values(T0, [5] * 8),
                      uncertainty_s=1800, received_at=newer)
        self.assertEqual(r.behind_newer, 2)
        live = self.state.forecast(self.ds.id, T0, T0 + 8 * HOUR)
        self.assertEqual([o.result for o in live], [5] * 6 + [1, 1])

    def test_only_onto_a_forecast_datastream(self):
        raw = F.raw_datastream(observed_property=V.AIR_TEMPERATURE, unit="Cel")
        self.state.add(raw)
        with self.assertRaises(FC.ForecastError):
            FC.ingest(self.log, self.state, raw.id, T0, self.values(T0, [5]), uncertainty_s=1800)

    def test_each_value_is_range_checked_and_nothing_else(self):
        ds = forecast_datastream(thresholds={"min": -60.0, "max": 60.0, "flat_seconds": 3600.0,
                                             "flat_n": 2, "max_rate_per_s": 0.0001})
        state, log = P.State(), Log()
        state.add(ds)
        log.append_record(ds)
        values = self.values(T0, [5.0] * 10 + [85.0] + [-3.0, 12.0])   # flat, absurd, a front
        r = FC.ingest(log, state, ds.id, T0, values, uncertainty_s=1800, received_at=T0)
        self.assertEqual((r.written, r.out_of_range), (13, 1))
        self.assertEqual(len(state.assertions), 13, "one assertion per value, as for a reading")
        flagged = [a for a in state.assertions if a.flags]
        self.assertEqual(len(flagged), 1, "a steady forecast is not stuck; a front is not a fault")
        self.assertEqual(flagged[0].evidence["checks_run"], ["range"])

    def test_verify_by_lead_time(self):
        measured = F.raw_datastream(observed_property=V.AIR_TEMPERATURE, unit="Cel",
                                    expected_interval=3600.0)
        self.state.add(measured)
        for i in range(12):
            self.state.add(F.observation(measured, result=10.0, measured_at=T0 + i * HOUR, seq=i))
        rng = random.Random(1)
        for issue in range(3):
            issued = T0 + issue * HOUR
            FC.ingest(self.log, self.state, self.ds.id, issued,
                      self.values(issued, [10.0 + rng.choice([-1, 1]) * 0.5] * 6),
                      uncertainty_s=1800, received_at=issued)
        errors = FC.verify(self.state, self.ds.id, measured.id)
        self.assertEqual(sorted(errors), [0, 1, 2, 3, 4, 5])
        self.assertTrue(all(abs(e) == 0.5 for es in errors.values() for e in es))


if __name__ == "__main__":
    unittest.main()
