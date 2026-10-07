#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The node side of store-and-forward (spec v0.1 §5.2, §5.3, §5.3.1, §2)."""
from __future__ import annotations

import datetime as _dt
import os
import sys
import unittest

import node as nd
import physics as ph

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sdk"))
import wire  # noqa: E402

JULY = _dt.datetime(2026, 7, 1, 0, 0, tzinfo=ph.UTC)
T0 = JULY.timestamp()


def _node(*channels, **kw):
    return nd.Node(0x4F2A17B3, channels or [nd.Channel(1, 300.0, 3600.0, lambda t: 231)],
                   **kw)


def _truth(at_s):
    """A ground-truth snapshot with only the fields a node reads."""
    world = ph.World(start=_dt.datetime.fromtimestamp(at_s, tz=ph.UTC),
                     beds=[ph.SoilBed(name="bed", theta=0.28)])
    return world.step()


class TestSchedule(unittest.TestCase):
    """§5.3.1: the tightest latency sets the schedule for everything sharing the
    radio."""

    def test_the_tightest_latency_wins(self):
        n = _node(nd.Channel(1, 3600.0, 3600.0, lambda t: 1),
                  nd.Channel(2, 300.0, 300.0, lambda t: 2))
        self.assertEqual(n.transmit_interval_s, 300.0)

    def test_a_sleepy_node_keeps_its_own_schedule(self):
        n = _node(nd.Channel(1, 3600.0, 3600.0, lambda t: 1))
        self.assertEqual(n.transmit_interval_s, 3600.0)

    def test_nothing_is_due_with_an_empty_buffer(self):
        self.assertFalse(_node().due(T0))

    def test_the_first_reading_is_due_immediately(self):
        n = _node()
        n.sample(_truth(T0))
        self.assertTrue(n.due(T0))


class TestSampling(unittest.TestCase):
    def test_a_channel_is_sampled_on_its_own_interval(self):
        n = _node(nd.Channel(1, 900.0, 3600.0, lambda t: 1))
        self.assertEqual(n.sample(_truth(T0)), 1)
        self.assertEqual(n.sample(_truth(T0 + 300)), 0, "not due yet")
        self.assertEqual(n.sample(_truth(T0 + 900)), 1)

    def test_channels_sample_independently(self):
        n = _node(nd.Channel(1, 300.0, 3600.0, lambda t: 1),
                  nd.Channel(2, 900.0, 3600.0, lambda t: 2))
        n.sample(_truth(T0))
        self.assertEqual(n.sample(_truth(T0 + 300)), 1, "only the fast channel")

    def test_a_sensor_with_nothing_to_report_is_skipped(self):
        n = _node(nd.Channel(1, 300.0, 3600.0, lambda t: None))
        self.assertEqual(n.sample(_truth(T0)), 0)
        self.assertEqual(n.buffered, 0)

    def test_a_sub_second_interval_is_refused(self):
        """§5.2: wire ages are whole seconds, so a faster channel cannot express
        distinct instants and the gateway would have to refuse the collision."""
        with self.assertRaisesRegex(ValueError, "whole-second"):
            nd.Channel(1, 0.5, 3600.0, lambda t: 1)

    def test_a_node_needs_a_channel(self):
        with self.assertRaises(ValueError):
            nd.Node(1, [])


class TestTransmitTimestamps(unittest.TestCase):
    """§2: ages are stamped at transmit, not at sample time."""

    def test_a_buffered_reading_leaves_with_its_real_age(self):
        n = _node()
        n.sample(_truth(T0))
        tx = n.transmit(T0 + 3 * 86400)
        message = wire.decode(tx.payload)
        self.assertEqual(message.base_age, 3 * 86400,
                         "three days in a buffer must show as three days of age")

    def test_base_age_is_the_youngest_reading(self):
        n = _node(nd.Channel(1, 300.0, 3600.0, lambda t: 231))
        n.sample(_truth(T0))
        n.sample(_truth(T0 + 300))
        n.sample(_truth(T0 + 600))
        message = wire.decode(n.transmit(T0 + 900).payload)
        self.assertEqual(message.base_age, 300)
        self.assertEqual(sorted(r.age_delta for r in message.readings), [0, 300, 600])

    def test_the_frame_carries_boot_and_seq(self):
        n = _node(boot=7)
        n.sample(_truth(T0))
        message = wire.decode(n.transmit(T0).payload)
        self.assertEqual((message.boot, message.seq), (7, 0))
        self.assertEqual(message.node, 0x4F2A17B3)


