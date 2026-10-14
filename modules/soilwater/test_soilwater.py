#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The soil-moisture advisory: its arithmetic, what it reads, its decisions, a recorded
summer against the drip timer, and Harrow Bend's beds through an outage and a moved
probe."""
from __future__ import annotations

import datetime as _dt
import json
import math
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

    def probe(self, theta, *, depth=0.20, hours=52, land=None, installed=None, removed=None,
              start=None):
        raw = FX.raw_datastream(unit="1", observed_property=V.SOIL_WATER,
                                expected_interval=3600.0, max_latency=3600.0)
        ds = FX.derived_datastream(raw, unit="cm3/cm3")
        cal = FX.calibration(raw.sensor)
        base = start or T0
        inst = Installation(uuid7(), raw.sensor, land or self.land,
                            installed or base - 24 * HOUR, removed_at=removed, depth_m=depth)
        for rec in (raw, ds, cal, inst):
            self.state.add(rec)
        obs = []
        for h in range(0, hours + 1):
            when = base + h * HOUR
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
        self.assertEqual([round(w, 3) for w in S.weights([0.20, 0.30, 0.40], 0.40)],
                         [0.25, 0.10, 0.0])
        self.assertEqual(S.weights([0.20, 0.30], 0.30), [0.25, 0.0],
                         "at the roots' front: the soil they are only reaching")
        self.assertEqual(S.weights([0.40], 0.30), [0.0], "below the roots counts for nothing")
        self.assertEqual([round(w, 3) for w in S.weights([0.10, 0.25], 0.30)], [0.175, 0.125])

    def test_the_driest_a_probe_in_the_soil_reads(self):
        self.assertAlmostEqual(S.soil_floor(0.10, 0.12), 0.03, msg="the evaporation layer")
        self.assertAlmostEqual(S.soil_floor(0.15, 0.12), 0.03)
        self.assertAlmostEqual(S.soil_floor(0.20, 0.12), 0.09, msg="below: the wilting point")

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
        g.probe(lambda h: 0.30 - 0.02 * h / 24)       # 6 mm a day: 13 gone, due in under a day
        rule, d = g.advice()
        self.assertEqual(rule, "soil-water-soon", d["context"])
        fast = Garden()
        fast.probe(lambda h: 0.33 - 0.04 * h / 24)    # 12 mm a day: 17 gone, 29 by tomorrow
        self.assertEqual(fast.advice()[0], "soil-water-now")
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

    def test_a_probe_drier_than_its_soil_can_be_is_out_of_it(self):
        """Below the top 15 cm nothing dries soil past its wilting point, 0.12 here: a probe
        at 20 cm reading 0.02 reads the air, and the advice says so rather than water."""
        g = Garden()
        g.probe(lambda h: 0.02)
        rule, d = g.advice()
        self.assertEqual(rule, "soil-untrusted")
        self.assertEqual(d["context"]["flags"], "out_of_soil")
        self.assertEqual(d["message"]["key"], "soilwater.untrusted_out_of_soil")
        self.assertEqual((d["context"]["out_of_soil_cm"], d["context"]["soil_floor_percent"]),
                         (20, 9.0))
        self.assertIn("reads 2.0% water, drier than its soil can be (9.0% at least): it may "
                      "be out of the soil", S.render(d, "en"))
        self.assertIn("puede estar fuera del suelo", S.render(d, "es"))
        [only] = S.Advisor(Log()).advise(g.state, [g.bed], MORNING)
        self.assertEqual(only.payload["rule"], "soil-untrusted", "its own words, no note")

    def test_near_the_surface_the_sun_dries_soil_to_half_its_wilting_point(self):
        g = Garden()
        g.probe(lambda h: 0.04, depth=0.10)
        rule, d = g.advice()
        self.assertEqual(rule, "soil-water-now", "0.04 is dry topsoil, not air")
        self.assertFalse(d["context"]["out_of_soil"])
        air = Garden()
        air.probe(lambda h: 0.02, depth=0.10)
        self.assertEqual(air.advice()[0], "soil-untrusted")

    def test_with_another_probe_the_advice_goes_on_and_a_note_says_why(self):
        g = Garden()
        g.probe(lambda h: 0.02)
        g.probe(lambda h: 0.29, depth=0.10)
        decision, note = (e.payload for e in S.Advisor(Log()).advise(g.state, [g.bed], MORNING))
        self.assertEqual(decision["rule"], "soil-enough")
        self.assertEqual(len(decision["inputs"]["observations"]), 1)
        self.assertEqual((note["rule"], note["topic"]), ("soil-probe-out-of-soil",
                                                         f"probes/{g.land}"))
        self.assertIn("probe at 20 cm reads 2.0% water", S.render(note, "en"))
        self.assertIn("probe at 8 inches", S.render(note, "en", units="us"))

    def test_in_sand_a_probe_in_the_air_cannot_be_told_from_dry_sand(self):
        g = Garden()
        g.bed = S.Bed(g.land, field_capacity=0.15, wilting_point=0.05)
        g.probe(lambda h: 0.02, depth=0.10)
        rule, d = g.advice()
        self.assertNotEqual(rule, "soil-untrusted")
        self.assertFalse(d["context"]["out_of_soil"])

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

    def test_what_covers_the_bed_and_grows_in_it_goes_on_the_record(self):
        g = Garden()
        g.bed = S.Bed(g.land, 0.30, 0.12, surface="organic_mulch", planting="shrubs")
        g.probe(lambda h: 0.25)
        _, d = g.advice()
        self.assertEqual((d["inputs"]["surface"], d["inputs"]["planting"]),
                         ("organic_mulch", "shrubs"))
        _, d = Garden().advice()
        self.assertNotIn("surface", d["inputs"])
        with self.assertRaises(ValueError):
            S.Bed(g.land, 0.30, 0.12, surface="gravel")
        with self.assertRaises(ValueError):
            S.Bed(g.land, 0.30, 0.12, planting="lawn")

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


def _drains(cycles: int, *, capacity=0.22, every_h=72, lead_h=12, excess=0.18, tau_h=3.0,
            drying_per_h=0.0006, noise=0.005, seed=1):
    """A probe's hours `(h, θ)`: dry and flat for `lead_h`, then a wetting every
    `every_h`, each draining back towards `capacity` while the crop dries the soil."""
    import math
    import random
    rng, out = random.Random(seed), []
    for h in range(lead_h):
        out.append((h, capacity - 0.03 + rng.gauss(0.0, noise)))
    for c in range(cycles):
        for t in range(every_h):
            v = capacity + excess * math.exp(-t / tau_h) - drying_per_h * t
            out.append((lead_h + c * every_h + t, v + rng.gauss(0.0, noise)))
    return out


def _timed(points):
    return [(T0 + h * HOUR, v) for h, v in points]


class TestLearnedCapacity(unittest.TestCase):
    """Field capacity learned from the bed's own probe: the level it drains back to after
    a soaking (`learned_capacity`), for the bed the soil survey does not describe."""

    def test_a_drain_down_is_fitted_to_the_level_it_drains_back_to(self):
        points = [(float(h - 12), v) for h, v in _drains(1)[12:]]
        fit = S.drain_fit(points)
        self.assertAlmostEqual(fit["field_capacity"], 0.22, delta=0.01)
        self.assertAlmostEqual(fit["excess"], 0.18, delta=0.03)
        self.assertIn(fit["tau_h"], (2.0, 3.0, 4.0))

    def test_each_wetting_is_found_and_one_noisy_reading_is_not_one(self):
        readings = _timed(_drains(3))
        self.assertEqual(len(S.drain_downs(readings)), 3)
        spiked = list(readings)
        h, v = spiked[40]
        spiked[40] = (h, v + 0.08)
        self.assertEqual(len(S.drain_downs(spiked)), 3)

    def test_three_drain_downs_teach_it_and_two_do_not(self):
        self.assertIsNone(S.learned_capacity(_timed(_drains(2))))
        found = S.learned_capacity(_timed(_drains(3)))
        self.assertAlmostEqual(found["field_capacity"], 0.22, delta=0.01)
        self.assertEqual(found["drains"], 3)
        self.assertLessEqual(found["half_drain_h"], 4)

    def test_a_watering_that_only_refills_part_way_teaches_nothing(self):
        """Back up to 0.20 and drying from there: the soil never held more than it
        could, so nothing drained, and the 0.20 says nothing about capacity."""
        readings = _timed(_drains(4, capacity=0.20, excess=0.0, drying_per_h=0.001))
        rising = [(t, v + (0.05 if (t - T0) / HOUR >= 12 else 0.0)) for t, v in readings]
        self.assertIsNone(S.learned_capacity(_timed(_drains(4, excess=0.0))))
        self.assertIsNone(S.learned_capacity(rising))

    def test_a_crop_drying_more_slowly_as_the_soil_dries_is_not_drainage(self):
        """Watered back to 0.27, below its field capacity of 0.30, so nothing drains. The
        crop then draws about 5 mm a day by daylight, less as the soil dries: a gentle curve
        over three days, read hourly with a probe's noise of 0.01. Fitted with "drainage"
        as slow as 36 hours, 34 of 200 such curves passed for drain-downs, down to 0.23:
        the ratchet that sank a learned value from 0.248 to 0.206 over the 2012 drought.
        Now a few still pass on noise alone, none more than 0.02 below the level watered
        to."""
        import random

        def curve(seed):
            rng, out, theta = random.Random(seed), [], 0.27
            for h in range(73):
                out.append((float(h), round(theta + rng.gauss(0.0, 0.01), 3)))
                sun = max(0.0, math.sin(math.pi * ((h % 24) - 6) / 12.0)) * math.pi
                theta -= 5.0 / 24.0 * sun * (theta - 0.12) / 0.18 / 300.0
            return out
        kept = [f["field_capacity"] for f in map(S.drain_fit, map(curve, range(200)))
                if f is not None and f["excess"] >= S.DRAIN_MIN_EXCESS]
        self.assertLessEqual(len(kept), 15)
        self.assertGreaterEqual(min(kept, default=0.27), 0.25)

    def test_drainage_faster_than_the_readings_cannot_be_seen(self):
        """On hourly readings, no τ under an hour is tried: half an hour's "drainage" is one
        reading."""
        points = [(float(h - 12), v) for h, v in _drains(1)[12:]]
        self.assertGreaterEqual(S.drain_fit(points)["tau_h"], 1.0)

    def test_a_gap_ends_a_drain_down(self):
        readings = [(t, v) for t, v in _timed(_drains(4))
                    if not 8 <= ((t - T0) / HOUR - 12) % 72 < 14]
        self.assertEqual(S.drain_downs(readings), [])

    @unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
    def test_the_advice_uses_the_beds_own_capacity(self):
        """Set up with a survey's 0.30, the bed drains back to 0.22 after every soaking:
        a sandy fill the survey never saw. A day after its last soaking, on the configured
        value it is a third short and needs water; on its own, it has most of its water
        left."""
        points = dict(_drains(4))
        last = 12 + 3 * 72 + 24
        g = Garden()
        g.probe(lambda h: points[h], hours=last)
        at = T0 + last * HOUR
        rule, d = g.advice(at)
        self.assertAlmostEqual(d["context"]["field_capacity"], 0.22, delta=0.01)
        self.assertEqual(d["context"]["learned_probes"], 1)
        self.assertEqual(d["inputs"]["learned"][0]["drains"], 4)
        self.assertNotEqual(rule, "soil-water-now")
        g.bed = S.replace(g.bed, learn=False)
        rule, d = g.advice(at)
        self.assertEqual(d["context"]["field_capacity"], 0.30)
        self.assertEqual(rule, "soil-water-now")

    def test_a_bed_can_give_each_layers_values(self):
        bed = S.Bed(uuid7(), 0.38, 0.25, layers=((0.10, 0.20, 0.09),))
        self.assertEqual(bed.limits_at(0.05), (0.20, 0.09))
        self.assertEqual(bed.limits_at(0.10), (0.20, 0.09))
        self.assertEqual(bed.limits_at(0.12), (0.38, 0.25))
        for bad in (((0.10, 0.09, 0.20),), ((0.20, 0.2, 0.1), (0.10, 0.3, 0.1)),
                    ((0.0, 0.2, 0.1),)):
            with self.assertRaises(ValueError):
                S.Bed(uuid7(), 0.38, 0.25, layers=bad)

    @unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
    def test_two_probes_in_two_soils_say_the_bed_is_layered(self):
        """Sandy topsoil at 5 cm drains back to 0.22, clay at 12 cm to 0.40: the bed
        is two soils, and its one pair of values cannot describe it."""
        top, clay = dict(_drains(4)), dict(_drains(4, capacity=0.40, excess=0.05, seed=2))
        last = 12 + 3 * 72 + 24
        g = Garden()
        g.probe(lambda h: top[h], depth=0.05, hours=last)
        g.probe(lambda h: clay[h], depth=0.12, hours=last)
        log = Log()
        events = S.Advisor(log).advise(g.state, [g.bed], T0 + last * HOUR)
        self.assertEqual([e.payload["rule"] for e in events][1:], ["soil-layered"])
        note = events[1].payload
        self.assertEqual(note["topic"], f"layers/{g.land}")
        self.assertEqual((note["context"]["shallow_cm"], note["context"]["deep_cm"]), (5, 12))
        g.state.add(Label(uuid7(), g.land, "bed 3", T0, language="en"))
        g.state.add(Label(uuid7(), g.land, "cama 3", T0, language="es"))
        self.assertIn("bed 3's soil is layered: its probe at 5 cm drains back to 22% water",
                      S.render(note, "en", g.state))
        self.assertIn("la de 12 cm a 40 %", S.render(note, "es", g.state))
        g.bed = S.Bed(g.land, 0.38, 0.25, layers=((0.08, 0.20, 0.09),))
        events = S.Advisor(log).advise(g.state, [g.bed], T0 + last * HOUR)
        self.assertEqual(len(events), 1, "given each layer's values, it has nothing to add")

    @unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
    def test_a_capacity_the_wilting_point_rules_out_is_not_used(self):
        points = dict(_drains(4))
        g = Garden()
        g.bed = S.Bed(g.land, field_capacity=0.30, wilting_point=0.20)
        g.probe(lambda h: points[h], hours=max(points))
        _, d = g.advice(T0 + max(points) * HOUR)
        self.assertEqual(d["context"]["field_capacity"], 0.30)
        self.assertEqual(d["context"]["learned_probes"], 0)


class WeatherGarden(Garden):
    """A bed with no probe, and the farm's station: hourly readings each local day, in
    America/Chicago, the same summer weather every day unless rain is given."""

    def station(self, days, *, rain=None, gap_days=()):
        import eto as E
        names = (("air", V.AIR_TEMPERATURE, "Cel"), ("rh", V.RELATIVE_HUMIDITY, "%"),
                 ("sun", V.SOLAR_RADIATION, "W/m2"), ("rain", V.PRECIPITATION_DEPTH, "mm"))
        ds = {}
        for name, prop, unit in names:
            ds[name] = FX.raw_datastream(unit=unit, observed_property=prop,
                                         expected_interval=3600.0, max_latency=3600.0)
            self.state.add(ds[name])
        start = _dt.datetime(2026, 7, 1, 5, tzinfo=_dt.timezone.utc)      # local midnight
        for d in range(days):
            if d in gap_days:
                continue
            for h in range(24):
                when = start + _dt.timedelta(days=d, hours=h, minutes=30)
                values = {"air": 20.0 + 12.0 * max(0.0, math.sin(math.pi * (h - 6) / 12.0)),
                          "rh": 60.0, "sun": 260.0,
                          "rain": (rain or {}).get(d, 0.0) / 24.0}
                for name, value in values.items():
                    self.state.add(FX.observation(ds[name], result=value, measured_at=when,
                                                  seq=d * 24 + h))
        return E.Station(lat=35.06, elevation_m=243.0, timezone="America/Chicago",
                         air_temperature=ds["air"].id, relative_humidity=ds["rh"].id,
                         solar_radiation=ds["sun"].id, precipitation=ds["rain"].id)


TOMATOES_AND_LETTUCE = (("tomato", _dt.date(2026, 5, 1)), ("lettuce", _dt.date(2026, 6, 15)))


class TestPlantingsAtDifferentStages(unittest.TestCase):
    """Tomatoes sown on 1 May with lettuce sown among them on 15 June: on 1 July the
    tomatoes are 61 days on, roots to 50 cm, the lettuce 16, roots to 15."""

    def test_the_roots_span_a_range_and_the_coefficient_is_the_mean(self):
        bed = S.Bed(uuid7(), 0.30, 0.12, plantings=TOMATOES_AND_LETTUCE)
        g = S.grown(bed, _dt.date(2026, 7, 1))
        tomato_kc, tomato_root = S.crop_day("tomato", 61)
        lettuce_kc, lettuce_root = S.crop_day("lettuce", 16)
        self.assertEqual((g.root_depth_mm, g.timing_depth_mm), (tomato_root, lettuce_root))
        self.assertAlmostEqual(g.crop_coefficient, (tomato_kc + lettuce_kc) / 2)
        self.assertAlmostEqual(g.timing_raw_mm, 0.18 / 3 * lettuce_root)
        self.assertAlmostEqual(g.raw_mm, 0.18 / 3 * tomato_root)
        before = S.grown(bed, _dt.date(2026, 6, 1))
        self.assertEqual((before.root_depth_mm, before.timing_depth_mm),
                         (S.crop_day("tomato", 31)[1], None), "the lettuce not yet sown")

    def test_one_crop_or_plantings_and_each_known(self):
        with self.assertRaises(ValueError):
            S.Bed(uuid7(), 0.30, 0.12, crop="tomato", planted=_dt.date(2026, 5, 1),
                  plantings=TOMATOES_AND_LETTUCE)
        with self.assertRaises(ValueError):
            S.Bed(uuid7(), 0.30, 0.12, plantings=(("kohlrabi", _dt.date(2026, 5, 1)),))
        with self.assertRaises(ValueError):
            S.Bed(uuid7(), 0.30, 0.12, plantings=(("lettuce", None),))


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestAdviceForPlantingsAtDifferentStages(unittest.TestCase):

    def test_by_probes_the_young_roots_time_it_and_the_old_set_the_refill(self):
        """The probe at 10 cm, among the lettuce's roots, is 0.07 under field capacity; the
        one at 40 cm, 0.01. The tomatoes alone have water to spare; the lettuce is due."""
        at = _dt.datetime(2026, 7, 1, 9, tzinfo=_dt.timezone.utc)
        g = Garden()
        g.probe(lambda h: 0.23, depth=0.10, start=at - 52 * HOUR)
        g.probe(lambda h: 0.29, depth=0.40, start=at - 52 * HOUR)
        g.bed = S.replace(g.bed, crop="tomato", planted=_dt.date(2026, 5, 1))
        alone, d = g.advice(at)
        self.assertIn(alone, ("soil-water-soon", "soil-enough"))
        refill = d["context"]["refill_mm"]
        g.bed = S.Bed(g.land, 0.30, 0.12, plantings=TOMATOES_AND_LETTUCE)
        rule, d = g.advice(at)
        c = d["context"]
        self.assertEqual(rule, "soil-water-now")
        self.assertEqual((c["timing_depth_cm"], c["root_depth_cm"], c["plantings"]), (15, 50, 2))
        self.assertAlmostEqual(c["timing_depletion_mm"], 0.07 * 150.0, places=1)
        self.assertAlmostEqual(c["refill_mm"], refill, places=1)
        text = S.render(d, "en")
        self.assertIn("its shallowest roots, in the top 15 cm, have used 39%", text)
        self.assertIn("down to its deepest roots at 50 cm", text)
        self.assertEqual([p["crop"] for p in d["inputs"]["plantings"]], ["tomato", "lettuce"])

    def test_young_roots_drying_fast_are_watered_a_day_early(self):
        """The probe at 10 cm has fallen 0.05 since yesterday: the lettuce's 15 cm has used
        7.5 mm, short of its 9, but at about 7 mm a day it would be past half its 27 by
        tomorrow."""
        at = _dt.datetime(2026, 7, 1, 9, tzinfo=_dt.timezone.utc)
        g = Garden()
        g.probe(lambda h: min(0.30, 0.25 + 0.05 * (52 - h) / 24.0), depth=0.10,
                start=at - 52 * HOUR)
        g.probe(lambda h: 0.29, depth=0.40, start=at - 52 * HOUR)
        g.bed = S.Bed(g.land, 0.30, 0.12, plantings=TOMATOES_AND_LETTUCE)
        rule, d = g.advice(at)
        c = d["context"]
        self.assertEqual(rule, "soil-water-now")
        self.assertLess(c["timing_depletion_mm"], 9.0)
        self.assertGreaterEqual(c["timing_depletion_mm"] + c["timing_drying_mm_per_day"], 13.5)

    def test_soil_past_field_capacity_below_does_not_fill_the_dry_top(self):
        """The probe at 40 cm reads 0.33, draining: averaged with the dry top it would say
        the bed has lost nothing. Each probe's own deficit counts, none its surplus."""
        at = _dt.datetime(2026, 7, 1, 9, tzinfo=_dt.timezone.utc)
        g = Garden()
        g.probe(lambda h: 0.23, depth=0.10, start=at - 52 * HOUR)
        g.probe(lambda h: 0.33, depth=0.40, start=at - 52 * HOUR)
        g.bed = S.Bed(g.land, 0.30, 0.12, plantings=TOMATOES_AND_LETTUCE)
        rule, d = g.advice(at)
        c = d["context"]
        self.assertEqual(rule, "soil-water-now")
        self.assertFalse(c["wetter_than_capacity"])
        weights = S.weights([0.10, 0.40], c["root_depth_mm"] / 1000.0)
        self.assertAlmostEqual(c["refill_mm"], weights[0] / sum(weights) * 0.07
                               * c["root_depth_mm"], places=0)

    def test_a_probe_named_for_the_young_planting_times_it(self):
        """A probe at 10 cm among the tomatoes reads 0.29; one at 10 cm among the lettuce,
        0.23. Unnamed, the two are averaged and the lettuce's dry soil is hidden; named, the
        lettuce's own probe times the watering, and the refill is at least what it lost."""
        at = _dt.datetime(2026, 7, 1, 9, tzinfo=_dt.timezone.utc)
        g = Garden()
        tomato_top, _ = g.probe(lambda h: 0.29, depth=0.10, start=at - 52 * HOUR)
        tomato_deep, _ = g.probe(lambda h: 0.29, depth=0.40, start=at - 52 * HOUR)
        lettuce_top, _ = g.probe(lambda h: 0.23, depth=0.10, start=at - 52 * HOUR)
        g.bed = S.Bed(g.land, 0.30, 0.12, plantings=TOMATOES_AND_LETTUCE)
        unnamed, _ = g.advice(at)
        self.assertNotEqual(unnamed, "soil-water-now")
        (tomato, sown), (lettuce, sown_l) = TOMATOES_AND_LETTUCE
        g.bed = S.Bed(g.land, 0.30, 0.12, plantings=(
            (tomato, sown, (tomato_top.sensor, tomato_deep.sensor)),
            (lettuce, sown_l, (lettuce_top.sensor,))))
        rule, d = g.advice(at)
        c = d["context"]
        self.assertEqual(rule, "soil-water-now")
        self.assertAlmostEqual(c["timing_depletion_mm"], 0.07 * 150.0, places=1)
        self.assertAlmostEqual(c["depletion_mm"], 0.01 * c["root_depth_mm"], delta=0.2)
        self.assertEqual(c["refill_mm"], c["timing_depletion_mm"])
        with self.assertRaises(ValueError):
            S.Bed(g.land, 0.30, 0.12, plantings=(("tomato", sown, (), "extra"),))

    def test_by_the_weather_the_young_roots_time_it_too(self):
        g = WeatherGarden()
        station = g.station(8, rain={0: 80.0})
        at = TestByTheWeather.MORNING(4)
        g.bed = S.replace(g.bed, crop="tomato", planted=_dt.date(2026, 5, 1))
        self.assertEqual(g.advice(at, station=station)[0], "soil-weather-enough")
        g.bed = S.Bed(g.land, 0.30, 0.12, plantings=TOMATOES_AND_LETTUCE)
        rule, d = g.advice(at, station=station)
        self.assertEqual(rule, "soil-weather-water-now")
        self.assertIn("its shallowest roots, in the top 15 cm", S.render(d, "en"))


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestTheCropsClockByTheSeasonsWarmth(unittest.TestCase):
    """Sown on 1 July, the station's days 20 to 32 °C, a mean of 26 (`thermal`)."""

    def setUp(self):
        import thermal as T
        self.g = WeatherGarden()
        self.station = self.g.station(12)
        past = {}
        for y in range(2010, 2020):
            d = _dt.date(y, 1, 1)
            while d.year == y:
                past[d] = (14.0, 24.0)
                d += _dt.timedelta(days=1)
        self.normal = T.Normal(past)

    def context(self, advisor, crop):
        bed = S.replace(self.g.bed, crop=crop, planted=_dt.date(2026, 7, 1))
        return advisor.judge(self.g.state, bed, TestByTheWeather.MORNING(10),
                             station=self.station)["context"]

    def test_tomatoes_count_the_degree_days_they_have_gathered(self):
        """Over their base of 7: 19 a day for ten days, normal year or none."""
        for advisor in (S.Advisor(Log(), normal=self.normal), S.Advisor(Log())):
            c = self.context(advisor, "tomato")
            self.assertEqual((c["calendar_days"], c["by_warmth"]), (10, True))
            self.assertAlmostEqual(c["crop_gdd"], 190, delta=1)

    def test_a_station_put_up_after_sowing_clocks_it_only_with_the_normal_year(self):
        """Sown on 1 June; the station's first day is 1 July. Without the normal year to
        stand in for June, three quarters of the season is unknown: the calendar."""
        bed = S.replace(self.g.bed, crop="tomato", planted=_dt.date(2026, 6, 1))
        at = TestByTheWeather.MORNING(10)
        alone = S.Advisor(Log()).judge(self.g.state, bed, at, station=self.station)["context"]
        self.assertFalse(alone["by_warmth"])
        filled = S.Advisor(Log(), normal=self.normal).judge(self.g.state, bed, at,
                                                            station=self.station)["context"]
        self.assertTrue(filled["by_warmth"])
        self.assertAlmostEqual(filled["crop_gdd"], 30 * 12 + 10 * 19, delta=3)

    def test_cabbage_runs_ahead_of_its_days_in_a_warm_summer(self):
        """The revision has no degree-days for cabbage: its 1998 days run by this summer's
        21.5 degree-days a day over its base of 4.5 against the normal year's 14.5."""
        c = self.context(S.Advisor(Log(), normal=self.normal), "cabbage")
        self.assertEqual((c["calendar_days"], c["by_warmth"]), (10, True))
        self.assertAlmostEqual(c["crop_days"], 10 * 21.5 / 14.5, places=1)

    def test_without_the_farms_normal_year_cabbage_keeps_the_calendar(self):
        c = self.context(S.Advisor(Log()), "cabbage")
        self.assertEqual((c["calendar_days"], c["crop_days"], c["by_warmth"]), (10, 10, False))


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestLookingAheadToTomorrow(unittest.TestCase):
    """A bed with 15 cm of roots holds 27 mm its plants can use: a third gone is 9 mm, half
    gone 13.5. The advice comes once a morning, so it also waters a bed that, drying as it
    has been, would be past half gone before the next."""

    @staticmethod
    def soaked(mm_per_day, full_at=20, root_mm=150.0):
        """Soaked to 0.40 at midnight, drained back to 0.30 by hour `full_at`, drying at
        `mm_per_day` since."""
        per_h = mm_per_day / root_mm / 24.0
        return lambda h: (0.30 + 0.10 * (full_at - h) / full_at if h <= full_at
                          else 0.30 - per_h * (h - full_at))

    def shallow(self, mm_per_day):
        g = Garden()
        g.bed = S.replace(g.bed, root_depth_mm=150.0)
        g.probe(self.soaked(mm_per_day), depth=0.10)
        return g

    def test_drying_fast_it_is_watered_a_day_early_and_says_why(self):
        """6 mm a day since hour 20: 8 mm gone by the morning, short of the 9 at a third,
        but 14 by tomorrow, past the 13.5 at half."""
        g = self.shallow(6.0)
        rule, d = g.advice()
        self.assertEqual(rule, "soil-water-now")
        self.assertLess(d["context"]["depletion_mm"], g.bed.raw_mm)
        self.assertAlmostEqual(d["context"]["drying_mm_per_day"], 6.0, delta=0.3)
        self.assertEqual(d["message"]["key"], "soilwater.water_now_ahead")
        self.assertIn("it would be short of water before tomorrow morning", S.render(d, "en"))

    def test_drying_slowly_it_waits(self):
        rule, _ = self.shallow(3.0).advice()
        self.assertNotEqual(rule, "soil-water-now")

    def test_a_day_that_began_above_field_capacity_begins_there(self):
        """Still draining when the day measured began (hour 28; at field capacity only at
        31): the drainage is not the crop's drying. From 0.30 the day lost about 7 mm; from
        its first readings, over 8."""
        f = self.soaked(8.0, full_at=31)
        rows = [(T0 + h * HOUR, f(h)) for h in range(53)]
        with_cap = S._drying_mm_per_day(rows, MORNING, 150.0, 0.30)
        self.assertAlmostEqual(with_cap, 7.0, delta=0.4)
        self.assertGreater(S._drying_mm_per_day(rows, MORNING, 150.0), with_cap + 1.0)

    def test_part_of_a_day_is_no_rate(self):
        """A crop draws by day: under a whole day of readings, no rate is guessed."""
        rows = [(T0 + h * HOUR, 0.30 - 0.001 * h) for h in range(20)]
        self.assertEqual(S._drying_mm_per_day(rows, T0 + 19 * HOUR, 150.0), 0.0)

    def test_inches_for_a_us_reader(self):
        g = self.shallow(6.0)
        g.state.add(Label(uuid7(), g.land, "bed 3", T0, language="en"))
        _, d = g.advice()
        said = S.render(d, "en", g.state, units="us")
        self.assertIn(f"drying at {d['context']['drying_mm_per_day'] / 25.4:.2f} inches a day", said)
        self.assertIn("About 0.3 inches brings it back to field capacity", said)
        self.assertIn("pulgadas", S.render(d, "es", g.state, units="us"))

    def test_on_a_hot_day_fao_56_lowers_the_refill_point(self):
        """Drying about 9 mm a day with 16.5 mm gone: short of a third of 54 mm, and not past
        half by tomorrow, so the plain rule waits; FAO-56's Eq. 8.5 makes p under 0.2 that
        day, and it is due."""
        self.assertAlmostEqual(S.adjusted_p(1 / 3, 9.0), 1 / 3 - 0.16)
        self.assertEqual((S.adjusted_p(0.5, 0.0), S.adjusted_p(0.2, 20.0)), (0.7, 0.1))
        g = Garden()
        g.probe(lambda h: 0.245 + 0.03 * (52 - h) / 24.0)
        plain, d = g.advice()
        self.assertEqual(plain, "soil-water-soon")
        g.bed = S.replace(g.bed, adjust_p=True)
        rule, d = g.advice()
        self.assertEqual(rule, "soil-water-now")
        c = d["context"]
        self.assertAlmostEqual(c["depletion_fraction"],
                               S.adjusted_p(1 / 3, c["drying_mm_per_day"]), places=3)
        self.assertLess(c["depletion_fraction"], 0.2)
        # A mild day leaves it at a third: FAO-56 would raise it, which waits too long.
        g2 = Garden()
        g2.probe(lambda h: 0.245 + 0.004 * (52 - h) / 24.0)
        g2.bed = S.replace(g2.bed, adjust_p=True)
        self.assertAlmostEqual(g2.advice()[1]["context"]["depletion_fraction"], 1 / 3, places=3)

    def test_short_is_at_or_past_the_refill_point(self):
        with self.assertRaises(ValueError):
            S.Bed(uuid7(), 0.30, 0.12, depletion_fraction=0.4, short_fraction=0.3)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestABedUnderCover(unittest.TestCase):
    """`covered_by_its_probes`: three storms of 15 mm or more in the farm's gauge, while the
    valve stayed shut, none of which moved a probe, is a bed the rain does not reach."""

    @staticmethod
    def storms(days, mm=20.0):
        return [(T0 + (24 * d + h) * HOUR, mm / 4.0) for d in days for h in (10, 11, 12, 13)]

    @staticmethod
    def probe(rises_on=()):
        rows = []
        for h in range(24 * 12):
            day = h // 24
            wet = any(day > d or (day == d and h % 24 >= 14) for d in rises_on)
            rows.append((T0 + h * HOUR, 0.30 if wet else 0.22))
        return [rows]

    def test_three_storms_that_moved_nothing(self):
        covered, storms = S.covered_by_its_probes(self.storms((2, 5, 8)), self.probe(), [])
        self.assertEqual((covered, storms), (True, 3))

    def test_one_that_wet_the_soil_is_an_open_bed(self):
        covered, _ = S.covered_by_its_probes(self.storms((2, 5, 8)), self.probe(rises_on=(5,)), [])
        self.assertIsNone(covered)

    def test_light_rain_and_storms_on_watering_days_do_not_count(self):
        light = self.storms((2, 5, 8), mm=8.0)
        self.assertEqual(S.covered_by_its_probes(light, self.probe(), []), (None, 0))
        watered = [(T0 + (24 * 5 + 11) * HOUR, T0 + (24 * 5 + 12) * HOUR)]
        self.assertEqual(S.covered_by_its_probes(self.storms((2, 5, 8)), self.probe(), watered),
                         (None, 2))


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestRainComingOnACoveredBed(unittest.TestCase):

    def test_rain_that_cannot_reach_the_bed_does_not_hold_the_watering(self):
        g = Garden()
        g.probe(lambda h: 0.18)
        fc = g.rain(2.0)                                     # 2 mm an hour forecast
        self.assertEqual(g.advice(forecast=fc)[0], "soil-rain-coming")
        g.bed = S.replace(g.bed, rain_share=0.0)
        rule, d = g.advice(forecast=fc)
        self.assertEqual(rule, "soil-water-now")
        self.assertGreater(d["context"]["rain_mm"], 40.0)
        self.assertEqual(d["context"]["rain_reaching_mm"], 0.0)


