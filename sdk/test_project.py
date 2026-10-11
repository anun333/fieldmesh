#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Derived state, and the invariants the spec exists to protect.

Each class here corresponds to a clause that v0 got wrong and v0.1 fixed, so these
are the regression tests for the review itself — not just for the code.
"""
from __future__ import annotations

import datetime as _dt
import unittest

import fixtures as fx
import log as L
import project as P
from ids import uuid7
from model import Assertor, Calibration, ClockQuality, QualityFlag, Usable

UTC = _dt.timezone.utc


class TestSupersessionChains(unittest.TestCase):
    def test_only_the_tip_of_a_chain_is_live(self):
        raw = fx.raw_datastream()
        a = fx.observation(raw)
        b = fx.observation(raw, supersedes=a.id)
        c = fx.observation(raw, supersedes=b.id)
        self.assertEqual(P.live([a, b, c]), [c])

    def test_nothing_superseded_means_everything_is_live(self):
        raw = fx.raw_datastream()
        obs = [fx.observation(raw, seq=n, measured_at=fx.at(n)) for n in range(3)]
        self.assertEqual(len(P.live(obs)), 3)


class TestRecalibration(unittest.TestCase):
    """§3.2 — the clause that keeps the SensorThings promise alive past the first
    recalibration, which is the most ordinary maintenance event there is."""

    def setUp(self):
        self.raw = fx.raw_datastream()
        self.derived = fx.derived_datastream(self.raw)
        self.c1, self.c2 = uuid7(), uuid7()
        self.first = fx.observation(self.derived, result=0.30, calibration=self.c1)
        self.redone = fx.observation(self.derived, result=0.28,
                                     calibration=self.c2, supersedes=self.first.id)

    def test_exactly_one_live_row_per_timestamp(self):
        live = P.live_observations([self.first, self.redone])
        self.assertEqual(len(live), 1)
        self.assertEqual(live[(self.derived.id, fx.T0)].calibration, self.c2)

    def test_the_superseded_row_is_still_in_the_history(self):
        history = [self.first, self.redone]
        self.assertIn(self.first, history)
        self.assertEqual(self.first.result, 0.30, "the original is never altered")

    def test_two_live_rows_at_one_timestamp_is_the_v0_bug_and_is_refused(self):
        """Without `supersedes` this is exactly what v0 produced: two observations
        at one phenomenonTime, which doubles every SensorThings client's data."""
        orphan = fx.observation(self.derived, result=0.28, calibration=self.c2)
        with self.assertRaisesRegex(P.ProjectionError, "two live observations"):
            P.live_observations([self.first, orphan])

    def test_non_strict_mode_is_at_least_deterministic(self):
        orphan = fx.observation(self.derived, result=0.28, calibration=self.c2)
        pair = [self.first, orphan]
        a = P.live_observations(pair, strict=False)
        b = P.live_observations(list(reversed(pair)), strict=False)
        self.assertEqual(a, b)

    def test_raw_is_never_superseded_so_it_stays_archival(self):
        raw_obs = fx.observation(self.raw, result=512)
        raw_obs.validate_against(self.raw)
        self.assertEqual(P.live([raw_obs]), [raw_obs])


