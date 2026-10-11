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
from model import (Assertor, MaintenanceAction, MaintenanceEvent, QualityFlag,
                   Threshold, Usable, evidence_problems)
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


class TestClearSky(unittest.TestCase):
    """More sunshine than a clear sky gives at the site and hour (`checks.clear_sky`)."""

    SITE = {"clear_sky_lat": 36.01, "clear_sky_lon": -85.13, "clear_sky_elevation_m": 583.0}

    def _assess(self, result, when, **thresholds):
        import vocab as V
        ds = fx.raw_datastream(unit="W/m2", observed_property=V.SOLAR_RADIATION,
                               thresholds={**self.SITE, **thresholds})
        obs = fx.observation(ds, result=result, measured_at=when)
        return C.assess(_state(ds, obs), obs)

    def test_the_sun_module_gives_fao_56s_example_8(self):
        """Example 8: on 3 September at 20 degrees south, Ra = 32.2 MJ m-2 a day."""
        import sun
        day = _dt.datetime(2026, 9, 3, tzinfo=UTC)
        mj = sum(sun.extraterrestrial_w(-20.0, 0.0, day + _dt.timedelta(minutes=m + 0.5))
                 for m in range(24 * 60)) * 60.0 / 1e6
        self.assertAlmostEqual(mj, 32.2, delta=0.15)

    def test_sunshine_at_night_is_out_of_range(self):
        """At Crossville, 06:00 UTC is midnight: a station whose clock is in the wrong zone
        shows the afternoon's sun then."""
        a = self._assess(450.0, _dt.datetime(2024, 6, 21, 6, 0, tzinfo=UTC))
        self.assertEqual(_flags(a), ["out_of_range"])
        self.assertIn("clear_sky", a.evidence["checks_run"])
        self.assertEqual(a.evidence["messages"]["clear_sky"]["key"], "check.clear_sky.above")

    def test_a_bright_noon_is_clean_and_lux_sent_as_watts_is_not(self):
        noon = _dt.datetime(2024, 6, 21, 18, 0, tzinfo=UTC)
        self.assertEqual(_flags(self._assess(980.0, noon)), [])
        self.assertEqual(_flags(self._assess(98000.0, noon)), ["out_of_range"])

    def test_an_hourly_mean_is_held_to_the_hours_mean_sky(self):
        """At 11:00 UTC on 21 June the sun has just risen at Crossville: a clear sky gives
        98 W/m2 at that moment but 25 on average over the hour before it. So 100 W/m2 is
        a plausible moment and an impossible hour's mean."""
        when = _dt.datetime(2024, 6, 21, 11, 0, tzinfo=UTC)
        self.assertEqual(_flags(self._assess(100.0, when, clear_sky_factor=1.25)), [])
        self.assertEqual(_flags(self._assess(100.0, when, clear_sky_window_s=3600.0,
                                             clear_sky_factor=1.25)), ["out_of_range"])

    def test_it_runs_only_on_sunshine_with_its_site_given(self):
        night = _dt.datetime(2024, 6, 21, 6, 0, tzinfo=UTC)
        ds = fx.raw_datastream(thresholds=dict(self.SITE))            # a soil probe
        obs = fx.observation(ds, result=450.0, measured_at=night)
        self.assertNotIn("clear_sky", C.assess(_state(ds, obs), obs).evidence["checks_run"])
        import vocab as V
        ds = fx.raw_datastream(unit="W/m2", observed_property=V.SOLAR_RADIATION)
        obs = fx.observation(ds, result=450.0, measured_at=night)
        a = C.assess(_state(ds, obs), obs)
        self.assertEqual(_flags(a), [])
        self.assertNotIn("clear_sky", a.evidence["checks_run"])


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


