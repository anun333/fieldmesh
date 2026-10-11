#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The livestock water monitor: its judgements, its decisions, and §15's acceptance test
on Harrow Bend's paddock."""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sim"))

try:
    import celpy  # noqa: F401
    HAVE_CEL = True
except ImportError:
    HAVE_CEL = False

import fixtures as FX  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from log import Log  # noqa: E402
from model import Assertor, Label, QualityFlag, Usable  # noqa: E402
from project import State  # noqa: E402

import water as W  # noqa: E402

MIN = _dt.timedelta(minutes=1)
T0 = _dt.datetime(2026, 7, 14, 6, tzinfo=_dt.timezone.utc)


class Paddock:
    """One trough's series in a fresh state, filled by `level(minutes)`."""

    def __init__(self, level, *, minutes=360, every=5, delay=0.0):
        self.state = State()
        self.log = Log()
        raw = FX.raw_datastream(unit="1", observed_property=V.VESSEL_FILL_FRACTION,
                                expected_interval=300.0, max_latency=300.0)
        self.ds = FX.derived_datastream(raw)
        self.cal = FX.calibration(raw.sensor)
        for rec in (raw, self.ds, self.cal):
            self.state.add(rec)
        self.obs = []
        for m in range(0, minutes + 1, every):
            when = T0 + m * MIN
            o = FX.observation(self.ds, result=round(level(m), 3), measured_at=when,
                               received_at=when + delay * MIN, calibration=self.cal.id,
                               seq=m)
            self.state.add(o)
            self.obs.append(o)
        self.trough = W.Trough(self.ds.id, capacity_l=400.0)

    def flag(self, o, flags, *, at=None):
        a = FX.assertion(o.id, flags=flags, check="range", asserted_at=at or o.received_at)
        self.state.add(a)
        return a

    def context(self, minutes):
        return W.trough_context(self.state, self.trough, T0 + minutes * MIN)[0]


