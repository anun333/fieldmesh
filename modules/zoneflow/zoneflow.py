#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Irrigation zone flow: a clogged head, a broken one — layer 2 (spec v0.1 §11).

A zone's flow is the sum of its heads' flows. A meter on the irrigation line gives each
run of each zone its flow: an OpenSprinkler station reports it as the zone closes, and
the MQTT bridge writes it to the log. This sets each run beside two references:

* **The zone's usual flow**, the median of its last runs. A run well below it is a
  clogged head or filter, or a valve not opening fully. A run well above it is a broken
  head, a lost nozzle or a leak. These are sudden.
* **What its heads should give**: the zone's inventory of heads against the makers'
  charts, scaled by √P to the pressure they run at. A zone whose usual flow has drifted
  below that is clogging slowly, as drip lines do. With too few runs yet to have a usual
  flow, the inventory stands in.

A shortfall is **sized in heads**: "about one 15-foot half-circle spray head's worth is
not flowing". The arithmetic and its limits are in docs/notes/water-meters.md:

* a meter's own error is about ±2%;
* pressure moves every head at once, as its square root;
* so the default tolerance, 10% of the usual flow, sees a clogged half head in a typical
  lawn zone (−14%), and not a quarter head (−7%).

OpenSprinkler's own flow alert fires only above a set point, so it never sees a clog.

Read-only and advisory: it never touches a valve. Each finding is a CEL rule judged
through layer 1 (`modules/rules`). A decision is written only when an alert is raised or
cleared, as the livestock water monitor writes them.

    monitor = Monitor(log)
    monitor.check(state, zones, at=now)
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import statistics
import sys
from dataclasses import dataclass
from uuid import UUID

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
import i18n  # noqa: E402
import rules as R  # noqa: E402
from model import Usable  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "zoneflow")

GALLON_L = 3.785411784
#: Units a zone's flow series may be in, to US gallons a minute.
TO_GPM = {"[gal_us]/min": 1.0, "L/min": 1.0 / GALLON_L, "m3/h": 1000.0 / 60.0 / GALLON_L,
          "m3/s": 60000.0 / GALLON_L}

#: Each head from its maker's chart: `(gpm, the psi it was measured at, kind, size)`. The
#: psi is None for a pressure-compensating emitter, whose flow does not change with
#: pressure. The kind and size name it in a message: a spray head by its radius in feet, a
#: rotor by its nozzle, an emitter by its gallons an hour.
HEADS = {}
# Rain Bird MPR fixed spray nozzles on 4-inch pop-ups, at 30 psi (MPR performance charts).
for _radius, _full, _half, _quarter in ((8, 1.05, 0.52, 0.26), (10, 1.58, 0.79, 0.39),
                                         (12, 2.60, 1.30, 0.65), (15, 3.70, 1.85, 0.92)):
    HEADS[f"rainbird-mpr-{_radius}F"] = (_full, 30.0, "spray-full", float(_radius))
    HEADS[f"rainbird-mpr-{_radius}H"] = (_half, 30.0, "spray-half", float(_radius))
    HEADS[f"rainbird-mpr-{_radius}Q"] = (_quarter, 30.0, "spray-quarter", float(_radius))
# Rain Bird 5000 / 5000 Plus Rain Curtain rotor nozzles, at 45 psi (5000 nozzle chart).
for _nozzle, _gpm in ((1.5, 1.54), (2.0, 2.07), (2.5, 2.51), (3.0, 3.09), (4.0, 4.01),
                      (5.0, 5.09), (6.0, 6.01), (8.0, 8.03)):
    HEADS[f"rainbird-5000-{_nozzle}"] = (_gpm, 45.0, "rotor", _nozzle)
# Rain Bird Xeri-Bug pressure-compensating drip emitters, 15 to 50 psi.
for _gph in (0.5, 1.0, 2.0):
    HEADS[f"xeribug-{_gph}"] = (_gph / 60.0, None, "emitter", _gph)