class TestTheSoakTest(unittest.TestCase):
    """A person pours a measured amount of water on a square metre around a bed's probes
    (`regimens/soak_test.star`): the probes must rise, not past what soil can hold, and the
    level they drain back to is the bed's field capacity, measured on the day."""

    START = T0 + 20 * HOUR

    def run_soak(self, after, label=True):
        """The bed at 0.22 until the soak at hour 20; `after(hours since)` from then."""
        import regimen as G
        g = Garden()
        if label:
            g.state.add(Label(uuid7(), g.land, "bed 3", T0, language="en"))
        g.probe(lambda h: 0.22 if h <= 20 else after(h - 20), hours=20 + 54)
        runner = G.Runner(Log())
        start = runner.start(S.soak_test(), S.soak_start_context(g.state, g.bed, self.START),
                             self.START, subject=g.bed.feature)
        written = []
        for h in range(1, 54):
            when = self.START + h * HOUR
            written += runner.tick(when, lambda subject, run, w=when:
                                   S.soak_context(g.state, g.bed, run.started_at, w))
        return g, start, written

    @staticmethod
    def drains(peak=0.40, to=0.28):
        """Up to `peak` over two hours, then draining to `to` with τ four hours."""
        return lambda t: (0.22 + (peak - 0.22) * t / 2.0 if t <= 2
                          else to + (peak - to) * math.exp(-(t - 2) / 4.0) - 0.0002 * (t - 2))

    def test_it_asks_for_enough_water_to_wet_past_field_capacity(self):
        """0.30 − 0.22 + 0.05, over the 300 mm root zone: 39 litres on a square metre."""
        g, start, written = self.run_soak(self.drains())
        pour = written[0].payload
        self.assertEqual(pour["message"]["key"], "soilwater.soak.pour")
        self.assertAlmostEqual(pour["message"]["params"]["litres"], 39.0, delta=0.1)
        self.assertIn("pour 39 litres of water over a square metre", S.render(pour, "en", g.state))

    def test_a_good_soak_reports_the_level_it_drained_back_to(self):
        g, _, written = self.run_soak(self.drains())
        alerts = [e.payload for e in written if e.payload["alert"]]
        self.assertEqual([a["message"]["key"] for a in alerts],
                         ["soilwater.soak.pour", "soilwater.soak.drained"])
        report = alerts[-1]
        self.assertAlmostEqual(report["context"]["capacity_percent"], 28.0, delta=0.5)
        self.assertIn("drained back to 28", S.render(report, "en", g.state))

    def test_no_rise_is_said(self):
        g, _, written = self.run_soak(lambda t: 0.22)
        keys = [e.payload["message"]["key"] for e in written if e.payload["alert"]]
        self.assertIn("soilwater.soak.no_rise", keys)
        self.assertIn("soilwater.soak.not_drained", keys)

    def test_more_water_than_soil_can_hold_is_a_probe_reading_high(self):
        g, _, written = self.run_soak(self.drains(peak=0.62, to=0.45))
        keys = [e.payload["message"]["key"] for e in written if e.payload["alert"]]
        self.assertIn("soilwater.soak.too_high", keys)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestATensionSensorBesideTheProbe(unittest.TestCase):
    """A tension sensor at a probe's depth: each hour a point on the soil's retention curve,
    and the probe's field capacity is read off it at 33 kPa (`retention.py`), with no
    drain-down needed."""

    HOURS = 240

    def garden(self, tension_depth=0.20):
        from test_retention import silt_loam
        g = Garden()
        kpa = lambda h: 10.0 * 6.0 ** ((h % 96) / 95.0)        # drying from 10 to 60 kPa, four days
        g.probe(lambda h: silt_loam(kpa(h)), hours=self.HOURS)
        raw = FX.raw_datastream(unit="kPa", observed_property=V.SOIL_WATER_POTENTIAL,
                                expected_interval=3600.0, max_latency=3600.0)
        ds = FX.derived_datastream(raw, unit="kPa")
        cal = FX.calibration(raw.sensor, a=-1.0)
        for rec in (raw, ds, cal, Installation(uuid7(), raw.sensor, g.land, T0 - 24 * HOUR,
                                               depth_m=tension_depth)):
            g.state.add(rec)
        for h in range(self.HOURS + 1):
            g.state.add(FX.observation(ds, result=round(-kpa(h), 2), measured_at=T0 + h * HOUR,
                                       calibration=cal.id, seq=h))
        return g, silt_loam(33.0)

    def test_field_capacity_is_read_off_the_soils_own_curve(self):
        g, truth = self.garden()
        _, d = g.advice(T0 + (self.HOURS + 1) * HOUR)
        self.assertEqual(d["context"]["measured_probes"], 1)
        self.assertAlmostEqual(d["context"]["field_capacity"], truth, delta=0.01)
        self.assertEqual(d["inputs"]["learned"][0]["how"], "measured")

    def test_a_tension_sensor_at_another_depth_is_not_paired(self):
        g, _ = self.garden(tension_depth=0.40)
        _, d = g.advice(T0 + (self.HOURS + 1) * HOUR)
        self.assertEqual(d["context"]["measured_probes"], 0)


