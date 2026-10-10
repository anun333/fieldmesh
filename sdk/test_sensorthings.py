#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The SensorThings out-adapter (spec v0.1 §10).

The first class is the one that matters: it is the compatibility promise that v0
would have broken on the first recalibration.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import unittest

import fixtures as fx
import log as L
import project as P
import sensorthings as st
from ids import uuid7
from model import Assertor, ClockQuality, QualityFlag, Usable

UTC = _dt.timezone.utc


def _state(*records) -> P.State:
    lg = L.Log()
    for r in records:
        lg.append_record(r)
    return P.state_from_log(lg)


class TestOnlyLiveObservationsAreServed(unittest.TestCase):
    """§3.2 — the clause the whole adapter exists to honour."""

    def setUp(self):
        self.raw = fx.raw_datastream()
        self.derived = fx.derived_datastream(self.raw)
        self.first = fx.observation(self.derived, result=0.30, calibration=uuid7())
        self.redone = fx.observation(self.derived, result=0.28,
                                     calibration=uuid7(), supersedes=self.first.id)
        self.state = _state(self.raw, self.derived, self.first, self.redone)
        self.svc = st.Service(self.state, "https://farm.example")

    def test_the_superseded_row_is_in_the_log_but_not_on_the_wire(self):
        self.assertEqual(len(self.state.observations), 2)
        served = self.svc.observations(self.derived.id)
        self.assertEqual(served["@iot.count"], 1)
        self.assertEqual(served["value"][0]["result"], 0.28)

    def test_no_phenomenon_time_appears_twice(self):
        """A client that saw both rows would double every chart — the v0 bug."""
        served = self.svc.observations(self.derived.id)["value"]
        times = [o["phenomenonTime"] for o in served]
        self.assertEqual(len(times), len(set(times)))

    def test_raw_and_derived_are_two_separate_datastreams(self):
        doc = self.svc.datastreams()
        self.assertEqual(doc["@iot.count"], 2)
        kinds = sorted(d["properties"]["kind"] for d in doc["value"])
        self.assertEqual(kinds, ["derived", "raw"])

    def test_datastream_properties_carry_both_intervals(self):
        """§5.3.1: a client (and a farmer) can see which series is expensive."""
        props = self.svc.datastream(self.raw)["properties"]
        self.assertEqual(props["expected_interval_s"], self.raw.expected_interval)
        self.assertEqual(props["max_latency_s"], self.raw.max_latency)

    def test_a_derived_datastream_points_at_its_source(self):
        doc = self.svc.datastreams()
        derived = [d for d in doc["value"] if d["properties"]["kind"] == "derived"][0]
        self.assertEqual(derived["properties"]["derived_from"], str(self.raw.id))


class TestQualityMapping(unittest.TestCase):
    """§3.3 → `resultQuality`, which 1.1 types DQ_Element with multiplicity 0..*."""

    def setUp(self):
        self.ds = fx.raw_datastream()
        self.obs = fx.observation(self.ds)

    def _svc(self, *assertions):
        return st.Service(_state(self.ds, self.obs, *assertions))

    def test_absent_when_nothing_has_been_asserted(self):
        doc = self._svc().observation(self.obs)
        self.assertNotIn("resultQuality", doc)

    def test_present_for_a_clean_assertion(self):
        """"Checked, no objection" is a judgement, and collapsing it into "not
        checked" throws away what a certifier cares about."""
        clean = fx.assertion(self.obs.id, flags=set())
        doc = self._svc(clean).observation(self.obs)
        self.assertIn("resultQuality", doc)
        self.assertEqual(doc["resultQuality"][0]["flags"], [])
        self.assertEqual(doc["resultQuality"][0]["usable"], "good")

    def test_the_flag_set_maps_natively_because_multiplicity_is_many(self):
        a = fx.assertion(self.obs.id,
                         flags={QualityFlag.STUCK, QualityFlag.OUT_OF_RANGE})
        element = self._svc(a).observation(self.obs)["resultQuality"][0]
        self.assertEqual(element["flags"], ["out_of_range", "stuck"])
        self.assertEqual(element["usable"], "bad")

    def test_it_carries_the_threshold_version_that_produced_it(self):
        th = fx.threshold(self.ds, flat_n=6)
        a = fx.assertion(self.obs.id, flags={QualityFlag.STUCK},
                         threshold_version=th.id, check_version="2")
        element = self._svc(th, a).observation(self.obs)["resultQuality"][0]
        self.assertEqual(element["thresholdVersion"], str(th.id))
        self.assertEqual(element["checkVersion"], "2")

    def test_a_persons_override_is_what_is_served(self):
        machine = fx.assertion(self.obs.id, flags={QualityFlag.STUCK})
        person = fx.assertion(self.obs.id, flags={QualityFlag.STUCK},
                              usable=Usable.GOOD, assertor=Assertor.PERSON,
                              assertor_id=uuid7(), check="manual-review")
        element = self._svc(machine, person).observation(self.obs)["resultQuality"][0]
        self.assertEqual(element["usable"], "good")
        self.assertEqual(element["assertor"], "person")

    def test_a_superseded_assertion_is_not_served(self):
        old = fx.assertion(self.obs.id, flags={QualityFlag.STUCK})
        new = fx.assertion(self.obs.id, flags=set(), supersedes=old.id,
                           asserted_at=fx.at(5))
        element = self._svc(old, new).observation(self.obs)["resultQuality"][0]
        self.assertEqual(element["flags"], [])


