#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Scored fault drills (docs/VIRTUAL_FARM.md step 6, spec v0.1 §9.2).

§9.2: **scored detection, not asserted detection.** "It flags the obvious case" is not
a measurement. This seeds a known fault at a known time, runs the whole chain, and
scores what the health checks said against what was actually wrong — precision,
recall, the false-alarm rate on clean readings, and the latency between onset and the
first correct flag.

    python3 drill.py                 # every fault kind, scored
    python3 drill.py --fault drift --days 10
    python3 drill.py --link meshtastic

Ground truth comes from `Sensor.injected()`, which nothing in `sdk/checks.py` can
reach. That separation is the whole point: a detector scored against the fixture that
produced it is scored against itself.

**Some faults are not detectable, and the drill says so.** A constant bias is
invisible to every §4.2 check that looks at one series — the readings still move like
real soil, just offset. Reporting recall 0 for it is the honest result and the useful
one: it tells a farmer which failures the system cannot see, which is information they
can act on by installing a redundant probe. A drill that only ran catchable faults
would be a demo.

**Latency is the number a farmer feels.** A stuck probe caught eighteen hours after it
froze is caught, but a season of irrigation decisions was made on fiction in the
meantime. Recall without latency flatters a slow detector.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from dataclasses import dataclass, field

import faults as F
import harness
import link as lk
import node as nd
import physics as ph

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sdk"))
import gateway as G  # noqa: E402
import vocab as V  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
from ids import uuid7  # noqa: E402
from model import (Calibration, ClockQuality, Datastream,  # noqa: E402
                   DatastreamKind, Threshold)
from registry import NodeBinding, Registry  # noqa: E402

NODE = 0x4F2A17B3
SOIL = V.SOIL_WATER
START = _dt.datetime(2026, 7, 1, 0, 0, tzinfo=ph.UTC)

#: Thresholds for a soil series, chosen with the quantisation dwell in mind (§4.2):
#: a probe at three decimals repeats for about eight hours overnight, so an
#: eighteen-hour flatline limit is the floor that does not cry wolf.
SOIL_THRESHOLDS = {
    "min": 0.02, "max": 0.46,
    "flat_seconds": 18 * 3600, "flat_n": 4,
    "max_rate_per_s": 0.0004,
    "cross_tolerance": 0.04,
}


@dataclass
class DrillResult:
    """What one drill measured. Every number is against ground truth."""

    fault: str
    onset: _dt.datetime
    readings: int = 0
    faulty_readings: int = 0
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0
    first_catch: _dt.datetime | None = None
    flags_seen: set = field(default_factory=set)
    detectable: bool = True
    note: str = ""

    @property
    def precision(self) -> float:
        hits = self.true_positives + self.false_positives
        return self.true_positives / hits if hits else 0.0

    @property
    def recall(self) -> float:
        actual = self.true_positives + self.false_negatives
        return self.true_positives / actual if actual else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def false_alarm_rate(self) -> float:
        """False positives as a share of readings that were actually fine.

        The number that decides whether a farmer keeps trusting the flags.
        """
        clean = self.true_negatives + self.false_positives
        return self.false_positives / clean if clean else 0.0

    @property
    def caught(self) -> bool:
        return self.first_catch is not None

    @property
    def latency_s(self) -> float | None:
        if self.first_catch is None:
            return None
        return (self.first_catch - self.onset).total_seconds()

    def line(self) -> str:
        latency = (f"{self.latency_s / 3600:>6.1f}h" if self.caught else "  never")
        flags = ",".join(sorted(self.flags_seen)) or "-"
        return (f"{self.fault:<34}{self.recall * 100:>7.0f}%"
                f"{self.precision * 100:>8.0f}%"
                f"{self.false_alarm_rate * 100:>8.1f}%{latency:>9}  {flags}")


