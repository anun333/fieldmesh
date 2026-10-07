#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Injectable sensor faults (docs/VIRTUAL_FARM.md step 4).

The producer half. `physics.py` says what is true; this corrupts what the *sensor*
reports about it, which is the only honest place to put a sensor fault — the soil did
not change because a probe went bad.

Each fault knows when it began and what it is doing, so a drill can score a detector
against ground truth instead of against a hand-written fixture. `Sensor.injected()`
is that ground truth, and nothing in `sdk/checks.py` can see it.

What is deliberately *not* here: clock skew. §2 has nodes report **ages** rather than
timestamps, and a node computes an age from its own clock at both ends, so a constant
offset cancels exactly. A node whose clock is six hours wrong still produces a correct
`measured_at`, and `test_faults.py` demonstrates that rather than asserting it. Only
clock *drift* across the buffer dwell survives the subtraction, and over the minutes
or hours a reading actually waits it is far below the uncertainty the node already
declares. That is not an accident; it is why §2 is built on ages.

What *does* corrupt times is stamping the age at sample time instead of transmit time,
which §2 forbids and which a driver is most likely to get wrong. That is modelled as a
deliberate node misbehaviour so the damage can be shown — see `Node.stamp_at_sample`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class Fault:
    """Base: a sensor misbehaviour that starts at a moment and then persists."""

    begins_at_s: float = 0.0
    kind: str = "fault"

    def active(self, at_s: float) -> bool:
        return at_s >= self.begins_at_s

    def apply(self, value: float, at_s: float) -> float | None:
        raise NotImplementedError

    def describe(self) -> str:
        return self.kind


@dataclass
class Drifting(Fault):
    """A probe whose reading wanders away from truth at a steady rate.

    The commonest real failure and the hardest to catch: every individual reading
    is plausible, the series looks healthy, and only the comparison with a
    reference or a neighbour reveals it. §4.2's cross-check is the detector that
    has a chance here; range only catches it once it has gone far enough to be
    absurd.
    """

    kind: str = "drift"
    per_day: float = 0.0        # in the sensor's reported units

    def apply(self, value, at_s):
        if not self.active(at_s):
            return value
        days = (at_s - self.begins_at_s) / 86400.0
        return value + self.per_day * days

    def describe(self) -> str:
        return f"drift {self.per_day:+g}/day from {self.begins_at_s:.0f}"


@dataclass
class Sticking(Fault):
    """A probe that freezes on its last reading: a full bucket, a dead ADC.

    What flatline is for — provided the threshold clears the quantisation dwell,
    which §4.2 now requires precisely because the virtual farm flagged a healthy
    probe before it did.
    """

    kind: str = "stuck"
    _frozen: float | None = field(default=None, repr=False)

    def apply(self, value, at_s):
        if not self.active(at_s):
            self._frozen = value
            return value
        if self._frozen is None:
            self._frozen = value
        return self._frozen

    def describe(self) -> str:
        return f"stuck from {self.begins_at_s:.0f}"


@dataclass
class Biased(Fault):
    """A constant offset: a probe installed at the wrong depth, a miscalibration.

    Invisible to every check in §4.2 that looks at one series, which is the point
    of including it — a detector that claims to catch this is lying, and a drill
    should score that honestly.
    """

    kind: str = "bias"
    offset: float = 0.0

    def apply(self, value, at_s):
        return value + self.offset if self.active(at_s) else value

    def describe(self) -> str:
        return f"bias {self.offset:+g} from {self.begins_at_s:.0f}"


@dataclass
class Noisy(Fault):
    """Electrical noise: a loose connection, a failing supply."""

    kind: str = "noise"
    sigma: float = 0.0
    seed: int = 1
    _rng: random.Random = field(default=None, repr=False)

    def apply(self, value, at_s):
        if not self.active(at_s):
            return value
        if self._rng is None:
            self._rng = random.Random(self.seed)
        return value + self._rng.gauss(0.0, self.sigma)

    def describe(self) -> str:
        return f"noise sigma={self.sigma:g} from {self.begins_at_s:.0f}"


@dataclass
class Dead(Fault):
    """A sensor that stops answering. Produces absence, not a wrong value.

    §4.2 is explicit that this is *not* a reading-level flag: the series goes stale,
    which is a datastream state, and the absence is already recorded as a gap. A
    dead sensor should produce no observations at all and no quality assertions
    about readings that do not exist.
    """

    kind: str = "dead"

    def apply(self, value, at_s):
        return None if self.active(at_s) else value

    def describe(self) -> str:
        return f"dead from {self.begins_at_s:.0f}"


@dataclass
class OutOfRange(Fault):
    """A reading beyond what the physical quantity can be — a disconnected probe
    reading its rail voltage, say. The easiest fault to catch, included so a drill
    has a positive control."""

    kind: str = "out_of_range"
    value: float = 0.0

    def apply(self, value, at_s):
        return self.value if self.active(at_s) else value

    def describe(self) -> str:
        return f"reads {self.value:g} from {self.begins_at_s:.0f}"


class Sensor:
    """A reader, a resolution, and zero or more faults.

    `read` takes ground truth and returns the true physical value; `resolution` is
    the step the sensor reports in, so quantisation is modelled rather than assumed
    away — it is what made a healthy probe look flatlined (§4.2).
    """

    __slots__ = ("read", "scale", "faults", "name")

    def __init__(self, read, *, scale: float = 1000.0, faults=(), name: str = ""):
        self.read = read
        #: Wire units per physical unit. A soil probe reporting 0.001 steps has a
        #: scale of 1000 and sends integers (§5.1: the node applies nothing).
        self.scale = scale
        self.faults = list(faults)
        self.name = name

    def __call__(self, truth):
        value = self.read(truth)
        if value is None:
            return None
        at_s = truth.when.timestamp()
        for fault in self.faults:
            value = fault.apply(value, at_s)
            if value is None:
                return None
        return int(round(value * self.scale))

    def inject(self, fault: Fault) -> Fault:
        self.faults.append(fault)
        return fault

    def injected(self, at_s: float | None = None) -> list[str]:
        """Ground truth for scoring: what is actually wrong, in words.

        Nothing in `sdk/checks.py` can reach this. That is the producer/detector
        separation, and it is what makes a score honest.
        """
        return [f.describe() for f in self.faults
                if at_s is None or f.active(at_s)]

    @property
    def faulty(self) -> bool:
        return bool(self.faults)


__all__ = ["Sensor", "Fault", "Drifting", "Sticking", "Biased", "Noisy", "Dead",
           "OutOfRange"]
