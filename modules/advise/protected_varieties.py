#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Is a variety protected? A check before propagating it for sale.

    python3 modules/advise/protected_varieties.py --cache DIR "Kizuri:Malus domestica" "Green Ice"

A nursery that raises a protected variety from seed or tubers and sells it breaks the
Plant Variety Protection Act. The USDA's Plant Variety Protection Office publishes every
application it has received, monthly, as a spreadsheet (the Application Status Report,
ams.usda.gov; listed on data.gov under CC BY 4.0): variety, species, status, the date a
certificate issued and the years it runs. Read at run time and cached; the applicant
column is not read.

What a match means:

* **protected** — a certificate issued and still within its term;
* **provisionally protected** — an application is pending; the Act protects a variety
  from the date of application, so treat it as protected;
* **not under PVP** — a certificate expired, or the application was abandoned, withdrawn,
  denied or found ineligible.

**What this does not check: patents.** PVP covers varieties grown from seed and tubers.
Fruit trees, berries, grapes and most ornamentals propagated from cuttings or grafts are
usually protected by a plant patent instead, and some seed varieties by a utility patent;
neither is in this report. So "not found" is not "free to propagate". And PVP lets a farmer
save seed of a protected variety to replant on their own farm (7 U.S.C. 2543), but not
sell it for planting.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import urllib.request
import zipfile

URL = "https://www.ams.usda.gov/sites/default/files/media/USPVPApplicationStatusReport.xlsx"
COLUMNS = {"B": "application", "C": "variety", "D": "experimental", "E": "scientific",
           "F": "common", "H": "application_date", "I": "certified_seed", "J": "status",
           "K": "status_date", "L": "issued", "M": "years"}      # G, the applicant, is skipped
NOT_UNDER_PVP = ("Certificate Expired", "Application Abondoned", "Application Withdrawn",
                 "Certificate Abondoned", "Application Ineligible", "Application Denied")


def fetch(cache: str) -> str:
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, "USPVPApplicationStatusReport.xlsx")
    if not os.path.exists(path):
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 fieldmesh/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as h:
            h.write(r.read())
    return path


def read(path: str) -> list[dict]:
    """The report's rows, from its one worksheet of inline strings, without a library."""
    with zipfile.ZipFile(path) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    rows = []
    for r in re.findall(r"<row[^>]*>(.*?)</row>", sheet, flags=re.S):
        cells = {}
        for m in re.finditer(r'<c [^>]*?r="([A-Z]+)\d+"[^>]*>(.*?)</c>', r, flags=re.S):
            v = re.search(r"<t[^>]*>(.*?)</t>", m.group(2), flags=re.S) or \
                re.search(r"<v>(.*?)</v>", m.group(2), flags=re.S)
            if m.group(1) in COLUMNS:
                cells[COLUMNS[m.group(1)]] = _unescape(v.group(1)).strip() if v else ""
        if cells.get("application") and cells["application"] != "Application #":
            rows.append(cells)
    return rows


def _unescape(text: str) -> str:
    return (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&apos;", "'"))


def _name(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _species(text: str) -> str:
    return " ".join((text or "").lower().split()[:2])


def standing(row: dict, today: _dt.date) -> str:
    status = row.get("status", "")
    if status == "Application Pending":
        return "provisionally protected"
    if status == "Certificate Issued":
        try:
            issued = _dt.datetime.strptime(row["issued"], "%m/%d/%Y").date()
            years = int(row["years"])
        except (KeyError, ValueError):
            return "protected"
        ends = issued.replace(year=issued.year + years)
        return "protected" if today < ends else "not under PVP"
    if status in NOT_UNDER_PVP:
        return "not under PVP"
    return "unknown"


def check(rows: list, variety: str, scientific: str | None = None,
          today: _dt.date | None = None) -> list[dict]:
    """Every application for a variety of this name (and species, if given), with where
    it stands today. Matched on the name without spacing or punctuation, and on the
    experimental name too."""
    today = today or _dt.date.today()
    want, sp = _name(variety), _species(scientific) if scientific else None
    out = []
    for r in rows:
        if want not in (_name(r.get("variety")), _name(r.get("experimental"))):
            continue
        if sp and _species(r.get("scientific")) != sp:
            continue
        out.append({**r, "standing": standing(r, today)})
    return out


def verdict(matches: list) -> str:
    stands = {m["standing"] for m in matches}
    for s in ("protected", "provisionally protected"):
        if s in stands:
            return s
    return "not under PVP" if matches else "not found"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("varieties", nargs="+", help="variety, or variety:scientific name")
    ap.add_argument("--cache", required=True)
    args = ap.parse_args(argv)
    rows = read(fetch(args.cache))
    for item in args.varieties:
        variety, _, scientific = item.partition(":")
        matches = check(rows, variety, scientific or None)
        v = verdict(matches)
        detail = "; ".join(f"PV {m['application']} {m['variety']} ({m['scientific']}): {m['status']}"
                           + (f", issued {m['issued']} for {m['years']} years" if m.get("issued") else "")
                           for m in matches)
        print(f"{variety}: {v}" + (f" — {detail}" if detail else ""))
    print("\nPlant and utility patents are not checked: fruit trees, berries and plants "
          "propagated from cuttings are usually patented, not certificated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
