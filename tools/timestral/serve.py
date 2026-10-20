#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Serve Timestral over a Unix socket, for `sdk/tsfm.Remote`: the model in a container,
the farm's code outside it, without PyTorch.

    python serve.py SOCKET --accept-weights-licence [--model REPO] [--revision SHA] [--offline]

One JSON message a line each way. `{"about": true}` gives the model's repo, weights and
package; `{"target", "covariates", "horizon"}` gives `{"quantiles", "levels"}`. Requests
are answered one at a time, however many clients connect.
"""
import argparse
import json
import os
import socketserver
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "sdk"))
import tsfm as TS  # noqa: E402


def make_server(path: str, model):
    """A server answering for `model` (anything with `forecast(target, covariates, horizon)`
    and a repo, weights and package) on the Unix socket at `path`, not yet serving."""
    lock = threading.Lock()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            for line in self.rfile:
                try:
                    m = json.loads(line)
                    if m.get("about"):
                        reply = {"repo": model.repo, "weights": model.weights, "package": model.package}
                    else:
                        with lock:
                            q, levels = model.forecast(m["target"], m["covariates"], int(m["horizon"]))
                        reply = {"quantiles": q, "levels": list(levels)}
                except Exception as e:  # noqa: BLE001 — the client is told, the server stays up
                    reply = {"error": f"{type(e).__name__}: {e}"}
                self.wfile.write(json.dumps(reply).encode() + b"\n")
                self.wfile.flush()

    if os.path.exists(path):
        os.remove(path)
    server = socketserver.ThreadingUnixStreamServer(path, Handler)
    os.chmod(path, 0o666)
    return server


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("socket")
    ap.add_argument("--accept-weights-licence", action="store_true")
    ap.add_argument("--model", default=TS.DEFAULT_MODEL)
    ap.add_argument("--revision")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args(argv)
    try:
        model = TS.load(args.model, accept_weights_licence=args.accept_weights_licence,
                        revision=args.revision, offline=args.offline, threads=args.threads)
    except TS.LicenceNotAccepted as e:
        print(e, file=sys.stderr)
        return 2
    server = make_server(args.socket, model)
    print(f"serving {model.repo} ({model.weights[:12]}) on {args.socket}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
