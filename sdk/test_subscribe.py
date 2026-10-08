#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for §7.5 subscriptions. The first class is the reason the module exists."""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
import unittest

import fixtures as fx
import log as L
import subscribe as S
from hlc import Stamp
from ids import uuid7

UTC = _dt.timezone.utc


def _log_with(n: int) -> tuple[L.Log, object]:
    log = L.Log()
    ds = fx.raw_datastream()
    log.append_record(ds)
    for i in range(n):
        log.append_record(fx.observation(datastream=ds, measured_at=fx.at(i), seq=i))
    return log, ds


def _remote_event_from_yesterday(ds) -> L.Event:
    """An edit made offline on another replica, a day ago, arriving only now.

    Its HLC stamp is older than everything this log has written today, so `receive`
    inserts it into the *middle* of history.
    """
    yesterday = _dt.datetime.now(tz=UTC) - _dt.timedelta(days=1)
    obs = fx.observation(datastream=ds, measured_at=fx.at(-60 * 24), seq=999)
    import codec
    return L.Event(id=uuid7(), stamp=Stamp(int(yesterday.timestamp() * 1000), 0),
                   kind="observation", payload=codec.dump(obs),
                   recorded_at=yesterday)


class TestTheOfflineEditIsNotLost(unittest.TestCase):
    """§7.5's failure, demonstrated rather than asserted."""

    def setUp(self):
        self.log, self.ds = _log_with(10)
        self.sub = S.Subscription(self.log, "irrigation", S.MemoryCursorStore())
        self.sub.deliver(lambda e: None)              # caught up
        self.late = _remote_event_from_yesterday(self.ds)
        self.log.receive(self.late)

    def test_the_late_event_landed_in_the_middle_of_hlc_order(self):
        """The precondition: if it appended at the end there would be no trap."""
        order = [e.id for e in self.log.events]
        self.assertLess(order.index(self.late.id), len(order) - 1)

    def test_a_cursor_on_the_last_stamp_seen_never_sees_it(self):
        """The naive design, run for real. Every event after the last stamp seen —
        and the late one is *before* it, so the answer is nothing."""
        caught_up_to = max(e.stamp for e in self.log.events if e.id != self.late.id)
        after = [e for e in self.log.events
                 if (e.stamp.wall_ms, e.stamp.counter)
                 > (caught_up_to.wall_ms, caught_up_to.counter)]
        self.assertNotIn(self.late.id, {e.id for e in after})

    def test_a_cursor_on_hlc_position_never_sees_it(self):
        position = len(self.log.events) - 1             # "I have read this many"
        later = self.log.events[position:]
        self.assertNotIn(self.late.id, {e.id for e in later})

    def test_the_arrival_cursor_delivers_it(self):
        got = []
        self.sub.deliver(got.append)
        self.assertEqual([e.id for e in got], [self.late.id])

    def test_after_which_the_subscriber_is_caught_up(self):
        self.sub.deliver(lambda e: None)
        self.assertEqual(self.sub.lag(), 0)


class TestAtLeastOnce(unittest.TestCase):

    def setUp(self):
        self.log, _ = _log_with(6)

    def test_a_crash_before_ack_redelivers_the_batch(self):
        """Act, then save. A crash in between costs a duplicate, never a loss."""
        sub = S.Subscription(self.log, "m", S.MemoryCursorStore())
        first = sub.poll()
        self.assertEqual(len(first), 7)
        # ...the handler ran, and the process died before ack()...
        again = sub.poll()
        self.assertEqual([e.id for e in again.events], [e.id for e in first.events])

    def test_a_handler_that_raises_leaves_the_cursor_where_it_was(self):
        sub = S.Subscription(self.log, "m", S.MemoryCursorStore())
        seen = []

        def flaky(event):
            seen.append(event.id)
            if len(seen) == 3:
                raise RuntimeError("valve controller unreachable")

        with self.assertRaises(RuntimeError):
            sub.deliver(flaky, batch_size=100)
        self.assertEqual(sub.cursor.offset, 0)
        self.assertEqual(sub.lag(), 7)

    def test_redelivery_after_a_failure_is_everything_not_just_the_rest(self):
        """Batch granularity: the events before the failure come round again, which is
        why handlers must be idempotent on `event.id`."""
        sub = S.Subscription(self.log, "m", S.MemoryCursorStore())
        calls = []

        def once_flaky(event):
            calls.append(event.id)
            if len(calls) == 2:
                raise RuntimeError("once")

        with self.assertRaises(RuntimeError):
            sub.deliver(once_flaky, batch_size=100)
        sub.deliver(lambda e: calls.append(e.id), batch_size=100)
        self.assertEqual(len(set(calls)), 7)
        self.assertGreater(len(calls), 7, "at-least-once: some came twice")


