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
import json
from urllib.parse import quote as _url_quote
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


def humanise_term(uri: str) -> str:
    """A legible name for a vocabulary URI: the last path segment, unpunctuated.

    `.../volume_fraction_of_condensed_water_in_soil/` becomes
    "volume fraction of condensed water in soil". A camelCase ODM2 term such as
    `batteryVoltage` becomes "battery voltage". Only a fallback — a label registry
    entry always wins — but it is the fallback a GIS legend actually shows.
    """
    tail = uri.rstrip("/").rsplit("/", 1)[-1]
    if not tail:
        return uri
    spaced = tail.replace("_", " ")
    out = []
    for i, ch in enumerate(spaced):
        # A camelCase hump becomes a word break, and the capital that marked it is
        # lowered — it was punctuation, not emphasis. Two exceptions, both because the
        # capital is part of the word rather than a separator: a run of capitals is
        # left alone (RSSI), and so is a lone trailing capital, which is what makes
        # `pH` survive as `pH` instead of becoming `p h`. Soil pH is a measurand this
        # project will certainly meet, so getting it wrong was not academic.
        if (ch.isupper() and i and spaced[i - 1].islower()
                and i < len(spaced) - 1):
            out.append(" ")
            out.append(ch.lower())
            continue
        out.append(ch)
    return "".join(out).strip()