class TestFlatlineIsSampleRateIndependent(unittest.TestCase):
    """§4.2 says "identical values for LONGER THAN physically plausible" — a
    duration. A count-only threshold means different physical things on two farms
    that sample at different rates, which makes it untunable."""

    def _flat_run(self, sample_minutes, hours, **thresholds):
        """A probe frozen at one value for `hours`, sampled every n minutes."""
        ds = fx.raw_datastream(expected_interval=sample_minutes * 60,
                              thresholds=thresholds)
        count = int(hours * 60 / sample_minutes) + 1
        obs = [fx.observation(ds, result=0.31, measured_at=fx.at(i * sample_minutes),
                              seq=i) for i in range(count)]
        return obs[-1], _state(ds, *obs)

    def test_a_duration_threshold_means_the_same_thing_at_any_sample_rate(self):
        """The property the count-based version did not have."""
        for sample_minutes in (60, 15, 5, 1):
            with self.subTest(sample_minutes=sample_minutes):
                obs, state = self._flat_run(sample_minutes, hours=8,
                                           flat_seconds=6 * 3600, flat_n=2)
                self.assertEqual(_flags(C.assess(state, obs)), ["stuck"],
                                 "8 hours frozen is 8 hours frozen")
                obs, state = self._flat_run(sample_minutes, hours=4,
                                           flat_seconds=6 * 3600, flat_n=2)
                self.assertEqual(_flags(C.assess(state, obs)), [],
                                 "4 hours frozen is under a 6-hour limit")

    def test_a_count_only_threshold_is_coupled_to_the_sample_rate(self):
        """Demonstrating the trap rather than asserting it. The same flat_n=12
        catches a 1-hour freeze at 5-minute sampling and misses it at hourly."""
        fast, state_fast = self._flat_run(5, hours=1, flat_n=12)
        self.assertEqual(_flags(C.assess(state_fast, fast)), ["stuck"])
        slow, state_slow = self._flat_run(60, hours=1, flat_n=12)
        self.assertEqual(_flags(C.assess(state_slow, slow)), [],
                         "same threshold, same physical fault, opposite verdict")

    def test_both_knobs_must_be_satisfied_when_both_are_set(self):
        """flat_n is a confidence guard: two equal readings an hour apart prove
        very little, however long the span between them."""
        obs, state = self._flat_run(60, hours=12, flat_seconds=3600, flat_n=50)
        self.assertEqual(_flags(C.assess(state, obs)), [],
                         "the span qualifies but there are too few samples")
        obs, state = self._flat_run(60, hours=12, flat_seconds=3600, flat_n=2)
        self.assertEqual(_flags(C.assess(state, obs)), ["stuck"])

    def test_the_evidence_says_so_when_only_a_count_threshold_is_set(self):
        obs, state = self._flat_run(5, hours=2, flat_n=12)
        reason = C.assess(state, obs).evidence["fired"]["flatline"]
        self.assertIn("moves with the sample rate", reason)

    def test_the_evidence_reports_the_span_not_just_the_count(self):
        obs, state = self._flat_run(15, hours=8, flat_seconds=3600, flat_n=2)
        reason = C.assess(state, obs).evidence["fired"]["flatline"]
        self.assertIn("unchanged over", reason)
        self.assertIn("28800s", reason)

    def test_a_fresh_value_resets_the_span(self):
        ds = fx.raw_datastream(thresholds={"flat_seconds": 3600, "flat_n": 2})
        obs = [fx.observation(ds, result=0.31, measured_at=fx.at(i * 60), seq=i)
               for i in range(8)]
        obs.append(fx.observation(ds, result=0.44, measured_at=fx.at(8 * 60), seq=8))
        state = _state(ds, *obs)
        self.assertEqual(_flags(C.assess(state, obs[-1])), [])


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


class TestMaintenanceExplainsAStep(unittest.TestCase):
    """Q22: a battery change lifts a node's voltage in one reading. The rate check reads
    the device's maintenance log before calling that a fault, and keeps what it would
    have said in the evidence."""

    def _battery(self, *events_at, device=None):
        ds = fx.raw_datastream(thresholds={"max_rate_per_s": 0.0001})   # 0.36 V an hour
        before = fx.observation(ds, result=3.31, measured_at=fx.at(0), seq=0)
        after = fx.observation(ds, result=4.12, measured_at=fx.at(60), seq=1)
        events = [MaintenanceEvent(id=uuid7(), device=device or ds.sensor, at=fx.at(m),
                                   action=MaintenanceAction.SERVICED, note="new 18650 cell")
                  for m in events_at]
        state = _state(ds, before, after, *events)
        return C.assess(state, after)

    def test_a_logged_battery_change_explains_the_step(self):
        a = self._battery(30)
        self.assertEqual(_flags(a), [])
        explained = a.evidence["explained"]["rate"]
        self.assertEqual(explained["params"]["action"], "serviced")
        self.assertIn("/s", explained["params"]["finding"], "what the check would have said is kept")
        self.assertIn("rate", a.evidence["checks_run"])
        self.assertNotIn("rate", a.evidence["fired"])

    def test_without_the_log_entry_it_is_still_a_step(self):
        self.assertEqual(_flags(self._battery()), ["rate_exceeded"])

    def test_maintenance_before_the_previous_reading_explains_nothing(self):
        self.assertEqual(_flags(self._battery(-10)), ["rate_exceeded"])

    def test_another_device_is_maintenance_on_something_else(self):
        self.assertEqual(_flags(self._battery(30, device=uuid7())), ["rate_exceeded"])

    def test_a_probe_lifted_out_to_clean_is_not_a_spike(self):
        ds = fx.raw_datastream(thresholds=SOIL_SHAPE, expected_interval=3600.0)
        values = [0.25, 0.25, 0.25, 0.02, 0.25, 0.25]
        obs = [fx.observation(ds, result=v, measured_at=fx.at(i * 60), seq=i)
               for i, v in enumerate(values)]
        cleaned = MaintenanceEvent(id=uuid7(), device=ds.sensor, at=fx.at(170),
                                   action=MaintenanceAction.CLEANED)
        state = _state(ds, cleaned)
        late = []
        for o in obs:
            state.add(o)
            state.add(C.assess(state, o))
            late += C.spike_assertions(state, o)
        self.assertEqual(late, [])
        self.assertEqual(_flags(state.live_assertion_for(obs[3].id)), [],
                         "the drop to air while out of the ground is explained too")


