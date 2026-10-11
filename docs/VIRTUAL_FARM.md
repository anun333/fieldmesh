<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# The virtual farm — the sim as layer zero's substrate

Oct 7, 2026. Companion to [spec/v0.1.md](spec/v0.1.md).

> **Status: proposed.** Nothing built yet. This is the sequencing decision — the virtual farm
> comes before hardware and before a pilot — and the design that follows from it.

## Why fiction first

A real farm shows you the faults it happens to have, in the order the weather supplies them, once per season. Layer zero's hardest clauses — the ones most likely to be wrong — are all about failure: a node that reboots and resets its counter, a three-day buffer draining against a duty cycle, a probe that drifts past plausibility, a recalibration that must not destroy a season of history, a lost acknowledgement that might or might not have opened a valve. Waiting for a real farm to produce one of each is a multi-year sampling problem.

A fictional farm can carry one of everything, on demand, deterministically, with ground truth available for scoring. That makes it the right substrate for the contract, and it is already proven house doctrine: this is what `campus_twin` does for buildings, where the virtual campus is simultaneously the rehearsal environment, the validation harness and the presentation artifact.

Four properties earn it:

- **No real-site dependency.** No privacy problem, no permission to seek, no season to wait for. The whole experience ships in the repo.
- **Total coverage on demand.** Every flag, every failure mode, every clause of the spec, live at once.
- **Ground truth for scoring.** The sim knows what it injected, so a health check's verdict can be scored honestly rather than eyeballed.
- **A standing integration gate.** "The contract works" becomes a test that fails when a clause exists in the spec but nothing in the farm exercises it.

## What it does not earn

[v0.1 §9.2](spec/v0.1.md) says reliability claims require at least one full growing season of field data, not a few weeks in the lab. **A simulator is not a season, and no amount of simulated fidelity converts into a reliability claim.** The distinction to hold:

| The virtual farm validates | Only a real season validates |
| --- | --- |
| The contract is implementable and internally consistent | That real soil probes drift the way the sim drifts |
| Three different apps can be built on it unchanged | That a farmer finds the data trustworthy |
| Health checks catch the faults they claim to catch, measured | That the thresholds are right for real soil, real weather, real neglect |
| Node firmware survives reboots, outages and duty cycles | Battery life, enclosure survival, rodents, condensation |
| An observation's provenance chain holds end to end | That the failures the sim does not know about are survivable |

So the virtual farm moves the pilot farm **off the development critical path** and leaves it **on the claims critical path**. The sequencing changes; the honesty bar does not. The risk of this approach is a project that mistakes a green test suite for field-readiness, and the mitigation is to keep that sentence in the README.

## The doctrine

Borrowed from `campus_twin` because it is already load-bearing there, and because the failure modes it prevents are the same ones.

**1. Placed means speaking.** A device appears in the model only when the sim actually emits its telemetry. A sensor in the matrix with no producer behind it stays matrix-only and is never rendered as a live asset. *A producer without a placement is a demo; a placement without a producer is a lie.*

**2. Deterministic.** Seed plus `ts0` reproduces the farm byte for byte. A fault that appears on one run appears on every run. Without this, a failing test is unactionable.

**3. Fiction-first defaults.** Every tool's default subject is the sim preset, never a real site. Real farm data is the exception a flag opts into, and it lives outside the repo (see *Site data* below).

**4. Detection is measured, not asserted.** A health check's claim — that it catches a stuck probe, that it catches drift — is scored on labeled data with precision, recall, false-alarm rate on clean rows, and per-episode detection. `campus_twin` does this against public labeled fault datasets and skips cleanly when they are absent; the same discipline applies here, with the ag equivalents. "It flags the obvious case" is not a measurement.

**5. Plausible fiction, disciplined.** Named real sensor models only where a real catalogue can select one, with provenance. Otherwise a consistent fictional model family carrying every field the checks actually read. Never a hand-invented model with convenient specifications.

## Harrow Bend — the canonical farm

