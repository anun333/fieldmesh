#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Weather stations that speak their own local protocol, into the log (spec v0.1 §10).

Three stations keep their data on the farm's network rather than only in a maker's
cloud, each in its own way. Each is read here, parsed to what the MQTT bridge's profiles
parse to, and written by the bridge's bindings and rules: the binding is the allowlist,
values land as published on raw datastreams, and a time with no zone is never guessed
(`mqtt_bridge.Bridge.ingest`).

* **WeatherFlow Tempest**: the hub broadcasts each minute's observation over UDP port
  50222 (`obs_st`, WeatherFlow's Tempest UDP reference v171). The device is the
  station's serial number, the time the observation's epoch seconds. Points, in its
  units: `wind_lull`, `wind_avg`, `wind_gust` (m/s), `wind_direction` (degrees),
  `station_pressure` (hPa), `air_temperature` (Cel), `relative_humidity` (%),
  `illuminance` (lux), `uv_index`, `solar_radiation` (W/m2), `rain` (mm in the report
  interval), `precipitation_type`, `lightning_distance` (km), `lightning_count`,
  `battery` (V).
* **Davis WeatherLink Live**: `GET http://<ip>/v1/current_conditions`, at most every 10
  seconds (Davis's local API). One device a sensor record, `<did>:<lsid>`, its time its
  own `ts`. Every number is a point under Davis's name, in Davis's units: `temp` °F,
  `wind_speed_last` mph, `solar_rad` W/m2, and rain as **counts** of the gauge's
  `rain_size` (1: 0.01 in, 2: 0.2 mm, 3: 0.1 mm, 4: 0.001 in), which a calibration turns
  into millimetres (§3.2).
* **Ecowitt gateways** (and the Fine Offset family behind them): the gateway's
  "customized upload" posts a form in the Ecowitt protocol to a server it is pointed at.
  The device is its `PASSKEY`. Every numeric field is a point under Ecowitt's name, in its
  units (`tempf`, `windspeedmph`, `solarradiation`, `dailyrainin`...). `dateutc` is read
  as UTC, as its name says, whether epoch seconds or `YYYY-MM-DD HH:MM:SS`.
  **The post is plain HTTP on the farm's network**, so anything there could post: the
  server takes only bound PASSKEYs, and the command line will not start it without
  `--allow`, the gateway's address.

    python3 station_adapters.py --bindings b.json --log farm.jsonl tempest
    python3 station_adapters.py --bindings b.json --log farm.jsonl weatherlink 192.168.1.40
    python3 station_adapters.py --bindings b.json --log farm.jsonl ecowitt --allow 192.168.1.41

with bindings keyed `tempest:ST-00000512`, `weatherlink:001D0A700002:1`,
`ecowitt:<PASSKEY>`, as the bridge's are.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import socket
import sys
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UTC = _dt.timezone.utc
TEMPEST_PORT = 50222
ECOWITT_PORT = 49199

#: The `obs` array of a Tempest `obs_st`, index by index (UDP reference v171).
TEMPEST_OBS = ("time", "wind_lull", "wind_avg", "wind_gust", "wind_direction",
               "wind_sample_interval", "station_pressure", "air_temperature",
               "relative_humidity", "illuminance", "uv_index", "solar_radiation", "rain",
               "precipitation_type", "lightning_distance", "lightning_count", "battery",
               "report_interval")
#: Ecowitt form fields that describe the post, not the weather.
ECOWITT_META = frozenset({"PASSKEY", "stationtype", "model", "dateutc", "freq", "runtime",
                          "interval", "heap"})


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def parse_tempest(message) -> dict | None:
    """A Tempest hub's UDP datagram (bytes, text or dict) to `{device, points, health,
    stamp}`; None for anything but an `obs_st`."""
    if isinstance(message, (bytes, str)):
        try:
            message = json.loads(message)
        except ValueError:
            return None
    if not isinstance(message, dict) or message.get("type") != "obs_st":
        return None
    rows = message.get("obs") or []
    if not rows or not isinstance(rows[0], list):
        return None
    values = dict(zip(TEMPEST_OBS, rows[0]))
    points = {k: v for k, v in values.items()
              if k not in ("time", "wind_sample_interval", "report_interval")
              and _number(v) is not None}
    return {"device": message.get("serial_number"), "points": points, "health": {},
            "stamp": values.get("time")}


def parse_weatherlink(body) -> list:
    """A WeatherLink Live's `current_conditions` reply to one parsed message a sensor
    record, `<did>:<lsid>`."""
    if isinstance(body, (bytes, str)):
        try:
            body = json.loads(body)
        except ValueError:
            return []
    data = (body or {}).get("data") or {}
    out = []
    for record in data.get("conditions") or []:
        if not isinstance(record, dict):
            continue
        device = f"{data.get('did')}:{record.get('lsid')}"
        points = {k: v for k, v in record.items()
                  if k not in ("lsid", "data_structure_type", "txid", "ts")
                  and _number(v) is not None}
        out.append({"device": device, "points": points, "health": {},
                    "stamp": record.get("ts", data.get("ts"))})
    return out


def parse_ecowitt(form: dict) -> dict | None:
    """An Ecowitt gateway's customized-upload form, `{field: value}`, to one parsed
    message."""
    key = form.get("PASSKEY")
    if not key:
        return None
    stamp = form.get("dateutc")
    if isinstance(stamp, str) and stamp and not stamp.isdigit():
        stamp = None if stamp == "now" else stamp.replace("+", " ").strip() + "+00:00"
    points = {}
    for k, v in form.items():
        if k in ECOWITT_META:
            continue
        x = _number(v)
        if x is not None:
            points[k] = x
    return {"device": key, "points": points, "health": {}, "stamp": stamp}


# ----------------------------------------------------------------- listening

def _now() -> _dt.datetime:
    return _dt.datetime.now(tz=UTC)


def tempest_listen(bridge, *, port: int = TEMPEST_PORT, host: str = "0.0.0.0",
                   stop: threading.Event | None = None, ready=None) -> None:
    """Receive the hub's broadcasts until `stop` is set. `ready(port)` is called once
    bound, with the port, which a test passes as 0."""
    stop = stop or threading.Event()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.settimeout(0.2)
        if ready:
            ready(sock.getsockname()[1])
        while not stop.is_set():
            try:
                datagram, sender = sock.recvfrom(65535)
            except socket.timeout:
                continue
            parsed = parse_tempest(datagram)
            if parsed is not None:
                bridge.ingest("tempest", parsed, arrived=_now(),
                              provenance={"udp_from": sender[0], "profile": "tempest"})


def weatherlink_poll(bridge, host: str, *, timeout: float = 10.0) -> int:
    """Read a WeatherLink Live once; returns how many observations were written."""
    url = f"http://{host}/v1/current_conditions"
    with urllib.request.urlopen(url, timeout=timeout) as reply:    # the farm's own LAN
        body = reply.read()
    arrived = _now()
    return sum(bridge.ingest("weatherlink", p, arrived=arrived,
                             provenance={"http_from": host, "profile": "weatherlink"})
               for p in parse_weatherlink(body))


def ecowitt_server(bridge, *, host: str = "0.0.0.0", port: int = ECOWITT_PORT,
                   allow: frozenset = frozenset()) -> ThreadingHTTPServer:
    """An HTTP server for an Ecowitt gateway's posts, not yet serving: call
    `serve_forever()`. With `allow`, posts from any other address are refused (403)."""
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):                                         # noqa: N802
            if allow and self.client_address[0] not in allow:
                self.send_response(403)
                self.end_headers()
                return
            length = min(int(self.headers.get("Content-Length") or 0), 65536)
            form = {k: v[-1] for k, v in urllib.parse.parse_qs(
                self.rfile.read(length).decode("utf-8", "replace")).items()}
            parsed = parse_ecowitt(form)
            if parsed is not None:
                with lock:
                    bridge.ingest("ecowitt", parsed, arrived=_now(),
                                  provenance={"http_from": self.client_address[0],
                                              "profile": "ecowitt"})
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None) -> int:
    import time

    import log as L
    import mqtt_bridge as B
    import project as P
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bindings", required=True)
    ap.add_argument("--log", required=True)
    sub = ap.add_subparsers(dest="station", required=True)
    sub.add_parser("tempest")
    wl = sub.add_parser("weatherlink")
    wl.add_argument("host")
    wl.add_argument("--every", type=float, default=60.0)
    ew = sub.add_parser("ecowitt")
    ew.add_argument("--port", type=int, default=ECOWITT_PORT)
    ew.add_argument("--allow", action="append", default=[],
                    help="the gateway's address; posts from any other are refused")
    args = ap.parse_args(argv)
    with open(args.bindings, encoding="utf-8") as handle:
        bindings = json.load(handle)
    log = L.Log(args.log)
    bridge = B.Bridge(log, P.state_from_log(log), bindings)
    try:
        if args.station == "tempest":
            tempest_listen(bridge)
        elif args.station == "weatherlink":
            while True:
                weatherlink_poll(bridge, args.host)
                time.sleep(max(10.0, args.every))
        else:
            if not args.allow:
                ap.error("an Ecowitt gateway posts plain HTTP on the farm's network: name "
                         "its address with --allow, so nothing else can post readings")
            ecowitt_server(bridge, port=args.port, allow=frozenset(args.allow)).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        summary = {k: (sorted(v) if isinstance(v, set) else v)
                   for k, v in bridge.report.__dict__.items()}
        print(json.dumps(summary, indent=1), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
