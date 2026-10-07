#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Injectable faults, and two §2 properties worth proving rather than asserting."""
from __future__ import annotations

import datetime as _dt
import unittest

import faults as F
import harness
import link as lk
import node as nd
import physics as ph
import world_demo as wd

JULY = _dt.datetime(2026, 7, 15, 0, 0, tzinfo=ph.UTC)
T0 = JULY.timestamp()


def _days(n=2.0, start=JULY):
    world = ph.default_world(start=start)
    return list(world.run(days=n))


class TestSensorFaults(unittest.TestCase):
    def setUp(self):
        self.rows = _days(3.0)

    def _series(self, *faults):
        sensor = F.Sensor(lambda t: t.soil["bed3"], faults=list(faults))
        return [sensor(r) for r in self.rows[::12]]   # hourly

    def test_a_clean_sensor_tracks_the_physics(self):
        clean = self._series()
        self.assertGreater(len(set(clean)), 5, "soil moves over three days")
        self.assertTrue(all(isinstance(v, int) for v in clean),
                        "the node reports integers (§5.1)")

    def test_drift_diverges_from_truth(self):
        clean = self._series()
        drifted = self._series(F.Drifting(begins_at_s=T0, per_day=0.02))
        self.assertEqual(clean[0], drifted[0], "nothing has drifted yet")
        self.assertGreater(drifted[-1] - clean[-1], 40,
                           "three days at 0.02/day is about 0.06")

    def test_drift_before_its_start_time_does_nothing(self):
        late = self._series(F.Drifting(begins_at_s=T0 + 10 * 86400, per_day=0.1))
        self.assertEqual(late, self._series())

    def test_sticking_freezes_the_reading(self):
        stuck = self._series(F.Sticking(begins_at_s=T0 + 3600))
        self.assertEqual(len(set(stuck[2:])), 1, "frozen after the first hour")

    def test_bias_is_a_constant_offset(self):
        clean = self._series()
        biased = self._series(F.Biased(begins_at_s=T0, offset=0.05))
        self.assertTrue(all(b - c == 50 for b, c in zip(biased, clean)))

    def test_bias_is_invisible_to_a_single_series(self):
        """Included precisely because no §4.2 check can catch it — a detector that
        claims to would be lying, and a drill should score that honestly."""
        biased = self._series(F.Biased(begins_at_s=T0, offset=0.05))
        self.assertGreater(len(set(biased)), 5, "it still moves like real soil")

    def test_noise_perturbs_but_does_not_trend(self):
        clean = self._series()
        noisy = self._series(F.Noisy(begins_at_s=T0, sigma=0.01, seed=2))
        self.assertNotEqual(clean, noisy)
        deltas = [n - c for n, c in zip(noisy, clean)]
        self.assertLess(abs(sum(deltas) / len(deltas)), 12, "no systematic shift")

    def test_a_dead_sensor_produces_absence_not_a_wrong_value(self):
        """§4.2: a dead sensor should produce no observations at all, and no
        quality assertions about readings that do not exist."""
        dead = self._series(F.Dead(begins_at_s=T0 + 3600))
        self.assertIsNotNone(dead[0])
        self.assertTrue(all(v is None for v in dead[2:]))

    def test_out_of_range_is_the_positive_control(self):
        reads = self._series(F.OutOfRange(begins_at_s=T0, value=4.2))
        self.assertTrue(all(v == 4200 for v in reads))

    def test_faults_compose_in_order(self):
        both = self._series(F.Biased(begins_at_s=T0, offset=0.05),
                           F.Sticking(begins_at_s=T0 + 3600))
        self.assertEqual(len(set(both[2:])), 1)

    def test_injected_is_ground_truth_the_detectors_cannot_see(self):
        sensor = F.Sensor(lambda t: t.soil["bed3"])
        self.assertEqual(sensor.injected(), [])
        self.assertFalse(sensor.faulty)
        sensor.inject(F.Sticking(begins_at_s=T0 + 500))
        self.assertTrue(sensor.faulty)
        self.assertEqual(sensor.injected(at_s=T0), [], "not active yet")
        self.assertEqual(len(sensor.injected(at_s=T0 + 600)), 1)

    def test_quantisation_is_modelled_not_assumed_away(self):
        """It is what made a healthy probe look flatlined (§4.2)."""
        coarse = F.Sensor(lambda t: t.soil["bed3"], scale=10)
        fine = F.Sensor(lambda t: t.soil["bed3"], scale=10000)
        hourly = self.rows[::12]
        self.assertLess(len({coarse(r) for r in hourly}),
                        len({fine(r) for r in hourly}))


