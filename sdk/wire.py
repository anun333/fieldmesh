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
      readings  : [+ (channel: uint, age-delta: uint, value: int)]
    ]

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
reading-triple = (channel: uint, age-delta: uint, value: int)
"""


class WireError(Exception):
    """A frame that cannot be trusted. Never guessed at."""


@dataclass(frozen=True, slots=True)
class Reading:
    channel: int
    age_delta: int      # seconds before `base_age`
    value: int          # exactly as the node sampled it

    def __post_init__(self) -> None:
        if not 0 <= self.channel <= 0xFF:
            raise WireError("channel is one byte (§1)")
        if self.age_delta < 0:
            raise WireError("age_delta counts backwards from base_age; not negative")


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
        flat += [r.channel, r.age_delta, r.value]
    return cbor2.dumps([message.version, message.node, message.boot, message.seq,
                        message.base_age, message.dropped, flat])


def decode(payload: bytes) -> Message:
    """Parse a frame, or raise. A frame that does not parse is a gap, never a guess."""
    try:
        doc = cbor2.loads(payload)
    except Exception as exc:                       # noqa: BLE001 - any codec error
        raise WireError(f"not CBOR: {exc}") from exc
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
    readings = tuple(Reading(flat[i], flat[i + 1], flat[i + 2])
                     for i in range(0, len(flat), 3))
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
