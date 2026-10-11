#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline edits to the farm's records, and their conflicts (spec v0.1 §7.4; Q7, Q14).

Two people on two phones edit one harvest lot in a field with no signal. Both sync that
evening. §7.4 says what happens next, and this is it:

* **Concurrency comes from what each writer had seen, not from the clock.** Every edit
  names the versions of the record in front of its writer (`RecordEdit.base`). An edit
  made after seeing another has it in its history and simply follows it, whatever the
  two phones' clocks said. Two edits neither of which had seen the other are concurrent.
  An HLC stamp cannot make that call — it puts every event in one order, but two stamps
  do not say whether one writer knew of the other.
* **Q14's fields never resolve silently.** Concurrent edits to a protected field that
  disagree keep both values; `RecordState.conflicts()` lists them and
  `notice_conflicts` writes the conflict into the log, where a subscriber asks a
  person. A person resolves it by editing the field having seen both — an ordinary edit,
  so the resolution is in the history like everything else.
* **Everything else is latest edit wins in HLC order** (§7.4), and the fields where two
  devices disagreed are still reported (`edited_on_two_devices`), which is Q7's plan B
  mark, there from the start.
* **A void concurrent with any protected edit is a conflict.** Field by field the two
  never meet, and the void would quietly take a withdrawal or a spray off the record
  while another phone was correcting it.
* **Set-like fields merge by union.** An edit adds or removes elements, and a removal
  only removes what its writer had seen added, so an addition made concurrently with a
  removal survives it.

All of it happens at projection time over the log (§7.4): nothing is discarded, the
result is the same on every replica that holds the same events, and it can be re-run
when the rules improve.

Conflicted values are not hidden behind the stand-in the current record shows. The checks
these records exist for — a treated animal's withdrawal, a harvest inside a spray's
pre-harvest interval — read every candidate value and take the cautious one.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field, replace
from uuid import UUID

from ids import uuid7
from records import (EDITABLE, IDENTITY, AnimalTreatment, ConflictNotice, HarvestLot,
                     InputApplication, RecordEdit, field_names)


@dataclass(frozen=True, slots=True)
class Version:
    """One version of a record: its creation, or one edit."""

    id: UUID
    order: int            # place in the log's HLC order
    base: tuple
    set: dict
    add: dict
    remove: dict
    edit: RecordEdit | None = None


@dataclass(frozen=True, slots=True)
class Conflict:
    """Concurrent versions of a protected field that disagree (Q14)."""

    record: UUID
    kind: str
    field: str
    candidates: tuple     # ((version id, value), ...) in HLC order
    noticed: bool = False

    @property
    def versions(self) -> tuple:
        return tuple(sorted((v for v, _ in self.candidates), key=lambda u: u.int))

    @property
    def key(self) -> tuple:
        return (self.record, self.field, self.versions)


@dataclass(frozen=True, slots=True)
class IntervalBreach:
    """A harvest inside a product's pre-harvest or re-entry interval."""

    lot: UUID
    application: UUID
    interval: str               # "preharvest" or "reentry"
    applied_at: _dt.datetime
    harvested_at: _dt.datetime
    limit: _dt.timedelta

    def __str__(self) -> str:
        gap = self.harvested_at - self.applied_at
        return (f"lot {self.lot} was harvested {gap} after application "
                f"{self.application}, inside its {self.interval} interval of {self.limit}")


@dataclass
class _Record:
    created: object
    versions: dict = field(default_factory=dict)       # version id -> Version
    ancestors: dict = field(default_factory=dict)      # version id -> frozenset
    current: object = None
    values: dict = field(default_factory=dict)         # field -> candidate values
    conflicted: set = field(default_factory=set)
    two_devices: set = field(default_factory=set)
    heads: tuple = ()


