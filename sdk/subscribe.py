#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Subscriptions with a durable cursor (spec v0.1 §7.5).

"Nothing above layer zero polls" implies delivery guarantees, and §7.5 states them:
**at-least-once, with a durable cursor each subscriber can replay from.** A module that
restarts, silently misses what happened while it was down, and cannot replay it will make
wrong decisions while its decision events claim full provenance — the worst combination,
because the record says the decision was well informed.

## The cursor is an arrival offset, and nothing else works

`Log.receive` inserts a remote event by its HLC stamp, so an edit made offline on a phone
yesterday and synced today lands in the middle of history. Every cursor that is a
position in that order — an index, the last stamp seen, the last event id — is already
past it, and the subscriber never sees the event. It is a silent miss, it only happens in
the offline case, and the offline case is the one the spec was written for.

So the cursor counts **arrivals**: the order this replica learned events in, which only
ever grows at the end. `test_subscribe.py` demonstrates the stamp-based cursor losing an
event that the arrival cursor delivers, rather than asserting the difference.

## Three consequences worth knowing

* **At-least-once means duplicates.** A subscriber that crashes after acting on a batch
  but before its cursor is saved gets the batch again. Handlers MUST be idempotent on
  `event.id`. The alternative ordering — save, then act — loses the batch instead, and a
  lost batch is the failure §7.5 forbids, so this is the right way round.
* **Delivery is in arrival order, not HLC order.** A subscriber that needs causal order
  sorts by `stamp` itself; one that needs completeness gets it from the cursor. Those are
  different promises and only the second can be made without buffering forever.
* **A cursor belongs to one replica.** Arrival order differs between replicas, so an
  offset from one is meaningless against another. Every cursor carries the id of the last
  event it covered, and a cursor whose anchor does not match the log **refuses to run**
  rather than silently skipping or replaying the wrong events.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from dataclasses import dataclass
from uuid import UUID

from log import Event, Log


class CursorMismatch(Exception):
    """The cursor does not describe this log.

    Raised rather than recovered from, because every recovery is a guess: resetting to
    zero redelivers a season, and trusting the offset delivers the wrong events. The
    person running the subscriber has to decide which, so the error says what it saw.
    """


@dataclass(frozen=True, slots=True)
class Cursor:
    """How far a subscriber has got: `offset` arrivals processed, the last being `anchor`."""

    offset: int = 0
    anchor: UUID | None = None

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError("offset must not be negative")
        if (self.offset == 0) != (self.anchor is None):
            raise ValueError("a cursor at offset 0 has no anchor, and any other has one")

    def check(self, log: Log) -> None:
        """Refuse to run against a log this cursor does not describe."""
        if self.offset == 0:
            return
        if self.offset > log.arrival_count:
            raise CursorMismatch(
                f"cursor is at arrival {self.offset} but this log has only "
                f"{log.arrival_count} — it was issued by a different replica, or the "
                f"log was truncated")
        found = log.arrival_at(self.offset - 1).id
        if found != self.anchor:
            raise CursorMismatch(
                f"cursor expects event {self.anchor} at arrival {self.offset - 1}, "
                f"found {found} — arrival order differs between replicas, so a cursor "
                f"from one cannot be used against another")

    def to_jsonable(self) -> dict:
        return {"offset": self.offset,
                "anchor": str(self.anchor) if self.anchor else None}

    @classmethod
    def from_jsonable(cls, doc: dict) -> "Cursor":
        anchor = doc.get("anchor")
        return cls(offset=int(doc.get("offset", 0)),
                   anchor=UUID(anchor) if anchor else None)


class CursorStore:
    """A cursor on disk, one file per subscriber.

    Written by write-then-rename, with an fsync, so a power cut leaves either the old
    cursor or the new one and never half of each. A half-written cursor is the one state
    that cannot be reasoned about afterwards, and a farm gateway loses power as a matter
    of routine.
    """

    __slots__ = ("path",)

    def __init__(self, path: str | os.PathLike):
        self.path = os.fspath(path)

    def load(self) -> Cursor:
        if not os.path.exists(self.path):
            return Cursor()
        with open(self.path, encoding="utf-8") as handle:
            return Cursor.from_jsonable(json.load(handle))

    def save(self, cursor: Cursor, *, subscriber: str | None = None) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        doc = cursor.to_jsonable()
        doc["saved_at"] = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()
        if subscriber:
            doc["subscriber"] = subscriber
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".cursor-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


class MemoryCursorStore:
    """A cursor that lives as long as the process. For tests and throwaway readers —
    never for a module that makes decisions, which is the whole point of §7.5."""

    __slots__ = ("_cursor",)

    def __init__(self, cursor: Cursor | None = None):
        self._cursor = cursor or Cursor()

    def load(self) -> Cursor:
        return self._cursor

    def save(self, cursor: Cursor, *, subscriber: str | None = None) -> None:
        self._cursor = cursor


@dataclass(frozen=True, slots=True)
class Batch:
    """Events to process, and the cursor to save once they have been processed."""

    events: tuple[Event, ...]
    next_cursor: Cursor
    scanned: int

    def __len__(self) -> int:
        return len(self.events)


class Subscription:
    """One subscriber's view of the log.

    `kinds` filters what is *delivered*, but the cursor advances over everything it
    scanned. A filtered subscriber whose cursor only moved on matching events would
    re-scan every non-matching event forever, and on a farm that is almost all of them.
    """

    __slots__ = ("log", "name", "store", "kinds")

    def __init__(self, log: Log, name: str, store, *, kinds=None):
        self.log = log
        self.name = name
        self.store = store
        self.kinds = frozenset(kinds) if kinds else None

    @property
    def cursor(self) -> Cursor:
        return self.store.load()

    def lag(self) -> int:
        """Arrivals not yet processed. The number to alert on."""
        return self.log.arrival_count - self.cursor.offset

    def poll(self, max_events: int | None = None) -> Batch:
        """The next events after the saved cursor. Does **not** advance the cursor."""
        cursor = self.store.load()
        cursor.check(self.log)
        window = self.log.arrivals_since(cursor.offset)
        if max_events is not None:
            window = window[:max_events]
        if not window:
            return Batch(events=(), next_cursor=cursor, scanned=0)
        delivered = tuple(e for e in window
                          if self.kinds is None or e.kind in self.kinds)
        next_cursor = Cursor(offset=cursor.offset + len(window), anchor=window[-1].id)
        return Batch(events=delivered, next_cursor=next_cursor, scanned=len(window))

    def ack(self, batch: Batch) -> None:
        """Save the cursor — call only after every event in `batch` was handled.

        Acting first and saving second is what makes delivery at-least-once: a crash in
        between redelivers the batch. The opposite order loses it.
        """
        self.store.save(batch.next_cursor, subscriber=self.name)

    def deliver(self, handler, *, batch_size: int = 500) -> int:
        """Hand every outstanding event to `handler(event)`, saving after each batch.

        Returns how many events were delivered. If `handler` raises, the cursor is left
        where it was and the exception propagates, so the batch is redelivered next time
        rather than half-marked as done.
        """
        delivered = 0
        while True:
            batch = self.poll(batch_size)
            if batch.scanned == 0:
                return delivered
            for event in batch.events:
                handler(event)
            self.ack(batch)
            delivered += len(batch.events)
