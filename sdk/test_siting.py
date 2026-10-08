#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for the siting check. The physics is synthetic here, so every number is known."""
from __future__ import annotations

import datetime as _dt
import math
import unittest

import fixtures as fx
import log as L
import project as P
import siting as S
import vocab as V
from ids import uuid7
from model import (Calibration, Datastream, DatastreamKind, Device, DeviceKind,
                   Installation, QualityFlag)

UTC = _dt.timezone.utc
T0 = _dt.datetime(2026, 6, 10, tzinfo=UTC)
D = 0.13                          # damping depth used to synthesise the readings
SURFACE_PEAK_H = 15.5
SURFACE_SWING = 5.0


def _temperature(z: float, when: _dt.datetime, damping: float = D) -> float:
    """The analytic periodic solution of the heat equation, which the check inverts."""
    hours = when.timestamp() / 3600.0
    lag = z / damping
    phase = 2 * math.pi * (hours - SURFACE_PEAK_H) / 24.0 - lag
    return round(18.0 + SURFACE_SWING * math.exp(-z / damping) * math.cos(phase), 1)


class _Farm:
    """A handful of probes reporting synthetic soil temperature, hourly for 2 days."""

    def __init__(self, recorded: dict, physical: dict | None = None,
                 damping: dict | None = None):
        self.log = L.Log()
        self.ids = {}
        physical = physical or recorded
        damping = damping or {}
        site, feature = uuid7(), uuid7()
        for name, depth in recorded.items():
            device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=site)
            raw = Datastream(id=uuid7(), thing=uuid7(), sensor=device.id,
                             observed_property=V.SOIL_TEMPERATURE, feature=feature,
                             kind=DatastreamKind.RAW, unit="Cel")
            derived = Datastream(id=uuid7(), thing=raw.thing, sensor=device.id,
                                 observed_property=V.SOIL_TEMPERATURE,
                                 feature=feature, kind=DatastreamKind.DERIVED,
                                 derived_from=raw.id, unit="Cel")
            cal = Calibration(id=uuid7(), sensor=device.id, datastream=raw.id,
                              method="identity", valid_from=T0 - _dt.timedelta(days=9))
            install = Installation(id=uuid7(), device=device.id, feature=feature,
                                   installed_at=T0 - _dt.timedelta(days=9),
                                   depth_m=depth)
            for record in (device, raw, derived, cal, install):
                self.log.append_record(record)
            for hour in range(49):
                when = T0 + _dt.timedelta(hours=hour)
                value = _temperature(physical[name], when,
                                     damping.get(name, D))
                self.log.append_record(fx.observation(
                    derived, result=value, measured_at=when, calibration=cal.id,
                    node=None, boot=None, seq=None))
            self.ids[name] = device.id
        self.state = P.state_from_log(self.log)
        self.at = T0 + _dt.timedelta(hours=48)

    def assess(self, name):
        return S.assess_siting(self.state, self.ids[name], self.at)


STANDARD = {"a20": 0.20, "b20": 0.20, "c20": 0.20, "d20": 0.20,
            "a40": 0.40, "b40": 0.40, "c40": 0.40}


class TestFit(unittest.TestCase):

    def test_it_recovers_a_known_peak_hour_and_swing(self):
        samples = [((T0 + _dt.timedelta(hours=h)).timestamp(),
                    20 + 3 * math.cos(2 * math.pi * (h - 14) / 24))
                   for h in range(48)]
        fit = S.fit_diurnal(samples)
        self.assertAlmostEqual(fit.peak_hour, 14.0, places=3)
        self.assertAlmostEqual(fit.amplitude, 3.0, places=3)

    def test_a_trend_does_not_move_the_peak(self):
        """Early-summer soil warms by a degree over two days. Without the trend term
        that drift leaks into the cosine and shifts the peak."""
        samples = [((T0 + _dt.timedelta(hours=h)).timestamp(),
                    20 + 0.6 * h / 24 + 3 * math.cos(2 * math.pi * (h - 14) / 24))
                   for h in range(48)]
        self.assertAlmostEqual(S.fit_diurnal(samples).peak_hour, 14.0, places=2)

    def test_a_peak_after_midnight_is_reported_after_midnight(self):
        samples = [((T0 + _dt.timedelta(hours=h)).timestamp(),
                    20 + 3 * math.cos(2 * math.pi * (h - 1.5) / 24))
                   for h in range(48)]
        self.assertAlmostEqual(S.fit_diurnal(samples).peak_hour, 1.5, places=2)

    def test_too_few_or_too_short_is_none_not_a_guess(self):
        self.assertIsNone(S.fit_diurnal([(0, 1.0)] * 5))
        short = [((T0 + _dt.timedelta(hours=h)).timestamp(), 1.0) for h in range(14)]
        self.assertIsNone(S.fit_diurnal(short))


