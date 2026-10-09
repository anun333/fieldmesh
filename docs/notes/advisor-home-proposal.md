<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Where the advisor lives — a proposal

**2026-10-08. A proposal, not a decision; nothing has moved.** The maintainer decides the three
questions at the end.

## The problem

`tools/advise.py LAT LON` now tells a farmer what to grow, when to sow, which fruit
cultivars get their chill, what to fix in the soil, what bees and livestock face, and what
changes by the 2050s. That is layer 3 — the spec's *decision support: agronomic models,
forecasting, simulation* (v0 "Layers above") — and it is sitting inside layer zero, whose
first line says it "ships no end-user features". Nobody decided this; it accreted, one
useful tool at a time, from the plant-conditions plan. Three things now show the cost:

1. **Layer zero's language packs are mostly the advisor's.** 89 of the 177 strings in
   `sdk/packs/*.json` are `advise.*`. A translator who volunteers for layer zero is asked
   to translate a crop report; a release of layer zero is held by a sentence about
   paraguayos.
2. **The licences are muddled.** The advisor's code carries the SDK's Apache-2.0 headers
   in `tools/`; its data sits in `docs/notes/` beside the CC-BY spec under five licences
   (CC0, CC BY 4.0, BSD-3, the studies GloBI cites); and if it is ever run as a service, the
   reference server's AGPL reasoning (keep hosted improvements open) applies to it at least
   as much as to the server.
3. **It does not meet the bar the spec sets for layer 3.** v0 asks that layer-3 models be
   "versioned and calibrated per site; confidence shown; suspect and stuck readings
   excluded". The advisor stamps no model or data version on its report, shows confidence
   only as "8 years in 10", and reads no farm's own readings at all yet.

## What would move

| moves (the advisor) | stays (layer zero and its validation) |
| --- | --- |
| `advise.py`, `plant_match.py`, `site_profile.py`, `dssat_crops.py`, `plant_conditions.py`, `globi_bees.py`, `interactions.py`, `chill_requirements.py`, `tunnel_gain.py`, and their tests | `ismn_*.py`, `q5_encoding.py`, `packs.py`, everything in `sdk/`, `server/`, `sim/` |
| the data: `plant-list.csv`, `plant-characteristics-usda.csv`, `crop-parameters-dssat.csv` (+ its licence), `plant-bees-globi*.{csv,txt}`, `interactions.csv`, `chill-requirements.csv`, the animal/fertilizer/nursery/structure lists | the spec, and notes about layer zero (siting, spikes, Q-notes, validation) |
| the `advise.*` pack strings, into the module's own pack | the `enum.`, `term.`, `unit.`, `check.`, `siting.` strings |
| the plan and results notes (`plant-conditions.md`, `site-match-tennessee.md`, `hoop-houses.md`, …) | |

`soil_survey.py` is used by both: layer zero's flatline thresholds (Q24) and the
advisor's site profile. It stays in layer zero's `tools/` and the advisor imports it —
dependencies point down, as v0 requires; layer zero never imports the advisor.

## Options

| | where | for | against |
| --- | --- | --- | --- |
| **A** | stay in `tools/` (today) | no work | contradicts layer zero's scope; packs and licences stay mixed; nothing enforces "dependencies point down" |
| **B** | **`modules/advise/` in this repository**, with its own README, LICENSE, pack, data manifest and tests in `make test` | one CI, one checkout, history kept; the move is mechanical; an import check in CI can enforce the direction | the repository grows; a module's release is still tied to the repository's |
| **C** | a separate repository, `librefarm-advise` | the cleanest boundary; its own releases, licence and contributors; layer zero's repo returns to its scope | two CIs; cross-repo changes (a pack format change) need two PRs; premature while there is one maintainer |

**Recommendation: B now, C when the advisor has a release cadence or a contributor of its
own.** B fixes the scope, pack and licence problems at the cost of a few `git mv`s, and
leaves the C split as a later `git subtree split` with history intact.

## What B would add beyond the move

- **A module pack.** The pack format already namespaces by prefix; the module ships
  `modules/advise/packs/{en,es}.json` holding `advise.*`, and `i18n` would merge module packs
  over the base at load. `make packs` checks both.
- **A data manifest** (`modules/advise/data/MANIFEST.csv`): per file its source, licence,
  retrieval date and checksum, replacing the prose table in `LICENSING.md`.
- **A version stamp on every report**: the module version, the data manifest's hash and
  the DSSAT commit, so a report can be reproduced and a changed recommendation explained —
  the spec's "models versioned".
- **An import check** in CI: nothing under `sdk/`, `server/` or `sim/` may import from
  `modules/`.
- **Offline.** The advisor fetches NASA POWER, the soil survey, PLANTS and GloBI at run
  time (cached). Layer 4 must work offline, so the module should also be able to run from a
  pre-fetched regional bundle; that is a later step, noted so the layout leaves room for it.

## Decisions for the maintainer

1. **Where:** A, B or C.
2. **Licence for the module's code:** Apache-2.0 (like the SDK — easiest to embed in an
   app) or AGPL-3.0 (like the reference server — keeps a hosted advisor's improvements
   open). The data keeps its sources' licences either way.
3. **Name:** `advise` (what it does), or a name for the layer-3 family it starts
   (`decide`, `plan`).