class TestPayloadBudget(unittest.TestCase):
    def test_a_frame_fits_the_data_rate(self):
        n = _node(nd.Channel(1, 300.0, 86400.0, lambda t: 231), dr=0)
        for i in range(40):
            n.sample(_truth(T0 + i * 300))
        tx = n.transmit(T0 + 40 * 300)
        self.assertLessEqual(len(tx.payload), n.max_payload)
        self.assertLess(tx.readings, 40, "the rest stays buffered")

    def test_a_better_data_rate_carries_more(self):
        def carried(dr):
            n = _node(nd.Channel(1, 300.0, 86400.0, lambda t: 231), dr=dr)
            for i in range(40):
                n.sample(_truth(T0 + i * 300))
            return n.transmit(T0 + 40 * 300).readings
        self.assertGreater(carried(3), carried(0))

    def test_what_does_not_fit_stays_buffered_not_lost(self):
        n = _node(nd.Channel(1, 300.0, 86400.0, lambda t: 231), dr=0)
        for i in range(40):
            n.sample(_truth(T0 + i * 300))
        tx = n.transmit(T0 + 40 * 300)
        self.assertEqual(n.buffered + tx.readings, 40)


class TestDutyCycle(unittest.TestCase):
    """§5.2: the limit is a regulation, so it costs latency rather than data."""

    def test_a_node_that_cannot_afford_a_message_defers_it(self):
        n = _node(duty_budget_s=1.0)        # less than one SF12 frame
        n.sample(_truth(T0))
        tx = n.transmit(T0)
        self.assertFalse(tx.sent)
        self.assertIn("duty cycle", tx.deferred)
        self.assertEqual(n.buffered, 1, "the reading is kept")

    def test_the_sequence_number_is_not_consumed_by_a_deferral(self):
        n = _node(duty_budget_s=1.0)
        n.sample(_truth(T0))
        n.transmit(T0)
        self.assertEqual(n.seq, 0)

    def test_budget_recovers_over_the_hour(self):
        n = _node(duty_budget_s=3.0)
        n.sample(_truth(T0))
        self.assertTrue(n.transmit(T0).sent)
        n.sample(_truth(T0 + 300))
        self.assertFalse(n.transmit(T0 + 300).sent)
        n.sample(_truth(T0 + 3700))
        self.assertTrue(n.transmit(T0 + 3700).sent)


class TestEviction(unittest.TestCase):
    """§5.3: a node that evicts MUST report the count."""

    def _fill(self, policy, n_readings=20):
        n = _node(nd.Channel(1, 300.0, 86400.0, lambda t: 231), policy=policy)
        for i in range(n_readings):
            n.sample(_truth(T0 + i * 300))
        return n

    def test_the_buffer_does_not_grow_past_its_limit(self):
        n = self._fill(nd.BufferPolicy(buffer_max=5))
        self.assertEqual(n.retained, 5)

    def test_evictions_are_counted(self):
        n = self._fill(nd.BufferPolicy(buffer_max=5))
        self.assertEqual(n.dropped_pending, 15)

    def test_the_count_is_reported_once_and_then_cleared(self):
        n = self._fill(nd.BufferPolicy(buffer_max=5))
        tx = n.transmit(T0 + 20 * 300)
        self.assertEqual(tx.dropped_reported, 15)
        self.assertEqual(wire.decode(tx.payload).dropped, 15)
        self.assertEqual(n.dropped_pending, 0, "not double-counted")

    def test_oldest_eviction_keeps_the_newest_readings(self):
        n = self._fill(nd.BufferPolicy(buffer_max=3, eviction=nd.EVICT_OLDEST))
        kept = sorted(h.sampled_at_s for h in n._held)
        self.assertEqual(kept[-1], T0 + 19 * 300)

    def test_newest_eviction_keeps_the_oldest_readings(self):
        n = self._fill(nd.BufferPolicy(buffer_max=3, eviction=nd.EVICT_NEWEST))
        kept = sorted(h.sampled_at_s for h in n._held)
        self.assertEqual(kept[0], T0)

    def test_a_bad_policy_is_refused(self):
        with self.assertRaises(ValueError):
            nd.BufferPolicy(eviction="whatever")
        with self.assertRaises(ValueError):
            nd.BufferPolicy(drain_order="whatever")
        with self.assertRaises(ValueError):
            nd.BufferPolicy(buffer_max=0)


