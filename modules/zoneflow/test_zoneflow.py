#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Irrigation zone flow: the heads' arithmetic, the usual flow learned from normal runs,
decisions raised and cleared, and the drill on simulated seasons."""
from __future__ import annotations

import datetime as _dt
import os
import statistics
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))

try:
    import celpy  # noqa: F401
    HAVE_CEL = True
except ImportError:
    HAVE_CEL = False

import fixtures as FX  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from log import Log  # noqa: E402
from model import Label  # noqa: E402
from project import State  # noqa: E402

import zoneflow as Z  # noqa: E402

UTC = _dt.timezone.utc
T0 = _dt.datetime(2026, 7, 1, 10, tzinfo=UTC)
DAY = _dt.timedelta(days=1)


def lawn(**kw):
    return Z.Zone(uuid7(), uuid7(), heads=Z.LAWN, **kw)


class TestTheHeads(unittest.TestCase):

    def test_a_lawn_zone_of_six_halves_and_two_quarters_gives_12_94_gpm(self):
        self.assertAlmostEqual(Z.expected_gpm(lawn()), 12.94, places=2)

    def test_a_nozzle_scales_with_the_root_of_pressure_and_an_emitter_does_not(self):
        """Rain Bird's chart gives the 15F 2.60 gpm at 15 psi: √(15/30) of 3.70 is 2.62."""
        self.assertAlmostEqual(Z.head_gpm("rainbird-mpr-15F", 15.0), 2.60, delta=0.03)
        self.assertEqual(Z.head_gpm("xeribug-1.0", 15.0), Z.head_gpm("xeribug-1.0", 50.0))

    def test_a_shortfall_is_sized_in_the_zones_own_heads(self):
        zone = lawn()
        self.assertEqual(Z.size_in_heads(zone, 1.85), (1, "rainbird-mpr-15H"))
        self.assertEqual(Z.size_in_heads(zone, 0.92), (1, "rainbird-mpr-15Q"))
        self.assertEqual(Z.size_in_heads(zone, 3.70), (2, "rainbird-mpr-15H"))
        self.assertIsNone(Z.size_in_heads(zone, 0.30), "less than half the smallest head")

    def test_an_unknown_head_or_a_wild_tolerance_is_refused(self):
        with self.assertRaises(ValueError):
            Z.Zone(uuid7(), uuid7(), heads=(("hunter-mp-2000", 3),))
        with self.assertRaises(ValueError):
            lawn(tolerance=0.8)


class TestTheUsualFlow(unittest.TestCase):

    def test_a_clogged_half_head_is_low_sized_and_stays_low_until_fixed(self):
        zone = lawn()
        flows = [12.9, 13.0, 12.8, 12.95, 13.05, 12.9] + [11.1] * 8
        ctx = Z.judge_runs(flows, zone)
        self.assertEqual(ctx["low_runs"], 8.0, "a lasting clog never becomes the usual")
        self.assertAlmostEqual(ctx["usual_gpm"], 12.92, delta=0.05)
        self.assertEqual((ctx["sized"], ctx["heads"], ctx["head_kind"], ctx["head_size"]),
                         (True, 1.0, Z.KINDS["spray-half"], 15.0))
        self.assertEqual(Z.alerts(ctx, zone), {"low"})
        fixed = Z.judge_runs(flows + [12.9], zone)
        self.assertEqual(Z.alerts(fixed, zone), set())

    def test_one_run_out_is_not_enough(self):
        zone = lawn()
        self.assertEqual(Z.alerts(Z.judge_runs([12.9, 13.0, 12.8, 12.95, 11.0], zone), zone), set())

    def test_a_broken_head_is_high(self):
        zone = lawn()
        ctx = Z.judge_runs([12.9, 13.0, 12.8, 12.95, 21.0, 21.2], zone)
        self.assertEqual(Z.alerts(ctx, zone), {"high"})

    def test_a_slow_drift_becomes_the_usual_but_not_what_the_heads_should_give(self):
        zone = Z.Zone(uuid7(), uuid7(), heads=Z.DRIP)
        flows = [Z.expected_gpm(zone) * (1 - 0.01 * n) for n in range(30)]
        ctx = Z.judge_runs(flows, zone)
        self.assertEqual(ctx["low_runs"], 0.0)
        self.assertEqual(Z.alerts(ctx, zone), {"drift"})

    def test_with_too_few_runs_the_inventory_stands_in(self):
        zone = lawn()
        ctx = Z.judge_runs([11.0, 11.0], zone)
        self.assertFalse(ctx["learned"])
        self.assertEqual(ctx["usual_gpm"], 12.94)
        self.assertEqual(Z.alerts(ctx, zone), {"low"})


