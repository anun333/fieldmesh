#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plant names in other languages, from AGROVOC and Wikidata.

    python3 -I modules/advise/plant_names.py modules/advise/data/plant-list.csv \\
        --langs es,fr --cache DIR --out modules/advise/data/plant-names.csv

A report in Spanish that says "Maize (Zea mays)" has translated everything but the thing
the farmer plants. Two openly licensed sources carry names; neither carries all of them,
and neither should be trusted blindly, so each name says where it came from:

1. **AGROVOC** (FAO; CC BY 4.0 in FAO's languages — English, French, Spanish, Arabic,
   Russian, Chinese). A plant is a taxon concept whose labels are its scientific name in
   every language, linked by `produces` to what it is grown for — *Zea mays* produces
   *maize*, "Maíz". Taken when that product's English name is the plant's English common
   name on our list (singular or plural), or when it is the only product.
2. **Wikidata** (CC0). A taxon's preferred common name in the language, or its label there
   when that is not a scientific name, or the label of what it is the source of
   (P1672: *Malus domestica* → apple, "manzana").

A plant with neither keeps its English common name beside the scientific one, which is
honest; a guessed name is not. Run only with `-I` and a cache: the answers are data.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

AGROVOC = "https://agrovoc.fao.org/sparql"
WIKIDATA = "https://query.wikidata.org/sparql"
UA = "fieldmesh/0.1 (farm data stack; plant names for a crop advisor)"
FIELDS = ["scientific_name", "language", "name", "source", "concept"]


def _query(endpoint: str, q: str, cache: str | None, tag: str) -> list:
    path = os.path.join(cache, f"{tag}.json") if cache else None
    if path and os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    url = endpoint + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/sparql-results+json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                doc = json.load(r)
            break
        except urllib.error.HTTPError as exc:
            # The query services ask callers to slow down with 429 and say for how long;
            # waiting is the polite answer, and the cache means it is paid once.
            if exc.code != 429 or attempt == 5:
                raise
            wait = min(int(exc.headers.get("Retry-After") or 65), 300)
            print(f"  {tag}: asked to wait {wait} s", file=sys.stderr, flush=True)
            time.sleep(wait)
    rows = [{**{k: v["value"] for k, v in b.items()},
             **({"lang": b["value"]["xml:lang"]} if "xml:lang" in b.get("value", {}) else {})}
            for b in doc["results"]["bindings"]]
    if path:
        json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  {tag}: {len(rows)} rows", file=sys.stderr, flush=True)
    time.sleep(1)
    return rows


def agrovoc_products(names: list, langs: list, cache: str | None) -> list:
    out = []
    for i in range(0, len(names), 50):
        chunk = names[i:i + 50]
        vals = " ".join(json.dumps(n) + "@en" for n in chunk)
        optional = " ".join(
            f'OPTIONAL {{ ?prod skosxl:prefLabel/skosxl:literalForm ?p_{lang} '
            f'FILTER(LANG(?p_{lang})="{lang}") }}' for lang in langs)
        q = f"""PREFIX skosxl: <http://www.w3.org/2008/05/skos-xl#>
PREFIX agrontology: <http://aims.fao.org/aos/agrontology#>
SELECT ?name ?c ?prod ?p_en {' '.join('?p_' + l for l in langs)} WHERE {{
  VALUES ?name {{ {vals} }}
  ?c skosxl:prefLabel/skosxl:literalForm ?name ; agrontology:produces ?prod .
  ?prod skosxl:prefLabel/skosxl:literalForm ?p_en FILTER(LANG(?p_en)="en") {optional} }}"""
        out += _query(AGROVOC, q, cache, f"agrovoc-{'-'.join(langs)}-{i}")
    return out


def wikidata_names(names: list, langs: list, cache: str | None) -> list:
    out = []
    lang_list = ",".join(json.dumps(l) for l in langs)
    for i in range(0, len(names), 20):
        chunk = names[i:i + 20]
        vals = " ".join(json.dumps(n) for n in chunk)
        # Each branch filters its own language, so the service never builds every label
        # in every language first — the difference between seconds and a timeout.
        q = f"""SELECT ?name ?item ?kind ?value ?rank ?src_en WHERE {{
  VALUES ?name {{ {vals} }}
  ?item wdt:P225 ?name ; wdt:P31 wd:Q16521 .
  {{ ?item p:P1843 ?st . ?st ps:P1843 ?value ; wikibase:rank ?rank .
     FILTER(LANG(?value) IN ({lang_list})) BIND("common" AS ?kind) }}
  UNION {{ ?item rdfs:label ?value FILTER(LANG(?value) IN ({lang_list})) BIND("label" AS ?kind) }}
  UNION {{ ?item wdt:P1672 ?src . ?src rdfs:label ?value FILTER(LANG(?value) IN ({lang_list}))
           ?src rdfs:label ?src_en FILTER(LANG(?src_en) = "en") BIND("source_of" AS ?kind) }} }}"""
        out += _query(WIKIDATA, q, cache, f"wikidata2-{'-'.join(langs)}-{i}")
    return out


