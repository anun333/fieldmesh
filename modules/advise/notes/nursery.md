<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Nursery: baby trees, transplants and other starts

**2026-10-08. A plan, saved for later — nothing here is built yet.** The fourth companion
to [plant-conditions.md](plant-conditions.md). A nursery sells the plants on the other
lists young: bare-root and container tree seedlings for forestry and erosion work,
grafted fruit trees, live stakes, vegetable and flower transplants, crowns, bulbs, sod and
seed. [nursery-list.csv](../data/nursery-list.csv) has 22 item types, each with examples from the
plant list, how it is propagated, how it is sold, its season, and what to watch.

## What is different about growing starts

| dimension | the nursery side | the site side |
| --- | --- | --- |
| **Propagation** | seed, cuttings (hardwood, softwood), grafting and budding, layering, division, tissue culture — USDA PLANTS records which methods work per species | skills, mist bench, greenhouse |
| **Dormancy** | cold stratification or scarification before seed will germinate — a USDA PLANTS field, and in detail per woody species in the *Woody Plant Seed Manual* | a cooler, or sowing in autumn to let winter do it |
| **Light** | seedlings and transplants are judged by daily light; some flower only at certain day lengths | greenhouse or shade house; the sunlight dimension, under cover |
| **Heat and cold** | root zones in black containers overheat in summer and freeze in winter, sooner than ground-planted roots | container placement, shade cloth, overwintering |
| **Water** | small containers need water daily and lose nutrients in the runoff | reliable water; capture of runoff — a sensor and fertilizer question fieldmesh already covers |
| **Time to saleable** | weeks for transplants, one or two years for bare-root seedlings, more for grafted and container trees | cash flow |
| **Season** | bare-root stock is lifted and planted dormant; transplants follow spring and autumn | the climate's calendar |

## The rules

Nursery stock moves plants between farms, and with them pests and disease, so it is
regulated in ways the rest of a farm is not:

- **A nursery licence and inspection** from the state department of agriculture, in most
  states; phytosanitary certificates to ship across state lines or abroad; quarantines on
  particular hosts (citrus, for citrus greening, is the familiar one).
- **Certified clean stock.** Seed potatoes, strawberry plants, citrus budwood, grape and
  fruit-tree material come through certification programs — USDA's National Clean Plant
  Network for fruit trees, grapes and berries — because saved stock accumulates viruses.
- **Patents and plant variety protection.** Many fruit varieties, rootstocks, berries and
  seed varieties are patented or PVP-protected, and some are trademarked "club" varieties;
  propagating them without a licence is infringement, even from a plant you own.
- **Seed laws** for selling seed: labelling, germination testing.

## Sources

| source | gives | licence |
| --- | --- | --- |
| USDA PLANTS | propagation methods, cold stratification, seedling vigour, seeds per pound, commercial availability, nursery-stock product | CC0 |
| USDA FS *Woody Plant Seed Manual* (Agriculture Handbook 727) | seed collection, storage, dormancy and germination for woody species | US government work |
| USDA FS *Nursery Manual for Native Plants* (Agriculture Handbook 730) | how to run a native-plant nursery | US government work |
| USDA GRIN | germplasm and accepted names | US government work |
| National Clean Plant Network; state certification programs | clean stock | — |
| USPTO plant patents; USDA PVP Office | what may not be propagated without a licence | public records |

## Build order

1. Pull the propagation fields from USDA PLANTS with the rest of the plant characteristics.
2. A propagation calendar for a farm: when to sow, stratify, take cuttings, graft, lift.
3. A check for protected varieties before anything is propagated for sale. *Built 2026-10-09 for
   Plant Variety Protection:* [protected_varieties.py](../protected_varieties.py) reads the
   PVP Office's monthly Application Status Report (every application since 1970: 18,327
   rows, 8,955 certificates issued, 983 pending) and says whether a variety is protected,
   provisionally protected (pending: the Act protects from the date of application), or not
   under PVP. Kizuri apple: protected to 2047. Plant patents are not checked — fruit trees,
   berries and plants propagated from cuttings are usually patented rather than
   certificated (Honeycrisp was, until 2008), and the patent office serves plant patents as
   scanned images — so "not found" is never "free to propagate", and the tool says so.