def stuck_from(minute, start=0.92, per_hour=0.12):
    """A float that sticks shut at `minute`: the level falls by `per_hour` of capacity."""
    return lambda m: start if m < minute else max(0.0, start - per_hour * (m - minute) / 60)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestJudgement(unittest.TestCase):
    def alerts(self, paddock, minutes):
        out = set()
        context, inputs = W.trough_context(paddock.state, paddock.trough, T0 + minutes * MIN)
        for rule in W.rules_for(paddock.trough):
            import rules as R
            if R.judge(rule, context, inputs, T0 + minutes * MIN)["alert"]:
                out.add(rule.id)
        return out

    def test_a_float_holding_its_setpoint_is_quiet(self):
        p = Paddock(lambda m: 0.92 - 0.01 * (m % 15 == 5))
        self.assertEqual(self.alerts(p, 360), set())

    def test_a_stuck_float_is_noticed_before_the_trough_is_low(self):
        p = Paddock(stuck_from(60))
        # Under the mark from minute 80; an hour later it is "not refilling".
        self.assertEqual(self.alerts(p, 135), set())
        c = p.context(150)
        self.assertAlmostEqual(c["below_setpoint_h"], 70 / 60, places=2)
        self.assertAlmostEqual(c["fall_l_per_h"], 0.12 * 400, delta=2)
        self.assertEqual(self.alerts(p, 150), {"water-not-refilling"})
        self.assertAlmostEqual(c["hours_to_empty"], (c["level"] - 0.10) / 0.12, delta=0.1)
        steep = Paddock(stuck_from(60, per_hour=0.15))
        self.assertEqual(self.alerts(steep, 360), {"water-not-refilling", "water-low"})

    def test_empty_and_flagged_only_out_of_range_is_empty_unconfirmed_not_untrusted(self):
        p = Paddock(stuck_from(0, start=0.5, per_hour=0.12), minutes=300)
        last = p.obs[-1]
        self.assertLess(last.result, 0.10)
        p.flag(last, {QualityFlag.OUT_OF_RANGE})
        self.assertIn("water-empty-unconfirmed", self.alerts(p, 300))
        self.assertNotIn("water-untrusted", self.alerts(p, 300))
        self.assertNotIn("water-empty", self.alerts(p, 300))

    def test_any_other_flag_is_untrusted(self):
        p = Paddock(lambda m: 0.92)
        p.flag(p.obs[-1], {QualityFlag.STUCK})
        self.assertEqual(self.alerts(p, 360), {"water-untrusted"})

    def test_silence_is_an_alert_and_late_readings_are_not_known_early(self):
        late = Paddock(lambda m: 0.92, minutes=240, delay=45)
        # Every reading lands 45 minutes after it was taken, so at any moment the
        # newest the gateway holds is 45 minutes old: unseen, though all will arrive.
        c = late.context(120)
        self.assertAlmostEqual(c["hours_since_reading"], 0.75, places=2)
        self.assertEqual(self.alerts(late, 120), {"water-unseen"})
        prompt = Paddock(lambda m: 0.92, minutes=240)
        self.assertEqual(self.alerts(prompt, 120), set())

    def test_a_later_override_does_not_reach_back(self):
        p = Paddock(lambda m: 0.92)
        last = p.obs[-1]
        p.flag(last, {QualityFlag.STUCK})
        person = FX.assertion(last.id, flags={QualityFlag.STUCK}, usable=Usable.GOOD,
                              check="manual-review", assertor=Assertor.PERSON,
                              assertor_id=uuid7(), asserted_at=last.received_at + 60 * MIN)
        p.state.add(person)
        self.assertEqual(self.alerts(p, 360), {"water-untrusted"})
        self.assertEqual(self.alerts(p, 360 + 61), {"water-unseen"})


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestMonitor(unittest.TestCase):
    def test_decisions_are_written_on_change_and_survive_a_restart(self):
        p = Paddock(stuck_from(60), minutes=600)
        m = W.Monitor(p.log)
        self.assertEqual(m.check(p.state, [p.trough], T0 + 30 * MIN), [])
        raised = m.check(p.state, [p.trough], T0 + 200 * MIN)
        self.assertEqual([e.payload["rule"] for e in raised], ["water-not-refilling"])
        self.assertEqual(m.check(p.state, [p.trough], T0 + 210 * MIN), [])
        event = raised[0]
        self.assertEqual(event.payload["trust"], "advisory")
        self.assertEqual(event.payload["subject"], str(p.ds.id))
        self.assertTrue(event.payload["inputs"]["observations"])

        again = W.Monitor(p.log)
        self.assertEqual([e.id for e in again.standing()], [event.id])
        self.assertEqual(again.check(p.state, [p.trough], T0 + 220 * MIN), [])

        self.assertEqual(again.unacknowledged(), [event])
        again.acknowledge(event, by=uuid7(), at=T0 + 221 * MIN, note="on my way")
        self.assertEqual(again.unacknowledged(), [])
        self.assertEqual(W.Monitor(p.log).unacknowledged(), [])
        self.assertEqual(again.standing(), [event], "acknowledging is not clearing")

    def test_a_cleared_alert_writes_a_decision_that_says_so(self):
        p = Paddock(lambda m: 0.92 if m < 60 or m > 240 else 0.70, minutes=360)
        m = W.Monitor(p.log)
        [up] = m.check(p.state, [p.trough], T0 + 200 * MIN)
        [down] = m.check(p.state, [p.trough], T0 + 300 * MIN)
        self.assertEqual((up.payload["alert"], down.payload["alert"]), (True, False))
        self.assertEqual(m.standing(), [])
        with self.assertRaises(ValueError):
            m.acknowledge(down, by=uuid7(), at=T0)

    def test_the_message_names_the_trough_in_the_readers_language(self):
        p = Paddock(stuck_from(60), minutes=600)
        for name, lang in (("north trough", "en"), ("bebedero norte", "es")):
            p.state.add(Label(uuid7(), p.ds.id, name, T0, language=lang))
        [event] = W.Monitor(p.log).check(p.state, [p.trough], T0 + 200 * MIN)
        en = W.render(event.payload, "en", p.state)
        es = W.render(event.payload, "es", p.state)
        self.assertTrue(en.startswith("north trough has not refilled for 2.0 hours"), en)
        self.assertIn("bebedero norte no se ha vuelto a llenar en 2,0 horas", es)
        # The sentence that fits is chosen when the rule is judged, so the decision
        # names it and any renderer says it without knowing this module.
        import rules as R
        rules = {r.id: r for r in W.rules_for(p.trough)}
        resting = {"has_reading": True, "usable": True, "low_side_range": False,
                   "level": 0.8, "level_percent": 80.0, "hours_since_reading": 0.1,
                   "below_setpoint_h": 3.0, "fall_l_per_h": 0.0,
                   "hours_to_empty": W.NO_ESTIMATE}
        idle = dict(R.judge(rules["water-not-refilling"], resting, {}, T0), subject=str(p.ds.id))
        self.assertEqual(idle["message"]["key"], "water.not_refilling_idle")
        self.assertIn("north trough", R.render(idle, "en", p.state))
        self.assertIn("before the stock start drinking", R.render(idle, "en", p.state))
        silent, _ = W.trough_context(State(), p.trough, T0)
        never = dict(R.judge(rules["water-unseen"], silent, {}, T0), subject=str(p.ds.id))
        self.assertIn("No reading has ever arrived from north trough", R.render(never, "en", p.state))


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestAcceptanceOnHarrowBend(unittest.TestCase):
    """§15: "Livestock water monitor — newest reading first after an outage."

    Harrow Bend's paddock node carries both troughs and drains its backlog newest-first.
    Its radio goes out for twelve hours on day 2; the south trough's float sticks shut on
    day 9. The monitor runs every ten minutes over the whole season, judging only what
    the gateway had received by then.
    """

    DAYS = 10.0
    EVERY = 10 * MIN

    @classmethod
    def setUpClass(cls):
        import harrow_bend as hb
        cls.farm = hb.build(seed=1)
        start = cls.farm.world.start
        cls.outage = (start + _dt.timedelta(days=2), start + _dt.timedelta(days=2.5))
        cls.farm.links["paddock"].outage(cls.outage[0].timestamp(), cls.outage[1].timestamp())
        hb.season(cls.farm, days=cls.DAYS)
        cls.troughs = [W.Trough(cls.farm.series["trough_north"].derived.id, capacity_l=400.0),
                       W.Trough(cls.farm.series["trough_south"].derived.id, capacity_l=250.0)]
        cls.north, cls.south = (str(t.datastream) for t in cls.troughs)
        cls.monitor = W.Monitor(cls.farm.log)
        cls.decisions = []
        t = start + cls.EVERY
        while t <= start + _dt.timedelta(days=cls.DAYS):
            cls.decisions += cls.monitor.check(cls.farm.state, cls.troughs, t)
            t += cls.EVERY

    def raised(self, subject, rule):
        return [_dt.datetime.fromisoformat(e.payload["evaluated_at"]) for e in self.decisions
                if e.payload["subject"] == subject and e.payload["rule"] == rule
                and e.payload["alert"]]

    def test_the_healthy_trough_raises_nothing_but_the_outage(self):
        rules = {e.payload["rule"] for e in self.decisions
                 if e.payload["subject"] == self.north and e.payload["alert"]}
        self.assertEqual(rules, {"water-unseen"})

    def test_the_outage_is_an_alert_and_clears_when_the_radio_returns(self):
        start, end = self.outage
        for subject in (self.north, self.south):
            [raised] = [t for t in self.raised(subject, "water-unseen") if start <= t <= end]
            self.assertLessEqual(raised - start, _dt.timedelta(minutes=50))
            cleared = [_dt.datetime.fromisoformat(e.payload["evaluated_at"])
                       for e in self.decisions if e.payload["subject"] == subject
                       and e.payload["rule"] == "water-unseen" and not e.payload["alert"]
                       and _dt.datetime.fromisoformat(e.payload["evaluated_at"]) > raised]
            self.assertTrue(cleared)
            self.assertLessEqual(cleared[0] - end, _dt.timedelta(minutes=20))

    def test_newest_reading_first_after_the_outage(self):
        """The clause itself: the first look after the radio returns sees the trough as
        it is now, not as it was when the radio went out twelve hours earlier."""
        end = self.outage[1]
        t = end
        while True:
            t += self.EVERY
            context, _ = W.trough_context(self.farm.state, self.troughs[0], t)
            if context["has_reading"] and context["hours_since_reading"] < 12:
                break
        self.assertLessEqual(t - end, _dt.timedelta(minutes=20))
        self.assertLess(context["hours_since_reading"], 0.25)

    def test_the_stuck_float_is_caught_hours_before_the_stock_run_dry(self):
        """Stuck at midnight, it shows nothing until the stock start drinking. From the
        first reading under the float's mark, an hour's hold and a look; then hours of
        warning before the trough is too low to drink from."""
        stuck = self.farm.world.start + _dt.timedelta(days=9)
        rows = [o for o in self.farm.state.live_observations_of(self.troughs[1].datastream)
                if o.measured_at >= stuck]
        first_below = min(o.received_at for o in rows
                          if o.result < self.troughs[1].float_setpoint - W.SETPOINT_MARGIN)
        first_dry = min(o.received_at for o in rows if o.result < 0.10)
        [refill] = [t for t in self.raised(self.south, "water-not-refilling") if t >= stuck]
        empty = [t for t in self.raised(self.south, "water-empty")
                 + self.raised(self.south, "water-empty-unconfirmed") if t >= stuck]
        self.assertTrue(empty, "the trough emptied, and the monitor said so")
        self.assertLessEqual(refill - first_below,
                             _dt.timedelta(hours=self.troughs[1].refill_hold_h) + 2 * self.EVERY)
        self.assertGreaterEqual(min(empty) - refill, _dt.timedelta(hours=4))
        self.assertLessEqual(min(empty) - first_dry, self.EVERY)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestAsItsOwnProcess(unittest.TestCase):
    """Q11: through the host's socket, holding only its grant, the monitor decides
    exactly as it does in-process; run as a process, its decisions carry its name."""

    def setUp(self):
        import modhost as M
        self.M = M
        self.p = Paddock(stuck_from(60), minutes=600)
        self.dir = tempfile.mkdtemp(prefix="fm-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.path = os.path.join(self.dir, "m.sock")
        self.host = M.ModuleHost(self.p.log, self.p.state, self.path).start()
        manifest = M.Manifest.load(os.path.join(HERE, "module.json"))
        self.grant, self.token = M.grant(self.p.log, manifest, datastreams=[self.p.ds.id])

    def tearDown(self):
        self.host.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_through_the_socket_it_decides_as_it_does_in_process(self):
        local = W.Monitor(Log())
        with self.M.ModuleClient(self.path, self.token) as c:
            remote = W.Monitor(c.log())
            for m in (30, 100, 200, 400, 600):
                t = T0 + m * MIN
                a = [(e.payload["rule"], e.payload["alert"], e.payload["context"])
                     for e in local.check(self.p.state, [self.p.trough], t)]
                b = [(e.payload["rule"], e.payload["alert"], e.payload["context"])
                     for e in remote.check(c.state(t), [self.p.trough], t)]
                self.assertEqual(a, b, m)
            self.assertEqual([e.id for e in W.Monitor(c.log()).standing()],
                             [e.id for e in remote.standing()], "it remembers through the host")

    def test_as_a_process_its_decisions_carry_its_name(self):
        config = os.path.join(self.dir, "troughs.json")
        with open(config, "w", encoding="utf-8") as h:
            json.dump({"troughs": [{"datastream": str(self.p.ds.id), "capacity_l": 400.0}]}, h)
        done = subprocess.run([sys.executable, "-I", os.path.join(HERE, "water.py"),
                               "--socket", self.path, "--config", config,
                               "--at", (T0 + 200 * MIN).isoformat()],
                              env={"FIELDMESH_MODULE_TOKEN": self.token,
                                   "PATH": os.environ.get("PATH", "")},
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        said = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([s["rule"] for s in said], ["water-not-refilling"])
        decisions = [e for e in self.p.log.events if e.kind == "decision"]
        self.assertEqual([(e.payload["module"], e.payload["module_grant"]) for e in decisions],
                         [("water", str(self.grant.id))])


if __name__ == "__main__":
    unittest.main()
