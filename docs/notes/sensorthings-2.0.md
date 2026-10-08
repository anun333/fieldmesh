<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# What the SensorThings 2.0 draft looks like

Read Oct 7, 2026, against the editor's rendering of OGC 23-019 and the published 1.1 standard (OGC 18-088). Written to answer one question: what changes for layer zero, and does it change the decision to ship on 1.1.

> **Snapshot caveat.** The copy read here is stamped **Version 0.1, submission date 2025-11-26**, with approval and publication dates still `XXXX-XX-XX` and the standard draft notice attached ("This document is not an OGC Standard"). Repository activity suggests later revisions exist, so treat specific attribute names below as true of this snapshot and re-check before implementing.

## Status

| | |
| --- | --- |
| Document | OGC 23-019, *OGC SensorThings API 2.0* |
| Editor | Hylke van der Schaaf |
| Version read | 0.1, submitted 2025-11-26 |
| Approval / publication | Not yet — both dates are placeholders |
| Public comment | 19 Dec 2025 – 18 Jan 2026, via issues on the OGC SensorThings GitHub repository |
| Expected publication | 2026 |

The acknowledged contributors are worth noticing: BRGM, Datacove, Fraunhofer IOSB, the OGC/WMO Water Quality IE, the OGC GeoTech IE, OneWater, Secure Dimensions, SensorUP, Universitat Autònoma de Barcelona (CREAF), the University of Calgary, and the Water4All partnership. This is a hydrology, water-quality and environmental-monitoring revision, not an IoT-vendor revision — which explains both its strengths for a farm (sampling, features of interest) and the one thing it drops.

## The two structural changes

**1. The result structure moves into SWE-Common.** A Datastream no longer declares `observationType` and `unitOfMeasurement`. It declares:

- `resultType` — a SWE-Common JSON description of the result structure (`JSON_Object`, multiplicity 1)
- `resultEncoding` — the SWE-Common encoding of that structure (`JSON_Object`, 0..1; defaults to JSON)

The unit of measure is now a field *inside* `resultType`, and `unitOfMeasurement` no longer exists as a Datastream attribute. Because SWE-Common can describe a structure covering several observed properties, **`MultiDatastream` is obsolete** and a Datastream may link to multiple ObservedProperties.

**2. Features are restructured.** `FeatureOfInterest` is renamed `Feature`, a new `FeatureType` entity carries type information, and the single mandatory Observation→Feature link becomes a three-way arrangement:

- `Datastream.UltimateFeaturesOfInterest` — the domain object: a river, a building, a plot of land
- `Datastream.ProximateFeatureOfInterest` — what is directly characterized
- `Observation.ProximateFeatureOfInterest` — now **optional**, and generally a sample

The draft's own example: in water quality the ultimate feature is the river, the proximate feature is a section or a specific point where samples are taken. It also explicitly covers the case where the observation's target is part of the Thing itself, giving a drone's battery level as the example.

## Entities

Nine: Thing, Location, HistoricalLocation, Datastream, Sensor, ObservedProperty, Observation, Feature, FeatureType.

## The Observation entity, in full

Table 17 — attributes:

| Name | Type | Multiplicity | Note |
| --- | --- | --- | --- |
| `id` | ANY | 1 | Read-only |
| `phenomenonTime` | TM_Object | 1 | Mandatory, but a client may omit it on POST because "many resource-constrained sensing devices do not have a clock" |
| `result` | ANY | 1 | "The estimated value of an ObservedProperty from the Observation" |
| `resultTime` | TM_Instant | 0..1 | Now optional; in 1.1 it was mandatory-but-nullable |
| `validTime` | TM_Period | 0..1 | The period during which the result may be used |
| `properties` | JSON_Object | 0..1 | Renamed from `parameters` |

Table 18 — relations: `Datastream` (1), `ProximateFeatureOfInterest` (Feature, 0..1).

`TM_Object` encodes as a complex type with a mandatory `start` and an optional `end`, so one type covers both an instant and an interval.

### The finding that changes our spec: no `resultQuality`

**SensorThings 1.1 has it.** Its Observation table defines `resultQuality` — "Describes the quality of the result" — typed `DQ_Element`, multiplicity **zero-to-many**. A structured, repeatable quality element: exactly the right home for a set of quality assertions.

**The 2.0 draft does not.** Table 17 above is the complete attribute list. The strings `resultQuality` and `DQ_Element` appear **nowhere** in the document. This is not an extraction artifact — the property tables parse cleanly as text, `validTime` and `parameters` are both found, and the Datastream table extracts in full.

Consequences for layer zero:

- Under **1.1**, the live quality assertion maps natively onto `resultQuality`, and the zero-to-many multiplicity even accommodates the flag-set model directly.
- Under **2.0**, it has to travel in `properties` alongside `received_at`, `seq` and `clock_quality` — a generic extension bag whose documented purpose in 1.1 was "environmental conditions during measurement". It works, but a standards-aware client has no way to know quality is in there.
- This is worth raising with OGC while the standard is unpublished. See [open-questions.md](../spec/open-questions.md) Q18.

### The second finding, stated fairly: tasking lives in a different document

The words *tasking*, *ControlStream*, *actuation* and *command* do not appear in the 2.0 draft. That is **not a regression**, and it would be wrong to read it as one: tasking was never in Part 1. It has always lived in a separate document, *SensorThings API Part 2 — Tasking Core* (OGC 17-079r1), and 1.1's Part 1 has no tasking either. 23-019 is a Part 1 / Sensing revision, so the absence is exactly what the document's scope implies.

What is genuinely unknown is whether Part 2 gets a 2.0 revision, and nothing in 23-019 commits to one. So the practical position is unchanged: the command contract in [v0.1 §6](../spec/v0.1.md) aligns to Part 2 Tasking Core as it stands, or to OGC API — Connected Systems Part 2, whose ControlStreams are published and purpose-built. That is Q3b, and the 1.1-versus-2.0 choice does not bear on it.

## The Datastream entity

Changes from 1.1: `resultType` and `resultEncoding` added; `unitOfMeasurement` and `observationType` removed; `definition` added; `description` now optional; `observedArea`, `phenomenonTime` and `resultTime` server-generated and 0..1; `properties` 0..1. Relations: `Thing` (1), `Sensor` (1), `ObservedProperty` (now potentially several), plus the two Feature links.

## API-level changes

- **OData 4.01 alignment**, with an explicit disclaimer: "The OGC SensorThings API v2 interface is not an OData interface and does not claim to be an OData service. It specifies a subset of the OData 4.01 specification and extends it."
- **A `$metadata` endpoint** is added for service inspection, and is where an implementation advertises its extensions.
- **Annotations are renamed:** `@iot.id` → `id`, `@iot.selfLink` → `@id`, `@iot.navigationLink` → `@navigationLink`.
- **Deep update semantics are inverted.** In 1.1, a deep update *added* the specified entities to a collection; in 2.0, following OData 4.01, it *replaces* the list of related entities. This is the kind of change that silently destroys data in a client written against 1.1.
- Query options are unchanged in spirit: `$select`, `$expand`, `$filter`, `$top`, `$skip`, `$orderby`, `$count`.

## Units

`UCUM` appears in 2.0 only in the abbreviations list. The normative statement lives in 1.1, whose `unitOfMeasurement` is a JSON object of `name`, `symbol` and `definition` whose values "SHOULD follow the Unified Code for Unit of Measure (UCUM)". In 2.0 the unit moved inside SWE-Common's structure description, which carries UCUM codes in its own unit-of-measure field. So UCUM remains the answer in both versions; only its location changes. This is why [v0.1 §3.4](../spec/v0.1.md) treats UCUM as an alignment rather than a preference.

## Mapping table for layer zero

| Layer zero field | SensorThings 1.1 | SensorThings 2.0 draft |
| --- | --- | --- |
| `measured_at` | `phenomenonTime` | `phenomenonTime` |
| `measured_at_uncertainty` | `parameters` | `properties` |
| `received_at` | `parameters` | `properties` |
| `seq`, `boot`, `clock_quality` | `parameters` | `properties` |
| `result` | `result` | `result` |
| Quality assertion | **`resultQuality`** (`DQ_Element`, 0..\*) | `properties` — no equivalent |
| `calibration`, `supersedes`, `provenance` | `parameters` | `properties` |
| Datastream `unit` | `unitOfMeasurement.definition` (UCUM) | inside `resultType` (SWE-Common, UCUM) |
| Datastream `feature` | — (feature was per-Observation) | **`UltimateFeaturesOfInterest`** |
| Observation `feature` override | `FeatureOfInterest` (mandatory) | `ProximateFeatureOfInterest` (optional) |
| Raw vs derived datastream | Two Datastreams | Two Datastreams |
| Device health (battery, RSSI) | A Datastream on the sensor's Thing | Same, and explicitly blessed |

Two things in the 2.0 model are better fits for layer zero than 1.1:

- **Feature on the Datastream.** [v0.1 §3.1](../spec/v0.1.md) moves the feature to the datastream with a per-observation override, which is precisely the ultimate/proximate split. Under 1.1 that has to be expressed by repeating the feature on each observation.
- **Observations on the Thing itself.** [v0.1 §4.3](../spec/v0.1.md) makes battery and signal into ordinary datastreams; 2.0 names that case explicitly.

Neither is a reason to wait for 2.0. Both mean the 2.0 migration will *simplify* the adapter rather than complicate it.

## Will vendors move to 2.0, and does it matter?

