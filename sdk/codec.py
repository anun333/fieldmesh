#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""JSON encoding for the contract types (spec v0.1 §7.1, §7.6).

The log is the authoritative copy (§7.1) and everything exports in open formats at
any time, with no fee and no support ticket (§7.6). Both need one encoding, and it
has to round-trip exactly — a log you cannot replay into identical records is not an
audit trail.

Explicit per-field converters rather than type-hint reflection: the hints in
`model.py` are strings under `from __future__ import annotations`, and resolving
them at runtime to drive decoding is both fragile and silent when it goes wrong.
A table is longer and cannot quietly mis-decode a field.

What this deliberately does *not* do is prune. §7.6: an export that carried only
calibrated values would be the silent cleaning this spec exists to prevent, so raw
observations, quality assertions and their threshold versions all encode the same
way and all come out.
"""
from __future__ import annotations

import datetime as _dt
from enum import Enum
from uuid import UUID

from model import (Assertor, Calibration, ClockQuality, Datastream,
                   DatastreamKind, Device, DeviceKind, Grant, GrantRevocation,
                   Installation, Label, MaintenanceAction, MaintenanceEvent, Observation,
                   QualityAssertion, QualityFlag, Threshold, Usable)
from records import (Animal, AnimalGroup, AnimalTreatment, ConflictNotice, EDITABLE,
                     HarvestLot, InputApplication, Land, LandKind, Quantity, RecordEdit)

TYPE_KEY = "_t"


# ------------------------------------------------------------------- scalars

def _enc_uuid(v):
    return None if v is None else str(v)


def _dec_uuid(v):
    return None if v is None else UUID(v)


def _enc_time(v):
    return None if v is None else v.isoformat().replace("+00:00", "Z")


def _dec_time(v):
    if v is None:
        return None
    s = v[:-1] + "+00:00" if v.endswith("Z") else v
    return _dt.datetime.fromisoformat(s)


def _enc_enum(v):
    return None if v is None else v.value


def _dec_enum(cls):
    return lambda v: None if v is None else cls(v)


def _enc_flags(v):
    return sorted(f.value for f in v)


def _dec_flags(v):
    return frozenset(QualityFlag(x) for x in v)


def _same(v):
    return v


def _enc_uuids(v):
    return [str(x) for x in v]


def _dec_uuids(v):
    return tuple(_dec_uuid(x) for x in v)


def _enc_uuid_set(v):
    return sorted(str(x) for x in v)


def _dec_uuid_set(v):
    return frozenset(UUID(x) for x in v)


def _enc_text_set(v):
    return sorted(v)


def _dec_text_set(v):
    return frozenset(v)


def _enc_qty(v):
    return None if v is None else {"value": v.value, "unit": v.unit}


def _dec_qty(v):
    return None if v is None else Quantity(v["value"], v["unit"])


# ----------------------------------------------------------- per-type tables

_CONVERTERS = {
    Datastream: {
        "id": (_enc_uuid, _dec_uuid),
        "thing": (_enc_uuid, _dec_uuid),
        "sensor": (_enc_uuid, _dec_uuid),
        "observed_property": (_same, _same),
        "feature": (_enc_uuid, _dec_uuid),
        "kind": (_enc_enum, _dec_enum(DatastreamKind)),
        "unit": (_same, _same),
        "derived_from": (_enc_uuid, _dec_uuid),
        "expected_interval": (_same, _same),
        "max_latency": (_same, _same),
        "thresholds": (_same, _same),
        "buffer_policy": (_same, _same),
        "window_s": (_same, _same),
        "probability_of": (_same, _same),
        "ensemble": (_same, _same),
    },
    Grant: {
        "id": (_enc_uuid, _dec_uuid),
        "grantee": (_same, _same),
        "datastreams": (_enc_uuids, _dec_uuids),
        "purpose": (_same, _same),
        "issued_at": (_enc_time, _dec_time),
        "until": (_enc_time, _dec_time),
        "includes_future": (_same, _same),
        "reshare": (_same, _same),
        "issued_by": (_enc_uuid, _dec_uuid),
    },
    GrantRevocation: {
        "id": (_enc_uuid, _dec_uuid),
        "grant": (_enc_uuid, _dec_uuid),
        "at": (_enc_time, _dec_time),
        "revoked_by": (_enc_uuid, _dec_uuid),
        "reason": (_same, _same),
    },
    Label: {
        "id": (_enc_uuid, _dec_uuid),
        "entity": (_enc_uuid, _dec_uuid),
        "name": (_same, _same),
        "set_at": (_enc_time, _dec_time),
        "language": (_same, _same),
        "description": (_same, _same),
        "set_by": (_enc_uuid, _dec_uuid),
        "supersedes": (_enc_uuid, _dec_uuid),
    },
    Device: {
        "id": (_enc_uuid, _dec_uuid),
        "kind": (_enc_enum, _dec_enum(DeviceKind)),
        "site": (_enc_uuid, _dec_uuid),
        "model": (_same, _same),
        "serial": (_same, _same),
        "manufacturer": (_same, _same),
        "firmware": (_same, _same),
        "driver": (_same, _same),
        "driver_version": (_same, _same),
        "capabilities": (_same, _same),
        "note": (_same, _same),
    },
    Installation: {
        "id": (_enc_uuid, _dec_uuid),
        "device": (_enc_uuid, _dec_uuid),
        "feature": (_enc_uuid, _dec_uuid),
        "installed_at": (_enc_time, _dec_time),
        "removed_at": (_enc_time, _dec_time),
        "depth_m": (_same, _same),
        "orientation_deg": (_same, _same),
        "installed_by": (_enc_uuid, _dec_uuid),
        "note": (_same, _same),
        "surface": (_same, _same),
    },
    MaintenanceEvent: {
        "id": (_enc_uuid, _dec_uuid),
        "device": (_enc_uuid, _dec_uuid),
        "at": (_enc_time, _dec_time),
        "action": (_enc_enum, _dec_enum(MaintenanceAction)),
        "performed_by": (_enc_uuid, _dec_uuid),
        "note": (_same, _same),
    },
    Calibration: {
        "id": (_enc_uuid, _dec_uuid),
        "sensor": (_enc_uuid, _dec_uuid),
        "method": (_same, _same),
        "valid_from": (_enc_time, _dec_time),
        "valid_to": (_enc_time, _dec_time),
        "reference": (_same, _same),
        "coefficients": (_same, _same),
        "performed_by": (_enc_uuid, _dec_uuid),
        "datastream": (_enc_uuid, _dec_uuid),
    },
    Observation: {
        "id": (_enc_uuid, _dec_uuid),
        "datastream": (_enc_uuid, _dec_uuid),
        "measured_at": (_enc_time, _dec_time),
        "measured_at_uncertainty": (_same, _same),
        "received_at": (_enc_time, _dec_time),
        "result": (_same, _same),
        "clock_quality": (_enc_enum, _dec_enum(ClockQuality)),
        "node": (_same, _same),
        "boot": (_same, _same),
        "seq": (_same, _same),
        "feature": (_enc_uuid, _dec_uuid),
        "calibration": (_enc_uuid, _dec_uuid),
        "supersedes": (_enc_uuid, _dec_uuid),
        "provenance": (_same, _same),
        "issued_at": (_enc_time, _dec_time),
    },
    Threshold: {
        "id": (_enc_uuid, _dec_uuid),
        "datastream": (_enc_uuid, _dec_uuid),
        "values": (_same, _same),
        "created_at": (_enc_time, _dec_time),
        "supersedes": (_enc_uuid, _dec_uuid),
    },
    QualityAssertion: {
        "id": (_enc_uuid, _dec_uuid),
        "observation": (_enc_uuid, _dec_uuid),
        "flags": (_enc_flags, _dec_flags),
        "usable": (_enc_enum, _dec_enum(Usable)),
        "check": (_same, _same),
        "asserted_at": (_enc_time, _dec_time),
        "assertor": (_enc_enum, _dec_enum(Assertor)),
        "check_version": (_same, _same),
        "threshold_version": (_enc_uuid, _dec_uuid),
        "assertor_id": (_enc_uuid, _dec_uuid),
        "supersedes": (_enc_uuid, _dec_uuid),
        "note": (_same, _same),
        "evidence": (_same, _same),
    },
    # ------------------------------------------- records (§3, §7.4; Q14)
    Land: {
        "id": (_enc_uuid, _dec_uuid),
        "site": (_enc_uuid, _dec_uuid),
        "kind": (_enc_enum, _dec_enum(LandKind)),
        "boundary": (_same, _same),
        "parent": (_enc_uuid, _dec_uuid),
        "archived": (_same, _same),
        "tags": (_enc_text_set, _dec_text_set),
    },
    Animal: {
        "id": (_enc_uuid, _dec_uuid),
        "site": (_enc_uuid, _dec_uuid),
        "species": (_same, _same),
        "tag": (_same, _same),
        "born": (_enc_time, _dec_time),
        "sex": (_same, _same),
        "archived": (_same, _same),
        "tags": (_enc_text_set, _dec_text_set),
    },
    AnimalGroup: {
        "id": (_enc_uuid, _dec_uuid),
        "site": (_enc_uuid, _dec_uuid),
        "members": (_enc_uuid_set, _dec_uuid_set),
        "archived": (_same, _same),
        "tags": (_enc_text_set, _dec_text_set),
    },
    InputApplication: {
        "id": (_enc_uuid, _dec_uuid),
        "site": (_enc_uuid, _dec_uuid),
        "applied_at": (_enc_time, _dec_time),
        "land": (_enc_uuids, _dec_uuids),
        "product": (_same, _same),
        "rate": (_enc_qty, _dec_qty),
        "area": (_enc_qty, _dec_qty),
        "method": (_same, _same),
        "purpose": (_same, _same),
        "registration": (_same, _same),
        "product_lot": (_same, _same),
        "preharvest_interval_days": (_same, _same),
        "reentry_interval_h": (_same, _same),
        "applied_by": (_enc_uuid, _dec_uuid),
        "note": (_same, _same),
        "void": (_same, _same),
        "tags": (_enc_text_set, _dec_text_set),
    },
    AnimalTreatment: {
        "id": (_enc_uuid, _dec_uuid),
        "site": (_enc_uuid, _dec_uuid),
        "administered_at": (_enc_time, _dec_time),
        "animals": (_enc_uuid_set, _dec_uuid_set),
        "product": (_same, _same),
        "dose": (_enc_qty, _dec_qty),
        "withdrawal_days": (_same, _same),
        "route": (_same, _same),
        "reason": (_same, _same),
        "registration": (_same, _same),
        "product_lot": (_same, _same),
        "administered_by": (_enc_uuid, _dec_uuid),
        "note": (_same, _same),
        "void": (_same, _same),
        "tags": (_enc_text_set, _dec_text_set),
    },
    HarvestLot: {
        "id": (_enc_uuid, _dec_uuid),
        "site": (_enc_uuid, _dec_uuid),
        "harvested_at": (_enc_time, _dec_time),
        "land": (_enc_uuids, _dec_uuids),
        "crop": (_same, _same),
        "quantity": (_enc_qty, _dec_qty),
        "lot": (_same, _same),
        "note": (_same, _same),
        "void": (_same, _same),
        "tags": (_enc_text_set, _dec_text_set),
    },
    # `set`, `add` and `remove` are encoded by the converters of the record the edit
    # names, so they are handled in dump() and load() rather than in this table.
    RecordEdit: {
        "id": (_enc_uuid, _dec_uuid),
        "record": (_enc_uuid, _dec_uuid),
        "kind": (_same, _same),
        "base": (_enc_uuids, _dec_uuids),
        "edited_at": (_enc_time, _dec_time),
        "edited_by": (_enc_uuid, _dec_uuid),
        "reason": (_same, _same),
    },
    ConflictNotice: {
        "id": (_enc_uuid, _dec_uuid),
        "record": (_enc_uuid, _dec_uuid),
        "kind": (_same, _same),
        "field": (_same, _same),
        "versions": (_enc_uuids, _dec_uuids),
        "noticed_at": (_enc_time, _dec_time),
    },
}

_BY_NAME = {cls.__name__: cls for cls in _CONVERTERS}


def dump_fields(kind: str, values: dict) -> dict:
    """Field values of an editable record, encoded as that record encodes them, so an
    edit's `set` reads back as the same types the record holds."""
    table = _CONVERTERS[EDITABLE[kind]]
    return {name: table[name][0](value) for name, value in values.items()}


