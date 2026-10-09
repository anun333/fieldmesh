#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for the siting check. The physics is synthetic here, so every number is known."""
from __future__ import annotations

import datetime as _dt
import math
import random
import unittest

import fixtures as fx
import log as L
import project as P
import siting as S
import vocab as V
from ids import uuid7
from model import (Calibration, Datastream, DatastreamKind, Device, DeviceKind,
                   Installation, MaintenanceAction, MaintenanceEvent, QualityFlag)

UTC = _dt.timezone.utc
T0 = _dt.datetime(2026, 6, 10, tzinfo=UTC)
D = 0.13                          # damping depth used to synthesise the readings
SURFACE_PEAK_H = 15.5
SURFACE_SWING = 5.0


def _temperature(z: float, when: _dt.datetime, damping: float = D,
                 noise: float = 0.0) -> float:
    """The analytic periodic solution of the heat equation, which the check inverts.
    `noise` is added before rounding to the sensor's 0.1 C, as a real sensor's own noise
    dithers a wave smaller than one step into something a long fit can read."""
    hours = when.timestamp() / 3600.0
    lag = z / damping
    phase = 2 * math.pi * (hours - SURFACE_PEAK_H) / 24.0 - lag
    return round(18.0 + SURFACE_SWING * math.exp(-z / damping) * math.cos(phase) + noise, 1)


class _Farm:
    """A handful of probes reporting synthetic soil temperature, hourly for 2 days."""

    def __init__(self, recorded: dict, physical: dict | None = None,
                 damping: dict | None = None, hours: int = 49,
                 episode: dict | None = None, noise_c: float = 0.0,
                 silent: dict | None = None):
        """`episode` = {name: (from_hour, to_hour, depth)}: where a probe physically
        was for a while, with no record of it — an unlogged move, or a bad day."""
        self.log = L.Log()
        self.ids = {}
        physical = physical or recorded
        damping = damping or {}
        site, feature = uuid7(), uuid7()
        rng = random.Random(7)
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
            for hour in range(hours):
                if silent and name in silent and \
                        silent[name][0] <= hour < silent[name][1]:
                    continue
                when = T0 + _dt.timedelta(hours=hour)
                z = physical[name]
                if episode and name in episode and \
                        episode[name][0] <= hour < episode[name][1]:
                    z = episode[name][2]
                value = _temperature(z, when, damping.get(name, D),
                                     rng.gauss(0.0, noise_c) if noise_c else 0.0)
                self.log.append_record(fx.observation(
                    derived, result=value, measured_at=when, calibration=cal.id,
                    node=None, boot=None, seq=None))
            self.ids[name] = device.id
        self.state = P.state_from_log(self.log)
        self.at = T0 + _dt.timedelta(hours=hours - 1)

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



