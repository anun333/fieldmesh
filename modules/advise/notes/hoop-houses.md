<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Hoop houses and other cover

**2026-10-08.** A companion to [plant-conditions.md](plant-conditions.md). A hoop house —
a high tunnel — is **a second site inside the farm**, with its own climate. It is also the
place where librefarm's sensors pay off fastest, because a closed tunnel on a sunny day
can cook a crop in an afternoon, and an open one on a clear night can freeze it.
[structures-list.csv](../data/structures-list.csv) lists ten kinds of cover, from floating row
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
exactly the ones PLANTS does not cover. Since then the DSSAT crop models cover tomato,
pepper, cabbage and the beans in the open ([site-match-tennessee.md](site-match-tennessee.md));
running them under a tunnel's measured climate is the natural next step once a tunnel is
instrumented.

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
a tunnel is instrumented, and `modules/advise/tunnel_gain.py` computes them from two `time,value`
series (inside air, outside air):

    python3 modules/advise/tunnel_gain.py inside.csv outside.csv --limit-c 35

It bins each night's gain by how cold the outside night was, hands `plant_match.py` the
10th percentile of the gain on the coldest nights (below −5 °C, or below 0 °C if a winter
had none) — so the figure errs cold, which is the safe side for a frost verdict — and
reports the inside and outside frost-free seasons and the hours above the crop's limit.

**Tested against the virtual farm, not yet against a tunnel.** sim/physics.py now has a
`Tunnel`: inside air relaxing toward the outside plus trapped sun by day and the soil's
stored heat by night, a night gain that falls from 3 °C on a mild night to 1 °C on a clear
night at −5 °C, and sides that go up at 27 °C. A simulated year, sampled hourly the way a
logger would, gives back:

| outside night | nights | inside warmer by (median) |
| --- | ---: | ---: |
| below −5 °C | 111 | +1.1 °C |
| −5 to 0 °C | 54 | +1.7 °C |
| 0 to 5 °C | 50 | +2.7 °C |
| above 5 °C | 151 | +3.1 °C |

— the gain the physics was given, recovered without being told it, with
`--winter-gain-f 2.0` for the matcher and a frost-free season 23 days longer inside. The
same tunnel with the sides never opened spends 507 hours above 35 °C; vented, none.
These numbers are the model's, not a tunnel's: what the test proves is that the tool reads
a gain correctly, and what it cannot prove is what a real tunnel's gain is. The first
instrumented tunnel replaces the table. (The Harrow Bend scenario's own hoop-house sensor
read a flat outside + 6 °C until 2026-10-09; it now reads this model, and the simulator's
tests all pass with it.)

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