def load_fields(kind: str, doc: dict) -> dict:
    table = _CONVERTERS[EDITABLE[kind]]
    out = {}
    for name, value in doc.items():
        if name not in table:
            raise ValueError(f"{kind} has no field {name!r}")
        out[name] = table[name][1](value)
    return out


#: Fields added after logs existed, written only when set — so every log line written
#: before them reads back, and is written again, byte for byte the same.
_OMIT_WHEN_NONE = {(Observation, "issued_at"), (Datastream, "window_s"), (Installation, "surface"),
                   (Datastream, "probability_of"), (Datastream, "ensemble")}


def dump(record) -> dict:
    """A contract record as a JSON-able dict, tagged with its type."""
    table = _CONVERTERS.get(type(record))
    if table is None:
        raise TypeError(f"no encoding for {type(record).__name__}")
    out = {TYPE_KEY: type(record).__name__}
    for name, (enc, _) in table.items():
        value = getattr(record, name)
        if value is None and (type(record), name) in _OMIT_WHEN_NONE:
            continue
        out[name] = enc(value)
    if isinstance(record, RecordEdit):
        out["set"] = dump_fields(record.kind, record.set)
        out["add"] = dump_fields(record.kind, record.add)
        out["remove"] = dump_fields(record.kind, record.remove)
    return out


def load(doc: dict):
    """Rebuild a contract record from `dump` output.

    The constructor validates, so a decoded record is as legal as a constructed
    one — a log line that violates the spec fails on replay rather than becoming
    state nobody checked.
    """
    name = doc.get(TYPE_KEY)
    cls = _BY_NAME.get(name)
    if cls is None:
        raise ValueError(f"unknown record type {name!r}")
    table = _CONVERTERS[cls]
    kwargs = {}
    for field_name, (_, dec) in table.items():
        if field_name in doc:
            kwargs[field_name] = dec(doc[field_name])
    if cls is RecordEdit:
        for part in ("set", "add", "remove"):
            kwargs[part] = load_fields(kwargs["kind"], doc.get(part, {}))
    return cls(**kwargs)


def jsonable(value):
    """Best-effort encoding for free-form payloads (provenance, coefficients).

    Used for the parts of an event payload that are not contract records.
    """
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, _dt.datetime):
        return _enc_time(value)
    return value