class TestTimeMapping(unittest.TestCase):
    """§2 — `measured_at` is phenomenonTime; the rest has no STA equivalent."""

    def setUp(self):
        self.ds = fx.raw_datastream()

    def test_phenomenon_time_is_measured_at_in_iso_with_z(self):
        obs = fx.observation(self.ds, measured_at=_dt.datetime(2026, 6, 1, 12, 30,
                                                              tzinfo=UTC))
        doc = st.Service(_state(self.ds, obs)).observation(obs)
        self.assertEqual(doc["phenomenonTime"], "2026-06-01T12:30:00Z")

    def test_result_time_is_null_not_received_at(self):
        """received_at means something different; claiming it as resultTime would
        be a small lie in a field researchers read."""
        obs = fx.observation(self.ds, measured_at=fx.at(0), received_at=fx.at(4320))
        doc = st.Service(_state(self.ds, obs)).observation(obs)
        self.assertIsNone(doc["resultTime"])
        self.assertEqual(doc["parameters"]["fieldmesh"]["received_at"],
                         st.iso(obs.received_at))

    def test_the_other_four_time_fields_travel_in_parameters(self):
        obs = fx.observation(self.ds, uncertainty=600, boot=3, seq=77,
                             clock_quality=ClockQuality.NONE)
        extras = st.Service(_state(self.ds, obs)).observation(obs)["parameters"]["fieldmesh"]
        self.assertEqual(extras["measured_at_uncertainty_s"], 600)
        self.assertEqual(extras["clock_quality"], "none")
        self.assertEqual((extras["boot"], extras["seq"]), (3, 77))

    def test_extras_are_namespaced_so_they_do_not_pose_as_environmental_params(self):
        obs = fx.observation(self.ds)
        params = st.Service(_state(self.ds, obs)).observation(obs)["parameters"]
        self.assertEqual(list(params), ["fieldmesh"])

    def test_interval_times_expose_the_uncertainty_window(self):
        """Opt-in: standards-native honesty, but many clients assume an instant."""
        obs = fx.observation(self.ds, measured_at=_dt.datetime(2026, 6, 1, 12,
                                                               tzinfo=UTC),
                             uncertainty=600, clock_quality=ClockQuality.NONE)
        svc = st.Service(_state(self.ds, obs), interval_times=True)
        self.assertEqual(svc.observation(obs)["phenomenonTime"],
                         "2026-06-01T11:50:00Z/2026-06-01T12:10:00Z")

    def test_datastream_phenomenon_time_is_the_extent(self):
        a = fx.observation(self.ds, measured_at=fx.at(0), seq=0)
        b = fx.observation(self.ds, measured_at=fx.at(30), seq=1)
        doc = st.Service(_state(self.ds, a, b)).datastream(self.ds)
        self.assertIn("/", doc["phenomenonTime"])
        self.assertTrue(doc["phenomenonTime"].startswith(st.iso(a.measured_at)))

    def test_served_observations_follow_the_section_2_ordering(self):
        obs = [fx.observation(self.ds, node="!bed01", boot=1, seq=n,
                              measured_at=fx.at(n)) for n in (2, 0, 1)]
        served = st.Service(_state(self.ds, *obs)).observations(self.ds.id)["value"]
        seqs = [o["parameters"]["fieldmesh"]["seq"] for o in served]
        self.assertEqual(seqs, [0, 1, 2])


