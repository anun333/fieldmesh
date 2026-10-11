#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Modules as separate processes, permissioned per point (spec v0.1 §8.3; Q11).

A module — the water monitor, the soil advisory, someone else's — runs as its own
process. It reaches the foundation over a unix socket, presenting a token on every call,
and the foundation answers only what the token was granted: these datastreams, these
event kinds to write, nothing else. A crashed or hostile module cannot take the
foundation down, read a series it was not given, or write a reading, a quality verdict
or a grant.

Three pieces:

* **A manifest**, the module's own `module.json`: what it may ever ask for — which
  observed properties it reads, which event kinds it writes. It is a ceiling, not a
  grant.
* **A grant**, the farmer's, made at install (§8.2: an owner's act): within the
  manifest, *which points* — datastreams by id, or properties on named features — and
  which kinds it may write. A grant is a log record like a sharing grant, so who allowed
  what, when, is audited. The log holds the token's SHA-256, never the token.
* **The host**, the foundation's side of the socket. Every call is checked against the
  grant; a refusal says why and is written to the log. Writes are stamped with the
  module's name and grant, so a decision is traceable to the module that made it, and
  a module reads back only what it wrote itself — modules never reach into each other
  (§11).

`RemoteState` and `RemoteLog` are the module's side: the parts of `project.State` and
`log.Log` a module uses, answered over the socket, so a module written against the SDK
runs unchanged in its own process. Under systemd each module is a service holding its
token as a credential (deploy/systemd/); WASI's capability sandbox is the stated target
(Q11).

    python3 sdk/modhost.py grant --log farm.jsonl --manifest modules/water/module.json \\
        --datastream 0190…  --token-out /etc/fieldmesh/modules/water.token
    python3 sdk/modhost.py serve --log farm.jsonl --socket /run/fieldmesh/modules.sock
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import hmac
import json
import os
import secrets
import socket
import socketserver
import sys
import threading
from dataclasses import dataclass, field
from uuid import UUID

# Run as a service it is started isolated (`python3 -I`, deploy/systemd/), which leaves
# the script's own directory off the path; the SDK it is part of goes back on.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codec  # noqa: E402
from ids import uuid7  # noqa: E402

GRANT = "module_grant"
REVOCATION = "module_revocation"
REFUSAL = "module_refused"
#: Kinds no module may write, whatever its manifest says: readings, their quality and
#: thresholds, calibrations, corrections and every kind of grant are the foundation's.
FOUNDATION_ONLY = frozenset({
    "observation", "quality_assertion", "threshold", "calibration", "datastream",
    "device", "installation", "maintenance", "label", "correction", "grant",
    "grant_revocation", GRANT, REVOCATION, REFUSAL})
MAX_REQUEST = 1 << 20
#: What a module may be granted to read of *other* modules' writes: decisions (§7.7),
#: and what was done about them — who was told, who acknowledged. A notifier or a page
#: reads these; nothing else written by a module is anyone else's to read.
EVENT_READS = frozenset({"decision", "notification", "acknowledgement"})
#: The most events one `follow` call returns; the cursor takes the rest.
FOLLOW_LIMIT = 2000


