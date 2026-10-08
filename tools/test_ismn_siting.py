# SPDX-License-Identifier: Apache-2.0
"""The real-soil siting tool's windowing. The archive itself is not in the repository,
so the measurement is not re-run here; what is tested is that a window holds exactly
the readings a full scan would have picked."""
import datetime as dt
import unittest

import ismn_siting as T

UTC = dt.timezone.utc


class WindowTest(unittest.TestCase):
    def setUp(self):
        start = dt.datetime(2020, 1, 1, tzinfo=UTC)
        self.series = {start + dt.timedelta(hours=h): float(h) for h in range(24 * 10)}
        self.window = T.windower({0.05: self.series})

    def test_matches_a_full_scan_including_both_ends(self):
        for hours in (0, 30, 48, 49, 100, 239, 300):
            at = dt.datetime(2020, 1, 1, tzinfo=UTC) + dt.timedelta(hours=hours)
            expected = {t: v for t, v in self.series.items() if at - T.WINDOW <= t <= at}
            self.assertEqual(self.window(0.05, at), expected, hours)

    def test_a_window_is_49_hourly_readings_when_none_are_missing(self):
        at = dt.datetime(2020, 1, 5, tzinfo=UTC)
        self.assertEqual(len(self.window(0.05, at)), 49)

    def test_before_the_record_is_empty(self):
        self.assertEqual(self.window(0.05, dt.datetime(2019, 1, 1, tzinfo=UTC)), {})


class PersistenceRuleTest(unittest.TestCase):
    """The tool's k-of-n must decide as the SDK's persistent assessment does."""

    def rows(self, verdicts, start=dt.date(2020, 1, 1)):
        return [(start + dt.timedelta(days=i), v, None) for i, v in enumerate(verdicts)]

    def test_five_of_seven(self):
        D, C, I = "displaced", "consistent", "indeterminate"
        out = T.k_of_n(self.rows([D, D, C, D, D, D, C]), 5, 7)
        self.assertEqual(out, [(dt.date(2020, 1, 7), True)])
        out = T.k_of_n(self.rows([D, D, C, D, C, D, C]), 5, 7)
        self.assertEqual(out[0][1], False)
        out = T.k_of_n(self.rows([I, I, I, D, D, D, D]), 5, 7)
        self.assertIsNone(out[0][1], "fewer than five days could decide")

    def test_a_gap_in_the_record_restarts_the_count(self):
        rows = self.rows(["displaced"] * 4) + self.rows(["displaced"] * 4, dt.date(2020, 1, 6))
        self.assertEqual(T.k_of_n(rows, 5, 7), [])

    def test_weekly_steps(self):
        week = dt.timedelta(days=7)
        rows = [(dt.date(2020, 1, 1) + i * week, "displaced", None) for i in range(4)]
        self.assertEqual(T.k_of_n(rows, 3, 4, week), [(dt.date(2020, 1, 22), True)])
        self.assertEqual(T.k_of_n(rows, 3, 4), [], "read as days, these are not consecutive")

    def test_time_to_alarm_counts_from_the_move(self):
        """Every window displaced: under 3 of 4 weekly two-week windows, the first alarm
        is at the third window wholly after the move — five weeks on."""
        week = dt.timedelta(days=7)
        rows = [(dt.date(2020, 1, 1) + i * week, "displaced", None) for i in range(70)]
        waits = T.time_to_alarm(rows, 3, 4, dt.timedelta(days=14), week)
        self.assertTrue(waits)
        self.assertEqual(set(waits), {35})

    def test_an_episode_is_a_run_of_alarmed_days(self):
        day = dt.date(2020, 1, 1)
        alarms = [True, True, None, True, False, True, True]
        decisions = [(day + dt.timedelta(days=i), a) for i, a in enumerate(alarms)]
        self.assertEqual(T.episodes(decisions), 2, "an undecided day does not split one")


if __name__ == "__main__":
    unittest.main()