class TestUnitsAndTypes(unittest.TestCase):
    """§3.4 — UCUM, and 1.1 Table 12 observation types."""

    def test_ucum_code_is_the_symbol_with_a_ucum_definition(self):
        ds = fx.raw_datastream()
        uom = st.Service(_state(ds)).datastream(ds)["unitOfMeasurement"]
        self.assertEqual(uom["symbol"], "cm3/cm3")
        self.assertIn("unitsofmeasure.org", uom["definition"])

    def test_a_unitless_series_gets_null_properties_as_1_1_requires(self):
        ds = dataclasses.replace(fx.raw_datastream(), unit=None)
        uom = st.Service(_state(ds)).datastream(ds)["unitOfMeasurement"]
        self.assertEqual(uom, {"name": None, "symbol": None, "definition": None})

    def test_a_label_supplies_a_better_unit_name_when_one_exists(self):
        ds = fx.raw_datastream()
        svc = st.Service(_state(ds), labels={ds.id: {"unit_name": "cubic centimetre per cubic centimetre"}})
        self.assertEqual(svc.datastream(ds)["unitOfMeasurement"]["name"],
                         "cubic centimetre per cubic centimetre")

    def test_observation_type_by_result(self):
        cases = [(0.23, "OM_Measurement"), (7, "OM_CountObservation"),
                 (True, "OM_TruthObservation"), ("dry", "OM_CategoryObservation")]
        for result, expected in cases:
            with self.subTest(result=result):
                self.assertTrue(st.observation_type(result).endswith(expected))

    def test_a_bool_is_a_truth_observation_not_a_count(self):
        """In Python a bool *is* an int, so order of checks matters."""
        self.assertTrue(st.observation_type(False).endswith("OM_TruthObservation"))

    def test_a_declared_unit_makes_it_a_measurement_whatever_the_values_look_like(self):
        """The defect a GIS client found in Harrow Bend.

        A raw soil-moisture series carries scaled integers — `280` for 0.280 cm3/cm3 —
        and typing the datastream from the first value it could find made the whole
        series an `OM_CountObservation` while the same document declared a unit of
        `cm3/cm3`. A count has no unit, so one document asserted two incompatible
        things, and a consumer honouring `observationType` would be within its rights
        to refuse to average or interpolate a continuous measurement.

        A unit is the declaration that something is a measured quantity, so it decides.
        """
        ds = fx.raw_datastream()
        obs = fx.observation(ds, result=280)
        doc = st.Service(_state(ds, obs)).datastream(ds)
        self.assertTrue(doc["observationType"].endswith("OM_Measurement"),
                        doc["observationType"])
        self.assertIsNotNone(doc["unitOfMeasurement"])

    def test_a_declared_unit_is_enough_before_any_reading_arrives(self):
        """A type that needs data to be known is useless to a client building a
        legend against an empty series, and the declaration already settles it."""
        ds = fx.raw_datastream()
        doc = st.Service(_state(ds)).datastream(ds)
        self.assertTrue(doc["observationType"].endswith("OM_Measurement"))

    def test_without_a_unit_the_values_decide(self):
        """§3.4 lets a datastream with no meaningful unit declare none. That is the
        case where the value's own type is the only evidence there is."""
        ds = fx.raw_datastream(unit=None)
        obs = fx.observation(ds, result=True)
        doc = st.Service(_state(ds, obs)).datastream(ds)
        self.assertTrue(doc["observationType"].endswith("OM_TruthObservation"),
                        doc["observationType"])

    def test_an_empty_unitless_datastream_falls_back_to_om_observation(self):
        ds = fx.raw_datastream(unit=None)
        doc = st.Service(_state(ds)).datastream(ds)
        self.assertTrue(doc["observationType"].endswith("OM_Observation"))