class TestClockOffsetCancels(unittest.TestCase):
    """§2 has nodes report AGES, not timestamps, and this is why.

    A node computes an age from its own clock at both ends, so a constant offset
    subtracts out exactly. A node whose clock is six hours wrong still produces a
    correct `measured_at`. Demonstrated rather than asserted, because it is the
    justification for the whole design.
    """

    def _run(self, offset_hours):
        world, node, gateway, _ = wd.build(stuck_float=False, dr=0, seed=1,
                                           start=JULY)
        harness.run(world=world, node=node, gateway=gateway,
                    link=lk.Link(lk.WIRED), days=0.5,
                    node_clock_offset_s=offset_hours * 3600.0)
        return sorted(o.measured_at for o in gateway.state.observations)

    def test_a_six_hour_error_changes_nothing(self):
        self.assertEqual(self._run(0.0), self._run(6.0))

    def test_nor_does_a_backwards_error(self):
        self.assertEqual(self._run(0.0), self._run(-3.0))

    def test_the_readings_are_at_their_real_times(self):
        times = self._run(6.0)
        self.assertGreaterEqual(times[0], JULY)
        self.assertLess(times[-1], JULY + _dt.timedelta(days=1))


class TestStampingAtSampleTimeCorruptsTheData(unittest.TestCase):
    """The §2 violation a driver is most likely to make, modelled so the damage can
    be shown: ages stamped when the reading was taken rather than when the frame
    leaves, so a buffered batch is backdated by its whole dwell."""

    def _measured_times(self, *, stamp_at_sample, outage_hours):
        world, node, gateway, _ = wd.build(stuck_float=False, dr=0, seed=1,
                                           start=JULY)
        node.stamp_at_sample = stamp_at_sample
        node.ack_timeout_s = 1800.0
        outage_from = JULY + _dt.timedelta(hours=2)
        harness.run(world=world, node=node, gateway=gateway,
                    link=lk.Link(lk.WIRED), days=1.0,
                    outages=[(outage_from,
                              outage_from + _dt.timedelta(hours=outage_hours))])
        return sorted(o.measured_at for o in gateway.state.observations)

    def test_without_an_outage_the_mistake_is_invisible(self):
        """Which is exactly why it ships: nothing reveals it until a link drops."""
        correct = self._measured_times(stamp_at_sample=False, outage_hours=0)
        wrong = self._measured_times(stamp_at_sample=True, outage_hours=0)
        self.assertEqual(correct, wrong)

    def test_after_an_outage_the_whole_window_collapses_onto_the_recovery(self):
        """The damage, stated precisely: readings taken during the outage arrive
        claiming they were taken when the link came back. Six hours of history
        becomes one instant, and nothing in the record says so."""
        outage = (JULY + _dt.timedelta(hours=2), JULY + _dt.timedelta(hours=8))
        correct = self._measured_times(stamp_at_sample=False, outage_hours=6)
        wrong = self._measured_times(stamp_at_sample=True, outage_hours=6)
        self.assertNotEqual(correct, wrong)

        def during(times):
            return [t for t in times if outage[0] <= t < outage[1]]

        self.assertGreater(len(during(correct)), 50,
                           "store-and-forward recovers the window with real times")
        self.assertEqual(during(wrong), [],
                         "the mistake erases the window entirely")


class TestResendKeepsItsSequenceNumber(unittest.TestCase):
    """§5.2, the same rule §6.3 states for commands. A retry under a fresh number
    is a new message to the gateway, which then writes the same readings again at
    timestamps a rounding apart."""

    def _lossy(self, *, ack_timeout):
        world, node, gateway, _ = wd.build(stuck_float=False, dr=0, seed=1,
                                           start=JULY)
        node.ack_timeout_s = ack_timeout
        report = harness.run(world=world, node=node, gateway=gateway,
                             link=lk.Link(lk.MESHTASTIC, seed=1), days=1.0)
        return node, gateway, report

    def test_a_resend_reuses_its_seq_and_is_recognised_as_a_duplicate(self):
        node, gateway, report = self._lossy(ack_timeout=1800.0)
        self.assertGreater(report.duplicates_rejected, 10,
                           "resends of frames that did arrive")
        self.assertEqual(gateway.state.validate(), [])

    def test_the_series_is_not_inflated_with_phantom_readings(self):
        """768 readings are produced in a day; a resend under a fresh seq produced
        2498 before this was fixed."""
        node, gateway, report = self._lossy(ack_timeout=1800.0)
        self.assertLessEqual(len(gateway.state.observations), 800)
        self.assertGreater(len(gateway.state.observations), 700,
                           "and store-and-forward still recovers nearly all of it")

    def test_without_a_deadline_the_cumulative_ack_stalls_at_the_first_hole(self):
        """§5.2: a deadline is mandatory on a link that relies on cumulative
        acknowledgement, because `highest_contiguous` cannot pass a gap."""
        stalled, gateway, _ = self._lossy(ack_timeout=None)
        resending, _, _ = self._lossy(ack_timeout=1800.0)
        self.assertGreater(stalled.unacked, 10 * resending.unacked)

    def test_a_resend_is_marked_as_one(self):
        node = nd.Node(0x1, [nd.Channel(1, 300.0, 300.0, lambda t: 231)],
                       ack_timeout_s=60.0)
        world = ph.World(start=JULY, beds=[ph.SoilBed(name="b")])
        node.sample(world.step())
        first = node.transmit(T0)
        self.assertFalse(first.resend)
        node.expire_unacked(T0 + 120)
        self.assertEqual(node.awaiting_resend, 1)
        again = node.transmit(T0 + 120)
        self.assertTrue(again.resend)
        self.assertEqual(again.seq, first.seq, "the same number, by design")


if __name__ == "__main__":
    unittest.main(verbosity=2)
