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


class TestOpenSprinkler(unittest.TestCase):
    """An irrigation controller's valves into the log (docs/notes/irrigation-projects.md),
    from the messages its firmware formats in services/notifier.cpp."""

    def setUp(self):
        self.farm = _Farm(["zone3", "zone3_ran", "rain_delay", "scale"])
        self.farm.streams["zone3"] = self._truth("zone3")
        self.farm.streams["rain_delay"] = self._truth("rain_delay")
        spec = {"uncertainty_s": 5.0, "points": {
            "station.3.open": "zone3", "station.3.ran_s": "zone3_ran",
            "raindelay": "rain_delay", "water_level": "scale"}}
        self.bridge = B.Bridge(self.farm.log, self.farm.state,
                               _bindings(self.farm, **{"opensprinkler:opensprinkler": spec}))

    def _truth(self, name):
        ds = fx.raw_datastream(unit=None)
        self.farm.log.append_record(ds)
        self.farm.state.add(ds)
        return ds

    def test_a_valve_opening_and_closing_is_a_truth_then_its_run_time(self):
        opened = ARRIVED
        closed = ARRIVED + _dt.timedelta(minutes=90)
        self.assertEqual(self.bridge.handle("opensprinkler/station/3",
                                            '{"state":1,"duration":5400}', arrived=opened), 1)
        self.assertEqual(self.bridge.handle("opensprinkler/station/3",
                                            '{"state":0,"duration":5400,"flow":2.41}',
                                            arrived=closed), 2)
        self.assertEqual([(o.measured_at, o.result) for o in self.farm.rows("zone3")],
                         [(opened, True), (closed, False)])
        [ran] = self.farm.rows("zone3_ran")
        self.assertEqual(ran.result, 5400)
        self.assertTrue(ran.provenance["stamped_on_arrival"], "its messages carry no time")

    def test_the_rest_it_says_lands_where_it_is_bound(self):
        self.bridge.handle("opensprinkler/raindelay", '{"state":1}', arrived=ARRIVED)
        self.bridge.handle("opensprinkler/weather", '{"water level":84}', arrived=ARRIVED)
        self.bridge.handle("opensprinkler/availability", "online", arrived=ARRIVED)
        self.assertIs(self.farm.rows("rain_delay")[0].result, True)
        self.assertEqual(self.farm.rows("scale")[0].result, 84)
        self.assertEqual(self.bridge.report.unusable_value, 0)

    def test_parsed_as_the_firmware_formats_it(self):
        parse = lambda topic, payload: B.parse("opensprinkler", topic, payload)
        self.assertEqual(parse("opensprinkler/station/12", {"state": 1, "duration": 600})["points"],
                         {"station.12.open": True, "station.12.scheduled_s": 600})
        self.assertEqual(parse("opensprinkler/sensor/flow", {"count": 120, "volume": 31.5})["points"],
                         {"flow.count": 120, "flow.volume": 31.5})
        self.assertEqual(parse("opensprinkler/station/3/alert/flow",
                               {"flow_rate": 9.5, "duration": 300, "alert_setpoint": 6.0})["points"],
                         {"station.3.alert_flow_rate": 9.5})
        self.assertEqual(parse("opensprinkler/sensor2", {"state": 1})["points"], {"sensor2": True})
        self.assertIsNone(parse("opensprinkler/system", {"reboot": 1}))

    def test_a_program_run_or_skipped_with_the_scales_it_ran_at(self):
        """As 2.2.1(6)'s notifier formats them (`NOTIFY_PROGRAM_SCHED`): `wl` an integer
        percentage, the scales `%.4g`."""
        parse = lambda topic, text: B.parse("opensprinkler", topic, json.loads(text))
        self.assertEqual(parse("opensprinkler/program/2",
                               '{"state":1,"wl":84,"wa":0.84,"sa":0.5,"ta":0.42}')["points"],
                         {"program.2.ran": True, "program.2.water_level": 84,
                          "program.2.sensor_scale": 0.5, "program.2.total_scale": 0.42})
        self.assertEqual(parse("opensprinkler/program/0", '{"state":"skipped","wtrestr":1}')["points"],
                         {"program.0.ran": False, "program.0.weather_restricted": True})
        self.assertEqual(parse("opensprinkler/program/0", '{"state":"skipped","wtrestr":0}')["points"],
                         {"program.0.ran": False, "program.0.weather_restricted": False},
                         "skipped at a 0% watering level, not by a restriction")

    def test_a_controller_under_its_own_root_topic(self):
        self.assertIsNone(B.detect("farm/os1/station/3"))
        self.assertEqual(B.detect("farm/os1/station/3", {"opensprinkler": "farm/os1"}), "opensprinkler")
        parsed = B.parse("opensprinkler", "farm/os1/station/3", {"state": 0, "duration": 60},
                         {"opensprinkler": "farm/os1"})
        self.assertEqual((parsed["device"], parsed["points"]["station.3.ran_s"]), ("farm/os1", 60))


