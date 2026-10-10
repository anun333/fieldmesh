#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""See it run: a log, derived state, and a SensorThings view. No hardware, no site data.

    python3 demo.py            # the whole chain
    python3 demo.py --json     # just the served Observations collection

Three things worth watching for, each a clause the v0 draft got wrong:

  * the log holds five observations and the service serves four — the
    recalibrated row supersedes its predecessor, so no client sees two
    observations at one phenomenonTime
  * a backfilled reading gets the calibration that was in force when it was
    taken, not the one current at ingest
  * a clockless node's reading carries an honest uncertainty, and `--interval`
    shows it as a phenomenonTime window
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json

import fixtures as fx
import log as L
import project as P
import sensorthings as st
from ids import uuid7
from model import ClockQuality, QualityFlag

UTC = _dt.timezone.utc


def build():
    """A bed with a soil-moisture probe, one season, with the awkward cases in it."""
    lg = L.Log()
    raw = fx.raw_datastream(expected_interval=3600.0)
    derived = fx.derived_datastream(raw)
    lg.append_record(raw)
    lg.append_record(derived)

    spring = fx.calibration(raw.sensor, a=1.00,
                            valid_from=_dt.datetime(2026, 3, 1, tzinfo=UTC),
                            valid_to=_dt.datetime(2026, 6, 1, tzinfo=UTC))
    summer = fx.calibration(raw.sensor, a=1.07,
                            valid_from=_dt.datetime(2026, 6, 1, tzinfo=UTC))
    lg.append_record(spring)
    lg.append_record(summer)

    thresholds = fx.threshold(derived, flat_n=6, max=0.55)
    lg.append_record(thresholds)

    # An ordinary reading from a GPS-synced node.
    good = fx.observation(derived, result=0.31, calibration=summer.id,
                          measured_at=fx.at(0), boot=4, seq=10)
    lg.append_record(good)

    # A reading taken in May that only arrived in June, after a buffer drain.
    # §3.2: it must get the SPRING calibration, by measured_at.
    backfilled_at = _dt.datetime(2026, 5, 30, 9, 0, tzinfo=UTC)
    backfilled = fx.observation(derived, result=0.27,
                                calibration=spring.id,
                                measured_at=backfilled_at,
                                received_at=fx.at(0), boot=4, seq=9)
    lg.append_record(backfilled)

    # A clockless node: legal, but it has to say how little it knows.
    vague = fx.observation(derived, result=0.29, calibration=summer.id,
                           measured_at=fx.at(60), uncertainty=1800,
                           clock_quality=ClockQuality.NONE, boot=4, seq=11)
    lg.append_record(vague)

    # A flatlined probe, caught by a health check under a named threshold.
    stuck = fx.observation(derived, result=0.31, calibration=summer.id,
                           measured_at=fx.at(120), boot=4, seq=12)
    lg.append_record(stuck)
    lg.append_record(fx.assertion(stuck.id, flags={QualityFlag.STUCK},
                                  check="flatline", check_version="1",
                                  threshold_version=thresholds.id,
                                  asserted_at=fx.at(121)))

    # Recalibration: the season is re-derived. Appends, supersedes, never rewrites.
    lg.append_record(fx.observation(derived, result=0.33, calibration=uuid7(),
                                    measured_at=fx.at(0), boot=4, seq=10,
                                    supersedes=good.id))
    return lg, raw, derived, spring, summer, backfilled


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true",
                    help="print only the served Observations collection")
    ap.add_argument("--interval", action="store_true",
                    help="emit phenomenonTime as the uncertainty window (§2)")
    ap.add_argument("--v2", action="store_true",
                    help="use the unpublished 2.0 draft dialect")
    args = ap.parse_args()

    lg, raw, derived, spring, summer, backfilled = build()
    state = P.state_from_log(lg)
    dialect = st.SensorThings20Draft if args.v2 else st.SensorThings11
    svc = st.Service(state, "https://harrow-bend.example", dialect=dialect,
                     interval_times=args.interval,
                     labels={raw.thing: {"name": "north bed"},
                             raw.feature: {"name": "north bed, 0-15cm"}})

    served = svc.observations(derived.id)
    if args.json:
        print(json.dumps(served, indent=2))
        return 0

    print(f"log                {len(lg)} events, append-only, "
          f"{len(list(lg.records()))} records")
    print(f"observations       {len(state.observations)} in the log")
    print(f"  live             {len(state.live_observations())} "
          f"(one supersedes its predecessor)")
    print(f"  served over STA  {served['@iot.count']}   <- no duplicate "
          f"phenomenonTime reaches a client")
    print(f"state.validate()   {state.validate() or 'clean'}")
    print()

    chosen = state.calibration_for(raw.sensor, backfilled.measured_at)
    print("calibration by measured_at (§3.2)")
    print(f"  reading measured {backfilled.measured_at.date()}, "
          f"received {backfilled.received_at.date()}")
    print(f"  calibration used {'spring' if chosen == spring else 'summer'} "
          f"(a={chosen.coefficients['a']})  <- ingest time would have picked summer")
    print()

    print(f"datastream health  {svc.datastream(derived)['properties']['health']}")
    print(f"dialect            SensorThings {dialect.version}"
          f"{' (unpublished draft)' if args.v2 else ''}")
    print()

    print("served observations")
    for doc in served["value"]:
        extras = doc[dialect.extras_key]["fieldmesh"]
        quality = doc.get("resultQuality") or extras.get("result_quality")
        mark = ""
        if quality:
            mark = f"  [{quality[0]['usable']}: {','.join(quality[0]['flags']) or 'no objection'}]"
        print(f"  {doc['phenomenonTime']:<46} {doc['result']!s:>5}"
              f"  +/-{extras['measured_at_uncertainty_s']:>6.0f}s"
              f"  {extras['clock_quality']:<13}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
