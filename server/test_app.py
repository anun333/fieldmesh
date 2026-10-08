#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the HTTP service, with no socket involved."""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import unittest
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "sdk"))

import app as A  # noqa: E402

import fixtures as F  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402

UTC = _dt.timezone.utc


def _farm(rows: int = 12):
    """A log with one raw datastream and `rows` readings on it."""
    ds = F.raw_datastream()
    log = L.Log()
    log.append_record(ds)
    for i in range(rows):
        log.append_record(F.observation(datastream=ds, result=0.20 + i * 0.01,
                                        measured_at=F.at(i * 15), node="n1",
                                        boot=0, seq=i))
    return ds, P.state_from_log(log)


class _Case(unittest.TestCase):

    def setUp(self):
        self.ds, self.state = _farm()
        self.app = A.make_app(self.state)

    def get(self, path, query="", method="GET"):
        status, headers, body = self.app.handle(method, path, query)
        doc = json.loads(body) if body else None
        return status, headers, doc


class TestServiceDocument(_Case):

    def test_the_root_lists_every_entity_set(self):
        status, _, doc = self.get("/v1.1")
        self.assertEqual(status, 200)
        names = {e["name"] for e in doc["value"]}
        self.assertEqual(names, {"Things", "Datastreams", "Sensors",
                                 "ObservedProperties", "Observations",
                                 "FeaturesOfInterest"})

    def test_the_bare_root_advertises_the_versioned_path(self):
        status, _, doc = self.get("/")
        self.assertEqual(status, 200)
        self.assertTrue(doc["value"][0]["url"].endswith("/v1.1"))

    def test_an_unknown_path_is_404(self):
        self.assertEqual(self.get("/nope")[0], 404)

    def test_an_unknown_entity_set_is_404_and_names_it(self):
        status, _, doc = self.get("/v1.1/Sheep")
        self.assertEqual(status, 404)
        self.assertEqual(doc["error"]["target"], "Sheep")


class TestReadOnly(_Case):

    def test_every_mutating_method_is_405_with_an_allow_header(self):
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            status, headers, doc = self.get("/v1.1/Observations", method=method)
            self.assertEqual(status, 405, method)
            self.assertEqual(headers["Allow"], "GET, HEAD")
            self.assertIn("§7.1", doc["error"]["message"])

    def test_head_returns_the_headers_and_no_body(self):
        status, headers, _ = self.app.handle("HEAD", "/v1.1/Datastreams", "")[0:3]
        self.assertEqual(status, 200)

    def test_head_body_is_empty(self):
        _, _, body = self.app.handle("HEAD", "/v1.1/Datastreams", "")
        self.assertEqual(body, b"")


