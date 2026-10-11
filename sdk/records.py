#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The farm's records (spec v0.1 §3, §7.4; open-questions Q7, Q14).

§3 says records follow farmOS conventions and sensing follows SensorThings, both in one
log. The sensing half has been built since the start. These are the records Q14 named
as the ones where a silent loss is a compliance record, an animal, a harvest or a
boundary that is wrong without anyone knowing:

* `Land` — a field, bed or paddock, and its boundary (farmOS's land asset);
* `InputApplication` — product, rate, area and date (farmOS's input log): the organic
  and pesticide record;
* `AnimalTreatment` — product, dose, date and the withdrawal that follows (farmOS's
  medical log);
* `HarvestLot` — what, where, when and how much, under a lot code (farmOS's harvest log
  with its lot number): the traceability record;

and the two things around them a farm needs to say which animals: `Animal` and
`AnimalGroup`.

**A record is created once and then edited, never overwritten.** Two people on two
phones editing one record offline is ordinary on a farm, so an edit is its own record,
`RecordEdit`, naming what it changes and — the part that makes conflicts decidable —
which versions of the record its writer had already seen. `edits.py` projects the
current record from the creation and its edits. Each type declares:

* `PROTECTED` — Q14's fields. Two concurrent edits that disagree keep both values and
  raise a conflict a person resolves. Everything else is latest edit wins in HLC order.
* `SETS` — set-like fields (tags, which animals, a group's members). They merge by
  union: an edit adds or removes elements, and a removal only removes what its writer
  had seen added, so a concurrent addition survives it.

Names are not here: a field is named by a `Label`, like every other entity (§1). People
are referenced by id, never by name, because a name is personal data and §7.3 erases
personal data by key.
"""
from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field, fields
from enum import Enum
from uuid import UUID

from model import _opt_uuid7, _utc, _uuid7

#: What a set-like field holds, so an edit's additions can be checked.
_SET_OF_UUIDS = "uuids"
_SET_OF_TEXT = "text"


# ------------------------------------------------------------------ helpers

def _text(value, name: str, *, optional: bool = False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    if value != value.strip():
        raise ValueError(f"{name} must not carry leading or trailing whitespace")
    return value


def _tags(value, name: str = "tags") -> frozenset:
    tags = frozenset(value)
    for t in tags:
        _text(t, name)
    return tags


def _uuid_set(value, name: str, *, nonempty: bool) -> frozenset:
    ids = frozenset(value)
    if nonempty and not ids:
        raise ValueError(f"{name} must name at least one")
    for i in ids:
        _uuid7(i, name)
    return ids


def _uuid_tuple(value, name: str) -> tuple:
    """A list of ids in canonical order, so two writers listing the same lands in a
    different order have written the same value."""
    ids = tuple(sorted(set(value), key=lambda u: u.int))
    if not ids:
        raise ValueError(f"{name} must name at least one")
    for i in ids:
        _uuid7(i, name)
    return ids


def _days(value, name: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a whole number of days, zero or more")
    return value


@dataclass(frozen=True, slots=True)
class Quantity:
    """A number and its UCUM unit (§3.4), as farmOS's quantity is a value and a unit.

    A rate is `kg/har` or `L/har`, a dose `mL`, a harvest `kg`. The unit is a code, not
    prose, for the same reason an observation's is: a report summing two harvests has
    to know whether it is adding kilograms to pounds.
    """

    value: float
    unit: str

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("a quantity's value must be a number")
        if not math.isfinite(self.value):
            raise ValueError("a quantity's value must be finite")
        if self.value < 0:
            raise ValueError("a quantity is not negative; a correction is an edit")
        if not isinstance(self.unit, str) or not self.unit or any(c.isspace() for c in self.unit):
            raise ValueError("a quantity's unit must be a UCUM code such as 'kg' or "
                             "'L/har' (§3.4)")


# ------------------------------------------------------------------- land

class LandKind(str, Enum):
    """farmOS's land types that a sensor or a record can sit on."""
    FIELD = "field"
    BED = "bed"
    PADDOCK = "paddock"
    OTHER = "other"


def _ring(ring, name: str) -> None:
    if not isinstance(ring, list) or len(ring) < 4:
        raise ValueError(f"{name}: a ring has at least four positions, the last "
                         "repeating the first")
    for pos in ring:
        if (not isinstance(pos, list) or len(pos) not in (2, 3)
                or not all(isinstance(c, (int, float)) and not isinstance(c, bool)
                           for c in pos)):
            raise ValueError(f"{name}: a position is [longitude, latitude]")
        lon, lat = pos[0], pos[1]
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"{name}: [{lon}, {lat}] is not a longitude and latitude "
                             "(GeoJSON puts longitude first)")
    if ring[0] != ring[-1]:
        raise ValueError(f"{name}: a ring must close — its last position repeats its first")


def check_boundary(boundary) -> dict | None:
    """A GeoJSON Polygon or MultiPolygon in WGS 84, longitude first (RFC 7946)."""
    if boundary is None:
        return None
    if not isinstance(boundary, dict) or boundary.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError("a boundary is a GeoJSON Polygon or MultiPolygon")
    coords = boundary.get("coordinates")
    polygons = [coords] if boundary["type"] == "Polygon" else coords
    if not isinstance(polygons, list) or not polygons:
        raise ValueError("a boundary has coordinates")
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError("a polygon is a list of rings")
        for i, ring in enumerate(polygon):
            _ring(ring, "outer ring" if i == 0 else f"hole {i}")
    return boundary


@dataclass(frozen=True, slots=True)
class Land:
    """A field, bed or paddock, and where its edges are.

    Its id is the feature of interest's (§3: "a field or bed asset and the feature of
    interest it represents" share one id), so the probes in a bed and the records
    about it meet on one key. `parent` puts a bed in its field.
    """

    id: UUID
    site: UUID
    kind: LandKind
    boundary: dict | None = None
    parent: UUID | None = None
    archived: bool = False
    tags: frozenset = frozenset()

    PROTECTED = frozenset({"boundary"})
    SETS = {"tags": _SET_OF_TEXT}

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.site, "site")
        _opt_uuid7(self.parent, "parent")
        object.__setattr__(self, "kind", LandKind(self.kind))
        check_boundary(self.boundary)
        if self.parent == self.id:
            raise ValueError("land cannot be its own parent")
        if not isinstance(self.archived, bool):
            raise TypeError("archived is true or false")
        object.__setattr__(self, "tags", _tags(self.tags))


# ---------------------------------------------------------------- animals

@dataclass(frozen=True, slots=True)
class Animal:
    """One animal. `species` is a code — an AGROVOC URI where there is one (Q4) — and
    `tag` is what is on its ear, which is how a person finds it in a pen."""

    id: UUID
    site: UUID
    species: str
    tag: str | None = None
    born: _dt.datetime | None = None
    sex: str | None = None
    archived: bool = False
    tags: frozenset = frozenset()

    PROTECTED = frozenset()
    SETS = {"tags": _SET_OF_TEXT}

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.site, "site")
        _text(self.species, "species")
        _text(self.tag, "tag", optional=True)
        _text(self.sex, "sex", optional=True)
        if self.born is not None:
            _utc(self.born, "born")
        if not isinstance(self.archived, bool):
            raise TypeError("archived is true or false")
        object.__setattr__(self, "tags", _tags(self.tags))


