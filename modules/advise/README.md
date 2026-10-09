<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/advise/` — what to grow here, and when

A **layer-3 module** (spec v0.1 §11, decision support) built on layer zero. Given a point, it
reads thirty years of the place's weather, its soil and its plant data, and writes a report
a farmer can act on: which food crops mature and when to sow them, which fruit cultivars
get their winter chill and how often frost follows bloom, what suits the soil and what it
needs, which bees visit, what heat the livestock face, and what changes by the 2050s. In
English and Spanish, and in any language a pack is added for.

```sh
python3 modules/advise/advise.py 35.06445 -86.59137 --cache CACHE --out OUT --lang en,es --windows
python3 modules/advise/advise.py 35.06445 -86.59137 --cache CACHE --out OUT --warm 1.0 --future-label 2050s
cd modules/advise && python3 -m unittest discover -p 'test_*.py'
```

Examples: [notes/advise-mcallister.en.md](notes/advise-mcallister.en.md),
[notes/advise-mcallister.es.md](notes/advise-mcallister.es.md), and the 2050s versions beside
them. The method and the results behind each section are in
[notes/site-match-tennessee.md](notes/site-match-tennessee.md); the plan it came from is
[notes/plant-conditions.md](notes/plant-conditions.md).

## Why it is a module

It moved here from `tools/` on 2026-10-09 ([notes/advisor-home-proposal.md](notes/advisor-home-proposal.md),
option B, decided). Layer zero "ships no end-user features", and the advisor had grown
inside it: half of layer zero's language strings were a crop report's, its code carried
the SDK's licence, and its data sat among the spec's notes. As a module:

* **It depends on layer zero, never the reverse.** It imports `sdk/` (the language packs),
  `tools/soil_survey.py` and `tools/nasa_power.py`; nothing in `sdk/`, `server/`, `sim/` or
  `tools/` imports it, and `tools/test_layering.py` fails if anything starts to.
* **Its strings are its own.** [packs/](packs/) holds every `advise.*` string, merged over
  layer zero's pack of the same language at load (`i18n.register`). A module key cannot
  shadow layer zero's.
* **Its data is listed.** [data/MANIFEST.csv](data/MANIFEST.csv) gives every data file's
  source, licence, retrieval date and checksum; a test fails if a file changes without its
  line.
* **Every report says what made it** — the module version, the data manifest's hash and the
  DSSAT commit the crop models are pinned to — so a report can be reproduced and a changed
  recommendation explained.

## Licence

The code is **AGPL-3.0-or-later** ([LICENSE](LICENSE)), as the reference server is: an
advisor is the piece most likely to be run as a hosted service, and the network clause
keeps a hosted copy's improvements open (Q2's reasoning, applied here). The data keeps
each source's own licence, per [data/MANIFEST.csv](data/MANIFEST.csv) — CC0, CC BY 4.0
and BSD-3-Clause, the last with DSSAT's notice in
[data/crop-parameters-dssat-LICENSE.txt](data/crop-parameters-dssat-LICENSE.txt). Notes and
packs' prose are CC BY 4.0 like the rest of the documentation.

## What is in it

| file | what it does |
| --- | --- |
| `advise.py` | the report, now and for a warmer decade |
| `site_profile.py` | a site's climate (NASA POWER), soil (USDA soil survey) and erosion |
| `plant_match.py` | each plant against the site, with the condition that decides; bloom calendar |
| `dssat_crops.py` | DSSAT crop models (CROPGRO, CERES maize, sorghum, millet, rice, wheat, barley) run on the site's thirty years; sowing windows |
| `fruit_bloom.py` | fruit chill, bloom date and frost after bloom |
| `chill_requirements.py`, `chill_requirements_pome.py` | the openly licensed chill tables, re-keyed |
| `plant_conditions.py`, `globi_bees.py`, `interactions.py` | USDA PLANTS data, bee records, what mixes with what |
| `tunnel_gain.py` | a hoop house's measured warmth, from paired sensors |
| `module.py` | version, data manifest, language packs |