class TestPaging(_Case):

    def test_top_limits_the_page_and_offers_a_next_link(self):
        status, _, doc = self.get("/v1.1/Observations", "$top=5")
        self.assertEqual(status, 200)
        self.assertEqual(len(doc["value"]), 5)
        self.assertIn("@iot.nextLink", doc)

    def test_the_next_link_actually_returns_the_next_page(self):
        _, _, first = self.get("/v1.1/Observations", "$top=5")
        nxt = urlparse(first["@iot.nextLink"])
        _, _, second = self.get(nxt.path, nxt.query)
        self.assertEqual(len(second["value"]), 5)
        firsts = {o["@iot.id"] for o in first["value"]}
        seconds = {o["@iot.id"] for o in second["value"]}
        self.assertEqual(firsts & seconds, set())

    def test_walking_every_page_yields_each_row_exactly_once(self):
        seen, path, query, guard = [], "/v1.1/Observations", "$top=5", 0
        while True:
            guard += 1
            self.assertLess(guard, 20, "paging did not terminate")
            _, _, doc = self.get(path, query)
            seen.extend(o["@iot.id"] for o in doc["value"])
            if "@iot.nextLink" not in doc:
                break
            parts = urlparse(doc["@iot.nextLink"])
            path, query = parts.path, parts.query
        self.assertEqual(len(seen), 12)
        self.assertEqual(len(set(seen)), 12)

    def test_the_last_page_has_no_next_link(self):
        _, _, doc = self.get("/v1.1/Observations", "$top=100")
        self.assertNotIn("@iot.nextLink", doc)

    def test_count_is_the_filtered_total_not_the_page_size(self):
        _, _, doc = self.get("/v1.1/Observations", "$top=3&$count=true")
        self.assertEqual(doc["@iot.count"], 12)
        self.assertEqual(len(doc["value"]), 3)

    def test_count_is_absent_unless_asked_for(self):
        _, _, doc = self.get("/v1.1/Observations", "$top=3")
        self.assertNotIn("@iot.count", doc)

    def test_top_beyond_the_cap_is_refused_rather_than_silently_clamped(self):
        """Clamping would answer a different question than the one asked."""
        status, _, doc = self.get("/v1.1/Observations", "$top=10000000")
        self.assertEqual(status, 400)
        self.assertIn("$top", doc["error"]["message"])

    def test_a_negative_skip_is_a_bad_request(self):
        self.assertEqual(self.get("/v1.1/Observations", "$skip=-1")[0], 400)

    def test_a_non_numeric_top_is_a_bad_request(self):
        status, _, doc = self.get("/v1.1/Observations", "$top=lots")
        self.assertEqual(status, 400)
        self.assertEqual(doc["error"]["target"], "lots")


class TestFilter(_Case):

    def test_filter_narrows_the_set_and_count_follows_it(self):
        _, _, doc = self.get("/v1.1/Observations",
                             "$filter=result gt 0.25&$count=true&$top=100")
        self.assertTrue(all(o["result"] > 0.25 for o in doc["value"]))
        self.assertEqual(doc["@iot.count"], len(doc["value"]))

    def test_an_unsupported_filter_is_501_and_returns_no_data(self):
        """The whole point. Silence here would look like 'nothing matched'."""
        status, _, doc = self.get("/v1.1/Observations", "$filter=result add 1 gt 2")
        self.assertEqual(status, 501)
        self.assertNotIn("value", doc)

    def test_a_malformed_filter_is_400_and_returns_no_data(self):
        status, _, doc = self.get("/v1.1/Observations", "$filter=result gt")
        self.assertEqual(status, 400)
        self.assertNotIn("value", doc)

    def test_an_unknown_dollar_option_is_501_rather_than_ignored(self):
        status, _, doc = self.get("/v1.1/Observations", "$apply=groupby((x))")
        self.assertEqual(status, 501)
        self.assertEqual(doc["error"]["target"], "$apply")

    def test_a_filter_on_phenomenon_time_works_on_the_wire_format(self):
        _, _, doc = self.get(
            "/v1.1/Observations",
            "$filter=phenomenonTime ge 2026-06-01T12:30:00Z&$count=true&$top=100")
        self.assertEqual(doc["@iot.count"], 10)


class TestOrderBy(_Case):

    def test_descending_order(self):
        _, _, doc = self.get("/v1.1/Observations", "$orderby=result desc&$top=100")
        results = [o["result"] for o in doc["value"]]
        self.assertEqual(results, sorted(results, reverse=True))

    def test_order_then_page_sees_the_global_maximum_first(self):
        """A paged `$orderby` must sort the whole set before slicing, or page one is
        merely the first few rows in storage order, re-sorted among themselves."""
        _, _, page = self.get("/v1.1/Observations", "$orderby=result desc&$top=1")
        _, _, every = self.get("/v1.1/Observations", "$orderby=result desc&$top=100")
        self.assertEqual(page["value"][0]["result"], every["value"][0]["result"])

    def test_a_malformed_orderby_is_a_bad_request(self):
        self.assertEqual(
            self.get("/v1.1/Observations", "$orderby=result sideways")[0], 400)

    def test_ordering_on_a_property_some_rows_lack_does_not_500(self):
        status, _, doc = self.get("/v1.1/Observations", "$orderby=nosuch&$top=100")
        self.assertEqual(status, 200)
        self.assertEqual(len(doc["value"]), 12)