#: Each kind of head as a number, for a CEL condition to choose its message by.
KINDS = {"spray-full": 1.0, "spray-half": 2.0, "spray-quarter": 3.0, "rotor": 4.0,
         "emitter": 5.0}
#: Runs a zone's usual flow is the median of, and the fewest it is learned from.
LEARN_RUNS = 7
MIN_RUNS = 3
#: The share of the usual flow a run may stray by, without and with a gauge on the line.
#: Over 300 simulated seasons a gauge reading within 1% took the supply's swing out, and 6%
#: then caught every clogged quarter-circle head by its second run, with one false alert
#: in 12,000 runs; 5% gave 14 (`drill`).
TOLERANCE = 0.10
GAUGED_TOLERANCE = 0.06
#: A line pressure series' units, to psi.
TO_PSI = {"[psi]": 1.0, "kPa": 0.1450377377, "bar": 14.50377377}
#: The minutes before a run's flow reading its pressure is read over: OpenSprinkler reports
#: a run's flow as the zone closes, so the minutes before are the run.
RUN_PRESSURE_MIN = 10.0


@dataclass(frozen=True)
class Zone:
    """One irrigation zone: the land it waters (its label names it), the series of its
    runs' flows, its heads as `((head, count), ...)` from `HEADS`, the pressure they run
    at when known, and the share of the usual flow a run may stray by. `since` drops the
    runs before a change to the zone, such as heads added or replaced, so its usual flow
    is learned afresh."""

    feature: UUID
    flow: UUID
    heads: tuple = ()
    pressure_psi: float | None = None
    #: The share of the usual flow a run may stray by: 10% by default, 6% with a gauge on
    #: the line (`pressure`), which then sees a clogged quarter-circle head (`drill`).
    tolerance: float | None = None
    since: _dt.datetime | None = None
    #: Runs in a row out of tolerance, the same way, before a low or high flow is said.
    #: Two: one run out is a pressure dip as often as a fault (`drill`).
    confirm_runs: int = 2
    #: The line's gauge pressure, read during each run (`vocab.WATER_PRESSURE`). Each run's
    #: flow is then taken to one pressure, by √P, so a supply that wanders does not read
    #: as a clog or a break: `pressure_psi`, or the runs' median pressure. A narrower
    #: `tolerance` then holds (`drill`).
    pressure: UUID | None = None

    def __post_init__(self) -> None:
        if self.tolerance is None:
            object.__setattr__(self, "tolerance", GAUGED_TOLERANCE if self.pressure else TOLERANCE)
        for head, count in self.heads:
            if head not in HEADS:
                raise ValueError(f"unknown head {head!r}; known: {', '.join(HEADS)}")
            if count < 1:
                raise ValueError("a zone has at least one of each head it lists")
        if not 0 < self.tolerance < 0.5:
            raise ValueError("a tolerance is a share of the usual flow, between 0 and 0.5")
        if self.confirm_runs < 1:
            raise ValueError("an alert needs at least one run")


def head_gpm(head: str, pressure_psi: float | None = None) -> float:
    """One head's flow, gpm, at a pressure: the chart's, scaled by √P for a nozzle."""
    gpm, at = HEADS[head][:2]
    if at is None or pressure_psi is None:
        return gpm
    return gpm * math.sqrt(pressure_psi / at)


def expected_gpm(zone: Zone) -> float | None:
    """What the zone's heads should give together, gpm; None without an inventory."""
    if not zone.heads:
        return None
    return sum(count * head_gpm(head, zone.pressure_psi) for head, count in zone.heads)


def size_in_heads(zone: Zone, shortfall_gpm: float):
    """The whole number of one of the zone's head types whose flow best matches a
    shortfall, `(count, head)`, or None when no type comes within half a head of it."""
    best = None
    for head, count in zone.heads:
        q = head_gpm(head, zone.pressure_psi)
        k = round(shortfall_gpm / q)
        if not 1 <= k <= count:
            continue
        miss = abs(shortfall_gpm - k * q) / q
        if miss <= 0.5 and (best is None or miss < best[0]):
            best = (miss, k, head)
    return None if best is None else (best[1], best[2])