class RecordState:
    """The farm's records as of one log, with their conflicts. Built by `project`."""

    def __init__(self) -> None:
        self._records: dict[UUID, _Record] = {}
        self._conflicts: list[Conflict] = []
        self._notices: dict[tuple, ConflictNotice] = {}
        self.problems: list[str] = []

    # ------------------------------------------------------------ reading

    def get(self, record_id: UUID):
        """The record as it stands. For a conflicted field this is a stand-in — the
        candidate latest in HLC order — so read `conflicts()` before trusting it."""
        rec = self._records.get(record_id)
        return None if rec is None else rec.current

    def __contains__(self, record_id: UUID) -> bool:
        return record_id in self._records

    def of_type(self, cls) -> list:
        return [r.current for r in self._records.values() if type(r.current) is cls]

    def values(self, record_id: UUID, name: str) -> tuple:
        """Every value a field currently has: one, or the candidates of a conflict."""
        rec = self._records[record_id]
        if name in rec.values:
            return rec.values[name]
        return (getattr(rec.current, name),)

    def conflicts(self, record_id: UUID | None = None) -> list[Conflict]:
        return [c for c in self._conflicts if record_id is None or c.record == record_id]

    def conflicted_fields(self, record_id: UUID) -> frozenset:
        return frozenset(self._records[record_id].conflicted)

    def edited_on_two_devices(self, record_id: UUID) -> frozenset:
        """Unprotected fields where concurrent edits disagreed and HLC order chose
        (Q7's plan B mark), so a person can see a value was contested."""
        return frozenset(self._records[record_id].two_devices)

    def heads(self, record_id: UUID) -> tuple:
        """The versions no other version has seen — what an edit made now has seen."""
        return self._records[record_id].heads

    def history(self, record_id: UUID) -> list[Version]:
        rec = self._records[record_id]
        return sorted(rec.versions.values(), key=lambda v: v.order)

    @property
    def notices(self) -> tuple:
        return tuple(self._notices.values())

    # ------------------------------------------------- what the records are for

    def _active(self, record_id: UUID) -> bool:
        """Not voided — unless every candidate says void, a record counts. A void in
        conflict with an edit is not a void yet."""
        return not all(self.values(record_id, "void"))

    def withdrawal_until(self, animal: UUID, commodity: str) -> _dt.datetime | None:
        """When the last withdrawal on this animal's `commodity` ends, or None.

        Reads every candidate of a conflicted treatment and takes the latest end, so a
        disagreement between two phones never shortens a withdrawal.
        """
        latest = None
        for treatment in self.of_type(AnimalTreatment):
            if animal not in treatment.animals or not self._active(treatment.id):
                continue
            for at in self.values(treatment.id, "administered_at"):
                for days in self.values(treatment.id, "withdrawal_days"):
                    if commodity in days:
                        end = at + _dt.timedelta(days=days[commodity])
                        latest = end if latest is None or end > latest else latest
        return latest

    def under_withdrawal(self, animal: UUID, commodity: str, at: _dt.datetime) -> bool:
        end = self.withdrawal_until(animal, commodity)
        return end is not None and at < end

    def harvest_problems(self) -> list[IntervalBreach]:
        """Harvest lots taken from land inside an application's pre-harvest or re-entry
        interval. Candidates of a conflict count — the earliest harvest, the latest
        application and the longest interval — so a disagreement cannot hide a breach."""
        breaches = []
        applications = [a for a in self.of_type(InputApplication) if self._active(a.id)]
        for lot in self.of_type(HarvestLot):
            if not self._active(lot.id):
                continue
            land = set().union(*self.values(lot.id, "land"))
            harvested = min(self.values(lot.id, "harvested_at"))
            for app in applications:
                if not land & set().union(*self.values(app.id, "land")):
                    continue
                before = [t for t in self.values(app.id, "applied_at") if t <= harvested]
                if not before:
                    continue
                applied = max(before)
                limits = []
                phi = [d for d in self.values(app.id, "preharvest_interval_days") if d]
                if phi:
                    limits.append(("preharvest", _dt.timedelta(days=max(phi))))
                rei = [h for h in self.values(app.id, "reentry_interval_h") if h]
                if rei:
                    limits.append(("reentry", _dt.timedelta(hours=max(rei))))
                for name, limit in limits:
                    if harvested < applied + limit:
                        breaches.append(IntervalBreach(lot.id, app.id, name, applied,
                                                       harvested, limit))
        return breaches

    def trace(self, lot_id: UUID, *, days: int = 365) -> list:
        """What was applied to a lot's land in the `days` before it was harvested — the
        first question of a recall, and of a residue finding."""
        land = set().union(*self.values(lot_id, "land"))
        harvested = max(self.values(lot_id, "harvested_at"))
        since = harvested - _dt.timedelta(days=days)
        found = []
        for app in self.of_type(InputApplication):
            if not land & set().union(*self.values(app.id, "land")):
                continue
            if any(since <= t <= harvested for t in self.values(app.id, "applied_at")):
                found.append(app)
        return sorted(found, key=lambda a: a.applied_at)


