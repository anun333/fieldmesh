#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sowing advisory: Harrington's temperatures read right, days to emergence between
them, and the morning's decisions for a bed's crops, in English and Spanish."""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import math
import os
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
from model import Installation, Label, QualityFlag  # noqa: E402
from project import State  # noqa: E402

import sowing as S  # noqa: E402

UTC = _dt.timezone.utc
HOUR = _dt.timedelta(hours=1)
T0 = _dt.datetime(2026, 4, 1, 5, tzinfo=UTC)
MORNING = T0 + _dt.timedelta(days=4, hours=2)           # 07:00 on the fifth day


class TestHarringtonsTable(unittest.TestCase):

    def test_every_crop_is_read_and_in_celsius(self):
        self.assertEqual(len(S.CROPS), 24)
        bean = S.CROPS["bean"]
        self.assertAlmostEqual(bean["min_c"], 15.6, places=1)                     # 60 °F
        self.assertAlmostEqual(bean["max_c"], 35.0, places=1)                     # 95 °F
        self.assertEqual([t for t, _ in bean["days"]], [0.0, 5.0, 10.0, 15.0, 20.0, 25.0,
                                                        30.0, 35.0, 40.0])

    def test_cabbage_is_harringtons_45_to_95_not_the_misprint(self):
        self.assertAlmostEqual(S.CROPS["cabbage"]["high_c"], 35.0, places=1)

    def test_the_data_is_what_the_manifest_says(self):
        with open(os.path.join(HERE, "data", "MANIFEST.csv"), encoding="utf-8") as h:
            rows = list(csv.DictReader(line for line in h if not line.startswith("#")))
        self.assertEqual({r["file"] for r in rows}, {"germination-harrington.csv"})
        for r in rows:
            with open(os.path.join(HERE, "data", r["file"]), "rb") as h:
                self.assertEqual(hashlib.sha256(h.read()).hexdigest(), r["sha256"], r["file"])


class TestDaysToEmergence(unittest.TestCase):

    def test_at_a_tested_temperature_it_is_harringtons_figure(self):
        self.assertAlmostEqual(S.days_to_emergence("tomato", 20.0), 8.2)
        self.assertAlmostEqual(S.days_to_emergence("lettuce", 0.0), 49.0)

    def test_between_them_the_rate_is_interpolated_not_the_days(self):
        """Half way from 20 °C (8.2 days) to 25 (5.9): the rates' mean, 6.9 days, where
        the days' mean would say 7.05."""
        self.assertAlmostEqual(S.days_to_emergence("tomato", 22.5),
                               2.0 / (1.0 / 8.2 + 1.0 / 5.9), places=6)

    def test_next_to_a_temperature_the_seed_hardly_germinates_at_there_is_no_estimate(self):
        self.assertIsNone(S.days_to_emergence("bean", 12.0))      # 0 at 10 °C, 16.1 at 15
        self.assertIsNone(S.days_to_emergence("chard", 20.0))     # its days were not tabled
        self.assertIsNone(S.days_to_emergence("tomato", 45.0))


class TestSeedbed(unittest.TestCase):

    def test_a_bed_names_known_crops(self):
        with self.assertRaises(ValueError):
            S.Seedbed(uuid7(), crops=())
        with self.assertRaises(ValueError):
            S.Seedbed(uuid7(), crops=("okra",))


class Garden:
    """A bed with a soil temperature probe whose hourly readings come from `celsius(h)`."""

    def __init__(self, crops=("bean", "lettuce", "tomato", "pea")):
        self.state = State()
        self.land = uuid7()
        self.bed = S.Seedbed(self.land, crops=crops)
        self.state.add(Label(uuid7(), self.land, "bed 3", T0, language="en"))
        self.state.add(Label(uuid7(), self.land, "bancal 3", T0, language="es"))

    def probe(self, celsius, *, depth=0.05, hours=98, first=0):
        raw = FX.raw_datastream(unit="Cel", observed_property=V.SOIL_TEMPERATURE,
                                expected_interval=3600.0, max_latency=3600.0)
        ds = FX.derived_datastream(raw, unit="Cel")
        cal = FX.calibration(raw.sensor)
        inst = Installation(uuid7(), raw.sensor, self.land, T0 - 24 * HOUR, depth_m=depth)
        for rec in (raw, ds, cal, inst):
            self.state.add(rec)
        obs = []
        for h in range(first, hours + 1):
            o = FX.observation(ds, result=round(celsius(h), 2), measured_at=T0 + h * HOUR,
                               calibration=cal.id, seq=h)
            self.state.add(o)
            obs.append(o)
        return ds, obs

    def advice(self, at=MORNING):
        return {d["context"]["crop_key"].rsplit(".", 1)[1]: d
                for d in S.Advisor.judge(self.state, self.bed, at)}


