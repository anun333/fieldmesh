#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Health checks (spec v0.1 §4.2) and the assertion model they write into."""
from __future__ import annotations

import datetime as _dt
import unittest

import checks as C
import fixtures as fx
import log as L
import project as P
from model import Assertor, QualityFlag, Threshold, Usable
from ids import uuid7

UTC = _dt.timezone.utc


def _state(*records) -> P.State:
    lg = L.Log()
    for r in records:
        lg.append_record(r)
    return P.state_from_log(lg)


def _flags(assertion):
    return sorted(f.value for f in assertion.flags)


class TestThresholdResolution(unittest.TestCase):
    """§4.2: thresholds live on the datastream with sensible defaults."""

    def test_defaults_then_datastream_then_versioned_record(self):
        ds = fx.raw_datastream(thresholds={"max": 0.5, "flat_n": 4})
        self.assertEqual(C.thresholds_for(ds)["max"], 0.5)
        self.assertEqual(C.thresholds_for(ds)["flat_n"], 4)
        record = Threshold(id=uuid7(), datastream=ds.id, values={"max": 0.6})
        merged = C.thresholds_for(ds, record)
        self.assertEqual(merged["max"], 0.6, "the versioned record wins")
        self.assertEqual(merged["flat_n"], 4, "and does not erase the rest")

    def test_defaults_are_loose_enough_not_to_cry_wolf(self):
        """A default that fires often costs the farmer's trust in every flag."""
        self.assertIsNone(C.DEFAULTS["min"])
        self.assertIsNone(C.DEFAULTS["max"])
        self.assertIsNone(C.DEFAULTS["max_rate_per_s"])
        self.assertIsNone(C.DEFAULTS["cross_tolerance"])


class TestRange(unittest.TestCase):
    def setUp(self):
        self.ds = fx.raw_datastream(thresholds={"min": 0.0, "max": 0.55})

    def _assess(self, result):
        obs = fx.observation(self.ds, result=result)
        return C.assess(_state(self.ds, obs), obs)

    def test_above_saturation_is_out_of_range(self):
        a = self._assess(0.91)
        self.assertEqual(_flags(a), ["out_of_range"])
        self.assertEqual(a.usable, Usable.BAD)

    def test_below_the_floor_is_out_of_range(self):
        self.assertEqual(_flags(self._assess(-0.2)), ["out_of_range"])

    def test_inside_the_range_is_clean(self):
        self.assertEqual(_flags(self._assess(0.3)), [])

    def test_no_range_configured_means_no_opinion(self):
        ds = fx.raw_datastream()
        obs = fx.observation(ds, result=99999.0)
        self.assertEqual(_flags(C.assess(_state(ds, obs), obs)), [])

    def test_a_non_numeric_result_is_skipped_not_guessed_at(self):
        ds = fx.raw_datastream(thresholds={"max": 0.5})
        obs = fx.observation(ds, result="dry")
        self.assertEqual(_flags(C.assess(_state(ds, obs), obs)), [])


class TestFlatline(unittest.TestCase):
    def _series(self, values, flat_n=4):
        ds = fx.raw_datastream(thresholds={"flat_n": flat_n})
        obs = [fx.observation(ds, result=v, measured_at=fx.at(i), seq=i)
               for i, v in enumerate(values)]
        return ds, obs, _state(ds, *obs)

    def test_a_long_run_of_identical_values_is_stuck(self):
        ds, obs, state = self._series([0.3] * 6)
        self.assertEqual(_flags(C.assess(state, obs[-1])), ["stuck"])

    def test_a_short_run_is_not(self):
        ds, obs, state = self._series([0.3] * 3)
        self.assertEqual(_flags(C.assess(state, obs[-1])), [])

    def test_the_run_only_counts_back_to_the_last_change(self):
        ds, obs, state = self._series([0.3] * 5 + [0.4, 0.4])
        self.assertEqual(_flags(C.assess(state, obs[-1])), [],
                         "a fresh value resets the run")

    def test_the_threshold_is_the_boundary(self):
        ds, obs, state = self._series([0.3] * 5, flat_n=4)
        self.assertEqual(_flags(C.assess(state, obs[4])), ["stuck"])
        self.assertEqual(_flags(C.assess(state, obs[3])), [])