class TestLateral(unittest.TestCase):
    """Which bed's irrigation a probe answers to — synthetic, so every number is known."""

    def _farm(self, physical_bed: dict, *, rain_only=False, lag_bins=None):
        """Six probes in three beds; each bed watered at its own hour on alternate
        days. `physical_bed` says where each probe really is; records say where it was
        put."""
        lag_bins = lag_bins or {}
        recorded = {"a1": "A", "a2": "A", "b1": "B", "b2": "B", "c1": "C", "c2": "C"}
        hours = {"A": 4, "B": 9, "C": 15}
        features = {name: uuid7() for name in "ABC"}
        log = L.Log()
        site = uuid7()
        self.ids = {}
        for probe, bed in recorded.items():
            device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=site)
            raw = Datastream(id=uuid7(), thing=uuid7(), sensor=device.id,
                             observed_property=V.SOIL_WATER, feature=features[bed],
                             kind=DatastreamKind.RAW, unit="cm3/cm3")
            derived = Datastream(id=uuid7(), thing=raw.thing, sensor=device.id,
                                 observed_property=V.SOIL_WATER,
                                 feature=features[bed], kind=DatastreamKind.DERIVED,
                                 derived_from=raw.id, unit="cm3/cm3")
            cal = Calibration(id=uuid7(), sensor=device.id, datastream=raw.id,
                              method="identity", valid_from=T0 - _dt.timedelta(days=9))
            install = Installation(id=uuid7(), device=device.id,
                                   feature=features[bed],
                                   installed_at=T0 - _dt.timedelta(days=9))
            for record in (device, raw, derived, cal, install):
                log.append_record(record)
            theta, really = 0.25, physical_bed.get(probe, bed)
            lag = lag_bins.get(probe, 0)
            for step in range(3 * 96):
                when = T0 + _dt.timedelta(minutes=15 * step)
                theta -= 0.0004                          # drying, everywhere alike
                water_at = when - _dt.timedelta(minutes=15 * lag)
                if (not rain_only and water_at.day % 2 == 0
                        and water_at.hour == hours[really] and water_at.minute == 0):
                    theta += 0.03
                if when.minute == 0 and (
                        (when.day == T0.day + 1 and when.hour == 20)
                        or (when.day == T0.day + 2 and when.hour == 8)):
                    theta += 0.02                        # two showers, on every bed
                log.append_record(fx.observation(
                    derived, result=round(theta, 4), measured_at=when,
                    calibration=cal.id, node=None, boot=None, seq=None))
            self.ids[probe] = device.id
        self.state = P.state_from_log(log)
        self.at = T0 + _dt.timedelta(days=3)

    def assess(self, probe):
        return S.assess_lateral(self.state, self.ids[probe], self.at)

    def test_a_probe_in_its_recorded_bed_is_consistent(self):
        self._farm({})
        self.assertEqual(self.assess("a1").verdict, S.CONSISTENT)

    def test_a_probe_moved_to_another_bed_is_displaced(self):
        self._farm({"a2": "C"})
        finding = self.assess("a2")
        self.assertEqual(finding.verdict, S.DISPLACED, finding.reason)

    def test_the_bed_mate_left_behind_is_unconfirmed_not_consistent(self):
        """Its only peer is the one that moved. -0.03 is an absence of evidence, and
        the first version called it consistent."""
        self._farm({"a2": "C"})
        self.assertEqual(self.assess("a1").verdict, S.INDETERMINATE)

    def test_a_deep_probe_that_lags_its_bed_is_still_consistent(self):
        """A deep probe answers irrigation later; lockstep would be too strict."""
        self._farm({}, lag_bins={"a2": 3})
        self.assertEqual(self.assess("a2").verdict, S.CONSISTENT)

    def test_a_rain_only_window_cannot_tell_beds_apart(self):
        """Rain wets every bed at once, so it identifies none of them — and a probe
        that has really moved must not be *confirmed* by it. With two showers there
        are enough events to reach the comparison, which the first version of this
        test never did: one shower stopped it at "too few events"."""
        self._farm({"a2": "C"}, rain_only=True)
        finding = self.assess("a2")
        self.assertEqual(finding.verdict, S.INDETERMINATE, finding.reason)
        self.assertEqual(finding.key, "lateral.undiscriminating")

    def test_the_finding_renders_in_spanish(self):
        import i18n
        self._farm({"a2": "C"})
        finding = self.assess("a2")
        text = str(i18n.Translator("es").text(finding.key, **finding.params))
        self.assertIn("sin ningún registro", text)


