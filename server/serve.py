#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Put a socket in front of `app.App` (spec v0.1 §7.6, §8.2, §10).

Standard library only. Everything with a decision about *data* in it lives in `app.py`
and `odata.py`, where it can be tested without a port; this file owns the socket and the
decisions a socket brings with it — who is asking, how many at once, how fast, and over
what.

    python3 serve.py --days 7 --open                 # a simulated week, on this machine only
    python3 serve.py --log farm.jsonl                # a real farm's log; tokens required
    python3 serve.py --log farm.jsonl --host 0.0.0.0 --tls-cert c.pem --tls-key k.pem

What it holds to:

* **Every request names who is asking**, as a bearer token (`access.py`): a farm user,
  who reads everything, or a grantee, who reads what their grants cover now (§7.6).
  `--open` allows anonymous reading for a demo, and only on the loopback interface.
* **Nothing leaves this machine in the clear.** Binding anything but loopback needs a
  certificate; behind a reverse proxy, bind loopback and let the proxy hold it.
* **One slow or hostile client cannot stall the rest.** Each connection has its own
  thread and a timeout, a TLS handshake happens in that thread rather than in the accept
  loop, at most `--max-concurrent` requests are worked on at once (the rest get 503), and
  each principal is rate-limited (429, with `Retry-After`).
* **The access log never holds a token.** One line per request: who, what, the outcome.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import ipaddress
import os
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sim"))
sys.path.insert(0, HERE)

import access as AC  # noqa: E402
import app as A  # noqa: E402

#: Sent with every response. The bodies are JSON, never to be sniffed into anything
#: else; an authenticated answer is not to be cached by anything in between.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


def is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


class Server(ThreadingHTTPServer):
    """A thread per connection, a cap on the work done at once, and TLS negotiated in
    the connection's own thread so a client that stalls its handshake stalls only
    itself."""

    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, handler, *, app, access, limiter, open_access=False,
                 tls: ssl.SSLContext | None = None, max_concurrent: int = 16,
                 timeout_s: float = 20.0, log_stream=None):
        self.app, self.access, self.limiter = app, access, limiter
        self.open_access, self.tls, self.timeout_s = open_access, tls, timeout_s
        self.slots = threading.BoundedSemaphore(max_concurrent)
        self.log_stream = log_stream or sys.stderr
        self._log_lock = threading.Lock()
        super().__init__(address, handler)

    def finish_request(self, request, client_address):
        request.settimeout(self.timeout_s)
        if self.tls is None:
            return super().finish_request(request, client_address)
        try:
            wrapped = self.tls.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            request.close()
            return
        try:
            super().finish_request(wrapped, client_address)
        finally:
            # The wrapper took the connection over; closing the original is a no-op.
            try:
                wrapped.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            wrapped.close()

    def handle_error(self, request, client_address):
        # A client that hangs up or times out is ordinary, and a traceback per
        # disconnect would bury the access log.
        pass

    def access_log(self, line: str) -> None:
        with self._log_lock:
            self.log_stream.write(line + "\n")
            self.log_stream.flush()


class Handler(BaseHTTPRequestHandler):

    server_version = "fieldmesh/0"
    server: Server

    def version_string(self) -> str:
        return self.server_version            # not which Python, which helps nobody but an attacker

    def _send(self, status: int, headers: dict, body: bytes, who: str) -> None:
        self.send_response(status)
        for key, value in {**headers, **SECURITY_HEADERS}.items():
            self.send_header(key, value)
        # A GIS client is very often a browser tab on another origin. Tokens travel in
        # a header, not a cookie, so a page on another origin cannot ride on a user's
        # credentials; it can read only with a token it was given.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)
        path = urlparse(self.path).path
        self.server.access_log(f"{self.client_address[0]} {who} {self.command} {path} "
                               f"{status} {len(body or b'')}")

    def _refuse(self, status: int, message: str, who: str, extra: dict | None = None):
        status_, headers, body = A._error(status, message)
        headers.update(extra or {})
        self._send(status, headers, body, who)

    def _respond(self):
        if not self.server.slots.acquire(blocking=False):
            return self._refuse(503, "busy; try again shortly", "-", {"Retry-After": "2"})
        try:
            now = _dt.datetime.now(tz=_dt.timezone.utc)
            who = self.server.access.resolve(self.headers.get("Authorization"), now)
            if who is None and self.server.open_access and not self.headers.get("Authorization"):
                who = AC.OPEN
            if who is None:
                return self._refuse(
                    401, "a bearer token is required: ask the farm's owner for one",
                    "-", {"WWW-Authenticate": 'Bearer realm="fieldmesh"'})
            allowed, wait = self.server.limiter.allow(who.key, time.monotonic())
            label = f"{who.kind}:{who.name}"
            if not allowed:
                return self._refuse(429, "too many requests", label,
                                    {"Retry-After": str(max(1, round(wait)))})
            parts = urlparse(self.path)
            status, headers, body = self.server.app.handle(
                self.command, parts.path, parts.query, dict(self.headers.items()),
                principal=who, at=now)
            self._send(status, headers, body, label)
        finally:
            self.server.slots.release()

    do_GET = _respond
    do_HEAD = _respond
    do_POST = _respond
    do_PUT = _respond
    do_PATCH = _respond
    do_DELETE = _respond

    def do_OPTIONS(self):
        # A CORS preflight cannot carry the token it is asking permission to send.
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Accept-Language")
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass                      # the access log above is the one log


