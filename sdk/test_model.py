#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The contract's own rules, enforced at the boundary (spec v0.1 §1-§4)."""
from __future__ import annotations

import dataclasses
import datetime as _dt
import unittest
import uuid

import fixtures as fx
from ids import uuid7
from model import (Assertor, ClockQuality, Datastream,
                   DatastreamKind, QualityFlag,
                   Usable, derive_usable)

UTC = _dt.timezone.utc


class TestImmutability(unittest.TestCase):
    """§3.2: written once, never altered."""

    def test_observation_cannot_be_assigned_to(self):
        obs = fx.observation(fx.raw_datastream())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            obs.result = 0.99

    def test_assertion_cannot_be_assigned_to(self):
        a = fx.assertion(uuid7())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.usable = Usable.BAD


class TestIdentity(unittest.TestCase):
    """§1: UUIDv7 everywhere."""

    def test_v4_ids_are_rejected(self):
        ds = fx.raw_datastream()
        with self.assertRaisesRegex(ValueError, "UUIDv7"):
            dataclasses.replace(ds, id=uuid.uuid4())

    def test_seq_is_uint16(self):
        ds = fx.raw_datastream()
        fx.observation(ds, seq=0xFFFF)
        with self.assertRaisesRegex(ValueError, "uint16"):
            fx.observation(ds, seq=0x10000)

    def test_boot_is_not_negative(self):
        with self.assertRaisesRegex(ValueError, "boot"):
            fx.observation(fx.raw_datastream(), boot=-1)

    def test_nothing_may_supersede_itself(self):
        ds = fx.raw_datastream()
        obs = fx.observation(ds)
        with self.assertRaisesRegex(ValueError, "supersede itself"):
            dataclasses.replace(obs, supersedes=obs.id)


class TestTime(unittest.TestCase):
    """§2: UTC, and a bound on every timestamp."""

    def test_naive_datetimes_are_rejected(self):
        ds = fx.raw_datastream()
        with self.assertRaisesRegex(ValueError, "UTC"):
            fx.observation(ds, measured_at=_dt.datetime(2026, 6, 1))

    def test_non_utc_offsets_are_rejected(self):
        ds = fx.raw_datastream()
        kiev = _dt.timezone(_dt.timedelta(hours=3))
        with self.assertRaisesRegex(ValueError, "UTC"):
            fx.observation(ds, measured_at=_dt.datetime(2026, 6, 1, tzinfo=kiev))

    def test_uncertainty_is_mandatory_and_never_zero(self):
        ds = fx.raw_datastream()
        with self.assertRaisesRegex(ValueError, "never zero"):
            fx.observation(ds, uncertainty=0)
        with self.assertRaisesRegex(ValueError, "never zero"):
            fx.observation(ds, uncertainty=-1)

    def test_interval_is_the_uncertainty_window(self):
        obs = fx.observation(fx.raw_datastream(), uncertainty=30)
        lo, hi = obs.interval()
        self.assertEqual((hi - lo).total_seconds(), 60)
        self.assertEqual(obs.measured_at - lo, _dt.timedelta(seconds=30))

    def test_clockless_node_still_needs_an_honest_bound(self):
        """A `none` clock is legal; an unbounded timestamp is not."""
        ds = fx.raw_datastream()
        obs = fx.observation(ds, clock_quality=ClockQuality.NONE, uncertainty=600)
        self.assertEqual(obs.clock_quality, ClockQuality.NONE)
        self.assertEqual(obs.measured_at_uncertainty, 600)


