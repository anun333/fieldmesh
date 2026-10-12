#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""MQTT into the log — one adapter for the device families that already publish there.

Most cheap sensors already speak MQTT and differ only in topic shape and payload: a
greenhouse ESPHome node, a Tasmota plug on the irrigation pump, a Shelly relay, a Zigbee
soil sensor, a Home Assistant entity, an **OpenSprinkler** irrigation controller opening and
closing its valves, the cheap weather stations and rain gauges **`rtl_433`** hears on 433,
868 and 915 MHz, and — the one that matters most for fields — a **ChirpStack v4**
LoRaWAN uplink, which is what a farm gateway will commonly be running. Each profile below
knows one family's shape. A family whose root topic is not its default names it in the
bindings: `{"prefixes": {"opensprinkler": "farm/os1"}, "devices": …}`.

Derived from campus_twin's `mqtt_bridge.py` (see PROVENANCE.md). The profile parsers
are the same; what they feed is not, and four rules changed on the way:

* **The binding is the allowlist, and it binds to datastreams.** A message from a device
  nobody bound, or a point on it nobody bound, is skipped and counted — and the unbound
  devices are reported by id, because "why is nothing arriving?" during setup is almost
  always "it is arriving under a name you did not bind".
* **No scale, offset or invert.** Values land as published on a raw datastream; any
  conversion is a calibration (§3.2), versioned and visible. Booleans stay booleans —
  ON/OFF is a truth observation, not `1.0`.
* **A timestamp with no zone is not guessed.** Tasmota's `Time` is local and carries no
  offset. Upstream parsed it with `fromisoformat` and called `.timestamp()`, which reads a
  naive time in *the host machine's* zone — so one message got different timestamps on
  different machines. Here a naive stamp needs the binding's `timezone`, or the reading is
  stamped on arrival instead and counted.
* **Uncertainty is declared, not invented.** A reading stamped on arrival carries the
  binding's `uncertainty_s`, which must cover the platform's own latency (§2).

ESPresense, upstream's BLE room-presence profile, is gone: it exists to see people's
phones walk past, and a farm deployment has no business doing that.

No MQTT library is required. Feed it JSON lines on stdin from
the emulator, or from a real broker with the Mosquitto client:

    python3 mqtt_emulator.py | python3 mqtt_bridge.py --bindings b.json --dry-run
    mosquitto_sub -h gateway.local -t '#' -F '%j' | python3 mqtt_bridge.py --bindings b.json --log farm.jsonl
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from dataclasses import dataclass, field
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import project as P
from ids import uuid7
from model import ClockQuality, DatastreamKind, Observation

UTC = _dt.timezone.utc

PROFILES = ("esphome", "tasmota", "shelly", "zigbee2mqtt", "ha", "chirpstack", "opensprinkler",
            "rtl_433")
#: Families that do not publish over MQTT but speak their own local protocol, read by
#: `station_adapters.py` and written here by the same bindings and rules.
DIRECT = ("tempest", "weatherlink", "ecowitt")
DEFAULT_PREFIXES = {"zigbee2mqtt": "zigbee2mqtt", "ha": "homeassistant",
                    "opensprinkler": "opensprinkler", "rtl_433": "rtl_433"}
#: Link-health keys a profile reports beside its points. Bindable like any point —
#: §4.3 makes signal and battery ordinary datastreams, not a side channel.
HEALTH_KEYS = ("rssi", "snr", "battery", "linkquality")


class BindingError(ValueError):
    """The bindings cannot be used. Raised before anything is written."""


# ------------------------------------------------------------ recognise and parse