class TestPersistence(unittest.TestCase):
    """`displaced` only when most of a week's daily assessments agree.

    Eight days of hourly readings, so seven daily 48-hour windows end at the last one.
    Day 0 is the latest window, ending at `at`; hour 0 is eight days before that."""

    HOURS = 24 * 8 + 1

    def farm(self, **kw):
        return _Farm(STANDARD, hours=self.HOURS, **kw)

    def persistent(self, farm, name="a20"):
        return S.assess_siting_persistent(farm.state, farm.ids[name], farm.at)

    def test_a_probe_where_its_record_says_stays_consistent(self):
        finding = self.persistent(self.farm())
        self.assertEqual(finding.verdict, S.CONSISTENT, finding.reason)
        self.assertEqual(finding.evidence["persistence"]["displaced"], 0)
        self.assertEqual(finding.evidence["persistence"]["decided"], 7)

    def test_a_move_held_all_week_is_displaced(self):
        farm = self.farm(physical={**STANDARD, "a20": 0.05})
        finding = self.persistent(farm)
        self.assertEqual(finding.verdict, S.DISPLACED)
        self.assertEqual(finding.evidence["persistence"]["displaced"], 7)
        self.assertAlmostEqual(finding.implied_depth_m, 0.05, delta=0.02)
        self.assertEqual(finding.at, farm.at)

    def test_a_fresh_move_is_unconfirmed_not_consistent(self):
        """Moved two days ago: today's window sees it, the week does not yet. Saying
        `consistent` here would be false; `displaced` would be premature."""
        farm = self.farm(episode={"a20": (self.HOURS - 49, self.HOURS, 0.05)})
        self.assertEqual(farm.assess("a20").verdict, S.DISPLACED)
        finding = self.persistent(farm)
        self.assertEqual(finding.verdict, S.INDETERMINATE)
        self.assertEqual(finding.key, "siting.unconfirmed")
        self.assertLess(finding.evidence["persistence"]["displaced"], 5)
        self.assertIn("of the last 7 checks", finding.reason)

    def test_a_bad_day_midweek_raises_nothing(self):
        farm = self.farm(episode={"a20": (72, 96, 0.05)})
        finding = self.persistent(farm)
        self.assertEqual(finding.verdict, S.CONSISTENT, finding.reason)
        self.assertLess(finding.evidence["persistence"]["displaced"], 5)

    def test_a_persistent_finding_flags_the_whole_span(self):
        """Readings from the first displaced day on are in doubt, not just the last
        two days of them."""
        farm = self.farm(physical={**STANDARD, "a20": 0.05})
        finding = self.persistent(farm)
        self.assertEqual(finding.evidence["window_h"], 48.0 + 6 * 24)
        flagged = S.suspect_assertions(farm.state, finding).assertions
        self.assertEqual(len(flagged), self.HOURS)

    def test_the_message_reads_in_every_shipped_language(self):
        import i18n
        farm = self.farm(episode={"a20": (self.HOURS - 49, self.HOURS, 0.05)})
        finding = self.persistent(farm)
        text = str(i18n.Translator("es").text(finding.key, **finding.params))
        self.assertIn("de las últimas 7 comprobaciones", text)


class TestWeekly(unittest.TestCase):
    """A real station's profile: one probe at each of 5, 10 and 20 cm, and one at 55 cm
    whose wave is too small to read over two days. Five weeks of hourly readings with a
    sensor's noise, so the weekly assessment has four two-week windows."""

    PROFILE = {"p05": 0.05, "p10": 0.10, "p20": 0.20, "p55": 0.55}
    HOURS = 24 * 35 + 1

    def farm(self, physical):
        return _Farm(self.PROFILE, physical={**self.PROFILE, **physical},
                     hours=self.HOURS, noise_c=0.05)

    def test_over_two_days_the_deep_probe_is_not_a_peer(self):
        farm = self.farm({})
        daily = farm.assess("p20")
        self.assertEqual(daily.peers_used, 2)
        self.assertFalse(daily.evidence["robust"])
        weekly = S.assess_siting_weekly(farm.state, farm.ids["p20"], farm.at)
        self.assertEqual(weekly.peers_used, 3)
        self.assertTrue(weekly.evidence["robust"])
        self.assertEqual(weekly.verdict, S.CONSISTENT, weekly.reason)

    def test_a_moved_neighbour_is_not_blamed_on_the_probe_extrapolated_from_it(self):
        """McAllister Farm, 2023: the 10 cm probe went in 4 cm shallow. Read daily
        against the 5 and 10 cm probes, the 20 cm probe looks far too deep and is called
        displaced, every day. Weekly, the 55 cm probe outvotes the moved one."""
        farm = self.farm({"p10": 0.06})
        daily = S.assess_siting_persistent(farm.state, farm.ids["p20"], farm.at)
        self.assertEqual(daily.verdict, S.DISPLACED)
        weekly = S.assess_siting_weekly(farm.state, farm.ids["p20"], farm.at)
        self.assertEqual(weekly.verdict, S.CONSISTENT, weekly.reason)
        self.assertAlmostEqual(weekly.implied_depth_m, 0.20, delta=0.03)

    def test_a_10_cm_push_is_called_weekly_and_not_daily(self):
        farm = self.farm({"p20": 0.30})
        daily = S.assess_siting_persistent(farm.state, farm.ids["p20"], farm.at)
        self.assertEqual(daily.verdict, S.CONSISTENT, "10 cm is inside the 12 cm two-peer tolerance")
        weekly = S.assess_siting_weekly(farm.state, farm.ids["p20"], farm.at)
        self.assertEqual(weekly.verdict, S.DISPLACED, weekly.reason)
        self.assertAlmostEqual(weekly.implied_depth_m, 0.30, delta=0.03)
        self.assertEqual(weekly.evidence["persistence"]["count"], 4)
        self.assertEqual(weekly.evidence["window_h"], 14 * 24 + 3 * 7 * 24)