def _norm(text: str) -> str:
    t = re.sub(r"\(.*?\)", "", text.lower()).strip()
    return t[:-1] if t.endswith("s") else t


def _latin(name: str, scientific: str) -> bool:
    """A scientific name passing as a common one: the genus again, or any binomial."""
    first = name.split()[0].lower() if name.split() else ""
    return (first == scientific.split()[0].lower()
            or bool(re.fullmatch(r"[A-Z][a-z]+ [a-z]+( (var|subsp)\. [a-z]+)?", name)))


def choose(plants: list, agro: list, wiki: list, lang: str) -> dict:
    """{scientific_name: (name, source, concept)} for one language."""
    out = {}
    english = {p["scientific_name"]: p["common_name"] for p in plants}
    products = {}
    for r in agro:
        if r.get(f"p_{lang}"):
            products.setdefault(r["name"], {})[r["prod"]] = (r["p_en"], r[f"p_{lang}"])
    for sci, prods in products.items():
        mine = _norm(english.get(sci, ""))
        match = [(c, es) for c, (en, es) in prods.items() if _norm(en) == mine or _norm(en) in mine.split(" or ")]
        if not match and len(prods) == 1:
            match = [(c, es) for c, (en, es) in prods.items()]
        if len(match) == 1:
            out[sci] = (match[0][1], "AGROVOC (CC BY 4.0)", match[0][0])
    by = {}
    for r in wiki:
        if r.get("lang") == lang:
            by.setdefault(r["name"], []).append(r)
    for sci, rs in by.items():
        if sci in out:
            continue
        pref = {r["value"] for r in rs if r["kind"] == "common" and r.get("rank", "").endswith("PreferredRank")}
        labels = {r["value"] for r in rs if r["kind"] == "label" and not _latin(r["value"], sci)}
        # What a plant is the source of is often a by-product ("maicena" for maize), so it
        # is taken only when its English name is the plant's own on our list.
        mine = _norm(english.get(sci, ""))
        sources = {r["value"] for r in rs if r["kind"] == "source_of" and not _latin(r["value"], sci)
                   and _norm(r.get("src_en", "")) == mine}
        for found in (pref, labels, sources):
            if len(found) == 1:
                item = rs[0]["item"]
                out[sci] = (next(iter(found)), "Wikidata (CC0)", item)
                break
    return {k: (_tidy(v[0]), v[1], v[2]) for k, v in out.items()}


#: What a product label carries that a plant's name does not: "Semilla de ricino" names
#: castor seed, "Litchi (fruta)" the fruit. Dropped so the plant is named, not its product.
_PRODUCT = re.compile(r"^(?:semillas? de |graines? de )", re.I)


def _tidy(name: str) -> str:
    name = re.sub(r"\s*\([^)]*\)$", "", _PRODUCT.sub("", name.strip()))
    return name[:1].upper() + name[1:]


def read_plants(path: str) -> list:
    with open(path, encoding="utf-8") as h:
        return list(csv.DictReader(line for line in h if not line.startswith("#")))


def load(path: str) -> dict:
    """{language: {scientific name: name}} from a written names file."""
    out: dict = {}
    for r in read_plants(path):
        out.setdefault(r["language"], {})[r["scientific_name"]] = r["name"]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plants")
    ap.add_argument("--langs", default="es,fr")
    ap.add_argument("--cache")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    langs = args.langs.split(",")
    if args.cache:
        os.makedirs(args.cache, exist_ok=True)
    plants = read_plants(args.plants)
    names = sorted({p["scientific_name"] for p in plants})
    agro = agrovoc_products(names, langs, args.cache)
    wiki = wikidata_names(names, langs, args.cache)
    rows = []
    for lang in langs:
        chosen = choose(plants, agro, wiki, lang)
        for sci in names:
            if sci in chosen:
                name, source, concept = chosen[sci]
                rows.append({"scientific_name": sci, "language": lang, "name": name,
                             "source": source, "concept": concept})
        print(f"{lang}: {len(chosen)} of {len(names)} plants named "
              f"({sum(1 for v in chosen.values() if v[1].startswith('AGROVOC'))} AGROVOC, "
              f"{sum(1 for v in chosen.values() if v[1].startswith('Wikidata'))} Wikidata)")
    with open(args.out, "w", newline="", encoding="utf-8") as h:
        h.write("# SPDX-License-Identifier: CC-BY-4.0\n# Plant names by language. AGROVOC (FAO, CC BY 4.0, "
                "agrovoc.fao.org) and Wikidata (CC0), chosen by modules/advise/plant_names.py; each "
                "row names its source and concept. Retrieved 2026-10-09.\n")
        w = csv.DictWriter(h, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
