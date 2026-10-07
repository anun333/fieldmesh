#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A day of Harrow Bend: physics -> node -> wire -> gateway -> observations.

    python3 world_demo.py
    python3 world_demo.py --days 3 --outage 12 --stuck-float
    python3 world_demo.py --dr 3

The first time the whole chain runs on its own. Nothing here is hardware and nothing
is a real farm: the world is deterministic from a seed, the node obeys its duty
cycle, and the gateway sees only what the node managed to send.

Worth watching:

* with `--stuck-float`, the trough empties and the range check flags it — a fault
  the physics produced and a detector noticed, written apart (the producer/detector
  doctrine)
* with `--outage`, the node buffers, evicts what will not fit, and reports the count,
  so the loss arrives as a recorded gap rather than as readings that never existed
* the duty cycle is obeyed throughout, which is why a long backlog takes real time
  to clear
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

import node as nd
import physics as ph

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sdk"))
import gateway as G  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
from ids import uuid7  # noqa: E402
from model import (ClockQuality, Datastream, DatastreamKind,  # noqa: E402
                   Calibration, Threshold)
from registry import NodeBinding, Registry  # noqa: E402

NODE = 0x4F2A17B3
SOIL = "http://vocab.example.org/cf/soil_moisture_content"
TROUGH = "http://vocab.example.org/odm2/water_level_fraction"


def _pair(log, state, thing, sensor, feature, prop, unit, *, interval, latency,
          thresholds, scale):
    """A raw datastream, its derived twin, and the calibration between them."""
    raw = Datastream(id=uuid7(), thing=thing, sensor=sensor, observed_property=prop,
                     feature=feature, kind=DatastreamKind.RAW, unit=unit,
                     expected_interval=interval, max_latency=latency)
    derived = Datastream(id=uuid7(), thing=thing, sensor=sensor,
                         observed_property=prop, feature=feature,
                         kind=DatastreamKind.DERIVED, derived_from=raw.id, unit=unit,
                         expected_interval=interval, max_latency=latency,
                         thresholds=thresholds)
    cal = Calibration(id=uuid7(), sensor=sensor, method="linear",
                      valid_from=_dt.datetime(2026, 1, 1, tzinfo=ph.UTC),
                      coefficients={"a": scale, "b": 0.0, "decimals": 3})
    th = Threshold(id=uuid7(), datastream=derived.id, values=thresholds)
    for record in (raw, derived, cal, th):
        log.append_record(record)
        state.add(record)
    return raw


