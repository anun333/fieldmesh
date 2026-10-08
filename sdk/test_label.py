#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for §1 labels: names that are not keys, can change, and keep their history."""
from __future__ import annotations

import datetime as _dt
import tempfile
import unittest

import export as X
import fixtures as fx
import log as L
import project as P
import sensorthings as ST
from ids import uuid7
from model import Label

UTC = _dt.timezone.utc


def when(month, day=1):
    return _dt.datetime(2026, month, day, tzinfo=UTC)


def label(entity, name, *, at, language="en", supersedes=None):
    return Label(id=uuid7(), entity=entity, name=name, language=language,
                 set_at=at, supersedes=supersedes)


class TestRename(unittest.TestCase):

    def setUp(self):
        self.bed = uuid7()
        self.log = L.Log()
        self.first = label(self.bed, "north bed", at=when(3))
        self.log.append_record(self.first)
        self.second = label(self.bed, "tomato house", at=when(7),
                            supersedes=self.first.id)
        self.log.append_record(self.second)
        self.state = P.state_from_log(self.log)

    def test_the_current_name_is_the_rename(self):
        self.assertEqual(self.state.label_for(self.bed).name, "tomato house")

    def test_the_old_name_still_finds_the_entity(self):
        """A certifier's report from spring says "north bed". The bed has been renamed
        since. The question "which entity was that?" must still have an answer."""
        self.assertEqual(self.state.entities_named("north bed"), [self.bed])
        self.assertEqual(self.state.entities_named("  North Bed "), [self.bed],
                         "the report was typed by a person")

    def test_what_it_was_called_at_a_given_time(self):
        self.assertEqual(self.state.label_as_of(self.bed, when(5)).name, "north bed")
        self.assertEqual(self.state.label_as_of(self.bed, when(8)).name,
                         "tomato house")
        self.assertIsNone(self.state.label_as_of(self.bed, when(1)))

    def test_the_history_keeps_both(self):
        self.assertEqual([l.name for l in self.state.label_history(self.bed)],
                         ["north bed", "tomato house"])

    def test_a_rename_cannot_move_a_name_to_another_entity(self):
        """Superseding another entity's label would let a rename silently re-point a
        name, which is the one thing §1's separation of names from keys prevents."""
        other = uuid7()
        self.log.append_record(label(other, "stolen", at=when(8),
                                     supersedes=self.second.id))
        problems = P.state_from_log(self.log).validate()
        self.assertTrue(any("different entity" in p for p in problems), problems)


class TestLanguages(unittest.TestCase):

    def setUp(self):
        self.bed = uuid7()
        log = L.Log()
        for name, language in (("bed 1", "en"), ("cama 1", "es-MX")):
            log.append_record(label(self.bed, name, at=when(3), language=language))
        self.state = P.state_from_log(log)

    def test_exact_language(self):
        self.assertEqual(self.state.label_for(self.bed, "es-MX").name, "cama 1")

    def test_a_primary_tag_finds_a_regional_label(self):
        self.assertEqual(self.state.label_for(self.bed, "es").name, "cama 1")

    def test_a_different_region_falls_back_to_the_same_language(self):
        """A farm that labelled in Mexican Spanish should not look untranslated to a
        visitor from Spain."""
        self.assertEqual(self.state.label_for(self.bed, "es-ES").name, "cama 1")

    def test_a_missing_language_falls_back_and_reports_which(self):
        found = self.state.label_for(self.bed, "fr")
        self.assertEqual(found.name, "bed 1")
        self.assertEqual(found.language, "en")

    def test_no_fallback_when_asked_for_none(self):
        self.assertIsNone(self.state.label_for(self.bed, "fr", fallback=()))


class TestValidation(unittest.TestCase):

    def test_an_empty_name_is_refused(self):
        with self.assertRaises(ValueError):
            label(uuid7(), "   ", at=when(1))

    def test_surrounding_whitespace_is_refused(self):
        """'north bed ' and 'north bed' would be two names for one thing."""
        with self.assertRaises(ValueError):
            label(uuid7(), "north bed ", at=when(1))

    def test_a_language_must_be_a_tag(self):
        with self.assertRaises(ValueError):
            label(uuid7(), "x", at=when(1), language="Spanish")


class TestLabelsReachTheClients(unittest.TestCase):

    def setUp(self):
        self.ds = fx.raw_datastream()
        self.log = L.Log()
        self.log.append_record(self.ds)
        self.log.append_record(label(self.ds.feature, "bed 1", at=when(3)))
        self.log.append_record(label(self.ds.feature, "cama 1", at=when(3),
                                     language="es"))
        self.log.append_record(label(self.ds.id, "bed 1 moisture", at=when(3)))
        self.state = P.state_from_log(self.log)

    def test_sensorthings_names_come_from_the_log(self):
        svc = ST.Service(self.state)
        self.assertEqual(svc.feature_of_interest(self.ds.feature)["name"], "bed 1")
        self.assertEqual(svc.datastream(self.ds)["name"], "bed 1 moisture")

    def test_sensorthings_in_spanish(self):
        svc = ST.Service(self.state, language="es")
        doc = svc.feature_of_interest(self.ds.feature)
        self.assertEqual(doc["name"], "cama 1")
        self.assertEqual(doc["properties"]["nameLanguage"], "es")

    def test_an_untranslated_name_is_marked_rather_than_passed_off(self):
        """Asked for Spanish, given English — and told so."""
        doc = ST.Service(self.state, language="es").datastream(self.ds)
        self.assertEqual(doc["name"], "bed 1 moisture")
        self.assertEqual(doc["properties"]["nameLanguage"], "en")

    def test_an_explicit_override_still_wins(self):
        svc = ST.Service(self.state, labels={self.ds.feature: {"name": "override"}})
        self.assertEqual(svc.feature_of_interest(self.ds.feature)["name"], "override")

    def test_labels_are_exported_and_survive_a_round_trip(self):
        directory = tempfile.mkdtemp()
        manifest = X.export_log(self.log, directory, geojson=False)
        self.assertIn("labels.csv", {f.name for f in manifest.files})
        back = P.state_from_log(X.import_log(directory))
        self.assertEqual(back.label_for(self.ds.feature, "es").name, "cama 1")


if __name__ == "__main__":
    unittest.main()
