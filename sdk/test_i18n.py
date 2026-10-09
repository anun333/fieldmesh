#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for language packs. Most are guards that run over every pack on disk, so a
university contributing a new language gets these checks without writing any."""
from __future__ import annotations

import unittest

import checks as C
import fixtures as fx
import i18n
import log as L
import model as M
import project as P
import sensorthings as ST
import vocab as V


class TestTheEnglishSourceIsComplete(unittest.TestCase):
    """Adding an enum value or a vocabulary term without a string fails here, rather
    than surfacing as a raw code in a farmer's interface."""

    def setUp(self):
        self.en = i18n.load("en").strings

    def test_every_enum_value_has_a_string(self):
        for cls in (M.ClockQuality, M.DatastreamKind, M.QualityFlag, M.Usable,
                    M.Assertor, M.DeviceKind, M.MaintenanceAction, P.Health):
            for member in cls:
                with self.subTest(enum=cls.__name__, value=member.value):
                    self.assertIn(f"enum.{cls.__name__}.{member.value}", self.en)

    def test_every_vocabulary_term_has_a_name(self):
        for uri in V.TERMS:
            self.assertIn(f"term.{uri}", self.en)

    def test_every_unit_the_vocabulary_accepts_has_a_name(self):
        """Not only each term's default unit — every unit the gate lets a datastream
        be declared in, or a farm declaring kelvin sees the bare code."""
        units = {u for accepted in V.ACCEPTED_UNITS.values() for u in accepted}
        units |= {unit for unit, _ in V.TERMS.values()}
        for unit in sorted(units):
            self.assertIn(f"unit.{unit}", self.en)


class TestEveryPackOnDisk(unittest.TestCase):
    """Run over whatever packs exist — including ones contributed after this was
    written."""

    def test_there_is_more_than_one_language(self):
        self.assertGreaterEqual(len(i18n.available()), 2)

    def test_every_pack_is_sound(self):
        for tag in i18n.available():
            with self.subTest(pack=tag):
                self.assertEqual(i18n.check_pack(tag), [])

    def test_every_template_renders_in_every_pack(self):
        """Feed each template the fields its English source uses, as numbers. A
        translation that cannot render would otherwise surface only in production."""
        source = i18n.load("en").strings
        for tag in i18n.available():
            translator = i18n.Translator(tag)
            for key, template in source.items():
                params = {name: 1.5 for name in i18n.fields_of(template)}
                with self.subTest(pack=tag, key=key):
                    rendered = translator.text(key, **params)
                    self.assertNotEqual(rendered.text, key)


class TestFieldChecking(unittest.TestCase):

    def _with(self, strings):
        pack = i18n.Pack(tag="zz", name="Test", native_name="Test", direction="ltr",
                         status="draft", strings=strings, note="test pack")
        i18n._CACHE["zz"] = pack
        self.addCleanup(i18n._CACHE.pop, "zz", None)

    def test_a_dropped_field_is_caught(self):
        """A translation that drops `{max}` silently loses the number a farmer needs."""
        self._with({"check.range.above": "{value} is too high"})
        problems = i18n.check_pack("zz")
        self.assertTrue(any("dropped field" in p for p in problems), problems)

    def test_a_misspelt_field_is_caught(self):
        self._with({"check.range.above": "{value} > {maxx}"})
        self.assertTrue(i18n.check_pack("zz"))

    def test_an_unknown_key_is_caught(self):
        self._with({"check.range.abvoe": "{value} > {max}"})
        self.assertTrue(any("not a key" in p for p in i18n.check_pack("zz")))

    def test_a_broken_translation_falls_back_instead_of_crashing(self):
        """Rendering never raises in front of a farmer."""
        self._with({"check.range.above": "{value} > {maxx}"})
        rendered = i18n.Translator("zz").text("check.range.above", value=1, max=2)
        self.assertEqual(rendered.text, "1 above max 2")
        self.assertTrue(rendered.fell_back)

    def test_a_draft_must_say_what_it_needs(self):
        i18n._CACHE["zz"] = i18n.Pack(tag="zz", name="T", native_name="T",
                                      direction="ltr", status="draft", strings={})
        self.addCleanup(i18n._CACHE.pop, "zz", None)
        self.assertTrue(any("note" in p for p in i18n.check_pack("zz")))


