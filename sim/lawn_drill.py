#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A lawn's sprinkler system and the add-ons it can take, backtested on recorded summers.

    python3 lawn_drill.py                                    # McAllister Farm, 2012 and 2013
    python3 lawn_drill.py --weather FILE --summers 1991-2020 --workers 3

A home lawn on an in-ground sprinkler system: a timer, spray heads, and nothing else. Then
the things that can be added to it without replacing it, one at a time and together, each
run on identical weather (docs/notes/lawn-sprinklers.md has the sources):

| policy | waters |
| --- | --- |
| `timer` | three mornings a week, 13 mm from spray heads at 05:00, whatever the weather: about 1.5 inches a week, the top of UT Extension's 1 to 1.5 (W161-F) |
| `twice_weekly` | the same heads, 13 mm twice a week: UT Extension's "½ inch ... no more than twice each week", deep and infrequent, a setting rather than hardware |
| `rain_sensor` | the timer, bypassed while a rain sensor is wet: 6.35 mm (¼ inch, the largest set point UF/IFAS AE221 recommends) in the last 24 hours, which covers the rain and the sensor's drying out, about 19 hours |
| `soil_sensor` | the timer, bypassed while a soil sensor at 7 cm reads above its set point: a bypass sensor (UF/IFAS AE437), calibrated as it would be, from its reading a day after a soaking, set at 62.5% of that, the middle of AE437's 50 to 75% |
| `cycle_soak` | the timer's 13 mm in three runs an hour apart, a controller setting |
| `rotary` | the timer with its spray nozzles swapped for rotary nozzles: 15 mm an hour in place of 40, run long enough to put down the same 13 mm |
| `weather` | the timer scaled each morning by yesterday's reference ET less its rain over the summer's mean, as a weather-based controller or an add-on ET sensor does; OpenSprinkler's ETo method with a summer baseline |
| `all` | the rain sensor, the soil sensor, cycle and soak, and rotary nozzles together |
| `on_demand` | a soil sensor that starts the watering rather than only stopping it (AE437's on-demand kind): at 05:00, below its set point, ten-minute spray runs an hour apart until the probe reads full again, at most four |

Spray heads put down 40 mm an hour, Rain Bird's 15 Series MPR at 30 psi on square spacing
(1.58 in/h); rotary nozzles 15 mm an hour, Rain Bird's RN (0.6 in/h).

The lawn is cool-season turf, tall fescue as Tennessee grows it: crop coefficient 0.95
(FAO-56 Table 12), roots in the top 15 cm (UT Extension wets "at least 6 inches"). It
grows on one of two soils (`physics.LayeredBed`):

* `native`: the silt loam the soil survey maps at McAllister Farm, field capacity 0.30,
  wilting point 0.12, saturation 0.42, taking water at 8 mm an hour (assumed);
* `yard`: what a builder leaves, 10 cm of sandy loam brought in over a compacted clay
  subsoil (`physics.SANDY_LOAM`, `physics.COMPACTED_CLAY`, round values, assumed).

Scored per policy: water applied; what ran off; what drained below the roots; hours of
drought stress (half of the available water gone); and hours the turf stood in water, its
top 5 cm within 0.02 of saturation, when it is short of air and prone to disease. What it
cannot score: how evenly the heads water (a nozzle swap or pressure regulation is bought
partly for that), roots growing deeper under deep watering, and the grass itself.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import os
import statistics
import sys

import physics as ph

HERE = os.path.dirname(os.path.abspath(__file__))
UTC = _dt.timezone.utc
STEP_MIN = ph.STEP.total_seconds() / 60.0

SPRAY_MM_H = 40.0
ROTARY_MM_H = 15.0
RUN_MM = 13.0
WATER_HOUR = 5
TIMER_DAYS = (0, 2, 4)                 # Monday, Wednesday, Friday
TWICE_DAYS = (0, 3)                    # Monday, Thursday
RAIN_SET_MM = 6.35
SOIL_PROBE_M = 0.07
SOIL_SET_SHARE = 0.625
CYCLES, SOAK_MIN = 3, 60.0
ON_DEMAND_RUN_MIN, ON_DEMAND_MAX = 10.0, 4
TURF_KC = 0.95
ROOTS_MM = 150.0

#: The survey's silt loam at McAllister Farm. Its intake rate and wetting-front suction
#: are assumed, typical of a silt loam.
SILT_LOAM = {"saturation": 0.42, "field_capacity": 0.30, "wilting_point": 0.12,
             "ks_mm_per_h": 8.0, "suction_mm": 170.0}
SOILS = ("native", "yard")
POLICIES = ("timer", "twice_weekly", "rain_sensor", "soil_sensor", "cycle_soak", "rotary",
            "weather", "all", "on_demand")


def lawn(soil: str) -> ph.LayeredBed:
    if soil == "native":
        horizons = (ph.Horizon(600, **SILT_LOAM),)
    elif soil == "yard":
        horizons = (ph.Horizon(100, **ph.SANDY_LOAM), ph.Horizon(500, **ph.COMPACTED_CLAY))
    else:
        raise ValueError(f"a soil is one of {SOILS}")
    return ph.LayeredBed(name="lawn", depth_mm=ROOTS_MM, horizons=horizons,
                         crop_coefficient=TURF_KC)


def calibrate(soil: str, climate, start: _dt.datetime) -> float:
    """A soil sensor's "full" reading, as AE437's automatic calibration takes it: soak
    the lawn, wait a day, read the probe."""
    bed, when = lawn(soil), start
    for n in range(int((WATER_HOUR + 4 + 24) * 60 / STEP_MIN)):
        hour = n * STEP_MIN / 60.0
        given = 10.0 * STEP_MIN / 60.0 if WATER_HOUR <= hour < WATER_HOUR + 4 else 0.0
        bed.step(climate.step(when), irrigation_mm=given)
        when += ph.STEP
    return bed.theta_at(SOIL_PROBE_M)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _eto_scale(climate, day: _dt.date, baseline: float) -> float:
    import irrigation_drill as D
    seen, e = climate.days.get(day), D.eto(climate, day)
    if not seen or e is None:
        return 1.0
    return min(2.0, max(0.0, (e - seen.get("PRECTOTCORR", 0.0)) / baseline))


def run(policy: str, soil: str, climate, start: _dt.datetime, days: int = 92,
        baseline: float | None = None, soil_set: float = SOIL_SET_SHARE) -> dict:
    """One summer of one policy on one soil; a soil sensor set at `soil_set` of its
    calibrated reading."""
    if policy not in POLICIES:
        raise ValueError(f"a policy is one of {POLICIES}")
    bed = lawn(soil)
    full = calibrate(soil, climate, start)
    setpoint = soil_set * full
    rate = ROTARY_MM_H if policy in ("rotary", "all") else SPRAY_MM_H
    rain_24h = collections.deque([0.0] * int(24 * 60 / STEP_MIN), maxlen=int(24 * 60 / STEP_MIN))
    applied = rain = stressed_h = soggy_h = 0.0
    bypassed = runs = 0
    cycles: list = []                   # (start minute of day, end minute), today's runs
    when = start
    top = 0.05
    for _ in range(int(days * 24 * 60 / STEP_MIN)):
        minute = when.hour * 60 + when.minute
        if minute == WATER_HOUR * 60:
            cycles = _plan(policy, bed, climate, when, rate, setpoint, sum(rain_24h), baseline)
            runs += bool(cycles)
            bypassed += cycles is None
            cycles = cycles or []
        if policy == "on_demand" and cycles and minute in [int(s) for s, _ in cycles[1:]]:
            if bed.theta_at(SOIL_PROBE_M) >= full:   # the probe reads full: stop here
                cycles = [c for c in cycles if c[0] < minute]
        given = sum(_overlap(minute, minute + STEP_MIN, s, e) for s, e in cycles) * rate / 60.0
        w = climate.step(when)
        bed.step(w, irrigation_mm=given)
        applied += given
        rain += w.rain_mm
        rain_24h.append(w.rain_mm)
        if bed.stress >= 0.5:
            stressed_h += STEP_MIN / 60.0
        if bed.theta_at(top) >= bed._props[0].saturation - 0.02:
            soggy_h += STEP_MIN / 60.0
        when += ph.STEP
    return {"policy": policy, "soil": soil, "applied_mm": applied, "runoff_mm": bed.runoff_mm,
            "drained_mm": bed.drained_mm, "stressed_h": stressed_h, "soggy_h": soggy_h,
            "rain_mm": rain, "et_mm": bed.et_mm, "waterings": runs, "bypassed": bypassed,
            "full": full}


def _plan(policy, bed, climate, when, rate, setpoint, rain_24h, baseline):
    """Today's runs, as `[(start, end)]` minutes of the day; `[]` when none is scheduled;
    None when one was scheduled and a sensor bypassed it."""
    start = WATER_HOUR * 60.0
    if policy == "on_demand":
        if bed.theta_at(SOIL_PROBE_M) > setpoint:
            return []
        step = ON_DEMAND_RUN_MIN + SOAK_MIN
        return [(start + k * step, start + k * step + ON_DEMAND_RUN_MIN)
                for k in range(ON_DEMAND_MAX)]
    days = TWICE_DAYS if policy == "twice_weekly" else TIMER_DAYS
    if when.weekday() not in days:
        return []
    if policy in ("rain_sensor", "all") and rain_24h >= RAIN_SET_MM:
        return None
    if policy in ("soil_sensor", "all") and bed.theta_at(SOIL_PROBE_M) > setpoint:
        return None
    mm = RUN_MM
    if policy == "weather":
        mm *= _eto_scale(climate, (when - _dt.timedelta(days=1)).date(), baseline)
        if mm <= 0:
            return None
    minutes = mm / rate * 60.0
    if policy in ("cycle_soak", "all"):
        each = minutes / CYCLES
        return [(start + k * (each + SOAK_MIN), start + k * (each + SOAK_MIN) + each)
                for k in range(CYCLES)]
    return [(start, start + minutes)]


def summer_baseline(climate) -> float:
    import irrigation_drill as D
    return D.baselines(climate)["summer"]


def _one(job):
    path, year, policy, soil, soil_set = job
    climate = ph.RecordedClimate.from_csv(path, seed=1)
    return (year, run(policy, soil, climate, _dt.datetime(year, 6, 1, tzinfo=UTC),
                      baseline=summer_baseline(climate), soil_set=soil_set))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--weather", help="a recorded-weather CSV with whole summers")
    ap.add_argument("--summers", help="YEAR-YEAR, June 1 to August 31 each")
    ap.add_argument("--soil-set", type=float, default=SOIL_SET_SHARE,
                    help="the soil sensor's set point, a share of its calibrated reading")
    ap.add_argument("--workers", type=int, default=1,
                    help="processes to run summers in (each holds one summer's weather)")
    args = ap.parse_args(argv)
    if args.weather:
        a, _, b = (args.summers or "").partition("-")
        jobs = [(args.weather, y) for y in range(int(a), int(b or a) + 1)]
    else:
        jobs = [(os.path.join(HERE, "data", f"mcallister-{y}-summer.csv"), y) for y in (2012, 2013)]
    work = [(path, year, p, s, args.soil_set) for path, year in jobs for s in SOILS
            for p in POLICIES]
    if args.workers > 1:
        from multiprocessing import Pool
        with Pool(args.workers, maxtasksperchild=1) as pool:
            results = pool.map(_one, work)
    else:
        results = [_one(j) for j in work]
    years = sorted({y for y, _ in results})
    print(f"McAllister Farm's summers {years[0]}-{years[-1]} ({len(years)}), June to August; "
          f"a cool-season lawn, roots 15 cm; soil sensors set at {args.soil_set:.0%} of "
          f"their calibrated reading; mean per summer:")
    for soil in SOILS:
        print(f"\n{soil}:")
        print(f"  {'policy':13s} {'applied':>8s} {'runoff':>7s} {'drained':>8s} "
              f"{'dry h':>6s} {'soggy h':>8s} {'skipped':>8s}")
        for policy in POLICIES:
            rs = [r for _, r in results if r["soil"] == soil and r["policy"] == policy]
            m = {k: statistics.mean(r[k] for r in rs) for k in
                 ("applied_mm", "runoff_mm", "drained_mm", "stressed_h", "soggy_h", "bypassed")}
            worst = max(rs, key=lambda r: r["stressed_h"])
            print(f"  {policy:13s} {m['applied_mm']:6.0f} mm {m['runoff_mm']:5.0f} mm "
                  f"{m['drained_mm']:6.0f} mm {m['stressed_h']:6.1f} {m['soggy_h']:8.1f} "
                  f"{m['bypassed']:8.1f}"
                  + (f"   (worst {worst['stressed_h']:.0f} h)" if worst["stressed_h"] >= 1 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
