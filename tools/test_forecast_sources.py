# SPDX-License-Identifier: Apache-2.0
"""Forecast runs from NWS (a real, trimmed run) and MET Norway (its documented shape),
and into layer zero's log as a forecast datastream."""
import datetime as dt
import json
import os
import sys
import unittest

import forecast_sources as FS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import forecast as FC  # noqa: E402
import project as P  # noqa: E402
from ids import uuid7  # noqa: E402
from log import Log  # noqa: E402
from model import Datastream, DatastreamKind  # noqa: E402

UTC = dt.timezone.utc
FIXTURE = os.path.join(HERE, "fixtures", "nws-gridpoint-HUN-62-57.json")


class DurationTest(unittest.TestCase):
    def test_iso_durations(self):
        self.assertEqual([FS.duration_hours(d) for d in ("PT1H", "PT13H", "P1D", "P1DT6H")], [1, 13, 24, 30])
        with self.assertRaises(ValueError):
            FS.duration_hours("PT30M")

    def test_amounts_are_spread_and_past_hours_dropped(self):
        issued = dt.datetime(2026, 10, 9, 8, 30, tzinfo=UTC)
        vals = [{"validTime": "2026-10-09T06:00:00+00:00/PT6H", "value": 12.0}]
        out = FS.expand(vals, issued, amount=True)
        self.assertEqual([t.hour for t, _ in out], [8, 9, 10, 11], "06:00 and 07:00 had ended")
        self.assertEqual({v for _, v in out}, {2.0})


class NwsTest(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE, encoding="utf-8") as h:
            self.doc = json.load(h)
        self.run = FS.nws_run(self.doc)

    def test_issue_time_and_units(self):
        self.assertEqual(self.run.issued_at, dt.datetime(2026, 10, 9, 8, 28, 39, tzinfo=UTC))
        self.assertEqual(self.run.units, {"air_temperature": "Cel", "relative_humidity": "%",
                                          "wind_speed": "km/h", "precipitation": "mm"})

    def test_hourly_and_none_before_the_issue(self):
        temps = self.run.series["air_temperature"]
        self.assertTrue(all(t + FS.HOUR > self.run.issued_at for t, _ in temps))
        gaps = {(b[0] - a[0]) for a, b in zip(temps, temps[1:])}
        self.assertEqual(gaps, {FS.HOUR})

    def test_rain_is_conserved(self):
        issued = self.run.issued_at
        sent = 0.0
        for item in self.doc["properties"]["quantitativePrecipitation"]["values"]:
            start, _, dur = item["validTime"].partition("/")
            if FS.parse_time(start) >= issued.replace(minute=0, second=0) + FS.HOUR:
                sent += item["value"]
        got = sum(v for t, v in self.run.series["precipitation"]
                  if t >= issued.replace(minute=0, second=0) + FS.HOUR)
        self.assertAlmostEqual(got, sent, places=6)

    def test_into_the_log(self):
        ds = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(), feature=uuid7(),
                        observed_property=FS.VARIABLES["air_temperature"][0], unit="Cel",
                        kind=DatastreamKind.FORECAST, expected_interval=3600.0, max_latency=3600.0)
        state, log = P.State(), Log()
        state.add(ds)
        log.append_record(ds)
        r = FC.ingest(log, state, ds.id, self.run.issued_at, self.run.series["air_temperature"],
                      uncertainty_s=1800, provenance=self.run.provenance())
        self.assertEqual(r.written, len(self.run.series["air_temperature"]))
        self.assertEqual(state.validate(), [])


class MetnoTest(unittest.TestCase):
    DOC = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10.75, 59.91, 30]},
           "properties": {
               "meta": {"updated_at": "2026-10-09T08:00:00Z",
                        "units": {"air_temperature": "celsius", "precipitation_amount": "mm",
                                  "relative_humidity": "%", "wind_speed": "m/s"}},
               "timeseries": [
                   {"time": "2026-10-09T07:00:00Z", "data": {"instant": {"details": {"air_temperature": 9.0}},
                                                            "next_1_hours": {"details": {"precipitation_amount": 9.9}}}},
                   {"time": "2026-10-09T08:00:00Z", "data": {"instant": {"details": {"air_temperature": 9.5, "relative_humidity": 80.0, "wind_speed": 3.1}},
                                                            "next_1_hours": {"details": {"precipitation_amount": 0.4}},
                                                            "next_6_hours": {"details": {"precipitation_amount": 2.0}}}},
                   {"time": "2026-10-09T09:00:00Z", "data": {"instant": {"details": {"air_temperature": 10.0}},
                                                            "next_1_hours": {"details": {"precipitation_amount": 0.2}}}},
                   {"time": "2026-10-10T00:00:00Z", "data": {"instant": {"details": {"air_temperature": 4.0}},
                                                            "next_6_hours": {"details": {"precipitation_amount": 3.0}}}}]}}

    def test_shape(self):
        run = FS.metno_run(self.DOC)
        self.assertEqual(run.issued_at, dt.datetime(2026, 10, 9, 8, tzinfo=UTC))
        self.assertEqual([v for _, v in run.series["air_temperature"]], [9.5, 10.0, 4.0], "07:00 had ended")
        rain = run.series["precipitation"]
        self.assertEqual([v for _, v in rain[:2]], [0.4, 0.2], "hourly where given")
        self.assertEqual(len(rain), 8)
        self.assertAlmostEqual(sum(v for _, v in rain[2:]), 3.0, "six-hourly spread over six")
        self.assertEqual(run.units["wind_speed"], "m/s")

    def test_daily_summary(self):
        run = FS.metno_run(self.DOC)
        (day1, d1), (day2, d2) = FS.daily(run)
        self.assertEqual((d1["min"], d1["max"]), (9.5, 10.0))
        self.assertAlmostEqual(d1["rain"], 0.6)


if __name__ == "__main__":
    unittest.main()