One named, persistent, deterministic fictional farm, not a per-demo throwaway. The name is a placeholder worth keeping unless something better turns up; the point is that it is *one* place everyone points at.

Anchored on the prime meridian at longitude 0, following the constellation's existing null-island convention, so nothing can be mistaken for a real location.

Composition is chosen so that each of the three acceptance-test apps has a home and each hard clause has something that exercises it:

| Feature | What it is | Why it is there |
| --- | --- | --- |
| **Vegetable blocks** | Six beds, drip irrigation, soil moisture at two depths per bed | The irrigation controller's home; depth and orientation history; the recalibration case |
| **Stock paddock** | Two water troughs, float sensors, a long mesh hop | The livestock water monitor's home; the freshness-priority backlog case |
| **Research plot** | Duplicated probes on one feature, full metadata | The research data logger's home; the cross-check flag; timestamp uncertainty that matters |
| **Hoop house** | Air temperature, humidity, good wifi | The contrast case — a link where store-and-forward never triggers, so the machinery must not depend on it |
| **Well, pump, tank, second pump** | One well with declared capacity, two draws | The shared-resource contention case: two modules, one well, no scheduler |
| **Weather station** | A local-API station (Ecowitt / WeatherFlow / Davis shape) | The inbound adapter path; a datastream layer zero did not originate |
| **Terrain and distance** | Enough spread that one node is marginal and one is multi-hop | Makes mesh realism real rather than configured |

## The completeness matrix

The farm is complete when every row is live on it with meaningful data. Each row names the clause it exists to exercise, which is what makes this a gate on the spec rather than a feature checklist.

