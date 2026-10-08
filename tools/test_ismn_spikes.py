# SPDX-License-Identifier: Apache-2.0
"""The spike and jump detectors on series whose answer is known."""
import datetime as dt
import unittest

import ismn_spikes as T

T0 = dt.datetime(2020, 6, 1, tzinfo=dt.timezone.utc)


def series(values, every_h=1):
    return [(T0 + dt.timedelta(hours=every_h * i), v, "G") for i, v in enumerate(values)]


class SpikeTest(unittest.TestCase):

    def test_out_and_back_in_one_sample_is_a_spike(self):
        found = T.detect(series([0.20, 0.20, 0.20, 0.31, 0.20, 0.20]))
        self.assertEqual(found[("spike", 0.03)], {3})
        self.assertEqual(found[("spike", 0.05)], {3})

    def test_a_dropout_is_a_spike_too(self):
        found = T.detect(series([0.27, 0.27, 0.10, 0.27, 0.27]))
        self.assertEqual(found[("spike", 0.03)], {2})

    def test_rain_rises_and_holds(self):
        """A wetting front: a fast rise, then slow drainage. Not a spike."""
        found = T.detect(series([0.15, 0.15, 0.26, 0.27, 0.265, 0.26, 0.255]))
        self.assertEqual(found[("spike", 0.03)], set())

    def test_the_way_back_from_a_spike_is_not_a_drop(self):
        found = T.detect(series([0.20, 0.20, 0.31, 0.20, 0.20]))
        self.assertEqual(found[("drop", 0.03)], set())

    def test_no_decision_across_a_long_gap(self):
        rows = series([0.20, 0.20]) + [(T0 + dt.timedelta(hours=6), 0.31, "G"),
                                       (T0 + dt.timedelta(hours=7), 0.20, "G")]
        self.assertEqual(T.detect(rows)[("spike", 0.03)], set())

    def test_sampling_every_three_hours_still_decides(self):
        found = T.detect(series([0.20, 0.20, 0.31, 0.20, 0.20], every_h=3))
        self.assertEqual(found[("spike", 0.03)], {2})


class DropTest(unittest.TestCase):

    def test_a_fall_from_a_steady_level(self):
        found = T.detect(series([0.30, 0.30, 0.30, 0.30, 0.22, 0.22, 0.22]))
        self.assertEqual(found[("stable drop", 0.05)], {4})
        self.assertEqual(found[("drop", 0.05)], {4})

    def test_drainage_just_after_rain_is_not_a_stable_drop(self):
        """Mammoth Cave, 5 cm, 2025-12-19: 0.286, 0.334, 0.430, 0.370 — a wetting front
        passing, rated good, and draining 0.06 in an hour."""
        found = T.detect(series([0.286, 0.334, 0.430, 0.370, 0.335, 0.322]))
        self.assertIn(3, found[("drop", 0.05)])
        self.assertEqual(found[("stable drop", 0.05)], set())

    def test_the_drop_cap_scales_with_the_gap_up_to_three_hours(self):
        found = T.detect(series([0.30, 0.30, 0.22, 0.22], every_h=2))
        self.assertEqual(found[("stable drop", 0.05)], set(), "0.08 over 2 h is 0.04/h")
        found = T.detect(series([0.30, 0.30, 0.18, 0.18], every_h=2))
        self.assertEqual(found[("stable drop", 0.05)], {2})


class EventTest(unittest.TestCase):

    def test_flags_two_apart_are_one_event(self):
        rows = [(None, 0.1, f) for f in ("G", "D06", "G", "D06", "G", "G", "G", "D06")]
        self.assertEqual(T.events(rows, "D06"), [[1, 3], [7, 7]])

    def test_a_flag_among_several(self):
        rows = [(None, 0.1, f) for f in ("G", "D06,D03", "G")]
        self.assertEqual(T.events(rows, "D06"), [[1, 1]])

    def test_decimation_keeps_the_hours_it_names(self):
        rows = series([0.1] * 7)
        self.assertEqual([r[0].hour for r in T.decimate(rows, 3)], [0, 3, 6])


if __name__ == "__main__":
    unittest.main()
