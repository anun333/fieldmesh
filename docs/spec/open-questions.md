<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Open questions: every option

Companion to [v0.1](v0.1.md). Oct 7, 2026.

Each question lists **all** options considered, not just the two in the original draft, with the trade-off that decides between them and a recommendation. Recommendations are arguments, not conclusions — the point is that the reasoning is written down, so a later reversal is cheap and informed.

**Status legend**

| | Meaning |
| --- | --- |
| **Blocks v0** | A conformance test or node firmware cannot be written until this is decided |
| **Blocks commands** | Needed before the command contract is frozen, which v0.1 defers by a season |
| **Blocks third parties** | Needed before anyone outside the project ships a module or a driver |
| **Blocks the pilot** | Needed before data from a real farm is collected or shared |
| **Decided in v0.1** | Resolved in the spec; options recorded here so the decision can be revisited |

---

# Part A — Blocks v0

> **Q1 has been reclassified.** The decision to build against a simulated farm first ([VIRTUAL_FARM.md](../VIRTUAL_FARM.md)) moves the pilot farm off the development critical path. It is kept in this section because its timing constraint is unchanged and unforgiving, but it no longer gates the first release.
>
> **Q5 is now decided** (2026-10-07, on measurement) and no longer blocks anything. It is kept below with its full option table, because the two candidates the measurement eliminated were eliminated for reasons worth not re-litigating.

## Q1. Who is the first pilot farm, and what crop or livestock?

**Status: blocks the pilot and every reliability claim; no longer blocks the first release.** Code no longer waits on it. But a growing season is on the claims critical path and seasons do not reschedule: a decision in autumn 2026 buys a 2027 season, and a decision in spring 2027 costs a year. The simulated farm removes the pressure to pick badly — it does not remove the calendar.

| Option | For | Against |
| --- | --- | --- |
| University extension research plot | Instrumentation discipline, staff who log failures, publishable data, credibility with other farmers, existing grant channels | Not a working farm — equipment gets attention a real farm never gives it, so it under-tests neglect |
| University teaching farm | Diversified, tolerant of experiments, students as labour | Turnover; nobody owns the deployment over winter |
| A working diversified vegetable farm | The real case: neglect, dust, rodents, nobody reading dashboards | Tolerance for failure is low; a bad season costs them money and you their trust |
| Small livestock operation (stock water) | Water monitoring is read-only and high-value — a dry trough is an emergency, and detecting it is pure upside | Narrower data model exercise; less irrigation learning |
| Commercial greenhouse | Dense sensing, good connectivity, engaged operator | Good connectivity means store-and-forward is never tested |
| Co-op or community garden | Several users, natural multi-site and sharing test | Diffuse ownership; nobody to call when a node dies |
| Your own test bed only | Full control, fast iteration | Does not satisfy "one full growing season of field data" in any honest sense |

**A candidate list with sources is in [notes/pilot-candidates.md](../notes/pilot-candidates.md)**, weighted toward Middle Tennessee, with the funding route (Southern SARE on-farm grants, $15-20k precedents) and the national instrumented networks worth comparing against rather than installing on.

**One criterion is missing from the list below: distance to the nearest public reference station.** The drills measured that a feature with a single sensor cannot detect drift, bias or noise at all, and drift is the commonest real failure, so a free peer would be worth a great deal.

Checked rather than assumed. The NRCS AWDB REST API serves SCAN data with no token — five soil depths, hourly, QC-flagged, since 2003 — but the three Tennessee stations are **75 to 160 km** from every candidate site, which is too far to stand in for a probe on the feature. At that range it is good for setting range thresholds from twenty-three years of regional evidence rather than from guesswork, and not for cross-check.

What makes the criterion live is the **Tennessee Mesonet**: 95 stations, one per county, the same five depths, **five-minute cadence**, real-time and public, with half of them due operational by the end of 2026 — the same moment a pilot decision buys a 2027 season. Siting a pilot near one of those is worth real weight.

**Selection criteria that matter more than the category:** an existing water or irrigation pain the farm already loses money to; genuinely poor connectivity, because that is the hard case the spec is built around; one person on site who will actually report a failure; willingness to run a full season; and tolerance for losing the data if it goes wrong.

**Recommendation:** two sites, not one — an extension or university plot for discipline and credibility, plus one working diversified farm for the failures the plot will never produce. Pick the second for connectivity that is actually bad. The crop or livestock choice determines Q12, so decide them together.

## Q4. Unit system, and observed-property vocabulary

**Status: DECIDED 2026-10-07 — UCUM for units, and the layered vocabulary recommended
below.** Implemented as [sdk/vocab.py](../../sdk/vocab.py), which is now the only place
an observed-property URI is written down. Every URI was fetched and returned 200 on the
day of the decision, because a term nobody can resolve is free text with extra syntax.

Deciding it found a real defect rather than merely settling a preference. The
placeholders said `cf/soil_moisture_content`, and **`soil_moisture_content` is not a CF
standard name at any version of the table.** The nearest real CF names are mass-based
(`mass_content_of_water_in_soil`, kg m-2), so the plausible-looking guess pointed at the
wrong dimension. The volumetric quantity a soil probe reports is
`volume_fraction_of_condensed_water_in_soil`, canonical units `1` — which is exactly what
`cm3/cm3` is. A unit error wearing a credible URI is the failure mode this question was
really about, and we had already shipped one.

What landed, against checked CF table version 95 (2026-09-16):

| Measurand | Term | Source |
| --- | --- | --- |
| Soil water content | `volume_fraction_of_condensed_water_in_soil` | CF |
| Air temperature, relative humidity, soil temperature | the obvious CF names | CF |
| Field capacity, wilting point | `..._at_field_capacity`, `..._at_wilting_point` | CF |
| Battery voltage | `batteryVoltage` | ODM2 |
| Signal strength | `receivedSignalStrenghtIndication` | ODM2 |
| Trough fill fraction | `vessel_fill_fraction` | **local** |

One local term out of nine, and the reason is recorded rather than shrugged at: ODM2's
`waterLevel` is a **height in metres**, and what a float-regulated stock trough usefully
reports is how full it is — dimensionless, bounded, and the thing §4.2's thresholds are
expressed in. Declaring a fraction under a term defined as a length would have been the
same class of error as the placeholder. A test asserts the local-term list, so adding a
second one breaks the build and prompts the trip upstream.

### Q4a. Units

| Option | For | Against |
| --- | --- | --- |
| **UCUM** | SensorThings 1.1 says `unitOfMeasurement` values SHOULD follow UCUM; the 2.0 draft embeds units in SWE-Common, which also uses UCUM codes; grammar-based, so derived units compose (`cm3/cm3`, `kPa`, `Cel`); used by HL7 and SWE | Codes are not human-friendly; the grammar needs a library to validate properly |
| QUDT | Rich ontology, URIs, dimensional analysis, good for reasoning | Heavy; RDF toolchain; overkill for a node that reports kPa |
| UN/CEFACT Recommendation 20 | Used in trade and EDI, appears in some ag data exchange | Trade-shaped, not measurement-shaped; no grammar for derived units |
| OGC/OM unit URNs | Native to the older SWE stack | Effectively superseded; verbose |
| SI plus a curated local table | Simple, legible, no dependency | You have just invented a unit system, and nobody else can read your exports |
| Free strings | Zero effort | The failure this spec exists to prevent |

**Recommendation: UCUM.** It is not a preference — it is what both target versions of the standard already point at, which turns a decision into an alignment. Validate codes at datastream creation and reject anything that does not parse, because a unit that is wrong at declaration time is wrong for the life of the series.

### Q4b. Observed properties

The original draft paired this with AGROVOC. Worth separating: **AGROVOC is a multilingual thesaurus of agricultural concepts — crops, practices, pests, commodities — not a vocabulary of measurable physical properties.** It is the right tool for the records side and the wrong shape for "what this sensor measures".