They will, eventually. It costs us almost nothing, for four reasons.

**1. The reference implementation already serves both at once.** FROST-Server — Fraunhofer IOSB's server, the most widely deployed open-source STA implementation, from the same institute as the 2.0 editor — has shipped both a 2.0 data-model plugin and a 2.0 API plugin since version 2.8.0, **both disabled by default**. Its documentation notes that the two API plugins can be enabled simultaneously, while only one data-model plugin can. So the expected deployment pattern for the whole ecosystem is one data model serving two API versions side by side. Dual-serving is not a workaround; it is how the reference implementation is built.

**2. We are a server, not a client.** The SensorThings adapter is out-only ([v0.1 §10](../spec/v0.1.md)). A client consuming vendor feeds is bound by the vendor's version choice; a server publishing data is not — clients adapt to servers. We can expose `/sta/v1.1/` and `/sta/v2.0/` from one internal model, and the internal model is richer than both.

**3. The migration will be slow for everyone, because 2.0 breaks clients.** Annotation renames (`@iot.id` → `id`), inverted deep-update semantics, `MultiDatastream` removal and the `resultType` restructuring each break existing clients independently. SensorThings' installed base is national environmental monitoring networks, water and hydrology services, smart-city platforms and research infrastructure — none of which migrate quickly, and all of which will keep 1.1 endpoints running for years.

**4. 2.0's direction suits us better, not worse.** Feature on the Datastream and observations whose target is part of the Thing itself are both things [v0.1](../spec/v0.1.md) does and 1.1 makes awkward. Wider 2.0 adoption makes our model more natural to express, not less.

### Who the vendors actually are

Worth separating two meanings of "vendor", because they pull in opposite directions:

- **Sensor and farm-software vendors** — Meter Group, Sentek, Acclima, Davis, Ecowitt, Campbell Scientific, the major farm-management platforms — almost universally do **not** speak SensorThings. They expose proprietary APIs or cloud portals, and where agriculture has interop standards they are ISOBUS/ISOXML and the ADAPT/AgGateway family. These vendors reach us through the device-driver layer and the weather-station adapters, and the SensorThings version is irrelevant to them.
- **Data consumers** — GIS tools, QGIS plugins, research data infrastructure, environmental monitoring networks, university partners. These are the ones who read a SensorThings endpoint, and these are who the adapter is for.

So the version question is not "what will our hardware suppliers adopt". It is "what will the research and GIS tools that read our data support", and the answer is both, for a long time.

### The one genuine exposure

If 2.0 becomes the norm with no structured quality field, our quality assertions become non-standard precisely when the data most needs to be credible to an outsider — a researcher, a certifier, a buyer. That is the argument for raising it now rather than later, and the constituency already exists inside the 2.0 contributor list: water-quality and hydrology programmes are built on QA/QC flags. See Q18.

## Verdict: ship on 1.1

- It is published; 2.0 is an unapproved draft whose attribute names are still moving.
- 1.1 has `resultQuality`, which the quality model needs and which 2.0 currently drops.
- Neither version carries tasking, so the command contract is unaffected by the choice.
- The differences are confined to serialization — attribute names, the annotation prefixes, where the unit lives — so one thin adapter layer absorbs the migration. Keep that layer separate from the data model from the first commit, and 2.0 becomes a day's work rather than a refactor.

## Sources

- [OGC SensorThings API 2.0 draft (23-019), editor's rendering](https://hylkevds.github.io/23-019/23-019.html)
- [OGC SensorThings API Part 1: Sensing 1.1 (18-088)](https://docs.ogc.org/is/18-088/18-088.html)
- [OGC public comment request for SensorThings 2.0](https://www.ogc.org/requests/ogc-seeks-public-comment-on-proposed-ogc-sensorthings-api-version-2-0/)
- [OGC SensorThings standard page](https://www.ogc.org/standards/sensorthings/)
- [OGC announcement: publication of OGC API — Connected Systems](https://www.ogc.org/announcement/ogc-announces-publication-of-ogc-api-connected-systems-and-updates-to-supporting-standards/)
- [OGC API — Connected Systems](https://csapi.developer.ogc.org/)
- [FROST-Server changelog, v2.x branch](https://github.com/FraunhoferIOSB/FROST-Server/blob/v2.x/CHANGELOG.md) — 2.0 data-model and API plugins, added in 2.8.0, disabled by default
- [FROST-Server plugin settings](https://fraunhoferiosb.github.io/FROST-Server/settings/plugins.html) — both API plugins may be enabled at once; only one data-model plugin
- [FROST-Server project page, Fraunhofer IOSB](https://www.iosb.fraunhofer.de/en/projects-and-products/frost-server.html)
- ["The State of OGC SensorThings API", FOSS4G 2026](https://talks.osgeo.org/foss4g-2026/talk/QSFUVY/)
