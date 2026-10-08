#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The layer-zero contract as code (spec v0.1 §1–§4).

Every type here is **frozen**. That is not a style preference: §3.2 says an
observation is written once and never altered, and §3.3 moved quality off the
observation for the same reason. A mutable dataclass would let a caller do the one
thing the spec forbids, and the append-only log in `log.py` could not detect it.
Corrections are new records (§7.3); re-derivations supersede (§3.2); quality
judgements are separate assertions (§3.3).

The constructors reject what the spec forbids, so a violation fails at the boundary
rather than becoming a bad row somebody has to explain a season later:

* UTC-aware timestamps only (§2 "everything is stored in UTC")
* `measured_at_uncertainty` present and non-zero (§2)
* `seq` within uint16, `boot` non-negative (§1)
* a `raw` datastream has no `derived_from`; a `derived` one must have it (§3.1)
* a raw observation carries no calibration and is never superseded (§3.2)
* a derived observation must name the calibration that produced it (§3.2)
* `usable` agrees with `flags` unless a person overrode it (§3.3)

Cross-object rules need both objects, so they live in `Observation.validate_against`
rather than in `__post_init__`.

Note: these are value types compared with `==`. They hold plain dicts for the
open-ended fields (`thresholds`, `provenance`, `coefficients`, `buffer_policy`), so
hashing an instance raises — key collections by `.id`, which is the identity the
spec actually uses.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID

from ids import is_uuid7

UTC = _dt.timezone.utc


# ---------------------------------------------------------------- enumerations

class ClockQuality(str, Enum):
    """§2. A category, not a bound — the bound is `measured_at_uncertainty`."""

    GPS = "gps"
    NETWORK = "network"
    RTC_SYNCED = "rtc_synced"
    RTC_UNSYNCED = "rtc_unsynced"
    NONE = "none"


class DatastreamKind(str, Enum):
    RAW = "raw"
    DERIVED = "derived"


class QualityFlag(str, Enum):
    """§3.3. A *set* of these, not one of them.

    `stale` is deliberately absent: §4.2 makes staleness a datastream state,
    because flagging a reading would mean mutating a record that was correct when
    written, on the evidence of a later reading that never arrived. Device
    warnings are absent for the same kind of reason (§4.3) — battery is a
    property of a device, and belongs in its own datastream.
    """

    SUSPECT = "suspect"
    STUCK = "stuck"
    OUT_OF_RANGE = "out_of_range"
    RATE_EXCEEDED = "rate_exceeded"


class Usable(str, Enum):
    GOOD = "good"
    QUESTIONABLE = "questionable"
    BAD = "bad"


class Assertor(str, Enum):
    FOUNDATION = "foundation"
    PERSON = "person"


class DeviceKind(str, Enum):
    """§4.1, §8.1. What a registered thing physically is.

    `SENSOR` is the kind `Datastream.sensor` points at. That field was a bare UUID
    with no record behind it until §4.1 was built, which is why a probe could be
    moved between beds with nothing recording that it had happened.
    """

    NODE = "node"
    SENSOR = "sensor"
    GATEWAY = "gateway"


class MaintenanceAction(str, Enum):
    """§4.1's maintenance log, with exactly the four actions the spec names.

    Closed on purpose. A vocabulary that grows by whoever needs a word next is how
    a log becomes unqueryable, so a missing action is a **spec** change rather than
    a code change — and there is at least one missing. A battery replacement on a
    solar or primary-cell node is a real field event that explains a step
    discontinuity in the §4.3 battery datastream, and none of these four covers it.
    Recorded as Q22 rather than quietly added here.
    """

    CLEANED = "cleaned"
    MOVED = "moved"
    REPLACED = "replaced"
    RECALIBRATED = "recalibrated"


#: §3.3 precedence: a person outranks the foundation.
ASSERTOR_PRECEDENCE: dict[Assertor, int] = {Assertor.FOUNDATION: 0, Assertor.PERSON: 1}

_BAD_FLAGS = frozenset({QualityFlag.STUCK, QualityFlag.OUT_OF_RANGE})


def derive_usable(flags) -> Usable:
    """The canonical §3.3 summary: `bad` if stuck or out of range, `questionable`
    if only suspect or rate-exceeded, `good` if nothing is flagged.

    One function, so two implementations cannot disagree on the same input — which
    is the whole reason the flag set has a summary at all.
    """
    flags = frozenset(flags)
    if flags & _BAD_FLAGS:
        return Usable.BAD
    if flags:
        return Usable.QUESTIONABLE
    return Usable.GOOD


