<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Plant growing conditions: the list, the dimensions, the sources

**2026-10-08. A plan, saved for later — nothing here is built yet.** The idea: for each
plantable plant, dig out the conditions it grows best in — soil, water, climate, light —
and match them against what a farm actually has, which librefarm already measures or
looks up. That is a layer-3 (decision support) module: "what grows well *here*, and what
would grow well here in twenty years."

The list is [plant-list.csv](plant-list.csv): **477 plants, 98 families** — cereals and
pseudocereals, pulses, roots and tubers, vegetables, oilseeds, sugar, fibre,
beverage crops, spices and herbs, temperate, berry and tropical fruit, nuts, forage
grasses and legumes, cover crops, agroforestry trees, pollinator and beneficial plants,
cut and edible flowers, bee forage, timber, Christmas trees and forest farming, plantings
against erosion, and a do-not-plant list of invasives. Animals, bees, fertilizers, and
what mixes with what, are in [animals-bees-and-inputs.md](animals-bees-and-inputs.md);
tree farms and erosion control in
[trees-and-conservation-planting.md](trees-and-conservation-planting.md); growing them as
nursery stock in [nursery.md](nursery.md); growing under cover in
[hoop-houses.md](hoop-houses.md). Keyed by scientific name, because every data source below is. Each name is to be
checked against USDA PLANTS when its conditions are pulled; the common name is a label,
not a key, and multilingual names can come from AGROVOC (see Q4) rather than from here.

## What to dig out, and where each side comes from

Every dimension has two sides: what the **plant** needs, and what the **site** has. The
site side is mostly in reach already.

| dimension | the plant needs | the site has — source |
| --- | --- | --- |
| **Soil texture** | adapted to coarse / medium / fine soils | sand, silt and clay at each depth — `tools/soil_survey.py` (USDA SSURGO) in the US; ISRIC SoilGrids worldwide |
| **Soil chemistry** | pH range; tolerance of salinity, lime (CaCO₃) | the same surveys; a farm's own soil test beats both |
| **Drainage** | anaerobic (waterlogging) tolerance; rooting depth | survey drainage class and depth to a restrictive layer; librefarm soil-moisture probes show how long the soil stays saturated |
| **Water** | annual rainfall range; drought tolerance; moisture use; seasonal water demand | rainfall from NASA POWER (daily, any point, 1981 on) or CHELSA normals; available water capacity (field capacity − wilting point) from the soil survey; irrigation availability from the farm |
| **Cold** | minimum temperature survived; frost-free days needed; for fruit trees, chill hours | daily minima from NASA POWER → last and first frost dates, frost-free days, chill hours |
| **Heat and season** | temperature range for growth (minimum, optimum, maximum); growing degree days to maturity, with a base temperature | daily temperatures → growing degree days and season length |
| **Sunlight** | shade tolerance; daily light needed; **day-length response** (short-day, long-day, neutral); C3 or C4 photosynthesis | daily solar radiation from NASA POWER (1984 on); day length computed from latitude and date; shade from trees and buildings only on the farm itself (observation, or a light sensor) |
| **Climate class** | the Köppen classes it is grown in | Köppen class at the point (already used for the dwell tables, Q24) |
| **Climate trend** | — | `~/dev/climate-analysis`: Berkeley Earth monthly temperature, with an absolute baseline, for 7 continents, 23 countries and 15 US states — "historical versus now" by region. CHELSA's CMIP6 futures for "in 2050" at a point |

**Also worth carrying, as found while drafting:**

- **Invasiveness, by region.** Several plants on this list are useful in one place and
  invasive in another — leucaena, buffelgrass, napier grass, black locust, Kentucky
  bluegrass outside its range. A suitability list that recommends an invasive is worse
  than none. USDA PLANTS carries US noxious and invasive status; GRIIS (the Global
  Register of Introduced and Invasive Species) is the worldwide candidate.
- **Day length matters more than it looks.** An onion variety bred for long northern
  days will not bulb in Kenya; many soybean and rice varieties flower by day length.
  Conditions differ by *variety* as well as by species — the list stops at species.
- **Elevation, slope and aspect** (a south slope is warmer and drier in the northern
  hemisphere) and **wind exposure**.
- **Pollination**: whether the crop needs pollinators or a second variety to set fruit.
- **Role in a rotation**: nitrogen fixation, family (pest and disease carry-over between
  related crops), rooting depth, allelopathy.

## Sources, and whether we may build on them

