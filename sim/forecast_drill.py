#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Forecasts through layer zero, scored against the weather that happened.

    python3 forecast_drill.py                         # McAllister Farm, spring 2007
    python3 forecast_drill.py --sd0 2.5 --per-day 0.6 # a worse forecast
    python3 forecast_drill.py --bias 1.5              # one that runs warm

The virtual farm lives through McAllister Farm's real spring of 2007 (sim/data/, NASA
POWER), warm March and Easter freeze. A weather station measures its air; a forecaster
issues a run every six hours with an error of a declared size (sim/forecaster.py);
every run lands in the log on a `forecast` datastream (sdk/forecast.py, Q26), and the
station's readings on a raw one. Then two questions, each answered from the log alone:

* **How good were the forecasts here?** Every stored run against what the station
  measured, by lead day (`sdk.forecast.verify`). The producer knows the error it added;
  the log has to give it back.
* **Would a frost watch have helped?** At each issue the watch reads the live forecast
  for the next 48 hours and warns if it falls to `--warn` (0 °C by default, a margin
  over the −2.2 °C that kills open bloom). Each frost night the station recorded is
  scored by how many hours of warning it got — 12 is enough to cover a crop, light
  heaters or close a tunnel — and each warning that no frost followed is a false
  alarm, the cost that teaches a farmer to ignore the next one.

The watch is a stand-in for a layer 1 rule, which is not built: it is here to show
forecasts arriving as data and being acted on, and to be scored the way such a rule
will have to be (v0.1 §11: backtested before it goes live).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import random
import statistics
import sys

import forecaster as FCS
import physics as ph

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "sdk"))
import forecast as FC  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import ClockQuality, Datastream, DatastreamKind, Observation  # noqa: E402

UTC = _dt.timezone.utc
HOUR = _dt.timedelta(hours=1)
WEATHER = os.path.join(HERE, "data", "mcallister-2007-spring.csv")
DAMAGE_C = -2.2
ENOUGH_LEAD_H = 12


def hourly_truth(climate, start: _dt.datetime, days: float) -> list:
    """`(top of the hour, air °C, rain mm in the hour)` from a world on `climate`."""
    world = ph.World(start=start, climate=climate)
    out, rain = [], 0.0
    for truth in world.run(days=days):
        rain += truth.weather.rain_mm
        if truth.when.minute == 0:
            out.append([truth.when, truth.weather.air_temp_c, 0.0])
        if truth.when.minute == 55 and out:
            out[-1][2], rain = round(rain, 3), 0.0
    return [tuple(x) for x in out]


def declare(state, log, *, kind, unit, prop, expected_interval, sensor, thing, feature):
    ds = Datastream(id=uuid7(), thing=thing, sensor=sensor, feature=feature, observed_property=prop,
                    unit=unit, kind=kind, expected_interval=expected_interval, max_latency=3600.0)
    log.append_record(ds)
    state.add(ds)
    return ds