def daily(mean, swing=4.0):
    """A day's soil temperature at 5 cm: warmest mid-afternoon, coolest at dawn."""
    return lambda h: mean + swing * math.sin(2.0 * math.pi * ((h - 9) % 24) / 24.0)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestTheMorningsAdvice(unittest.TestCase):

    def test_a_cool_spring_soil_tells_the_crops_apart(self):
        """Soil averaging 12 °C at 5 cm: too cold for beans (16), slow for tomatoes (best
        from 16), good for lettuce and peas."""
        g = Garden()
        g.probe(daily(12.0))
        a = g.advice()
        self.assertEqual({c: d["rule"] for c, d in a.items()},
                         {"bean": "sowing-cold", "lettuce": "sowing-good",
                          "tomato": "sowing-cool", "pea": "sowing-good"})
        mean = a["bean"]["context"]["mean_c"]
        self.assertAlmostEqual(mean, 12.0, delta=0.15)
        self.assertAlmostEqual(a["lettuce"]["context"]["days"], S.days_to_emergence("lettuce", mean), places=1)
        self.assertAlmostEqual(a["tomato"]["context"]["days"], S.days_to_emergence("tomato", mean), places=1)
        self.assertAlmostEqual(a["tomato"]["context"]["days"], 23.0, delta=0.5)
        self.assertEqual(a["bean"]["topic"], f"sowing/{g.land}/bean")

    def test_said_in_the_readers_language_crop_and_bed_named(self):
        g = Garden()
        g.probe(daily(12.0))
        a = g.advice()
        mean = a["bean"]["context"]["mean_c"]
        self.assertEqual(S.render(a["bean"], "en", g.state),
                         f"Not yet for beans in bed 3: the soil at 5 cm has averaged {mean:.1f} °C over "
                         "the last three days, and the seed needs at least 16 °C to germinate.")
        self.assertIn("Todavía no para frijoles en bancal 3", S.render(a["bean"], "es", g.state))
        self.assertIn("Seedlings in about 5 days", S.render(a["lettuce"], "en", g.state))
        self.assertIn("would come up slowly", S.render(a["tomato"], "en", g.state))
        self.assertIn("Si siembra tomates en bancal 3 ahora", S.render(a["tomato"], "es", g.state))

    def test_a_hot_summer_soil(self):
        """Soil averaging 33 °C: past spinach's 29 °C limit, above lettuce's and beans' best
        but under their limit, within sweet corn's best (to 35 °C)."""
        g = Garden(crops=("spinach", "lettuce", "bean", "corn"))
        g.probe(daily(33.0))
        a = g.advice()
        self.assertEqual({c: d["rule"] for c, d in a.items()},
                         {"spinach": "sowing-hot", "lettuce": "sowing-warm", "bean": "sowing-warm",
                          "corn": "sowing-good"})

    def test_a_probe_deeper_than_the_seed_does_not_speak_for_it(self):
        g = Garden()
        g.probe(daily(12.0), depth=0.20)
        self.assertEqual({d["rule"] for d in g.advice().values()}, {"sowing-no-probe"})

    def test_silence_a_new_probe_and_a_flagged_reading_give_no_advice(self):
        g = Garden()
        g.probe(daily(12.0), hours=88)                      # silent for ten hours
        self.assertEqual(g.advice()["bean"]["rule"], "sowing-unseen")
        new = Garden()
        new.probe(daily(12.0), first=88)                    # ten hours of readings in all
        self.assertEqual(new.advice()["bean"]["rule"], "sowing-too-new")
        flagged = Garden()
        _, obs = flagged.probe(daily(12.0))
        flagged.state.add(FX.assertion(obs[-1].id, flags={QualityFlag.OUT_OF_RANGE},
                                       check="range", asserted_at=obs[-1].received_at))
        d = flagged.advice()["bean"]
        self.assertEqual(d["rule"], "sowing-untrusted")
        self.assertIn("failed the health checks", S.render(d, "en", flagged.state))

    def test_written_once_a_crop_a_morning(self):
        g = Garden()
        g.probe(daily(12.0))
        events = S.Advisor(Log()).advise(g.state, [g.bed], MORNING)
        self.assertEqual(len(events), 4)
        self.assertEqual({e.payload["topic"] for e in events},
                         {f"sowing/{g.land}/{c}" for c in g.bed.crops})


if __name__ == "__main__":
    unittest.main()
