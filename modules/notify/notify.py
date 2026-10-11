#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Notifications, escalation and acknowledgement — layer 1 (spec v0.1 §11).

Every module so far ends at a decision in the log (§7.7): a trough is empty, bed 3 needs
water, it will frost in the tunnel tonight. A decision nobody reads protects nothing.
This module carries decisions to people, in their own language, on the phone they have:

* **Push**, through [ntfy](https://ntfy.sh) (Apache-2.0 and GPL-2.0, self-hostable, an
  Android app on F-Droid and an iPhone app), with an "I'm on it" button.
* **SMS**, through a cellular modem on the farm's own computer, driven by ModemManager
  (`mmcli`), so a basic phone gets the alert and no internet is needed. A reply of
  "OK 417" acknowledges it.

§11 asks that **alerts escalate and need acknowledgement**. A route says which rules go
to whom, in tiers: the person who checks the troughs first, and if nobody says "on it"
within half an hour, the owner. Escalation stops when someone acknowledges, and the
others are told who did; when the module that raised the alert clears it, everyone who
was told hears that too.

**What it knows, it reads from the log.** Decisions are followed from their arrival
cursor (§7.5); every message sent and every acknowledgement is written back as an event.
A notifier that restarts rebuilds who was told what from the log, so it neither sends
everything again nor forgets an alert half-escalated. Sending comes before writing: a
crash between the two can repeat a message, never lose one.

**What it never writes to the log: anyone's phone number.** The roster, the farm's
private configuration, maps people to their numbers and topics. The log names people by
the same ids it uses everywhere else (§7.4), so an export or a shared view of the log
carries who was told, never how to reach them.

It reads any module's decisions without importing any module: the decision names its
message and its subject (`rules.render`), and each module's language pack is data.
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import glob
import hashlib
import json
import math
import os
import re
import secrets
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from uuid import UUID

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
import i18n  # noqa: E402
import rules as R  # noqa: E402

NOTIFICATION = "notification"           # the event kind for a message sent, or tried
ACKNOWLEDGEMENT = "acknowledgement"     # the same kind the water monitor writes
MIN = _dt.timedelta(minutes=1)
#: A person no channel reached is tried again this often, this many times, while the
#: alert stands. Escalation does not wait for them: a tier nobody in was reached
#: hands on at once.
RETRY_AFTER = 10 * MIN
MAX_TRIES = 3


def register_packs(modules_dir: str = os.path.join(HERE, os.pardir)) -> list[str]:
    """Every installed module's language pack, so any module's decision can be said.
    Packs are data; no module's code is imported. A broken pack is skipped and named."""
    skipped = []
    for packs in sorted(glob.glob(os.path.join(modules_dir, "*", "packs"))):
        name = os.path.basename(os.path.dirname(packs))
        try:
            i18n.register(packs, name)
        except ValueError as exc:
            skipped.append(f"{name}: {exc}")
    return skipped


register_packs()


# ------------------------------------------------------------------- roster

@dataclass(frozen=True)
class Person:
    """Someone the farm tells. `contacts` in order of preference, each `(via, address)`:
    `("ntfy", topic)` or `("sms", "+16155550123")`."""

    key: str
    id: UUID
    name: str
    language: str = "en"
    contacts: tuple = ()
    #: Local hours ("21:00", "06:00") when only urgent alerts reach them.
    quiet: tuple | None = None

    def __post_init__(self) -> None:
        if not self.contacts:
            raise ValueError(f"{self.key}: nobody can be told without a way to reach them")
        for via, address in self.contacts:
            if via not in ("ntfy", "sms"):
                raise ValueError(f"{self.key}: no channel {via!r}")
            if via == "sms" and not PHONE.fullmatch(address):
                raise ValueError(f"{self.key}: {address!r} is not an international number")


PHONE = re.compile(r"\+[1-9][0-9]{6,14}")


@dataclass(frozen=True)
class Route:
    """Which decisions go to whom. `rules` are patterns over rule ids ("water-*");
    `tiers` are lists of people, the first told first."""

    rules: tuple
    tiers: tuple
    escalate_after_min: float = 30.0
    #: Urgent alerts reach people in their quiet hours.
    urgent: bool = False
    #: Tell everyone who heard of the alert when it clears.
    notify_clear: bool = True
    modules: tuple = ()

    def matches(self, decision: dict) -> bool:
        if self.modules and decision.get("module") not in self.modules:
            return False
        return any(fnmatch.fnmatchcase(decision.get("rule", ""), p) for p in self.rules)


