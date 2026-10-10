<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Is public data enough to really test this?

Researched 2026-10-07, after testing the APIs rather than reading about them.

**Short answer: it validates about half of layer zero, and the half it cannot touch is
the half we claim is novel.**

The data model and the quality checks can be scored against real sensors with real
faults, for free, over decades. The transport contract — store-and-forward, the duty
cycle, batching, eviction, deduplication, cumulative acknowledgement — cannot be tested
by any public dataset, because every archive has already thrown that layer away. A
harmonised hourly series is what survives *after* the problems §5 exists to solve.

## What is usable, in order of value

### 1. ISMN — the one that matters

The **International Soil Moisture Network** hosts **71 networks and 2,842 stations**
with data from **1952 to the present**, the longest continuous records running about
forty years. SCAN, SNOTEL, USCRN, ARM and COSMOS all contribute, so US and Tennessee
coverage comes with it. Free with registration, **CC-BY-4.0**, with an MIT-licensed
Python reader (`ismn`) that exposes measurements and their flags as pandas columns.

Four properties make it the right validation set, and the first is decisive:

- **Flagged values are retained, not deleted.** "Measurements that are detected as
  erroneous by the quality control procedures are not deleted from the database but
  tagged as such." That is the difference between a labelled fault dataset and a list
  of holes.
- **The flag vocabulary maps onto §4.2.** `C` flags are observations exceeding a
  plausible geophysical range — `C01` soil moisture below 0 m³/m³, `C02` above 0.6,
  `C03` above the saturation point — which is precisely our `out_of_range`. `D` flags
  are questionable or dubious observations from consistency and spectrum-based checks,
  the family our flatline and rate checks belong to. `M` is missing, `G` is good.
- **Units already match.** Everything is converted to volumetric soil moisture in
  m³/m³, which is our `cm3/cm3` exactly — the same quantity, the same UCUM code, no
  conversion and therefore no conversion error.
- **Harmonised to hourly UTC**, which §2 wants anyway.

What this buys, concretely:

- **Score the range check on real data.** ISMN's `C` flags are an independent
  judgement about the same readings. Precision, recall and false-alarm rate against
  them is a real measurement, not a measurement against our own fixtures.
- **Test the quality model's expressiveness.** Mapping `C01`–`C03` and `D01`–`D10`
  into §3.3's flag set is a concrete interop exercise, and if the mapping is lossy
  that is a finding about our model rather than about theirs.
- **Set thresholds from forty years instead of from guesswork.** The canonical farm had
  to invent `min`, `max` and `max_rate_per_s`; §4.2 now says a rate threshold derives
  from the fastest legitimate process, and this is where that number comes from.
- **Real drift.** Forty-year records at some stations contain the slow failures the
  drills showed a single probe cannot see.

### 2. SCAN directly, via the NRCS AWDB REST API

Tested on 2026-10-07, no token:
`https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/`, OpenAPI documented.

Three Tennessee stations — Allen Farms (Giles), McAllister Farm (Lincoln), Eastview
Farm (Franklin) — soil moisture and temperature at 2, 4, 8, 20 and 40 inches, hourly
through monthly, since June 2003, live to the current day, with QC and QA flags. The
element code carries its depth: `elements=SMS:-2`, not `elements=SMS`.

**But SCAN deletes rather than tags.** Measured over 22 years of daily 8-inch readings
across the three stations: 23,240 readings, of which 686 carry `qcFlag=S` for
suspect — and the suspect count equals the missing-value count exactly. Asking for
`returnOriginalValues=true` returns neither a value nor an original for those rows.
Thirteen readings are `E` for estimated and do carry values.

So SCAN gives **labelled gaps, not labelled bad values**: useful for §5.4's gap
handling and §4.2's staleness, useless for scoring a value-based check. It is still
the best source of regional threshold evidence, and its live endpoint is the simplest
thing to point an ingest adapter at.

### 3. Small datasets with real, documented faults

- **AquaIntel** (IEEE DataPort) — 3,886 multi-sensor readings from an IoT edge node
  built for irrigation and anomaly detection, with per-timestamp ground-truth labels,
  **a real sensor-displacement fault where a level probe lost contact**, and a runaway
  pump event ending in total saturation. Small, but the faults actually happened.
- A published **fault-injected soil moisture dataset** covering **drift, bias, spike
  and malfunction** — independently the same taxonomy as `sim/faults.py`, which is
  reassuring about the fault library and means the two are comparable.
- **myClim's `mc_prep_TMSoffsoil`** — a published R detector for out-of-soil
  measurements from TMS loggers. A probe lifted out of the ground is the exact case our
  person-override example uses, and here is somebody else's detector for it to compare
  against.

### 4. The Tennessee Mesonet, when it exists

