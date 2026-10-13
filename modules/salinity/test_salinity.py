#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The salinity monitor: a probe's bulk conductivity to the pore water's and to a saturated
paste's, crop tolerances, and alerts raised and cleared as a tunnel bed's salt climbs."""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
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
from model import Installation, Label  # noqa: E402
from project import State  # noqa: E402

import salinity as SA  # noqa: E402

UTC = _dt.timezone.utc
HOUR = _dt.timedelta(hours=1)
T0 = _dt.datetime(2026, 5, 1, tzinfo=UTC)


class TestFromTheProbeToTheCropsScale(unittest.TestCase):

    def test_topps_curve_both_ways(self):
        self.assertAlmostEqual(SA.topp_water(20.0), 0.3454, places=4)
        self.assertAlmostEqual(SA.topp_permittivity(0.3454), 20.0, places=2)

    def test_hilhorst_by_hand(self):
        """0.3 dS/m bulk, at the water Topp gives a permittivity of 20, at 20 °C:
        80.3 × 0.3 / (20 − 4.1) = 1.515 dS/m in the pore water."""
        self.assertAlmostEqual(SA.pore_water_ec(0.3, SA.topp_water(20.0), 20.0), 1.515, places=3)

    def test_too_dry_to_say(self):
        self.assertIsNone(SA.pore_water_ec(0.3, 0.08, 20.0))

    def test_the_manuals_worked_example(self):
        """METER's TEROS 11/12 manual: 0.1 water, pore water at 0.7 dS/m, bulk density 1.5:
        a saturation extract of 0.162 dS/m, the porosity rounded to 0.43 on the way; 0.161
        unrounded."""
        self.assertAlmostEqual(SA.saturation_extract_ec(0.7, 0.1, 1.5), 0.162, delta=0.001)

    def test_the_tolerances_are_maas_and_grattans_and_the_manifest_holds(self):
        self.assertEqual(len(SA.CROPS), 25)
        self.assertEqual((SA.CROPS["bean"]["threshold"], SA.CROPS["bean"]["slope"]), (1.0, 19.0))
        self.assertEqual((SA.CROPS["tomato"]["threshold"], SA.CROPS["tomato"]["slope"]), (2.5, 9.9))
        with open(os.path.join(HERE, "data", "MANIFEST.csv"), encoding="utf-8") as h:
            rows = list(csv.DictReader(line for line in h if not line.startswith("#")))
        for r in rows:
            with open(os.path.join(HERE, "data", r["file"]), "rb") as h:
                self.assertEqual(hashlib.sha256(h.read()).hexdigest(), r["sha256"], r["file"])


class TunnelBed:
    """A bed with a TEROS-12-like probe at 15 cm: water, bulk conductivity and temperature
    from one body, hourly; the conductivity from `bulk(h)`."""

    def __init__(self, crop="lettuce"):
        self.state = State()
        self.land = uuid7()
        self.bed = SA.SaltBed(self.land, crop=crop, bulk_density=1.4)
        self.state.add(Label(uuid7(), self.land, "tunnel bed 2", T0, language="en"))
        self.state.add(Label(uuid7(), self.land, "bancal del túnel 2", T0, language="es"))
        sensor = uuid7()
        self.ds = {}
        for role, prop, unit in (("water", V.SOIL_WATER, "cm3/cm3"), ("conductivity", V.BULK_EC, "dS/m"),
                                 ("temperature", V.SOIL_TEMPERATURE, "Cel")):
            raw = FX.raw_datastream(sensor=sensor, unit=unit if role != "water" else "1",
                                    observed_property=prop, expected_interval=3600.0, max_latency=3600.0)
            ds = FX.derived_datastream(raw, unit=unit)
            for rec in (raw, ds):
                self.state.add(rec)
            self.ds[role] = ds
        self.cal = FX.calibration(sensor)
        self.state.add(self.cal)
        self.state.add(Installation(uuid7(), sensor, self.land, T0 - 24 * HOUR, depth_m=0.15))
        self.n = 0

    def hours(self, count, bulk, *, water=0.30, temperature=20.0):
        for _ in range(count):
            when = T0 + self.n * HOUR
            for role, value in (("water", water), ("conductivity", bulk(self.n)),
                                ("temperature", temperature)):
                self.state.add(FX.observation(self.ds[role], result=value, measured_at=when,
                                              calibration=self.cal.id, seq=self.n % 65536))
            self.n += 1
        return T0 + self.n * HOUR


def bulk_for(ece, *, water=0.30, temperature=20.0, bulk_density=1.4):
    """The bulk conductivity a probe reads for a soil whose saturated paste would read `ece`."""
    porosity = 1.0 - bulk_density / 2.65
    pore = ece * porosity / water
    eb = SA.topp_permittivity(water)
    return pore * (eb - 4.1) / (80.3 - 0.37 * (temperature - 20.0))


@unittest.skipUnless(HAVE_CEL, "cel-python is not installed (modules/rules/requirements.txt)")
class TestTheMonitor(unittest.TestCase):

    def test_climbing_then_past_lettuces_threshold_then_washed_out(self):
        """Lettuce's yield starts to fall at 1.3 dS/m and loses 13% per dS/m beyond."""
        g = TunnelBed("lettuce")
        monitor = SA.Monitor(Log())
        at = g.hours(7 * 24, lambda h: bulk_for(0.6))
        self.assertEqual(monitor.check(g.state, [g.bed], at), [], "half the threshold: nothing")
        at = g.hours(7 * 24, lambda h: bulk_for(1.12))
        [rising] = monitor.check(g.state, [g.bed], at)
        self.assertEqual(rising.payload["rule"], "salt-rising")
        self.assertIn("Salt in tunnel bed 2 is climbing: about 1.1 dS/m", SA.render(rising.payload, "en", g.state))
        self.assertIn("rendimiento de lechuga", SA.render(rising.payload, "es", g.state))
        at = g.hours(7 * 24, lambda h: bulk_for(2.3))
        written = monitor.check(g.state, [g.bed], at)
        self.assertEqual({(e.payload["rule"], e.payload["alert"]) for e in written},
                         {("salt-over", True), ("salt-rising", False)})
        over = next(e for e in written if e.payload["rule"] == "salt-over")
        self.assertAlmostEqual(over.payload["context"]["ece"], 2.3, delta=0.02)
        self.assertEqual(over.payload["context"]["loss_percent"], 13.0)
        self.assertIn("about 13% of it is lost", SA.render(over.payload, "en", g.state))
        at = g.hours(7 * 24, lambda h: bulk_for(0.5))
        cleared = monitor.check(g.state, [g.bed], at)
        self.assertEqual({(e.payload["rule"], e.payload["alert"]) for e in cleared}, {("salt-over", False)})

    def test_wetter_soil_reads_higher_bulk_but_the_same_salt(self):
        """The same salt at two water contents: the bulk conductivity differs, the estimate
        does not."""
        g = TunnelBed("tomato")
        ece = []
        for water in (0.22, 0.34):
            at = g.hours(7 * 24, lambda h, w=water: bulk_for(2.0, water=w), water=water)
            ece.append(SA.salt_context(g.state, g.bed, at)[0]["ece"])
        self.assertAlmostEqual(ece[0], 2.0, delta=0.02)
        self.assertAlmostEqual(ece[1], 2.0, delta=0.02)

    def test_a_dry_or_new_probe_says_nothing(self):
        g = TunnelBed("bean")
        at = g.hours(7 * 24, lambda h: bulk_for(3.0, water=0.08), water=0.08)
        self.assertEqual(SA.Monitor(Log()).check(g.state, [g.bed], at), [], "too dry to compute")
        n = TunnelBed("bean")
        at = n.hours(12, lambda h: bulk_for(3.0))
        self.assertEqual(SA.Monitor(Log()).check(n.state, [n.bed], at), [], "under a day of readings")

    def test_an_unknown_crop_is_refused(self):
        with self.assertRaises(ValueError):
            SA.SaltBed(uuid7(), crop="okra")


if __name__ == "__main__":
    unittest.main()
