#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for §7.6 export. The real one is the round trip."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import codec
import export as X
import fixtures as fx
import log as L
import project as P


def _seeded_log(rows: int = 25):
    """A log with every record type, a supersession and a correction in it.

    The supersession is on the **derived** series, not the raw one. §3.2 says a raw
    observation is never superseded — it is the archival truth — and `State.validate`
    enforces it, which is how the first version of this helper was caught building an
    invalid log. Recalibration appends a new derived row that supersedes the old one;
    the raw reading it came from never changes.
    """
    log = L.Log()
    ds = fx.raw_datastream()
    derived = fx.derived_datastream(raw=ds)
    cal = fx.calibration(sensor=ds.sensor)
    th = fx.threshold(derived, flat_seconds=3600)
    for record in (ds, derived, cal, th):
        log.append_record(record)

    first_derived = first_event = None
    for i in range(rows):
        raw = fx.observation(datastream=ds, result=200 + i * 5,
                             measured_at=fx.at(i * 15), node="n1", boot=0, seq=i)
        event = log.append_record(raw)
        calibrated = fx.observation(
            datastream=derived, result=0.200 + i * 0.005,
            measured_at=fx.at(i * 15), node="n1", boot=0, seq=i,
            calibration=cal.id,
            provenance={"derived_from_observation": str(raw.id)})
        log.append_record(calibrated)
        log.append_record(fx.assertion(calibrated.id, evidence={
            "checks_run": ["range", "flatline"], "fired": {},
            "thresholds": {"flat_seconds": 3600}}))
        if first_derived is None:
            first_derived, first_event = calibrated, event

    # Recalibration: a new derived row supersedes the old one (§3.2), and a
    # compensating event records a judgement about the raw reading (§7.3). An export
    # that drops either is the silent cleaning §7.6 forbids.
    log.append_record(fx.observation(
        datastream=derived, result=0.999, measured_at=fx.at(0),
        calibration=cal.id, supersedes=first_derived.id))
    log.correct(first_event.id, reason="probe was out of the ground")
    return log


class TestArchiveRoundTrip(unittest.TestCase):
    """The claim the matrix row makes: a full export that loses nothing."""

    def setUp(self):
        self.log = _seeded_log()
        self.dir = tempfile.mkdtemp()

    def test_the_archive_replays_into_an_identical_event_list(self):
        X.export_log(self.log, self.dir)
        back = X.import_log(self.dir)
        self.assertEqual([e.to_jsonable() for e in back.events],
                         [e.to_jsonable() for e in self.log.events])

    def test_event_ids_and_hlc_stamps_survive(self):
        """`append` would mint new ones, which is a different history that happens to
        contain the same records. §7.1 and §7.4 both depend on these surviving."""
        X.export_log(self.log, self.dir)
        back = X.import_log(self.dir)
        self.assertEqual([str(e.stamp) for e in back.events],
                         [str(e.stamp) for e in self.log.events])
        self.assertEqual([e.id for e in back.events],
                         [e.id for e in self.log.events])

    def test_the_derived_state_is_identical_after_a_round_trip(self):
        X.export_log(self.log, self.dir)
        before, after = P.state_from_log(self.log), P.state_from_log(
            X.import_log(self.dir))
        self.assertEqual(len(before.observations), len(after.observations))
        self.assertEqual(after.validate(), [])
        self.assertEqual(
            {o.id for o in before.live_observations().values()},
            {o.id for o in after.live_observations().values()})

    def test_corrections_survive(self):
        """§7.3 events carry a reason and no record, so an export built from
        `log.records()` would drop them without a word."""
        self.assertEqual(len(list(self.log.corrections())), 1)
        X.export_log(self.log, self.dir)
        self.assertEqual(len(list(X.import_log(self.dir).corrections())), 1)

    def test_superseded_rows_survive(self):
        X.export_log(self.log, self.dir)
        back = X.import_log(self.dir)
        superseded = [r for r in back.records()
                      if getattr(r, "supersedes", None) is not None]
        self.assertTrue(superseded)

    def test_importing_twice_is_idempotent(self):
        """The log dedups by event id, so a double import must not double the history."""
        X.export_log(self.log, self.dir)
        once = X.import_log(self.dir)
        twice = X.read_archive(os.path.join(self.dir, X.ARCHIVE), into=once)
        self.assertEqual(len(twice.events), len(self.log.events))

    def test_the_archive_is_the_format_the_log_itself_writes(self):
        """An export is a replica, not a conversion — so a log opened straight onto the
        exported file replays it with no import step at all."""
        X.export_log(self.log, self.dir)
        direct = L.Log(path=os.path.join(self.dir, X.ARCHIVE))
        self.assertEqual(len(direct.events), len(self.log.events))
        self.assertEqual(direct.skipped_lines, ())


