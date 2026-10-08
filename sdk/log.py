#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The append-only log (spec v0.1 §7.1, §7.3).

Every change to records, every observation, every command and every decision is an
event. Current state is derived from the log, so history can always be replayed and
audited. The two stores in §7.2 — time-series and records — are projections of this;
neither is authoritative.

**There is no update and no delete, by construction.** Not a flag, not a private
method: the API does not contain one. §7.3 says a correction is a compensating
event, and the farmOS-conventions half of the model is CRUD-shaped enough that an
implementer will reach for a mutation if one is within reach. `correct()` is the
only way to change what the state says, and it leaves the original readable
forever.

Events are stamped with a hybrid logical clock (§7.4), not a wall clock, for the
reason §2 gives: farm clocks are not trustworthy, and an event ordering that a bad
clock can reorder is not an audit trail. The HLC stamp is the log's order; the
file's line order is only how it happens to be stored.

Durability is deliberately plain. One JSONL line per event, opened append-only, one
`write` and one `flush` per append. A line that fails to parse on replay is reported
and skipped rather than taking the whole log down with it — a truncated final line
after a power cut is the expected case on a farm gateway, not an exception.

What is *not* here yet: erasure by key destruction (§7.3), which needs the key
management in open-questions Q17, and the sharing grants of §7.6. Both append like
anything else when they arrive.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from bisect import insort
from dataclasses import dataclass
from uuid import UUID

import codec
from hlc import Hlc, Stamp
from ids import uuid7

#: Event kinds for the contract records. Free-form kinds are allowed — the log does
#: not police vocabulary — but these are what `records()` knows how to decode.
RECORD_KINDS = {
    "Datastream": "datastream",
    "Device": "device",
    "Label": "label",
    "Installation": "installation",
    "MaintenanceEvent": "maintenance",
    "Calibration": "calibration",
    "Observation": "observation",
    "Threshold": "threshold",
    "QualityAssertion": "quality_assertion",
}

CORRECTION = "correction"


