# SPDX-License-Identifier: AGPL-3.0-or-later
"""The apple and pear tables read back, on pages built to be awkward.

The apple table has what makes the real one hard: a header spanning two rows and three
columns, a cultivar whose name and study span two rows, a citation that is a link where
the others are buttons, a thousand written with a point, and a blank use. The pear text
has a name wrapped across the lines either side of its data line."""
import unittest

import chill_requirements_pome as C


def td(text, rowspan=1, key=None, link=False):
    span = f' rowspan="{rowspan}"' if rowspan > 1 else ""
    if key and link:
        text = f'<a href="#{key}" class="ArticleReference">{text}</a>'
    elif key:
        text = (f'<button type="button" id="{key}-button" class="ArticleReference">'
                f'<span id="{key}a" aria-hidden="true"></span>{text}</button>')
    return f'<td valign="middle"{span} align="left">{text}</td>'


HEAD = ('<tr><th rowspan="2">Cultivar</th><th rowspan="2">Usage</th><th rowspan="2">Location</th>'
        '<th rowspan="2">Method</th><th colspan="3">Chilling requirements</th><th>Heat req</th>'
        '<th rowspan="2">Reference</th></tr><tr><th>CH</th><th>CU</th><th>CP</th><th>GDH</th></tr>')
ROWS = [
    td("Anna") + td("Dessert") + td("Egypt") + td("E") + td("253") + td("233") + td("") + td("5731")
    + td("El-Agamy et al., 2000", key="B2"),
    td("Golden Delicious", 2) + td("Dessert") + td("Spain") + td("S") + td("") + td("") + td("62.1")
    + td("9015") + td("Díez-Palet et al., 2019", 2, key="B3"),
    td("Cider") + td("Spain") + td("S") + td("1.005") + td("1.495") + td("72.7") + td("11111"),
    td("Edgar") + td("") + td("USA") + td("E") + td("1127") + td("") + td("") + td("")
    + td("Hauagge and Cummins, 1991", key="B1", link=True),
]
PAGE = ("<table><tr><td>a layout table first</td></tr></table>"
        "<table>" + HEAD + "".join(f"<tr>{r}</tr>" for r in ROWS) + "</table>")
CROSSREF = {"message": {"reference": [
    {"key": "B1", "author": "Hauagge", "year": "1991", "article-title": "Phenotypic variation",
     "journal-title": "J. Am. Soc. Hortic. Sci.", "volume": "116", "first-page": "100",
     "DOI": "10.21273/JASHS.116.1.100"},
    {"key": "B2", "author": "Smith", "year": "2000", "article-title": "Not El-Agamy's paper"},
    {"key": "B3", "author": "Diez-Palet", "year": "2019", "article-title": "Blooming under Mediterranean climate"},
]}}

PEAR_TEXT = """
                 Table 2. Average chilling and forcing periods and agroclimatic requirements (mean ± sd)
      Cultivar        Start   End   (Days)   CP   CU   CH   Start   End   (Days)   GDH
   Alexandrine
                  10 Nov 16 Jan           67        47.5 ± 2.5 1027 ± 141 753 ± 117 28 Jan     26 Mar          58         7287 ± 945
    Douillard
 Beurré d´Anjou 08 Nov 15 Jan             65        47.7 ± 2.8   1100 ± 100 745 ± 117 30 Jan   03 Apr          62        6619 ± 750
 Packham´s Tri-
                  10 Nov 16 Jan           67        47.5 ± 2.5   1163 ± 31 753 ± 117 29 Jan    29 Mar          60        6997 ± 1048
      umph
Agronomy 2023, 13, 518                                                                                                  6 of 13
"""


class AppleTest(unittest.TestCase):
    def setUp(self):
        self.rows = C.apples(PAGE, CROSSREF)

    def test_spans_expand_and_carry_the_study(self):
        self.assertEqual([r["cultivar"] for r in self.rows], ["Anna", "Golden Delicious", "Golden Delicious", "Edgar"])
        self.assertEqual([r["usage"] for r in self.rows], ["dessert", "dessert", "cider", "-"])
        cider = self.rows[2]
        self.assertTrue(cider["study"].startswith("Díez-Palet et al., 2019: Blooming"))
        self.assertEqual((cider["chill_portions"], cider["method"]), ("72.7", "statistical"))

    def test_a_point_thousand_is_read_as_one(self):
        cider = self.rows[2]
        self.assertEqual((cider["chill_hours"], cider["chill_units"], cider["heat_gdh"]), ("1005", "1495", "11111"))
        self.assertEqual(C.thousands("62.1"), "62.1")
        self.assertEqual(C.thousands("1.234.567"), "1234567")

    def test_a_link_citation_resolves_like_a_button(self):
        edgar = self.rows[3]
        self.assertEqual(edgar["study"], "Hauagge and Cummins, 1991: Phenotypic variation. "
                                         "J. Am. Soc. Hortic. Sci. 116:100. doi:10.21273/JASHS.116.1.100")
        self.assertEqual((edgar["chill_units"], edgar["heat_gdh"]), ("-", "-"))

    def test_a_key_naming_another_paper_is_not_taken(self):
        self.assertEqual(self.rows[0]["study"], "El-Agamy et al., 2000")


class PearTest(unittest.TestCase):
    def test_wrapped_names_and_values(self):
        rows = C.pears(PEAR_TEXT)
        self.assertEqual([r["cultivar"] for r in rows], ["Alexandrine Douillard", "Beurré d’Anjou", "Packham’s Triumph"])
        self.assertEqual((rows[0]["chill_hours"], rows[0]["chill_units"], rows[0]["chill_portions"], rows[0]["heat_gdh"]),
                         ("753 ± 117", "1027 ± 141", "47.5 ± 2.5", "7287 ± 945"))
        self.assertEqual(rows[2]["heat_gdh"], "6997 ± 1048")


if __name__ == "__main__":
    unittest.main()