class TestTheCropThroughItsSeason(unittest.TestCase):
    """FAO-56's curve for a sown crop (`crop_day`): its crop coefficient by stage (the 2025
    revision's Table 6.1), and its roots from 15 cm at sowing to the shallow end of the
    maximum's range as mid-season begins; its stages in the 1998 days, or in the revision's
    degree-days (Table 6.11) where it gives them."""

    def test_tomatoes_from_sowing_to_the_end(self):
        """1998's 30, 40, 45 and 30 days; the revision's fresh market 0.60, 1.10 and 1.00,
        roots to 0.6 m."""
        self.assertEqual(S.crop_day("tomato", 0), (0.6, 150.0))
        kc, root = S.crop_day("tomato", 50)                     # half way through development
        self.assertAlmostEqual(kc, 0.6 + 0.5 * (1.10 - 0.6))
        self.assertAlmostEqual(root, 150.0 + 0.5 * (600.0 - 150.0))
        self.assertEqual(S.crop_day("tomato", 80), (1.10, 600.0))
        self.assertAlmostEqual(S.crop_day("tomato", 145)[0], 1.00)
        self.assertAlmostEqual(S.crop_day("tomato:processing", 400)[0], 0.85)

    def test_by_degree_days_where_the_revision_gives_them(self):
        """Fresh-market tomatoes: 325, 660, 880 and 200 degree-days (Table 6.11)."""
        kc, root = S.crop_day("tomato", 0, gdd=325 + 330)       # half way through development
        self.assertAlmostEqual(kc, 0.6 + 0.5 * (1.10 - 0.6))
        self.assertAlmostEqual(root, 150.0 + 0.5 * (600.0 - 150.0))
        self.assertEqual(S.crop_day("tomato", 0, gdd=1000), (1.10, 600.0))
        self.assertAlmostEqual(S.crop_day("tomato", 0, gdd=2100)[0], 1.00)
        self.assertEqual(S.crop_day("cabbage", 0, gdd=5000), S.crop_day("cabbage", 0),
                         "a crop the revision has no degree-days for keeps its days")

    def test_an_established_lawn_is_the_same_all_year(self):
        self.assertEqual(S.crop_day("turf_cool", 0), S.crop_day("turf_cool", 200))
        S.Bed(uuid7(), 0.30, 0.12, crop="turf_cool")             # no sowing date needed

    def test_the_revisions_mown_lawn_uses_less_than_1998s(self):
        """Table 6.4's lawn cut under 10 cm: 0.70 at its peak, held all year as the 1998
        lawns hold theirs, against 1998's 0.95 for cool-season turf."""
        self.assertEqual(S.crop_day("turf_lawn", 0), (0.70, 500.0))
        self.assertEqual(S.crop_day("turf_lawn", 300), S.crop_day("turf_lawn", 0))
        self.assertEqual(S.crop_day("turf_cool", 0)[0], 0.95)
        S.Bed(uuid7(), 0.30, 0.12, crop="turf_lawn")

    def test_a_sown_crop_needs_its_date_and_a_known_name(self):
        with self.assertRaises(ValueError):
            S.Bed(uuid7(), 0.30, 0.12, crop="tomato")
        with self.assertRaises(ValueError):
            S.Bed(uuid7(), 0.30, 0.12, crop="kohlrabi", planted=_dt.date(2026, 5, 1))

    def test_the_bed_is_as_its_crop_is_that_day(self):
        bed = S.Bed(uuid7(), 0.30, 0.12, crop="bean", planted=_dt.date(2026, 5, 1))
        young, grown = S.grown(bed, _dt.date(2026, 5, 10)), S.grown(bed, _dt.date(2026, 7, 1))
        self.assertEqual((young.root_depth_mm, young.crop_coefficient), (150.0, 0.5))
        self.assertEqual((grown.root_depth_mm, grown.crop_coefficient), (500.0, 1.05))
        self.assertLess(young.raw_mm, grown.raw_mm)
        plain = S.Bed(uuid7(), 0.30, 0.12)
        self.assertIs(S.grown(plain, _dt.date(2026, 7, 1)), plain)

    def test_the_crop_table_is_what_the_manifest_says(self):
        import csv
        import hashlib
        with open(os.path.join(HERE, "data", "MANIFEST.csv"), encoding="utf-8") as h:
            rows = list(csv.DictReader(line for line in h if not line.startswith("#")))
        self.assertEqual({r["file"] for r in rows}, {"fao56-crops.csv", "fao56rev-crops.csv"})
        for r in rows:
            with open(os.path.join(HERE, "data", r["file"]), "rb") as h:
                self.assertEqual(hashlib.sha256(h.read()).hexdigest(), r["sha256"])
        self.assertEqual(len([c for c in S.CROPS if ":" not in c]), 23, "20 sown, 3 lawns")
        self.assertEqual(S.CROPS["tomato"]["edition"], 2025)
        self.assertEqual(S.CROPS["turf_cool"]["edition"], 1998)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestAdviceForAGrowingCrop(unittest.TestCase):

    def test_a_seedlings_roots_do_not_reach_a_probe_a_grown_crops_do(self):
        """Ten days after sowing tomatoes have 15 cm of roots: a probe at 20 cm is below
        them, and the bed has no probe in its root zone. Eighty days on, it reads for 60 cm."""
        g = Garden()
        g.probe(lambda h: 0.25)
        g.bed = S.replace(g.bed, crop="tomato", planted=MORNING.date() - _dt.timedelta(days=10))
        rule, d = g.advice()
        self.assertEqual(rule, "soil-no-probe")
        self.assertEqual(d["context"]["root_depth_cm"], 15)
        g.bed = S.replace(g.bed, planted=MORNING.date() - _dt.timedelta(days=80))
        rule, d = g.advice()
        self.assertNotEqual(rule, "soil-no-probe")
        self.assertEqual(d["context"]["root_depth_cm"], 60)

    def test_the_balance_charges_a_young_crop_less(self):
        """Lettuce sown the day of the soaking: 0.7 of the reference ET through its first
        twenty days, where a bed with no crop named takes 1, and its 15 cm of roots pass the
        point where the crop slows sooner than 30 cm would: about 0.6 of the depletion."""
        g = WeatherGarden()
        station = g.station(12, rain={0: 80.0})
        at = TestByTheWeather.MORNING(8)
        plain = S.bed_context(g.state, g.bed, at, station=station)[0]["depletion_mm"]
        lettuce = S.replace(g.bed, crop="lettuce", planted=_dt.date(2026, 7, 1))
        young = S.bed_context(g.state, lettuce, at, station=station)[0]["depletion_mm"]
        self.assertLess(young, 0.7 * plain)
        self.assertGreater(young, 0.5 * plain)


