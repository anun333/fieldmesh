# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field erosion map on a synthetic slope, with a soil polygon that has a hole."""
import unittest

import erosion_map as E
import site_profile as SP


def plane(slope_pct, n=12, step=0.0001, lat=35.0):
    """A DEM rising northward at `slope_pct`, in a grid of `n` x `n` cells."""
    dy_m = step * 110540.0
    pts = [(-86.6 + i * step, lat + j * step, 100.0 + j * dy_m * slope_pct / 100.0)
           for i in range(n) for j in range(n)]
    return E.grid(pts)


class GeometryTest(unittest.TestCase):
    def test_multipolygons_and_holes(self):
        polys = E.parse_wkt("MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0), (4 4, 6 4, 6 6, 4 6, 4 4)), "
                            "((20 20, 30 20, 30 30, 20 30, 20 20)))")
        self.assertEqual(len(polys), 2)
        self.assertTrue(E.contains(polys, 2, 2))
        self.assertFalse(E.contains(polys, 5, 5), "in the hole")
        self.assertTrue(E.contains(polys, 25, 25))
        self.assertFalse(E.contains(polys, 15, 15))


class SlopeTest(unittest.TestCase):
    def test_a_plane_reads_its_own_slope(self):
        g = plane(5.0)
        self.assertAlmostEqual(E.slope_pct(g, 5, 5), 5.0, places=1)
        self.assertIsNone(E.slope_pct(g, 0, 5), "an edge cell has no neighbours to difference")


class CellsTest(unittest.TestCase):
    def test_loss_against_tolerable_by_the_cell_s_own_soil(self):
        g = plane(5.0)
        field = [[[(-86.61, 34.99), (-86.58, 34.99), (-86.58, 35.01), (-86.61, 35.01)]]]
        unit = ([[[(-86.61, 34.99), (-86.58, 34.99), (-86.58, 35.01), (-86.61, 35.01)]]],
                {"mukey": "1", "muname": "silt loam", "k": 0.43, "t": 4.0})
        rows = E.cells(g, field, [unit], r_si=5000.0, c=0.3)
        self.assertEqual(len(rows), 10 * 10, "edge cells drop out")
        r = rows[0]
        expected = 5000.0 * 0.43 * E.K_TO_SI * SP.ls_factor(r["slope_pct"], 30.0) * 0.3
        self.assertAlmostEqual(r["loss_t_ha"], round(expected, 2), places=1)
        s = E.summary(rows)
        self.assertEqual(s["share_over_tolerable"], 1.0)
        hay = E.summary(E.cells(g, field, [unit], r_si=5000.0, c=0.01))
        self.assertEqual(hay["share_over_tolerable"], 0.0)

    def test_a_cell_outside_every_soil_polygon_is_left_out_not_guessed(self):
        g = plane(5.0)
        field = [[[(-86.61, 34.99), (-86.58, 34.99), (-86.58, 35.01), (-86.61, 35.01)]]]
        self.assertEqual(E.cells(g, field, [], r_si=5000.0, c=0.3), [])


if __name__ == "__main__":
    unittest.main()