| Layer | Must show | Clause |
| --- | --- | --- |
| Identity | A node that rebooted mid-season and reset `seq`, with nothing lost or deduplicated away | §1 `boot` |
| | Observations whose `id` order differs from their `measured_at` order | §1 id-not-a-sort-key |
| Time | All five `clock_quality` values present, including one `none` node with an honest uncertainty | §2 |
| | A reading that sat in a buffer for days and still has a correct `measured_at` | §2 age-at-transmit |
| Data model | Every datastream as a raw/calibrated pair | §3.2 |
| | One series recalibrated mid-season, with superseded rows still present and exactly one live row per timestamp | §3.2 `supersedes` |
| | A backfilled reading that got the calibration in force when it was taken, not the current one | §3.2 |
| | A mobile or handheld reading that overrides its datastream's feature | §3.1 |
| Quality | One live instance of each flag: `stuck`, `out_of_range`, `rate_exceeded`, `suspect` | §3.3 — all four produced by [sim/drill.py](../sim/drill.py) |
| | A reading carrying two flags at once | §3.3 flag-set |
| | A person's override outranking a machine assertion, with the original still visible | §3.3 precedence |
| | A threshold retuned mid-season, with historical assertions unchanged and traceable to the old version | §3.3 |
| Devices | A soil probe drifting across a season; a battery dying; a sensor moved and reinstalled with dates | §4.1 — **done**: 28 devices registered with declared §8 capabilities, each with an `Installation` carrying feature, depth and dates. `bed6_shallow` is lifted mid-season and reinstalled deeper in bed2, which is the event that makes the siting history non-trivial — before it every installation was open and nothing exercised closing one. "Where was this probe, and how deep, when it took that reading" now has exactly one answer per instant, and an unclosed installation is reported as an overlap **And an installation is now checked against physics:** every bed probe reports soil temperature, and [sdk/siting.py](../sdk/siting.py) reads each probe's depth from when its daily peak arrives. `make siting` scores it against moves nobody logged |
| | A stale datastream whose last good reading is *not* flagged | §4.2 staleness-is-not-a-flag |
| | Battery and RSSI as ordinary datastreams with their own thresholds | §4.3 |
| Transport | A node in a three-day outage draining its backlog against a duty cycle | §5.3 |
| | Two nodes with opposite drain policies — fresh-first and chronological — both correct | §5.3 |
| | An evicted reading reported as a count and recorded as a gap | §5.3, §5.4 |
| | A batched message carrying several readings under one `seq` | §5.2 |
| | An unconfirmed link released by cumulative ack | §5.2 |
| | A measured airtime budget the fleet provably fits inside | §5.2 |
| Commands | Deferred from the first release, but exercisable in sim: a dry run naming the limit it would hit; a lost ack resolving to `unknown`; a retry with the same ID executing once; a capacity refusal when two modules want one well with no scheduler running | §6.3–§6.5 |
| Storage | A correction as a compensating event, with the original readable | §7.3 |
| | An offline edit conflict resolved by HLC where the wall clocks disagree | §7.4 — **done**: [sdk/records.py](../sdk/records.py), [sdk/edits.py](../sdk/edits.py). Two phones in bed 3, one clock six hours fast: an edit made after seeing another follows it though its clock says it is older; concurrent edits to the harvest's weight and the bed's boundary keep both values, are noticed into the log and resolved by a person; every replica agrees |
| | A grant issued, used, revoked — and the revocation not retracting what was already delivered | §7.6 — **done**: [sdk/sharing.py](../sdk/sharing.py). The research plot's two probes are shared with a partner mid-season; the grant covers what had arrived when it was made and nothing after (Q16), a delivery is taken, the grant is revoked, nothing more can be read, and the delivery already made stands |
| | A module that went down, missed events, and replayed them from its cursor | §7.5 — **done**: [sdk/subscribe.py](../sdk/subscribe.py). An irrigation-controller subscriber processes half the season and dies; an offline edit then syncs late and lands *behind* it in HLC order; the module resumes and receives everything it missed including that edit, nothing it had acknowledged twice, and nothing lost |
| Interop | A full export round-trip losing nothing, raw and assertions included | §7.6 — **done**: [sdk/export.py](../sdk/export.py), `make export`. A season exports to a JSONL archive plus per-type CSV plus a GeoJSON view, verifies against a checksummed manifest, and replays into a byte-identical event list and a state that validates clean. Losslessness is measured per cell, not claimed |
| | A SensorThings 1.1 endpoint validated against FROST-Server | §10 — **done**: documents accepted at full key parity ([notes/frost-validation.md](notes/frost-validation.md)), and served over HTTP from [server/](../server/) with `$filter`, `$expand`, `$orderby`, `$select`, `$top`/`$skip` and paging. **QGIS 3.44 reads it and maps it** — 56 datastreams, 5450 observations, 10 features with geometry ([notes/qgis-validation.md](notes/qgis-validation.md)) |
| Apps | All three acceptance-test apps running against the farm, unchanged | §15 |
| History | A full simulated season behind the trends: drift, weather, repairs | §9.2 |

A clause with no row is a clause nothing tests. A row with no producer is the lie doctrine 1 forbids.

## Relationship to campus_twin

`campus_twin` has solved a large part of this for buildings, and the overlap is real but narrower than it looks. It is a **buildings/BAS** platform: spatial backbone from walked ground truth, CMMS, work orders, HVAC diagnostics, vertical transport. The shared ground is the *sensing and transport half* — observations, device health, Meshtastic and Modbus connectors with emulators, store-and-forward spooling, fault injection, the virtual-site doctrine.

### Code may move, by copy and relicense

`campus_twin` is GPL-3.0, but it is **single-author** — every commit is the same copyright holder, and there is no CLA because there are no outside contributors. GPL-3.0 binds that project's downstream recipients, not its author, so the code can be relicensed at will. There is no license trap here; the only things that could create one are external, and they check out:

- **Dependencies ignore authorship.** The core of `campus_twin` is deliberately stdlib-only. The connectors fieldmesh wants are clean: `modbus_*` pulls nothing, and `meshtastic_bridge.py` needs `paho-mqtt` (EPL-2.0 or EDL-1.0, and EDL is BSD-3-equivalent) only for the live gateway path — the emulator and its tests need nothing. There is **no dependency on the `meshtastic` PyPI package**, which is GPL-3.0 and would have been a genuine obstacle whoever wrote the calling code.
- **Vendored third-party code** travels under its own license, so anything vendored must be checked file by file before it moves.

