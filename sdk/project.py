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
from bisect import bisect_right
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID

import vocab
from model import (Calibration, Datastream, DatastreamKind, Device,
                   Installation, Label, MaintenanceEvent, Observation,
                   QualityAssertion, Threshold, Usable)

STALENESS_FACTOR = 3.0   # §4.2: "no reading for 3x the expected interval"


class ProjectionError(Exception):
    """A spec invariant the log's contents violate."""


@dataclass(frozen=True, slots=True)
class DeviceView:
    """§4.1 assembled: the durable records plus what the readings say.

    Frozen and not a log record. Nothing writes this; `State.device_view` derives it,
    and it goes stale the moment another reading arrives — which is correct, because
    "last seen" is a fact about the world and not a field anybody should be able to
    edit.
    """

    device: Device
    installation: Installation | None
    installations: tuple
    datastreams: tuple
    last_seen: _dt.datetime | None
    last_measured_at: _dt.datetime | None
    boot: int | None
    maintenance: tuple
    calibrations: tuple

    @property
    def feature(self):
        """Where it is now, or None if it is not installed anywhere."""
        return self.installation.feature if self.installation else None

    @property
    def depth_m(self):
        return self.installation.depth_m if self.installation else None

    def last_action(self, action):
        """When this device was last cleaned, moved, replaced or recalibrated.

        The question a certifier asks, and the reason `action` is an enum rather than
        prose — "when was this probe last cleaned" cannot be answered by grepping
        notes.
        """
        matching = [m for m in self.maintenance if m.action is action]
        return matching[-1].at if matching else None


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


def later_issue(a: Observation, b: Observation) -> Observation:
    """Of two forecasts for one valid time, the live one: the later issue (Q26). Ties
    go to the later id, so any replay order gives the same answer."""
    return max(a, b, key=lambda o: (o.issued_at, o.id.int))


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
        if obs.issued_at is not None and clash.issued_at is not None:
            out[key] = later_issue(clash, obs)      # a forecast: the latest issue lives
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

def calibration_for(calibrations, sensor: UUID, measured_at: _dt.datetime,
                    datastream: UUID | None = None):
    """The calibration in force for `sensor` when the reading was taken (§3.2).

    Selected by `measured_at`, never by ingest time — applying whatever is current
    at ingest silently gives wrong coefficients to everything that arrived late
    from a buffer, which is an *Honest data* violation produced entirely by an
    unstated default.

    **And by channel.** A calibration that names this raw `datastream` beats one that
    covers the whole sensor, and one naming a *different* datastream never applies.
    Without that, a two-channel device's calibrations compete and the later one is
    applied to both — which is what happened the first time a soil probe reported
    temperature as well as moisture.

    Overlapping intervals within one scope are a data error, not something to
    resolve quietly, so the latest `valid_from` wins and the overlap is reported by
    `overlapping_calibrations`.
    """
    specific, general = [], []
    for c in calibrations:
        if c.sensor != sensor or not c.covers(measured_at):
            continue
        if c.datastream is None:
            general.append(c)
        elif c.datastream == datastream:
            specific.append(c)
    matches = specific or general
    if not matches:
        return None
    return max(matches, key=lambda c: (c.valid_from, c.id.int))


