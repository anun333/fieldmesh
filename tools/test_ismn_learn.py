# SPDX-License-Identifier: Apache-2.0
"""The learned-flatline scorer, on records built to show what it counts."""
import datetime as _dt
import unittest

import ismn_learn as L
import ismn_score as S

UTC = _dt.timezone.utc
T0 = _dt.datetime(2015, 1, 1, tzinfo=UTC)


def records(hours, run_h, *, long_run_at=None, long_run_h=0):
    out, value, i = [], 0.2, 0
    while i < hours:
        if long_run_at is not None and i == long_run_at:
            for _ in range(long_run_h):
                out.append((T0 + _dt.timedelta(hours=i), value, "G"))
                i += 1
            value = round(value + 0.001, 3)
            continue
        if i % run_h == 0:
            value = round(value + 0.001, 3)
        out.append((T0 + _dt.timedelta(hours=i), value, "G"))
        i += 1
    return out


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.sensor = S.Sensor("m", "SCAN", "X", 35.0, -86.0, 0.5, 0.51, "probe")

    def test_a_long_healthy_run_after_the_first_year_is_counted_against_each(self):
        recs = records(3 * 8760, 12, long_run_at=2 * 8760, long_run_h=50)
        r = L.score(self.sensor, recs, 40 * 3600.0)
        self.assertEqual(r["learned_s"], 40 * 3600.0, "11 h runs learn 22 h; floored at the default")
        self.assertEqual((r["false_default"], r["false_learned"]), (1, 1))

    def test_too_little_after_the_first_year_is_skipped(self):
        self.assertIsNone(L.score(self.sensor, records(9000, 12), 40 * 3600.0))

    def test_no_survey_takes_the_clay_column(self):
        default, texture = L.default_for(self.sensor, {})
        self.assertIn("clay", texture)
        self.assertGreater(default, 0)


if __name__ == "__main__":
    unittest.main()