class TestFallback(unittest.TestCase):

    def test_a_language_with_no_pack_falls_back_and_says_so(self):
        """The bug the first version had: English first in the chain was treated as
        'not a fallback', so French rendered silently in English."""
        rendered = i18n.Translator("fr").text("check.range.above", value=1, max=2)
        self.assertEqual(rendered.language, "en")
        self.assertTrue(rendered.fell_back)

    def test_a_regional_tag_uses_its_language(self):
        rendered = i18n.Translator("es-CO").enum(M.QualityFlag.SUSPECT)
        self.assertEqual(rendered.text, "sospechosa")
        self.assertFalse(rendered.fell_back)

    def test_fallbacks_are_counted_so_a_deployment_can_report_its_gaps(self):
        translator = i18n.Translator("fr")
        translator.enum(M.Usable.GOOD)
        self.assertIn("enum.Usable.good", translator.fallbacks)


class TestNumbersAreRegional(unittest.TestCase):
    """Spanish does not decide the decimal separator; the region does."""

    def test_spain_uses_a_comma(self):
        text = i18n.Translator("es").text("check.range.above", value=0.52, max=0.46)
        self.assertIn("0,52", str(text))

    def test_thousands_in_spain_group_with_a_point(self):
        """'20,696' is twenty in Spain: grouped thousands follow the decimal convention."""
        self.assertEqual(format(i18n._Number(20696.4, ","), ",.0f"), "20.696")
        self.assertEqual(format(i18n._Number(20696.45, ","), ",.1f"), "20.696,5")
        self.assertEqual(format(i18n._Number(20696.4, "."), ",.0f"), "20,696")

    def test_mexico_uses_a_point(self):
        text = i18n.Translator("es-MX").text("check.range.above", value=0.52, max=0.46)
        self.assertIn("0.52", str(text))

    def test_data_is_never_localised(self):
        """Only rendered text changes. The stored parameter is still a number."""
        ds = fx.raw_datastream()
        obs = fx.observation(ds, result=0.52)
        finding = C.check_range(obs, [], {"min": 0.0, "max": 0.46}, [])
        self.assertEqual(finding.params["value"], 0.52)
        self.assertIsInstance(finding.params["value"], float)


class TestTheLogRendersInAnyLanguage(unittest.TestCase):
    """The property the whole design rests on: an assertion stored once, in codes,
    rendered later in a language nobody chose when it was written."""

    def setUp(self):
        ds = fx.raw_datastream(thresholds={"min": 0.0, "max": 0.46})
        log = L.Log()
        log.append_record(ds)
        obs = fx.observation(ds, result=0.52)
        log.append_record(obs)
        state = P.state_from_log(log)
        self.assertion = C.assess(state, obs)

    def test_the_english_note_is_still_a_sentence(self):
        self.assertIn("0.52 above max 0.46", self.assertion.note)

    def test_the_same_record_renders_in_spanish(self):
        message = self.assertion.evidence["messages"]["range"]
        text = i18n.Translator("es").text(message["key"], **message["params"])
        self.assertEqual(str(text), "0,52 está por encima del máximo de 0,46")

    def test_the_flag_is_a_code_and_renders_separately(self):
        self.assertIn(M.QualityFlag.OUT_OF_RANGE, self.assertion.flags)
        self.assertEqual(
            str(i18n.Translator("es").enum(M.QualityFlag.OUT_OF_RANGE)),
            "fuera de rango")


class TestSensorThingsSpeaksTheLanguage(unittest.TestCase):

    def setUp(self):
        ds = fx.raw_datastream()
        log = L.Log()
        log.append_record(ds)
        self.state, self.ds = P.state_from_log(log), ds

    def test_observed_property_names_come_from_the_pack(self):
        doc = ST.Service(self.state, language="es").observed_property(
            V.SOIL_WATER)
        self.assertEqual(doc["name"], "contenido volumétrico de agua en el suelo")
        self.assertEqual(doc["properties"]["nameLanguage"], "es")

    def test_the_unit_symbol_stays_a_code_in_every_language(self):
        """A client converting units needs `cm3/cm3`, not a translation of it."""
        unit = ST.Service(self.state, language="es").unit_of_measurement(self.ds)
        self.assertEqual(unit["symbol"], "cm3/cm3")
        self.assertEqual(unit["name"], "centímetro cúbico por centímetro cúbico")


class TestScaffold(unittest.TestCase):

    def test_a_new_pack_starts_with_every_key_empty(self):
        doc = i18n.scaffold("sw", name="Swahili", native_name="Kiswahili")
        self.assertEqual(set(doc["strings"]), set(i18n.load("en").strings))
        self.assertTrue(all(v == "" for v in doc["strings"].values()))
        self.assertEqual(doc["_meta"]["status"], "draft")

    def test_a_right_to_left_language_says_so(self):
        doc = i18n.scaffold("ar", name="Arabic", native_name="العربية",
                            direction="rtl")
        self.assertEqual(doc["_meta"]["direction"], "rtl")


if __name__ == "__main__":
    unittest.main()
