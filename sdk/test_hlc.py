#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Hybrid logical clock behaviour (spec v0.1 §7.4)."""
from __future__ import annotations

import unittest

from hlc import Hlc, Stamp, before


class FakeClock:
    def __init__(self, ms=1000):
        self.ms = ms

    def __call__(self):
        return self.ms


class TestStamp(unittest.TestCase):
    def test_ordering_is_by_wall_then_counter(self):
        self.assertTrue(before(Stamp(5, 0), Stamp(5, 1)))
        self.assertTrue(before(Stamp(5, 9), Stamp(6, 0)))
        self.assertFalse(before(Stamp(5, 1), Stamp(5, 1)))

    def test_parse_roundtrip(self):
        for s in (Stamp(0, 0), Stamp(1_700_000_000_000, 4095)):
            self.assertEqual(Stamp.parse(str(s)), s)

    def test_rejects_negatives(self):
        with self.assertRaises(ValueError):
            Stamp(-1, 0)
        with self.assertRaises(ValueError):
            Stamp(0, -1)


class TestHlc(unittest.TestCase):
    def test_counts_within_one_millisecond(self):
        h = Hlc(clock=FakeClock(1000))
        self.assertEqual(h.now(), Stamp(1000, 0))
        self.assertEqual(h.now(), Stamp(1000, 1))
        self.assertEqual(h.now(), Stamp(1000, 2))

    def test_resets_counter_when_physical_time_advances(self):
        clock = FakeClock(1000)
        h = Hlc(clock=clock)
        h.now()
        h.now()
        clock.ms = 1001
        self.assertEqual(h.now(), Stamp(1001, 0))

    def test_never_goes_backwards_when_the_clock_does(self):
        clock = FakeClock(1000)
        h = Hlc(clock=clock)
        first = h.now()
        clock.ms = 400                   # the case §2 says to expect
        second = h.now()
        self.assertTrue(before(first, second))
        self.assertEqual(second, Stamp(1000, 1))

    def test_update_takes_the_max_and_counts(self):
        h = Hlc(clock=FakeClock(1000))
        h.now()                                      # 1000.0
        merged = h.update(Stamp(1000, 7))
        self.assertEqual(merged, Stamp(1000, 8))     # max(0,7)+1

    def test_update_adopts_a_remote_future_stamp(self):
        h = Hlc(clock=FakeClock(1000))
        merged = h.update(Stamp(5000, 3))
        self.assertEqual(merged, Stamp(5000, 4))

    def test_update_ignores_a_remote_past_stamp(self):
        h = Hlc(clock=FakeClock(1000))
        h.now()
        merged = h.update(Stamp(10, 0))
        self.assertEqual(merged, Stamp(1000, 1))

    def test_causality_survives_a_wrong_clock(self):
        """The §7.4 scenario: a phone whose clock is hours fast must not let a
        later-but-causally-earlier write win."""
        fast = Hlc(clock=FakeClock(9_000_000))     # badly wrong, far ahead
        slow = Hlc(clock=FakeClock(1_000))         # correct
        a = fast.now()                             # the fast phone writes
        b = slow.update(a)                         # the gateway learns of it, then writes
        self.assertTrue(before(a, b),
                        "a write that happened after learning of `a` must sort after it")
        c = slow.now()
        self.assertTrue(before(b, c))


if __name__ == "__main__":
    unittest.main(verbosity=2)