class TestDrainOrder(unittest.TestCase):
    """§5.3: the two target apps want opposite answers, and both are correct."""

    def _backlog(self, drain_order):
        n = _node(nd.Channel(1, 300.0, 86400.0, lambda t: 231),
                  policy=nd.BufferPolicy(drain_order=drain_order), dr=0)
        for i in range(40):
            n.sample(_truth(T0 + i * 300))
        return n, n.transmit(T0 + 40 * 300)

    def test_chronological_sends_the_oldest_first(self):
        """A research logger wants the series unbroken."""
        n, tx = self._backlog(nd.CHRONOLOGICAL)
        message = wire.decode(tx.payload)
        oldest_age = 40 * 300 - 0
        self.assertEqual(message.base_age + max(r.age_delta for r in message.readings),
                         oldest_age)

    def test_fresh_first_sends_the_newest_first(self):
        """A livestock water monitor wants the current value through."""
        n, tx = self._backlog(nd.FRESH_FIRST)
        message = wire.decode(tx.payload)
        self.assertEqual(message.base_age, 300,
                         "the youngest reading is 300 s old and goes in this frame")

    def test_both_eventually_deliver_everything(self):
        for order in (nd.CHRONOLOGICAL, nd.FRESH_FIRST):
            n, _ = self._backlog(order)
            now = T0 + 40 * 300
            for tx in n.drain(now, max_messages=32):
                n.ack(tx.seq)
            self.assertEqual(n.buffered, 0, order)


class TestConfirmation(unittest.TestCase):
    """§5.2: one small cumulative ack retires many uplinks."""

    def _sent_three(self):
        n = _node(nd.Channel(1, 300.0, 86400.0, lambda t: 231), dr=0)
        for i in range(18):
            n.sample(_truth(T0 + i * 300))
        now = T0 + 18 * 300
        sent = [n.transmit(now), n.transmit(now), n.transmit(now)]
        return n, [tx for tx in sent if tx.sent]

    def test_an_ack_releases_everything_up_to_it(self):
        n, sent = self._sent_three()
        self.assertGreaterEqual(len(sent), 2)
        before = n.unacked
        released = n.ack(sent[1].seq)
        self.assertEqual(released, sent[0].readings + sent[1].readings)
        self.assertLess(n.unacked, before)

    def test_an_unknown_ack_releases_nothing(self):
        n, _ = self._sent_three()
        self.assertEqual(n.ack(9999), 0)

    def test_readings_are_held_until_confirmed(self):
        n, sent = self._sent_three()
        self.assertGreater(n.unacked, 0, "store-and-forward means held, not sent-and-forgotten")

    def test_nack_requeues_for_resend(self):
        n, sent = self._sent_three()
        held = n.unacked
        self.assertEqual(n.nack(), held)
        self.assertEqual(n.unacked, 0)
        self.assertGreaterEqual(n.buffered, held)


class TestReboot(unittest.TestCase):
    """§1: `boot` is the only non-volatile state a node must keep."""

    def test_boot_increments_and_seq_resets(self):
        n = _node(boot=4)
        n.sample(_truth(T0))
        n.transmit(T0)
        n.reboot()
        self.assertEqual((n.boot, n.seq), (5, 0))

    def test_the_buffer_is_lost_and_cannot_be_reported(self):
        """After a power cut the node has no memory of what it held, so the reboot
        event in the log is the only record (§5.4)."""
        n = _node(nd.Channel(1, 300.0, 86400.0, lambda t: 231))
        for i in range(10):
            n.sample(_truth(T0 + i * 300))
        lost = n.reboot()
        self.assertEqual(lost, 10)
        self.assertEqual(n.retained, 0)
        self.assertEqual(n.dropped_pending, 0,
                         "it cannot count what it does not remember")

    def test_non_volatile_buffering_survives_and_requeues(self):
        n = _node(nd.Channel(1, 300.0, 86400.0, lambda t: 231),
                  policy=nd.BufferPolicy(nonvolatile_buffer=True))
        for i in range(10):
            n.sample(_truth(T0 + i * 300))
        n.transmit(T0 + 10 * 300)
        self.assertEqual(n.reboot(), 0)
        self.assertEqual(n.buffered, 10, "including the unconfirmed ones")


