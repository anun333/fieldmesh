#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for the MQTT bridge, against the emulator's realistic farm traffic."""
from __future__ import annotations

import datetime as _dt
import json
import unittest

import fixtures as fx
import log as L
import mqtt_bridge as B
import mqtt_emulator as E
import project as P

UTC = _dt.timezone.utc
ARRIVED = _dt.datetime(2026, 6, 15, 19, 0, 30, tzinfo=UTC)


class _Farm:
    def __init__(self, names):
        self.log = L.Log()
        self.streams = {}
        for name in names:
            unit = None if name in ("vent", "leak") else "1"
            ds = fx.raw_datastream(unit=unit)
            self.log.append_record(ds)
            self.streams[name] = ds
        self.state = P.state_from_log(self.log)

    def rows(self, name):
        return self.state.live_observations_of(self.streams[name].id)


def _bindings(farm, **devices):
    return {"devices": {
        key: {**{k: v for k, v in spec.items() if k != "points"},
              "points": {point: {"datastream": str(farm.streams[stream].id)}
                         for point, stream in spec["points"].items()}}
        for key, spec in devices.items()}}


class TestProfiles(unittest.TestCase):

    def test_every_emulated_family_is_recognised(self):
        seen = {B.detect(m["topic"]) for m in E.messages()}
        self.assertTrue(set(B.PROFILES) <= seen)

    def test_presence_tracking_is_not_a_profile(self):
        """A BLE room receiver exists to see people's phones walk past."""
        self.assertIsNone(B.detect("espresense/devices/irk:phone/shed"))

    def test_on_off_becomes_a_boolean_not_a_number(self):
        self.assertIs(B.value_of("ON"), True)
        self.assertIs(B.value_of("closed"), False)
        self.assertIsNone(B.value_of("nan"))


class TestChirpStack(unittest.TestCase):
    """The profile that matters most: a LoRaWAN soil probe in a field."""

    def setUp(self):
        self.farm = _Farm(["water", "rssi"])
        self.bridge = B.Bridge(self.farm.log, self.farm.state, _bindings(
            self.farm, **{f"chirpstack:{E.FIELD_PROBE}": {
                "uncertainty_s": 2.0, "timezone": "UTC",
                "points": {"water_SOIL": "water", "rssi": "rssi"}}}))
        for m in E.messages():
            self.bridge.handle(m["topic"], m["payload"], arrived=ARRIVED)

    def test_the_bound_points_are_written_with_the_uplinks_own_time(self):
        rows = self.farm.rows("water")
        self.assertEqual(rows[0].result, 28.4)
        self.assertEqual(rows[0].measured_at, _dt.datetime(2026, 6, 15, 19, tzinfo=UTC))

    def test_link_health_is_an_ordinary_bindable_datastream(self):
        """§4.3: signal is a datastream, not a side channel."""
        self.assertEqual(self.farm.rows("rssi")[0].result, -112)

    def test_unbound_points_on_a_bound_device_are_ignored(self):
        self.assertEqual(self.bridge.report.written, 2)

    def test_unbound_devices_are_named_so_setup_can_be_debugged(self):
        self.assertIn("tasmota:pump-plug", self.bridge.report.unbound_devices)

    def test_a_redelivered_message_is_not_written_twice(self):
        """MQTT at QoS 1 delivers at least once."""
        for m in E.messages():
            self.bridge.handle(m["topic"], m["payload"], arrived=ARRIVED)
        self.assertEqual(len(self.farm.rows("water")), 1)
        self.assertGreater(self.bridge.report.already_present, 0)


class TestTimestampsWithNoZone(unittest.TestCase):
    """Tasmota's Time is local and has no offset. Upstream read it in whatever zone
    the host machine happened to be in."""

    def bridge(self, timezone):
        farm = _Farm(["power"])
        spec = {"uncertainty_s": 30.0, "points": {"ENERGY.Power": "power"}}
        if timezone:
            spec["timezone"] = timezone
        bridge = B.Bridge(farm.log, farm.state,
                          _bindings(farm, **{"tasmota:pump-plug": spec}))
        message = next(m for m in E.messages() if m["topic"] == "tele/pump-plug/SENSOR")
        bridge.handle(message["topic"], message["payload"], arrived=ARRIVED)
        return farm.rows("power")[0], bridge.report

    def test_with_a_declared_zone_the_local_time_is_converted(self):
        row, _ = self.bridge("America/Chicago")
        self.assertEqual(row.measured_at, _dt.datetime(2026, 6, 15, 19, tzinfo=UTC))

    def test_without_one_it_is_stamped_on_arrival_and_counted(self):
        row, report = self.bridge(None)
        self.assertEqual(row.measured_at, ARRIVED)
        self.assertEqual(report.stamped_on_arrival, 1)
        self.assertTrue(row.provenance["stamped_on_arrival"])


class TestBindingsAreChecked(unittest.TestCase):

    def setUp(self):
        self.farm = _Farm(["water"])

    def make(self, **spec):
        return B.Bridge(self.farm.log, self.farm.state, _bindings(
            self.farm, **{f"chirpstack:{E.FIELD_PROBE}": spec}))

    def test_uncertainty_is_required(self):
        with self.assertRaises(B.BindingError):
            self.make(points={"water_SOIL": "water"})

    def test_scale_is_refused(self):
        bindings = _bindings(self.farm, **{f"chirpstack:{E.FIELD_PROBE}": {
            "uncertainty_s": 2.0, "points": {"water_SOIL": "water"}}})
        bindings["devices"][f"chirpstack:{E.FIELD_PROBE}"]["points"][
            "water_SOIL"]["scale"] = 0.01
        with self.assertRaises(B.BindingError):
            B.Bridge(self.farm.log, self.farm.state, bindings)

    def test_an_unknown_profile_is_refused(self):
        with self.assertRaises(B.BindingError):
            B.Bridge(self.farm.log, self.farm.state,
                     {"devices": {"espresense:x": {"uncertainty_s": 1, "points": {}}}})


class TestFeed(unittest.TestCase):

    def test_mosquitto_sub_json_lines_feed_straight_in(self):
        """`mosquitto_sub -F '%j'` writes JSON with `topic` and a string `payload` —
        the live path, with no MQTT library in the SDK."""
        farm = _Farm(["water"])
        bridge = B.Bridge(farm.log, farm.state, _bindings(
            farm, **{f"chirpstack:{E.FIELD_PROBE}": {
                "uncertainty_s": 2.0, "points": {"water_SOIL": "water"}}}))
        uplink = next(m for m in E.messages() if m["topic"].startswith("application"))
        line = json.dumps({"tst": "2026-06-15T19:00:01Z", "topic": uplink["topic"],
                           "qos": 1, "retain": 0,
                           "payload": json.dumps(uplink["payload"])})
        report = bridge.feed([line, "not json", ""])
        self.assertEqual(report.written, 1)
        self.assertEqual(farm.state.validate(), [])


if __name__ == "__main__":
    unittest.main()
