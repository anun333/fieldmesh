#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Forecast each silent soil probe's reading into a farm's log, one run per call — for cron.
Optional: it runs Timestral (`sdk/tsfm.py`), whose weights' licence a farm must accept.

    python3 tools/probe_forecast.py farm-log.jsonl --accept-weights-licence \\
        [--rain DATASTREAM --air DATASTREAM] [--offline]

For each bed with soil probes in the log, each probe that has given no good reading for
`--stale-h` hours (6), but did within `--max-silence-h` (a week), while another in the
same bed still reads: the model forecasts its reading from its last good hour to
`--ahead-h` (24) past now, from its last 1,024 hours, the other probes in the bed and the
station's rain and air (`--rain`, `--air`) through those hours. The median goes into the
log as a forecast (Q26) on a datastream of its own, installed in the bed at the probe's
depth, each value carrying the run's receipt as its provenance: for a person to read. The
soil advisory does not take it. Tried in place of its own rule for carrying the silent
probe, it lost a tomato crop more at Davis in the backtests of 2026-10-20
(docs/notes/soilwater-backtests.md), though closer to the truth on real records.

On ISMN's records of six SCAN stations a probe hidden three days was carried this way 40
to 65% closer to the truth than by any rule (docs/notes/timestral.md). The day ahead was
0.0067 off where the forecast at the run's time held was 0.0070: a little better in the
Southwest, no better in Tennessee. Nothing is
scheduled by this tool; adding it to cron, hourly say, is the farm's decision.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import forecast as FC  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import tsfm as TS  # noqa: E402
from ids import uuid7  # noqa: E402
from model import Datastream, DatastreamKind, Installation, Label  # noqa: E402

HOUR = _dt.timedelta(hours=1)


def stream_name(probe) -> str:
    return f"Timestral forecast of soil probe {probe.id}"


def ensure_stream(log, state, probe, feature, depth_m: float, at: _dt.datetime):
    """The forecast datastream for `probe`, declared, installed at its depth and named on
    the first run, found again by its name after."""
    name = stream_name(probe)
    for e in state.entities_named(name):
        if e in state.datastreams and state.datastreams[e].kind is DatastreamKind.FORECAST:
            return state.datastreams[e]
    ds = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(), feature=feature,
                    observed_property=probe.observed_property, unit=probe.unit,
                    kind=DatastreamKind.FORECAST, expected_interval=3600.0, max_latency=3600.0,
                    thresholds={"min": 0.0, "max": 0.6})
    records = (ds, Installation(id=uuid7(), device=ds.sensor, feature=feature, installed_at=at,
                                depth_m=depth_m, note="the forecast of the probe at this depth"),
               Label(id=uuid7(), entity=ds.id, name=name, set_at=at,
                     description="tools/probe_forecast.py, Timestral"))
    for record in records:
        log.append_record(record)
        state.add(record)
    return ds


def forecast_silent(log, state, model, at: _dt.datetime, *, station: dict | None = None,
                    stale_h: int = 6, max_silence_h: int = 168, ahead_h: int = 24,
                    ablate: bool = True) -> list:
    """One run: `[(probe id, hours forecast, receipt)]` for each silent probe forecast.
    Without `ablate`, the receipt does not say how far each input moved it (`tsfm.run`)."""
    done = []
    for feature in sorted({inst.feature for inst in state.installations.values()}, key=lambda u: u.int):
        probes = TS.soil_probes(state, feature, at)
        if len(probes) < 2:
            continue
        reading = {ds.id for ds, _ in probes if TS.last_good(state, ds.id, at, stale_h)}
        for ds, depth in probes:
            if ds.id in reading:
                continue
            last = TS.last_good(state, ds.id, at, max_silence_h)
            others = {f"probe at {round(d * 100)} cm": n.id for n, d in probes if n.id in reading}
            if last is None or not others:
                continue
            start = last + HOUR
            horizon = int((at - start) / HOUR) + 1 + ahead_h
            forecast, receipt = TS.run(model, state, ds.id, {**others, **(station or {})}, start,
                                       horizon, at, ablate=ablate)
            stream = ensure_stream(log, state, ds, feature, depth, at)
            FC.ingest(log, state, stream.id, at.replace(minute=0, second=0, microsecond=0),
                      list(zip(forecast.hours, forecast.median)), uncertainty_s=1800.0, received_at=at,
                      provenance={"source": "tools/probe_forecast.py", **receipt})
            done.append((ds.id, horizon, receipt))
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--accept-weights-licence", action="store_true",
                    help="the farm accepts Timestral's weights' licence (sdk/tsfm.py)")
    ap.add_argument("--model", default=TS.DEFAULT_MODEL)
    ap.add_argument("--revision", help="the weights' commit, to pin them")
    ap.add_argument("--offline", action="store_true", help="the weights from the cache alone")
    ap.add_argument("--rain", help="the station's rain datastream")
    ap.add_argument("--air", help="the station's air temperature datastream")
    ap.add_argument("--at", help="the run's time, ISO 8601; now by default")
    args = ap.parse_args(argv)
    try:
        model = TS.load(args.model, accept_weights_licence=args.accept_weights_licence,
                        revision=args.revision, offline=args.offline)
    except TS.LicenceNotAccepted as e:
        print(e, file=sys.stderr)
        return 2
    at = (_dt.datetime.fromisoformat(args.at) if args.at
          else _dt.datetime.now(tz=_dt.timezone.utc)).replace(second=0, microsecond=0)
    station = {name: uuid.UUID(v) for name, v in (("rain", args.rain), ("air", args.air)) if v}
    log = L.Log(args.log)
    state = P.state_from_log(log)
    for probe, horizon, receipt in forecast_silent(log, state, model, at, station=station):
        print(f"probe {probe}: {horizon} hours forecast; moved by {receipt['moved_by']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