class TestVerdicts(unittest.TestCase):

    def test_a_probe_where_its_record_says_is_consistent(self):
        farm = _Farm(STANDARD)
        finding = farm.assess("a20")
        self.assertEqual(finding.verdict, S.CONSISTENT, finding.reason)
        self.assertAlmostEqual(finding.implied_depth_m, 0.20, delta=0.02)
        self.assertAlmostEqual(finding.damping_depth_m, D, delta=0.01)

    def test_an_unlogged_lift_is_displaced(self):
        farm = _Farm(STANDARD, physical={**STANDARD, "a20": 0.05})
        finding = farm.assess("a20")
        self.assertEqual(finding.verdict, S.DISPLACED)
        self.assertAlmostEqual(finding.implied_depth_m, 0.05, delta=0.03)
        self.assertIn("shallower", finding.reason)

    def test_an_unlogged_push_is_displaced(self):
        farm = _Farm(STANDARD, physical={**STANDARD, "a20": 0.34})
        finding = farm.assess("a20")
        self.assertEqual(finding.verdict, S.DISPLACED)
        self.assertIn("deeper", finding.reason)

    def test_a_peak_that_wraps_past_midnight_is_still_read_as_deep(self):
        """At 40 cm the peak lands after midnight. Read as a plain number it would
        look like the shallowest probe on the farm."""
        farm = _Farm(STANDARD)
        finding = farm.assess("a40")
        self.assertEqual(finding.verdict, S.CONSISTENT, finding.reason)
        self.assertAlmostEqual(finding.implied_depth_m, 0.40, delta=0.03)

    def test_two_displaced_peers_do_not_disable_the_check_for_everyone(self):
        """The defect the first version had: least squares let two bad peers drag the
        calibration and widen the tolerance to metres, and every probe passed."""
        physical = {**STANDARD, "b20": 0.05, "c20": 0.36}
        farm = _Farm(STANDARD, physical=physical)
        self.assertEqual(farm.assess("b20").verdict, S.DISPLACED)
        self.assertEqual(farm.assess("c20").verdict, S.DISPLACED)
        honest = farm.assess("a20")
        self.assertEqual(honest.verdict, S.CONSISTENT)
        self.assertLess(honest.tolerance_m, 0.15,
                        "the tolerance must not balloon because of bad peers")

    def test_the_evidence_says_why(self):
        finding = _Farm(STANDARD, physical={**STANDARD, "a20": 0.05}).assess("a20")
        for key in ("recorded_depth_m", "implied_depth_m", "peak_hour_utc",
                    "damping_depth_m", "peers", "tolerance_m"):
            self.assertIn(key, finding.evidence)


class TestIndeterminate(unittest.TestCase):
    """The blind spots, reported as such and never as `consistent`."""

    def test_below_the_reach_of_the_daily_wave(self):
        farm = _Farm({**STANDARD, "deep": 0.90})
        finding = farm.assess("deep")
        self.assertEqual(finding.verdict, S.INDETERMINATE)
        self.assertIn("deeper than the daily wave reaches", finding.reason)

    def test_too_few_peers(self):
        farm = _Farm({"a20": 0.20, "a40": 0.40})
        self.assertEqual(farm.assess("a20").verdict, S.INDETERMINATE)

    def test_peers_at_only_one_depth_cannot_calibrate(self):
        farm = _Farm({"a": 0.20, "b": 0.20, "c": 0.20, "d": 0.20})
        finding = farm.assess("a")
        self.assertEqual(finding.verdict, S.INDETERMINATE)
        self.assertIn("two depths", finding.reason)

    def test_a_device_with_no_temperature_channel(self):
        farm = _Farm(STANDARD)
        lonely = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=uuid7())
        farm.log.append_record(lonely)
        state = P.state_from_log(farm.log)
        finding = S.assess_siting(state, lonely.id, farm.at)
        self.assertEqual(finding.verdict, S.INDETERMINATE)


class TestTheConfounder(unittest.TestCase):

    def test_a_drier_bed_reads_deeper_but_within_tolerance(self):
        """Dry soil damps the wave faster, so a correctly sited probe in a dry bed
        looks deeper than it is. The peer calibration and the tolerance are there so
        this is not a false alarm."""
        farm = _Farm(STANDARD, damping={"a20": 0.115})
        finding = farm.assess("a20")
        self.assertGreater(finding.implied_depth_m, 0.20)
        self.assertEqual(finding.verdict, S.CONSISTENT)


if __name__ == "__main__":
    unittest.main()


