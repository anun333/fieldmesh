#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Watering by the clock, by the forecast and by the soil, backtested on recorded summers.

    python3 irrigation_drill.py                              # McAllister Farm, summer 2013
    python3 irrigation_drill.py --weather FILE --summers 1991-2020

One bed, one season of recorded weather (sim/physics.RecordedClimate), the forecasts a
forecaster issues for it four times a day stored in a layer-zero log (Q26), and five
ways to decide each morning whether to water — every one run on identical weather:

| policy | waters |
| --- | --- |
| `timer` | `DOSE_MM` every second morning, whatever happens — a drip timer, as most farms run |
| `rain_skip` | the timer, but skips a watering when the live forecast at 04:00 gives `SKIP_MM` or more in the next 24 hours |
| `oracle_skip` | the same rule knowing the rain that will actually fall — the most a forecast could save |
| `soil` | on any morning the bed's own probe reads below the refill point (a third of the available water used), back up to field capacity |
| `soil_skip` | the soil rule, skipping when `SKIP_MM` or more is forecast |

Scored per policy: water applied; water drained below the roots, which is water paid for
and nitrate carried off; mean crop stress; and hours of stress at 0.5 or more — the
readily available water gone, FAO-56's usual depletion fraction.

The rules are stand-ins for a layer 2 irrigation module (not built; Q12 puts it second):
they are here to measure what a forecast is worth to one before anyone writes it, and to
be backtested the way §11 will require.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import random
import statistics
import sys

import forecast_drill as FD
import forecaster as FCS
import physics as ph

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "sdk"))
import forecast as FC  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import DatastreamKind  # noqa: E402

UTC = _dt.timezone.utc
HOUR = _dt.timedelta(hours=1)
SUMMER = os.path.join(HERE, "data", "mcallister-2013-summer.csv")
DOSE_MM = 12.0
SKIP_MM = 10.0
DECIDE_HOUR = 4
WATER_HOUR = 5
POLICIES = ("timer", "rain_skip", "oracle_skip", "soil", "soil_skip")


def bed() -> ph.SoilBed:
    """A 30 cm root zone in a silt loam, full canopy (Kc 1.05), starting at field capacity."""
    return ph.SoilBed(name="field", depth_mm=300.0, saturation=0.45, field_capacity=0.30,
                      wilting_point=0.12, crop_coefficient=1.05, theta=0.30)


def refill_point(b: ph.SoilBed) -> float:
    return b.field_capacity - (b.field_capacity - b.wilting_point) / 3.0


def forecasts(climate, start: _dt.datetime, days: float, skill: FCS.Skill, seed: int,
              issue_every_h: int = 6):
    """The season's rain forecasts in a log, and the hourly truth they were made from."""
    truth = FD.hourly_truth(climate, start, days)
    state, log = P.State(), L.Log()
    fc = FD.declare(state, log, kind=DatastreamKind.FORECAST, unit="mm", prop=V.PRECIPITATION_DEPTH,
                    expected_interval=issue_every_h * 3600.0, sensor=uuid7(), thing=uuid7(),
                    feature=uuid7())
    f = FCS.Forecaster(truth, skill=skill, seed=seed)
    issued = start - 6 * HOUR
    end = truth[-1][0]
    while issued < end:
        FC.ingest(log, state, fc.id, issued, f.run(issued)["precipitation"], uncertainty_s=1800.0,
                  received_at=issued, provenance={"source": "sim/forecaster.py"})
        issued += issue_every_h * HOUR
    return state, fc, truth


