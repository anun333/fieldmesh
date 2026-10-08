#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the OData query subset."""
from __future__ import annotations

import datetime as _dt
import unittest

import odata

UTC = _dt.timezone.utc


def ok(expr: str, doc: dict) -> bool:
    return odata.matches(odata.parse_filter(expr), doc)


class TestLiterals(unittest.TestCase):

    def test_numbers_strings_booleans_and_null(self):
        doc = {"n": 3, "f": 0.25, "s": "bed1", "b": True, "z": None}
        self.assertTrue(ok("n eq 3", doc))
        self.assertTrue(ok("f eq 0.25", doc))
        self.assertTrue(ok("s eq 'bed1'", doc))
        self.assertTrue(ok("b eq true", doc))
        self.assertTrue(ok("z eq null", doc))
        self.assertFalse(ok("z ne null", doc))

    def test_quote_doubling_inside_a_string(self):
        self.assertTrue(ok("s eq 'it''s'", {"s": "it's"}))

    def test_negative_and_exponent_numbers(self):
        self.assertTrue(ok("n lt -2", {"n": -3}))
        self.assertTrue(ok("n eq 1000.0", {"n": 1e3}))

    def test_a_bare_timestamp_is_a_datetime_not_a_name(self):
        tree = odata.parse_filter("t gt 2026-06-01T00:00:00Z")
        self.assertTrue(odata.matches(tree, {"t": "2026-06-02T00:00:00Z"}))
        self.assertFalse(odata.matches(tree, {"t": "2026-05-31T00:00:00Z"}))

    def test_a_bare_date_means_midnight_utc(self):
        self.assertTrue(ok("t ge 2026-06-01", {"t": "2026-06-01T00:00:00Z"}))


class TestTimeComparison(unittest.TestCase):

    def test_offsets_compare_as_instants_not_as_text(self):
        """The reason `_coerce_pair` parses instead of comparing strings.

        `12:00:00Z` and `13:00:00+01:00` are the same instant spelled two ways, and
        lexicographic comparison gets it backwards.
        """
        tree = odata.parse_filter("t eq 2026-06-01T12:00:00Z")
        self.assertTrue(odata.matches(tree, {"t": "2026-06-01T13:00:00+01:00"}))
        self.assertFalse(odata.matches(tree, {"t": "2026-06-01T13:00:00Z"}))

    def test_an_uncertainty_interval_compares_by_its_start(self):
        """§2 may emit `phenomenonTime` as a window. A client filtering on an instant
        should still get a usable answer rather than a type error."""
        doc = {"phenomenonTime": "2026-06-01T12:00:00Z/2026-06-01T12:00:30Z"}
        self.assertTrue(ok("phenomenonTime ge 2026-06-01T12:00:00Z", doc))


class TestNullOrdering(unittest.TestCase):

    def test_ordering_against_null_is_false_both_ways(self):
        """A reading with no result must match neither `gt` nor `le`, or a client
        partitioning a series into two halves silently loses rows."""
        doc = {"result": None}
        self.assertFalse(ok("result gt 0.4", doc))
        self.assertFalse(ok("result le 0.4", doc))


class TestLogic(unittest.TestCase):

    def test_precedence_is_or_lower_than_and(self):
        doc = {"a": 1, "b": 2, "c": 3}
        self.assertTrue(ok("a eq 9 or b eq 2 and c eq 3", doc))
        self.assertFalse(ok("(a eq 9 or b eq 2) and c eq 9", doc))

    def test_not_and_parentheses(self):
        self.assertTrue(ok("not (a eq 2)", {"a": 1}))


class TestFunctions(unittest.TestCase):

    def test_string_functions(self):
        doc = {"name": "bed1_moisture"}
        self.assertTrue(ok("startswith(name, 'bed1')", doc))
        self.assertTrue(ok("endswith(name, 'moisture')", doc))
        self.assertTrue(ok("contains(name, '_mo')", doc))
        self.assertTrue(ok("substringof('bed1', name)", doc))
        self.assertTrue(ok("length(name) eq 13", doc))
        self.assertTrue(ok("toupper(name) eq 'BED1_MOISTURE'", doc))

    def test_date_parts(self):
        doc = {"t": "2026-06-02T13:45:07Z"}
        self.assertTrue(ok("year(t) eq 2026", doc))
        self.assertTrue(ok("month(t) eq 6", doc))
        self.assertTrue(ok("day(t) eq 2", doc))
        self.assertTrue(ok("hour(t) eq 13", doc))
        self.assertTrue(ok("minute(t) eq 45", doc))
        self.assertTrue(ok("second(t) eq 7", doc))

    def test_round_is_half_away_from_zero_not_bankers(self):
        """Python rounds 0.5 to 0; OData rounds it to 1. A client comparing
        `round(result) eq 1` would otherwise get the wrong rows."""
        self.assertTrue(ok("round(r) eq 1", {"r": 0.5}))
        self.assertTrue(ok("round(r) eq 2", {"r": 1.5}))
        self.assertTrue(ok("round(r) eq -1", {"r": -0.5}))

    def test_wrong_arity_is_a_bad_request(self):
        with self.assertRaises(odata.BadRequest):
            odata.matches(odata.parse_filter("length(a, b) eq 1"), {"a": "x"})


class TestPaths(unittest.TestCase):

    def test_a_navigation_path_resolves_into_an_expanded_document(self):
        doc = {"result": 1, "Datastream": {"name": "bed1"}}
        self.assertTrue(ok("Datastream/name eq 'bed1'", doc))

    def test_a_missing_path_is_null_not_an_error(self):
        self.assertFalse(ok("Datastream/name eq 'bed1'", {"result": 1}))

    def test_id_is_accepted_as_an_alias_for_the_iot_id(self):
        self.assertTrue(ok("id eq 'x'", {"@iot.id": "x"}))


class TestRefusals(unittest.TestCase):
    """The load-bearing behaviour: never answer a question that was not asked."""

    def test_arithmetic_is_not_supported_and_says_so(self):
        with self.assertRaises(odata.NotSupported) as caught:
            odata.parse_filter("result add 1 gt 2")
        self.assertEqual(caught.exception.status, 501)
        self.assertIn("arithmetic", str(caught.exception))

    def test_an_unknown_function_is_not_supported_and_is_named(self):
        with self.assertRaises(odata.NotSupported) as caught:
            odata.parse_filter("geo.distance(a, b) lt 1")
        self.assertEqual(caught.exception.offending, "geo.distance")

    def test_syntax_errors_are_bad_requests_with_the_offending_text(self):
        for expr in ("result gt", "result gt )", "((result eq 1", "and result eq 1"):
            with self.assertRaises(odata.BadRequest, msg=expr):
                odata.parse_filter(expr)

    def test_an_empty_filter_is_rejected_rather_than_ignored(self):
        with self.assertRaises(odata.BadRequest):
            odata.parse_filter("   ")

    def test_an_unparsable_character_is_reported(self):
        with self.assertRaises(odata.BadRequest):
            odata.parse_filter("result ~ 1")


if __name__ == "__main__":
    unittest.main()