| Option | Covers | For | Against |
| --- | --- | --- | --- |
| **CF Standard Names** | Physical and environmental measurands (`soil_moisture_content`, `air_temperature`, `wind_speed`) | The de facto vocabulary for environmental measurement; precise definitions including units and sign conventions; maintained | Climate/met-centric; thin on soil chemistry and anything agronomic |
| **ODM2 / CUAHSI variable names** | Hydrology, soil, water quality | Strong exactly where CF is thin; designed for sensor + sample data | Smaller community; less tooling |
| AGROVOC | Crops, management, pests, commodities | Multilingual (matters for the bilingual requirement in layer 4); FAO-maintained; SKOS | Not measurands; too coarse to identify what a sensor reports |
| QUDT QuantityKind | Quantity kinds | Pairs naturally with QUDT units | Only if you took QUDT for units |
| NERC P01/P06 (BODC) | Oceanography, some water quality | Extremely precise compound terms | Marine-shaped; forbidding to a farm |
| ICASA / AgMIP | Agronomic model variables | Right for anything feeding a crop model (layer 3) | Model-input shaped, not sensor shaped |
| farmOS quantity types | farmOS records | Native to the records side | Tiny; not URI-identified in a useful way |
| Your own registry with URIs | Everything | Always fits | Nobody else resolves your URIs; the interoperability principle fails quietly |

**Recommendation:** layer them by what they are for, rather than picking one.

- **CF Standard Names** for sensor measurands, **ODM2** for the soil and water terms CF lacks.
- **AGROVOC** for the records side — crops, treatments, practices — where its multilingualism is an asset.
- A local registry with resolvable URIs for genuine gaps, and publish the gaps upstream rather than accumulating private terms.

Whatever is chosen, the rule in v0.1 §3.4 stands: a URI, never free text.

## Q4c. The durable namespace for local vocabulary terms

**Status: blocks publication of the vocabulary; blocks nothing in code.** Raised by the
Q4 decision of 2026-10-07, which produced exactly one local term and therefore a
namespace to put it in.

`sdk/vocab.py` currently uses `https://anun333.github.io/librefarm/vocab/`. It does not
resolve, because the repository is private, and it is the wrong long-term answer anyway:
a vocabulary namespace is supposed to outlive its hosting, and that one is pinned to a
personal account name. Every URI changes if the project ever gets an organisation or a
domain — and changing a published identifier is the thing identifiers exist to avoid.

| Option | For | Against |
| --- | --- | --- |
| **w3id.org permanent identifier** | Purpose-built for exactly this: a stable URI that redirects to wherever hosting currently lives, so hosting can move and the identifier cannot. Free. Community-run, widely used for vocabularies | Requires a pull request to the w3id repository, which means the first outside interaction. Adds a redirect hop |
| A project domain | Fully self-owned; shortest URIs; obvious home for human-readable term pages | Costs money annually, forever, and a lapsed registration is worse than no domain — somebody else can serve your identifiers |
| GitHub Pages under an organisation | Free; resolves as soon as it is public; no third party in the path | Still pinned to one hosting provider and one account name; moves break the URIs |
| GitHub Pages under the personal account (today) | Zero work; already written down | Does not resolve while the repo is private, and bakes a username into every identifier |
| `urn:` namespace | Honest about not being resolvable | Resolves for nobody, which gives up the property that made CF and ODM2 worth choosing |
| Publish the gap upstream and own no namespace | Nothing to maintain; the right end state | Upstream acceptance is not on our schedule, and the term is needed now |

**Recommendation: w3id.org, and submit `vessel_fill_fraction` to ODM2 in parallel.** The
two are not alternatives — w3id is insurance for however long upstream takes, and if
ODM2 accepts the term the local one becomes a permanent redirect to theirs, which is
precisely the case w3id is designed for. Do it when the repository goes public, since a
redirect to a 404 helps nobody. Until then the single `LOCAL` constant in
[sdk/vocab.py](../../sdk/vocab.py) is the whole migration surface.

## Q21. What unit does a *raw* datastream declare?

**Status: blocks v0 — it is a §3.1 data-model question, not an implementation detail.**
Raised 2026-10-07 by pointing a third-party SensorThings client at the HTTP service and
looking at what it made of Harrow Bend.

The farm's raw soil-moisture datastreams declare `unit = cm3/cm3` and carry values like
`280`. The calibration then applies `a = 1/1000`, giving `0.280 cm3/cm3` on the derived
series. So the raw datastream declares a unit **it is not in**: it is in thousandths of
cm3/cm3, and the declaration says otherwise. This is the same class of error as the
`soil_moisture_content` placeholder that Q4 caught — a plausible-looking declaration
that no check could falsify — and it is the same raw-versus-derived confusion that
produced the 99.8% false-alarm rate in §4.2. Three findings, one root.

It surfaced through `observationType`. Serving the type inferred from a sample's Python
type made a scaled-integer raw series an `OM_CountObservation` *with* a unit, which is
self-contradictory — a count has no unit. That particular bug is fixed (the type now
follows the declaration), but the fix only moved the question: if a unit decides that
something is a measurement, the raw series' unit had better be true.

| Option | For | Against |
| --- | --- | --- |
| **Raw declares no unit (`null`)** | Honest: before calibration the number has no physical meaning, and §3.4 already allows a null unit for a quantity that has none. Keeps the scale factor where it belongs, in the calibration, which is the thing allowed to change | FROST-Server **rejects a Datastream with no `unitOfMeasurement`** — measured 2026-10-07, 400 — so a raw series could not be mirrored into the reference implementation. `observationType` also falls back to the value's type, and a scaled integer is not really a count either |
| Raw declares the scaled unit, e.g. `10*-3.cm3/cm3` | UCUM expresses it exactly, so the calibration becomes a pure unit conversion and the declaration is checkable | **The scale is a calibration property.** A recalibration that changes the scale would have to change the datastream's unit, and §3.1 declares the unit once and never changes it. This option is only safe if scale is frozen for the life of the series, which is a stronger promise than calibration makes |
| Raw declares the physical unit and a separate `raw_scale` field | Minimal change; the relationship is explicit and machine-readable | Invents a field the standard has nowhere to put, so it survives only in `properties` and no other implementation will honour it. Also still false: the declared unit is not the unit of the values |
| No raw datastream at all — calibrate at ingest | The question disappears, and so does a whole class of confusion | Destroys §3.2's reason for existing: the raw series is the record that lets a wrong calibration be corrected without losing data. Not an option |
| Raw declares a dimensionless `1` | True of an ADC count; parses as UCUM; satisfies FROST | Loses the information that these are thousandths of something, so nobody can reconstruct physical values from the raw series alone |

**Recommendation: `1`, with the scale recorded in the calibration where it already
lives.** It is the only option that is true of the values, parses as UCUM, keeps the
scale in the record that is allowed to change, and does not fail against the reference
implementation. `null` is more honest still, but a model that cannot round-trip through
FROST loses the conformance oracle this project has been checking itself against, and
that is too high a price for a shade of precision.

Whichever is chosen, §3.4's new clause applies and makes this falsifiable: the unit a
datastream declares must be consistent with the values it carries. Harrow Bend and
`sdk/fixtures.py` both need changing, which is why this is recorded rather than quietly
fixed — it changes the canonical farm.

## Q22. Does the maintenance vocabulary need a battery replacement?

**Status: blocks nothing; a small gap in §4.1 with a real consequence.** Raised 2026-10-08
by implementing §4.1's maintenance log.

§4.1 names four actions — cleaned, moved, replaced, recalibrated — and
[sdk/model.py](../../sdk/model.py)'s `MaintenanceAction` implements exactly those, because
a vocabulary that grows by whoever needs a word next is how a log becomes unqueryable.
Which immediately showed that one is missing.

**A battery replacement is a real field event on every node this project targets, and none
of the four covers it.** It is not `replaced` — the device was not replaced, its cell was.
The consequence is specific rather than tidy-minded: §4.3 makes battery voltage a
datastream, so a battery change produces a **step discontinuity** in a series that §4.2's
rate-of-change check is watching. Without a maintenance event to explain it, that step is
either a false alarm or, worse, a true alarm nobody can account for a season later. The
same argument covers a solar panel cleaned or a desiccant pack changed.

| Option | For | Against |
| --- | --- | --- |
| **Add `serviced` as a fifth action, with the detail in `note`** | One new term covers batteries, panels, desiccant and anything else routine; keeps the vocabulary small; the note carries what a human needs | "Serviced" is vague enough that it may absorb events that deserve their own term, which is how the vocabulary rots anyway |
| Add `battery_replaced` specifically | Exactly the event that interacts with §4.2 and §4.3; a rate check could consult it directly | Invites one term per consumable, and the list never closes |
| Leave the four and use `note` on `replaced` | No spec change | `replaced` then means two different things, and the queryability the enumeration exists for is lost for both |
| Let the vocabulary be open (free strings) | Never blocks a farmer | The failure §3.4 rejects for observed properties, re-made here. Two farms would spell the same action differently and neither could query the other's log |
| Treat it as a `Device` replacement — new device, new id | Honest if the whole node was swapped | Wrong for a cell change: the probe, its calibration and its siting history all continue, and forking the identity would break them |

