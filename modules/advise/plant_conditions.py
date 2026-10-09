#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pull USDA PLANTS characteristics for every plant on the list.

    python3 modules/advise/plant_conditions.py modules/advise/data/plant-list.csv \\
        --cache /path/to/cache --out modules/advise/data/plant-characteristics-usda.csv

For each scientific name: search PLANTS, accept only an exact name match, follow a
synonym to the accepted name, and read the characteristics — soil textures, pH, rainfall,
drought, minimum temperature, frost-free days, salinity, shade, roots, bloom period,
toxicity, bloat, palatability, nitrogen fixation, propagation, products — and the US
noxious and invasive status. USDA PLANTS is CC0; the output says so, and when it was
retrieved. Responses are cached, so a re-run costs nothing and the network is touched
once per plant.

**PLANTS covers the United States and its territories.** A crop grown only elsewhere may
be absent, or present without characteristics; the output says which, per plant, rather
than leaving a silent blank. The values are generalised: maize is listed as not adapted
to fine-textured soils, which is not true of a clay loam — a starting layer, to be
cross-checked (modules/advise/notes/plant-conditions.md).
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

API = "https://plantsservices.sc.egov.usda.gov/api/"
PAUSE_S = 0.25          # be a polite client of a public service


def normalise(name: str) -> str:
    """A scientific name reduced to what comparing needs: no hybrid sign, one form of
    each rank word, lower case, single spaces."""
    name = html.unescape(re.sub(r"<[^>]+>", "", name))
    name = name.replace("×", " ").replace(" x ", " ")
    name = re.sub(r"\bssp\.", "subsp.", name)
    return " ".join(name.lower().split())


def name_of(search_text: str) -> str:
    """The name in a PLANTS search result, without its authors: the italic parts, with
    the rank words between them. `<i>Zea mays</i> L. ssp. <i>everta</i> (Sturtev.) Zhuk.`
    → `zea mays subsp. everta`. A rank word counts only when an epithet follows it, so an
    author's "L. f." at the end is not read as a form."""
    search_text = re.sub(r"\[.*?\]", "", search_text)       # a hybrid's parentage
    parts = re.split(r"(<i>.*?</i>)", search_text)
    out = []
    for i, part in enumerate(parts):
        if part.startswith("<i>"):
            out.append(part[3:-4])
        elif any(p.startswith("<i>") for p in parts[i + 1:]):
            m = re.search(r"\b(ssp|subsp|var|f)\.$", part.strip())
            if m:
                out.append(m.group(1) + ".")
    return normalise(" ".join(out))


#: Current names PLANTS files under an older one. Explicit, so every substitution is
#: visible and reviewable rather than guessed.
PLANTS_NAMES = {
    "Salvia rosmarinus": "Rosmarinus officinalis",
    "Selenicereus undatus": "Hylocereus undatus",
    "Acca sellowiana": "Feijoa sellowiana",
    "Actinidia deliciosa": "Actinidia chinensis",
}


def candidates(ours: str) -> list[str]:
    """Names to try, most specific first. A cultivar group in brackets and a subgenus
    are not in PLANTS; a variety may be, and if not, its species is; and a name PLANTS
    knows only by an older one is tried under that."""
    base = re.sub(r"\(.*?\)", "", ours).strip()
    base = re.sub(r"\bsubg\. \w+", "", base).strip()
    out = [normalise(base)]
    words = normalise(base).split()
    if len(words) > 2:
        out.append(" ".join(words[:2]))
    if ours in PLANTS_NAMES:
        out.append(normalise(PLANTS_NAMES[ours]))
    return list(dict.fromkeys(out))


