#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A simulated link between a node and a gateway (spec v0.1 §5.2, §5.4).

Until now `world_demo` handed frames straight from the node to the gateway, so every
message arrived exactly once and in order. That is the one condition under which none
of layer zero's hard clauses matter: no duplicates to deduplicate, no holes to record
as gaps, no lost acknowledgement to resend past. This is the link that takes that
comfort away.

It loses frames, delays them by a variable amount — so reordering emerges rather than
being a separate knob — duplicates them, drops acknowledgements, and goes out
entirely for a while. All of it deterministic from a seed, because a fault that only
happens sometimes is a fault you cannot fix.

**The lost acknowledgement is the interesting one.** When a frame arrives but its ack
does not, the node's deadline expires and it resends — with the *same* sequence number,
as §6.3 requires of commands and as §1's dedup key requires of readings. The gateway
then sees a genuine duplicate and must recognise it. That round trip is the only way
to test the dedup contract end to end, and it cannot happen over a perfect link.

`confirmation` reflects §5.2's three cases. A link that confirms nothing needs the
gateway's cumulative ack; one that confirms every frame does not, and pays a downlink
per message for the privilege.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

CONFIRM_NONE = "none"
CONFIRM_RECEIPT = "gateway_receipt"
CONFIRM_FRAME = "confirmed"


@dataclass(frozen=True, slots=True)
class LinkProfile:
    """What a link does to the frames it carries.

    Reordering has no knob of its own: give `delay_s` a range and frames sent close
    together will overtake each other, which is how reordering actually happens.
    """

    name: str = "ideal"
    loss: float = 0.0
    duplicate: float = 0.0
    delay_s: tuple = (0.0, 0.0)
    ack_loss: float = 0.0
    confirmation: str = CONFIRM_NONE

    def __post_init__(self) -> None:
        for field_name in ("loss", "duplicate", "ack_loss"):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be a probability")
        low, high = self.delay_s
        if low < 0 or high < low:
            raise ValueError("delay_s must be a non-negative (low, high)")
        if self.confirmation not in (CONFIRM_NONE, CONFIRM_RECEIPT, CONFIRM_FRAME):
            raise ValueError(f"unknown confirmation mode {self.confirmation!r}")


#: Profiles for the links §5.2 names. The numbers are plausible rather than
#: measured — a real figure needs a field season, which open-questions Q6 and Q1
#: between them are the path to.
MESHTASTIC = LinkProfile(name="meshtastic", loss=0.06, duplicate=0.02,
                         delay_s=(0.5, 12.0), ack_loss=0.10,
                         confirmation=CONFIRM_NONE)
LORAWAN_UNCONFIRMED = LinkProfile(name="lorawan-unconfirmed", loss=0.04,
                                  duplicate=0.005, delay_s=(0.2, 2.0),
                                  ack_loss=0.08, confirmation=CONFIRM_RECEIPT)
LORAWAN_CONFIRMED = LinkProfile(name="lorawan-confirmed", loss=0.01,
                                duplicate=0.0, delay_s=(0.2, 3.0), ack_loss=0.02,
                                confirmation=CONFIRM_FRAME)
WIRED = LinkProfile(name="wired", confirmation=CONFIRM_FRAME)

PRESETS = {p.name: p for p in (MESHTASTIC, LORAWAN_UNCONFIRMED,
                               LORAWAN_CONFIRMED, WIRED, LinkProfile())}


@dataclass(frozen=True, slots=True)
class Delivery:
    """A frame arriving at the gateway."""

    payload: bytes
    at_s: float
    duplicate_of: int | None = None     # the ordinal of the frame it repeats


@dataclass
class LinkStats:
    sent: int = 0
    lost: int = 0
    lost_to_outage: int = 0
    delivered: int = 0
    duplicated: int = 0
    acks_sent: int = 0
    acks_lost: int = 0

    def as_dict(self) -> dict:
        return {"sent": self.sent, "lost": self.lost,
                "lost_to_outage": self.lost_to_outage,
                "delivered": self.delivered, "duplicated": self.duplicated,
                "acks_sent": self.acks_sent, "acks_lost": self.acks_lost}


