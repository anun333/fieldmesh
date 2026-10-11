#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Weather forecasts from open sources, as runs for sdk/forecast.py to ingest.

    python3 tools/forecast_sources.py nws LAT LON [--json run.json]
    python3 tools/forecast_sources.py metno LAT LON --user-agent "yourapp/1.0 you@example.org"

A run is one issue of a forecast: when it was issued, where it came from, and per
variable an hourly series of `(valid time, value)`. The variables are the ones a farm
acts on, under the vocabulary terms and units a datastream declares (sdk/vocab.py):

| variable | term | unit |
| --- | --- | --- |
| air_temperature | CF air_temperature | Cel |
| relative_humidity | CF relative_humidity | % |
| wind_speed | CF wind_speed | km/h (NWS), m/s (MET Norway) — as each sends it |
| precipitation | CF lwe_thickness_of_precipitation_amount | mm in the hour |

Values are kept as the source sent them — NWS's temperatures are whole Fahrenheit
degrees converted to Celsius, and `18.888888888888889` stays that, as layer zero keeps
any raw value. Hours that end before the issue time are dropped: they are an analysis
of the past, not a forecast. An amount given over several hours (NWS's six-hour rain)
is spread evenly over them, so the hours still sum to what was forecast.

## Sources, and why these two

| source | covers | licence | used |
| --- | --- | --- | --- |
| NWS, api.weather.gov — the gridded forecast (NDFD, 2.5 km, about 7 days, updated about hourly) | the United States | public domain (US government work) | **yes** |
| MET Norway, api.met.no locationforecast 2.0 (ECMWF-based outside the Nordics, about 9 days) | the world | CC BY 4.0 and NLOD 2.0 — free, commercial use included; the terms require a User-Agent naming the application and a contact, and caching | **yes**; the contact is the user's to give |
| Open-Meteo | the world | data CC BY 4.0, but the free API is for non-commercial use | no — a farm business is commercial |
| ECMWF open data | the world | CC BY 4.0 | not yet: GRIB2, which needs a decoding library |
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

UTC = _dt.timezone.utc
HOUR = _dt.timedelta(hours=1)

#: variable -> (vocabulary term, whether it is an amount over the period)
VARIABLES = {
    "air_temperature": ("http://vocab.nerc.ac.uk/standard_name/air_temperature/", False),
    "relative_humidity": ("http://vocab.nerc.ac.uk/standard_name/relative_humidity/", False),
    "wind_speed": ("http://vocab.nerc.ac.uk/standard_name/wind_speed/", False),
    "precipitation": ("http://vocab.nerc.ac.uk/standard_name/lwe_thickness_of_precipitation_amount/", True),
    "precipitation_probability": ("http://vocab.nerc.ac.uk/standard_name/lwe_thickness_of_precipitation_amount/", False),
    "cloud_area_fraction": ("http://vocab.nerc.ac.uk/standard_name/cloud_area_fraction/", False),
}

#: What a probability is the probability of (Q26). NWS's gridded probability of
#: precipitation is the chance of a measurable amount — 0.01 inch, 0.254 mm — within
#: each hour it is given for.
EVENTS = {
    "precipitation_probability": {"comparison": "ge", "threshold": 0.254, "unit": "mm",
                                  "period_s": 3600},
}


@dataclass
class Run:
    issued_at: _dt.datetime
    source: str
    where: str
    series: dict = field(default_factory=dict)      # variable -> [(valid_at, value)]
    units: dict = field(default_factory=dict)       # variable -> UCUM unit
    timezone: str | None = None                     # the place's own, when the source says
    events: dict = field(default_factory=dict)      # variable -> its event, for a probability

    def provenance(self) -> dict:
        return {"source": self.source, "where": self.where}


def parse_time(text: str) -> _dt.datetime:
    t = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"{text!r} has no timezone")
    return t.astimezone(UTC)


