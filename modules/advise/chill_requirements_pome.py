#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apples' and pears' winter chill, from two openly licensed papers.

    python3 -I modules/advise/chill_requirements_pome.py \\
        --apple-html apple_review.html --apple-refs apple_review_crossref.json \\
        --pear-text pear2023.txt --out modules/advise/data/chill-requirements-pome.csv

The stone-fruit table (modules/advise/chill_requirements.py) left the advisor blind to the pome
fruit, the commonest orchard trees in a temperate farm. Two CC BY 4.0 sources close it:

* **Apples** — González Noguer, Delgado, Else & Hadley (2023), *Apple (Malus × domestica
  Borkh.) dormancy — a review of regulatory mechanisms and agroclimatic requirements*,
  Frontiers in Horticulture 2:1217689, doi:10.3389/fhort.2023.1217689. Its Table 2
  compiles 173 published requirements — cultivar, use (dessert, cider, crab, rootstock),
  place, method, chill hours / Utah units / chill portions, heat — each with its study,
  read here from the article's HTML. Cells that span rows carry their text *and* their
  reference key down, so each row is tied to its study exactly (the table's citation
  buttons and links are keyed `B47`, as the article's references are in Crossref), and
  each key is checked against the author and year the cell prints.
* **Pears** — Fadón, Espiau, Errea & Alonso Segura (2023), *Agroclimatic requirements of
  traditional European pear (Pyrus communis L.) cultivars from Australia, Europe, and
  North America*, Agronomy 13(2):518, doi:10.3390/agronomy13020518. Table 2: 16 cultivars
  over twenty years at Zaragoza, estimated statistically, chill in all three models and
  heat — read from the text `pdftotext -layout` makes of the published PDF.

Values are kept as printed, but for one thing: a few apple rows write a thousand with a
point, European style ("1.005" chill hours), which in the hours, units and degree-hours
columns — whole numbers everywhere else — can only mean 1005. Chill hours are hours
between 0 and 7.2 °C, as in the stone-fruit table and the site profile.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import unicodedata

FIELDS = ["crop", "cultivar", "usage", "chill_hours", "chill_units", "chill_portions", "heat_gdh",
          "method", "location", "source", "study"]
APPLE_SOURCE = "González Noguer et al. 2023, Front. Hortic. 2:1217689, Table 2"
PEAR_SOURCE = "Fadón et al. 2023, Agronomy 13:518, Table 2"
PEAR_STUDY = ("Fadón E, Espiau MT, Errea P, Alonso Segura JM (2023) Agroclimatic requirements of traditional "
              "European pear (Pyrus communis L.) cultivars from Australia, Europe, and North America. "
              "Agronomy 13(2):518. doi:10.3390/agronomy13020518")
APPLE_ROWS, PEAR_ROWS = 173, 16
METHODS = {"E": "experimental", "S": "statistical"}


def _text(inner: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner))).strip()


def table_rows(page: str, index: int = 1) -> list:
    """A HTML table as rows of (text, reference key) cells, row and column spans expanded."""
    table = re.findall(r"<table.*?</table>", page, flags=re.S)[index]
    grid, pending = [], {}
    for row in re.findall(r"<tr.*?</tr>", table, flags=re.S):
        queue = re.findall(r"<t[hd]([^>]*)>(.*?)</t[hd]>", row, flags=re.S)
        out, col = [], 0
        while queue or col in pending:
            if col in pending:
                cell, left = pending[col]
                out.append(cell)
                if left > 1:
                    pending[col] = (cell, left - 1)
                else:
                    del pending[col]
                col += 1
                continue
            attrs, inner = queue.pop(0)
            m = re.search(r'id="(B\d+)-button"|href="#(B\d+)"', inner)
            key = (m.group(1) or m.group(2)) if m else None
            cell = (_text(inner), key)
            rows_spanned = int(m.group(1)) if (m := re.search(r'rowspan="(\d+)"', attrs)) else 1
            cols_spanned = int(m.group(1)) if (m := re.search(r'colspan="(\d+)"', attrs)) else 1
            for _ in range(cols_spanned):
                out.append(cell)
                if rows_spanned > 1:
                    pending[col] = (cell, rows_spanned - 1)
                col += 1
        grid.append(out)
    return grid


def citation(ref: dict) -> str:
    """A Crossref reference as one line, after the table's own author-year (Crossref
    keeps only the first author, so the table's form is the right one to lead with)."""
    parts = []
    if ref.get("article-title"):
        parts.append(ref["article-title"].strip("‘’'\" "))
    venue = " ".join(str(x) for x in (ref.get("journal-title") or ref.get("series-title") or "",
                                      ref.get("volume") or "") if x)
    if venue:
        parts.append(venue + (f":{ref['first-page']}" if ref.get("first-page") else ""))
    if ref.get("DOI"):
        parts.append(f"doi:{ref['DOI']}")
    if not ref.get("article-title"):
        return ref.get("unstructured") or ". ".join(parts) or "?"
    return ". ".join(parts)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def agrees(short: str, ref: dict) -> bool:
    """Whether a reference is the one a cell's "Hauagge and Cummins, 1991" names: same
    first author (accents aside) and year."""
    m = re.match(r"([^\s,]+).*?(\d{4})", short)
    return bool(m) and _fold(ref.get("author") or "").startswith(_fold(m.group(1))) \
        and str(ref.get("year", "")).startswith(m.group(2))


