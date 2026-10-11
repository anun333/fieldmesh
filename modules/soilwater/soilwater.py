#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Soil-moisture advisory — layer 2 (spec v0.1 §11; open-questions Q12).

Each morning, for each bed: water today and how much, wait for the rain that is coming,
it will need water in a day or two, it is too wet, or it has enough — and when it cannot
say, why not. Read-only, so it ships without commands, and Q12's other reason for it: a
season of its advice, kept as decision events (§7.7), is the irrigation module's evidence
base before that module exists.

The arithmetic is FAO-56's root-zone water balance, read from the probes rather than
modelled:

* **total available water** `TAW = (field capacity − wilting point) × root depth`;
* **depletion** `Dr = (field capacity − θ) × root depth`, θ the root zone's water;
* water when `Dr ≥ p × TAW`, `p` the fraction a crop can lose before it is stressed
  (FAO-56 puts most vegetables between 0.3 and 0.5; the default is a third), back up to
  field capacity — `Dr` millimetres.

**The probes are found, not configured.** A bed's probes are the soil-moisture series
whose device was installed in that bed when it took the reading (§4.1), at the depth its
installation says. Each stands for the soil from halfway to the probe above it to
halfway to the one below, and only the part inside the root zone counts — so a probe
lifted out of one bed and pushed into another changes both beds' advice on the day it
moves, and a probe deeper than the roots counts for nothing.

**Quality decides what is read.** Only readings the health checks had passed by the time
of the advice count (`State.quality_as_of`), so a stuck or drifting probe does not water
a bed; a bed whose probes are all flagged gets "check the probes", not advice built on a
broken one. Rain coming is read from a forecast datastream in the log (Q26), so the
forecast a decision rested on is in the log beside it.

Every advice is a CEL rule judged through layer 1 (`modules/rules`), advisory, and one
decision event is written per bed per call: the morning's record, kept whether or not
it changes.

    advisor = Advisor(log)
    advisor.advise(state, beds, at=morning, forecast=rain_forecast_id)
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import sys
from dataclasses import dataclass, replace
from uuid import UUID

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
import i18n  # noqa: E402
import rules as R  # noqa: E402
import vocab as V  # noqa: E402
from model import SURFACES, DatastreamKind, Usable  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "soilwater")

HOUR = _dt.timedelta(hours=1)
#: How far back the drying rate looks for the last wetting.
DRYING_WINDOW_H = 36.0
#: The shortest stretch a drying rate is measured over.
DRYING_MIN_H = 6.0
NO_ESTIMATE = 1e6
#: What grows in a bed, in a word.
PLANTINGS = ("vegetables", "flowers", "shrubs", "turf", "trees", "mixed")
#: Two probes in one bed whose learned field capacities differ by this much are in two
#: soils: several times the spread of one probe's drain-downs (about 0.02), and about a
#: texture class apart (a sandy loam holds roughly 0.20, a loam 0.27).
LAYER_GAP = 0.08


@dataclass(frozen=True)
class Bed:
    """One bed the advisory looks after: its land id (the feature its probes are
    installed in), its soil's water limits as volume fractions, and its crop's root
    depth and depletion fraction. The limits come from a soil test or SSURGO
    (`tools/soil_survey.py` reads both from the survey for a point).

    A bed whose soil changes with depth can say so: `layers` are `(bottom_m,
    field_capacity, wilting_point)`, top down, from a soil test of each layer or the
    survey's horizons; below the last, and for a bed with none, the bed's own two
    values stand."""

    feature: UUID
    field_capacity: float
    wilting_point: float
    root_depth_mm: float = 300.0
    depletion_fraction: float = 1 / 3
    skip_rain_mm: float = 10.0
    wet_margin: float = 0.02
    soon_days: float = 2.0
    stale_after_h: float = 6.0
    #: The series of the valve that waters this bed, open or shut (`vocab.VALVE_OPEN`),
    #: when a controller reports it — an OpenSprinkler's station through the MQTT bridge.
    #: With it the watering check can tell a blocked line from a bed nobody watered.
    valve: UUID | None = None
    #: Learn the bed's field capacity from its own probes (`learned_capacity`), the
    #: configured value standing until there is enough to learn from.
    learn: bool = True
    #: What covers the soil (`model.SURFACES`: bare, organic or inorganic mulch, plastic,
    #: turf) and what grows in it (`PLANTINGS`). The bed's record, written into each
    #: decision, so a season's advice can be read against what the bed was: a mulched
    #: shrub bed dries slower than bare vegetables, and the probes see that, not this.
    surface: str | None = None
    planting: str | None = None
    layers: tuple = ()
    #: For a bed with no probe, advised from the farm's station (`weather_balance`): the
    #: crop's coefficient on reference ET (FAO-56's Kc; 1.0 a full canopy, 0.95 a
    #: cool-season lawn), and how fast its watering puts water down, mm an hour, so the
    #: valve's minutes become millimetres.
    crop_coefficient: float = 1.0
    application_mm_per_h: float | None = None

    def __post_init__(self) -> None:
        if not 0 < self.wilting_point < self.field_capacity < 1:
            raise ValueError("0 < wilting point < field capacity < 1, as volume fractions")
        if self.root_depth_mm <= 0:
            raise ValueError("a root zone has a depth")
        if not 0 < self.depletion_fraction < 1:
            raise ValueError("the depletion fraction is between 0 and 1 (FAO-56's p)")
        if self.surface is not None and self.surface not in SURFACES:
            raise ValueError(f"a bed's surface is one of {SURFACES}")
        if self.planting is not None and self.planting not in PLANTINGS:
            raise ValueError(f"a bed's planting is one of {PLANTINGS}")
        if self.crop_coefficient <= 0 or (self.application_mm_per_h is not None
                                          and self.application_mm_per_h <= 0):
            raise ValueError("a crop coefficient and an application rate are positive")
        bottoms = [layer[0] for layer in self.layers]
        if bottoms != sorted(set(bottoms)) or any(
                not (b > 0 and 0 < wp < fc < 1) for b, fc, wp in self.layers):
            raise ValueError("layers are (bottom_m, field capacity, wilting point), top down, "
                             "with 0 < wilting point < field capacity < 1")

    def limits_at(self, depth_m: float) -> tuple[float, float]:
        """The field capacity and wilting point of the soil at a depth."""
        for bottom, fc, wp in self.layers:
            if depth_m <= bottom:
                return fc, wp
        return self.field_capacity, self.wilting_point

    @property
    def taw_mm(self) -> float:
        return (self.field_capacity - self.wilting_point) * self.root_depth_mm

    @property
    def raw_mm(self) -> float:
        return self.depletion_fraction * self.taw_mm