**Recommendation: add `serviced`, and have §4.2's rate check consult the maintenance log
before flagging a step on a device datastream.** The second half is the point — the
vocabulary addition is cheap, but it is only worth anything if a check actually reads it.
That makes this a §4.2 change as much as a §4.1 one, which is why it is a question rather
than a patch.

## Q23. A rate-of-change limit that works at any sampling interval

**Status: blocks scoring against hourly data; affects every farm that samples slower
than every 15 minutes.** Raised 2026-10-08 while building `tools/ismn_score.py`.

§4.2's rate check allows a change of `max_rate_per_s × elapsed`. Harrow Bend's soil limit,
0.00015/s, was derived from drip irrigation at 15-minute sampling — about 0.135 per step,
which a real irrigation event (≈0.083) stays under. But the allowance grows with the gap.
At ISMN's hourly sampling it is **0.54 m³/m³ in one step**, nearly the whole physical range,
so a spike from 0.25 to 0.40 passes and the check can effectively never fire. A test now
asserts exactly that.

It is the `flat_n` trap reversed. `flat_n` was a count that meant different durations at
different sample rates; this is a rate whose allowed step means different things at
different gaps. What is physically bounded is not the rate but the **size of one jump**:
an irrigation event adds about 0.08 however long you wait to look.

| Option | For | Against |
| --- | --- | --- |
| **Add `max_step`: a jump larger than any single legitimate event is implausible regardless of the gap; keep the rate for short gaps** | Bounded by physics, independent of sampling; catches the hourly spike | A long gap *can* legitimately hold more than one event — a 50 mm storm over six hours can raise soil water by more than one irrigation does — so the cap must grow with the gap past some point, or the check turns a storm into an alarm |
| `max_step` that grows sub-linearly, e.g. capped at the infiltration a storm of the gap's length could deliver | Physically argued at every gap | Needs a rainfall bound per site, which is climate data the farm may not have |
| Make the rate limit depend on the declared sample interval | One number per series, simple | Couples the threshold to sampling again — the exact mistake `flat_seconds` was introduced to undo |
| Leave it; document that rate is for fast-sampled series | No change | Every hourly logger, and the whole of ISMN, gets a check that cannot fire while appearing to run |

**Measured since — and it changes the recommendation.** One hourly step in the top 20 cm,
19 humid-subtropical SCAN stations, 8 million good readings, in m³/m³:

| | median | 90th | 99th | 99.9th | 99.99th |
| --- | --- | --- | --- | --- | --- |
| good | 0.001 | 0.005 | 0.016 | 0.069 | 0.167 |
| ISMN spike (D06) | 0.006 | 0.016 | 0.072 | 0.225 | 0.362 |
| ISMN jump (D07, D08) | 0.074 | 0.167 | 0.337 | 0.524 | 0.856 |

The distributions overlap. Healthy soil legitimately rises 0.17 in an hour after heavy rain
on sand, which is more than half of ISMN's jumps. And readings flagged as spikes mostly have
*small* steps: ISMN's detector is spectrum-based and marks the region around an excursion,
not the jump. **A step-size cap cannot reproduce it** at any false-alarm rate a farmer would
accept.

**Measured: the shape works, and ISMN's spike flag is the wrong yardstick.** Candidate
detectors on every SCAN probe in the top 21 cm — 1,797 probes, 11,520 probe-years — in
[notes/spikes-and-jumps.md](../notes/spikes-and-jumps.md):

| detector | ISMN negative jumps caught | flags on readings ISMN rates good, per probe-year | probes never flagged | at 3-hourly sampling |
| --- | --- | --- | --- | --- |
| **spike: out by ≥ 0.05 and back within one sample** | 21% | 0.46 | 77% | 0.34 |
| **fall faster than 0.05 per hour** | 61% | 1.21 | 56% | 0.16 |
| rise faster than 0.17 per hour | 5% (12% of positive jumps) | 0.40 | 55% | 0.00 — blind |
| the rate check today | 0 of 1,849 in Tennessee | — | — | — |

Three findings decide it. ISMN's D06 "spike" sits on steps with a median of 0.005 — it is a
relative test firing on noise in dry soil — so agreement with it is not a goal. The shape
check's flags on readings ISMN rates good concentrate on a few probes (85% from the worst
5%), and those are plainly broken: Spickard's three probes flipping between two levels
hour by hour, Goshute swinging 0.3, a dead sensor at Orchard Range reading 0.000, and
McAllister Farm's new 2026 digital probe. On the median probe it never fires, and at
coarser sampling it fires less, not more. And soil empties more slowly than it fills —
healthy falls reach 0.032 at the 99.9th percentile against 0.073 for rises — so a cap on
falls catches most of ISMN's negative jumps where a cap on rises cannot tell a fault from
rain.

**Recommendation, measured:** for soil water, replace `max_rate_per_s` with

1. a **shape spike** check at 0.05 m³/m³ raising `rate_exceeded` — judged one reading late,
   because it needs the reading after: when reading *n + 1* arrives, an assertion on
   reading *n* is appended, the pattern the siting check already uses;
2. a **cap on falls** of 0.05 m³/m³ per hour, scaling with the gap up to three hours,
   raising `suspect`, because a wetting front draining at 5 cm can legitimately exceed it;
3. **no rise cap** from rate; a per-step backstop is optional, and its behaviour at coarse
   sampling is unmeasured.

Keep `max_rate_per_s` itself for measurands where a rate really is the physics. Open
beside this: whether thresholds relative to a probe's own range beat absolute ones in very
sandy or very clayey soil.

## Q24. Flatline thresholds that know how deep the probe is

**Status: causes false alarms on every deep probe today.** Raised 2026-10-08 by scoring
§4.2 against 2.8 million real readings from the three Tennessee SCAN stations in ISMN
(see [notes/ismn-scoring.md](../notes/ismn-scoring.md)).

§4.2 already says a flatline threshold must exceed the *quantisation dwell* — how long a
healthy probe legitimately repeats one value. Harrow Bend's 18 hours was set from a
shallow probe's overnight dwell (about 8 h). Real data says the dwell grows with depth,
because water moves more slowly the deeper you go. These are the longest runs of one
identical value among readings **ISMN itself rates good**:

| depth | 99.9th percentile | longest | share of runs ≥ 18 h |
| --- | --- | --- | --- |
| 5 cm | 7 h | 105 h | 0.00% |
| 10 cm | 8 h | 103 h | 0.00% |
| 20 cm | 9 h | 29 h | 0.01% |
| 51 cm | 21 h | 157 h | 0.15% |
| 1.02 m | 63 h | 351 h | 0.51% |

So 18 hours is right for the top 20 cm and wrong below it. Across the whole Tennessee
record our checks raised `stuck` on 33,369 readings ISMN calls good, and almost all of
them are on the deep probes. The dwell grows roughly exponentially with depth — an e-folding
of about 0.44 m between 5 cm and 1 m — the same physics that damps the daily temperature
wave the siting check reads.

| Option | For | Against |
| --- | --- | --- |
| **A depth-scaled default from the installation record** (§4.1 now has `depth_m`), fitted to the table above | Physically argued; works from the first day; uses a record that exists for exactly this kind of reason | One soil's numbers; a sandy soil drains faster and a clay slower, so the curve is a default, not a law |
| A per-series threshold learned from the series' own history — e.g. several times its observed 99.9th-percentile dwell — once a season is in | Adapts to soil, sensor resolution and depth at once | Needs history first; a probe stuck from installation would learn "stuck" as normal, so it needs a floor and a cap from the depth default anyway |
| Flatline off below some depth | Simple; no false alarms | A deep probe that really dies is then invisible to the one check that sees it |
| One threshold for everything, set long enough for 1 m | No false alarms | At 5 cm it would wait two weeks to notice a probe in a bucket |

**Soil texture matters as much as depth — measured, and it changes the recommendation.**
For all 87 humid-subtropical SCAN stations (1,720 probes), grouped by the USDA soil survey's
texture at each probe's own depth, the 99.9th-percentile dwell on good readings:

| depth | sandy | loamy | clayey |
| --- | --- | --- | --- |
| top 20 cm | 9 h | 11 h | 19 h |
| 51 cm | 15 h | 22 h | 32 h |
| 1 m | 22 h | 40 h | 64 h |

(An earlier version grouped by the global HWSD database, which turned out to misclassify
Tennessee and Mississippi soils at field scale; this replaces it.)

**Climate changes it for sand.** The same measurement over 210 SCAN stations, by Köppen
main class — temperate (C, 113 stations) reproduces the table above; cold (D, 34) is close
to it; dry (B, 63) is not:

| depth | dry: sandy | loamy | clayey | temperate: sandy | loamy | clayey |
| --- | --- | --- | --- | --- | --- | --- |
| top 20 cm | 14 h | 7 h | 8 h | 11 h | 11 h | 19 h |
| 51 cm | 32 h | 25 h | 28 h | 23 h | 21 h | 31 h |
| 1 m | **71 h** | 34 h | 45 h | 27 h | 38 h | 58 h |

Dry sandy soil goes days without changing, so in a dry climate deep sand dwells longest —
the reverse of the temperate ordering. A default from texture alone would put a flatline
at 44 hours on a dry sandy 1 m probe whose healthy dwell is 71.
[tools/soil_survey.py](../../tools/soil_survey.py) now takes the climate class, and
without one uses the longest dwell any climate showed, so an unknown climate errs towards
quiet. Cells measured on fewer than ten probes — cold-climate clay, and cold sand at
51 cm — take the temperate value.

**Recommendation, revised: learn each series' threshold from its own history** — several
times its observed 99.9th-percentile dwell — as the primary mechanism, because it absorbs
depth, texture, climate and sensor resolution together. Until a series has a season of
history, use a default from depth, texture *and* climate looked up in the soil survey at
the probe's location — [tools/soil_survey.py](../../tools/soil_survey.py) does this for any US point —
so a new probe starts from its own soil rather than from one number for all of them. Where
no survey exists, fall back to the clay column, so a new probe errs towards quiet rather
than towards a flood of false `stuck` flags. The
default doubles as the floor and cap on what a series may learn, so a probe stuck from the
day it was installed cannot teach itself that stuck is normal. And note what the 351-hour
maximum at Tennessee's 1 m cannot tell us — healthy soil, or a stuck sensor ISMN did not
flag — which is why every number here is a 99.9th percentile, not a maximum.

## Q25. When a two-peer siting check fires, which probe moved?

**Status: partly answered by measurement; how a non-robust alarm is reported is still
open.** Raised 2026-10-08, when the siting check found a real unlogged depth change in
ISMN's data and attributed it to the wrong probe (see
[notes/siting-real-soil.md](../notes/siting-real-soil.md)).

A real station is one profile with one probe per depth, and over two days only the top
three carry a readable daily wave. Each is judged against a line through the other two.
Three probes and a two-parameter line leave exactly one degree of freedom, so *any* single
probe's displacement fits the readings equally well. And a peer's error is amplified in a
probe extrapolated beyond it. At McAllister Farm, a replacement 10 cm probe sat about 4 cm
shallower than its predecessor; its own offset was within tolerance, while the 20 cm
probe, extrapolated from a 5–10 cm line squeezed into 3 cm of real depth, was called
displaced by 10–15 cm.

| Option | For | Against |
| --- | --- | --- |
| **A deeper peer over a longer window** — two-week windows, in which the 51 cm probe every such station already has carries a readable wave, so the fit has three peers | **Measured, and adopted as `assess_siting_weekly`.** McAllister's 20 cm probe stops being blamed — it reads 20 cm in every year after 2023 — and the robust 8 cm tolerance brings 10 cm moves within reach: about four in five called within six months, at 0.04 false episodes per probe-year, as few as the daily check | Slower: a 15 cm move is called in about five weeks rather than one, so it complements the daily check rather than replacing it. Still cannot resolve the real 2–4 cm shifts |
| **Report the profile, not the probe**, when the fit is not robust: "something in this profile moved; probes involved: …" | True, and what `robust: false` already means; costs nothing | Leaves a farmer to dig up three probes to find one |
| **Blame the probe whose own records changed when the alarm began** — a logged replacement, a maintenance visit, a gap in its readings | Exactly right at both stations where it happened: at McAllister and Allen Farms the 10 cm probe had an 18-month gap and a new sensor logged days before the profile changed | Only helps when the move coincided with a record; the unlogged cultivator strike has none |
| **Name the probe whose omission lets the rest line up best**, with four probes | Right 78–100% of the time for constructed moves of 10 cm or more (a scratch measurement, not yet in the tool) | 57–62% for 5 cm, and no use for the real 2–4 cm shifts. With nothing moved it still "names" someone — usually the deep probe, which sits in a different soil horizon — so it must only speak when the profile as a whole misfits |
| ~~Fit phase and amplitude together~~ | — | **Does not discriminate, by the physics.** In uniform soil both log-amplitude and phase are straight-line functions of depth with the same damping depth, so they are two noisy readings of one number per probe: every single-culprit hypothesis still fits exactly. Measured, amplitude named the culprit about as often as phase. What the pair *does* catch is a clock offset, which shifts phase and not amplitude |
| **Install a fourth shallow probe** (15 or 30 cm) | A robust fit even over two days | Hardware and labour on every profile — and a station's existing 51 cm probe already does most of this over two weeks |

**Recommendation:** run both schedules — daily for the large, fast move, weekly for the
smaller one and for attribution. When only the daily check fires and its fit is not
robust, report the profile and name the probe whose records changed at the onset, where
there is one, rather than the probe the arithmetic points at. Two observations that need
deciding together with this: a peer installed a few centimetres from its record biases the
others' implied depths for as long as it stays; and a replacement is exactly when a depth
error is most likely — both Tennessee replacements in 2023 went in 2–4 cm from their
predecessors — so a maintenance-record convention that asks for the *measured* depth at
every replacement would remove the cause rather than detect it.

## Q5. Binary encoding

**Status: DECIDED 2026-10-07 — CBOR packed arrays with a CDDL schema.** It blocked
build-order steps 3-7, so it was the critical path; it turned out to be decidable by
direct measurement without waiting for simulated nodes.

The original pair was Protocol Buffers or CBOR. Two more are worth knowing about, one of which is designed for precisely this job.

| Option | Size | For | Against |
| --- | --- | --- | --- |
| Protocol Buffers | Small (varints) | Schema-first, codegen, mature, `nanopb` works on an MCU | Not self-describing; field tags cost bytes; schema distribution is its own problem; protobuf-on-MCU is a build-system annoyance |
| CBOR with maps (RFC 8949) | Medium | IETF standard, self-describing, tiny MCU libraries, COSE gives you signing | Map keys on every message waste exactly the airtime you cannot spare |
| **CBOR with packed arrays + CDDL schema** | Small | Near-protobuf size with a standard encoding; CDDL gives you a schema and generated validators; COSE for signing; trivial decoders everywhere | Positional arrays are unreadable without the schema, so the schema becomes load-bearing |
| **SenML + SenML-CBOR (RFC 8428)** | Small | An IETF standard **for sensor measurement lists**: base-name and base-time fields give you exactly the batch delta-compression v0.1 §5.2 needs, plus a unit field; already understood by IoT tooling | Its data model has no place for `boot`, `seq`, provenance or quality, so it needs an extension — and once extended it is no longer interoperable in the way that made it attractive |
| MessagePack | Small | Simple, fast, wide library support | No IETF standing; no schema language; CBOR is the standardized version of this idea |
| Cayenne LPP | Very small | An existing LoRaWAN convention; decoders already in network servers | Fixed, limited type set; no versioning; cannot express this data model |
| Hand-rolled bit-packed struct | Smallest | Total control; squeezes the duty cycle hardest | No versioning, no tooling, brittle against change — and §12 requires a version in every packet |
| FlatBuffers / Cap'n Proto | Medium | Zero-copy reads | Solves a problem a farm node does not have |
| ASN.1 UPER | Smallest schema-defined | Genuinely the most compact standardized option | Tooling is hostile; nobody on a volunteer project will enjoy it |

**Decided on measurement, 2026-10-07: CBOR packed arrays with a CDDL schema.** Full result and method in [notes/q5-encoding-measurement.md](../notes/q5-encoding-measurement.md); reproduce with `make q5`.