class TestSelect(_Case):

    def test_select_keeps_only_the_named_properties(self):
        _, _, doc = self.get("/v1.1/Observations", "$select=result&$top=1")
        self.assertEqual(set(doc["value"][0]) - {"@iot.id", "@iot.selfLink"},
                         {"result"})

    def test_select_keeps_the_self_link_so_the_client_can_navigate(self):
        _, _, doc = self.get("/v1.1/Observations", "$select=result&$top=1")
        self.assertIn("@iot.selfLink", doc["value"][0])


class TestEntitiesAndNavigation(_Case):

    def test_a_datastream_by_id(self):
        status, _, doc = self.get(f"/v1.1/Datastreams({self.ds.id})")
        self.assertEqual(status, 200)
        self.assertEqual(doc["@iot.id"], str(self.ds.id))

    def test_a_quoted_id_is_accepted(self):
        self.assertEqual(self.get(f"/v1.1/Datastreams('{self.ds.id}')")[0], 200)

    def test_a_missing_datastream_is_404(self):
        import uuid
        self.assertEqual(self.get(f"/v1.1/Datastreams({uuid.uuid4()})")[0], 404)

    def test_a_malformed_id_is_404_not_500(self):
        self.assertEqual(self.get("/v1.1/Datastreams(banana)")[0], 404)

    def test_observations_of_a_datastream(self):
        status, _, doc = self.get(
            f"/v1.1/Datastreams({self.ds.id})/Observations", "$count=true&$top=100")
        self.assertEqual(status, 200)
        self.assertEqual(doc["@iot.count"], 12)

    def test_the_scoped_next_link_keeps_the_scope(self):
        _, _, doc = self.get(f"/v1.1/Datastreams({self.ds.id})/Observations", "$top=5")
        self.assertIn(f"Datastreams({self.ds.id})/Observations",
                      doc["@iot.nextLink"])

    def test_a_single_valued_navigation_link(self):
        for nav in ("Sensor", "Thing", "ObservedProperty"):
            status, _, doc = self.get(f"/v1.1/Datastreams({self.ds.id})/{nav}")
            self.assertEqual(status, 200, nav)
            self.assertIn("@iot.selfLink", doc)

    def test_observation_to_its_datastream(self):
        _, _, obs = self.get("/v1.1/Observations", "$top=1")
        ident = obs["value"][0]["@iot.id"]
        status, _, doc = self.get(f"/v1.1/Observations({ident})/Datastream")
        self.assertEqual(status, 200)
        self.assertEqual(doc["@iot.id"], str(self.ds.id))

    def test_a_property_of_an_entity(self):
        status, _, doc = self.get(f"/v1.1/Datastreams({self.ds.id})/name")
        self.assertEqual(status, 200)
        self.assertIn("name", doc)

    def test_dollar_value_returns_text_not_json(self):
        status, headers, _ = self.app.handle(
            "GET", f"/v1.1/Datastreams({self.ds.id})/name/$value", "")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/plain")

    def test_an_unknown_property_is_404_and_names_it(self):
        status, _, doc = self.get(f"/v1.1/Datastreams({self.ds.id})/colour")
        self.assertEqual(status, 404)
        self.assertEqual(doc["error"]["target"], "colour")

    def test_two_levels_of_navigation_is_501_not_a_wrong_answer(self):
        status, _, _ = self.get(
            f"/v1.1/Datastreams({self.ds.id})/Observations/FeatureOfInterest")
        self.assertEqual(status, 501)

    def test_a_sub_path_on_an_entity_set_is_404(self):
        self.assertEqual(self.get("/v1.1/Datastreams/Observations")[0], 404)

    def test_metadata_is_501_and_points_at_the_service_document(self):
        status, _, doc = self.get("/v1.1/$metadata")
        self.assertEqual(status, 501)
        self.assertIn("service document", doc["error"]["message"])