class TestEvidenceFloor(unittest.TestCase):
    """Q19: a machine's assertion says what looked at the reading and what objected."""

    def test_every_assessment_meets_the_floor(self):
        ds, obs, state = TestRateOfChange()._pair(0.30, 0.90, 1, limit=0.001)
        a = C.assess(state, obs)
        self.assertEqual(evidence_problems(a), [])
        self.assertEqual(set(a.evidence["fired"]), {"rate"})
        self.assertTrue(set(a.evidence["fired"]) <= set(a.evidence["checks_run"]))

    def test_a_bare_machine_assertion_is_reported(self):
        ds = fx.raw_datastream()
        obs = fx.observation(ds)
        bare = fx.assertion(obs.id, flags=[QualityFlag.STUCK], evidence={})
        problems = _state(ds, obs, bare).validate()
        self.assertTrue(any("checks_run" in p for p in problems), problems)
        self.assertTrue(any("names no check" in p for p in problems), problems)

    def test_fired_must_be_among_what_ran(self):
        ds = fx.raw_datastream()
        obs = fx.observation(ds)
        odd = fx.assertion(obs.id, flags=[QualityFlag.STUCK],
                           evidence={"checks_run": ["range"], "fired": {"flatline": "x"}})
        self.assertIn("did not run: flatline", " ".join(evidence_problems(odd)))

    def test_a_persons_override_needs_none(self):
        ds = fx.raw_datastream()
        obs = fx.observation(ds)
        person = fx.assertion(obs.id, assertor=Assertor.PERSON, usable=Usable.GOOD,
                              check="manual-review", evidence={})
        self.assertEqual(evidence_problems(person), [])