class TestTheSoilsRootingLimit(unittest.TestCase):
    """`Bed.rooting_limit_mm`: how deep the soil lets roots go, whatever the crop."""

    def test_it_stops_the_crops_curve_and_a_beds_own_depth(self):
        planted = _dt.date(2026, 5, 1)
        tomato = S.Bed(uuid7(), 0.30, 0.12, crop="tomato", planted=planted,
                       rooting_limit_mm=400.0)
        self.assertEqual(S.grown(tomato, planted + _dt.timedelta(days=10)).root_depth_mm, 150.0)
        self.assertEqual(S.grown(tomato, planted + _dt.timedelta(days=80)).root_depth_mm, 400.0)
        plain = S.Bed(uuid7(), 0.30, 0.12, root_depth_mm=500.0, rooting_limit_mm=300.0)
        self.assertEqual(S.grown(plain, planted).root_depth_mm, 300.0)
        with self.assertRaises(ValueError):
            S.Bed(uuid7(), 0.30, 0.12, rooting_limit_mm=0.0)

    def test_a_probe_set_into_the_hardpan_is_not_counted(self):
        """A pan at 30 cm and probes at 10 and 30: the one at 30 reads the wet soil under the
        roots, and would make the bed look half as dry as it is."""
        g = Garden()
        g.probe(lambda h: 0.21, depth=0.10)
        g.probe(lambda h: 0.30, depth=0.30)
        g.bed = S.replace(g.bed, root_depth_mm=600.0, rooting_limit_mm=300.0)
        c = S.bed_context(g.state, g.bed, MORNING)[0]
        self.assertEqual((c["root_depth_cm"], c["probes"]), (30, 1))
        self.assertAlmostEqual(c["depletion_mm"], 27.0)


