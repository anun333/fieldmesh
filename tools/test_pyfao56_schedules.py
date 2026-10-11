# SPDX-License-Identifier: Apache-2.0
"""pyfao56's saved schedule: the drill's bed, every summer, and reproducible where pyfao56 is."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "sim"))

import irrigation_drill as D  # noqa: E402
import pyfao56_schedules as S  # noqa: E402

try:
    import pyfao56  # noqa: F401
    HAVE_PYFAO56 = True
except ImportError:
    HAVE_PYFAO56 = False


class TestTheSavedSchedule(unittest.TestCase):
    def test_it_waters_the_drills_own_bed(self):
        bed = D.bed()
        self.assertEqual((S.BED["thetaFC"], S.BED["thetaWP"], S.BED["theta0"]),
                         (bed.field_capacity, bed.wilting_point, bed.theta))
        self.assertEqual(S.BED["Zrmax"] * 1000.0, bed.depth_mm)
        self.assertAlmostEqual(S.BED["Kcbmid"], bed.crop_coefficient)
        self.assertAlmostEqual(S.MAD, 1 / 3, msg="the soil probe rule's refill point")

    def test_every_summer_is_there_and_every_depth_is_a_watering(self):
        schedule = D.pyfao56_schedule()
        years = {d.year for d in schedule}
        self.assertEqual(years, set(range(1991, 2021)))
        self.assertTrue(all(dt.date(d.year, 6, 1) <= d <= dt.date(d.year, 8, 31) for d in schedule))
        self.assertTrue(all(0.0 < mm < 60.0 for mm in schedule.values()))


@unittest.skipUnless(HAVE_PYFAO56, "pyfao56 runs in an environment of its own (see the module)")
class TestReproduced(unittest.TestCase):
    def test_a_summer_comes_out_as_saved(self):
        import physics as ph
        weather = os.environ.get("FIELDMESH_WEATHER_1991_2020")
        if not weather:
            self.skipTest("set FIELDMESH_WEATHER_1991_2020 to the thirty-year weather CSV")
        got = dict(S.schedule(ph.RecordedClimate.from_csv(weather), 2013))
        saved = {d: mm for d, mm in D.pyfao56_schedule().items() if d.year == 2013}
        self.assertEqual(got, saved)


if __name__ == "__main__":
    unittest.main()