def _build(*, seed: int, redundant: bool, start: _dt.datetime, dr: int,
           link_profile):
    """A drill farm: one bed, optionally with a second probe in the same bed.

    The redundant probe is the research-plot feature from the completeness matrix,
    and it is the only reason §4.2's cross-check has anything to compare against.
    """
    world = ph.default_world(start=start, seed=seed)
    log = L.Log()
    state = P.State()
    site, thing, feature = uuid7(), uuid7(), uuid7()

    sensors, raws = [], []
    for index in range(2 if redundant else 1):
        sensor_id = uuid7()
        raw = Datastream(id=uuid7(), thing=thing, sensor=sensor_id,
                         observed_property=SOIL, feature=feature,
                         kind=DatastreamKind.RAW, unit="cm3/cm3",
                         expected_interval=900.0, max_latency=3600.0)
        derived = Datastream(id=uuid7(), thing=thing, sensor=sensor_id,
                             observed_property=SOIL, feature=feature,
                             kind=DatastreamKind.DERIVED, derived_from=raw.id,
                             unit="cm3/cm3", expected_interval=900.0,
                             max_latency=3600.0, thresholds=SOIL_THRESHOLDS)
        cal = Calibration(id=uuid7(), sensor=sensor_id, method="linear",
                          valid_from=_dt.datetime(2026, 1, 1, tzinfo=ph.UTC),
                          coefficients={"a": 0.001, "b": 0.0, "decimals": 3})
        th = Threshold(id=uuid7(), datastream=derived.id, values=SOIL_THRESHOLDS)
        for record in (raw, derived, cal, th):
            log.append_record(record)
            state.add(record)
        sensors.append(F.Sensor(lambda t: t.soil["bed3"], scale=1000.0,
                                name=f"probe{index + 1}"))
        raws.append(raw)

    registry = Registry()
    registry.register_node(NodeBinding(node=NODE, site=site,
                                       clock_quality=ClockQuality.RTC_UNSYNCED,
                                       uncertainty_s=12.0, firmware="0.3.1",
                                       driver="sim", driver_version="0.1"))
    channels = []
    for index, (sensor, raw) in enumerate(zip(sensors, raws), start=1):
        registry.bind_point(NODE, index, raw.id)
        channels.append(nd.Channel(index, 900.0, 3600.0, sensor,
                                   name=sensor.name))

    node = nd.Node(NODE, channels, dr=dr, ack_timeout_s=1800.0,
                   policy=nd.BufferPolicy(buffer_max=600))
    gateway = G.Gateway(registry, log, state)
    link = lk.Link(link_profile, seed=seed)
    return world, node, gateway, link, sensors, raws


def drill(fault: F.Fault | None, *, days: float = 6.0, seed: int = 1,
          redundant: bool = True, dr: int = 3,
          link_profile=None, detectable: bool = True,
          note: str = "") -> DrillResult:
    """Seed one fault on the first probe, run, and score against ground truth."""
    link_profile = link_profile if link_profile is not None else lk.WIRED
    world, node, gateway, link, sensors, raws = _build(
        seed=seed, redundant=redundant, start=START, dr=dr,
        link_profile=link_profile)

    onset = START + _dt.timedelta(days=days / 3.0)
    if fault is not None:
        fault.begins_at_s = onset.timestamp()
        sensors[0].inject(fault)

    harness.run(world=world, node=node, gateway=gateway, link=link, days=days)

    state = gateway.state
    derived = {ds.id for ds in state.datastreams.values()
               if ds.kind is DatastreamKind.DERIVED
               and ds.derived_from == raws[0].id}
    result = DrillResult(
        fault=(fault.describe().split(" from ")[0] if fault else "none (control)"),
        onset=onset, detectable=detectable, note=note)

    for obs in state.observations:
        if obs.datastream not in derived:
            continue
        result.readings += 1
        truly_faulty = bool(fault) and obs.measured_at >= onset
        assertion = P.live_assertion(state.assertions, obs.id)
        flagged = bool(assertion and assertion.flags)
        if flagged and assertion is not None:
            result.flags_seen |= {f.value for f in assertion.flags}
        if truly_faulty:
            result.faulty_readings += 1
            if flagged:
                result.true_positives += 1
                if result.first_catch is None or obs.measured_at < result.first_catch:
                    result.first_catch = obs.measured_at
            else:
                result.false_negatives += 1
        else:
            if flagged:
                result.false_positives += 1
            else:
                result.true_negatives += 1
    return result


#: The faults worth drilling, with an honest expectation for each. `needs_peer`
#: marks the ones no single-series check can see — measured, not assumed.
def scenarios():
    return [
        (None, False, "the control: nothing is wrong, so nothing may be flagged"),
        (F.OutOfRange(value=4.2), False,
         "a disconnected probe reading its rail — the positive control"),
        (F.Sticking(), False, "a frozen ADC or a probe in a bucket"),
        (F.Drifting(per_day=0.05), True,
         "the commonest real failure, and invisible to one probe: every reading is "
         "plausible and the series looks healthy"),
        (F.Noisy(sigma=0.03, seed=5), True,
         "a loose connection; intermittent, so recall is low even when caught"),
        (F.Biased(offset=0.08), True,
         "a probe at the wrong depth or miscalibrated. The readings still move like "
         "real soil, just offset, so nothing in one series can tell"),
        (F.Dead(), False,
         "produces absence, not a wrong value. §4.2 makes this datastream "
         "staleness, not a reading flag, so no flag is the correct answer."),
    ]