#: The advice, most urgent first; the first that holds is the morning's decision.
def rules_for(bed: Bed) -> list:
    p = {"raw_mm": round(bed.raw_mm, 2), "skip_rain_mm": bed.skip_rain_mm,
         "stale_after_h": bed.stale_after_h, "soon_days": bed.soon_days}
    usable = "has_probe && has_reading && usable && hours_since_reading <= stale_after_h"
    weather = "!has_probe && by_weather"
    rules = [
        R.Rule("soil-weather-unseen", "1", f"{weather} && weather_missing_days >= 2", p,
               alert_key="soilwater.weather_unseen",
               message_params={"days": "weather_missing_days"}),
        R.Rule("soil-weather-rain-coming", "1",
               f"{weather} && depletion_mm >= raw_mm && rain_mm >= skip_rain_mm", p,
               alert_key="soilwater.weather_rain_coming",
               message_params={"used": "used_percent", "rain": "rain_mm"}),
        R.Rule("soil-weather-water-now", "1", f"{weather} && depletion_mm >= raw_mm", p,
               alert_key="soilwater.weather_water_now",
               message_params={"used": "used_percent", "mm": "refill_mm"},
               message_variants=(("!watering_recorded",
                                  "soilwater.weather_water_now_unrecorded"),)),
        R.Rule("soil-weather-enough", "1", weather, p, alert_key="soilwater.weather_enough",
               message_params={"left": "left_percent"}),
        R.Rule("soil-no-probe", "1", "!has_probe", p, alert_key="soilwater.no_probe",
               message_params={"depth": "root_depth_cm"}),
        R.Rule("soil-unseen", "1", "!has_reading || hours_since_reading > stale_after_h", p,
               alert_key="soilwater.unseen", message_params={"hours": "hours_since_reading"},
               message_variants=((f"hours_since_reading >= {NO_ESTIMATE!r}",
                                  "soilwater.never_seen"),)),
        R.Rule("soil-untrusted", "1", "!usable", p, alert_key="soilwater.untrusted",
               message_params={"flags": "flags"}),
        R.Rule("soil-too-wet", "1", f"{usable} && wetter_than_capacity", p,
               alert_key="soilwater.too_wet", message_params={}),
        R.Rule("soil-rain-coming", "1",
               f"{usable} && depletion_mm >= raw_mm && rain_mm >= skip_rain_mm", p,
               alert_key="soilwater.rain_coming",
               message_params={"used": "used_percent", "rain": "rain_mm"}),
        R.Rule("soil-water-now", "1", f"{usable} && depletion_mm >= raw_mm", p,
               alert_key="soilwater.water_now",
               message_params={"used": "used_percent", "mm": "refill_mm"}),
        R.Rule("soil-water-soon", "1", f"{usable} && days_to_water <= soon_days", p,
               alert_key="soilwater.water_soon", message_params={"days": "days_to_water"}),
        R.Rule("soil-enough", "1", usable, p, alert_key="soilwater.enough",
               message_params={"left": "left_percent"}),
    ]
    return [replace(r, subject_param="bed") for r in rules]


# ----------------------------------------------------------------- context

def probes_of(state, bed: Bed, at: _dt.datetime) -> list:
    """`(datastream, depth_m)` for each calibrated soil-moisture series whose device is
    installed in the bed at `at` (§4.1), shallowest first."""
    found = []
    for ds in state.datastreams.values():
        if ds.kind is not DatastreamKind.DERIVED or ds.observed_property != V.SOIL_WATER:
            continue
        inst = state.installation_of(ds.sensor, at)
        if inst is None or inst.feature != bed.feature or inst.depth_m is None:
            continue
        found.append((ds, inst.depth_m))
    return sorted(found, key=lambda p: (p[1], p[0].id.int))


def weights(depths_m: list, root_depth_m: float) -> list:
    """The share of the root zone each probe stands for: from halfway to the probe above
    (or the surface) to halfway to the one below (or the root zone's bottom)."""
    out = []
    for i, d in enumerate(depths_m):
        if d > root_depth_m:
            out.append(0.0)      # below the roots: it says what drains, not what they use
            continue
        top = 0.0 if i == 0 else (depths_m[i - 1] + d) / 2
        bottom = (d + depths_m[i + 1]) / 2 if i + 1 < len(depths_m) else root_depth_m
        out.append(max(0.0, min(bottom, root_depth_m) - min(top, root_depth_m)))
    return out


def _drying_mm_per_day(rows, at, root_depth_mm) -> float:
    """How fast the root zone is drying, from its last wetting to now."""
    since = at - DRYING_WINDOW_H * HOUR
    window = [(t, v) for t, v in rows if t >= since]
    if len(window) < 2:
        return 0.0
    peak_t, peak_v = max(window, key=lambda tv: (tv[1], tv[0]))
    last_t, last_v = window[-1]
    span_h = (last_t - peak_t) / HOUR
    if span_h < DRYING_MIN_H:
        return 0.0
    return max(0.0, (peak_v - last_v) * root_depth_mm / (span_h / 24.0))


# ------------------------------------------------------------ learned soil

#: How far back a probe's field capacity is learned from, and the fewest drain-downs it
#: is learned from: until then the bed's configured value stands.
LEARN_DAYS = 60.0
LEARN_MIN_DRAINS = 3
#: A wetting: the probe's reading, smoothed, rising by this much within four hours.
WETTING_RISE = 0.04
#: A drain-down is followed this long at most, and counts only if it runs this long
#: before the next wetting.
DRAIN_MAX_H = 72
DRAIN_MIN_H = 16
#: A drain-down says nothing about capacity unless the probe was this much wetter than
#: the level it drained back to: a watering that only refilled the soil part way does not
#: drain at all.
DRAIN_MIN_EXCESS = 0.02
#: The drainage time constants tried, hours.
DRAIN_TAUS_H = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 36.0)