def _now() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def _time(text: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Refused(Exception):
    """A call the grant does not allow."""


# ------------------------------------------------------------------ manifest

@dataclass(frozen=True)
class Manifest:
    """What a module may ever ask for (§8.3). Read from its `module.json`."""

    name: str
    version: str
    reads: frozenset             # observed-property URIs
    writes: frozenset            # event kinds
    commands: frozenset = frozenset()
    events: frozenset = frozenset()   # kinds of other modules' writes it reads

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("a module name is a plain word")
        bad = self.writes & FOUNDATION_ONLY
        if bad:
            raise ValueError(f"no module may write {sorted(bad)}: those are the foundation's")
        if not self.events <= EVENT_READS:
            raise ValueError(f"no module may read {sorted(self.events - EVENT_READS)} "
                             f"of others; only {sorted(EVENT_READS)}")
        if self.commands:
            raise ValueError("commands are deferred from the first release (§6)")

    @classmethod
    def load(cls, path: str) -> "Manifest":
        with open(path, encoding="utf-8") as h:
            doc = json.load(h)
        return cls(name=doc["name"], version=str(doc["version"]),
                   reads=frozenset(doc.get("reads", {}).get("observed_properties", [])),
                   writes=frozenset(doc.get("writes", [])),
                   commands=frozenset(doc.get("commands", [])),
                   events=frozenset(doc.get("reads", {}).get("events", [])))


# --------------------------------------------------------------------- grant

@dataclass(frozen=True)
class Grant:
    """What the farmer allowed one module: points to read, kinds to write."""

    id: UUID
    module: str
    version: str
    token_sha256: str
    datastreams: frozenset = frozenset()          # by id
    properties: frozenset = frozenset()           # on `features`, or anywhere if none named
    features: frozenset = frozenset()
    writes: frozenset = frozenset()
    granted_at: _dt.datetime | None = None
    granted_by: UUID | None = None
    #: Kinds of every module's writes it may read (`EVENT_READS`): a notifier's
    #: decisions to deliver, a page's alerts to show.
    events: frozenset = frozenset()

    def payload(self) -> dict:
        return {"id": str(self.id), "module": self.module, "version": self.version,
                "token_sha256": self.token_sha256,
                "datastreams": sorted(str(d) for d in self.datastreams),
                "properties": sorted(self.properties),
                "features": sorted(str(f) for f in self.features),
                "writes": sorted(self.writes),
                "events": sorted(self.events),
                "granted_at": self.granted_at.isoformat() if self.granted_at else None,
                "granted_by": str(self.granted_by) if self.granted_by else None}

    @classmethod
    def from_payload(cls, p: dict) -> "Grant":
        return cls(id=UUID(p["id"]), module=p["module"], version=p["version"],
                   token_sha256=p["token_sha256"],
                   datastreams=frozenset(UUID(d) for d in p.get("datastreams", [])),
                   properties=frozenset(p.get("properties", [])),
                   features=frozenset(UUID(f) for f in p.get("features", [])),
                   writes=frozenset(p.get("writes", [])),
                   granted_at=_time(p["granted_at"]) if p.get("granted_at") else None,
                   granted_by=UUID(p["granted_by"]) if p.get("granted_by") else None,
                   events=frozenset(p.get("events", [])) & EVENT_READS)

    def may_read(self, ds) -> bool:
        if ds.id in self.datastreams:
            return True
        if ds.observed_property in self.properties:
            return not self.features or ds.feature in self.features
        return False


def grant(log, manifest: Manifest, *, datastreams=(), properties=(), features=(),
          writes=None, events=None, by: UUID | None = None, at: _dt.datetime | None = None):
    """Grant a module what its manifest allows, for these points. Returns
    `(grant, token)`; the token is shown once and only its hash is logged.

    An owner's act (§8.2): like a sharing grant, it moves the farm's data, here to a
    piece of software. Reading other modules' decisions (`events`) defaults to what the
    manifest declares, as writing does; a decision carries what it was judged on, so
    the grant record says it plainly.
    """
    props = frozenset(properties)
    if not props <= manifest.reads:
        raise ValueError(f"{manifest.name} does not declare {sorted(props - manifest.reads)}")
    kinds = frozenset(manifest.writes if writes is None else writes)
    if not kinds <= manifest.writes:
        raise ValueError(f"{manifest.name} does not declare writing {sorted(kinds - manifest.writes)}")
    reads = frozenset(manifest.events if events is None else events)
    if not reads <= manifest.events:
        raise ValueError(f"{manifest.name} does not declare reading {sorted(reads - manifest.events)}")
    token = secrets.token_urlsafe(32)
    g = Grant(uuid7(), manifest.name, manifest.version, token_hash(token),
              frozenset(datastreams), props, frozenset(features), kinds, at or _now(), by,
              reads)
    log.append(GRANT, g.payload())
    return g, token


def revoke(log, grant_id: UUID, *, by: UUID | None = None, at: _dt.datetime | None = None):
    return log.append(REVOCATION, {"grant": str(grant_id), "at": (at or _now()).isoformat(),
                                   "by": str(by) if by else None})


# ---------------------------------------------------------------------- host

class ModuleHost:
    """The foundation's side of the socket: answers what each module's grant allows.

    `state` is the live sensing projection the gateway keeps; the host reads it under
    `lock`, which the gateway holds while it folds, so a module never sees a half-folded
    state. Grants are read from the log and followed as they are appended.
    """

    def __init__(self, log, state, path: str, *, lock: threading.RLock | None = None):
        self.log, self.state, self.path = log, state, path
        self.lock = lock or threading.RLock()
        self._grants: dict[str, Grant] = {}          # token hash -> grant
        self._revoked: set[UUID] = set()
        #: What decisions are about: a module granted decisions may read their names.
        self._subjects: set[UUID] = set()
        for event in log.events:
            self._learn(event)
        self._unsubscribe = log.on_commit(self._learn)
        self._server = None
        self._thread = None
        #: Refusals by (module, op, reason). The first of each is written to the log;
        #: the rest are counted here, so a module looping on a refused call cannot fill
        #: the farm's disk with the record of it.
        self.refusals: dict[tuple, int] = {}

    def _learn(self, event) -> None:
        if event.kind == GRANT:
            g = Grant.from_payload(event.payload)
            self._grants[g.token_sha256] = g
        elif event.kind == REVOCATION:
            self._revoked.add(UUID(event.payload["grant"]))
        elif event.kind == "decision" and event.payload.get("subject"):
            try:
                self._subjects.add(UUID(event.payload["subject"]))
            except (TypeError, ValueError):
                pass

    # ----------------------------------------------------------- lifecycle

    def start(self) -> "ModuleHost":
        if os.path.exists(self.path):
            os.unlink(self.path)
        host = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                # A module holds its connection for as long as it runs. One that dies
                # mid-request ends its own connection and nobody else's.
                try:
                    while True:
                        line = self.rfile.readline(MAX_REQUEST + 1)
                        if not line:
                            return
                        reply = host.answer(line)
                        self.wfile.write(json.dumps(reply, separators=(",", ":")).encode()
                                         + b"\n")
                        self.wfile.flush()
                except (OSError, ValueError):
                    return

        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True

        self._server = Server(self.path, Handler)
        os.chmod(self.path, 0o660)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._unsubscribe()
        if os.path.exists(self.path):
            os.unlink(self.path)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ------------------------------------------------------------- answers

    def answer(self, line: bytes) -> dict:
        """One request in, one reply out. Never raises: a malformed or hostile request
        gets an error, and the foundation carries on."""
        if len(line) > MAX_REQUEST:
            return {"ok": False, "error": "request too large"}
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("a request is a JSON object")
        except ValueError as exc:
            return {"ok": False, "error": f"malformed request: {exc}"}
        try:
            g = self._grant_for(req.get("token"))
            op = req.get("op")
            handler = getattr(self, f"_op_{op}", None) if isinstance(op, str) else None
            if handler is None:
                raise Refused(f"no operation {op!r}")
            with self.lock:
                return {"ok": True, "result": handler(g, req)}
        except Refused as exc:
            module = None
            try:
                module = self._grant_for(req.get("token")).module
            except Refused:
                pass
            key = (module, req.get("op"), str(exc))
            with self.lock:
                if key not in self.refusals:
                    self.log.append(REFUSAL, {"module": module, "op": req.get("op"),
                                              "reason": str(exc)})
                self.refusals[key] = self.refusals.get(key, 0) + 1
            return {"ok": False, "refused": True, "error": str(exc)}
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "error": f"bad request: {exc!r}"}

    def _grant_for(self, token) -> Grant:
        if not isinstance(token, str) or not token:
            raise Refused("no token")
        digest = token_hash(token)
        for known, g in self._grants.items():
            if hmac.compare_digest(known, digest):
                if g.id in self._revoked:
                    raise Refused("the grant was revoked")
                return g
        raise Refused("unknown token")

    def _readable(self, g: Grant, ds_id) -> object:
        ds = self.state.datastreams.get(UUID(ds_id))
        if ds is None or not g.may_read(ds):
            raise Refused(f"datastream {ds_id} is not granted")
        return ds

    def _readable_entities(self, g: Grant) -> set:
        """The granted datastreams and what they hang from — thing, sensor, feature —
        and every feature a granted sensor has been installed in (§4.1), since a probe
        moved to another bed is still read there."""
        out = set(g.features)
        sensors = set()
        for ds in self.state.datastreams.values():
            if g.may_read(ds):
                out |= {ds.id, ds.feature, ds.thing, ds.sensor}
                sensors.add(ds.sensor)
        out |= {i.feature for i in self.state.installations.values() if i.device in sensors}
        return out

    def _op_whoami(self, g, req):
        return {"module": g.module, "version": g.version, "grant": str(g.id),
                "writes": sorted(g.writes), "events": sorted(g.events),
                "granted_at": g.granted_at.isoformat() if g.granted_at else None}

    def _op_datastreams(self, g, req):
        return [codec.dump(ds) for ds in self.state.datastreams.values() if g.may_read(ds)]

    def _op_observations(self, g, req):
        ds = self._readable(g, req["datastream"])
        at = _time(req["at"])
        since = _time(req["since"]) if req.get("since") else None
        rows = []
        for o in self.state.live_observations_of(ds.id):
            if o.measured_at > at or o.received_at > at or (since and o.measured_at < since):
                continue
            usable, flags = self.state.quality_as_of(o.id, at)
            rows.append({"o": codec.dump(o), "usable": usable.value,
                         "flags": sorted(f.value for f in flags)})
        return rows

    def _op_forecast(self, g, req):
        ds = self._readable(g, req["datastream"])
        return [codec.dump(o) for o in
                self.state.forecast(ds.id, _time(req["start"]), _time(req["end"]))]

    def _op_installation(self, g, req):
        device = UUID(req["device"])
        if device not in self._readable_entities(g):
            raise Refused(f"device {device} is not behind a granted datastream")
        inst = self.state.installation_of(device, _time(req["when"]))
        return codec.dump(inst) if inst is not None else None

    def _op_label(self, g, req):
        entity = UUID(req["entity"])
        named = "decision" in g.events and entity in self._subjects
        if not named and entity not in self._readable_entities(g):
            raise Refused(f"entity {entity} is not granted")
        label = self.state.label_for(entity, req.get("language", "en"))
        return codec.dump(label) if label is not None else None

    def _op_append(self, g, req):
        kind, payload = req["kind"], req["payload"]
        if kind not in g.writes or kind in FOUNDATION_ONLY:
            raise Refused(f"{g.module} may not write {kind!r}")
        if not isinstance(payload, dict):
            raise Refused("a payload is a JSON object")
        payload = {**payload, "module": g.module, "module_grant": str(g.id)}
        return self.log.append(kind, payload).to_jsonable()

    def _op_events(self, g, req):
        """What this module wrote, under this grant or an earlier one of the same
        module, in log order. Nothing another module wrote."""
        kinds = set(req.get("kinds") or g.writes) & g.writes
        return [e.to_jsonable() for e in self.log.events
                if e.kind in kinds and e.payload.get("module") == g.module]

    def _op_follow(self, g, req):
        """Events after an arrival offset (§7.5): its own writes, and every module's
        writes of the kinds its grant reads. The cursor is the log's arrival order, so
        an event synced late is never skipped. `{"events": [...], "next": offset}`."""
        after = req.get("after", 0)
        if not isinstance(after, int) or isinstance(after, bool) or after < 0:
            raise ValueError("after is an arrival offset")
        kinds = set(req.get("kinds") or (g.writes | g.events))
        out, offset = [], after
        for offset, e in enumerate(self.log.arrivals_since(after), start=after + 1):
            if e.kind in kinds and (e.kind in g.events or (e.kind in g.writes and
                                                           e.payload.get("module") == g.module)):
                out.append(e.to_jsonable())
                if len(out) >= FOLLOW_LIMIT:
                    break
        return {"events": out, "next": offset}


