#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Scored siting drill: does the depth check find the move nobody logged? (§4.1, §9.2)

Two farms. A **control** farm where nothing is disturbed, which is the only honest way
to measure false alarms. A **disturbed** farm where, on day 4, five things happen to
five probes:

| probe        | event                                   | expectation |
| ------------ | --------------------------------------- | ----------- |
| bed4_shallow | lifted 0.20 -> 0.05 m, **not logged**   | caught      |
| bed2_shallow | pushed 0.20 -> 0.36 m, **not logged**   | caught      |
| bed5_shallow | nudged 0.20 -> 0.27 m, **not logged**   | missed — below the 8 cm tolerance |
| bed3_deep    | moved to bed5, same depth, **not logged** | depth check blind; the lateral check catches it |
| bed6_shallow | moved to bed1 at 0.30 m, **logged**     | **not** flagged — the control |

Every soil probe is assessed at the start of every day from day 3, when the daily wave
has established itself to 40 cm. The unit scored is the **device-day**: a siting
judgement is about a probe over a window, not about one reading. Ground truth is the
disagreement between where the simulator has the probe and where its installation
record says it is, which the check cannot see.

    python3 siting_drill.py
    python3 siting_drill.py --days 14 --seed 3

The expected-miss rows are there on purpose. A drill that only ran faults the check can
catch would be a demonstration, not a measurement.

**The lateral numbers are optimistic, and by how much is unknown.** The simulator keeps
one moisture layer per bed, so a bed's shallow and deep probes respond to its irrigation
identically and the matches come out near 1.0. Real soil lags and damps the wetting
front with depth. `assess_lateral` was built for that — lag tolerance up to an hour, a
margin before calling anything — but these numbers do not test it. A season of real
probes, or a layered moisture model, would.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from dataclasses import dataclass, field

import harrow_bend as hb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "sdk"))
import siting as S  # noqa: E402

#: A probe is truly displaced if its physical depth differs from the record by more
#: than this. Below it, the move is inside the sensor's own siting uncertainty.
TRUTH_DEPTH_M = 0.05

SPIN_UP_DAYS = 3
DISTURB_ON_DAY = 4

EVENTS = [
    ("bed4_shallow", "lifted 0.20 -> 0.05 m, unlogged", "depth"),
    ("bed2_shallow", "pushed 0.20 -> 0.36 m, unlogged", "depth"),
    ("bed5_shallow", "nudged 0.20 -> 0.27 m, unlogged", "depth"),
    ("bed3_deep", "moved to bed5 at the same depth, unlogged", "lateral"),
    ("bed6_shallow", "moved to bed1 at 0.30 m, logged", "logged"),
]


@dataclass
class Tally:
    label: str
    assessed: int = 0
    flagged: int = 0
    indeterminate: int = 0
    first_flag_day: float | None = None
    implied: list = field(default_factory=list)
    #: The same device-days judged by the lateral (moisture) check.
    lateral_flagged: int = 0
    lateral_indeterminate: int = 0
    lateral_first_day: float | None = None

    def rate(self) -> float:
        return self.flagged / self.assessed if self.assessed else 0.0


def _soil_probes(farm):
    return sorted(n for n, s in farm.series.items()
                  if n.startswith("bed") and not n.endswith("_temp")
                  and s.siting is not None)


def _truly_displaced(farm, name: str, at) -> tuple[bool, str]:
    """Ground truth: the physics against the record. Unreachable by the check."""
    series = farm.series[name]
    record = farm.state.installation_of(series.device.id, at)
    if record is None:
        return False, "none"
    bed_of = {v["id"]: k for k, v in farm.features.items() if v.get("id")}
    depth_off = abs(series.siting.depth_m - (record.depth_m or 0.0))
    if depth_off > TRUTH_DEPTH_M:
        return True, "depth"
    if bed_of.get(record.feature) != series.siting.bed:
        return True, "lateral"
    return False, "none"


