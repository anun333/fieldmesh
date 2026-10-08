#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests, on a response recorded from Soil Data Access for McAllister Farm."""
from __future__ import annotations

import unittest

import soil_survey as S

#: Recorded 2026-10-08 for (35.06445, -86.59137), trimmed to the fields queried.
RECORDED = {"Table": [
    ["muname", "compname", "comppct_r", "hzdept_r", "hzdepb_r", "sandtotal_r",
     "claytotal_r", "wsatiated_r", "wthirdbar_r", "wfifteenbar_r"],
    ["Dickson silt loam, 2 to 5 percent slopes", "Dickson", "85", "0", "25", "20.4",
     "10.5", "42", "25.8", "10"],
    ["Dickson silt loam, 2 to 5 percent slopes", "Dickson", "85", "25", "61", "16.2",
     "19.4", "41", "27.5", "12.1"],
    ["Dickson silt loam, 2 to 5 percent slopes", "Dickson", "85", "61", "107", "16.6",
     "24.6", "46", "28.9", "13.8"],
    ["Dickson silt loam, 2 to 5 percent slopes", "Dickson", "85", "107", "183", "26.4",
     "43.5", "44", "37", "23.7"],
    ["Dickson silt loam, 2 to 5 percent slopes", "Dickson", "85", "183", "208", None,
     None, None, None, None],
]}


class TestSoilSurvey(unittest.TestCase):

    def setUp(self):
        self.soil = S.parse(RECORDED)

    def test_the_dominant_soil_is_read(self):
        self.assertEqual(self.soil["component"], "Dickson")
        self.assertEqual(len(self.soil["horizons"]), 5)

    def test_water_contents_are_converted_from_percent(self):
        """SSURGO reports volume percent; the farm stores m3/m3. Mixing them is a
        100x error of exactly the kind the calibration bug produced."""
        self.assertEqual(self.soil["horizons"][0]["saturated"], 0.42)

    def test_a_probe_at_5_cm_gets_the_maps_saturation_plus_a_margin(self):
        """0.44 — tighter than the generic 0.46, which let 0.42-0.46 pass in a soil
        that saturates at 0.42."""
        limits = S.proposed_limits(self.soil, 0.05)
        self.assertEqual(limits["max"], 0.44)
        self.assertEqual(limits["texture"], "loamy")
        self.assertEqual(limits["source"]["component"], "Dickson")

    def test_a_deep_clayey_horizon_gets_a_longer_flatline(self):
        """1.2 m here is 43.5% clay: in a temperate climate the measured dwell is 58 h,
        so 116 h with the stated factor of two — not the 18 h that misfired at depth."""
        limits = S.proposed_limits(self.soil, 1.2, "C")
        self.assertEqual(limits["texture"], "clayey")
        self.assertEqual(limits["flat_seconds"], 116 * 3600)
        self.assertEqual(limits["source"]["dwell_climate"], "C")

    def test_an_unknown_climate_takes_the_longest_measured_dwell(self):
        for depth, kind_band in ((0.05, ("loamy", "top")), (1.2, ("clayey", "deep"))):
            longest = max(S.DWELL_P999_H[c][kind_band] for c in "BCD")
            for climate in (None, "A", "E"):
                limits = S.proposed_limits(self.soil, depth, climate)
                self.assertEqual(limits["flat_seconds"],
                                 int(longest * S.DWELL_FACTOR * 3600), (depth, climate))
                self.assertEqual(limits["source"]["dwell_climate"], "unknown")

    def test_dry_sand_dwells_longest_at_depth(self):
        """Measured, and the reason climate is a key at all: in a dry climate deep sand
        changes least, the reverse of the temperate ordering."""
        dry, temperate = S.DWELL_P999_H["B"], S.DWELL_P999_H["C"]
        self.assertGreater(dry[("sandy", "deep")], dry[("clayey", "deep")])
        self.assertLess(temperate[("sandy", "deep")], temperate[("clayey", "deep")])

    def test_a_thinly_measured_cell_takes_the_temperate_value(self):
        self.assertEqual(S.DWELL_P999_H["D"][("clayey", "deep")],
                         S.DWELL_P999_H["C"][("clayey", "deep")])
        self.assertEqual(S.DWELL_P999_H["D"][("loamy", "deep")], 38)

    def test_below_the_described_profile_there_is_no_proposal(self):
        """183-208 cm has no properties; no guess is offered."""
        self.assertIsNone(S.proposed_limits(self.soil, 1.95))
        self.assertIsNone(S.proposed_limits(self.soil, 3.0))

    def test_an_empty_response_is_no_soil_rather_than_an_error(self):
        self.assertEqual(S.parse({"Table": []})["horizons"], [])


if __name__ == "__main__":
    unittest.main()
