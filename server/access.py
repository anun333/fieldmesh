#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who may ask the service, and for what (spec v0.1 §7.6, §8.2).

Every request carries a bearer token, and a token stands for one of two kinds of reader:

* **a farm user**, with one of §8.2's roles. The service is read-only, so every role
  reads everything the farm has; the roles matter for the privileged operations, which
  are not done here.
* **a grantee** of a sharing grant (§7.6), who reads exactly what their grants cover at
  the moment they ask — the series granted, the readings that had arrived by the time
  the grant was made unless it says otherwise — and nothing once the grant ends or is
  revoked. `sharing.view` builds what they see.

A token is issued by the owner and is a log record, so who could read the farm's data,
and from when, is in the audit trail; the log holds the token's SHA-256, never the token.
Revoking a token is another record. A revoked *grant* leaves its grantee's token valid
and their view empty, because the grant is what they were given and the token only says
who is asking.

    python3 server/access.py issue --log farm.jsonl --role viewer --user 0190…
    python3 server/access.py issue --log farm.jsonl --grantee "state university soil lab"
    python3 server/access.py revoke --log farm.jsonl 0190…
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import hmac
import os
import secrets
import sys
import threading
from dataclasses import dataclass
from uuid import UUID

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "sdk"))
from ids import uuid7  # noqa: E402

ACCESS = "access_token"
ACCESS_REVOCATION = "access_token_revocation"
ROLES = ("owner", "manager", "worker", "viewer", "service")


def _now() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def _time(text: str | None):
    if not text:
        return None
    return _dt.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Principal:
    """Who a request is from. `kind` is `user`, `grantee` or `open` (anonymous, which
    the server allows only on its own machine and only when told to)."""

    kind: str
    name: str                   # the role, the grantee, or "anonymous"
    token: UUID | None = None   # the access-token record

    @property
    def key(self) -> str:
        """What rate limits are counted against."""
        return f"{self.kind}:{self.token or self.name}"


OPEN = Principal("open", "anonymous")


def issue(log, *, role: str | None = None, user: UUID | None = None,
          grantee: str | None = None, until: _dt.datetime | None = None,
          by: UUID | None = None, at: _dt.datetime | None = None):
    """Issue a token. Returns `(record id, token)`; the token is shown once."""
    if (role is None) == (grantee is None):
        raise ValueError("a token is for a farm user with a role, or for a grantee")
    if role is not None and role not in ROLES:
        raise ValueError(f"a role is one of {ROLES} (§8.2)")
    if grantee is not None and not grantee.strip():
        raise ValueError("a grantee has a name, the one their grants name")
    at = at or _now()
    if until is not None and until <= at:
        raise ValueError("a token must end after it begins")
    token = secrets.token_urlsafe(32)
    ident = uuid7()
    log.append(ACCESS, {
        "id": str(ident), "token_sha256": token_hash(token),
        "principal": ({"kind": "user", "role": role, "user": str(user) if user else None}
                      if role else {"kind": "grantee", "grantee": grantee}),
        "issued_at": at.isoformat(), "until": until.isoformat() if until else None,
        "issued_by": str(by) if by else None})
    return ident, token


def revoke(log, token_id: UUID, *, by: UUID | None = None, at: _dt.datetime | None = None):
    return log.append(ACCESS_REVOCATION, {"token": str(token_id),
                                          "at": (at or _now()).isoformat(),
                                          "by": str(by) if by else None})


class Access:
    """Resolves a request's `Authorization` header against the tokens in the log, and
    follows the log as tokens are issued and revoked."""

    def __init__(self, log) -> None:
        self._tokens: dict[str, dict] = {}            # hash -> record payload
        self._revoked: dict[str, _dt.datetime] = {}   # record id -> when
        self._lock = threading.Lock()
        for event in log.events:
            self._learn(event)
        log.on_commit(self._learn)

    def _learn(self, event) -> None:
        with self._lock:
            if event.kind == ACCESS:
                self._tokens[event.payload["token_sha256"]] = event.payload
            elif event.kind == ACCESS_REVOCATION:
                at = _time(event.payload["at"])
                prior = self._revoked.get(event.payload["token"])
                self._revoked[event.payload["token"]] = min(at, prior) if prior else at

    @property
    def any_issued(self) -> bool:
        return bool(self._tokens)

    def resolve(self, authorization: str | None, at: _dt.datetime) -> Principal | None:
        """The principal a header's bearer token stands for at `at`, or None."""
        if not authorization:
            return None
        scheme, _, token = authorization.strip().partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        digest = token_hash(token.strip())
        with self._lock:
            found = next((p for h, p in self._tokens.items()
                          if hmac.compare_digest(h, digest)), None)
            if found is None:
                return None
            revoked = self._revoked.get(found["id"])
        if at < _time(found["issued_at"]):
            return None
        if found.get("until") and at >= _time(found["until"]):
            return None
        if revoked is not None and at >= revoked:
            return None
        who = found["principal"]
        if who["kind"] == "user":
            return Principal("user", who["role"], UUID(found["id"]))
        return Principal("grantee", who["grantee"], UUID(found["id"]))


class RateLimiter:
    """A token bucket per principal: `rate` requests a second, bursts of `burst`."""

    def __init__(self, rate: float = 10.0, burst: int = 40) -> None:
        self.rate, self.burst = rate, burst
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float) -> tuple[bool, float]:
        """`(allowed, seconds until the next request would be)`."""
        with self._lock:
            level, last = self._buckets.get(key, (float(self.burst), now))
            level = min(float(self.burst), level + (now - last) * self.rate)
            if level >= 1.0:
                self._buckets[key] = (level - 1.0, now)
                return True, 0.0
            self._buckets[key] = (level, now)
            return False, (1.0 - level) / self.rate


def main(argv=None) -> int:
    import log as L

    ap = argparse.ArgumentParser(description="Issue or revoke a token for the data service")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("issue")
    i.add_argument("--log", required=True)
    who = i.add_mutually_exclusive_group(required=True)
    who.add_argument("--role", choices=ROLES)
    who.add_argument("--grantee")
    i.add_argument("--user", type=UUID)
    i.add_argument("--days", type=float, help="the token ends after this many days")
    r = sub.add_parser("revoke")
    r.add_argument("--log", required=True)
    r.add_argument("token", type=UUID)
    args = ap.parse_args(argv)
    lg = L.Log(args.log)
    if args.cmd == "issue":
        until = _now() + _dt.timedelta(days=args.days) if args.days else None
        ident, token = issue(lg, role=args.role, user=args.user, grantee=args.grantee,
                             until=until)
        print(f"token {ident}: {token}")
        print("Shown once; the log keeps only its hash. Send it the way you would a key.")
        return 0
    revoke(lg, args.token)
    print(f"revoked {args.token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