def _disturb(farm) -> None:
    hb.displace(farm, "bed4_shallow", depth_m=0.05)
    hb.displace(farm, "bed2_shallow", depth_m=0.36)
    hb.displace(farm, "bed5_shallow", depth_m=0.27)
    hb.displace(farm, "bed3_deep", bed="bed5")
    hb.relocate(farm, "bed6_shallow", to="bed1", at=farm.world.when, depth_m=0.30,
                by=None)


def run(*, days: float = 10.0, seed: int = 1, disturbed: bool = True) -> dict:
    """Run one farm and tally every device-day assessment by what was really true."""
    farm = hb.build(seed=seed)
    hb.season(farm, days=SPIN_UP_DAYS, events=False, seed=seed)
    tallies: dict[str, Tally] = {}
    clean = Tally("clean probes (including the logged move)")
    day = SPIN_UP_DAYS
    while day < days:
        if disturbed and day == DISTURB_ON_DAY:
            _disturb(farm)
        at = farm.world.when
        for name in _soil_probes(farm):
            finding = S.assess_siting(farm.state, farm.series[name].device.id, at)
            truly, kind = _truly_displaced(farm, name, at)
            if disturbed and day >= DISTURB_ON_DAY and name in {e[0] for e in EVENTS}:
                if day == DISTURB_ON_DAY:
                    # Assessed the instant after the disturbance, on a window that
                    # holds no reading taken since. Not catchable by any check, so
                    # not counted against this one — latency already says how long
                    # the evidence takes to arrive.
                    continue
                tally = tallies.setdefault(name, Tally(name))
            else:
                tally = clean
            tally.assessed += 1
            if finding.verdict == S.INDETERMINATE:
                tally.indeterminate += 1
            if finding.displaced:
                tally.flagged += 1
                if tally.first_flag_day is None and day >= DISTURB_ON_DAY:
                    tally.first_flag_day = day - DISTURB_ON_DAY
            if finding.implied_depth_m is not None and tally is not clean:
                tally.implied.append(round(finding.implied_depth_m, 3))
            lateral = S.assess_lateral(farm.state, farm.series[name].device.id, at)
            if lateral.verdict == S.INDETERMINATE:
                tally.lateral_indeterminate += 1
            if lateral.displaced:
                tally.lateral_flagged += 1
                if tally.lateral_first_day is None and day >= DISTURB_ON_DAY:
                    tally.lateral_first_day = day - DISTURB_ON_DAY
        hb._run_segment(farm, hb.SeasonReport(days=1.0), 1.0)
        day += 1
    return {"clean": clean, "events": tallies}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=10.0)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    control = run(days=args.days, seed=args.seed, disturbed=False)["clean"]
    disturbed = run(days=args.days, seed=args.seed, disturbed=True)

    print(f"siting drill, {args.days:g} days, seed {args.seed}; disturbed on day "
          f"{DISTURB_ON_DAY}, assessed daily from day {SPIN_UP_DAYS}\n")
    print(f"control farm   {control.assessed} device-days: depth check "
          f"{control.flagged} false alarms, lateral check "
          f"{control.lateral_flagged} false alarms")
    dclean = disturbed["clean"]
    print(f"disturbed farm {dclean.assessed} clean device-days: depth "
          f"{dclean.flagged}, lateral {dclean.lateral_flagged} false alarms "
          f"({dclean.lateral_indeterminate} lateral indeterminate)\n")
    print(f"  {'probe':<13} {'event':<42} {'depth':>7} {'lateral':>8}")
    for name, event, kind in EVENTS:
        tally = disturbed["events"].get(name)
        if tally is None:
            continue
        def cell(flagged, first):
            when = f"{first:g}d" if first is not None else "never"
            return f"{flagged}/{tally.assessed} {when}"
        print(f"  {name:<13} {event:<42} "
              f"{cell(tally.flagged, tally.first_flag_day):>9} "
              f"{cell(tally.lateral_flagged, tally.lateral_first_day):>10}")
    print("\n  Each check sees what the other cannot: depth leaves a thermal signature"
          "\n  and no irrigation one; a change of bed leaves an irrigation signature"
          "\n  and no thermal one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
