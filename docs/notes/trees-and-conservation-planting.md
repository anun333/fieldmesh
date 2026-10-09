<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Tree farms, and planting against erosion

**2026-10-08. A plan, saved for later — nothing here is built yet.** The third companion
to [plant-conditions.md](plant-conditions.md) and
[animals-bees-and-inputs.md](animals-bees-and-inputs.md). The species are in
[plant-list.csv](plant-list.csv), categories `timber`, `Christmas tree`, `biomass`,
`syrup`, `forest farming`, `erosion: …` and `invasive: do not plant (US)`.

## Tree farms

**What makes trees different is the harvest date.** A Christmas tree is cut after a few
years, coppiced willow and poplar every few, pulpwood after one or two decades, hardwood
sawtimber and veneer after many decades — typical rotations vary by region and product,
and are to be sourced per species. A tree planted now must suit the climate of the decade
it is cut in, not the one it is planted in. So for trees the climate-*trend* dimension
moves from interesting to decisive:

- `~/dev/climate-analysis` already projects the Mid-South to 2060;
- the USFS **Climate Change Tree Atlas** models current and future suitable habitat for
  125 eastern US species on a 20 km grid;
- the USFS **Seedlot Selection Tool** matches a planting site's *future* climate to the
  *current* climate of seed sources — the right method, whether or not we use the tool;
- CHELSA's CMIP6 projections give the same anywhere.

| dimension | the tree side | the site side |
| --- | --- | --- |
| **Product** | lumber, veneer, pulpwood, posts, Christmas tree, naval stores, nursery stock — all USDA PLANTS fields; coppice potential, growth rate, lifespan, height at 20 years likewise | markets within hauling distance |
| **Site productivity** | site index: height reached at a base age, by soil and climate | soil survey; USFS Forest Inventory and Analysis plots nearby show what actually grows |
| **Climate at harvest** | the species' climate envelope | projections, above |
| **Pests and disease** | known threats | which are present or arriving. Fraser fir root rot on wet soils; chestnut blight; emerald ash borer (why ash is not on the list); hemlock woolly adelgid; southern pine beetle |
| **Fire, wind, ice** | tolerance | exposure |
| **Invasiveness** | — | Paulownia is on the list as timber and is **invasive in the eastern US**; black locust is invasive in Europe; leucaena on many tropical islands |

**Income while the trees grow** is the usual obstacle, and it is where trees mix with the
other lists: alley cropping (pecan or walnut rows with crops between), silvopasture (pines
with cattle or sheep — the animal list), forest farming under the canopy (ginseng,
goldenseal, ramps, black cohosh; shiitake on oak logs, a fungus and not on the plant
list), maple and birch syrup, Christmas trees as the quicker return. Carbon credits and
USDA cost-share for forest stewardship exist and have rules to look into.

## Planting against erosion

**Erosion can be estimated before anything is planted.** The USDA's Revised Universal Soil
Loss Equation multiplies five factors: soil loss = **R** (rainfall erosivity) × **K** (soil
erodibility) × **LS** (slope length and steepness) × **C** (cover) × **P** (practice).

| factor | where it comes from |
| --- | --- |
| R | rainfall intensity — US maps; elsewhere global erosivity datasets (licence to check) |
| K, and T (the tolerable loss) | the soil survey: SSURGO carries both, so `tools/soil_survey.py` can add them in one query |
| LS | elevation — USGS 3DEP (public domain) in the US; Copernicus DEM worldwide (licence to check) |
| **C and P** | **what is planted, and how** — the part a farmer controls |

So the useful output is a map of where on a farm R × K × LS is high, and which plantings
bring C and P down there.

