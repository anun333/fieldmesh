#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The wired control link (Q6): Modbus RTU framing, and a round trip over a pty.

Q6 keeps a wired driver in the test suite because it is the only link where a discrepancy
is unambiguously a data-model bug — no loss, no duplication, no duty cycle to blame."""
from __future__ import annotations

import os
import unittest

import modbus_rtu as M


class FakeSource:
    def __init__(self):
        self.registers = {(1, "input", 100): [281, 2150]}

    def read(self, unit, table, address, words):
        got = self.registers.get((unit, table, address))
        return got[:words] if got and len(got) >= words else None


class FramingTest(unittest.TestCase):
    def test_the_crc_matches_the_specifications_example(self):
        # Modbus over Serial Line V1.02: read 10 holding registers from unit 1 at 0.
        self.assertEqual(M.build_read(1, "holding", 0, 10).hex(), "01030000000ac5cd")

    def test_writes_are_refused_by_construction(self):
        with self.assertRaises(KeyError):
            M.build_read(1, "coil", 0, 1)

    def test_bounds(self):
        for args in ((0, "input", 0, 1), (1, "input", 0, 126), (248, "input", 0, 1)):
            with self.assertRaises(ValueError):
                M.build_read(*args)

    def test_a_reply_parses_and_a_bad_one_does_not(self):
        reply = M.with_crc(bytes((1, 4, 4, 0x01, 0x19, 0x08, 0x66)))
        self.assertEqual(M.parse_reply(reply, 1, 4, 2), [281, 2150])
        self.assertIsNone(M.parse_reply(reply[:-1] + b"\x00", 1, 4, 2), "bad CRC")
        self.assertIsNone(M.parse_reply(reply, 2, 4, 2), "another unit")
        self.assertIsNone(M.parse_reply(M.with_crc(bytes((1, 0x84, 2))), 1, 4, 2), "exception")


class OverAPtyTest(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = os.openpty()
        self.responder = M.RtuResponder(self.master, FakeSource())
        self.responder.start()
        self.source = M.RtuSource(fd=self.slave, baud=19200, timeout=1.0)

    def tearDown(self):
        self.responder.stop.set()
        self.responder.join(timeout=1)
        self.source.close()
        os.close(self.master)

    def test_two_registers_come_back_as_written(self):
        self.assertEqual(self.source.read(1, "input", 100, 2), [281, 2150])
        self.assertEqual(self.responder.requests, [(1, 4, 100, 2)])

    def test_an_unknown_register_is_an_exception_not_a_value(self):
        self.assertIsNone(self.source.read(1, "input", 7, 1))


if __name__ == "__main__":
    unittest.main()
