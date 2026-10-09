<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Animals, bees, flowers and fertilizers — and what mixes with what

**2026-10-08. A plan, saved for later — nothing here is built yet.** The companion to
[plant-conditions.md](plant-conditions.md). The same idea, extended: every living thing
on a farm, and every input, has conditions it does best in, and the farm has conditions
librefarm can measure or look up. And they interact — some combinations help each other,
some harm each other — so the useful answer is not a list of things that suit the site
but a set that suits the site *and each other*.

| list | what is in it |
| --- | --- |
| [plant-list.csv](plant-list.csv) | 380 plants in 88 families — now including **cut flowers**, **edible flowers** and **bee forage** trees, shrubs and herbs |
| [animal-list.csv](animal-list.csv) | 99 entries — **bees** (honey bee races, stingless bees, bumble bees, managed solitary bees, wild crop specialists), **meat, egg and dairy** animals by breed, waterfowl, camelids, aquaculture, insects, guardian animals |
| [fertilizer-list.csv](fertilizer-list.csv) | 60 — synthetic N, P and K, liming and pH, micronutrients, **manures by animal**, organic fertilizers, and **rhizobia inoculants matched to legume groups** |

The animal list's last column is what each breed is *commonly described* as suited to —
"heat-tolerant", "cold-hardy", "parasite-resistant" — and is marked to verify. Breed
claims are where folklore lives.

## Bees

What decides which bee, and whether bees thrive at all:

- **Climate.** Winter length and cold decide which honey bee race overwinters well — the
  frugal Carniolan and dark European bees for long winters, the Italian for warm ones;
  stingless bees only where it does not freeze. Daily minimum temperatures (NASA POWER)
  give the site side.
- **Forage through the whole season.** A colony needs something in flower from first
  flight to last. USDA PLANTS carries a **bloom period** for each plant, so the plant
  list can be laid out as a bloom calendar for a farm and its gaps found — the early
  spring and late summer "hunger gaps" are the usual ones.
- **What the crops need.** Crops range from needing no pollinator (wheat, rice, maize) to
  depending on one entirely (most cucurbits, kiwifruit, almonds). USDA's 2017 *Attractiveness
  of Agricultural Crops to Pollinating Bees* rates US crops for honey bees, bumble bees and
  solitary bees, nectar and pollen.
- **Nesting.** Most native bees nest in the ground or in hollow stems. Squash bees nest in
  the soil under the very plants they pollinate, so deep tillage there destroys them; mason
  bees need tubes or stems; alkali bees need bare alkaline ground.
- **Pesticides and mowing.** The largest conflicts are with the farm's own practices —
  insecticide during bloom, and mowing a flowering cover crop while bees are on it.

## Flowers

Three roles, all already in the plant list:

- **A crop.** Cut flowers have the same soil, water, climate and light needs as any crop,
  and several are ruled by **day length** — chrysanthemums flower as days shorten — which
  is why sunlight is its own dimension in the plant plan.
- **Bee and beneficial-insect forage.** Flowering strips feed pollinators and the insects
  that eat crop pests.
- **Food.** Edible flowers, and crops whose flowers are eaten (squash blossoms, roselle).

## Meat, egg and dairy animals

What decides which animals, and which breeds:

| dimension | the animal side | the site side |
| --- | --- | --- |
| **Heat** | heat-stress threshold, commonly expressed as a temperature–humidity index (THI); for dairy cows the commonly cited onset is around 68–72 | daily temperature and humidity from NASA POWER → THI, and hours above it |
| **Cold** | cold hardiness; housing needed | daily minima, wind |
| **Feed** | dry-matter intake per head; grazer, browser or omnivore | pasture productivity from the forage plants on the list, rainfall and soil; feed bought in |
| **Water** | litres per head per day, rising with heat and lactation | wells, ponds, rainfall |
| **Parasites and disease** | resistance: hair sheep and Kiko goats to worms; N'Dama cattle and West African Dwarf goats to trypanosomiasis | warm, wet climates favour gut worms; tsetse zones; ticks |
| **Predators** | vulnerability | local predators; guardian animals |
| **Purpose** | meat, eggs, milk, fibre, draft, pest control | market, household |

## Fertilizers

What decides which fertilizer:

- **What the soil has.** pH, phosphorus, potassium, organic matter and cation exchange
  capacity — from a soil test first, the soil survey (`tools/soil_survey.py`, SoilGrids)
  second. pH decides whether lime or sulfur comes before anything else.
- **What the crop takes.** USDA PLANTS' fertility requirement, and nutrient removal per
  unit of yield.
