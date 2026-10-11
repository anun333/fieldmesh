#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real forecasts scored against a real farm's station.

    python3 tools/nbm_verify.py --from 2026-03-01 --to 2026-04-30 --cache CACHE

The National Blend of Models (NBM) is what the National Weather Service's own forecasts
start from, and NOAA keeps every run of it in a public bucket (noaa-nbm-pds, as
cloud-optimised GeoTIFFs; public domain). McAllister Farm has a SCAN station measuring
air temperature every hour (USDA NRCS, public domain). This reads the forecast for the
station's 2.5 km grid cell from each 00 and 12 UTC run — every 3 hours to 2 days, every
6 to 7 — puts the runs into a layer-zero log on a `forecast` datastream and the
station's readings on a raw one (Q26), and scores them from the log:

* error by lead day, all hours and the cold nights a frost watch is for;
* the frost watch the virtual farm backtests (sim/forecast_drill.py), on real forecasts:
  each frost night the station recorded, and whether the forecast standing 12 hours
  before reached the warning threshold.

Values stay as sent — both sources work in whole or tenth Fahrenheit degrees — and are
reported in Celsius. NBM's cell is read with GDAL over HTTP (`gdallocationinfo` on
`/vsicurl/`), one value per file, cached, so a re-run costs nothing. SCAN's hours are local
standard time, UTC−6 at McAllister; AWDB gives the offset with the station.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as _dt
import json
import os
import re
import statistics
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import forecast as FC  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import ClockQuality, Datastream, DatastreamKind, Observation  # noqa: E402

UTC = _dt.timezone.utc
HOUR = _dt.timedelta(hours=1)
BUCKET = "https://noaa-nbm-pds.s3.amazonaws.com"
AWDB = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data"
LEADS_H = tuple(range(3, 49, 3)) + tuple(range(54, 169, 6))
DAMAGE_C = -2.2
ENOUGH_LEAD_H = 12


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def celsius(value: float, unit: str) -> float:
    """A temperature in its declared unit, in °C: the unit is on the datastream, never
    assumed from the source."""
    if unit == "Cel":
        return value
    if unit == "[degF]":
        return f_to_c(value)
    if unit == "K":
        return value - 273.15
    raise ValueError(f"not a temperature unit: {unit!r}")


def nbm_key(issued: _dt.datetime, valid: _dt.datetime, var: str = "temp") -> str:
    return (f"blendv4.3/conus/{issued:%Y/%m/%d/%H%M}/{var}/"
            f"blendv4.3_conus_{var}_{issued:%Y-%m-%dT%H:%M}_{valid:%Y-%m-%dT%H:%M}.tif")


def read_cell(key: str, lat: float, lon: float) -> float | None:
    """One grid cell of one NBM file, or None if the file or value is missing."""
    env = dict(os.environ, GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")
    try:
        out = subprocess.run(["gdallocationinfo", "-valonly", "-wgs84", f"/vsicurl/{BUCKET}/{key}",
                              f"{lon}", f"{lat}"], capture_output=True, text=True, timeout=60, env=env)
    except subprocess.TimeoutExpired:
        return None
    text = out.stdout.strip()
    if out.returncode != 0 or not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return None
    value = float(text)
    return None if value == -9999 else value


def nbm_runs(start: _dt.date, end: _dt.date, lat: float, lon: float, cache: str,
             hours=(0, 12), workers: int = 8, var: str = "temp", leads=None) -> dict:
    """{issued: [(valid, value)]} for one NBM field — `temp` in °F by default — read in
    parallel and cached in `cache`. Fields share one cache file; keys name the field.

    Units are the field's own and the files do not carry them: `temp` °F, `rh` and `sky`
    %, `dswrf` W m-2, and `windspd` in knots — its median ratio to NASA POWER's 10 m wind
    at McAllister Farm in March 2026 was 2.0, against 1.94 for knots and 2.24 for mph."""
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, f"nbm-{lat:.4f}-{lon:.4f}.json")
    known = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    wanted = []
    d = start
    while d <= end:
        for h in hours:
            issued = _dt.datetime(d.year, d.month, d.day, h, tzinfo=UTC)
            for lead in (leads or LEADS_H):
                key = nbm_key(issued, issued + lead * HOUR, var)
                if key not in known:
                    wanted.append(key)
        d += _dt.timedelta(days=1)
    if wanted:
        print(f"  reading {len(wanted)} NBM cells…", file=sys.stderr, flush=True)
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            for key, value in zip(wanted, pool.map(lambda k: read_cell(k, lat, lon), wanted)):
                known[key] = value
        with open(path, "w", encoding="utf-8") as h:
            json.dump(known, h)
    runs: dict = {}
    for key, value in known.items():
        if f"/{var}/" not in key:
            continue
        m = re.search(r"_(\d{4}-\d\d-\d\dT\d\d:\d\d)_(\d{4}-\d\d-\d\dT\d\d:\d\d)\.tif$", key)
        if not m or value is None:
            continue
        issued = _dt.datetime.fromisoformat(m.group(1)).replace(tzinfo=UTC)
        if not start <= issued.date() <= end:
            continue
        runs.setdefault(issued, []).append((_dt.datetime.fromisoformat(m.group(2)).replace(tzinfo=UTC), value))
    return {k: sorted(v) for k, v in sorted(runs.items())}