class TestRateOfChange(unittest.TestCase):
    def _pair(self, a, b, minutes_apart, limit):
        ds = fx.raw_datastream(thresholds={"max_rate_per_s": limit})
        first = fx.observation(ds, result=a, measured_at=fx.at(0), seq=0)
        second = fx.observation(ds, result=b, measured_at=fx.at(minutes_apart),
                                seq=1)
        return ds, second, _state(ds, first, second)

    def test_an_impossible_jump_is_flagged(self):
        ds, obs, state = self._pair(0.30, 0.90, 1, limit=0.001)
        a = C.assess(state, obs)
        self.assertEqual(_flags(a), ["rate_exceeded"])
        self.assertEqual(a.usable, Usable.QUESTIONABLE,
                         "a fast change is suspicious, not proof of a dead probe")

    def test_a_plausible_change_is_not(self):
        ds, obs, state = self._pair(0.30, 0.31, 60, limit=0.001)
        self.assertEqual(_flags(C.assess(state, obs)), [])

    def test_a_longer_gap_permits_a_larger_change(self):
        """Three hours of absence genuinely allows more change than three minutes."""
        _, close, state_close = self._pair(0.30, 0.50, 2, limit=0.0005)
        self.assertEqual(_flags(C.assess(state_close, close)), ["rate_exceeded"])
        _, far, state_far = self._pair(0.30, 0.50, 600, limit=0.0005)
        self.assertEqual(_flags(C.assess(state_far, far)), [])

    def test_the_first_reading_in_a_series_has_nothing_to_compare_to(self):
        ds = fx.raw_datastream(thresholds={"max_rate_per_s": 0.0000001})
        obs = fx.observation(ds, result=0.3)
        self.assertEqual(_flags(C.assess(_state(ds, obs), obs)), [])


class TestCrossCheck(unittest.TestCase):
    """§4.2 Cross-check → `suspect` only, because it cannot say which probe lies."""

    def _two_probes(self, a, b, *, same_feature=True, same_sensor=False,
                    minutes_apart=0, tolerance=0.05):
        feature = uuid7()
        one = fx.raw_datastream(feature=feature,
                                thresholds={"cross_tolerance": tolerance})
        two = fx.raw_datastream(
            feature=feature if same_feature else uuid7(),
            sensor=one.sensor if same_sensor else None,
            thresholds={"cross_tolerance": tolerance})
        mine = fx.observation(one, result=a, measured_at=fx.at(0))
        theirs = fx.observation(two, result=b, measured_at=fx.at(minutes_apart))
        return mine, _state(one, two, mine, theirs)

    def test_disagreement_is_suspect_never_bad(self):
        mine, state = self._two_probes(0.30, 0.50)
        a = C.assess(state, mine)
        self.assertEqual(_flags(a), ["suspect"])
        self.assertEqual(a.usable, Usable.QUESTIONABLE,
                         "calling either probe bad would be a guess dressed as "
                         "a measurement")

    def test_agreement_is_clean(self):
        mine, state = self._two_probes(0.30, 0.32)
        self.assertEqual(_flags(C.assess(state, mine)), [])

    def test_a_different_feature_is_not_a_peer(self):
        mine, state = self._two_probes(0.30, 0.90, same_feature=False)
        self.assertEqual(_flags(C.assess(state, mine)), [])

    def test_the_same_sensor_is_not_redundancy(self):
        mine, state = self._two_probes(0.30, 0.90, same_sensor=True)
        self.assertEqual(_flags(C.assess(state, mine)), [])

    def test_readings_far_apart_in_time_are_not_comparable(self):
        mine, state = self._two_probes(0.30, 0.90, minutes_apart=600)
        self.assertEqual(_flags(C.assess(state, mine)), [])


class TestOneAssertionPerRun(unittest.TestCase):
    """The resolution of the §3.3/§4.2 ambiguity.

    §4.2 lists four checks producing one flag each; §3.3 makes `flags` a set and
    has precedence pick exactly one live assertion. One assertion per run,
    carrying the union, is the only coherent reading.
    """

    def setUp(self):
        self.ds = fx.raw_datastream(thresholds={"max": 0.55, "flat_n": 3})
        self.obs = [fx.observation(self.ds, result=0.91, measured_at=fx.at(i),
                                   seq=i) for i in range(4)]
        self.state = _state(self.ds, *self.obs)

    def test_two_checks_firing_produce_one_assertion_with_both_flags(self):
        a = C.assess(self.state, self.obs[-1])
        self.assertEqual(_flags(a), ["out_of_range", "stuck"])
        self.assertEqual(a.usable, Usable.BAD)
        self.assertEqual(a.check, C.SUITE)

    def test_separate_assertions_per_check_would_lose_a_flag(self):
        """Why the suite model is necessary, demonstrated rather than asserted."""
        stuck_only = fx.assertion(self.obs[-1].id, flags={QualityFlag.STUCK},
                                  check="flatline", asserted_at=fx.at(10))
        range_only = fx.assertion(self.obs[-1].id,
                                  flags={QualityFlag.OUT_OF_RANGE},
                                  check="range", asserted_at=fx.at(11))
        winner = P.live_assertion([stuck_only, range_only], self.obs[-1].id)
        self.assertEqual(len(winner.flags), 1,
                         "precedence picks one, so the other check's finding "
                         "silently disappears")

    def test_evidence_records_which_checks_fired_and_why(self):
        a = C.assess(self.state, self.obs[-1])
        self.assertEqual(set(a.evidence["fired"]), {"range", "flatline"})
        self.assertIn("above max", a.evidence["fired"]["range"])
        self.assertIn("flatline", a.evidence["checks_run"])
        self.assertEqual(a.evidence["thresholds"]["max"], 0.55)

    def test_evidence_records_checks_that_ran_and_stayed_quiet(self):
        clean = fx.observation(self.ds, result=0.3, measured_at=fx.at(99), seq=99)
        a = C.assess(_state(self.ds, clean), clean)
        self.assertEqual(a.evidence["fired"], {})
        self.assertEqual(len(a.evidence["checks_run"]), 4)

    def test_a_clean_assessment_still_produces_an_assertion(self):
        """"Checked, no objection" is not the same as never having looked."""
        clean = fx.observation(self.ds, result=0.3, measured_at=fx.at(99), seq=99)
        a = C.assess(_state(self.ds, clean), clean)
        self.assertEqual(a.flags, frozenset())
        self.assertEqual(a.usable, Usable.GOOD)

    def test_the_threshold_version_is_stamped(self):
        th = fx.threshold(self.ds, max=0.55, flat_n=3)
        a = C.assess(self.state, self.obs[-1], threshold=th)
        self.assertEqual(a.threshold_version, th.id)