DAY_H = 24
#: Sixteen days of hourly readings, to midnight: two weeks of days to judge.
SIGNS_AT = T0 + 16 * DAY_H * HOUR


class TestRootsSeenByTheirProbes(unittest.TestCase):
    """`root_signs`: over two weeks, a probe whose soil keeps falling on its dry days, well
    below field capacity, has roots at it; one that stays level has none."""

    def signs(self, *thetas):
        g = Garden()
        for depth, theta in thetas:
            g.probe(theta, depth=depth, hours=16 * DAY_H)
        return S.root_signs(g.state, g.bed, SIGNS_AT)

    def test_falling_below_field_capacity_is_roots_and_level_is_none(self):
        signs = self.signs((0.10, lambda h: 0.29 - 0.006 * h / DAY_H),
                           (0.30, lambda h: 0.30))
        (d1, rate1, there1), (d2, rate2, there2) = signs
        self.assertEqual((d1, there1), (0.10, True))
        self.assertAlmostEqual(rate1, 0.006, places=4)
        self.assertEqual((d2, rate2, there2), (0.30, 0.0, False))

    def test_draining_just_past_field_capacity_is_not_yet_roots(self):
        """From 0.33 down 0.003 a day: as fast as roots would take it, but never 0.02 below
        field capacity, so it may be the soil draining."""
        (_, rate, there), = self.signs((0.60, lambda h: 0.33 - 0.003 * h / DAY_H))
        self.assertGreater(rate, S.ROOT_SIGN_RATE)
        self.assertIsNone(there)

    def test_a_day_the_soil_was_wetted_does_not_count(self):
        """Watered back to field capacity every morning at 06:00, falling 0.04 by the next:
        no whole day is dry, so there is nothing to say."""
        (_, rate, there), = self.signs((0.10, lambda h: 0.30 - 0.04 * ((h - 6) % DAY_H) / DAY_H))
        self.assertEqual((rate, there), (0.0, None))


def by_day(start, per_day):
    """Readings that fall `per_day` a day, all of it from 06:00 to 18:00: the stair-step."""
    def theta(h):
        days, hour = divmod(h, DAY_H)
        return start - per_day * (days + min(1.0, max(0.0, (hour - 6) / 12.0)))
    return theta


class TestTheStairStep(unittest.TestCase):
    """With the farm's timezone, `root_signs` reads the stair-step: roots draw by day. The
    test's farm keeps UTC."""

    def signs(self, theta, *, days=16, timezone="UTC"):
        g = Garden()
        g.probe(theta, depth=0.30, hours=days * DAY_H)
        return S.root_signs(g.state, g.bed, T0 + days * DAY_H * HOUR, timezone)

    def test_falling_by_day_is_roots_before_the_soil_is_far_under_field_capacity(self):
        """0.003 a day for five days: 0.015 down, not yet 0.02 under field capacity."""
        theta = by_day(0.30, 0.003)
        (_, _, there), = self.signs(theta, days=5)
        self.assertIs(there, True)
        (_, _, there), = self.signs(theta, days=5, timezone=None)
        self.assertIsNone(there)

    def test_falling_by_night_as_by_day_is_no_roots(self):
        """0.004 a day around the clock, as water draining or creeping up to roots above:
        well under field capacity in a fortnight, which without the clock looks like roots."""
        theta = lambda h: 0.30 - 0.004 * h / DAY_H
        (_, _, there), = self.signs(theta)
        self.assertIs(there, False)
        (_, _, there), = self.signs(theta, timezone=None)
        self.assertIs(there, True)

    def test_its_days_run_04_00_to_04_00_on_the_farms_clock(self):
        at = _dt.datetime(2026, 7, 10, 9, tzinfo=_dt.timezone.utc)      # 04:00 in Chicago
        begin, end, day = S._sign_days(at, "America/Chicago")[0]
        self.assertEqual((begin.hour, end, day), (9, at, _dt.date(2026, 7, 9)))


