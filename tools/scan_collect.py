#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A real station, live, into a farm log — for cron. Plan B for build step 7 (Q6).

    python3 tools/scan_collect.py farm-log.jsonl --station 2075:TN:SCAN --soil-cache DIR

Build step 7 wants one real device driver before any hardware arrives. An NRCS SCAN
station is a real device on a real farm — McAllister Farm's has measured soil water and
temperature at five depths, air temperature, rain and its own battery every hour since
2003 — and NRCS publishes each hour through the AWDB web service (public domain). So
this reads the last few days of one station and appends them to a log as layer zero
would take them from a node: a raw datastream per sensor, in the unit the station sends
(Q21: a value already in a unit declares that unit), every reading assessed by the §4.2
checks as it lands, with a device and an installation at its depth behind each series.

The soil-moisture series start from the soil survey's thresholds for their own depth
and texture (tools/soil_survey.py), as Q24 says a new probe should, and can learn their
own after a season (`checks.learn_threshold`).

Each call is idempotent — an hour already in the log is skipped — so it can run often.
AWDB gives hours in the station's local standard time; the station's own offset is used,
never the host's.

    41 */6 * * *  cd ~/dev/librefarm && python3 tools/scan_collect.py ~/dev/librefarm-data/mcallister-scan.jsonl --station 2075:TN:SCAN --soil-cache ~/dev/librefarm-data/soil
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
import soil_survey as SS  # noqa: E402
import checks as C  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import (ClockQuality, Datastream, DatastreamKind, Device, DeviceKind,  # noqa: E402
                   Installation, Label, Observation)

UTC = _dt.timezone.utc
AWDB = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
INCH_M = 0.0254

#: AWDB element → (vocabulary term, the UCUM code of AWDB's unit, words for the name).
ELEMENTS = {
    "TOBS": (V.AIR_TEMPERATURE, "[degF]", "air temperature"),
    "PRCP": (V.PRECIPITATION_DEPTH, "[in_i]", "rain this hour"),
    "BATT": (V.BATTERY_VOLTAGE, "V", "battery"),
    "SMS": (V.SOIL_WATER, "%", "soil water"),
    "STO": (V.SOIL_TEMPERATURE, "[degF]", "soil temperature"),
}
UNITS = {"degF": "[degF]", "in": "[in_i]", "volt": "V", "pct": "%"}

#: What each can physically be, in AWDB's units — the range check; wide on purpose — and
#: how long one may hold a value before it is `stuck`. Every flatline is set in seconds:
#: left to the default count of twelve, the first live week flagged 413 healthy readings —
#: a dry rain gauge reading 0 all day, and deep soil temperature holding one whole °F.
LIMITS = {"TOBS": {"min": -40.0, "max": 130.0, "flat_seconds": 6 * 3600.0},
          # A gauge reads 0 for weeks without rain; a flat run says nothing about it.
          "PRCP": {"min": 0.0, "max": 6.0, "flat_n": None},
          # Measured: the battery never held one value more than 10 h (three stations, two
          # years); twice that.
          "BATT": {"min": 10.0, "max": 16.0, "flat_seconds": 20 * 3600.0},
          "STO": {"min": -40.0, "max": 140.0}}

#: Soil temperature in whole °F holds a value far longer as depth damps the daily wave.
#: The longest healthy run at McAllister Farm, Allen Farms and Eastview Farm over
#: 2023-10 to 2025-09, by depth in inches — 47, 47, 87, 366 and 627 hours — and the
#: flatline at twice that, Q24's factor. A dead sensor at 1 m takes seven weeks to show;
#: that is the physics of a whole-degree reading, said rather than hidden.
SOIL_TEMPERATURE_FLAT_H = {-2: 94, -4: 94, -8: 174, -20: 732, -40: 1254}
#: Q23's soil shape check, in percent: out by 5 points and straight back is a glitch;
#: a fall faster than 5 points an hour is faster than soil drains.
SOIL_SHAPE = {"spike_step": 5.0, "max_fall_per_s": 5.0 / 3600.0}


def fetch(path: str, **params) -> object:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{AWDB}/{path}?{query}", headers={"User-Agent": "librefarm/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def series_of(doc: list) -> list:
    """[(element, depth in inches or None, UCUM unit, [(local time text, value)])] from one
    AWDB data response."""
    out = []
    for station in doc:
        for block in station.get("data", []):
            se = block["stationElement"]
            code = se["elementCode"]
            if code not in ELEMENTS:
                continue
            unit = UNITS.get(se.get("storedUnitCode"))
            if unit != ELEMENTS[code][1]:
                raise ValueError(f"{code}: AWDB unit {se.get('storedUnitCode')!r} is not the "
                                 f"one this adapter maps; refusing to guess")
            values = [(v["date"], v["value"]) for v in block.get("values", [])
                      if v.get("value") is not None]
            out.append((code, se.get("heightDepth"), unit, values))
    return out


def stream_name(station_name: str, code: str, depth_in) -> str:
    words = ELEMENTS[code][2]
    if depth_in is not None:
        return f"{station_name} SCAN: {words} at {round(-depth_in * 2.54)} cm"
    return f"{station_name} SCAN: {words}"


