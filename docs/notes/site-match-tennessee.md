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
| fruit chill requirements | [chill_requirements.py](../../tools/chill_requirements.py), [chill_requirements_pome.py](../../tools/chill_requirements_pome.py) | [chill-requirements.csv](chill-requirements.csv), [chill-requirements-pome.csv](chill-requirements-pome.csv) (CC BY 4.0) |

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
curves and the CROPGRO, CERES-Maize, CERES-Sorghum, CERES-Millet, CERES-Rice and
Cropsim-CERES wheat and barley phenology, and runs every cultivar of 28 crops through the
site's thirty years of
weather and day length: planted a week after each year's last frost (four weeks before it
for cool-season crops, two weeks before the first fall frost for the winter cereals), does
it reach physiological maturity before the first fall frost — or, for the winter cereals,
survive the winter and mature? [crop-parameters-dssat.csv](crop-parameters-dssat.csv) carries the
parameters, with DSSAT's notice.

At McAllister Farm:

| crop | cultivars maturing 8 years in 10 | days to maturity |
| --- | --- | --- |
| maize (CERES-Maize) | 166 of 166 hybrids | 86–148 |
| sorghum (CERES-Sorghum) | 51 of 55 | 113–194 |
| pearl millet (CERES-Millet) | 48 of 60 | 99–226 |
| wheat, fall-sown (Cropsim-CERES) | 5 of 8 — the winter wheats | 229–248 |
| barley, fall-sown (Cropsim-CERES) | 1 of 3 | 261 |
| rice, drill-seeded (CERES-Rice) | 42 of 55 | 122–221 |
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

