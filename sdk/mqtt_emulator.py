#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""What each device family really publishes on a farm, with no broker needed.

Emits `{"topic": ..., "payload": ...}` lines for `mqtt_bridge.py`. Derived from
campus_twin's `mqtt_emulator.py` (see PROVENANCE.md), with the devices moved from a
plant room to a farm and the presence-tracking messages removed.

The ChirpStack uplink uses the field names of a common LoRaWAN soil probe's published
decoder (`water_SOIL`, `temp_SOIL`, `conduct_SOIL`, `Bat`), because a bridge tested only
against invented payloads has not been tested against the thing it will meet.

    python3 mqtt_emulator.py | python3 mqtt_bridge.py --bindings b.json --dry-run
"""
from __future__ import annotations

import json
import sys

#: A LoRaWAN soil probe's device EUI, as ChirpStack names it.
FIELD_PROBE = "a84041000181c1f4"


def messages(*, vent_open: bool = True, leak: bool = False,
             soil_water_pct: float = 28.4) -> list[dict]:
    return [
        # ESPHome node in the hoop house: a number, and an ON/OFF.
        {"topic": "hoop-node/sensor/air_temperature/state", "payload": "24.5"},
        {"topic": "hoop-node/binary_sensor/vent_open/state",
         "payload": "ON" if vent_open else "OFF"},
        # Tasmota plug on the irrigation pump. `Time` is LOCAL and has no offset.
        {"topic": "tele/pump-plug/SENSOR", "payload": {
            "Time": "2026-06-15T14:00:00",
            "ENERGY": {"Power": 740.0, "Total": 211.4}}},
        {"topic": "tele/pump-plug/STATE", "payload": {"Wifi": {"RSSI": 58,
                                                               "Signal": -71}}},
        # Shelly Gen2 relay on the well pump.
        {"topic": "shelly-well/status/switch:0", "payload": {
            "id": 0, "apower": 1120.0, "voltage": 238.9,
            "temperature": {"tC": 36.1}}},
        # Zigbee2MQTT: a leak sensor under the tank, a soil sensor in the hoop house.
        {"topic": "zigbee2mqtt/tank_leak", "payload": {
            "water_leak": leak, "battery": 91, "linkquality": 88}},
        {"topic": "zigbee2mqtt/hoop_soil", "payload": {
            "soil_moisture": 31, "temperature": 21.4, "battery": 77,
            "linkquality": 120}},
        {"topic": "zigbee2mqtt/bridge/state", "payload": {"state": "online"}},
        # Home Assistant statestream: a rain gauge's daily total.
        {"topic": "homeassistant/sensor/rain_gauge_daily/state", "payload": "4.2"},
        # ChirpStack v4 uplink from a field soil probe, decoded.
        {"topic": f"application/3/device/{FIELD_PROBE}/event/up", "payload": {
            "deviceInfo": {"devEui": FIELD_PROBE},
            "time": "2026-06-15T19:00:00Z",
            "object": {"water_SOIL": soil_water_pct, "temp_SOIL": 19.6,
                       "conduct_SOIL": 412, "Bat": 3.58},
            "rxInfo": [{"rssi": -112, "snr": 4.5}]}},
        # OpenSprinkler on the beds' drip zones, as its firmware publishes: zone 3 opens
        # for its 90 scheduled minutes and closes with its flow; the rain delay ends.
        {"topic": "opensprinkler/station/3", "payload": {"state": 1, "duration": 5400}},
        {"topic": "opensprinkler/station/3", "payload": {"state": 0, "duration": 5400,
                                                         "flow": 2.41}},
        {"topic": "opensprinkler/raindelay", "payload": {"state": 0}},
        {"topic": "opensprinkler/weather", "payload": {"water level": 84}},
        {"topic": "opensprinkler/availability", "payload": "online"},
        {"topic": "some/other/thing", "payload": "ignored"},
    ]


def main() -> int:
    for message in messages():
        sys.stdout.write(json.dumps(message) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
