#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The power model behind the per-datastream sampling guidance (spec §3.1, §5.2)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import power_budget as pb  # noqa: E402

SOIL_HOURLY = pb.Channel("soil", 3600, 3600)
SOIL_5MIN = pb.Channel("soil", 300, 3600)
TROUGH = pb.Channel("trough", 300, 300)


class TestTransmitSchedule(unittest.TestCase):
    def test_the_tightest_latency_sets_the_interval(self):
        """A trough float that must be known within five minutes forces the radio
        awake every five minutes however sleepy everything else on the node is."""
        interval, _ = pb.transmit_schedule([SOIL_HOURLY, TROUGH], cap=6)
        self.assertEqual(interval, 300)

    def test_a_sleepy_node_transmits_on_its_own_schedule(self):
        interval, readings = pb.transmit_schedule([SOIL_HOURLY], cap=6)
        self.assertEqual(interval, 3600)
        self.assertEqual(readings, 1)

    def test_readings_per_transmit_counts_every_channel(self):
        _, readings = pb.transmit_schedule([SOIL_5MIN, TROUGH], cap=6)
        self.assertEqual(readings, 2, "5-minute window, two channels")

    def test_a_fast_sampler_with_slow_latency_accumulates(self):
        _, readings = pb.transmit_schedule([SOIL_5MIN], cap=6)
        self.assertEqual(readings, 12, "12 five-minute samples in an hour")


class TestWhereTheEnergyGoes(unittest.TestCase):
    def test_transmit_dominates_every_configuration(self):
        for label, chans in (("sleepy", [SOIL_HOURLY]), ("urgent", [TROUGH]),
                             ("mixed", [SOIL_HOURLY, TROUGH])):
            with self.subTest(label):
                b = pb.node_budget(chans)
                self.assertGreater(b["tx_mah"] / b["total_mah"], 0.80)

    def test_reading_a_sensor_is_a_rounding_error(self):
        """So slowing a sensor down to spare the SENSOR saves nothing."""
        for chans in ([SOIL_HOURLY], [TROUGH], [SOIL_5MIN, TROUGH]):
            b = pb.node_budget(chans)
            self.assertLess(b["sample_mah"] / b["total_mah"], 0.03)

    def test_sleep_matters_on_a_sleepy_node_and_not_on_a_busy_one(self):
        sleepy = pb.node_budget([SOIL_HOURLY])
        busy = pb.node_budget([TROUGH])
        self.assertGreater(sleepy["sleep_mah"] / sleepy["total_mah"], 0.10)
        self.assertLess(busy["sleep_mah"] / busy["total_mah"], 0.03)


class TestTheCounterintuitiveResults(unittest.TestCase):
    """These three are the whole point, so they are pinned."""

    def test_sampling_more_often_costs_through_the_radio_not_the_probe(self):
        slow = pb.node_budget([SOIL_HOURLY])
        fast = pb.node_budget([SOIL_5MIN])
        self.assertGreater(fast["total_mah"], 2 * slow["total_mah"],
                           "12x the readings is not free")
        sensor_share = (fast["sample_mah"] - slow["sample_mah"]) / \
                       (fast["total_mah"] - slow["total_mah"])
        self.assertLess(sensor_share, 0.05,
                        "and almost none of the extra cost is the probe")
        self.assertGreater(fast["msgs_per_tx"], slow["msgs_per_tx"],
                           "it is the extra message that costs")

    def test_an_extra_reading_that_fits_an_existing_message_is_nearly_free(self):
        one = pb.node_budget([SOIL_HOURLY, TROUGH])
        both = pb.node_budget([SOIL_5MIN, TROUGH])
        self.assertEqual(one["msgs_per_tx"], both["msgs_per_tx"])
        self.assertLess(both["total_mah"] / one["total_mah"] - 1, 0.02)

    def test_co_location_costs_an_order_of_magnitude(self):
        """The biggest single factor, and the one that is a placement decision
        rather than a configuration one."""
        alone = pb.node_budget([SOIL_HOURLY])
        shared = pb.node_budget([SOIL_HOURLY, TROUGH])
        self.assertGreater(shared["total_mah"] / alone["total_mah"], 8.0)
        self.assertGreater(alone["days"], 1000)
        self.assertLess(shared["days"], 200)


class TestSensitivity(unittest.TestCase):
    def test_a_faster_data_rate_helps_a_lot(self):
        """Airtime, not payload, so a better link is worth more than any
        configuration choice here."""
        slow = pb.node_budget([TROUGH], dr=0)
        fast = pb.node_budget([TROUGH], dr=5)
        self.assertGreater(fast["days"] / slow["days"], 5.0)

    def test_a_worse_sleep_current_ruins_a_sleepy_node_only(self):
        good = pb.node_budget([SOIL_HOURLY], sleep_ua=10)
        bad = pb.node_budget([SOIL_HOURLY], sleep_ua=150)   # a careless ESP32
        self.assertLess(bad["days"] / good["days"], 0.5)
        busy_good = pb.node_budget([TROUGH], sleep_ua=10)
        busy_bad = pb.node_budget([TROUGH], sleep_ua=150)
        self.assertGreater(busy_bad["days"] / busy_good["days"], 0.8)

    def test_mah_helper(self):
        self.assertAlmostEqual(pb.mah(120.0, 3600.0), 120.0)
        self.assertAlmostEqual(pb.mah(120.0, 1.8), 0.06)


if __name__ == "__main__":
    unittest.main(verbosity=2)
