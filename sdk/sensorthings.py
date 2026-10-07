#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""OGC SensorThings API out-adapter (spec v0.1 §10, §2, §3.2, §3.3).

The promise this keeps is "existing tools in both ecosystems work on day one", and
the clause it exists to honour is §3.2: **only live observations are served.** A
recalibrated series holds both the old and the new row forever, and a client that
saw both would get two observations at one `phenomenonTime` — doubling every chart
and breaking the compatibility claim on the most ordinary maintenance event there
is. `Service.observations()` serves `project.live_observations`, never raw history.

Ship on 1.1 (published; `resultQuality` exists), serve 2.0 alongside once it
publishes. That is why every version-dependent name is a class attribute on a
`Dialect` rather than a literal: the 2.0 draft renames `@iot.id` to `id`,
`@iot.selfLink` to `@id`, `parameters` to `properties`, and drops `resultQuality`
entirely. Keeping those in one table is what makes §10's "one thin layer" true
rather than aspirational, and it is the reason nothing in `model.py` knows what
SensorThings is.

Two mapping decisions worth stating, because both could reasonably go the other way:

**Layer-zero fields are namespaced under `parameters/librefarm`.** 1.1 documents
`parameters` as "key-value pairs showing the environmental conditions during
measurement". `received_at`, `seq`, `boot` and `clock_quality` are not that, and
scattering them at the top level would both misrepresent them and collide with a
legitimate use. Nesting keeps `$filter` working — `parameters/librefarm/clock_quality
eq 'none'` is a valid path — and reduces the 2.0 migration to one key.

**`resultTime` is null.** 1.1 makes it mandatory-but-nullable, and it means "when
the result was generated", which layer zero does not record. `received_at` is a
different thing (when the gateway got it) and claiming it as `resultTime` would be
a small lie in a field researchers read. Null is the honest encoding, and 1.1
explicitly provides for it.

