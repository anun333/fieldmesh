<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Hoop houses and other cover

**2026-10-08.** A companion to [plant-conditions.md](plant-conditions.md). A hoop house —
a high tunnel — is **a second site inside the farm**, with its own climate. It is also the
place where librefarm's sensors pay off fastest, because a closed tunnel on a sunny day
can cook a crop in an afternoon, and an open one on a clear night can freeze it.
[structures-list.csv](structures-list.csv) lists ten kinds of cover, from floating row
cover to heated greenhouses, and the livestock versions: hoop barns and mobile poultry
houses.

## What a high tunnel changes

| dimension | effect | how sure |
| --- | --- | --- |
| season | adds roughly **two to four weeks** at each end | the figure extension services give |
| winter nights | warmer, by an amount that varies by tunnel, cover and night; a row cover inside adds about another 1.5 degrees on average, more on the coldest nights | **measure it** — see below |
| rain | none: **everything must be irrigated** | physics |
| wind | cut | physics |
| light | most, not all, gets through the film; diffused | by film |
| heat by day | trapped — overheating within hours if the sides stay shut | the main risk |
| soil salts | build up, because no rain leaches them | measurable: the soil survey's EC, a soil test, or an EC-reading probe |
| pests and disease | fewer rain-splashed leaf diseases; more mites, aphids and powdery mildew | |
| pollination | bees are shut out; crops that need them need a hive inside (bumble bees are the usual greenhouse pollinator) or hand pollination | |

**Cost-share.** NRCS pays for high tunnels through EQIP, as conservation practice 325,
"High Tunnel System", offered in every state; payment caps are set by each state.

## What the matcher says

`plant_match.py --cover high-tunnel` matches a site as a crop under a tunnel sees it,
changed only as far as is defensible: the season lengthened by two weeks at each end,
rainfall dropped (irrigated), and the winter low left as it is outside unless a measured
gain is given (`--winter-gain-f`). Only what is grown under cover is judged — the first
run happily put bur oak in a hoop house.

At McAllister Farm, of the 253 plants that are grown under cover, **193 have no USDA
PLANTS characteristics** — tomato, lettuce, spinach, peppers, potato, beans, peas,
ranunculus, anemone, lisianthus among them. Only a handful change verdict (eggplant,
claytonia, blueberry, rosemary). The machinery is right; the crops tunnels exist for are
exactly the ones PLANTS does not cover. That is the second independent argument, after
[site-match-tennessee.md](site-match-tennessee.md), for a food-crop source.

## Measure the tunnel instead

The figures above are general. What a grower needs is *their* tunnel's, and librefarm
already has everything needed to measure it: an air temperature and humidity sensor
inside, one outside, a soil probe inside.

| question | measured as |
| --- | --- |
| how much warmer on winter nights | the inside-minus-outside nightly minimum, by month and by outside minimum — it shrinks on clear, still nights |
| how much longer a season | inside frost dates against outside, from the same pair |
| how often it overheats | hours above a crop's limit, and how fast it climbs after sunrise with the sides shut |
| whether salt is building | soil EC over the seasons, against outside |
| disease pressure | hours of high humidity and condensation |

The first three are what `--winter-gain-f` and the season extension should come from once
a tunnel is instrumented. A tool to compute them from a paired inside/outside series is
the obvious next step; it needs a real tunnel's data to be worth calibrating.

**Alarms first, automation later.** Overheating and freezing are the fastest failures on a
farm, so a tunnel is the strongest case for layer 1's alerting. Opening and closing roll-up
sides by motor is a *command*, and v0.1 defers commands until a season of evidence on the
observation path — deliberately, because commands carry the liability. A tunnel is likely
the first place a farmer will ask for them.

## Siting a tunnel

The site profile already carries what siting needs: slope and drainage from the soil
survey (a tunnel on a wet or steep spot is a tunnel full of water or sliding), day length
and solar radiation by month (winter light decides what will grow in January), and the
wind and snow a frame has to bear — the last two not yet in the profile.

## Animals under cover

Hoop barns — the same frame with a fabric roof and deep bedding — house finishing hogs,
cattle on winter feed, sheep and goats at a fraction of a barn's cost, and the bedding
becomes compost: the fertilizer list's manure, already composting. Mobile poultry houses
follow cattle across pasture, which is one of the combinations on the interactions list.
Both have the tunnel's main risk, heat; the site profile's heat-stress estimate applies.