95 stations, one per county, the same five depths, **five-minute cadence**, real-time
and public, half due operational by the end of 2026. Unlike SCAN's hourly, five
minutes is inside §4.2's cross-check window, so a station in the pilot's county is a
genuine peer.

## What no public data can test

Everything the transport contract claims, which is most of what is distinctive here:

| Clause | Why an archive cannot test it |
| --- | --- |
| §5.2 duty cycle, batching, payload budget | The frames are gone; only the harmonised series survives |
| §5.3 buffering, eviction, drain order, the resend horizon | Same |
| §5.2 cumulative acknowledgement and abandoning a permanent hole | Same, and this was the subtlest bug the sim found |
| §1 `(site, node, boot, seq)` deduplication, reboots, wrap | Sequence numbers do not survive ingest |
| §2 transmit-time age stamping | Archives carry timestamps, not ages |
| §6 the command contract | Nothing public commands anything |
| §7.5 subscriptions, §7.6 grants and export | Ours to build |
| Whether a farmer trusts the result | Only a season on a farm |

This is the honest shape of it: **public data validates the half of layer zero that
looks like everyone else's, and cannot touch the half that is the reason the project
exists.** The simulated farm covers the transport half, and §9.2 is right that a
simulator is not a season.

## What to do about it

1. **A scoring run against ISMN.** *Done 2026-10-08 — see [ismn-scoring.md](ismn-scoring.md): 2.8 million Tennessee readings, the checks quiet in the root zone, and two real defects found (Q23, Q24).* `tools/ismn_score.py`, the ag counterpart of the
   HVAC fault-detection scoring in `campus_twin`: load an ISMN download, map its flags
   into §3.3's, run `sdk/checks.py` over the real series, and report precision, recall,
   false-alarm rate on `G` rows, and per-episode detection. Skips cleanly when the
   download is absent, like every other optional stage. This is §9.2's "replay of real
   recorded field data", and it is the strongest validation available without hardware.
2. **An ISMN flag mapping**, written down. If §3.3 cannot express `C03` (above
   saturation, which needs a per-soil saturation figure the datastream does not carry)
   then that is a gap worth knowing about.
3. **Derive the thresholds the canonical farm invented** from ISMN statistics, and say
   in the spec where each number came from.
4. **Leave the transport half to the sim and the pilot.** Do not pretend an archive
   tested it.

## Caveats

- ~~ISMN was not downloaded~~ *(resolved 2026-10-08: downloaded, and the flag vocabulary verified against the archive — it matched)*. Originally: `ismn.earth` refused the connection from here, so the flag
  semantics above come from the HESS paper and the ISMN documentation rather than from
  the data. **Verify the flag vocabulary against an actual download before building the
  scorer**, and check how many `C` and `D` rows the Tennessee SCAN stations actually
  carry — a flag family that is rare in practice scores nothing.
- CC-BY-4.0 requires attribution, and ISMN asks for citation of the network papers.
- The AquaIntel and fault-injected datasets were found by search and not inspected.
- Scoring our checks against another system's QC flags measures *agreement*, not
  correctness. Where we disagree with ISMN, either could be right, and the honest
  report says so rather than treating their flags as truth.

## Sources

- [ISMN: serving Earth system science for over a decade (HESS 2021)](https://hess.copernicus.org/articles/25/5749/2021/) · [ISMN quality flags](https://ismn.earth/en/data/ismn-quality-flags/) · [ISMN flag overview](https://ismn.earth/en/data/flag-overview/) · [ISMN data](https://ismn.earth/en/data/) · [TUW-GEO/ismn Python reader (MIT)](https://github.com/TUW-GEO/ismn)
- [NRCS AWDB REST API](https://wcc.sc.egov.usda.gov/awdbRestApi/swagger-ui/index.html) · [R {awdb}](https://cran.nics.utk.edu/cran/web/packages/awdb/index.html) · [Python soildb](https://py-soildb.readthedocs.io/en/latest/awdb.html)
- [AquaIntel multi-sensor IoT telemetry dataset](https://ieee-dataport.org/documents/aquaintel-multi-sensor-iot-telemetry-smart-water-management-anomaly-detection) · [Fault detection in smart farming, drift/bias/spike/malfunction](https://ejournal.nusamandiri.ac.id/index.php/jitk/article/view/7481) · [myClim mc_prep_TMSoffsoil](https://rdrr.io/cran/myClim/man/mc_prep_TMSoffsoil.html) · [Self-supervised anomaly detection of rogue soil moisture sensors](https://cdnjs.deepai.org/publication/self-supervised-anomaly-detection-of-rogue-soil-moisture-sensors)
- [NCSMMN partner networks](https://www.drought.gov/drought-in-action/ncsmmn-partner-networks)
