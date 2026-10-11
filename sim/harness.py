#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run a world through a node, a link and a gateway (docs/VIRTUAL_FARM.md step 3).

One loop, shared by the demo and the tests, so what a test exercises and what a
demo shows are the same code.

The order inside a tick is the order §5.1 and §5.2 describe, and it matters:

    the world advances                       physics.py
    the node samples what is due             node.sample
    the node gives up on unacknowledged      node.expire_unacked  (§5.2)
    the node drains if due or behind         node.drain           (§5.3.1)
    the link carries, loses, delays, repeats link.send / link.deliver
    the gateway ingests                      gateway.receive      (§5.1 step 4)
    the gateway acknowledges, periodically   gateway.highest_contiguous (§5.2)
    the link carries the ack back, or loses it

`node_clock_offset_s` exists to demonstrate a §2 property rather than to model a
fault: because a node reports *ages* computed from its own clock at both ends, a
constant offset cancels exactly and `measured_at` comes out right however wrong the
node's clock is. Set it to six hours and watch nothing happen.

It is set **on the node**, not applied by the harness, because the node has one
clock and must use it at both ends. An earlier version of this loop sampled against
true time and transmitted against skewed time, and the offset no longer cancelled —
which is a fair warning: mixing clocks is how this breaks in reality, and it breaks
silently.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from dataclasses import dataclass, field

import link as lk

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sdk"))
import wire  # noqa: E402


@dataclass
class RunReport:
    """What a run did. Everything here is either counted or in the log."""

    ticks: int = 0
    frames_sent: int = 0
    frames_deferred: int = 0
    frames_ingested: int = 0
    duplicates_rejected: int = 0
    quarantined: int = 0
    undecodable: int = 0
    acks_sent: int = 0
    requeued: int = 0
    link: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {k: v for k, v in self.__dict__.items() if k != "link"}
        out["link"] = dict(self.link)
        return out


def run(*, world, node, gateway, link=None, days: float = 1.0,
        ack_every_s: float = 900.0, node_clock_offset_s: float = 0.0,
        outages=()) -> RunReport:
    """Step the world for `days`, carrying readings to the gateway.

    `outages` is a sequence of `(start, end)` datetimes during which the radio is
    unreachable — distinct from random loss, because nothing gets through and the
    node does not know.
    """
    link = link if link is not None else lk.Link(lk.WIRED)
    if node_clock_offset_s:
        node.clock_offset_s = node_clock_offset_s
    for start, end in outages:
        link.outage(start.timestamp(), end.timestamp())

    report = RunReport(link=link.stats.as_dict())
    last_ack = None

    for truth in world.run(days=days):
        report.ticks += 1
        true_now = truth.when.timestamp()
        node_now = true_now + node.clock_offset_s

        node.sample(truth)
        report.requeued += node.expire_unacked(node_now)

        if node.due(node_now) or node.behind(node_now):
            for attempt in node.drain(node_now, max_messages=8):
                link.send(attempt.payload, true_now)
                report.frames_sent += 1
            if node.buffered and not node.due(node_now):
                report.frames_deferred += 1

        for delivery in link.deliver(true_now):
            received_at = _dt.datetime.fromtimestamp(delivery.at_s,
                                                     tz=_dt.timezone.utc)
            result = gateway.receive(delivery.payload, received_at=received_at)
            if result.status == "accepted":
                report.frames_ingested += 1
            elif result.status == "duplicate":
                report.duplicates_rejected += 1
            elif result.status == "quarantined":
                report.quarantined += 1
            elif result.status == "undecodable":
                report.undecodable += 1
            if not link.needs_cumulative_ack:
                # §5.2's `confirmed` case: the link acknowledges each frame itself,
                # which is why it costs a downlink per message. The node is told
                # straight away and never needs the gateway's cumulative ack.
                link.send_ack(wire.decode(delivery.payload).seq, true_now)
                report.acks_sent += 1

        if link.needs_cumulative_ack and (last_ack is None
                                          or true_now - last_ack >= ack_every_s):
            acked = gateway.highest_contiguous(node.node_id, node.boot,
                                               now_s=true_now)
            if acked is not None:
                link.send_ack(acked, true_now)
                report.acks_sent += 1
            last_ack = true_now

        # The link is the physical medium, so it runs on true time throughout.
        # Polling it on the node's skewed clock was another mixed-clock bug: acks
        # queued at true time never came due, and the node resent forever.
        for seq in link.acks(true_now):
            node.ack(seq, cumulative=link.needs_cumulative_ack)

    report.link = link.stats.as_dict()
    return report


__all__ = ["run", "RunReport"]
