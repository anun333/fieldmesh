#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The Modbus collector: a METER ATMOS 41 Gen 2 weather station, as its integrator guide
describes its registers, answering over a pty."""
from __future__ import annotations

import datetime as _dt
import os
import struct
import unittest

import fixtures as fx
import log as L
import modbus_collector as C
import modbus_rtu as M
import project as P

UTC = _dt.timezone.utc
T0 = _dt.datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


def words_of(values: dict) -> list:
    """The 44 input registers an ATMOS 41 Gen 2 would answer with, big-endian floats."""
    words = [0] * 44
    for name, value in values.items():
        offset, _ = C.MAPS["atmos41_gen2"]["points"][name]
        hi, lo = struct.unpack(">HH", struct.pack(">f", value))
        words[offset], words[offset + 1] = hi, lo
    return words


class FakeAtmos:
    """Answers a burst read of 3001-3044 with the next of `readings`, as the station
    resets its accumulators on each read; anything else is an illegal address."""

    def __init__(self, *readings):
        self.readings = list(readings)
        self.reads = []

    def read(self, unit, table, address, words):
        self.reads.append((unit, table, address, words))
        if (unit, table, address, words) != (1, "input", 3000, 44) or not self.readings:
            return None
        return words_of(self.readings.pop(0))


class _Farm:
    def __init__(self, *names, kind_derived=()):
        self.log = L.Log()
        self.streams = {}
        for name in names:
            ds = fx.raw_datastream(unit="1")
            if name in kind_derived:
                ds = fx.derived_datastream(ds, unit="1")
            self.log.append_record(ds)
            self.streams[name] = ds
        self.state = P.state_from_log(self.log)

    def bindings(self, **points):
        return {"devices": {"weather": {
            "map": "atmos41_gen2", "port": "/dev/ttyUSB0", "uncertainty_s": 2.0,
            "points": {p: {"datastream": str(self.streams[s].id)} for p, s in points.items()}}}}


class TestDecode(unittest.TestCase):

    def test_the_guides_byte_order_and_its_slip(self):
        """Table 22 puts the high word in the first register, the order decoded here. Its
        example has a slip: 123456.0 is 0x47F12000, and the 0x471F2000 it prints is
        40736.0."""
        self.assertEqual(C.decode([0x47F1, 0x2000], {"x": (0, "f32")}), {"x": 123456.0})
        self.assertEqual(C.decode([0x471F, 0x2000], {"x": (0, "f32")}), {"x": 40736.0})

    def test_every_point_of_a_burst(self):
        values = {"solar_radiation": 812.5, "air_temperature": 27.25,
                  "relative_humidity": 0.625, "precipitation": 1.5, "tilt_y": -0.75}
        got = C.decode(words_of(values), C.MAPS["atmos41_gen2"]["points"])
        for name, value in values.items():
            self.assertAlmostEqual(got[name], value, places=4)


class TestCollector(unittest.TestCase):

    def setUp(self):
        self.farm = _Farm("sun", "air", "rh", "rain")
        self.station = FakeAtmos(
            {"solar_radiation": 812.5, "air_temperature": 27.25, "relative_humidity": 0.625,
             "precipitation": 0.0},
            {"solar_radiation": 640.0, "air_temperature": 27.75, "relative_humidity": 0.6,
             "precipitation": 2.25})
        self.collector = C.Collector(
            self.farm.log, self.farm.state,
            self.farm.bindings(solar_radiation="sun", air_temperature="air",
                               relative_humidity="rh", precipitation="rain"),
            {"/dev/ttyUSB0": self.station})

    def rows(self, name):
        return self.farm.state.live_observations_of(self.farm.streams[name].id)

    def test_one_burst_read_a_poll_and_the_bound_points_written(self):
        self.assertEqual(self.collector.poll(T0), 4)
        self.assertEqual(self.station.reads, [(1, "input", 3000, 44)])
        self.assertEqual(self.rows("sun")[0].result, 812.5)
        self.assertEqual(self.rows("rh")[0].result, 0.625)
        self.assertEqual(self.rows("air")[0].measured_at, T0)

    def test_each_reading_says_what_it_covers(self):
        """Its accumulators reset on every read: the rain is the rain since the poll
        before, and the first poll's span is not known."""
        later = T0 + _dt.timedelta(minutes=5)
        self.collector.poll(T0)
        self.collector.poll(later)
        first, second = self.rows("rain")
        self.assertIsNone(first.provenance["since"])
        self.assertEqual(second.provenance["since"], T0.isoformat())
        self.assertEqual(second.result, 2.25)

    def test_a_silent_station_writes_nothing_and_is_counted(self):
        self.collector.poll(T0)
        self.collector.poll(T0 + _dt.timedelta(minutes=5))
        self.assertEqual(self.collector.poll(T0 + _dt.timedelta(minutes=10)), 0)
        self.assertEqual(self.collector.report.no_answer, 1)
        self.assertEqual(self.collector.report.no_answer_devices, {"weather"})


class TestBindingsAreChecked(unittest.TestCase):

    def test_what_is_refused(self):
        farm = _Farm("air", "cal", kind_derived=("cal",))
        sources = {"/dev/ttyUSB0": FakeAtmos()}
        cases = [
            (dict(map="vantage_pro"), "unknown map"),
            (dict(port="/dev/ttyUSB9"), "no source open"),
            (dict(uncertainty_s=0), "uncertainty_s"),
        ]
        for change, message in cases:
            b = farm.bindings(air_temperature="air")
            b["devices"]["weather"].update(change)
            with self.assertRaisesRegex(C.BindingError, message):
                C.Collector(farm.log, farm.state, b, sources)
        with self.assertRaisesRegex(C.BindingError, "no point"):
            C.Collector(farm.log, farm.state, farm.bindings(dew_point="air"), sources)
        with self.assertRaisesRegex(C.BindingError, "derived"):
            C.Collector(farm.log, farm.state, farm.bindings(air_temperature="cal"), sources)
        b = farm.bindings(air_temperature="air")
        b["devices"]["weather"]["points"]["air_temperature"]["scale"] = 0.1
        with self.assertRaisesRegex(C.BindingError, "Calibration"):
            C.Collector(farm.log, farm.state, b, sources)


class TestOverTheWire(unittest.TestCase):
    """The same station answering RTU frames on a pty, through modbus_rtu's driver."""

    def test_a_poll_over_a_serial_line(self):
        master, slave = os.openpty()
        station = FakeAtmos({"solar_radiation": 455.0, "air_temperature": 19.5})
        responder = M.RtuResponder(master, station)
        responder.start()
        source = M.RtuSource(fd=slave, baud=9600, parity="E", timeout=1.0)
        try:
            farm = _Farm("sun", "air")
            collector = C.Collector(farm.log, farm.state,
                                    farm.bindings(solar_radiation="sun", air_temperature="air"),
                                    {"/dev/ttyUSB0": source})
            self.assertEqual(collector.poll(T0), 2)
            self.assertEqual(responder.requests, [(1, 4, 3000, 44)])
            [air] = farm.state.live_observations_of(farm.streams["air"].id)
            self.assertEqual(air.result, 19.5)
        finally:
            responder.stop.set()
            responder.join(timeout=1)
            source.close()
            os.close(master)


if __name__ == "__main__":
    unittest.main()