**Wheat and barley** carry what the other models do not: vernalization and winter
hardiness. Development runs on thermal time scaled by a vernalization factor (cold days
counted through a −5/0/7/15 °C response until the cultivar's requirement, P1V, is met)
and a long-day factor; and a kill temperature hardens from −6 °C toward the ecotype's
limit (−20 °C for the US soft red winter ecotype) through cool autumn days and softens on
warm ones. Newton, a US winter wheat, sown two weeks before the median first frost
(October 20 here) flowers about April 30 and matures in 230 days — early June, when
Tennessee wheat is cut, which is what leaves room for the double-crop soybean sown into
its stubble. NASA POWER carries no snow, so the crown is never insulated; that errs toward
winter kill.

Three rules go beyond DSSAT, each because a result was wrong without it. DSSAT stops
counting cold once the spike grows, so a spring wheat sown in October "flowered" in late
February and matured; now a daily minimum of −2.2 °C or below from boot on ends the season
(K-State's C-646 puts injury at 28 °F at boot, 30 °F at heading), and the fall-sown spring
wheats fail most years, as they would. A sowing swept through summer "matured" too, so a
day over 31 °C while it flowers ends the season (above 31 °C pollination fails: Porter &
Gawith 1999), and a season longer than nine months does not count — phenology alone lets a
June-sown winter wheat wait out the summer for its cold. Five of the eight wheats, the
winter ones, mature from a fall sowing 8 years in 10. Barley's three cultivars were
calibrated in Syria and England; one matures, and its winter types flower in mid-March
here, earlier than Tennessee barley heads. A local calibration would fix barley.

**Rice** runs DSSAT's direct-seeded path, as Mid-South rice is drilled rather than
transplanted: germination paced by the sowing day's warmth, a juvenile phase, a short-day
phase that also waits out a spell of cold nights before panicle initiation, then heading and
grain fill. Lemont, a southern long-grain, sown May 1 heads in about 98 days and matures in
about 122, the end of August, as the region's rice does. The season is no obstacle at
McAllister — 42 of 55 cultivars mature 8 years in 10 — but rice there is a question of
water, a flooded field on silt loam, which no phenology model asks.

**When to sow.** With `--windows` the tool sows every week of the year, with the fastest,
a middle and the slowest of the cultivars that mature here 8 years in 10 (by simulated
days, not by the size of their requirement, which ignores day length and once picked a
short-day sorghum that never flowers in summer), and ends each season at the first freeze below that
crop's own damage threshold (DSSAT's FREEZ1: −2.2 °C for tomato and beans, −6 for cabbage,
−9 for faba bean, −29 for lentil). Sowing windows that mature 8 years in 10 at McAllister
Farm: tomato Apr 9–Jul 2; pepper Apr 9–May 28; maize Apr 9–Jul 30; sorghum Apr 9–Jul 9;
pearl millet Apr 9–Jul 30; soybean Apr 9–Aug 20 (the late end is the double crop after
wheat); peanut Apr 9–Jul 2; dry bean Apr 9–Aug 13;
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

## One command, in any language

`tools/advise.py LAT LON --lang en,es --windows` runs all of the above for a point and
writes a report a farmer can read — the site, food crops with sowing windows, fruit trees
by winter chill with bloom dates and the frost after them, what suits,
what needs lime, sulfur or water, what does not suit and why, what is refused as invasive,
bees, livestock heat — plus the data behind it. Its words come from the language packs, so
the same report renders in Spanish (dates, decimal commas and the reasons included) and in
any language a pack is added for; plant names stay English until AGROVOC's are added.
Example: [advise-mcallister.en.md](advise-mcallister.en.md),
[advise-mcallister.es.md](advise-mcallister.es.md).

**Invasive listings by state.** USDA PLANTS lists invasive and noxious status by state for
13 jurisdictions — Tennessee is not one of them, Alabama and North Carolina are — plus the
federal noxious weed list. A plant listed in the site's own state, or federally, is
refused; one listed elsewhere carries a caution naming the states. So the report refuses
water spinach (a federal noxious weed) and kudzu (on the project's do-not-plant list), and
flags paulownia as listed in Alabama, Connecticut, North Carolina and Wisconsin. The
Tennessee Invasive Plant Council's list would close the local gap; its terms are to check.

## The 2050s

`advise.py --warm 1.0 --future-label 2050s` runs everything twice, the second time on the
same thirty years of weather with every day 1.0 °C warmer (the delta method), and writes
what changes: [advise-mcallister-2050s.en.md](advise-mcallister-2050s.en.md),
[advise-mcallister-2050s.es.md](advise-mcallister-2050s.es.md).

**Why +1.0 °C.** The Berkeley Earth series for Tennessee in `~/dev/climate-analysis` puts
the 2050 level at +1.89 °C against 1951–1980 and 2060 at +2.18 °C. The 2011–2020 mean sits at
+1.149 °C and the trend runs at 0.264 °C a decade, so the 1991–2020 baseline this record
represents (centred near 2005) is about +0.89; 1.89 − 0.89 ≈ +1.0 °C for the 2050s (and
≈ +1.3 °C for the 2060s). The figure comes from that repository's data and method; none of
its code is imported.

**What moves at McAllister.** Frost-free days 8 years in 10 go from 207 to 213, growing
degree days from 2774 to 2985, days over 35 °C from 13 to 21, and the dairy heat-stress
upper estimate from 172 to 183 days; the hardiness zone stays 8a (1.8 °F is under half a
zone). Every modelled crop's sowing window opens about two weeks earlier (maize and soybean
from April 9 to March 26), and many close a week later. The longer season lets more
sorghum (51 → 52 of 55) and pearl millet (48 → 53 of 60) cultivars mature; no crop loses
one. The plant matcher moves one plant (saltmeadow cordgrass now fits). Chill barely moves
(1048 to 1023 hours on average), because warming turns hours below freezing into chill
hours about as fast as it lifts others above 7.2 °C — see below.

**What the delta method cannot say.** It moves today's weather and keeps its variability,
so it says nothing about wetter springs, longer droughts or stronger storms. It is uniform
over the day and the year, while the Mid-South's record shows nights warming faster than
days (the "warming hole" in summer maxima): with warmer nights and the same days, chill
would fall faster and heat stress at night rise faster than this shows. Rain is left
unchanged because the record gives no defensible direction for it here.

## Stone fruit by winter chill

A peach, plum or cherry that does not get its winter chill flowers late and unevenly, and
chill was the one condition for fruit trees with no open source behind it. FAO ECOCROP is
non-commercial, and CITA Aragón's 143-cultivar dataset is CC BY-NC-ND. The source that
works is the review by Fadón, Herrera, Guerrero, Guerra and Rodrigo (2020, *Agronomy*
10:409, CC BY 4.0), which tabulates every published requirement it found:
**[chill-requirements.csv](chill-requirements.csv)**, 662 requirements for 531 cultivars of
almond, European and Japanese apricot, peach, nectarine, flat peach, European and Japanese
plum, and sweet and sour cherry. Each row carries its model (chill hours, Utah units,
chill portions, and growing degree hours for heat), method, place, and the original study.

Re-keying it was the work: the tables centre each cultivar's name across its rows, which
text extraction cannot follow (a four-row cultivar's name lands beside its third row).
[chill_requirements.py](../../tools/chill_requirements.py) reads the PDF's word positions
instead and splits each page's rows so every name sits nearest its rows' midpoint. The
result reproduces the review's own cultivar count for every crop. One cherry is extra
because the review's Table 8 itself is one short. Every one of the 658 rows a text
extraction shows is present, plus 4 rows the PDF prints with no location.

**Counting chill.** A chill hour is an hour between 0 and 7.2 °C — the review's definition,
and chillR's — so hours below freezing do not count, though the site profile counted them
at first. That correction cut McAllister's figure by a third (1648 to 1048 hours a winter,
November to February). Chill is counted over full winters only (the record's half-winters
at each end had pulled the mean down a few percent), and for fruit through the end of
March, since a tree goes on gathering chill until it has enough: 1090 hours 8 years in 10.
The advisor holds each cultivar's requirement to the top of its published range, and a
cultivar measured twice to the higher figure. At McAllister that covers every almond,
nectarine, flat peach and Japanese plum, 115 of 126 peaches, 26 of 41 European apricots,
25 of 40 cherries and 4 of 9 European plums: the high-chill end of the list falls short.
Warming hardly changes it (1047 in the 2050s; 108 peaches, 24 apricots), because a warmer
winter here turns hours below freezing into chill hours nearly as fast as it lifts others
above 7.2 °C — a mild-winter site would lose chill faster. The requirements were measured
in a dozen countries — Spain for 43% of rows, then China, the US and Korea — by methods
that do not always agree, so the report calls them a guide.

**Bloom and frost.** Late frost at bloom is the commoner loss here, and 145 of the
requirements come with a heat requirement too, so bloom can be simulated:
[fruit_bloom.py](../../tools/fruit_bloom.py) counts chill from November 1 until the
cultivar's requirement is met, then growing degree hours (Anderson et al. 1986: base 4,
optimum 25, ceiling 36 °C) until its heat requirement is met — bloom — and calls a year
frosted when the minimum reaches −2.2 °C (28 °F, 10% bud kill at full bloom for sweet
cherry; 27 °F for peach and apricot, in Washington State's Prosser measurements) within two
weeks after. At McAllister:

| crop | bloom (median) | frost after bloom |
| --- | --- | --- |
| almond | Feb 4–Mar 12 (Feb 20) | 8 years in 10 |
| Japanese apricot | Dec 18–Mar 21 (Feb 28) | 7 in 10 |
| nectarine | Mar 16–Apr 2 (Mar 21) | 4 in 10 |
| European apricot | Mar 14–Apr 15 (Mar 23) | 3 in 10 |
| peach | Mar 19–Apr 13 (Mar 26) | 2 in 10 |
| Japanese plum | Mar 12–Apr 5 (Mar 27) | 2 in 10 |
| cherry | Mar 29–Apr 30 (Apr 28) | 0 in 10 |

That is the shape growers know: almonds are not grown in Tennessee because they bloom into
February frosts, peaches lose a crop to spring frost some years, late-blooming cherries
escape. In the 2050s every crop blooms about a week earlier and the frost count holds or
falls by one — the frosts move earlier too. The grid's minimums are milder than an orchard
floor on a still night, so these counts err low, and an orchard on a slope will do better
than one in a frost pocket.

## Apples and pears

The stone-fruit review leaves out the commonest orchard trees. Two more CC BY 4.0 papers
cover them, re-keyed by [chill_requirements_pome.py](../../tools/chill_requirements_pome.py)
into **[chill-requirements-pome.csv](chill-requirements-pome.csv)**:

* **Apples:** the review by González Noguer, Delgado, Else and Hadley (2023, *Frontiers in
  Horticulture* 2:1217689). Its Table 2 holds 173 published requirements, each with the
  cultivar's use (dessert, cider, crab or rootstock), place, method and study. It is read
  from the article's HTML, where a cell spanning several rows carries its citation key
  down to each, and every key is checked against the author and year the cell prints. One
  cell writes a thousand with a point (Raxao, "1.005" chill hours), read as 1005.
* **Pears:** Fadón, Espiau, Errea and Alonso Segura (2023, *Agronomy* 13:518), 16
  traditional European pears over twenty years at Zaragoza, in all three chill models and
  heat.

Both define a chill hour as the stone-fruit review does, 0 to 7.2 °C. The advisor counts
the dessert and cider apples. It leaves out rootstocks, crab apples and the 16 cultivars
the table gives no use for, since none of those says what will fruit. That leaves 78
apples with a chill-hour requirement, 54 of them from one study (Hauagge and Cummins 1991).

At McAllister, **55 of 78 apples and all 16 pears** get their chill. The pears need 825 to
894 hours at the top of their spread, well inside the site's 1090. In the 2050s the apples
fall to **39**. Apples, unlike stone fruit, lose ground here, because Hauagge and Cummins
put sixteen common cultivars between 1049 and 1090 hours: Golden Delicious, Gala, Fuji,
McIntosh and Granny Smith among them. That is right where McAllister's 8-in-10 winter sits,
so the 2050s' 43 fewer hours carry all sixteen across the line. The cliff is in the table
more than in the orchard. Those requirements come from one place and one method, and a
cultivar 20 hours short still blooms, only less evenly. But it marks which apples a
warming winter here reaches first.

Only 24 apple estimates come with a heat requirement too, and 21 of them are local apples
from northwestern Spain, 19 of those for cider (Delgado and others 2021). So the apple bloom
below speaks mostly for those:

| crop | bloom (median) | frost after bloom | 2050s |
| --- | --- | --- | --- |
| apple | Apr 7–23 (Apr 15) | 0 in 10 | Apr 12, 0 in 10 |
| pear | Apr 1–5 (Apr 3) | 1 in 10 | Mar 29, 0 in 10 |

Two apples bred for warm winters, Anna and Dorsett Golden, need about 250 hours in the
Egyptian study and bloom here at the start of March. Frost follows two years in three,
which is why they are planted in Florida and not Tennessee. The estimates disagree as much
as they do for stone fruit. Hauagge and Cummins give Dorsett Golden 814 hours to Egypt's
238, and a Moroccan statistical estimate pairs Gala's 537 hours with 22,402 degree-hours of
heat, which simulates bloom on May 19. Estimates from warm-winter sites trade chill for
heat and do not travel. The pear estimates, from one orchard and one method, barely differ
from each other, which says more about the method than about the pears.

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

[interactions.csv](interactions.csv): **506 records** of one thing affecting another, each
with its mechanism and source. 154 come from USDA PLANTS fields that already encode a link
— 40 palatable forages, 35 browses, 31 toxic plants, 28 nitrogen fixers, 15 marked
allelopathic, 5 bloat risks; 327 from GloBI's bee records; 25 curated from the plan, each
now carrying its own citation (a paper, an extension guide or a regulation) and worded to
what that source supports. Checking them changed five: poultry following cattle is
`unproven` (a controlled trial found broilers left dung pats and face-fly larvae alone);
ducks in rice are `mixed` (weeds down, planthoppers up, because the ducks eat the spiders
too); squash bees *prefer* tilled soil, so it is deep tillage over nests already dug that
harms them; nothing supported "pigs tolerate acorns" as a toxicology claim; and kudzu and
mowing during bloom were dropped where no source carried them.

The PLANTS toxicity flags line up with known agronomy — sorghum's prussic acid, black
cherry and chokecherry's cyanide, sweet clover's dicoumarol, leucaena's mimosine,
buckwheat's photosensitisation — while "bloat: medium" on maize is another PLANTS oddity.

## Not checked yet

For the 28 crops with a crop model, temperature, day length and time to maturity — and for
wheat and barley, vernalization, winter kill, freeze after boot and heat at flowering — are
checked together, by simulation; for 531 stone-fruit cultivars, 78 apples and 16 pears,
winter chill, and for 167 of them, bloom date and frost after it. Still not checked: chill
and bloom for blueberries (no openly licensed table found), heat damage to fruit set beyond
the development curve, transplanted rice (the drill-seeded path is ported, as the
Mid-South sows it), oats and rye (no DSSAT model), and everything for the 255 plants with
neither source — most fruit, herbs and flowers.

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
