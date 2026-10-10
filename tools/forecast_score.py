#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Score the forecasts a farm collected against its station.

    python3 tools/forecast_score.py ~/dev/fieldmesh-data/mcallister-forecasts.jsonl

Reads a log that tools/forecast_collect.py has been filling, finds the forecast
datastream by its name ("NWS forecast: air temperature"), fetches the station's hourly
air temperature for the same weeks (a SCAN station through NRCS AWDB, McAllister Farm's
by default), and scores every collected run against it the way tools/nbm_verify.py
scores NOAA's archive: error by lead day, cold-night bias, and the frost watch night by
night. The station is added to an in-memory copy only — the collected log is not changed.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import nbm_verify as N  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import ClockQuality, Datastream, DatastreamKind, Observation  # noqa: E402


def with_station(state, fc_id, station: list, unit: str = "[degF]"):
    """The station's readings, as a raw datastream beside the forecast, in memory."""
    fc = state.datastreams[fc_id]
    raw = Datastream(id=uuid7(), thing=fc.thing, sensor=uuid7(), feature=fc.feature,
                     observed_property=V.AIR_TEMPERATURE, unit=unit, kind=DatastreamKind.RAW,
                     expected_interval=3600.0, max_latency=3600.0)
    state.add(raw)
    for t, v in station:
        state.add(Observation(id=uuid7(), datastream=raw.id, measured_at=t, measured_at_uncertainty=1800.0,
                              received_at=t, result=v, clock_quality=ClockQuality.NETWORK))
    return raw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--name", default="NWS forecast: air temperature")
    ap.add_argument("--station", default="2075:TN:SCAN")
    ap.add_argument("--utc-offset", type=float, default=-6.0)
    ap.add_argument("--cache", default=os.path.expanduser("~/dev/fieldmesh-data/cache"))
    args = ap.parse_args(argv)
    state = P.state_from_log(L.Log(args.log))
    named = [e for e in state.entities_named(args.name) if e in state.datastreams]
    if not named:
        print(f"no datastream named {args.name!r} in {args.log}", file=sys.stderr)
        return 2
    fc = state.datastreams[named[0]]
    rows = state.observations_of(fc.id)
    if not rows:
        print("no forecasts collected yet", file=sys.stderr)
        return 1
    first = min(o.issued_at for o in rows).date()
    last = max(o.measured_at for o in rows).date()
    today = _dt.datetime.now(tz=_dt.timezone.utc).date()
    os.makedirs(args.cache, exist_ok=True)
    station = N.scan_hourly(args.station, first, min(last, today), args.utc_offset, args.cache)
    raw = with_station(state, fc.id, station)
    s = N.score(state, raw, fc)
    runs = len({o.issued_at for o in rows})
    scored = sum(v["n"] for v in s["by_lead_day"].values())
    print(f"{args.name}: {runs} runs collected since {first}; {scored} forecast hours have a station "
          f"reading to score against (SCAN {args.station})")
    N.report(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