def scan_hourly(triplet: str, start: _dt.date, end: _dt.date, utc_offset_h: float, cache: str) -> list:
    """[(UTC time, °F)] from AWDB, whose hours are the station's local standard time."""
    path = os.path.join(cache, f"scan-{triplet.replace(':', '_')}-{start}-{end}.json")
    if os.path.exists(path):
        doc = json.load(open(path, encoding="utf-8"))
    else:
        url = (f"{AWDB}?stationTriplets={triplet}&elements=TOBS&duration=HOURLY"
               f"&beginDate={start}%2000:00&endDate={end}%2023:00")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "fieldmesh"}), timeout=120) as r:
            doc = json.load(r)
        with open(path, "w", encoding="utf-8") as h:
            json.dump(doc, h)
    out = []
    for item in doc[0]["data"][0]["values"]:
        if item.get("value") is None:
            continue
        local = _dt.datetime.fromisoformat(item["date"])
        out.append(((local - _dt.timedelta(hours=utc_offset_h)).replace(tzinfo=UTC), float(item["value"])))
    return out


def build_log(runs: dict, station: list):
    """Both series into a layer-zero log: the station raw, the forecast on its own kind."""
    state, log = P.State(), L.Log()
    thing, feature = uuid7(), uuid7()
    raw = Datastream(id=uuid7(), thing=thing, sensor=uuid7(), feature=feature, observed_property=V.AIR_TEMPERATURE,
                     unit="[degF]", kind=DatastreamKind.RAW, expected_interval=3600.0, max_latency=3600.0)
    fc = Datastream(id=uuid7(), thing=thing, sensor=uuid7(), feature=feature, observed_property=V.AIR_TEMPERATURE,
                    unit="[degF]", kind=DatastreamKind.FORECAST, expected_interval=12 * 3600.0, max_latency=3600.0)
    for ds in (raw, fc):
        log.append_record(ds)
        state.add(ds)
    for seq, (t, v) in enumerate(station):
        obs = Observation(id=uuid7(), datastream=raw.id, measured_at=t, measured_at_uncertainty=1800.0,
                          received_at=t, result=v, clock_quality=ClockQuality.NETWORK,
                          provenance={"source": "NRCS AWDB, SCAN 2075:TN:SCAN TOBS"})
        log.append_record(obs)
        state.add(obs)
    for issued, values in runs.items():
        FC.ingest(log, state, fc.id, issued, values, uncertainty_s=1800.0, received_at=issued,
                  provenance={"source": "NOAA NBM v4.3 (noaa-nbm-pds)"})
    return state, raw, fc


