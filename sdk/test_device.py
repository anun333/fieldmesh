#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for §4.1's device record, its siting history and its maintenance log."""
from __future__ import annotations

import datetime as _dt
import unittest

import codec
import fixtures as fx
import log as L
import project as P
from ids import uuid7
from model import (Device, DeviceKind, Installation, MaintenanceAction,
                   MaintenanceEvent)

UTC = _dt.timezone.utc


def when(month: int, day: int = 1) -> _dt.datetime:
    return _dt.datetime(2026, month, day, 12, 0, tzinfo=UTC)


class TestDevice(unittest.TestCase):

    def test_an_undeclared_capability_is_unknown_not_false(self):
        """§6.3 branches on this. A node that cannot persist its dedup table across a
        reboot has to *say so*, and silence is not the same as saying no."""
        bare = Device(id=uuid7(), kind=DeviceKind.NODE, site=uuid7())
        self.assertIsNone(bare.dedup_volatile)
        self.assertIsNone(bare.confirms_delivery)
        self.assertEqual(bare.safe_states, {})

        declared = Device(id=uuid7(), kind=DeviceKind.NODE, site=uuid7(),
                          capabilities={"dedup_volatile": False})
        self.assertIs(declared.dedup_volatile, False)

    def test_provenance_carries_only_what_is_set(self):
        device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=uuid7(),
                        firmware="1.4.2")
        self.assertEqual(device.provenance(), {"firmware": "1.4.2"})

    def test_safe_states_must_be_a_mapping_to_be_believed(self):
        device = Device(id=uuid7(), kind=DeviceKind.NODE, site=uuid7(),
                        capabilities={"safe_states": "closed"})
        self.assertEqual(device.safe_states, {})

    def test_kind_is_an_enum(self):
        with self.assertRaises(TypeError):
            Device(id=uuid7(), kind="node", site=uuid7())


class TestInstallation(unittest.TestCase):

    def test_depth_is_positive_downwards(self):
        """A sign convention nobody states is one somebody gets wrong."""
        with self.assertRaises(ValueError) as caught:
            Installation(id=uuid7(), device=uuid7(), feature=uuid7(),
                         installed_at=when(3), depth_m=-0.2)
        self.assertIn("positive downwards", str(caught.exception))

    def test_orientation_is_a_compass_azimuth(self):
        Installation(id=uuid7(), device=uuid7(), feature=uuid7(),
                     installed_at=when(3), orientation_deg=359.9)
        for bad in (360.0, -1.0):
            with self.assertRaises(ValueError, msg=bad):
                Installation(id=uuid7(), device=uuid7(), feature=uuid7(),
                             installed_at=when(3), orientation_deg=bad)

    def test_removal_must_follow_installation(self):
        with self.assertRaises(ValueError):
            Installation(id=uuid7(), device=uuid7(), feature=uuid7(),
                         installed_at=when(6), removed_at=when(3))

    def test_the_interval_is_half_open(self):
        """So a move does not produce an instant two installations both claim."""
        one = Installation(id=uuid7(), device=uuid7(), feature=uuid7(),
                           installed_at=when(3), removed_at=when(6))
        self.assertTrue(one.covers(when(3)))
        self.assertTrue(one.covers(when(5)))
        self.assertFalse(one.covers(when(6)))
        self.assertFalse(one.covers(when(2)))

    def test_an_open_installation_covers_everything_after_it(self):
        open_ = Installation(id=uuid7(), device=uuid7(), feature=uuid7(),
                             installed_at=when(3))
        self.assertTrue(open_.covers(when(12, 31)))


class TestCodecRoundTrip(unittest.TestCase):

    def test_all_three_types_round_trip(self):
        device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=uuid7(),
                        model="TEROS-12", serial="SN-9",
                        capabilities={"dedup_volatile": True,
                                      "safe_states": {"valve": "closed"}})
        records = [
            device,
            Installation(id=uuid7(), device=device.id, feature=uuid7(),
                         installed_at=when(3), depth_m=0.2, orientation_deg=180.0,
                         note="bed1 shallow"),
            MaintenanceEvent(id=uuid7(), device=device.id, at=when(7),
                             action=MaintenanceAction.CLEANED, note="silt"),
        ]
        for record in records:
            with self.subTest(kind=type(record).__name__):
                self.assertEqual(codec.load(codec.dump(record)), record)

    def test_they_survive_a_log_replay(self):
        log = L.Log()
        device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=uuid7())
        log.append_record(device)
        log.append_record(Installation(id=uuid7(), device=device.id,
                                       feature=uuid7(), installed_at=when(3)))
        log.append_record(MaintenanceEvent(id=uuid7(), device=device.id, at=when(7),
                                           action=MaintenanceAction.MOVED))
        state = P.state_from_log(log)
        self.assertIn(device.id, state.devices)
        self.assertEqual(len(state.installations), 1)
        self.assertEqual(len(state.maintenance), 1)
        self.assertEqual(state.validate(), [])


