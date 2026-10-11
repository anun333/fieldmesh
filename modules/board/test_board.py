#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The farm's board: what stands, who was told, what cleared, said in each language,
and served read-only."""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import os
import re
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

from ids import uuid7  # noqa: E402
from log import Log  # noqa: E402
from model import Label  # noqa: E402
from project import State  # noqa: E402

import board as B  # noqa: E402

MIN = _dt.timedelta(minutes=1)
UTC = _dt.timezone.utc
T0 = _dt.datetime(2026, 7, 14, 18, tzinfo=UTC)          # 1 pm in Tennessee
MARIA, SAM = str(uuid7()), str(uuid7())
NORTH, SOUTH, BED = uuid7(), uuid7(), uuid7()
BOARD = B.Board("Harrow Bend", "America/Chicago", ("en", "es"), {MARIA: "María", SAM: "Sam"})


class Farm:
    def __init__(self):
        self.log, self.state = Log(), State()
        for entity, en, es in ((NORTH, "north trough", "bebedero norte"),
                               (SOUTH, "south <trough>", "bebedero sur"),
                               (BED, "bed 3", "cama 3")):
            for name, lang in ((en, "en"), (es, "es")):
                self.state.add(Label(uuid7(), entity, name, T0 - 600 * MIN, language=lang))

    def water(self, subject, rule, alert, at, key="water.empty"):
        return self.log.append("decision", {
            "rule": rule, "subject": str(subject), "alert": alert, "evaluated_at": at.isoformat(),
            "message": {"key": key, "params": {"percent": 6.0}, "subject_param": "trough"}
            if alert else None})

    def told(self, decision, person, via, at, reason="raised"):
        self.log.append("notification", {"decision": str(decision.id), "person": person,
                                         "via": via, "at": at.isoformat(), "reason": reason,
                                         "outcome": "sent"})

    def page(self, at, language="en"):
        return B.render(BOARD, B.snapshot(self.log.events, at), language, at, self.state)


class TestWhatStands(unittest.TestCase):
    def test_an_alert_shows_who_was_told_and_who_is_on_it(self):
        f = Farm()
        up = f.water(NORTH, "water-empty", True, T0)
        f.told(up, MARIA, "sms", T0)
        page = f.page(T0 + 10 * MIN)
        self.assertIn("north trough is nearly empty", page)
        self.assertIn("Nobody has said they are on it yet.", page)
        self.assertIn("Told: María (SMS 13:00)", page)
        f.told(up, SAM, "ntfy", T0 + 30 * MIN, reason="escalated")
        f.log.append("acknowledgement", {"decision": str(up.id), "by": SAM,
                                         "at": (T0 + 34 * MIN).isoformat(), "via": "ntfy"})
        es = f.page(T0 + 40 * MIN, "es")
        self.assertIn("bebedero norte está casi vacío", es)
        self.assertIn("Sam se encarga, desde las 13:34.", es)
        self.assertIn("Avisados: María (SMS 13:00), Sam (notificación 13:30)", es)
        self.assertIn('class="alert acked"', es)

    def test_a_cleared_alert_moves_down_for_a_day_then_goes(self):
        f = Farm()
        up = f.water(NORTH, "water-empty", True, T0)
        f.told(up, MARIA, "sms", T0)
        f.water(NORTH, "water-empty", False, T0 + 90 * MIN)
        snap = B.snapshot(f.log.events, T0 + 2 * 60 * MIN)
        self.assertEqual(snap["alerts"], [])
        [cleared] = snap["cleared"]
        self.assertEqual(cleared.decision_id, str(up.id))
        self.assertIn("No longer the case since 14:30:", f.page(T0 + 2 * 60 * MIN))
        self.assertEqual(B.snapshot(f.log.events, T0 + 26 * 60 * MIN)["cleared"], [])

    def test_advice_nobody_was_sent_stands_below_the_alerts_and_goes_stale(self):
        f = Farm()
        f.log.append("decision", {
            "rule": "soil-water-now", "subject": str(BED), "topic": f"advice/{BED}", "alert": True,
            "evaluated_at": T0.isoformat(), "valid_until": (T0 + 24 * 60 * MIN).isoformat(),
            "message": {"key": "soilwater.water_now", "params": {"used": 55.0, "mm": 18.0},
                        "subject_param": "bed"}})
        snap = B.snapshot(f.log.events, T0 + 60 * MIN)
        self.assertEqual((len(snap["alerts"]), len(snap["standing"])), (0, 1))
        page = f.page(T0 + 60 * MIN)
        self.assertIn("Also standing", page)
        self.assertIn("Water bed 3 today", page)
        self.assertIn("No alert stands.", page)
        self.assertEqual(B.snapshot(f.log.events, T0 + 25 * 60 * MIN)["standing"], [])

    def test_the_board_sees_only_what_was_known_at_the_moment_it_shows(self):
        f = Farm()
        f.water(NORTH, "water-empty", True, T0 + 60 * MIN)
        self.assertEqual(B.snapshot(f.log.events, T0)["standing"], [])


class TestReadings(unittest.TestCase):
    """The newest reading of each series the board is granted, beside the alerts."""

    def setUp(self):
        import fixtures as FX
        import vocab as V
        self.FX = FX
        self.f = Farm()
        raw = FX.raw_datastream(unit="1", observed_property=V.VESSEL_FILL_FRACTION,
                                expected_interval=300.0, max_latency=300.0)
        self.trough = FX.derived_datastream(raw)
        self.air = FX.derived_datastream(FX.raw_datastream(unit="Cel", observed_property=V.AIR_TEMPERATURE,
                                                           expected_interval=900.0, max_latency=900.0))
        for ds in (raw, self.trough, self.air):
            self.f.state.add(ds)
        for entity, name in ((self.trough.id, "bebedero norte"), (self.air.id, "invernadero")):
            self.f.state.add(Label(uuid7(), entity, name, T0 - 600 * MIN, language="es"))
        self.board = B.Board("Harrow Bend", "America/Chicago", ("en", "es"), {},
                             (self.trough.id, self.air.id, uuid7()))

    def add(self, ds, value, minute):
        o = self.FX.observation(ds, result=value, measured_at=T0 + minute * MIN,
                                received_at=T0 + minute * MIN, seq=minute)
        self.f.state.add(o)
        return o

    def page(self, at):
        snap = B.snapshot(self.f.log.events, at)
        snap["readings"] = B.latest_readings(self.f.state, self.board.series, at)
        return B.render(self.board, snap, "es", at, self.f.state)

    def test_the_newest_reading_each_in_its_own_terms(self):
        self.add(self.trough, 0.44, 0)
        self.add(self.trough, 0.46, 5)
        self.add(self.air, 3.25, 0)
        page = self.page(T0 + 10 * MIN)
        self.assertIn("Últimas lecturas", page)
        self.assertIn("<strong>bebedero norte</strong>: 46 %", page)
        self.assertIn("<strong>invernadero</strong>: 3,2 °C", page, "a decimal comma in Spanish")
        self.assertIn("Sin lecturas en los últimos tres días.", page, "a series it was not given")

    def test_a_flagged_or_late_reading_says_so(self):
        from model import QualityFlag
        o = self.add(self.trough, 0.05, 0)
        self.f.state.add(self.FX.assertion(o.id, flags={QualityFlag.STUCK}, check="stuck",
                                           asserted_at=T0 + MIN))
        self.add(self.air, 3.0, 0)
        page = self.page(T0 + 60 * MIN)
        self.assertIn("Los controles marcaron esta lectura: estancada.", page)
        # Both are late: three five-minute intervals and three of fifteen are under an hour.
        self.assertEqual(page.count("Nada más reciente desde hace 1,0 horas."), 2)
        self.assertEqual(page.count('<article class="alert"><p><strong>'), 2)

    def test_a_reading_not_yet_received_is_not_shown(self):
        o = self.FX.observation(self.trough, result=0.9, measured_at=T0, received_at=T0 + 30 * MIN, seq=1)
        self.f.state.add(o)
        [r, *_] = B.latest_readings(self.f.state, self.board.series, T0 + 10 * MIN)
        self.assertIsNone(r["value"])


class TestPruning(unittest.TestCase):
    def test_a_board_that_runs_for_months_holds_days_and_shows_the_same(self):
        f = Farm()
        start = T0
        for d in range(120):
            at = start + d * 24 * 60 * MIN
            up = f.water(NORTH, "water-low", True, at, key="water.low")
            f.told(up, MARIA, "sms", at)
            f.water(NORTH, "water-low", False, at + 60 * MIN)
        standing = f.water(SOUTH, "water-empty", True, start + 30 * 24 * 60 * MIN)
        f.told(standing, MARIA, "sms", start + 30 * 24 * 60 * MIN)
        now = start + 119 * 24 * 60 * MIN + 2 * 60 * MIN
        kept = B.prune(list(f.log.events), now)
        self.assertLess(len(kept), 20)
        self.assertEqual(B.render(BOARD, B.snapshot(kept, now), "en", now, f.state),
                         B.render(BOARD, B.snapshot(f.log.events, now), "en", now, f.state))
        self.assertIn(str(standing.id), {str(e.id) for e in kept}, "an old alert still standing")


class TestThePage(unittest.TestCase):
    def test_everything_written_by_a_farm_or_a_module_is_escaped(self):
        f = Farm()
        up = f.water(SOUTH, "water-empty", True, T0)
        f.told(up, MARIA, "sms", T0)
        page = f.page(T0 + MIN)
        self.assertIn("south &lt;trough&gt;", page)
        self.assertNotIn("<trough>", page)

    def test_it_runs_no_script_it_did_not_hash_and_loads_nothing(self):
        page = Farm().page(T0)
        csp = re.search(r'Content-Security-Policy" content="([^"]+)"', page).group(1)
        self.assertIn("default-src 'none'", csp)
        for kind, body in (("script", B.SCRIPT), ("style", B.STYLE)):
            digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
            self.assertIn(f"{kind}-src 'sha256-{digest}'", csp)
            self.assertIn(f"<{kind}>{body}</{kind}>", page)
        self.assertNotRegex(page, r'(src|href)="(https?:)?//')

    def test_it_says_when_it_was_made_and_warns_when_that_was_long_ago(self):
        page = Farm().page(T0)
        self.assertIn(f'data-made="{T0.isoformat()}"', page)
        self.assertIn("As of 13:00.", page)
        self.assertIn('<p id="stale" hidden>This page has not updated for more than 10 minutes', page)
        self.assertIn('http-equiv="refresh" content="60"', page)

    def test_each_language_has_its_page_and_the_index_offers_them(self):
        d = tempfile.mkdtemp()
        try:
            names = B.write(BOARD, [], T0, d)
            self.assertEqual(names, ["index.en.html", "index.es.html", "index.html"])
            with open(os.path.join(d, "index.html"), encoding="utf-8") as h:
                index = h.read()
            self.assertIn('href="index.es.html" hreflang="es">español</a>', index)
            with open(os.path.join(d, "index.es.html"), encoding="utf-8") as h:
                self.assertIn('<html lang="es"', h.read())
        finally:
            shutil.rmtree(d)


class TestServing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        B.write(BOARD, [], T0, self.dir)
        self.server = B.make_server(self.dir, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir)

    def get(self, path, method="GET"):
        req = urllib.request.Request(self.url + path, method=method,
                                     data=b"x" if method == "POST" else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def test_it_serves_its_pages_and_nothing_else(self):
        code, body, headers = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Harrow Bend", body)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.get("/index.es.html")[0], 200)
        for path in ("/../board.py", "/index.html/../../etc/passwd", "/board.py", "/index.xx.html",
                     "/%2e%2e/board.py"):
            self.assertEqual(self.get(path)[0], 404, path)
        self.assertEqual(self.get("/", "POST")[0], 405)

    def test_beyond_this_machine_only_with_tls(self):
        with self.assertRaisesRegex(SystemExit, "without TLS"):
            B.make_server(self.dir, "0.0.0.0", 0)


try:
    import cryptography  # noqa: F401
    HAVE_CRYPTOGRAPHY = True
except ImportError:
    HAVE_CRYPTOGRAPHY = False


@unittest.skipUnless(HAVE_CRYPTOGRAPHY, "cryptography is not installed (requirements-tools.txt)")
class TestTls(unittest.TestCase):
    """Given a certificate, it serves the pages over TLS and nothing over plain HTTP, and
    a client that stalls its handshake stalls only itself."""

    def setUp(self):
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
        now = _dt.datetime.now(tz=UTC)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - _dt.timedelta(days=1))
                .not_valid_after(now + _dt.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                .sign(key, hashes.SHA256()))
        self.dir = tempfile.mkdtemp()
        self.cert, key_path = os.path.join(self.dir, "c.pem"), os.path.join(self.dir, "k.pem")
        with open(self.cert, "wb") as h:
            h.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(key_path, "wb") as h:
            h.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
        pages = os.path.join(self.dir, "pages")
        B.write(BOARD, [], T0, pages)
        self.server = B.make_server(pages, "127.0.0.1", 0, tls=B.tls_context(self.cert, key_path))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def get(self, path, context=None):
        import http.client
        conn = (http.client.HTTPSConnection("127.0.0.1", self.port, context=context, timeout=10)
                if context else http.client.HTTPConnection("127.0.0.1", self.port, timeout=10))
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            return r.status, r.read()
        finally:
            conn.close()

    def test_it_speaks_tls_and_nothing_else(self):
        import http.client
        import ssl
        trusted = ssl.create_default_context(cafile=self.cert)
        code, body = self.get("/index.es.html", trusted)
        self.assertEqual(code, 200)
        self.assertIn("Necesita a alguien".encode(), body)
        with self.assertRaises((http.client.HTTPException, OSError)):
            self.get("/")
        with self.assertRaises(ssl.SSLError):
            self.get("/", ssl.create_default_context())     # a certificate it does not trust

    def test_a_stalled_handshake_stalls_only_itself(self):
        import socket
        import ssl
        stalled = socket.create_connection(("127.0.0.1", self.port))   # says nothing
        try:
            code, _ = self.get("/", ssl.create_default_context(cafile=self.cert))
            self.assertEqual(code, 200)
        finally:
            stalled.close()


class TestAsItsOwnProcess(unittest.TestCase):
    """Through the host, granted the farm's decisions and their names, it writes the
    pages and writes nothing to the log."""

    def test_it_draws_the_board_from_the_log_through_the_host(self):
        import modhost as M
        f = Farm()
        d = tempfile.mkdtemp(prefix="fm-", dir="/tmp" if os.path.isdir("/tmp") else None)
        host = M.ModuleHost(f.log, f.state, os.path.join(d, "m.sock")).start()
        try:
            import fixtures as FX
            import vocab as V
            now = _dt.datetime.now(tz=UTC)
            trough = FX.derived_datastream(FX.raw_datastream(
                unit="1", observed_property=V.VESSEL_FILL_FRACTION, expected_interval=300.0))
            f.state.add(trough)
            f.state.add(Label(uuid7(), trough.id, "bebedero sur", now - 60 * MIN, language="es"))
            f.state.add(FX.observation(trough, result=0.61, measured_at=now - 4 * MIN,
                                       received_at=now - 4 * MIN, seq=1))
            _, token = M.grant(f.log, M.Manifest.load(os.path.join(HERE, "module.json")),
                               datastreams=[trough.id])
            up = f.water(NORTH, "water-empty", True, now - 5 * MIN)
            f.told(up, MARIA, "sms", now - 5 * MIN)
            config = os.path.join(d, "board.json")
            with open(config, "w", encoding="utf-8") as h:
                json.dump({"farm": "Harrow Bend", "timezone": "America/Chicago",
                           "languages": ["en", "es"], "people": {MARIA: "María"},
                           "series": [str(trough.id)]}, h)
            before = len(f.log.events)
            done = subprocess.run([sys.executable, "-I", os.path.join(HERE, "board.py"),
                                   "--socket", os.path.join(d, "m.sock"), "--config", config,
                                   "--out", os.path.join(d, "pages"), "--once"],
                                  env={"FIELDMESH_MODULE_TOKEN": token, "PATH": os.environ.get("PATH", "")},
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(os.path.join(d, "pages", "index.es.html"), encoding="utf-8") as h:
                page = h.read()
            self.assertIn("bebedero norte está casi vacío", page)
            self.assertIn("María (SMS", page)
            self.assertIn("<strong>bebedero sur</strong>: 61 %", page, "a granted reading, by name")
            self.assertEqual(len(f.log.events), before, "it writes nothing")
        finally:
            host.stop()
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