def score(state, raw, fc, warn_c: tuple = (1.0, 0.0, -1.0, -2.2)) -> dict:
    """Forecast against station from one log, whatever units each was declared in."""
    f_to_c = lambda v, u=fc.unit: celsius(v, u)          # noqa: E731 — the forecast's unit
    s_to_c = lambda v, u=raw.unit: celsius(v, u)         # noqa: E731 — the station's
    errors = {}
    cold = {}
    for obs in state.observations_of(fc.id):
        truth = state.nearest(raw.id, obs.measured_at, 0.0)
        if truth is None:
            continue
        lead_day = max(0, int((obs.measured_at - obs.issued_at).total_seconds() // 86400))
        e = f_to_c(obs.result) - s_to_c(truth.result)
        errors.setdefault(lead_day, []).append(e)
        if s_to_c(truth.result) <= 2.0:
            cold.setdefault(lead_day, []).append(e)
    summary = {day: {"n": len(es), "mae_c": statistics.mean(abs(x) for x in es), "bias_c": statistics.mean(es)}
               for day, es in sorted(errors.items())}
    cold_summary = {day: {"n": len(es), "mae_c": statistics.mean(abs(x) for x in es), "bias_c": statistics.mean(es)}
                    for day, es in sorted(cold.items())}
    # Frost nights the station recorded, and the forecast standing 12 hours before each.
    readings = sorted((o.measured_at, s_to_c(o.result)) for o in state.observations_of(raw.id))
    events, current = [], None
    for t, v in readings:
        if v <= DAMAGE_C:
            if current is None or t - current[1] > 6 * HOUR:
                current = [t, t, v]
                events.append(current)
            current[1], current[2] = t, min(current[2], v)
    issues = sorted({o.issued_at for o in state.observations_of(fc.id)})
    watch = []
    for first, last, lowest in events:
        standing = [i for i in issues if i <= first - ENOUGH_LEAD_H * HOUR]
        if not standing:
            continue
        issued = standing[-1]
        run = [o for o in state.observations_of(fc.id)
               if o.issued_at == issued and first - 6 * HOUR <= o.measured_at <= last + 6 * HOUR]
        forecast_min = min((f_to_c(o.result) for o in run), default=None)
        watch.append({"night": first, "observed_min_c": lowest, "issued": issued,
                      "forecast_min_c": forecast_min,
                      "warned": {w: forecast_min is not None and forecast_min <= w for w in warn_c}})
    return {"by_lead_day": summary, "cold_nights": cold_summary, "frost_nights": watch,
            "nights": nights(state, raw, fc, warn_c, f_to_c, s_to_c)}


def nights(state, raw, fc, warn_c: tuple, f_to_c=None, s_to_c=None) -> dict:
    """Night by night, the call a farmer would have made at dusk: the run standing at
    22 UTC (late afternoon here) forecasting the night's minimum (00–14 UTC), against the
    station's. Per threshold: frosts warned (hits), frosts not (misses), and warned
    nights that stayed above the damage line (false alerts)."""
    f_to_c = f_to_c or (lambda v: celsius(v, fc.unit))
    s_to_c = s_to_c or (lambda v: celsius(v, raw.unit))
    obs_by_night, issues = {}, sorted({o.issued_at for o in state.observations_of(fc.id)})
    for o in state.observations_of(raw.id):
        if o.measured_at.hour <= 14:
            n = o.measured_at.date()
            obs_by_night[n] = min(obs_by_night.get(n, 99.0), s_to_c(o.result))
    by_issue = {}
    for o in state.observations_of(fc.id):
        by_issue.setdefault(o.issued_at, []).append(o)
    table = {w: {"hits": 0, "misses": 0, "false": 0, "quiet": 0} for w in warn_c}
    for n, observed in obs_by_night.items():
        start = _dt.datetime(n.year, n.month, n.day, tzinfo=UTC)
        standing = [i for i in issues if i <= start - 2 * HOUR]
        if not standing:
            continue
        run = [f_to_c(o.result) for o in by_issue[standing[-1]]
               if start <= o.measured_at <= start + 14 * HOUR]
        if not run:
            continue
        low, frost = min(run), observed <= DAMAGE_C
        for w, row in table.items():
            warned = low <= w
            row["hits" if warned and frost else "misses" if frost else "false" if warned else "quiet"] += 1
    return table


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, default=35.06437)
    ap.add_argument("--lon", type=float, default=-86.59136)
    ap.add_argument("--station", default="2075:TN:SCAN")
    ap.add_argument("--utc-offset", type=float, default=-6.0, help="the station's local standard time")
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--json", help="write the scores here")
    args = ap.parse_args(argv)
    start, end = _dt.date.fromisoformat(args.start), _dt.date.fromisoformat(args.end)
    runs = nbm_runs(start, end, args.lat, args.lon, args.cache)
    station = scan_hourly(args.station, start, end + _dt.timedelta(days=8), args.utc_offset, args.cache)
    state, raw, fc = build_log(runs, station)
    problems = state.validate()
    s = score(state, raw, fc)
    print(f"NBM v4.3 at {args.lat:.4f}, {args.lon:.4f} against SCAN {args.station}, {start} to {end}: "
          f"{len(runs)} runs, {len(state.observations_of(fc.id))} forecast values, "
          f"{len(station)} station hours; log problems: {len(problems)}")
    report(s)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as h:
            json.dump(s, h, indent=1, default=str)
    return 0


def report(s: dict) -> None:
    """The score, as tables."""
    print("\n  lead day   n      MAE °C   bias °C   | station ≤ 2 °C:   n   MAE   bias")
    for day, v in s["by_lead_day"].items():
        c = s["cold_nights"].get(day)
        cold = f"{c['n']:>5} {c['mae_c']:5.2f} {c['bias_c']:+5.2f}" if c else ""
        print(f"  {day:>8} {v['n']:>5}  {v['mae_c']:7.2f}   {v['bias_c']:+7.2f}   | {cold:>22}")
    print(f"\n  Frost nights at the station (≤ {DAMAGE_C} °C), and the run standing {ENOUGH_LEAD_H} h before:")
    for w in s["frost_nights"]:
        marks = " ".join(f"{'✓' if ok else '·'}{thr:+g}" for thr, ok in w["warned"].items())
        fmin = f"{w['forecast_min_c']:+.1f}" if w["forecast_min_c"] is not None else "—"
        print(f"    {w['night']:%Y-%m-%d %H:%M} UTC  observed {w['observed_min_c']:+.1f}, forecast {fmin} "
              f"(issued {w['issued']:%m-%d %H}Z)  warned at: {marks}")
    print("\n  Night by night, the run standing at dusk (22 UTC):")
    print("    warn at   frosts warned   missed   false alerts   quiet nights")
    for w, row in s["nights"].items():
        print(f"    {w:+6.1f}   {row['hits']:>13}   {row['misses']:>6}   {row['false']:>12}   {row['quiet']:>12}")


if __name__ == "__main__":
    raise SystemExit(main())
