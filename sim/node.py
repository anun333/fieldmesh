#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A simulated node: sampling, buffering, draining (spec v0.1 §5.2, §5.3, §5.3.1).

The node half of store-and-forward. The gateway half is `sdk/gateway.py`; this is
what sits in a bed with a battery and decides what to send and when.

It samples each channel on that channel's own interval, holds readings until the
link confirms them, restamps their ages at **transmit** (§2), packs what fits the
current payload budget (§5.2), and transmits on the tightest `max_latency` it
carries (§5.3.1). What it cannot keep, it evicts and **counts**, so the loss reaches
the log as a gap rather than as readings that quietly never existed (§5.3).

Three behaviours that are easy to get wrong and are the point of simulating this:

**The duty cycle is a regulation, not a preference.** A node that cannot afford a
message does not send it — it stays buffered, which costs latency rather than data
(§5.2). A sim that ignores this produces a fleet that could not legally exist.

**A reboot loses the buffer, and cannot report it.** §1 makes `boot` the only
non-volatile state a node is required to keep, so after a cold start the node has no
memory of the readings it was holding and cannot count them as dropped. The *reboot
event* is what reveals the loss (§5.4), which is precisely why a boot increment is
logged as a reboot rather than inferred from a sequence hole. A node with
non-volatile buffering can say so; the default is the honest, cheap hardware.

**A latency requirement is a ceiling, not a schedule.** §5.3.1 sets the transmit
interval from the tightest `max_latency`, but that is the longest a reading may wait,
not how often the radio should speak. A node sampling twelve readings an hour and
sending one message an hour that holds five is permanently behind, and will lose data
forever while looking healthy. So the node also drains opportunistically whenever it
has a backlog and the duty cycle allows, and `feasible` says up front whether the
configuration can ever keep up — a question that belongs at registration, not in
month three when someone notices the gaps.

**Fresh-first and chronological are both correct.** §5.3: a livestock water monitor
wants the newest reading after an outage, a research logger wants the series
unbroken. The policy is per datastream and the node obeys it; neither is a default
that suits both.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sdk"))
import wire  # noqa: E402
from airtime import (DUTY_CYCLE_BUDGET_S, MAX_APP_PAYLOAD,  # noqa: E402
                     DutyCycle, frame_airtime)

CHRONOLOGICAL = "chronological"
FRESH_FIRST = "fresh_first"
EVICT_OLDEST = "oldest"
EVICT_NEWEST = "newest"


@dataclass(frozen=True, slots=True)
class BufferPolicy:
    """§5.3. What a node retains, what it discards, and in which order it drains."""

    buffer_max: int = 2000
    eviction: str = EVICT_OLDEST
    drain_order: str = CHRONOLOGICAL
    #: A node with flash or FRAM can keep its buffer across a cold start. Most
    #: cannot, and §1 only requires `boot` to survive.
    nonvolatile_buffer: bool = False

    def __post_init__(self) -> None:
        if self.buffer_max < 1:
            raise ValueError("buffer_max must be at least one reading")
        if self.eviction not in (EVICT_OLDEST, EVICT_NEWEST):
            raise ValueError(f"eviction must be {EVICT_OLDEST!r} or {EVICT_NEWEST!r}")
        if self.drain_order not in (CHRONOLOGICAL, FRESH_FIRST):
            raise ValueError(
                f"drain_order must be {CHRONOLOGICAL!r} or {FRESH_FIRST!r}")


@dataclass(frozen=True, slots=True)
class Channel:
    """One point on this node.

    `sense` turns ground truth into the integer the node would sample — the scale
    lives here and in the calibration, never on the wire (§5.1, §3.2). Returning
    None means the sensor had nothing to report this tick.
    """

    channel: int
    sample_interval_s: float
    max_latency_s: float
    sense: Callable
    name: str = ""

    def __post_init__(self) -> None:
        if self.sample_interval_s <= 0 or self.max_latency_s <= 0:
            raise ValueError("intervals must be positive")
        if self.sample_interval_s < 1.0:
            # §5.2: wire ages are whole seconds, so a faster channel cannot express
            # distinct instants and the gateway would have to refuse the collision.
            raise ValueError(
                "sample_interval_s below 1 s cannot be expressed by the wire "
                "format's whole-second ages (§5.2)")


