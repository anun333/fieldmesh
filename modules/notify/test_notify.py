#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Notifications: escalation, acknowledgement, the two channels, and the water monitor's
alerts carried to people on Harrow Bend."""
from __future__ import annotations

import datetime as _dt
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sim"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "water"))

try:
    import celpy  # noqa: F401
    HAVE_CEL = True
except ImportError:
    HAVE_CEL = False

from ids import uuid7  # noqa: E402
from log import Log  # noqa: E402
from model import Label  # noqa: E402
from project import State  # noqa: E402

import notify as N  # noqa: E402

MIN = _dt.timedelta(minutes=1)
UTC = _dt.timezone.utc
T0 = _dt.datetime(2026, 7, 14, 18, tzinfo=UTC)          # 1 pm in Tennessee
MARIA, SAM = uuid7(), uuid7()
TROUGH = uuid7()


def roster(**changes) -> dict:
    doc = {"farm": "Harrow Bend", "timezone": "America/Chicago",
           "people": {"maria": {"id": str(MARIA), "name": "María", "language": "es",
                                "contacts": [{"via": "sms", "address": "+16155550101"}]},
                      "sam": {"id": str(SAM), "name": "Sam", "language": "en",
                              "contacts": [{"via": "ntfy", "address": "hb-sam"},
                                           {"via": "sms", "address": "+16155550102"}]}},
           "routes": [{"rules": ["water-*"], "tiers": [["maria"], ["sam"]],
                       "escalate_after_min": 30, "urgent": True},
                      {"rules": ["frost-watch"], "tiers": [["sam", "maria"]],
                       "notify_clear": False}]}
    doc.update(changes)
    return doc


class Phone:
    """A channel that records what it sent and hands back what people replied."""

    def __init__(self, via, *, down=()):
        self.via, self.down = via, set(down)
        self.sent, self.inbox, self.cleared = [], [], []

    def send(self, address, text, **kw):
        if address in self.down:
            raise N.DeliveryError(f"{address} unreachable")
        self.sent.append((address, text, kw))
        return {"ref": str(len(self.sent)),
                "segments": N.sms_segments(text) if self.via == "sms" else None}

    def replies(self):
        out, self.inbox = self.inbox, []
        return out

    def done(self, reply):
        self.cleared.append(reply.ref)

    def to(self, address):
        return [text for a, text, _ in self.sent if a == address]


class Farm:
    def __init__(self, doc=None, *, since=T0 - 60 * MIN, sms_down=(), ntfy_down=()):
        self.log, self.state = Log(), State()
        for name, lang in (("north trough", "en"), ("bebedero norte", "es")):
            self.state.add(Label(uuid7(), TROUGH, name, T0 - 600 * MIN, language=lang))
        self.sms, self.ntfy = Phone("sms", down=sms_down), Phone("ntfy", down=ntfy_down)
        self.roster = N.Roster.from_json(doc or roster())
        self.since = since
        self.notifier = self.fresh()

    def fresh(self):
        return N.Notifier(self.roster, N.LocalSource(self.log), self.log,
                          {"sms": self.sms, "ntfy": self.ntfy}, since=self.since)

    def decide(self, rule, alert, at, *, subject=TROUGH, key="water.empty", **extra):
        message = None
        if alert and key == "rules.frost.alert":
            message = {"key": key, "params": {"low": -1.5, "warn": 0.0}}
        elif alert:
            params = {"hours": 0.6} if key == "water.unseen" else {"percent": 6.0}
            message = {"key": key, "params": params, "subject_param": "trough"}
        return self.log.append("decision", {"rule": rule, "subject": str(subject) if subject else None,
                                            "alert": alert, "evaluated_at": at.isoformat(),
                                            "message": message, **extra})

    def step(self, at, notifier=None):
        return (notifier or self.notifier).step(at, self.state)

    def notifications(self, **match):
        return [e.payload for e in self.log.events if e.kind == "notification"
                and all(e.payload.get(k) == v for k, v in match.items())]


class TestRoster(unittest.TestCase):
    def test_a_roster_must_be_able_to_reach_everyone_it_names(self):
        bad = roster()
        bad["routes"][0]["tiers"] = [["maria"], ["nobody"]]
        with self.assertRaisesRegex(ValueError, "nobody"):
            N.Roster.from_json(bad)
        for contacts in ([], [{"via": "sms", "address": "615-555-0101"}],
                         [{"via": "pigeon", "address": "the barn"}]):
            doc = roster()
            doc["people"]["maria"]["contacts"] = contacts
            with self.assertRaises(ValueError):
                N.Roster.from_json(doc)

    def test_quiet_hours_cross_midnight_in_the_farms_own_time(self):
        doc = roster()
        doc["people"]["sam"]["quiet"] = ["21:00", "06:00"]
        r = N.Roster.from_json(doc)
        sam = r.people["sam"]
        central = lambda h: _dt.datetime(2026, 7, 14, h, tzinfo=UTC) + 5 * 60 * MIN  # CDT
        self.assertTrue(r.quiet_for(sam, central(23)))
        self.assertTrue(r.quiet_for(sam, central(5)))
        self.assertFalse(r.quiet_for(sam, central(6)))
        self.assertFalse(r.quiet_for(sam, central(20)))

    def test_a_sender_without_a_country_code_is_still_known(self):
        self.assertTrue(N.same_number("+16155550101", "6155550101"))
        self.assertFalse(N.same_number("+16155550101", "+16155550102"))
        self.assertFalse(N.same_number("+16155550101", "0101"))


class TestEscalation(unittest.TestCase):
    def test_an_alert_climbs_the_tiers_until_someone_answers(self):
        f = Farm()
        up = f.decide("water-empty", True, T0)
        f.step(T0)
        [to_maria] = f.sms.to("+16155550101")
        self.assertIn("Harrow Bend: bebedero norte está casi vacío", to_maria)
        code = f.notifications(reason="raised")[0]["code"]
        self.assertIn(f"Responda OK {code}", to_maria)
        self.assertEqual(f.ntfy.sent, [], "the owner is not told yet")
        f.step(T0 + 20 * MIN)
        self.assertEqual(f.ntfy.sent, [])
        f.step(T0 + 30 * MIN)
        [(topic, to_sam, kw)] = f.ntfy.sent
        self.assertEqual(topic, "hb-sam")
        self.assertIn("Nobody has answered this for 30 minutes. north trough is nearly empty", to_sam)
        self.assertEqual((kw["button"], kw["urgent"]), ("I'm on it", True))
        # Sam presses "I'm on it": the button posts the token to the farm's topic.
        f.ntfy.inbox.append(N.Reply("ntfy", None, f"ack {kw['token']}", T0 + 33 * MIN, "m1"))
        f.step(T0 + 34 * MIN)
        [ack] = [e for e in f.log.events if e.kind == "acknowledgement"]
        self.assertEqual((ack.payload["decision"], ack.payload["by"], ack.payload["via"]),
                         (str(up.id), str(SAM), "ntfy"))
        self.assertIn("Sam se encarga: bebedero norte", f.sms.to("+16155550101")[-1])
        before = len(f.sms.sent) + len(f.ntfy.sent)
        f.step(T0 + 120 * MIN)
        self.assertEqual(len(f.sms.sent) + len(f.ntfy.sent), before, "answered: nothing more")
        f.decide("water-empty", False, T0 + 150 * MIN)
        f.step(T0 + 151 * MIN)
        self.assertIn("Ya no es así (15:30): bebedero norte", f.sms.to("+16155550101")[-1])
        self.assertIn("No longer the case (15:30): north trough", f.ntfy.sent[-1][1])

    def test_alerts_due_together_go_as_one_message_with_one_button(self):
        f = Farm()
        north, south = f.decide("water-unseen", True, T0, key="water.unseen"), \
            f.decide("water-unseen", True, T0, subject=uuid7(), key="water.unseen")
        f.step(T0)
        [(_, sms, _)] = f.sms.sent
        codes = [n["code"] for n in f.notifications(reason="raised")]
        self.assertTrue(sms.startswith("Harrow Bend: 2 alertas: 1) No llega nada de bebedero norte"), sms)
        self.assertIn(f"u OK y un número para una: {codes[0]}, {codes[1]}.", sms)
        raised = f.notifications(reason="raised")
        self.assertEqual(len(raised), 2, "one event per alert")
        self.assertEqual(len({n["batch"] for n in raised}), 1, "tied by one batch")
        self.assertEqual([("segments" in n) for n in raised], [True, False], "its cost counted once")
        f.step(T0 + 30 * MIN)
        [(_, push, kw)] = f.ntfy.sent
        self.assertIn("Nobody has answered these for 30 minutes. 2 alerts: 1) Nothing heard", push)
        f.ntfy.inbox.append(N.Reply("ntfy", None, f"ack {kw['token']}", T0 + 31 * MIN, "m"))
        f.step(T0 + 31 * MIN)
        acked = {e.payload["decision"] for e in f.log.events if e.kind == "acknowledgement"}
        self.assertEqual(acked, {str(north.id), str(south.id)}, "one button takes them all")

    def test_a_restart_carries_on_from_the_log(self):
        f = Farm()
        f.decide("water-empty", True, T0)
        f.step(T0)
        again = f.fresh()                                    # the process restarted
        again.step(T0 + 10 * MIN, f.state)
        self.assertEqual(len(f.sms.sent), 1, "not sent twice")
        again.step(T0 + 30 * MIN, f.state)
        self.assertEqual(len(f.ntfy.sent), 1, "and escalated on the original clock")
        self.assertEqual(again.dispatcher.episodes[f.notifications()[0]["decision"]].code,
                         f.notifications()[0]["code"])

    def test_a_tier_nobody_in_could_be_reached_hands_on_at_once_and_is_tried_again(self):
        f = Farm(sms_down={"+16155550101"})
        f.decide("water-empty", True, T0)
        f.step(T0)
        self.assertEqual(len(f.ntfy.sent), 1, "Sam hears at once, not in half an hour")
        self.assertEqual([p["outcome"] for p in f.notifications(reason="raised")], ["failed"])
        f.sms.down.clear()
        f.step(T0 + 5 * MIN)
        self.assertEqual(f.sms.sent, [], "not before the retry interval")
        f.step(T0 + 10 * MIN)
        self.assertEqual(len(f.sms.to("+16155550101")), 1)

    def test_a_person_unreachable_by_push_gets_the_sms(self):
        f = Farm(ntfy_down={"hb-sam"})
        f.decide("water-empty", True, T0)
        f.step(T0)
        f.step(T0 + 30 * MIN)
        self.assertEqual([(p["via"], p["outcome"]) for p in f.notifications(person=str(SAM))],
                         [("ntfy", "failed"), ("sms", "sent")])
        self.assertIn("Reply OK", f.sms.to("+16155550102")[0])

    def test_quiet_hours_hold_what_is_not_urgent(self):
        doc = roster()
        for person in doc["people"].values():
            person["quiet"] = ["21:00", "06:00"]
        f = Farm(doc, since=T0)
        night = _dt.datetime(2026, 7, 15, 4, tzinfo=UTC)          # 11 pm in Tennessee
        f.decide("frost-watch", True, night, subject=None, key="rules.frost.alert",
                 valid_until=(night + 14 * 60 * MIN).isoformat())
        f.decide("water-empty", True, night)
        f.step(night)
        self.assertEqual(len(f.sms.to("+16155550101")), 1, "the trough is urgent")
        self.assertEqual(f.ntfy.sent, [], "the frost watch waits")
        f.step(night + 30 * MIN)
        [escalated] = f.ntfy.sent
        self.assertIn("north trough", escalated[1], "and so is its escalation, at night")
        f.step(night + 7 * 60 * MIN)                                # 6 am
        self.assertIn("Frost warning", f.ntfy.sent[-1][1])
        self.assertEqual(len(f.ntfy.sent), 2)

    def test_a_new_answer_ends_the_old_alert_and_an_answer_goes_stale(self):
        f = Farm(since=T0)
        night = 14 * 60 * MIN
        first = f.decide("frost-watch", True, T0, subject=None, key="rules.frost.alert",
                         valid_until=(T0 + night).isoformat())
        f.step(T0)
        self.assertEqual(len(f.ntfy.sent), 1)
        f.step(T0 + night + MIN)
        ep = f.notifier.dispatcher.episodes[str(first.id)]
        self.assertEqual(ep.ended, "expired")
        second = f.decide("frost-watch", True, T0 + 24 * 60 * MIN, subject=None,
                          key="rules.frost.alert", valid_until=(T0 + 24 * 60 * MIN + night).isoformat())
        f.step(T0 + 24 * 60 * MIN)
        self.assertEqual(len(f.ntfy.sent), 2, "tonight's warning is news again")
        f.decide("frost-watch", False, T0 + 48 * 60 * MIN, subject=None)
        f.step(T0 + 48 * 60 * MIN)
        self.assertEqual(f.notifier.dispatcher.episodes[str(second.id)].ended, "expired")
        self.assertEqual(len(f.ntfy.sent), 2, "no all-clear for a frost watch")

    def test_history_before_the_notifier_was_installed_is_not_news(self):
        f = Farm(since=T0)
        f.decide("water-empty", True, T0 - 5 * MIN)
        f.step(T0)
        self.assertEqual(f.sms.sent, [])

    def test_a_decision_no_route_names_goes_nowhere(self):
        f = Farm()
        f.decide("soil-enough", True, T0)
        f.step(T0)
        self.assertEqual((f.sms.sent, f.ntfy.sent), ([], []))

    def test_the_log_names_people_and_never_their_numbers(self):
        f = Farm()
        f.decide("water-empty", True, T0)
        for m in (0, 30, 60):
            f.step(T0 + m * MIN)
        text = json.dumps([e.to_jsonable() for e in f.log.events])
        self.assertNotIn("6155550101", text)
        self.assertNotIn("6155550102", text)
        self.assertNotIn("hb-sam", text)
        self.assertIn(str(MARIA), text)
        [n] = f.notifications(person=str(MARIA))
        self.assertEqual(n["segments"], N.sms_segments(f.sms.sent[0][1]))
        self.assertGreater(n["segments"], 1, "Spanish runs on the 70-character budget")


class TestReplies(unittest.TestCase):
    def setUp(self):
        self.f = Farm()
        self.up = self.f.decide("water-empty", True, T0)
        self.f.step(T0)
        self.code = self.f.notifications()[0]["code"]

    def reply(self, text, sender="+16155550101", at=None):
        self.f.sms.inbox.append(N.Reply("sms", sender, text, at or T0 + 5 * MIN, f"/sms/{text}"))
        return self.f.step(T0 + 5 * MIN)

    def acks(self):
        return [e for e in self.f.log.events if e.kind == "acknowledgement"]

    def test_ok_and_the_number_acknowledges(self):
        self.reply(f"Ok {self.code}")
        [ack] = self.acks()
        self.assertEqual((ack.payload["by"], ack.payload["via"]), (str(MARIA), "sms"))
        self.assertEqual(self.f.sms.cleared, [f"/sms/Ok {self.code}"], "taken off the modem")

    def test_the_number_alone_acknowledges(self):
        self.reply(self.code)
        self.assertEqual(len(self.acks()), 1)

    def test_yes_alone_takes_every_alert_its_sender_was_told_about(self):
        f = Farm()
        f.decide("water-unseen", True, T0, key="water.unseen")
        f.decide("water-unseen", True, T0, subject=uuid7(), key="water.unseen")   # one radio
        f.step(T0)
        self.assertEqual(len(f.sms.sent), 1, "two alerts due together are one message")
        f.sms.inbox.append(N.Reply("sms", "6155550101", "Sí, voy", T0 + 5 * MIN, "x"))
        f.step(T0 + 5 * MIN)
        self.assertEqual(len([e for e in f.log.events if e.kind == "acknowledgement"]), 2)
        f.step(T0 + 40 * MIN)
        self.assertEqual(f.ntfy.sent, [], "so neither climbs to Sam")

    def test_a_reply_that_says_no_is_never_an_acknowledgement(self):
        for text in (f"no puedo {self.code}", f"si no puedo, {self.code}", f"can't {self.code}",
                     "who is this?", f"ok {int(self.code) % 900 + 101}"):
            self.reply(text)
        self.assertEqual(self.acks(), [])
        self.assertEqual(self.f.notifier.dispatcher.unmatched_replies, 5)
        self.f.step(T0 + 30 * MIN)
        self.assertEqual(len(self.f.ntfy.sent), 1, "so it still escalates")

    def test_a_stranger_cannot_acknowledge(self):
        self.reply(f"OK {self.code}", sender="+19995550000")
        self.assertEqual(self.acks(), [])


class FakeMmcli:
    """`mmcli` as ModemManager 1.23 answers, from its source (cli/mmcli-output.c): a
    list is `{"modem.messaging.sms": [...]}`, a created SMS is under
    `modem.messaging.created-sms`, an SMS is `sms.content` and `sms.properties`."""

    def __init__(self):
        self.calls, self.texts, self.store = [], [], {}
        self.next = 7

    def __call__(self, argv):
        self.calls.append(argv)
        args = argv[1:]
        if any(a.startswith("--messaging-create-sms=") for a in args):
            text_file = next(a.split("=", 1)[1] for a in args
                             if a.startswith("--messaging-create-sms-with-text="))
            with open(text_file, encoding="utf-8") as h:
                self.texts.append(h.read())
            path = f"/org/freedesktop/ModemManager1/SMS/{self.next}"
            self.next += 1
            return json.dumps({"modem": {"messaging": {"created-sms": path}}})
        if "--messaging-list-sms" in args:
            return json.dumps({"modem.messaging.sms": sorted(self.store)})
        if args[0] == "-s" and "-J" in args:
            number, text, state, pdu = self.store[args[1]]
            return json.dumps({"sms": {
                "content": {"data": "--", "number": number, "text": text},
                "dbus-path": args[1],
                "properties": {"class": "--", "delivery-report": "--", "pdu-type": pdu,
                               "state": state, "storage": "me", "smsc": "+12063130004",
                               "timestamp": "2026-07-14T13:05:12-05:00", "validity": "--"}}})
        if any(a.startswith("--messaging-delete-sms=") for a in args):
            self.store.pop(next(a.split("=", 1)[1] for a in args
                                if a.startswith("--messaging-delete-sms=")), None)
            return "successfully deleted SMS from modem\n"
        if "--send" in args:
            return "successfully sent the SMS\n"
        raise AssertionError(argv)


class TestChannels(unittest.TestCase):
    def test_the_modem_takes_the_text_by_file_and_reads_replies(self):
        mm = FakeMmcli()
        modem = N.Modem(run=mm)
        text = "Harrow Bend: bebedero norte está casi vacío. Responda OK 417 cuando alguien se encargue."
        got = modem.send("+16155550101", text)
        self.assertEqual(mm.texts, [text])
        create = mm.calls[0]
        self.assertIn("--messaging-create-sms=number='+16155550101'", create)
        self.assertNotIn(text, " ".join(create), "the text is never an argument")
        self.assertEqual([c[1:3] for c in mm.calls[1:]],
                         [["-s", "/org/freedesktop/ModemManager1/SMS/7"],
                          ["-m", "any"]])
        self.assertEqual(got["segments"], 2)
        with self.assertRaises(N.DeliveryError):
            modem.send("615; rm -rf /", "x")
        mm.store["/org/freedesktop/ModemManager1/SMS/3"] = ("+16155550101", "Ok 417", "received", "deliver")
        mm.store["/org/freedesktop/ModemManager1/SMS/4"] = ("+16155550101", "draft", "stored", "submit")
        [reply] = modem.replies()
        self.assertEqual((reply.sender, reply.text, reply.at.utcoffset()),
                         ("+16155550101", "Ok 417", -_dt.timedelta(hours=5)))
        modem.done(reply)
        self.assertNotIn(reply.ref, mm.store)

    def test_a_modem_that_fails_says_so(self):
        def broken(argv):
            raise N.DeliveryError("mmcli: error: couldn't find modem")
        with self.assertRaisesRegex(N.DeliveryError, "couldn't find modem"):
            N.Modem(run=broken).send("+16155550101", "x")

    def test_ntfy_posts_one_message_with_a_button_that_acknowledges(self):
        seen = []

        class Resp:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.body

        def opener(req, timeout):
            seen.append(req)
            if req.get_method() == "POST":
                return Resp(b'{"id":"abc","event":"message"}')
            lines = [{"id": "m1", "time": 1784048700, "event": "open"},
                     {"id": "m2", "time": 1784048712, "event": "message", "message": "ack tok123456"}]
            return Resp("\n".join(json.dumps(x) for x in lines).encode())

        n = N.Ntfy("https://ntfy.example.org/", "hb-acks", token="tk_pub", ack_token="tk_ack",
                   opener=opener)
        n.send("hb-sam", "north trough is nearly empty", title="Harrow Bend", urgent=True,
               button="I'm on it", token="tok123456")
        body = json.loads(seen[0].data)
        self.assertEqual(seen[0].full_url, "https://ntfy.example.org")
        self.assertEqual(seen[0].get_header("Authorization"), "Bearer tk_pub")
        self.assertEqual((body["topic"], body["priority"], body["title"]), ("hb-sam", 5, "Harrow Bend"))
        [action] = body["actions"]
        self.assertEqual((action["url"], action["body"], action["headers"]["Authorization"]),
                         ("https://ntfy.example.org/hb-acks", "ack tok123456", "Bearer tk_ack"))
        [reply] = n.replies()
        self.assertEqual((reply.text, reply.ref), ("ack tok123456", "m2"))
        self.assertTrue(seen[1].full_url.endswith("/hb-acks/json?poll=1&since=24h"))
        n.replies()
        self.assertTrue(seen[2].full_url.endswith("since=m2"), "read past by the cursor")

    def test_segments_are_counted_as_the_network_bills_them(self):
        self.assertEqual(N.sms_segments("a" * 160), 1)
        self.assertEqual(N.sms_segments("a" * 161), 2)
        self.assertEqual(N.sms_segments("ñ" * 160), 1, "ñ is in GSM-7")
        self.assertEqual(N.sms_segments("á" * 70), 1)
        self.assertEqual(N.sms_segments("á" * 71), 2, "á is not")
        self.assertEqual(N.sms_segments("{" * 80), 1)
        self.assertEqual(N.sms_segments("{" * 81), 2, "an escaped character costs two")


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestOnHarrowBend(unittest.TestCase):
    """The water monitor's season on Harrow Bend — the radio out for twelve hours on day
    2, the south trough's float stuck on day 9 — with the notifier looking every ten
    minutes. María checks the troughs and reads Spanish on a basic phone; Sam owns the
    farm and has the push app. Nobody answers, so every alert climbs to Sam."""

    DAYS = 10.0
    EVERY = 10 * MIN

    @classmethod
    def setUpClass(cls):
        import harrow_bend as hb
        import water as W
        cls.farm = hb.build(seed=1)
        start = cls.farm.world.start
        cls.farm.links["paddock"].outage((start + _dt.timedelta(days=2)).timestamp(),
                                         (start + _dt.timedelta(days=2.5)).timestamp())
        hb.season(cls.farm, days=cls.DAYS)
        troughs = [W.Trough(cls.farm.series["trough_north"].derived.id, capacity_l=400.0),
                   W.Trough(cls.farm.series["trough_south"].derived.id, capacity_l=250.0)]
        cls.south = str(troughs[1].datastream)
        cls.sms, cls.ntfy = Phone("sms"), Phone("ntfy")
        monitor = W.Monitor(cls.farm.log)
        notifier = N.Notifier(N.Roster.from_json(roster()), N.LocalSource(cls.farm.log),
                              cls.farm.log, {"sms": cls.sms, "ntfy": cls.ntfy}, since=start)
        cls.sent_at = {}
        t = start + cls.EVERY
        while t <= start + _dt.timedelta(days=cls.DAYS):
            monitor.check(cls.farm.state, troughs, t)
            for e in notifier.step(t, cls.farm.state):
                if e.kind == "notification":
                    cls.sent_at.setdefault((e.payload["decision"], e.payload["reason"]), t)
            t += cls.EVERY
        cls.decisions = {str(e.id): e.payload for e in cls.farm.log.events if e.kind == "decision"}
        cls.notes = [e.payload for e in cls.farm.log.events if e.kind == "notification"]

    def test_every_alert_reached_the_first_tier_at_the_next_look(self):
        raised = [d for d, p in self.decisions.items() if p["alert"]
                  and p["rule"].startswith("water-")]
        self.assertTrue(raised)
        for d in raised:
            when = _dt.datetime.fromisoformat(self.decisions[d]["evaluated_at"])
            self.assertLessEqual(self.sent_at[(d, "raised")] - when, self.EVERY, self.decisions[d]["rule"])

    def test_the_stuck_float_reached_the_owner_half_an_hour_later_in_his_language(self):
        [d] = [d for d, p in self.decisions.items() if p["alert"]
               and p["rule"] == "water-not-refilling" and p["subject"] == self.south]
        self.assertEqual(self.sent_at[(d, "escalated")] - self.sent_at[(d, "raised")], 30 * MIN)
        to_maria = [t for t in self.sms.to("+16155550101") if "bebedero sur" in t]
        self.assertTrue(any("no se ha vuelto a llenar" in t for t in to_maria))
        self.assertTrue(any("has not refilled" in t for _, t, _ in self.ntfy.sent))

    def test_the_outage_was_one_message_to_each_person_not_one_per_trough(self):
        unseen = {d for d, p in self.decisions.items() if p["alert"] and p["rule"] == "water-unseen"}
        self.assertEqual(len(unseen), 2)
        for reason in ("raised", "escalated", "cleared"):
            notes = [n for n in self.notes if n["decision"] in unseen and n["reason"] == reason]
            self.assertEqual(len(notes), 2 if reason != "cleared" else 4, reason)
            self.assertEqual(len({(n["person"], n["batch"]) for n in notes}),
                             1 if reason != "cleared" else 2, reason)

    def test_what_a_season_of_alerts_costs(self):
        """Ten days, two troughs: the count a farmer would live with. A message is one
        batch, and SMS segments are what a modem's plan bills."""
        alerts = sum(1 for p in self.decisions.values() if p["alert"])
        sent = [n for n in self.notes if n["outcome"] == "sent"]
        messages = {n.get("batch") or (n["decision"], n["person"], n["reason"]) for n in sent}
        self.assertEqual(len(messages), len(self.sms.sent) + len(self.ntfy.sent))
        self.assertLess(len(messages), 4 * alerts, "fewer than one message per alert per person")
        segments = sum(n.get("segments", 0) for n in self.notes)
        self.assertEqual(segments, sum(N.sms_segments(t) for _, t, _ in self.sms.sent))
        self.assertLessEqual(max(N.sms_segments(t) for _, t, _ in self.sms.sent), 6,
                             "the outage's two alerts in Spanish are the longest message")
        self.__class__.summary = (alerts, len(self.sms.sent), len(self.ntfy.sent), segments)