# ------------------------------------------------------------------ projection

def project(log) -> RecordState:
    """The records and their conflicts from a log (§7.1, §7.4). Deterministic: two
    replicas holding the same events get the same state, whatever order they learned
    them in."""
    state = RecordState()
    edits = []
    for order, event in enumerate(log.events):
        rec = event.record()
        if rec is None:
            continue
        if type(rec).__name__ in EDITABLE:
            if rec.id in state._records:
                state.problems.append(f"{type(rec).__name__} {rec.id} is created twice; "
                                      "the later creation is ignored — change a record "
                                      "with an edit")
                continue
            sets = type(rec).SETS
            scalars = {n: getattr(rec, n) for n in field_names(type(rec))
                       if n not in IDENTITY and n not in sets}
            initial = {n: getattr(rec, n) for n in sets}
            r = _Record(created=rec)
            r.versions[rec.id] = Version(rec.id, order, (), scalars, initial, {})
            state._records[rec.id] = r
        elif isinstance(rec, RecordEdit):
            edits.append((order, rec))
        elif isinstance(rec, ConflictNotice):
            state._notices.setdefault(rec.key, rec)

    for order, e in edits:
        r = state._records.get(e.record)
        if r is None:
            state.problems.append(f"edit {e.id} changes record {e.record}, which this "
                                  "replica does not have")
            continue
        if type(r.created).__name__ != e.kind:
            state.problems.append(f"edit {e.id} says {e.record} is a {e.kind}; it is a "
                                  f"{type(r.created).__name__}")
            continue
        r.versions[e.id] = Version(e.id, order, e.base, e.set, e.add, e.remove, e)

    for record_id, r in state._records.items():
        _resolve(state, record_id, r)
    return state


def _ancestors(r: _Record) -> None:
    """Every version each version had seen, through its bases."""
    memo = r.ancestors

    def walk(vid):
        if vid in memo:
            return memo[vid]
        seen = set()
        stack = list(r.versions[vid].base)
        while stack:
            b = stack.pop()
            if b in seen or b not in r.versions:
                continue
            seen.add(b)
            if b in memo:
                seen |= memo[b]
            else:
                stack.extend(r.versions[b].base)
        memo[vid] = frozenset(seen)
        return memo[vid]

    for vid in sorted(r.versions, key=lambda v: r.versions[v].order):
        walk(vid)


def _distinct(values) -> list:
    out = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


def _resolve(state: RecordState, record_id: UUID, r: _Record) -> None:
    cls = type(r.created)
    for v in r.versions.values():
        missing = [b for b in v.base if b not in r.versions]
        if missing:
            state.problems.append(f"edit {v.id} was made after {len(missing)} version(s) of "
                                  f"{record_id} this replica has not received yet")
    _ancestors(r)
    anc = r.ancestors
    seen_by_someone = set().union(*anc.values()) if anc else set()
    r.heads = tuple(sorted((v for v in r.versions if v not in seen_by_someone),
                           key=lambda u: u.int))

    values = {}
    for name in field_names(cls):
        if name in IDENTITY:
            continue
        if name in cls.SETS:
            values[name] = _union(r, name)
            continue
        writes = [v for v in r.versions.values() if name in v.set]
        maximal = sorted((w for w in writes
                          if not any(w.id in anc[o.id] for o in writes if o is not w)),
                         key=lambda v: v.order)
        winner = maximal[-1]
        values[name] = winner.set[name]
        distinct = _distinct(w.set[name] for w in maximal)
        if len(distinct) > 1:
            if name in cls.PROTECTED:
                r.conflicted.add(name)
                r.values[name] = tuple(distinct)
                c = Conflict(record_id, cls.__name__, name,
                             tuple((w.id, w.set[name]) for w in maximal))
                state._conflicts.append(replace(c, noticed=c.key in state._notices))
            else:
                r.two_devices.add(name)
    if "void" in cls.PROTECTED:
        _void_against_edits(state, record_id, r)
    try:
        r.current = replace(r.created, **values)
    except (TypeError, ValueError) as exc:
        state.problems.append(f"{cls.__name__} {record_id}: its edits together make an "
                              f"invalid record ({exc}); showing it as created")
        r.current = r.created