def _quote(text: str) -> str:
    """Percent-encode an entity id for use inside `Set('...')`.

    `safe=""` on purpose: the slashes in a vocabulary URI are exactly what must not
    survive into the path, or the router splits the id into path segments.
    """
    return _url_quote(text, safe="")


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

    Names come from §1 `Label` records in the log, in `language`, falling back as
    `State.label_for` does. Anything unlabelled falls back to its id — legible,
    stable, and obviously a placeholder rather than an invented name. Where a fallback
    language supplied the name, `properties.nameLanguage` says so, so a client can
    mark the gap instead of passing English off as the Spanish it asked for.

    `labels` is an explicit override, `{id: {"name": ..., "description": ...}}`, which
    wins over the log. `geometries` maps a feature of interest to its GeoJSON — kept
    out of the log on purpose (§10.1: field boundaries are site-private material).
    """

    __slots__ = ("state", "base_url", "dialect", "labels", "interval_times",
                 "language", "geometries")

    def __init__(self, state: P.State, base_url: str = "http://localhost:8080",
                 *, dialect: type[Dialect] = SensorThings11,
                 labels: dict | None = None,
                 interval_times: bool = False,
                 language: str = "en",
                 geometries: dict | None = None):
        self.state = state
        self.base_url = base_url.rstrip("/")
        self.dialect = dialect
        self.labels = labels or {}
        self.language = language
        self.geometries = geometries or {}
        #: When true, `phenomenonTime` is emitted as the §2 uncertainty window
        #: rather than an instant. Standards-native honesty — a client sees the
        #: bound directly — but many clients assume an instant, so it is opt-in.
        self.interval_times = interval_times

    # ------------------------------------------------------------- helpers

    def _root(self) -> str:
        return self.base_url + self.dialect.base_path

    def _link(self, entity_set: str, ident: UUID) -> str:
        return f"{self._root()}/{entity_set}({ident})"

    def _label(self, ident, field: str, fallback: str) -> str:
        explicit = self.labels.get(ident, {}).get(field)
        if explicit:
            return explicit
        if field in ("name", "description") and isinstance(ident, UUID):
            found = self.state.label_for(ident, self.language)
            if found is not None:
                value = found.name if field == "name" else found.description
                if value:
                    return value
        return fallback

    def _name_language(self, ident) -> str | None:
        """The language the displayed name is actually in, when a Label supplied it."""
        if ident in self.labels or not isinstance(ident, UUID):
            return None
        found = self.state.label_for(ident, self.language)
        return found.language if found is not None else None

    def _with_language(self, properties: dict, ident) -> dict:
        language = self._name_language(ident)
        if language is not None:
            properties["nameLanguage"] = language
        return properties

    def _control(self, entity_set: str, ident: UUID) -> dict:
        d = self.dialect
        return {d.id_key: str(ident), d.self_key: self._link(entity_set, ident)}

    def _navs(self, entity_set: str, ident: UUID, *roles: str) -> dict:
        d = self.dialect
        base = self._link(entity_set, ident)
        return {f"{role}{d.nav_suffix}": f"{base}/{role}" for role in roles}

    def collection(self, items: list, *, count: bool = True) -> dict:
        """An entity-set response.

        `@iot.count` is included by default because 1.1's own Example 11 shows it
        on a plain entity-set request with no query options. FROST-Server is more
        conservative and omits it unless `$count=true` is asked for — both read
        the spec defensibly, so this is a parameter rather than a decision, and
        an HTTP layer honours `$count` by passing it through.
        """
        d = self.dialect
        doc = {}
        if count:
            doc[d.count_key] = len(items)
        doc[d.value_key] = list(items)
        return doc

    # ------------------------------------------------------------ entities

    def thing(self, ident: UUID) -> dict:
        doc = self._control("Things", ident)
        doc["name"] = self._label(ident, "name", str(ident))
        doc["description"] = self._label(ident, "description",
                                         "A thing layer zero observes")
        doc["properties"] = self._with_language({}, ident)
        # **No `Locations` link.** 1.1 makes Thing.Locations 0..*, and layer zero has
        # no Location record: geometry here belongs to a feature of interest — a bed, a
        # paddock, a trough — not to the Thing that happens to observe it. Advertising
        # the link anyway is what this used to do, and a walk of every emitted link
        # found it answering 404 to itself. A link you cannot answer is worse than one
        # you never offered, because the client only learns after following it.
        doc.update(self._navs("Things", ident, "Datastreams"))
        return doc

    def sensor(self, ident: UUID) -> dict:
        """A Sensor, enriched from its §4.1 `Device` record when one exists.

        `Datastream.sensor` was a bare UUID with no record behind it until §4.1 was
        built, so this could only ever repeat the id back. With a device registered it
        serves the hardware a person recognises — make, model, serial, firmware — and
        `metadata` becomes the driver manifest rather than a placeholder.

        Still falls back cleanly, because a datastream may name a sensor nobody has
        registered: §8.1's "heard but not trusted" is a real state, and refusing to
        serve the entity would hide it rather than show it.
        """
        doc = self._control("Sensors", ident)
        device = self.state.devices.get(ident)
        fallback = str(ident)
        described = "A sensor"
        if device is not None:
            parts = [p for p in (device.manufacturer, device.model) if p]
            if parts:
                fallback = " ".join(parts)
            described = f"{device.kind.value} {fallback}"
            if device.serial:
                described += f", serial {device.serial}"
        doc["name"] = self._label(ident, "name", fallback)
        doc["description"] = self._label(ident, "description", described)
        # 1.1 requires both. With a device record, `metadata` carries what §9.1's
        # driver manifest declares, which is what a client would actually want.
        doc["encodingType"] = ("application/json" if device is not None
                               else "application/pdf")
        if device is not None:
            manifest = dict(device.capabilities)
            manifest.update(device.provenance())
            doc["metadata"] = json.dumps(manifest, sort_keys=True) if manifest \
                else str(ident)
            doc["properties"] = {
                "kind": device.kind.value,
                "model": device.model,
                "serial": device.serial,
                "manufacturer": device.manufacturer,
                "firmware": device.firmware,
                "registered": True,
            }
            self._with_language(doc["properties"], ident)
        else:
            doc["metadata"] = self._label(ident, "metadata", str(ident))
            # §8.1: an unregistered device is heard but not trusted, and a client
            # deserves to know which it is looking at.
            doc["properties"] = {"registered": False}
        doc.update(self._navs("Sensors", ident, "Datastreams"))
        return doc

    def observed_property(self, uri: str) -> dict:
        """§3.4 observed properties are vocabulary URIs, so the URI *is* the
        identity — there is no separate UUID to mint.

        Two things here were found by loading Harrow Bend in QGIS 3.44 and looking at
        the legend:

        * **The id is percent-encoded in the self link.** A vocabulary URI contains
          `/` and `:`, so an unencoded one inside `ObservedProperties('...')` made a
          path the router split in the wrong places — we advertised a link and then
          answered 404 to it. A service whose own self links do not resolve is worse
          than one that omits them, because a client has no way to know.
        * **The displayed name is derived with the trailing slash stripped first.**
          Both vocabulary servers want the trailing slash (the slashless form
          redirects, and a redirect is a different identifier to a dumb client), and
          the old fallback took everything after the last `/` — which for
          `.../air_temperature/` is the empty string. Every observed property in QGIS
          showed a blank name. Nothing was wrong with the URI; the name derivation had
          simply never seen one that ended in a slash.
        """
        doc = {self.dialect.id_key: uri,
               self.dialect.self_key:
                   f"{self._root()}/ObservedProperties('{_quote(uri)}')"}
        doc["name"] = self._label(uri, "name", humanise_term(uri))
        doc["definition"] = uri
        doc["description"] = self._label(uri, "description", uri)
        # 1.1 Table 9 gives ObservedProperty a Datastreams navigation link. It was
        # simply missing, which a client cannot work around: there is no other way to
        # ask "which series measure this property?" without listing every datastream
        # and filtering client-side.
        doc[f"Datastreams{self.dialect.nav_suffix}"] = (
            f"{self._root()}/ObservedProperties('{_quote(uri)}')/Datastreams")
        return doc

    def feature_of_interest(self, ident: UUID) -> dict:
        doc = self._control(self.dialect.feature_set, ident)
        doc["name"] = self._label(ident, "name", str(ident))
        doc["description"] = self._label(ident, "description",
                                         "A field, bed, tank or animal")
        doc["encodingType"] = "application/geo+json"
        # The geometries channel first; a `feature` inside an explicit labels override
        # is still honoured, which is how it travelled before it had its own channel.
        doc["feature"] = (self.geometries.get(ident)
                          or self.labels.get(ident, {}).get("feature"))
        doc["properties"] = self._with_language({}, ident)
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
        doc["phenomenonTime"] = self._phenomenon_extent(ds.id)
        # 1.1 Table 10 makes Datastream.resultTime zero-to-one, and layer zero
        # records no result times, so the field is omitted rather than emitted as
        # a null. FROST-Server omits it too. Observation.resultTime is "One
        # (mandatory)" and nullable, so that one is emitted as null.

        doc["properties"] = self._with_language({
            "kind": kind,
            "derived_from": str(ds.derived_from) if ds.derived_from else None,
            "expected_interval_s": ds.expected_interval,
            "max_latency_s": ds.max_latency,
            "thresholds": dict(ds.thresholds),
            "health": self._health(ds).value,
        }, ds.id)
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
        assertion = self.state.live_assertion_for(obs.id)
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

    def datastreams(self, *, count: bool = True) -> dict:
        return self.collection([self.datastream(ds) for ds in
                                sorted(self.state.datastreams.values(),
                                       key=lambda d: d.id.int)], count=count)

    def observations(self, datastream_id: UUID | None = None,
                     *, expand: tuple[str, ...] = (),
                     count: bool = True) -> dict:
        """**Live observations only** (§3.2).

        A superseded row stays in the log forever and is never served here, so a
        client sees exactly one observation per `phenomenonTime`.
        """
        live = self.state.live_observations().values()
        if datastream_id is not None:
            live = [o for o in live if o.datastream == datastream_id]
        return self.collection([self.observation(o, expand=expand)
                                for o in P.order_observations(live)], count=count)

    def things(self, *, count: bool = True) -> dict:
        idents = {ds.thing for ds in self.state.datastreams.values()}
        return self.collection([self.thing(i) for i in
                                sorted(idents, key=lambda u: u.int)], count=count)

    def sensors(self, *, count: bool = True) -> dict:
        idents = {ds.sensor for ds in self.state.datastreams.values()}
        return self.collection([self.sensor(i) for i in
                                sorted(idents, key=lambda u: u.int)], count=count)

    def observed_properties(self, *, count: bool = True) -> dict:
        uris = {ds.observed_property for ds in self.state.datastreams.values()}
        return self.collection([self.observed_property(u) for u in sorted(uris)],
                               count=count)

    def features_of_interest(self, *, count: bool = True) -> dict:
        idents = {ds.feature for ds in self.state.datastreams.values()}
        idents |= {o.feature for o in self.state.observations if o.feature}
        return self.collection([self.feature_of_interest(i) for i in
                                sorted(idents, key=lambda u: u.int)], count=count)

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
        """1.1 Table 10's `observationType`, from the **declaration** not a sample.

        Derived from `ds.unit`, because that is the durable fact. The version this
        replaces read the Python type of the first result it could find, and a GIS
        client pointed at Harrow Bend showed what that costs: a raw soil-moisture
        series carries scaled integers, so `280` typed the whole datastream as
        `OM_CountObservation` — a *count* — while the same document declared a unit of
        `cm3/cm3`. A count has no unit, so the two halves of one document contradicted
        each other, and a consumer that honours `observationType` would be entitled to
        refuse to average or interpolate a continuous measurement.

        A declared unit means a measured quantity; that is what a unit is for. Only
        when there is no unit does the value's own type decide, and then it decides
        something real — a boolean is a truth observation, a bare integer a count, a
        string a category.

        (The scaled-integer raw series raises a separate and larger question about
        what unit a raw datastream should declare at all. See open-questions Q21; it
        is not this method's to answer.)
        """
        if ds.unit:
            return _OBSERVATION_TYPES[float]
        rows = self.state.observations_of(ds.id)
        if rows:
            return observation_type(rows[0].result)
        return ANY_OBSERVATION

    def _health(self, ds: Datastream) -> P.Health:
        """Staleness for one datastream, from the per-datastream index.

        The scan this replaces walked every observation in the log, for every
        datastream, on every `/Datastreams` request — the same quadratic shape §7.2
        forbids, hidden in a serialiser rather than in the projection.
        """
        stamps = self.state._times_by_datastream.get(ds.id)
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
        "evidence": dict(a.evidence),
        "note": a.note,
    }