class TestAttribution(unittest.TestCase):
    """Q25: a two-peer alarm names the probe whose records changed.

    McAllister Farm, 2023: a replacement 10 cm probe went in about 4 cm shallow, and
    the daily check — two peers, nothing to outvote — called the 20 cm probe
    displaced, because it is read off a line through the 5 and 10 cm probes."""

    PROFILE = {"p05": 0.05, "p10": 0.10, "p20": 0.20, "p55": 0.55}

    def farm(self, hours=24 * 8 + 1, **kw):
        return _Farm(self.PROFILE, physical={**self.PROFILE, "p10": 0.06},
                     hours=hours, noise_c=0.05, **kw)

    def judge(self, farm):
        return S.assess_siting_persistent(farm.state, farm.ids["p20"], farm.at)

    def test_the_probe_whose_records_changed_is_named(self):
        farm = self.farm()
        event = MaintenanceEvent(id=uuid7(), device=farm.ids["p10"],
                                 at=T0 - _dt.timedelta(days=3),
                                 action=MaintenanceAction.REPLACED)
        farm.log.append_record(event)
        farm.state.add(event)
        finding = self.judge(farm)
        self.assertEqual(finding.verdict, S.DISPLACED, "something did move")
        self.assertEqual(finding.key, "siting.profile_named")
        self.assertEqual(finding.evidence["attribution"]["named"], str(farm.ids["p10"]))
        self.assertEqual(finding.params["change"], "replaced")
        self.assertIn("cannot tell which moved", finding.reason)
        self.assertEqual(finding.evidence["displacement"]["key"], "siting.deeper",
                         "what the arithmetic said is kept")

    def test_with_no_record_to_go_on_it_says_so(self):
        finding = self.judge(self.farm())
        self.assertEqual(finding.verdict, S.DISPLACED)
        self.assertEqual(finding.key, "siting.profile_unnamed")
        self.assertIsNone(finding.evidence["attribution"]["named"])
        self.assertEqual(len(finding.evidence["attribution"]["profile"]), 3)

    def test_a_silence_in_a_probes_readings_counts_as_a_change(self):
        """At both Tennessee stations the 10 cm record went quiet for 18 months before
        its replacement; the silence is itself a record."""
        farm = self.farm(hours=24 * 18 + 1, silent={"p10": (24, 24 * 9)})
        finding = self.judge(farm)
        self.assertEqual(finding.key, "siting.profile_named")
        self.assertEqual(finding.params["change"], "readings resumed")

    def test_a_robust_finding_needs_no_attribution(self):
        farm = _Farm(STANDARD, physical={**STANDARD, "a20": 0.05}, hours=24 * 8 + 1)
        finding = S.assess_siting_persistent(farm.state, farm.ids["a20"], farm.at)
        self.assertTrue(finding.evidence["robust"])
        self.assertNotIn("attribution", finding.evidence)
        self.assertEqual(finding.key, "siting.shallower")

    def test_the_message_reads_in_spanish(self):
        import i18n
        farm = self.farm()
        finding = self.judge(farm)
        text = str(i18n.Translator("es").text(finding.key, **finding.params))
        self.assertIn("perfil", text)


if __name__ == "__main__":
    unittest.main()