class TestTheRootsTheAdviceCounts(unittest.TestCase):
    """`rooted`: the probes only ever make the root zone shallower than the crop's curve."""

    def test_a_level_probe_the_roots_should_have_passed_stops_them_half_way(self):
        signs = [(0.10, 0.006, True), (0.30, 0.0, False), (0.60, 0.0, False)]
        self.assertEqual(S.rooted(700.0, signs), (200.0, 0.10, 0.30))

    def test_not_until_the_curve_is_15_cm_past_it(self):
        signs = [(0.10, 0.006, True), (0.30, 0.0, False)]
        self.assertEqual(S.rooted(400.0, signs), (400.0, 0.10, None))
        self.assertEqual(S.rooted(450.0, signs), (200.0, 0.10, 0.30))

    def test_a_stop_that_stands_holds_on_a_morning_that_cannot_see_it(self):
        """Waterings left the probe at 10 cm too few dry days to judge by this morning."""
        signs = [(0.10, 0.0, None), (0.30, 0.0, False)]
        self.assertEqual(S.rooted(700.0, signs), (700.0, 0.0, None))
        self.assertEqual(S.rooted(700.0, signs, held=(0.10, 0.30)), (200.0, 0.10, 0.30))
        self.assertEqual(S.rooted(400.0, signs, held=(0.10, 0.30)), (400.0, 0.0, None),
                         "and only where the curve is 15 cm past the probe")

    def test_roots_deeper_than_the_curve_are_not_counted(self):
        signs = [(0.10, 0.006, True), (0.60, 0.004, True)]
        self.assertEqual(S.rooted(400.0, signs), (400.0, 0.60, None))

    def test_with_no_roots_seen_a_level_probe_says_nothing(self):
        signs = [(0.10, 0.003, None), (0.30, 0.0, False)]
        self.assertEqual(S.rooted(700.0, signs), (700.0, 0.0, None))

    def test_the_deepest_roots_seen_are_the_ones_counted_from(self):
        signs = [(0.10, 0.0, False), (0.30, 0.005, True), (0.60, 0.0, False)]
        self.assertEqual(S.rooted(800.0, signs), (450.0, 0.30, 0.60))


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestRootsThatStop(unittest.TestCase):
    """Tomatoes 80 days from sowing should have roots to 60 cm. The probe at 10 cm dries well
    below field capacity, the one at 30 cm stays level: something stops the roots between
    them. The advice times its watering by the top 20 cm, still refills to 60, and says
    so."""

    def garden(self, **bed):
        g = Garden()
        g.probe(lambda h: 0.29 - 0.006 * h / DAY_H, depth=0.10, hours=16 * DAY_H)
        g.probe(lambda h: 0.30, depth=0.30, hours=16 * DAY_H)
        g.bed = S.replace(g.bed, crop="tomato",
                          planted=SIGNS_AT.date() - _dt.timedelta(days=80), **bed)
        return g

    def test_the_advice_is_timed_by_the_top_and_a_note_says_why(self):
        g = self.garden()
        log = Log()
        out = S.Advisor(log).advise(g.state, [g.bed], SIGNS_AT)
        advice, note = (e.payload for e in out)
        c = advice["context"]
        self.assertEqual((c["roots_expected_cm"], c["root_depth_cm"], c["timing_depth_cm"],
                          c["roots_seen_cm"], c["roots_blocked_cm"]), (60, 60, 20, 10, 30))
        self.assertEqual(note["rule"], "soil-roots-blocked")
        text = S.render(note, "en")
        self.assertIn("about 60 cm", text)
        self.assertIn("at 30 cm has stayed level", text)
        self.assertIn("when the top 20 cm has used its share, and still refills to 60 cm", text)
        self.assertIn("rooting limit", text)
        self.assertIn("30 cm", S.render(note, "es"))
        us = S.render(note, "en", units="us")
        self.assertIn("about 24 inches", us)
        self.assertIn("at 12 inches has stayed level", us)
        self.assertIn("12 pulgadas", S.render(note, "es", units="us"))

    def test_with_its_rooting_limit_set_the_advice_takes_it_and_says_nothing(self):
        """Set at 25 cm, as the note asks: the roots are counted to it, and the probe at
        30 cm is no longer one they should have passed."""
        g = self.garden(rooting_limit_mm=250.0)
        out = S.Advisor(Log()).advise(g.state, [g.bed], SIGNS_AT)
        self.assertEqual(len(out), 1)
        c = out[0].payload["context"]
        self.assertEqual((c["roots_expected_cm"], c["root_depth_cm"], c["roots_blocked"]),
                         (25, 25, False))

    def test_a_stop_stands_once_seen_on_three_of_the_last_seven_mornings(self):
        g = self.garden()
        log = Log()
        advisor = S.Advisor(log)

        def morning(days_ago, blocked):
            when = SIGNS_AT - _dt.timedelta(days=days_ago)
            log.append(S.R.DECISION, {
                "subject": str(g.bed.feature), "topic": f"advice/{g.bed.feature}",
                "evaluated_at": when.isoformat(), "rule": "soil-soon",
                "context": {"roots_blocked": blocked, "roots_seen_cm": 10, "roots_blocked_cm": 30}})
        for days_ago, blocked in ((9, True), (8, True), (6, True), (5, False), (3, True)):
            morning(days_ago, blocked)
        self.assertIsNone(advisor._held(g.bed, SIGNS_AT), "two in the last week")
        morning(1, True)
        self.assertEqual(advisor._held(g.bed, SIGNS_AT), (0.10, 0.30))

    def test_a_bed_with_no_crop_named_reads_no_signs(self):
        g = Garden()
        g.probe(lambda h: 0.29 - 0.006 * h / DAY_H, depth=0.10, hours=16 * DAY_H)
        g.probe(lambda h: 0.30, depth=0.30, hours=16 * DAY_H)
        g.bed = S.replace(g.bed, root_depth_mm=500.0)
        c = S.Advisor(Log()).judge(g.state, g.bed, SIGNS_AT)["context"]
        self.assertEqual((c["root_depth_cm"], c["roots_blocked"]), (50, False))


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestByTheWeather(unittest.TestCase):
    """A bed with no probe, advised from the farm's own station (`weather_balance`)."""

    MORNING = staticmethod(lambda day: _dt.datetime(2026, 7, 1, 9, tzinfo=_dt.timezone.utc)
                           + _dt.timedelta(days=day))

    def test_without_a_station_it_still_says_no_probe(self):
        g = WeatherGarden()
        self.assertEqual(g.advice(self.MORNING(5))[0], "soil-no-probe")

    def test_a_soaking_then_dry_days_until_it_is_due(self):
        g = WeatherGarden()
        station = g.station(12, rain={0: 80.0})
        rules = [g.advice(self.MORNING(d), station=station)[0] for d in (2, 5)]
        self.assertEqual(rules, ["soil-weather-enough", "soil-weather-water-now"])
        _, d = g.advice(self.MORNING(5), station=station)
        self.assertGreaterEqual(d["context"]["depletion_mm"], g.bed.raw_mm)
        self.assertEqual(d["message"]["key"], "soilwater.weather_water_now_unrecorded",
                         "with no valve recorded, it says it cannot see the watering")
        self.assertEqual(d["inputs"]["estimated"], ["wind"])

    def test_two_days_of_three_missing_and_it_cannot_tell(self):
        g = WeatherGarden()
        station = g.station(12, rain={0: 80.0}, gap_days=(8, 9))
        rule, d = g.advice(self.MORNING(10), station=station)
        self.assertEqual(rule, "soil-weather-unseen")
        self.assertIn("Check the station", S.render(d, "en"))

    def test_a_recorded_watering_refills_it(self):
        from model import ClockQuality, Observation
        g = WeatherGarden()
        station = g.station(12, rain={0: 80.0})
        valve = FX.raw_datastream(unit=None, observed_property=V.VALVE_OPEN)
        g.state.add(valve)
        opened = _dt.datetime(2026, 7, 6, 10, tzinfo=_dt.timezone.utc)
        for when, state in ((opened, True), (opened + _dt.timedelta(hours=2), False)):
            g.state.add(Observation(uuid7(), valve.id, when, 1.0, when, state,
                                    ClockQuality.NETWORK, node="opensprinkler", boot=1, seq=1))
        g.bed = S.replace(g.bed, valve=valve.id, application_mm_per_h=15.0)
        rule, d = g.advice(self.MORNING(6), station=station)
        self.assertEqual(rule, "soil-weather-enough")
        self.assertTrue(d["context"]["watering_recorded"])

    def test_with_no_record_of_watering_its_own_advice_is_taken_as_followed(self):
        g = WeatherGarden()
        station = g.station(12, rain={0: 80.0})
        advisor = S.Advisor(Log())
        [due] = advisor.advise(g.state, [g.bed], self.MORNING(5), station=station)
        self.assertEqual(due.payload["rule"], "soil-weather-water-now")
        [next_day] = advisor.advise(g.state, [g.bed], self.MORNING(6), station=station)
        self.assertEqual(next_day.payload["rule"], "soil-weather-enough")
        [fresh] = S.Advisor(Log()).advise(g.state, [g.bed], self.MORNING(6), station=station)
        self.assertEqual(fresh.payload["rule"], "soil-weather-water-now",
                         "an advisory with no memory of its advice sees no watering")

    def test_a_silent_probe_is_carried_on_the_weather_from_its_last_good_reading(self):
        """Heard until 11 July, then silent: three days on, with the station, the advice
        goes on from the probe's last reading, and says to check the probe. Without the
        station, there is no advice, as before."""
        g = WeatherGarden()
        station = g.station(15, rain={0: 80.0})
        g.probe(lambda h: 0.25, hours=24)
        rule, d = g.advice(self.MORNING(13), station=station)
        self.assertEqual(rule, "soil-weather-water-now")
        self.assertTrue(d["context"]["anchored"])
        self.assertGreater(d["context"]["probe_silent_hours"], 72)
        self.assertGreater(d["context"]["depletion_mm"], 0.05 * 300.0,
                           "more gone than at the last reading, by the weather since")
        self.assertIn("check the probes", S.render(d, "en"))
        self.assertEqual(g.advice(self.MORNING(13))[0], "soil-unseen")

    def test_a_flagged_reading_is_not_the_anchor(self):
        g = WeatherGarden()
        station = g.station(15, rain={0: 80.0})
        _, obs = g.probe(lambda h: 0.25 if h < 40 else 0.05, hours=48)
        for o in obs[40:]:
            g.state.add(FX.assertion(o.id, flags={QualityFlag.OUT_OF_RANGE}, check="range",
                                     asserted_at=o.received_at))
        at = T0 + 48 * HOUR + 5 * HOUR
        rule, d = g.advice(at, station=station)
        self.assertTrue(d["context"]["anchored"])
        self.assertAlmostEqual(d["context"]["probe_silent_hours"], 14.0, delta=1.0)
        self.assertLess(d["context"]["depletion_mm"], 0.10 * 300.0,
                        "anchored on 0.25, not the flagged 0.05")


    def test_a_reading_out_of_the_soil_is_not_the_anchor(self):
        g = WeatherGarden()
        station = g.station(15, rain={0: 80.0})
        g.probe(lambda h: 0.25 if h < 40 else 0.01, hours=48)
        rule, d = g.advice(T0 + 48 * HOUR + 5 * HOUR, station=station)
        self.assertTrue(d["context"]["anchored"])
        self.assertTrue(d["context"]["out_of_soil"])
        self.assertLess(d["context"]["depletion_mm"], 0.10 * 300.0,
                        "anchored on 0.25, not the air's 0.01")