# ------------------------------------------------------------------ validators

def _uuid7(value, name: str) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID, got {type(value).__name__}")
    if not is_uuid7(value):
        raise ValueError(f"{name} must be a UUIDv7 (§1), got version {value.version}")
    return value


def _opt_uuid7(value, name: str):
    return None if value is None else _uuid7(value, name)


def _utc(value, name: str) -> _dt.datetime:
    if not isinstance(value, _dt.datetime):
        raise TypeError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware and UTC (§2); got naive")
    if value.utcoffset() != _dt.timedelta(0):
        raise ValueError(f"{name} must be UTC (§2); got offset {value.utcoffset()}")
    return value


# --------------------------------------------------------------------- records

@dataclass(frozen=True, slots=True)
class Datastream:
    """§3.1. One sensor, one observed property, one unit, on one Thing.

    The 2.0 SensorThings draft allows several observed properties per datastream;
    one is a subset of that, so this maps unchanged to 1.1 and to 2.0.

    `feature` lives here rather than on each observation because for a fixed
    installed sensor it never changes (§3.1).

    `expected_interval` and `max_latency` are deliberately separate: the first is
    how often this series is sampled and drives staleness (§4.2); the second is
    how stale a reading may be when it reaches the gateway, and it is the one
    that spends the battery, because a node's transmit interval is the tightest
    `max_latency` it carries (§5.3.1). Reading a sensor is under 2% of a node's
    energy; the radio is the rest.
    """

    id: UUID
    thing: UUID
    sensor: UUID
    observed_property: str          # a vocabulary URI, never free text (§3.4)
    feature: UUID
    kind: DatastreamKind
    unit: str | None = None         # UCUM code; None for a boolean or state (§3.4)
    derived_from: UUID | None = None
    expected_interval: float | None = None   # seconds; drives staleness (§4.2)
    max_latency: float | None = None         # seconds; drives the transmit
                                             # schedule and the battery (§5.3.1)
    thresholds: dict = field(default_factory=dict)
    buffer_policy: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.thing, "thing")
        _uuid7(self.sensor, "sensor")
        _uuid7(self.feature, "feature")
        _opt_uuid7(self.derived_from, "derived_from")
        if not isinstance(self.kind, DatastreamKind):
            raise TypeError("kind must be a DatastreamKind")
        if not self.observed_property or "://" not in str(self.observed_property):
            raise ValueError(
                "observed_property must be a vocabulary URI, not free text (§3.4)")
        if self.kind is DatastreamKind.RAW and self.derived_from is not None:
            raise ValueError("a raw datastream has no derived_from (§3.1)")
        if self.kind is DatastreamKind.DERIVED and self.derived_from is None:
            raise ValueError("a derived datastream must name its derived_from (§3.1)")
        if self.derived_from == self.id:
            raise ValueError("a datastream cannot derive from itself")
        if self.expected_interval is not None and self.expected_interval <= 0:
            raise ValueError("expected_interval must be positive")
        if self.max_latency is not None and self.max_latency <= 0:
            raise ValueError("max_latency must be positive")


#: A BCP 47 tag, loosely: a primary language subtag and optional subtags.
_LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


@dataclass(frozen=True, slots=True)
class Label:
    """§1. A human name for an entity — separate from its identity, and editable.

    "Labels are not keys" is the whole of what v0.1 said, and it left the label with
    nowhere to live: a simulator helper handed names to the SensorThings view as a side
    table, and a real farm had no way to name anything at all. QGIS showed what that
    costs — a legend of bare UUIDs is unusable for the one job a map has.

    **A rename appends; it does not overwrite.** A label superseding another keeps the
    old one in history, because names appear in places that outlive them: a certifier's
    report from last spring says "north bed", and the question "which entity was that?"
    must still have an answer after the bed is renamed. `State.entities_named` answers
    it.

    **One label per entity per language.** Layer 4 must be bilingual (§11), so
    `language` is a BCP 47 tag and an entity can carry an English and a Spanish name
    side by side. A missing translation falls back, and the caller is told which
    language it actually got rather than being handed English while asking for Spanish.
    """

    id: UUID
    entity: UUID
    name: str
    set_at: _dt.datetime
    language: str = "en"
    description: str | None = None
    set_by: UUID | None = None
    supersedes: UUID | None = None

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.entity, "entity")
        _opt_uuid7(self.set_by, "set_by")
        _opt_uuid7(self.supersedes, "supersedes")
        _utc(self.set_at, "set_at")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("a label needs a name — an empty one is not a name (§1)")
        if self.name != self.name.strip():
            raise ValueError("a label's name must not carry leading or trailing "
                             "whitespace; 'north bed ' and 'north bed' would be two "
                             "names for one thing")
        if not _LANGUAGE.match(self.language or ""):
            raise ValueError(f"language must be a BCP 47 tag such as 'en' or "
                             f"'es-MX', got {self.language!r}")
        if self.supersedes == self.id:
            raise ValueError("a label cannot supersede itself")


