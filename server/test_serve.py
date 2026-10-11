#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The service on a real socket: who may ask, what a grantee sees, and what one slow
or greedy client can do to the rest (spec v0.1 §7.6, §8.2)."""
from __future__ import annotations

import datetime as _dt
import http.client
import io
import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
sys.path.insert(0, HERE)

import access as AC  # noqa: E402
import app as A  # noqa: E402
import fixtures as F  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import serve as S  # noqa: E402
from ids import uuid7  # noqa: E402
from model import Grant, GrantRevocation, Label  # noqa: E402

NOW = _dt.datetime.now(tz=_dt.timezone.utc)


class Farm:
    """Two series. The lab is granted one, and only what had arrived when it was made."""

    def __init__(self, *, rate=50.0, burst=200, max_concurrent=16, timeout_s=5.0,
                 open_access=False, tls=None, app=None):
        self.log = L.Log()
        self.soil = F.raw_datastream()
        self.trough = F.raw_datastream(unit="1")
        self.before = F.observation(self.soil, result=0.21, measured_at=NOW - _dt.timedelta(hours=3),
                                    received_at=NOW - _dt.timedelta(hours=3), seq=1)
        self.after = F.observation(self.soil, result=0.22, measured_at=NOW - _dt.timedelta(hours=1),
                                   received_at=NOW - _dt.timedelta(hours=1), seq=2)
        self.hidden = F.observation(self.trough, result=0.9, measured_at=NOW - _dt.timedelta(hours=2),
                                    received_at=NOW - _dt.timedelta(hours=2), seq=3)
        self.grant = Grant(uuid7(), "soil lab", (self.soil.id,), "drought study",
                           NOW - _dt.timedelta(hours=2))
        names = [Label(uuid7(), self.soil.thing, "station", NOW - _dt.timedelta(days=1)),
                 Label(uuid7(), self.soil.thing, "estación", NOW - _dt.timedelta(days=1),
                       language="es")]
        for r in (self.soil, self.trough, self.before, self.after, self.hidden, self.grant,
                  *names):
            self.log.append_record(r)
        self.state = P.state_from_log(self.log)
        self.viewer_id, self.viewer = AC.issue(self.log, role="viewer")
        self.lab_id, self.lab = AC.issue(self.log, grantee="soil lab")
        self.access = AC.Access(self.log)
        self.out = io.StringIO()
        self.app = app or A.make_app(self.state, "http://127.0.0.1")
        self.httpd = S.make_server(self.app, self.access, host="127.0.0.1", port=0,
                                   open_access=open_access, tls=tls, rate=rate, burst=burst,
                                   max_concurrent=max_concurrent, timeout_s=timeout_s,
                                   log_stream=self.out)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def get(self, path, token=None, headers=None, context=None):
        conn = (http.client.HTTPSConnection("127.0.0.1", self.port, context=context, timeout=10)
                if context else http.client.HTTPConnection("127.0.0.1", self.port, timeout=10))
        h = dict(headers or {})
        if token:
            h["Authorization"] = f"Bearer {token}"
        conn.request("GET", path, headers=h)
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), (json.loads(body) if body else None)


class TestWhoMayAsk(unittest.TestCase):
    def setUp(self):
        self.farm = Farm()

    def tearDown(self):
        self.farm.close()

    def test_no_token_and_a_wrong_token_are_refused(self):
        status, headers, _ = self.farm.get("/v1.1/Datastreams")
        self.assertEqual(status, 401)
        self.assertEqual(headers["WWW-Authenticate"], 'Bearer realm="fieldmesh"')
        self.assertEqual(self.farm.get("/v1.1/Datastreams", token="guess")[0], 401)
        status, _, doc = self.farm.get("/v1.1/Datastreams", token=self.farm.viewer)
        self.assertEqual((status, len(doc["value"])), (200, 2))

    def test_a_grantee_sees_what_the_grant_covers_by_every_path(self):
        f = self.farm
        ds = f.get("/v1.1/Datastreams", token=f.lab)[2]["value"]
        self.assertEqual([d["@iot.id"] for d in ds], [str(f.soil.id)])
        obs = f.get(f"/v1.1/Datastreams({f.soil.id})/Observations", token=f.lab)[2]["value"]
        self.assertEqual([o["@iot.id"] for o in obs], [str(f.before.id)],
                         "the reading that arrived after the grant is not theirs")
        self.assertEqual(len(f.get("/v1.1/Observations", token=f.lab)[2]["value"]), 1)
        self.assertEqual(f.get(f"/v1.1/Datastreams({f.trough.id})", token=f.lab)[0], 404)
        self.assertEqual(f.get(f"/v1.1/Observations({f.hidden.id})", token=f.lab)[0], 404)
        self.assertEqual(f.get(f"/v1.1/Observations({f.after.id})", token=f.lab)[0], 404)
        things = f.get("/v1.1/Things", token=f.lab)[2]["value"]
        self.assertEqual([t["@iot.id"] for t in things], [str(f.soil.thing)])
        reached = f.get(f"/v1.1/Things({f.soil.thing})/Datastreams", token=f.lab)[2]["value"]
        self.assertEqual([d["@iot.id"] for d in reached], [str(f.soil.id)])
        self.assertEqual(f.get(f"/v1.1/Things({f.trough.thing})", token=f.lab)[0], 404)
        self.assertEqual(f.get(f"/v1.1/Sensors({f.trough.sensor})", token=f.lab)[0], 404)
        self.assertEqual(len(f.get("/v1.1/Datastreams", token=f.viewer)[2]["value"]), 2)

    def test_a_revoked_grant_empties_the_view_and_a_revoked_token_is_refused(self):
        f = self.farm
        rev = GrantRevocation(uuid7(), f.grant.id, NOW - _dt.timedelta(minutes=1))
        f.log.append_record(rev)
        f.state.add(rev)
        status, _, doc = f.get("/v1.1/Datastreams", token=f.lab)
        self.assertEqual((status, doc["value"]), (200, []))
        AC.revoke(f.log, f.viewer_id)
        self.assertEqual(f.get("/v1.1/Datastreams", token=f.viewer)[0], 401)

    def test_a_token_ends_when_it_says(self):
        f = self.farm
        ident, token = AC.issue(f.log, role="viewer", at=NOW - _dt.timedelta(days=2),
                                until=NOW - _dt.timedelta(days=1))
        self.assertEqual(f.get("/v1.1/Datastreams", token=token)[0], 401)

    def test_the_log_holds_hashes_and_the_access_log_holds_no_token(self):
        f = self.farm
        f.get("/v1.1/Datastreams", token=f.viewer)
        everything = json.dumps([e.to_jsonable() for e in f.log.events])
        self.assertNotIn(f.viewer, everything)
        self.assertNotIn(f.lab, everything)
        self.assertNotIn(f.viewer, f.out.getvalue())
        self.assertIn("user:viewer GET /v1.1/Datastreams 200", f.out.getvalue())

    def test_every_answer_carries_the_security_headers(self):
        _, headers, _ = self.farm.get("/v1.1/Datastreams", token=self.farm.viewer)
        for key, value in S.SECURITY_HEADERS.items():
            self.assertEqual(headers[key], value)
        self.assertEqual(headers["Server"], "fieldmesh/0", "no Python version in it")


class TestWhereItMayListen(unittest.TestCase):
    def test_beyond_this_machine_only_with_tls_and_never_open(self):
        log = L.Log()
        app = A.make_app(P.State(), "http://x")
        with self.assertRaisesRegex(SystemExit, "without TLS"):
            S.make_server(app, AC.Access(log), host="0.0.0.0", port=0)
        with self.assertRaisesRegex(SystemExit, "only on this machine"):
            S.make_server(app, AC.Access(log), host="0.0.0.0", port=0, open_access=True,
                          tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER))

    def test_open_reads_without_a_token_on_loopback(self):
        f = Farm(open_access=True)
        try:
            self.assertEqual(f.get("/v1.1/Datastreams")[0], 200)
            self.assertEqual(f.get("/v1.1/Datastreams", token="wrong")[0], 401,
                             "a wrong token is still wrong")
        finally:
            f.close()


class TestOneClientCannotStallTheRest(unittest.TestCase):
    def test_a_principal_over_its_rate_is_told_to_wait(self):
        f = Farm(rate=1.0, burst=3)
        try:
            codes = [f.get("/v1.1/Datastreams", token=f.viewer)[0] for _ in range(4)]
            self.assertEqual(codes, [200, 200, 200, 429])
            status, headers, _ = f.get("/v1.1/Datastreams", token=f.viewer)
            self.assertEqual(status, 429)
            self.assertGreaterEqual(int(headers["Retry-After"]), 1)
            self.assertEqual(f.get("/v1.1/Datastreams", token=f.lab)[0], 200,
                             "another principal has its own allowance")
        finally:
            f.close()

    def test_a_client_that_never_finishes_its_request_holds_up_nobody(self):
        f = Farm(timeout_s=1.0)
        try:
            slow = socket.create_connection(("127.0.0.1", f.port))
            slow.sendall(b"GET /v1.1/Datastreams HTTP/1.1\r\nHost: x\r\n")
            start = time.monotonic()
            with ThreadPoolExecutor(8) as pool:
                codes = list(pool.map(lambda _: f.get("/v1.1/Datastreams", token=f.viewer)[0],
                                      range(16)))
            self.assertEqual(codes, [200] * 16)
            self.assertLess(time.monotonic() - start, 5.0)
            slow.settimeout(5.0)
            self.assertEqual(slow.recv(1024), b"", "dropped after its timeout")
            slow.close()
        finally:
            f.close()

    def test_past_the_concurrency_cap_the_answer_is_busy(self):
        class Slow:
            lock = threading.RLock()

            def __init__(self, app):
                self.inner = app

            def handle(self, *a, **kw):
                time.sleep(0.6)
                return self.inner.handle(*a, **kw)

        base = Farm()
        base.close()
        f = Farm(max_concurrent=1, app=Slow(A.make_app(base.state, "http://127.0.0.1")))
        try:
            with ThreadPoolExecutor(3) as pool:
                codes = sorted(pool.map(lambda _: f.get("/v1.1/Datastreams", token=f.viewer)[0],
                                        range(3)))
            self.assertIn(503, codes)
            self.assertIn(200, codes)
        finally:
            f.close()

    def test_two_languages_at_once_never_cross(self):
        f = Farm()
        try:
            def name(lang):
                doc = f.get("/v1.1/Things", token=f.viewer, headers={"Accept-Language": lang})[2]
                names = {t["name"] for t in doc["value"]}
                return lang, names
            with ThreadPoolExecutor(8) as pool:
                for lang, names in pool.map(name, ["en", "es"] * 20):
                    self.assertIn({"en": "station", "es": "estación"}[lang], names)
                    self.assertNotIn({"en": "estación", "es": "station"}[lang], names)
        finally:
            f.close()


class TestTls(unittest.TestCase):
    def test_it_speaks_tls_and_nothing_else_when_given_a_certificate(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        import ipaddress
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(NOW - _dt.timedelta(days=1))
                .not_valid_after(NOW + _dt.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                .sign(key, hashes.SHA256()))
        d = tempfile.mkdtemp()
        try:
            cert_path, key_path = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
            with open(cert_path, "wb") as h:
                h.write(cert.public_bytes(serialization.Encoding.PEM))
            with open(key_path, "wb") as h:
                h.write(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
            f = Farm(tls=S.tls_context(cert_path, key_path))
            try:
                client = ssl.create_default_context(cafile=cert_path)
                self.assertEqual(f.get("/v1.1/Datastreams", token=f.viewer, context=client)[0], 200)
                with self.assertRaises((http.client.HTTPException, OSError)):
                    f.get("/v1.1/Datastreams", token=f.viewer)
            finally:
                f.close()
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestFollowingTheLog(unittest.TestCase):
    def test_a_token_issued_by_another_process_counts_without_a_restart(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "farm.jsonl")
            L.Log(path).append_record(F.raw_datastream())
            mem = L.Log()
            events, offset = S.read_from(path, 0)
            for e in events:
                mem.receive(e)
            access = AC.Access(mem)
            _, token = AC.issue(L.Log(path), role="viewer")      # another process
            self.assertIsNone(access.resolve(f"Bearer {token}", NOW))
            stop = threading.Event()
            t = threading.Thread(target=S.follow, args=(path, mem, threading.RLock(), offset),
                                 kwargs={"every_s": 0.05, "stop": stop}, daemon=True)
            t.start()
            deadline = time.monotonic() + 5
            while access.resolve(f"Bearer {token}", _dt.datetime.now(tz=_dt.timezone.utc)) is None:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.05)
            stop.set()
            with open(path, "rb") as h:
                self.assertEqual(len(h.read().splitlines()), 2, "the server never writes the file")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