@dataclass(frozen=True, slots=True)
class AnimalGroup:
    """A herd or flock. Members merge by union (§7.4): an animal added on one phone and
    another removed on a second both stand, and an animal added on one while another
    phone removes it stays in."""

    id: UUID
    site: UUID
    members: frozenset = frozenset()
    archived: bool = False
    tags: frozenset = frozenset()

    PROTECTED = frozenset()
    SETS = {"members": _SET_OF_UUIDS, "tags": _SET_OF_TEXT}

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.site, "site")
        object.__setattr__(self, "members", _uuid_set(self.members, "members",
                                                      nonempty=False))
        if not isinstance(self.archived, bool):
            raise TypeError("archived is true or false")
        object.__setattr__(self, "tags", _tags(self.tags))


# ------------------------------------------------------------------- logs

@dataclass(frozen=True, slots=True)
class InputApplication:
    """What was put on the land: product, rate, area and date — the record an organic
    certifier and a pesticide inspector both ask for.

    `preharvest_interval_days` and `reentry_interval_h` are the label's intervals.
    They are limits something reads — `RecordState.harvest_problems` checks every
    harvest lot against them — which is why Q14 protects them with the rest.

    `void` withdraws a record entered by mistake. It stays in history, and voiding is
    protected: a phone that voids a spray while another corrects its rate has made two
    decisions about one compliance record, and a person should see both.
    """

    id: UUID
    site: UUID
    applied_at: _dt.datetime
    land: tuple
    product: str
    rate: Quantity
    area: Quantity | None = None
    method: str | None = None
    purpose: str | None = None
    registration: str | None = None
    product_lot: str | None = None
    preharvest_interval_days: int | None = None
    reentry_interval_h: float | None = None
    applied_by: UUID | None = None
    note: str | None = None
    void: bool = False
    tags: frozenset = frozenset()

    PROTECTED = frozenset({"applied_at", "land", "product", "rate", "area",
                           "preharvest_interval_days", "reentry_interval_h", "void"})
    SETS = {"tags": _SET_OF_TEXT}

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.site, "site")
        _utc(self.applied_at, "applied_at")
        object.__setattr__(self, "land", _uuid_tuple(self.land, "land"))
        _text(self.product, "product")
        if not isinstance(self.rate, Quantity):
            raise TypeError("rate is a Quantity")
        if self.area is not None and not isinstance(self.area, Quantity):
            raise TypeError("area is a Quantity")
        for name in ("method", "purpose", "registration", "product_lot", "note"):
            _text(getattr(self, name), name, optional=True)
        _days(self.preharvest_interval_days, "preharvest_interval_days")
        if self.reentry_interval_h is not None:
            if (isinstance(self.reentry_interval_h, bool)
                    or not isinstance(self.reentry_interval_h, (int, float))
                    or self.reentry_interval_h < 0):
                raise ValueError("reentry_interval_h is hours, zero or more")
        _opt_uuid7(self.applied_by, "applied_by")
        if not isinstance(self.void, bool):
            raise TypeError("void is true or false")
        object.__setattr__(self, "tags", _tags(self.tags))


