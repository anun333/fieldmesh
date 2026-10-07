#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""UUIDv7 conformance and the monotonicity §3.3 depends on."""
from __future__ import annotations

import random
import unittest
import uuid

import ids


class FakeClock:
    def __init__(self, ms=1_700_000_000_000):
        self.ms = ms

    def __call__(self):
        return self.ms


class TestLayout(unittest.TestCase):
    def test_version_and_variant_are_rfc9562(self):
        u = ids.uuid7()
        self.assertEqual(u.version, 7)
        self.assertEqual(u.variant, uuid.RFC_4122)
        self.assertEqual(u.bytes[6] & 0xF0, 0x70, "version nibble")
        self.assertEqual(u.bytes[8] & 0xC0, 0x80, "variant bits")

    def test_timestamp_is_big_endian_millis_in_the_first_48_bits(self):
        clock = FakeClock(0x0123456789AB)
        g = ids.Uuid7Generator(clock=clock)
        self.assertEqual(ids.uuid7_time(g()), 0x0123456789AB)

    def test_uuid7_time_rejects_other_versions(self):
        with self.assertRaises(ValueError):
            ids.uuid7_time(uuid.uuid4())

    def test_is_uuid7(self):
        self.assertTrue(ids.is_uuid7(ids.uuid7()))
        self.assertFalse(ids.is_uuid7(uuid.uuid4()))

    def test_randomness_fills_rand_b(self):
        clock = FakeClock()
        g = ids.Uuid7Generator(clock=clock)
        tails = {g().bytes[9:16] for _ in range(50)}
        self.assertGreater(len(tails), 45, "rand_b should not repeat")


class TestMonotonicity(unittest.TestCase):
    def test_strictly_increasing_within_one_millisecond(self):
        g = ids.Uuid7Generator(clock=FakeClock())
        made = [g() for _ in range(500)]
        ints = [u.int for u in made]
        self.assertEqual(ints, sorted(ints))
        self.assertEqual(len(set(ints)), len(ints))

    def test_strictly_increasing_across_advancing_time(self):
        clock = FakeClock()
        g = ids.Uuid7Generator(clock=clock)
        made = []
        for _ in range(40):
            made.append(g())
            clock.ms += 1
        ints = [u.int for u in made]
        self.assertEqual(ints, sorted(ints))

    def test_a_backwards_clock_cannot_produce_a_lower_id(self):
        clock = FakeClock()
        g = ids.Uuid7Generator(clock=clock)
        before = g()
        clock.ms -= 10_000          # NTP step, or an RTC with a dying cell
        after = g()
        self.assertGreater(after.int, before.int,
                           "the generator must hold its own monotonic floor")

    def test_counter_overflow_borrows_a_millisecond(self):
        clock = FakeClock()
        g = ids.Uuid7Generator(clock=clock)
        made = [g() for _ in range(5000)]   # > 4095 in one ms
        ints = [u.int for u in made]
        self.assertEqual(ints, sorted(ints))
        self.assertEqual(len(set(ints)), len(ints))
        self.assertGreater(ids.uuid7_time(made[-1]), ids.uuid7_time(made[0]))

    def test_deterministic_with_a_pinned_rng(self):
        def make():
            return ids.Uuid7Generator(clock=FakeClock(), rng=random.Random(7))
        self.assertEqual([u.int for u in [make()() for _ in range(1)]],
                         [u.int for u in [make()() for _ in range(1)]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
