<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# What grows at three Tennessee farms, and why not

**2026-10-08.** The first working run of the plan in
[plant-conditions.md](plant-conditions.md): the plant list turned into data, three sites
profiled, the plants matched against them, and the bee forage calendar laid over the
months. The sites are the three SCAN stations whose soil and sensors this project already
knows best — McAllister Farm, Allen Farms and Eastview Farm, south-central Tennessee.

| step | tool | output |
| --- | --- | --- |
| plant list → USDA PLANTS data | [plant_conditions.py](../../tools/plant_conditions.py) | [plant-characteristics-usda.csv](plant-characteristics-usda.csv) (CC0) |
| site profile | [site_profile.py](../../tools/site_profile.py) | NASA POWER 1991–2020 + the soil survey |
| match and bloom calendar | [plant_match.py](../../tools/plant_match.py) | per plant: which condition decides |
| bees per plant | [globi_bees.py](../../tools/globi_bees.py) | bee records from GloBI |
| what mixes with what | [interactions.py](../../tools/interactions.py) | [interactions.csv](interactions.csv) |

## The three sites

| | McAllister Farm | Allen Farms | Eastview Farm |
| --- | --- | --- | --- |
| soil | Dickson silt loam, 2–5% | Hampshire silt loam, 5–12%, eroded | Decatur silty clay loam, 2–6%, eroded |
| drainage | moderately well | well | well |
| topsoil pH; organic matter | 6.2; 2.8% | 6.2; 2.0% | 6.5; 1.0% |
| available water (topsoil) | 0.158 | 0.138 | 0.150 m³/m³ |
| climate | Cfa, 15.4 °C, 1,376 mm | same grid cell | Cfa, 15.1 °C, 1,359 mm |
| frost-free days (median; 8 years in 10) | 215; 207 | 215; 207 | 215; 205 |
| growing degree days (°C, base 10) | 2,774 | 2,774 | 2,712 |
| chill hours (estimate) | about 1,600 | about 1,600 | about 1,600 |
| dairy heat-stress days a year (range of estimates) | 96–172 | 96–172 | 91–168 |
| bare-soil erosion (estimate) against tolerable | 175 vs 6.7 t/ha/yr — 26× | 328 vs 9.0 — 37× | 127 vs 11.2 — 11× |
| warming within 1991–2020 | +0.50 °C | +0.50 °C | +0.51 °C |

- **NASA POWER is coarse.** McAllister and Allen Farms, 27 km apart, share a grid cell
  and so an identical climate; only their soils differ. The grid also smooths extremes:
  it puts all three sites in hardiness zone 8a where the USDA's station-based map puts
  this area around 7, and its frost dates are optimistic. The profile says so on every
  run, and the match keeps a margin for it.
- **Erosion is the loudest number.** Bare, these silt loams would lose 11 to 37 times what
  the soil survey calls tolerable — Allen Farms most, on its 9% eroded slope. The
  practical meaning: on these soils, ground left bare over winter is the costly mistake,
  and cover crops, perennial forage and buffers are not optional.
- **Heat stress for dairy cattle** falls on a quarter to nearly half the year, depending
  on which estimate — the case for the heat-tolerant breeds on the animal list.

## The match

At McAllister Farm (the others differ only where topsoil pH does):

| verdict | plants |
| --- | --- |
| suits | 88 |
| suits, with cautions | 46 |
| suits, with lime or sulfur | 20 |
| suits, with irrigation | 3 |
| unsuited | 26 |
| refused — invasive | 12 |
| no data in USDA PLANTS | 278 |

**Ruled out:** every tropical crop on the list — citrus, mango, papaya, pineapple, coffee,
coconut, sugarcane, tamarind, breadfruit, and the tropical forage and agroforestry trees
(napier and guinea grass, vetiver, leucaena, gliricidia) — by the frost-free season, and
in most cases the winter as well; and a few coastal or deep-south species (radiata pine,
bitter panicum, saltmeadow cordgrass).

**Suits, or suits with cautions** (most often rainfall above PLANTS' range, as for maize,
blueberry and chestnut), by category, among others: wheat, oats, barley, rye, sorghum, maize; soybean,
cowpea; alfalfa, red clover, vetches, birdsfoot trefoil, sunn hemp; tall fescue,
orchardgrass, switchgrass and the native prairie grasses; pecan, black walnut, Chinese
chestnut, American hazelnut; pear, persimmon, pawpaw, muscadine, blueberry, elderberry;
white and red oak, black cherry, shortleaf and loblolly pine, sugar maple; Fraser fir and
the other Christmas trees; all fourteen streambank plantings, the windbreak shrubs, the
slope grasses; the bee trees — tulip poplar, basswood, sourwood, red maple, redbud.