- **The soil's texture.** Nitrate leaches through sand; split applications there.
- **Legumes and the right inoculant.** A legume fixes nitrogen only with its own group of
  rhizobia — soybean with *Bradyrhizobium japonicum*, alfalfa with *Sinorhizobium
  meliloti*, and so on; the list maps each inoculant to the legumes on the plant list.
- **The animals.** Manure is where the animal list feeds the plant list. Its nutrient
  content varies so widely that it should be tested, or taken from the NRCS tables.
- **Rules.** US organic certification (7 CFR 205) allows some inputs, restricts others —
  raw manure must be composted or applied 90 or 120 days before harvest — and prohibits
  synthetic nitrogen.

## What mixes with what

Represent each interaction as a record: **this** affects **that**, *for better or worse*,
*by what mechanism*, *under what condition*, *according to which source*. Species-level
interactions already exist in the open: GloBI (Global Biotic Interactions, CC BY 4.0) has
plant–pollinator and many other records. Farm-practice ones mostly do not, and would be
this project's contribution.

Well-known examples, each to be sourced before it is relied on:

| mixes well | mechanism |
| --- | --- |
| maize, beans and squash (the "three sisters") | the bean climbs the maize and fixes nitrogen; the squash shades out weeds |
| a legume cover crop before a cereal | nitrogen left in the soil |
| cattle with sheep or goats | they prefer different plants, and mostly do not share gut parasites, so grazing together dilutes each other's worm burden |
| poultry following cattle | they scratch apart dung pats and eat fly larvae |
| ducks in rice; fish in rice | pest and weed control; manure for the crop |
| pigs in woodland | finishing on acorns and nuts |
| donkeys, llamas or guardian dogs with sheep and goats | protection from canids |
| bees with orchards, cucurbits and almonds; clover, buckwheat and phacelia for the bees | pollination; forage |
| black soldier fly on manure, feeding poultry | waste becomes feed, and frass becomes fertilizer |
| silkworms and mulberry | the only food silkworms eat |

| mixes badly | mechanism |
| --- | --- |
| insecticide or mowing during bloom, and bees | kills foragers |
| deep tillage and squash bees | destroys nests in the soil under the crop |
| chickens with turkeys | chickens carry blackhead (*Histomonas*), which kills turkeys |
| sheep and copper | sheep are poisoned by copper levels other livestock tolerate — feeds, minerals, orchard copper sprays |
| goats and young trees | they strip bark |
| black walnut, and tomatoes and their relatives; black walnut shavings and horses | juglone |
| wilted cherry and other *Prunus* leaves, and ruminants | cyanide |
| lush legume pasture (alfalfa, clover) and cattle | bloat — a USDA PLANTS field |
| acorns in quantity, and cattle or horses | tannin poisoning (pigs tolerate them) |
| waterfowl alongside chickens | a reservoir for avian influenza |
| *Bombus terrestris* outside its native range | invasive where introduced |
| poultry litter applied repeatedly | phosphorus builds up and runs off |
| fresh manure on food crops | pathogens — the organic rule's waiting interval exists for this |

**USDA PLANTS already links the lists.** Its characteristics include *Bloat*, *Toxicity*,
*Palatable Graze/Browse Animal*, *Nitrogen Fixation*, *Known Allelopath* and *Bloom
Period* — plant-to-animal, plant-to-plant and plant-to-bee facts, in the public domain, for
every plant it covers.

## Sources

| source | gives | licence |
| --- | --- | --- |
| USDA PLANTS characteristics | the plant side, plus the links above | CC0 |
| USDA, *Attractiveness of Agricultural Crops to Pollinating Bees* (2017) | crop × bee type, nectar and pollen, pollination need | US government work — to confirm |
| GloBI | species interactions, including plant–pollinator | CC BY 4.0 (credit the original datasets) |
| NRCS Agricultural Waste Management Field Handbook, chapter 4 | manure quantity and nutrients by animal | US government work |
| 7 CFR 205.601–606 | inputs allowed, restricted and prohibited in US organic production | US regulation, public domain |
| NASA POWER | temperature, humidity → THI; cold; rainfall | CC BY 4.0 |
| FAO DAD-IS | livestock breeds by country | **terms not found**; FAO's default is non-commercial — to check before any reuse |
| Klein et al. 2007 (*Proc. R. Soc. B*) | pollinator dependence of the world's crops | a paper — cite the figures |

## Build order, after the plant plan's

1. The **interaction records**, starting from the USDA PLANTS fields that already encode
   them, then GloBI for pollinators.
2. **Bloom calendars** for a farm's plants, with the hunger gaps marked.
3. **Heat stress** for a farm's animals from NASA POWER — hours above THI thresholds by month.
4. **Fertilizer** from soil test + crop demand + manure available, with the organic rules
   as a filter.