def detect(topic: str, prefixes: dict | None = None) -> str | None:
    """Which family published this topic, or None if it is not one of ours."""
    px = {**DEFAULT_PREFIXES, **(prefixes or {})}
    t = topic.split("/")
    root = px["opensprinkler"].split("/")
    if t[:len(root)] == root and len(t) > len(root):
        return "opensprinkler"
    root = px["rtl_433"].split("/")
    if t[:len(root)] == root and len(t) == len(root) + 2 and t[-1] == "events":
        return "rtl_433"
    if t[0] == px["zigbee2mqtt"] and len(t) == 2 and t[1] != "bridge":
        return "zigbee2mqtt"
    if t[0] == px["ha"] and len(t) == 4 and t[3] == "state":
        return "ha"
    if t[0] == "tele" and len(t) == 3 and t[2] in ("SENSOR", "STATE"):
        return "tasmota"
    if (t[0] == "application" and len(t) == 6 and t[2] == "device"
            and t[4:] == ["event", "up"]):
        return "chirpstack"
    if len(t) == 4 and t[1] in ("sensor", "binary_sensor") and t[3] == "state":
        return "esphome"
    if len(t) == 3 and t[1] == "status":
        return "shelly"
    return None


def _flat(d, prefix=""):
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flat(v, key + "."))
        else:
            out[key] = v
    return out


_TRUE = ("on", "true", "open", "wet", "detected", "home")
_FALSE = ("off", "false", "closed", "dry", "clear", "not_home")