class TestCalibrationSelection(unittest.TestCase):
    """§3.2 — selected by `measured_at`, never by ingest time."""

    def setUp(self):
        self.sensor = uuid7()
        self.spring = fx.calibration(self.sensor, a=1.00,
                                     valid_from=_dt.datetime(2026, 3, 1, tzinfo=UTC),
                                     valid_to=_dt.datetime(2026, 6, 1, tzinfo=UTC))
        self.summer = fx.calibration(self.sensor, a=1.07,
                                     valid_from=_dt.datetime(2026, 6, 1, tzinfo=UTC))
        self.cals = [self.spring, self.summer]

    def test_a_backfilled_reading_gets_the_calibration_in_force_when_taken(self):
        """The failure this prevents: a reading that sat in a node's buffer for
        days, then got whatever coefficients happened to be current at ingest."""
        measured = _dt.datetime(2026, 5, 30, tzinfo=UTC)
        chosen = P.calibration_for(self.cals, self.sensor, measured)
        self.assertEqual(chosen, self.spring)
        self.assertNotEqual(chosen, self.summer,
                            "ingest-time selection would silently pick summer")

    def test_a_current_reading_gets_the_current_calibration(self):
        measured = _dt.datetime(2026, 6, 2, tzinfo=UTC)
        self.assertEqual(P.calibration_for(self.cals, self.sensor, measured),
                         self.summer)

    def test_the_boundary_belongs_to_the_later_calibration(self):
        boundary = _dt.datetime(2026, 6, 1, tzinfo=UTC)
        self.assertEqual(P.calibration_for(self.cals, self.sensor, boundary),
                         self.summer)

    def test_before_any_calibration_there_is_none(self):
        early = _dt.datetime(2026, 1, 1, tzinfo=UTC)
        self.assertIsNone(P.calibration_for(self.cals, self.sensor, early))

    def test_another_sensors_calibration_is_not_borrowed(self):
        self.assertIsNone(P.calibration_for(self.cals, uuid7(),
                                            _dt.datetime(2026, 6, 2, tzinfo=UTC)))

    def test_overlaps_are_reported_not_resolved_quietly(self):
        sloppy = fx.calibration(self.sensor, a=0.9,
                                valid_from=_dt.datetime(2026, 4, 1, tzinfo=UTC),
                                valid_to=_dt.datetime(2026, 7, 1, tzinfo=UTC))
        clashes = P.overlapping_calibrations(self.cals + [sloppy], self.sensor)
        self.assertTrue(clashes)


class TestCalibrationApplication(unittest.TestCase):
    """§3.2: reproducible from raw value, calibration and driver version."""

    @staticmethod
    def _cal(method="linear", **coefficients):
        return Calibration(id=uuid7(), sensor=uuid7(), method=method,
                           valid_from=fx.at(-60), coefficients=coefficients)

    def test_linear_scaling(self):
        self.assertAlmostEqual(P.apply_calibration(231, self._cal(a=0.001)), 0.231)

    def test_an_offset_is_applied(self):
        self.assertAlmostEqual(
            P.apply_calibration(231, self._cal(a=0.001, b=-0.01)), 0.221)

    def test_identity_passes_the_value_through(self):
        cal = fx.calibration(uuid7(), method="identity")
        self.assertEqual(P.apply_calibration(231, cal), 231)

    def test_a_polynomial(self):
        cal = self._cal("polynomial", c=[0.0, 0.001, 0.0000001])
        self.assertAlmostEqual(P.apply_calibration(100, cal), 0.1 + 0.001)

    def test_an_unknown_method_raises_rather_than_passing_through(self):
        """A silent passthrough would put an uncalibrated number in a calibrated
        series, which is the silent cleaning the spec exists to prevent."""
        cal = fx.calibration(uuid7(), method="sorcery")
        with self.assertRaisesRegex(P.CalibrationError, "unknown method"):
            P.apply_calibration(231, cal)

    def test_a_missing_coefficient_raises(self):
        with self.assertRaisesRegex(P.CalibrationError, "coefficient"):
            P.apply_calibration(231, self._cal(b=1.0))

    def test_declared_decimals_refuse_precision_the_probe_lacks(self):
        """0.001 * 86 is exactly 0.08600000000000001 in IEEE 754 — correct, and a
        claim of seventeen significant figures no probe can support."""
        noisy = P.apply_calibration(86, self._cal(a=0.001))
        self.assertNotEqual(noisy, 0.086)
        clean = P.apply_calibration(86, self._cal(a=0.001, decimals=3))
        self.assertEqual(clean, 0.086)

    def test_rounding_is_part_of_the_calibration_so_it_stays_reproducible(self):
        cal = self._cal(a=0.001, decimals=3)
        self.assertEqual(P.apply_calibration(86, cal),
                         P.apply_calibration(86, cal))

    def test_a_bad_decimals_declaration_is_refused(self):
        with self.assertRaises(P.CalibrationError):
            P.apply_calibration(86, self._cal(a=0.001, decimals="three"))
        with self.assertRaises(P.CalibrationError):
            P.apply_calibration(86, self._cal(a=0.001, decimals=-1))


