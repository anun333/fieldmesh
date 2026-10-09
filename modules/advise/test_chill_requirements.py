# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chill tables read back from word positions, on a page built to be awkward.

The synthetic page has what makes the real one hard: names centred across their rows (a
four-row cultivar's name between its second and third rows, nearer the third), a name
wrapped onto two lines, a blank cell beside a "-" one, and a range wider than its column
heading."""
import unittest

import chill_requirements as C

PITCH = 14.4


def word(x0, y, text, width=None):
    width = width or 5.0 * len(text)
    return f'<word xMin="{x0:.1f}" yMin="{y - 4:.1f}" xMax="{x0 + width:.1f}" yMax="{y + 4:.1f}">{text}</word>'


def row(y, ch="-", cu="-", cp="-", gdh="-", method="S", loc="Spain", ref="[26]", name=None):
    out = [word(110, y, name)] if name else []
    for x, v in ((190, ch), (228, cu), (270, cp), (336, gdh)):
        if v is not None:
            out.append(word(x - 2.5 * len(v), y, v))
    out += [word(408, y, method), word(437, y, loc, 3.7 * len(loc)), word(480, y, ref)]
    return out


def page():
    w = [word(150, 60, "Table"), word(180, 60, "1."), word(195, 60, "Chilling"), word(240, 60, "and"),
         word(260, 60, "heat"), word(285, 60, "requirements"), word(350, 60, "of"), word(365, 60, "almond"),
         word(400, 60, "cultivars.")]
    w += [word(117, 80, "Cultivar"), word(396, 80, "Method"), word(443, 80, "Loc."), word(480, 80, "Ref.")]
    w += [word(188, 85, "CH", 12), word(225, 85, "CU", 12), word(268, 85, "CP", 12), word(334, 85, "GDH", 20)]
    y = 100.0
    w += row(y, ch="23", cu="−82", cp="7.6", gdh="9224", loc="Tunisia", ref="[35]", name="Malagueña")
    four = [y + PITCH * k for k in range(1, 5)]                     # Marcona: four rows
    w += row(four[0], ch="169", gdh="High", ref="[33]")
    w += row(four[1], cu="435", gdh="6681", method="E", ref="[43]")
    w += row(four[2], cu="428", gdh="6603")
    w += row(four[3], cp="22.0 ± 4.7", gdh="6378 ± 1341", ref="[36]")
    w.append(word(110, (four[1] + four[2]) / 2 + 3.5, "Marcona"))   # off-centre, as printed
    y = four[3] + PITCH
    w += row(y, ch=None, cu="-", gdh="Very high", ref="[33]", name="Lluch")   # blank CH cell
    three = [y + PITCH * k for k in range(1, 4)]                    # a wrapped name on three rows,
    w += row(three[0], ch="169", gdh="Very high", ref="[33]")       # as the PDF prints one
    w += row(three[1], ch="1015–1105", method="E", ref="[60]")      # a range wider than "CH"
    w += row(three[2], ch="79", cu="−50", cp="21.1", gdh="5368", loc="Tunisia", ref="[35]")
    w += [word(110, three[1] - 4.95, "Fournat"), word(110, three[1] + 4.95, "de Brézenaud")]
    return "<page " + "".join(w) + "</page>"


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.rows, self.worst = C.parse("<doc>" + page() + "</doc>")
        self.by = {}
        for r in self.rows:
            self.by.setdefault(r["cultivar"], []).append(r)

    def test_names_find_their_rows(self):
        self.assertEqual({k: len(v) for k, v in self.by.items()},
                         {"Malagueña": 1, "Marcona": 4, "Lluch": 1, "Fournat de Brézenaud": 3})
        self.assertLess(self.worst, PITCH / 2)

    def test_values_land_in_their_columns(self):
        m = self.by["Malagueña"][0]
        self.assertEqual((m["chill_hours"], m["chill_units"], m["chill_portions"], m["heat_gdh"]),
                         ("23", "−82", "7.6", "9224"))
        self.assertEqual(self.by["Marcona"][3]["chill_portions"], "22.0 ± 4.7")
        self.assertEqual(self.by["Lluch"][0]["chill_hours"], "-", "a blank cell reads as none")
        self.assertEqual(self.by["Fournat de Brézenaud"][1]["chill_hours"], "1015–1105",
                         "a range wider than its heading is a value, not part of a name")

    def test_method_and_place(self):
        self.assertEqual([r["method"] for r in self.by["Marcona"]],
                         ["statistical", "experimental", "statistical", "statistical"])
        self.assertEqual(self.by["Malagueña"][0]["location"], "Tunisia")


class AssignTest(unittest.TestCase):
    def test_each_name_nearest_its_midpoint(self):
        rows = [(y,) for y in (0, 10, 20, 30, 40, 50)]
        names = [(0, "a"), (15, "b"), (45, "c")]
        got = [(n, len(rs)) for n, rs, _ in C.assign(names, rows)]
        self.assertEqual(got, [("a", 1), ("b", 2), ("c", 3)])


class PeachBlockTest(unittest.TestCase):
    def test_blocks_by_count_where_the_alphabet_restarts(self):
        names = [f"W{i}" for i in range(7)] + [f"C{i:02d}" for i in range(25)] + ["Afterglow", "Belle"]
        crops = C.peach_blocks(names)
        self.assertEqual(crops[6], "flat peach")
        self.assertEqual(crops[7], "nectarine")
        self.assertEqual(crops[-1], "peach")

    def test_a_boundary_off_the_alphabet_is_an_error(self):
        with self.assertRaises(ValueError):
            C.peach_blocks([f"A{i}" for i in range(7)] + [f"B{i:02d}" for i in range(26)])  # B00 follows A6


if __name__ == "__main__":
    unittest.main()
