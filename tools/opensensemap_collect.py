#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real soil probes, live, into a farm log, from openSenseMap — for testing without hardware.

    python3 tools/opensensemap_collect.py farm-log.jsonl --box 5e5ad22de8fdda001b0bb5ae \\
        --depth 0.10 --hours 48

openSenseMap (openSenseMap.org, run by re:edu and the University of Münster's senseBox
project) publishes every reading of thousands of citizen stations, no key needed, under the
Open Data Commons Public Domain Dedication and Licence 1.0. Some carry soil probes: on
2026-10-13, 19 stations had reported in the last day from TRUEBNER SMT50s (soil water and
temperature) and Dragino LSE01s (the LoRaWAN probe fieldmesh's soil-sensor note
recommends, which also reports conductivity). This reads one station's soil series and
appends them to a log as layer zero would take them from a node: a raw datastream per
probe series in the unit the station declares, every reading assessed by the §4.2 checks as
it lands, a device and an installation behind each.

A unit is taken only where it is certain what it means; anything else is refused and said
(Q21). One LSE01 declares its conductivity in "Ohm", which a conductivity is not: it is
left out rather than guessed. The probes' depth is not published; give it with `--depth`
for the soil advisory to use them.

Readings arrive a minute apart; one in `--every` seconds is kept (600 by default). Each
call is idempotent: a reading already in the log is skipped.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import checks as C  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import (ClockQuality, Datastream, DatastreamKind, Device, DeviceKind,  # noqa: E402
                   Installation, Label, Observation)

UTC = _dt.timezone.utc
API = "https://api.opensensemap.org"
LICENCE = "ODC-PDDL-1.0"

#: A series' title, lowercased, → (vocabulary term, {the station's unit: its UCUM code},
#: words for the name). Titles are the stations' own, in German or English.
SOIL = (
    (("bodenfeuchte", "soil moisture", "soil water", "soilmoisture"),
     V.SOIL_WATER, {"%": "%"}, "soil water"),
    (("bodentemperatur", "soil temperature", "soiltemperature"),
     V.SOIL_TEMPERATURE, {"°C": "Cel", "°F": "[degF]"}, "soil temperature"),
    (("leitfähigkeit", "conductivity", "electrical conductivity", "ec"),
     V.BULK_EC, {"µS/cm": "uS/cm", "uS/cm": "uS/cm", "mS/cm": "mS/cm", "dS/m": "dS/m"},
     "soil conductivity"),
)
#: Makers by the series' sensor type.
MAKERS = {"SMT50": "TRUEBNER", "LSE01": "Dragino"}
#: The range check, wide on purpose, and how long a value may hold.
LIMITS = {V.SOIL_WATER: {"min": 0.0, "max": 60.0, "flat_seconds": 48 * 3600.0,
                         "spike_step": 5.0, "max_fall_per_s": 5.0 / 3600.0},
          V.SOIL_TEMPERATURE: {"min": -30.0, "max": 60.0, "flat_seconds": 12 * 3600.0},
          V.BULK_EC: {"min": 0.0, "max": 20000.0, "flat_seconds": 48 * 3600.0}}