class TestMovedAndReinstalled(unittest.TestCase):
    """The case the completeness matrix had been skipping for want of a Device type."""

    def setUp(self):
        self.log = L.Log()
        self.site = uuid7()
        self.device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=self.site,
                             model="TEROS-12", firmware="1.4.2")
        self.bed1, self.bed4 = uuid7(), uuid7()
        self.log.append_record(self.device)

        # Installed in bed1 at 20 cm in March, lifted in June, reinstalled in bed4
        # at 40 cm facing south. Closing the first installation is a re-append of the
        # same id with `removed_at` set — the same pattern recalibration uses.
        self.first = Installation(id=uuid7(), device=self.device.id,
                                  feature=self.bed1, installed_at=when(3),
                                  depth_m=0.20)
        self.log.append_record(self.first)
        self.closed = Installation(id=self.first.id, device=self.device.id,
                                   feature=self.bed1, installed_at=when(3),
                                   removed_at=when(6), depth_m=0.20)
        self.second = Installation(id=uuid7(), device=self.device.id,
                                   feature=self.bed4, installed_at=when(6),
                                   depth_m=0.40, orientation_deg=180.0)
        self.log.append_record(self.closed)
        self.log.append_record(self.second)
        self.log.append_record(MaintenanceEvent(
            id=uuid7(), device=self.device.id, at=when(6),
            action=MaintenanceAction.MOVED, note="bed1 -> bed4, 20cm -> 40cm"))
        self.state = P.state_from_log(self.log)

    def test_the_state_is_clean(self):
        self.assertEqual(self.state.validate(), [])

    def test_where_it_was_depends_on_when_you_ask(self):
        """The reason installations carry dates at all: "how deep was this probe when
        it took that reading" is unanswerable from a field overwritten on every move.
        """
        april = self.state.installation_of(self.device.id, when(4))
        july = self.state.installation_of(self.device.id, when(7))
        self.assertEqual(april.feature, self.bed1)
        self.assertEqual(april.depth_m, 0.20)
        self.assertEqual(july.feature, self.bed4)
        self.assertEqual(july.depth_m, 0.40)

    def test_before_installation_it_was_nowhere(self):
        self.assertIsNone(self.state.installation_of(self.device.id, when(1)))

    def test_the_move_instant_belongs_to_exactly_one_installation(self):
        at_move = self.state.installation_of(self.device.id, when(6))
        self.assertEqual(at_move.feature, self.bed4)

    def test_the_siting_history_is_both_installations(self):
        history = self.state.installations_of(self.device.id)
        self.assertEqual([i.feature for i in history], [self.bed1, self.bed4])

    def test_the_maintenance_log_records_that_it_happened(self):
        events = self.state.maintenance_of(self.device.id)
        self.assertEqual([e.action for e in events], [MaintenanceAction.MOVED])

    def test_an_unclosed_first_installation_is_reported_as_overlapping(self):
        """If nobody closes the old installation, two of them cover July — and the
        depth question has two answers, which is worse than none."""
        log = L.Log()
        log.append_record(self.device)
        log.append_record(Installation(id=uuid7(), device=self.device.id,
                                       feature=self.bed1, installed_at=when(3)))
        log.append_record(Installation(id=uuid7(), device=self.device.id,
                                       feature=self.bed4, installed_at=when(6)))
        state = P.state_from_log(log)
        problems = state.validate()
        self.assertTrue(any("overlap" in p for p in problems), problems)
        with self.assertRaises(P.ProjectionError):
            state.installation_of(self.device.id, when(7))


class TestDeviceView(unittest.TestCase):
    """§4.1's "last seen and the current boot counter" — derived, never stored."""

    def setUp(self):
        self.log = L.Log()
        self.device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=uuid7(),
                             model="TEROS-12")
        self.log.append_record(self.device)
        self.feature = uuid7()
        self.log.append_record(Installation(
            id=uuid7(), device=self.device.id, feature=self.feature,
            installed_at=when(3), depth_m=0.2))
        self.ds = fx.raw_datastream(sensor=self.device.id, feature=self.feature)
        self.log.append_record(self.ds)
        for i in range(5):
            self.log.append_record(fx.observation(
                datastream=self.ds, result=0.2, measured_at=fx.at(i * 15),
                node="n1", boot=7, seq=i))
        self.log.append_record(MaintenanceEvent(
            id=uuid7(), device=self.device.id, at=when(5),
            action=MaintenanceAction.CLEANED))
        self.state = P.state_from_log(self.log)
        self.view = self.state.device_view(self.device.id)

    def test_it_finds_the_datastreams_the_device_feeds(self):
        self.assertEqual([d.id for d in self.view.datastreams], [self.ds.id])

    def test_last_seen_and_boot_come_from_the_readings(self):
        self.assertIsNotNone(self.view.last_seen)
        self.assertEqual(self.view.boot, 7)

    def test_it_knows_where_the_device_is_and_how_deep(self):
        self.assertEqual(self.view.feature, self.feature)
        self.assertEqual(self.view.depth_m, 0.2)

    def test_last_action_answers_the_certifier_question(self):
        self.assertEqual(self.view.last_action(MaintenanceAction.CLEANED), when(5))
        self.assertIsNone(self.view.last_action(MaintenanceAction.REPLACED))

    def test_a_device_with_no_readings_has_no_last_seen_rather_than_a_guess(self):
        lonely = Device(id=uuid7(), kind=DeviceKind.NODE, site=uuid7())
        log = L.Log()
        log.append_record(lonely)
        view = P.state_from_log(log).device_view(lonely.id)
        self.assertIsNone(view.last_seen)
        self.assertIsNone(view.boot)
        self.assertIsNone(view.installation)

    def test_an_unknown_device_raises_rather_than_returning_an_empty_view(self):
        with self.assertRaises(KeyError):
            self.state.device_view(uuid7())

    def test_the_sensor_index_survives_a_datastream_being_reappended(self):
        """A datastream is keyed by id and last-write-wins, so an index maintained
        incrementally in `add` would list it twice."""
        self.log.append_record(self.ds)
        state = P.state_from_log(self.log)
        self.assertEqual(len(state.datastreams_of_sensor(self.device.id)), 1)