def _compare(args, profile) -> int:
    """One probe against two, which is the finding worth printing."""
    print(f"Detection with and without a redundant probe in the same bed\n"
          f"{args.days:g} days from {START:%Y-%m-%d}  ·  DR{args.dr}  ·  "
          f"link {profile.name}\n")
    header = (f"{'fault':<26}{'1 probe':>18}{'2 probes':>18}   what changes")
    print(header)
    print("-" * (len(header) + 20))
    rows = []
    for fault, needs_peer, note in scenarios():
        alone = drill(_fresh(fault), days=args.days, seed=args.seed, dr=args.dr,
                      redundant=False, link_profile=profile)
        paired = drill(_fresh(fault), days=args.days, seed=args.seed, dr=args.dr,
                       redundant=True, link_profile=profile)
        rows.append((alone, paired, needs_peer, note))
        change = ("unchanged" if abs(paired.recall - alone.recall) < 0.02
                  else f"{alone.recall * 100:.0f}% -> {paired.recall * 100:.0f}%")
        print(f"{alone.fault:<26}"
              f"{alone.recall * 100:>9.0f}% recall"
              f"{paired.recall * 100:>11.0f}% recall   {change}")

    blind = [a for (a, p, needs, _) in rows
             if needs and a.recall < 0.02 and p.recall > 0.1]
    print()
    if blind:
        names = ", ".join(r.fault for r in blind)
        print(f"A single probe on a feature cannot see: {names}.")
        print("Every reading is individually plausible and the series looks healthy,")
        print("so no check that looks at one series has anything to go on. Drift is")
        print("the commonest real failure of the three.")
    print()
    for alone, paired, needs, note in rows:
        marker = "! " if needs else "  "
        print(f"{marker}{alone.fault:<24}{note}")
    return 0


def _fresh(fault):
    """A fault instance carries state once applied, so each drill gets its own."""
    if fault is None:
        return None
    return type(fault)(**{k: v for k, v in vars(fault).items()
                          if not k.startswith("_") and k != "begins_at_s"})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=6.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--dr", type=int, default=3, choices=(0, 1, 2, 3, 4, 5))
    ap.add_argument("--link", default="wired", choices=sorted(lk.PRESETS))
    ap.add_argument("--no-redundant", action="store_true",
                    help="remove the second probe, so cross-check has nothing")
    ap.add_argument("--compare", action="store_true",
                    help="score with and without a redundant probe, side by side — "
                         "which is the result worth looking at")
    ap.add_argument("--fault", help="drill only the fault whose name starts with this")
    args = ap.parse_args()

    profile = lk.PRESETS[args.link]

    if args.compare:
        return _compare(args, profile)

    print(f"Fault drills  ·  {args.days:g} days from {START:%Y-%m-%d}  ·  "
          f"DR{args.dr}  ·  link {profile.name}  ·  "
          f"{'one probe' if args.no_redundant else 'two probes in one bed'}")
    print(f"onset at day {args.days / 3:.1f}; ground truth from Sensor.injected(), "
          f"which the checks cannot see\n")
    header = (f"{'fault':<34}{'recall':>8}{'precis':>8}"
              f"{'false alarm':>12}{'latency':>7}  flags")
    print(header)
    print("-" * (len(header) + 14))

    results = []
    for fault, needs_peer, note in scenarios():
        if args.fault and not (fault and fault.kind.startswith(args.fault)):
            if not (args.fault == "none" and fault is None):
                continue
        result = drill(fault, days=args.days, seed=args.seed, dr=args.dr,
                       redundant=not args.no_redundant, link_profile=profile,
                       detectable=not needs_peer or not args.no_redundant,
                       note=note)
        results.append(result)
        print(result.line())

    print()
    for result in results:
        marker = "  " if result.detectable else "! "
        print(f"{marker}{result.fault:<32}{result.note}")
    print()
    control = next((r for r in results if r.fault.startswith("none")), None)
    if control:
        print(f"control false-alarm rate: {control.false_alarm_rate * 100:.2f}% "
              f"over {control.readings} readings"
              f"{'  — clean' if control.false_positives == 0 else '  — CRYING WOLF'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