def duration_hours(text: str) -> int:
    """ISO 8601 durations as NWS writes them: PT2H, P1D, P1DT6H."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?)?", text)
    if not m or not any(m.groups()):
        raise ValueError(f"unsupported duration {text!r}")
    return int(m.group(1) or 0) * 24 + int(m.group(2) or 0)


def expand(values: list, issued: _dt.datetime, amount: bool) -> list:
    """NWS `{validTime: "start/PTnH", value}` intervals -> hourly `(start, value)`, an
    amount spread over its hours; hours ending at or before the issue dropped."""
    out = []
    for item in values:
        if item.get("value") is None:
            continue
        start_text, _, dur = item["validTime"].partition("/")
        start, hours = parse_time(start_text), duration_hours(dur)
        for k in range(hours):
            t = start + k * HOUR
            if t + HOUR <= issued:
                continue
            out.append((t, item["value"] / hours if amount else item["value"]))
    return out


NWS_UNITS = {"wmoUnit:degC": "Cel", "wmoUnit:percent": "%", "wmoUnit:km_h-1": "km/h", "wmoUnit:mm": "mm"}
NWS_FIELDS = {"temperature": "air_temperature", "relativeHumidity": "relative_humidity",
              "windSpeed": "wind_speed", "quantitativePrecipitation": "precipitation",
              "probabilityOfPrecipitation": "precipitation_probability",
              "skyCover": "cloud_area_fraction"}


def nws_run(grid_doc: dict) -> Run:
    """A run from an api.weather.gov `/gridpoints/{office}/{x},{y}` document."""
    p = grid_doc["properties"]
    issued = parse_time(p["updateTime"])
    run = Run(issued_at=issued, source="api.weather.gov (NWS NDFD)",
              where=f"{p.get('gridId')} {p.get('gridX')},{p.get('gridY')}")
    for key, var in NWS_FIELDS.items():
        if key not in p:
            continue
        uom = p[key].get("uom")
        if uom not in NWS_UNITS:
            raise ValueError(f"{key}: unexpected unit {uom!r}")
        run.series[var] = expand(p[key]["values"], issued, VARIABLES[var][1])
        run.units[var] = NWS_UNITS[uom]
        if var in EVENTS:
            run.events[var] = dict(EVENTS[var])
    return run


METNO_UNITS = {"celsius": "Cel", "%": "%", "m/s": "m/s", "mm": "mm"}
METNO_INSTANT = {"air_temperature": "air_temperature", "relative_humidity": "relative_humidity",
                 "wind_speed": "wind_speed"}


def metno_run(doc: dict) -> Run:
    """A run from an api.met.no `locationforecast/2.0/compact` document. Instant values
    stay at the times given (hourly near term, six-hourly later); rain comes from
    `next_1_hours`, or `next_6_hours` spread over six."""
    props = doc["properties"]
    issued = parse_time(props["meta"]["updated_at"])
    units = props["meta"].get("units", {})
    lon, lat = (doc.get("geometry") or {}).get("coordinates", [None, None])[:2]
    run = Run(issued_at=issued, source="api.met.no locationforecast 2.0", where=f"{lat},{lon}")
    for var in METNO_INSTANT.values():
        run.series[var] = []
        if units.get(var) in METNO_UNITS:
            run.units[var] = METNO_UNITS[units[var]]
    run.series["precipitation"], run.units["precipitation"] = [], "mm"
    covered = set()
    for step in props["timeseries"]:
        t = parse_time(step["time"])
        if t + HOUR <= issued:
            continue
        details = step["data"]["instant"]["details"]
        for key, var in METNO_INSTANT.items():
            if key in details:
                run.series[var].append((t, details[key]))
        one = step["data"].get("next_1_hours", {}).get("details", {})
        six = step["data"].get("next_6_hours", {}).get("details", {})
        if "precipitation_amount" in one:
            if t not in covered:
                run.series["precipitation"].append((t, one["precipitation_amount"]))
                covered.add(t)
        elif "precipitation_amount" in six:
            for k in range(6):
                if t + k * HOUR not in covered:
                    run.series["precipitation"].append((t + k * HOUR, six["precipitation_amount"] / 6.0))
                    covered.add(t + k * HOUR)
    run.series = {k: v for k, v in run.series.items() if v}
    return run


def fetch_json(url: str, user_agent: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/geo+json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_nws(lat: float, lon: float, user_agent: str) -> Run:
    point = fetch_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", user_agent)
    run = nws_run(fetch_json(point["properties"]["forecastGridData"], user_agent))
    run.timezone = point["properties"].get("timeZone")
    return run


def fetch_metno(lat: float, lon: float, user_agent: str) -> Run:
    return metno_run(fetch_json(f"https://api.met.no/weatherapi/locationforecast/2.0/compact"
                                f"?lat={lat:.4f}&lon={lon:.4f}", user_agent))


def daily(run: Run, tz: _dt.tzinfo = UTC) -> list:
    """Per day in `tz`: min and max temperature, rain, hours at or below 0 °C."""
    days = {}
    for t, v in run.series.get("air_temperature", []):
        d = days.setdefault(t.astimezone(tz).date(), {"min": v, "max": v, "rain": 0.0, "frost_h": 0})
        d["min"], d["max"] = min(d["min"], v), max(d["max"], v)
        d["frost_h"] += v <= 0.0
    for t, v in run.series.get("precipitation", []):
        d = days.get(t.astimezone(tz).date())
        if d is not None:
            d["rain"] += v
    return sorted(days.items())


def to_json(run: Run) -> dict:
    return {"issued_at": run.issued_at.isoformat(), "source": run.source, "where": run.where,
            "timezone": run.timezone, "units": run.units,
            "series": {k: [(t.isoformat(), v) for t, v in vs] for k, vs in run.series.items()}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", choices=("nws", "metno"))
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--user-agent", default="fieldmesh/0.1",
                    help="MET Norway requires the application and a contact in it")
    ap.add_argument("--json", help="write the run here")
    ap.add_argument("--tz", help="IANA time zone for the daily summary (NWS supplies one)")
    args = ap.parse_args(argv)
    if args.source == "metno" and args.user_agent == "fieldmesh/0.1":
        print("MET Norway's terms ask for a contact in the User-Agent: pass --user-agent "
              "'yourapp/1.0 you@example.org'", file=sys.stderr)
        return 2
    run = (fetch_nws if args.source == "nws" else fetch_metno)(args.lat, args.lon, args.user_agent)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as h:
            json.dump(to_json(run), h, indent=1)
    print(f"{run.source}, {run.where}, issued {run.issued_at:%Y-%m-%d %H:%M} UTC")
    zone = args.tz or run.timezone
    tz = ZoneInfo(zone) if zone else UTC
    if zone:
        print(f"  days in {zone}")
    for day, d in daily(run, tz):
        frost = f", {d['frost_h']} h at or below 0 °C" if d["frost_h"] else ""
        print(f"  {day}  {d['min']:5.1f} – {d['max']:5.1f} °C, rain {d['rain']:4.1f} mm{frost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