def judge_runs(flows_gpm: list, zone: Zone) -> dict:
    """The context for the latest of a zone's runs, oldest first, in gpm.

    **The usual flow is learned from normal runs only.** Each run in turn is set beside
    the median of the last `LEARN_RUNS` runs that were themselves within the tolerance.
    Until there are `MIN_RUNS` of those, the inventory stands in. A clog that lasts does
    not become the new usual: its alert stands until the flow comes back.

    **A slow drift does become the usual**, because each run is within tolerance of the
    last few. So the recent runs are also set beside the inventory, when there is one."""
    expected = expected_gpm(zone)
    ctx = {"has_run": bool(flows_gpm), "has_usual": False, "has_expected": expected is not None,
           "flow_gpm": 0.0, "usual_gpm": 0.0, "expected_gpm": round(expected or 0.0, 2),
           "percent_of_usual": 100.0, "percent_of_expected": 100.0, "learned": False,
           "sized": False, "heads": 0.0, "head_kind": 0.0, "head_size": 0.0,
           "tolerance_percent": round(zone.tolerance * 100, 1), "runs": float(len(flows_gpm)),
           "low_runs": 0.0, "high_runs": 0.0}
    if not flows_gpm:
        return ctx
    normal, usual, learned, low_runs, high_runs = [], expected, False, 0, 0
    for flow in flows_gpm:
        if len(normal) >= MIN_RUNS:
            usual, learned = statistics.median(normal[-LEARN_RUNS:]), True
        else:
            usual, learned = expected, False
        if usual is None or abs(flow / usual - 1.0) <= zone.tolerance:
            normal.append(flow)
            low_runs = high_runs = 0
        elif flow < usual:
            low_runs, high_runs = low_runs + 1, 0
        else:
            low_runs, high_runs = 0, high_runs + 1
    ctx.update({"low_runs": float(low_runs), "high_runs": float(high_runs)})
    flow = flows_gpm[-1]
    ctx.update({"flow_gpm": round(flow, 2), "learned": learned})
    if usual:
        ctx.update({"has_usual": True, "usual_gpm": round(usual, 2),
                    "percent_of_usual": round(100.0 * flow / usual, 1)})
        sized = size_in_heads(zone, usual - flow) if flow < usual else None
        if sized:
            _, _, kind, size = HEADS[sized[1]]
            ctx.update({"sized": True, "heads": float(sized[0]), "head_kind": KINDS[kind],
                        "head_size": size})
    if expected and len(normal) >= MIN_RUNS:
        recent = statistics.median(normal[-LEARN_RUNS:])
        ctx["percent_of_expected"] = round(100.0 * recent / expected, 1)
    return ctx


def rules_for(zone: Zone) -> list:
    p = {"low_percent": round(100.0 - zone.tolerance * 100.0, 1),
         "high_percent": round(100.0 + zone.tolerance * 100.0, 1),
         "confirm_runs": float(zone.confirm_runs)}
    params = {"flow": "flow_gpm", "usual": "usual_gpm", "expected": "expected_gpm",
              "percent": "percent_of_usual", "of_expected": "percent_of_expected",
              "heads": "heads", "size": "head_size"}
    sized = tuple((f"sized && head_kind == {n}", f"zoneflow.low_sized_{kind.replace('-', '_')}")
                  for kind, n in KINDS.items())
    rules = [
        R.Rule("zone-flow-low", "1", "has_usual && low_runs >= confirm_runs", p,
               alert_key="zoneflow.low", message_params=params, message_variants=sized),
        R.Rule("zone-flow-high", "1", "has_usual && high_runs >= confirm_runs", p,
               alert_key="zoneflow.high", message_params=params),
        R.Rule("zone-flow-drift", "1",
               "has_expected && learned && percent_of_expected < low_percent", p,
               alert_key="zoneflow.drift", message_params=params),
    ]
    units = {"flow": "[gal_us]/min", "usual": "[gal_us]/min", "expected": "[gal_us]/min"}
    return [R.Rule(r.id, r.version, r.condition, r.params, alert_key=r.alert_key,
                   message_params=r.message_params, message_variants=r.message_variants,
                   subject_param="zone", unit_params=units) for r in rules]