class ReferenceGarden(WeatherGarden):
    """The weather garden's station, rain of 30 mm on days 0, 5, 10 and 15, and a second bed
    nearby whose probe dries at `share` of the balance's `Kc · ETo`: each rain lifts it to
    0.34, it drains to 0.28 within hours, and its root zone then runs down at that rate."""

    START = _dt.datetime(2026, 7, 1, 5, tzinfo=_dt.timezone.utc)      # local midnight, day 0
    RAIN_DAYS = (0, 5, 10, 15)

    def __init__(self, share, *, days=20, silent_after_h=None):
        super().__init__()
        import eto as E
        self.station_ = self.station(days, rain={d: 30.0 for d in self.RAIN_DAYS})
        day = self.START.astimezone(_dt.timezone(-_dt.timedelta(hours=5))).date() + _dt.timedelta(days=2)
        self.eto_mm = E.eto_of(self.station_, day, E.summaries(
            self.state, self.station_, day, day, self.morning(days - 1))[day])[0]
        self.reference_land = uuid7()
        self.reference = S.Bed(self.reference_land, field_capacity=0.30, wilting_point=0.12)
        per_h = share * self.eto_mm / 300.0 / 24.0
        wettings = [24.0 * d + 8.0 for d in self.RAIN_DAYS]

        def theta(h):
            since = [h - w for w in wettings if h >= w]
            if not since:
                return 0.28
            t = since[-1]
            return 0.28 + 0.06 * math.exp(-t / 3.0) - per_h * t
        self.theta = theta
        self.probe(theta, hours=24 * days, land=self.reference_land, start=self.START)

    def morning(self, day):
        return self.START + _dt.timedelta(days=day, hours=4)