def _smoothed(values: list) -> list:
    """A running median of three: one noisy reading is not a wetting."""
    out = []
    for i in range(len(values)):
        window = sorted(values[max(0, i - 1):i + 2])
        out.append(window[len(window) // 2])
    return out


def _solve3(m: list, v: list):
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for c in range(3):
        p = max(range(c, 3), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-12:
            return None
        a[c], a[p] = a[p], a[c]
        for r in range(3):
            if r != c:
                f = a[r][c] / a[c][c]
                for k in range(c, 4):
                    a[r][k] -= f * a[c][k]
    return [a[i][3] / a[i][i] for i in range(3)]


def drain_fit(points: list):
    """Fit one drain-down, `[(hours since its peak, reading)]`, as water above field
    capacity draining away while the crop dries the soil steadily:

        θ(t) = fc + a·exp(−t / τ) − r·t

    For each τ in `DRAIN_TAUS_H`, `fc`, `a` and `r` are a linear least-squares fit; a
    drain-down cannot gain water, so `a` and `r` are not negative; the τ that fits best
    wins. Returns `{"field_capacity", "excess", "drying_per_day", "tau_h"}` or None."""
    best = None
    for tau in DRAIN_TAUS_H:
        rows = [(1.0, math.exp(-t / tau), -t) for t, _ in points]
        m = [[sum(x[i] * x[j] for x in rows) for j in range(3)] for i in range(3)]
        b = [sum(x[i] * y for x, (_, y) in zip(rows, points)) for i in range(3)]
        solved = _solve3(m, b)
        if solved is None or solved[1] < 0 or solved[2] < 0:
            continue
        fc, a, r = solved
        sse = sum((y - fc - a * x[1] - r * x[2]) ** 2 for x, (_, y) in zip(rows, points))
        if best is None or sse < best[0]:
            best = (sse, fc, a, r, tau)
    if best is None:
        return None
    _, fc, a, r, tau = best
    return {"field_capacity": fc, "excess": a, "drying_per_day": r * 24.0, "tau_h": tau}


def drain_downs(readings: list) -> list:
    """Every drain-down in a probe's hourly readings, `[(time, θ)]` oldest first: from the
    peak of each wetting until the next wetting, or `DRAIN_MAX_H`, when that is at least
    `DRAIN_MIN_H` of readings with no gap over three hours. Each is `drain_fit`'s result
    with its `peak_at`, and `half_drain_h`, the hours the probe took to lose half of what
    the wetting added."""
    if len(readings) < DRAIN_MIN_H:
        return []
    times = [t for t, _ in readings]
    smooth = _smoothed([v for _, v in readings])

    def rise_at(i: int, floor: int) -> bool:
        lo = min(smooth[max(floor, i - 4):i], default=smooth[i])
        return smooth[i] - lo >= WETTING_RISE

    out, i = [], 1
    while i < len(readings):
        if not rise_at(i, 0):
            i += 1
            continue
        peak = i
        while peak + 1 < len(readings) and smooth[peak + 1] >= smooth[peak] - 0.005 \
                and times[peak + 1] - times[peak] <= 3 * HOUR:
            peak += 1
        end = peak + 1
        while end < len(readings) and (times[end] - times[peak]) / HOUR <= DRAIN_MAX_H \
                and times[end] - times[end - 1] <= 3 * HOUR and not rise_at(end, peak):
            end += 1
        span = times[end - 1] - times[peak]
        if span / HOUR >= DRAIN_MIN_H:
            points = [((times[k] - times[peak]) / HOUR, readings[k][1]) for k in range(peak, end)]
            fit = drain_fit(points)
            if fit is not None:
                before = min(smooth[max(0, i - 12):i + 1])
                half = before + (smooth[peak] - before) / 2.0
                fit["half_drain_h"] = next(((times[k] - times[peak]) / HOUR
                                            for k in range(peak, end) if smooth[k] <= half), None)
                fit["peak_at"] = times[peak]
                out.append(fit)
        i = max(end, i + 1)
    return out


def learned_capacity(readings: list):
    """A probe's field capacity, learned from its own drain-downs: the median of the
    levels it drained back to, from those where it had been clearly wetter
    (`DRAIN_MIN_EXCESS`), when there are `LEARN_MIN_DRAINS` of them; else None.
    `{"field_capacity", "drains", "half_drain_h"}`, the last the median hours to lose half
    a wetting, or None when none did within its drain-down."""
    import statistics
    kept = [d for d in drain_downs(readings) if d["excess"] >= DRAIN_MIN_EXCESS]
    if len(kept) < LEARN_MIN_DRAINS:
        return None
    halves = [d["half_drain_h"] for d in kept if d["half_drain_h"] is not None]
    return {"field_capacity": round(statistics.median(d["field_capacity"] for d in kept), 3),
            "drains": len(kept),
            "half_drain_h": statistics.median(halves) if halves else None}


#: How far back the weather balance runs. It starts full there unless a soaking since
#: (rain and recorded watering at least the root zone's available water) refilled it.
BALANCE_DAYS = 60


def weather_balance(state, bed: Bed, station, at: _dt.datetime, *,
                    days: int = BALANCE_DAYS, assumed: dict | None = None) -> dict:
    """The root zone's depletion from the farm's station alone, FAO-56's daily balance
    (chapter 8): each local day up to yesterday, the depletion falls by the day's rain and
    recorded watering, never below full, and rises by the crop's ET, `Ks · Kc · ETo`,
    never past the available water. `Ks` (eq. 84) slows the crop once the readily
    available water is gone.

    * **Rain is the station's gauge**, all of it taken as reaching the roots; on a
      mulched or sloping bed it is less.
    * **Watering is the valve's recorded minutes** times `Bed.application_mm_per_h`.
      Without both, the advisory's own advice to water is taken as followed (`assumed`,
      `{local day: mm}`), and the advice says so: a balance that never sees the watering
      it asked for asks again every morning, and on the backtest bed called for 1,027 mm
      in 2013 where 157 was enough.
    * **A day the station did not cover** takes the mean ET of the week before it, and
      is counted; two of the last three missing and the advisory says it cannot tell.

    Returns `depletion_mm`, `eto_mm` (yesterday's), `days_since_full`, `missing_recent`,
    `watering_recorded` and the FAO-56 stand-ins the station needed (`estimated`)."""
    import eto as E
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(station.timezone)
    today = at.astimezone(tz).date()
    first, last = today - _dt.timedelta(days=days), today - _dt.timedelta(days=1)
    summaries = E.summaries(state, station, first, last, at)
    recorded = bed.valve is not None and bed.application_mm_per_h is not None
    taw, raw = bed.taw_mm, bed.raw_mm
    dr, since_full, known, estimated, missing, eto_mm = 0.0, days, [], set(), [], 0.0
    day = first
    while day <= last:
        got = E.eto_of(station, day, summaries[day])
        if got is None:
            eto_mm, rain = (sum(known[-7:]) / len(known[-7:]) if known else 0.0), 0.0
            missing.append(day)
        else:
            eto_mm, rain, used = got
            rain = rain or 0.0
            known.append(eto_mm)
            estimated.update(used)
        water = rain
        if recorded:
            lo = _dt.datetime.combine(day, _dt.time(), tzinfo=tz).astimezone(_dt.timezone.utc)
            seen, minutes = valve_minutes(state, bed.valve, lo, lo + 24 * HOUR)
            water += minutes / 60.0 * bed.application_mm_per_h if seen else 0.0
        else:
            water += (assumed or {}).get(day, 0.0)
        dr = max(0.0, dr - water)
        since_full = 0 if dr == 0.0 and water > 0 else since_full + 1
        ks = 1.0 if dr <= raw else max(0.0, (taw - dr) / ((1.0 - bed.depletion_fraction) * taw))
        dr = min(taw, dr + ks * bed.crop_coefficient * eto_mm)
        day += _dt.timedelta(days=1)
    return {"depletion_mm": dr, "eto_mm": eto_mm, "days_since_full": since_full,
            "missing_recent": sum(1 for d in missing if d > last - _dt.timedelta(days=3)),
            "watering_recorded": recorded, "estimated": estimated}


def _capacity(state, bed: Bed, ds, depth_m: float, wilting: float, rows: list,
              at: _dt.datetime):
    """A probe's learned field capacity at `at`, from its readings of the last
    `LEARN_DAYS` that the health checks had passed by then, or None: not learning, not
    enough drain-downs yet, or a value its soil's wilting point says cannot be right."""
    if not bed.learn:
        return None
    since = at - _dt.timedelta(days=LEARN_DAYS)
    readings = []
    for o in rows:
        if o.measured_at >= since and state.quality_as_of(o.id, at)[0] is Usable.GOOD:
            readings.append((o.measured_at, float(o.result)))
    found = learned_capacity(readings)
    if found is None or found["field_capacity"] <= wilting + 0.03:
        return None
    return {**found, "datastream": ds.id, "depth_m": depth_m}


def bed_context(state, bed: Bed, at: _dt.datetime, *, forecast: UUID | None = None,
                station=None, assumed: dict | None = None):
    """What the advisory knew about a bed at `at`: `(context, inputs)`. A bed with no
    probe in its root zone is advised from the farm's `station` (`eto.Station`) when
    there is one (`weather_balance`)."""
    root_m = bed.root_depth_mm / 1000.0
    probes = probes_of(state, bed, at)
    ws = weights([d for _, d in probes], root_m)
    in_zone = [(ds, d, w) for (ds, d), w in zip(probes, ws) if w > 0]
    base = {"has_probe": bool(in_zone), "root_depth_cm": round(bed.root_depth_mm / 10.0),
            "has_reading": False, "usable": False, "flags": "",
            "hours_since_reading": NO_ESTIMATE, "theta": 0.0,
            "wetter_than_capacity": False, "depletion_mm": 0.0, "refill_mm": 0.0,
            "used_percent": 0.0, "left_percent": 0.0, "rain_mm": 0.0,
            "days_to_water": NO_ESTIMATE, "probes": len(in_zone),
            "field_capacity": bed.field_capacity, "wilting_point": bed.wilting_point,
            "learned_probes": 0, "layered": False, "layers_configured": bool(bed.layers),
            "by_weather": False, "weather_missing_days": 0, "watering_recorded": False}
    inputs = {"bed": str(bed.feature), "observations": [], "forecast": None}
    inputs.update({k: getattr(bed, k) for k in ("surface", "planting") if getattr(bed, k)})
    if not in_zone:
        if station is not None:
            balance = weather_balance(state, bed, station, at, assumed=assumed)
            taw = bed.taw_mm
            base.update({
                "by_weather": True, "weather_missing_days": balance["missing_recent"],
                "watering_recorded": balance["watering_recorded"],
                "depletion_mm": round(balance["depletion_mm"], 1),
                "refill_mm": round(balance["depletion_mm"], 1),
                "used_percent": round(100.0 * min(1.0, balance["depletion_mm"] / taw), 0),
                "left_percent": round(100.0 * max(0.0, 1.0 - balance["depletion_mm"] / taw), 0),
                "eto_mm": round(balance["eto_mm"], 2),
                "days_since_full": balance["days_since_full"]})
            if forecast is not None:
                ahead = state.forecast(forecast, at, at + 24 * HOUR)
                base["rain_mm"] = round(sum(o.result for o in ahead
                                            if isinstance(o.result, (int, float))), 1)
                inputs["forecast"] = str(forecast)
            inputs["station"] = {k: str(v) for k, v in (
                ("air_temperature", station.air_temperature),
                ("relative_humidity", station.relative_humidity),
                ("solar_radiation", station.solar_radiation),
                ("wind_speed", station.wind_speed),
                ("precipitation", station.precipitation)) if v is not None}
            inputs["estimated"] = sorted(balance["estimated"])
        return base, inputs

    latest, flagged, series, capacities, limits = [], set(), [], [], []
    for ds, depth, w in in_zone:
        inst = state.installation_of(ds.sensor, at)
        rows = sorted((o for o in state.live_observations_of(ds.id)
                       if o.received_at <= at and o.measured_at <= at
                       and o.measured_at >= inst.installed_at
                       and isinstance(o.result, (int, float)) and not isinstance(o.result, bool)),
                      key=lambda o: o.measured_at)
        if not rows:
            continue
        good = []
        for o in rows[-int(DRYING_WINDOW_H * 4) - 8:]:
            usable, flags = state.quality_as_of(o.id, at)
            if usable is Usable.GOOD:
                good.append(o)
            elif o is rows[-1]:
                flagged |= {f.value for f in flags} or {"questionable"}
        newest = rows[-1]
        latest.append(newest.measured_at)
        fresh = (at - newest.measured_at) / HOUR <= bed.stale_after_h
        if fresh and good and good[-1] is newest:
            series.append((w, good))
            limits.append(bed.limits_at(depth))
            capacities.append(_capacity(state, bed, ds, depth, limits[-1][1], rows, at))
    if not latest:
        return base, inputs
    base["has_reading"] = True
    base["hours_since_reading"] = round((at - max(latest)) / HOUR, 2)
    base["flags"] = ",".join(sorted(flagged))
    if not series:
        return base, inputs

    total = sum(w for w, _ in series)
    theta = sum(w * good[-1].result for w, good in series) / total
    # Each probe's slice of the root zone at its own soil's limits, the field capacity
    # learned where there is enough to learn from.
    capacity = sum(w * (c["field_capacity"] if c else fc)
                   for (w, _), c, (fc, _) in zip(series, capacities, limits)) / total
    wilting = sum(w * wp for (w, _), (_, wp) in zip(series, limits)) / total
    learned = [{"datastream": str(c["datastream"]), **{k: c[k] for k in
                ("depth_m", "field_capacity", "drains", "half_drain_h")}}
               for c in capacities if c]
    bed = replace(bed, field_capacity=capacity, wilting_point=wilting)
    if len(learned) >= 2:
        top, bottom = learned[0], learned[-1]
        base.update({"layered": abs(bottom["field_capacity"] - top["field_capacity"]) >= LAYER_GAP,
                     "shallow_cm": round(top["depth_m"] * 100.0),
                     "deep_cm": round(bottom["depth_m"] * 100.0),
                     "shallow_fc_percent": round(top["field_capacity"] * 100.0),
                     "deep_fc_percent": round(bottom["field_capacity"] * 100.0)})
    # The root zone's water over time, on the hours every counted probe has a reading.
    by_time = {}
    for w, good in series:
        for o in good:
            key = o.measured_at.replace(minute=0, second=0, microsecond=0)
            by_time.setdefault(key, {})[id(good)] = (w, o.result)
    history = sorted((t, sum(w * v for w, v in vals.values()) / sum(w for w, _ in vals.values()))
                     for t, vals in by_time.items() if len(vals) == len(series))
    depletion = max(0.0, (bed.field_capacity - theta) * bed.root_depth_mm)
    drying = _drying_mm_per_day(history, at, bed.root_depth_mm)
    to_go = bed.raw_mm - depletion
    days = to_go / drying if drying > 0.1 and to_go > 0 else (0.0 if to_go <= 0 else NO_ESTIMATE)
    rain = 0.0
    if forecast is not None:
        ahead = state.forecast(forecast, at, at + 24 * HOUR)
        rain = sum(o.result for o in ahead if isinstance(o.result, (int, float)))
        inputs["forecast"] = str(forecast)
    inputs["observations"] = [str(good[-1].id) for _, good in series]
    if learned:
        inputs["learned"] = learned
    base.update({
        "usable": True, "theta": round(theta, 3), "field_capacity": round(capacity, 3),
        "wilting_point": round(wilting, 3),
        "learned_probes": len(learned),
        "wetter_than_capacity": theta > bed.field_capacity + bed.wet_margin,
        "depletion_mm": round(depletion, 1), "refill_mm": round(depletion, 1),
        "used_percent": round(100.0 * min(1.0, depletion / bed.taw_mm), 0),
        "left_percent": round(100.0 * max(0.0, 1.0 - depletion / bed.taw_mm), 0),
        "rain_mm": round(rain, 1), "days_to_water": round(days, 1),
        "drying_mm_per_day": round(drying, 2)})
    return base, inputs


# ----------------------------------------------------------------- advisor

class Advisor:
    """Writes one decision per bed per call: the morning's advice, or why there is none."""

    def __init__(self, log) -> None:
        self.log = log

    def judge(self, state, bed: Bed, at: _dt.datetime, *, forecast: UUID | None = None,
              station=None) -> dict:
        """The decision for one bed, without writing it."""
        assumed = self._assumed(bed, station) if station is not None else None
        context, inputs = bed_context(state, bed, at, forecast=forecast, station=station,
                                      assumed=assumed)
        for rule in rules_for(replace(bed, field_capacity=context["field_capacity"],
                                      wilting_point=context["wilting_point"])):
            d = R.judge(rule, context, inputs, at)
            if d["alert"]:
                # One answer per bed per morning, whichever rule gave it (§7.7): the
                # morning's advice replaces yesterday's, and stands for a day.
                d["subject"] = str(bed.feature)
                d["topic"] = f"advice/{bed.feature}"
                d["valid_until"] = (at + _dt.timedelta(days=1)).isoformat()
                return d
        raise AssertionError("the last rule holds whenever none before it does")

    def _assumed(self, bed: Bed, station) -> dict:
        """`{local day: mm}`: this advisory's own advice to water the bed by the weather,
        as it wrote it, taken as followed where no valve records the watering."""
        from zoneinfo import ZoneInfo
        tz, out = ZoneInfo(station.timezone), {}
        for event in getattr(self.log, "events", ()):
            p = event.payload
            if (event.kind == R.DECISION and p.get("rule") == "soil-weather-water-now"
                    and p.get("subject") == str(bed.feature)):
                day = _dt.datetime.fromisoformat(p["evaluated_at"]).astimezone(tz).date()
                out[day] = p["context"]["refill_mm"]
        return out

    def advise(self, state, beds, at: _dt.datetime, *, forecast: UUID | None = None,
               station=None) -> list:
        """The morning's decision for each bed, and for a bed its probes show is
        layered, a note saying so (`layering`)."""
        out = []
        for bed in beds:
            decision = self.judge(state, bed, at, forecast=forecast, station=station)
            out.append(self.log.append(R.DECISION, decision))
            note = self.layering(decision, bed, at)
            if note is not None:
                out.append(self.log.append(R.DECISION, note))
        return out

    @staticmethod
    def layering(decision: dict, bed: Bed, at: _dt.datetime) -> dict | None:
        """When two of a bed's probes have learned field capacities `LAYER_GAP` or more
        apart and the bed was given one soil's values, a note that it is layered: one
        wilting point cannot describe two soils, and the advice can wait too long for
        the one that holds water the roots cannot take. None otherwise."""
        context = decision["context"]
        if not context.get("layered") or context.get("layers_configured"):
            return None
        names = ("layered", "layers_configured", "shallow_cm", "deep_cm",
                 "shallow_fc_percent", "deep_fc_percent")
        d = R.judge(layering_rule(), {k: context[k] for k in names}, decision["inputs"], at)
        d.update({"subject": str(bed.feature), "topic": f"layers/{bed.feature}",
                  "valid_until": (at + _dt.timedelta(days=1)).isoformat()})
        return d


def layering_rule() -> R.Rule:
    return R.Rule("soil-layered", "1", "layered && !layers_configured", {},
                  alert_key="soilwater.layered", subject_param="bed",
                  message_params={"shallow": "shallow_cm", "deep": "deep_cm",
                                  "shallow_fc": "shallow_fc_percent",
                                  "deep_fc": "deep_fc_percent"})


# ---------------------------------------------------------------- regimen

#: The watering check's defaults (Q10): the watering an hour after the 04:00 advice, a
#: drip line's rate, three hours for the water to reach the probes, and the share of the
#: expected rise that counts as arrived. On the recorded summer (`backtest`), across 51
#: waterings, every bed that was watered rose by at least 0.74 of what its watering
#: should add and no blocked one by more than 0.27; half is the middle of that gap.
WATERING_CHECK = {"water_after_min": 60.0, "mm_per_hour": 12.0, "soak_min": 180.0,
                  "share": 0.5}


def watering_check(params=None):
    """The regimen that checks a watering arrived: `regimens/watering_check.star`."""
    import regimen as G
    return G.load(os.path.join(HERE, "regimens", "watering_check.star"),
                  params={**WATERING_CHECK, **(params or {})})


def watering_check_context(decision: dict, bed: Bed) -> dict:
    """What the regimen plans from: the morning's advice for the bed."""
    return {"advice": decision["rule"], "refill_mm": decision["context"]["refill_mm"],
            "root_depth_mm": bed.root_depth_mm, "bed": str(bed.feature)}


def response_context(state, bed: Bed, since: _dt.datetime, at: _dt.datetime) -> dict:
    """How much the root zone's water rose between `since` and `at`, as a fraction and
    in percentage points, from the same depth-weighted reading the advice uses; and,
    when the bed's valve reports, how long it stood open (`valve_open_min`) and whether
    that is known (`valve_known`)."""
    before, _ = bed_context(state, bed, since)
    after, _ = bed_context(state, bed, at)
    ok = before["usable"] and after["usable"]
    rise = after["theta"] - before["theta"] if ok else 0.0
    known, minutes = valve_minutes(state, bed.valve, since, at) if bed.valve else (False, 0.0)
    return {"has_reading": ok, "rise": round(rise, 4), "rise_percent": round(rise * 100.0, 1),
            "valve_known": known, "valve_open_min": round(minutes, 1)}


def valve_minutes(state, valve: UUID, since: _dt.datetime, at: _dt.datetime) -> tuple[bool, float]:
    """How long a valve stood open between two times, from its open-and-shut series as
    received by `at`: `(known, minutes)`. Known needs its state at `since` — its last
    report before then — or a first report after it that opens it. A first report that
    shuts a valve never seen opening is a lost message, not a valve that stayed shut."""
    rows = sorted((o for o in state.live_observations_of(valve)
                   if o.received_at <= at and o.measured_at <= at and isinstance(o.result, bool)),
                  key=lambda o: o.measured_at)
    before = [o for o in rows if o.measured_at < since]
    inside = [o for o in rows if o.measured_at >= since]
    is_open = before[-1].result if before else None
    if is_open is None and inside and not inside[0].result:
        return False, 0.0
    if is_open is None and not inside:
        return False, 0.0
    minutes, opened = 0.0, since if is_open else None
    for o in inside:
        if o.result and opened is None:
            opened = o.measured_at
        elif not o.result and opened is not None:
            minutes += (o.measured_at - opened) / _dt.timedelta(minutes=1)
            opened = None
    if opened is not None:
        minutes += (at - opened) / _dt.timedelta(minutes=1)
    return True, minutes


def render(decision: dict, language: str = "en", state=None) -> str | None:
    """A decision's advice in `language`, naming the bed by its label there."""
    return R.render(decision, language, state)


# ---------------------------------------------------------------- backtest

def backtest(climate, start: _dt.datetime, days: float, *, seed: int = 1,
             probe_noise: float = 0.01, check=None, blocked=frozenset(),
             forgotten=frozenset(), valve: bool = False, soil=None, depths=(0.20,),
             configured=None, learn: bool = True, layers=(), probe_bias: float = 0.0) -> dict:
    """§11: the advisory on a recorded summer, watering when it says to and skipping when
    it says rain is coming, scored like `sim/irrigation_drill.py`'s policies — water
    applied, water drained past the roots, crop stress — so it can be set beside the
    drip timer most farms run. Hourly probe readings at 20 cm, the drill's forecasts in
    the log, the advice at 04:00 and the watering from 05:00.

    With `check`, a watering-check regimen (`watering_check()`) runs after each advice to
    water, and the days in `blocked` (counted from `start`) are waterings that never reach
    the bed, as through a blocked drip line: the person waters, the soil gets nothing.
    The days in `forgotten` are advice to water that nobody followed. With `valve`, the
    bed's valve reports opening and shutting, as an OpenSprinkler station does through the
    MQTT bridge: it runs on a blocked day and stays shut on a forgotten one. The result's
    `checks` says, per watering, whether the regimen said the water did not arrive, and in
    which words.

    `soil` is the virtual bed, the drill's (`irrigation_drill.bed`) by default; a
    `physics.LayeredBed` makes a bed of horizons, read by a probe at each of `depths`.
    `configured` is the field capacity and wilting point the bed is set up with, as
    `(fc, wp)`, the virtual bed's own by default: give it a soil survey's for the bed a
    survey does not describe, and `layers` each layer's (`Bed.layers`). `learn` lets the
    advisory learn the field capacity from the probes (`Bed.learn`). `probe_bias` is added
    to every reading, as an uncalibrated probe reads high or low. The result adds what ran off, the field capacity the last
    advice used, what each probe had learned by then, and whether it said the bed is
    layered."""
    import statistics
    import random

    sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sim"))
    import forecaster as FCS
    import irrigation_drill as D
    import physics as ph
    from ids import uuid7
    from log import Log
    from model import ClockQuality, Datastream, Installation, Observation

    state, fc, truth = D.forecasts(climate, start, days, FCS.Skill(), seed)
    b = soil if soil is not None else D.bed()
    world = ph.World(start=start, climate=climate, beds=[b])
    land, probes = uuid7(), []
    for depth in depths:
        sensor = uuid7()
        raw = Datastream(id=uuid7(), thing=uuid7(), sensor=sensor,
                         observed_property=V.SOIL_WATER, feature=land, kind=DatastreamKind.RAW,
                         unit="1", expected_interval=3600.0, max_latency=3600.0)
        probe = Datastream(id=uuid7(), thing=raw.thing, sensor=sensor,
                           observed_property=V.SOIL_WATER, feature=land,
                           kind=DatastreamKind.DERIVED, derived_from=raw.id, unit="cm3/cm3",
                           expected_interval=3600.0, max_latency=3600.0)
        for rec in (raw, probe, Installation(uuid7(), sensor, land, start - 24 * HOUR,
                                             depth_m=depth)):
            state.add(rec)
        probes.append((probe, depth))
    cal = uuid7()
    valve_ds = None
    if valve:
        valve_ds = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(),
                              observed_property=V.VALVE_OPEN, feature=land,
                              kind=DatastreamKind.RAW, unit=None)
        state.add(valve_ds)
        state.add(Observation(uuid7(), valve_ds.id, start - HOUR, 1.0, start - HOUR, False,
                              ClockQuality.NETWORK, node="opensprinkler", boot=1, seq=0))

    def report(when, is_open, seq=[1]):
        seq[0] += 1
        state.add(Observation(uuid7(), valve_ds.id, when, 1.0, when, is_open,
                              ClockQuality.NETWORK, node="opensprinkler", boot=1, seq=seq[0] & 0xFFFF))
    capacity, wilting = configured or (b.field_capacity, b.wilting_point)
    bed = Bed(land, capacity, wilting, root_depth_mm=b.depth_mm, skip_rain_mm=D.SKIP_MM,
              valve=valve_ds.id if valve_ds else None, learn=learn, layers=tuple(layers))
    advisor, noise = Advisor(Log()), random.Random(seed)
    applied, dose_now, stressed_h, stress, advice, last, last_at = 0.0, 0.0, 0.0, [], {}, None, None
    runner = None
    if check is not None:
        import regimen as G
        runner, checks = G.Runner(Log()), []

        def respond(subject, run):
            return response_context(state, bed, run.started_at, world.when)
    for n in range(int(days * 24 * 12)):
        when = world.when
        if when.minute == 0:
            for probe, depth in probes:
                truth = b.theta_at(depth) if hasattr(b, "theta_at") else b.theta
                state.add(Observation(uuid7(), probe.id, when, 60.0, when,
                                      round(truth + probe_bias + noise.gauss(0.0, probe_noise), 3),
                                      ClockQuality.GPS, node="!soil", boot=1, seq=n & 0xFFFF,
                                      calibration=cal))
        if when.hour == D.DECIDE_HOUR and when.minute == 0:
            d = advisor.judge(state, bed, when, forecast=fc.id)
            advice[d["rule"]] = advice.get(d["rule"], 0) + 1
            last, last_at = d, when
            want = d["context"]["refill_mm"] if d["rule"] == "soil-water-now" else 0.0
            dose_now = want / 12.0
            if runner is not None:
                runner.start(check, watering_check_context(d, bed), when, subject=bed.feature)
        day = (when - start).days
        if when.hour == D.WATER_HOUR and dose_now and day not in forgotten:
            if valve_ds is not None and when.minute == 0:
                report(when, True)
            if day not in blocked:
                world.irrigate(b.name, dose_now)
            applied += dose_now
        if valve_ds is not None and when.hour == D.WATER_HOUR + 1 and when.minute == 0 \
                and dose_now and day not in forgotten:
            report(when, False)
        if runner is not None and when.minute == 0:
            for e in runner.tick(when, respond):
                checks.append({"day": (_dt.datetime.fromisoformat(e.payload["due_at"]) - start).days,
                               "alert": e.payload["alert"],
                               "key": (e.payload["message"] or {}).get("key"),
                               "rise_percent": e.payload["context"].get("rise_percent"),
                               "expected_percent": round(e.payload["context"]["expected_percent"], 1)})
        if when.hour == D.WATER_HOUR + 1 and when.minute == 0:
            dose_now = 0.0
        tick = world.step()
        s = tick.soil_stress[b.name]
        stress.append(s)
        if s >= 0.5:
            stressed_h += 1.0 / 12.0
    return {"policy": "advisory", "applied_mm": applied, "drained_mm": b.drained_mm,
            "runoff_mm": b.runoff_mm, "field_capacity": last["context"]["field_capacity"],
            "learned": [{k: v for k, v in x.items() if k != "datastream"}
                        for x in last["inputs"].get("learned", [])],
            "layered": Advisor.layering(last, bed, last_at) is not None,
            "mean_stress": statistics.mean(stress), "stressed_h": stressed_h,
            "advice": advice, "checks": checks if runner is not None else None}


def weather_backtest(climate, start: _dt.datetime, days: float, *, seed: int = 1,
                     rate_mm_per_h: float = 12.0, record_valve: bool = True) -> dict:
    """The advisory for the backtest bed with **no probe**, from a station on the farm:
    hourly air temperature, humidity, sunshine and rain, as the virtual farm's recorded
    weather gives them (`backtest` for the rest). Sunshine is each recorded day's total
    spread over the hours in the clear sky's shape (`sun.py`); there is no wind sensor,
    so FAO-56's 2 m/s stands in. Watering runs at `rate_mm_per_h` from 05:00 for as long
    as the advice's millimetres take, and with `record_valve` the valve reports it.

    Scored as `backtest` is. The balance's reference ET is FAO-56 Penman–Monteith; the
    virtual farm's own water loss is Hargreaves' formula on the same sunshine, so the
    balance runs on a model of the bed that is not the bed, as on a real farm."""
    import statistics

    sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sim"))
    import eto as E
    import forecaster as FCS
    import irrigation_drill as D
    import physics as ph
    import sun as SUN
    from ids import uuid7
    from log import Log
    from model import ClockQuality, Datastream, Observation

    state, fc, truth = D.forecasts(climate, start, days, FCS.Skill(), seed)
    b = D.bed()
    world = ph.World(start=start, climate=climate, beds=[b])
    land = uuid7()

    def series(prop, unit):
        ds = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(), observed_property=prop,
                        feature=uuid7(), kind=DatastreamKind.RAW, unit=unit,
                        expected_interval=3600.0, max_latency=3600.0)
        state.add(ds)
        return ds
    air, rh = series(V.AIR_TEMPERATURE, "Cel"), series(V.RELATIVE_HUMIDITY, "%")
    sunshine, rain = series(V.SOLAR_RADIATION, "W/m2"), series(V.PRECIPITATION_DEPTH, "mm")
    valve = series(V.VALVE_OPEN, None)
    # The virtual farm's hours are local solar time, so its station's day is UTC's.
    station = E.Station(lat=D.LAT, elevation_m=D.ELEVATION_M, timezone="UTC",
                        air_temperature=air.id, relative_humidity=rh.id,
                        solar_radiation=sunshine.id, precipitation=rain.id)
    bed = Bed(land, b.field_capacity, b.wilting_point, root_depth_mm=b.depth_mm,
              skip_rain_mm=D.SKIP_MM, valve=valve.id if record_valve else None,
              application_mm_per_h=rate_mm_per_h if record_valve else None)
    seq = [0]

    def write(ds, when, value):
        seq[0] += 1
        state.add(Observation(uuid7(), ds.id, when, 60.0, when, value, ClockQuality.NETWORK,
                              node="station", boot=1, seq=seq[0] & 0xFFFF))

    def hourly_sun(day):
        """Each hour's mean W/m2 ending at hour h, the day's recorded total in the clear
        sky's shape."""
        total_mj = climate.days.get(day, {}).get("ALLSKY_SFC_SW_DWN", 0.0)
        ends = [_dt.datetime.combine(day, _dt.time(), tzinfo=_dt.timezone.utc)
                + _dt.timedelta(hours=h) for h in range(1, 25)]
        shape = [SUN.clear_sky_mean_w(D.LAT, 0.0, D.ELEVATION_M, e, 3600.0) for e in ends]
        scale = total_mj * 1e6 / (3600.0 * sum(shape)) if sum(shape) else 0.0
        return {e: w * scale for e, w in zip(ends, shape)}

    advisor = Advisor(Log())
    applied, stressed_h, stress, advice = 0.0, 0.0, [], {}
    rain_hour, sun_today, water_until = 0.0, {}, None
    for n in range(int(days * 24 * 12)):
        when = world.when
        if when.minute == 0:
            if when.hour == 0 or not sun_today:
                sun_today = hourly_sun(when.date())
                sun_today.update(hourly_sun(when.date() - _dt.timedelta(days=1)))
            if n:
                write(rain, when, round(rain_hour, 3))
                write(sunshine, when, round(sun_today.get(when, 0.0), 1))
            rain_hour = 0.0
        if when.hour == D.DECIDE_HOUR and when.minute == 0:
            d = advisor.advise(state, [bed], when, forecast=fc.id, station=station)[0].payload
            advice[d["rule"]] = advice.get(d["rule"], 0) + 1
            if d["rule"] == "soil-weather-water-now":
                begin = when + HOUR
                water_until = begin + _dt.timedelta(hours=d["context"]["refill_mm"] / rate_mm_per_h)
                if record_valve:
                    write(valve, begin, True)
                    write(valve, water_until, False)
        if water_until is not None and when.hour >= D.WATER_HOUR:
            step_end = when + ph.STEP
            minutes = max(0.0, (min(step_end, water_until) - when) / _dt.timedelta(minutes=1))
            if minutes > 0:
                mm = rate_mm_per_h * minutes / 60.0
                world.irrigate(b.name, mm)
                applied += mm
            if step_end >= water_until:
                water_until = None
        tick = world.step()
        if when.minute == 0:
            write(air, when, tick.weather.air_temp_c)
            write(rh, when, tick.weather.relative_humidity)
        rain_hour += tick.weather.rain_mm
        s = tick.soil_stress[b.name]
        stress.append(s)
        if s >= 0.5:
            stressed_h += 1.0 / 12.0
    return {"policy": "weather", "applied_mm": applied, "drained_mm": b.drained_mm,
            "mean_stress": statistics.mean(stress), "stressed_h": stressed_h,
            "advice": advice}


# ------------------------------------------------------------------ process

def main(argv=None) -> int:
    """The advisory as its own process (§8.3; Q11): over the host's socket, holding only
    the token its grant gave it — a systemd credential, or `FIELDMESH_MODULE_TOKEN`."""
    import argparse
    import json
    import modhost as M

    ap = argparse.ArgumentParser(description="Soil-moisture advisory, as a module process")
    ap.add_argument("--socket", required=True)
    ap.add_argument("--config", required=True,
                    help="JSON: {\"beds\": [{\"feature\": id, \"field_capacity\": 0.3, "
                         "\"wilting_point\": 0.12, ...}], \"forecast\": id or null, "
                         "\"station\": {\"lat\": 35.1, \"elevation_m\": 243, "
                         "\"timezone\": \"America/Chicago\", \"air_temperature\": id, ...} "
                         "or null}")
    ap.add_argument("--at", help="advise for this moment (ISO 8601); default now")
    ap.add_argument("--language", default="en")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as h:
        config = json.load(h)
    beds = [Bed(**{**b, "feature": UUID(b["feature"]),
                   "layers": tuple(tuple(x) for x in b.get("layers", ()))})
            for b in config["beds"]]
    forecast = UUID(config["forecast"]) if config.get("forecast") else None
    station = None
    if config.get("station"):
        import eto as E
        spec = dict(config["station"])
        for key in ("air_temperature", "relative_humidity", "solar_radiation",
                    "wind_speed", "precipitation"):
            if spec.get(key):
                spec[key] = UUID(spec[key])
        station = E.Station(**spec)
    at = (_dt.datetime.fromisoformat(args.at) if args.at
          else _dt.datetime.now(tz=_dt.timezone.utc))
    with M.ModuleClient(args.socket, M.token_from_environment()) as client:
        state = client.state(at)
        for event in Advisor(client.log()).advise(state, beds, at, forecast=forecast,
                                                  station=station):
            print(json.dumps({"rule": event.payload["rule"],
                              "message": render(event.payload, args.language, state)},
                             ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