# -------------------------------------------------------------------- client

class ModuleClient:
    """A module's connection to its host. One socket, one request at a time."""

    def __init__(self, path: str, token: str):
        self.token = token
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(path)
        self._file = self._sock.makefile("rwb")

    def call(self, op: str, **args):
        self._file.write(json.dumps({"token": self.token, "op": op, **args},
                                    default=str).encode() + b"\n")
        self._file.flush()
        reply = json.loads(self._file.readline())
        if not reply.get("ok"):
            raise (Refused if reply.get("refused") else RuntimeError)(reply.get("error"))
        return reply["result"]

    def close(self) -> None:
        self._file.close()
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def state(self, at: _dt.datetime, *, lookback: _dt.timedelta = _dt.timedelta(days=3)):
        return RemoteState(self, at, lookback)

    def log(self):
        return RemoteLog(self)

    def follow(self, after: int = 0, kinds=None) -> tuple:
        """`(events, next offset)`: see the host's `follow`."""
        from log import Event
        found = self.call("follow", after=after, **({"kinds": sorted(kinds)} if kinds else {}))
        return [Event.from_jsonable(e) for e in found["events"]], found["next"]


@dataclass
class _Remote:
    usable: dict = field(default_factory=dict)     # observation id -> (Usable, flags)


class RemoteState:
    """The parts of `project.State` a module reads, as the host allows them, as of one
    moment. Fetched lazily and kept for the life of the object, so a module judging one
    moment asks each question once."""

    def __init__(self, client: ModuleClient, at: _dt.datetime, lookback: _dt.timedelta):
        from model import QualityFlag, Usable
        self._Q, self._U = QualityFlag, Usable
        self.client, self.at, self.lookback = client, at, lookback
        self._datastreams = None
        self._rows: dict = {}
        self._quality: dict = {}

    @property
    def datastreams(self) -> dict:
        if self._datastreams is None:
            self._datastreams = {d.id: d for d in
                                 (codec.load(x) for x in self.client.call("datastreams"))}
        return self._datastreams

    def live_observations_of(self, datastream_id, tail=None) -> list:
        if datastream_id not in self._rows:
            rows = self.client.call("observations", datastream=str(datastream_id),
                                    at=self.at.isoformat(),
                                    since=(self.at - self.lookback).isoformat())
            out = []
            for r in rows:
                o = codec.load(r["o"])
                self._quality[o.id] = (self._U(r["usable"]),
                                       frozenset(self._Q(f) for f in r["flags"]))
                out.append(o)
            self._rows[datastream_id] = out
        rows = self._rows[datastream_id]
        return rows[-tail:] if tail else list(rows)

    def quality_as_of(self, observation_id, at):
        if at != self.at:
            raise ValueError("a remote state answers as of the moment it was opened")
        return self._quality.get(observation_id, (self._U.GOOD, frozenset()))

    def installation_of(self, device_id, when):
        found = self.client.call("installation", device=str(device_id), when=when.isoformat())
        return codec.load(found) if found else None

    def label_for(self, entity, language: str = "en", **_):
        found = self.client.call("label", entity=str(entity), language=language)
        return codec.load(found) if found else None

    def forecast(self, datastream_id, start, end) -> list:
        return [codec.load(x) for x in self.client.call(
            "forecast", datastream=str(datastream_id), start=start.isoformat(),
            end=end.isoformat())]