@dataclass(frozen=True, slots=True)
class Device:
    """§4.1 and §8.1. A registered physical device: the durable half.

    **§4.1 describes a view, not a record.** Read literally it says a device record
    holds "last seen, and the current boot counter" — and a record in an append-only
    log cannot hold *current* anything without being mutated, which §3.2 forbids for
    exactly the reasons that apply here. So §4.1 decomposes into three records and a
    projection:

    * this `Device` — identity, hardware, firmware and declared capabilities;
    * `Installation` — where it is, how deep, facing where, from when until when;
    * `MaintenanceEvent` — what was done to it and by whom;
    * and `project.device_view`, which derives last seen and the current boot counter
      from the readings themselves, because those are observations about the device
      rather than claims it makes about itself.

    `capabilities` is the §8 driver manifest as declared. It is an open dict like
    `thresholds`, because the manifest is the driver's vocabulary and not ours, but
    the three capabilities layer zero actually branches on get named accessors — an
    undeclared capability must read as **unknown**, never as a convenient default.
    `§6.3` turns on precisely this: a node that cannot persist its dedup table across
    a reboot has to say so.
    """

    id: UUID
    kind: DeviceKind
    site: UUID
    model: str | None = None
    serial: str | None = None
    manufacturer: str | None = None
    firmware: str | None = None
    driver: str | None = None
    driver_version: str | None = None
    capabilities: dict = field(default_factory=dict)
    note: str | None = None

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.site, "site")
        if not isinstance(self.kind, DeviceKind):
            raise TypeError("kind must be a DeviceKind")

    @property
    def dedup_volatile(self) -> bool | None:
        """§6.3. `None` means the driver never said, which is not the same as `False`."""
        return self.capabilities.get("dedup_volatile")

    @property
    def confirms_delivery(self) -> bool | None:
        """§5.4. Whether the link tells the node its frame arrived."""
        return self.capabilities.get("confirms_delivery")

    @property
    def safe_states(self) -> dict:
        """§8's declared safe states, empty when undeclared."""
        value = self.capabilities.get("safe_states")
        return value if isinstance(value, dict) else {}

    def provenance(self) -> dict:
        """What §3.2 wants stamped on a reading so a derivation is reproducible."""
        out = {}
        for key in ("firmware", "driver", "driver_version"):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out


@dataclass(frozen=True, slots=True)
class Installation:
    """§4.1. Where a device is, with dates. Closed by re-appending with `removed_at`.

    The same shape as `Calibration` and for the same reason: a question like "how deep
    was this probe when it took that reading" is unanswerable without knowing what was
    in force *then*, and a field that is overwritten on every move cannot answer it at
    all. `removed_at = None` means still installed.

    `depth_m` is positive downwards from the surface, because every soil reference does
    it that way and a sign convention nobody states is a sign convention somebody gets
    wrong. `orientation_deg` is a compass azimuth; both are numbers rather than prose
    so that a wrong one can be caught.
    """

    id: UUID
    device: UUID
    feature: UUID
    installed_at: _dt.datetime
    removed_at: _dt.datetime | None = None
    depth_m: float | None = None
    orientation_deg: float | None = None
    installed_by: UUID | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.device, "device")
        _uuid7(self.feature, "feature")
        _opt_uuid7(self.installed_by, "installed_by")
        _utc(self.installed_at, "installed_at")
        if self.removed_at is not None:
            _utc(self.removed_at, "removed_at")
            if self.removed_at <= self.installed_at:
                raise ValueError("removed_at must be after installed_at")
        if self.depth_m is not None and self.depth_m < 0:
            raise ValueError(
                "depth_m is positive downwards from the surface (§4.1); a sensor "
                "above ground is an orientation, not a negative depth")
        if self.orientation_deg is not None and not 0 <= self.orientation_deg < 360:
            raise ValueError("orientation_deg is a compass azimuth in [0, 360)")

    def covers(self, when: _dt.datetime) -> bool:
        """Half-open [installed_at, removed_at), so two installations never both
        apply to one instant."""
        _utc(when, "when")
        if when < self.installed_at:
            return False
        return self.removed_at is None or when < self.removed_at