@dataclass(frozen=True)
class Roster:
    farm: str
    timezone: str
    people: dict
    routes: tuple

    def __post_init__(self) -> None:
        for route in self.routes:
            for tier in route.tiers:
                for key in tier:
                    if key not in self.people:
                        raise ValueError(f"a route names {key!r}, who is not in the roster")

    @classmethod
    def from_json(cls, doc: dict) -> "Roster":
        people = {}
        for key, p in doc["people"].items():
            people[key] = Person(key, UUID(p["id"]), p.get("name", key), p.get("language", "en"),
                                 tuple((c["via"], c["address"]) for c in p["contacts"]),
                                 tuple(p["quiet"]) if p.get("quiet") else None)
        routes = tuple(Route(tuple(r["rules"]), tuple(tuple(t) for t in r["tiers"]),
                             float(r.get("escalate_after_min", 30.0)), bool(r.get("urgent", False)),
                             bool(r.get("notify_clear", True)), tuple(r.get("modules", ())))
                       for r in doc["routes"])
        return cls(doc.get("farm", ""), doc.get("timezone", "UTC"), people, routes)

    def route_for(self, decision: dict) -> Route | None:
        return next((r for r in self.routes if r.matches(decision)), None)

    def by_id(self, person_id: str) -> Person | None:
        return next((p for p in self.people.values() if str(p.id) == person_id), None)

    def local(self, at: _dt.datetime) -> _dt.datetime:
        from zoneinfo import ZoneInfo
        return at.astimezone(ZoneInfo(self.timezone))

    def quiet_for(self, person: Person, at: _dt.datetime) -> bool:
        if not person.quiet:
            return False
        now = self.local(at).strftime("%H:%M")
        start, end = person.quiet
        return (start <= now < end) if start <= end else (now >= start or now < end)


# ------------------------------------------------------------------ episodes

@dataclass
class Episode:
    """One raised alert, from its decision to its end, and everyone told about it."""

    decision_id: str
    decision: dict
    key: tuple                                     # (module, topic)
    route: Route
    code: str | None = None
    tier: int = -1                                 # the highest tier tried
    tier_at: _dt.datetime | None = None
    told: dict = field(default_factory=dict)       # person key -> first time reached
    tries: dict = field(default_factory=dict)      # (person key, reason) -> (n, last)
    noticed: set = field(default_factory=set)      # (person key, reason) sent
    acked: tuple | None = None                     # (person key or id, at)
    ended: str | None = None                       # cleared, superseded, expired
    ended_at: _dt.datetime | None = None
    tokens: dict = field(default_factory=dict)     # token sha256 -> person key

    @property
    def opened_at(self) -> _dt.datetime:
        return _dt.datetime.fromisoformat(self.decision["evaluated_at"])


@dataclass(frozen=True)
class Send:
    """A message due: about which alert, to whom, why."""

    episode: str
    person: str
    reason: str            # raised, escalated, acknowledged, cleared
    tier: int


@dataclass(frozen=True)
class Reply:
    """Something a person sent back: an SMS, or an ntfy button's request."""

    via: str
    sender: str | None
    text: str
    at: _dt.datetime
    ref: str