class TestFeatureResolution(unittest.TestCase):
    """§3.1 — feature on the datastream, overridden per observation when it varies."""

    def test_expand_gives_the_datastreams_feature_by_default(self):
        ds = fx.raw_datastream()
        obs = fx.observation(ds)
        doc = st.Service(_state(ds, obs)).observation(obs, expand=("FeatureOfInterest",))
        self.assertEqual(doc["FeatureOfInterest"]["@iot.id"], str(ds.feature))

    def test_expand_gives_the_override_for_a_handheld_reading(self):
        ds = fx.raw_datastream()
        sample = uuid7()
        obs = fx.observation(ds, feature=sample)
        doc = st.Service(_state(ds, obs)).observation(obs, expand=("FeatureOfInterest",))
        self.assertEqual(doc["FeatureOfInterest"]["@iot.id"], str(sample))
        self.assertNotEqual(doc["FeatureOfInterest"]["@iot.id"], str(ds.feature))

    def test_features_of_interest_set_includes_overrides(self):
        ds = fx.raw_datastream()
        sample = uuid7()
        doc = st.Service(_state(ds, fx.observation(ds, feature=sample))).features_of_interest()
        ids = {f["@iot.id"] for f in doc["value"]}
        self.assertEqual(ids, {str(ds.feature), str(sample)})

    def test_nothing_is_expanded_unless_asked(self):
        ds = fx.raw_datastream()
        doc = st.Service(_state(ds, fx.observation(ds))).observation(fx.observation(ds))
        self.assertNotIn("FeatureOfInterest", doc)
        self.assertIn("FeatureOfInterest@iot.navigationLink", doc)


class TestEntitySetsAndLinks(unittest.TestCase):
    def setUp(self):
        self.ds = fx.raw_datastream()
        self.obs = fx.observation(self.ds)
        self.svc = st.Service(_state(self.ds, self.obs), "https://farm.example")

    def test_control_information_uses_1_1_names(self):
        doc = self.svc.datastream(self.ds)
        self.assertEqual(doc["@iot.id"], str(self.ds.id))
        self.assertEqual(doc["@iot.selfLink"],
                         f"https://farm.example/v1.1/Datastreams({self.ds.id})")
        self.assertIn("Observations@iot.navigationLink", doc)

    def test_observed_property_is_identified_by_its_vocabulary_uri(self):
        """§3.4: the URI *is* the identity; there is no UUID to mint."""
        doc = self.svc.observed_properties()["value"][0]
        self.assertEqual(doc["@iot.id"], fx.SOIL_MOISTURE)
        self.assertEqual(doc["definition"], fx.SOIL_MOISTURE)

    def test_things_and_sensors_are_derived_from_the_datastreams(self):
        self.assertEqual(self.svc.things()["@iot.count"], 1)
        self.assertEqual(self.svc.sensors()["@iot.count"], 1)

    def test_unlabelled_entities_fall_back_to_their_id(self):
        thing = self.svc.things()["value"][0]
        self.assertEqual(thing["name"], str(self.ds.thing))

    def test_labels_are_used_when_supplied(self):
        svc = st.Service(_state(self.ds, self.obs),
                         labels={self.ds.thing: {"name": "north bed"}})
        self.assertEqual(svc.things()["value"][0]["name"], "north bed")

    def test_root_lists_every_entity_set(self):
        names = {e["name"] for e in self.svc.root()["value"]}
        self.assertEqual(names, {"Things", "Locations", "HistoricalLocations",
                                 "Datastreams", "Sensors", "ObservedProperties",
                                 "Observations", "FeaturesOfInterest"})

    def test_root_carries_server_settings_as_1_1_requires(self):
        """§9.2.1: serverSettings SHALL be present with a conformance array. This was
        missing until the standard's text was checked; no client had complained."""
        settings = self.svc.root()["serverSettings"]
        self.assertIn("conformance", settings)
        self.assertTrue(all(u.startswith("http://www.opengis.net/spec/iot_sensing/1.1/")
                            for u in settings["conformance"]))

    def test_conformance_does_not_claim_what_is_not_implemented(self):
        """A client reads this to decide what it may rely on; overclaiming is worse
        than underclaiming. Read-only, no MQTT, no geospatial $filter, no $ref."""
        claimed = " ".join(self.svc.root()["serverSettings"]["conformance"])
        for not_ours in ("create-update-delete", "mqtt", "batch-request",
                         "request-data", "resource-path", "multi-datastream"):
            self.assertNotIn(not_ours, claimed)

    def test_everything_is_json_serialisable(self):
        for doc in (self.svc.root(), self.svc.datastreams(), self.svc.observations(),
                    self.svc.things(), self.svc.sensors(),
                    self.svc.observed_properties(), self.svc.features_of_interest()):
            json.dumps(doc)