class TestCsv(unittest.TestCase):

    def setUp(self):
        self.log = _seeded_log(rows=8)
        self.dir = tempfile.mkdtemp()
        self.manifest = X.export_log(self.log, self.dir, geojson=False)

    def test_one_file_per_record_type(self):
        names = {f.name for f in self.manifest.files}
        for expected in ("observations.csv", "datastreams.csv", "calibrations.csv",
                         "thresholds.csv", "qualityassertions.csv"):
            self.assertIn(expected, names)

    def test_observations_round_trip_through_csv(self):
        back = X.read_csv_records(self.dir, "Observation")
        original = [r for r in self.log.records() if type(r).__name__ == "Observation"]
        self.assertEqual([codec.dump(r) for r in back],
                         [codec.dump(r) for r in original])

    def test_every_record_type_round_trips_through_csv(self):
        for kind in ("Datastream", "Calibration", "Threshold", "QualityAssertion"):
            with self.subTest(kind=kind):
                back = X.read_csv_records(self.dir, kind)
                original = [r for r in self.log.records()
                            if type(r).__name__ == kind]
                self.assertEqual([codec.dump(r) for r in back],
                                 [codec.dump(r) for r in original])

    def test_nested_fields_survive_as_json_in_a_cell(self):
        back = X.read_csv_records(self.dir, "QualityAssertion")
        self.assertTrue(any(a.evidence for a in back))
        self.assertTrue(all(isinstance(a.evidence, dict) for a in back))

    def test_quality_flags_survive_as_a_set(self):
        back = X.read_csv_records(self.dir, "QualityAssertion")
        self.assertTrue(all(isinstance(a.flags, frozenset) for a in back))

    def test_corrections_get_their_own_file(self):
        names = {f.name for f in self.manifest.files}
        self.assertIn("corrections.csv", names)

    def test_csv_losslessness_is_measured_not_claimed(self):
        """Every CSV here is lossless, and the manifest says so because it was
        checked — not because the format guarantees it."""
        for entry in self.manifest.files:
            if entry.name.endswith(".csv"):
                self.assertTrue(entry.lossless, entry.name)

    def test_an_empty_string_survives_rather_than_becoming_null(self):
        """A bare cell cannot tell `""` from absent, so an empty string is quoted."""
        log = L.Log()
        ds = fx.raw_datastream()
        log.append_record(ds)
        log.append_record(fx.observation(datastream=ds, result=0.2, node=""))
        directory = tempfile.mkdtemp()
        manifest = X.export_log(log, directory, geojson=False)
        self.assertTrue(next(f for f in manifest.files
                             if f.name == "observations.csv").lossless)
        self.assertEqual(X.read_csv_records(directory, "Observation")[0].node, "")

    def test_a_numeric_looking_string_stays_a_string(self):
        """The defect the round-trip test found on its first run: `check_version` is
        the string `"1"` and came back as the integer `1`."""
        self.assertEqual(
            X.read_csv_records(self.dir, "QualityAssertion")[0].check_version, "1")

    def test_losslessness_is_verified_by_decoding_not_by_reasoning(self):
        """A value its own decoder cannot reproduce must be caught even if nobody
        anticipated it. `nan` is the example: it is not equal to itself."""
        self.assertEqual(X._cell(float("nan"))[1], False)
        self.assertEqual(X._cell("1"), ('"1"', True))

    def test_the_preferred_columns_come_first(self):
        with open(os.path.join(self.dir, "observations.csv"), encoding="utf-8") as h:
            header = h.readline().strip().split(",")
        self.assertEqual(header[:4], ["id", "datastream", "measured_at", "result"])


