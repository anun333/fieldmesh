#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""What mixes with what: interaction records for the plant and animal lists.

    python3 tools/interactions.py docs/notes/plant-list.csv \\
        docs/notes/plant-characteristics-usda.csv --globi docs/notes/plant-bees-globi.csv \\
        --out docs/notes/interactions.csv

One record per interaction: **this** affects **that**, *for better or worse*, *by what
mechanism*, *how strongly*, *according to which source*
(docs/notes/animals-bees-and-inputs.md). Three sources, kept apart in the `source`
column so their different standing is visible:

* **USDA PLANTS** characteristics that already encode a link — bloat, toxicity, nitrogen
  fixation, allelopathy, palatability to grazers and browsers;
* **GloBI** records of bees visiting or pollinating each plant;
* **curated** well-known combinations, each marked *to cite* until it has a source.
"""
from __future__ import annotations

import argparse
import csv

#: Well-known combinations from docs/notes/animals-bees-and-inputs.md. Each is to be
#: sourced before anything relies on it.
CURATED = [
    ("Maize, common bean and squash", "each other", "benefit", "three sisters: the bean climbs the maize and fixes nitrogen; the squash shades out weeds", ""),
    ("legume cover crop", "a following cereal", "benefit", "nitrogen left in the soil", ""),
    ("cattle", "sheep and goats", "benefit", "grazed together they prefer different plants and mostly do not share gut parasites, diluting each other's worm burden", ""),
    ("poultry", "cattle pasture", "benefit", "following cattle, they scratch apart dung pats and eat fly larvae", ""),
    ("ducks", "rice", "benefit", "pest and weed control; manure", ""),
    ("fish (common carp)", "rice", "benefit", "pest control; manure", ""),
    ("pigs", "woodland", "benefit", "finishing on acorns and nuts", ""),
    ("donkeys, llamas, guardian dogs", "sheep and goats", "benefit", "protection from canid predators", ""),
    ("goats", "kudzu, multiflora rose and other invasive brush", "benefit", "browse it down", ""),
    ("black soldier fly", "poultry and fish", "benefit", "larvae raised on manure become feed; frass becomes fertilizer", ""),
    ("silkworm", "mulberry", "benefit", "the only food silkworms eat", ""),
    ("windbreaks and hedgerows", "livestock and bees", "benefit", "shelter from wind", ""),
    ("riparian buffers", "streams", "benefit", "catch manure and fertilizer runoff", ""),
    ("insecticide or mowing during bloom", "bees", "harm", "kills foragers", ""),
    ("deep tillage", "squash bees", "harm", "destroys nests in the soil beneath cucurbits", ""),
    ("chickens", "turkeys", "harm", "chickens carry blackhead (Histomonas), which kills turkeys", ""),
    ("copper (feeds, minerals, orchard sprays)", "sheep", "harm", "sheep are poisoned at levels other livestock tolerate", ""),
    ("goats", "young trees", "harm", "they strip bark", ""),
    ("Black walnut", "tomatoes and other Solanaceae; horses (shavings)", "harm", "juglone", ""),
    ("wilted cherry and other Prunus leaves", "ruminants", "harm", "cyanide", ""),
    ("acorns in quantity", "cattle and horses", "harm", "tannin poisoning (pigs tolerate them)", ""),
    ("waterfowl", "chickens", "harm", "a reservoir for avian influenza", ""),
    ("Bombus terrestris", "places outside its native range", "harm", "invasive where introduced", ""),
    ("poultry litter, applied repeatedly", "water", "harm", "phosphorus builds up and runs off", ""),
    ("fresh manure", "food crops", "harm", "pathogens; the organic rule's 90/120-day interval exists for this", ""),
]

PLANTS_LINKS = [
    ("Bloat", ("Medium", "High"), "cattle and sheep grazing it", "harm", "bloat"),
    ("Toxicity", ("Slight", "Moderate", "Severe"), "livestock", "harm", "toxic"),
    ("Nitrogen Fixation", ("Medium", "High"), "the crop that follows", "benefit", "nitrogen fixation"),
    ("Known Allelopath", ("Yes",), "neighbouring plants", "harm", "allelopathy (PLANTS marks it; often weakly evidenced)"),
    ("Palatable Graze Animal", ("High",), "grazing livestock", "benefit", "palatable forage"),
    ("Palatable Browse Animal", ("High",), "browsing livestock (goats)", "benefit", "palatable browse"),
]


def read_csv(path: str) -> list:
    with open(path, encoding="utf-8") as h:
        return list(csv.DictReader(line for line in h if not line.startswith("#")))


def records(plants: list, chars: list, globi: list | None) -> list:
    common = {p["scientific_name"]: p["common_name"] for p in plants}
    out = []
    for c in chars:
        name = c["scientific_name"]
        label = f"{common.get(name, name)} ({name})"
        for field, values, obj, effect, mechanism in PLANTS_LINKS:
            if c.get(field) in values:
                out.append({"subject": label, "object": obj, "effect": effect,
                            "mechanism": mechanism, "level": c[field],
                            "source": "USDA PLANTS (CC0)"})
    for g in globi or []:
        if g.get("bee_records") and int(g["bee_records"]) > 0:
            name = g["scientific_name"]
            bees = g.get("managed_bees_recorded") or g.get("top_bees", "")
            out.append({"subject": f"{common.get(name, name)} ({name})",
                        "object": f"bees: {bees}", "effect": "benefit",
                        "mechanism": "flowers visited or pollinated (recorded)",
                        "level": f"{g['bee_records']} records, {g.get('bee_taxa')} bee taxa",
                        "source": "GloBI (CC BY 4.0) and the studies it cites"})
    for subject, obj, effect, mechanism, level in CURATED:
        out.append({"subject": subject, "object": obj, "effect": effect,
                    "mechanism": mechanism, "level": level, "source": "curated — to cite"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plant_list")
    ap.add_argument("characteristics")
    ap.add_argument("--globi")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    rows = records(read_csv(args.plant_list), read_csv(args.characteristics),
                   read_csv(args.globi) if args.globi else None)
    with open(args.out, "w", newline="", encoding="utf-8") as h:
        h.write("# SPDX-License-Identifier: CC-BY-4.0\n# Interaction records. Sources per row: "
                "USDA PLANTS (CC0), GloBI (CC BY 4.0, with the studies listed in "
                "plant-bees-globi-studies.txt), or curated (to cite).\n")
        w = csv.DictWriter(h, fieldnames=["subject", "object", "effect", "mechanism", "level", "source"])
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        by[r["source"].split(" ")[0]] = by.get(r["source"].split(" ")[0], 0) + 1
    print(f"{len(rows)} interaction records: " + ", ".join(f"{k} {v}" for k, v in by.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