class TestDatastream(unittest.TestCase):
    """§3.1 and §3.4."""

    def test_raw_has_no_derived_from(self):
        with self.assertRaisesRegex(ValueError, "raw datastream has no derived_from"):
            dataclasses.replace(fx.raw_datastream(), derived_from=uuid7())

    def test_derived_must_name_its_source(self):
        raw = fx.raw_datastream()
        with self.assertRaisesRegex(ValueError, "must name its derived_from"):
            Datastream(id=uuid7(), thing=raw.thing, sensor=raw.sensor,
                       observed_property=fx.SOIL_MOISTURE, feature=raw.feature,
                       kind=DatastreamKind.DERIVED)

    def test_cannot_derive_from_itself(self):
        raw = fx.raw_datastream()
        ident = uuid7()
        with self.assertRaisesRegex(ValueError, "derive from itself"):
            Datastream(id=ident, thing=raw.thing, sensor=raw.sensor,
                       observed_property=fx.SOIL_MOISTURE, feature=raw.feature,
                       kind=DatastreamKind.DERIVED, derived_from=ident)

    def test_observed_property_must_be_a_uri_not_free_text(self):
        """§3.4: a URI from a shared vocabulary, never free text."""
        raw = fx.raw_datastream()
        with self.assertRaisesRegex(ValueError, "vocabulary URI"):
            dataclasses.replace(raw, observed_property="soil moisture")

    def test_unit_may_be_null_for_a_boolean_series(self):
        """§3.4: no meaningful unit means null, not an invented one."""
        ds = dataclasses.replace(fx.raw_datastream(), unit=None)
        self.assertIsNone(ds.unit)

    def test_expected_interval_must_be_positive(self):
        with self.assertRaises(ValueError):
            fx.raw_datastream(expected_interval=0)

    def test_max_latency_must_be_positive(self):
        with self.assertRaises(ValueError):
            fx.raw_datastream(max_latency=0)

    def test_sampling_and_latency_are_independent(self):
        """§3.1/§5.3.1: how often a series is read and how fast it must arrive
        are different numbers, and only the second spends the battery. A series
        may legitimately be sampled often and reported slowly, or the reverse."""
        sleepy = fx.raw_datastream(expected_interval=300.0, max_latency=3600.0)
        self.assertLess(sleepy.expected_interval, sleepy.max_latency)
        urgent = fx.raw_datastream(expected_interval=3600.0, max_latency=60.0)
        self.assertGreater(urgent.expected_interval, urgent.max_latency)

    def test_latency_is_optional(self):
        self.assertIsNone(fx.raw_datastream(max_latency=None).max_latency)


class TestFeature(unittest.TestCase):
    """§3.1: feature on the datastream, overridable per observation."""

    def test_defaults_to_the_datastreams_feature(self):
        ds = fx.raw_datastream()
        obs = fx.observation(ds)
        self.assertIsNone(obs.feature)
        self.assertEqual(obs.effective_feature(ds), ds.feature)

    def test_override_wins_for_a_handheld_reading(self):
        ds = fx.raw_datastream()
        sample = uuid7()
        obs = fx.observation(ds, feature=sample)
        self.assertEqual(obs.effective_feature(ds), sample)


class TestRawVersusDerived(unittest.TestCase):
    """§3.2: raw is the archival truth; derived carries the calibration."""

    def test_raw_observation_carries_no_calibration(self):
        raw = fx.raw_datastream()
        obs = fx.observation(raw, calibration=uuid7())
        with self.assertRaisesRegex(ValueError, "raw observation carries no calibration"):
            obs.validate_against(raw)

    def test_raw_observation_is_never_superseded(self):
        raw = fx.raw_datastream()
        obs = fx.observation(raw, supersedes=uuid7())
        with self.assertRaisesRegex(ValueError, "never superseded"):
            obs.validate_against(raw)

    def test_derived_observation_must_name_its_calibration(self):
        raw = fx.raw_datastream()
        derived = fx.derived_datastream(raw)
        obs = fx.observation(derived)
        with self.assertRaisesRegex(ValueError, "must name the calibration"):
            obs.validate_against(derived)

    def test_a_well_formed_pair_validates(self):
        raw = fx.raw_datastream()
        derived = fx.derived_datastream(raw)
        fx.observation(raw).validate_against(raw)
        fx.observation(derived, calibration=uuid7()).validate_against(derived)

    def test_datastream_mismatch_is_caught(self):
        a, b = fx.raw_datastream(), fx.raw_datastream()
        with self.assertRaisesRegex(ValueError, "mismatch"):
            fx.observation(a).validate_against(b)