class FakeNtfyServer:
    """Enough of an ntfy server, over real HTTP, for a process to publish to."""

    def __init__(self):
        self.posts = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                outer.posts.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self._reply(b'{"id":"x1","event":"message"}')

            def do_GET(self):
                self._reply(b"")

            def _reply(self, body):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class TestAsItsOwnProcess(unittest.TestCase):
    """Q11: the notifier as a module process, granted every module's decisions and
    nothing of the farm's readings, publishing to an ntfy server over HTTP."""

    def setUp(self):
        import modhost as M
        self.M = M
        self.log, self.state = Log(), State()
        self.dir = tempfile.mkdtemp(prefix="fm-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.path = os.path.join(self.dir, "m.sock")
        self.host = M.ModuleHost(self.log, self.state, self.path).start()
        self.ntfy = FakeNtfyServer()

    def tearDown(self):
        self.host.stop()
        self.ntfy.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_it_tells_people_what_another_module_decided(self):
        M = self.M
        water, water_token = M.grant(self.log, M.Manifest.load(
            os.path.join(HERE, os.pardir, "water", "module.json")), at=T0 - 60 * MIN)
        _, token = M.grant(self.log, M.Manifest.load(os.path.join(HERE, "module.json")),
                           at=T0 - 60 * MIN)
        self.assertEqual(self.log.events[-1].payload["events"], ["acknowledgement", "decision"])
        with M.ModuleClient(self.path, water_token) as w:
            w.call("append", kind="decision", payload={
                "rule": "water-empty", "subject": str(TROUGH), "alert": True,
                "evaluated_at": _dt.datetime.now(tz=UTC).isoformat(),
                "message": {"key": "water.empty", "params": {"percent": 6.0},
                            "subject_param": "trough"}})
        doc = roster(channels={"ntfy": {"server": self.ntfy.url, "ack_topic": "hb-acks"}})
        doc["people"]["maria"]["contacts"] = [{"via": "ntfy", "address": "hb-maria"}]
        config = os.path.join(self.dir, "notify.json")
        with open(config, "w", encoding="utf-8") as h:
            json.dump(doc, h)
        done = subprocess.run([sys.executable, "-I", os.path.join(HERE, "notify.py"),
                               "--socket", self.path, "--config", config, "--once"],
                              env={"FIELDMESH_MODULE_TOKEN": token, "PATH": os.environ.get("PATH", "")},
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        [post] = self.ntfy.posts
        self.assertEqual(post["topic"], "hb-maria")
        self.assertIn("está casi vacío", post["message"])
        self.assertEqual(post["actions"][0]["url"], f"{self.ntfy.url}/hb-acks")
        [n] = [e.payload for e in self.log.events if e.kind == "notification"]
        self.assertEqual((n["module"], n["outcome"], n["via"]), ("notify", "sent", "ntfy"))


@unittest.skipUnless(os.environ.get("FIELDMESH_NTFY_SERVER"),
                     "set FIELDMESH_NTFY_SERVER to a scratch ntfy server to check against a real one")
class TestAgainstARealNtfyServer(unittest.TestCase):
    """The push channel against a real ntfy server: publish, then press the button the
    way the phone app does, and read the acknowledgement back."""

    def test_publish_and_acknowledge(self):
        """With FIELDMESH_NTFY_TOKEN and FIELDMESH_NTFY_ACK_TOKEN as well, against a
        server that denies by default: the notifier's token publishes to `hb-*` and
        reads; the phone's — the one in every button — writes `hb-acks` only."""
        server = os.environ["FIELDMESH_NTFY_SERVER"]
        token, ack_token = os.environ.get("FIELDMESH_NTFY_TOKEN"), os.environ.get("FIELDMESH_NTFY_ACK_TOKEN")
        if token:
            topic, acks = "hb-sam", "hb-acks"
        else:
            topic, acks = f"fm-test-{uuid7().hex[:12]}", f"fm-acks-{uuid7().hex[:12]}"
        n = N.Ntfy(server, acks, token=token, ack_token=ack_token)
        sent = n.send(topic, "north trough is nearly empty", title="Harrow Bend", urgent=True,
                      button="I'm on it", token="tok_abcdefgh123")
        self.assertTrue(sent["ref"])

        def get(url, bearer=None, body=None, method="GET"):
            req = urllib.request.Request(url, data=body, method=method)
            if bearer:
                req.add_header("Authorization", f"Bearer {bearer}")
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.read()

        lines = get(f"{server}/{topic}/json?poll=1&since=all", token).decode().splitlines()
        got = json.loads(lines[-1])
        self.assertEqual((got["title"], got["priority"]), ("Harrow Bend", 5))
        [action] = got["actions"]
        # The phone presses the button: the request it makes is the action's own.
        press = urllib.request.Request(action["url"], data=action["body"].encode(),
                                       method=action["method"])
        for name, value in (action.get("headers") or {}).items():
            press.add_header(name, value)
        urllib.request.urlopen(press, timeout=10).close()
        replies = n.replies()
        self.assertEqual(replies[-1].text, "ack tok_abcdefgh123")
        if ack_token:
            for url, body in ((f"{server}/{acks}/json?poll=1&since=all", None),
                              (f"{server}/{topic}", b"forged")):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    get(url, ack_token, body, "POST" if body else "GET")
                self.assertEqual(caught.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