class TestQualityPrecedence(unittest.TestCase):
    """§3.3 — the rule that makes two implementations agree."""

    def setUp(self):
        self.obs = uuid7()

    def test_no_assertion_means_no_objection(self):
        self.assertEqual(P.usable_of([], self.obs), Usable.GOOD)

    def test_a_person_outranks_the_foundation(self):
        machine = fx.assertion(self.obs, flags={QualityFlag.STUCK})
        person = fx.assertion(self.obs, flags={QualityFlag.STUCK},
                              usable=Usable.GOOD, assertor=Assertor.PERSON,
                              assertor_id=uuid7(), check="manual-review",
                              asserted_at=fx.at(-60))
        self.assertEqual(P.usable_of([machine, person], self.obs), Usable.GOOD)
        self.assertEqual(P.live_assertion([machine, person], self.obs), person,
                         "even an older person assertion outranks the machine")
        self.assertIn(machine, [machine, person],
                      "the machine's original stays visible (§3.3)")

    def test_ties_break_by_asserted_at_then_id(self):
        older = fx.assertion(self.obs, flags={QualityFlag.SUSPECT},
                             asserted_at=fx.at(0))
        newer = fx.assertion(self.obs, flags=set(), asserted_at=fx.at(5))
        self.assertEqual(P.live_assertion([older, newer], self.obs), newer)

    def test_id_breaks_a_full_tie_deterministically(self):
        a = fx.assertion(self.obs, flags=set(), asserted_at=fx.at(0))
        b = fx.assertion(self.obs, flags=set(), asserted_at=fx.at(0))
        winner = max([a, b], key=lambda x: x.id.int)
        self.assertEqual(P.live_assertion([a, b], self.obs), winner)
        self.assertEqual(P.live_assertion([b, a], self.obs), winner)

    def test_quality_as_of_knows_only_what_had_been_asserted(self):
        """A decision made at a moment could only know the verdicts made by then: a
        later override does not reach back, and a reassessment that superseded the
        verdict only later leaves it live until then."""
        ds = fx.raw_datastream()
        obs = fx.observation(ds)
        state = P.State()
        for rec in (ds, obs):
            state.add(rec)
        machine = fx.assertion(obs.id, flags={QualityFlag.STUCK}, asserted_at=fx.at(0))
        reassessed = fx.assertion(obs.id, flags=set(), supersedes=machine.id,
                                  asserted_at=fx.at(30))
        person = fx.assertion(obs.id, flags={QualityFlag.STUCK}, usable=Usable.BAD,
                              assertor=Assertor.PERSON, assertor_id=uuid7(),
                              check="manual-review", asserted_at=fx.at(60))
        for a in (machine, reassessed, person):
            state.add(a)
        self.assertEqual(state.quality_as_of(obs.id, fx.at(-1)), (Usable.GOOD, frozenset()))
        self.assertEqual(state.quality_as_of(obs.id, fx.at(10)),
                         (Usable.BAD, frozenset({QualityFlag.STUCK})))
        self.assertEqual(state.quality_as_of(obs.id, fx.at(40)), (Usable.GOOD, frozenset()))
        self.assertEqual(state.quality_as_of(obs.id, fx.at(70))[0], Usable.BAD)

    def test_a_superseded_assertion_does_not_win(self):
        old = fx.assertion(self.obs, flags={QualityFlag.STUCK})
        new = fx.assertion(self.obs, flags=set(), supersedes=old.id,
                           asserted_at=fx.at(10))
        self.assertEqual(P.live_assertion([old, new], self.obs), new)
        self.assertEqual(P.usable_of([old, new], self.obs), Usable.GOOD)

    def test_assertions_about_other_observations_are_ignored(self):
        mine = fx.assertion(self.obs, flags=set())
        theirs = fx.assertion(uuid7(), flags={QualityFlag.STUCK})
        self.assertEqual(P.usable_of([mine, theirs], self.obs), Usable.GOOD)