**Copying is not importing.** The constellation rule — every joint a published contract or a one-way read, no code imports across repos, each repo survives the others' absence — is an architectural convention about *runtime coupling*, and a vendored fork satisfies it completely. fieldmesh owning its own copy, free to diverge, is the rule working as intended. What the rule forbids is a path dependency or an import of `campus_twin`, which would make fieldmesh stop building when its sibling moved.

**Relicense in place first, then copy.** The tempting shortcut is to copy a GPL-3.0 file into fieldmesh and stamp it Apache-2.0. That works, but it builds a one-way valve: the Apache copy can flow back into campus_twin (Apache-2.0 is GPLv3-compatible), while later GPL-only improvements on the campus side cannot flow forward without relicensing again. Cheaper to relicense the genuinely shared files to Apache-2.0 **in their current home** — a header change each, and a permissive file inside a GPL-3.0 project is an ordinary arrangement — and then fork. Improvements then move in both directions forever.

### What is worth taking

| From campus_twin | For fieldmesh | Clause |
| --- | --- | --- |
| `mesh_emulator.py`, `meshtastic_bridge.py` | The first link driver and its emulator | §5.2, Q6 |
| `_ingest.py` — shared retry/auth/spool POST | Store-and-forward on the gateway side | §5.2 |
| `csv_replay.py` | The CSV adapter, and replay for the conformance suite | §9.2, §10 |
| `modbus_collector.py`, `modbus_emulator.py`, `modbus_rtu.py` | The wired driver that acts as the control in every debugging session | Q6 |
| `mqtt_bridge.py`, `mqtt_emulator.py` | The bus observations are published on | §5.1 |
| `test_metric_registry.py` — fails a change when a producer emits an unregistered metric name | The enforcement §3.4 needs: a URI from the vocabulary, never free text, checked by a test rather than by review | §3.4 |

That last row is the most valuable thing in the list, because it is the pattern that makes a vocabulary rule real instead of aspirational.

**Status: the relicensing is done and two files have moved.** The transport spine is
dual-licensed in its original home (`campus_twin/LICENSING.md`), and `sdk/spool.py` and
`sdk/modbus_rtu.py` are here under Apache-2.0 with tests. The rest is blocked on decisions
rather than on effort — chiefly Q5, because an emulator cannot emit a wire format that has
not been chosen. [sdk/PROVENANCE.md](../sdk/PROVENANCE.md) records what moved, what changed,
and what each remaining file is waiting for.

### Where the domains genuinely diverge

Worth knowing before a fork, because it predicts which files will rot. A building's BACnet point is permanently wired, addressed and mains-powered, with no airtime budget. A farm's soil probe moves between beds, carries install depth and orientation as data, and runs solar against a 1% duty cycle. The transport and emulator layers transfer well; anything that assumes a fixed, always-powered, always-reachable point will need rewriting rather than adapting. Fork and diverge is the right expectation, not fork and track.

**What transfers with no license question at all, because patterns are not code:** the canonical named fictional site, determinism via seed and `ts0`, the completeness matrix as a standing gate, fiction-first defaults, an emulator beside every connector, the producer/detector doctrine, scored fault drills with ground truth, and the `.site/` convention.

**One question worth deciding deliberately** rather than by drift: whether the *sensing contract* — observation, datastream, device health, quality assertion, transport message — should eventually be extracted as a third artifact both repos read, or whether the two stay parallel with separate vocabularies. Parallel is right for now; both are young enough on the farm side that premature unification would bind fieldmesh to a buildings-shaped model. Revisit once fieldmesh's contract has survived its own first season.

## Site data

Adopt the sibling convention unchanged: a gitignored `.site/` directory, one subdirectory per farm, treated like a `.env`, never committed. Real farm data — field boundaries, well logs, contacts, photographs, certification records — is exactly the material that must not end up in a public repo, and a farmer's trust in that is not recoverable once broken.

