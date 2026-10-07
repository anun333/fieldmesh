#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The encodings compared for Q5 (spec v0.1 §5.2).

The airtime arithmetic these rest on moved to `sdk/airtime.py`, where a
link driver can use it at runtime; its tests are `sdk/test_airtime.py`.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import q5_encoding as q5  # noqa: E402


class TestEncodings(unittest.TestCase):
    def test_every_candidate_produces_bytes(self):
        for name, fn in q5.CANDIDATES:
            with self.subTest(name):
                self.assertIsInstance(fn(4, True), bytes)

    def test_hand_packed_is_the_floor(self):
        floor = len(q5.hand_packed(8, True))
        for name, fn in q5.CANDIDATES:
            with self.subTest(name):
                self.assertGreaterEqual(len(fn(8, True)), floor)

    def test_hand_packed_size_is_exactly_the_documented_layout(self):
        """1 version + 4 node + 2 boot + 2 seq + 2 base_age + n x 5."""
        for n in (1, 4, 8):
            self.assertEqual(len(q5.hand_packed(n, True)), 11 + 5 * n)

    def test_omitting_the_node_id_saves_four_bytes(self):
        self.assertEqual(len(q5.hand_packed(8, True))
                         - len(q5.hand_packed(8, False)), 4)

    def test_cbor_maps_cannot_carry_even_one_reading_at_dr0(self):
        """The measurement's sharpest result: named keys are not merely
        wasteful at SF12, they are unusable."""
        self.assertGreater(len(q5.cbor_maps(1, True)), 51)

    def test_flat_packing_beats_nested_arrays(self):
        self.assertLess(len(q5.cbor_packed_flat(8, True)),
                        len(q5.cbor_packed(8, True)))

    def test_cbor_packed_fits_dr0_at_six_readings(self):
        self.assertLessEqual(len(q5.cbor_packed_flat(6, True)), 51)
        self.assertGreater(len(q5.cbor_packed_flat(8, True)), 51)

    def test_protobuf_round_trips(self):
        """Sizing comes from the real library, so the schema must be valid."""
        blob = q5.protobuf(8, True)
        cls = q5._protobuf_class()
        back = cls()
        back.ParseFromString(blob)
        self.assertEqual(back.seq, q5.SEQ)
        self.assertEqual(len(back.readings), 8)
        self.assertEqual(back.readings[3].value, q5.VALUES[3])

    def test_senml_needs_custom_labels_to_be_usable_and_they_cost_bytes(self):
        """RFC 8428 requires a label ending in `_` to be understood or the
        record rejected, so the interoperability that made SenML attractive
        does not survive carrying boot and seq."""
        self.assertGreater(len(q5.senml_cbor_extended(8, True)),
                           len(q5.senml_cbor(8, True)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
