#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for CSV import. The timezone tests are the ones that matter."""
from __future__ import annotations

import datetime as _dt
import os
import tempfile
import unittest

import csv_import as C
import fixtures as fx
import log as L
import project as P

UTC = _dt.timezone.utc


class _Case(unittest.TestCase):

    def setUp(self):
        self.ds = fx.raw_datastream()
        self.derived = fx.derived_datastream(raw=self.ds)
        self.log = L.Log()
        for record in (self.ds, self.derived):
            self.log.append_record(record)
        self.state = P.state_from_log(self.log)
        self.dir = tempfile.mkdtemp()

    def csv(self, text: str) -> str:
        path = os.path.join(self.dir, "logger.csv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def mapping(self, **over):
        base = {"timestamp": {"column": "When", "format": "%Y-%m-%d %H:%M",
                              "timezone": "America/Chicago"},
                "uncertainty_s": 450,
                "columns": {"VWC": {"datastream": str(self.ds.id)}}}
        base.update(over)
        return base

    def imported(self, text, **over):
        report = C.import_csv(self.log, self.state, self.csv(text),
                              self.mapping(**over),
                              received_at=_dt.datetime(2026, 10, 8, tzinfo=UTC))
        return report, self.state.live_observations_of(self.ds.id)


class TestTimezones(_Case):
    """The defect this module exists to avoid: local time read as UTC."""

    def test_local_time_is_converted_not_assumed(self):
        """14:00 in Chicago in June is 19:00 UTC. Read as UTC it would be five hours
        early, and the series would still look like a perfectly plausible day."""
        _, rows = self.imported("When,VWC\n2026-06-01 14:00,0.291\n")
        self.assertEqual(rows[0].measured_at, _dt.datetime(2026, 6, 1, 19, tzinfo=UTC))

    def test_a_missing_timezone_is_refused(self):
        with self.assertRaises(C.MappingError) as caught:
            self.imported("When,VWC\n2026-06-01 14:00,0.291\n",
                          timestamp={"column": "When", "format": "%Y-%m-%d %H:%M"})
        self.assertIn("timezone", str(caught.exception))

    def test_the_autumn_hour_that_happens_twice_is_not_guessed(self):
        report, rows = self.imported("When,VWC\n2026-11-01 01:30,0.291\n")
        self.assertEqual(report.ambiguous_time, 1)
        self.assertEqual(rows, [])

    def test_the_spring_hour_that_never_happened_is_not_guessed(self):
        """And it is called nonexistent, not ambiguous — the first version could not
        tell the two apart."""
        report, rows = self.imported("When,VWC\n2026-03-08 02:30,0.291\n")
        self.assertEqual(report.nonexistent_time, 1)
        self.assertEqual(report.ambiguous_time, 0)
        self.assertEqual(rows, [])

    def test_a_cell_with_its_own_offset_beats_the_mapping(self):
        _, rows = self.imported("When,VWC\n2026-06-01T14:00:00+00:00,0.291\n",
                                timestamp={"column": "When", "format": "iso",
                                           "timezone": "America/Chicago"})
        self.assertEqual(rows[0].measured_at, _dt.datetime(2026, 6, 1, 14, tzinfo=UTC))

    def test_utc_and_epoch_formats(self):
        _, rows = self.imported("When,VWC\n1780315200,0.291\n",
                                timestamp={"column": "When", "format": "epoch_s",
                                           "timezone": "UTC"})
        self.assertEqual(rows[0].measured_at.tzinfo, UTC)


class TestValuesArriveAsWritten(_Case):

    def test_scale_and_offset_are_refused(self):
        """A transform on import stores a value the file never contained, with no
        record of the change. That is a Calibration's job (§3.2)."""
        with self.assertRaises(C.MappingError) as caught:
            self.imported("When,VWC\n2026-06-01 14:00,29.1\n",
                          columns={"VWC": {"datastream": str(self.ds.id),
                                           "scale": 0.01}})
        self.assertIn("Calibration", str(caught.exception))

    def test_importing_into_a_derived_datastream_is_refused(self):
        with self.assertRaises(C.MappingError):
            self.imported("When,VWC\n2026-06-01 14:00,0.291\n",
                          columns={"VWC": {"datastream": str(self.derived.id)}})

    def test_the_value_is_exactly_what_the_cell_said(self):
        _, rows = self.imported("When,VWC\n2026-06-01 14:00,0.291\n")
        self.assertEqual(rows[0].result, 0.291)

    def test_blank_nan_and_text_are_counted_not_stored(self):
        report, rows = self.imported(
            "When,VWC\n2026-06-01 14:00,\n2026-06-01 14:15,nan\n2026-06-01 14:30,err\n"
            "2026-06-01 14:45,0.29\n")
        self.assertEqual((report.blank, report.not_numeric, report.written), (1, 2, 1))
        self.assertEqual(len(rows), 1)


class TestHonestyAndRepeatability(_Case):

    def test_uncertainty_is_required(self):
        with self.assertRaises(C.MappingError):
            self.imported("When,VWC\n2026-06-01 14:00,0.291\n", uncertainty_s=None)

    def test_reimporting_the_same_file_writes_nothing_twice(self):
        text = "When,VWC\n2026-06-01 14:00,0.291\n2026-06-01 14:15,0.290\n"
        first, _ = self.imported(text)
        second, rows = self.imported(text)
        self.assertEqual((first.written, second.written), (2, 0))
        self.assertEqual(second.already_present, 2)
        self.assertEqual(len(rows), 2)

    def test_every_reading_traces_to_its_line(self):
        _, rows = self.imported("When,VWC\n2026-06-01 14:00,0.291\n")
        provenance = rows[0].provenance
        self.assertEqual(provenance["source_line"], 2)
        self.assertEqual(provenance["source_file"], "logger.csv")
        self.assertEqual(len(provenance["source_sha256"]), 64)

    def test_an_unknown_datastream_is_refused_before_anything_is_written(self):
        import uuid
        with self.assertRaises(C.MappingError):
            self.imported("When,VWC\n2026-06-01 14:00,0.291\n",
                          columns={"VWC": {"datastream": str(uuid.uuid4())}})
        self.assertEqual(self.state.live_observations_of(self.ds.id), [])

    def test_the_log_still_validates(self):
        self.imported("When,VWC\n2026-06-01 14:00,0.291\n")
        self.assertEqual(P.state_from_log(self.log).validate(), [])


if __name__ == "__main__":
    unittest.main()
