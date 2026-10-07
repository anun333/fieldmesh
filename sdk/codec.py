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
                   DatastreamKind, Observation, QualityAssertion, QualityFlag,
                   Threshold, Usable)

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
}

_BY_NAME = {cls.__name__: cls for cls in _CONVERTERS}


def dump(record) -> dict:
    """A contract record as a JSON-able dict, tagged with its type."""
    table = _CONVERTERS.get(type(record))
    if table is None:
        raise TypeError(f"no encoding for {type(record).__name__}")
    out = {TYPE_KEY: type(record).__name__}
    for name, (enc, _) in table.items():
        out[name] = enc(getattr(record, name))
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
