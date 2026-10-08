#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The scoring core, on synthetic series. The reader comes after the real download
has been inspected — the flag vocabulary is provisional until then."""
from __future__ import annotations

import datetime as _dt
import unittest

import ismn_score as S

UTC = _dt.timezone.utc
T0 = _dt.datetime(2024, 6, 1, tzinfo=UTC)


def hourly(values_and_flags):
    return [(T0 + _dt.timedelta(hours=i), v, f)
            for i, (v, f) in enumerate(values_and_flags)]


class TestFamilies(unittest.TestCase):

    def test_known_flags_map_to_families(self):
        self.assertEqual(S.families("G"), {"good"})
        self.assertEqual(S.families("C02"), {"range"})
        self.assertEqual(S.families("D06,D08"), {"spike", "break"})

    def test_an_unknown_flag_is_visible_not_counted_as_good(self):
        self.assertEqual(S.families("Z99"), {"unknown:Z99"})
        self.assertEqual(S.families(""), {"unknown:<none>"})


class TestScoring(unittest.TestCase):

    def test_an_out_of_range_reading_isms_flags_is_caught_by_ours(self):
        rows = hourly([(0.25, "G")] * 5 + [(0.70, "C02")] + [(0.25, "G")] * 3)
        score = S.score_series(rows)
        self.assertEqual(score.by_family["range"], 1)
        self.assertEqual(score.agreement("range"), 1.0)

    def test_at_hourly_sampling_the_rate_check_cannot_see_a_spike(self):
        """A measured limitation of our check, found by writing this test — not a
        property of the scorer.

        The rate limit is 0.00015/s, derived from drip irrigation at 15-minute sampling.
        ISMN is hourly, and an hour at that rate permits a jump of 0.54 m3/m3: nearly
        the whole physical range. A spike from 0.25 to 0.40 passes. A per-second limit
        times an interval grows without bound, while the thing that is physically
        bounded is the size of one jump — the same trap `flat_n` fell into, reversed.
        Recorded as Q23 rather than fixed, because a cap must still allow a storm over
        a long gap.
        """
        rows = hourly([(0.25, "G")] * 5 + [(0.40, "D06")] + [(0.25, "G")] * 3)
        self.assertEqual(S.score_series(rows).agreement("spike"), 0.0)
        self.assertAlmostEqual(S.OUR_THRESHOLDS["max_rate_per_s"] * 3600, 0.54)

    def test_at_the_sampling_rate_it_was_derived_for_it_does(self):
        rows = [(T0 + _dt.timedelta(minutes=15 * i), v, f) for i, (v, f) in
                enumerate([(0.25, "G")] * 5 + [(0.40, "D06")] + [(0.25, "G")] * 3)]
        self.assertEqual(S.score_series(rows, interval_s=900.0).agreement("spike"),
                         1.0)

    def test_our_flags_on_readings_ismn_calls_good_are_counted(self):
        """Disagreement, not error: reported as such."""
        rows = hourly([(0.25, "G")] * 5 + [(0.50, "G")])
        score = S.score_series(rows)
        self.assertGreater(sum(score.ours_on_good.values()), 0)

    def test_ancillary_flags_have_no_counterpart_and_score_nothing(self):
        """D01-D05 use soil temperature and precipitation we do not have in a single
        series; they are counted but never scored as misses."""
        rows = hourly([(0.25, "G")] * 3 + [(0.26, "D04")])
        score = S.score_series(rows)
        self.assertEqual(score.by_family["ancillary"], 1)
        self.assertEqual(score.caught["ancillary"], 0)

    def test_a_reading_with_no_value_is_skipped(self):
        rows = hourly([(0.25, "G"), (None, "M"), (0.25, "G")])
        self.assertEqual(S.score_series(rows).readings, 2)


if __name__ == "__main__":
    unittest.main()


class TestReader(unittest.TestCase):
    """The format as the real archive has it, verified on 2026-10-08."""

    HEADER = ("SCAN SCAN Allen_Farms 35.07470 -86.89380 215.0 0.0508 0.0508 "
              "'Stevens-Hydraprobe-Analog'")

    def test_the_header_is_read_including_a_quoted_instrument(self):
        sensor = S.parse_header(self.HEADER, "SCAN/Allen_Farms/x.stm")
        self.assertEqual((sensor.network, sensor.station), ("SCAN", "Allen_Farms"))
        self.assertEqual((sensor.lat, sensor.lon), (35.0747, -86.8938))
        self.assertEqual(sensor.depth_to, 0.0508)
        self.assertEqual(sensor.instrument, "Stevens-Hydraprobe-Analog")

    def test_records_are_utc_with_combined_flags_kept_whole(self):
        rows = list(S.parse_records(["2003/06/04 00:00 0.349 G V",
                                     "2003/06/04 01:00 0.452 C03,D02 V"]))
        self.assertEqual(rows[0][0], _dt.datetime(2003, 6, 4, tzinfo=UTC))
        self.assertEqual(rows[1][1:], (0.452, "C03,D02"))
        self.assertEqual(S.families(rows[1][2]), {"range", "ancillary"})

    def test_a_missing_value_is_none_not_a_number(self):
        rows = list(S.parse_records(["2003/06/04 00:00 -9999 M V"]))
        self.assertIsNone(rows[0][1])

    def test_a_malformed_line_raises_rather_than_being_skipped(self):
        """A format surprise must be found, not averaged away."""
        with self.assertRaises(ValueError):
            list(S.parse_records(["2003/06/04 00:00"]))
