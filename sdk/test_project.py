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
from model import Assertor, ClockQuality, QualityFlag, Usable

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
