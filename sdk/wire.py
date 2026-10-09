#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The wire message (spec v0.1 §5.2, §5.3).

CBOR packed arrays with a CDDL schema, decided on measurement — see
docs/notes/q5-encoding-measurement.md. Positional, so the schema is load-bearing
rather than decorative: nothing here is self-describing, and that is the point.

    message = [
      version   : uint,        ; format version, in every packet (§12)
      node      : uint / null, ; null where the link identifies the device
      boot      : uint,        ; cold-start counter, non-volatile (§1)
      seq       : uint,        ; uint16, resets per boot, wraps (§1)
      base-age  : uint,        ; seconds before TRANSMIT, not before sampling (§2)
      dropped   : uint,        ; readings evicted since the last message (§5.3)
      readings  : [+ (channel: uint, age-delta: uint, value: int / aggregate)]
    ]
    aggregate = [n: uint, min: int, max: int, unchanged: uint]   ; Q20

An aggregate is a window's summary from a node that samples often and reports seldom
(Q20): how many samples, their extremes, and how long the value has been unchanged —
enough for the gateway's range and flatline checks at the sampling resolution while
paying the airtime of the reporting one. Its age is the window's end.

`node` is a slot holding null rather than an omitted field, because positional
decoding of an optional head is ambiguous and one byte is a cheap price for a
decoder that cannot misread a frame. Omitting it entirely would save four.

Three things this deliberately does not do:

**It does not scale values.** §5.1 says the node applies nothing and §3.2 says the
raw datastream holds exactly what the node sent, so a soil probe's 231 arrives as
231 and becomes 0.231 in the *derived* series, through a calibration whose
coefficients include the wire scale. That keeps "raw is what the node sent"
literally true and keeps the derivation reproducible from
`(raw value, calibration, driver version)`.

**It does not fix the batch size.** `pack` takes `max_payload` and fits what it
can, because §5.2 forbids sizing a batch at build time: LoRaWAN MAC commands
piggyback in `FOpts` and shrink the available `FRMPayload`, and ADR moves the data
rate under a running node.