def value_of(v):
    """A payload value as a result: a number, a boolean, or None if it is neither.

    ON/OFF and friends become **booleans**, not 1.0 and 0.0. A truth observation is a
    different kind of thing from a measurement (§3.4: a boolean datastream has no
    unit), and coding it as a number loses that.
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v if v == v else None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        try:
            number = float(s)
        except ValueError:
            return None
        return number if number == number else None
    return None


def _payload(raw):
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def parse(profile: str, topic: str, raw, prefixes: dict | None = None) -> dict | None:
    """`(profile, topic, payload)` -> `{device, points, health, stamp}`, or None.

    `stamp` is the payload's own time string, untouched; deciding what it means is
    the binding's job, because only the binding knows the device's timezone.
    """
    t = topic.split("/")
    p = _payload(raw)
    if profile == "opensprinkler":
        return _opensprinkler({**DEFAULT_PREFIXES, **(prefixes or {})}["opensprinkler"], t, p)
    if profile == "rtl_433":
        return _rtl_433(p)
    if profile == "esphome":
        return {"device": t[0], "points": {t[2]: p}, "health": {}, "stamp": None}
    if profile == "tasmota":
        if not isinstance(p, dict):
            return None
        flat = _flat(p)
        if t[2] == "STATE":
            health = {"rssi": flat["Wifi.Signal"]} if "Wifi.Signal" in flat else {}
            return {"device": t[1], "points": {}, "health": health, "stamp": None}
        stamp = flat.pop("Time", None)
        return {"device": t[1], "points": flat, "health": {}, "stamp": stamp}
    if profile == "shelly":
        if not isinstance(p, dict):
            return None
        return {"device": t[0], "points": _flat(p, t[2] + "."), "health": {},
                "stamp": None}
    if profile == "zigbee2mqtt":
        if not isinstance(p, dict):
            return None
        flat = _flat(p)
        health = {k: flat.pop(k) for k in ("linkquality", "battery") if k in flat}
        return {"device": t[1], "points": flat, "health": health, "stamp": None}
    if profile == "ha":
        return {"device": f"{t[1]}.{t[2]}", "points": {"state": p}, "health": {},
                "stamp": None}
    if profile == "chirpstack":
        if not isinstance(p, dict):
            return None
        device = (p.get("deviceInfo") or {}).get("devEui") or t[3]
        rx = (p.get("rxInfo") or [{}])[0]
        health = {k: rx[k] for k in ("rssi", "snr") if k in rx}
        return {"device": device, "points": _flat(p.get("object") or {}),
                "health": health, "stamp": p.get("time")}
    return None


#: What an rtl_433 event says about the radio and the decoder, not about the weather.
RTL_433_META = frozenset({"time", "model", "subtype", "channel", "id", "mic", "mod", "freq",
                          "freq1", "freq2", "noise", "protocol", "rssi", "snr"})


def _rtl_433(p) -> dict | None:
    """An event `rtl_433` (GPL-2.0) decoded off the air and published on
    `rtl_433/<host>/events`, its `-F mqtt` events topic: one JSON object a reception,
    the decoder's own field names (`src/devices/fineoffset.c` for a Fine Offset WH65B:
    `temperature_C`, `humidity`, `wind_dir_deg`, `wind_avg_m_s`, `wind_max_m_s`,
    `rain_mm`, `uv`, `uvi`, `light_lux`, `battery_ok`).

    * **The device is the decoder's model and its ids**, `<model>[-<subtype>][-<channel>]
      -<id>`, as rtl_433 itself names a device's topic. Many stations pick a new id when
      their batteries are changed; the station then arrives unbound, and is reported by
      its new name.
    * **Every other number or truth is a point**, under the decoder's name; the radio's
      `rssi` and `snr` (with `-M level`) are link health.
    * **`rain_mm` is the gauge's running total**, as the station counts it, not the
      rain since the last message; a day's rain is a derivation, not a reading.
    * **`light_lux` is light, not sunshine.** Declaring it as solar radiation in W/m2
      would be the unit lie §3.4 forbids; the clear-sky check catches it when it is.
    * **Its time is local and zoneless by default.** Run it with `-M time:unix` (epoch
      seconds) or `-M time:iso:tz`, or give the binding a `timezone`; otherwise each
      reading is stamped on arrival.
    """
    if not isinstance(p, dict) or "model" not in p:
        return None
    device = "-".join(str(p[k]) for k in ("model", "subtype", "channel", "id") if k in p)
    points = {k: v for k, v in p.items() if k not in RTL_433_META
              and (isinstance(v, (int, float, bool)))}
    health = {k: p[k] for k in ("rssi", "snr") if isinstance(p.get(k), (int, float))}
    return {"device": device, "points": points, "health": health, "stamp": p.get("time")}


def _opensprinkler(root: str, t: list, p) -> dict | None:
    """An OpenSprinkler controller (GPL-3.0 firmware), as its firmware publishes under its
    root topic (`services/notifier.cpp`; docs/notes/irrigation-projects.md):

    * `station/<n>`: `{"state":1,"duration":s}` as a valve opens, the duration scheduled;
      `{"state":0,"duration":s,"flow":f}` as it closes, the duration it ran and, with a
      flow sensor, its flow. Points `station.<n>.open`, `.scheduled_s`, `.ran_s`, `.flow`;
    * `raindelay`, `sensor1`… `sensor4`: `{"state":0|1}`, points of the same names;
    * `sensor/flow`: `{"count","volume"}`, points `flow.count` and `flow.volume`;
    * `weather`: `{"water level":%}`, the controller's watering scale, point `water_level`;
    * `station/<n>/alert/flow`: point `station.<n>.alert_flow_rate`;
    * `program/<n>` (2.2.1(6) and later), as a program starts:
      `{"state":1,"wl":%,"wa":w,"sa":s,"ta":t}` when it runs, with the watering percentage
      and the weather, sensor and total scales it ran at; `{"state":"skipped","wtrestr":r}`
      when it does not, `r` above 0 for a weather restriction. Points `program.<n>.ran`,
      `.water_level`, `.sensor_scale`, `.total_scale`, `.weather_restricted`.

    The device is the root topic, which names the controller. A valve's state is a truth,
    never 1 and 0. Its messages carry no time, so they are stamped on arrival."""
    rest = t[len(root.split("/")):]
    out = {"device": root, "points": {}, "health": {}, "stamp": None}
    if not isinstance(p, dict):
        return None if rest != ["availability"] else out
    if len(rest) == 2 and rest[0] == "station" and rest[1].isdigit() and "state" in p:
        n, opened = rest[1], bool(p["state"])
        out["points"][f"station.{n}.open"] = opened
        if "duration" in p:
            out["points"][f"station.{n}.{'scheduled_s' if opened else 'ran_s'}"] = p["duration"]
        if not opened and "flow" in p:
            out["points"][f"station.{n}.flow"] = p["flow"]
    elif len(rest) == 4 and rest[0] == "station" and rest[2:] == ["alert", "flow"]:
        if "flow_rate" in p:
            out["points"][f"station.{rest[1]}.alert_flow_rate"] = p["flow_rate"]
    elif len(rest) == 1 and (rest[0] == "raindelay" or (rest[0].startswith("sensor") and rest[0][6:].isdigit())):
        if "state" in p:
            out["points"][rest[0]] = bool(p["state"])
    elif len(rest) == 2 and rest[0] == "program" and rest[1].isdigit() and "state" in p:
        n = rest[1]
        if p["state"] == "skipped":
            out["points"][f"program.{n}.ran"] = False
            if isinstance(p.get("wtrestr"), (int, float)):
                out["points"][f"program.{n}.weather_restricted"] = p["wtrestr"] > 0
        else:
            out["points"][f"program.{n}.ran"] = bool(p["state"])
            for key, point in (("wl", "water_level"), ("sa", "sensor_scale"), ("ta", "total_scale")):
                if isinstance(p.get(key), (int, float)) and not isinstance(p[key], bool):
                    out["points"][f"program.{n}.{point}"] = p[key]
    elif rest == ["sensor", "flow"]:
        out["points"].update({f"flow.{k}": p[k] for k in ("count", "volume") if k in p})
    elif rest == ["weather"] and "water level" in p:
        out["points"]["water_level"] = p["water level"]
    else:
        return None
    return out


# --------------------------------------------------------------------- bridge

@dataclass
class BridgeReport:
    messages: int = 0
    not_ours: int = 0
    unbound: int = 0
    written: int = 0
    already_present: int = 0
    unusable_value: int = 0
    stamped_on_arrival: int = 0
    out_of_window: int = 0
    unbound_devices: set = field(default_factory=set)


def _zone(name):
    if name is None:
        return None
    if name.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise BindingError(f"unknown timezone {name!r}") from exc


class Bridge:
    """Bound MQTT messages -> observations on raw datastreams.

    Bindings::

        {"devices": {
           "chirpstack:a84041000181c1f4": {
              "uncertainty_s": 2.0,
              "timezone": "UTC",
              "points": {"water_SOIL": {"datastream": "<raw datastream uuid>"},
                         "rssi":       {"datastream": "<raw datastream uuid>"}}}}}
    """

    def __init__(self, log, state: P.State, bindings: dict, *,
                 prefixes: dict | None = None):
        self.log, self.state = log, state
        self.prefixes = prefixes
        self.report = BridgeReport()
        self._devices = self._validate(bindings)

    def _validate(self, bindings: dict) -> dict:
        devices = {}
        for key, spec in (bindings.get("devices") or {}).items():
            profile, _, _ = key.partition(":")
            if profile not in PROFILES + DIRECT:
                raise BindingError(f"{key}: unknown profile {profile!r} "
                                   f"(known: {', '.join(PROFILES + DIRECT)})")
            uncertainty = spec.get("uncertainty_s")
            if not isinstance(uncertainty, (int, float)) or uncertainty <= 0:
                raise BindingError(
                    f"{key}: uncertainty_s is required and positive (§2) — it must "
                    f"cover the platform's own latency for readings stamped on arrival")
            points = {}
            for point, point_spec in (spec.get("points") or {}).items():
                for forbidden in ("scale", "offset", "invert"):
                    if forbidden in point_spec:
                        raise BindingError(
                            f"{key} {point}: `{forbidden}` is not applied — a value is "
                            f"stored as published and converted by a Calibration (§3.2)")
                try:
                    ident = UUID(str(point_spec["datastream"]))
                except (KeyError, ValueError, TypeError) as exc:
                    raise BindingError(f"{key} {point}: datastream must be a UUID") \
                        from exc
                ds = self.state.datastreams.get(ident)
                if ds is None:
                    raise BindingError(f"{key} {point}: no datastream {ident} declared")
                if ds.kind is not DatastreamKind.RAW:
                    raise BindingError(f"{key} {point}: {ident} is derived; bind the "
                                       f"raw datastream (§3.2)")
                points[point] = ds
            devices[key] = {"points": points, "uncertainty": float(uncertainty),
                            "zone": _zone(spec.get("timezone")),
                            "quality": ClockQuality(spec.get("clock_quality", "network"))}
        return devices

    def _stamp(self, text, binding, arrived):
        """The payload's own time, if it can be trusted; otherwise arrival time. Seconds
        since the Unix epoch, as a number or digits, are UTC and need no zone."""
        if isinstance(text, (int, float)) and not isinstance(text, bool):
            text = repr(text)
        if not isinstance(text, str) or not text:
            return None
        try:
            if text.replace(".", "", 1).isdigit():
                parsed = _dt.datetime.fromtimestamp(float(text), tz=UTC)
            else:
                parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (ValueError, OverflowError, OSError):
            return None
        if parsed.tzinfo is None:
            if binding["zone"] is None:
                return None
            parsed = parsed.replace(tzinfo=binding["zone"])
        stamped = parsed.astimezone(UTC)
        # A device clock years out or in the future is a device fault, not a reading
        # time. Reported, then stamped on arrival rather than believed.
        if not (_dt.datetime(2020, 1, 1, tzinfo=UTC) <= stamped
                <= arrived + _dt.timedelta(days=1)):
            self.report.out_of_window += 1
            return None
        return stamped

    def handle(self, topic: str, raw, *, arrived: _dt.datetime | None = None) -> int:
        """Process one message. Returns how many observations it wrote."""
        arrived = arrived or _dt.datetime.now(tz=UTC)
        self.report.messages += 1
        profile = detect(topic, self.prefixes)
        if profile is None:
            self.report.not_ours += 1
            return 0
        parsed = parse(profile, topic, raw, self.prefixes)
        if parsed is None:
            self.report.not_ours += 1
            return 0
        return self.ingest(profile, parsed, arrived=arrived,
                           provenance={"mqtt_topic": topic, "mqtt_profile": profile})

    def ingest(self, profile: str, parsed: dict, *, arrived: _dt.datetime,
               provenance: dict) -> int:
        """Write one parsed message, `{device, points, health, stamp}`, under the
        bindings: what MQTT messages come to after `parse`, and what a station read over
        its own protocol comes to (`station_adapters.py`)."""
        key = f"{profile}:{parsed['device']}"
        binding = self._devices.get(key)
        if binding is None:
            self.report.unbound += 1
            self.report.unbound_devices.add(key)
            return 0
        stamped = self._stamp(parsed["stamp"], binding, arrived)
        if stamped is None:
            measured = arrived
            self.report.stamped_on_arrival += 1
        else:
            measured = stamped
        written = 0
        values = {**parsed["points"], **parsed["health"]}
        for point, ds in binding["points"].items():
            if point not in values:
                continue
            result = value_of(values[point])
            if result is None:
                self.report.unusable_value += 1
                continue
            if self.state.has_observation_at(ds.id, measured):
                # MQTT at QoS 1 delivers at least once; a duplicate is ordinary.
                self.report.already_present += 1
                continue
            obs = Observation(
                id=uuid7(), datastream=ds.id, measured_at=measured,
                measured_at_uncertainty=binding["uncertainty"], received_at=arrived,
                result=result, clock_quality=binding["quality"],
                provenance={**provenance, "stamped_on_arrival": stamped is None})
            self.log.append_record(obs)
            self.state.add(obs)
            written += 1
        self.report.written += written
        return written

    def feed(self, lines) -> BridgeReport:
        """JSON lines, as the emulator writes them or `mosquitto_sub -F '%j'` does."""
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                self.report.messages += 1
                self.report.not_ours += 1
                continue
            self.handle(message.get("topic", ""), message.get("payload"))
        return self.report


def main(argv=None) -> int:
    import log as L
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bindings", required=True)
    ap.add_argument("--log", help="the log file to append to (JSONL); a declared "
                                  "farm's datastreams must already be in it")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and report; write nothing")
    args = ap.parse_args(argv)
    log = L.Log(args.log) if args.log and not args.dry_run else L.Log()
    if args.log and args.dry_run:
        for event in L.Log(args.log).events:
            log.receive(event)
    state = P.state_from_log(log)
    with open(args.bindings, encoding="utf-8") as handle:
        bindings = json.load(handle)
        bridge = Bridge(log, state, bindings, prefixes=bindings.get("prefixes"))
    report = bridge.feed(sys.stdin)
    summary = {k: (sorted(v) if isinstance(v, set) else v)
               for k, v in report.__dict__.items()}
    print(json.dumps(summary, indent=1), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