Scored on what §5.2 says actually binds — readings per hour inside a 1% duty cycle at EU868 DR0 (SF12), the worst case a node must survive:

| Encoding | 8 readings | Max batch at DR0 | Readings/h |
| --- | --- | --- | --- |
| Hand-packed struct (the floor) | 51 B | 8 | 103 |
| **CBOR packed, flat + CDDL** | 64 B | 6 | **77** |
| Protocol Buffers | 91 B | 4 | 52 |
| SenML-CBOR + custom labels | 177 B | 1 | 13 |
| CBOR maps, named keys | 178 B | **0** | 0 |

**Two candidates are eliminated by measurement, not taste.** CBOR with named keys cannot carry a *single* reading at DR0 — 56 bytes against a 51-byte limit. And SenML, the most interesting candidate, does not survive carrying `boot` and `seq`: it has nowhere to put them, adding `boot_`/`seq_` costs 15 bytes, and RFC 8428 requires a label ending in `_` to be understood or the record rejected — so extended SenML is SenML that no stock consumer may accept. The interoperability that made it attractive is gone and it is still 3.5x the floor.

**That table compares maxima, and a maximum is not an operating point.** At realistic duties the surviving candidates are indistinguishable on airtime: hourly sampling with hourly transmission costs 1.6 s/h hand-packed against 1.8 s/h in CBOR — 4.6% of the budget against 5.0%. At five-minute sampling with hourly transmission they are *identical*, both needing two messages. The 25% gap in maximum throughput is invisible at any rate a farm would run, and surfaces only at one-minute sampling (62% against 78% of budget) and on backlog drain after a long outage (8.4 h against 11.2 h at five-minute sampling; under an hour either way at hourly).

**So airtime does not decide this, and tooling does.** CBOR brings CDDL as a schema language, COSE for signing, and a decoder in every language — which §12's versioned format and §9.2's conformance suite need, and which a layout existing only in prose cannot give. Protobuf loses on the same ground rather than on bytes: field tags and varint framing buy nothing over CDDL here while requiring a code generator in the node's build.

The hand-packed layout stays **documented as an escape hatch** for a node draining a very long backlog at SF12, distinguished by the version byte — a profile, not a second format.

## Q6. Which link ships first

**Status: blocks v0.** It sets the airtime budget everything else is sized against.

| Option | For | Against |
| --- | --- | --- |
| **Meshtastic** | Cheap, reproducible hardware a DIY builder can buy; mesh routing for free; no network server or gateway infrastructure; an active community | No delivery confirmation, so v0.1 §5.2's cumulative ack must be real; you manage duty cycle yourself; not a commercial-deployment story |
| LoRaWAN via ChirpStack | Duty cycle and ADR handled for you; confirmed uplinks available; the commercial path; existing coverage in some regions | Needs a gateway and a network server; confirmed uplinks cost downlink budget and battery; more moving parts before the first reading |
| Wifi | Trivial to build against | Tests none of the hard cases; a farm that has wifi at the sensor does not need this spec's hardest machinery |
| Cellular (LTE-M / NB-IoT) | Coverage without infrastructure; good for one remote node | Per-device cost and SIM management; power budget; carrier dependence |
| Wired RS-485 / Modbus | The most reliable option; the only one where a bug is definitely in your code | Limited reach; not the connectivity problem the spec addresses |

**Recommendation: Meshtastic first, and keep a wired Modbus driver in the test suite.** Meshtastic is the harsher case, so building against it forces the cumulative-ack and backlog clauses to be implemented rather than described — the failure mode of a spec like this is that the offline machinery is specified and never exercised. The wired driver earns its place for a different reason: it is the only link where a discrepancy is unambiguously a data-model bug, which makes it the control in every debugging session. LoRaWAN second, once the contract has survived a season.

## Q8. farmOS's role

**Status: blocks v0.** It determines whether the append-only log is real. v0.1 §7.1 assumes option B; confirm or overrule it.

| Option | For | Against |
| --- | --- | --- |
| **A. farmOS authoritative for records; layer zero is a sensor sidecar** | Fastest to something useful; inherits farmOS's UI, community and records model for free | Abandons *Auditable* and *Farmer-owned* as stated: state is not derived from the log, history is not replayable, and the project becomes a farmOS accessory rather than a foundation |
| **B. Log authoritative; farmOS a one-way projection** | Every principle survives; existing farmOS clients keep working; farmOS stays genuinely optional | A projector to write and keep correct; two models to understand; some farmOS features will not round-trip |
| **C. Log authoritative; farmOS API emulated, no farmOS install** | Cleanest end state; one system to operate; no Drupal | You now own compatibility with an API you do not control, and partial emulation annoys users more than no emulation |
| D. Dual-write with reconciliation | Looks like it gets both | Two writers, no single order, permanent drift. The trap |
| **E. Split authority: farmOS owns records; the log owns observations, commands and decisions** | Honest, much less work than B, and the sensor side — the part that is actually novel — keeps full auditability | "Any action can be traced back to why it happened" holds for half the system; compliance records straddle the boundary |

**Recommendation: B, with C as the end state.** B keeps every principle while letting farmOS's ecosystem work on day one, and it converts the original "when to replace farmOS, if ever" into a non-event: the projector gets retired when nobody needs it, and nothing else changes.

If B's projector proves too much work for the first season, **take E deliberately and write it down**, rather than drifting into A by accident. The difference between a chosen shortcut and an accident is whether the spec says so.

---

# Part B — Blocks commands

## Q3. SensorThings 1.1 now, or wait for 2.0?

**Status: decided in v0.1 — ship 1.1.** Recorded here because the research behind it is specific and perishable.

| Option | For | Against |
| --- | --- | --- |
| **1.1 now** | Published and stable; `resultQuality` exists as `DQ_Element` 0..\*, which v0.1 §3.3's model needs; mature server implementations to test against | A migration to 2.0 is coming |
| Wait for 2.0 | One migration avoided | Unpublished: document 23-019, version 0.1, submitted 2025-11-26, approval and publication dates still `XXXX-XX-XX`. Building a farm's data foundation on an unapproved draft trades a known migration for an unknown one |
| Both, behind one serialization layer | Future-proof | Twice the surface, before anyone has asked for either |
| Target the 2.0 draft now | Ready on publication | The draft's entity names and annotations are still moving |

**Recommendation: 1.1, with the adapter's serialization confined to one layer**, and both versions served side by side once 2.0 publishes. This is not a hedge: FROST-Server already ships 1.1 and 2.0 API plugins that run simultaneously over one data model, so dual-serving is the ecosystem's own pattern. Because the adapter is out-only, clients adapt to us rather than the reverse, and the exposure to vendor version choice is close to zero — see [notes/sensorthings-2.0.md](../notes/sensorthings-2.0.md), which also covers why the vendors in this market do not speak SensorThings at all. The one finding there that changes the spec: 2.0 has no `resultQuality`.

## Q3b. Which standard the command contract aligns with

**Status: blocks commands.** v0 assumed SensorThings Part 2 (Tasking). That remains available — note that tasking has never been in Part 1 in either version, so the 2.0 draft's silence on it is a matter of document scope, not a gap. What is new is that a published alternative now exists, and that nothing commits Part 2 to a 2.0 revision.

| Option | For | Against |
| --- | --- | --- |
| SensorThings Part 2, Tasking Core (OGC 17-079r1) | Already in the SensorThings family; simple `Task` / `TaskingCapability` model; small; unaffected by the 1.1/2.0 choice | No announced 2.0 revision, so its future is unclear; its model has no expiry-reversion, no bounded idempotency, no dry run — the parts that keep a pump safe |
| OGC API — Connected Systems Part 2 | **Published**, v1.0; ControlStreams are purpose-built for commands flowing to and from systems; links to SensorThings rather than replacing it; actively developed | Heavier, with SWE lineage and a larger conceptual surface than a farm valve needs |
| Own contract, aligned with neither | Fits the safety requirements exactly | Interoperability principle takes a real hit; every integrator learns something bespoke |
| **Own contract, plus a Connected Systems adapter when commands ship** | Safety contract stays uncompromised; standard compatibility arrives as a translation, where it belongs | Two things to maintain, eventually |
| W3C WoT Thing Description actions | Good web-of-things fit; reasonable tooling | Nothing about duty cycles, expiry reversion or interlocks |
| MQTT convention (Sparkplug B, Homie) | Pragmatic, widely implemented on the bus you already use | Not a standard for *tasking* semantics; no safety model |

