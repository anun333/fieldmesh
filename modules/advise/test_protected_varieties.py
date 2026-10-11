# SPDX-License-Identifier: AGPL-3.0-or-later
"""The protected-variety check, on a small report built the way the PVPO's is."""
import datetime as _dt
import os
import tempfile
import unittest
import zipfile

import protected_varieties as PV

HEAD = ["Application #", "Variety Name", "Experimental Name", "Scientific Name", "Common Name",
        "Applicant ", "Application Date", "Certified Seed", "Certificate Status", "Status Date",
        "Issued Date", "Years Protected"]
ROWS = [["7100001", "Green Ice", "", "Lactuca sativa L.", "Lettuce", "Someone", "", "", "Certificate Expired", "", "04/10/1973", "17"],
        ["202100027", "Kizuri", "WA 2", "Malus domestica Borkh.", "Apple", "Someone", "", "", "Certificate Issued", "", "11/30/2022", "25"],
        ["202300001", "Old Gold", "", "Zea mays L.", "Corn", "Someone", "", "", "Certificate Issued", "", "01/15/2001", "20"],
        ["202500001", "", "38F038", "Glycine max (L.) Merr.", "Soybean", "Someone", "", "", "Application Pending", "", "", ""]]


def xlsx(path):
    def row(n, values):
        cells = "".join(f'<c t="inlineStr" r="{chr(66 + i)}{n}"><is><t>{v}</t></is></c>'
                        for i, v in enumerate(values))
        return f'<row r="{n}">{cells}</row>'
    body = '<row r="1"></row>' + row(2, HEAD) + "".join(row(3 + i, r) for i, r in enumerate(ROWS))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet><sheetData>{body}</sheetData></worksheet>")


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        path = os.path.join(self.dir.name, "r.xlsx")
        xlsx(path)
        self.rows = PV.read(path)
        self.today = _dt.date(2026, 10, 9)

    def tearDown(self):
        self.dir.cleanup()

    def test_the_applicant_is_never_read(self):
        self.assertEqual(len(self.rows), 4)
        self.assertTrue(all("applicant" not in r and "Someone" not in r.values() for r in self.rows))

    def test_a_certificate_in_its_term_protects(self):
        m = PV.check(self.rows, "Kizuri", "Malus domestica", self.today)
        self.assertEqual(PV.verdict(m), "protected")

    def test_a_term_that_has_run_out_does_not(self):
        self.assertEqual(PV.verdict(PV.check(self.rows, "Old Gold", today=self.today)), "not under PVP")
        self.assertEqual(PV.verdict(PV.check(self.rows, "green ice", today=self.today)), "not under PVP")

    def test_a_pending_application_already_protects(self):
        self.assertEqual(PV.verdict(PV.check(self.rows, "38F038", today=self.today)),
                         "provisionally protected")

    def test_the_species_must_agree_when_given(self):
        self.assertEqual(PV.check(self.rows, "Kizuri", "Pyrus communis", self.today), [])
        self.assertEqual(PV.verdict(PV.check(self.rows, "Honeycrisp", today=self.today)), "not found")



class OssiTest(unittest.TestCase):
    """The flag the other way round: pledged free, from a list the farm supplies."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "ossi.csv")
        with open(self.path, "w", encoding="utf-8") as h:
            h.write("variety,crop\nAbundant Bloomsdale,Spinach\n21st Century Fire,Lettuce\n"
                    "Green Ice,Lettuce\n")

    def tearDown(self):
        self.dir.cleanup()

    def test_a_pledged_variety_is_flagged_and_an_unlisted_one_is_not(self):
        ossi = PV.read_ossi(self.path)
        self.assertEqual(len(PV.pledged(ossi, "abundant  bloomsdale")), 1)
        self.assertEqual(PV.pledged(ossi, "Abundant Bloomsdale", "Corn"), [])
        note = PV.ossi_note(PV.pledged(ossi, "21st Century Fire", "lettuce"), "not found")
        self.assertTrue(note.startswith("OSSI-pledged (Lettuce): free to use, save, breed"))
        self.assertEqual(PV.ossi_note([], "not found"), "not on the OSSI list given")

    def test_pledged_and_under_a_certificate_is_called_out(self):
        ossi = PV.read_ossi(self.path)
        self.assertIn("ask the breeder", PV.ossi_note(PV.pledged(ossi, "Green Ice"), "protected"))
        self.assertNotIn("ask the breeder", PV.ossi_note(PV.pledged(ossi, "Green Ice"), "not under PVP"))

    def test_a_list_without_varieties_is_refused(self):
        with open(self.path, "w", encoding="utf-8") as h:
            h.write("name,crop\nX,Y\n")
        with self.assertRaisesRegex(ValueError, "variety"):
            PV.read_ossi(self.path)


if __name__ == "__main__":
    unittest.main()