class RemoteLog:
    """A module's view of the log: append what its grant allows, and read back what it
    wrote itself."""

    def __init__(self, client: ModuleClient):
        self.client = client

    def append(self, kind: str, payload: dict):
        from log import Event
        return Event.from_jsonable(self.client.call("append", kind=kind,
                                                    payload=codec.jsonable(payload)))

    @property
    def events(self) -> tuple:
        from log import Event
        return tuple(Event.from_jsonable(e) for e in self.client.call("events"))


def token_from_environment() -> str:
    """The module's token: a systemd credential (`LoadCredential=token:…`), or
    `FIELDMESH_MODULE_TOKEN` for a module run by hand."""
    creds = os.environ.get("CREDENTIALS_DIRECTORY")
    if creds and os.path.exists(os.path.join(creds, "token")):
        with open(os.path.join(creds, "token"), encoding="utf-8") as h:
            return h.read().strip()
    token = os.environ.get("FIELDMESH_MODULE_TOKEN")
    if not token:
        raise SystemExit("no module token: set a systemd credential named token, or "
                         "FIELDMESH_MODULE_TOKEN")
    return token


# ----------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    import log as L
    import project as P

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grant", help="grant a module its points; writes its token")
    g.add_argument("--log", required=True)
    g.add_argument("--manifest", required=True)
    g.add_argument("--datastream", action="append", default=[])
    g.add_argument("--property", action="append", default=[])
    g.add_argument("--feature", action="append", default=[])
    g.add_argument("--no-events", action="store_true",
                   help="withhold other modules' decisions even if the manifest asks")
    g.add_argument("--token-out", required=True)
    r = sub.add_parser("revoke", help="revoke a grant")
    r.add_argument("--log", required=True)
    r.add_argument("grant")
    s = sub.add_parser("serve", help="serve modules over a unix socket")
    s.add_argument("--log", required=True)
    s.add_argument("--socket", required=True)
    args = ap.parse_args(argv)

    lg = L.Log(args.log)
    if args.cmd == "grant":
        manifest = Manifest.load(args.manifest)
        made, token = grant(lg, manifest, datastreams=[UUID(d) for d in args.datastream],
                            properties=args.property, features=[UUID(f) for f in args.feature],
                            events=() if args.no_events else None)
        fd = os.open(args.token_out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            h.write(token + "\n")
        print(f"granted {manifest.name}: grant {made.id}; token in {args.token_out}")
        return 0
    if args.cmd == "revoke":
        revoke(lg, UUID(args.grant))
        print(f"revoked {args.grant}")
        return 0
    state = P.state_from_log(lg)
    lg.on_commit(lambda e: state.add(e.record()) if e.record() is not None else None)
    host = ModuleHost(lg, state, args.socket).start()
    print(f"serving modules on {args.socket}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        host.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