**Recommendation: own contract, with a Connected Systems adapter.** v0.1 §6 already specifies more safety than either standard offers — bounded dedup, expiry reversion, `unknown` acknowledgement, dry-run with named limits — and contorting that to fit a serialization would trade a safety property for a compatibility checkbox. Read Connected Systems Part 2 properly before freezing §6 regardless; it is new enough that it was probably not on the table when v0 was written, and borrowing its vocabulary costs nothing.

## Q13. Command dedup persistence on a node

**Status: blocks commands.** v0.1 §6.3 requires non-volatile dedup or a declared `dedup_volatile`; the mechanism is open.

| Option | For | Against |
| --- | --- | --- |
| EEPROM / flash write per command | Simple, survives cold start | Flash wear; a write in the command path |
| FRAM | Effectively unlimited writes, fast | Extra component and cost |
| RTC backup RAM, coin cell | Cheap, no wear | Lost if the cell dies, which is silent |
| Ring buffer of recent command IDs in NVM, written lazily | Bounded wear | A window where a reboot loses the newest entries |
| `dedup_volatile`, relying on max runtime and safe state | No hardware requirement; honest | Double execution is possible and must be bounded by runtime limits, which constrains what commands may be issued at all |

**Recommendation:** FRAM or a lazily-written NVM ring where the hardware allows, and `dedup_volatile` declared honestly where it does not. The spec already handles the second case by refusing commands whose double execution is not runtime-bounded; what matters is that a node never *silently* has volatile dedup.

---

# Part C — Blocks third parties

## Q2. License for the spec, SDK and reference implementation

**Status: DECIDED 2026-10-07 — the three-license split, as recommended below.** Spec and
all prose CC-BY-4.0; `sdk/`, `sim/` and `tools/` Apache-2.0; `server/` AGPL-3.0-or-later.
Written down in [LICENSING.md](../../LICENSING.md), with every file carrying an SPDX line.
Decided before the first outside contribution, which was the whole constraint — after one,
relicensing needs every contributor's agreement. The options are kept below because the
reasoning is the part that has to survive, not the verdict.

| Option | For | Against |
| --- | --- | --- |
| Apache-2.0 everywhere | Explicit patent grant, which matters in agriculture; device makers embed it without a lawyer; GPLv3-compatible | Nothing stops a vendor running it as closed SaaS — awkward against *Farmer-owned* |
| MIT everywhere | Shortest, most permissive, best understood | No patent grant |
| **Spec CC-BY-4.0 · SDK and wire format Apache-2.0 · reference implementation AGPL-3.0** | Each artifact gets the license its job needs: the spec spreads, the SDK is embeddable in firmware, the server cannot be enclosed as a closed service | Three licenses to explain; AGPL deters some commercial contributors |
| Spec CC-BY-4.0 · everything else Apache-2.0 | Maximum adoption; simplest story | Same SaaS-enclosure exposure |
| GPL-3.0 everywhere | Matches much of the existing ag ecosystem; strong reciprocity | Device makers will not put GPL in firmware, so the SDK — the thing you most want adopted — is the thing most harmed |
| MPL-2.0 everywhere | File-level copyleft; a genuine middle ground; embeddable | Less familiar; satisfies neither camp fully |
| AGPL plus commercial dual license | A revenue path | Requires a CLA, which deters contributors and creates an entity requirement (Q9) |

On the *Reimplement, don't copy* principle: it is satisfied by speaking HTTP to farmOS rather than vendoring its code or schema. It does **not** bar taking code from `campus_twin`, which is the same author's and therefore relicensable at will — see [VIRTUAL_FARM.md](../VIRTUAL_FARM.md). Relicensing the shared transport and emulator files to Apache-2.0 in their current home, before forking them here, keeps improvements flowing both ways and keeps this question's recommendation intact. Apache-2.0 combines with GPLv3-or-later, and farmOS sits on Drupal, which is GPLv2-or-later — the "or later" makes a v3 combination possible — but under v0.1 §7.1 the question is moot, because nothing links.

**Recommendation: the three-license split.** Spec under CC-BY-4.0 so it can be implemented by anyone including a competitor; SDK, wire format and conformance suite under Apache-2.0 so a sensor manufacturer can ship it in a product; reference implementation and server under AGPL-3.0 so a hosting vendor cannot take the farmer-owned stack and make it not farmer-owned. Decide before the first outside contribution, because relicensing later needs every contributor's agreement.

## Q10. Rule language for layer 1

**Status: blocks third parties.** Not needed for v0, but it determines whether layer 1 can be trusted.

The binding constraint eliminates most options: v0.1 §11 requires rules to be backtestable on past seasons and decision events to be reproducible. That means **deterministic and side-effect-free**, which plain Python cannot promise.

| Option | For | Against |
| --- | --- | --- |
| Small declarative DSL (YAML conditions) | Legible to a farmer; trivially sandboxed; easy to show in a UI | Outgrown fast; every escape hatch becomes a language you did not design |
| **CEL (Common Expression Language)** | Sandboxed, typed, fast, no I/O, deterministic by design; proven in Kubernetes admission control; small embeddable implementations | Single expressions only — not a language for multi-step regimens |
| **Starlark** | Deterministic and hermetic by construction; Python-like, so it reads as familiar; proven at scale in Bazel; handles multi-step logic | Not Python, so libraries do not transfer; smaller ecosystem |
| RestrictedPython | Real Python | Not a security boundary — a determined module escapes it; unsafe for third-party rules |
| Lua | Tiny, fast, embeddable, well understood | Sandboxing is manual; non-determinism available unless you remove it |
| Rhai | Rust-native, sandboxed, good fit for the edge daemon | Small community; another syntax to learn |
| JSONLogic | Trivially serializable and storable | Unreadable past about ten lines |
| Datalog / rules engine | Declarative, analyzable, conflict detection comes free | Unfamiliar to the audience; a steep ask for a farm module author |
| Full Python, trusted authors only | No limits | Kills third-party modules and backtesting in one move |

**Recommendation: CEL for conditions, Starlark for regimens.** Conditions ("soil moisture below 18% for 6 hours") are expressions and belong in CEL, where they are cheap to evaluate, store and display. Regimens (a multi-step irrigation sequence with waits and checks) need control flow, and Starlark gives it deterministically. Both refuse I/O, which is what makes a decision event's provenance claim true rather than aspirational.

## Q11. How modules are packaged and isolated

**Status: blocks third parties.** v0.1 §8.3 says the foundation enforces per-point permissions; the enforcement mechanism is open.

| Option | For | Against |
| --- | --- | --- |
| **Separate OS processes + IPC, under systemd with seccomp/landlock and cgroups** | Simple; works today on a Raspberry Pi; resource limits and restart policy for free; a crashed module cannot take the foundation down | Isolation is only as good as the sandbox configuration; packaging and dependency hell is yours to solve |
| Containers (Podman or Docker) | Strong isolation; a real distribution story; familiar to developers | Heavy on a Pi; image size over a rural link; a container runtime is a lot of machinery to require of a farm gateway |
| **WebAssembly + WASI component model** | Capability-based security maps one-to-one onto "each module declares what it may read, write and command" — the permission model becomes the runtime rather than a check layered on top; tiny artifacts, so modules update over a bad link; genuine sandbox | The Python-on-WASI story is still rough in 2026; every I/O capability needs a host function; debugging is worse |
| In-process Python plugins | Trivial; fast | No isolation at all. A third-party module can do anything, which contradicts the clause that makes third-party modules safe |
| VMs | Strongest isolation | Absurd on farm hardware |
| Flatpak/Nix packaging over processes | Reproducible, good dependency isolation | Does not provide the *permission* enforcement, only the packaging |

**Recommendation: processes for v0, WASI as the stated target.** Ship processes under systemd with per-module capability tokens over a unix socket — enough to enforce the permission model, and buildable now. State WASI as the direction, because capability-based sandboxing *is* the security model the spec describes and the alignment is too good to leave unclaimed. Do not block on it: the Python toolchain is not ready, and the first modules will be Python.

---

# Part D — Blocks the pilot

## Q7. Conflict rules for offline edits

