#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""No-network tests for the gateway spool (spec v0.1 §5.2, §5.4).

urlopen is replaced, so these run anywhere and prove the three behaviours the
store-and-forward clause depends on: a 4xx never retries, an unreachable log
spools instead of dropping, and a drain clears what it can while refusing to
jam on a poison batch.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error

import spool


class FakeResp:
    def __init__(self, status=200, body=b"ok"):
        self.status, self._b = status, body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def patch(seq):
    """Replace urlopen with one that yields `seq` in order (callables raise)."""
    calls = []

    def fake(req, timeout=None):
        calls.append(req.full_url)
        item = seq[min(len(calls) - 1, len(seq) - 1)]
        if isinstance(item, Exception):
            raise item
        return item
    spool.urllib.request.urlopen = fake
    return calls


class TestSpool(unittest.TestCase):
    def setUp(self):
        self._real = spool.urllib.request.urlopen
        self.tmp = tempfile.mkdtemp()
        self.spoolfile = os.path.join(self.tmp, "spool.jsonl")

    def tearDown(self):
        spool.urllib.request.urlopen = self._real

    def _read(self):
        with open(self.spoolfile) as f:
            return f.read().strip()

    def test_happy_path_posts_once(self):
        calls = patch([FakeResp(200)])
        code, _ = spool.post_batch("http://log", {"obs": 1})
        self.assertEqual(code, 200)
        self.assertEqual(len(calls), 1)

    def test_4xx_returns_immediately_and_never_retries(self):
        err = urllib.error.HTTPError("http://log", 422, "bad", {}, None)
        err.read = lambda: b"malformed"
        calls = patch([err])
        code, body = spool.post_batch("http://log", {"obs": 1}, retries=3)
        self.assertEqual(code, 422)
        self.assertIn("malformed", body)
        self.assertEqual(len(calls), 1, "a malformed batch must not be retried")

    def test_unreachable_log_spools_rather_than_drops(self):
        patch([urllib.error.URLError("refused")])
        code, body = spool.post_batch("http://log", {"obs": 7}, retries=2,
                                      backoff=0, spool=self.spoolfile)
        self.assertEqual((code, body), (0, "spooled"))
        with open(self.spoolfile) as f:
            self.assertEqual(json.loads(f.read().strip()), {"obs": 7})

    def test_drain_reposts_backlog_and_empties_the_spool(self):
        with open(self.spoolfile, "w") as f:
            f.write(json.dumps({"obs": 1}) + "\n" + json.dumps({"obs": 2}) + "\n")
        patch([FakeResp(200)])
        posted, kept = spool.drain_spool("http://log", self.spoolfile)
        self.assertEqual((posted, kept), (2, 0))
        self.assertEqual(self._read(), "")

    def test_drain_keeps_what_is_still_unreachable(self):
        with open(self.spoolfile, "w") as f:
            f.write(json.dumps({"obs": 1}) + "\n")
        patch([urllib.error.URLError("still down")])
        posted, kept = spool.drain_spool("http://log", self.spoolfile)
        self.assertEqual((posted, kept), (0, 1))
        self.assertEqual(json.loads(self._read()), {"obs": 1})

    def test_drain_drops_poison_instead_of_jamming(self):
        with open(self.spoolfile, "w") as f:
            f.write(json.dumps({"bad": 1}) + "\n")
        err = urllib.error.HTTPError("http://log", 400, "bad", {}, None)
        err.read = lambda: b"nope"
        patch([err])
        posted, kept = spool.drain_spool("http://log", self.spoolfile)
        self.assertEqual((posted, kept), (0, 0), "poison must leave the queue")
        self.assertEqual(self._read(), "")

    def test_token_from_env_is_sent_as_bearer(self):
        seen = {}

        def fake(req, timeout=None):
            seen.update(req.headers)
            return FakeResp(200)
        spool.urllib.request.urlopen = fake
        os.environ[spool.TOKEN_ENV] = "s3cret"
        try:
            spool.post_batch("http://log", {"obs": 1})
        finally:
            del os.environ[spool.TOKEN_ENV]
        self.assertEqual(seen.get("Authorization"), "Bearer s3cret")

    def test_path_is_parameterised(self):
        calls = patch([FakeResp(200)])
        spool.post_batch("http://log/", {"obs": 1}, path="/v0/observations")
        self.assertEqual(calls[0], "http://log/v0/observations")


if __name__ == "__main__":
    unittest.main(verbosity=2)