| purpose | NRCS practice (to verify codes) | from the list |
| --- | --- | --- |
| streambanks | Riparian Forest Buffer (391); Streambank and Shoreline Protection (580) | willows and dogwoods as live stakes, buttonbush, alders, river birch, sycamore, sedges, rushes |
| field edges and runoff | Filter Strip (393); Field Border (386) | switchgrass, big bluestem, wildryes |
| channels | Grassed Waterway (412) | sod-forming grasses: creeping red fescue, western wheatgrass, buffalograss |
| wind | Windbreak/Shelterbelt (380); Hedgerow Planting (422) | eastern redcedar, Norway spruce, bur oak, hackberry, plums, chokecherry, buffaloberry |
| slopes | Contour Buffer Strips (332); Vegetative Barrier (601); Critical Area Planting (342) | vetiver hedges, switchgrass, fragrant sumac, coralberry |
| dunes and shores | — | American beachgrass, sea oats, bitter panicum, saltmeadow cordgrass, beach plum, bayberry |
| arid and saline ground | — | fourwing saltbush, big sagebrush |
| tropical slopes | contour hedgerows of leguminous trees ("SALT", the Philippines) | leucaena, gliricidia, calliandra, vetiver, napier grass |

**What to look up for each species** — USDA PLANTS has most of it: root depth; vegetative
spread rate (rhizomes knit soil); anaerobic tolerance (streambanks flood); *propagated by
cuttings* (willows and dogwoods can be cut as stakes and pushed into a bank); resprout
ability and coppice potential (recovery after floods or browsing); nitrogen fixation
(alders, buffaloberry, New Jersey tea, false indigo).

**Plantings that also yield.** Hedgerows of elderberry, aronia, plums and hazelnut hold
soil and produce fruit and nuts; windbreaks shelter livestock in cold wind and bees in
spring; riparian buffers catch manure runoff before it reaches water — where the
fertilizer list's phosphorus warning ends up.

## Do not plant

Some of the worst invasions in the United States were planted on purpose, for erosion
control or forage: **kudzu, crownvetch, sericea lespedeza, multiflora rose, autumn olive,
Russian olive, Japanese honeysuckle, Chinese privet, saltcedar, giant reed, cogongrass,
weeping lovegrass.** They are on the list, marked, so a recommender recognises them by
name and refuses them rather than not knowing them at all. Goats are one of the better
tools for clearing several of them — a use for the animal list.

Invasiveness is **regional**, so the flag cannot be a property of the species alone. False
indigo bush is native and useful in the eastern US and invasive in Europe; smooth
cordgrass is native on the Atlantic coast and invasive on the Pacific. The US flag comes
from USDA PLANTS' noxious and invasive status by state; worldwide, from GRIIS.

## Sources

| source | gives | licence |
| --- | --- | --- |
| USDA PLANTS characteristics | product fields, growth, roots, spread, propagation, flood tolerance, invasive status (US) | CC0 |
| NRCS conservation practice standards; Plant Materials Program guides | what to plant for each purpose, by region | US government work |
| USFS *Silvics of North America* (Agriculture Handbook 654) | climate, soils and growth of North American trees | US government work |
| USFS Forest Inventory and Analysis | measured tree growth on plots nationwide | US government work |
| USFS Climate Change Tree Atlas | current and future habitat, 125 eastern species | federal; terms not found |
| USFS Seedlot Selection Tool | method: seed source matched to future climate | a tool |
| SSURGO; USGS 3DEP | K and T factors; slope | public domain |
| World Agroforestry's Agroforestree Database | 670 agroforestry species, worldwide | **all rights reserved** — reference only |
| GRIIS | introduced and invasive species by country | to check |

## Build order

1. Add K and T to the `tools/soil_survey.py` query; slope from elevation.
2. An erosion-risk map per farm field: R × K × LS, against T.
3. Plantings per purpose, filtered by the site's conditions and by regional invasiveness.
4. For trees, check every recommendation against the climate of its harvest decade. The
   machinery now exists: `tools/advise.py --warm` re-runs the whole match on the site's
   weather shifted to a later decade ([site-match-tennessee.md](site-match-tennessee.md),
   "The 2050s"; +1.0 °C for the 2050s and about +1.3 °C for the 2060s at the Tennessee
   farms, from `~/dev/climate-analysis`). It is a uniform shift: species limited by summer
   nights or by drought need the seasonal and variability changes a CMIP6 downscale gives.
   For fruit trees, chill is now checked by cultivar for stone fruit, apples and pears, with
   bloom date and frost after bloom, and the 2050s run reports how each moves.
