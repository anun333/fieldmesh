#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The airtime arithmetic the Q5 decision rests on (spec v0.1 §5.2)."""
from __future__ import annotations

import importlib.util
import unittest

_spec = importlib.util.spec_from_file_location(
    "q5", __file__.replace("test_q5_encoding.py", "q5_encoding.py"))
q5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(q5)


class TestTimeOnAir(unittest.TestCase):
    """Checked against the Semtech SX127x formula and widely published
    LoRaWAN airtime figures. If this arithmetic is wrong, the whole Q5
    comparison is wrong, so it is pinned rather than trusted."""

    def test_sf12_full_dr0_frame(self):
        """The load-bearing number: SF12, BW125, CR4/5, 64-byte PHY payload
        (51 app + 13 LoRaWAN), with the low-data-rate optimisation on.

            T_sym      = 2^12 / 125000           = 32.768 ms
            T_preamble = 12.25 x 32.768           = 401.408 ms
            symbols    = 8 + ceil(508/40) x 5     = 73
            T_payload  = 73 x 32.768              = 2392.064 ms
            ToA                                   = 2793.472 ms
        """
        self.assertAlmostEqual(q5.time_on_air(64, 12), 2.793472, delta=0.000001)

    def test_sf7_small_frame(self):
        """Hand-derived rather than recalled, so the expectation is checkable:

            T_sym      = 2^7 / 125000           = 1.024 ms
            T_preamble = (8 + 4.25) x 1.024      = 12.544 ms
            symbols    = 8 + ceil(224/28) x 5    = 48
            T_payload  = 48 x 1.024              = 49.152 ms
            ToA                                  = 61.696 ms
        """
        self.assertAlmostEqual(q5.time_on_air(26, 7), 0.061696, delta=0.000001)

    def test_each_step_down_in_spreading_factor_roughly_halves_airtime(self):
        for sf in (8, 9, 10):
            faster = q5.time_on_air(40, sf)
            slower = q5.time_on_air(40, sf + 1)
            self.assertLess(faster, slower)
            self.assertAlmostEqual(slower / faster, 2.0, delta=0.35)

    def test_low_data_rate_optimisation_applies_at_sf11_and_12(self):
        """Mandatory on 125 kHz at SF11/12, and it costs airtime — a jump
        bigger than the SF step alone would predict."""
        ratio_10_11 = q5.time_on_air(40, 11) / q5.time_on_air(40, 10)
        ratio_9_10 = q5.time_on_air(40, 10) / q5.time_on_air(40, 9)
        self.assertGreater(ratio_10_11, ratio_9_10)

    def test_airtime_grows_with_payload(self):
        self.assertLess(q5.time_on_air(20, 12), q5.time_on_air(60, 12))

    def test_duty_cycle_budget_is_one_percent_of_an_hour(self):
        self.assertEqual(q5.DUTY_CYCLE_BUDGET_S, 36.0)


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
