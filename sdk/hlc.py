#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Hybrid logical clocks for event ordering (spec v0.1 §7.4).

Offline edits need a resolution rule, and the spec's own §2 is the reason it cannot
be wall-clock last-writer-wins: layer zero records `clock_quality` precisely because
farm device clocks are unreliable. A phone whose clock is six hours fast would win
every conflict it took part in, silently, and a node reporting
`clock_quality = none` must never beat a GPS-synced one on the strength of a
timestamp nobody believes.

An HLC stamp is `(wall_ms, counter)`:

* it never goes backwards, even when the physical clock does;
* it preserves causality — anything this node learned about before writing sorts
  before the write;
* it stays within a bounded distance of physical time, so stamps remain legible to
  a human reading the log, which a pure Lamport counter does not.

That is the whole contract. `before()` gives the deterministic total order that
projections use; `Hlc.update()` is what makes causality hold, and a replica that
receives a remote stamp without calling it has silently dropped that guarantee.

Last-writer-wins over HLC order still loses one value when writes are genuinely
concurrent. §7.4 requires a conflict event for fields where that matters; HLC tells
you *that* two writes were concurrent, not what to do about it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True, order=True, slots=True)
class Stamp:
    """A point in hybrid-logical time. Ordered by (wall_ms, counter)."""

    wall_ms: int
    counter: int = 0

    def __post_init__(self) -> None:
        if self.wall_ms < 0:
            raise ValueError("wall_ms must not be negative")
        if self.counter < 0:
            raise ValueError("counter must not be negative")

    def __str__(self) -> str:
        return f"{self.wall_ms}.{self.counter}"

    @classmethod
    def parse(cls, s: str) -> "Stamp":
        wall, _, counter = s.partition(".")
        return cls(int(wall), int(counter or 0))


def before(a: Stamp, b: Stamp) -> bool:
    """Deterministic total order. Equal stamps are not before each other."""
    return (a.wall_ms, a.counter) < (b.wall_ms, b.counter)


class Hlc:
    """One node's hybrid logical clock.

    `clock` is injectable so tests can move physical time, including backwards.
    """

    __slots__ = ("_clock", "_last")

    def __init__(self, *, clock=_wall_ms):
        self._clock = clock
        self._last = Stamp(0, 0)

    @property
    def last(self) -> Stamp:
        return self._last

    def now(self) -> Stamp:
        """Stamp a local event."""
        physical = self._clock()
        if physical > self._last.wall_ms:
            self._last = Stamp(physical, 0)
        else:
            # Physical time has not advanced past what we have already issued —
            # either the same millisecond or a clock that stepped back. Count.
            self._last = Stamp(self._last.wall_ms, self._last.counter + 1)
        return self._last

    def update(self, remote: Stamp) -> Stamp:
        """Merge a stamp received from elsewhere, then stamp the receive event.

        Call this on every inbound stamp. Skipping it is what breaks causality.
        """
        physical = self._clock()
        local = self._last
        wall = max(local.wall_ms, remote.wall_ms, physical)
        if wall == local.wall_ms == remote.wall_ms:
            counter = max(local.counter, remote.counter) + 1
        elif wall == local.wall_ms:
            counter = local.counter + 1
        elif wall == remote.wall_ms:
            counter = remote.counter + 1
        else:
            counter = 0
        self._last = Stamp(wall, counter)
        return self._last