class Dispatcher:
    """Decides what to send, from the log alone. Pure: no clock, no network.

    `since` is when the farm installed it: decisions judged before then are history,
    not news, and are never sent.
    """

    def __init__(self, roster: Roster, since: _dt.datetime, *, rng=None) -> None:
        self.roster, self.since = roster, since
        self.episodes: dict[str, Episode] = {}
        self._open: dict[tuple, str] = {}          # (module, topic) -> episode id
        self._seen: set[str] = set()
        self._rng = rng or secrets.SystemRandom()
        self.unmatched_replies = 0

    # ------------------------------------------------------------- learning

    def learn(self, event) -> None:
        """Fold one event: a decision, a notification, an acknowledgement. Idempotent,
        so an event seen once on writing and again from the cursor counts once."""
        if str(event.id) in self._seen:
            return
        self._seen.add(str(event.id))
        p = event.payload
        if event.kind == R.DECISION:
            self._decision(str(event.id), p)
        elif event.kind == NOTIFICATION:
            ep = self.episodes.get(p.get("decision"))
            if ep is not None:
                self._notification(ep, p)
        elif event.kind == ACKNOWLEDGEMENT:
            ep = self.episodes.get(p.get("decision"))
            if ep is not None and ep.acked is None:
                person = self.roster.by_id(p.get("by", ""))
                ep.acked = (person.key if person else p.get("by"),
                            _dt.datetime.fromisoformat(p["at"]))

    def _decision(self, decision_id: str, p: dict) -> None:
        if "evaluated_at" not in p or "rule" not in p:
            return
        at = _dt.datetime.fromisoformat(p["evaluated_at"])
        key = (p.get("module"), R.topic_of(p))
        # A newer answer on the same question ends the old alert: cleared if it says
        # the alert is over, superseded if it raises a new one (tonight's frost
        # warning is not last night's).
        old = self._open.pop(key, None)
        if old is not None:
            ep = self.episodes[old]
            stale = ep.decision.get("valid_until")
            if stale and _dt.datetime.fromisoformat(stale) <= at:
                # It had stopped standing before this answer came, whenever it was
                # noticed: an all-clear for it would announce nothing.
                ep.ended, ep.ended_at = "expired", _dt.datetime.fromisoformat(stale)
            else:
                ep.ended = "cleared" if not p.get("alert") else "superseded"
                ep.ended_at = at
        if not p.get("alert") or at < self.since:
            return
        route = self.roster.route_for(p)
        if route is None:
            return
        self.episodes[decision_id] = Episode(decision_id, p, key, route)
        self._open[key] = decision_id

    def _notification(self, ep: Episode, p: dict) -> None:
        person = self.roster.by_id(p.get("person", ""))
        if person is None:
            return
        at = _dt.datetime.fromisoformat(p["at"])
        reason = p["reason"]
        if p.get("code") and ep.code is None:
            ep.code = p["code"]
        if p.get("token_sha256"):
            ep.tokens[p["token_sha256"]] = person.key
        if reason in ("raised", "escalated"):
            tier = int(p.get("tier", 0))
            if tier > ep.tier:
                ep.tier, ep.tier_at = tier, at
            if p.get("outcome") == "sent":
                ep.told.setdefault(person.key, at)
        # A try is a round: every channel a person has, tried at one moment, is one.
        n, last = ep.tries.get((person.key, reason), (0, None))
        ep.tries[(person.key, reason)] = (n if last == at else n + 1, at)
        if p.get("outcome") == "sent":
            ep.noticed.add((person.key, reason))

    # --------------------------------------------------------------- deciding

    def due(self, now: _dt.datetime) -> list[Send]:
        """What should go out now, in a stable order."""
        out = []
        for ep in self.episodes.values():
            if ep.ended is None and ep.decision.get("valid_until") and \
                    _dt.datetime.fromisoformat(ep.decision["valid_until"]) <= now:
                ep.ended, ep.ended_at = "expired", now
                self._open.pop(ep.key, None)
            out += self._due(ep, now)
        return out

    def _ready(self, ep: Episode, person: str, reason: str, now: _dt.datetime) -> bool:
        if (person, reason) in ep.noticed:
            return False
        n, last = ep.tries.get((person, reason), (0, None))
        if n >= MAX_TRIES or (last is not None and now - last < RETRY_AFTER):
            return False
        return ep.route.urgent or not self.roster.quiet_for(self.roster.people[person], now)

    def _due(self, ep: Episode, now: _dt.datetime) -> list[Send]:
        tiers = ep.route.tiers
        if ep.ended == "cleared":
            if not ep.route.notify_clear:
                return []
            return [Send(ep.decision_id, k, "cleared", -1) for k in ep.told
                    if self._ready(ep, k, "cleared", now)]
        if ep.ended is not None:
            return []
        if ep.acked is not None:
            return [Send(ep.decision_id, k, "acknowledged", -1) for k in ep.told
                    if k != ep.acked[0] and self._ready(ep, k, "acknowledged", now)]
        out = []
        # Anyone already due who was not reached, again.
        for t in range(0, ep.tier + 1):
            reason = "raised" if t == 0 else "escalated"
            out += [Send(ep.decision_id, k, reason, t) for k in tiers[t]
                    if k not in ep.told and self._ready(ep, k, reason, now)]
        nxt = ep.tier + 1
        if nxt < len(tiers):
            waited = ep.tier_at is None or now - ep.tier_at >= ep.route.escalate_after_min * MIN
            nobody = ep.tier >= 0 and not any(k in ep.told for k in tiers[ep.tier]) and \
                all(ep.tries.get((k, "raised" if ep.tier == 0 else "escalated"), (0,))[0] > 0
                    for k in tiers[ep.tier])
            if ep.tier < 0 or waited or nobody:
                reason = "raised" if nxt == 0 else "escalated"
                out += [Send(ep.decision_id, k, reason, nxt) for k in tiers[nxt]
                        if self._ready(ep, k, reason, now)]
        return out

    # -------------------------------------------------------------- codes

    def code_for(self, ep: Episode) -> str:
        """A three-digit number for SMS replies, unique among standing alerts."""
        if ep.code is None:
            taken = {e.code for e in self.episodes.values() if e.ended is None}
            while True:
                code = f"{self._rng.randrange(100, 1000)}"
                if code not in taken:
                    ep.code = code
                    break
        return ep.code

    # ------------------------------------------------------------- replies

    def match(self, reply: Reply) -> list[tuple[Episode, Person]]:
        """Which alerts a reply acknowledges, and who sent it. An SMS counts when it
        says yes in its sender's language or English and names alerts by number, or is
        a number alone; a yes with no number takes every open alert its sender was
        told about — two troughs on one silent radio are one errand. Anything that says
        no, "no puedo 417" included, acknowledges nothing."""
        if reply.via == "ntfy":
            m = re.fullmatch(r"\s*ack\s+([A-Za-z0-9_-]{8,})\s*", reply.text)
            digest = hashlib.sha256(m.group(1).encode()).hexdigest() if m else None
            found = [(ep, self.roster.people[ep.tokens[digest]]) for ep in self.episodes.values()
                     if digest in ep.tokens and ep.ended is None and ep.acked is None]
            self.unmatched_replies += not found
            return found
        senders = [p for p in self.roster.people.values()
                   if any(via == "sms" and same_number(a, reply.sender or "")
                          for via, a in p.contacts)]
        if not senders:
            self.unmatched_replies += 1
            return []
        person = senders[0]
        words = re.findall(r"[^\W\d_]+|\d+", re.sub(r"['’]", "", reply.text.lower()))
        codes = [w for w in words if re.fullmatch(r"\d{3}", w)]
        if any(w in words_of("notify.no_words", person.language) | words_of("notify.no_words", "en")
               for w in words):
            self.unmatched_replies += 1
            return []
        yes = words_of("notify.ack_words", person.language) | words_of("notify.ack_words", "en")
        said_yes = any(w in yes for w in words)
        open_eps = [ep for ep in self.episodes.values() if ep.ended is None and ep.acked is None]
        found = []
        if codes and (said_yes or len(words) == len(codes)):
            found = [(ep, person) for ep in open_eps if ep.code in codes]
        elif said_yes and not codes:
            found = [(ep, person) for ep in open_eps if person.key in ep.told]
        self.unmatched_replies += not found
        return found


