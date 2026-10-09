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
* **curated** well-known combinations, each with its source — a paper, an extension
  guide, a regulation — and worded to what that source supports.
"""
from __future__ import annotations

import argparse
import csv

#: Well-known combinations from docs/notes/animals-bees-and-inputs.md, each with the source
#: that supports it as worded here. Checking them changed five: the poultry-after-cattle
#: claim did not hold up in a controlled trial (`unproven`), ducks in rice cut weeds but
#: let planthoppers rise (`mixed`), squash bees *prefer* tilled soil, the guide gives no
#: support for "pigs tolerate acorns" (the Iberian pig row is the evidence pigs eat them),
#: and kudzu and mowing were dropped where no source carried them.
#: (subject, object, effect, mechanism, level, source)
CURATED = [
    ("Maize, common bean and squash", "each other", "benefit",
     "the three sisters: interplanted, more food energy and protein per hectare than the same crops grown apart "
     "(12.25 million kcal and 349 kg protein/ha in New York trials)", "",
     "Mt.Pleasant J (2016) Ethnobiology Letters 7(1):87–98, doi:10.14237/ebl.7.1.2016.721; "
     "Mt.Pleasant J, Burt RF (2010) J. Ethnobiology 30(1):52–79, doi:10.2993/0278-0771-30.1.52"),
    ("legume cover crop", "a following cereal", "benefit",
     "nitrogen left in the soil; how much depends on the legume, how well it grew and when it was killed", "",
     "Clark A, ed. (2007) Managing Cover Crops Profitably, 3rd ed. SARE Handbook 9, "
     "https://www.sare.org/wp-content/uploads/Managing-Cover-Crops-Profitably.pdf"),
    ("cattle", "sheep", "benefit",
     "most gut worms are specific to one host, so grazing together dilutes the larvae: lambs mixed with cattle shed "
     "about half the worm eggs and gained about 40 g a day more", "",
     "Joly F et al. (2022) Front. Anim. Sci. 3:997815, doi:10.3389/fanim.2022.997815"),
    ("poultry", "cattle pasture", "unproven",
     "said to scratch apart dung pats and eat fly larvae; in a controlled trial broilers were never seen foraging in "
     "pats and face-fly larvae survived as well with them as without (laying hens not tested)", "",
     "Phillips HN, Moon RD, Sorge US, Heins BJ (2020) Animals 10(12):2429, doi:10.3390/ani10122429"),
    ("ducks", "rice", "mixed",
     "weeds controlled and income up with organic certification, but planthoppers and leafhoppers rose: the ducks "
     "also cut the spiders and dragonflies that eat them", "",
     "Qian P et al. (2022) Biocontrol Sci. Technol. 32(6):715–730, doi:10.1080/09583157.2022.2044016"),
    ("fish (common carp)", "rice", "benefit",
     "fish eat rice pests and the rice moderates the water for fish; unused fertilizer feeds plankton the fish eat and "
     "unused feed fertilizes the rice — kept 1,200 years in south China", "",
     "Xie J et al. (2011) PNAS 108(50):E1381–E1387, doi:10.1073/pnas.1111043108"),
    ("pigs", "oak woodland (dehesa)", "benefit",
     "finished on acorns and grass: Spain's 'de bellota' Iberian pork is defined by it in law, with the number of pigs "
     "per hectare capped by the tree cover so the woodland is not overgrazed", "",
     "Real Decreto 4/2014, de 10 de enero, norma de calidad del ibérico (BOE, 11 January 2014)"),
    ("guardian dogs, llamas, donkeys", "sheep and goats", "benefit",
     "protection from predators; dogs are the most widely used, and each guardian has to be chosen and bonded to the flock", "",
     "Coffey L (2020) Livestock Guardian Animals: Protecting the Flock or Herd. ATTRA/NCAT IP599"),
    ("goats", "multiflora rose and other invasive brush", "benefit",
     "goats alone killed all multiflora rose canes in 2.5 years, goats with cattle 92%; cattle alone gave only modest control", "",
     "Luginbuhl J-M, Harvey TE, Green JT, Poore MH, Mueller JP (1999) Agroforestry Systems 44:241–252, "
     "doi:10.1023/A:1006250728166"),
    ("black soldier fly", "poultry and fish", "benefit",
     "larvae grown on manure or food waste become feed (about 42% protein, 29% fat); what they may be grown on "
     "for feed is regulated, differently by country", "",
     "Wang Y-S, Shelomi M (2017) Foods 6(10):91, doi:10.3390/foods6100091"),
    ("mulberry", "silkworm", "benefit",
     "the silkworm's food: sericulture begins with growing mulberry leaf", "",
     "FAO (1988) Manuals on Sericulture 1: Mulberry cultivation. FAO Agricultural Services Bulletin 73/1"),
    ("windbreaks", "livestock", "benefit",
     "slowing cold wind cuts cold stress, the feed needed to stay warm and deaths in storms; designed right, summer "
     "breezes still get through", "",
     "USDA National Agroforestry Center, Working Trees: Windbreaks Protect Livestock, "
     "https://fs.usda.gov/nac/assets/documents/workingtrees/infosheets/WTInfoSheet-WindbreaksProtectLivestock.pdf"),
    ("riparian forest buffers", "streams", "benefit",
     "retain much of the nitrate in shallow groundwater and the sediment in runoff where soils are thin; phosphorus "
     "retention is generally lower", "",
     "Lowrance R et al. (1997) Environmental Management 21(5):687–712, doi:10.1007/s002679900060"),
    ("insecticide sprayed on bloom", "bees", "harm",
     "bloom is when bees are most exposed; mow flowering weeds before spraying, and if bloom must be treated choose "
     "products not labelled toxic to bees and spray in the evening", "",
     "Hooven L, Sagili R, Johansen E (2013) How to Reduce Bee Poisoning from Pesticides. Pacific Northwest Extension PNW 591"),
    ("deep tillage after squash", "squash bees", "harm",
     "they nest in the soil under the crop: tilling 41 cm deep cut emergence (11 against about 8 bees a cage) and "
     "delayed it — yet they prefer to nest in tilled soil, so the harm is to nests already dug, not to tillage as such", "",
     "Ullmann KS, Meisner MH, Williams NM (2016) Agric. Ecosyst. Environ. 232:240–246, doi:10.1016/j.agee.2016.08.002; "
     "Skidmore AR et al. (2019) Environ. Entomol. 48(4):961–967, doi:10.1093/ee/nvz052"),
    ("chickens", "turkeys", "harm",
     "blackhead (Histomonas), carried in chickens' caecal worms; it kills up to nearly all of a turkey flock, often "
     "unnoticed in chickens", "",
     "McDougald LR (2005) Avian Diseases 49(4):462–476, doi:10.1637/7420-081005R.1"),
    ("copper (cattle minerals and feeds)", "sheep", "harm",
     "sheep are the most susceptible livestock: copper builds up in the liver until a sudden crisis; minerals made "
     "for cattle are the usual cause, and molybdenum in the diet matters", "",
     "Merck Veterinary Manual, Copper Poisoning in Animals, "
     "https://www.merckvetmanual.com/toxicology/copper-poisoning/copper-poisoning-in-animals"),
    ("goats", "young trees", "harm",
     "they stripped bark from 10–11-year-old longleaf pines in cool-season grazing; 17–18-year-old loblolly were not touched", "",
     "Karki U et al. (2019) Agroforestry Systems 93(5):1647–1657, doi:10.1007/s10457-018-0271-1"),
    ("Black walnut", "tomatoes; horses (shavings)", "harm",
     "juglone: tomatoes whose roots reach the walnut's wilt; walnut chips or sawdust as bedding give horses acute laminitis", "",
     "Ontario Ministry of Agriculture, Food and Agribusiness, Walnut toxicity, https://www.ontario.ca/page/walnut-toxicity"),
    ("wilted cherry and other Prunus leaves", "ruminants", "harm",
     "wilting turns the leaves' glycosides to cyanide; 1.2–4.8 lb of wilted black cherry leaves can kill a 1,200 lb cow", "",
     "Miller D, Duppstadt L (2023) Cyanide poisoning of livestock from cherry tree leaves. Penn State Extension, "
     "citing Burrows & Tyrl, Toxic Plants of North America"),
    ("acorns and oak in quantity", "cattle, sheep and horses", "harm",
     "tannin poisoning; goats (and mule deer) are relatively resistant", "",
     "Merck Veterinary Manual, Overview of Quercus Poisoning, "
     "https://www.merckvetmanual.com/toxicology/quercus-poisoning/overview-of-quercus-poisoning"),
    ("wild waterfowl", "chickens and turkeys", "harm",
     "wild aquatic birds are the natural reservoir of influenza A and carry it without illness", "",
     "Webster RG, Bean WJ, Gorman OT, Chambers TM, Kawaoka Y (1992) Microbiol. Rev. 56(1):152–179, "
     "doi:10.1128/mr.56.1.152-179.1992"),
    ("Bombus terrestris", "places outside its native range", "harm",
     "introduced to Chile, it spread through Patagonia within years and replaced the native giant bumble bee "
     "B. dahlbomii, bringing the parasite Apicystis bombi with it", "",
     "Morales CL, Arbetman MP, Cameron SA, Aizen MA (2013) Front. Ecol. Environ. 11(10):529–534, doi:10.1890/120321; "
     "Arbetman MP et al. (2013) Biol. Invasions 15(3):489–494, doi:10.1007/s10530-012-0311-0"),
    ("poultry litter, applied for years", "soil and water", "harm",
     "phosphorus builds up in the surface soil (Bray-1 P 188 against 9 mg/kg in the top 5 cm after 12–35 years), "
     "where runoff picks it up", "",
     "Sharpley AN, Smith SJ, Bain WR (1993) Soil Sci. Soc. Am. J. 57(4):1131–1137, "
     "doi:10.2136/sssaj1993.03615995005700040041x"),
    ("raw manure", "food crops", "harm",
     "pathogens; US organic rules require it worked in at least 120 days before harvest of crops whose edible part "
     "touches the soil, 90 days for others, unless composted", "",
     "7 CFR 205.203(c)(1), https://www.ecfr.gov/current/title-7/subtitle-B/chapter-I/subchapter-M/part-205/subpart-C/section-205.203"),
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
    for subject, obj, effect, mechanism, level, source in CURATED:
        out.append({"subject": subject, "object": obj, "effect": effect,
                    "mechanism": mechanism, "level": level, "source": f"curated: {source}"})
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
                "plant-bees-globi-sources.txt), or curated (each row's own citation).\n")
        w = csv.DictWriter(h, fieldnames=["subject", "object", "effect", "mechanism", "level", "source"])
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        key = r["source"].split(" ")[0].rstrip(":")
        by[key] = by.get(key, 0) + 1
    print(f"{len(rows)} interaction records: " + ", ".join(f"{k} {v}" for k, v in by.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