@dataclass(frozen=True, slots=True)
class Event:
    """One entry. Frozen, like everything else that is supposed to be history."""

    id: UUID
    stamp: Stamp
    kind: str
    payload: dict
    recorded_at: _dt.datetime

    def to_jsonable(self) -> dict:
        return {
            "id": str(self.id),
            "stamp": str(self.stamp),
            "kind": self.kind,
            "payload": self.payload,
            "recorded_at": self.recorded_at.isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def from_jsonable(cls, doc: dict) -> "Event":
        ts = doc["recorded_at"]
        ts = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        return cls(
            id=UUID(doc["id"]),
            stamp=Stamp.parse(doc["stamp"]),
            kind=doc["kind"],
            payload=doc["payload"],
            recorded_at=_dt.datetime.fromisoformat(ts),
        )

    def record(self):
        """Decode the payload back into a contract record, or None if this event
        does not carry one (a correction's reason, say)."""
        if codec.TYPE_KEY not in self.payload:
            return None
        return codec.load(self.payload)


class LogError(Exception):
    pass


class Log:
    """An append-only event log, optionally backed by a JSONL file.

    In memory with no path, which is what most tests want; give a path and every
    append is durable before the call returns.
    """

    __slots__ = ("_events", "_ids", "_path", "_hlc", "_skipped", "_arrivals",
                 "_listeners", "_listener_errors")

    def __init__(self, path: str | os.PathLike | None = None, *, hlc: Hlc | None = None):
        self._events: list[Event] = []
        self._ids: set[UUID] = set()
        self._path = os.fspath(path) if path is not None else None
        self._hlc = hlc or Hlc()
        self._skipped: list[str] = []
        #: Events in the order this replica *learned* them, which is not HLC order.
        #: See `arrivals_since` for why the difference is the whole of §7.5.
        self._arrivals: list[Event] = []
        self._listeners: list = []
        self._listener_errors: list[str] = []
        if self._path and os.path.exists(self._path):
            self._replay()

    # ------------------------------------------------------------- reading

    @property
    def events(self) -> tuple[Event, ...]:
        """Every event, in HLC order. A tuple, so a caller cannot edit history."""
        return tuple(self._events)

    @property
    def skipped_lines(self) -> tuple[str, ...]:
        """Lines that would not parse on replay — reported, never silently lost."""
        return tuple(self._skipped)

    @property
    def arrival_count(self) -> int:
        """How many events this replica has learned, ever. A cursor is an offset into
        this count."""
        return len(self._arrivals)

    def arrivals_since(self, offset: int) -> tuple[Event, ...]:
        """Events this replica learned after the first `offset`, in arrival order.

        **Arrival order, not HLC order — and that difference is §7.5.** `receive`
        takes events from other replicas and inserts them by HLC stamp, so an event
        written offline yesterday and synced today lands in the *middle* of history.
        A subscriber whose cursor is a position in HLC order, or the last stamp it
        saw, is already past that point and never sees the event: a silent miss,
        which is exactly the failure §7.5 exists to forbid, and it happens only in the
        offline case — the one that matters most and is tested least.

        Arrival order only ever grows at the end, so an offset into it cannot be
        overtaken. It is also already durable: `_commit` appends to the file in
        arrival order and only the in-memory list is sorted by stamp, so replaying the
        file reconstructs this sequence exactly.
        """
        if offset < 0:
            raise ValueError("offset must not be negative")
        return tuple(self._arrivals[offset:])

    def arrival_at(self, offset: int) -> Event:
        """The event at an arrival offset, for checking a cursor's anchor."""
        return self._arrivals[offset]

    def on_commit(self, listener):
        """Call `listener(event)` after every commit. Returns an unsubscribe function.

        **A wakeup, not a delivery guarantee.** "Nothing above layer zero polls"
        (§7.5) needs something to wake a subscriber, but a subscriber that is down
        when the wakeup fires misses it — so the guarantee comes from the cursor and
        this only saves it a poll. A listener that raises does not undo the commit,
        which has already been made durable; the error is recorded in
        `listener_errors` rather than swallowed, because a broken subscriber should be
        visible.
        """
        self._listeners.append(listener)

        def unsubscribe():
            if listener in self._listeners:
                self._listeners.remove(listener)
        return unsubscribe

    @property
    def listener_errors(self) -> tuple[str, ...]:
        return tuple(self._listener_errors)

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self):
        return iter(self._events)

    def records(self, kind: str | None = None):
        """Decode contract records out of the log, in log order.

        This is the raw history, superseded rows included. Getting *current* state
        from it is `project.py`'s job — §7.1 says state is derived, and the
        derivation is a separate, testable step.
        """
        for ev in self._events:
            if kind is not None and ev.kind != kind:
                continue
            rec = ev.record()
            if rec is not None:
                yield rec

    def corrections(self):
        """Every compensating event (§7.3), in log order."""
        return (ev for ev in self._events if ev.kind == CORRECTION)

    # ------------------------------------------------------------- writing

    def append(self, kind: str, payload: dict, *, encoded: bool = False) -> Event:
        """Append one event. The only way anything enters the log.

        `encoded` says the payload is already JSON-able, which `append_record`
        knows because `codec.dump` produced it. Re-walking an encoded document was
        a third of the ingest cost at season scale.
        """
        if not kind:
            raise LogError("an event must have a kind")
        event = Event(
            id=uuid7(),
            stamp=self._hlc.now(),
            kind=kind,
            payload=payload if encoded else codec.jsonable(payload),
            recorded_at=_dt.datetime.now(tz=_dt.timezone.utc),
        )
        return self._commit(event)

    def append_record(self, record) -> Event:
        """Append a contract record under its conventional kind."""
        kind = RECORD_KINDS.get(type(record).__name__)
        if kind is None:
            raise LogError(f"no event kind for {type(record).__name__}")
        return self.append(kind, codec.dump(record), encoded=True)

    def correct(self, target: UUID, reason: str, *, replacement=None) -> Event:
        """Record a correction as a compensating event (§7.3).

        Nothing is updated in place. `target` is the event being corrected and
        stays readable; `replacement` is the record that should be believed
        instead, when there is one.
        """
        if not isinstance(target, UUID):
            raise TypeError("target must be the UUID of the event being corrected")
        if target not in self._ids:
            raise LogError(f"cannot correct an event that is not in the log: {target}")
        if not reason:
            raise LogError("a correction must say why — it is the audit trail (§7.1)")
        payload = {"corrects": str(target), "reason": reason}
        if replacement is not None:
            payload["replacement"] = codec.dump(replacement)
        return self.append(CORRECTION, payload)

    def receive(self, event: Event) -> Event:
        """Take an event from another replica, merging its HLC stamp (§7.4).

        This is what keeps causality across offline edits: a replica that appends a
        remote event without merging its stamp has dropped the guarantee.
        """
        if event.id in self._ids:
            return event          # already have it; idempotent by design
        self._hlc.update(event.stamp)
        return self._commit(event)

    # ------------------------------------------------------------ internals

    @staticmethod
    def _order(event: Event):
        return (event.stamp.wall_ms, event.stamp.counter, event.id.int)

    def _commit(self, event: Event) -> Event:
        if event.id in self._ids:
            raise LogError(f"duplicate event id {event.id}")
        # HLC stamps are monotonic for events this log issues itself, so the
        # ordinary case is an append at the end. Sorting the whole history on every
        # append made that O(n log n) per event and O(n^2 log n) over a season —
        # one simulated day of a five-node farm spent sixteen seconds in here,
        # against §7.2's promise that years of readings never slow everyday work.
        if self._events and self._order(event) < self._order(self._events[-1]):
            insort(self._events, event, key=self._order)
        else:
            self._events.append(event)
        self._ids.add(event.id)
        self._arrivals.append(event)
        if self._path:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_jsonable(), separators=(",", ":")) + "\n")
                f.flush()
        # Wake subscribers only after the event is durable, so a subscriber that
        # reacts immediately can never see an event the log would lose in a crash.
        for listener in tuple(self._listeners):
            try:
                listener(event)
            except Exception as exc:          # noqa: BLE001 — recorded, not hidden
                self._listener_errors.append(f"{event.id}: {exc!r}")
        return event

    def _replay(self) -> None:
        with open(self._path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = Event.from_jsonable(json.loads(line))
                except Exception as exc:
                    # A half-written final line after a power cut is ordinary on a
                    # farm gateway. Report it; never discard the rest of history.
                    self._skipped.append(f"line {lineno}: {exc}")
                    continue
                if event.id in self._ids:
                    continue
                self._events.append(event)
                self._arrivals.append(event)      # file order *is* arrival order
                self._ids.add(event.id)
                self._hlc.update(event.stamp)
        self._events.sort(key=self._order)