class TestValidatedAgainstFrost(unittest.TestCase):
    """Findings from running FROST-Server as a conformance oracle.

    FROST accepted a deep insert of these documents (HTTP 201) and round-tripped
    `resultQuality` — nested `evidence` included — and `parameters/fieldmesh`
    intact, so both extension decisions hold in the reference implementation.
    These tests pin the two places where its output and ours differed.
    """

    def setUp(self):
        self.ds = fx.raw_datastream()
        self.obs = fx.observation(self.ds)
        self.svc = st.Service(_state(self.ds, self.obs))

    def test_datastream_omits_result_time(self):
        """1.1 Table 10 makes Datastream.resultTime zero-to-one, and layer zero
        records no result times. FROST omits it; emitting a bare null was noise."""
        self.assertNotIn("resultTime", self.svc.datastream(self.ds))

    def test_observation_still_emits_result_time_as_null(self):
        """Table 18 makes it "One (mandatory)" and explicitly nullable, so here
        the null is required rather than noise."""
        doc = self.svc.observation(self.obs)
        self.assertIn("resultTime", doc)
        self.assertIsNone(doc["resultTime"])

    def test_count_is_included_by_default_as_example_11_shows(self):
        """1.1's Example 11 emits @iot.count on a plain entity-set request with
        no query options."""
        self.assertIn("@iot.count", self.svc.observations())

    def test_count_can_be_suppressed_the_way_frost_does(self):
        """FROST omits it unless $count=true. Both readings are defensible, so an
        HTTP layer passes $count through rather than this being hard-coded."""
        doc = self.svc.observations(count=False)
        self.assertNotIn("@iot.count", doc)
        self.assertIn("value", doc)

    def test_every_entity_set_honours_count(self):
        for getter in (self.svc.datastreams, self.svc.things, self.svc.sensors,
                       self.svc.observed_properties, self.svc.features_of_interest):
            with self.subTest(getter.__name__):
                self.assertNotIn("@iot.count", getter(count=False))
                self.assertIn("@iot.count", getter())


class TestDialectSeam(unittest.TestCase):
    """§10 — the migration is confined to one layer, which is only true if the
    version-dependent names live in one table."""

    def setUp(self):
        self.ds = fx.raw_datastream()
        self.obs = fx.observation(self.ds)
        self.a = fx.assertion(self.obs.id, flags={QualityFlag.STUCK})
        self.state = _state(self.ds, self.obs, self.a)

    def test_the_2_0_draft_renames_control_information(self):
        doc = st.Service(self.state, dialect=st.SensorThings20Draft).datastream(self.ds)
        self.assertEqual(doc["id"], str(self.ds.id))
        self.assertIn("@id", doc)
        self.assertNotIn("@iot.id", doc)
        self.assertIn("Observations@navigationLink", doc)

    def test_the_2_0_draft_renames_parameters_to_properties(self):
        doc = st.Service(self.state, dialect=st.SensorThings20Draft).observation(self.obs)
        self.assertIn("fieldmesh", doc["properties"])
        self.assertNotIn("parameters", doc)

    def test_quality_has_nowhere_standard_to_go_in_2_0(self):
        """Table 17 has no resultQuality, so it falls into the extras bag where
        nothing standards-aware will look — the argument in Q18."""
        doc = st.Service(self.state, dialect=st.SensorThings20Draft).observation(self.obs)
        self.assertNotIn("resultQuality", doc)
        self.assertEqual(doc["properties"]["fieldmesh"]["result_quality"][0]["usable"],
                         "bad")

    def test_1_1_keeps_quality_in_its_standard_place(self):
        doc = st.Service(self.state, dialect=st.SensorThings11).observation(self.obs)
        self.assertEqual(doc["resultQuality"][0]["usable"], "bad")
        self.assertNotIn("result_quality", doc["parameters"]["fieldmesh"])

    def test_the_model_knows_nothing_about_sensorthings(self):
        import model
        with open(model.__file__) as f:
            source = f.read()
        for token in ("@iot", "phenomenonTime", "resultQuality", "unitOfMeasurement"):
            self.assertNotIn(token, source,
                             f"{token} leaked into the data model; §10 keeps "
                             f"serialisation in one layer")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestVocabularyUriPresentation(unittest.TestCase):
    """Found by loading Harrow Bend in QGIS 3.44 and reading the legend."""

    def test_a_trailing_slash_does_not_erase_the_name(self):
        """The defect: both vocabulary servers want the trailing slash, and the name
        was derived as 'everything after the last slash' — which is the empty string.
        Every observed property in the GIS legend was blank."""
        uri = "http://vocab.nerc.ac.uk/standard_name/air_temperature/"
        self.assertEqual(st.humanise_term(uri), "air temperature")

    def test_camel_case_becomes_words(self):
        self.assertEqual(
            st.humanise_term("http://vocabulary.odm2.org/variablename/batteryVoltage/"),
            "battery voltage")

    def test_a_lone_trailing_capital_survives(self):
        """`pH` must not become `p h`. Soil pH is a measurand this will meet."""
        self.assertEqual(st.humanise_term("http://x/pH/"), "pH")

    def test_a_run_of_capitals_survives(self):
        self.assertEqual(st.humanise_term("http://x/RSSI/"), "RSSI")

    def test_a_label_registry_entry_still_wins(self):
        ds = fx.raw_datastream()
        svc = st.Service(_state(ds),
                         labels={ds.observed_property: {"name": "soil water"}})
        self.assertEqual(svc.observed_property(ds.observed_property)["name"],
                         "soil water")

    def test_the_self_link_percent_encodes_the_uri(self):
        """Unencoded, the id's own slashes become path separators and the service
        answers 404 to a link it emitted itself."""
        ds = fx.raw_datastream()
        doc = st.Service(_state(ds)).observed_property(ds.observed_property)
        self.assertNotIn("//vocab", doc["@iot.selfLink"].split("ObservedProperties")[1])
        self.assertIn("%2F", doc["@iot.selfLink"])

    def test_observed_property_offers_a_datastreams_link(self):
        ds = fx.raw_datastream()
        doc = st.Service(_state(ds)).observed_property(ds.observed_property)
        self.assertIn("Datastreams@iot.navigationLink", doc)


