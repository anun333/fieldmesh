#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""LoRa airtime and the duty-cycle budget (spec v0.1 §5.2).

Every claim about what a node can send rests on this arithmetic, so both reference
points are hand-derived rather than recalled.
"""
from __future__ import annotations

import unittest

import airtime as A


class TestTimeOnAir(unittest.TestCase):
    def test_sf12_full_dr0_frame(self):
        """The load-bearing number: SF12, BW125, CR4/5, 64-byte PHY payload
        (51 app + 13 LoRaWAN), with the low-data-rate optimisation on.

            T_sym      = 2^12 / 125000           = 32.768 ms
            T_preamble = 12.25 x 32.768           = 401.408 ms
            symbols    = 8 + ceil(508/40) x 5     = 73
            T_payload  = 73 x 32.768              = 2392.064 ms
            ToA                                   = 2793.472 ms
        """
        self.assertAlmostEqual(A.time_on_air(64, 12), 2.793472, delta=0.000001)

    def test_sf7_small_frame(self):
        """T_sym 1.024 ms, preamble 12.544 ms, 48 symbols, 49.152 ms payload."""
        self.assertAlmostEqual(A.time_on_air(26, 7), 0.061696, delta=0.000001)

    def test_each_step_down_in_spreading_factor_roughly_halves_airtime(self):
        for sf in (8, 9, 10):
            faster = A.time_on_air(40, sf)
            slower = A.time_on_air(40, sf + 1)
            self.assertLess(faster, slower)
            self.assertAlmostEqual(slower / faster, 2.0, delta=0.35)

    def test_low_data_rate_optimisation_applies_at_sf11_and_12(self):
        """Mandatory on 125 kHz at SF11/12, and it costs airtime — a jump bigger
        than the spreading factor alone would predict."""
        ratio_10_11 = A.time_on_air(40, 11) / A.time_on_air(40, 10)
        ratio_9_10 = A.time_on_air(40, 10) / A.time_on_air(40, 9)
        self.assertGreater(ratio_10_11, ratio_9_10)

    def test_airtime_grows_with_payload(self):
        self.assertLess(A.time_on_air(20, 12), A.time_on_air(60, 12))

    def test_frame_airtime_adds_the_lorawan_overhead(self):
        self.assertAlmostEqual(A.frame_airtime(51, dr=0), A.time_on_air(64, 12))

    def test_the_eu868_tables(self):
        self.assertEqual(A.MAX_APP_PAYLOAD[0], 51)
        self.assertEqual(A.MAX_APP_PAYLOAD[3], 115)
        self.assertEqual(A.SF_FOR_DR[0], 12)
        self.assertEqual(A.SF_FOR_DR[5], 7)
        self.assertEqual(A.LORAWAN_OVERHEAD, 13)

    def test_the_budget_is_one_percent_of_an_hour(self):
        self.assertEqual(A.DUTY_CYCLE_BUDGET_S, 36.0)


class TestDutyCycle(unittest.TestCase):
    """§5.2's limit is a radio regulation, so `allows` is a precondition."""

    def test_an_empty_budget_is_fully_available(self):
        d = A.DutyCycle()
        self.assertEqual(d.used(0.0), 0.0)
        self.assertEqual(d.remaining(0.0), 36.0)

    def test_recording_consumes_the_budget(self):
        d = A.DutyCycle()
        d.record(2.8, now=0.0)
        self.assertAlmostEqual(d.used(1.0), 2.8)
        self.assertAlmostEqual(d.remaining(1.0), 33.2)

    def test_it_refuses_once_the_budget_is_spent(self):
        d = A.DutyCycle()
        for i in range(12):
            d.record(2.8, now=float(i))
        self.assertFalse(d.allows(2.8, now=12.0),
                         "12 x 2.8 s is 33.6 s; another 2.8 would exceed 36")
        self.assertTrue(d.allows(2.0, now=12.0))

    def test_the_window_rolls(self):
        d = A.DutyCycle()
        d.record(30.0, now=0.0)
        self.assertFalse(d.allows(10.0, now=100.0))
        self.assertTrue(d.allows(10.0, now=3601.0),
                        "an hour later the old transmission no longer counts")

    def test_a_custom_budget_is_respected(self):
        """A 0.1% sub-band, or a network fair-use policy stricter than the law."""
        d = A.DutyCycle(budget_s=3.6)
        self.assertTrue(d.allows(2.8, now=0.0))
        d.record(2.8, now=0.0)
        self.assertFalse(d.allows(2.8, now=1.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
