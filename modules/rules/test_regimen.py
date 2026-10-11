#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regimens (Q10): Starlark plans that cannot touch the world, CEL checks, and runs kept
in the log."""
from __future__ import annotations

import datetime as _dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))

try:
    import celpy  # noqa: F401
    import starlark  # noqa: F401
    HAVE_BOTH = True
except ImportError:
    HAVE_BOTH = False

from log import Log  # noqa: E402

import regimen as G  # noqa: E402
import rules as R  # noqa: E402

MIN = _dt.timedelta(minutes=1)
T0 = _dt.datetime(2026, 7, 14, 9, tzinfo=_dt.timezone.utc)
BED = "0192aaaa-0000-7000-8000-000000000001"

SOAK = '''
def plan(ctx, params):
    if ctx["need_mm"] < params["min_mm"]:
        return []
    return [
        say("rules.test.water", subject = ctx["bed"], label = "bed", mm = ctx["need_mm"]),
        wait(ctx["need_mm"] / params["mm_per_hour"] * 60 + params["soak_min"]),
        check("rise >= expected", "rules.test.dry", subject = ctx["bed"], label = "bed",
              show = ["rise"], expected = ctx["need_mm"] / 300.0),
    ]
'''


def regimen(source=SOAK, **params):
    return G.Regimen("soak-check", "1", source,
                     {"min_mm": 5.0, "mm_per_hour": 12.0, "soak_min": 60.0, **params})


@unittest.skipUnless(HAVE_BOTH, "starlark-pyo3 and cel-python (modules/rules/requirements.txt)")
class TestPlans(unittest.TestCase):
    def test_a_plan_is_steps_and_the_same_every_time(self):
        ctx = {"need_mm": 18.0, "bed": BED}
        steps = G.plan(regimen(), ctx)
        self.assertEqual([s["kind"] for s in steps], ["say", "wait", "check"])
        self.assertEqual(steps[1]["minutes"], 150.0)
        self.assertEqual(steps[2]["params"], {"expected": 0.06})
        self.assertEqual(G.plan(regimen(), ctx), steps)
        self.assertEqual(G.plan(regimen(), {"need_mm": 2.0, "bed": BED}), [])

    def test_a_regimen_cannot_reach_the_world_or_run_for_ever(self):
        for body in ('open("/etc/passwd")', 'load("x.star", "y")', "import os",
                     "while True:\n        pass", "return plan(ctx, params)",
                     "return [x for x in range(100000000)]", 'return time.now()'):
            source = f"def plan(ctx, params):\n    {body}\n"
            with self.assertRaises(G.RegimenError, msg=body):
                G.plan(regimen(source), {})

    def test_what_is_not_a_plan_is_refused(self):
        bad = {"not a list": "return {}",
               "a step of no kind": 'return [{"kind": "act"}]',
               "a key that is not one": 'return [say("Water it")]',
               "a wait into the past": "return [wait(-5)]",
               "a wait of a month": "return [wait(60 * 24 * 30)]",
               "a condition that is not CEL": 'return [check("rise >=", "rules.test.dry")]',
               "a subject that is not text": 'return [say("rules.test.water", subject = 3)]',
               "too many steps": 'return [wait(1) for i in range(101)]'}
        for why, body in bad.items():
            with self.assertRaises(G.RegimenError, msg=why):
                G.plan(regimen(f"def plan(ctx, params):\n    {body}\n"), {})


@unittest.skipUnless(HAVE_BOTH, "starlark-pyo3 and cel-python (modules/rules/requirements.txt)")
class TestRuns(unittest.TestCase):
    def setUp(self):
        self.log = Log()
        self.runner = G.Runner(self.log)
        self.rise = 0.0
        self.ctx = lambda subject, run: {"rise": self.rise}

    def test_each_step_is_a_decision_when_it_falls_due(self):
        start = self.runner.start(regimen(), {"need_mm": 18.0, "bed": BED}, T0, subject=BED)
        self.assertEqual(start.payload["step"], "start")
        self.assertEqual(len(start.payload["plan"]), 3)
        self.assertEqual(start.payload["regimen_sha256"], regimen().sha256)
        [say] = self.runner.tick(T0, self.ctx)
        self.assertTrue(say.payload["alert"])
        self.assertEqual(say.payload["message"],
                         {"key": "rules.test.water", "params": {"mm": 18.0}, "subject_param": "bed"})
        self.assertEqual(self.runner.tick(T0 + 149 * MIN, self.ctx), [], "not before its time")
        self.rise = 0.01
        [check] = self.runner.tick(T0 + 150 * MIN, self.ctx)
        self.assertTrue(check.payload["alert"], "the water did not arrive")
        self.assertEqual(check.payload["message"]["params"], {"expected": 0.06, "rise": 0.01})
        self.assertEqual(check.payload["topic"], start.payload["topic"], "one question per run")
        self.assertTrue(self.runner.runs[start.payload["regimen_run"]].finished)
        self.assertEqual(self.runner.tick(T0 + 300 * MIN, self.ctx), [])

    def test_a_check_that_passes_says_nothing_to_anyone(self):
        self.runner.start(regimen(), {"need_mm": 18.0, "bed": BED}, T0, subject=BED)
        self.rise = 0.07
        written = self.runner.tick(T0 + 200 * MIN, self.ctx)
        self.assertEqual([e.payload["alert"] for e in written], [True, False])
        self.assertIsNone(written[-1].payload["message"])

    def test_a_runner_that_restarts_carries_on_from_the_log_and_writes_nothing_twice(self):
        self.runner.start(regimen(), {"need_mm": 18.0, "bed": BED}, T0, subject=BED)
        self.runner.tick(T0, self.ctx)
        again = G.Runner(self.log)
        self.assertIsNone(again.start(regimen(), {"need_mm": 18.0, "bed": BED}, T0, subject=BED))
        # The plan comes from the log, not from planning again on what has changed since.
        self.assertEqual(len(again.tick(T0 + 200 * MIN, self.ctx)), 1)
        self.assertEqual(sum(1 for e in self.log.events if e.kind == "decision"), 3)

    def test_nothing_to_do_starts_nothing(self):
        self.assertIsNone(self.runner.start(regimen(), {"need_mm": 1.0, "bed": BED}, T0))
        self.assertEqual(self.log.events, ())

    def test_its_message_is_said_by_any_renderer(self):
        from model import Label
        from project import State
        from uuid import UUID
        from ids import uuid7
        import i18n
        d = os.path.join(os.path.dirname(HERE), "soilwater", "packs")
        i18n.register(d, "soilwater")
        state = State()
        state.add(Label(uuid7(), UUID(BED), "cama 3", T0 - 60 * MIN, language="es"))
        decision = {"subject": BED, "message": {
            "key": "soilwater.regimen.no_response", "subject_param": "bed",
            "params": {"rise_percent": 0.4, "mm": 18.0, "expected_percent": 6.0}}}
        self.assertIn("Las sondas de cama 3 casi no muestran agua nueva", R.render(decision, "es", state))


if __name__ == "__main__":
    unittest.main()