class TestFeasibility(unittest.TestCase):
    """A latency ceiling is not a schedule, and an impossible configuration should
    be caught at registration rather than as silent loss in month three."""

    def test_an_ordinary_node_is_feasible(self):
        n = _node(nd.Channel(1, 300.0, 3600.0, lambda t: 1), dr=0)
        self.assertTrue(n.feasible)
        self.assertIn("ok", n.feasibility())

    def test_oversampling_beyond_the_link_is_caught(self):
        n = _node(nd.Channel(1, 30.0, 3600.0, lambda t: 1),
                  nd.Channel(2, 30.0, 3600.0, lambda t: 2), dr=0)
        self.assertFalse(n.feasible)
        self.assertIn("INFEASIBLE", n.feasibility())
        self.assertIn("lose data permanently", n.feasibility())

    def test_a_better_data_rate_can_rescue_it(self):
        channels = [nd.Channel(1, 30.0, 3600.0, lambda t: 1),
                    nd.Channel(2, 30.0, 3600.0, lambda t: 2)]
        self.assertFalse(_node(*channels, dr=0).feasible)
        self.assertTrue(_node(*channels, dr=5).feasible)

    def test_behind_is_not_the_same_as_due(self):
        n = _node(nd.Channel(1, 300.0, 3600.0, lambda t: 231))
        for i in range(5):
            n.sample(_truth(T0 + i * 300))
        now = T0 + 5 * 300
        n.transmit(now)
        n.sample(_truth(now + 300))
        n.sample(_truth(now + 600))
        later = now + 600
        self.assertFalse(n.due(later), "inside the latency ceiling")
        self.assertTrue(n.behind(later), "but holding more than one frame's worth")

    def test_drain_clears_a_backlog_when_the_budget_allows(self):
        n = _node(nd.Channel(1, 300.0, 86400.0, lambda t: 231), dr=3)
        for i in range(60):
            n.sample(_truth(T0 + i * 300))
        now = T0 + 60 * 300
        for tx in n.drain(now):
            n.ack(tx.seq)
        self.assertEqual(n.buffered, 0)

    def test_drain_stops_on_a_duty_cycle_deferral(self):
        n = _node(nd.Channel(1, 300.0, 86400.0, lambda t: 231), dr=0,
                  duty_budget_s=6.0)
        for i in range(60):
            n.sample(_truth(T0 + i * 300))
        sent = n.drain(T0 + 60 * 300)
        self.assertLessEqual(len(sent), 2, "two SF12 frames is about 6 s")
        self.assertGreater(n.buffered, 0)


class TestAgainstPhysics(unittest.TestCase):
    """The node and the world together, which is what step 3 needs."""

    def test_a_day_of_a_trough_and_a_bed(self):
        world = ph.default_world(start=JULY)
        n = nd.Node(0x4F2A17B3, [
            nd.Channel(1, 900.0, 3600.0, lambda t: round(t.soil["bed3"] * 1000),
                       name="bed3"),
            nd.Channel(2, 300.0, 300.0,
                       lambda t: round(t.trough_fraction["paddock"] * 1000),
                       name="trough"),
        ])
        self.assertTrue(n.feasible)
        sent = 0
        for truth in world.run(days=1):
            n.sample(truth)
            now = truth.when.timestamp()
            if n.due(now) or n.behind(now):
                for tx in n.drain(now):
                    n.ack(tx.seq)
                    sent += 1
        self.assertGreater(sent, 200, "a 5-minute latency over 24 h")
        self.assertEqual(n.buffered, 0, "nothing left behind")
        self.assertLess(n.duty.used(world.when.timestamp()), 36.0,
                        "and legally, inside the duty cycle")


if __name__ == "__main__":
    unittest.main(verbosity=2)