def run_policy(policy: str, climate, start: _dt.datetime, days: float, state, fc, truth,
               seed: int = 1, probe_noise: float = 0.01) -> dict:
    b = bed()
    world = ph.World(start=start, climate=climate, beds=[b])
    rain_by_hour = {t: mm for t, _, mm in truth}
    probe = random.Random(seed)
    applied, dose_now, decisions, skipped = 0.0, 0.0, 0, 0
    stress, stressed_h, rain = [], 0.0, 0.0
    for _ in range(int(days * 24 * 12)):
        when = world.when
        if when.hour == DECIDE_HOUR and when.minute == 0:
            day = (when.date() - start.date()).days
            ahead = sum(o.result for o in state.forecast(fc.id, when, when + 24 * HOUR))
            really = sum(rain_by_hour.get(when + k * HOUR, 0.0) for k in range(24))
            reading = b.theta + probe.gauss(0.0, probe_noise)
            want = 0.0
            if policy in ("timer", "rain_skip", "oracle_skip") and day % 2 == 0:
                want = DOSE_MM
            elif policy in ("soil", "soil_skip") and reading < refill_point(b):
                want = max(0.0, (b.field_capacity - reading) * b.depth_mm)
            if want:
                decisions += 1
                if (policy in ("rain_skip", "soil_skip") and ahead >= SKIP_MM) or \
                        (policy == "oracle_skip" and really >= SKIP_MM):
                    want = 0.0
                    skipped += 1
            dose_now = want / 12.0                       # over the hour from 05:00
        if when.hour == WATER_HOUR and dose_now:
            world.irrigate("field", dose_now)
            applied += dose_now
        if when.hour == WATER_HOUR + 1 and when.minute == 0:
            dose_now = 0.0
        truth_tick = world.step()
        rain += truth_tick.weather.rain_mm
        s = truth_tick.soil_stress["field"]
        stress.append(s)
        if s >= 0.5:
            stressed_h += 1.0 / 12.0
    return {"policy": policy, "applied_mm": applied, "drained_mm": b.drained_mm, "runoff_mm": b.runoff_mm,
            "et_mm": b.et_mm, "rain_mm": rain, "mean_stress": statistics.mean(stress),
            "stressed_h": stressed_h, "waterings_wanted": decisions, "skipped": skipped}


def season(weather: str, start: _dt.datetime, days: float, *, skill: FCS.Skill = FCS.Skill(),
           seed: int = 1, climate=None, policies=POLICIES) -> dict:
    climate = climate or ph.RecordedClimate.from_csv(weather, seed=seed)
    state, fc, truth = forecasts(climate, start, days, skill, seed)
    return {p: run_policy(p, climate, start, days, state, fc, truth, seed) for p in policies}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weather", default=SUMMER)
    ap.add_argument("--summers", help="YEAR-YEAR, June 1 to August 31 each")
    ap.add_argument("--sd0", type=float, default=FCS.Skill.sd0_c)
    ap.add_argument("--miss", type=float, default=FCS.Skill.miss)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)
    skill = FCS.Skill(sd0_c=args.sd0, miss=args.miss)
    if args.summers:
        a, _, b = args.summers.partition("-")
        years = range(int(a), int(b) + 1)
    else:
        years = [2013]
    climate = ph.RecordedClimate.from_csv(args.weather, seed=args.seed)
    totals = {p: [] for p in POLICIES}
    for year in years:
        start = _dt.datetime(year, 6, 1, tzinfo=UTC)
        r = season(args.weather, start, 92, skill=skill, seed=args.seed + year, climate=climate)
        for p, v in r.items():
            totals[p].append(v)
        if len(years) > 1:
            t, s = r["timer"], r["rain_skip"]
            print(f"  {year}: rain {t['rain_mm']:4.0f} mm; timer {t['applied_mm']:4.0f}, rain_skip "
                  f"{s['applied_mm']:4.0f}, soil {r['soil']['applied_mm']:4.0f}, soil_skip {r['soil_skip']['applied_mm']:4.0f} mm",
                  flush=True)
    n = len(years)
    rain = statistics.mean(r["rain_mm"] for r in totals["timer"])
    print(f"\n{n} summer(s), June 1 – August 31, rain {rain:.0f} mm on average; a 30 cm root zone; dose "
          f"{DOSE_MM:g} mm; skip at {SKIP_MM:g} mm forecast in 24 h; mean per summer:")
    print("  policy        applied   drained   transpired   mean stress   hours stressed ≥0.5   skipped")
    for p in POLICIES:
        rows = totals[p]
        avg = lambda k: statistics.mean(r[k] for r in rows)
        print(f"  {p:<12} {avg('applied_mm'):7.0f} mm {avg('drained_mm'):6.0f} mm {avg('et_mm'):8.0f} mm"
              f"   {avg('mean_stress'):10.3f}   {avg('stressed_h'):16.0f}   {avg('skipped'):7.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
