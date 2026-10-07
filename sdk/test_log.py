#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The append-only log (spec v0.1 §7.1, §7.3, §7.4)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import fixtures as fx
import log as L
from hlc import Hlc, Stamp, before
from ids import uuid7


class FakeClock:
    def __init__(self, ms=1000):
        self.ms = ms

    def __call__(self):
        return self.ms


class LogCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "log.jsonl")


class TestAppendOnly(LogCase):
    def test_there_is_no_mutation_api(self):
        """§7.3: a correction is a compensating event. Nothing updates in place,
        and the API must not offer a way to try."""
        for name in ("update", "delete", "remove", "pop", "clear", "replace",
                     "__setitem__", "__delitem__"):
            self.assertFalse(hasattr(L.Log, name), f"Log must not expose {name}")

    def test_events_view_is_immutable(self):
        lg = L.Log()
        lg.append("note", {"a": 1})
        self.assertIsInstance(lg.events, tuple)
        with self.assertRaises(AttributeError):
            lg.events.append("nope")

    def test_duplicate_event_ids_are_refused(self):
        lg = L.Log()
        ev = lg.append("note", {})
        with self.assertRaisesRegex(L.LogError, "duplicate"):
            lg._commit(ev)

    def test_a_kind_is_required(self):
        with self.assertRaises(L.LogError):
            L.Log().append("", {})


class TestPersistence(LogCase):
    def test_replay_reproduces_the_log_exactly(self):
        lg = L.Log(self.path)
        raw = fx.raw_datastream()
        lg.append_record(raw)
        lg.append_record(fx.observation(raw))
        lg.append_record(fx.assertion(uuid7()))
        again = L.Log(self.path)
        self.assertEqual(again.events, lg.events,
                         "a log you cannot replay identically is not an audit trail")
        self.assertEqual(again.skipped_lines, ())

    def test_records_decode_back_into_contract_types(self):
        lg = L.Log(self.path)
        raw = fx.raw_datastream()
        obs = fx.observation(raw, result=0.42)
        lg.append_record(raw)
        lg.append_record(obs)
        decoded = list(L.Log(self.path).records("observation"))
        self.assertEqual(decoded, [obs])

    def test_appends_are_durable_before_the_call_returns(self):
        lg = L.Log(self.path)
        lg.append("note", {"n": 1})
        with open(self.path) as f:
            self.assertEqual(len(f.read().splitlines()), 1)

    def test_a_truncated_final_line_does_not_lose_history(self):
        """Expected on a farm gateway after a power cut, not an exception."""
        lg = L.Log(self.path)
        lg.append("note", {"n": 1})
        lg.append("note", {"n": 2})
        with open(self.path, "a") as f:
            f.write('{"id": "half-writ')
        recovered = L.Log(self.path)
        self.assertEqual(len(recovered), 2)
        self.assertEqual(len(recovered.skipped_lines), 1)
        self.assertIn("line 3", recovered.skipped_lines[0])

    def test_an_illegal_record_fails_on_replay_rather_than_becoming_state(self):
        with open(self.path, "w") as f:
            bad = {"id": str(uuid7()), "stamp": "1.0", "kind": "observation",
                   "recorded_at": "2026-06-01T00:00:00Z",
                   "payload": {"_t": "Observation", "id": str(uuid7()),
                               "datastream": str(uuid7()),
                               "measured_at": "2026-06-01T00:00:00Z",
                               "measured_at_uncertainty": 0,     # §2 violation
                               "received_at": "2026-06-01T00:00:00Z",
                               "result": 1, "clock_quality": "gps"}}
            f.write(json.dumps(bad) + "\n")
        lg = L.Log(self.path)
        with self.assertRaisesRegex(ValueError, "never zero"):
            list(lg.records())


class TestCorrections(LogCase):
    def test_correction_is_a_new_event_and_the_original_survives(self):
        lg = L.Log(self.path)
        raw = fx.raw_datastream()
        lg.append_record(raw)
        obs = fx.observation(raw, result=99.0)
        target = lg.append_record(obs)
        lg.correct(target.id, "entered against the wrong bed")
        self.assertEqual(len(lg), 3)
        self.assertIn(obs, list(lg.records("observation")),
                      "the original stays readable forever (§7.3)")
        reasons = [e.payload["reason"] for e in lg.corrections()]
        self.assertEqual(reasons, ["entered against the wrong bed"])

    def test_correction_can_carry_a_replacement(self):
        lg = L.Log()
        raw = fx.raw_datastream()
        lg.append_record(raw)
        target = lg.append_record(fx.observation(raw, result=99.0))
        better = fx.observation(raw, result=0.21)
        lg.correct(target.id, "typo", replacement=better)
        payload = next(lg.corrections()).payload
        self.assertEqual(payload["replacement"]["_t"], "Observation")
        self.assertEqual(payload["corrects"], str(target.id))

    def test_a_correction_needs_a_reason(self):
        lg = L.Log()
        ev = lg.append("note", {})
        with self.assertRaisesRegex(L.LogError, "must say why"):
            lg.correct(ev.id, "")

    def test_cannot_correct_an_event_that_is_not_there(self):
        with self.assertRaisesRegex(L.LogError, "not in the log"):
            L.Log().correct(uuid7(), "nonexistent")


class TestOrdering(LogCase):
    def test_events_are_held_in_hlc_order(self):
        lg = L.Log(hlc=Hlc(clock=FakeClock(1000)))
        for n in range(5):
            lg.append("note", {"n": n})
        stamps = [e.stamp for e in lg]
        self.assertEqual(stamps, sorted(stamps, key=lambda s: (s.wall_ms, s.counter)))

    def test_a_remote_event_merges_its_stamp(self):
        """§7.4: a replica that appends without merging has dropped causality."""
        clock = FakeClock(1000)
        lg = L.Log(hlc=Hlc(clock=clock))
        local_before = lg.append("note", {"where": "here"})
        remote = L.Event(id=uuid7(), stamp=Stamp(9_000_000, 2), kind="note",
                         payload={"where": "the phone with the bad clock"},
                         recorded_at=local_before.recorded_at)
        lg.receive(remote)
        after = lg.append("note", {"where": "here again"})
        self.assertTrue(before(remote.stamp, after.stamp),
                        "a write after learning of the remote must sort after it")

    def test_receive_is_idempotent(self):
        lg = L.Log()
        ev = L.Event(id=uuid7(), stamp=Stamp(5, 0), kind="note", payload={},
                     recorded_at=fx.T0)
        lg.receive(ev)
        lg.receive(ev)
        self.assertEqual(len(lg), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