**Status: blocks the pilot.** The moment two people edit on two phones in one field, this is live.

| Option | For | Against |
| --- | --- | --- |
| LWW per field on wall-clock time (v0's position) | Trivial | **Unsafe in this system by its own admission.** v0.1 §2 records `clock_quality` precisely because farm device clocks are unreliable; a phone with a wrong clock silently wins every conflict |
| **LWW per field on hybrid logical clocks** | Cheap; preserves causality; a bad wall clock can no longer win on the strength of a bad timestamp; small change from naive LWW | Still loses one value silently when writes are genuinely concurrent |
| Vector clocks | Detects true concurrency exactly | State grows with the number of writers; needs pruning |
| CRDTs per field type | Correct by construction; no lost updates; Automerge and Yjs are mature | Heavier; awkward over farmOS-shaped records; overkill for a field that is one number |
| **Resolution at projection time over the event log** | Fits the architecture already chosen — events are retained regardless, so resolution is a read-time concern and can be re-run when the rules improve | Projection logic must be deterministic and versioned, or two replicas disagree |
| Manual merge queue for every conflict | Never loses data | Unusable; the queue is ignored by week two |
| Single-writer leases per entity | Prevents conflicts instead of resolving them | Needs connectivity to acquire a lease, which is the thing you do not have |

**Recommendation: hybrid logical clocks plus resolution at projection time**, with CRDT semantics for the few genuinely set-like fields — tags, animal groups, applied inputs — where union is obviously right. Emit a conflict event, as v0.1 §7.4 requires, for fields where a silent loss has consequences.

**Sub-question worth writing down (Q14):** *which* fields those are. Quantities, treatments, harvest weights and anything feeding a compliance record should never resolve silently. That list belongs in the spec as a table, because "conflict in a way that matters" is otherwise left to each implementer's judgement.

## Q9. Legal entity, liability coverage and sustainability

**Status: blocks the pilot.** Putting software on someone else's farm without an answer to liability is the one item here with personal exposure.

### Q9a. Legal entity

| Option | For | Against |
| --- | --- | --- |
| No entity, personal project | Zero overhead | Personal liability; cannot hold grant money or a trademark |
| **Fiscal host (Open Collective, Software Freedom Conservancy, Commons Conservancy, NumFOCUS)** | Cheap and fast; liability separation; can receive grants and donations; no board to run | Less control; some hosts take a percentage; acceptance is not automatic |
| Own nonprofit (US 501(c)(3) or (c)(6); EU stichting or e.V.) | Full control; credible to institutional partners; the right long-term home | Months of work, filing fees, a board, annual compliance |
| LLC or B-corp | Simple to form; can trade and contract | Governance signals "company", which deters contributors to a farmer-owned project |
| Join an existing foundation (Eclipse, Linux Foundation, OSGeo, Apache) | Instant governance, legal and IP machinery; credibility | Process overhead; loss of autonomy; most want traction before they want you |

**Recommendation: a fiscal host now, own entity later.** It is the cheapest thing that separates personal liability from the project and lets grant money arrive, which Q9c needs. Revisit when there is money, staff or a trademark worth defending.

### Q9b. Liability

| Option | For | Against |
| --- | --- | --- |
| Disclaimer only (the standard license warranty disclaimer) | Free; what nearly all free software does | Thin comfort when software that moved water is involved |
| **Disclaimer + documented safety boundary + mandatory hardwired interlocks** | Already the spec's position; shifts the safety-critical function to hardware that software cannot override; demonstrably designed for failure | Requires the installer to actually fit the interlocks, which is outside your control |
| General liability and errors-and-omissions insurance | Real coverage | Costs money; underwriters are wary of agricultural control software; needs an entity |
| Entity shield (Q9a) | Separates personal assets | Does not make the risk go away |
| A certification program that places responsibility on integrators | Scales; creates a revenue path (Q9c) | Needs the conformance suite to be authoritative first |
| **Ship no command capability in the first season** | Removes the entire category of risk for the period when the code is least proven | Delays the irrigation module, which is the most compelling demo |

**Recommendation: all of the last three, in that order.** v0.1's scope cut already does the strongest thing available — no commands in the first release — and that is worth stating publicly as a safety decision rather than a roadmap detail. Keep the interlock requirement non-negotiable in the spec, and the documented safety boundary current.

### Q9c. Sustainability

| Option | For | Against |
| --- | --- | --- |
| **Grants (USDA SARE, NIFA, EU Horizon, state agriculture departments)** | Pays for exactly this kind of work; extension partners know the process; non-dilutive | Cyclical deadlines; reporting burden; funds projects, not maintenance |
| Paid setup and support | Honest alignment: the software is free, expertise is paid | Does not scale without hiring; you become a consultancy |
| Paid hosting | Recurring revenue | Directly contradicts local-first unless carefully framed as convenience |
| **Conformance certification and trademark fees** | Scales; funded by device makers rather than farmers; strengthens the standard as a side effect | Needs a trademark, an entity and a credible suite — so it is a year-two option |
| Hardware sales or kits | Farmers want a thing they can buy; margin on nodes | A hardware business is a different business |
| Dual licensing | Real revenue from vendors | Requires a CLA, which deters contributors |
| Donations | Easy to start | Will not fund serious work |
| Open core | Proven model | The withheld features are the ones farmers need; contradicts *Farmer-owned* |

**Recommendation: grants plus an extension partnership for the pilot season; certification and trademark fees as the long-term engine; paid setup as the bridge. Not open core** — the features you would have to withhold are precisely the ones the principles promise.

## Q12. Which layer 2 module ships first

**Status: blocks the pilot.** It determines what the pilot farm actually gets, and it interacts with Q1.

| Option | Needs commands? | For | Against |
| --- | --- | --- | --- |
| Irrigation (v0's candidate) | **Yes** | The most compelling demo; the clearest value; the deepest pain | Needs the command contract, which v0.1 defers by a season; carries all the liability; the hardest thing to debug while the data model is also new |
| **Livestock water monitoring** | No | Read-only, so it ships with v0; high value — a dry trough is an emergency; exercises store-and-forward, backlog and quality assertions exactly where they are most likely wrong | Narrower; less visually impressive |
| **Soil-moisture advisory** | No | Read-only; produces the irrigation module's evidence base a season early; directly tests calibration, drift and quality assertions | Advice without actuation can feel incomplete to a farmer |
| Greenhouse climate | Yes | Dense sensing, fast feedback loops | Needs commands; good connectivity means the hard machinery goes untested |
| Cold chain and storage | No | Read-only; compliance value; clear financial stakes | Narrow; not the diversified-farm case |
| Compliance reporting | No | Read-only; answers a real administrative burden; tests the log model hard | No sensor story; depends on which certification scheme the pilot is in |

**Recommendation: livestock water monitoring or soil-moisture advisory, chosen to match the pilot farm (Q1). Irrigation second.** This reverses v0's candidate, and the reason is the scope cut: a read-only module ships with a commands-free v0, carries no liability, and stresses the parts of layer zero most likely to be wrong. It also means the irrigation module arrives with a season of real data behind it to backtest its rules against, which v0.1 §11 requires of it anyway.

---

# Part E — Decided in v0.1

Recorded so each decision can be revisited with its alternatives intact.

| Question | Decision | Options rejected, and why |
| --- | --- | --- |
| **Short point index on constrained links** | Node-local **channel index**, one byte; registry-assigned 16-bit index as an optional extension above 255 points | A global 16-bit index costs a second byte and requires provisioning a shared space, so a swapped node must be reprovisioned; a truncated hash of the point UUID risks silent collisions; SenML-style names cost far more airtime |
| **Quality representation** | Append-only assertions: a flag **set** plus a `usable` summary, with check and threshold versions | A single mutable enum could not express concurrent conditions, left two implementations free to disagree, and mutated an immutable record; a free-text note is unqueryable |
| **Recalibration** | Separate raw and derived datastreams; append with `supersedes` | Overwriting destroys history; two results in one row put two observations at one `phenomenonTime` and broke SensorThings clients; a new datastream per calibration epoch fragments the calibrated series and makes a season impossible to chart |
| **Staleness** | Datastream health state, not a reading flag | Flagging a reading means mutating a correct record because a *later* one failed to arrive |
| **Node identity** | `(site, node, boot, seq)`, `seq` 16-bit | `(node, seq)` alone silently discards everything after a reboot; a monotonic 32-bit counter in NVM costs more writes than a boot counter |
| **Offline edit ordering** | Hybrid logical clocks | Wall-clock LWW lets an unsynced clock win, which §2 already says is likely |
| **Capacity enforcement** | Layer zero, beside per-point authorization | The layer-1 scheduler is declared non-safety-critical and may be down; per-node interlocks cannot see another node's output |
| **farmOS** | One-way projection of the log (Q8 option B) | See Q8 |
| **SensorThings version** | 1.1 now (Q3) | See Q3 |
| **Units** | UCUM (Q4a) | See Q4a |
| **Timestamp uncertainty** | Mandatory `measured_at_uncertainty`, never zero | `clock_quality` alone is a category, not a bound, and a research logger cannot use an unbounded timestamp |

---

# Part F — New questions this revision raises

| # | Question | Status |
| --- | --- | --- |
| Q14 | Which record fields must never resolve a conflict silently? (see Q7) | Blocks the pilot |
| Q15 | Time-series downsampling and retention defaults — what is kept at full resolution, for how long, and does a farmer ever lose raw data to a retention policy? If *Honest data* means anything, raw retention is probably forever | Blocks v0 |
| Q16 | Default grant scope: does a new grant include observations that arrive after it was made? Safer default is no, but it makes research sharing tedious | Blocks the pilot |
| Q17 | Crypto-shredding key management for erasure (§7.3): per-subject keys, where they live, and what happens to a backup taken before the shred | Blocks the pilot |
| Q18 | Should the missing `resultQuality` in the SensorThings 2.0 draft be raised with OGC? | **Done 2026-10-07** — posted as a comment on [#174](https://github.com/opengeospatial/sensorthings/issues/174#issuecomment-6050541663); see [notes/q18-ogc-issue-draft.md](../notes/q18-ogc-issue-draft.md) |
| Q19 | Should an assertion's `evidence` object be normative, and what shape? | Blocks third parties |
| Q20 | May a node send an aggregate for a low-urgency series, when §5.1 says it applies nothing? | Blocks v0 node firmware |
| Q21 | What unit does a *raw* datastream declare? | Blocks v0 |
| Q22 | Does the maintenance vocabulary need a battery replacement? | Blocks nothing |
| Q23 | A rate-of-change limit that works at any sampling interval | Measured; recommendation awaits a decision |
| Q24 | Flatline thresholds that know the probe's depth, soil and climate | False alarms on deep probes today |
| Q25 | When a two-peer siting check fires, which probe moved? | Partly measured; reporting open |

**Q18 is no longer what it looked like.** A search of the OGC repository before
drafting anything found issue **#174**, opened by the 2.0 editor in January 2024 and
labelled `sensing v2.0`: *"Since no one really knows what to do with the
resultQuality DQ_Element property on Observation, we need something better."* The
removal is deliberate, issue **#68** documents why `DQ_Element` was unusable
(ambiguous between ISO 19115 and 19157; no category result type), and sixteen
comments carry a worked replacement design from the EU CitiObs project and UFZ's
`saqc`. Asking for `resultQuality` back would have been asking for the thing they
already decided was broken.

What #174 does have is four questions still open — annotation cardinality, whether
compound types are too hard for clients, how history is represented, and how a
measure's parameters are stored — and this project had to answer all four to build
§3.3. The draft at [q18-ogc-issue-draft.md](../notes/q18-ogc-issue-draft.md) is
therefore a **comment on #174**, not a new issue, and it supplies evidence rather
than requests. Last activity on #174 was 2025-08-25; the 2.0 draft was submitted
three months later without a quality model.

The original framing, kept because the underlying facts are still true:

On **Q18 — yes, and soon.** The 2.0 draft (23-019) has no `resultQuality` attribute: Table 17 lists `id`, `phenomenonTime`, `result`, `resultTime`, `validTime` and `properties`, and the string `resultQuality` appears nowhere in the document, nor does `DQ_Element`. SensorThings 1.1 had it, typed `DQ_Element` with multiplicity zero-to-many. The formal comment period closed on 18 January 2026, but the standard is unpublished and issues are still accepted in the OGC SensorThings GitHub repository, so there is a window. A farm data foundation that must distinguish a stuck sensor from a dry soil is a good concrete argument for keeping a structured quality field in the core, and "we are building on this and here is what we lose" is the kind of feedback a draft standard is for. Cost: an hour. Upside: the mapping in v0.1 §3.3 stops being a workaround.

## Q19. Should `evidence` on a quality assertion be normative?

**Status: blocks third parties.** Added by the §17 amendment of 2026-10-07. The
field exists and is populated; whether a conforming implementation must produce it,
and in what shape, is undecided.

| Option | For | Against |
| --- | --- | --- |
| **Leave it optional and unspecified** | Costs nothing now; implementations experiment before the shape is frozen | Two implementations produce incomparable evidence, so a conformance suite cannot test it and a farmer cannot compare two gateways' reasoning |
| **Normative with a fixed shape** (`checks_run`, `fired`, `thresholds`) | A false alarm becomes traceable *across* implementations, which is what the audit principle promises; the conformance suite can assert it | Freezes a shape before much experience with real checks; a check with unusual evidence has to distort it |
| **Normative minimum, open extension** | A floor the suite can test, with room above it | The usual risk: the extension area becomes where everything interesting lives, and comparability erodes anyway |
| **Drop it; put reasoning in `note`** | One fewer field | A string is unqueryable, so "which threshold caused this false alarm" goes back to being read by a human |

**Recommendation: normative minimum, open extension**, once two or three real
checks exist. `checks_run` and `fired` are the floor — they answer "what looked at
this reading, and what objected" — and that is the pair *Auditable* actually
promises. Deciding it before the health checks have run a season would freeze a
guess; deciding it after third parties ship drivers would be too late, so the
window is between build-order steps 4 and 7.

## Q20. May a node send an aggregate instead of every sample?

**Status: blocks v0 node firmware.** Raised by the power measurement in
[notes/power-budget.md](../notes/power-budget.md).

There is a tension between three clauses that only shows up once power is counted.
§4.2 runs health checks **in the foundation**; §5.1 says the node "samples, applies
nothing"; and the power model says you pay for what you *send*. Together those mean
**detection resolution equals transmitted resolution**: to catch a flatline at
five-minute resolution the gateway must receive five-minute data, and that is the
expensive thing. A farmer who wants a stuck probe caught within the hour must pay
hourly-resolution airtime for a series they otherwise only care about daily.

| Option | For | Against |
| --- | --- | --- |
| **Send every sample; accept the cost** | §5.1 and §3.2 stay exactly as written — raw is what the node sent, and nothing on the node can be wrong in a way the log cannot show | The honest-data principle ends up charging for detection a farmer may not want at that resolution. On a shared node it is nearly free; on a sleepy one it is most of the budget |
| **Node sends a compact aggregate for low-urgency series** — sample count, min, max, and the length of the current unchanged run | Preserves what the checks actually need (a flat run and a rate excursion are both detectable from those four numbers) for a handful of bytes instead of twelve readings. Would make hourly reporting with five-minute detection possible | The node has now computed something, which §5.1 forbids and §3.2 complicates — an aggregate is not "exactly what the node sent" for any one instant, so it needs its own datastream kind rather than passing as raw |
| **Move the checks onto the node** | Cheapest of all; the node already has the samples | Squarely against §5.1 and §4.2, and it puts threshold versioning and assertion provenance on a microcontroller that cannot be audited or updated over LoRa (§8.1) |
| **Per-series choice, declared in the manifest** | The farmer decides where to spend, per series | Two ingest paths and two conformance stories; a driver author can pick the cheap one by default and quietly lose detectability |

**Recommendation: option 2, as a third datastream `kind`** — `raw`, `derived`, and
an `aggregate` whose observations carry a window rather than an instant and are
explicitly not raw readings. That keeps §5.1 intact for raw series (a node still
applies no calibration and no judgement), keeps §3.2's archival claim honest
(an aggregate is a different thing, labelled as one), and gives the health checks
something to work on without paying full resolution. It is a real addition to the
data model though, not a tweak, so it wants deciding before node firmware is
written rather than after.

Worth noting what is *not* in tension: on a node that already transmits often for an
urgent series, sending every sample of a sleepy one costs under 2%. This question
only bites for a node whose series are all slow, which is exactly the node where
battery life matters most.