class TestThresholdRetuning(unittest.TestCase):
    """§3.3 — retuning a threshold must not re-flag or erase history."""

    def test_history_keeps_the_threshold_version_that_produced_it(self):
        ds = fx.raw_datastream()
        obs = fx.observation(ds)
        v1 = fx.threshold(ds, flat_n=6)
        v2 = fx.threshold(ds, flat_n=24)

        was_flagged = fx.assertion(obs.id, flags={QualityFlag.STUCK},
                                   threshold_version=v1.id, asserted_at=fx.at(0))
        after_retune = fx.assertion(obs.id, flags=set(), threshold_version=v2.id,
                                    supersedes=was_flagged.id, asserted_at=fx.at(10))
        history = [was_flagged, after_retune]

        self.assertEqual(P.usable_of(history, obs.id), Usable.GOOD)
        self.assertEqual(was_flagged.threshold_version, v1.id)
        self.assertEqual(was_flagged.flags, frozenset({QualityFlag.STUCK}),
                         "the old assertion is unchanged, so a false alarm stays "
                         "traceable to the threshold that caused it")


class TestOrdering(unittest.TestCase):
    """§2 — a node's counter beats its clock; overlapping uncertainty is unordered."""

    def test_within_one_node_boot_and_seq_beat_a_skewed_clock(self):
        ds = fx.raw_datastream()
        earlier_seq = fx.observation(ds, node="!bed01", boot=1, seq=5,
                                     measured_at=fx.at(10),
                                     clock_quality=ClockQuality.RTC_UNSYNCED)
        later_seq = fx.observation(ds, node="!bed01", boot=1, seq=6,
                                   measured_at=fx.at(0),      # clock disagrees
                                   clock_quality=ClockQuality.RTC_UNSYNCED)
        self.assertTrue(P.precedes(earlier_seq, later_seq))
        self.assertFalse(P.precedes(later_seq, earlier_seq))

    def test_a_reboot_orders_after_the_previous_boot(self):
        ds = fx.raw_datastream()
        before_reboot = fx.observation(ds, node="!bed01", boot=1, seq=900)
        after_reboot = fx.observation(ds, node="!bed01", boot=2, seq=0)
        self.assertTrue(P.precedes(before_reboot, after_reboot),
                        "a seq that reset to 0 is not earlier — boot says otherwise")

    def test_across_nodes_confident_clocks_order_normally(self):
        ds = fx.raw_datastream()
        a = fx.observation(ds, node="!bed01", measured_at=fx.at(0), uncertainty=1)
        b = fx.observation(ds, node="!bed02", measured_at=fx.at(10), uncertainty=1)
        self.assertTrue(P.precedes(a, b))
        self.assertFalse(P.concurrent(a, b))

    def test_overlapping_uncertainty_is_honestly_unordered(self):
        """A clockless node's reading cannot be ordered against a GPS one when
        their windows overlap, and pretending otherwise is the dishonesty §2
        exists to prevent."""
        ds = fx.raw_datastream()
        gps = fx.observation(ds, node="!bed01", measured_at=fx.at(0),
                             uncertainty=1, clock_quality=ClockQuality.GPS)
        guessed = fx.observation(ds, node="!bed02", measured_at=fx.at(2),
                                 uncertainty=600, clock_quality=ClockQuality.NONE)
        self.assertTrue(P.concurrent(gps, guessed))
        self.assertFalse(P.precedes(gps, guessed))
        self.assertFalse(P.precedes(guessed, gps))

    def test_order_observations_is_deterministic_either_way_in(self):
        ds = fx.raw_datastream()
        obs = [fx.observation(ds, node="!bed01", boot=1, seq=n,
                              measured_at=fx.at(n)) for n in range(6)]
        self.assertEqual(P.order_observations(obs),
                         P.order_observations(list(reversed(obs))))