def thousands(value: str) -> str:
    """Hours, units and degree-hours are whole numbers; a few rows write a thousand with a
    point, European style ("1.005"). Only in those columns, where no decimal occurs."""
    return value.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", value) else value


def apples(page: str, crossref: dict) -> list:
    refs = {r.get("key"): r for r in crossref["message"].get("reference", [])}
    out = []
    for row in table_rows(page)[2:]:
        if len(row) != 9:
            raise ValueError(f"apple table row of {len(row)} cells: {row}")
        (cultivar, _), (usage, _), (place, _), (method, _), (ch, _), (cu, _), (cp, _), (gdh, _), (short, key) = row
        ref = refs.get(key)
        ref = ref if ref and agrees(short, ref) else None
        out.append({"crop": "apple", "cultivar": cultivar, "usage": usage.lower() or "-",
                    "chill_hours": thousands(ch) or "-", "chill_units": thousands(cu) or "-",
                    "chill_portions": cp or "-", "heat_gdh": thousands(gdh) or "-",
                    "method": METHODS.get(method, method), "location": place, "source": APPLE_SOURCE,
                    "study": f"{short}: {citation(ref)}" if ref else short})
    return out


PEAR_ROW = re.compile(
    r"^(?P<name>.*?)\s*\d{1,2} [A-Z][a-z]{2}\s+\d{1,2} [A-Z][a-z]{2}\s+\d+\s+"
    r"(?P<cp>[\d.]+ ± [\d.]+)\s+(?P<cu>\d+ ± \d+)\s+(?P<ch>\d+ ± \d+)\s+"
    r"\d{1,2} [A-Z][a-z]{2}\s+\d{1,2} [A-Z][a-z]{2}\s+\d+\s+(?P<gdh>\d+ ± \d+)\s*$")


def pears(text: str) -> list:
    """Table 2 of the pear paper. A name too long for its cell wraps onto the lines either
    side of its data line, which then carries no name."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if "Table 2. Average chilling and forcing" in l)
    out = []
    for i in range(start, min(len(lines), start + 60)):
        m = PEAR_ROW.match(lines[i])
        if not m:
            continue
        name = m.group("name").strip()
        if not name:
            before, after = lines[i - 1].strip(), lines[i + 1].strip()
            name = before[:-1] + after if before.endswith("-") else f"{before} {after}"
        name = name.replace("´", "’")
        out.append({"crop": "pear", "cultivar": name, "usage": "dessert",
                    "chill_hours": m.group("ch"), "chill_units": m.group("cu"),
                    "chill_portions": m.group("cp"), "heat_gdh": m.group("gdh"),
                    "method": "statistical", "location": "Spain", "source": PEAR_SOURCE,
                    "study": PEAR_STUDY})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apple-html", required=True)
    ap.add_argument("--apple-refs", required=True, help="the review's Crossref record (api.crossref.org/works/DOI)")
    ap.add_argument("--pear-text", required=True, help="pdftotext -layout of the pear paper")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with open(args.apple_html, encoding="utf-8", errors="replace") as h:
        page = h.read()
    with open(args.apple_refs, encoding="utf-8") as h:
        crossref = json.load(h)
    with open(args.pear_text, encoding="utf-8") as h:
        pear_text = h.read()
    rows = apples(page, crossref) + pears(pear_text)
    n_apple = sum(r["crop"] == "apple" for r in rows)
    n_pear = sum(r["crop"] == "pear" for r in rows)
    with open(args.out, "w", newline="", encoding="utf-8") as h:
        h.write("# SPDX-License-Identifier: CC-BY-4.0\n"
                "# Apples: González Noguer M, Delgado A, Else MA, Hadley P (2023) Front. Hortic. 2:1217689, "
                "doi:10.3389/fhort.2023.1217689, CC BY 4.0, Table 2. Pears: Fadón E, Espiau MT, Errea P, "
                "Alonso Segura JM (2023) Agronomy 13:518, doi:10.3390/agronomy13020518, CC BY 4.0, Table 2. "
                "Re-keyed by modules/advise/chill_requirements_pome.py, values as printed (but a thousand printed 1.005 "
                "is 1005). CH = chill hours (0-7.2 C), CU = Utah chill units, CP = Dynamic-model chill "
                "portions, GDH = growing degree hours.\n")
        w = csv.DictWriter(h, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{n_apple} apple requirements, {n_pear} pear")
    problems = []
    if n_apple != APPLE_ROWS:
        problems.append(f"apples: {n_apple} rows, the review's table has {APPLE_ROWS}")
    if n_pear != PEAR_ROWS:
        problems.append(f"pears: {n_pear} rows, the paper's table has {PEAR_ROWS}")
    missing = sum(1 for r in rows if r["crop"] == "apple" and ":" not in r["study"])
    if missing:
        problems.append(f"{missing} apple rows whose study is not the reference their key names")
    for p in problems:
        print("  MISMATCH", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
