#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The soil-moisture advisory: its arithmetic, what it reads, its decisions, a recorded
summer against the drip timer, and Harrow Bend's beds through an outage and a moved
probe."""
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
try:
    import starlark  # noqa: F401
    HAVE_STARLARK = HAVE_CEL
except ImportError:
    HAVE_STARLARK = False

import fixtures as FX  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from log import Log  # noqa: E402
from model import Datastream, DatastreamKind, Installation, Label, QualityFlag  # noqa: E402
from project import State  # noqa: E402

import soilwater as S  # noqa: E402

HOUR = _dt.timedelta(hours=1)
T0 = _dt.datetime(2026, 7, 10, tzinfo=_dt.timezone.utc)
MORNING = T0 + 52 * HOUR          # 04:00 on the third day


class Garden:
    """One bed, with probes whose readings come from `theta(hours)`."""

    def __init__(self):
        self.state = State()
        self.land = uuid7()
        self.bed = S.Bed(self.land, field_capacity=0.30, wilting_point=0.12)

    def probe(self, theta, *, depth=0.20, hours=52, land=None, installed=None, removed=None):
        raw = FX.raw_datastream(unit="1", observed_property=V.SOIL_WATER,
                                expected_interval=3600.0, max_latency=3600.0)
        ds = FX.derived_datastream(raw, unit="cm3/cm3")
        cal = FX.calibration(raw.sensor)
        inst = Installation(uuid7(), raw.sensor, land or self.land,
                            installed or T0 - 24 * HOUR, removed_at=removed, depth_m=depth)
        for rec in (raw, ds, cal, inst):
            self.state.add(rec)
        obs = []
        for h in range(0, hours + 1):
            when = T0 + h * HOUR
            o = FX.observation(ds, result=round(theta(h), 3), measured_at=when,
                               calibration=cal.id, seq=h)
            self.state.add(o)
            obs.append(o)
        return ds, obs

    def rain(self, mm_per_hour, hours=24):
        fc = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(),
                        observed_property=V.PRECIPITATION_DEPTH, feature=uuid7(),
                        kind=DatastreamKind.FORECAST, unit="mm",
                        expected_interval=6 * 3600.0, max_latency=3600.0)
        self.state.add(fc)
        for h in range(1, hours + 1):
            self.state.add(FX.observation(fc, result=mm_per_hour, measured_at=MORNING + h * HOUR,
                                          received_at=MORNING - HOUR, issued_at=MORNING - HOUR,
                                          seq=h))
        return fc.id

    def advice(self, at=MORNING, **kw):
        d = S.Advisor(Log()).judge(self.state, self.bed, at, **kw)
        return d["rule"], d


class TestArithmetic(unittest.TestCase):
    def test_each_probe_stands_for_its_slice_of_the_root_zone(self):
        self.assertEqual(S.weights([0.20, 0.40], 0.30), [0.30, 0.0])
        self.assertEqual([round(w, 3) for w in S.weights([0.20, 0.30, 0.40], 0.30)],
                         [0.25, 0.05, 0.0])
        self.assertEqual(S.weights([0.40], 0.30), [0.0], "below the roots counts for nothing")
        self.assertEqual([round(w, 3) for w in S.weights([0.10, 0.25], 0.30)], [0.175, 0.125])

    def test_taw_and_the_refill_point_are_fao_56s(self):
        b = S.Bed(uuid7(), field_capacity=0.30, wilting_point=0.12)
        self.assertAlmostEqual(b.taw_mm, 54.0)
        self.assertAlmostEqual(b.raw_mm, 18.0)
        with self.assertRaises(ValueError):
            S.Bed(uuid7(), field_capacity=0.12, wilting_point=0.30)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestAdvice(unittest.TestCase):
    def test_water_now_and_how_much(self):
        g = Garden()
        g.probe(lambda h: 0.22)
        rule, d = g.advice()
        self.assertEqual(rule, "soil-water-now")
        self.assertAlmostEqual(d["context"]["refill_mm"], 24.0)
        self.assertEqual(d["context"]["used_percent"], 44)

    def test_rain_coming_holds_the_watering(self):
        g = Garden()
        g.probe(lambda h: 0.22)
        fc = g.rain(1.0)
        rule, d = g.advice(forecast=fc)
        self.assertEqual(rule, "soil-rain-coming")
        self.assertEqual(d["inputs"]["forecast"], str(fc))
        self.assertEqual(g.advice(forecast=g.rain(0.2))[0], "soil-water-now")

    def test_soon_enough_and_too_wet(self):
        drying = Garden()
        drying.probe(lambda h: 0.30 - 0.01 * max(0, h - 40) / 12 if h > 40 else 0.30 - 0.0)
        self.assertEqual(drying.advice()[0], "soil-enough")
        g = Garden()
        g.probe(lambda h: 0.28 - 0.02 * h / 12)       # 0.04 a day, from 0.28
        rule, d = g.advice(at=T0 + 20 * HOUR)
        self.assertEqual(rule, "soil-water-soon", d["context"])
        wet = Garden()
        wet.probe(lambda h: 0.34)
        self.assertEqual(wet.advice()[0], "soil-too-wet")

    def test_a_flagged_probe_is_not_read_and_a_good_one_still_is(self):
        g = Garden()
        _, obs = g.probe(lambda h: 0.20)
        g.state.add(FX.assertion(obs[-1].id, flags={QualityFlag.STUCK}, check="flatline",
                                 asserted_at=obs[-1].received_at))
        rule, d = g.advice()
        self.assertEqual(rule, "soil-untrusted")
        self.assertEqual(d["context"]["flags"], "stuck")
        g.probe(lambda h: 0.29, depth=0.10)
        rule, d = g.advice()
        self.assertEqual(rule, "soil-enough", "advice from the probe that passed")
        self.assertEqual(len(d["inputs"]["observations"]), 1)

    def test_a_silent_probe_gives_no_advice(self):
        g = Garden()
        g.probe(lambda h: 0.22, hours=40)
        rule, d = g.advice()
        self.assertEqual(rule, "soil-unseen")
        self.assertAlmostEqual(d["context"]["hours_since_reading"], 12.0)

    def test_a_moved_probe_leaves_its_bed_and_joins_the_other(self):
        g = Garden()
        other = uuid7()
        moved = T0 + 30 * HOUR
        ds, _ = g.probe(lambda h: 0.22, removed=moved)
        sensor = g.state.datastreams[ds.id].sensor
        g.state.add(Installation(uuid7(), sensor, other, moved, depth_m=0.20))
        self.assertEqual(g.advice()[0], "soil-no-probe")
        there = S.Bed(other, field_capacity=0.30, wilting_point=0.12)
        d = S.Advisor(Log()).judge(g.state, there, MORNING)
        self.assertEqual(d["rule"], "soil-water-now")
        early = S.Advisor(Log()).judge(g.state, there, T0 + 29 * HOUR)
        self.assertEqual(early["rule"], "soil-no-probe", "not there before it was moved")

    def test_a_probe_below_the_roots_is_no_probe(self):
        g = Garden()
        g.probe(lambda h: 0.22, depth=0.40)
        self.assertEqual(g.advice()[0], "soil-no-probe")

    def test_one_decision_per_bed_and_the_advice_in_the_readers_language(self):
        g = Garden()
        g.probe(lambda h: 0.22)
        for name, lang in (("bed 3", "en"), ("cama 3", "es")):
            g.state.add(Label(uuid7(), g.land, name, T0, language=lang))
        log = Log()
        [event] = S.Advisor(log).advise(g.state, [g.bed], MORNING)
        self.assertEqual(len(log), 1)
        self.assertEqual(event.payload["trust"], "advisory")
        self.assertEqual(S.render(event.payload, "en", g.state),
                         "Water bed 3 today: 44% of the water its plants can use is gone. "
                         "About 24 mm brings it back to field capacity.")
        self.assertIn("Riegue cama 3 hoy: ya se gastó el 44 %", S.render(event.payload, "es", g.state))


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestBacktestOnARecordedSummer(unittest.TestCase):
    """§11: backtested on a past season before it goes live. McAllister Farm's summer of
    2013, June to August, the drill's forecasts in the log; the advisory waters when it
    says to and skips when it says rain is coming."""

    @classmethod
    def setUpClass(cls):
        import irrigation_drill as D
        import physics as ph
        start = _dt.datetime(2013, 6, 1, tzinfo=_dt.timezone.utc)
        climate = ph.RecordedClimate.from_csv(D.SUMMER, seed=1)
        cls.drill = D.season(D.SUMMER, start, 92, seed=1, climate=climate,
                             policies=("timer", "soil_skip"))
        climate = ph.RecordedClimate.from_csv(D.SUMMER, seed=1)
        cls.advisory = S.backtest(climate, start, 92, seed=1)

    def test_it_waters_far_less_than_the_timer_without_more_stress(self):
        timer, a = self.drill["timer"], self.advisory
        self.assertLess(a["applied_mm"], 0.6 * timer["applied_mm"])
        self.assertLess(a["drained_mm"], timer["drained_mm"])
        self.assertLessEqual(a["stressed_h"], timer["stressed_h"] + 6)

    def test_it_matches_the_drills_soil_rule_it_replaces(self):
        """The same refill point and dose as the drill's stand-in rule, reached through
        probes, quality and CEL instead of the bed's true water. Not equal: the probe's
        noise is drawn hourly here and once a morning there, which on 2013 moves the
        total by about a fifth (155 mm against 190)."""
        rule = self.drill["soil_skip"]["applied_mm"]
        self.assertAlmostEqual(self.advisory["applied_mm"], rule, delta=0.25 * rule)

    def test_every_morning_got_advice(self):
        self.assertEqual(sum(self.advisory["advice"].values()), 92)
        self.assertIn("soil-water-now", self.advisory["advice"])


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestHarrowBend(unittest.TestCase):
    """Six beds every morning for eight days: the far bed node's radio is out from day 5
    to day 8, and on day 4 a probe is lifted out of bed 6 and pushed into bed 2."""

    @classmethod
    def setUpClass(cls):
        import harrow_bend as hb
        cls.farm = hb.build(seed=1)
        hb.season(cls.farm, days=8.0)
        cls.beds = {f"bed{k}": S.Bed(cls.farm.features[f"bed{k}"]["id"],
                                     field_capacity=0.30, wilting_point=0.12)
                    for k in range(1, 7)}
        cls.log = Log()
        advisor = S.Advisor(cls.log)
        cls.mornings = {}
        start = cls.farm.world.start
        for day in range(1, 8):
            at = start + _dt.timedelta(days=day, hours=4)
            events = advisor.advise(cls.farm.state, list(cls.beds.values()), at)
            cls.mornings[day] = {name: e.payload for name, e in zip(cls.beds, events)}

    def test_the_first_morning_tells_the_beds_apart(self):
        first = self.mornings[1]
        self.assertEqual(first["bed6"]["rule"], "soil-water-now")
        self.assertNotEqual(first["bed1"]["rule"], "soil-water-now")
        used = {k: first[f"bed{k}"]["context"]["used_percent"] for k in range(1, 7)}
        # Started from 0.38 down to 0.16: the three wet beds are still near capacity,
        # the three dry ones well into their water, bed 6 furthest — each bed's own
        # timer runs on its own days, so within each three the order can change.
        self.assertGreater(min(used[k] for k in (4, 5, 6)), max(used[k] for k in (1, 2, 3)))
        self.assertEqual(max(used, key=used.get), 6)

    def test_the_outage_silences_the_advice_for_its_beds_only(self):
        for day in (6, 7):
            m = self.mornings[day]
            for name in ("bed1", "bed3"):
                self.assertEqual(m[name]["rule"], "soil-unseen", (day, name))
            for name in ("bed4", "bed5"):
                self.assertNotEqual(m[name]["rule"], "soil-unseen", (day, name))

    def test_the_moved_probe_counts_in_its_new_bed(self):
        """Bed 6 lost its shallow probe; bed 2 gained it. Bed 2's own probe is behind the
        outage, so the probe that moved in is what still gives bed 2 its advice."""
        for day in (6, 7):
            m = self.mornings[day]
            self.assertEqual(m["bed6"]["rule"], "soil-no-probe", day)
            self.assertNotIn(m["bed2"]["rule"], ("soil-unseen", "soil-no-probe"), day)
            self.assertEqual(m["bed2"]["context"]["probes"], 2)
            self.assertEqual(len(m["bed2"]["inputs"]["observations"]), 1)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestAsItsOwnProcess(unittest.TestCase):
    """Q11: through the host's socket the advisory says what it says in-process, and as
    a process it writes one decision per bed under its own name."""

    def setUp(self):
        import modhost as M
        self.M = M
        self.g = Garden()
        self.g.probe(lambda h: 0.22)
        self.g.probe(lambda h: 0.30, depth=0.40)
        self.fc = self.g.rain(1.0)
        self.log = Log()
        self.dir = tempfile.mkdtemp(prefix="fm-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.path = os.path.join(self.dir, "m.sock")
        self.host = M.ModuleHost(self.log, self.g.state, self.path).start()
        manifest = M.Manifest.load(os.path.join(HERE, "module.json"))
        self.grant, self.token = M.grant(self.log, manifest,
                                         properties=[V.SOIL_WATER, V.PRECIPITATION_DEPTH])

    def tearDown(self):
        self.host.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_through_the_socket_it_advises_as_it_does_in_process(self):
        with self.M.ModuleClient(self.path, self.token) as c:
            for forecast in (None, self.fc):
                local = S.Advisor(Log()).judge(self.g.state, self.g.bed, MORNING, forecast=forecast)
                remote = S.Advisor(c.log()).judge(c.state(MORNING), self.g.bed, MORNING,
                                                  forecast=forecast)
                self.assertEqual((remote["rule"], remote["context"]),
                                 (local["rule"], local["context"]))

    def test_as_a_process_it_writes_one_decision_per_bed(self):
        config = os.path.join(self.dir, "beds.json")
        with open(config, "w", encoding="utf-8") as h:
            json.dump({"beds": [{"feature": str(self.g.land), "field_capacity": 0.30,
                                 "wilting_point": 0.12}], "forecast": None}, h)
        done = subprocess.run([sys.executable, "-I", os.path.join(HERE, "soilwater.py"),
                               "--socket", self.path, "--config", config,
                               "--at", MORNING.isoformat()],
                              env={"FIELDMESH_MODULE_TOKEN": self.token,
                                   "PATH": os.environ.get("PATH", "")},
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([json.loads(x)["rule"] for x in done.stdout.splitlines()],
                         ["soil-water-now"])
        self.assertEqual([e.payload["module"] for e in self.log.events if e.kind == "decision"],
                         ["soilwater"])



@unittest.skipUnless(HAVE_STARLARK, "starlark-pyo3 and cel-python (modules/rules/requirements.txt)")
class TestTheWateringCheck(unittest.TestCase):
    """A regimen (Q10): after the advice to water, did the water arrive? Backtested on
    McAllister Farm's recorded summers with some waterings that never reach the bed, as
    through a blocked drip line. 2013 is where the threshold was chosen; 2012 was not
    looked at until it was."""

    @staticmethod
    def score(path, start, blocked):
        import physics as ph
        r = S.backtest(ph.RecordedClimate.from_csv(path, seed=1), start, 92, seed=1,
                       check=S.watering_check(), blocked=frozenset(blocked))
        out = {"caught": 0, "missed": 0, "false": 0, "quiet": 0}
        for c in r["checks"]:
            if c["day"] in blocked:
                out["caught" if c["alert"] else "missed"] += 1
            else:
                out["false" if c["alert"] else "quiet"] += 1
        return out, r

    def test_it_catches_every_watering_that_never_arrived_on_2013(self):
        import irrigation_drill as D
        got, r = self.score(D.SUMMER, _dt.datetime(2013, 6, 1, tzinfo=_dt.timezone.utc),
                            {14, 30, 46, 78, 90})
        self.assertEqual(got, {"caught": 5, "missed": 0, "false": 0, "quiet": 7})
        self.assertEqual(r["stressed_h"], 0.0, "the next morning's advice waters it again")

    def test_and_on_a_summer_it_was_not_tuned_on(self):
        path = os.path.join(HERE, os.pardir, os.pardir, "sim", "data", "mcallister-2012-summer.csv")
        got, _ = self.score(path, _dt.datetime(2012, 6, 1, tzinfo=_dt.timezone.utc),
                            set(range(0, 92, 2)))
        self.assertEqual((got["missed"], got["false"]), (0, 0))
        self.assertGreater(got["caught"], 0)

    def test_advice_not_to_water_plans_nothing(self):
        import regimen as G
        bed = S.Bed(uuid7(), 0.30, 0.12, root_depth_mm=300.0)
        for rule in ("soil-enough", "soil-rain-coming", "soil-too-wet"):
            ctx = S.watering_check_context({"rule": rule, "context": {"refill_mm": 20.0}}, bed)
            self.assertEqual(G.plan(S.watering_check(), ctx), [])
        ctx = S.watering_check_context({"rule": "soil-water-now", "context": {"refill_mm": 18.0}}, bed)
        steps = G.plan(S.watering_check(), ctx)
        self.assertEqual(steps[0], {"kind": "wait", "minutes": 60.0 + 90.0 + 180.0})
        self.assertEqual(steps[1]["params"]["expected_percent"], 6.0)


if __name__ == "__main__":
    unittest.main()