class TestFeatureGeometry(unittest.TestCase):
    """Geometry reaches the view as a side table, never as a log record.

    A real farm's field boundaries live in a gitignored `.site/` directory — they are
    the farmer's, and §3 has no record type for them. The label table is the same
    channel human names use, for the same reason.
    """

    def test_a_feature_with_no_geometry_serves_null_rather_than_omitting_it(self):
        ds = fx.raw_datastream()
        doc = st.Service(_state(ds)).feature_of_interest(ds.feature)
        self.assertIsNone(doc["feature"])
        self.assertEqual(doc["encodingType"], "application/geo+json")

    def test_geometry_from_the_label_table_is_served_as_geojson(self):
        ds = fx.raw_datastream()
        point = {"type": "Point", "coordinates": [0.0001, 0.0]}
        svc = st.Service(_state(ds), labels={ds.feature: {"name": "bed2",
                                                          "feature": point}})
        doc = svc.feature_of_interest(ds.feature)
        self.assertEqual(doc["feature"], point)
        self.assertEqual(doc["name"], "bed2")


class TestLocations(unittest.TestCase):
    """A Thing's Locations link exists and answers truthfully — the third attempt.

    First it was advertised with nothing behind it (a 404 to its own link). Then it was
    dropped, which 1.1's entity-control requirement does not allow either. A collection
    that answers, empty when the truth is empty, is what was wanted all along.
    """

    def setUp(self):
        self.ds = fx.raw_datastream()
        self.point = {"type": "Point", "coordinates": [0.0001, 0.0]}

    def test_things_advertise_locations_and_historical_locations(self):
        doc = st.Service(_state(self.ds)).thing(self.ds.thing)
        self.assertIn("Locations@iot.navigationLink", doc)
        self.assertIn("HistoricalLocations@iot.navigationLink", doc)

    def test_a_thing_is_located_at_its_features_geometry(self):
        svc = st.Service(_state(self.ds), geometries={self.ds.feature: self.point})
        self.assertEqual(svc.location_ids(self.ds.thing), [self.ds.feature])
        self.assertEqual(svc.location(self.ds.feature)["location"], self.point)

    def test_without_geometry_there_is_no_location_rather_than_an_empty_one(self):
        """A Location with no position would be a claim about nothing."""
        self.assertEqual(st.Service(_state(self.ds)).location_ids(self.ds.thing), [])

    def test_historical_locations_are_served_and_empty(self):
        """Things here do not move; devices do, and §4.1 records that as Installations,
        which 1.1 has nowhere to put. Inventing a Thing history would misplace it."""
        doc = st.Service(_state(self.ds)).historical_locations()
        self.assertEqual(doc["value"], [])