class TestPosition(unittest.TestCase):
    """GNSS fixes against the recorded feature — the lateral move temperature misses."""

    def _farm(self, fix_at, *, fixes=12, scatter_m=2.5, geometry=True):
        import random
        rng = random.Random(7)
        log = L.Log()
        site, feature = uuid7(), uuid7()
        node = Device(id=uuid7(), kind=DeviceKind.NODE, site=site)
        log.append_record(node)
        log.append_record(Installation(id=uuid7(), device=node.id, feature=feature,
                                       installed_at=T0 - _dt.timedelta(days=9)))
        streams = {}
        for prop in (V.LATITUDE, V.LONGITUDE):
            raw = Datastream(id=uuid7(), thing=uuid7(), sensor=node.id,
                             observed_property=prop, feature=feature,
                             kind=DatastreamKind.RAW, unit="deg")
            derived = Datastream(id=uuid7(), thing=raw.thing, sensor=node.id,
                                 observed_property=prop, feature=feature,
                                 kind=DatastreamKind.DERIVED, derived_from=raw.id,
                                 unit="deg")
            cal = Calibration(id=uuid7(), sensor=node.id, datastream=raw.id,
                              method="identity", valid_from=T0 - _dt.timedelta(days=9))
            for record in (raw, derived, cal):
                log.append_record(record)
            streams[prop] = (derived, cal)
        for hour in range(fixes):
            when = T0 + _dt.timedelta(hours=hour)
            for prop, axis in ((V.LONGITUDE, 0), (V.LATITUDE, 1)):
                derived, cal = streams[prop]
                value = fix_at[axis] + rng.gauss(0, scatter_m) / S.METRES_PER_DEGREE
                log.append_record(fx.observation(derived, result=value,
                                                 measured_at=when, calibration=cal.id,
                                                 node=None, boot=None, seq=None))
        state = P.state_from_log(log)
        geometries = ({feature: {"type": "Point", "coordinates": [0.0, 0.0]}}
                      if geometry else {})
        return state, node.id, geometries, T0 + _dt.timedelta(hours=fixes)

    def test_a_node_at_its_feature_is_consistent(self):
        state, node, geo, at = self._farm((0.0, 0.0))
        finding = S.assess_position(state, node, at, geo)
        self.assertEqual(finding.verdict, S.CONSISTENT, finding.reason)
        self.assertLess(finding.distance_m, 5)

    def test_a_node_carried_a_hundred_metres_is_displaced(self):
        state, node, geo, at = self._farm((100 / S.METRES_PER_DEGREE, 0.0))
        finding = S.assess_position(state, node, at, geo)
        self.assertEqual(finding.verdict, S.DISPLACED)
        self.assertAlmostEqual(finding.distance_m, 100, delta=5)

    def test_gps_scatter_alone_is_not_a_move(self):
        """A node a few metres off centre, with ordinary scatter, must not be flagged:
        GNSS cannot resolve it and should not pretend to."""
        state, node, geo, at = self._farm((6 / S.METRES_PER_DEGREE, 0.0),
                                          scatter_m=4.0)
        self.assertEqual(S.assess_position(state, node, at, geo).verdict,
                         S.CONSISTENT)

    def test_one_wild_fix_does_not_move_the_answer(self):
        """Medians, so a multipath bounce of a kilometre changes nothing.

        The wild fix is injected on *both* axes at one instant. The first version of
        this test put it on latitude only, so it had no longitude partner, was dropped
        by the pairing step, and never reached the median it claimed to test.
        """
        state, node, geo, at = self._farm((0.0, 0.0), fixes=11)
        when = T0 + _dt.timedelta(minutes=30)
        for prop in (V.LATITUDE, V.LONGITUDE):
            derived = next(ds for ds in state.datastreams.values()
                           if ds.observed_property == prop
                           and ds.kind is DatastreamKind.DERIVED)
            cal = next(c for c in state.calibrations.values()
                       if c.datastream == derived.derived_from)
            state.add(fx.observation(derived, result=1000 / S.METRES_PER_DEGREE,
                                     measured_at=when, calibration=cal.id,
                                     node=None, boot=None, seq=None))
        finding = S.assess_position(state, node, at, geo)
        self.assertEqual(finding.fixes, 12, "the wild fix is in the sample")
        self.assertEqual(finding.verdict, S.CONSISTENT)
        self.assertLess(finding.distance_m, 5)

    def test_without_geometry_it_says_so(self):
        state, node, geo, at = self._farm((0.0, 0.0), geometry=False)
        finding = S.assess_position(state, node, at, geo)
        self.assertEqual(finding.verdict, S.INDETERMINATE)
        self.assertEqual(finding.key, "position.no_geometry")

    def test_too_few_fixes_is_indeterminate_not_consistent(self):
        state, node, geo, at = self._farm((0.0, 0.0), fixes=2)
        self.assertEqual(S.assess_position(state, node, at, geo).verdict,
                         S.INDETERMINATE)

    def test_the_finding_renders_in_spanish(self):
        import i18n
        state, node, geo, at = self._farm((100 / S.METRES_PER_DEGREE, 0.0))
        finding = S.assess_position(state, node, at, geo)
        text = str(i18n.Translator("es").text(finding.key, **finding.params))
        self.assertIn("sin ningún registro", text)