def thresholds(code: str, depth_in, soil: dict | None) -> dict:
    if code == "STO":
        hours = SOIL_TEMPERATURE_FLAT_H.get(depth_in, max(SOIL_TEMPERATURE_FLAT_H.values()))
        return {**LIMITS[code], "flat_seconds": hours * 3600.0}
    if code != "SMS":
        return dict(LIMITS[code])
    depth_m = -depth_in * INCH_M
    limits = SS.proposed_limits(soil, depth_m, "C") if soil and soil.get("horizons") else None
    if limits:
        top = limits["max"]
        return {"min": 0.0, "max": round(top * 100.0, 1) if top else 60.0,
                "flat_seconds": float(limits["flat_seconds"]), **SOIL_SHAPE}
    dwell = SS.DWELL_P999_H[None][("clayey", SS.band(depth_m))]
    return {"min": 0.0, "max": 60.0, "flat_seconds": dwell * SS.DWELL_FACTOR * 3600.0,
            **SOIL_SHAPE}


def declare(log, state, station: dict, code, depth_in, unit, soil) -> Datastream:
    """Find the series by its name, or declare it with its device, installation and name."""
    name = stream_name(station["name"], code, depth_in)
    for e in state.entities_named(name):
        if e in state.datastreams:
            return state.datastreams[e]
    feature = next((ds.feature for ds in state.datastreams.values()), None) or uuid7()
    thing = next((ds.thing for ds in state.datastreams.values()), None) or uuid7()
    now = _dt.datetime.now(tz=UTC)
    device = Device(id=uuid7(), kind=DeviceKind.SENSOR, site=feature,
                    model=f"SCAN {code}", manufacturer="NRCS SCAN",
                    note=f"{station['stationTriplet']}, read through AWDB")
    start = _dt.datetime.fromisoformat(station["beginDate"]).replace(tzinfo=UTC)
    install = Installation(id=uuid7(), device=device.id, feature=feature, installed_at=start,
                           depth_m=(-depth_in * INCH_M) if depth_in is not None else None)
    ds = Datastream(id=uuid7(), thing=thing, sensor=device.id, observed_property=ELEMENTS[code][0],
                    feature=feature, kind=DatastreamKind.RAW, unit=unit,
                    expected_interval=3600.0, max_latency=6 * 3600.0,
                    thresholds=thresholds(code, depth_in, soil))
    label = Label(id=uuid7(), entity=ds.id, name=name, set_at=now,
                  description=f"NRCS SCAN {station['stationTriplet']}, hourly, public domain")
    for record in (device, install, ds, label):
        log.append_record(record)
        state.add(record)
    return ds


def collect(log_path: str, station: dict, doc: list, soil: dict | None,
            received_at: _dt.datetime | None = None) -> dict:
    """Append one AWDB response to the log. Returns `{series name: (new, already)}`."""
    log = L.Log(log_path)
    state = P.state_from_log(log)
    offset = _dt.timedelta(hours=station.get("dataTimeZone", 0.0))
    received = received_at or _dt.datetime.now(tz=UTC)
    report = {}
    for code, depth, unit, values in series_of(doc):
        ds = declare(log, state, station, code, depth, unit, soil)
        have = {o.measured_at for o in state.live_observations_of(ds.id)}
        new = already = 0
        for text, value in values:
            local = _dt.datetime.strptime(text, "%Y-%m-%d %H:%M")
            when = (local - offset).replace(tzinfo=UTC)
            if when in have:
                already += 1
                continue
            obs = Observation(id=uuid7(), datastream=ds.id, measured_at=when,
                              measured_at_uncertainty=1800.0, received_at=received,
                              result=value, clock_quality=ClockQuality.NETWORK,
                              provenance={"source": "NRCS AWDB", "station": station["stationTriplet"],
                                          "element": code, "depth_in": depth})
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
        report[stream_name(station["name"], code, depth)] = (new, already)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--station", default="2075:TN:SCAN", help="AWDB station triplet")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--soil-cache", help="directory to keep the soil survey's answer in")
    args = ap.parse_args(argv)
    [station] = fetch("stations", stationTriplets=args.station, returnStationElements="false")
    soil = None
    if args.soil_cache:
        os.makedirs(args.soil_cache, exist_ok=True)
        path = os.path.join(args.soil_cache, args.station.replace(":", "_") + ".json")
        if os.path.exists(path):
            soil = json.load(open(path, encoding="utf-8"))
        else:
            soil = SS.query(station["latitude"], station["longitude"])
            json.dump(soil, open(path, "w", encoding="utf-8"))
    end = _dt.datetime.now(tz=UTC) + _dt.timedelta(hours=station.get("dataTimeZone", 0.0))
    begin = end - _dt.timedelta(days=args.days)
    doc = fetch("data", stationTriplets=args.station,
                elements="TOBS,PRCP,BATT,SMS:*,STO:*", duration="HOURLY",
                beginDate=f"{begin:%Y-%m-%d}%2000:00", endDate=f"{end:%Y-%m-%d}%2023:00")
    report = collect(args.log, station, doc, soil)
    new = sum(n for n, _ in report.values())
    print(f"{station['stationTriplet']} {station['name']}: {new} new readings over {len(report)} "
          f"series ({sum(a for _, a in report.values())} already in the log)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
