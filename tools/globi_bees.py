#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Which bees are recorded visiting or pollinating each plant on the list, from GloBI.

    python3 tools/globi_bees.py docs/notes/plant-list.csv --cache DIR \\
        --out docs/notes/plant-bees-globi.csv --citations docs/notes/plant-bees-globi-studies.txt

GloBI (Global Biotic Interactions) indexes species-interaction records from hundreds of
studies and collections; its data is CC BY 4.0, and each record carries the study it came
from, which must be credited in turn — so the studies behind every count are written out
too. Only records of a bee (Apidae, Megachilidae, Halictidae, Andrenidae, Colletidae,
Melittidae, Stenotritidae) *visiting the flowers of* or *pollinating* the plant are kept.

**Records, not abundance.** A count says how often a pairing was written down, which
follows where people looked — honey bees on crops in Europe and North America are
recorded far more than stingless bees on tropical fruit. Absence is not evidence of
absence. Each query takes at most `LIMIT` records; a plant that hits it says so.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

API = ("https://api.globalbioticinteractions.org/interaction?targetTaxon={taxon}"
       "&interactionType=interactsWith&fields=source_taxon_name,source_taxon_path,"
       "interaction_type,target_taxon_name,study_title&limit={limit}")
LIMIT = 4000
BEE_FAMILIES = ("Apidae", "Megachilidae", "Halictidae", "Andrenidae", "Colletidae",
                "Melittidae", "Stenotritidae")
KEPT = ("visitsFlowersOf", "pollinates")
#: The managed bees on the animal list, so a plant's row says which of them are recorded.
MANAGED = ("Apis mellifera", "Apis cerana", "Bombus terrestris", "Bombus impatiens",
           "Osmia lignaria", "Osmia cornifrons", "Osmia cornuta", "Osmia bicornis",
           "Megachile rotundata", "Nomia melanderi", "Xenoglossa pruinosa",
           "Peponapis pruinosa", "Habropoda laboriosa", "Melipona beecheii",
           "Tetragonisca angustula", "Tetragonula carbonaria", "Heterotrigona itama")
PAUSE_S = 0.5
USER_AGENT = "librefarm-tools/0.1 (globi_bees.py; open-source farm data research)"


def query_name(scientific: str) -> str:
    """GloBI matches names, so hybrids lose the sign and cultivar groups are dropped."""
    name = scientific.replace("×", " ").split("(")[0]
    if " subg. " in name:                       # a subgenus: query the genus
        return name.split()[0]
    return " ".join(name.split()[:2])


def is_bee(path: str | None) -> bool:
    return bool(path) and any(f in path for f in BEE_FAMILIES)


def fetch(taxon: str, cache: str) -> dict:
    url = API.format(taxon=urllib.parse.quote(taxon), limit=LIMIT)
    os.makedirs(cache, exist_ok=True)
    file = os.path.join(cache, hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")
    if os.path.exists(file):
        with open(file, encoding="utf-8") as h:
            return json.load(h)
    # GloBI refuses Python's default user agent; say who is asking.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        doc = json.loads(response.read().decode("utf-8"))
    with open(file, "w", encoding="utf-8") as h:
        json.dump(doc, h)
    time.sleep(PAUSE_S)
    return doc


def summarise(doc: dict) -> tuple[dict, set]:
    cols = doc.get("columns", [])
    rows = [dict(zip(cols, r)) for r in doc.get("data", [])]
    bees = [r for r in rows if r.get("interaction_type") in KEPT
            and is_bee(r.get("source_taxon_path"))]
    taxa = collections.Counter(r["source_taxon_name"] for r in bees)
    # GloBI names the field `study_title`; it holds the study's full citation.
    studies = {r.get("study_title") or r.get("study_citation") for r in bees}
    studies.discard(None)
    return {"bee_records": len(bees), "bee_taxa": len(taxa),
            "top_bees": "; ".join(f"{n} ({c})" for n, c in taxa.most_common(8)),
            "managed_bees_recorded": "; ".join(m for m in MANAGED if m in taxa),
            "studies": len(studies),
            "capped": "yes" if len(rows) >= LIMIT else ""}, studies


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plant_list")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--citations", required=True)
    args = ap.parse_args(argv)
    with open(args.plant_list, encoding="utf-8") as h:
        plants = list(csv.DictReader(line for line in h if not line.startswith("#")))
    out, all_studies = [], set()
    for p in plants:
        taxon = query_name(p["scientific_name"])
        try:
            summary, studies = summarise(fetch(taxon, args.cache))
        except Exception as exc:                       # reported, not hidden
            summary, studies = {"error": type(exc).__name__}, set()
        all_studies |= studies
        out.append({"scientific_name": p["scientific_name"], "queried_as": taxon, **summary})
    fields = ["scientific_name", "queried_as", "bee_records", "bee_taxa", "managed_bees_recorded",
              "top_bees", "studies", "capped", "error"]
    with open(args.out, "w", newline="", encoding="utf-8") as h:
        h.write("# SPDX-License-Identifier: CC-BY-4.0\n# Derived from GloBI (Global Biotic "
                "Interactions, globalbioticinteractions.org), CC BY 4.0, and the studies "
                "listed in the accompanying citations file.\n")
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    with open(args.citations, "w", encoding="utf-8") as h:
        h.write("SPDX-License-Identifier: CC-BY-4.0\nStudies behind the bee records in "
                "plant-bees-globi.csv, as cited by GloBI.\n\n")
        h.write("\n".join(sorted(all_studies)) + "\n")
    with_bees = sum(1 for r in out if r.get("bee_records"))
    print(f"{len(out)} plants; {with_bees} with bee records; {len(all_studies)} studies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
