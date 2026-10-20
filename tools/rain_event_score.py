#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Score a farm's collected rain forecasts day by day, as the backtests' forecaster is set:
how often a rain day was forecast dry, and a dry day forecast wet, at a day's lead.

    python3 tools/rain_event_score.py forecasts.jsonl station.jsonl

`forecasts.jsonl` is a log `tools/forecast_collect.py` fills ("NWS forecast:
precipitation"); `station.jsonl` one `tools/scan_collect.py` fills, the station's own rain.
For each issue, the UTC day whose noon lies 12 to 36 hours after it: a rain day if the
station had 1 mm or more, forecast wet if the issue's hours that day sum to 1 mm or more.
The harness's forecaster misses a rain day a quarter of the time at a day's lead and
forecasts a dry day wet one in twelve (`modules/soilwater/backtest.forecast_skill`); this
says how a real forecast for the farm compares, each rate with a 90% interval (Wilson).
Only days the station read every hour of count.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from model import DatastreamKind, Usable  # noqa: E402

HOUR = _dt.timedelta(hours=1)
WET_MM = 1.0
#: Millimetres in each unit a rain gauge or forecast reports in (UCUM).
TO_MM = {"mm": 1.0, "[in_i]": 25.4}


def to_mm(ds) -> float:
    if ds.unit not in TO_MM:
        raise SystemExit(f"rain in {ds.unit!r}: not a unit this knows ({sorted(TO_MM)})")
    return TO_MM[ds.unit]
#: The harness's rates (`backtest.forecast_skill`).
ASSUMED = {"miss": 0.25, "false_alarm": 1 / 12}


def wilson(k: int, n: int, z: float = 1.645) -> tuple:
    """A share's 90% interval."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def station_days(state) -> dict:
    """`{day: mm}` for each UTC day the station's rain gauge read all 24 hours of."""
    hours: dict = {}
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    for ds in state.datastreams.values():
        if ds.observed_property != V.PRECIPITATION_DEPTH or ds.kind is DatastreamKind.FORECAST:
            continue
        mm = to_mm(ds)
        for o in state.live_observations_of(ds.id):
            if isinstance(o.result, (int, float)) and state.quality_as_of(o.id, now)[0] is Usable.GOOD:
                hours[o.measured_at.replace(minute=0, second=0, microsecond=0)] = float(o.result) * mm
    days: dict = {}
    for t, mm in hours.items():
        days.setdefault(t.date(), []).append(mm)
    return {d: sum(v) for d, v in days.items() if len(v) == 24}


def issues(state) -> dict:
    """`{issued_at: {hour: mm}}` of the precipitation forecast, every issue kept."""
    out: dict = {}
    for ds in state.datastreams.values():
        if ds.observed_property != V.PRECIPITATION_DEPTH or ds.kind is not DatastreamKind.FORECAST:
            continue
        mm = to_mm(ds)
        for o in state.observations_of(ds.id):
            if isinstance(o.result, (int, float)):
                out.setdefault(o.issued_at, {})[o.measured_at] = float(o.result) * mm
    return out


def score(forecast_state, station_state) -> dict:
    days = station_days(station_state)
    rows = []
    for issued, hours in sorted(issues(forecast_state).items()):
        for day, observed in sorted(days.items()):
            noon = _dt.datetime.combine(day, _dt.time(12), tzinfo=_dt.timezone.utc)
            lead_h = (noon - issued).total_seconds() / 3600.0
            if not 12 <= lead_h < 36:
                continue
            day_hours = [mm for t, mm in hours.items() if t.date() == day]
            if len(day_hours) < 24:
                continue
            rows.append({"issued_at": issued.isoformat(), "day": day.isoformat(),
                         "observed_mm": round(observed, 1), "forecast_mm": round(sum(day_hours), 1)})
    wet = [r for r in rows if r["observed_mm"] >= WET_MM]
    dry = [r for r in rows if r["observed_mm"] < WET_MM]
    missed = sum(r["forecast_mm"] < WET_MM for r in wet)
    false = sum(r["forecast_mm"] >= WET_MM for r in dry)
    return {"issues_scored": len({r["issued_at"] for r in rows}), "days": len({r["day"] for r in rows}),
            "rain_day_issues": len(wet), "dry_day_issues": len(dry),
            "miss": (missed / len(wet) if wet else None, wilson(missed, len(wet))),
            "false_alarm": (false / len(dry) if dry else None, wilson(false, len(dry))),
            "assumed": ASSUMED, "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("forecasts")
    ap.add_argument("station")
    args = ap.parse_args(argv)
    s = score(P.state_from_log(L.Log(args.forecasts)), P.state_from_log(L.Log(args.station)))
    for r in s.pop("rows"):
        print(f"  issued {r['issued_at'][:16]}  {r['day']}  forecast {r['forecast_mm']:5.1f} mm  "
              f"fell {r['observed_mm']:5.1f} mm")
    for k in ("miss", "false_alarm"):
        rate, (lo, hi) = s[k]
        shown = "n/a" if rate is None else f"{rate:.2f} (90%: {lo:.2f} to {hi:.2f})"
        print(f"{k}: {shown}; the harness assumes {ASSUMED[k]:.2f}")
    print({k: v for k, v in s.items() if k not in ("miss", "false_alarm", "assumed")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