#: What a withdrawal period can hold back. Kept to the four a label states.
COMMODITIES = frozenset({"meat", "milk", "eggs", "honey"})


@dataclass(frozen=True, slots=True)
class AnimalTreatment:
    """A medicine given: product, dose, date, and the withdrawal that follows — the
    days before meat, milk, eggs or honey from a treated animal may be sold.

    `animals` merges by union. If one phone adds a calf to a treatment while another
    removes a heifer, both changes stand; if one removes the heifer while the other
    adds her, she stays. Union errs towards an animal being under withdrawal, which is
    the safe direction.
    """

    id: UUID
    site: UUID
    administered_at: _dt.datetime
    animals: frozenset
    product: str
    dose: Quantity
    withdrawal_days: dict = field(default_factory=dict)
    route: str | None = None
    reason: str | None = None
    registration: str | None = None
    product_lot: str | None = None
    administered_by: UUID | None = None
    note: str | None = None
    void: bool = False
    tags: frozenset = frozenset()

    PROTECTED = frozenset({"administered_at", "product", "dose", "withdrawal_days", "void"})
    SETS = {"animals": _SET_OF_UUIDS, "tags": _SET_OF_TEXT}

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.site, "site")
        _utc(self.administered_at, "administered_at")
        object.__setattr__(self, "animals", _uuid_set(self.animals, "animals",
                                                      nonempty=False))
        _text(self.product, "product")
        if not isinstance(self.dose, Quantity):
            raise TypeError("dose is a Quantity")
        if not isinstance(self.withdrawal_days, dict):
            raise TypeError("withdrawal_days maps a commodity to days")
        for commodity, days in self.withdrawal_days.items():
            if commodity not in COMMODITIES:
                raise ValueError(f"withdrawal is for one of {sorted(COMMODITIES)}, "
                                 f"not {commodity!r}")
            _days(days, f"withdrawal_days[{commodity}]")
        for name in ("route", "reason", "registration", "product_lot", "note"):
            _text(getattr(self, name), name, optional=True)
        _opt_uuid7(self.administered_by, "administered_by")
        if not isinstance(self.void, bool):
            raise TypeError("void is true or false")
        object.__setattr__(self, "tags", _tags(self.tags))

    def withdrawal_until(self, commodity: str) -> _dt.datetime | None:
        days = self.withdrawal_days.get(commodity)
        if days is None:
            return None
        return self.administered_at + _dt.timedelta(days=days)


@dataclass(frozen=True, slots=True)
class HarvestLot:
    """What was harvested, where, when and how much, under the lot code that goes on
    the box — the record a buyer's recall starts from."""

    id: UUID
    site: UUID
    harvested_at: _dt.datetime
    land: tuple
    crop: str
    quantity: Quantity
    lot: str
    note: str | None = None
    void: bool = False
    tags: frozenset = frozenset()

    PROTECTED = frozenset({"harvested_at", "land", "crop", "quantity", "lot", "void"})
    SETS = {"tags": _SET_OF_TEXT}

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.site, "site")
        _utc(self.harvested_at, "harvested_at")
        object.__setattr__(self, "land", _uuid_tuple(self.land, "land"))
        _text(self.crop, "crop")
        if not isinstance(self.quantity, Quantity):
            raise TypeError("quantity is a Quantity")
        _text(self.lot, "lot")
        _text(self.note, "note", optional=True)
        if not isinstance(self.void, bool):
            raise TypeError("void is true or false")
        object.__setattr__(self, "tags", _tags(self.tags))