class TestLearnedFlatline(unittest.TestCase):
    """Q24: a series learns its flatline from its own history, inside bounds its soil sets."""

    def _series(self, days, run_hours, *, every_h=1.0, stuck_from=None):
        ds = fx.raw_datastream(expected_interval=every_h * 3600.0)
        out, value = [], 0.20
        n = int(days * 24 / every_h)
        for i in range(n):
            if stuck_from is None or i < stuck_from:
                if i % run_hours == 0:
                    value = round(value + 0.001, 3)
            out.append(fx.observation(ds, result=value, measured_at=fx.at(i * every_h * 60), seq=i % 65536))
        return ds, out

    def test_runs_are_measured_as_the_check_measures_them(self):
        ds, obs = self._series(1, 6)
        self.assertEqual(set(C.dwell_runs(obs)), {5 * 3600.0})

    def test_nothing_is_learned_before_a_season(self):
        ds, obs = self._series(30, 6)
        self.assertIsNone(C.learned_flat_seconds(obs, 18 * 3600.0))

    def test_twice_the_healthy_dwell_inside_the_bounds(self):
        ds, obs = self._series(100, 12)                     # runs of 11 h
        value, basis = C.learned_flat_seconds(obs, 18 * 3600.0)
        self.assertEqual(value, 22 * 3600.0)
        self.assertIsNone(basis["bounded"])

    def test_a_quiet_deep_probe_is_capped_at_twice_its_soils_default(self):
        ds, obs = self._series(100, 60)                     # runs of 59 h
        value, basis = C.learned_flat_seconds(obs, 18 * 3600.0)
        self.assertEqual((value, basis["bounded"]), (36 * 3600.0, "cap"))

    def test_a_quiet_year_never_shortens_the_soils_default(self):
        """Measured: a threshold learned shorter from one year raised ten times the false
        alarms in the drought years after."""
        ds, obs = self._series(100, 8)
        value, basis = C.learned_flat_seconds(obs, 18 * 3600.0)
        self.assertEqual((value, basis["bounded"]), (18 * 3600.0, "floor"))

    def test_a_new_threshold_supersedes_and_ignores_stuck_readings(self):
        ds, obs = self._series(100, 12)
        old = fx.threshold(ds, flat_seconds=18 * 3600.0, max=0.55)
        frozen = [fx.observation(ds, result=0.5, measured_at=fx.at((2400 + i) * 60), seq=i)
                  for i in range(120)]
        stuck = [fx.assertion(o.id, flags=[QualityFlag.STUCK]) for o in frozen]
        state = _state(ds, old, *obs, *frozen, *stuck)
        new = C.learn_threshold(state, ds.id, 18 * 3600.0, created_at=fx.at(200 * 1440))
        self.assertEqual(new.supersedes, old.id)
        self.assertEqual(new.values["max"], 0.55, "other values are kept")
        self.assertEqual(new.values["flat_seconds"], 22 * 3600,
                         "the five-day freeze, already flagged, taught it nothing")
        self.assertEqual(new.values["flat_seconds_learned"]["runs"], len(C.dwell_runs(obs)))


SOIL_SHAPE = {"spike_step": 0.05, "max_fall_per_s": 0.05 / 3600}


def _hourly(values, *, minutes=60, thresholds=SOIL_SHAPE):
    ds = fx.raw_datastream(thresholds=thresholds, expected_interval=minutes * 60.0)
    obs = [fx.observation(ds, result=v, measured_at=fx.at(i * minutes), seq=i)
           for i, v in enumerate(values)]
    return ds, obs


class TestSpikeByShape(unittest.TestCase):
    """Q23: a glitch goes out and comes straight back; the soil does not."""

    def arrive(self, values, **kw):
        """Readings arriving one at a time, as through the gateway: each assessed on
        arrival, and each arrival allowed to settle what came before it."""
        ds, obs = _hourly(values, **kw)
        log = L.Log()
        log.append_record(ds)
        state = P.state_from_log(log)
        late = []
        for o in obs:
            state.add(o)
            state.add(C.assess(state, o))
            for a in C.spike_assertions(state, o):
                state.add(a)
                late.append(a)
        return state, obs, late

    def flags_of(self, state, o):
        return sorted(f.value for f in state.live_assertion_for(o.id).flags)

    def test_out_and_back_in_one_reading_is_a_spike_judged_one_reading_late(self):
        state, obs, late = self.arrive([0.25, 0.25, 0.25, 0.40, 0.25, 0.25])
        self.assertEqual([a.observation for a in late], [obs[3].id])
        self.assertEqual(self.flags_of(state, obs[3]), ["rate_exceeded"])
        self.assertEqual(state.live_assertion_for(obs[3].id).usable, Usable.QUESTIONABLE)
        self.assertEqual(self.flags_of(state, obs[4]), [], "the way back is a good reading")

    def test_a_dropout_is_a_spike(self):
        """The drop is a fall too fast for soil when it arrives (`suspect`); the next
        reading shows it was a glitch (`rate_exceeded`), added rather than replacing
        what was already said. Its return is neither."""
        state, obs, _ = self.arrive([0.27, 0.27, 0.27, 0.10, 0.27])
        self.assertEqual(self.flags_of(state, obs[3]), ["rate_exceeded", "suspect"])
        self.assertEqual(self.flags_of(state, obs[4]), [],
                         "and its return is not a fall")

    def test_rain_rises_and_holds(self):
        state, obs, late = self.arrive([0.15, 0.15, 0.26, 0.27, 0.265, 0.26, 0.255])
        self.assertEqual(late, [])
        self.assertTrue(all(self.flags_of(state, o) == [] for o in obs))

    def test_two_readings_out_at_15_minutes_is_still_a_spike(self):
        """The simulator's spike lasts half an hour: two readings at 15-minute sampling."""
        state, obs, late = self.arrive([0.25, 0.25, 0.45, 0.45, 0.25, 0.25], minutes=15)
        self.assertEqual({a.observation for a in late}, {obs[2].id, obs[3].id})

    def test_two_readings_out_at_hourly_is_not(self):
        """At hourly sampling the same shape spans an hour — longer than a glitch, and
        on ISMN's record the two-reading version doubled the false flags."""
        state, obs, late = self.arrive([0.25, 0.25, 0.45, 0.45, 0.25, 0.25])
        self.assertEqual(late, [])

    def test_a_backfilled_spike_is_judged_when_assessed(self):
        """A reading assessed after its successor arrived — a backfill or a batch
        re-run — is judged straight away."""
        ds, obs = _hourly([0.25, 0.25, 0.40, 0.25])
        state = _state(ds, *obs)
        self.assertEqual(_flags(C.assess(state, obs[2])), ["rate_exceeded"])
        self.assertIn("spike", C.assess(state, obs[2]).evidence["checks_run"])

    def test_the_check_is_not_claimed_before_it_could_run(self):
        ds, obs = _hourly([0.25, 0.25, 0.40])
        state = _state(ds, *obs)
        self.assertNotIn("spike", C.assess(state, obs[2]).evidence["checks_run"])

    def test_the_flag_is_added_and_a_person_is_not_overruled(self):
        ds, obs = _hourly([0.25, 0.25, 0.25, 0.40, 0.25])
        state = _state(ds, *obs[:4])
        stuck = C.assess(state, obs[3])
        state.add(stuck)
        mine = fx.assertion(obs[3].id, flags=(), check="manual",
                            assertor=Assertor.PERSON, asserted_at=fx.at(500))
        state.add(mine)
        state.add(obs[4])
        self.assertEqual(C.spike_assertions(state, obs[4]), [])

    def test_judging_twice_changes_nothing(self):
        state, obs, late = self.arrive([0.25, 0.25, 0.25, 0.40, 0.25])
        self.assertEqual(len(late), 1)
        self.assertEqual(C.spike_assertions(state, obs[4]), [])

    def test_off_unless_configured(self):
        state, obs, late = self.arrive([0.25, 0.25, 0.40, 0.25], thresholds={})
        self.assertEqual(late, [])