**Fixable:** topsoil pH 6.2 is a little low for barley, red clover, sweet clover,
partridge pea and big bluestem (lime), and a little high for shortleaf pine and bald
cypress (sulfur). At Eastview Farm, pH 6.5, most of these pass.

## What this run found wrong with the data

**USDA PLANTS is a conservation-planting database.** It covers the plants on our list
that conservation programs plant — erosion plantings (35 of 38 with characteristics),
forage grasses (16 of 18), forage legumes (11 of 12), timber (24 of 29) — and almost none
of the food: vegetables 5 of 59, spices and herbs none of 34, cut flowers 1 of 23,
tropical fruit 11 of 32, pulses 6 of 23. Apple and peach have entries and no
characteristics. **So this first version answers conservation, forage and timber
questions, and is mostly silent on food crops.** Filling that is the case for asking FAO
about ECOCROP ([the draft request](fao-ecocrop-request-draft.md)), or for another open
crop source.

**Its limits are guidance, not limits.** PLANTS lists white clover as needing 250
frost-free days and dying below 22 °F, and bermudagrass, crimson clover and annual
ryegrass much the same — all staples of Tennessee pasture and cover cropping, at 207 days
and 11 °F. Crimson clover and annual ryegrass are winter annuals, for which frost-free
days do not apply at all. Buckwheat, an eight-week summer annual, is listed at 365
frost-free days; aronia, hardy far colder, at 24 °F; mango, killed by a few degrees of
frost, at 17 °F. The first version of the matcher took the values as limits and ruled out
half of Tennessee's pastures. It now rules a plant out only on an overwhelming shortfall —
under 75% of the season, or more than 15 °F below the minimum — which still excludes
every tropical crop; anything less is a caution that quotes what PLANTS lists, and an
implausible season on an annual is named as implausible and not used.

## Bees: the bloom calendar

Of the plants that suit the sites, 143 have a PLANTS bloom period. Laid over the months
(the northern-hemisphere reading of PLANTS' seasons):

| | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| suited plants in flower | 1 | 2 | 37 | 55 | 45 | 23 | 25 | 18 | **0** | **0** | **0** | 1 |

Bees can fly here from February to December (a mean daily maximum of 10 °C or more).
**September to November show nothing recorded in flower** — but that is at least partly
missing data: asters have no PLANTS characteristics, and PLANTS gives goldenrod "late
summer". The true autumn gap is narrower than this; that it exists at all is the familiar
pattern, and goldenrod, asters and late-sown buckwheat are the usual answers.

## Food crops, from a crop model

USDA PLANTS knows almost nothing about food crops, so a second source was brought in: the
**DSSAT** crop models (BSD-3-Clause), whose parameter files give each crop's cardinal
temperatures for development, its response to day length, and — per cultivar — how long
each phase takes. [dssat_crops.py](../../tools/dssat_crops.py) ports DSSAT's own response
curves and the CROPGRO and CERES-Maize phenology, and runs every cultivar of 23 crops through the site's
thirty years of weather and day length: planted a week after each year's last frost (four
weeks before it for cool-season crops), does it reach physiological maturity before the
first fall frost? [crop-parameters-dssat.csv](crop-parameters-dssat.csv) carries the
parameters, with DSSAT's notice.

At McAllister Farm:

| crop | cultivars maturing 8 years in 10 | days to maturity |
| --- | --- | --- |
| maize (CERES-Maize) | 166 of 166 hybrids | 86–148 |
| dry bean | 30 of 30 | 75–107 |
| tomato | 4 of 4 | 120–131 |
| pepper | 5 of 5 | 155–182 |
| cabbage (spring) | 3 of 3 | 116–150 |
| peanut | 38 of 38 | 133–178 |
| soybean | 36 of 59 | 89–200 |
| cowpea | 10 of 12 | 136–197 |
| chickpea, lentil, faba bean (spring) | all | 96–153 |
| sunflower, canola, flax, safflower | all | 81–128 |
| quinoa, amaranth | all | 87–91 |
| cotton | 17 of 17 | 118–172 |
| **pigeon pea** | **0 of 3** | short-day: long summer days delay flowering until frost |
| **velvet bean** | **0 of 20** | likewise |

