#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""UUIDv7 identity (spec v0.1 §1).

RFC 9562 §5.7 layout, big-endian:

    0                   1                   2                   3
    |unix_ts_ms (48 bits)                   |ver|rand_a |var|rand_b…|
    bits   0..47  Unix timestamp, milliseconds
    bits  48..51  version, 0b0111
    bits  52..63  rand_a — used here as a monotonic counter (RFC 9562 §6.2,
                  the dedicated-counter method)
    bits  64..65  variant, 0b10
    bits  66..127 rand_b, 62 bits of randomness

Why v7 and not v4: §1 wants ids generated offline with no coordination, and v7's
leading timestamp makes them k-sortable, so a log file is roughly in insertion
order without an index.

**The counter is what makes this usable.** Two ids minted in the same millisecond
with only random tails would sort arbitrarily against each other, so an append-only
log could not use `id` as a tiebreak — which §3.3's precedence rule does. Using
rand_a as a per-millisecond counter makes successive ids *strictly* increasing as
128-bit integers, which `test_ids.py` asserts.

A clock that steps backwards cannot be allowed to break that, so the generator keeps
its own monotonic floor and carries the counter forward rather than re-issuing a
lower timestamp. Ids are then still unique and still ordered; they are just briefly
ahead of the wall clock, which matters far less than a log that cannot be ordered.

**Ordering ids is not ordering measurements.** §1: observation ids are minted by the
gateway at ingest, so a reading that spent three days in a node's buffer gets a
*later* id than readings taken after it. Sorting observations by id is a spec
violation; `project.order_observations` is the right thing. `uuid7_time()` exists for
debugging and audit, never for `measured_at`.
"""
from __future__ import annotations

import secrets
import threading
import time
import uuid

_COUNTER_BITS = 12
_COUNTER_MAX = (1 << _COUNTER_BITS) - 1   # 4095 ids per millisecond, then borrow
_RAND_B_BITS = 62


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


class Uuid7Generator:
    """Thread-safe, strictly monotonic UUIDv7 source.

    `clock` and `rng` are injectable so tests can pin both; production uses the
    system clock and `secrets`.
    """

    __slots__ = ("_clock", "_rand", "_floor_ms", "_counter", "_lock")

    def __init__(self, *, clock=_wall_ms, rng=None):
        self._clock = clock
        self._rand = (rng or secrets.SystemRandom()).getrandbits
        self._floor_ms = -1
        self._counter = 0
        self._lock = threading.Lock()

    def __call__(self) -> uuid.UUID:
        with self._lock:
            ms, counter = self._tick()
            rand_b = self._rand(_RAND_B_BITS)
        return _assemble(ms, counter, rand_b)

    def _tick(self) -> tuple[int, int]:
        """Advance the (millisecond, counter) pair. Caller holds the lock."""
        now = self._clock()
        if now > self._floor_ms:
            self._floor_ms, self._counter = now, 0
            return self._floor_ms, self._counter
        # Same millisecond, or a clock that went backwards: hold the floor and
        # count. Either way the result is strictly greater than the last one.
        self._counter += 1
        if self._counter > _COUNTER_MAX:
            self._floor_ms += 1
            self._counter = 0
        return self._floor_ms, self._counter


def _assemble(ms: int, counter: int, rand_b: int) -> uuid.UUID:
    if not 0 <= ms < (1 << 48):
        raise ValueError(f"timestamp out of range for UUIDv7: {ms}")
    if not 0 <= counter <= _COUNTER_MAX:
        raise ValueError(f"counter out of range: {counter}")
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6] = 0x70 | ((counter >> 8) & 0x0F)        # version 7 + counter high nibble
    b[7] = counter & 0xFF
    b[8] = 0x80 | ((rand_b >> 56) & 0x3F)        # variant 0b10 + 6 random bits
    b[9:16] = (rand_b & ((1 << 56) - 1)).to_bytes(7, "big")
    return uuid.UUID(bytes=bytes(b))


_default = Uuid7Generator()


def uuid7() -> uuid.UUID:
    """A new UUIDv7 from the process-wide generator."""
    return _default()


def uuid7_time(u: uuid.UUID) -> int:
    """The embedded Unix timestamp in milliseconds.

    For audit and debugging only. This is when the id was *minted* — for an
    observation, ingest time, never `measured_at` (§1).
    """
    if not is_uuid7(u):
        raise ValueError(f"not a UUIDv7: {u}")
    return int.from_bytes(u.bytes[0:6], "big")


def is_uuid7(u: uuid.UUID) -> bool:
    return u.version == 7 and u.variant == uuid.RFC_4122