class TestFall(unittest.TestCase):
    """Q23: soil fills fast and empties slowly, so falls get a tight cap and rises none."""

    def test_a_fast_fall_from_a_steady_level_is_suspect(self):
        ds, obs = _hourly([0.30, 0.30, 0.22, 0.22])
        state = _state(ds, *obs)
        a = C.assess(state, obs[2])
        self.assertEqual(_flags(a), ["suspect"])
        self.assertIn("fall", a.evidence["fired"])

    def test_a_fast_rise_is_not(self):
        ds, obs = _hourly([0.15, 0.15, 0.32, 0.32])
        self.assertEqual(_flags(C.assess(_state(ds, *obs), obs[2])), [])

    def test_the_allowance_scales_with_the_gap(self):
        ds, obs = _hourly([0.30, 0.22], minutes=120)
        self.assertEqual(_flags(C.assess(_state(ds, *obs), obs[1])), [], "0.04 per hour")
        ds, obs = _hourly([0.30, 0.18], minutes=120)
        self.assertEqual(_flags(C.assess(_state(ds, *obs), obs[1])), ["suspect"])

    def test_beyond_three_hours_nothing_is_decided(self):
        ds, obs = _hourly([0.30, 0.05], minutes=240)
        self.assertEqual(_flags(C.assess(_state(ds, *obs), obs[1])), [])


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

    def test_a_raw_series_is_not_a_peer_of_a_derived_one(self):
        """The unit error that produced a 99.8% false-alarm rate on a farm with
        nothing wrong with it: a derived reading of 0.280 was being compared against
        its neighbour's raw reading of 280."""
        feature = uuid7()
        mine = fx.raw_datastream(feature=feature,
                                 thresholds={"cross_tolerance": 0.05})
        derived_mine = fx.derived_datastream(mine, thresholds={"cross_tolerance": 0.05})
        neighbour = fx.raw_datastream(feature=feature,
                                      thresholds={"cross_tolerance": 0.05})
        derived_neighbour = fx.derived_datastream(
            neighbour, thresholds={"cross_tolerance": 0.05})

        physical = fx.observation(derived_mine, result=0.280, calibration=uuid7())
        wire_units = fx.observation(neighbour, result=280)
        agreeing = fx.observation(derived_neighbour, result=0.281,
                                  calibration=uuid7())
        state = _state(mine, derived_mine, neighbour, derived_neighbour,
                       physical, wire_units, agreeing)
        self.assertEqual(_flags(C.assess(state, physical)), [],
                         "0.280 must be compared with 0.281, not with 280")

    def test_a_unit_mismatch_is_not_a_peer(self):
        feature = uuid7()
        import dataclasses
        mine = fx.raw_datastream(feature=feature,
                                 thresholds={"cross_tolerance": 0.05})
        theirs = dataclasses.replace(
            fx.raw_datastream(feature=feature,
                              thresholds={"cross_tolerance": 0.05}), unit="%")
        a = fx.observation(mine, result=0.28)
        b = fx.observation(theirs, result=28.0)
        self.assertEqual(_flags(C.assess(_state(mine, theirs, a, b), a)), [])

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
        self.assertEqual(len(a.evidence["checks_run"]), 5)

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


