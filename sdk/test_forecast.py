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

    def test_as_of_a_moment_only_the_issues_out_by_then(self):
        """A decision taken at T0 + 1 h sees the early run alone, though the log it is
        replayed from holds the later one too."""
        s = self.state(self.early + self.late)
        then = s.forecast(self.ds.id, T0, T0 + 4 * HOUR, as_of=T0 + HOUR)
        self.assertEqual([o.result for o in then], [5.0, 4.0, 3.0, 2.0])
        now = s.forecast(self.ds.id, T0, T0 + 4 * HOUR, as_of=T0 + 2 * HOUR)
        self.assertEqual([o.result for o in now], [5.0, 4.0, -1.0, -2.0])
        self.assertEqual(s.forecast(self.ds.id, T0, T0 + 4 * HOUR, as_of=T0 - HOUR), [])

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



class EnsembleTest(unittest.TestCase):
    """An ensemble is members, each an ordinary forecast series (Q26): a window's event
    ("will the night reach −2.2 °C?") is counted on the members' runs."""

    def members(self, n=4):
        sensor, thing, feature = uuid7(), uuid7(), uuid7()
        return [Datastream(id=uuid7(), thing=thing, sensor=sensor, feature=feature,
                           observed_property=V.AIR_TEMPERATURE, unit="Cel",
                           kind=DatastreamKind.FORECAST, expected_interval=6 * 3600.0,
                           max_latency=3600.0, ensemble={"member": m, "members": n})
                for m in range(n)]

    def test_a_member_is_declared_and_checked(self):
        [ds, *_] = self.members()
        self.assertEqual(codec.load(codec.dump(ds)), ds)
        self.assertNotIn("ensemble", codec.dump(forecast_datastream()))
        for bad in ({"member": 4, "members": 4}, {"member": 0, "members": 1},
                    {"member": "0", "members": 4}, {"member": 0}, {"member": 0, "members": 4, "x": 1}):
            with self.assertRaises(ValueError, msg=bad):
                forecast_datastream(ensemble=bad)
        with self.assertRaises(ValueError):
            F.raw_datastream(ensemble={"member": 0, "members": 4})   # a measurement is one
        with self.assertRaises(ValueError):
            forecast_datastream(ensemble={"member": 0, "members": 4},
                                probability_of={"comparison": "le", "threshold": 0.0,
                                                "unit": "Cel", "period_s": 3600}, )

    def test_the_chance_of_a_window_is_the_share_of_members_whose_run_reaches_it(self):
        ms = self.members(4)
        state = P.State()
        other = forecast_datastream()               # not a member, same model or not
        for ds in ms + [other]:
            state.add(ds)
        lows = {0: [2.0, -2.5, 1.0], 1: [3.0, 1.0, 0.5], 2: [-2.2, 0.0, 1.0], 3: [4.0, 4.0, 4.0]}
        for m, ds in enumerate(ms):
            for o in run(ds, T0, lows[m]):
                state.add(o)
        self.assertEqual([d.id for d in FC.members(state, ms[2].id)], [d.id for d in ms])
        with self.assertRaises(FC.ForecastError):
            FC.members(state, other.id)
        got = FC.event_probability(state, [d.id for d in ms], T0, T0 + 3 * HOUR,
                                   comparison="le", threshold=-2.2)
        self.assertEqual((got["probability"], got["members"], got["missing"]), (0.5, 4, 0))
        # A later run that warms one member changes the live chance, not what was known.
        for o in run(ms[0], T0 + HOUR, [1.0, 1.0]):
            state.add(o)
        live = FC.event_probability(state, [d.id for d in ms], T0 + HOUR, T0 + 3 * HOUR,
                                    comparison="le", threshold=-2.2)
        then = FC.event_probability(state, [d.id for d in ms], T0 + HOUR, T0 + 3 * HOUR,
                                    comparison="le", threshold=-2.2, at=T0)
        # In the later window only member 0 reached it, and only in the run known then.
        self.assertEqual((live["probability"], then["probability"]), (0.0, 0.25))
        none = FC.event_probability(state, [d.id for d in ms], T0 + 9 * HOUR, T0 + 12 * HOUR,
                                    comparison="le", threshold=-2.2)
        self.assertEqual((none["probability"], none["missing"]), (None, 4))


if __name__ == "__main__":
    unittest.main()


POP = {"comparison": "ge", "threshold": 0.254, "unit": "mm", "period_s": 3600}


def pop_datastream(**kw):
    fields = dict(id=uuid7(), thing=uuid7(), sensor=uuid7(), feature=uuid7(),
                  observed_property=V.PRECIPITATION_DEPTH, unit="%",
                  kind=DatastreamKind.FORECAST, expected_interval=3600.0, max_latency=3600.0,
                  probability_of=POP)
    fields.update(kw)
    return Datastream(**fields)


class ProbabilityTest(unittest.TestCase):
    """A chance of rain is a forecast of a probability, of a declared event (Q26)."""

    def test_the_event_is_declared_and_checked(self):
        ds = pop_datastream()
        self.assertEqual(V.check(ds.observed_property, ds.unit, probability_of=ds.probability_of), [])
        with self.assertRaises(ValueError):
            pop_datastream(unit="mm")                          # a probability is not a depth
        with self.assertRaises(ValueError):
            pop_datastream(probability_of={"comparison": "about", "threshold": 1,
                                           "unit": "mm", "period_s": 3600})
        with self.assertRaises(ValueError):
            F.raw_datastream(probability_of=POP)               # a measurement measures
        self.assertTrue(V.check(ds.observed_property, "%",
                                probability_of=dict(POP, unit="Cel")))

    def test_round_trips_and_old_lines_are_unchanged(self):
        ds = pop_datastream()
        self.assertEqual(codec.load(codec.dump(ds)), ds)
        self.assertNotIn("probability_of", codec.dump(forecast_datastream()))

    def test_brier_scores_issues_against_the_gauge(self):
        fc = pop_datastream()
        gauge = F.raw_datastream(observed_property=V.PRECIPITATION_DEPTH, unit="mm",
                                 expected_interval=3600.0)
        issued = T0
        probs = [10, 90, 50, 0]
        rain = [0.0, 3.0, 0.2, 0.0]                             # wet only in the second hour
        log = Log()
        for r in [fc, gauge] + run(fc, issued, probs):
            log.append_record(r)
        for i, mm in enumerate(rain):
            log.append_record(F.observation(gauge, result=mm, measured_at=issued + i * HOUR + dt.timedelta(minutes=30), seq=i))
        state = P.state_from_log(log)
        pairs = FC.brier(state, fc.id, gauge.id)
        flat = [p for lead in sorted(pairs) for p in pairs[lead]]
        self.assertEqual(flat, [(0.1, False), (0.9, True), (0.5, False), (0.0, False)])
        self.assertAlmostEqual(FC.brier_score(flat), (0.01 + 0.01 + 0.25 + 0) / 4)
