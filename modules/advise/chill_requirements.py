#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fruit cultivars' winter chill, from an openly licensed review.

    pdftotext -bbox fadon2020.pdf fadon2020.html
    python3 -I modules/advise/chill_requirements.py fadon2020.html --out modules/advise/data/chill-requirements.csv

A peach or cherry that does not get its winter chill flowers late, unevenly or not at all,
so a site's chill hours (modules/advise/site_profile.py) only mean something against a cultivar's
requirement. The open sources for those requirements are few: FAO ECOCROP is
non-commercial, and the most complete recent dataset (CITA Aragón's, 143 cultivars) is
CC BY-NC-ND. This reads the tables of

    Fadón E, Herrera S, Guerrero BI, Guerra ME, Rodrigo J (2020) Chilling and heat
    requirements of temperate stone fruit trees (Prunus sp.). Agronomy 10(3):409.
    doi:10.3390/agronomy10030409 — CC BY 4.0

— 530 cultivars of almond, apricot, peach, nectarine, plum and cherry, each requirement
with its chill model, method, place and original study — from the word positions
`pdftotext -bbox` gives for the published PDF.

The tables centre each cultivar's name across its rows, which is what makes them hard to
read as text: a four-row cultivar's name can land beside its third row. Read by position
it is easy. A name sits at the midpoint of its rows, so on each page the rows are split
into one contiguous run per name, choosing the split that puts every name nearest its
run's midpoint (least squares, by dynamic programming). The parse is checked against the
review's own count of cultivars per crop (its Table 8).

Units as published: chill hours (CH, hours between 0 and 7.2 °C), chill units (CU, Utah
model, can be negative), chill portions (CP, Dynamic model), growing degree hours (GDH).
Values are kept as printed — ranges, ± spreads, "<300", "Very high" — because flattening
them would claim a precision the studies do not.
"""
from __future__ import annotations

import argparse
import csv
import html
import re

TABLES = {1: "almond", 2: "European apricot", 3: "Japanese apricot", 4: "peach",
          5: "European plum", 6: "Japanese plum", 7: "cherry (sweet or sour)"}

#: Table 4 runs block by block — flat peach, nectarine, peach — with each block's label in a
#: column of its own left of the names. The labels are not centred on their blocks (the
#: nectarine label sits 12 pt off), so the blocks are taken from the review's own counts
#: in order, and each boundary is checked to fall where the alphabet starts again.
PEACH_BLOCKS = (("flat peach", 7), ("nectarine", 25), ("peach", None))
PEACH_LABEL_X = 125.0

#: The review's Table 8 (cultivars per crop) — the parse must reproduce it. One exception,
#: the review's own: Table 8 counts 50 cherries, but Table 7 lists 51 names (49 sweet,
#: '0900 Ziraat', and Montmorency, the one sour cherry).
CULTIVARS = {"almond": 106, "European apricot": 68, "Japanese apricot": 77, "flat peach": 7,
             "nectarine": 25, "peach": 172, "European plum": 9, "Japanese plum": 16,
             "cherry (sweet or sour)": 51}

WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
TITLE = re.compile(r"^Table (\d)\. (Cont\.|Chilling and heat requirements of)")
LINE_TOL = 2.0          # points: words within this of a line's centre are on it
#: Points: a name continued on the next line is closer than this. Right for this PDF's
#: geometry (its one wrapped name gaps 2.0 pt; names on neighbouring rows 6 pt or more). A
#: wrapped name on a one-row cultivar directly under a named row would be merged with it;
#: none occurs here, and the cultivar-count check would catch one.
WRAP_GAP = 3.5


def pages(doc: str) -> list:
    """[[(x0, y0, x1, y1, text)]] per page."""
    return [[(float(a), float(b), float(c), float(d), html.unescape(w)) for a, b, c, d, w in WORD.findall(p)]
            for p in doc.split("<page ")[1:]]


def lines(words: list) -> list:
    """Words clustered into lines: [(y centre, [words left to right])]."""
    out = []
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        y = (w[1] + w[3]) / 2
        if out and y - out[-1][0] <= LINE_TOL:
            out[-1][1].append(w)
        else:
            out.append([y, [w]])
    return [(sum((w[1] + w[3]) / 2 for w in ws) / len(ws), sorted(ws)) for _, ws in out]


def text_of(ws) -> str:
    return " ".join(w[4] for w in ws)


def fragments(page: list):
    """Yield (table, [lines]) for each table, or piece of one, on a page."""
    ls = lines(page)
    starts = [(i, int(m.group(1))) for i, (_, ws) in enumerate(ls) if (m := TITLE.match(text_of(ws)))]
    for k, (i, table) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(ls)
        yield table, ls[i + 1:end]


def read_fragment(table: int, ls: list):
    """(names [(y, name)], rows [(y, values, method, location, ref)]) for one fragment."""
    units = next(ws for _, ws in ls if [w[4] for w in ws if w[4] in ("CH", "CU", "CP", "GDH")] == ["CH", "CU", "CP", "GDH"])
    centre = {w[4]: (w[0] + w[2]) / 2 for w in units if w[4] in ("CH", "CU", "CP", "GDH")}
    head = next(ws for _, ws in ls if any(w[4] == "Method" for w in ws))
    method_x = next((w[0] + w[2]) / 2 for w in head if w[4] == "Method")
    ref_x0 = next(w[0] for w in head if w[4] == "Ref.")
    cultivar_x = next((w[0] + w[2]) / 2 for _, ws in ls for w in ws if w[4] == "Cultivar")
    # A word is a name's if its centre is nearer the Cultivar heading than the CH column:
    # a range like 1015–1105 is wider than its heading and starts left of it.
    is_name = lambda w: abs((w[0] + w[2]) / 2 - cultivar_x) < abs((w[0] + w[2]) / 2 - centre["CH"])
    below = [(y, ws) for y, ws in ls if y > max((w[1] + w[3]) / 2 for w in units) + LINE_TOL]

    rows, row_ys = [], []
    for y, ws in below:
        ref = [w for w in ws if w[0] >= ref_x0 - 10]
        meth = [w for w in ws if abs((w[0] + w[2]) / 2 - method_x) < 15 and w[4] in ("E", "S")]
        if not ref or not meth or not ref[0][4].startswith("["):
            continue
        cols = {k: [] for k in ("CH", "CU", "CP", "GDH")}
        for w in ws:
            if not is_name(w) and w[2] < method_x - 15:
                k = min(cols, key=lambda c: abs(centre[c] - (w[0] + w[2]) / 2))
                cols[k].append(w)
        loc = [w for w in ws if meth[0][2] < w[0] and w[2] < ref_x0 - 5]
        rows.append((y, [text_of(cols[k]) or "-" for k in cols], meth[0][4], text_of(loc),
                     text_of(ref).strip("[]")))
        row_ys.append(y)
    if not rows:
        return [], []
    top, bottom = rows[0][0] - 12, rows[-1][0] + 12
    pieces = []
    for y, ws in below:
        ws = [w for w in ws if is_name(w) and not (table == 4 and w[2] < PEACH_LABEL_X)]
        if ws and top <= y <= bottom:
            pieces.append([y, min(w[1] for w in ws), max(w[3] for w in ws), text_of(ws)])
    names = []
    for y, y0, y1, name in pieces:
        if names and y0 - names[-1][2] < WRAP_GAP:
            prev = names[-1]
            names[-1] = [(prev[0] + y) / 2, prev[1], y1, prev[3] + " " + name]
        else:
            names.append([y, y0, y1, name])
    return [(y, n) for y, _, _, n in names], rows


def assign(names: list, rows: list) -> list:
    """Contiguous runs of rows, one per name, each name nearest its run's midpoint."""
    m, n = len(names), len(rows)
    if m > n:
        raise ValueError(f"more names than rows near {names[0][1]!r}")
    inf = float("inf")
    cost = [[inf] * (n + 1) for _ in range(m + 1)]
    back = [[0] * (n + 1) for _ in range(m + 1)]
    cost[0][0] = 0.0
    for i in range(1, m + 1):
        for j in range(i, n - (m - i) + 1):
            for k in range(i - 1, j):
                if cost[i - 1][k] == inf:
                    continue
                c = cost[i - 1][k] + (names[i - 1][0] - (rows[k][0] + rows[j - 1][0]) / 2) ** 2
                if c < cost[i][j]:
                    cost[i][j], back[i][j] = c, k
    out, j = [], n
    for i in range(m, 0, -1):
        k = back[i][j]
        out.append((names[i - 1][1], rows[k:j], abs(names[i - 1][0] - (rows[k][0] + rows[j - 1][0]) / 2)))
        j = k
    return out[::-1]


def peach_blocks(names: list) -> list:
    """Table 4's cultivars, in table order, to their sub-crops (a name can recur in two
    blocks, so this goes by position)."""
    out, i = [], 0
    for crop, count in PEACH_BLOCKS:
        block = names[i:i + count] if count else names[i:]
        if i and block and block[0].casefold() >= names[i - 1].casefold():
            raise ValueError(f"the {crop} block should start where the alphabet restarts, not at {block[0]!r}")
        out += [crop] * len(block)
        i += len(block)
    return out


def parse(doc: str) -> tuple:
    out, worst, seq = [], 0.0, 0
    for page in pages(doc):
        for table, ls in fragments(page):
            names, rows = read_fragment(table, ls)
            if not rows:
                continue
            for name, group, off in assign(names, rows):
                worst, seq = max(worst, off), seq + 1
                name = re.sub(r"(\S)\(", r"\1 (", name)
                for _, (ch, cu, cp, gdh), method, loc, ref in group:
                    out.append({"_seq": seq, "crop": TABLES[table], "cultivar": name,
                                "chill_hours": ch, "chill_units": cu, "chill_portions": cp, "heat_gdh": gdh,
                                "method": {"E": "experimental", "S": "statistical"}[method],
                                "location": loc, "review_ref": ref})
    seqs = list(dict.fromkeys(r["_seq"] for r in out if r["crop"] == "peach"))
    name_of = {r["_seq"]: r["cultivar"] for r in out}
    crop_of = dict(zip(seqs, peach_blocks([name_of[s] for s in seqs])))
    for r in out:
        if r["crop"] == "peach":
            r["crop"] = crop_of[r["_seq"]]
    return out, worst


def references(doc: str) -> dict:
    """The review's numbered reference list, so each row can name its original study."""
    text = "\n".join(text_of(ws) for page in pages(doc) for _, ws in lines(page))
    tail = text[text.rindex("\nReferences"):]
    out, current = {}, None
    for line in tail.splitlines()[1:]:
        m = re.match(r"^(\d+)\. (.*)$", line)
        if m and (current is None or int(m.group(1)) == current + 1):
            current = int(m.group(1))
            out[current] = m.group(2).strip()
        elif current and line.strip() and not line.startswith(("Agronomy 2020", "©", "Licensee", "article distributed",
                                                                "(CC BY)", "by/4.0")):
            out[current] += " " + line.strip()
    return {k: re.sub(r"\s*\[(CrossRef|PubMed)\]", "", v).strip() for k, v in out.items()}


def check(rows: list) -> list:
    counts = {}
    for r in rows:
        counts.setdefault(r["crop"], set()).add(r["_seq"])
    return [f"{crop}: {len(counts.get(crop, ()))} cultivars, the review says {n}"
            for crop, n in CULTIVARS.items() if len(counts.get(crop, ())) != n]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bbox", help="pdftotext -bbox output of the review")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with open(args.bbox, encoding="utf-8") as h:
        doc = h.read()
    (rows, worst), refs = parse(doc), references(doc)
    for r in rows:
        nums = [int(n) for n in re.findall(r"\d+", r["review_ref"])]
        r["study"] = " | ".join(refs.get(n, "?") for n in nums)
    with open(args.out, "w", newline="", encoding="utf-8") as h:
        h.write("# SPDX-License-Identifier: CC-BY-4.0\n"
                "# From Fadón E, Herrera S, Guerrero BI, Guerra ME, Rodrigo J (2020) Chilling and heat requirements of "
                "temperate stone fruit trees (Prunus sp.). Agronomy 10(3):409, doi:10.3390/agronomy10030409, CC BY 4.0; "
                "tables re-keyed by modules/advise/chill_requirements.py, values as printed. CH = chill hours (0-7.2 C), "
                "CU = Utah chill units, CP = Dynamic-model chill portions, GDH = growing degree hours.\n")
        w = csv.DictWriter(h, fieldnames=[k for k in rows[0] if k != "_seq"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    problems = check(rows)
    print(f"{len(rows)} requirements for {len({r['_seq'] for r in rows})} cultivars; "
          f"worst name offset from its rows' midpoint {worst:.1f} pt")
    for p in problems:
        print("  MISMATCH", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
