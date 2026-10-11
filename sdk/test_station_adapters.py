#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Weather stations on their own local protocols — Tempest's UDP broadcast, WeatherLink
Live's HTTP API, an Ecowitt gateway's posts — parsed from the makers' documented examples
and carried over real sockets on loopback."""
from __future__ import annotations

import datetime as _dt
import json
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import fixtures as fx
import log as L
import mqtt_bridge as B
import project as P
import station_adapters as A

UTC = _dt.timezone.utc

#: WeatherFlow's own example, Tempest UDP reference v171.
OBS_ST = {"serial_number": "ST-00000512", "type": "obs_st", "hub_sn": "HB-00013030",
          "obs": [[1588948614, 0.18, 0.22, 0.27, 144, 6, 1017.57, 22.37, 50.26, 328, 0.03, 3,
                   0.000000, 0, 0, 0, 2.410, 1]],
          "firmware_revision": 129}
#: Shaped as Davis's local API reference gives it; an ISS record.
WLL = {"data": {"did": "001D0A700002", "ts": 1531754005, "conditions": [
    {"lsid": 48308, "data_structure_type": 1, "txid": 1, "temp": 62.7, "hum": 1.1,
     "wind_speed_last": 0.0, "wind_dir_last": 0, "solar_rad": 747, "uv_index": 5.5,
     "rain_size": 2, "rainfall_daily": 63, "ts": 1531754005}]}, "error": None}


class _Farm:
    def __init__(self, key, **points):
        self.log = L.Log()
        self.streams = {}
        for point in points.values():
            ds = fx.raw_datastream(unit="1")
            self.log.append_record(ds)
            self.streams[point] = ds
        self.state = P.state_from_log(self.log)
        self.bridge = B.Bridge(self.log, self.state, {"devices": {key: {
            "uncertainty_s": 2.0,
            "points": {p: {"datastream": str(self.streams[n].id)} for p, n in points.items()}}}})

    def rows(self, name):
        return self.state.live_observations_of(self.streams[name].id)


def _wait_for(check, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


class TestTempest(unittest.TestCase):

    def test_the_makers_example_parses_index_by_index(self):
        p = A.parse_tempest(json.dumps(OBS_ST))
        self.assertEqual(p["device"], "ST-00000512")
        self.assertEqual((p["points"]["air_temperature"], p["points"]["relative_humidity"],
                          p["points"]["solar_radiation"], p["points"]["rain"],
                          p["points"]["battery"]), (22.37, 50.26, 3, 0.0, 2.41))
        self.assertEqual(p["stamp"], 1588948614)
        self.assertIsNone(A.parse_tempest({"type": "rapid_wind", "ob": [1, 2.3, 128]}))

    def test_heard_over_udp_and_written_at_its_own_time(self):
        farm = _Farm("tempest:ST-00000512", air_temperature="air", solar_radiation="sun")
        stop, port = threading.Event(), []
        listener = threading.Thread(target=A.tempest_listen, args=(farm.bridge,),
                                    kwargs={"port": 0, "host": "127.0.0.1", "stop": stop,
                                            "ready": port.append}, daemon=True)
        listener.start()
        try:
            self.assertTrue(_wait_for(lambda: port))
            message = dict(OBS_ST, obs=[[int(time.time()) - 60] + OBS_ST["obs"][0][1:]])
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(json.dumps(message).encode(), ("127.0.0.1", port[0]))
            self.assertTrue(_wait_for(lambda: farm.rows("air")))
            [air] = farm.rows("air")
            self.assertEqual(air.result, 22.37)
            self.assertEqual(air.measured_at,
                             _dt.datetime.fromtimestamp(message["obs"][0][0], tz=UTC))
        finally:
            stop.set()
            listener.join(timeout=2)


class TestWeatherLinkLive(unittest.TestCase):

    def test_one_message_a_sensor_record_and_rain_left_as_counts(self):
        [p] = A.parse_weatherlink(json.dumps(WLL))
        self.assertEqual(p["device"], "001D0A700002:48308")
        self.assertEqual((p["points"]["temp"], p["points"]["rainfall_daily"],
                          p["points"]["rain_size"]), (62.7, 63, 2))
        self.assertNotIn("lsid", p["points"])
        self.assertEqual(p["stamp"], 1531754005)

    def test_polled_over_http(self):
        body = json.dumps(dict(WLL, data=dict(WLL["data"], conditions=[
            dict(WLL["data"]["conditions"][0], ts=int(time.time()) - 30)]))).encode()

        class Davis(BaseHTTPRequestHandler):
            def do_GET(self):                                  # noqa: N802
                ok = self.path == "/v1/current_conditions"
                self.send_response(200 if ok else 404)
                self.end_headers()
                if ok:
                    self.wfile.write(body)

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Davis)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            farm = _Farm("weatherlink:001D0A700002:48308", temp="air", solar_rad="sun")
            written = A.weatherlink_poll(farm.bridge, f"127.0.0.1:{server.server_address[1]}")
            self.assertEqual(written, 2)
            self.assertEqual(farm.rows("sun")[0].result, 747)
        finally:
            server.shutdown()
            server.server_close()


class TestEcowitt(unittest.TestCase):

    FORM = {"PASSKEY": "0123456789ABCDEF", "stationtype": "GW2000A_V3.1.0",
            "dateutc": "2026-06-15 19:00:00", "tempf": "81.3", "humidity": "61",
            "solarradiation": "712.40", "dailyrainin": "0.12", "model": "GW2000A"}

    def test_its_form_and_its_utc_time_in_either_form(self):
        p = A.parse_ecowitt(self.FORM)
        self.assertEqual(p["device"], "0123456789ABCDEF")
        self.assertEqual(p["points"], {"tempf": 81.3, "humidity": 61.0,
                                       "solarradiation": 712.4, "dailyrainin": 0.12})
        self.assertEqual(p["stamp"], "2026-06-15 19:00:00+00:00")
        self.assertEqual(A.parse_ecowitt(dict(self.FORM, dateutc="1781550000"))["stamp"],
                         "1781550000")
        self.assertIsNone(A.parse_ecowitt(dict(self.FORM, dateutc="now"))["stamp"])

    def _post(self, allow, form):
        farm = _Farm("ecowitt:0123456789ABCDEF", tempf="air")
        server = A.ecowitt_server(farm.bridge, host="127.0.0.1", port=0, allow=allow)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            data = urllib.parse.urlencode(form).encode()
            url = f"http://127.0.0.1:{server.server_address[1]}/data/report/"
            try:
                with urllib.request.urlopen(url, data=data, timeout=5) as reply:
                    status = reply.status
            except urllib.error.HTTPError as exc:
                status = exc.code
            return status, farm
        finally:
            server.shutdown()
            server.server_close()

    def test_a_post_from_the_gateway_is_written(self):
        now = _dt.datetime.now(tz=UTC).replace(microsecond=0)
        status, farm = self._post(frozenset({"127.0.0.1"}),
                                  dict(self.FORM, dateutc=now.strftime("%Y-%m-%d %H:%M:%S")))
        self.assertEqual(status, 200)
        [air] = farm.rows("air")
        self.assertEqual((air.result, air.measured_at), (81.3, now))

    def test_a_post_from_anywhere_else_is_refused(self):
        status, farm = self._post(frozenset({"192.0.2.10"}), self.FORM)
        self.assertEqual(status, 403)
        self.assertEqual(farm.rows("air"), [])

    def test_an_unbound_gateway_is_named_not_written(self):
        status, farm = self._post(frozenset({"127.0.0.1"}), dict(self.FORM, PASSKEY="FFFF"))
        self.assertEqual(status, 200)
        self.assertEqual(farm.rows("air"), [])
        self.assertIn("ecowitt:FFFF", farm.bridge.report.unbound_devices)


if __name__ == "__main__":
    unittest.main()