class TestFindingsBecomeAssertions(unittest.TestCase):
    """A displaced probe's readings become `suspect` — without erasing anything."""

    def setUp(self):
        self.farm = _Farm(STANDARD, physical={**STANDARD, "a20": 0.05})
        self.state = self.farm.state
        self.finding = self.farm.assess("a20")
        self.assertEqual(self.finding.verdict, S.DISPLACED)
        self.readings = [o for ds in self.state.datastreams_of_sensor(self.finding.device)
                         if ds.kind is DatastreamKind.DERIVED
                         for o in self.state.live_observations_of(ds.id)]

    def apply(self, flagging):
        for assertion in flagging.assertions:
            self.farm.log.append_record(assertion)
            self.state.add(assertion)

    def test_every_reading_in_the_window_is_flagged_suspect(self):
        flagging = S.suspect_assertions(self.state, self.finding)
        self.assertEqual(len(flagging.assertions), len(self.readings))
        self.apply(flagging)
        for obs in self.readings:
            live = self.state.live_assertion_for(obs.id)
            self.assertIn(QualityFlag.SUSPECT, live.flags)
            self.assertEqual(live.check, S.SITING_CHECK)

    def test_a_consistent_finding_flags_nothing(self):
        consistent = self.farm.assess("b20")
        self.assertEqual(S.suspect_assertions(self.state, consistent).assertions, ())

    def test_running_it_again_writes_nothing_new(self):
        """Assessed daily over overlapping windows — must not stack."""
        self.apply(S.suspect_assertions(self.state, self.finding))
        again = S.suspect_assertions(self.state, self.finding)
        self.assertEqual(again.assertions, ())
        self.assertEqual(again.already_flagged, len(self.readings))

    def test_an_earlier_stuck_flag_is_carried_and_the_reading_stays_bad(self):
        """Adding siting must not soften a worse judgement already made."""
        from model import QualityAssertion, QualityFlag, Usable
        target = self.readings[5]
        stuck = QualityAssertion(id=uuid7(), observation=target.id,
                                 flags=frozenset({QualityFlag.STUCK}),
                                 usable=Usable.BAD, check="foundation",
                                 asserted_at=T0, evidence={"fired": {"flatline": "x"}})
        self.farm.log.append_record(stuck)
        self.state.add(stuck)
        self.apply(S.suspect_assertions(self.state, self.finding))
        live = self.state.live_assertion_for(target.id)
        self.assertEqual(live.flags, {QualityFlag.STUCK, QualityFlag.SUSPECT})
        self.assertIs(live.usable, Usable.BAD)
        self.assertEqual(live.supersedes, stuck.id)
        self.assertIn("fired", live.evidence, "earlier evidence is carried forward")

    def test_a_person_outranks_the_siting_flag(self):
        """A machine flag superseding a human override would erase the override from
        the live view — exactly what §3.3's precedence exists to prevent."""
        from model import Assertor, QualityAssertion, Usable
        target = self.readings[3]
        human = QualityAssertion(id=uuid7(), observation=target.id, flags=frozenset(),
                                 usable=Usable.GOOD, check="override",
                                 asserted_at=T0, assertor=Assertor.PERSON,
                                 note="probe checked by hand; fine")
        self.farm.log.append_record(human)
        self.state.add(human)
        flagging = S.suspect_assertions(self.state, self.finding)
        self.assertEqual(flagging.person_outranks, 1)
        self.assertNotIn(target.id, {a.observation for a in flagging.assertions})

    def test_the_flag_renders_in_spanish_from_the_record(self):
        import i18n
        self.apply(S.suspect_assertions(self.state, self.finding))
        live = self.state.live_assertion_for(self.readings[0].id)
        message = live.evidence["messages"]["siting"]
        text = str(i18n.Translator("es").text(message["key"], **message["params"]))
        self.assertIn("menos profunda", text)

    def test_the_log_still_validates(self):
        self.apply(S.suspect_assertions(self.state, self.finding))
        self.assertEqual(P.state_from_log(self.farm.log).validate(), [])