`resultQuality` is emitted whenever an assertion exists, **including a clean one**,
and omitted only when nothing has been asserted. §3.3's empty flag set is a
judgement — "checked, no objection" — and collapsing it into "not checked" would
throw away the distinction a certifier cares about.
"""
from __future__ import annotations

import datetime as _dt
from uuid import UUID

import project as P
from model import Datastream, Observation, QualityAssertion

OM = "http://www.opengis.net/def/observationType/OGC-OM/2.0/"
UCUM_DEFINITION = "http://unitsofmeasure.org/ucum.html"

#: §3.4 units are UCUM codes; 1.1's `unitOfMeasurement` wants a name and symbol
#: too, and inventing a prose name for every code is worse than repeating it.
#: A label registry supplies better ones when it exists.
_OBSERVATION_TYPES = {
    bool: OM + "OM_TruthObservation",
    int: OM + "OM_CountObservation",
    float: OM + "OM_Measurement",
    str: OM + "OM_CategoryObservation",
}
ANY_OBSERVATION = OM + "OM_Observation"


def observation_type(result) -> str:
    """The O&M value code for a result (1.1 Table 12).

    `bool` is checked before `int` deliberately — in Python a bool *is* an int,
    and a truth observation typed as a count would be wrong.
    """
    if isinstance(result, bool):
        return _OBSERVATION_TYPES[bool]
    for py_type, uri in _OBSERVATION_TYPES.items():
        if py_type is not bool and isinstance(result, py_type):
            return uri
    return ANY_OBSERVATION


def iso(when: _dt.datetime) -> str:
    """ISO 8601 with a `Z`, which is what every STA example uses."""
    return when.isoformat().replace("+00:00", "Z")


class Dialect:
    """Version-dependent names. Subclass; do not branch on a version string."""

    version = "1.1"
    base_path = "/v1.1"
    id_key = "@iot.id"
    self_key = "@iot.selfLink"
    nav_suffix = "@iot.navigationLink"
    count_key = "@iot.count"
    value_key = "value"
    extras_key = "parameters"          # 2.0 draft: "properties"
    quality_key = "resultQuality"      # 2.0 draft: absent entirely
    feature_set = "FeaturesOfInterest"
    feature_link = "FeatureOfInterest"
    supports_quality = True


class SensorThings11(Dialect):
    """OGC 18-088, published. The default, per §10."""


class SensorThings20Draft(Dialect):
    """OGC 23-019, **unpublished draft** — names from the version read 2026-10-07.

    Provided to prove the seam, not for production. `supports_quality` is False
    because Table 17 has no `resultQuality`, so quality falls back into the
    extras object; see docs/notes/sensorthings-2.0.md and open-questions Q18.
    """

    version = "2.0"
    base_path = "/v2.0"
    id_key = "id"
    self_key = "@id"
    nav_suffix = "@navigationLink"
    extras_key = "properties"
    feature_set = "Features"
    supports_quality = False


class Service:
    """A read-only SensorThings view over derived state (§7.1).

    `labels` maps an entity id to `{"name": ..., "description": ...}`. §1 keeps
    human names out of the keys, and layer zero has no label registry yet, so
    anything unlabelled falls back to its id — legible, stable, and obviously a
    placeholder rather than an invented name.
    """

    __slots__ = ("state", "base_url", "dialect", "labels", "interval_times")

    def __init__(self, state: P.State, base_url: str = "http://localhost:8080",
                 *, dialect: type[Dialect] = SensorThings11,
                 labels: dict | None = None,
                 interval_times: bool = False):
        self.state = state
        self.base_url = base_url.rstrip("/")
        self.dialect = dialect
        self.labels = labels or {}
        #: When true, `phenomenonTime` is emitted as the §2 uncertainty window
        #: rather than an instant. Standards-native honesty — a client sees the
        #: bound directly — but many clients assume an instant, so it is opt-in.
        self.interval_times = interval_times

    # ------------------------------------------------------------- helpers

    def _root(self) -> str:
        return self.base_url + self.dialect.base_path

    def _link(self, entity_set: str, ident: UUID) -> str:
        return f"{self._root()}/{entity_set}({ident})"

    def _label(self, ident: UUID, field: str, fallback: str) -> str:
        return self.labels.get(ident, {}).get(field) or fallback

    def _control(self, entity_set: str, ident: UUID) -> dict:
        d = self.dialect
        return {d.id_key: str(ident), d.self_key: self._link(entity_set, ident)}

    def _navs(self, entity_set: str, ident: UUID, *roles: str) -> dict:
        d = self.dialect
        base = self._link(entity_set, ident)
        return {f"{role}{d.nav_suffix}": f"{base}/{role}" for role in roles}

    def collection(self, items: list) -> dict:
        d = self.dialect
        return {d.count_key: len(items), d.value_key: list(items)}

    # ------------------------------------------------------------ entities

    def thing(self, ident: UUID) -> dict:
        doc = self._control("Things", ident)
        doc["name"] = self._label(ident, "name", str(ident))
        doc["description"] = self._label(ident, "description",
                                         "A thing layer zero observes")
        doc["properties"] = {}
        doc.update(self._navs("Things", ident, "Datastreams", "Locations"))
        return doc

    def sensor(self, ident: UUID) -> dict:
        doc = self._control("Sensors", ident)
        doc["name"] = self._label(ident, "name", str(ident))
        doc["description"] = self._label(ident, "description", "A sensor")
        # 1.1 requires both; a driver manifest (§9.1) will supply something
        # better than this placeholder when it exists.
        doc["encodingType"] = "application/pdf"
        doc["metadata"] = self._label(ident, "metadata", str(ident))
        doc.update(self._navs("Sensors", ident, "Datastreams"))
        return doc

    def observed_property(self, uri: str) -> dict:
        """§3.4 observed properties are vocabulary URIs, so the URI *is* the
        identity — there is no separate UUID to mint."""
        doc = {self.dialect.id_key: uri,
               self.dialect.self_key: f"{self._root()}/ObservedProperties('{uri}')"}
        doc["name"] = self._label(uri, "name", uri.rsplit("/", 1)[-1])
        doc["definition"] = uri
        doc["description"] = self._label(uri, "description", uri)
        return doc

    def feature_of_interest(self, ident: UUID) -> dict:
        doc = self._control(self.dialect.feature_set, ident)
        doc["name"] = self._label(ident, "name", str(ident))
        doc["description"] = self._label(ident, "description",
                                         "A field, bed, tank or animal")
        doc["encodingType"] = "application/geo+json"
        doc["feature"] = self.labels.get(ident, {}).get("feature")
        return doc

    def unit_of_measurement(self, ds: Datastream) -> dict | None:
        """1.1: a JSON object of name, symbol and definition, whose values SHOULD
        follow UCUM. §3.4: null unit for a boolean or state, and 1.1 says those
        properties SHALL then be null."""
        if ds.unit is None:
            return {"name": None, "symbol": None, "definition": None}
        return {
            "name": self._label(ds.id, "unit_name", ds.unit),
            "symbol": ds.unit,
            "definition": UCUM_DEFINITION,
        }

    def datastream(self, ds: Datastream) -> dict:
        """One layer-zero datastream as one STA Datastream.

        The raw/derived split in §3.2 therefore surfaces as *two* Datastreams per
        point, which is the honest mapping: a client that wants archival values
        reads one, a client that wants usable values reads the other, and both are
        ordinary Datastreams rather than a convention a client has to know about.
        """
        kind = ds.kind.value
        doc = self._control("Datastreams", ds.id)
        doc["name"] = self._label(ds.id, "name", f"{ds.observed_property} ({kind})")
        doc["description"] = self._label(
            ds.id, "description",
            f"{kind} series for observed property {ds.observed_property}")
        doc["unitOfMeasurement"] = self.unit_of_measurement(ds)
        doc["observationType"] = self._datastream_observation_type(ds)
        extent = self._phenomenon_extent(ds.id)
        doc["phenomenonTime"] = extent
        doc["resultTime"] = None
        doc["properties"] = {
            "kind": kind,
            "derived_from": str(ds.derived_from) if ds.derived_from else None,
            "expected_interval_s": ds.expected_interval,
            "thresholds": dict(ds.thresholds),
            "health": self._health(ds).value,
        }
        doc.update(self._navs("Datastreams", ds.id, "Thing", "Sensor",
                              "ObservedProperty", "Observations"))
        return doc

    def observation(self, obs: Observation, ds: Datastream | None = None,
                    *, expand: tuple[str, ...] = ()) -> dict:
        """One observation. `expand` inlines related entities the way STA's
        `$expand` does — `("FeatureOfInterest",)` is the useful one, because
        §3.1 resolves the feature per observation (the datastream's, unless the
        observation overrides it for a handheld reading or a sample)."""
        d = self.dialect
        ds = ds if ds is not None else self.state.datastreams[obs.datastream]
        doc = self._control("Observations", obs.id)
        doc["phenomenonTime"] = self._phenomenon_time(obs)
        doc["result"] = obs.result
        doc["resultTime"] = None          # see the module docstring
        extras = {
            "measured_at_uncertainty_s": obs.measured_at_uncertainty,
            "received_at": iso(obs.received_at),
            "clock_quality": obs.clock_quality.value,
            "node": obs.node,
            "boot": obs.boot,
            "seq": obs.seq,
            "calibration": str(obs.calibration) if obs.calibration else None,
            "supersedes": str(obs.supersedes) if obs.supersedes else None,
            "provenance": dict(obs.provenance),
        }
        assertion = P.live_assertion(self.state.assertions, obs.id)
        if assertion is not None:
            quality = [_quality_element(assertion)]
            if d.supports_quality:
                doc[d.quality_key] = quality
            else:
                # 2.0 drops resultQuality (Table 17). Nothing standards-aware
                # will look here, which is the argument in Q18.
                extras["result_quality"] = quality
        doc[d.extras_key] = {"librefarm": extras}
        doc[f"{d.feature_link}{d.nav_suffix}"] = (
            f"{self._link('Observations', obs.id)}/{d.feature_link}")
        doc[f"Datastream{d.nav_suffix}"] = (
            f"{self._link('Observations', obs.id)}/Datastream")
        if d.feature_link in expand:
            doc[d.feature_link] = self.feature_of_interest(
                obs.effective_feature(ds))
        if "Datastream" in expand:
            doc["Datastream"] = self.datastream(ds)
        return doc

    # ---------------------------------------------------------- entity sets

    def datastreams(self) -> dict:
        return self.collection([self.datastream(ds) for ds in
                                sorted(self.state.datastreams.values(),
                                       key=lambda d: d.id.int)])

    def observations(self, datastream_id: UUID | None = None,
                     *, expand: tuple[str, ...] = ()) -> dict:
        """**Live observations only** (§3.2).

        A superseded row stays in the log forever and is never served here, so a
        client sees exactly one observation per `phenomenonTime`.
        """
        live = self.state.live_observations().values()
        if datastream_id is not None:
            live = [o for o in live if o.datastream == datastream_id]
        return self.collection([self.observation(o, expand=expand)
                                for o in P.order_observations(live)])

    def things(self) -> dict:
        idents = {ds.thing for ds in self.state.datastreams.values()}
        return self.collection([self.thing(i) for i in sorted(idents, key=lambda u: u.int)])

    def sensors(self) -> dict:
        idents = {ds.sensor for ds in self.state.datastreams.values()}
        return self.collection([self.sensor(i) for i in sorted(idents, key=lambda u: u.int)])

    def observed_properties(self) -> dict:
        uris = {ds.observed_property for ds in self.state.datastreams.values()}
        return self.collection([self.observed_property(u) for u in sorted(uris)])

    def features_of_interest(self) -> dict:
        idents = {ds.feature for ds in self.state.datastreams.values()}
        idents |= {o.feature for o in self.state.observations if o.feature}
        return self.collection([self.feature_of_interest(i)
                                for i in sorted(idents, key=lambda u: u.int)])

    def root(self) -> dict:
        """The service document: every entity set this view serves."""
        sets = ["Things", "Datastreams", "Sensors", "ObservedProperties",
                "Observations", self.dialect.feature_set]
        return {self.dialect.value_key: [
            {"name": s, "url": f"{self._root()}/{s}"} for s in sets]}

    # ------------------------------------------------------------ internals

    def _phenomenon_time(self, obs: Observation) -> str:
        if not self.interval_times:
            return iso(obs.measured_at)
        lo, hi = obs.interval()
        return f"{iso(lo)}/{iso(hi)}"

    def _phenomenon_extent(self, datastream_id: UUID) -> str | None:
        stamps = [o.measured_at for o in self.state.observations
                  if o.datastream == datastream_id]
        if not stamps:
            return None
        lo, hi = min(stamps), max(stamps)
        return iso(lo) if lo == hi else f"{iso(lo)}/{iso(hi)}"

    def _datastream_observation_type(self, ds: Datastream) -> str:
        for obs in self.state.observations:
            if obs.datastream == ds.id:
                return observation_type(obs.result)
        return ANY_OBSERVATION

    def _health(self, ds: Datastream) -> P.Health:
        stamps = [o.measured_at for o in self.state.observations
                  if o.datastream == ds.id]
        now = max(stamps) if stamps else None
        return P.datastream_health(ds, now, now) if now else P.Health.UNKNOWN


def _quality_element(a: QualityAssertion) -> dict:
    """§3.3's live assertion as a DQ_Element-shaped object.

    1.1 types `resultQuality` as `DQ_Element` with multiplicity zero-to-many,
    which is why the flag *set* maps natively rather than needing to be flattened
    into one value.
    """
    return {
        "flags": sorted(f.value for f in a.flags),
        "usable": a.usable.value,
        "check": a.check,
        "checkVersion": a.check_version,
        "thresholdVersion": str(a.threshold_version) if a.threshold_version else None,
        "assertedAt": iso(a.asserted_at),
        "assertor": a.assertor.value,
    }