class TestSupersededRowsAreNeverServed(unittest.TestCase):
    """§3.2 — recalibration appends; the old row stays in the log and off the wire."""

    def test_a_superseded_observation_is_absent_from_the_collection(self):
        ds = F.raw_datastream()
        log = L.Log()
        log.append_record(ds)
        original = F.observation(datastream=ds, result=0.20, measured_at=F.at(0))
        log.append_record(original)
        log.append_record(F.observation(datastream=ds, result=0.21,
                                        measured_at=F.at(0),
                                        supersedes=original.id))
        state = P.state_from_log(log)
        app = A.make_app(state)
        _, _, doc = app.handle("GET", "/v1.1/Observations", "$top=100")
        doc = json.loads(doc) if isinstance(doc, bytes) else doc
        status, _, body = app.handle("GET", "/v1.1/Observations", "$top=100")
        rows = json.loads(body)["value"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["result"], 0.21)
        self.assertNotIn(str(original.id), {r["@iot.id"] for r in rows})


if __name__ == "__main__":
    unittest.main()


class TestEverySelfLinkResolves(unittest.TestCase):
    """The bug class QGIS found, pinned generally rather than case by case.

    A service that emits a link it cannot answer is worse than one that emits none: the
    client has no way to tell a broken link from an empty result, and it will have
    followed the link before finding out. This walks every entity set, takes every
    `@iot.selfLink` and `...@iot.navigationLink` the service produces, and fetches it.

    It caught `ObservedProperties('http://vocab.nerc.ac.uk/...')`, where the id is a
    vocabulary URI (§3.4) and its unencoded slashes split the path into the wrong
    segments.
    """

    def setUp(self):
        self.ds, self.state = _farm(rows=3)
        self.app = A.make_app(self.state)

    def _fetch(self, url):
        parts = urlparse(url)
        return self.app.handle("GET", parts.path, parts.query)[0]

    def _links(self, doc):
        for key, value in doc.items():
            if key.endswith("@iot.navigationLink") or key == "@iot.selfLink":
                yield key, value

    def test_every_self_and_navigation_link_in_every_set_answers_200(self):
        sets = ["Things", "Datastreams", "Sensors", "ObservedProperties",
                "Observations", "FeaturesOfInterest"]
        checked = 0
        for name in sets:
            status, _, body = self.app.handle("GET", f"/v1.1/{name}", "$top=100")
            self.assertEqual(status, 200, name)
            for doc in json.loads(body)["value"]:
                for key, url in self._links(doc):
                    with self.subTest(set=name, link=key, url=url):
                        self.assertEqual(self._fetch(url), 200)
                    checked += 1
        self.assertGreater(checked, 20, "the walk found suspiciously few links")


class TestUriKeyedObservedProperties(_Case):
    """§3.4 — an observed property's identity is its vocabulary URI, not a UUID."""

    def _first(self):
        _, _, doc = self.get("/v1.1/ObservedProperties", "$top=1")
        return doc["value"][0]

    def test_it_is_addressable_by_its_percent_encoded_uri(self):
        prop = self._first()
        parts = urlparse(prop["@iot.selfLink"])
        status, _, doc = self.get(parts.path, parts.query)
        self.assertEqual(status, 200)
        self.assertEqual(doc["@iot.id"], prop["@iot.id"])

    def test_the_self_link_percent_encodes_the_slashes(self):
        """Unencoded, the id's own slashes become path separators."""
        self.assertIn("%2F", self._first()["@iot.selfLink"])

    def test_its_datastreams_navigation_link_resolves_and_is_narrowed(self):
        prop = self._first()
        parts = urlparse(prop["Datastreams@iot.navigationLink"])
        status, _, doc = self.get(parts.path, "$count=true&$top=100")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(doc["@iot.count"], 1)
        every = self.get("/v1.1/Datastreams", "$count=true&$top=100")[2]
        self.assertLessEqual(doc["@iot.count"], every["@iot.count"])

    def test_an_unknown_observed_property_uri_is_404_not_a_crash(self):
        self.assertEqual(
            self.get("/v1.1/ObservedProperties('http%3A%2F%2Fnope.invalid%2Fx')")[0],
            404)
