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
        self.assertEqual(V.local_terms(), [V.VESSEL_FILL_FRACTION])

    def test_fill_fraction_is_not_declared_as_a_length(self):
        """Why the local term is local: ODM2 `waterLevel` is metres, this is a ratio."""
        self.assertEqual(V.TERMS[V.VESSEL_FILL_FRACTION][0], "1")
        self.assertNotIn("waterLevel", V.VESSEL_FILL_FRACTION)

    def test_source_of_answers_for_unseen_uris(self):
        self.assertEqual(V.source_of(V.CF + "wind_speed/"), "CF")
        self.assertEqual(V.source_of("http://example.invalid/x"), "unknown")


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
