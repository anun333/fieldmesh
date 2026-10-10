#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Collect forecast runs into a farm's log, one run per call — for cron.

    python3 tools/forecast_collect.py farm-log.jsonl --lat 35.0645 --lon -86.5914

Each call fetches the current run (NWS by default; `--source metno --user-agent ...`
elsewhere) and appends it to the log on one `forecast` datastream per variable (Q26). The
datastreams are declared on the first call and found again by their names, which live in
the log as labels — "NWS forecast: air temperature" — so there is no side file to lose.
A run already in the log is skipped, so calling more often than the source updates costs
nothing but the fetch.

A season of runs in the log, next to the farm's own station, is what scores the forecast
for this place (tools/forecast_score.py; tools/nbm_verify.py shows the result on NOAA's
archive). Morning and dusk from cron, say — the NWS grid updates about hourly, but a farm
acts on the forecast at dusk, and every run kept costs log space: some 185 hours of each
variable, each with its range-check assertion, about 470 KB a run for two variables, so
about 350 MB a year at two runs a day:

    17 6,18 * * *  cd ~/dev/fieldmesh && python3 tools/forecast_collect.py ~/farm/log.jsonl --lat 35.0645 --lon -86.5914

Nothing is scheduled by this tool itself; adding that line is the farm's decision.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import forecast_sources as FS  # noqa: E402
import forecast as FC  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
from ids import uuid7  # noqa: E402
from model import Datastream, DatastreamKind, Label  # noqa: E402

UTC = _dt.timezone.utc
SOURCE_NAMES = {"nws": "NWS", "metno": "MET Norway"}

#: What each variable can physically be, by unit — the range check's bounds, declared on
#: the datastream. Wide on purpose: they catch a broken feed or a mixed-up unit, not
#: weather that is merely extreme.
BOUNDS = {"Cel": (-60.0, 60.0), "[degF]": (-76.0, 140.0), "%": (0.0, 100.0),
          "km/h": (0.0, 400.0), "m/s": (0.0, 110.0), "mm": (0.0, 300.0)}


def stream_name(source: str, variable: str) -> str:
    return f"{SOURCE_NAMES[source]} forecast: {variable.replace('_', ' ')}"


def ensure_datastreams(log, state, run: FS.Run, source: str, *, thing=None, feature=None) -> dict:
    """{variable: datastream id}, declaring and naming any not yet in the log. A unit
    that changed under a name is a new datastream, never a silent re-reading."""
    out = {}
    now = _dt.datetime.now(tz=UTC)
    for variable, unit in run.units.items():
        name = stream_name(source, variable)
        existing = [e for e in state.entities_named(name)
                    if e in state.datastreams and state.datastreams[e].unit == unit
                    and state.datastreams[e].kind is DatastreamKind.FORECAST]
        if existing:
            out[variable] = existing[0]
            continue
        lo, hi = BOUNDS.get(unit, (None, None))
        ds = Datastream(id=uuid7(), thing=thing or uuid7(), sensor=uuid7(), feature=feature or uuid7(),
                        observed_property=FS.VARIABLES[variable][0], unit=unit,
                        kind=DatastreamKind.FORECAST, expected_interval=3600.0, max_latency=3600.0,
                        thresholds={"min": lo, "max": hi},
                        probability_of=run.events.get(variable))
        label = Label(id=uuid7(), entity=ds.id, name=name, set_at=now,
                      description=f"{run.source}, {run.where}")
        for record in (ds, label):
            log.append_record(record)
            state.add(record)
        out[variable] = ds.id
    return out


def collect(log_path: str, run: FS.Run, source: str, variables=None) -> dict:
    """Append one run to the log at `log_path`; `variables` limits which series are kept."""
    if variables:
        run.series = {k: v for k, v in run.series.items() if k in variables}
        run.units = {k: v for k, v in run.units.items() if k in variables}
    log = L.Log(log_path)
    state = P.state_from_log(log)
    ids = ensure_datastreams(log, state, run, source)
    report = {}
    for variable, values in run.series.items():
        r = FC.ingest(log, state, ids[variable], run.issued_at, values, uncertainty_s=1800.0,
                      provenance=run.provenance())
        report[variable] = (r.written, r.already_present)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--source", choices=("nws", "metno"), default="nws")
    ap.add_argument("--user-agent", default="fieldmesh/0.1")
    ap.add_argument("--variables", default="air_temperature,precipitation",
                    help="which to keep, of air_temperature, precipitation, relative_humidity, "
                         "wind_speed and precipitation_probability; each run re-forecasts some "
                         "185 hours, so every variable kept twice a day adds about 170 MB a year")
    args = ap.parse_args(argv)
    fetch = FS.fetch_nws if args.source == "nws" else FS.fetch_metno
    run = fetch(args.lat, args.lon, args.user_agent)
    report = collect(args.log, run, args.source, set(args.variables.split(",")))
    parts = ", ".join(f"{v}: {w} new, {a} already" for v, (w, a) in report.items())
    print(f"{run.source} issued {run.issued_at:%Y-%m-%d %H:%M} UTC — {parts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