def same_number(a: str, b: str) -> bool:
    """`+16155550123` and `6155550123` are one phone: a modem may report the sender
    without its country code. Seven digits or more must agree, from the end."""
    da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    short, long_ = sorted((da, db), key=len)
    return len(short) >= 7 and long_.endswith(short)


def words_of(key: str, language: str) -> set[str]:
    """A pack's comma-separated word list, lower-cased."""
    words = str(i18n.Translator(language).text(key))
    return {w.strip().lower() for w in words.split(",") if w.strip()}


# ------------------------------------------------------------------ messages

def message(roster: Roster, ep: Episode, person: Person, reason: str, via: str, state,
            now: _dt.datetime) -> str:
    """The text one person gets, in their language."""
    t = i18n.Translator(person.language)
    said = R.render(ep.decision, person.language, state) or ep.decision.get("rule", "?")
    if reason == "escalated":
        minutes = (now - ep.opened_at) / MIN
        said = str(t.text("notify.escalated", minutes=minutes, text=said))
    elif reason == "cleared":
        when = roster.local(ep.ended_at or now).strftime("%H:%M")
        said = str(t.text("notify.cleared", time=when, text=said))
    elif reason == "acknowledged":
        who = roster.people.get(ep.acked[0]) if ep.acked else None
        said = str(t.text("notify.acknowledged", who=who.name if who else "?", text=said))
    if via == "sms" and reason in ("raised", "escalated"):
        said = f"{said} {t.text('notify.reply_sms', code=ep.code)}"
    return str(t.text("notify.from", farm=roster.farm, text=said)) if roster.farm else said


_GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
_GSM7_EXT = set("^{}\\[~]|€\f")


def sms_segments(text: str) -> int:
    """How many SMS a text costs: 160 GSM-7 characters, or 70 once one character is
    outside it — "á" is, so most Spanish runs on the smaller budget (3GPP TS 23.038)."""
    if all(c in _GSM7 or c in _GSM7_EXT for c in text):
        n = sum(2 if c in _GSM7_EXT else 1 for c in text)
        return 1 if n <= 160 else math.ceil(n / 153)
    n = len(text.encode("utf-16-le")) // 2
    return 1 if n <= 70 else math.ceil(n / 67)


# ------------------------------------------------------------------ channels

class DeliveryError(Exception):
    pass


class Ntfy:
    """Push through an ntfy server: one topic per person, and one the farm reads its
    acknowledgements from. `token` publishes and reads; `ack_token`, embedded in each
    message's button, should be able to write the acknowledgement topic and nothing
    else, since everyone told holds it."""

    via = "ntfy"

    def __init__(self, server: str, ack_topic: str, *, token: str | None = None,
                 ack_token: str | None = None, timeout: float = 15.0, opener=None):
        self.server = server.rstrip("/")
        self.ack_topic, self.token, self.ack_token = ack_topic, token, ack_token
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self._since = "24h"

    def _request(self, url: str, body: bytes | None = None) -> bytes:
        req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self._open(req, timeout=self.timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise DeliveryError(f"ntfy: {exc}") from exc

    def send(self, address: str, text: str, *, title: str, urgent: bool,
             button: str | None = None, token: str | None = None) -> dict:
        msg = {"topic": address, "title": title, "message": text,
               "priority": 5 if urgent else 4, "tags": ["warning"]}
        if button and token:
            action = {"action": "http", "label": button, "method": "POST",
                      "url": f"{self.server}/{self.ack_topic}", "body": f"ack {token}",
                      "clear": True}
            if self.ack_token:
                action["headers"] = {"Authorization": f"Bearer {self.ack_token}"}
            msg["actions"] = [action]
        out = json.loads(self._request(self.server, json.dumps(msg).encode()) or b"{}")
        return {"ref": out.get("id")}

    def replies(self) -> list[Reply]:
        raw = self._request(f"{self.server}/{self.ack_topic}/json?poll=1&since={self._since}")
        out = []
        for line in raw.decode("utf-8", "replace").splitlines():
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("event") != "message":
                continue
            out.append(Reply("ntfy", None, m.get("message", ""),
                             _dt.datetime.fromtimestamp(m["time"], tz=_dt.timezone.utc), m["id"]))
            self._since = m["id"]
        return out

    def done(self, reply: Reply) -> None:
        pass                        # read past by the cursor; the server expires it


class Modem:
    """SMS through a cellular modem and ModemManager. `run(argv) -> stdout` runs
    `mmcli`, and raises on failure; the text goes in by file, so nothing in it is ever
    parsed as an argument."""

    via = "sms"

    def __init__(self, modem: str = "any", *, run=None, mmcli: str = "mmcli"):
        self.modem, self.mmcli = modem, mmcli
        self._run = run or self._subprocess

    @staticmethod
    def _subprocess(argv: list[str]) -> str:
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeliveryError(f"mmcli: {exc}") from exc
        if done.returncode != 0:
            raise DeliveryError(f"mmcli: {done.stderr.strip() or done.returncode}")
        return done.stdout

    def _json(self, *args: str) -> dict:
        out = self._run([self.mmcli, *args, "-J"])
        try:
            return json.loads(out)
        except ValueError as exc:
            raise DeliveryError(f"mmcli said something that is not JSON: {out[:80]!r}") from exc

    def send(self, address: str, text: str, **_) -> dict:
        if not PHONE.fullmatch(address):
            raise DeliveryError(f"not an international number: {address!r}")
        fd, path = tempfile.mkstemp(prefix="fieldmesh-sms-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as h:
                h.write(text)
            made = self._json("-m", self.modem, f"--messaging-create-sms=number='{address}'",
                              f"--messaging-create-sms-with-text={path}")
        finally:
            os.unlink(path)
        sms = made["modem"]["messaging"]["created-sms"]
        try:
            self._run([self.mmcli, "-s", sms, "--send"])
        finally:
            try:
                self._run([self.mmcli, "-m", self.modem, f"--messaging-delete-sms={sms}"])
            except DeliveryError:
                pass            # sent or not, a leftover in the modem's store is harmless
        return {"ref": sms, "segments": sms_segments(text)}

    def replies(self) -> list[Reply]:
        out = []
        for path in self._json("-m", self.modem, "--messaging-list-sms").get("modem.messaging.sms", []):
            sms = self._json("-s", path)["sms"]
            props, content = sms.get("properties", {}), sms.get("content", {})
            if props.get("pdu-type") != "deliver" or props.get("state") != "received":
                continue
            try:
                at = _dt.datetime.fromisoformat(props.get("timestamp", ""))
            except ValueError:
                at = _dt.datetime.now(tz=_dt.timezone.utc)
            out.append(Reply("sms", content.get("number"), content.get("text", ""), at, path))
        return out

    def done(self, reply: Reply) -> None:
        self._run([self.mmcli, "-m", self.modem, f"--messaging-delete-sms={reply.ref}"])


# ------------------------------------------------------------------ notifier

class Notifier:
    """The dispatcher, its channels and the log, one step at a time.

    `source.follow(after) -> (events, next)` is the log's arrival cursor — the host's
    for a module process, `LocalSource` in-process; `log.append` writes; `state`
    answers labels."""

    def __init__(self, roster: Roster, source, log, channels: dict, *, since: _dt.datetime,
                 rng=None) -> None:
        self.roster, self.source, self.log, self.channels = roster, source, log, channels
        self.dispatcher = Dispatcher(roster, since, rng=rng)
        self.cursor = 0
        self._rng = rng or secrets.SystemRandom()

    def catch_up(self) -> None:
        while True:
            events, nxt = self.source.follow(self.cursor)
            for e in events:
                self.dispatcher.learn(e)
            moved, self.cursor = nxt != self.cursor, nxt
            if not events or not moved:
                return

    def _write(self, kind: str, payload: dict):
        event = self.log.append(kind, payload)
        self.dispatcher.learn(event)
        return event

    def step(self, now: _dt.datetime, state=None) -> list:
        """Read what is new, take in replies, send what is due. Returns the events
        written."""
        self.catch_up()
        written = []
        for channel in self.channels.values():
            try:
                replies = channel.replies()
            except DeliveryError as exc:
                print(f"notify: no replies from {channel.via}: {exc}", file=sys.stderr)
                continue
            for reply in replies:
                for ep, person in self.dispatcher.match(reply):
                    written.append(self._write(ACKNOWLEDGEMENT, {
                        "decision": ep.decision_id, "by": str(person.id),
                        "at": now.isoformat(), "via": reply.via}))
                try:
                    channel.done(reply)
                except DeliveryError as exc:
                    print(f"notify: could not clear a reply: {exc}", file=sys.stderr)
        # What one round sends can make more due at once — a tier nobody in could be
        # reached hands on to the next — so look again until nothing new is due.
        for _ in range(8):
            sends = self.dispatcher.due(now)
            if not sends:
                break
            for send in sends:
                written += self._deliver(send, now, state)
        return written

    def _deliver(self, send: Send, now: _dt.datetime, state) -> list:
        ep = self.dispatcher.episodes[send.episode]
        person = self.roster.people[send.person]
        code = self.dispatcher.code_for(ep)
        t = i18n.Translator(person.language)
        written = []
        for via, address in person.contacts:
            channel = self.channels.get(via)
            if channel is None:
                continue
            payload = {"decision": ep.decision_id, "topic": ep.key[1], "person": str(person.id),
                       "reason": send.reason, "tier": send.tier, "code": code, "via": via,
                       "at": now.isoformat()}
            text = message(self.roster, ep, person, send.reason, via, state, now)
            token = None
            if via == "ntfy" and send.reason in ("raised", "escalated"):
                token = secrets.token_urlsafe(18)
                payload["token_sha256"] = hashlib.sha256(token.encode()).hexdigest()
            try:
                got = channel.send(address, text, title=self.roster.farm or "fieldmesh",
                                   urgent=ep.route.urgent,
                                   button=str(t.text("notify.button")), token=token)
                payload["outcome"] = "sent"
                if got.get("segments"):
                    payload["segments"] = got["segments"]
            except DeliveryError as exc:
                payload["outcome"], payload["error"] = "failed", str(exc)[:200]
            written.append(self._write(NOTIFICATION, payload))
            if payload["outcome"] == "sent":
                break
        return written


class LocalSource:
    """The arrival cursor over an in-process log, as the host's `follow` answers it."""

    def __init__(self, log, kinds=(R.DECISION, NOTIFICATION, ACKNOWLEDGEMENT)):
        self.log, self.kinds = log, set(kinds)

    def follow(self, after: int = 0) -> tuple:
        new = self.log.arrivals_since(after)
        return [e for e in new if e.kind in self.kinds], after + len(new)


def channels_from(config: dict, secret=lambda name: None) -> dict:
    out = {}
    if "ntfy" in config.get("channels", {}):
        c = config["channels"]["ntfy"]
        out["ntfy"] = Ntfy(c["server"], c["ack_topic"], token=secret("ntfy-token"),
                           ack_token=secret("ntfy-ack-token"))
    if "sms" in config.get("channels", {}):
        out["sms"] = Modem(config["channels"]["sms"].get("modem", "any"))
    return out


# ------------------------------------------------------------------- process

def _secret(name: str) -> str | None:
    """A systemd credential, or `FIELDMESH_<NAME>` for a run by hand."""
    creds = os.environ.get("CREDENTIALS_DIRECTORY")
    if creds and os.path.exists(os.path.join(creds, name)):
        with open(os.path.join(creds, name), encoding="utf-8") as h:
            return h.read().strip()
    return os.environ.get("FIELDMESH_" + name.upper().replace("-", "_"))


def main(argv=None) -> int:
    """The notifier as its own process (§8.3), over the host's socket. Its grant reads
    every module's decisions and acknowledgements and writes its own notifications."""
    import argparse
    import time
    import modhost as M

    ap = argparse.ArgumentParser(description="Notifications: decisions to people, with escalation")
    ap.add_argument("--socket", required=True)
    ap.add_argument("--config", required=True, help="the roster: people, routes, channels (JSON)")
    ap.add_argument("--every", type=float, default=60.0, help="seconds between looks")
    ap.add_argument("--once", action="store_true", help="one look, then exit")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as h:
        config = json.load(h)
    roster = Roster.from_json(config)
    channels = channels_from(config, _secret)
    with M.ModuleClient(args.socket, M.token_from_environment()) as client:
        who = client.call("whoami")
        since = _dt.datetime.fromisoformat(who["granted_at"])

        class Source:
            def follow(self, after=0):
                return client.follow(after)

        notifier = Notifier(roster, Source(), client.log(), channels, since=since)
        while True:
            now = _dt.datetime.now(tz=_dt.timezone.utc)
            for event in notifier.step(now, client.state(now)):
                p = event.payload
                print(json.dumps({"kind": event.kind, "reason": p.get("reason"),
                                  "via": p.get("via"), "outcome": p.get("outcome"),
                                  "decision": p.get("decision")}), flush=True)
            if args.once:
                return 0
            time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