def build(*, stuck_float: bool, dr: int, seed: int, start: _dt.datetime):
    world = ph.default_world(start=start, seed=seed)
    if stuck_float:
        world.troughs["paddock"].float_stuck_shut = True

    log = L.Log()
    state = P.State()
    site = uuid7()
    bed_thing, bed_sensor, bed_feature = uuid7(), uuid7(), uuid7()
    trough_thing, trough_sensor, trough_feature = uuid7(), uuid7(), uuid7()

    soil_raw = _pair(log, state, bed_thing, bed_sensor, bed_feature, SOIL,
                     "cm3/cm3", interval=900.0, latency=3600.0,
                     # 18 h, not 6: soil quantised to 0.001 genuinely repeats for
                     # about 8 h overnight when ET is near zero, so a shorter
                     # threshold fires nightly on a healthy probe.
                     thresholds={"max": 0.46, "min": 0.0,
                                 "flat_seconds": 18 * 3600, "flat_n": 4},
                     scale=0.001)
    trough_raw = _pair(log, state, trough_thing, trough_sensor, trough_feature,
                       TROUGH, "1", interval=300.0, latency=300.0,
                       # No flatline: a float-regulated level is constant by
                       # design, so a flat trough is the HEALTHY state. The range
                       # check is what catches a stuck float.
                       thresholds={"min": 0.10, "max": 1.0,
                                   "flat_n": None, "flat_seconds": None},
                       scale=0.001)

    registry = Registry()
    registry.register_node(NodeBinding(
        node=NODE, site=site, clock_quality=ClockQuality.RTC_UNSYNCED,
        uncertainty_s=12.0, firmware="0.3.1", driver="sim", driver_version="0.1"))
    registry.bind_point(NODE, 1, soil_raw.id)
    registry.bind_point(NODE, 2, trough_raw.id)

    node = nd.Node(NODE, [
        nd.Channel(1, 900.0, 3600.0,
                   lambda t: round(t.soil["bed3"] * 1000), name="bed3 soil"),
        nd.Channel(2, 300.0, 300.0,
                   lambda t: round(t.trough_fraction["paddock"] * 1000),
                   name="paddock trough"),
    ], dr=dr, policy=nd.BufferPolicy(buffer_max=400))

    return world, node, G.Gateway(registry, log, state), log


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=1.0)
    ap.add_argument("--outage", type=float, default=0.0,
                    help="hours of radio outage, starting at 06:00 on day 1")
    ap.add_argument("--stuck-float", action="store_true",
                    help="the float valve sticks shut and the trough empties")
    ap.add_argument("--dr", type=int, default=0, choices=(0, 1, 2, 3, 4, 5))
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    start = _dt.datetime(2026, 7, 15, 0, 0, tzinfo=ph.UTC)
    world, node, gateway, log = build(stuck_float=args.stuck_float, dr=args.dr,
                                      seed=args.seed, start=start)
    print(f"Harrow Bend  ·  {args.days:g} day(s) from {start:%Y-%m-%d}  ·  "
          f"EU868 DR{args.dr}  ·  seed {args.seed}")
    print(f"node {NODE:#x}  ·  {node.feasibility()}")
    print(f"transmit ceiling {node.transmit_interval_s:.0f} s "
          f"(tightest max_latency)\n")

    outage_from = start + _dt.timedelta(hours=6)
    outage_to = outage_from + _dt.timedelta(hours=args.outage)
    sent = deferred = 0

    for truth in world.run(days=args.days):
        node.sample(truth)
        now = truth.when.timestamp()
        if outage_from <= truth.when < outage_to:
            continue                      # radio down: the node keeps buffering
        if node.due(now) or node.behind(now):
            for attempt in node.drain(now, max_messages=8):
                gateway.receive(attempt.payload, received_at=truth.when)
                node.ack(attempt.seq)     # the gateway's cumulative ack
                sent += 1
            if node.buffered and not node.due(now):
                deferred += 1

    state = gateway.state
    live = state.live_observations()
    kinds = {}
    for event in log:
        kinds[event.kind] = kinds.get(event.kind, 0) + 1

    print(f"{'messages delivered':<26}{sent}")
    print(f"{'node buffer at the end':<26}{node.buffered} buffered, "
          f"{node.dropped_pending} evictions unreported")
    print(f"{'duty used in the last hour':<26}"
          f"{node.duty.used(world.when.timestamp()):.1f} s of 36 s")
    print(f"{'observations in the log':<26}{len(state.observations)}")
    print(f"{'live observations':<26}{len(live)}")
    print(f"{'state.validate()':<26}{state.validate() or 'clean'}")
    print()
    print("log events")
    for kind in sorted(kinds):
        print(f"  {kind:<24}{kinds[kind]}")

    flagged = [a for a in state.assertions if a.flags]
    print()
    print(f"quality assertions        {len(state.assertions)} "
          f"({len(flagged)} with a flag)")
    for assertion in flagged[:6]:
        obs = next(o for o in state.observations if o.id == assertion.observation)
        ds = state.datastreams[obs.datastream]
        label = "trough" if ds.observed_property == TROUGH else "soil"
        print(f"  {obs.measured_at:%m-%d %H:%M}  {label:<7}{obs.result!s:>7}  "
              f"{assertion.usable.value:<13}"
              f"{','.join(sorted(f.value for f in assertion.flags))}")
    if len(flagged) > 6:
        print(f"  ... and {len(flagged) - 6} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
