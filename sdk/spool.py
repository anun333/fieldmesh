#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The one gateway-side POST — retry, auth, and spool for every producer.

Layer zero's store-and-forward has two halves. The node half buffers readings until
its link confirms delivery (spec v0.1 §5.2). This is the *gateway* half: once a batch
has been received and expanded into observations, it still has to reach the log, and
the log may be on a machine that is briefly unreachable. A reading dropped here is
indistinguishable from a reading the sensor never took, and §5.4 forbids guessing.

  * AUTH    Bearer $LIBREFARM_TOKEN (or an explicit `token=`) when set.
  * RETRY   network errors and 5xx retry with exponential backoff; 4xx returns
            immediately, because a malformed batch will never succeed.
  * SPOOL   after retries are exhausted, `spool=<path>` appends the batch as one
            JSONL line instead of dropping it. drain_spool() re-posts the backlog;
            poison batches (4xx) are dropped with a warning rather than jamming the
            queue forever. Callers drain at startup.

A spooled batch that is later dropped as poison is a gap, and the caller is
responsible for recording it as one (§5.4) — this module reports, it never guesses.

Stdlib only. Pure functions; no globals beyond the environment token.

Provenance: adapted from campus_twin's `open-bas/connectors/_ingest.py`
(same author, Apache-2.0 OR GPL-3.0-or-later at origin). See PROVENANCE.md.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request


DEFAULT_PATH = "/api/ingest"
TOKEN_ENV = "LIBREFARM_TOKEN"


def post_json(base_url, path, doc, *, timeout=10, retries=3, backoff=1.5, token=None):
    """POST any JSON document to a write route (same auth + retry rules as post_batch,
    no spool). Returns (status, body); re-raises after the last retry."""
    return _post(base_url, path, doc, timeout=timeout, retries=retries, backoff=backoff,
                 token=token, spool=None)


def post_batch(base_url, batch, *, path=DEFAULT_PATH, timeout=10, retries=3,
               backoff=1.5, token=None, spool=None):
    """POST a batch of observations to the ingest route.

    Returns (status, body). On unrecoverable failure: appends to `spool` and returns
    (0, "spooled") when a spool path is given, else re-raises the last error."""
    return _post(base_url, path, batch, timeout=timeout, retries=retries,
                 backoff=backoff, token=token, spool=spool)


def _post(base_url, path, batch, *, timeout, retries, backoff, token, spool):
    data = json.dumps(batch).encode()
    headers = {"Content-Type": "application/json"}
    tok = token if token is not None else os.environ.get(TOKEN_ENV)
    if tok:
        headers["Authorization"] = "Bearer " + tok
    url = base_url.rstrip("/") + path
    last = None
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code < 500:          # our batch is wrong — retrying can't fix it
                return e.code, e.read().decode(errors="replace")
            last = e
        except Exception as e:        # URLError, timeout, connection refused…
            last = e
        if attempt + 1 < retries:
            time.sleep(backoff * 2 ** attempt)
    if spool:
        with open(spool, "a") as f:
            f.write(json.dumps(batch) + "\n")
        print(f"post failed after {retries} tries ({last}) — batch spooled to {spool}",
              file=sys.stderr)
        return 0, "spooled"
    raise last


def drain_spool(base_url, spool, *, path=DEFAULT_PATH, timeout=10, token=None):
    """Re-post every spooled batch; keep only the still-failing ones (atomically).

    Returns (posted, kept). 4xx batches are POISON — logged and dropped, never kept
    (they would block the drain forever). Call at startup. A dropped batch is lost
    data: record it as a gap (spec v0.1 §5.4)."""
    if not spool or not os.path.exists(spool):
        return 0, 0
    posted, kept = 0, []
    with open(spool) as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    for ln in lines:
        try:
            batch = json.loads(ln)
        except ValueError:
            print("spool: dropping unparseable line", file=sys.stderr)
            continue
        try:
            code, body = post_batch(base_url, batch, path=path, timeout=timeout,
                                    retries=1, token=token)
        except Exception:
            kept.append(ln)           # still unreachable — keep for next drain
            continue
        if 200 <= code < 300:
            posted += 1
        elif 400 <= code < 500:
            print(f"spool: dropping poison batch (HTTP {code}: {body[:120]})",
                  file=sys.stderr)
        else:
            kept.append(ln)
    tmp = spool + ".tmp"
    with open(tmp, "w") as f:
        f.write("".join(ln + "\n" for ln in kept))
    os.replace(tmp, spool)
    if posted or kept:
        print(f"spool drain: {posted} posted, {len(kept)} kept", file=sys.stderr)
    return posted, len(kept)
