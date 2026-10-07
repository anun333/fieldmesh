#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Derived state (spec v0.1 §2, §3.2, §3.3, §4.2, §7.1).

§7.1: current state is derived from the log. This module is that derivation, kept
separate and testable, so "the log is authoritative" is a property you can check
rather than a claim in a document.

Four rules live here, each of which the spec states precisely because two
implementations could otherwise disagree:

* **Live observations** (§3.2) — superseded rows stay in the log forever, and
  exactly one live row exists per `(datastream, measured_at)`. Recalibration
  appends; nothing is overwritten. The uniqueness invariant is *checked*, not
  assumed, because the failure mode it prevents is two observations at one
  `phenomenonTime` breaking every SensorThings client.
* **Live quality assertion** (§3.3) — the non-superseded assertion with the
  highest precedence, a person outranking the foundation, ties broken by
  `asserted_at` then `id`. The id tiebreak is why `ids.py` guarantees strict
  monotonicity.
* **Calibration by `measured_at`** (§3.2) — never by ingest time. A reading that
  spent three days in a buffer gets the coefficients that were in force when it
  was taken.
* **Staleness** (§4.2) — a datastream state, never a flag on a reading.

Ordering (§2) is here too, and it is the subtle one: within a node `(boot, seq)`
beats `measured_at`, because a node's own counter is reliable when its clock is
not; across nodes, observations whose uncertainty intervals overlap are genuinely
*unordered* and `concurrent()` is how you ask.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID

from model import (Calibration, Datastream, DatastreamKind,
                   Observation, QualityAssertion, Threshold, Usable)

STALENESS_FACTOR = 3.0   # §4.2: "no reading for 3x the expected interval"


class ProjectionError(Exception):
    """A spec invariant the log's contents violate."""


class Health(str, Enum):
    OK = "ok"
    STALE = "stale"
    UNKNOWN = "unknown"      # no expected_interval declared, or no readings yet


# ------------------------------------------------------------- supersession

def _superseded_ids(records) -> set[UUID]:
    return {r.supersedes for r in records if r.supersedes is not None}


def live(records) -> list:
    """The records nothing supersedes.

    Chains resolve for free: with A←B←C only C survives, because both A and B are
    named by something. No recursion, no cycle risk.
    """
    records = list(records)
    dead = _superseded_ids(records)
    return [r for r in records if r.id not in dead]


def live_observations(observations, *, strict: bool = True) -> dict:
    """Live observations keyed by `(datastream, measured_at)` (§3.2).

    With `strict`, two live rows at one key raise — that is the invariant that
    keeps a SensorThings client from seeing two observations at one
    `phenomenonTime`. Pass `strict=False` to inspect a log you already know is
    broken; the newer `id` wins so the result is at least deterministic.
    """
    out: dict[tuple[UUID, _dt.datetime], Observation] = {}
    for obs in live(observations):
        key = (obs.datastream, obs.measured_at)
        clash = out.get(key)
        if clash is None:
            out[key] = obs
            continue
        if strict:
            raise ProjectionError(
                f"two live observations for datastream {obs.datastream} at "
                f"{obs.measured_at.isoformat()} ({clash.id} and {obs.id}) — §3.2 "
                f"allows exactly one; a re-derivation must carry `supersedes`")
        out[key] = max(clash, obs, key=lambda o: o.id.int)
    return out


def live_assertion(assertions, observation_id: UUID | None = None):
    """The one assertion that counts, per §3.3 precedence, or None.

    Several non-superseded assertions for one observation is normal and expected:
    the foundation's machine verdict and a person's override coexist, and the
    person wins while the original stays readable.
    """
    candidates = [a for a in live(assertions)
                  if observation_id is None or a.observation == observation_id]
    if not candidates:
        return None
    return max(candidates, key=lambda a: (a.precedence, a.asserted_at, a.id.int))


def usable_of(assertions, observation_id: UUID) -> Usable:
    """The usability an app should read. No assertion yet means no objection."""
    found = live_assertion(assertions, observation_id)
    return found.usable if found is not None else Usable.GOOD


# ------------------------------------------------------------- calibration