class Link:
    """One node's radio path, both directions."""

    __slots__ = ("profile", "stats", "_rng", "_queue", "_acks", "_outages",
                 "_ordinal")

    def __init__(self, profile: LinkProfile | None = None, *, seed: int = 1):
        self.profile = profile or LinkProfile()
        self.stats = LinkStats()
        self._rng = random.Random(seed)
        self._queue: list[tuple[float, int, bytes, int | None]] = []
        self._acks: list[tuple[float, int]] = []
        self._outages: list[tuple[float, float]] = []
        self._ordinal = 0

    # ------------------------------------------------------------------ outages

    def outage(self, from_s: float, to_s: float) -> None:
        """The radio is unreachable in `[from_s, to_s)`.

        Distinct from loss: during an outage *nothing* gets through, and the node
        does not know, so it keeps buffering until its acknowledgement deadline
        expires (§5.3).
        """
        if to_s < from_s:
            raise ValueError("an outage ends after it starts")
        self._outages.append((from_s, to_s))

    def down(self, at_s: float) -> bool:
        return any(a <= at_s < b for (a, b) in self._outages)

    # -------------------------------------------------------------- uplink

    def send(self, payload: bytes, at_s: float) -> str:
        """Hand a frame to the radio. Returns what became of it."""
        self.stats.sent += 1
        self._ordinal += 1
        ordinal = self._ordinal
        if self.down(at_s):
            self.stats.lost_to_outage += 1
            return "outage"
        if self._rng.random() < self.profile.loss:
            self.stats.lost += 1
            return "lost"
        self._enqueue(payload, at_s, ordinal, None)
        if self._rng.random() < self.profile.duplicate:
            # A mesh that forwards a frame twice, or a retry whose first copy
            # arrived after all. §1's dedup key is what makes this harmless.
            self.stats.duplicated += 1
            self._enqueue(payload, at_s, ordinal, ordinal)
        return "queued"

    def _enqueue(self, payload, at_s, ordinal, duplicate_of) -> None:
        low, high = self.profile.delay_s
        delay = low if high == low else self._rng.uniform(low, high)
        self._queue.append((at_s + delay, ordinal, payload, duplicate_of))

    def deliver(self, now_s: float):
        """Frames whose delay has elapsed, oldest arrival first.

        Sorted by arrival rather than by send order, which is where reordering
        shows up: two frames sent seconds apart with a twelve-second delay spread
        can swap places.
        """
        due = [item for item in self._queue if item[0] <= now_s]
        if not due:
            return []
        self._queue = [item for item in self._queue if item[0] > now_s]
        due.sort(key=lambda item: (item[0], item[1]))
        self.stats.delivered += len(due)
        return [Delivery(payload=payload, at_s=at, duplicate_of=dup)
                for (at, _, payload, dup) in due]

    # ------------------------------------------------------------- downlink

    def send_ack(self, seq: int, at_s: float) -> str:
        """The gateway's cumulative ack (§5.2): the highest contiguous seq it holds.

        One small downlink retires many uplinks, which is what makes
        store-and-forward affordable on a link that confirms nothing — and losing
        one is what causes the node to resend a frame that already arrived.
        """
        self.stats.acks_sent += 1
        if self.down(at_s) or self._rng.random() < self.profile.ack_loss:
            self.stats.acks_lost += 1
            return "lost"
        low, high = self.profile.delay_s
        delay = low if high == low else self._rng.uniform(low, high)
        self._acks.append((at_s + delay, seq))
        return "queued"

    def acks(self, now_s: float):
        """Acknowledgements that have arrived back at the node."""
        due = [item for item in self._acks if item[0] <= now_s]
        if not due:
            return []
        self._acks = [item for item in self._acks if item[0] > now_s]
        due.sort()
        return [seq for (_, seq) in due]

    # ---------------------------------------------------------------- inspection

    @property
    def in_flight(self) -> int:
        return len(self._queue)

    @property
    def needs_cumulative_ack(self) -> bool:
        """§5.2: a link that confirms nothing relies on the gateway saying so."""
        return self.profile.confirmation != CONFIRM_FRAME

    def loss_rate(self) -> float:
        if not self.stats.sent:
            return 0.0
        return (self.stats.lost + self.stats.lost_to_outage) / self.stats.sent


__all__ = ["Link", "LinkProfile", "LinkStats", "Delivery", "PRESETS",
           "MESHTASTIC", "LORAWAN_UNCONFIRMED", "LORAWAN_CONFIRMED", "WIRED",
           "CONFIRM_NONE", "CONFIRM_RECEIPT", "CONFIRM_FRAME"]