class TestCalibrationValidity(unittest.TestCase):
    """§4.1: a calibration carries the interval it is in force for."""

    def test_covers_is_half_open(self):
        sensor = uuid7()
        cal = fx.calibration(sensor, valid_from=fx.at(0), valid_to=fx.at(60))
        self.assertTrue(cal.covers(fx.at(0)))
        self.assertTrue(cal.covers(fx.at(59)))
        self.assertFalse(cal.covers(fx.at(60)), "end is exclusive, so adjacent "
                                                "calibrations never both apply")
        self.assertFalse(cal.covers(fx.at(-1)))

    def test_open_ended_calibration_is_still_in_force(self):
        cal = fx.calibration(uuid7(), valid_from=fx.at(0), valid_to=None)
        self.assertTrue(cal.covers(fx.at(10_000)))

    def test_valid_to_must_follow_valid_from(self):
        with self.assertRaises(ValueError):
            fx.calibration(uuid7(), valid_from=fx.at(60), valid_to=fx.at(0))


class TestQuality(unittest.TestCase):
    """§3.3: a flag set, a derived summary, and who may disagree with it."""

    def test_derive_usable_table(self):
        F = QualityFlag
        cases = [
            (set(), Usable.GOOD),
            ({F.SUSPECT}, Usable.QUESTIONABLE),
            ({F.RATE_EXCEEDED}, Usable.QUESTIONABLE),
            ({F.SUSPECT, F.RATE_EXCEEDED}, Usable.QUESTIONABLE),
            ({F.STUCK}, Usable.BAD),
            ({F.OUT_OF_RANGE}, Usable.BAD),
            ({F.STUCK, F.SUSPECT}, Usable.BAD),
        ]
        for flags, expected in cases:
            with self.subTest(flags=sorted(f.value for f in flags)):
                self.assertEqual(derive_usable(flags), expected)

    def test_two_flags_at_once(self):
        """§3.3's reason for a set: a sensor can be stuck *and* out of range."""
        a = fx.assertion(uuid7(), flags={QualityFlag.STUCK, QualityFlag.OUT_OF_RANGE})
        self.assertEqual(len(a.flags), 2)
        self.assertEqual(a.usable, Usable.BAD)

    def test_stale_is_not_a_reading_flag(self):
        """§4.2: staleness is a datastream state."""
        self.assertNotIn("stale", {f.value for f in QualityFlag})

    def test_device_warning_is_not_a_reading_flag(self):
        """§4.3: battery belongs in its own datastream."""
        self.assertNotIn("device_warning", {f.value for f in QualityFlag})

    def test_foundation_may_not_contradict_its_own_flags(self):
        with self.assertRaisesRegex(ValueError, "contradicts flags"):
            fx.assertion(uuid7(), flags={QualityFlag.STUCK}, usable=Usable.GOOD)

    def test_a_person_may_override(self):
        """§3.3: a person's override is a new assertion, and disagreement is the point."""
        a = fx.assertion(uuid7(), flags={QualityFlag.STUCK}, usable=Usable.GOOD,
                         assertor=Assertor.PERSON, assertor_id=uuid7(),
                         check="manual-review", note="probe was out of the ground")
        self.assertEqual(a.usable, Usable.GOOD)
        self.assertEqual(a.flags, frozenset({QualityFlag.STUCK}))

    def test_check_is_required(self):
        with self.assertRaisesRegex(ValueError, "check must name"):
            fx.assertion(uuid7(), check="")

    def test_flags_must_be_quality_flags(self):
        with self.assertRaises(TypeError):
            fx.assertion(uuid7(), flags={"stuck"})

    def test_person_outranks_foundation(self):
        lo = fx.assertion(uuid7())
        hi = fx.assertion(uuid7(), assertor=Assertor.PERSON, assertor_id=uuid7())
        self.assertGreater(hi.precedence, lo.precedence)


if __name__ == "__main__":
    unittest.main(verbosity=2)