def _void_against_edits(state: RecordState, record_id: UUID, r: _Record) -> None:
    """A void concurrent with an edit to any protected field is a conflict on `void`.

    Field by field, the two never meet — one phone wrote `void`, the other `dose` — and
    the void would win silently, taking a withdrawal or a spray off the record while
    someone else was correcting it. The phone that corrected the dose believed the
    record stood; that is a second decision about one compliance record, so a person
    sees both. A void made after seeing the correction is no conflict at all.
    """
    if "void" in r.conflicted:
        return
    cls = type(r.created)
    anc = r.ancestors
    writes = [v for v in r.versions.values() if "void" in v.set]
    maximal = [w for w in writes if not any(w.id in anc[o.id] for o in writes if o is not w)]
    voids = [w for w in maximal if w.set["void"] is True]
    if not voids:
        return
    rivals = [v for v in r.versions.values()
              if v.edit is not None and "void" not in v.set
              and any(f in cls.PROTECTED for f in v.set)
              and any(v.id not in anc[w.id] and w.id not in anc[v.id] for w in voids)]
    if not rivals:
        return
    candidates = sorted([(w, True) for w in voids] + [(v, False) for v in rivals],
                        key=lambda pair: pair[0].order)
    r.conflicted.add("void")
    r.values["void"] = (True, False)
    c = Conflict(record_id, cls.__name__, "void",
                 tuple((v.id, value) for v, value in candidates))
    state._conflicts.append(replace(c, noticed=c.key in state._notices))


def _union(r: _Record, name: str) -> frozenset:
    """An observed-remove set: an element is in if some addition of it was not seen by
    a removal of it. A removal concurrent with an addition does not take it out."""
    adds = [(v.id, e) for v in r.versions.values() for e in v.add.get(name, ())]
    removes = [(v.id, e) for v in r.versions.values() for e in v.remove.get(name, ())]
    present = set()
    for added_by, element in adds:
        if not any(e == element and (added_by in r.ancestors[removed_by])
                   for removed_by, e in removes):
            present.add(element)
    return frozenset(present)


# ------------------------------------------------------------------- writing

def create(log, record):
    """Write a new record. Its id is also its first version."""
    if type(record).__name__ not in EDITABLE:
        raise TypeError(f"{type(record).__name__} is not one of the farm's records")
    return log.append_record(record)


def edit(log, record_id: UUID, *, at: _dt.datetime, set=None, add=None, remove=None,
         by: UUID | None = None, reason: str | None = None, state: RecordState | None = None):
    """Edit a record as this replica sees it now. The edit's base is every version this
    replica holds of the record, so it follows all of them; anything another phone did
    that has not synced yet stays concurrent with it, as it truly is.

    The result is checked before anything is written, so an edit that would make an
    invalid record fails here rather than on every replica's projection.
    """
    state = state or project(log)
    current = state.get(record_id)
    if current is None:
        raise KeyError(f"no record {record_id} in this log")
    e = RecordEdit(uuid7(), record_id, type(current).__name__, state.heads(record_id), at,
                   dict(set or {}), dict(add or {}), dict(remove or {}), by, reason)
    changed = dict(e.set)
    for name in type(current).SETS:
        if name in e.add or name in e.remove:
            changed[name] = (getattr(current, name) | e.add.get(name, frozenset())) \
                - e.remove.get(name, frozenset())
    replace(current, **changed)          # validates; raises before the log is touched
    return log.append_record(e)


def resolve(log, record_id: UUID, name: str, value, *, at: _dt.datetime, reason: str,
            by: UUID | None = None, state: RecordState | None = None):
    """Settle a conflict: set the field having seen every candidate. `reason` is
    required, because this is the one edit whose why the next reader will ask."""
    state = state or project(log)
    if name not in state.conflicted_fields(record_id):
        raise ValueError(f"{name} of {record_id} is not in conflict")
    if not (reason or "").strip():
        raise ValueError("a resolution says why one value was chosen")
    return edit(log, record_id, at=at, set={name: value}, by=by, reason=reason, state=state)


def notice_conflicts(log, *, at: _dt.datetime, state: RecordState | None = None) -> list:
    """Write a `ConflictNotice` for every conflict not yet noticed, and return the
    events. Run it after a sync; running it twice writes nothing the second time."""
    state = state or project(log)
    written = []
    for c in state.conflicts():
        if c.noticed:
            continue
        notice = ConflictNotice(uuid7(), c.record, c.kind, c.field, c.versions, at)
        written.append(log.append_record(notice))
        state._notices[notice.key] = notice
    return written