## Build order

1. ~~**The data model and the log**, with no devices at all — the contract as code, plus the append-only and supersession tests.~~ **Done** — [sdk/](../sdk/), 116 tests. The four clauses v0 got wrong each have a regression test class: recalibration appends, calibration is selected by `measured_at`, quality is an assertion with precedence, and ordering prefers a node's counter over its clock.
2. ~~**`sim_physics` equivalent**: soil moisture responding to weather, irrigation and evaporation; a trough draining as stock drink.~~ **Done** — [sim/physics.py](../sim/physics.py), 29 tests. A seeded seasonal climate with clustered rain, a single-layer soil water balance with FAO-56-flavoured stress and drainage, and a trough whose float valve can stick shut — which empties 400 L by mid-afternoon on a July day and stays dry through the heat.
3. ~~**Simulated nodes over a simulated link**, with the airtime budget as exact arithmetic that fails loudly when a fleet reports too often.~~ **Done** — [sim/node.py](../sim/node.py) and [sim/link.py](../sim/link.py), 60 tests. The node samples, buffers, restamps at transmit, packs to the payload budget, evicts with a reported count, resends under its original sequence number, and defers rather than drops when the duty cycle is spent. The link loses, delays, duplicates, drops acknowledgements and goes out entirely — all seeded. Three spec defects came out of putting the two together.
4. **The fault library**: drift, flatline, out-of-range, clock skew, reboot, outage, backlog eviction, dropped and repeated messages. *Mostly built — [sim/faults.py](../sim/faults.py), 21 tests. Injectable: drift, sticking, bias, noise, death, out-of-range, plus a stuck float valve and the link's loss, delay, duplication and outage. [sim/test_world.py](../sim/test_world.py) scores them against ground truth including the half that is easy to forget — **a healthy farm must stay quiet** — which caught two threshold defects the moment it was written. Clock skew is deliberately absent: §2 reports ages, so a constant offset cancels, and `test_faults.py` demonstrates that rather than asserting it. What remains is a scored drill (step 6), not more producers.*
5. ~~**Harrow Bend assembled**, deterministic, with the completeness matrix enforced as a test.~~ **Done** — [sim/harrow_bend.py](../sim/harrow_bend.py) builds it from a seed, and [sim/test_harrow_bend.py](../sim/test_harrow_bend.py) runs one test per matrix row over a shared season; three rows are skipped, each saying why.
6. ~~**A scored drill**: seed a fault, show the farmer-facing symptom, score the health check's verdict against ground truth.~~ **Done** — [sim/drill.py](../sim/drill.py), 17 tests, `make drill`. Precision, recall, false-alarm rate on clean readings and latency from onset, scored against `Sensor.injected()` which the checks cannot reach. Its first run found a unit error worth more than the drill cost to build.
7. **One real link and one real device driver**, validated against the sim's expectations. *Half-started from the other end — the clients are real even though the devices are not. [server/](../server/) serves SensorThings 1.1 over HTTP, and QGIS 3.44 and Fraunhofer's `frost-sta-client` both read it; between them they found five defects no internal test could reach ([notes/qgis-validation.md](notes/qgis-validation.md)). What remains is the device side: a real radio and a real sensor. Until then, a real device's live stream: McAllister Farm's NRCS SCAN station is read into a layer-zero log every six hours by [tools/scan_collect.py](../tools/scan_collect.py), and its first week found a default that was wrong on live data and a probe that is ([notes/scan-live.md](notes/scan-live.md)).*
8. **Then the pilot farm**, with the apps already working and the contract already exercised.

Steps 1–6 need no hardware, no farm and no permission, which is the point. Steps 7–8 are where [open-questions.md](spec/open-questions.md) Q1, Q5 and Q6 stop being deferrable — and Q5 in particular becomes decidable by measurement at step 3 rather than by argument.