Checked 2026-10-08. The licence matters because the project is CC-BY / Apache / AGPL, and
a non-commercial source cannot be redistributed in it.

| source | gives | licence | use |
| --- | --- | --- | --- |
| **USDA PLANTS characteristics** — `plantsservices.sc.egov.usda.gov/api` | the plant side above, almost field for field: soil textures, pH, rainfall range, drought tolerance, moisture use, minimum temperature, frost-free days, salinity, CaCO₃, anaerobic and shade tolerance, root depth, fertility, nitrogen fixation | **CC0** (public domain) | **the backbone.** Probed: maize, sorghum, wheat, alfalfa and tomato all have characteristics. Values are coarse — maize is listed as not adapted to fine-textured soils, which is not true of clay loams — so a starting layer, cross-checked, not an answer |
| **NASA POWER** — agroclimatology | daily temperature, rainfall, humidity, wind, solar radiation for any point | **CC BY 4.0** | the site side, worldwide, per farm |
| **CHELSA v2.1** climatologies | 1 km monthly normals, worldwide; CMIP6 futures | **CC0** for the climatologies; the futures' licence still to check | site climate where a point series is not enough; projections |
| **ISRIC SoilGrids** | soil texture, pH, organic carbon worldwide at 250 m | CC BY 4.0 | soil outside the US |
| **USDA SSURGO** | soil at field scale, US | public domain | already in `tools/soil_survey.py` |
| **DSSAT crop models** (CROPGRO genotype files) | per crop: cardinal temperatures of development and day-length response; per cultivar, phase lengths — simulated against a site's weather in `tools/dssat_crops.py` | **BSD-3-Clause** | **the food-crop side** for 22 CROPGRO crops and CERES maize; the other cereals' CERES models next |
| **FAO ECOCROP** | 1,710 crops: temperature, rainfall, pH, photoperiod, soil, killing temperature, season length — the closest thing to the whole list in one table | FAO's standard licence is **CC BY-NC-SA 3.0 IGO: non-commercial.** The `Recocrop` R package (GPL-3) carries the parameters, described as expert opinion | **do not redistribute** without FAO's permission; usable to *check* our values against. Asking FAO for a licence is a cheap, worthwhile letter |
| **WorldClim** | climate normals | reported as non-commercial | avoid; CHELSA covers it |
| **Fadón et al. 2020**, *Agronomy* 10:409 | chill and heat requirements of 531 stone-fruit cultivars, each with model, method, place and study | **CC BY 4.0** | **fruit chill**, in [chill-requirements.csv](chill-requirements.csv) and the advisor; apples, pears and blueberries still lack an open table |
| CITA Aragón, *Agroclimatic requirements of temperate fruit trees* (2025) | 143 cultivars, three chill models | CC BY-NC-ND 3.0 ES | not used |
| USDA GRIN-Global evaluation data | chill descriptors for a few crops (walnut, almond, some peach accessions) | public domain | sparse, and no bulk download; not used yet |
| FAO-56 (crop coefficients) | water demand by growth stage, rooting depth, allowable depletion | an FAO publication (same licence question); the values are published facts | needs a decision: cite and tabulate facts, or ask |
| USDA Salinity Laboratory (Maas–Hoffman) | salt-tolerance thresholds by crop | US government work | to verify |
| AGROVOC | crop names in 40+ languages | to verify | names, not conditions |

## What to build, in order, when this is picked up

**Steps 1–4 are built** (2026-10-08) and run on three Tennessee farms:
[site-match-tennessee.md](site-match-tennessee.md). The run's main finding is that USDA
PLANTS covers conservation, forage and timber plants well and food crops hardly at all,
and that its limits are guidance rather than limits.

1. **Resolve each scientific name to a PLANTS symbol.** The old checklist download link
   now serves the web application; the API's search, or the CC0 Darwin Core archive of
   PLANTS on Zenodo/GBIF, are the routes.
2. **`tools/plant_conditions.py`** — pull characteristics for the list into a table, with
   the source and date on every value.
3. **The site side for one point** — NASA POWER for a farm's coordinates → frost dates,
   frost-free days, growing degree days, chill hours, rainfall by month, solar radiation
   and day length by month; soil from the survey.
4. **The match** — each plant scored against the site, dimension by dimension, saying
   *which* condition rules a plant out rather than one opaque score.
5. **Then the hard parts** — variety rather than species, invasiveness by region, and the
   2050 version from climate projections.
