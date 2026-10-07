#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Physics through a node to the gateway (docs/VIRTUAL_FARM.md steps 2-4).

The producer/detector doctrine, as a test: the world injects a fault, a detector
written separately notices it, and — the half that is easy to forget — a healthy
world stays quiet.
"""
from __future__ import annotations

import os
import sys
import unittest

import world_demo as wd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sdk"))
import physics as ph  # noqa: E402
import datetime as _dt  # noqa: E402

JULY = _dt.datetime(2026, 7, 15, 0, 0, tzinfo=ph.UTC)


def _run(*, days=1.0, stuck_float=False, dr=0, outage_hours=0.0, seed=1):
    world, node, gateway, log = wd.build(stuck_float=stuck_float, dr=dr, seed=seed,
                                         start=JULY)
    outage_from = JULY + _dt.timedelta(hours=6)
    outage_to = outage_from + _dt.timedelta(hours=outage_hours)
    for truth in world.run(days=days):
        node.sample(truth)
        now = truth.when.timestamp()
        if outage_from <= truth.when < outage_to:
            continue
        if node.due(now) or node.behind(now):
            for attempt in node.drain(now, max_messages=8):
                gateway.receive(attempt.payload, received_at=truth.when)
                node.ack(attempt.seq)
    return world, node, gateway, log


class TestAHealthyFarmStaysQuiet(unittest.TestCase):
    """The regression that matters most. A default which fires on a working farm
    costs the farmer's trust in every flag, which is dearer than a missed
    detection — so a clean day must produce a clean record."""

    def setUp(self):
        self.world, self.node, self.gateway, self.log = _run()
        self.state = self.gateway.state

    def test_no_reading_is_flagged(self):
        flagged = [a for a in self.state.assertions if a.flags]
        self.assertEqual(flagged, [], "a healthy farm must not cry wolf")

    def test_every_reading_is_still_assessed(self):
        """Silence because nothing was checked is not the same as silence because
        nothing was wrong (§3.3)."""
        self.assertGreater(len(self.state.assertions), 300)
        self.assertEqual(len(self.state.assertions),
                         len([o for o in self.state.observations
                              if self.state.datastreams[o.datastream].kind.value
                              == "derived"]))

    def test_the_state_validates(self):
        self.assertEqual(self.state.validate(), [])

    def test_nothing_is_left_buffered_or_unreported(self):
        self.assertEqual(self.node.buffered, 0)
        self.assertEqual(self.node.dropped_pending, 0)

    def test_the_node_stayed_inside_its_duty_cycle(self):
        self.assertLess(self.node.duty.used(self.world.when.timestamp()), 36.0)

    def test_no_gaps_quarantines_or_collisions_were_recorded(self):
        kinds = {e.kind for e in self.log}
        for bad in ("gap", "quarantine", "undecodable_frame", "unbound_channel",
                    "timestamp_collision", "underivable_reading"):
            self.assertNotIn(bad, kinds)

    def test_a_working_float_is_constant_and_that_is_not_a_fault(self):
        """A float-regulated level is constant by design, so flatline detection is
        a category error on it — the range check is what catches a stuck float."""
        trough = [ds for ds in self.state.datastreams.values()
                  if ds.observed_property == wd.TROUGH
                  and ds.kind.value == "derived"][0]
        levels = {o.result for o in self.state.observations
                  if o.datastream == trough.id}
        self.assertLess(len(levels), 40, "a regulated level barely moves")
        self.assertIsNone(trough.thresholds["flat_n"],
                          "so flatline is switched off for it")


class TestTheStuckFloatIsCaught(unittest.TestCase):
    """The fault the physics exists to produce, and the detector written apart
    from it."""

    def setUp(self):
        self.world, self.node, self.gateway, self.log = _run(stuck_float=True)
        self.state = self.gateway.state

    def test_the_trough_is_flagged_out_of_range(self):
        flagged = [a for a in self.state.assertions if a.flags]
        self.assertTrue(flagged)
        flags = {f.value for a in flagged for f in a.flags}
        self.assertIn("out_of_range", flags)

    def test_it_is_caught_in_the_afternoon_not_overnight(self):
        flagged = sorted((a for a in self.state.assertions if a.flags),
                         key=lambda a: a.asserted_at)
        first = next(o for o in self.state.observations
                     if o.id == flagged[0].observation)
        self.assertLess(first.measured_at.hour, 18)
        self.assertGreater(first.measured_at.hour, 8)

    def test_the_soil_series_is_not_implicated(self):
        """A fault in one series must not flag another."""
        for assertion in (a for a in self.state.assertions if a.flags):
            obs = next(o for o in self.state.observations
                       if o.id == assertion.observation)
            ds = self.state.datastreams[obs.datastream]
            self.assertEqual(ds.observed_property, wd.TROUGH)

    def test_the_evidence_names_the_check_and_the_threshold(self):
        flagged = [a for a in self.state.assertions if a.flags][0]
        self.assertIn("range", flagged.evidence["fired"])
        self.assertIsNotNone(flagged.threshold_version)


class TestAnOutageIsRecordedNotHidden(unittest.TestCase):
    def setUp(self):
        self.world, self.node, self.gateway, self.log = _run(outage_hours=10.0)

    def test_the_backlog_is_delivered_once_the_link_returns(self):
        self.assertEqual(self.node.buffered, 0)

    def test_observations_cover_the_outage_window(self):
        """Store-and-forward means the readings arrive late, not never."""
        hours = {o.measured_at.hour for o in self.gateway.state.observations}
        self.assertTrue({7, 10, 14}.issubset(hours))

    def test_the_state_still_validates(self):
        self.assertEqual(self.gateway.state.validate(), [])

    def test_late_readings_keep_their_true_measurement_time(self):
        """§2: ages stamped at transmit, so a buffered reading is not backdated to
        when it happened to arrive."""
        received = {o.received_at for o in self.gateway.state.observations}
        measured = {o.measured_at for o in self.gateway.state.observations}
        self.assertGreater(len(measured), len(received) // 2)


class TestDeterminism(unittest.TestCase):
    def test_two_identical_runs_produce_identical_readings(self):
        a = _run()[2].state
        b = _run()[2].state
        self.assertEqual([o.result for o in a.observations],
                         [o.result for o in b.observations])

    def test_a_dry_day_is_seed_independent_and_that_is_correct(self):
        """Rain is the climate's only stochastic input, so a short dry window is
        identical across seeds — temperature and ET are pure functions of time.
        Seed sensitivity is tested over a long enough window in
        `test_physics.py::TestDeterminism`, where rain actually occurs."""
        a = _run(seed=1)[2].state
        b = _run(seed=2)[2].state
        self.assertEqual([o.result for o in a.observations],
                         [o.result for o in b.observations])


if __name__ == "__main__":
    unittest.main(verbosity=2)
