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
import os
import sys
from dataclasses import dataclass
from uuid import UUID

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
import i18n  # noqa: E402
import rules as R  # noqa: E402
import vocab as V  # noqa: E402
from model import DatastreamKind, Usable  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "soilwater")

HOUR = _dt.timedelta(hours=1)
#: How far back the drying rate looks for the last wetting.
DRYING_WINDOW_H = 36.0
#: The shortest stretch a drying rate is measured over.
DRYING_MIN_H = 6.0
NO_ESTIMATE = 1e6


@dataclass(frozen=True)
class Bed:
    """One bed the advisory looks after: its land id (the feature its probes are
    installed in), its soil's water limits as volume fractions, and its crop's root
    depth and depletion fraction. The limits come from a soil test or SSURGO
    (`tools/soil_survey.py` reads both from the survey for a point)."""

    feature: UUID
    field_capacity: float
    wilting_point: float
    root_depth_mm: float = 300.0
    depletion_fraction: float = 1 / 3
    skip_rain_mm: float = 10.0
    wet_margin: float = 0.02
    soon_days: float = 2.0
    stale_after_h: float = 6.0

    def __post_init__(self) -> None:
        if not 0 < self.wilting_point < self.field_capacity < 1:
            raise ValueError("0 < wilting point < field capacity < 1, as volume fractions")
        if self.root_depth_mm <= 0:
            raise ValueError("a root zone has a depth")
        if not 0 < self.depletion_fraction < 1:
            raise ValueError("the depletion fraction is between 0 and 1 (FAO-56's p)")

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
    return [
        R.Rule("soil-no-probe", "1", "!has_probe", p, alert_key="soilwater.no_probe",
               message_params={"depth": "root_depth_cm"}),
        R.Rule("soil-unseen", "1", "!has_reading || hours_since_reading > stale_after_h", p,
               alert_key="soilwater.unseen", message_params={"hours": "hours_since_reading"}),
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


def bed_context(state, bed: Bed, at: _dt.datetime, *, forecast: UUID | None = None):
    """What the advisory knew about a bed at `at`: `(context, inputs)`."""
    root_m = bed.root_depth_mm / 1000.0
    probes = probes_of(state, bed, at)
    ws = weights([d for _, d in probes], root_m)
    in_zone = [(ds, d, w) for (ds, d), w in zip(probes, ws) if w > 0]
    base = {"has_probe": bool(in_zone), "root_depth_cm": round(bed.root_depth_mm / 10.0),
            "has_reading": False, "usable": False, "flags": "",
            "hours_since_reading": NO_ESTIMATE, "theta": 0.0,
            "wetter_than_capacity": False, "depletion_mm": 0.0, "refill_mm": 0.0,
            "used_percent": 0.0, "left_percent": 0.0, "rain_mm": 0.0,
            "days_to_water": NO_ESTIMATE, "probes": len(in_zone)}
    inputs = {"bed": str(bed.feature), "observations": [], "forecast": None}
    if not in_zone:
        return base, inputs

    latest, flagged, series = [], set(), []
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
    if not latest:
        return base, inputs
    base["has_reading"] = True
    base["hours_since_reading"] = round((at - max(latest)) / HOUR, 2)
    base["flags"] = ",".join(sorted(flagged))
    if not series:
        return base, inputs

    total = sum(w for w, _ in series)
    theta = sum(w * good[-1].result for w, good in series) / total
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
    base.update({
        "usable": True, "theta": round(theta, 3),
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

    def judge(self, state, bed: Bed, at: _dt.datetime, *, forecast: UUID | None = None) -> dict:
        """The decision for one bed, without writing it."""
        context, inputs = bed_context(state, bed, at, forecast=forecast)
        for rule in rules_for(bed):
            d = R.judge(rule, context, inputs, at)
            if d["alert"]:
                d["subject"] = str(bed.feature)
                return d
        raise AssertionError("the last rule holds whenever none before it does")

    def advise(self, state, beds, at: _dt.datetime, *, forecast: UUID | None = None) -> list:
        return [self.log.append(R.DECISION, self.judge(state, bed, at, forecast=forecast))
                for bed in beds]


def render(decision: dict, language: str = "en", state=None) -> str | None:
    """A decision's advice in `language`, naming the bed by its label there."""
    m = decision.get("message")
    if not m:
        return None
    name = None
    if state is not None and decision.get("subject"):
        label = state.label_for(UUID(decision["subject"]), language)
        name = label.name if label is not None else None
    params = {**m["params"], "bed": name or decision.get("subject", "?")}
    key = m["key"]
    if key == "soilwater.unseen" and params.get("hours", 0) >= NO_ESTIMATE:
        key = "soilwater.never_seen"
    return str(i18n.Translator(language).text(key, **params))


# ---------------------------------------------------------------- backtest

def backtest(climate, start: _dt.datetime, days: float, *, seed: int = 1,
             probe_noise: float = 0.01) -> dict:
    """§11: the advisory on a recorded summer, watering when it says to and skipping when
    it says rain is coming, scored like `sim/irrigation_drill.py`'s policies — water
    applied, water drained past the roots, crop stress — so it can be set beside the
    drip timer most farms run. Hourly probe readings at 20 cm, the drill's forecasts in
    the log, the advice at 04:00 and the watering from 05:00."""
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
    b = D.bed()
    world = ph.World(start=start, climate=climate, beds=[b])
    land, sensor = uuid7(), uuid7()
    raw = Datastream(id=uuid7(), thing=uuid7(), sensor=sensor, observed_property=V.SOIL_WATER,
                     feature=land, kind=DatastreamKind.RAW, unit="1",
                     expected_interval=3600.0, max_latency=3600.0)
    probe = Datastream(id=uuid7(), thing=raw.thing, sensor=sensor,
                       observed_property=V.SOIL_WATER, feature=land,
                       kind=DatastreamKind.DERIVED, derived_from=raw.id, unit="cm3/cm3",
                       expected_interval=3600.0, max_latency=3600.0)
    cal = uuid7()
    for rec in (raw, probe, Installation(uuid7(), sensor, land, start - 24 * HOUR, depth_m=0.20)):
        state.add(rec)
    bed = Bed(land, b.field_capacity, b.wilting_point, root_depth_mm=b.depth_mm,
              skip_rain_mm=D.SKIP_MM)
    advisor, noise = Advisor(Log()), random.Random(seed)
    applied, dose_now, stressed_h, stress, advice = 0.0, 0.0, 0.0, [], {}
    for n in range(int(days * 24 * 12)):
        when = world.when
        if when.minute == 0:
            state.add(Observation(uuid7(), probe.id, when, 60.0, when,
                                  round(b.theta + noise.gauss(0.0, probe_noise), 3),
                                  ClockQuality.GPS, node="!soil", boot=1, seq=n & 0xFFFF,
                                  calibration=cal))
        if when.hour == D.DECIDE_HOUR and when.minute == 0:
            d = advisor.judge(state, bed, when, forecast=fc.id)
            advice[d["rule"]] = advice.get(d["rule"], 0) + 1
            want = d["context"]["refill_mm"] if d["rule"] == "soil-water-now" else 0.0
            dose_now = want / 12.0
        if when.hour == D.WATER_HOUR and dose_now:
            world.irrigate("field", dose_now)
            applied += dose_now
        if when.hour == D.WATER_HOUR + 1 and when.minute == 0:
            dose_now = 0.0
        tick = world.step()
        s = tick.soil_stress["field"]
        stress.append(s)
        if s >= 0.5:
            stressed_h += 1.0 / 12.0
    return {"policy": "advisory", "applied_mm": applied, "drained_mm": b.drained_mm,
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
                         "\"wilting_point\": 0.12, ...}], \"forecast\": id or null}")
    ap.add_argument("--at", help="advise for this moment (ISO 8601); default now")
    ap.add_argument("--language", default="en")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as h:
        config = json.load(h)
    beds = [Bed(**{**b, "feature": UUID(b["feature"])}) for b in config["beds"]]
    forecast = UUID(config["forecast"]) if config.get("forecast") else None
    at = (_dt.datetime.fromisoformat(args.at) if args.at
          else _dt.datetime.now(tz=_dt.timezone.utc))
    with M.ModuleClient(args.socket, M.token_from_environment()) as client:
        state = client.state(at)
        for event in Advisor(client.log()).advise(state, beds, at, forecast=forecast):
            print(json.dumps({"rule": event.payload["rule"],
                              "message": render(event.payload, args.language, state)},
                             ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
