#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A read-only SensorThings 1.1 HTTP service over derived state (spec v0.1 §10).

Transport-free on purpose: `handle()` takes a method, a path and a query string, and
returns `(status, headers, body)`. `serve.py` puts a socket in front of it. Everything
worth testing is therefore testable without binding a port, and the same function can
later sit behind WSGI, ASGI or a test client without being rewritten.

## Read-only is a design decision, not a missing feature

§7.1 says the append-only log is the write path. A client that could POST an Observation
here would be writing to a projection, and a projection is derived state — the write
would be silently discarded the next time state was rebuilt from the log. So every
mutating method is 405 with an `Allow` header, which is the honest answer, rather than
501 "not yet", which implies it is coming.

## Why the observation path uses the index

`/Datastreams(id)/Observations` resolves through `State.live_observations_of`, which is
indexed per datastream, instead of filtering the whole live set. That is the request a
GIS client actually makes — one series at a time — and §7.2 promises that years of
readings do not slow everyday work. The unscoped `/Observations` has no such index and
says so in its own comment.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from urllib.parse import parse_qsl, unquote, urlencode
from uuid import UUID

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "sdk"))

import odata  # noqa: E402

import project as P  # noqa: E402
import sensorthings as ST  # noqa: E402

JSON = "application/json"

#: Entity sets, each mapped to the `Service` method that lists it. `FeaturesOfInterest`
#: is spelled by the dialect because 2.0 renames it (`Features`), and the whole point of
#: the dialect is that a version rename is one line.
_SETS = {
    "Things": "things",
    "Datastreams": "datastreams",
    "Sensors": "sensors",
    "ObservedProperties": "observed_properties",
    "Observations": None,            # handled specially: it is the unbounded one
    "FeaturesOfInterest": "features_of_interest",
    "Features": "features_of_interest",
}

#: Navigation links this service resolves, as (set, nav) -> handler name.
_NAVS = {
    ("Things", "Datastreams"),
    ("Datastreams", "Observations"),
    ("Datastreams", "Sensor"),
    ("Datastreams", "ObservedProperty"),
    ("Datastreams", "Thing"),
    ("Observations", "Datastream"),
    ("Observations", "FeatureOfInterest"),
    ("Sensors", "Datastreams"),
    ("ObservedProperties", "Datastreams"),
}

_MUTATING = ("POST", "PATCH", "PUT", "DELETE", "MERGE")