**It does not timestamp.** The node has no trustworthy clock (that is the premise
of §2), so it reports ages and the gateway computes times. `base_age` is stamped at
transmit — a message that sat three days in a buffer must have its age recomputed
as it leaves, or `measured_at` is wrong by the dwell time.
"""
from __future__ import annotations

from dataclasses import dataclass

import cbor2

VERSION = 1

#: The normative schema. Kept here as text so the spec, the encoder and the
#: conformance suite cannot drift apart silently.
CDDL = """\
message = [
  version:  uint,
  node:     uint / null,
  boot:     uint,
  seq:      uint,
  base-age: uint,
  dropped:  uint,
  readings: [+ reading-triple]
]
reading-triple = (channel: uint, age-delta: uint, value: int / aggregate)
aggregate = [n: uint, min: int, max: int, unchanged: uint]
"""


class WireError(Exception):
    """A frame that cannot be trusted. Never guessed at."""


@dataclass(frozen=True, slots=True)
class Reading:
    channel: int
    age_delta: int      # seconds before `base_age`
    #: Exactly as the node sampled it — or, on an aggregate channel, `(n, min, max,
    #: unchanged_s)` for the window ending at this age (Q20).
    value: int | tuple

    def __post_init__(self) -> None:
        if not 0 <= self.channel <= 0xFF:
            raise WireError("channel is one byte (§1)")
        if self.age_delta < 0:
            raise WireError("age_delta counts backwards from base_age; not negative")
        if isinstance(self.value, (list, tuple)):
            v = tuple(self.value)
            if len(v) != 4 or not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
                raise WireError("an aggregate is four integers: n, min, max, unchanged (Q20)")
            n, lo, hi, unchanged = v
            if n < 1 or lo > hi or unchanged < 0:
                raise WireError("an aggregate needs n >= 1, min <= max, unchanged >= 0")
            object.__setattr__(self, "value", v)
        elif not isinstance(self.value, int) or isinstance(self.value, bool):
            raise WireError("a reading's value is an integer or an aggregate")

    @property
    def is_aggregate(self) -> bool:
        return isinstance(self.value, tuple)


@dataclass(frozen=True, slots=True)
class Message:
    boot: int
    seq: int
    base_age: int
    readings: tuple = ()
    node: int | None = None
    dropped: int = 0
    version: int = VERSION

    def __post_init__(self) -> None:
        if not 0 <= self.seq <= 0xFFFF:
            raise WireError("seq is uint16 (§1)")
        if self.boot < 0:
            raise WireError("boot must not be negative (§1)")
        if self.base_age < 0:
            raise WireError("base_age must not be negative")
        if self.dropped < 0:
            raise WireError("dropped must not be negative")
        if not self.readings:
            raise WireError("a message carries at least one reading")
        object.__setattr__(self, "readings", tuple(self.readings))

    def age_of(self, reading: Reading) -> int:
        """Seconds between this reading and the transmit instant (§2)."""
        return self.base_age + reading.age_delta


def encode(message: Message) -> bytes:
    flat = []
    for r in message.readings:
        flat += [r.channel, r.age_delta, list(r.value) if r.is_aggregate else r.value]
    return cbor2.dumps([message.version, message.node, message.boot, message.seq,
                        message.base_age, message.dropped, flat])


def decode(payload: bytes) -> Message:
    """Parse a frame, or raise. A frame that does not parse is a gap, never a guess."""
    try:
        doc = cbor2.loads(payload)
    except Exception as exc:                       # noqa: BLE001 - any codec error
        raise WireError(f"not CBOR: {exc}") from exc
    if doc is getattr(cbor2, "break_marker", object()):
        # A break code outside an indefinite-length item is not a data item (RFC 8949
        # §3.2.1). cbor2 6 refuses it; cbor2 5 returned a sentinel. Refusing it here
        # makes the answer the same whichever version is installed — the first CI run,
        # on a newer cbor2 than this machine's, is how the difference was found.
        raise WireError("not CBOR: a lone break code is not a data item")
    if not isinstance(doc, list) or len(doc) != 7:
        raise WireError(f"expected 7 fields, got {type(doc).__name__} "
                        f"of length {len(doc) if isinstance(doc, list) else '?'}")
    version, node, boot, seq, base_age, dropped, flat = doc
    if version != VERSION:
        # §12: the version is in every packet precisely so this is a clean refusal
        # rather than a misparse.
        raise WireError(f"unsupported wire version {version!r} (this build speaks "
                        f"{VERSION})")
    if not isinstance(flat, list) or not flat or len(flat) % 3:
        raise WireError("readings must be a non-empty flat triple list")
    try:
        readings = tuple(Reading(flat[i], flat[i + 1], flat[i + 2])
                         for i in range(0, len(flat), 3))
    except TypeError as exc:
        raise WireError(f"malformed reading: {exc}") from exc
    return Message(boot=boot, seq=seq, base_age=base_age, readings=readings,
                   node=node, dropped=dropped, version=version)


def pack(readings, *, boot: int, seq: int, base_age: int, max_payload: int,
         node: int | None = None, dropped: int = 0) -> tuple[bytes, int]:
    """Encode as many readings as fit `max_payload`.

    Returns `(payload, packed_count)`. The caller keeps the remainder buffered and
    sends it next (§5.3), so a shrinking payload budget costs latency rather than
    data.

    Grows the batch one reading at a time rather than estimating, because CBOR
    integer widths change with magnitude and an estimate that is wrong by one byte
    is a dropped frame.
    """
    readings = list(readings)
    if not readings:
        raise WireError("nothing to pack")
    best: bytes | None = None
    count = 0
    for n in range(1, len(readings) + 1):
        candidate = encode(Message(boot=boot, seq=seq, base_age=base_age,
                                   readings=readings[:n], node=node,
                                   dropped=dropped))
        if len(candidate) > max_payload:
            break
        best, count = candidate, n
    if best is None:
        raise WireError(
            f"a single reading does not fit {max_payload} B — the link's payload "
            f"budget is too small for this format, which is a link-driver "
            f"configuration error, not a runtime condition")
    return best, count


class Window:
    """What a node keeps between reports to send an aggregate (Q20) — the reference
    for firmware, and what the tests hold the gateway to.

        w = Window()
        w.add(281, t)          # every sample, as taken
        n, lo, hi, unchanged = w.close()   # at each report

    `unchanged` is how long the current value has stood, from the first sample that
    had it to the latest, and it is **carried across windows**: a probe frozen since
    yesterday reports a day in this morning's first window, which is what lets the
    gateway see a flatline at the sampling resolution without the samples. The count
    and the extremes restart each window.
    """

    def __init__(self) -> None:
        self.n, self.lo, self.hi = 0, None, None
        self.value, self.since, self.latest = None, None, None

    def add(self, value: int, t_s: float) -> None:
        self.n += 1
        self.lo = value if self.lo is None else min(self.lo, value)
        self.hi = value if self.hi is None else max(self.hi, value)
        if value != self.value:
            self.value, self.since = value, t_s
        self.latest = t_s

    def close(self) -> tuple[int, int, int, int]:
        if not self.n:
            raise WireError("an empty window has nothing to report")
        out = (self.n, self.lo, self.hi, int(self.latest - self.since))
        self.n, self.lo, self.hi = 0, None, None
        return out


def restamp(readings, *, now_s: float, sampled_at_s) -> tuple[int, list]:
    """Recompute ages at transmit time (§2).

    `sampled_at_s` are the node-local monotonic times the readings were taken.
    Returns `(base_age, readings_with_fresh_deltas)`. A node draining a buffer MUST
    call this as each message leaves; stamping at sample time and then buffering
    for three days yields a `measured_at` wrong by the dwell time, which is the
    easiest way to corrupt a dataset silently.
    """
    readings = list(readings)
    if len(readings) != len(sampled_at_s):
        raise WireError("one sample time per reading")
    ages = [now_s - t for t in sampled_at_s]
    if any(a < 0 for a in ages):
        raise WireError("a reading cannot be sampled in the future")
    base = int(min(ages))
    out = [Reading(r.channel, int(a) - base, r.value)
           for r, a in zip(readings, ages)]
    return base, out