class Client:
    def __init__(self, cache: str):
        self.cache = cache
        os.makedirs(cache, exist_ok=True)

    def get(self, path: str):
        key = hashlib.sha256(path.encode()).hexdigest()[:24]
        file = os.path.join(self.cache, key + ".json")
        if os.path.exists(file):
            with open(file, encoding="utf-8") as h:
                return json.load(h)
        with urllib.request.urlopen(API + path, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        with open(file, "w", encoding="utf-8") as h:
            json.dump(data, h)
        time.sleep(PAUSE_S)
        return data


def find(client: Client, ours: str):
    """-> (plant record from search, the name that matched) or (None, None).

    The full name first; then, because PLANTS writes hybrids as `Mentha ×piperita` and
    its search does not find them from `Mentha piperita`, the genus, matched by the same
    normalised comparison."""
    for want in candidates(ours):
        queries = [want.replace("subsp.", "ssp."), want.split()[0]]
        for q in queries:
            for hit in client.get(f"PlantSearch?searchText={urllib.parse.quote(q)}") or []:
                if name_of(hit.get("Text", "")) == want:
                    return hit["Plant"], want
    return None, None


STATES = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
          "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
          "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
          "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
          "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
          "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
          "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
          "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
          "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
          "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
          "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
          "Wyoming": "WY", "Puerto Rico": "PR", "Virgin Islands": "VI", "Guam": "GU"}


def statuses(client: "Client", profile: dict) -> tuple[str, str]:
    """US noxious and invasive listings, by state: (readable text, state codes). The
    profile only says whether there are any; the lists come from their own endpoints."""
    text, codes = [], set()
    for has, path, kind in (("HasInvasiveStatuses", "PlantInvasiveStatus", "invasive"),
                            ("HasNoxiousStatuses", "PlantNoxiousStatus", "noxious")):
        if not profile.get(has):
            continue
        for s in client.get(f"{path}/{profile['Id']}") or []:
            place = s.get("LocalityName") or ""
            listing = ", ".join(s.get("InvasiveStatuses") or s.get("NoxiousStatuses") or [kind])
            text.append(f"{kind}: {place} ({listing})")
            if place in STATES:
                codes.add(STATES[place])
            elif place:
                codes.add(place)
    return "; ".join(sorted(set(text))), ";".join(sorted(codes))


def pull(client: Client, ours: str) -> dict:
    hit, matched = find(client, ours)
    row = {"scientific_name": ours}
    if hit is None:
        row["match"] = "not in PLANTS"
        return row
    profile = client.get(f"PlantProfile?symbol={hit['Symbol']}")
    note = "exact" if matched == candidates(ours)[0] else f"species ({matched})"
    if profile.get("AcceptedSymbol") and profile.get("AcceptedSymbol") != profile.get("Symbol"):
        profile = client.get(f"PlantProfile?symbol={profile['AcceptedSymbol']}")
        note += ", via synonym"
    listed, where = statuses(client, profile)
    row.update({"plants_symbol": profile.get("Symbol"),
                "plants_name": normalise(profile.get("ScientificName") or ""),
                "us_noxious_invasive": listed, "us_listed_states": where})
    if not profile.get("HasCharacteristics"):
        row["match"] = note + "; no characteristics"
        return row
    row["match"] = note
    for c in client.get(f"PlantCharacteristics/{profile['Id']}") or []:
        name, value = c.get("PlantCharacteristicName"), c.get("PlantCharacteristicValue")
        if name:
            row[name] = value
    return row


FIXED = ["scientific_name", "match", "plants_symbol", "plants_name", "us_noxious_invasive",
         "us_listed_states"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plant_list")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with open(args.plant_list, encoding="utf-8") as h:
        plants = list(csv.DictReader(line for line in h if not line.startswith("#")))
    client = Client(args.cache)
    rows = []
    for i, p in enumerate(plants, 1):
        try:
            rows.append(pull(client, p["scientific_name"]))
        except Exception as exc:          # a network error is reported, not hidden
            rows.append({"scientific_name": p["scientific_name"],
                         "match": f"error: {type(exc).__name__}"})
        if i % 50 == 0:
            print(f"  {i}/{len(plants)}")
    names = sorted({k for r in rows for k in r} - set(FIXED))
    with open(args.out, "w", newline="", encoding="utf-8") as h:
        h.write(f"# SPDX-License-Identifier: CC0-1.0\n# USDA NRCS PLANTS Database "
                f"characteristics, retrieved {_dt.date.today().isoformat()} via "
                f"{API}. Public domain (CC0).\n")
        w = csv.DictWriter(h, fieldnames=FIXED + names)
        w.writeheader()
        w.writerows(rows)
    found = sum(1 for r in rows if r.get("plants_symbol"))
    chars = sum(1 for r in rows if r.get("match") and "characteristics" not in r["match"]
                and r.get("plants_symbol"))
    print(f"{len(rows)} plants: {found} found in PLANTS, {chars} with characteristics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