def fetch(path: str, **params) -> object:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API}/{path}" + (f"?{query}" if query else "")
    req = urllib.request.Request(url, headers={"User-Agent": "fieldmesh/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def soil_series(box: dict) -> tuple[list, list]:
    """`([(sensor, term, ucum, words)], [(sensor title, why it was left out)])` for a box's
    soil series."""
    found, refused = [], []
    for s in box.get("sensors", []):
        title = (s.get("title") or "").strip()
        for names, term, units, words in SOIL:
            if title.lower() in names:
                unit = (s.get("unit") or "").strip()
                if unit in units:
                    found.append((s, term, units[unit], words))
                else:
                    refused.append((title, f"unit {unit!r} is not one a {words} reading "
                                           f"can be in; left out rather than guessed"))
                break
    return found, refused


def thinned(rows: list, every_s: float) -> list:
    """`[(time, value)]`, oldest first, at least `every_s` apart."""
    out = []
    for r in sorted(rows, key=lambda r: r["createdAt"]):
        try:
            value = float(r["value"])
        except (TypeError, ValueError):
            continue
        when = _dt.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
        if out and (when - out[-1][0]).total_seconds() < every_s:
            continue
        out.append((when, value))
    return out


def declare(log, state, box: dict, sensor: dict, term: str, unit: str, words: str,
            depth_m: float | None, every_s: float) -> Datastream:
    """Find the series by its name, or declare it with its device, installation and name."""
    name = f"{box['name']} (openSenseMap): {words}"
    for e in state.entities_named(name):
        if e in state.datastreams:
            return state.datastreams[e]
    feature = next((ds.feature for ds in state.datastreams.values()), None) or uuid7()
    thing = next((ds.thing for ds in state.datastreams.values()), None) or uuid7()
    now = _dt.datetime.now(tz=UTC)
    kind = sensor.get("sensorType") or ""
    maker = next((m for prefix, m in MAKERS.items() if kind.startswith(prefix)), None)
    device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=feature, model=kind or None,
                    manufacturer=maker,
                    note=f"openSenseMap box {box['_id']}, sensor {sensor['_id']}")
    start = _dt.datetime.fromisoformat(box.get("createdAt", "2000-01-01T00:00:00Z")
                                       .replace("Z", "+00:00"))
    install = Installation(id=uuid7(), device=device.id, feature=feature, installed_at=start,
                           depth_m=depth_m)
    ds = Datastream(id=uuid7(), thing=thing, sensor=device.id, observed_property=term,
                    feature=feature, kind=DatastreamKind.RAW, unit=unit,
                    expected_interval=every_s, max_latency=6 * 3600.0,
                    thresholds=dict(LIMITS[term]))
    label = Label(id=uuid7(), entity=ds.id, name=name, set_at=now,
                  description=f"openSenseMap box {box['_id']}, {LICENCE}")
    for record in (device, install, ds, label):
        log.append_record(record)
        state.add(record)
    return ds


def collect(log_path: str, box: dict, data: dict, *, depth_m: float | None = None,
            every_s: float = 600.0, received_at: _dt.datetime | None = None) -> dict:
    """Append one box's soil series to the log: `data` is `{sensor id: [rows as the API
    gives them]}`. Returns `{"series": {name: (new, already)}, "refused": [(title, why)]}`."""
    log = L.Log(log_path)
    state = P.state_from_log(log)
    received = received_at or _dt.datetime.now(tz=UTC)
    found, refused = soil_series(box)
    report = {}
    for sensor, term, unit, words in found:
        ds = declare(log, state, box, sensor, term, unit, words, depth_m, every_s)
        have = {o.measured_at for o in state.live_observations_of(ds.id)}
        new = already = 0
        for when, value in thinned(data.get(sensor["_id"], []), every_s):
            if when in have:
                already += 1
                continue
            obs = Observation(id=uuid7(), datastream=ds.id, measured_at=when,
                              measured_at_uncertainty=1.0, received_at=received,
                              result=value, clock_quality=ClockQuality.NETWORK,
                              provenance={"source": "openSenseMap", "box": box["_id"],
                                          "sensor": sensor["_id"], "licence": LICENCE})
            obs.validate_against(ds)
            log.append_record(obs)
            state.add(obs)
            assertion = C.assess(state, obs, asserted_at=received)
            log.append_record(assertion)
            state.add(assertion)
            for late in C.spike_assertions(state, obs, asserted_at=received):
                log.append_record(late)
                state.add(late)
            have.add(when)
            new += 1
        report[f"{box['name']} (openSenseMap): {words}"] = (new, already)
    return {"series": report, "refused": refused}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--box", required=True, help="the station's openSenseMap id")
    ap.add_argument("--depth", type=float, help="the probes' depth, metres")
    ap.add_argument("--hours", type=float, default=48.0)
    ap.add_argument("--every", type=float, default=600.0, help="seconds between readings kept")
    args = ap.parse_args(argv)
    box = fetch(f"boxes/{args.box}")
    found, _ = soil_series(box)
    now = _dt.datetime.now(tz=UTC)
    since = (now - _dt.timedelta(hours=args.hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {s["_id"]: fetch(f"boxes/{args.box}/data/{s['_id']}", **{
        "from-date": since, "to-date": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "format": "json"})
        for s, _, _, _ in found}
    out = collect(args.log, box, data, depth_m=args.depth, every_s=args.every)
    for name, (new, already) in out["series"].items():
        print(f"{name}: {new} new, {already} already in the log")
    for title, why in out["refused"]:
        print(f"left out {title}: {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