class TestRtl433(unittest.TestCase):
    """A cheap weather station heard off the air by rtl_433 on the gateway, as its MQTT
    events topic carries it (docs/notes/weather-stations.md)."""

    EVENT = next(m for m in E.messages() if m["topic"] == "rtl_433/gateway/events")

    def bridge(self, *, timezone=None, payload=None):
        farm = _Farm(["air", "rain", "gust", "signal"])
        spec = {"uncertainty_s": 60.0, "points": {
            "temperature_C": "air", "rain_mm": "rain", "wind_max_m_s": "gust",
            "rssi": "signal"}}
        if timezone:
            spec["timezone"] = timezone
        bridge = B.Bridge(farm.log, farm.state,
                          _bindings(farm, **{"rtl_433:Fineoffset-WH65B-117": spec}))
        written = bridge.handle(self.EVENT["topic"], payload or self.EVENT["payload"],
                                arrived=ARRIVED)
        return farm, bridge, written

    def test_parsed_with_the_decoders_own_names(self):
        parsed = B.parse("rtl_433", self.EVENT["topic"], self.EVENT["payload"])
        self.assertEqual(parsed["device"], "Fineoffset-WH65B-117")
        self.assertEqual(set(parsed["points"]),
                         {"battery_ok", "temperature_C", "humidity", "wind_dir_deg",
                          "wind_avg_m_s", "wind_max_m_s", "rain_mm", "uv", "uvi", "light_lux"})
        self.assertEqual(parsed["health"], {"rssi": -6.2, "snr": 21.3})

    def test_epoch_seconds_are_the_readings_own_time(self):
        farm, bridge, written = self.bridge()
        self.assertEqual(written, 4)
        [air] = farm.rows("air")
        self.assertEqual((air.measured_at, air.result),
                         (_dt.datetime(2026, 6, 15, 19, tzinfo=UTC), 27.4))
        self.assertFalse(air.provenance["stamped_on_arrival"])
        self.assertEqual(farm.rows("signal")[0].result, -6.2)

    def test_its_default_local_time_needs_the_stations_zone(self):
        local = dict(self.EVENT["payload"], time="2026-06-15 14:00:00")
        farm, bridge, _ = self.bridge(payload=local)
        self.assertEqual(farm.rows("air")[0].measured_at, ARRIVED)
        self.assertEqual(bridge.report.stamped_on_arrival, 1)
        farm, _, _ = self.bridge(payload=local, timezone="America/Chicago")
        self.assertEqual(farm.rows("air")[0].measured_at, _dt.datetime(2026, 6, 15, 19, tzinfo=UTC))

    def test_a_station_with_new_batteries_and_a_new_id_arrives_unbound_and_named(self):
        farm, bridge, written = self.bridge(payload=dict(self.EVENT["payload"], id=42))
        self.assertEqual(written, 0)
        self.assertIn("rtl_433:Fineoffset-WH65B-42", str(bridge.report.unbound_devices))

    def test_under_its_own_root_and_only_its_events_topic(self):
        self.assertIsNone(B.detect("rtl_433/gateway/states"))
        self.assertIsNone(B.detect("rtl_433/gateway/devices/Fineoffset-WH65B/117/temperature_C"))
        self.assertEqual(B.detect("farm/radio/pi/events", {"rtl_433": "farm/radio"}), "rtl_433")


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