if __name__ == "__main__":
    unittest.main()


class TestMultiChannelCalibration(unittest.TestCase):
    """One device, two channels, two calibrations — the case that silently derived
    every moisture reading on twelve probes with the temperature coefficients."""

    def setUp(self):
        from model import Calibration
        self.Calibration = Calibration
        self.sensor = uuid7()
        self.moisture = fx.raw_datastream(sensor=self.sensor)
        # Declared under the soil-temperature term. The first version of this test
        # put a Celsius channel under the soil-moisture term, and the vocabulary gate
        # caught it the moment it existed — the unit lie §3.4 forbids, in a test.
        import vocab as V
        self.temperature = fx.raw_datastream(sensor=self.sensor, unit="Cel",
                                             observed_property=V.SOIL_TEMPERATURE)
        self.cal_m = Calibration(id=uuid7(), sensor=self.sensor,
                                 datastream=self.moisture.id, method="linear",
                                 valid_from=when(1), coefficients={"a": 0.001})
        self.cal_t = Calibration(id=uuid7(), sensor=self.sensor,
                                 datastream=self.temperature.id, method="linear",
                                 valid_from=when(2), coefficients={"a": 0.1})
        self.cals = [self.cal_m, self.cal_t]

    def test_each_channel_gets_its_own_calibration(self):
        self.assertIs(P.calibration_for(self.cals, self.sensor, when(6),
                                        self.moisture.id), self.cal_m)
        self.assertIs(P.calibration_for(self.cals, self.sensor, when(6),
                                        self.temperature.id), self.cal_t)

    def test_the_later_calibration_does_not_win_for_the_other_channel(self):
        """The defect: by sensor alone, the later `valid_from` was applied to both."""
        chosen = P.calibration_for(self.cals, self.sensor, when(6), self.moisture.id)
        self.assertEqual(chosen.coefficients["a"], 0.001)

    def test_two_channels_calibrations_are_not_an_overlap(self):
        self.assertEqual(P.overlapping_calibrations(self.cals, self.sensor,
                                                    self.moisture.id), [])
        log = L.Log()
        for record in (self.moisture, self.temperature, *self.cals):
            log.append_record(record)
        self.assertEqual(P.state_from_log(log).validate(), [])

    def test_a_channel_specific_calibration_beats_a_sensor_wide_one(self):
        general = self.Calibration(id=uuid7(), sensor=self.sensor, method="linear",
                                   valid_from=when(4), coefficients={"a": 9.0})
        chosen = P.calibration_for([*self.cals, general], self.sensor, when(6),
                                   self.moisture.id)
        self.assertIs(chosen, self.cal_m)

    def test_a_single_channel_device_still_uses_a_sensor_wide_calibration(self):
        """`datastream=None` keeps the old behaviour for the common case."""
        general = self.Calibration(id=uuid7(), sensor=self.sensor, method="linear",
                                   valid_from=when(1), coefficients={"a": 0.5})
        self.assertIs(P.calibration_for([general], self.sensor, when(6),
                                        self.moisture.id), general)

    def test_a_calibration_for_another_channel_never_applies(self):
        self.assertIsNone(P.calibration_for([self.cal_t], self.sensor, when(6),
                                            self.moisture.id))

    def test_overlap_within_one_channel_is_still_reported(self):
        clash = self.Calibration(id=uuid7(), sensor=self.sensor,
                                 datastream=self.moisture.id, method="linear",
                                 valid_from=when(3), coefficients={"a": 0.002})
        self.assertEqual(len(P.overlapping_calibrations(
            [self.cal_m, clash], self.sensor, self.moisture.id)), 1)

    def test_the_scope_round_trips(self):
        self.assertEqual(codec.load(codec.dump(self.cal_m)), self.cal_m)