#: The records an edit can name, by type name.
EDITABLE = {cls.__name__: cls for cls in (Land, Animal, AnimalGroup, InputApplication,
                                          AnimalTreatment, HarvestLot)}

#: Fields an edit may never change: who a record is and where it belongs.
IDENTITY = frozenset({"id", "site"})


def field_names(cls) -> tuple:
    return tuple(f.name for f in fields(cls))


# ------------------------------------------------------------------ edits

@dataclass(frozen=True, slots=True)
class RecordEdit:
    """A change to one record, and what its writer had seen when making it (§7.4).

    `base` is the record's versions this writer had in front of them — the creation is
    version `record`, each edit is version `id` — so an edit made after seeing another
    has it in its history, and two edits neither of which had seen the other were made
    concurrently. **That is what decides a conflict, not the HLC stamp.** A stamp gives
    every event a place in one order, which settles who wins an unimportant field, but
    two stamps cannot say whether one writer knew of the other.

    `set` replaces scalar fields; `add` and `remove` change set-like ones, and a set
    field is never replaced wholesale, or union would mean nothing. `edited_at` is the
    writer's clock, kept for a person reading the history and never used to order.
    """

    id: UUID
    record: UUID
    kind: str
    base: tuple
    edited_at: _dt.datetime
    set: dict = field(default_factory=dict)
    add: dict = field(default_factory=dict)
    remove: dict = field(default_factory=dict)
    edited_by: UUID | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.record, "record")
        _utc(self.edited_at, "edited_at")
        _opt_uuid7(self.edited_by, "edited_by")
        _text(self.reason, "reason", optional=True)
        cls = EDITABLE.get(self.kind)
        if cls is None:
            raise ValueError(f"{self.kind!r} is not an editable record "
                             f"(one of {sorted(EDITABLE)})")
        base = tuple(sorted(set(self.base), key=lambda u: u.int))
        if not base:
            raise ValueError("an edit names what its writer had seen; a record nobody "
                             "has seen cannot be edited")
        for b in base:
            _uuid7(b, "base")
        if self.id in base:
            raise ValueError("an edit cannot have seen itself")
        object.__setattr__(self, "base", base)
        names = set(field_names(cls))
        sets = cls.SETS
        for key in self.set:
            if key in IDENTITY:
                raise ValueError(f"{key} is a record's identity and is never edited")
            if key not in names:
                raise ValueError(f"{self.kind} has no field {key!r}")
            if key in sets:
                raise ValueError(f"{key} is set-like; add or remove elements instead, "
                                 "so concurrent edits merge (§7.4)")
        object.__setattr__(self, "set", dict(self.set))
        for label in ("add", "remove"):
            checked = {}
            for key, values in getattr(self, label).items():
                if key not in sets:
                    raise ValueError(f"{label} applies to set-like fields "
                                     f"({sorted(sets)}), not {key!r}")
                values = frozenset(values)
                if sets[key] == _SET_OF_UUIDS:
                    _uuid_set(values, key, nonempty=False)
                else:
                    _tags(values, key)
                if values:
                    checked[key] = values
            object.__setattr__(self, label, checked)
        if not (self.set or self.add or self.remove):
            raise ValueError("an edit changes something")


@dataclass(frozen=True, slots=True)
class ConflictNotice:
    """§7.4: "the conflict event is itself in the log."

    Projection finds a conflict on its own — two concurrent versions of a protected
    field that disagree — so this record is not what makes a conflict real. It is what
    makes one *noticed*: a subscriber (§7.5) wakes on it and asks a person, and the
    audit trail shows when the farm learned. Two replicas may each notice the same
    conflict before they sync; the projection treats notices with the same record,
    field and versions as one.
    """

    id: UUID
    record: UUID
    kind: str
    field: str
    versions: tuple
    noticed_at: _dt.datetime

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.record, "record")
        _utc(self.noticed_at, "noticed_at")
        cls = EDITABLE.get(self.kind)
        if cls is None or self.field not in cls.PROTECTED:
            raise ValueError("a conflict is on a protected field of an editable record "
                             "(Q14)")
        versions = tuple(sorted(set(self.versions), key=lambda u: u.int))
        if len(versions) < 2:
            raise ValueError("a conflict is between at least two versions")
        for v in versions:
            _uuid7(v, "versions")
        object.__setattr__(self, "versions", versions)

    @property
    def key(self) -> tuple:
        return (self.record, self.field, self.versions)
