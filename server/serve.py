#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Put a socket in front of `app.App` (spec v0.1 §10).

Standard library only. The point of this file is to be boring: it owns the socket and
nothing else, so that everything with a decision in it lives in `app.py` and `odata.py`
where it can be tested without a port. If this file grows logic, that is a sign
something belongs in one of those.

    python3 serve.py --days 7            # a simulated week, served
    python3 serve.py --days 7 --port 8099

Not hardened for exposure to a network. It is single-threaded by choice — a read-only
projection served to one GIS client at a time is the use case, and concurrency here
would mean deciding what happens when state is rebuilt mid-request.
"""
from __future__ import annotations

import argparse
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "sdk"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "sim"))

import app as A  # noqa: E402


class Handler(BaseHTTPRequestHandler):

    server_version = "librefarm/0"
    app: A.App

    def _respond(self):
        parts = urlparse(self.path)
        status, headers, body = self.app.handle(self.command, parts.path, parts.query)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        # A GIS client is very often a browser tab or a desktop app on another origin.
        # This service is read-only and public by construction, so the permissive
        # header costs nothing that was not already readable.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if body:
            self.wfile.write(body)

    do_GET = _respond
    do_HEAD = _respond
    do_POST = _respond
    do_PUT = _respond
    do_PATCH = _respond
    do_DELETE = _respond

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def build_state(days: float, seed: int):
    """Harrow Bend, run for `days`, as the thing to serve.

    The simulator is the only source of a populated state that needs no hardware, which
    is the whole premise of docs/VIRTUAL_FARM.md.
    """
    import harrow_bend as hb
    farm = hb.build(seed=seed)
    hb.season(farm, days=days, seed=seed)
    return farm


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--days", type=float, default=2.0,
                    help="how much simulated season to serve")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    farm = build_state(args.days, args.seed)
    base = f"http://{args.host}:{args.port}"
    import harrow_bend as hb
    app = A.make_app(farm.state, base, labels=hb.labels(farm))

    streams = len(farm.state.datastreams)
    rows = len(farm.state.observations)
    print(f"serving {streams} datastreams, {rows} observations "
          f"({args.days:g} simulated days) at {base}/v1.1", flush=True)
    print(f"  try: curl -s '{base}/v1.1/Datastreams?$top=2'", flush=True)

    Handler.app = app
    httpd = HTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