@dataclass(frozen=True, slots=True)
class MaintenanceEvent:
    """§4.1's maintenance log. Accumulates, like an observation — never replaced.

    `note` is where the human detail goes, but the `action` is what makes the log
    queryable: "when was this probe last cleaned" is a question a certifier asks, and
    it cannot be answered by grepping prose.
    """

    id: UUID
    device: UUID
    at: _dt.datetime
    action: MaintenanceAction
    performed_by: UUID | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.device, "device")
        _opt_uuid7(self.performed_by, "performed_by")
        _utc(self.at, "at")
        if not isinstance(self.action, MaintenanceAction):
            raise TypeError("action must be a MaintenanceAction")


@dataclass(frozen=True, slots=True)
class Calibration:
    """§4.1. Carries a validity interval, because §3.2 selects calibration by
    `measured_at` and that is unanswerable without knowing what was in force when.

    `valid_to = None` means "still in force".

    **`datastream` scopes it to one raw channel.** A device with one channel needs
    nothing more, and `None` keeps that case — a calibration for the whole sensor.
    But a TEROS-12 reports moisture and temperature from one body, and a multi-depth
    probe can report six moistures. Selected by sensor alone, the two calibrations
    on a TEROS-12 competed, the later one won for both, and every moisture reading on
    twelve probes was derived with the temperature coefficients — 29.2 cm3/cm3 for a
    soil holding 0.292. `validate` reported the overlap; nothing in ingest asked it.
    """

    id: UUID
    sensor: UUID
    method: str
    valid_from: _dt.datetime
    valid_to: _dt.datetime | None = None
    reference: str | None = None
    coefficients: dict = field(default_factory=dict)
    performed_by: UUID | None = None
    datastream: UUID | None = None

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.sensor, "sensor")
        _opt_uuid7(self.performed_by, "performed_by")
        _opt_uuid7(self.datastream, "datastream")
        _utc(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _utc(self.valid_to, "valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("valid_to must be after valid_from")

    def covers(self, when: _dt.datetime) -> bool:
        """Half-open [valid_from, valid_to), so adjacent calibrations never both
        apply to one instant."""
        _utc(when, "when")
        if when < self.valid_from:
            return False
        return self.valid_to is None or when < self.valid_to


@dataclass(frozen=True, slots=True)
class Observation:
    """§3.2. Written once, never altered.

    `node`, `boot` and `seq` ride along because §2's ordering rule needs them: a
    node's own counter is authoritative for its own readings even when its clock
    is not.
    """

    id: UUID
    datastream: UUID
    measured_at: _dt.datetime
    measured_at_uncertainty: float          # seconds, half-width (§2)
    received_at: _dt.datetime
    result: float | int | str | bool | None
    clock_quality: ClockQuality
    node: str | None = None
    boot: int | None = None
    seq: int | None = None
    feature: UUID | None = None             # override; None = the datastream's (§3.1)
    calibration: UUID | None = None
    supersedes: UUID | None = None
    provenance: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.datastream, "datastream")
        _opt_uuid7(self.feature, "feature")
        _opt_uuid7(self.calibration, "calibration")
        _opt_uuid7(self.supersedes, "supersedes")
        _utc(self.measured_at, "measured_at")
        _utc(self.received_at, "received_at")
        if not isinstance(self.clock_quality, ClockQuality):
            raise TypeError("clock_quality must be a ClockQuality")
        u = self.measured_at_uncertainty
        if not isinstance(u, (int, float)) or isinstance(u, bool):
            raise TypeError("measured_at_uncertainty must be a number (§2)")
        if u <= 0:
            raise ValueError(
                "measured_at_uncertainty is mandatory and never zero (§2); "
                "a timestamp nobody can bound is unusable to a research logger")
        if self.seq is not None and not 0 <= self.seq <= 0xFFFF:
            raise ValueError("seq is uint16 (§1)")
        if self.boot is not None and self.boot < 0:
            raise ValueError("boot must not be negative (§1)")
        if self.supersedes == self.id:
            raise ValueError("an observation cannot supersede itself")

    @property
    def node_order(self) -> tuple[int, int] | None:
        """`(boot, seq)` when known — authoritative within one node (§2)."""
        if self.boot is None or self.seq is None:
            return None
        return (self.boot, self.seq)

    def interval(self) -> tuple[_dt.datetime, _dt.datetime]:
        """The window `measured_at` is known to lie in (§2)."""
        half = _dt.timedelta(seconds=self.measured_at_uncertainty)
        return (self.measured_at - half, self.measured_at + half)

    def effective_feature(self, datastream: Datastream) -> UUID:
        """The observation's own feature, else the datastream's (§3.1)."""
        return self.feature if self.feature is not None else datastream.feature

    def validate_against(self, datastream: Datastream) -> None:
        """The §3.2 rules that need the datastream to check."""
        if datastream.id != self.datastream:
            raise ValueError("datastream mismatch")
        if datastream.kind is DatastreamKind.RAW:
            if self.calibration is not None:
                raise ValueError(
                    "a raw observation carries no calibration — raw is what the "
                    "node sent (§3.2)")
            if self.supersedes is not None:
                raise ValueError(
                    "a raw observation is never superseded; it is the archival "
                    "truth (§3.2)")
        elif self.calibration is None:
            raise ValueError(
                "a derived observation must name the calibration that produced "
                "it (§3.2)")


@dataclass(frozen=True, slots=True)
class Threshold:
    """§4.2. Versioned, so an assertion can name the version it used and a retune
    cannot silently re-flag history."""

    id: UUID
    datastream: UUID
    values: dict = field(default_factory=dict)
    created_at: _dt.datetime | None = None
    supersedes: UUID | None = None

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.datastream, "datastream")
        _opt_uuid7(self.supersedes, "supersedes")
        if self.created_at is not None:
            _utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class QualityAssertion:
    """§3.3. A claim about an observation, by a named assessment, under a named
    threshold version, at a stated time — never a column on the observation.

    A person's override is a new assertion with `assertor = PERSON`, and the
    machine's original stays visible.

    **`check` names an assessment run, not a single check**, and `flags` carries
    the union of everything that fired in it. This resolves an ambiguity in the
    spec as written: §4.2 lists four checks that each produce one flag, while
    §3.3 makes `flags` a set *and* has precedence select exactly one live
    assertion. If each check wrote its own assertion, two firing at once would
    mean one silently wins and the other's flag disappears — the precise kind of
    silent loss this model exists to prevent. One assertion per run, carrying the
    union, is the only reading under which §3.3's precedence rule is coherent.

    `evidence` then records which individual checks fired and why, so collapsing
    them into one assertion loses no provenance. It is additive and optional;
    whether it should be normative is open (see the spec's open questions).
    """

    id: UUID
    observation: UUID
    flags: frozenset
    usable: Usable
    check: str
    asserted_at: _dt.datetime
    assertor: Assertor = Assertor.FOUNDATION
    check_version: str | None = None
    threshold_version: UUID | None = None
    assertor_id: UUID | None = None
    supersedes: UUID | None = None
    note: str | None = None
    evidence: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _uuid7(self.id, "id")
        _uuid7(self.observation, "observation")
        _opt_uuid7(self.threshold_version, "threshold_version")
        _opt_uuid7(self.assertor_id, "assertor_id")
        _opt_uuid7(self.supersedes, "supersedes")
        _utc(self.asserted_at, "asserted_at")
        if not isinstance(self.assertor, Assertor):
            raise TypeError("assertor must be an Assertor")
        if not isinstance(self.usable, Usable):
            raise TypeError("usable must be a Usable")
        flags = frozenset(self.flags)
        for f in flags:
            if not isinstance(f, QualityFlag):
                raise TypeError(f"flags must contain QualityFlag, got {f!r}")
        object.__setattr__(self, "flags", flags)
        if not self.check:
            raise ValueError("check must name the check that produced this (§3.3)")
        # The foundation must be self-consistent; only a person may disagree with
        # the derivation, and then the disagreement is the point (§3.3).
        if self.assertor is Assertor.FOUNDATION:
            expected = derive_usable(flags)
            if self.usable is not expected:
                raise ValueError(
                    f"usable={self.usable.value} contradicts flags "
                    f"{sorted(f.value for f in flags)} (expected "
                    f"{expected.value}); only a person may override (§3.3)")
        if self.supersedes == self.id:
            raise ValueError("an assertion cannot supersede itself")

    @property
    def precedence(self) -> int:
        return ASSERTOR_PRECEDENCE[self.assertor]