class TestGeoJson(unittest.TestCase):

    def setUp(self):
        self.log = _seeded_log(rows=5)
        self.state = P.state_from_log(self.log)
        self.dir = tempfile.mkdtemp()
        ds = next(iter(self.state.datastreams.values()))
        self.labels = {ds.feature: {"name": "bed1", "feature": {
            "type": "Point", "coordinates": [0.0001, 0.0]}}}

    def _written(self):
        manifest = X.export_log(self.log, self.dir, state=self.state,
                                labels=self.labels)
        with open(os.path.join(self.dir, X.GEOJSON), encoding="utf-8") as handle:
            return manifest, json.load(handle)

    def test_it_is_a_feature_collection_with_geometry(self):
        _, doc = self._written()
        self.assertEqual(doc["type"], "FeatureCollection")
        self.assertTrue(doc["features"])
        self.assertEqual(doc["features"][0]["geometry"]["type"], "Point")

    def test_each_feature_summarises_its_series(self):
        _, doc = self._written()
        series = doc["features"][0]["properties"]["series"]
        self.assertTrue(series)
        self.assertIn("latest_result", series[0])
        self.assertIn("unit", series[0])

    def test_it_is_declared_lossy(self):
        """It is a view. Claiming otherwise is the failure this module is about."""
        manifest, _ = self._written()
        entry = next(f for f in manifest.files if f.name == X.GEOJSON)
        self.assertFalse(entry.lossless)
        self.assertIn("authoritative", entry.note)

    def test_a_feature_without_geometry_is_reported_not_silently_dropped(self):
        """A GIS client discards a geometryless feature without a word, which is how a
        missing bed becomes invisible instead of noticeable."""
        manifest = X.export_log(self.log, self.dir, state=self.state, labels={})
        entry = next(f for f in manifest.files if f.name == X.GEOJSON)
        self.assertEqual(entry.rows, 0)
        self.assertIn("no geometry", entry.note)


class TestManifestAndVerify(unittest.TestCase):

    def setUp(self):
        self.log = _seeded_log(rows=6)
        self.dir = tempfile.mkdtemp()
        self.manifest = X.export_log(self.log, self.dir)

    def test_a_fresh_export_verifies_clean(self):
        self.assertEqual(X.verify(self.dir), [])

    def test_the_manifest_counts_every_event(self):
        self.assertEqual(self.manifest.events, len(self.log.events))

    def test_a_tampered_file_fails_verification(self):
        path = os.path.join(self.dir, X.ARCHIVE)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write('{"id":"x"}\n')
        problems = X.verify(self.dir)
        self.assertTrue(problems)
        self.assertTrue(any("checksum" in p for p in problems))

    def test_a_missing_file_fails_verification(self):
        os.remove(os.path.join(self.dir, "observations.csv"))
        self.assertTrue(any("missing" in p for p in X.verify(self.dir)))

    def test_a_missing_manifest_is_reported_rather_than_crashing(self):
        os.remove(os.path.join(self.dir, X.MANIFEST))
        self.assertEqual(X.verify(self.dir), ["MANIFEST.json is missing"])

    def test_every_file_on_disk_appears_in_the_manifest(self):
        """An unlisted file is an unverifiable file."""
        listed = {f.name for f in self.manifest.files} | {X.MANIFEST}
        self.assertEqual(set(os.listdir(self.dir)) - listed, set())


if __name__ == "__main__":
    unittest.main()


class TestCompressedArchive(unittest.TestCase):
    """Uncompressed stays canonical; gzip is offered because a season is ~900 MB."""

    def setUp(self):
        self.log = _seeded_log(rows=10)
        self.dir = tempfile.mkdtemp()

    def test_a_compressed_archive_round_trips(self):
        X.export_log(self.log, self.dir, geojson=False, compress=True)
        self.assertTrue(os.path.exists(os.path.join(self.dir, X.ARCHIVE + ".gz")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, X.ARCHIVE)))
        back = X.import_log(self.dir)
        self.assertEqual([e.to_jsonable() for e in back.events],
                         [e.to_jsonable() for e in self.log.events])

    def test_a_compressed_export_verifies(self):
        X.export_log(self.log, self.dir, geojson=False, compress=True)
        self.assertEqual(X.verify(self.dir), [])

    def test_the_manifest_names_whichever_archive_was_written(self):
        manifest = X.export_log(self.log, self.dir, geojson=False, compress=True)
        self.assertEqual(manifest.archive_name, X.ARCHIVE + ".gz")
        self.assertIsNotNone(manifest.archive)
        self.assertTrue(manifest.archive.lossless)

    def test_uncompressed_remains_the_default(self):
        """Because that file is byte-compatible with what the log itself writes, which
        is what makes an export a replica rather than a conversion."""
        manifest = X.export_log(self.log, self.dir, geojson=False)
        self.assertEqual(manifest.archive_name, X.ARCHIVE)
        direct = L.Log(path=os.path.join(self.dir, X.ARCHIVE))
        self.assertEqual(len(direct.events), len(self.log.events))

    def test_it_actually_compresses(self):
        plain = tempfile.mkdtemp()
        X.export_log(self.log, plain, geojson=False)
        X.export_log(self.log, self.dir, geojson=False, compress=True)
        big = os.path.getsize(os.path.join(plain, X.ARCHIVE))
        small = os.path.getsize(os.path.join(self.dir, X.ARCHIVE + ".gz"))
        self.assertLess(small, big)