class TestStaleness(unittest.TestCase):
    """§4.2 — a datastream state, never a flag on a reading."""

    def setUp(self):
        self.ds = fx.raw_datastream(expected_interval=300.0)

    def test_fresh_is_ok(self):
        self.assertEqual(
            P.datastream_health(self.ds, fx.T0, fx.T0 + _dt.timedelta(seconds=300)),
            P.Health.OK)

    def test_the_boundary_is_three_intervals(self):
        self.assertEqual(
            P.datastream_health(self.ds, fx.T0, fx.T0 + _dt.timedelta(seconds=900)),
            P.Health.OK)
        self.assertEqual(
            P.datastream_health(self.ds, fx.T0, fx.T0 + _dt.timedelta(seconds=901)),
            P.Health.STALE)

    def test_unknown_without_an_expected_interval(self):
        ds = fx.raw_datastream(expected_interval=None)
        self.assertEqual(P.datastream_health(ds, fx.T0, fx.at(10_000)),
                         P.Health.UNKNOWN)

    def test_unknown_before_the_first_reading(self):
        self.assertEqual(P.datastream_health(self.ds, None, fx.T0),
                         P.Health.UNKNOWN)


class TestStateFromLog(unittest.TestCase):
    """§7.1 — current state is derived from the log."""

    def _seeded(self):
        lg = L.Log()
        raw = fx.raw_datastream()
        derived = fx.derived_datastream(raw)
        lg.append_record(raw)
        lg.append_record(derived)
        cal = fx.calibration(raw.sensor)
        lg.append_record(cal)
        first = fx.observation(derived, result=0.30, calibration=cal.id)
        lg.append_record(first)
        lg.append_record(fx.observation(derived, result=0.28, calibration=cal.id,
                                        supersedes=first.id))
        return lg, raw, derived, first

    def test_state_is_rebuilt_from_events_alone(self):
        lg, raw, derived, first = self._seeded()
        st = P.state_from_log(lg)
        self.assertEqual(set(st.datastreams), {raw.id, derived.id})
        self.assertEqual(len(st.observations), 2, "history keeps both rows")
        self.assertEqual(len(st.live_observations()), 1, "one is live")
        self.assertEqual(st.validate(), [])

    def test_the_superseded_row_remains_inspectable(self):
        lg, _, _, first = self._seeded()
        st = P.state_from_log(lg)
        self.assertIn(first, st.observations)
        self.assertNotIn(first, st.live_observations().values())

    def test_a_later_version_of_a_keyed_record_replaces_it(self):
        lg = L.Log()
        raw = fx.raw_datastream()
        lg.append_record(raw)
        import dataclasses
        renamed = dataclasses.replace(raw, thresholds={"max": 0.55})
        lg.append_record(renamed)
        st = P.state_from_log(lg)
        self.assertEqual(st.datastreams[raw.id].thresholds, {"max": 0.55})

    def test_validate_reports_an_observation_with_no_datastream(self):
        lg = L.Log()
        lg.append_record(fx.observation(fx.raw_datastream()))
        problems = P.state_from_log(lg).validate()
        self.assertTrue(any("unknown datastream" in p for p in problems))

    def test_validate_reports_a_derived_stream_with_no_source(self):
        lg = L.Log()
        raw = fx.raw_datastream()
        lg.append_record(fx.derived_datastream(raw))      # source never logged
        problems = P.state_from_log(lg).validate()
        self.assertTrue(any("derives from unknown" in p for p in problems))

    def test_validate_reports_a_raw_observation_carrying_calibration(self):
        lg = L.Log()
        raw = fx.raw_datastream()
        lg.append_record(raw)
        lg.append_record(fx.observation(raw, calibration=uuid7()))
        problems = P.state_from_log(lg).validate()
        self.assertTrue(any("carries no calibration" in p for p in problems))

    def test_health_comes_off_the_derived_state(self):
        lg, raw, derived, _ = self._seeded()
        st = P.state_from_log(lg)
        self.assertEqual(st.health_of(derived.id, fx.at(5)), P.Health.OK)
        self.assertEqual(st.health_of(derived.id, fx.at(60)), P.Health.STALE)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestOrderedWindow(unittest.TestCase):
    """A check sees a reading's real predecessors, even when it arrives days late."""

    def setUp(self):
        import checks as C
        self.C = C
        self.ds = fx.raw_datastream(thresholds={"max_rate_per_s": 0.0001})
        self.log = L.Log()
        self.log.append_record(self.ds)
        # Two hours at 0.20, then three days of later readings that arrive *first* —
        # what a fresh-first drain does after an outage: newest readings out, then the
        # backlog. Three days is more than the checks' lookback of 112 readings, which
        # is what makes the difference; with one day the old code still coped.
        for i in range(8):
            self.log.append_record(fx.observation(
                self.ds, result=0.20, measured_at=fx.at(15 * i), node="n1",
                boot=0, seq=i))
        for i in range(8, 8 + 288):
            self.log.append_record(fx.observation(
                self.ds, result=0.30, measured_at=fx.at(15 * i), node="n1",
                boot=0, seq=i))
        # Then, after an outage, a buffered reading from the morning drains: a spike
        # to 0.45 just after the 0.20 run. Its true predecessor is 0.20, 7.5 min earlier.
        self.late = fx.observation(self.ds, result=0.45,
                                   measured_at=fx.at(15 * 7 + 7.5), node="n1",
                                   boot=0, seq=7)
        self.log.append_record(self.late)
        self.state = P.state_from_log(self.log)

    def test_the_window_ends_at_the_reading_and_holds_its_real_history(self):
        window = self.state.ordered_upto(self.ds.id, self.late, 5)
        self.assertEqual(window[-1].id, self.late.id)
        self.assertEqual([o.result for o in window[:-1]], [0.20] * 4)

    def test_a_late_spike_is_judged_against_its_true_predecessor(self):
        """Measured against the previous commit, not asserted: the old way took the last
        112 readings *inserted* — all of them measured after the spike — sorted them,
        and found the spike first in the list with no predecessor, so the rate check had
        nothing to compare and fired nothing. The window ending at the spike's own
        position finds the 0.20 reading 7.5 minutes before it."""
        assertion = self.C.assess(self.state, self.late)
        self.assertIn("rate", assertion.evidence["fired"])

    def test_superseded_rows_are_left_out_of_the_window(self):
        derived = fx.derived_datastream(raw=self.ds)
        cal = fx.calibration(sensor=self.ds.sensor)
        log = L.Log()
        for record in (self.ds, derived, cal):
            log.append_record(record)
        first = fx.observation(derived, result=0.2, measured_at=fx.at(0),
                               calibration=cal.id)
        log.append_record(first)
        replaced = fx.observation(derived, result=0.21, measured_at=fx.at(0),
                                  calibration=cal.id, supersedes=first.id)
        later = fx.observation(derived, result=0.22, measured_at=fx.at(15),
                               calibration=cal.id)
        for record in (replaced, later):
            log.append_record(record)
        state = P.state_from_log(log)
        window = state.ordered_upto(derived.id, later, 10)
        self.assertNotIn(first.id, {o.id for o in window})
        self.assertIn(replaced.id, {o.id for o in window})
