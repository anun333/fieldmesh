#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Modbus RTU over a serial line — stdlib only, READ function codes only *for now*.

Irrigation controllers, VFD pump drives, flow meters, soil-probe interfaces and most
tank-level transmitters speak Modbus RTU on RS-485, not TCP. A $10 USB-RS485 adapter on
the gateway reaches them. pymodbus would do it too, but it pulls in pyserial and a
dependency chain the Pi-class edge daemon should not need, and the protocol is small
enough to hold in one file:

  frame   [unit][function][payload…][CRC16 lo][CRC16 hi]   (CRC-16/MODBUS, poly 0xA001)
  read    FC03 holding / FC04 input: [unit][fc][addr hi][addr lo][count hi][count lo]
  reply   [unit][fc][byte count][data…]  or an exception [unit][fc|0x80][code]

There is no write function code in this file **yet**, and that is a sequencing decision,
not a permanent one. Layer zero does command pumps and valves (spec v0.1 §6), but the
first release ships observations only, and the command contract is frozen after a season
of field evidence. When FC05/FC06/FC16 arrive they arrive underneath §6: a desired state
rather than a toggle, an expiry, bounded idempotency, and node-side limits the server
cannot override. A bare Modbus write with none of that is exactly the unsafe path §6
exists to prevent, so the absence here is load-bearing until then.

This differs from the file's origin, where read-only was permanent by design. Expect
this file to diverge rather than track.

  RtuSource("/dev/ttyUSB0", baud=9600, parity="N")   # the collector source interface
  RtuResponder(fd, fake_source)                       # the test half: answers on a pty

Provenance: adapted from campus_twin's `open-bas/connectors/modbus_rtu.py`
(same author, Apache-2.0 OR GPL-3.0-or-later at origin). See PROVENANCE.md.
"""
from __future__ import annotations

import os
import select
import threading
import time

READ_FC = {"holding": 0x03, "input": 0x04}


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS: init 0xFFFF, reflected polynomial 0xA001."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(body: bytes) -> bytes:
    c = crc16(body)
    return body + bytes((c & 0xFF, c >> 8))                  # low byte first


def crc_ok(frame: bytes) -> bool:
    return len(frame) >= 4 and crc16(frame[:-2]) == frame[-2] | (frame[-1] << 8)


def build_read(unit: int, table: str, address: int, count: int) -> bytes:
    fc = READ_FC[table]                                      # KeyError = not a read: refused
    if not (0 <= address <= 0xFFFF and 1 <= count <= 125 and 1 <= unit <= 247):
        raise ValueError("address 0–65535, count 1–125, unit 1–247")
    return with_crc(bytes((unit, fc, address >> 8, address & 0xFF, count >> 8, count & 0xFF)))


def parse_reply(frame: bytes, unit: int, fc: int, count: int):
    """A reply frame → [words], or None for an exception/garbled/mismatched frame."""
    if not crc_ok(frame) or frame[0] != unit:
        return None
    if frame[1] == (fc | 0x80) or frame[1] != fc:
        return None
    n = frame[2]
    if n != 2 * count or len(frame) != 3 + n + 2:
        return None
    return [(frame[3 + 2 * i] << 8) | frame[4 + 2 * i] for i in range(count)]


def expected_len(fc_byte: int, head: bytes) -> int | None:
    """Total reply length once the first 3 bytes are known."""
    if fc_byte & 0x80:
        return 5
    if len(head) >= 3:
        return 3 + head[2] + 2
    return None


def _configure(fd, baud, parity, stopbits):
    import termios
    speeds = {1200: termios.B1200, 2400: termios.B2400, 4800: termios.B4800,
              9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
              57600: termios.B57600, 115200: termios.B115200}
    if baud not in speeds:
        raise ValueError(f"unsupported baud {baud}")
    attrs = termios.tcgetattr(fd)
    iflag, oflag, cflag, lflag = 0, 0, termios.CS8 | termios.CREAD | termios.CLOCAL, 0
    if parity in ("E", "O"):
        cflag |= termios.PARENB | (termios.PARODD if parity == "O" else 0)
    if stopbits == 2:
        cflag |= termios.CSTOPB
    attrs[0], attrs[1], attrs[2], attrs[3] = iflag, oflag, cflag, lflag
    attrs[4] = attrs[5] = speeds[baud]
    attrs[6][termios.VMIN], attrs[6][termios.VTIME] = 0, 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


class RtuSource:
    """The modbus_collector source interface over a serial device (or any tty fd)."""

    def __init__(self, device=None, *, baud=9600, parity="N", stopbits=1, timeout=1.0,
                 fd=None):
        self.fd = fd if fd is not None else os.open(device, os.O_RDWR | os.O_NOCTTY)
        _configure(self.fd, baud, parity, stopbits)
        self.timeout = timeout
        # 3.5 character times of silence separate frames (11 bits/char at this baud)
        self.gap = max(3.5 * 11 / baud, 0.00175)
        self.lock = threading.Lock()

    def _read_frame(self):
        buf = b""
        deadline = time.monotonic() + self.timeout
        need = None
        while time.monotonic() < deadline:
            r, _, _ = select.select([self.fd], [], [], max(0.0, deadline - time.monotonic()))
            if not r:
                break
            chunk = os.read(self.fd, 256)
            if not chunk:
                break
            buf += chunk
            if need is None and len(buf) >= 3:
                need = expected_len(buf[1], buf)
            if need is not None and len(buf) >= need:
                return buf[:need]
        return buf or None

    def read(self, unit, table, address, words):
        fc = READ_FC.get(table)
        if fc is None:
            return None
        with self.lock:
            time.sleep(self.gap)
            os.write(self.fd, build_read(unit, table, address, words))
            frame = self._read_frame()
        return parse_reply(frame, unit, fc, words) if frame else None

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


class RtuResponder(threading.Thread):
    """Test half: answer RTU read requests on `fd` from a FakeModbusSource-like `source`
    (read(unit, table, address, words) → words | None). Unknown registers → exception 02;
    anything that is not FC03/FC04 → exception 01 (and it is never acted on)."""

    def __init__(self, fd, source):
        super().__init__(daemon=True)
        self.fd, self.source, self.stop = fd, source, threading.Event()
        self.requests = []

    def run(self):
        buf = b""
        while not self.stop.is_set():
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if not r:
                continue
            try:
                buf += os.read(self.fd, 256)
            except OSError:
                return
            while len(buf) >= 8:
                req, buf = buf[:8], buf[8:]
                if not crc_ok(req):
                    buf = b""                                 # resync on garbage
                    break
                unit, fc = req[0], req[1]
                addr, count = (req[2] << 8) | req[3], (req[4] << 8) | req[5]
                self.requests.append((unit, fc, addr, count))
                table = {0x03: "holding", 0x04: "input"}.get(fc)
                words = self.source.read(unit, table, addr, count) if table else None
                if table is None:
                    reply = with_crc(bytes((unit, fc | 0x80, 0x01)))
                elif words is None:
                    reply = with_crc(bytes((unit, fc | 0x80, 0x02)))
                else:
                    data = b"".join(bytes((w >> 8, w & 0xFF)) for w in words)
                    reply = with_crc(bytes((unit, fc, len(data))) + data)
                os.write(self.fd, reply)
