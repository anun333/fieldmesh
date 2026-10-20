# SPDX-License-Identifier: Apache-2.0
"""Rain forecasts scored day by day against the station (`rain_event_score.py`): a day's
lead, 1 mm a rain day, the station's inches read as inches."""
import dataclasses
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import fixtures as FX  # noqa: E402
import rain_event_score as R  # noqa: E402
import vocab as V  # noqa: E402
from model import DatastreamKind  # noqa: E402
from project import State  # noqa: E402

UTC = dt.timezone.utc
HOUR = dt.timedelta(hours=1)
DAY0 = dt.datetime(2026, 10, 9, tzinfo=UTC)


def station(daily_inches):
    s = State()
    ds = FX.raw_datastream(unit="[in_i]", observed_property=V.PRECIPITATION_DEPTH, expected_interval=3600.0)
    s.add(ds)
    for d, inches in enumerate(daily_inches):
        for h in range(24):
            s.add(FX.observation(ds, result=inches if h == 12 else 0.0,
                                 measured_at=DAY0 + (24 * d + h) * HOUR, seq=24 * d + h))
    return s


def forecasts(issues):
    """`issues`: `[(issued_at, mm a day for the days after)]`, the mm at noon."""
    s = State()
    ds = FX.raw_datastream(unit="mm", observed_property=V.PRECIPITATION_DEPTH, expected_interval=3600.0)
    ds = dataclasses.replace(ds, kind=DatastreamKind.FORECAST)
    s.add(ds)
    seq = 0
    for issued, days in issues:
        first = (issued + dt.timedelta(days=1)).replace(hour=0, minute=0)
        for d, mm in enumerate(days):
            for h in range(24):
                seq += 1
                s.add(FX.observation(ds, result=mm if h == 12 else 0.0, measured_at=first + (24 * d + h) * HOUR,
                                     issued_at=issued, received_at=issued, seq=seq % 65536))
    return s


class TestRainDays(unittest.TestCase):
    def test_a_rain_day_missed_and_a_dry_day_forecast_wet(self):
        st = station([0.0, 0.5, 0.0, 0.0])         # 12.7 mm on the second day
        fc = forecasts([(DAY0 + 11 * HOUR, [0.0, 0.0]),          # the 10th: 12.7 mm, forecast dry
                        (DAY0 + 35 * HOUR, [5.0]),               # the 11th: dry, forecast 5 mm
                        (DAY0 + 59 * HOUR, [0.0])])              # the 12th: dry, forecast dry
        s = R.score(fc, st)
        self.assertEqual((s["rain_day_issues"], s["dry_day_issues"]), (1, 2))
        self.assertEqual(s["miss"][0], 1.0)
        self.assertEqual(s["false_alarm"][0], 0.5)
        [wet] = [r for r in s["rows"] if r["observed_mm"] >= 1.0]
        self.assertEqual(wet["observed_mm"], 12.7, "inches read as inches")

    def test_a_unit_it_does_not_know_is_refused(self):
        st = station([0.0])
        ds = next(iter(st.datastreams.values()))
        st.datastreams[ds.id] = dataclasses.replace(ds, unit="[ft_i]")
        with self.assertRaises(SystemExit):
            R.score(forecasts([]), st)

    def test_wilson(self):
        lo, hi = R.wilson(0, 4)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.40, places=2)


if __name__ == "__main__":
    unittest.main()