def _good(state, series: UUID, at: _dt.datetime, since=None):
    """A series' readings received by `at` that the checks had passed by then, oldest
    first, as `(measured_at, value)`."""
    rows = sorted((o for o in state.live_observations_of(series)
                   if o.received_at <= at and o.measured_at <= at
                   and (since is None or o.measured_at >= since)
                   and isinstance(o.result, (int, float)) and not isinstance(o.result, bool)),
                  key=lambda o: o.measured_at)
    return [(o.measured_at, float(o.result)) for o in rows
            if state.quality_as_of(o.id, at)[0] is Usable.GOOD]


def _runs(state, zone: Zone, at: _dt.datetime) -> list:
    ds = state.datastreams.get(zone.flow)
    if ds is None or ds.unit not in TO_GPM:
        return []
    return [(t, v * TO_GPM[ds.unit]) for t, v in _good(state, zone.flow, at, zone.since)]


def runs_of(state, zone: Zone, at: _dt.datetime) -> list:
    """The zone's runs' flows, gpm, oldest first: readings received by `at` that the
    health checks had passed by then, in the flow series' own unit."""
    return [g for _, g in _runs(state, zone, at)]


def run_pressures(state, zone: Zone, runs: list, at: _dt.datetime) -> list:
    """Each run's line pressure, psi: the median gauge reading over `RUN_PRESSURE_MIN`
    before its flow reading; None for a run with none, or without a gauge."""
    ds = state.datastreams.get(zone.pressure) if zone.pressure else None
    if ds is None or ds.unit not in TO_PSI:
        return [None] * len(runs)
    readings = [(t, v * TO_PSI[ds.unit]) for t, v in _good(state, zone.pressure, at)]
    out = []
    for t, _ in runs:
        lo = t - _dt.timedelta(minutes=RUN_PRESSURE_MIN)
        window = [p for u, p in readings if lo <= u <= t and p > 0]
        out.append(statistics.median(window) if window else None)
    return out


def zone_context(state, zone: Zone, at: _dt.datetime):
    """`(context, inputs)` for a zone at `at`. With a gauge, each run's flow is taken to
    one pressure before it is judged; the latest run is then said at its own pressure,
    and the usual and expected flows at that pressure too, so the meter's number and the
    message's agree."""
    runs = _runs(state, zone, at)
    flows = [g for _, g in runs]
    pressures = run_pressures(state, zone, runs, at)
    known = [p for p in pressures if p is not None]
    inputs = {"zone": str(zone.feature), "flow": str(zone.flow),
              "heads": [list(h) for h in zone.heads], "pressure_psi": zone.pressure_psi}
    if not known:
        return judge_runs(flows, zone), inputs
    p0 = zone.pressure_psi or statistics.median(known)
    adjusted = [g * math.sqrt(p0 / p) if p else g for g, p in zip(flows, pressures)]
    ctx = judge_runs(adjusted, zone)
    last = pressures[-1]
    if last:
        at_run = math.sqrt(last / p0)
        ctx.update({"flow_gpm": round(flows[-1], 2),
                    "usual_gpm": round(ctx["usual_gpm"] * at_run, 2),
                    "expected_gpm": round(ctx["expected_gpm"] * at_run, 2),
                    "run_pressure_psi": round(last, 1)})
    inputs.update({"pressure": str(zone.pressure), "reference_psi": round(p0, 1),
                   "runs_with_pressure": len(known)})
    return ctx, inputs