class TestTheDrill(unittest.TestCase):
    """A hundred simulated seasons of forty runs: the supply pressure wandering ±10%, the
    meter ±2% (`zoneflow.drill`)."""

    @classmethod
    def setUpClass(cls):
        cls.r = Z.drill(100)

    def test_healthy_zones_raise_nothing(self):
        self.assertEqual(self.r["false_alert_runs"], 0)

    def test_a_clogged_half_head_a_rotor_and_a_broken_head_are_always_seen(self):
        for name in ("half_head", "rotor", "broken"):
            caught = [x for x in self.r[name] if x is not None]
            self.assertEqual(len(caught), 100, name)
            self.assertLessEqual(statistics.median(caught), 1, name)

    def test_a_quarter_head_is_at_the_edge(self):
        caught = sum(x is not None for x in self.r["quarter_head"])
        self.assertLess(caught, 50)

    def test_drip_silting_is_seen_in_weeks(self):
        caught = [x for x in self.r["drip_drift"] if x is not None]
        self.assertEqual(len(caught), 100)
        self.assertLessEqual(max(caught), 25)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestDecisions(unittest.TestCase):
    """Runs as an OpenSprinkler station's flow lands in the log, through the monitor."""

    def setUp(self):
        self.state = State()
        self.flow = FX.raw_datastream(unit="[gal_us]/min", observed_property=V.FLOW_RATE)
        self.state.add(self.flow)
        self.zone = Z.Zone(uuid7(), self.flow.id, heads=Z.LAWN)
        self.state.add(Label(uuid7(), self.zone.feature, "front lawn", T0, language="en"))
        self.state.add(Label(uuid7(), self.zone.feature, "césped del frente", T0, language="es"))
        self.n = 0

    def run_at(self, flow):
        when = T0 + self.n * DAY
        self.state.add(FX.observation(self.flow, result=flow, measured_at=when, seq=self.n))
        self.n += 1
        return when + _dt.timedelta(minutes=5)

    def test_the_cel_rules_agree_with_the_drill(self):
        for flows in ([12.9, 13.0, 12.8, 11.1, 11.1], [12.9, 13.0, 12.8, 21.0, 21.0],
                      [12.9, 13.0, 12.8, 12.9], [11.0, 11.0]):
            ctx = Z.judge_runs(flows, self.zone)
            raised = {r.id.removeprefix("zone-flow-") for r in Z.rules_for(self.zone)
                      if Z.R.judge(r, ctx, {}, T0)["alert"]}
            self.assertEqual(raised, Z.alerts(ctx, self.zone), flows)

    def test_raised_once_said_in_the_readers_language_and_cleared_when_fixed(self):
        monitor = Z.Monitor(Log())
        for flow in (12.9, 13.0, 12.85, 12.95):
            self.assertEqual(monitor.check(self.state, [self.zone], self.run_at(flow)), [])
        self.assertEqual(monitor.check(self.state, [self.zone], self.run_at(11.1)), [])
        [raised] = monitor.check(self.state, [self.zone], self.run_at(11.05))
        self.assertEqual((raised.payload["rule"], raised.payload["alert"]), ("zone-flow-low", True))
        en = Z.render(raised.payload, "en", self.state)
        self.assertIn("front lawn ran at 11.1 gpm, 86% of its usual 12.9", en)
        self.assertIn("1 half-circle spray head(s) of 15 feet", en)
        self.assertIn("medio círculo de 15 pies", Z.render(raised.payload, "es", self.state))
        self.assertEqual(monitor.check(self.state, [self.zone], self.run_at(11.1)), [],
                         "still low: nothing new to say")
        [cleared] = monitor.check(self.state, [self.zone], self.run_at(12.9))
        self.assertEqual((cleared.payload["rule"], cleared.payload["alert"]), ("zone-flow-low", False))

    def test_a_restarted_monitor_remembers_what_stands(self):
        log = Log()
        monitor = Z.Monitor(log)
        for flow in (12.9, 13.0, 12.85, 12.95, 11.1):
            monitor.check(self.state, [self.zone], self.run_at(flow))
        monitor.check(self.state, [self.zone], self.run_at(11.0))
        again = Z.Monitor(log)
        self.assertEqual(again.check(self.state, [self.zone], self.run_at(11.05)), [])
        self.assertEqual(len(again.standing()), 1)

    def test_a_change_to_the_zone_is_learned_afresh_from_since(self):
        for flow in (12.9, 13.0, 12.85, 12.95):
            self.run_at(flow)
        changed = T0 + self.n * DAY
        for flow in (16.6, 16.7, 16.5, 16.65):
            at = self.run_at(flow)
        before = Z.Zone(self.zone.feature, self.flow.id)                  # no inventory
        after = Z.Zone(self.zone.feature, self.flow.id, since=changed)
        self.assertEqual(Z.alerts(Z.zone_context(self.state, before, at)[0], before), {"high"})
        self.assertEqual(Z.alerts(Z.zone_context(self.state, after, at)[0], after), set())



@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestInTheReadersUnits(unittest.TestCase):

    def test_litres_a_minute_for_a_metric_reader(self):
        zone = lawn()
        ctx = Z.judge_runs([12.9, 13.0, 12.8, 12.95, 11.1, 11.05], zone)
        rule = next(r for r in Z.rules_for(zone) if r.id == "zone-flow-low")
        d = Z.R.judge(rule, ctx, {}, T0)
        self.assertIn("ran at 11.1 gpm", Z.render(d, "en"))
        self.assertIn("ran at 42 litres a minute", Z.render(d, "en", units="metric"))
        self.assertIn("ran at 11.1 gpm", Z.render(d, "en", units="us"), "written in US units")

if __name__ == "__main__":
    unittest.main()
