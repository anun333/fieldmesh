#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Modbus RTU devices into the log: poll, decode, write what is bound (spec v0.1 §10).

`modbus_rtu.py` frames a read and parses the reply; this decides what to read from a
device, decodes it, and writes what the bindings name, as the MQTT bridge does for the
families that publish. A device's registers come from its **map**, written from the
maker's integrator guide, not guessed:

* `atmos41_gen2`: METER's ATMOS 41 Gen 2 all-in-one weather station (Integrator Guide
  18036, rev. 05, 2026). Its readings are 32-bit big-endian floats in input registers
  3001-3044, read with function code 04. **Reading them resets its accumulators**, so
  each value is the mean, total or maximum since the last read, and all are read in one
  burst, as the guide says to. Factory settings: server address 1, 9600 baud, even
  parity, one stop bit. Relative humidity is a fraction (`1`), precipitation the
  millimetres since the last read.

Rules, the bridge's:

* **The binding is the allowlist, and it binds to raw datastreams.** No scale or offset;
  a conversion is a calibration (§3.2).
* **A reading is stamped when it is read**, by the gateway's clock, with the binding's
  `uncertainty_s`. Its provenance says what it covers: the poll before it (`since`), or
  nothing known, on the first poll after the collector starts.
* **A device that does not answer is counted, and nothing is written.** A silence is
  `stale` (§4.2), not a zero.

    python3 modbus_collector.py --bindings b.json --log farm.jsonl --every 300

with bindings such as

    {"devices": {"weather": {"map": "atmos41_gen2", "port": "/dev/ttyUSB0",
                             "uncertainty_s": 2.0,
                             "points": {"air_temperature": {"datastream": "<uuid>"},
                                        "solar_radiation": {"datastream": "<uuid>"}}}}}
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import struct
import sys
import time
from dataclasses import dataclass, field
from uuid import UUID

import project as P
from ids import uuid7
from model import ClockQuality, DatastreamKind, Observation

UTC = _dt.timezone.utc

#: Each map: the table, the first register's address (its number less one), how many
#: 16-bit words one burst reads, the serial settings it ships with, and each point's
#: offset in words and type.
MAPS = {
    "atmos41_gen2": {
        "table": "input", "address": 3000, "words": 44, "unit": 1,
        "serial": {"baud": 9600, "parity": "E", "stopbits": 1},
        "points": {
            "solar_radiation": (0, "f32"),               # W/m2, mean
            "precipitation": (2, "f32"),                 # mm, total
            "drop_count": (4, "f32"),
            "tip_count": (6, "f32"),
            "precipitation_ec": (8, "f32"),              # uS/cm
            "lightning_count": (10, "f32"),
            "lightning_distance": (12, "f32"),           # km
            "wind_speed": (14, "f32"),                   # m/s, mean
            "wind_direction": (16, "f32"),               # degrees from north
            "gust_speed": (18, "f32"),                   # m/s, maximum
            "air_temperature": (20, "f32"),              # Cel, mean
            "vapor_pressure": (22, "f32"),               # kPa
            "atmospheric_pressure": (24, "f32"),         # kPa
            "relative_humidity": (26, "f32"),            # fraction
            "humidity_sensor_temperature": (28, "f32"),  # Cel
            "orientation": (30, "f32"),                  # degrees from vertical
            "air_temperature_min": (32, "f32"),
            "air_temperature_max": (34, "f32"),
            "wind_north": (36, "f32"),
            "wind_east": (38, "f32"),
            "tilt_x": (40, "f32"),
            "tilt_y": (42, "f32"),
        },
    },
}


class BindingError(ValueError):
    """The bindings cannot be used. Raised before anything is read."""


def decode(words: list, points: dict) -> dict:
    """`{point: value}` from a burst of 16-bit words. A 32-bit float spans two registers,
    most significant first, as the guide's Table 22 shows. (Its example's bytes have a
    slip: 123456.0 is 0x47F12000; the 0x471F2000 it prints is 40736.0.)"""
    out = {}
    for name, (offset, kind) in points.items():
        if kind != "f32" or offset + 1 >= len(words):
            continue
        value = struct.unpack(">f", struct.pack(">HH", words[offset], words[offset + 1]))[0]
        if value == value:                                  # NaN is no reading
            out[name] = round(value, 6)
    return out


@dataclass
class CollectorReport:
    polls: int = 0
    no_answer: int = 0
    written: int = 0
    no_answer_devices: set = field(default_factory=set)


