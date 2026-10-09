#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Scored fault drills (docs/VIRTUAL_FARM.md step 6, spec v0.1 §9.2).

§9.2 wants detection *measured*, so these pin the measurements. Numbers are tolerant
where the physics makes them so and exact where the claim is categorical — a control
that flags nothing must flag nothing.
"""
from __future__ import annotations

import datetime as _dt
import unittest

import drill as D
import faults as F
import link as lk


class TestScoring(unittest.TestCase):
    """The arithmetic, before trusting any of the numbers it produces."""

    def _result(self, **kw):
        base = dict(fault="x", onset=_dt.datetime(2026, 7, 1, tzinfo=D.ph.UTC))
        base.update(kw)
        return D.DrillResult(**base)

    def test_precision_and_recall(self):
        r = self._result(true_positives=8, false_positives=2, false_negatives=4,
                         true_negatives=90)
        self.assertAlmostEqual(r.precision, 0.8)
        self.assertAlmostEqual(r.recall, 8 / 12)
        self.assertAlmostEqual(r.f1, 2 * 0.8 * (8 / 12) / (0.8 + 8 / 12))

    def test_false_alarm_rate_is_against_clean_readings_only(self):
        """The number that decides whether a farmer keeps trusting the flags."""
        r = self._result(true_positives=5, false_positives=3, true_negatives=97,
                         false_negatives=0)
        self.assertAlmostEqual(r.false_alarm_rate, 3 / 100)

    def test_an_empty_drill_does_not_divide_by_zero(self):
        r = self._result()
        self.assertEqual((r.precision, r.recall, r.f1, r.false_alarm_rate),
                         (0.0, 0.0, 0.0, 0.0))

    def test_latency_is_none_until_something_is_caught(self):
        r = self._result()
        self.assertFalse(r.caught)
        self.assertIsNone(r.latency_s)
        r = self._result(first_catch=r.onset + _dt.timedelta(hours=3))
        self.assertTrue(r.caught)
        self.assertAlmostEqual(r.latency_s, 10800.0)


class TestTheControl(unittest.TestCase):
    """The most important drill: nothing is wrong, so nothing may be flagged."""

    def test_a_clean_farm_raises_no_flags_at_all(self):
        result = D.drill(None, days=4.0, redundant=True)
        self.assertEqual(result.false_positives, 0,
                         "a default that fires on a working farm costs the "
                         "farmer's trust in every flag")
        self.assertEqual(result.flags_seen, set())
        self.assertEqual(result.false_alarm_rate, 0.0)
        self.assertGreater(result.readings, 300, "and it actually ran")

    def test_a_clean_farm_is_quiet_with_one_probe_too(self):
        result = D.drill(None, days=4.0, redundant=False)
        self.assertEqual(result.false_positives, 0)

    def test_a_clean_farm_is_quiet_over_a_lossy_link(self):
        """Packet loss is not a data-quality fault."""
        result = D.drill(None, days=4.0, link_profile=lk.MESHTASTIC)
        self.assertEqual(result.false_positives, 0)


class TestCatchableFaults(unittest.TestCase):
    def test_out_of_range_is_caught_immediately(self):
        result = D.drill(F.OutOfRange(value=4.2), days=4.0)
        self.assertEqual(result.recall, 1.0)
        self.assertEqual(result.precision, 1.0)
        self.assertIn("out_of_range", result.flags_seen)
        self.assertLess(result.latency_s, 3600.0)

    def test_a_stuck_probe_is_caught_but_not_quickly(self):
        """Latency is the number a farmer feels: a probe caught hours after it froze
        is caught, and those hours of decisions were made on fiction.

        It varies with *when* the fault begins, which the drill made visible: part
        of the identical run can precede the fault, because a healthy probe already
        repeats overnight when evapotranspiration is near zero (§4.2's quantisation
        dwell). A probe that freezes at dawn is caught sooner than one that freezes
        at midday, through no merit of the detector.
        """
        result = D.drill(F.Sticking(), days=4.0)
        self.assertGreater(result.recall, 0.6)
        self.assertEqual(result.precision, 1.0)
        self.assertIn("stuck", result.flags_seen)
        self.assertGreater(result.latency_s, 2 * 3600,
                           "it cannot fire the instant the value freezes")
        self.assertLess(result.latency_s, 20 * 3600,
                        "nor should it take a day")


class TestOneProbeIsBlindToThreeFaultModes(unittest.TestCase):
    """The drill's headline finding, measured rather than argued.

    A feature with a single sensor cannot detect drift or bias at all: every reading
    is individually plausible and the series looks healthy, so no check that looks at
    one series has anything to go on. Drift is the commonest real failure.

    Noise was in that list until Q23 (2026-10-08). The rate check could not see it;
    the shape checks can, because noise makes readings fall faster than soil drains
    and jump out and back. The class keeps its name because the measurement it records
    was true, and the test below says what changed.
    """

    BLIND = (F.Drifting(per_day=0.05), F.Biased(offset=0.08))
    HARD = BLIND + (F.Noisy(sigma=0.03, seed=5),)

    def test_alone_it_sees_neither_drift_nor_bias(self):
        for fault in self.BLIND:
            with self.subTest(fault.kind):
                result = D.drill(D._fresh(fault), days=4.0, redundant=False)
                self.assertEqual(result.recall, 0.0)
                self.assertEqual(result.flags_seen, set())

    def test_alone_it_now_sees_noise_by_its_shape(self):
        result = D.drill(D._fresh(F.Noisy(sigma=0.03, seed=5)), days=4.0, redundant=False)
        self.assertGreater(result.recall, 0.3)
        self.assertEqual(result.precision, 1.0)
        self.assertLessEqual(result.flags_seen, {"rate_exceeded", "suspect"})

    def test_a_redundant_probe_sees_all_three(self):
        for fault in self.HARD:
            with self.subTest(fault.kind):
                result = D.drill(D._fresh(fault), days=4.0, redundant=True)
                self.assertGreater(result.recall, 0.1)
                self.assertIn("suspect", result.flags_seen)

    def test_bias_is_the_starkest_case(self):
        alone = D.drill(F.Biased(offset=0.08), days=4.0, redundant=False)
        paired = D.drill(F.Biased(offset=0.08), days=4.0, redundant=True)
        self.assertEqual(alone.recall, 0.0)
        self.assertEqual(paired.recall, 1.0)

    def test_drift_takes_time_even_with_a_peer(self):
        """It has to exceed the cross-check tolerance first, which is why a slow
        drift is the hardest real failure."""
        result = D.drill(F.Drifting(per_day=0.05), days=4.0, redundant=True)
        self.assertGreater(result.latency_s, 6 * 3600)

    def test_the_cross_check_only_ever_says_suspect(self):
        """It cannot say which of two disagreeing probes is wrong, so calling
        either one bad would be a guess dressed as a measurement."""
        result = D.drill(F.Biased(offset=0.08), days=4.0, redundant=True)
        self.assertEqual(result.flags_seen, {"suspect"})


class TestFaultsThatShouldNotBeFlagged(unittest.TestCase):
    def test_a_dead_sensor_produces_no_flags_because_that_is_correct(self):
        """§4.2 makes absence a datastream state, not a reading flag. There are no
        readings to flag, and inventing some would be worse than silence."""
        result = D.drill(F.Dead(), days=4.0)
        self.assertEqual(result.flags_seen, set())
        self.assertEqual(result.false_positives, 0)


class TestDeterminism(unittest.TestCase):
    def test_a_drill_is_reproducible(self):
        a = D.drill(F.Sticking(), days=4.0, seed=3)
        b = D.drill(F.Sticking(), days=4.0, seed=3)
        self.assertEqual((a.recall, a.precision, a.latency_s),
                         (b.recall, b.precision, b.latency_s))

    def test_fresh_gives_each_drill_its_own_fault_state(self):
        """A Sticking fault remembers the value it froze, so reusing the instance
        would leak state between drills."""
        original = F.Sticking(begins_at_s=1.0)
        copy = D._fresh(original)
        self.assertIsNot(copy, original)
        self.assertEqual(copy.kind, original.kind)
        self.assertEqual(copy.begins_at_s, 0.0, "the drill sets the onset itself")


if __name__ == "__main__":
    unittest.main(verbosity=2)