@dataclass(frozen=True, slots=True)
class Transmission:
    """What a transmit attempt did."""

    payload: bytes | None
    seq: int | None = None
    readings: int = 0
    airtime_s: float = 0.0
    dropped_reported: int = 0
    deferred: str | None = None       # why nothing was sent
    resend: bool = False              # a retry under its original seq (§5.2)

    @property
    def sent(self) -> bool:
        return self.payload is not None


@dataclass
class _Held:
    """One reading the node is still responsible for."""

    sampled_at_s: float
    reading: object
    seq: int | None = None            # set once it has been sent
    awaiting_resend: bool = False     # its acknowledgement never came
    attempts: int = 0                 # transmissions so far


class Node:
    """A duty-cycled sensing node."""

    __slots__ = ("node_id", "channels", "policy", "dr", "duty", "boot", "seq",
                 "ack_timeout_s", "resend_horizon_s", "stamp_at_sample",
                 "clock_offset_s",
                 "_held", "_dropped",
                 "_last_sample", "_last_tx", "_sent_order", "_sent_at")

    def __init__(self, node_id: int, channels, *, policy: BufferPolicy | None = None,
                 dr: int = 0, boot: int = 1,
                 duty_budget_s: float = DUTY_CYCLE_BUDGET_S,
                 ack_timeout_s: float | None = None,
                 resend_horizon_s: float = 3 * 86400.0,
                 stamp_at_sample: bool = False,
                 clock_offset_s: float = 0.0):
        if not channels:
            raise ValueError("a node needs at least one channel")
        self.node_id = node_id
        self.channels = {c.channel: c for c in channels}
        self.policy = policy or BufferPolicy()
        self.dr = dr
        self.duty = DutyCycle(budget_s=duty_budget_s)
        self.boot = boot
        self.seq = 0
        self._held: list[_Held] = []
        self._dropped = 0
        self._last_sample: dict[int, float] = {}
        self._last_tx: float | None = None
        self._sent_order: list[int] = []
        self._sent_at: dict[int, float] = {}
        #: How long to wait for a cumulative ack before assuming the frame was
        #: lost and requeueing its readings. None means never give up, which is
        #: only safe on a link that confirms every frame.
        self.ack_timeout_s = ack_timeout_s
        #: How long the node keeps trying to deliver a reading before giving up.
        #:
        #: It needs a bound at all because unbounded resending livelocks: a resend
        #: goes first by design, so a frame whose acknowledgement can never arrive
        #: blocks every reading behind it and the node saturates its buffer while
        #: looking busy. Measured: 316 readings stuck behind one such frame.
        #:
        #: The bound must be in **time**, not attempts. An attempt count silently
        #: caps how long a node can survive an outage — four attempts at a
        #: half-hour deadline is two hours, so a three-day outage lost everything
        #: while appearing to work. This is the farmer-facing number: how long the
        #: node holds a reading before it becomes a recorded gap (§5.4). It should
        #: exceed the longest outage the deployment intends to survive.
        self.resend_horizon_s = resend_horizon_s
        #: A deliberate §2 violation, for the sim only. A node that records a
        #: reading's age when it *samples* records zero — the reading is new — and
        #: never updates it, so a buffered batch arrives claiming every reading was
        #: taken at the instant the frame landed. Modelled so the damage can be
        #: shown; never set it on anything real.
        self.stamp_at_sample = stamp_at_sample
        #: How wrong this node's clock is. §2 has nodes report ages rather than
        #: timestamps precisely so that a constant offset cancels: the node
        #: subtracts two readings of its own clock, and the error goes with it. One
        #: clock, used for both ends — mixing a true sample time with a skewed
        #: transmit time is how this breaks, and it breaks silently.
        self.clock_offset_s = clock_offset_s

    # ------------------------------------------------------------- properties

    @property
    def transmit_interval_s(self) -> float:
        """§5.3.1: the tightest latency any channel asks for sets the schedule for
        all of them, because they share one radio."""
        return min(c.max_latency_s for c in self.channels.values())

    @property
    def max_payload(self) -> int:
        return MAX_APP_PAYLOAD[self.dr]

    @property
    def buffered(self) -> int:
        """Readings sampled but never sent."""
        return sum(1 for h in self._held if h.seq is None)

    @property
    def awaiting_resend(self) -> int:
        """Readings whose frame was sent and never acknowledged."""
        return sum(1 for h in self._held if h.awaiting_resend)

    @property
    def unacked(self) -> int:
        """Readings sent but not yet confirmed."""
        return sum(1 for h in self._held if h.seq is not None)

    @property
    def retained(self) -> int:
        return len(self._held)

    @property
    def dropped_pending(self) -> int:
        """Evictions not yet reported to the gateway."""
        return self._dropped

    @property
    def readings_per_hour(self) -> float:
        """What this node produces."""
        return sum(3600.0 / c.sample_interval_s for c in self.channels.values())

    def deliverable_per_hour(self) -> float:
        """What this node can actually send, given payload size and duty budget.

        Measured rather than estimated: pack a full batch and see both how many
        readings fit one frame and how many frames the duty cycle affords.
        """
        probe = [wire.Reading((i % 8) + 1, i, 100 + i) for i in range(64)]
        payload, per_frame = wire.pack(probe, boot=self.boot, seq=0, base_age=0,
                                       max_payload=self.max_payload,
                                       node=self.node_id)
        airtime = frame_airtime(len(payload), dr=self.dr)
        frames = self.duty.budget_s / airtime
        return frames * per_frame

    @property
    def feasible(self) -> bool:
        return self.deliverable_per_hour() >= self.readings_per_hour

    def feasibility(self) -> str:
        """A sentence a farmer or an installer can act on."""
        produced = self.readings_per_hour
        deliverable = self.deliverable_per_hour()
        if deliverable >= produced:
            return (f"ok: produces {produced:.0f} readings/h, can deliver "
                    f"{deliverable:.0f}/h at DR{self.dr}")
        return (f"INFEASIBLE: produces {produced:.0f} readings/h but can only "
                f"deliver {deliverable:.0f}/h at DR{self.dr}. It will lose data "
                f"permanently. Sample less often, raise the data rate, or split "
                f"the channels across nodes")

    # ---------------------------------------------------------------- sensing

    def sample(self, truth) -> int:
        """Sample every channel that is due. Returns how many readings were taken."""
        now_s = truth.when.timestamp() + self.clock_offset_s
        taken = 0
        for channel in self.channels.values():
            last = self._last_sample.get(channel.channel)
            if last is not None and now_s - last < channel.sample_interval_s:
                continue
            value = channel.sense(truth)
            self._last_sample[channel.channel] = now_s
            if value is None:
                continue
            self._held.append(_Held(sampled_at_s=now_s,
                                    reading=wire.Reading(channel.channel, 0,
                                                         int(value))))
            taken += 1
        self._evict()
        return taken

    def _evict(self) -> None:
        """§5.3. Discard down to `buffer_max` and count what went."""
        excess = len(self._held) - self.policy.buffer_max
        if excess <= 0:
            return
        if self.policy.eviction == EVICT_OLDEST:
            self._held = self._held[excess:]
        else:
            self._held = self._held[:-excess]
        self._dropped += excess

    # ------------------------------------------------------------- transmitting

    def due(self, now_s: float) -> bool:
        """Is a transmit required by the latency ceiling?"""
        if self.buffered == 0:
            return False
        if self._last_tx is None:
            return True
        return now_s - self._last_tx >= self.transmit_interval_s

    def behind(self, now_s: float) -> bool:
        """Is there more backlog than one frame can carry?

        Separate from `due` because the answers differ: a node can be inside its
        latency ceiling and still falling behind, which is the state that loses data
        silently.
        """
        return self.buffered > 0 and not self.due(now_s) and self.buffered > 1

    def drain(self, now_s: float, *, max_messages: int = 16):
        """Send while there is backlog and the duty cycle affords it.

        This is what keeps a node from sitting on a backlog with airtime to spare.
        It stops on the first deferral, so a duty-cycle refusal ends the burst
        rather than being retried in a loop.
        """
        sent = []
        for _ in range(max_messages):
            # Resends count as backlog. Under `fresh_first` the newest frame goes ahead
            # of them, and a drain that stopped once nothing was left unsent would leave
            # them behind every new sample until the horizon turned them into a gap.
            if self.buffered == 0 and self.awaiting_resend == 0:
                break
            attempt = self.transmit(now_s)
            if not attempt.sent:
                break
            sent.append(attempt)
        return sent

    def transmit(self, now_s: float) -> Transmission:
        """Drain what fits the payload budget and the duty cycle.

        Ages are computed here, not at sample time (§2). A batch that waited three
        days leaves with three days of age on it.

        A frame awaiting resend goes first and **keeps its sequence number**, so the
        gateway can recognise it as the message it may already hold.

        **Except under `fresh_first`, when there is something newer to say** (§5.3).
        Through a long outage every frame the node tries goes unacknowledged, so when
        the link returns the resends are all of the oldest readings. Sending them first
        delivered a trough's level from midnight at noon, twelve hours stale, for the
        one series whose whole policy is that the newest reading goes first — the
        livestock water monitor's acceptance test found it. Readings never sent that
        are newer than every frame awaiting resend go first; the resends follow in the
        same burst, under their own numbers.
        """
        pending = [h for h in self._held
                   if h.seq is None and not h.awaiting_resend]
        resend = self._next_resend()
        if resend is not None:
            if not (self.policy.drain_order == FRESH_FIRST and pending
                    and max(h.sampled_at_s for h in pending) > self._newest_awaiting()):
                return self._send(resend, now_s, seq=resend[0].seq, resend=True)
        if not pending:
            return Transmission(payload=None, deferred="nothing buffered")
        return self._send(self._drain_order(pending), now_s, seq=self.seq,
                          resend=False)

    def _newest_awaiting(self) -> float:
        return max((h.sampled_at_s for h in self._held if h.awaiting_resend),
                   default=float("-inf"))

    def _next_resend(self):
        """The frame to resend next, as a group: the earliest sent, or under
        `fresh_first` the one holding the newest readings — a fresh frame lost on the
        way is resent before the night's backlog, not after it (§5.3).

        One pass to group, then a lookup per sequence number — not a scan of the
        buffer per sequence number. The nested version was correct and was **the
        single most expensive thing in a simulated season**: 7.4 s of a 31 s week,
        more than the whole projection layer, because its cost is the product of two
        quantities that both grow during an outage. The buffer fills to
        `policy.buffer_max` while nothing is getting through, and `_sent_order`
        lengthens with every frame sent and unacknowledged, so exactly when a node is
        working hardest the scan is at its worst. That is the wrong shape for a
        reliability path: the code should not slow down in the conditions it exists
        to survive.

        Grouped fresh each call rather than kept as an index, deliberately.
        `_held` is mutated in a dozen places — eviction from either end, cumulative
        acknowledgement, hole abandonment, reboot — and an index that disagreed with
        the buffer would produce a resend of a frame the node no longer has, which is
        far worse than a slow scan. One pass over the buffer is O(held); the version
        it replaces was O(held x sent_order).
        """
        if not self._sent_order:
            return None
        groups: dict[int, list] = {}
        for h in self._held:
            if h.awaiting_resend and h.seq is not None:
                groups.setdefault(h.seq, []).append(h)
        if not groups:
            return None
        if self.policy.drain_order == FRESH_FIRST:
            return max(groups.values(), key=lambda g: max(h.sampled_at_s for h in g))
        for seq in self._sent_order:
            group = groups.get(seq)
            if group:
                return group
        return None

    def _send(self, ordered, now_s: float, *, seq: int,
              resend: bool) -> Transmission:
        ordered = list(ordered)
        if self.stamp_at_sample:
            # The mistake: the age was recorded when the reading was taken, so it
            # is zero, and nobody updated it. The gateway then computes
            # `measured_at = received_at`, collapsing a whole buffered batch onto
            # the instant the frame arrived.
            zeroed = [wire.Reading(h.reading.channel, 0, h.reading.value)
                      for h in ordered]
            return self._emit(ordered, zeroed, 0, now_s, seq=seq, resend=resend)
        reference = (min(h.sampled_at_s for h in ordered) if self.stamp_at_sample
                     else now_s)
        candidates = [wire.Reading(h.reading.channel,
                                   int(reference - h.sampled_at_s),
                                   h.reading.value)
                      for h in ordered]
        base = min(r.age_delta for r in candidates)
        candidates = [wire.Reading(r.channel, r.age_delta - base, r.value)
                      for r in candidates]

        return self._emit(ordered, candidates, base, now_s, seq=seq, resend=resend)

    def _emit(self, ordered, candidates, base, now_s, *, seq, resend):
        try:
            payload, count = wire.pack(candidates, boot=self.boot, seq=seq,
                                       base_age=base, max_payload=self.max_payload,
                                       node=self.node_id, dropped=self._dropped)
        except wire.WireError as exc:
            return Transmission(payload=None, deferred=str(exc))

        airtime = frame_airtime(len(payload), dr=self.dr)
        if not self.duty.allows(airtime, now_s):
            # §5.2: the limit is a regulation. Keep the data, lose the latency.
            return Transmission(
                payload=None, airtime_s=airtime,
                deferred=f"duty cycle: {airtime:.2f} s needed, "
                         f"{self.duty.remaining(now_s):.2f} s left this hour")

        self.duty.record(airtime, now_s)
        for held in ordered[:count]:
            held.seq = seq
            held.awaiting_resend = False
            held.attempts += 1
        self._sent_at[seq] = now_s
        reported = self._dropped
        self._dropped = 0
        if not resend:
            self._sent_order.append(seq)
            self.seq = (self.seq + 1) & 0xFFFF
        self._last_tx = now_s
        return Transmission(payload=payload, seq=seq, readings=count,
                            airtime_s=airtime, dropped_reported=reported,
                            resend=resend)

    def _drain_order(self, pending):
        """§5.3. Oldest first keeps a series unbroken; newest first gets the
        current value through when the backlog is longer than the budget."""
        if self.policy.drain_order == FRESH_FIRST:
            return sorted(pending, key=lambda h: -h.sampled_at_s)
        return sorted(pending, key=lambda h: h.sampled_at_s)

    # ------------------------------------------------------------ confirmation

    def ack(self, seq: int, *, cumulative: bool = True) -> int:
        """Release what an acknowledgement covers.

        Cumulative (§5.2): everything up to and including `seq`. One small downlink
        retires many uplinks, which is what makes store-and-forward affordable on a
        link that confirms nothing, and it is true because the gateway sends its
        *highest contiguous* seq.

        **A frame's own confirmation is not cumulative.** A link that confirms each
        frame says that frame arrived and nothing about the ones before it. Read as
        cumulative, the confirmation of a fresh frame released every older frame still
        waiting for resend, as if delivered: after a twelve-hour outage under
        `fresh_first`, 123 of the paddock's readings became 21. The same loss happened
        before that, more rarely, whenever a lost frame was followed by a confirmed one.
        """
        if seq not in self._sent_order:
            return 0
        if not cumulative:
            before = len(self._held)
            self._held = [h for h in self._held if h.seq != seq]
            self._sent_order.remove(seq)
            self._sent_at.pop(seq, None)
            return before - len(self._held)
        cutoff = self._sent_order.index(seq)
        released = set(self._sent_order[:cutoff + 1])
        before = len(self._held)
        self._held = [h for h in self._held if h.seq not in released]
        self._sent_order = self._sent_order[cutoff + 1:]
        for gone in released:
            self._sent_at.pop(gone, None)
        return before - len(self._held)

    def nack(self) -> int:
        """Give up waiting: return unconfirmed readings to the buffer for resend."""
        requeued = 0
        for held in self._held:
            if held.seq is not None:
                held.seq = None
                held.awaiting_resend = False
                held.attempts = 0
                requeued += 1
        self._sent_order.clear()
        self._sent_at.clear()
        return requeued

    def expire_unacked(self, now_s: float) -> int:
        """Mark frames whose acknowledgement never came for resend (§5.2).

        On a link that confirms nothing, a lost frame and a slow one are
        indistinguishable until this deadline passes.

        **The resend keeps its original sequence number.** This is the same rule
        §6.3 states for commands, and it matters here for the same reason: the
        dedup key is `(site, node, boot, seq)`, so a retry under a fresh number is
        a *new message* as far as the gateway is concerned. It then writes the same
        readings again, at timestamps that differ by the rounding of a recomputed
        age — phantom readings a second away from the real ones, in a series nobody
        can later untangle. Measured on a lossy link: 2498 observations where 768
        were expected.

        A deadline is **mandatory** on a link that relies on cumulative
        acknowledgement. Without one, a single lost frame stalls
        `highest_contiguous` at the hole below it forever and the node holds every
        later reading until it starts evicting.
        """
        if self.ack_timeout_s is None:
            return 0

        # The horizon sweep is unconditional, and has to be. Resending refreshes a
        # frame's deadline, so a frame the node keeps retrying never looks "stale"
        # and would never be reconsidered — which is the livelock wearing a
        # disguise. Age is measured from when the reading was *sampled*, which no
        # amount of retrying changes.
        abandoned = 0
        if self.resend_horizon_s is not None:
            keep = []
            for held in self._held:
                if (held.seq is not None
                        and now_s - held.sampled_at_s > self.resend_horizon_s):
                    abandoned += 1
                    continue
                keep.append(held)
            if abandoned:
                # §5.4: undeliverable is a gap, recorded, not an indefinite block.
                self._held = keep
                self._dropped += abandoned
                alive = {h.seq for h in self._held if h.seq is not None}
                self._sent_order = [s for s in self._sent_order if s in alive]
                for gone in set(self._sent_at) - alive:
                    self._sent_at.pop(gone, None)

        expired = [s for s in self._sent_order
                   if now_s - self._sent_at.get(s, now_s) >= self.ack_timeout_s]
        marked = 0
        for held in self._held:
            if held.seq in set(expired) and not held.awaiting_resend:
                held.awaiting_resend = True
                marked += 1
        return marked

    # ------------------------------------------------------------------ power

    def reboot(self) -> int:
        """Cold start. `boot` survives; the buffer usually does not.

        Returns how many readings were lost. The node cannot report these — after a
        power cut it has no memory of them — so the reboot event in the log is the
        only record (§5.4). That asymmetry is why §1 makes `boot` non-volatile.
        """
        lost = 0
        if not self.policy.nonvolatile_buffer:
            lost = len(self._held)
            self._held = []
            self._dropped = 0
        else:
            for held in self._held:
                held.seq = None
                held.awaiting_resend = False
        self.boot += 1
        self.seq = 0
        self._sent_order.clear()
        self._sent_at.clear()
        self._last_sample.clear()
        self._last_tx = None
        return lost


__all__ = ["Node", "Channel", "BufferPolicy", "Transmission", "CHRONOLOGICAL",
           "FRESH_FIRST", "EVICT_OLDEST", "EVICT_NEWEST"]