def calibration_for(calibrations, sensor: UUID, measured_at: _dt.datetime):
    """The calibration in force for `sensor` when the reading was taken (§3.2).

    Selected by `measured_at`, never by ingest time — applying whatever is current
    at ingest silently gives wrong coefficients to everything that arrived late
    from a buffer, which is an *Honest data* violation produced entirely by an
    unstated default.

    Overlapping intervals are a data error, not something to resolve quietly, so
    the latest `valid_from` wins and the overlap is reported by
    `overlapping_calibrations`.
    """
    matches = [c for c in calibrations
               if c.sensor == sensor and c.covers(measured_at)]
    if not matches:
        return None
    return max(matches, key=lambda c: (c.valid_from, c.id.int))


def overlapping_calibrations(calibrations, sensor: UUID) -> list[tuple]:
    """Pairs of calibrations for one sensor whose validity intervals overlap."""
    cals = sorted((c for c in calibrations if c.sensor == sensor),
                  key=lambda c: c.valid_from)
    clashes = []
    for i, a in enumerate(cals):
        for b in cals[i + 1:]:
            a_end = a.valid_to
            if a_end is None or b.valid_from < a_end:
                clashes.append((a, b))
    return clashes


class CalibrationError(Exception):
    """A calibration that cannot be applied. Never approximated."""