class Collector:
    """Polls each bound device in one burst and writes its bound points."""

    def __init__(self, log, state: P.State, bindings: dict, sources: dict):
        """`sources` maps each device's `port` to an open `modbus_rtu.RtuSource` (or
        anything with its `read(unit, table, address, words)`)."""
        self.log, self.state, self.sources = log, state, sources
        self.report = CollectorReport()
        self._devices = self._validate(bindings)
        self._last: dict = {}

    def _validate(self, bindings: dict) -> dict:
        devices = {}
        for key, spec in (bindings.get("devices") or {}).items():
            m = MAPS.get(spec.get("map"))
            if m is None:
                raise BindingError(f"{key}: unknown map {spec.get('map')!r} "
                                   f"(known: {', '.join(MAPS)})")
            if spec.get("port") not in self.sources:
                raise BindingError(f"{key}: no source open on port {spec.get('port')!r}")
            uncertainty = spec.get("uncertainty_s")
            if not isinstance(uncertainty, (int, float)) or uncertainty <= 0:
                raise BindingError(f"{key}: uncertainty_s is required and positive (§2)")
            points = {}
            for point, point_spec in (spec.get("points") or {}).items():
                if point not in m["points"]:
                    raise BindingError(f"{key}: {spec['map']} has no point {point!r}")
                for forbidden in ("scale", "offset", "invert"):
                    if forbidden in point_spec:
                        raise BindingError(f"{key} {point}: `{forbidden}` is not applied; "
                                           f"a conversion is a Calibration (§3.2)")
                try:
                    ident = UUID(str(point_spec["datastream"]))
                except (KeyError, ValueError, TypeError) as exc:
                    raise BindingError(f"{key} {point}: datastream must be a UUID") from exc
                ds = self.state.datastreams.get(ident)
                if ds is None:
                    raise BindingError(f"{key} {point}: no datastream {ident} declared")
                if ds.kind is not DatastreamKind.RAW:
                    raise BindingError(f"{key} {point}: {ident} is derived; bind the raw "
                                       f"datastream (§3.2)")
                points[point] = ds
            devices[key] = {"map": m, "map_name": spec["map"], "port": spec["port"],
                            "unit": int(spec.get("unit", m["unit"])), "points": points,
                            "uncertainty": float(uncertainty),
                            "quality": ClockQuality(spec.get("clock_quality", "network"))}
        return devices

    def poll(self, at: _dt.datetime | None = None) -> int:
        """Read every bound device once; returns how many observations were written."""
        at = at or _dt.datetime.now(tz=UTC)
        written = 0
        for key, d in self._devices.items():
            self.report.polls += 1
            m = d["map"]
            words = self.sources[d["port"]].read(d["unit"], m["table"], m["address"],
                                                 m["words"])
            if not words or len(words) != m["words"]:
                self.report.no_answer += 1
                self.report.no_answer_devices.add(key)
                continue
            since = self._last.get(key)
            self._last[key] = at
            values = decode(words, m["points"])
            for point, ds in d["points"].items():
                if point not in values or self.state.has_observation_at(ds.id, at):
                    continue
                obs = Observation(
                    id=uuid7(), datastream=ds.id, measured_at=at,
                    measured_at_uncertainty=d["uncertainty"], received_at=at,
                    result=values[point], clock_quality=d["quality"],
                    provenance={"modbus_map": d["map_name"], "modbus_unit": d["unit"],
                                "since": since.isoformat() if since else None})
                self.log.append_record(obs)
                self.state.add(obs)
                written += 1
        self.report.written += written
        return written


def main(argv=None) -> int:
    import log as L
    import modbus_rtu as M
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bindings", required=True)
    ap.add_argument("--log", required=True, help="the log file to append to (JSONL)")
    ap.add_argument("--every", type=float, help="seconds between polls; once if absent")
    args = ap.parse_args(argv)
    with open(args.bindings, encoding="utf-8") as handle:
        bindings = json.load(handle)
    sources = {}
    for spec in (bindings.get("devices") or {}).values():
        m = MAPS.get(spec.get("map"), {})
        serial = {**m.get("serial", {}), **{k: spec[k] for k in ("baud", "parity", "stopbits")
                                            if k in spec}}
        if spec.get("port") and spec["port"] not in sources:
            sources[spec["port"]] = M.RtuSource(spec["port"], **serial)
    log = L.Log(args.log)
    collector = Collector(log, P.state_from_log(log), bindings, sources)
    try:
        while True:
            collector.poll()
            if not args.every:
                break
            time.sleep(args.every)
    except KeyboardInterrupt:
        pass
    finally:
        for source in sources.values():
            source.close()
        summary = {k: (sorted(v) if isinstance(v, set) else v)
                   for k, v in collector.report.__dict__.items()}
        print(json.dumps(summary, indent=1), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