class Monitor:
    """Judges zones and writes a decision only where an alert changed: raised, or
    cleared. Which alerts stand is read back from the log when it starts."""

    def __init__(self, log) -> None:
        self.log = log
        self._standing: dict[tuple, object] = {}
        for event in log.events:
            self._learn(event)

    def _learn(self, event) -> None:
        p = event.payload
        if event.kind == R.DECISION and p.get("subject") and str(p.get("rule", "")).startswith("zone-flow-"):
            key = (p["rule"], p["subject"])
            if p.get("alert"):
                self._standing[key] = event
            else:
                self._standing.pop(key, None)

    def check(self, state, zones, at: _dt.datetime) -> list:
        """Judge every zone at `at`; return the decision events written."""
        written = []
        for zone in zones:
            context, inputs = zone_context(state, zone, at)
            subject = str(zone.feature)
            for rule in rules_for(zone):
                d = R.judge(rule, context, inputs, at)
                if d["alert"] == ((rule.id, subject) in self._standing):
                    continue
                d["subject"] = subject
                d["topic"] = f"{rule.id}/{subject}"
                event = self.log.append(R.DECISION, d)
                self._learn(event)
                written.append(event)
        return written

    def standing(self) -> list:
        return sorted(self._standing.values(), key=lambda e: (e.stamp, e.id.int))


def render(decision: dict, language: str = "en", state=None, units: str | None = None) -> str | None:
    """A decision's message in `language`, naming the zone by its label there."""
    return R.render(decision, language, state, units)


# ------------------------------------------------------------- simulation

def simulate(expected: float, runs: int, *, seed: int, meter_sd: float = 0.02,
             pressure_sd: float = 0.10, fault_at: int | None = None,
             fault_gpm: float = 0.0, drift_per_run: float = 0.0,
             gauge_sd: float | None = None) -> list:
    """A zone's runs' flows on a line whose pressure wanders and whose meter is not
    exact: `pressure_sd` is the supply pressure's spread as a share, which moves the flow
    by its square root, and `meter_sd` the meter's. From run `fault_at`, `fault_gpm` is
    added (negative for a clog); `drift_per_run` takes that share off each run after the
    first, as drip emitters silting up. With `gauge_sd`, each run's flow is taken back to
    the nominal pressure by a gauge that reads within that share, as `zone_context` does
    with a pressure series."""
    import random
    rng, out = random.Random(seed), []
    gauge = random.Random(seed + 1_000_003)
    for n in range(runs):
        pressure = max(0.5, 1.0 + rng.gauss(0.0, pressure_sd))
        flow = expected * math.sqrt(pressure) * (1.0 - drift_per_run * n)
        if fault_at is not None and n >= fault_at:
            flow += fault_gpm * math.sqrt(pressure)
        flow = max(0.0, flow * (1.0 + rng.gauss(0.0, meter_sd)))
        if gauge_sd is not None:
            flow /= math.sqrt(pressure * (1.0 + gauge.gauss(0.0, gauge_sd)))
        out.append(flow)
    return out


LAWN = (("rainbird-mpr-15H", 6), ("rainbird-mpr-15Q", 2))
ROTORS = (("rainbird-5000-3.0", 4),)
DRIP = (("xeribug-1.0", 100),)


def alerts(ctx: dict, zone: Zone) -> set:
    """What `rules_for` would raise on a context, in plain Python, for the drill: the
    same conditions as its CEL (tested to agree)."""
    out = set()
    if ctx["has_usual"] and ctx["low_runs"] >= zone.confirm_runs:
        out.add("low")
    if ctx["has_usual"] and ctx["high_runs"] >= zone.confirm_runs:
        out.add("high")
    if ctx["has_expected"] and ctx["learned"] and \
            ctx["percent_of_expected"] < 100.0 - zone.tolerance * 100.0:
        out.add("drift")
    return out


def _first(flows: list, zone: Zone, wanted: set, from_run: int) -> int | None:
    """Runs from `from_run` until any of `wanted` is raised; None if none is."""
    for n in range(from_run, len(flows)):
        if alerts(judge_runs(flows[:n + 1], zone), zone) & wanted:
            return n - from_run
    return None