def apply_calibration(raw_value, calibration: Calibration):
    """Compute a derived result from a raw one (§3.2).

    §3.2 requires the derivation be reproducible from
    `(raw value, calibration record, driver version)` alone, so the method is
    named in the record and only known methods are honoured. An unknown method
    **raises** rather than falling back to identity: a silent passthrough would
    publish an uncalibrated number in a calibrated series, which is exactly the
    silent cleaning the spec exists to prevent.

    The wire scale lives here too. §5.1 says the node applies nothing and §3.2
    says raw is exactly what the node sent, so a probe's `231` stays `231` in the
    raw series and becomes `0.231` here, through coefficients that carry the
    scale. Recalibrating changes those coefficients and supersedes the derived
    rows; the raw series never moves.
    """
    method = (calibration.method or "").strip().lower()
    coefficients = calibration.coefficients or {}
    if method in ("identity", "none", "passthrough"):
        return raw_value
    if method in ("linear", "two-point", "two_point"):
        if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
            raise CalibrationError(
                f"linear calibration needs a number, got {type(raw_value).__name__}")
        try:
            a = float(coefficients["a"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CalibrationError(
                f"calibration {calibration.id} declares method {method!r} but has "
                f"no usable coefficient 'a'") from exc
        b = float(coefficients.get("b", 0.0))
        return a * raw_value + b
    if method in ("polynomial", "poly"):
        coeffs = coefficients.get("c")
        if not isinstance(coeffs, (list, tuple)) or not coeffs:
            raise CalibrationError(
                f"calibration {calibration.id} declares {method!r} but has no "
                f"coefficient list 'c'")
        return sum(float(c) * raw_value ** i for i, c in enumerate(coeffs))
    raise CalibrationError(
        f"calibration {calibration.id} declares unknown method {method!r}; "
        f"refusing to guess, because a silent passthrough would put an "
        f"uncalibrated value in a calibrated series (§3.2)")


# ---------------------------------------------------------------- ordering

def precedes(a: Observation, b: Observation) -> bool:
    """True if `a` is strictly before `b` under §2.

    Within one node `(boot, seq)` decides, because the counter is trustworthy even
    when the clock is not. Across nodes `measured_at` decides, unless the
    uncertainty intervals overlap — then neither precedes the other and the honest
    answer is "unordered".
    """
    same_node = a.node is not None and a.node == b.node
    if same_node and a.node_order is not None and b.node_order is not None:
        return a.node_order < b.node_order
    a_lo, a_hi = a.interval()
    b_lo, b_hi = b.interval()
    return a_hi <= b_lo


def concurrent(a: Observation, b: Observation) -> bool:
    """True when §2 gives no ordering: neither precedes the other."""
    return not precedes(a, b) and not precedes(b, a)


def order_observations(observations) -> list:
    """A deterministic listing for display and export.

    A stable total order is not a claim that every pair is really ordered —
    §2 says overlapping-uncertainty pairs are not. Ask `concurrent()` when it
    matters; this exists so two implementations print the same list.
    """
    return sorted(
        observations,
        key=lambda o: (o.node or "", o.node_order or (-1, -1),
                       o.measured_at, o.id.int),
    )


# ---------------------------------------------------------------- staleness

def datastream_health(datastream: Datastream,
                      last_measured_at: _dt.datetime | None,
                      now: _dt.datetime,
                      *, factor: float = STALENESS_FACTOR) -> Health:
    """Current health of a series (§4.2).

    Staleness is a property of the datastream at a moment, not of any observation.
    Flagging the last good reading would mean reaching back and mutating a record
    that was correct when written, because a *later* reading never arrived — an
    append-only violation that also destroys the meaning of the value. The absence
    itself is already recorded honestly as a gap (§5.4).
    """
    if datastream.expected_interval is None or last_measured_at is None:
        return Health.UNKNOWN
    deadline = last_measured_at + _dt.timedelta(
        seconds=datastream.expected_interval * factor)
    return Health.OK if now <= deadline else Health.STALE


# ------------------------------------------------------------------- state

@dataclass(slots=True)
class State:
    """Current state, derived from the log (§7.1).

    Built by replaying records in log order; holds the full history as well, so
    `live_*` can be recomputed and a superseded row stays inspectable.
    """

    datastreams: dict = field(default_factory=dict)
    calibrations: dict = field(default_factory=dict)
    thresholds: dict = field(default_factory=dict)
    observations: list = field(default_factory=list)
    assertions: list = field(default_factory=list)

    def live_observations(self, *, strict: bool = True) -> dict:
        return live_observations(self.observations, strict=strict)

    def usable_of(self, observation_id: UUID) -> Usable:
        return usable_of(self.assertions, observation_id)

    def calibration_for(self, sensor: UUID, measured_at: _dt.datetime):
        return calibration_for(self.calibrations.values(), sensor, measured_at)

    def health_of(self, datastream_id: UUID, now: _dt.datetime) -> Health:
        ds = self.datastreams[datastream_id]
        stamps = [o.measured_at for o in self.observations
                  if o.datastream == datastream_id]
        return datastream_health(ds, max(stamps) if stamps else None, now)

    def add(self, record) -> None:
        """Fold one record into the current state.

        Same dispatch as `state_from_log`, so a gateway that appends and folds
        ends up with exactly what a replay would produce. Records keyed by id are
        replaced; observations and assertions accumulate, because supersession
        rather than replacement is how they change (§3.2, §3.3).
        """
        slot = _DISPATCH.get(type(record))
        if slot is None:
            return
        attr, keyed = slot
        if keyed:
            getattr(self, attr)[record.id] = record
        else:
            getattr(self, attr).append(record)

    def derived_of(self, raw_datastream_id: UUID):
        """The derived datastream computed from this raw one, if there is one (§3.2)."""
        for ds in self.datastreams.values():
            if ds.kind is DatastreamKind.DERIVED and ds.derived_from == raw_datastream_id:
                return ds
        return None

    def validate(self) -> list[str]:
        """Every spec violation the state can see. Empty list means clean.

        Reports rather than raises, so a conformance run can show all of them at
        once instead of one per fix.
        """
        problems: list[str] = []
        try:
            self.live_observations(strict=True)
        except ProjectionError as exc:
            problems.append(str(exc))
        for obs in self.observations:
            ds = self.datastreams.get(obs.datastream)
            if ds is None:
                problems.append(f"observation {obs.id} references unknown "
                                f"datastream {obs.datastream}")
                continue
            try:
                obs.validate_against(ds)
            except ValueError as exc:
                problems.append(f"observation {obs.id}: {exc}")
        for ds in self.datastreams.values():
            if ds.kind is DatastreamKind.DERIVED and ds.derived_from not in self.datastreams:
                problems.append(f"datastream {ds.id} derives from unknown "
                                f"{ds.derived_from}")
        seen_sensors = {c.sensor for c in self.calibrations.values()}
        for sensor in seen_sensors:
            for a, b in overlapping_calibrations(self.calibrations.values(), sensor):
                problems.append(f"calibrations {a.id} and {b.id} overlap for "
                                f"sensor {sensor}")
        return problems


_DISPATCH = {
    Datastream: ("datastreams", True),
    Calibration: ("calibrations", True),
    Threshold: ("thresholds", True),
    Observation: ("observations", False),
    QualityAssertion: ("assertions", False),
}


def state_from_log(log) -> State:
    """Replay a log into current state (§7.1).

    Records keyed by id are last-write-wins in log order, which is HLC order
    (§7.4) — the one place where "the latest version of this record" is decided.
    Observations and assertions accumulate instead, because supersession rather
    than replacement is how they change (§3.2, §3.3).
    """
    state = State()
    for record in log.records():
        slot = _DISPATCH.get(type(record))
        if slot is None:
            continue
        attr, keyed = slot
        if keyed:
            getattr(state, attr)[record.id] = record
        else:
            getattr(state, attr).append(record)
    return state