def overlapping_calibrations(calibrations, sensor: UUID,
                             datastream: UUID | None = None) -> list[tuple]:
    """Pairs of calibrations in one scope whose validity intervals overlap.

    The scope is the sensor *and* the datastream. Two calibrations on one TEROS-12 —
    one for moisture, one for temperature — are not an overlap; they convert
    different channels and never compete.
    """
    cals = sorted((c for c in calibrations
                   if c.sensor == sensor and c.datastream == datastream),
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


def _resolve(value: float, coefficients: dict) -> float:
    """Round to the calibration's declared output resolution, if it declares one."""
    decimals = coefficients.get("decimals")
    if decimals is None:
        return value
    try:
        places = int(decimals)
    except (TypeError, ValueError) as exc:
        raise CalibrationError(f"decimals must be an integer, got {decimals!r}") from exc
    if places < 0:
        raise CalibrationError("decimals must not be negative")
    return round(value, places)


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

    A calibration MAY declare `decimals`, the output resolution. `0.001 * 86` is
    exactly `0.08600000000000001` in IEEE 754 — correct, reproducible, and a claim
    of seventeen significant figures that no probe can support. Rounding to a
    declared resolution is not cleaning the data: it is declining to assert
    precision the instrument does not have, and because the resolution is part of
    the calibration record the derivation stays reproducible from
    `(raw value, calibration, driver version)` exactly as §3.2 requires. Omit it
    and nothing is rounded.
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
        return _resolve(a * raw_value + b, coefficients)
    if method in ("polynomial", "poly"):
        coeffs = coefficients.get("c")
        if not isinstance(coeffs, (list, tuple)) or not coeffs:
            raise CalibrationError(
                f"calibration {calibration.id} declares {method!r} but has no "
                f"coefficient list 'c'")
        return _resolve(sum(float(c) * raw_value ** i
                            for i, c in enumerate(coeffs)), coefficients)
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
    return sorted(observations, key=_display_key)


def _display_key(o):
    """The sort key for `order_observations`.

    A named function rather than an inline lambda because this is the second-hottest
    thing in a season — 5.7 million calls in one simulated week, 3.0 s of 31 s — and
    the cost is building the tuple, not comparing it: four attribute fetches, an
    `or`, and the `node_order` property, per observation per sort. Naming it makes
    that visible in a profile instead of showing up as `<lambda>`.

    `o.node` is a **string** (§1 — a node is named, not keyed by UUID), so `""` for a
    missing one is the correct neutral value and sorts it first. An earlier attempt at
    this optimisation keyed on `node.int`, which is right for a `UUID` and an
    `AttributeError` for a name; the tests caught it immediately. `o.id.int` is a
    genuine `UUID` and does want `.int`, because that skips `UUID.__lt__`.
    """
    return (o.node or "",
            o.node_order or (-1, -1),
            o.measured_at,
            o.id.int)


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

    The indexes are not an optimisation detail. §7.2 promises that years of
    readings never slow everyday records, and the first season-scale run broke that
    promise badly: rebuilding the live set on every quality check made ingest
    quadratic, and one simulated day of a five-node farm took a minute. These keep
    the same answers and make them cheap.
    """

    datastreams: dict = field(default_factory=dict)
    devices: dict = field(default_factory=dict)
    installations: dict = field(default_factory=dict)
    maintenance: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    calibrations: dict = field(default_factory=dict)
    thresholds: dict = field(default_factory=dict)
    observations: list = field(default_factory=list)
    assertions: list = field(default_factory=list)
    _by_datastream: dict = field(default_factory=dict, repr=False)
    _times_by_datastream: dict = field(default_factory=dict, repr=False)
    _superseded_obs: set = field(default_factory=set, repr=False)
    _by_observation: dict = field(default_factory=dict, repr=False)
    _superseded_assertions: set = field(default_factory=set, repr=False)
    _peer_streams: dict = field(default_factory=dict, repr=False)
    _maintenance_by_device: dict = field(default_factory=dict, repr=False)
    _labels_by_entity: dict = field(default_factory=dict, repr=False)
    #: Per datastream, observations kept in display order as they arrive, with their
    #: sort keys alongside: `datastream -> (keys, observations)`. See `ordered_upto`.
    _ordered: dict = field(default_factory=dict, repr=False)
    #: Per datastream, `(measured_at, observation)` in time order — for "the reading
    #: nearest this instant", which one check needs from a *different* series.
    _by_time: dict = field(default_factory=dict, repr=False)
    _superseded_labels: set = field(default_factory=set, repr=False)
    _streams_by_sensor: dict = field(default_factory=dict, repr=False)
    #: Per `(forecast datastream, valid time)`, the live issue. A later issue retires
    #: the earlier into `_superseded_obs` — no pointer in the data, so a run that
    #: arrives late, after a newer one, simply never becomes live (Q26).
    _forecast_live: dict = field(default_factory=dict, repr=False)   # ds -> {valid: obs}
    _forecast_keys: set = field(default_factory=set, repr=False)     # (ds, valid, issued)
    _last_issue: dict = field(default_factory=dict, repr=False)

    def observations_of(self, datastream_id: UUID) -> list:
        """Every observation on one series, in insertion order."""
        return self._by_datastream.get(datastream_id, [])

    def has_observation_at(self, datastream_id: UUID, measured_at) -> bool:
        """§3.2's uniqueness check, in constant time.

        Scanning the series for every arriving reading made ingest quadratic.
        """
        return measured_at in self._times_by_datastream.get(datastream_id, ())

    def ordered_upto(self, datastream_id: UUID, observation, limit: int | None):
        """Up to `limit` live readings ending at `observation`, in display order.

        What a health check needs: this reading and the ones before it. The version
        this replaces took the last `limit` readings *inserted*, sorted them, and
        searched the result for the reading — so every check paid for a sort, sixty
        million sort-key calls in a simulated seven weeks. It also judged a reading
        that arrived days late, after an outage, by whatever happened to have been
        inserted recently rather than by the readings truly before it. A window ending
        at the reading's own position gives it its real history, which is the offline
        case again.
        """
        keys, rows = self._ordered.get(datastream_id, ([], []))
        key = _display_key(observation)
        at = bisect_right(keys, key) - 1
        while at >= 0 and rows[at].id != observation.id:
            at -= 1
        if at < 0:
            return []
        out = []
        index = at
        while index >= 0 and (limit is None or len(out) < limit):
            row = rows[index]
            if row.id not in self._superseded_obs:
                out.append(row)
            index -= 1
        out.reverse()
        return out

    def following(self, datastream_id: UUID, observation, limit: int):
        """Up to `limit` live readings straight after `observation`, in display order.

        The mirror of `ordered_upto`, for the one check that needs the future: a spike
        is only a spike once the series has come back from it."""
        keys, rows = self._ordered.get(datastream_id, ([], []))
        key = _display_key(observation)
        at = bisect_right(keys, key) - 1
        while at >= 0 and rows[at].id != observation.id:
            at -= 1
        if at < 0:
            return []
        out = []
        index = at + 1
        while index < len(rows) and len(out) < limit:
            row = rows[index]
            if row.id not in self._superseded_obs:
                out.append(row)
            index += 1
        return out

    def nearest(self, datastream_id: UUID, when: _dt.datetime, within_s: float):
        """The live reading of a series closest to `when`, if one is within `within_s`.

        A binary search, so asking it once per reading costs nothing a season can feel —
        the reason it exists rather than a scan of the series.
        """
        times, rows = self._by_time.get(datastream_id, ([], []))
        at = bisect_right(times, when)
        best, best_gap = None, None
        for index in (at - 2, at - 1, at, at + 1):
            if 0 <= index < len(rows):
                row = rows[index]
                if row.id in self._superseded_obs:
                    continue
                gap = abs((row.measured_at - when).total_seconds())
                if gap <= within_s and (best_gap is None or gap < best_gap):
                    best, best_gap = row, gap
        return best

    def is_superseded(self, observation_id: UUID) -> bool:
        """Whether some later observation replaces this one (§3.2), in constant time.

        Public because the alternative was being written out by hand elsewhere as
        `any(o.supersedes == target for o in state.observations)` — correct, O(n) per
        question, and therefore O(n^2) across a recalibration that asks it about every
        row. One simulated fortnight spent **11 s of 34 s** inside that one generator,
        with 59 million UUID comparisons, re-deriving a set the projection had already
        built. An index nobody can reach is not an index.
        """
        return observation_id in self._superseded_obs

    def assertions_about(self, observation_id: UUID) -> list:
        return self._by_observation.get(observation_id, [])

    def live_observations(self, *, strict: bool = True) -> dict:
        out: dict = {}
        for obs in self.observations:
            if obs.id in self._superseded_obs:
                continue
            key = (obs.datastream, obs.measured_at)
            clash = out.get(key)
            if clash is None:
                out[key] = obs
                continue
            if strict:
                raise ProjectionError(
                    f"two live observations for datastream {obs.datastream} at "
                    f"{obs.measured_at.isoformat()} ({clash.id} and {obs.id}) — "
                    f"§3.2 allows exactly one; a re-derivation must carry "
                    f"`supersedes`")
            out[key] = max(clash, obs, key=lambda o: o.id.int)
        return out

    def live_observations_of(self, datastream_id: UUID,
                             tail: int | None = None) -> list:
        """The live rows of one series, which is what a health check needs.

        `tail` takes only the most recent rows *before* filtering, so a check that
        needs an hour of history does not pay for a season of it. Taken generously
        — supersession is rare, so a slice of the raw tail contains at least `tail`
        live rows in any realistic log.
        """
        rows = self._by_datastream.get(datastream_id, [])
        if tail is not None and len(rows) > tail:
            rows = rows[-tail:]
        if not self._superseded_obs:
            return list(rows)
        return [o for o in rows if o.id not in self._superseded_obs]

    def live_assertion_for(self, observation_id: UUID):
        candidates = [a for a in self.assertions_about(observation_id)
                      if a.id not in self._superseded_assertions]
        if not candidates:
            return None
        return max(candidates, key=lambda a: (a.precedence, a.asserted_at,
                                              a.id.int))

    def usable_of(self, observation_id: UUID) -> Usable:
        found = self.live_assertion_for(observation_id)
        return found.usable if found is not None else Usable.GOOD

    def calibration_for(self, sensor: UUID, measured_at: _dt.datetime,
                        datastream: UUID | None = None):
        return calibration_for(self.calibrations.values(), sensor, measured_at,
                               datastream)

    def health_of(self, datastream_id: UUID, now: _dt.datetime) -> Health:
        """A forecast's freshness is its latest issue: its newest `measured_at` is in
        the future, and would read as healthy long after the source went quiet."""
        ds = self.datastreams[datastream_id]
        if ds.kind is DatastreamKind.FORECAST:
            return datastream_health(ds, self._last_issue.get(datastream_id), now)
        stamps = [o.measured_at for o in self.observations
                  if o.datastream == datastream_id]
        return datastream_health(ds, max(stamps) if stamps else None, now)

    def latest_issue(self, datastream_id: UUID):
        """When a forecast datastream's newest run was issued, or None."""
        return self._last_issue.get(datastream_id)

    def forecast(self, datastream_id: UUID, start: _dt.datetime, end: _dt.datetime) -> list:
        """The live forecast between two valid times, in time order: for each hour,
        the latest issue that covered it."""
        hours = self._forecast_live.get(datastream_id, {})
        return [hours[at] for at in sorted(hours) if start <= at < end]

    def has_issue(self, datastream_id: UUID, valid_at: _dt.datetime, issued_at: _dt.datetime) -> bool:
        """Whether this run's value for this hour is already in the log — live or not."""
        return (datastream_id, valid_at, issued_at) in self._forecast_keys

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
            if attr == "datastreams":
                # A new or changed datastream can change who is comparable to whom,
                # so the cache below cannot outlive it. Datastreams arrive a few
                # dozen times in a season and observations hundreds of thousands of
                # times, which is what makes clearing the whole cache the right
                # trade rather than a careful partial invalidation.
                self._peer_streams.clear()
                self._streams_by_sensor.clear()
            return
        getattr(self, attr).append(record)
        if attr == "observations":
            self._by_datastream.setdefault(record.datastream, []).append(record)
            times, timed = self._by_time.setdefault(record.datastream, ([], []))
            if not times or record.measured_at >= times[-1]:
                times.append(record.measured_at)
                timed.append(record)
            else:
                at = bisect_right(times, record.measured_at)
                times.insert(at, record.measured_at)
                timed.insert(at, record)
            keys, rows = self._ordered.setdefault(record.datastream, ([], []))
            key = _display_key(record)
            # Nearly always an append — readings mostly arrive in order — and a late
            # one is a binary search plus one memmove, not a re-sort of the series.
            if not keys or key >= keys[-1]:
                keys.append(key)
                rows.append(record)
            else:
                at = bisect_right(keys, key)
                keys.insert(at, key)
                rows.insert(at, record)
            self._times_by_datastream.setdefault(
                record.datastream, set()).add(record.measured_at)
            if record.supersedes is not None:
                self._superseded_obs.add(record.supersedes)
            if record.issued_at is not None:
                hours = self._forecast_live.setdefault(record.datastream, {})
                self._forecast_keys.add((record.datastream, record.measured_at, record.issued_at))
                current = hours.get(record.measured_at)
                if current is None:
                    hours[record.measured_at] = record
                else:
                    winner = later_issue(current, record)
                    self._superseded_obs.add((record if winner is current else current).id)
                    hours[record.measured_at] = winner
                last = self._last_issue.get(record.datastream)
                if last is None or record.issued_at > last:
                    self._last_issue[record.datastream] = record.issued_at
        elif attr == "assertions":
            self._by_observation.setdefault(record.observation, []).append(record)
            if record.supersedes is not None:
                self._superseded_assertions.add(record.supersedes)
        elif attr == "maintenance":
            self._maintenance_by_device.setdefault(record.device, []).append(record)
        elif attr == "labels":
            self._labels_by_entity.setdefault(record.entity, []).append(record)
            if record.supersedes is not None:
                self._superseded_labels.add(record.supersedes)

    def comparable_datastreams(self, datastream_id: UUID) -> list:
        """Datastreams whose readings may be cross-checked against this one's (§4.2).

        Comparable means: a different datastream, a *different sensor*, and the same
        observed property, kind, unit and feature. Every one of those is load-bearing,
        and `kind` and `unit` most of all — a raw series carries whatever the node sent
        (`280`) and a derived series carries physical units (`0.280`), so comparing
        across them is a unit error that makes two healthy probes look like they
        violently disagree. Measured before that guard existed: a **99.8% false-alarm
        rate** on a farm with nothing wrong with it.

        Cached, because the answer depends only on the datastreams. Recomputing it per
        assessment meant scanning every datastream on the farm for every reading, with
        several `UUID` comparisons each — 2.5 s of a 31 s simulated week. The cache is
        cleared wholesale whenever a datastream is added or replaced, in `add`.
        """
        cached = self._peer_streams.get(datastream_id)
        if cached is not None:
            return cached
        own = self.datastreams.get(datastream_id)
        if own is None:
            return []
        peers = [ds for ds in self.datastreams.values()
                 if ds.id != own.id
                 and ds.sensor != own.sensor
                 and ds.observed_property == own.observed_property
                 and ds.kind is own.kind
                 and ds.unit == own.unit
                 and ds.feature == own.feature]
        self._peer_streams[datastream_id] = peers
        return peers

    # ------------------------------------------------------------- labels (§1)

    def label_for(self, entity: UUID, language: str = "en", *,
                  fallback: tuple[str, ...] = ("en",)):
        """The current name for an entity in `language`, or a fallback, or None.

        Returns the `Label` itself, so the caller can see `label.language` and know
        whether it got what it asked for. A UI asked for Spanish and silently handed
        English cannot mark the gap for a translator; one that can see the fallback can.

        A primary tag matches its regional variants in both directions — a request for
        `es` finds an `es-MX` name, and one for `es-MX` falls back to plain `es` —
        because a farm that labelled in Mexican Spanish should not appear untranslated
        to a Spanish-speaking visitor.
        """
        live = [label for label in self._labels_by_entity.get(entity, [])
                if label.id not in self._superseded_labels]
        if not live:
            return None
        for wanted in (language, *fallback):
            primary = wanted.split("-")[0]
            exact = [label for label in live if label.language == wanted]
            near = [label for label in live
                    if label.language.split("-")[0] == primary]
            for pool in (exact, near):
                if pool:
                    return max(pool, key=lambda label: (label.set_at, label.id.int))
        return None

    def label_as_of(self, entity: UUID, when: _dt.datetime, language: str = "en"):
        """What an entity was called at an instant — for reading an old report."""
        candidates = [label for label in self._labels_by_entity.get(entity, [])
                      if label.set_at <= when
                      and label.language.split("-")[0] == language.split("-")[0]]
        if not candidates:
            return None
        return max(candidates, key=lambda label: (label.set_at, label.id.int))

    def label_history(self, entity: UUID) -> list:
        """Every name an entity has had, oldest first, superseded ones included."""
        return sorted(self._labels_by_entity.get(entity, []),
                      key=lambda label: (label.set_at, label.id.int))

    def entities_named(self, name: str) -> list:
        """Every entity that has *ever* carried this name, in any language.

        The reason renames append rather than overwrite. A certifier's report from last
        spring says "north bed"; the bed has since become "tomato house"; this still
        finds it. Case and surrounding space are ignored, because the report was typed
        by a person.
        """
        wanted = name.strip().casefold()
        return sorted({label.entity for label in self.labels
                       if label.name.casefold() == wanted}, key=lambda u: u.int)

    def datastreams_of_sensor(self, device_id: UUID) -> list:
        """Every datastream this device feeds (§4.1).

        `Datastream.sensor` is the link, and it was a bare UUID with no record behind
        it until §4.1 existed — which is why a probe could be moved between beds with
        nothing recording that it had happened.

        Cached and cleared whenever a datastream changes, rather than maintained
        incrementally in `add`. The incremental version is where the bug lives: a
        datastream is keyed by id and last-write-wins, so re-appending one appends to
        the index a second time and the device appears to feed it twice.
        """
        if not self._streams_by_sensor:
            for ds in self.datastreams.values():
                self._streams_by_sensor.setdefault(ds.sensor, []).append(ds)
        return self._streams_by_sensor.get(device_id, [])

    def installation_of(self, device_id: UUID, when: _dt.datetime):
        """Where a device was at an instant (§4.1), or None.

        By `when`, for the same reason §3.2 selects calibration by `measured_at`: "how
        deep was this probe when it took that reading" is unanswerable from a field
        that gets overwritten on every move. Half-open intervals, so a move does not
        produce an instant that two installations both claim.
        """
        # `covers` validates the instant is UTC-aware, so there is no check here —
        # one validator, not two that could disagree.
        found = [i for i in self.installations.values()
                 if i.device == device_id and i.covers(when)]
        if not found:
            return None
        if len(found) > 1:
            raise ProjectionError(
                f"device {device_id} has {len(found)} overlapping installations at "
                f"{when.isoformat()} (§4.1)")
        return found[0]

    def installations_of(self, device_id: UUID) -> list:
        """Every installation of a device, oldest first — the siting history."""
        return sorted((i for i in self.installations.values()
                       if i.device == device_id),
                      key=lambda i: (i.installed_at, i.id.int))

    def maintenance_of(self, device_id: UUID) -> list:
        """The maintenance log for a device, oldest first (§4.1)."""
        return sorted(self._maintenance_by_device.get(device_id, []),
                      key=lambda m: (m.at, m.id.int))

    def calibrations_of(self, device_id: UUID) -> list:
        """A device's calibration history, oldest first (§4.1)."""
        return sorted((c for c in self.calibrations.values()
                       if c.sensor == device_id),
                      key=lambda c: (c.valid_from, c.id.int))

    def device_view(self, device_id: UUID, *, now: _dt.datetime | None = None):
        """§4.1's device record as the spec describes it — **derived, not stored.**

        Read literally, §4.1 says a device record holds "last seen, and the current
        boot counter". A record in an append-only log cannot hold *current* anything
        without being mutated, so those two come from the readings instead: they are
        observations about the device, not claims the device makes about itself. The
        durable half lives in `Device`, `Installation` and `MaintenanceEvent`; this
        assembles the view a person actually wants to look at.
        """
        device = self.devices.get(device_id)
        if device is None:
            raise KeyError(f"no device {device_id}")
        streams = self.datastreams_of_sensor(device_id)
        last = None
        for ds in streams:
            rows = self._by_datastream.get(ds.id, [])
            if rows and (last is None or rows[-1].received_at > last.received_at):
                last = rows[-1]
        # Falls back to the wall clock when the device has never reported, so a
        # device that is installed but silent still shows *where it is* rather than
        # appearing to be nowhere. "No readings" and "not installed" are different
        # facts and a view that conflated them would hide a dead sensor in a bed.
        at = now or (last.received_at if last
                     else _dt.datetime.now(tz=_dt.timezone.utc))
        return DeviceView(
            device=device,
            installation=(self.installation_of(device_id, at) if at else None),
            installations=tuple(self.installations_of(device_id)),
            datastreams=tuple(sorted(streams, key=lambda d: d.id.int)),
            last_seen=last.received_at if last else None,
            last_measured_at=last.measured_at if last else None,
            boot=last.boot if last else None,
            maintenance=tuple(self.maintenance_of(device_id)),
            calibrations=tuple(self.calibrations_of(device_id)),
        )

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
            for problem in vocab.check(ds.observed_property, ds.unit):
                problems.append(f"datastream {ds.id}: {problem}")
        for ds in self.datastreams.values():
            if ds.kind is DatastreamKind.DERIVED and ds.derived_from not in self.datastreams:
                problems.append(f"datastream {ds.id} derives from unknown "
                                f"{ds.derived_from}")
        scopes = {(c.sensor, c.datastream) for c in self.calibrations.values()}
        for sensor, datastream in scopes:
            for a, b in overlapping_calibrations(self.calibrations.values(), sensor,
                                                 datastream):
                where = f" datastream {datastream}" if datastream else ""
                problems.append(f"calibrations {a.id} and {b.id} overlap for "
                                f"sensor {sensor}{where}")
        # §4.1. Two installations covering one instant is the failure that makes
        # "how deep was this probe then" unanswerable, which is the whole reason the
        # record carries dates. Checked here rather than in `Installation.__post_init__`
        # because it needs every installation of the device, not one of them.
        by_device: dict = {}
        for installation in self.installations.values():
            if installation.device not in self.devices:
                problems.append(f"installation {installation.id} references unknown "
                                f"device {installation.device}")
            by_device.setdefault(installation.device, []).append(installation)
        for device, installations in by_device.items():
            ordered = sorted(installations, key=lambda i: (i.installed_at, i.id.int))
            for earlier, later in zip(ordered, ordered[1:]):
                if earlier.removed_at is None or later.installed_at < earlier.removed_at:
                    problems.append(
                        f"installations {earlier.id} and {later.id} overlap for "
                        f"device {device} (§4.1)")
        superseded = {label.id: label for label in self.labels}
        for label in self.labels:
            if label.supersedes is None:
                continue
            old = superseded.get(label.supersedes)
            if old is None:
                problems.append(f"label {label.id} supersedes unknown label "
                                f"{label.supersedes}")
            elif old.entity != label.entity:
                problems.append(f"label {label.id} supersedes a label for a "
                                f"different entity — a rename cannot move a name "
                                f"from one thing to another (§1)")
        for event in self.maintenance:
            if event.device not in self.devices:
                problems.append(f"maintenance event {event.id} references unknown "
                                f"device {event.device}")
        return problems


_DISPATCH = {
    Datastream: ("datastreams", True),
    Device: ("devices", True),
    Label: ("labels", False),
    Installation: ("installations", True),
    MaintenanceEvent: ("maintenance", False),
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

    This goes through `State.add` rather than repeating its dispatch, so a replay
    and an incremental fold end up identical — including the indexes. An earlier
    version duplicated the dispatch here and silently skipped them.
    """
    state = State()
    for record in log.records():
        state.add(record)
    return state