class TestAProbeCorrectsTheWeather(unittest.TestCase):
    """A bed with no probe takes the rate a probe in a bed nearby sees its root zone run down,
    on dry days, against what the balance says for them (`reference_factor`)."""

    def test_it_reads_the_share_of_the_balances_et_the_probe_sees(self):
        g = ReferenceGarden(0.7)
        found = S.reference_factor(g.state, g.reference, g.station_, g.morning(19))
        self.assertAlmostEqual(found["factor"], 0.7, delta=0.03)
        self.assertEqual(found["days"], 15, "days 1-4, 6-9, 11-14 and 16-18; rain days are wet")

    def test_a_probe_that_has_not_learned_its_level_corrects_nothing(self):
        """A probe reading high sees each spell's first depletion as water above field
        capacity; until its drain-downs have taught it its own level, it is not used."""
        g = ReferenceGarden(0.7)
        self.assertIsNone(S.reference_factor(g.state, S.replace(g.reference, learn=False),
                                             g.station_, g.morning(19)))

    def test_a_rate_out_of_bounds_is_a_fault_not_a_correction(self):
        g = ReferenceGarden(0.3)
        self.assertIsNone(S.reference_factor(g.state, g.reference, g.station_, g.morning(19)))

    def test_too_few_dry_days_and_there_is_nothing_to_say(self):
        g = ReferenceGarden(0.7, days=8)
        self.assertIsNone(S.reference_factor(g.state, g.reference, g.station_, g.morning(7)))

    def test_a_bed_cannot_be_its_own_reference(self):
        land = uuid7()
        with self.assertRaises(ValueError):
            S.Bed(land, field_capacity=0.30, wilting_point=0.12, reference=land)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestAdviceCorrectedByAProbeNearby(unittest.TestCase):

    def test_the_balance_moves_halfway_to_a_slower_rate_and_says_so(self):
        g = ReferenceGarden(0.7)
        at = g.morning(19)
        bed = S.replace(g.bed, reference=g.reference_land)
        [plain] = S.Advisor(Log()).advise(g.state, [g.bed], at, station=g.station_)
        events = S.Advisor(Log()).advise(g.state, [bed, g.reference], at, station=g.station_)
        corrected = next(e.payload for e in events if e.payload["subject"] == str(g.land))
        ctx = corrected["context"]
        self.assertTrue(ctx["corrected"])
        self.assertAlmostEqual(ctx["et_percent"], 85, delta=2, msg="halfway from 100% to 70%")
        self.assertAlmostEqual(ctx["depletion_mm"] / plain.payload["context"]["depletion_mm"],
                               0.85, delta=0.05)
        self.assertEqual(corrected["inputs"]["reference"]["bed"], str(g.reference_land))
        self.assertTrue(corrected["message"]["key"].endswith("_corrected"))
        g.state.add(Label(uuid7(), g.land, "bed 3", T0, language="en"))
        self.assertIn("by the farm's weather, with its water use set at "
                      f"{ctx['et_percent']:.0f}% of the weather's estimate from a probe in a bed nearby",
                      S.render(corrected, "en", g.state))
        self.assertIn("una sonda en un bancal cercano", S.render(corrected, "es", g.state))

    def test_a_faster_rate_is_taken_all_the_way(self):
        """More water is the safe error."""
        g = ReferenceGarden(1.2)
        bed = S.replace(g.bed, reference=g.reference_land)
        events = S.Advisor(Log()).advise(g.state, [bed, g.reference], g.morning(19),
                                         station=g.station_)
        ctx = next(e.payload["context"] for e in events if e.payload["subject"] == str(g.land))
        self.assertAlmostEqual(ctx["et_percent"], 120, delta=2)

    def test_without_its_reference_among_the_beds_it_is_the_balance_alone(self):
        g = ReferenceGarden(0.7)
        bed = S.replace(g.bed, reference=g.reference_land)
        [d] = S.Advisor(Log()).advise(g.state, [bed], g.morning(19), station=g.station_)
        self.assertFalse(d.payload["context"]["corrected"])

    def test_a_bed_whose_probe_falls_silent_takes_its_own_probes_rate(self):
        """The probe is in the bed itself and stops at the end of day 16. Two mornings later
        the fallback carries the bed on the weather, at the rate its probe saw before."""
        g = ReferenceGarden(0.7, days=17)
        station = g.station(20, rain={d: 30.0 for d in g.RAIN_DAYS})
        d = S.Advisor(Log()).judge(g.state, g.reference, g.morning(19), station=station)
        self.assertTrue(d["context"]["anchored"])
        self.assertTrue(d["context"]["corrected"])
        self.assertAlmostEqual(d["context"]["et_percent"], 85, delta=2)
        self.assertTrue(d["message"]["key"].endswith("_anchored"),
                        "the probes' silence is the message; the rate is in the record")


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestByTheWeatherOnARecordedSummer(unittest.TestCase):
    """The backtest bed with no probe, advised from a station on the farm, on McAllister
    Farm's summer of 2013, its watering unrecorded (`weather_backtest`)."""

    @classmethod
    def setUpClass(cls):
        import irrigation_drill as D
        import physics as ph
        cls.r = S.weather_backtest(ph.RecordedClimate.from_csv(D.SUMMER, seed=1),
                                   _dt.datetime(2013, 6, 1, tzinfo=_dt.timezone.utc), 92,
                                   seed=1, record_valve=False)

    def test_it_waters_about_as_the_probe_does_and_far_less_than_a_timer(self):
        """The probe-led advice used 155 mm and the drip timer 552 on the same summer."""
        self.assertAlmostEqual(self.r["applied_mm"], 155.0, delta=0.25 * 155.0)
        self.assertEqual(self.r["stressed_h"], 0.0)

    def test_a_station_installed_today_has_no_estimate_for_two_days(self):
        self.assertEqual(self.r["advice"]["soil-weather-unseen"], 2)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestAProbeNearbyOnTheDrought(unittest.TestCase):
    """The backtest bed with no probe through the 2012 drought, its watering unrecorded, a
    bed of the same soil and crop beside it with a probe (`weather_backtest`). By the
    weather alone it was given 314.4 mm with no stressed hour. Over thirty summers a true
    reference took that to 237 mm a summer on average, never short (README)."""

    @classmethod
    def setUpClass(cls):
        import physics as ph
        path = os.path.join(HERE, os.pardir, os.pardir, "sim", "data", "mcallister-2012-summer.csv")
        start = _dt.datetime(2012, 6, 1, tzinfo=_dt.timezone.utc)
        cls.r = {bias: S.weather_backtest(ph.RecordedClimate.from_csv(path, seed=1), start, 92,
                                          seed=1, record_valve=False, reference=True,
                                          reference_bias=bias)
                 for bias in (0.0, 0.05)}

    def test_a_probe_that_has_not_learned_its_level_by_the_drought_corrects_nothing(self):
        """Watered on its own advice through the drought, the reference's probe saw too few
        drain-downs to learn its own field capacity, so it never corrected the bed."""
        r = self.r[0.0]
        self.assertAlmostEqual(r["applied_mm"], 314.4, delta=0.5)
        self.assertEqual(r["stressed_h"], 0.0)

    def test_a_probe_reading_high_never_learns_and_so_corrects_nothing(self):
        """Uncorrected, such a probe took the bed to 397 stressed hours."""
        r = self.r[0.05]
        self.assertAlmostEqual(r["applied_mm"], 314.4, delta=0.5)
        self.assertEqual(r["stressed_h"], 0.0)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestEachProbesNoise(unittest.TestCase):
    """A backtest's probes draw their noise from a stream each, so runs with a probe more
    or less are set side by side on the same noise for the probes they share."""

    @staticmethod
    def draws(streams):
        return [[r.gauss(0.0, 1.0) for _ in range(50)] for r in streams]

    def test_a_probe_added_leaves_the_others_draws_as_they_were(self):
        two = self.draws(S.noise_streams(1, ["0.1 False", "0.3 False"]))
        three = self.draws(S.noise_streams(1, ["0.1 False", "0.3 False", "0.6 False"]))
        self.assertEqual(two, three[:2])

    def test_one_probe_draws_the_seeds_own_stream_as_before(self):
        import random
        (one,) = self.draws(S.noise_streams(7, ["0.2 False"]))
        before = random.Random(7)
        self.assertEqual(one, [before.gauss(0.0, 1.0) for _ in range(50)])

    def test_each_probe_draws_its_own(self):
        a, b, c = self.draws(S.noise_streams(1, ["0.1 False", "0.3 False", "0.1 True"]))
        self.assertNotEqual(a, b)
        self.assertNotEqual(b, c)


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
class TestLearningOnTheVirtualFarm(unittest.TestCase):
    """A yard the soil survey does not describe: 10 cm of brought-in sandy loam over a
    compacted clay subsoil, roots in the top 15 cm (`physics.LayeredBed`), on McAllister
    Farm's recorded summers. The survey says silt loam, field capacity 0.30 and wilting
    point 0.12. A soil test of each layer says 0.20 and 0.09 for the topsoil, 0.38 and
    0.25 for the clay."""

    SURVEY = (0.30, 0.12)

    @classmethod
    def setUpClass(cls):
        import irrigation_drill as D
        import physics as ph

        def run(year, depths, learn, configured=cls.SURVEY, layers=()):
            path = os.path.join(HERE, os.pardir, os.pardir, "sim", "data",
                                f"mcallister-{year}-summer.csv")
            yard = ph.LayeredBed(name="yard", depth_mm=150,
                                 horizons=(ph.Horizon(100, **ph.SANDY_LOAM),
                                           ph.Horizon(500, **ph.COMPACTED_CLAY)))
            return S.backtest(ph.RecordedClimate.from_csv(path, seed=1),
                              _dt.datetime(year, 6, 1, tzinfo=_dt.timezone.utc), 92, seed=1,
                              soil=yard, depths=depths, configured=configured, learn=learn,
                              layers=layers)
        cls.topsoil = {learn: run(2013, (0.05,), learn) for learn in (False, True)}
        cls.survey_2012 = run(2012, (0.05, 0.12), True)
        cls.tested_2012 = run(2012, (0.05, 0.12), True, (0.38, 0.25), ((0.10, 0.20, 0.09),))

    def test_one_probe_in_the_topsoil_on_the_surveys_values_drowns_the_yard(self):
        """It reads the topsoil at 0.23 as a quarter short of 0.30 and waters most days:
        about 680 mm in the summer of 2013, nearly all of it drained past the roots."""
        r = self.topsoil[False]
        self.assertGreater(r["applied_mm"], 600)
        self.assertGreater(r["advice"]["soil-water-now"], 45)

    def test_learning_the_topsoils_own_capacity_it_waters_a_quarter_as_much(self):
        off, on = self.topsoil[False], self.topsoil[True]
        self.assertLess(on["applied_mm"], 0.3 * off["applied_mm"])
        self.assertLess(on["drained_mm"], 0.4 * off["drained_mm"])
        self.assertEqual(on["stressed_h"], 0.0)
        self.assertAlmostEqual(on["field_capacity"], 0.23, delta=0.02)

    def test_a_probe_in_each_layer_learns_each_layer_and_says_it_is_layered(self):
        learned = {x["depth_m"]: x for x in self.survey_2012["learned"]}
        self.assertAlmostEqual(learned[0.05]["field_capacity"], 0.23, delta=0.02)
        self.assertAlmostEqual(learned[0.12]["field_capacity"], 0.40, delta=0.02)
        self.assertTrue(self.survey_2012["layered"])

    def test_given_each_layers_values_as_the_note_asks_it_waits_less(self):
        """One wilting point for two soils counts water the clay holds and the roots
        cannot take, so through the dry summer of 2012 the advice waited too long: 31
        hours of stress. With each layer's own values, and the capacities still learned,
        16, and no note. Not none: the roots hold about 17 mm they can use, and a hot day
        can take that past half between two mornings. Looking ahead a day (`short_fraction`)
        took the survey's 116 hours to 31; over thirty summers it took this yard from short
        in 18 to short in 8."""
        self.assertGreater(self.survey_2012["stressed_h"], 20)
        self.assertLess(self.tested_2012["stressed_h"], 0.6 * self.survey_2012["stressed_h"])
        self.assertFalse(self.tested_2012["layered"])


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestAProbeThatReadsOff(unittest.TestCase):
    """An uncalibrated probe reads high or low by the same amount all summer. On the
    advisory's backtest bed, McAllister Farm's 2013, where a true probe's advice used
    155 mm (docs/notes/soil-sensors.md)."""

    @classmethod
    def setUpClass(cls):
        import irrigation_drill as D
        import physics as ph
        start = _dt.datetime(2013, 6, 1, tzinfo=_dt.timezone.utc)
        cls.r = {bias: S.backtest(ph.RecordedClimate.from_csv(D.SUMMER, seed=1), start, 92,
                                  seed=1, probe_bias=bias)
                 for bias in (-0.05, 0.05)}

    def test_reading_low_it_learns_its_own_full_and_waters_far_less_than_unlearned(self):
        """Unlearned, a probe 0.05 low called for 748 mm. Learning, its drain-downs say
        where its full is, 0.05 low too, and the advice uses 256 mm."""
        low = self.r[-0.05]
        self.assertAlmostEqual(low["field_capacity"], 0.25, delta=0.02)
        self.assertLess(low["applied_mm"], 300)

    def test_reading_high_it_never_waters_and_so_never_learns(self):
        """A probe 0.05 high says the bed is full, so it is not watered, so the probe
        sees too few soakings to learn from: the bed goes dry. A second probe in the bed,
        and the cross-check between them, is what catches this."""
        high = self.r[0.05]
        self.assertEqual(high["field_capacity"], 0.30)
        self.assertLess(high["applied_mm"], 50)
        self.assertGreater(high["stressed_h"], 100)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestAProbeOutageCarriedOnTheWeather(unittest.TestCase):
    """The backtest bed with its probe and a station, through the 2012 drought, the probe's
    radio down for two weeks in July (`weather_backtest`)."""

    @classmethod
    def setUpClass(cls):
        import physics as ph
        path = os.path.join(HERE, os.pardir, os.pardir, "sim", "data", "mcallister-2012-summer.csv")
        start = _dt.datetime(2012, 6, 1, tzinfo=_dt.timezone.utc)
        cls.r = {fallback: S.weather_backtest(ph.RecordedClimate.from_csv(path, seed=1), start,
                                              92, seed=1, probe=True, outage=(30, 43),
                                              fallback=fallback)
                 for fallback in (False, True)}

    def test_without_the_fallback_two_weeks_without_advice_dry_the_bed(self):
        r = self.r[False]
        self.assertEqual(r["advice"]["soil-unseen"], 13)
        self.assertGreater(r["stressed_h"], 100)

    def test_with_it_the_advice_goes_on_and_the_bed_is_never_short(self):
        r = self.r[True]
        self.assertNotIn("soil-unseen", r["advice"])
        self.assertGreater(r["advice"]["soil-weather-water-now"], 0)
        self.assertEqual(r["stressed_h"], 0.0)


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestHarrowBend(unittest.TestCase):
    """Six beds every morning for eight days: the far bed node's radio is out from day 5
    to day 8, and on day 4 a probe is lifted out of bed 6 and pushed into bed 2."""

    @classmethod
    def setUpClass(cls):
        import harrow_bend as hb
        cls.farm = hb.build(seed=1)
        hb.season(cls.farm, days=8.0)
        # Roots to 35 cm: the probe moved into bed 2 at 30 cm is among them.
        cls.beds = {f"bed{k}": S.Bed(cls.farm.features[f"bed{k}"]["id"],
                                     field_capacity=0.30, wilting_point=0.12,
                                     root_depth_mm=350.0)
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

    def test_its_manifest_declares_the_stations_series_and_the_valves(self):
        """The balance reads a station's weather and a bed's valve; a sown crop's clock, its
        air temperature. A grant can give no more than the manifest declares."""
        manifest = self.M.Manifest.load(os.path.join(HERE, "module.json"))
        self.M.grant(Log(), manifest, properties=[
            V.AIR_TEMPERATURE, V.RELATIVE_HUMIDITY, V.SOLAR_RADIATION, V.WIND_SPEED,
            V.PRECIPITATION_DEPTH, V.VALVE_OPEN, V.SOIL_WATER, V.SOIL_WATER_POTENTIAL])

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

    def test_with_the_valve_reporting_it_says_which_of_the_two_it_was(self):
        """An OpenSprinkler's station through the MQTT bridge: on a blocked day the valve
        ran and no water came; on a forgotten one it never opened."""
        import irrigation_drill as D
        import physics as ph
        start = _dt.datetime(2013, 6, 1, tzinfo=_dt.timezone.utc)
        r = S.backtest(ph.RecordedClimate.from_csv(D.SUMMER, seed=1), start, 92, seed=1,
                       check=S.watering_check(), blocked=frozenset({14, 46, 90}),
                       forgotten=frozenset({30, 78}), valve=True)
        said = {c["day"]: c["key"] for c in r["checks"] if c["alert"]}
        self.assertEqual(said, {14: "soilwater.regimen.no_water_arrived",
                                46: "soilwater.regimen.no_water_arrived",
                                90: "soilwater.regimen.no_water_arrived",
                                30: "soilwater.regimen.not_watered",
                                78: "soilwater.regimen.not_watered"})
        self.assertTrue(all(not c["alert"] for c in r["checks"] if c["day"] not in said))

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



class TestValveMinutes(unittest.TestCase):
    """How long a valve stood open, from its open-and-shut series (vocab.VALVE_OPEN)."""

    def setUp(self):
        import vocab as V
        from model import ClockQuality, Datastream, Observation
        self.Obs, self.CQ = Observation, ClockQuality
        self.state = State()
        self.valve = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(), feature=uuid7(),
                                observed_property=V.VALVE_OPEN, kind=DatastreamKind.RAW, unit=None)
        self.state.add(self.valve)
        self.t0 = _dt.datetime(2026, 7, 14, 4, tzinfo=_dt.timezone.utc)
        self.seq = 0

    def says(self, minutes, is_open, *, late=0):
        self.seq += 1
        when = self.t0 + _dt.timedelta(minutes=minutes)
        self.state.add(self.Obs(uuid7(), self.valve.id, when, 1.0,
                                when + _dt.timedelta(minutes=late), is_open, self.CQ.NETWORK,
                                node="os", boot=1, seq=self.seq))

    def minutes(self, until=600):
        return S.valve_minutes(self.state, self.valve.id, self.t0,
                               self.t0 + _dt.timedelta(minutes=until))

    def test_an_opening_and_a_closing(self):
        self.says(-60, False)
        self.says(60, True)
        self.says(150, False)
        self.assertEqual(self.minutes(), (True, 90.0))

    def test_shut_all_along_is_known_and_none(self):
        self.says(-60, False)
        self.assertEqual(self.minutes(), (True, 0.0))

    def test_never_heard_from_is_not_known(self):
        self.assertEqual(self.minutes(), (False, 0.0))

    def test_a_closing_never_seen_opening_is_a_lost_message_not_a_shut_valve(self):
        self.says(150, False)
        self.assertEqual(self.minutes(), (False, 0.0))

    def test_open_across_the_window_counts_from_its_start_to_now(self):
        self.says(-30, True)
        self.assertEqual(self.minutes(until=45), (True, 45.0))

    def test_a_report_not_yet_received_is_not_known_yet(self):
        self.says(-60, False)
        self.says(60, True, late=600)
        self.assertEqual(self.minutes(until=120), (True, 0.0))


if __name__ == "__main__":
    unittest.main()
