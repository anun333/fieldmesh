# SPDX-License-Identifier: Apache-2.0
"""Scoring real forecasts against a station, without the network: file keys, units, and
the score on a log built by hand."""
import datetime as dt
import unittest

import nbm_verify as N

UTC = dt.timezone.utc
HOUR = dt.timedelta(hours=1)


class KeyTest(unittest.TestCase):
    def test_the_archive_s_layout(self):
        issued = dt.datetime(2026, 4, 1, 0, tzinfo=UTC)
        self.assertEqual(N.nbm_key(issued, issued + 12 * HOUR),
                         "blendv4.3/conus/2026/04/01/0000/temp/"
                         "blendv4.3_conus_temp_2026-04-01T00:00_2026-04-01T12:00.tif")

    def test_fahrenheit(self):
        self.assertAlmostEqual(N.f_to_c(28.0), -2.2222, places=3)


class ScoreTest(unittest.TestCase):
    def test_bias_lead_and_the_frost_watch(self):
        t0 = dt.datetime(2026, 3, 1, 0, tzinfo=UTC)
        # The station: 40 °F, except a frost of 24 °F from 09 to 12 UTC on March 3.
        station = [(t0 + k * HOUR, 24.0 if 57 <= k <= 60 else 40.0) for k in range(24 * 6)]
        # Each run forecasts 2 °F warm, and misses the frost to 30 °F.
        runs = {}
        for i in range(0, 72, 12):
            issued = t0 + i * HOUR
            runs[issued] = [(issued + lead * HOUR, (30.0 if 57 <= i + lead <= 60 else 42.0))
                            for lead in N.LEADS_H if i + lead < 24 * 6]
        state, raw, fc = N.build_log(runs, station)
        self.assertEqual(state.validate(), [])
        s = N.score(state, raw, fc)
        self.assertAlmostEqual(s["by_lead_day"][0]["bias_c"], 2.0 * 5 / 9, delta=0.6)
        (night,) = s["frost_nights"]
        self.assertAlmostEqual(night["observed_min_c"], N.f_to_c(24.0))
        self.assertEqual(night["warned"], {1.0: True, 0.0: True, -1.0: True, -2.2: False})


if __name__ == "__main__":
    unittest.main()