def drill(seasons: int = 300, runs: int = 40, *, pressure_sd: float = 0.05,
          meter_sd: float = 0.02, confirm_runs: int = 2, gauge_sd: float | None = None,
          tolerance: float = TOLERANCE) -> dict:
    """The check on simulated seasons of runs (`simulate`): false alerts on healthy
    zones, and how many runs after it starts each fault is said. A lawn zone (`LAWN`,
    12.94 gpm), a rotor zone (`ROTORS`) and a drip zone (`DRIP`), at the default
    tolerance. The supply pressure wanders with a standard deviation of `pressure_sd`,
    so ±10% at two deviations, and the meter's error is `meter_sd`. With `gauge_sd`, a
    pressure gauge on the line takes each run back to one pressure (`simulate`), and the
    zones are judged at `tolerance`."""
    lawn, rotors, drip = (Zone(UUID(int=n), UUID(int=10 + n), heads=h, confirm_runs=confirm_runs,
                               tolerance=tolerance)
                          for n, h in ((1, LAWN), (2, ROTORS), (3, DRIP)))
    out = {"false_alert_runs": 0, "seasons_with_false": 0, "runs": seasons * runs,
           "half_head": [], "quarter_head": [], "rotor": [], "broken": [], "drip_drift": []}
    for seed in range(seasons):
        kw = dict(seed=seed, pressure_sd=pressure_sd, meter_sd=meter_sd, gauge_sd=gauge_sd)
        healthy = simulate(expected_gpm(lawn), runs, **kw)
        false = sum(bool(alerts(judge_runs(healthy[:n + 1], lawn), lawn)) for n in range(runs))
        out["false_alert_runs"] += false
        out["seasons_with_false"] += bool(false)
        for name, zone, fault in (("half_head", lawn, -head_gpm("rainbird-mpr-15H")),
                                  ("quarter_head", lawn, -head_gpm("rainbird-mpr-15Q")),
                                  ("rotor", rotors, -head_gpm("rainbird-5000-3.0"))):
            flows = simulate(expected_gpm(zone), runs, fault_at=20, fault_gpm=fault, **kw)
            out[name].append(_first(flows, zone, {"low", "drift"}, 20))
        flows = simulate(expected_gpm(lawn), runs, fault_at=20, fault_gpm=8.0, **kw)
        out["broken"].append(_first(flows, lawn, {"high"}, 20))
        flows = simulate(expected_gpm(drip), runs, drift_per_run=0.01, **kw)
        out["drip_drift"].append(_first(flows, drip, {"low", "drift"}, 0))
    return out


def main(argv=None) -> int:
    """The check as its own process (§8.3; Q11), over the host's socket."""
    import argparse
    import json
    import time
    import modhost as M

    ap = argparse.ArgumentParser(description="Irrigation zone flow check, as a module process")
    ap.add_argument("--socket", required=True)
    ap.add_argument("--config", required=True,
                    help="JSON: {\"zones\": [{\"feature\": id, \"flow\": id, "
                         "\"heads\": [[\"rainbird-mpr-15H\", 6], ...], \"pressure_psi\": 30, "
                         "\"pressure\": id or absent}]}")
    ap.add_argument("--at", help="judge this one moment (ISO 8601) and exit")
    ap.add_argument("--every", type=float, default=900.0, help="seconds between looks")
    ap.add_argument("--language", default="en")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as h:
        config = json.load(h)
    zones = [Zone(**{**z, "feature": UUID(z["feature"]), "flow": UUID(z["flow"]),
                     "pressure": UUID(z["pressure"]) if z.get("pressure") else None,
                     "heads": tuple(tuple(x) for x in z.get("heads", ())),
                     "since": (_dt.datetime.fromisoformat(z["since"]) if z.get("since") else None)})
             for z in config["zones"]]
    with M.ModuleClient(args.socket, M.token_from_environment()) as client:
        monitor = Monitor(client.log())
        while True:
            at = (_dt.datetime.fromisoformat(args.at) if args.at
                  else _dt.datetime.now(tz=_dt.timezone.utc))
            state = client.state(at)
            for event in monitor.check(state, zones, at):
                print(json.dumps({"rule": event.payload["rule"], "alert": event.payload["alert"],
                                  "message": render(event.payload, args.language, state)},
                                 ensure_ascii=False), flush=True)
            if args.at:
                return 0
            time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