class HttpError(Exception):

    def __init__(self, status: int, message: str, target: str | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.target = target


def _json(doc, status: int = 200, extra: dict | None = None):
    body = json.dumps(doc, default=_default).encode()
    headers = {"Content-Type": JSON, "Content-Length": str(len(body))}
    if extra:
        headers.update(extra)
    return status, headers, body


def _default(value):
    if isinstance(value, _dt.datetime):
        return ST.iso(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"{type(value).__name__} is not JSON-serialisable")


def _error(status: int, message: str, target: str | None = None):
    """The OData error shape, which is what a SensorThings client parses.

    The offending text is quoted back in `target`. Without it, a 400 on a long
    `$filter` tells the client only that *something* was wrong with the URL.
    """
    err = {"code": str(status), "message": message}
    if target:
        err["target"] = target
    return _json({"error": err}, status=status)


# ------------------------------------------------------------------ query options

_KNOWN_OPTIONS = {"$filter", "$orderby", "$top", "$skip", "$count", "$select",
                  "$expand", "$resultFormat"}


class Options:
    """The parsed query options for one request."""

    __slots__ = ("filter_tree", "orderby", "top", "skip", "count", "select",
                 "expand", "raw")

    def __init__(self, query: str):
        pairs = parse_qsl(query, keep_blank_values=True)
        self.raw = dict(pairs)
        for key in self.raw:
            if key.startswith("$") and key not in _KNOWN_OPTIONS:
                raise odata.NotSupported(
                    f"the query option '{key}' is not implemented", key)
        self.filter_tree = (odata.parse_filter(self.raw["$filter"])
                            if self.raw.get("$filter") else None)
        self.orderby = _parse_orderby(self.raw.get("$orderby"))
        self.top = _parse_int("$top", self.raw.get("$top"), odata.DEFAULT_TOP)
        self.skip = _parse_int("$skip", self.raw.get("$skip"), 0)
        self.count = self.raw.get("$count", "").lower() == "true"
        self.select = tuple(s.strip() for s in self.raw["$select"].split(",")
                            if s.strip()) if self.raw.get("$select") else ()
        self.expand = tuple(s.strip() for s in self.raw["$expand"].split(",")
                            if s.strip()) if self.raw.get("$expand") else ()
        if self.top > odata.MAX_TOP:
            raise odata.BadRequest(
                f"$top may not exceed {odata.MAX_TOP}; page with $skip and the "
                f"@iot.nextLink instead", self.raw.get("$top"))
        if self.skip < 0 or self.top < 0:
            raise odata.BadRequest("$top and $skip must not be negative")


def _parse_int(name: str, text: str | None, default: int) -> int:
    if text is None or text == "":
        return default
    try:
        return int(text)
    except ValueError as exc:
        raise odata.BadRequest(f"{name} must be an integer", text) from exc


def _parse_orderby(text: str | None):
    if not text:
        return ()
    out = []
    for clause in text.split(","):
        parts = clause.split()
        if not parts:
            continue
        if len(parts) == 1:
            out.append((tuple(parts[0].split("/")), False))
        elif len(parts) == 2 and parts[1].lower() in ("asc", "desc"):
            out.append((tuple(parts[0].split("/")), parts[1].lower() == "desc"))
        else:
            raise odata.BadRequest("$orderby takes 'property' or 'property asc|desc'",
                                   clause)
    return tuple(out)


class _Sortable:
    """A total order over values that may be None or of mixed type.

    `$orderby` on a property some documents lack would otherwise raise `TypeError`
    halfway through a sort and turn a well-formed request into a 500. Nulls sort first,
    which is what OData says; values of different types sort by type name so the result
    is at least deterministic rather than an error.
    """

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def _key(self):
        v = self.value
        if v is None:
            return (0, "", 0.0)
        if isinstance(v, bool):
            return (1, "bool", float(v))
        if isinstance(v, (int, float)):
            return (1, "number", float(v))
        if isinstance(v, _dt.datetime):
            return (1, "datetime", v.timestamp())
        return (2, type(v).__name__, 0.0)

    def __lt__(self, other):
        a, b = self._key(), other._key()
        if a[:2] != b[:2]:
            return a[:2] < b[:2]
        if a[1] in ("number", "bool", "datetime"):
            return a[2] < b[2]
        return str(self.value) < str(other.value)

    def __eq__(self, other):
        return self._key() == other._key() and str(self.value) == str(other.value)


def apply_options(items, options: Options, *, base: str, query: dict):
    """Filter, order, page and project one entity set.

    Lazy where it can be: with no `$filter`, no `$orderby` and no `$count`, the pipeline
    pulls exactly `skip + top + 1` documents and stops, so `$top=10` against a season is
    a few dozen serialisations rather than a few hundred thousand. `$count` and
    `$orderby` both genuinely require the whole set — one to count it, the other because
    the last document can sort first — and that cost is the client's choice.
    """
    tree, order = options.filter_tree, options.orderby
    if tree is not None:
        items = (doc for doc in items if odata.matches(tree, doc))

    total = None
    if order:
        materialised = list(items)
        total = len(materialised)
        for segments, descending in reversed(order):
            materialised.sort(
                key=lambda d, s=segments: _Sortable(odata.resolve_path(d, s)),
                reverse=descending)
        items = iter(materialised)
    elif options.count:
        materialised = list(items)
        total = len(materialised)
        items = iter(materialised)

    page, overflow = _page(items, options.skip, options.top)
    if options.select:
        page = [_project(doc, options.select) for doc in page]

    doc: dict = {}
    if options.count:
        doc["@iot.count"] = total
    doc["value"] = page
    if overflow:
        doc["@iot.nextLink"] = _next_link(base, query, options)
    return doc


def _page(items, skip: int, top: int):
    """`top` documents starting at `skip`, plus whether at least one more exists."""
    page = []
    index = 0
    overflow = False
    for doc in items:
        if index < skip:
            index += 1
            continue
        if len(page) == top:
            overflow = True
            break
        page.append(doc)
        index += 1
    return page, overflow


def _project(doc: dict, select: tuple[str, ...]) -> dict:
    """`$select`, keeping the control information.

    `@iot.id` and `@iot.selfLink` survive a `$select` that does not name them: without
    the self link a client cannot navigate to what it just selected, and 1.1 treats the
    control information as part of the entity rather than as a property.
    """
    keep = {k: v for k, v in doc.items() if k in ("@iot.id", "@iot.selfLink")}
    for name in select:
        if name in doc:
            keep[name] = doc[name]
    return keep


def _next_link(base: str, query: dict, options: Options) -> str:
    nxt = dict(query)
    nxt["$skip"] = str(options.skip + options.top)
    nxt["$top"] = str(options.top)
    return f"{base}?{urlencode(nxt)}"


# ------------------------------------------------------------------------ routing

def _split_segment(segment: str):
    """`Things(abc)` -> `("Things", "abc")`; `Things` -> `("Things", None)`.

    The id is percent-decoded **here and not before**, which is the whole reason the
    path is split before it is unquoted. An ObservedProperty's id is a vocabulary URI
    containing slashes; decoding the path first would turn those into path separators
    and shatter the id across segments. QGIS found this by following a self link we had
    emitted and getting a 404 from our own service.
    """
    if segment.endswith(")") and "(" in segment:
        name, _, rest = segment.partition("(")
        ident = rest[:-1]
        if len(ident) >= 2 and ident[0] == ident[-1] == "'":
            ident = ident[1:-1]
        return name, unquote(ident)
    return segment, None


def _uuid(text: str, where: str) -> UUID:
    try:
        return UUID(text)
    except ValueError as exc:
        raise HttpError(404, f"not an entity id: {text}", where) from exc


def preferred_language(header: str | None, default: str = "en") -> str:
    """The highest-weighted tag from an `Accept-Language` header.

    `es-MX,es;q=0.9,en;q=0.8` gives `es-MX`. A malformed weight counts as zero rather
    than failing the request — a browser's language preference is a hint, and a
    service that 400s on a hint is being unhelpful about something the client cannot
    easily fix.
    """
    if not header:
        return default
    best, best_q = default, -1.0
    for part in header.split(","):
        tag, _, params = part.strip().partition(";")
        tag = tag.strip()
        if not tag or tag == "*":
            continue
        q = 1.0
        params = params.strip()
        if params.startswith("q="):
            try:
                q = float(params[2:])
            except ValueError:
                q = 0.0
        if q > best_q:
            best, best_q = tag, q
    return best


class App:
    """Routes requests onto a `sensorthings.Service`."""

    def __init__(self, service: ST.Service):
        self.service = service
        self.state = service.state
        self.base_path = service.dialect.base_path
        self._by_language: dict[str, ST.Service] = {service.language: service}

    def _service_for(self, language: str) -> ST.Service:
        """A view of the same state that names things in `language` (§1, §11)."""
        if language not in self._by_language:
            base = self.service
            self._by_language[language] = ST.Service(
                base.state, base.base_url, dialect=base.dialect, labels=base.labels,
                interval_times=base.interval_times, language=language,
                geometries=base.geometries)
        return self._by_language[language]

    # ------------------------------------------------------------- entry point

    def handle(self, method: str, path: str, query: str = "",
               headers: dict | None = None):
        """Serve one request. Never raises — every failure becomes a response.

        `Accept-Language` chooses the language entity names are given in (layer 4 is
        bilingual, §11); a name that has no translation falls back, and says so in
        `properties.nameLanguage`.
        """
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        language = preferred_language(headers.get("accept-language"),
                                      self.service.language)
        # Swapping the view for the length of one request is safe only because the
        # server is single-threaded by design (serve.py). A threaded server would
        # need the language threaded through the call instead.
        previous = self.service
        self.service = self._service_for(language)
        try:
            return self._handle(method, path, query)
        finally:
            self.service = previous

    def _handle(self, method: str, path: str, query: str):
        try:
            if method in _MUTATING:
                raise HttpError(
                    405,
                    "this service is read-only: the append-only log is the write "
                    "path (spec v0.1 §7.1), and a write to a projection would be "
                    "discarded when state was next rebuilt from the log")
            if method not in ("GET", "HEAD"):
                raise HttpError(405, f"{method} is not allowed")
            status, headers, body = self._route(path, query)
            if method == "HEAD":
                body = b""
            return status, headers, body
        except odata.QueryError as exc:
            return _error(exc.status, exc.message, exc.offending)
        except HttpError as exc:
            extra = {"Allow": "GET, HEAD"} if exc.status == 405 else None
            status, headers, body = _error(exc.status, exc.message, exc.target)
            if extra:
                headers.update(extra)
            return status, headers, body

    # ---------------------------------------------------------------- routing

    def _route(self, path: str, query: str):
        trimmed = path.rstrip("/")
        if trimmed in ("", self.base_path.rstrip("/")):
            if trimmed == "":
                return _json({"value": [
                    {"name": "SensorThings 1.1",
                     "url": self.service.base_url + self.base_path}]})
            return _json(self.service.root())
        if not trimmed.startswith(self.base_path):
            raise HttpError(404, f"no such path: {path}", path)
        rest = trimmed[len(self.base_path):].strip("/")
        if rest == "$metadata":
            raise HttpError(
                501, "$metadata (the CSDL document) is not implemented; the service "
                     "document at the service root lists every entity set")
        segments = rest.split("/")
        options = Options(query)
        return self._dispatch(segments, options, query)

    def _dispatch(self, segments: list[str], options: Options, query: str):
        head, ident = _split_segment(segments[0])
        if head not in _SETS:
            raise HttpError(404, f"no such entity set: {head}", head)
        tail = segments[1:]

        if ident is None:
            if tail:
                raise HttpError(404, "an entity set has no sub-path; address an "
                                     "entity first, as Set(id)", "/".join(segments))
            return self._collection(head, options, query, scope=None)

        # An ObservedProperty's identity *is* its vocabulary URI (§3.4), so it is the
        # one entity set whose key is not a UUID.
        entity_id = ident if head == "ObservedProperties" else _uuid(ident, head)
        if not tail:
            return _json(self._entity(head, entity_id))
        return self._navigate(head, entity_id, tail, options, query)

    def _navigate(self, head: str, entity_id: UUID, tail: list[str],
                  options: Options, query: str):
        nav = tail[0]
        want_value = len(tail) > 1 and tail[1] == "$value"
        if len(tail) > 1 and not want_value:
            raise HttpError(501, "only one level of navigation is implemented",
                            "/".join(tail))

        if (head, nav) in _NAVS:
            if want_value:
                raise HttpError(400, "$value addresses a property, not a navigation "
                                     "link", nav)
            return self._follow(head, entity_id, nav, options, query)

        # Not a navigation link, so it is a property of the entity.
        doc = self._entity(head, entity_id)
        if nav not in doc:
            raise HttpError(404, f"{head} has no property or navigation link "
                                 f"named {nav}", nav)
        if want_value:
            raw = doc[nav]
            text = raw if isinstance(raw, str) else json.dumps(raw, default=_default)
            body = text.encode()
            return 200, {"Content-Type": "text/plain",
                         "Content-Length": str(len(body))}, body
        return _json({nav: doc[nav]})

    # -------------------------------------------------------------- collections

    def _collection(self, head: str, options: Options, query: str,
                    scope: tuple[str, UUID] | None):
        base = f"{self.service.base_url}{self.base_path}/{head}"
        if scope is not None:
            kind, ident = scope
            base = f"{self.service.base_url}{self.base_path}/{kind}({ident})/{head}"
        items = self._items(head, options, scope)
        doc = apply_options(items, options, base=base, query=dict(
            parse_qsl(query, keep_blank_values=True)))
        return _json(doc)

    def _items(self, head: str, options: Options, scope):
        """A lazy sequence of serialized documents for one entity set."""
        if head == "Observations":
            return self._observation_items(options, scope)
        method = _SETS[head]
        collection = getattr(self.service, method)(count=False)
        items = collection["value"]
        if scope is not None:
            items = self._narrow(head, items, scope)
        return iter(items)

    def _narrow(self, head: str, items: list, scope):
        """Restrict a non-observation set to the entities reachable from `scope`."""
        kind, ident = scope
        if head == "Datastreams":
            streams = self.state.datastreams.values()
            if kind == "Things":
                keep = {str(ds.id) for ds in streams if ds.thing == ident}
            elif kind == "Sensors":
                keep = {str(ds.id) for ds in streams if ds.sensor == ident}
            elif kind == "ObservedProperties":
                keep = {str(ds.id) for ds in streams
                        if ds.observed_property == ident}
            else:
                keep = {str(ds.id) for ds in streams}
            return [d for d in items if d.get("@iot.id") in keep]
        return items

    def _observation_items(self, options: Options, scope):
        """Live observations, serialized one at a time (§3.2 — never a superseded row).

        Scoped to a datastream this goes through the per-datastream index; unscoped it
        has to consult the whole live set, because deduplication by
        `(datastream, phenomenonTime)` is global. That asymmetry is why a client should
        ask for `/Datastreams(id)/Observations`, and why that is the link the service
        advertises.
        """
        service = self.service
        if scope is not None and scope[0] == "Datastreams":
            ds_id = scope[1]
            if ds_id not in self.state.datastreams:
                raise HttpError(404, f"no such Datastream: {ds_id}", str(ds_id))
            rows = self.state.live_observations_of(ds_id)
        else:
            rows = self.state.live_observations().values()
        for obs in P.order_observations(rows):
            yield service.observation(obs, expand=options.expand)

    # ----------------------------------------------------------------- entities

    def _entity(self, head: str, entity_id: UUID) -> dict:
        if head == "Datastreams":
            ds = self.state.datastreams.get(entity_id)
            if ds is None:
                raise HttpError(404, f"no such Datastream: {entity_id}")
            return self.service.datastream(ds)
        if head == "Observations":
            for obs in self.state.live_observations().values():
                if obs.id == entity_id:
                    return self.service.observation(obs)
            raise HttpError(404, f"no such Observation: {entity_id}")
        # Things, Sensors, ObservedProperties and FeaturesOfInterest are projections of
        # the datastream set rather than records of their own (§1 keeps names out of
        # keys), so existence means "some datastream refers to it".
        method = _SETS[head]
        for doc in getattr(self.service, method)(count=False)["value"]:
            if doc.get("@iot.id") == str(entity_id):
                return doc
        raise HttpError(404, f"no such {head[:-1]}: {entity_id}")

    def _follow(self, head: str, entity_id: UUID, nav: str,
                options: Options, query: str):
        """One navigation hop, to a collection or to a single entity."""
        if nav in ("Datastreams", "Observations"):
            return self._collection(nav, options, query, scope=(head, entity_id))
        # A single-valued navigation link.
        if head == "Datastreams":
            ds = self.state.datastreams.get(entity_id)
            if ds is None:
                raise HttpError(404, f"no such Datastream: {entity_id}")
            if nav == "Sensor":
                return _json(self.service.sensor(ds.sensor))
            if nav == "Thing":
                return _json(self.service.thing(ds.thing))
            if nav == "ObservedProperty":
                return _json(self.service.observed_property(ds.observed_property))
        if head == "Observations":
            for obs in self.state.live_observations().values():
                if obs.id != entity_id:
                    continue
                ds = self.state.datastreams.get(obs.datastream)
                if nav == "Datastream":
                    if ds is None:
                        raise HttpError(404, "the observation's datastream is gone")
                    return _json(self.service.datastream(ds))
                if nav == "FeatureOfInterest":
                    feature = obs.effective_feature(ds) if ds else obs.feature
                    if feature is None:
                        raise HttpError(404, "this observation has no feature")
                    return _json(self.service.feature_of_interest(feature))
            raise HttpError(404, f"no such Observation: {entity_id}")
        raise HttpError(404, f"{head} has no navigation link named {nav}", nav)


def make_app(state: P.State, base_url: str = "http://localhost:8080", **kw) -> App:
    return App(ST.Service(state, base_url, **kw))