def drill(*, start: _dt.datetime, days: float, skill: FCS.Skill, warn_c: float = 0.0,
          seed: int = 1, issue_every_h: int = 6, station_noise_c: float = 0.2) -> dict:
    climate = ph.RecordedClimate.from_csv(WEATHER, seed=seed)
    truth = hourly_truth(climate, start, days)
    state, log = P.State(), L.Log()
    thing, feature = uuid7(), uuid7()
    station = declare(state, log, kind=DatastreamKind.RAW, unit="Cel", prop=V.AIR_TEMPERATURE,
                      expected_interval=3600.0, sensor=uuid7(), thing=thing, feature=feature)
    fc_temp = declare(state, log, kind=DatastreamKind.FORECAST, unit="Cel", prop=V.AIR_TEMPERATURE,
                      expected_interval=issue_every_h * 3600.0, sensor=uuid7(), thing=thing, feature=feature)
    fc_rain = declare(state, log, kind=DatastreamKind.FORECAST, unit="mm", prop=V.PRECIPITATION_DEPTH,
                      expected_interval=issue_every_h * 3600.0, sensor=uuid7(), thing=thing, feature=feature)
    noise = random.Random(seed)
    for seq, (t, temp, _) in enumerate(truth):
        obs = Observation(id=uuid7(), datastream=station.id, measured_at=t, measured_at_uncertainty=1.0,
                          received_at=t, result=round(temp + noise.gauss(0.0, station_noise_c), 2),
                          clock_quality=ClockQuality.GPS, node="!wx01", boot=1, seq=seq % 0x10000)
        log.append_record(obs)
        state.add(obs)

    forecaster = FCS.Forecaster(truth, skill=skill, seed=seed)
    warnings = []                                   # (issued_at, first forecast frost hour)
    issued, runs = start, 0
    end = truth[-1][0]
    while issued < end - 48 * HOUR:
        run = forecaster.run(issued)
        prov = {"source": "sim/forecaster.py", "skill": repr(skill)}
        FC.ingest(log, state, fc_temp.id, issued, run["air_temperature"], uncertainty_s=1800.0,
                  received_at=issued, provenance=prov)
        FC.ingest(log, state, fc_rain.id, issued, run["precipitation"], uncertainty_s=1800.0,
                  received_at=issued, provenance=prov)
        ahead = state.forecast(fc_temp.id, issued, issued + 48 * HOUR)
        cold = [o.measured_at for o in ahead if o.result <= warn_c]
        if cold:
            warnings.append((issued, cold[0]))
        runs += 1
        last_issue = issued
        issued += issue_every_h * HOUR

    # Frost nights the station recorded: runs of hours at or below the damage line.
    measured = sorted((o.measured_at, o.result) for o in state.observations_of(station.id))
    events, current = [], None
    for t, v in measured:
        if v <= DAMAGE_C:
            if current is None or t - current[-1] > 6 * HOUR:
                current = [t, t]
                events.append(current)
            current[-1] = t
    scored = []
    for first, last in events:
        leads = [(first - issued).total_seconds() / 3600.0 for issued, _ in warnings
                 if issued <= first and issued + 48 * HOUR >= first]
        scored.append({"start": first, "end": last, "warned_h": max(leads) if leads else 0.0})
    false_alarms = [w for w in warnings
                    if not any(w[0] <= e["start"] <= w[0] + 48 * HOUR or e["start"] <= w[1] <= e["end"] + 12 * HOUR
                               for e in scored)]
    errors = FC.verify(state, fc_temp.id, station.id)
    by_day = {}
    for lead, errs in errors.items():
        by_day.setdefault(lead // 24, []).extend(errs)
    verification = {day: {"n": len(e), "mae": statistics.mean(abs(x) for x in e),
                          "bias": statistics.mean(e), "sd": statistics.pstdev(e)}
                    for day, e in sorted(by_day.items())}
    problems = state.validate()
    return {"events": scored, "warnings": warnings, "false_alarms": false_alarms,
            "verification": verification, "runs": runs,
            "forecast_rows": len(state.observations_of(fc_temp.id)),
            "live_hours": len(state.forecast(fc_temp.id, start, end + HOUR)),
            "problems": problems,
            "health": state.health_of(fc_temp.id, last_issue + HOUR).value,
            # §4.2: stale after three intervals without a run
            "health_later": state.health_of(fc_temp.id, last_issue + 4 * issue_every_h * HOUR).value}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2007-03-15")
    ap.add_argument("--days", type=float, default=45.0)
    ap.add_argument("--sd0", type=float, default=FCS.Skill.sd0_c)
    ap.add_argument("--per-day", type=float, default=FCS.Skill.sd_per_day_c)
    ap.add_argument("--bias", type=float, default=0.0)
    ap.add_argument("--warn", type=float, default=0.0, help="warn when the forecast falls to this, °C")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)
    skill = FCS.Skill(sd0_c=args.sd0, sd_per_day_c=args.per_day, bias_c=args.bias)
    start = _dt.datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    r = drill(start=start, days=args.days, skill=skill, warn_c=args.warn, seed=args.seed)
    print(f"{r['forecast_rows']} forecast values from {r['runs']} runs in the log; {r['live_hours']} hours "
          f"live (the latest issue each); the datastream {r['health']} after its last run and "
          f"{r['health_later']} once runs stop arriving; log problems: {len(r['problems'])}")
    print("\nForecast error against the station, from the log (forecast − measured, °C):")
    print("  lead day      n    MAE   bias     sd   (declared sd at mid-day)")
    for day, v in r["verification"].items():
        print(f"  {day:>8} {v['n']:>6} {v['mae']:6.2f} {v['bias']:+6.2f} {v['sd']:6.2f}   ({skill.sd(day * 24 + 12):.2f})")
    print(f"\nFrost watch: warn at {args.warn:g} °C within 48 h; damage at {DAMAGE_C} °C; "
          f"{ENOUGH_LEAD_H} h of warning is enough.")
    for e in r["events"]:
        verdict = "in time" if e["warned_h"] >= ENOUGH_LEAD_H else ("late" if e["warned_h"] else "missed")
        print(f"  frost {e['start']:%b %d %H:%M}–{e['end']:%H:%M}: warned {e['warned_h']:.0f} h ahead — {verdict}")
    print(f"  {len(r['warnings'])} warnings issued, {len(r['false_alarms'])} with no frost after them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
