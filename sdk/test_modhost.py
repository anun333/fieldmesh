#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Modules as separate processes, permissioned per point (spec v0.1 §8.3; Q11)."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest

import fixtures as fx
import modhost as M
import vocab as V
from ids import uuid7
from log import Log
from model import QualityFlag, Usable
from project import State

HERE = os.path.dirname(os.path.abspath(__file__))


def manifest(name="water", reads=(V.VESSEL_FILL_FRACTION,), writes=("decision",)):
    return M.Manifest(name, "1", frozenset(reads), frozenset(writes))


class Farm:
    """A trough series, a soil series, readings in both, one of them flagged."""

    def __init__(self):
        self.log, self.state = Log(), State()
        self.trough = fx.raw_datastream(unit="1", observed_property=V.VESSEL_FILL_FRACTION)
        self.soil = fx.raw_datastream()
        self.state.add(self.trough)
        self.state.add(self.soil)
        self.obs = []
        for m in range(6):
            for ds, v in ((self.trough, 0.9), (self.soil, 0.25)):
                o = fx.observation(ds, result=v, measured_at=fx.at(m * 5), seq=m)
                self.state.add(o)
                self.obs.append(o)
        self.flagged = self.obs[-2]                     # the trough's last reading
        self.state.add(fx.assertion(self.flagged.id, flags={QualityFlag.STUCK},
                                    asserted_at=fx.at(26)))
        self.dir = tempfile.mkdtemp(prefix="fm-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.path = os.path.join(self.dir, "m.sock")
        self.host = M.ModuleHost(self.log, self.state, self.path).start()

    def close(self):
        self.host.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def client(self, token):
        return M.ModuleClient(self.path, token)


class TestManifestAndGrant(unittest.TestCase):
    def test_no_manifest_may_write_the_foundations_records_or_command(self):
        for kind in ("observation", "quality_assertion", "threshold", "grant", M.GRANT):
            with self.assertRaisesRegex(ValueError, "foundation"):
                manifest(writes=("decision", kind))
        with self.assertRaisesRegex(ValueError, "deferred"):
            M.Manifest("x", "1", frozenset(), frozenset(), frozenset({"open_valve"}))

    def test_a_grant_stays_inside_the_manifest_and_logs_only_the_hash(self):
        log = Log()
        with self.assertRaisesRegex(ValueError, "does not declare"):
            M.grant(log, manifest(), properties=[V.SOIL_WATER])
        with self.assertRaisesRegex(ValueError, "writing"):
            M.grant(log, manifest(), writes=["acknowledgement"])
        g, token = M.grant(log, manifest(), properties=[V.VESSEL_FILL_FRACTION])
        [event] = log.events
        self.assertEqual(event.kind, M.GRANT)
        self.assertNotIn(token, json.dumps(event.to_jsonable()))
        self.assertEqual(event.payload["token_sha256"], M.token_hash(token))

    def test_the_shipped_manifests_load(self):
        modules = os.path.join(HERE, os.pardir, "modules")
        found = [n for n in sorted(os.listdir(modules))
                 if os.path.exists(os.path.join(modules, n, "module.json"))]
        self.assertIn("water", found)
        for name in found:
            m = M.Manifest.load(os.path.join(modules, name, "module.json"))
            self.assertEqual(m.name, name)


class TestHost(unittest.TestCase):
    def setUp(self):
        self.farm = Farm()
        self.grant, self.token = M.grant(self.farm.log, manifest(),
                                         properties=[V.VESSEL_FILL_FRACTION])

    def tearDown(self):
        self.farm.close()

    def test_a_module_reads_only_its_points_with_their_quality_as_of_then(self):
        with self.farm.client(self.token) as c:
            self.assertEqual(c.call("whoami")["module"], "water")
            self.assertEqual([d["id"] for d in c.call("datastreams")], [str(self.farm.trough.id)])
            rows = c.call("observations", datastream=str(self.farm.trough.id),
                          at=fx.at(30).isoformat())
            self.assertEqual(len(rows), 6)
            last = rows[-1]
            self.assertEqual((last["usable"], last["flags"]), ("bad", ["stuck"]))
            early = c.call("observations", datastream=str(self.farm.trough.id),
                           at=fx.at(25).isoformat())
            self.assertEqual(early[-1]["usable"], "good", "not yet asserted at 25 minutes")
            with self.assertRaisesRegex(M.Refused, "not granted"):
                c.call("observations", datastream=str(self.farm.soil.id), at=fx.at(30).isoformat())

    def test_writes_are_stamped_and_the_foundations_kinds_refused(self):
        with self.farm.client(self.token) as c:
            event = c.call("append", kind="decision",
                           payload={"rule": "water-low", "module": "someone-else"})
            self.assertEqual((event["payload"]["module"], event["payload"]["module_grant"]),
                             ("water", str(self.grant.id)))
            for kind in ("observation", "quality_assertion", "acknowledgement"):
                with self.assertRaises(M.Refused):
                    c.call("append", kind=kind, payload={})
        kinds = [e.kind for e in self.farm.log.events]
        self.assertEqual(kinds.count("decision"), 1)
        self.assertEqual(kinds.count(M.REFUSAL), 3)

    def test_a_refusal_repeated_is_logged_once_and_counted(self):
        with self.farm.client(self.token) as c:
            for _ in range(50):
                with self.assertRaises(M.Refused):
                    c.call("append", kind="observation", payload={})
        self.assertEqual([e.kind for e in self.farm.log.events].count(M.REFUSAL), 1)
        self.assertEqual(sum(self.farm.host.refusals.values()), 50)

    def test_a_wrong_token_and_a_revoked_grant_are_refused(self):
        with self.farm.client("not-a-token") as c:
            with self.assertRaisesRegex(M.Refused, "unknown token"):
                c.call("whoami")
        with self.farm.client(self.token) as c:
            c.call("whoami")
            M.revoke(self.farm.log, self.grant.id)
            with self.assertRaisesRegex(M.Refused, "revoked"):
                c.call("whoami")

    def test_modules_never_read_each_others_writes(self):
        soil, soil_token = M.grant(self.farm.log, manifest("soilwater", reads=(V.SOIL_WATER,)),
                                   properties=[V.SOIL_WATER])
        with self.farm.client(self.token) as w, self.farm.client(soil_token) as s:
            w.call("append", kind="decision", payload={"rule": "water-low"})
            s.call("append", kind="decision", payload={"rule": "soil-water-now"})
            self.assertEqual([e["payload"]["rule"] for e in w.call("events")], ["water-low"])
            self.assertEqual([e["payload"]["rule"] for e in s.call("events")], ["soil-water-now"])
            with self.assertRaises(M.Refused):
                w.call("label", entity=str(self.farm.soil.feature))
            self.assertIsNone(w.call("label", entity=str(self.farm.trough.feature)))

    def test_a_malformed_request_and_a_dying_module_do_not_stop_the_host(self):
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.connect(self.farm.path)
        raw.sendall(b"{not json\n")
        self.assertIn(b"malformed", raw.recv(4096))
        raw.sendall(b'{"token": "x", "op": "whoa')       # dies mid-request
        raw.close()
        with self.farm.client(self.token) as c:
            self.assertEqual(c.call("whoami")["module"], "water")

    def test_the_remote_state_answers_as_the_local_one(self):
        at = fx.at(30)
        with self.farm.client(self.token) as c:
            remote = c.state(at)
            rows = remote.live_observations_of(self.farm.trough.id)
            local = [o for o in self.farm.state.live_observations_of(self.farm.trough.id)]
            self.assertEqual(rows, local)
            for o in rows:
                self.assertEqual(remote.quality_as_of(o.id, at),
                                 self.farm.state.quality_as_of(o.id, at))
            self.assertEqual(list(remote.datastreams), [self.farm.trough.id])
            log = c.log()
            log.append("decision", {"rule": "water-low"})
            self.assertEqual([e.payload["rule"] for e in log.events], ["water-low"])


class TestASeparateProcess(unittest.TestCase):
    """The point of Q11: the module is another process, with nothing of the foundation's
    in its memory, and the socket is all it has."""

    SCRIPT = textwrap.dedent('''
        import json, os, sys
        sys.path.insert(0, sys.argv[2])
        import modhost as M
        out = {}
        with M.ModuleClient(sys.argv[1], M.token_from_environment()) as c:
            out["me"] = c.call("whoami")["module"]
            for name, ds in (("trough", sys.argv[3]), ("soil", sys.argv[4])):
                try:
                    out[name] = len(c.call("observations", datastream=ds, at="2026-06-01T13:00:00+00:00"))
                except M.Refused as exc:
                    out[name] = "refused"
            try:
                c.call("append", kind="observation", payload={})
                out["write"] = "allowed"
            except M.Refused:
                out["write"] = "refused"
        print(json.dumps(out))
    ''')

    def test_a_module_process_gets_what_it_was_granted_and_nothing_else(self):
        farm = Farm()
        try:
            _, token = M.grant(farm.log, manifest(), properties=[V.VESSEL_FILL_FRACTION])
            script = os.path.join(farm.dir, "module.py")
            with open(script, "w", encoding="utf-8") as h:
                h.write(self.SCRIPT)
            env = {"FIELDMESH_MODULE_TOKEN": token, "PATH": os.environ.get("PATH", "")}
            done = subprocess.run([sys.executable, "-I", script, farm.path, HERE,
                                   str(farm.trough.id), str(farm.soil.id)],
                                  capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads(done.stdout),
                             {"me": "water", "trough": 6, "soil": "refused", "write": "refused"})
            no_token = subprocess.run([sys.executable, "-I", script, farm.path, HERE,
                                       str(farm.trough.id), str(farm.soil.id)],
                                      capture_output=True, text=True,
                                      env={"PATH": os.environ.get("PATH", "")}, timeout=60)
            self.assertNotEqual(no_token.returncode, 0)
            self.assertIn("no module token", no_token.stderr)
        finally:
            farm.close()


if __name__ == "__main__":
    unittest.main()
