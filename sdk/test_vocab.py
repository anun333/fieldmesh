#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for the observed-property vocabulary (Q4, decided 2026-10-07).

These are mostly guards rather than behaviour tests, because the failure this module
prevents is not a crash — it is a plausible-looking URI that nobody can resolve, which
no amount of running the code will reveal.
"""
from __future__ import annotations

import pathlib
import unittest

import vocab as V

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestTerms(unittest.TestCase):

    def test_every_term_has_a_known_source(self):
        for uri in V.TERMS:
            self.assertNotEqual(V.source_of(uri), "unknown", uri)

    def test_every_term_is_an_absolute_http_uri_ending_in_a_slash(self):
        # The trailing slash is not cosmetic: both vocabulary servers redirect the
        # slashless form, and a redirect is a different identifier to a dumb client.
        for uri in V.TERMS:
            self.assertRegex(uri, r"^https?://")
            self.assertTrue(uri.endswith("/"), uri)

    def test_soil_water_is_the_volumetric_cf_name_not_the_invented_one(self):
        """The specific error this module was written to fix.

        `soil_moisture_content` is not in the CF table at any version, and the real
        CF names that look closest are mass-based (kg m-2). A dimensionless series
        declared under a mass-based term is wrong in a way that still validates.
        """
        self.assertEqual(
            V.SOIL_WATER,
            "http://vocab.nerc.ac.uk/standard_name/"
            "volume_fraction_of_condensed_water_in_soil/")
        self.assertNotIn("soil_moisture_content", V.SOIL_WATER)
        self.assertEqual(V.TERMS[V.SOIL_WATER][0], "cm3/cm3")

    def test_odm2_rssi_keeps_odm2s_spelling(self):
        """Their identifier, their spelling. A corrected URI resolves to nothing."""
        self.assertIn("Strenght", V.RSSI)

    def test_local_terms_are_counted(self):
        """Adding a local term must be a deliberate act.

        A local term is a small admission that the shared vocabularies did not cover
        something, and the cost of letting them accumulate silently is the
        interoperability principle failing quietly. Breaking this test is the
        reminder to publish the gap upstream — update the number when you have.
        """
        self.assertEqual(sorted(V.local_terms()), sorted([V.VESSEL_FILL_FRACTION, V.VALVE_OPEN]))

    def test_fill_fraction_is_not_declared_as_a_length(self):
        """Why the local term is local: ODM2 `waterLevel` is metres, this is a ratio."""
        self.assertEqual(V.TERMS[V.VESSEL_FILL_FRACTION][0], "1")
        self.assertNotIn("waterLevel", V.VESSEL_FILL_FRACTION)

    def test_source_of_answers_for_unseen_uris(self):
        self.assertEqual(V.source_of(V.CF + "wind_speed/"), "CF")
        self.assertEqual(V.source_of("http://example.invalid/x"), "unknown")


class TestTheGate(unittest.TestCase):
    """§3.4 enforced at declaration, offline."""

    def test_a_registered_term_in_an_accepted_unit_passes(self):
        self.assertEqual(V.check(V.SOIL_WATER, "cm3/cm3"), [])
        self.assertEqual(V.check(V.SOIL_WATER, "%"), [])
        self.assertEqual(V.check(V.AIR_TEMPERATURE, "K"), [])

    def test_the_invented_term_that_started_all_this_is_refused(self):
        problems = V.check("http://vocab.example.org/cf/soil_moisture_content",
                           "cm3/cm3")
        self.assertTrue(problems)
        self.assertIn("not a registered term", problems[0])

    def test_a_unit_from_the_wrong_dimension_is_refused(self):
        """Celsius under soil moisture — the unit lie a test of ours committed."""
        problems = V.check(V.SOIL_WATER, "Cel")
        self.assertTrue(problems)
        self.assertIn("not a unit of", problems[0])

    def test_a_measured_quantity_with_no_unit_is_refused(self):
        self.assertTrue(V.check(V.BATTERY_VOLTAGE, None))

    def test_every_registered_term_has_accepted_units_including_its_own(self):
        for uri, (unit, _) in V.TERMS.items():
            with self.subTest(term=uri):
                if unit is None:
                    continue                      # a truth: the next test
                self.assertIn(unit, V.ACCEPTED_UNITS.get(uri, frozenset({unit})))
                self.assertIn(uri, V.ACCEPTED_UNITS)

    def test_a_truth_takes_no_unit_and_refuses_one(self):
        """A valve is open or shut (§3.4: a boolean datastream has no unit)."""
        self.assertEqual(V.check(V.VALVE_OPEN, None), [])
        for unit in ("1", "%", "s"):
            self.assertTrue(V.check(V.VALVE_OPEN, unit), unit)
        self.assertTrue(V.check(V.VALVE_OPEN, "1", raw=True), "not even a raw count")

    def test_validate_reports_a_bad_declaration(self):
        import fixtures as fx
        import log as L
        import project as P
        log = L.Log()
        log.append_record(fx.raw_datastream(unit="Cel"))
        problems = P.state_from_log(log).validate()
        self.assertTrue(any("not a unit of" in p for p in problems), problems)


class TestRawUnits(unittest.TestCase):
    """Q21: a raw series of scaled integers declares `1`; the scale is the calibration's."""

    def _farm(self, raw_unit, a):
        import fixtures as fx
        import log as L
        import project as P
        raw = fx.raw_datastream(unit=raw_unit, observed_property=V.SOIL_TEMPERATURE)
        derived = fx.derived_datastream(raw, unit="Cel")
        from dataclasses import replace
        cal = replace(fx.calibration(raw.sensor, a=a), datastream=raw.id)
        log = L.Log()
        for r in (raw, derived, cal):
            log.append_record(r)
        return P.state_from_log(log).validate()

    def test_a_raw_count_may_declare_one_whatever_its_term(self):
        self.assertEqual(V.check(V.SOIL_TEMPERATURE, "1", raw=True), [])
        self.assertTrue(V.check(V.SOIL_TEMPERATURE, "1"), "a derived series is in Celsius")

    def test_a_scaled_raw_series_claiming_the_calibrated_unit_is_reported(self):
        problems = self._farm("Cel", a=0.1)          # node sends 215 for 21.5 C
        self.assertTrue(any("(Q21)" in p for p in problems), problems)

    def test_declaring_one_satisfies_it(self):
        self.assertEqual([p for p in self._farm("1", a=0.1) if "Q21" in p], [])

    def test_a_small_correction_is_not_a_scale(self):
        self.assertEqual([p for p in self._farm("Cel", a=1.02) if "Q21" in p], [])

    def test_harrow_bend_declares_its_raw_counts_as_one(self):
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "sim"))
        import harrow_bend as hb
        farm = hb.build(seed=1)
        soil = [s.raw for s in farm.series.values() if s.raw.observed_property == V.SOIL_WATER]
        self.assertTrue(soil)
        self.assertEqual({r.unit for r in soil}, {V.RAW_COUNT})
        self.assertEqual([p for p in farm.state.validate() if "Q21" in p], [])


class TestNoPlaceholdersAnywhere(unittest.TestCase):

    def test_no_example_org_vocabulary_uris_survive_in_the_repository(self):
        """A repo-wide grep, because the placeholders were spread across four files
        and the fifth would have been missed by anything narrower."""
        offenders = []
        for path in list(ROOT.rglob("*.py")) + list(ROOT.rglob("*.md")):
            if ".git" in path.parts or path.name == "test_vocab.py":
                continue
            if "vocab.example.org" in path.read_text(errors="replace"):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