class TestReassessment(unittest.TestCase):
    """§3.3 — a retune appends and supersedes; it never rewrites."""

    def setUp(self):
        self.ds = fx.raw_datastream()
        self.obs = [fx.observation(self.ds, result=0.31, measured_at=fx.at(i),
                                   seq=i) for i in range(6)]

    def test_a_routine_pass_is_idempotent(self):
        strict = fx.threshold(self.ds, flat_n=3)
        state = _state(self.ds, strict, *self.obs)
        first = C.assess_series(state, self.ds.id, threshold=strict)
        self.assertEqual(len(first), 6)
        state2 = _state(self.ds, strict, *self.obs, *first)
        self.assertEqual(C.assess_series(state2, self.ds.id, threshold=strict), [],
                         "already-assessed observations are skipped")

    def test_a_retune_supersedes_and_the_old_verdict_survives(self):
        strict = fx.threshold(self.ds, flat_n=3)
        state = _state(self.ds, strict, *self.obs)
        old = C.assess_series(state, self.ds.id, threshold=strict,
                              asserted_at=fx.at(10))
        flagged = [a for a in old if QualityFlag.STUCK in a.flags]
        self.assertTrue(flagged, "the strict threshold should flag the flatline")

        loose = fx.threshold(self.ds, flat_n=50)
        state2 = _state(self.ds, strict, loose, *self.obs, *old)
        new = C.assess_series(state2, self.ds.id, threshold=loose,
                              asserted_at=fx.at(20), reassess=True)
        state3 = _state(self.ds, strict, loose, *self.obs, *old, *new)

        for obs in self.obs:
            self.assertEqual(state3.usable_of(obs.id), Usable.GOOD)
        survivor = flagged[0]
        self.assertIn(survivor, state3.assertions)
        self.assertEqual(survivor.threshold_version, strict.id,
                         "a false alarm stays traceable to the threshold that "
                         "caused it")

    def test_a_machine_pass_never_overrides_a_persons_judgement(self):
        """§3.3: a person outranks the foundation, so the suite must not supersede
        them even when re-assessing."""
        human = fx.assertion(self.obs[0].id, flags=set(), usable=Usable.BAD,
                             assertor=Assertor.PERSON, assertor_id=uuid7(),
                             check="manual-review",
                             note="probe was out of the ground")
        state2 = _state(self.ds, *self.obs, human)
        produced = C.assess_series(state2, self.ds.id, reassess=True)
        self.assertNotIn(self.obs[0].id, {a.observation for a in produced})
        state3 = _state(self.ds, *self.obs, human, *produced)
        self.assertEqual(state3.usable_of(self.obs[0].id), Usable.BAD)


class TestNothingIsMutated(unittest.TestCase):
    def test_assessment_leaves_the_observations_untouched(self):
        ds = fx.raw_datastream(thresholds={"max": 0.1})
        obs = fx.observation(ds, result=0.9)
        state = _state(ds, obs)
        before = (obs.result, obs.id, obs.measured_at)
        C.assess(state, obs)
        self.assertEqual((obs.result, obs.id, obs.measured_at), before)

    def test_staleness_is_not_among_the_checks(self):
        """§4.2 makes it a datastream state; project.datastream_health owns it."""
        names = {c.__name__ for c in C.DEFAULT_CHECKS}
        self.assertNotIn("check_staleness", names)
        self.assertNotIn("check_stale", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
