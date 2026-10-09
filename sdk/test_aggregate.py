#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Aggregates (Q20): a node that samples often and reports seldom sends a window's
summary, and the gateway still sees a flatline at the sampling resolution."""
from __future__ import annotations

import datetime as _dt
import unittest

import checks as C
import codec
import fixtures as fx
import gateway as G
import log as L
import project as P
import sensorthings as ST
import wire
from ids import uuid7
from model import (ClockQuality, Datastream, DatastreamKind, Observation, QualityFlag,
                   UTC, aggregate_problems)
from registry import NodeBinding, Registry

NODE = 0x51A0
NOW = _dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
HOUR = 3600.0


def aggregate_datastream(**kw) -> Datastream:
    raw = fx.raw_datastream(unit="1", expected_interval=HOUR)
    fields = {f: getattr(raw, f) for f in ("id", "thing", "sensor", "observed_property",
                                            "feature", "unit", "expected_interval",
                                            "max_latency")}
    fields.update(kind=DatastreamKind.AGGREGATE, window_s=HOUR)
    fields.update(kw)
    return Datastream(**fields)


class TestTheRecord(unittest.TestCase):
    def test_an_aggregate_declares_its_window(self):
        with self.assertRaises(ValueError):
            aggregate_datastream(window_s=None)
        with self.assertRaises(ValueError):
            fx.raw_datastream(window_s=HOUR)

    def test_its_result_is_the_four_numbers(self):
        self.assertEqual(aggregate_problems({"n": 12, "min": 280, "max": 285,
                                             "unchanged_s": 300}), [])
        self.assertTrue(aggregate_problems(281))
        self.assertTrue(aggregate_problems({"n": 0, "min": 1, "max": 2, "unchanged_s": 0}))
        self.assertTrue(aggregate_problems({"n": 3, "min": 5, "max": 2, "unchanged_s": 0}))
        ds = aggregate_datastream()
        bad = fx.observation(ds, result=281)
        with self.assertRaises(ValueError):
            bad.validate_against(ds)
        with self.assertRaises(ValueError):
            fx.observation(fx.raw_datastream(), result={"n": 1}).validate_against(
                fx.raw_datastream())

    def test_old_logs_stay_byte_identical(self):
        raw = fx.raw_datastream()
        self.assertNotIn("window_s", codec.dump(raw))
        ds = aggregate_datastream()
        self.assertEqual(codec.load(codec.dump(ds)), ds)

    def test_calibration_moves_the_extremes_only(self):
        cal = fx.calibration(uuid7(), a=-0.001, b=1.0)
        out = P.apply_calibration({"n": 12, "min": 280, "max": 300, "unchanged_s": 0}, cal)
        self.assertAlmostEqual(out["min"], 0.7)
        self.assertAlmostEqual(out["max"], 0.72)
        self.assertEqual((out["n"], out["unchanged_s"]), (12, 0))


class TestTheWire(unittest.TestCase):
    def test_an_aggregate_round_trips(self):
        m = wire.Message(boot=1, seq=2, base_age=30, node=NODE,
                         readings=[wire.Reading(3, 0, (12, 280, 285, 900))])
        self.assertEqual(wire.decode(wire.encode(m)).readings[0].value, (12, 280, 285, 900))

    def test_a_malformed_one_is_refused(self):
        with self.assertRaises(wire.WireError):
            wire.Reading(3, 0, (12, 290, 285, 0))
        with self.assertRaises(wire.WireError):
            wire.Reading(3, 0, (12, 280, 285))

    def test_one_aggregate_costs_a_fraction_of_twelve_samples(self):
        samples = [wire.Reading(3, 300 * i, 280 + i % 2) for i in range(12)]
        summary = [wire.Reading(3, 0, (12, 280, 281, 300))]
        full = len(wire.encode(wire.Message(boot=1, seq=1, base_age=0, readings=samples)))
        small = len(wire.encode(wire.Message(boot=1, seq=1, base_age=0, readings=summary)))
        self.assertLess(small * 3, full)

    def test_the_window_carries_an_unchanged_run_across_reports(self):
        w = wire.Window()
        for i, v in enumerate([280, 281, 281, 281]):
            w.add(v, 300.0 * i)
        self.assertEqual(w.close(), (4, 280, 281, 600))
        for i in range(4, 8):
            w.add(281, 300.0 * i)
        self.assertEqual(w.close(), (4, 281, 281, 1800), "the run started last window")


def _farm(flat_seconds=1800.0):
    lg = L.Log()
    agg = aggregate_datastream()
    derived = fx.derived_datastream(agg, unit="cm3/cm3", window_s=HOUR,
                                    thresholds={"flat_seconds": flat_seconds, "max": 0.55})
    cal = fx.calibration(agg.sensor, a=0.001, valid_from=_dt.datetime(2026, 1, 1, tzinfo=UTC))
    for r in (agg, derived, cal):
        lg.append_record(r)
    state = P.state_from_log(lg)
    reg = Registry()
    reg.register_node(NodeBinding(node=NODE, site=uuid7(), clock_quality=ClockQuality.RTC_UNSYNCED,
                                  uncertainty_s=12.0, firmware="0.4", driver="sdi12",
                                  driver_version="1.2"))
    reg.bind_point(NODE, 3, agg.id)
    return G.Gateway(reg, lg, state), lg, state, derived


class TestHourlyReportsFiveMinuteDetection(unittest.TestCase):
    """The claim Q20 was decided on: report hourly, catch a stuck probe at the sampling
    resolution, from the node's count rather than from samples."""

    def test_a_freeze_is_caught_within_one_report(self):
        gw, lg, state, derived = _farm()
        w = wire.Window()
        values = [280 + (i % 3) for i in range(12)]              # a live hour
        values += [282] * 12                                     # frozen from 01:00
        flags, spans = [], []
        for hour in range(2):
            for i in range(12):
                w.add(values[hour * 12 + i], 3600.0 * hour + 300.0 * i)
            report = wire.Reading(3, 0, w.close())
            received = NOW + _dt.timedelta(hours=hour)
            r = gw.receive(wire.encode(wire.Message(boot=1, seq=hour + 1, base_age=0,
                                                    node=NODE, readings=[report])),
                           received_at=received)
            self.assertTrue(r.accepted)
            flags.append(sorted(f.value for f in r.assertions[0].flags))
            spans.append(r.derived[0].result["unchanged_s"])
        self.assertEqual(flags, [[], ["stuck"]])
        # 282 first appeared with the last sample of the live hour: known to the sample.
        self.assertEqual(spans[1], 3600)
        self.assertEqual(state.validate(), [])

    def test_a_sample_on_an_aggregate_channel_is_recorded_not_guessed(self):
        gw, lg, state, derived = _farm()
        r = gw.receive(wire.encode(wire.Message(boot=1, seq=1, base_age=0, node=NODE,
                                                readings=[wire.Reading(3, 0, 281)])),
                       received_at=NOW)
        self.assertEqual(r.raw, ())
        self.assertIn(G.SHAPE, [e.kind for e in lg.events], "the mismatch is in the log")

    def test_served_as_a_window(self):
        gw, lg, state, derived = _farm()
        w = wire.Window()
        for i in range(12):
            w.add(281, 300.0 * i)
        gw.receive(wire.encode(wire.Message(boot=1, seq=1, base_age=0, node=NODE,
                                            readings=[wire.Reading(3, 0, w.close())])),
                   received_at=NOW)
        obs = state.observations_of(derived.id)[0]
        server = ST.Service(state)
        start, end = server.observation(obs)["phenomenonTime"].split("/")
        self.assertEqual(end, ST.iso(obs.measured_at))
        self.assertEqual(start, ST.iso(obs.measured_at - _dt.timedelta(hours=1)))
        self.assertTrue(server.datastream(derived)["observationType"].endswith(
            "OM_ComplexObservation"))


class TestChecks(unittest.TestCase):
    def test_the_evidence_names_range_and_flatline(self):
        ds = aggregate_datastream(thresholds={"flat_seconds": 600.0, "max": 300})
        obs = fx.observation(ds, result={"n": 12, "min": 280, "max": 320, "unchanged_s": 900})
        lg = L.Log()
        for r in (ds, obs):
            lg.append_record(r)
        a = C.assess(P.state_from_log(lg), obs)
        self.assertEqual(sorted(f.value for f in a.flags), ["out_of_range", "stuck"])
        self.assertEqual(a.evidence["checks_run"], ["range", "flatline"])


if __name__ == "__main__":
    unittest.main()