class TestDurableCursor(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.dir, "log.jsonl")
        self.cursor_path = os.path.join(self.dir, "cursors", "irrigation.json")

    def test_a_module_that_restarts_resumes_where_it_stopped(self):
        """The §7.5 sentence, end to end: a module goes down, the farm keeps writing,
        the module comes back and gets exactly what it missed."""
        log = L.Log(self.log_path)
        ds = fx.raw_datastream()
        log.append_record(ds)
        for i in range(4):
            log.append_record(fx.observation(datastream=ds, measured_at=fx.at(i), seq=i))
        before = []
        S.Subscription(log, "irrigation", S.CursorStore(self.cursor_path)).deliver(
            before.append)

        # The module is down. The farm is not.
        for i in range(4, 9):
            log.append_record(fx.observation(datastream=ds, measured_at=fx.at(i), seq=i))
        log.receive(_remote_event_from_yesterday(ds))

        # Both the log and the subscriber come back from disk.
        reopened = L.Log(self.log_path)
        after = []
        S.Subscription(reopened, "irrigation",
                       S.CursorStore(self.cursor_path)).deliver(after.append)
        self.assertEqual(len(after), 6, "five new readings and the late offline edit")
        self.assertEqual(set(e.id for e in before) & set(e.id for e in after), set())

    def test_arrival_order_survives_a_reopen(self):
        """It is what makes the cursor durable: `_commit` appends to the file in
        arrival order, and only the in-memory list is sorted by stamp."""
        log = L.Log(self.log_path)
        ds = fx.raw_datastream()
        log.append_record(ds)
        log.append_record(fx.observation(datastream=ds, measured_at=fx.at(0)))
        log.receive(_remote_event_from_yesterday(ds))
        arrived = [e.id for e in log.arrivals_since(0)]
        self.assertEqual([e.id for e in L.Log(self.log_path).arrivals_since(0)],
                         arrived)
        self.assertNotEqual([e.id for e in log.events], arrived,
                            "and it is genuinely different from HLC order")

    def test_the_cursor_file_is_written_atomically(self):
        store = S.CursorStore(self.cursor_path)
        store.save(S.Cursor(offset=3, anchor=uuid7()), subscriber="irrigation")
        leftovers = [f for f in os.listdir(os.path.dirname(self.cursor_path))
                     if f.startswith(".cursor-")]
        self.assertEqual(leftovers, [], "no temporary file left behind")
        with open(self.cursor_path, encoding="utf-8") as handle:
            doc = json.load(handle)
        self.assertEqual(doc["offset"], 3)
        self.assertEqual(doc["subscriber"], "irrigation")

    def test_a_missing_cursor_file_means_start_from_the_beginning(self):
        self.assertEqual(S.CursorStore(self.cursor_path).load(), S.Cursor())


class TestACursorBelongsToOneReplica(unittest.TestCase):
    """Arrival order differs between replicas, so a borrowed cursor must refuse."""

    def test_a_cursor_from_another_replica_is_refused(self):
        mine, _ = _log_with(5)
        theirs, _ = _log_with(5)
        store = S.MemoryCursorStore()
        S.Subscription(theirs, "m", store).deliver(lambda e: None)
        with self.assertRaises(S.CursorMismatch) as caught:
            S.Subscription(mine, "m", store).poll()
        self.assertIn("replica", str(caught.exception))

    def test_a_cursor_beyond_the_end_is_refused(self):
        log, _ = _log_with(2)
        store = S.MemoryCursorStore(S.Cursor(offset=99, anchor=uuid7()))
        with self.assertRaises(S.CursorMismatch):
            S.Subscription(log, "m", store).poll()

    def test_a_cursor_must_have_an_anchor_unless_it_is_at_zero(self):
        with self.assertRaises(ValueError):
            S.Cursor(offset=3, anchor=None)
        with self.assertRaises(ValueError):
            S.Cursor(offset=0, anchor=uuid7())


class TestFiltering(unittest.TestCase):

    def test_a_filtered_subscriber_still_advances_past_what_it_skips(self):
        """Otherwise it re-scans every non-matching event forever, and on a farm that
        is almost all of them."""
        log, _ = _log_with(4)
        sub = S.Subscription(log, "m", S.MemoryCursorStore(), kinds={"datastream"})
        got = []
        sub.deliver(got.append)
        self.assertEqual(len(got), 1)
        self.assertEqual(sub.lag(), 0)

    def test_an_empty_poll_does_not_move_the_cursor(self):
        log, _ = _log_with(1)
        sub = S.Subscription(log, "m", S.MemoryCursorStore())
        sub.deliver(lambda e: None)
        cursor = sub.cursor
        self.assertEqual(sub.poll().scanned, 0)
        self.assertEqual(sub.cursor, cursor)


class TestWakeup(unittest.TestCase):

    def test_on_commit_fires_after_each_append(self):
        log = L.Log()
        seen = []
        log.on_commit(seen.append)
        log.append_record(fx.raw_datastream())
        self.assertEqual(len(seen), 1)

    def test_unsubscribing_stops_it(self):
        log = L.Log()
        seen = []
        stop = log.on_commit(seen.append)
        stop()
        log.append_record(fx.raw_datastream())
        self.assertEqual(seen, [])

    def test_a_listener_that_raises_does_not_undo_the_commit_and_is_recorded(self):
        """The commit was already durable. A broken subscriber must be visible, not
        hidden — and must not be able to roll back the farm's history."""
        log = L.Log()

        def broken(event):
            raise RuntimeError("module crashed")

        log.on_commit(broken)
        log.append_record(fx.raw_datastream())
        self.assertEqual(len(log.events), 1)
        self.assertEqual(len(log.listener_errors), 1)
        self.assertIn("module crashed", log.listener_errors[0])


if __name__ == "__main__":
    unittest.main()
