#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The siting drill as a regression test: scored, on the real farm, with the misses."""
from __future__ import annotations

import unittest

import siting_drill as D


class TestSitingDrill(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.result = D.run(days=8.0, seed=1, disturbed=True)
        cls.events = cls.result["events"]

    def test_no_false_alarms_on_clean_probes(self):
        """The number that decides whether a farmer keeps trusting the flags."""
        clean = self.result["clean"]
        self.assertGreater(clean.assessed, 30)
        self.assertEqual(clean.flagged, 0)

    def test_an_unlogged_lift_is_caught_within_two_days(self):
        lift = self.events["bed4_shallow"]
        self.assertGreater(lift.flagged, 0)
        self.assertLessEqual(lift.first_flag_day, 2)

    def test_an_unlogged_push_is_caught_within_two_days(self):
        push = self.events["bed2_shallow"]
        self.assertGreater(push.flagged, 0)
        self.assertLessEqual(push.first_flag_day, 2)

    def test_a_lateral_move_at_the_same_depth_is_the_blind_spot(self):
        """Every bed shares the weather, so a move between beds at one depth leaves no
        thermal signature. Recall zero is the correct answer, and asserting it keeps
        anyone from later believing the check covers this."""
        self.assertEqual(self.events["bed3_deep"].flagged, 0)

    def test_a_logged_move_is_never_flagged(self):
        """The control. It also proves the simulator moves the probe with its record:
        before that fix, this exact move would have been flagged correctly."""
        self.assertEqual(self.events["bed6_shallow"].flagged, 0)


if __name__ == "__main__":
    unittest.main()