class TestFrozenSoil(unittest.TestCase):
    """A capacitance probe senses liquid water only, so frozen soil reads falsely dry."""

    def setUp(self):
        import datetime as _dt
        import vocab as V
        from ids import uuid7
        from model import Calibration, Datastream, DatastreamKind
        self.dt = _dt
        self.log = L.Log()
        sensor = uuid7()
        self.moisture = fx.raw_datastream(sensor=sensor)
        raw_t = fx.raw_datastream(sensor=sensor, unit="Cel",
                                  observed_property=V.SOIL_TEMPERATURE,
                                  expected_interval=3600.0)
        self.temperature = Datastream(
            id=uuid7(), thing=raw_t.thing, sensor=sensor,
            observed_property=V.SOIL_TEMPERATURE, feature=raw_t.feature,
            kind=DatastreamKind.DERIVED, derived_from=raw_t.id, unit="Cel",
            expected_interval=3600.0)
        self.cal = Calibration(id=uuid7(), sensor=sensor, datastream=raw_t.id,
                               method="identity", valid_from=fx.at(-60 * 24))
        for record in (self.moisture, raw_t, self.temperature, self.cal):
            self.log.append_record(record)

    def assess_at(self, soil_c, *, minutes_apart=10):
        self.log.append_record(fx.observation(
            self.temperature, result=soil_c, calibration=self.cal.id,
            measured_at=fx.at(minutes_apart)))
        obs = fx.observation(self.moisture, result=0.12, measured_at=fx.at(0))
        self.log.append_record(obs)
        state = P.state_from_log(self.log)
        return C.assess(state, obs)

    def test_moisture_read_in_frozen_soil_is_suspect(self):
        assertion = self.assess_at(-1.5)
        self.assertIn(QualityFlag.SUSPECT, assertion.flags)
        self.assertIn("frozen", assertion.evidence["fired"])

    def test_it_is_only_suspect_never_bad(self):
        """The reading is a true measurement of liquid water — just not the water an
        irrigation decision needs."""
        self.assertEqual(self.assess_at(-1.5).flags, {QualityFlag.SUSPECT})

    def test_soil_above_zero_is_not_flagged(self):
        self.assertNotIn("frozen", self.assess_at(4.0).evidence["fired"])

    def test_a_temperature_reading_hours_away_is_not_used(self):
        """No guessing from a reading taken long before or after."""
        self.assertNotIn("frozen",
                         self.assess_at(-3.0, minutes_apart=240).evidence["fired"])

    def test_without_a_temperature_channel_there_is_no_verdict(self):
        """Never inferred from the season or the date."""
        log = L.Log()
        ds = fx.raw_datastream()
        log.append_record(ds)
        obs = fx.observation(ds, result=0.12)
        log.append_record(obs)
        assertion = C.assess(P.state_from_log(log), obs)
        self.assertNotIn("frozen", assertion.evidence["fired"])

    def test_the_finding_renders_in_spanish(self):
        import i18n
        message = self.assess_at(-1.5).evidence["messages"]["frozen"]
        text = str(i18n.Translator("es").text(message["key"], **message["params"]))
        self.assertIn("helado", text)


class TestFrozenIsOnlyListedWhenItRan(unittest.TestCase):

    def test_a_probe_without_temperature_does_not_claim_the_frozen_check_ran(self):
        log = L.Log()
        ds = fx.raw_datastream()
        log.append_record(ds)
        obs = fx.observation(ds, result=0.2)
        log.append_record(obs)
        a = C.assess(P.state_from_log(log), obs)
        self.assertNotIn("frozen", a.evidence["checks_run"])