def tls_context(cert: str, key: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


def make_server(app, access, *, host: str = "127.0.0.1", port: int = 8080,
                open_access: bool = False, tls: ssl.SSLContext | None = None,
                rate: float = 10.0, burst: int = 40, max_concurrent: int = 16,
                timeout_s: float = 20.0, log_stream=None) -> Server:
    """The server, refusing the configurations that would expose the farm's data."""
    if not is_loopback(host) and tls is None:
        raise SystemExit(f"refusing to serve on {host} without TLS: give --tls-cert and "
                         "--tls-key, or bind 127.0.0.1 behind a proxy that holds one")
    if open_access and not is_loopback(host):
        raise SystemExit("--open serves without tokens, and only on this machine (127.0.0.1)")
    return Server((host, port), Handler, app=app, access=access,
                  limiter=AC.RateLimiter(rate, burst), open_access=open_access, tls=tls,
                  max_concurrent=max_concurrent, timeout_s=timeout_s, log_stream=log_stream)


def read_from(path: str, offset: int):
    """The whole lines appended to a log file since `offset`, as events, and the offset
    after them. A line still being written is left for next time."""
    import log as L
    import json
    events = []
    with open(path, "rb") as h:
        h.seek(offset)
        data = h.read()
    end = data.rfind(b"\n") + 1
    for line in data[:end].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(L.Event.from_jsonable(json.loads(line)))
        except (ValueError, KeyError):
            continue              # §7.1: a bad line is reported by replay, not here
    return events, offset + end


def follow(path: str, log, lock, offset: int, *, every_s: float = 2.0,
           stop: threading.Event | None = None) -> None:
    """Keep an in-memory copy of a farm's log current with its file, so a token issued
    or revoked by `access.py` in another process counts without a restart. The server
    never writes the file."""
    stop = stop or threading.Event()
    while not stop.wait(every_s):
        events, offset = read_from(path, offset)
        for event in events:
            with lock:
                log.receive(event)


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
    ap.add_argument("--log", help="serve this farm's log rather than the simulated farm")
    ap.add_argument("--days", type=float, default=2.0,
                    help="how much simulated season to serve, without --log")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--open", action="store_true",
                    help="allow reading without a token (loopback only)")
    ap.add_argument("--tls-cert")
    ap.add_argument("--tls-key")
    ap.add_argument("--rate", type=float, default=10.0, help="requests a second per principal")
    ap.add_argument("--max-concurrent", type=int, default=16)
    args = ap.parse_args(argv)

    import log as L
    import project as P
    geometries = {}
    if args.log:
        farm_log = L.Log()                 # in memory: the server reads, never writes
        events, offset = read_from(args.log, 0)
        for event in events:
            farm_log.receive(event)
        state = P.state_from_log(farm_log)
        source = args.log
    else:
        farm = build_state(args.days, args.seed)
        import harrow_bend as hb
        farm_log, state, geometries = farm.log, farm.state, hb.geometries(farm)
        source = f"{args.days:g} simulated days"
    tls = tls_context(args.tls_cert, args.tls_key) if args.tls_cert else None
    scheme = "https" if tls else "http"
    base = f"{scheme}://{args.host}:{args.port}"
    app = A.make_app(state, base, geometries=geometries)
    access = AC.Access(farm_log)
    if args.log:
        def fold(event):
            record = event.record()
            if record is not None:
                with app.lock:
                    state.add(record)
        farm_log.on_commit(fold)
        threading.Thread(target=follow, args=(args.log, farm_log, app.lock, offset),
                         daemon=True).start()
    httpd = make_server(app, access, host=args.host, port=args.port, open_access=args.open,
                        tls=tls, rate=args.rate, max_concurrent=args.max_concurrent)
    print(f"serving {len(state.datastreams)} datastreams, {len(state.observations)} "
          f"observations ({source}) at {base}/v1.1", flush=True)
    if args.open:
        print(f"  open on this machine: curl -s '{base}/v1.1/Datastreams?$top=2'", flush=True)
    elif not access.any_issued:
        print("  no tokens issued yet, so nobody can read: python3 server/access.py issue "
              "--log FARM --role viewer", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