**When to sow.** With `--windows` the tool sows every week of the year, with the fastest,
a middle and the slowest cultivar, and ends each season at the first freeze below that
crop's own damage threshold (DSSAT's FREEZ1: −2.2 °C for tomato and beans, −6 for cabbage,
−9 for faba bean, −29 for lentil). Sowing windows that mature 8 years in 10 at McAllister
Farm: tomato Apr 9–Jul 2; pepper Apr 9–May 21; maize Apr 9–Jul 23; soybean Apr 9–Aug 6
(the late end is the double crop after wheat); peanut Apr 9–Jul 2; dry bean Apr 9–Aug 13;
cabbage Mar 12–Aug 6, spring and fall; chickpea Feb 19–Aug 27; canola Mar 5–Jul 30. The
dates are sowing, not transplanting. Lentil and sunflower come out "all year" because
DSSAT gives them damage thresholds of −29 and −15 °C; lentil's is a modern winter-hardy
calibration, sunflower's is generous for young plants.

Sixteen food crops on the list move from *no data* to a verdict, and pigeon pea and
velvet bean are ruled out for the right reason — day length, which PLANTS never checked.
The matcher takes these with `--crop-seasons` and lets the crop model outrank PLANTS on the
season, since it runs thirty real seasons rather than comparing one number. Simplified,
and said so in the tool: hours are a sine between the day's minimum and maximum, soil
temperature is taken as the air's, and water and nutrient stress are not simulated.

## Bees per plant, from GloBI

[plant-bees-globi.csv](plant-bees-globi.csv): for every plant on the list, the bees
recorded visiting or pollinating it in GloBI — **327 of 473 plants**, from 49 source
datasets credited in [plant-bees-globi-sources.txt](plant-bees-globi-sources.txt)
(CropPol, the global crop-pollination database; DoPI; EuPPollNet; iNaturalist; museum
collections). The managed bees on the animal list turn up where they should: the squash
bee on squash, the blue orchard bee and its relatives on apple, the alfalfa leafcutting bee
on alfalfa, the southeastern blueberry bee on blueberry, the sugarbag bee on macadamia,
stingless bees on coffee.

Two cautions. These are **records, not dependence**: maize has 337 bee records because
bees collect its pollen, but it is wind-pollinated. And records follow where people
looked — Europe and North America, crops and gardens — so few records is not few bees.
Queries are limited to bee families and capped at 4,000 records; 26 plants reached the
cap, and their counts are lower bounds. The first version of the query took every
interaction and filtered after: a well-studied plant's first few thousand records were
its pests and diseases, and apple came back with no bees at all.

## What mixes with what

[interactions.csv](interactions.csv): **502 records** of one thing affecting another, each
with its mechanism and source. 150 come from USDA PLANTS fields that already encode a link
— 38 palatable forages, 33 browses, 31 toxic plants, 28 nitrogen fixers, 15 marked
allelopathic, 5 bloat risks; 327 from GloBI's bee records; 25 curated from the plan,
marked *to cite*. The PLANTS toxicity flags line up with known agronomy — sorghum's
prussic acid, black cherry and chokecherry's cyanide, sweet clover's dicoumarol,
leucaena's mimosine, buckwheat's photosensitisation — while "bloat: medium" on maize is
another PLANTS oddity.

## Not checked yet

For the 23 crops with a crop model, temperature, day length and time to maturity are now
checked together, by simulation. Still not checked: chill hours against a fruit tree's
requirement (no open source found yet), heat damage to fruit set beyond the development
curve, fall plantings of cool-season crops, the other cereals (sorghum, millet, wheat, barley
and rice each have their own DSSAT phenology, not ported yet), and everything for the 255 plants with neither
source — most fruit, herbs and flowers.

## Reproducing

```sh
python3 tools/plant_conditions.py docs/notes/plant-list.csv --cache CACHE \
    --out docs/notes/plant-characteristics-usda.csv
python3 tools/site_profile.py 35.06445 -86.59137 --cache CACHE --json site.json
python3 tools/plant_match.py docs/notes/plant-list.csv \
    docs/notes/plant-characteristics-usda.csv site.json --out match.csv
```

Climate: NASA POWER, CC BY 4.0. Soil: USDA NRCS SSURGO, public domain. Plants: USDA NRCS
PLANTS, CC0. Bees: GloBI, CC BY 4.0, and the studies it cites.
