<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Our health checks against ISMN's quality flags

**2026-10-08.** The §9.2 "replay of real recorded field data" that
[validation-data.md](validation-data.md) recommended, run for real: layer zero's §4.2 checks
over **2,792,596 hourly readings** from the three Tennessee SCAN stations, compared with the
quality flags ISMN assigned to the same readings.

**This measures agreement, not accuracy.** Where we and ISMN differ, either could be right —
and in the cases below where we looked closely, the disagreement turned out to be about the
soil rather than the sensor.

## What was scored

| | |
| --- | --- |
| Source | ISMN complete archive, downloaded 2026-10-08 — 6.3 GB, 49 GB uncompressed, read from the zip and never extracted |
| Stations | SCAN: Allen Farms (35.07, −86.89), Eastview Farm (35.14, −86.19), McAllister Farm |
| Sensors | 49 soil-moisture files, 5 cm to 1.02 m, Stevens Hydraprobe analog and digital, several replacements per position |
| Span | 2003 to 2026, hourly, UTC |
| Our thresholds | Harrow Bend's soil defaults — range 0.02–0.46, flatline 18 h, rate 0.00015/s — **not** ISMN's, or range agreement would be true by construction |
| Tool | [tools/ismn_score.py](../../tools/ismn_score.py) |

The flag vocabulary was verified against `ISMN_qualityflags_description.txt` inside the
archive before the reader was written, as the earlier note required. It matched the
documentation.

## Results

| ISMN family | readings | we flag | agreement |
| --- | --- | --- | --- |
| good (G) | 2,244,605 | 34,501 | — |
| plateau (D09, D10) | 276,884 | 84,584 | 31% |
| ancillary (D01–D05) | 207,437 | — | no counterpart |
| range (C01–C03) | 155,052 | 114,915 | 74% |
| break (D07, D08) | 1,494 | 0 | **0%** |
| spike (D06) | 355 | 0 | **0%** |

**After Q23** (decided 2026-10-08: spikes by shape, a cap on falls, no cap on rises), the
same Tennessee record scores: negative jumps (D07) **56%** (29 of 52), spikes (D06) 8% (27
of 355 — D06 mostly marks dry-soil noise, see [spikes-and-jumps.md](spikes-and-jumps.md)),
positive jumps (D08) 0% by design. The new checks raised 253 `suspect` and 49
`rate_exceeded` flags on the 2.24 million readings ISMN rates good — 0.013%.

What we raise on readings ISMN rates **good**, by depth:

| depth | good readings | stuck | out of range | share |
| --- | --- | --- | --- | --- |
| 5 cm | 480,097 | 123 | 171 | 0.06% |
| 10 cm | 501,525 | 409 | 961 | 0.27% |
| 20 cm | 503,143 | 106 | 0 | **0.02%** |
| 51 cm | 476,354 | 7,696 | 0 | 1.62% |
| 1.02 m | 283,486 | 25,035 | 0 | **8.83%** |

## What it means

### In the root zone, the checks hold up

In the top 20 cm — where an irrigation decision is made — our checks disagree with ISMN on
no more than 0.27% of the readings it rates good, and on 0.02% at 20 cm. That is the first
evidence on real sensors, rather than on the simulator, that the §4.2 checks are quiet when
nothing is wrong.

### Below that, the flatline check misfires — Q24

All the deep disagreement is `stuck`. The §4.2 amendment already says a flatline threshold
must exceed the *quantisation dwell*, how long a healthy probe repeats one value. Our 18 hours
was set from a shallow probe's overnight dwell. The archive shows the dwell grows with depth,
because water moves more slowly further down. Longest runs of one identical value among
readings ISMN rates good:

| depth | 99.9th percentile | longest |
| --- | --- | --- |
| 5 cm | 7 h | 105 h |
| 10 cm | 8 h | 103 h |
| 20 cm | 9 h | 29 h |
| 51 cm | 21 h | 157 h |
| 1.02 m | 63 h | 351 h |

Roughly exponential in depth, with an e-folding of about 0.44 m. Recorded as
[open-questions Q24](../spec/open-questions.md), recommending a depth-scaled default taken
from the §4.1 installation record, refined per series once a season of its own history exists.

### The rate check is blind at hourly sampling — Q23, confirmed

**Zero** of 1,849 readings ISMN flags as spikes or jumps. Predicted before the data arrived:
the 0.00015/s limit was set for 15-minute sampling and allows a single step of 0.54 m³/m³
over an hour. Real data now confirms it. ISMN's own D06 and D07/D08 readings are the
material to set a `max_step` from ([Q23](../spec/open-questions.md)).

### Range disagreements: the soil map sides with ISMN

ISMN's C03 — "above the saturation point" — uses saturation from the global HWSD soil
database, about 1 km resolution. At McAllister Farm, 5 cm, that puts saturation at
**0.427**: every C03 reading is at or above it, and every good reading below. The flagged
readings run from 0.427 to 0.492 and cluster in wet winters.

The USDA soil survey (SSURGO), mapped at field scale, settles it. McAllister Farm is
**Dickson silt loam**, whose top horizon saturates at **0.42**; Allen Farms is Hampshire silt
loam, also 0.42 near the surface; Eastview Farm is Decatur silty clay loam. So readings to
0.49 are above what the soil can physically hold, ISMN's flag is probably right, and our
generic 0.46 was too lenient. The likeliest cause is the probes' generic factory calibration
reading high in this soil — probes of this kind ship with one calibration whose accuracy
depends on the soil.

*Corrected twice.* A first draft called these soils silt loam, by assumption. A revision
"corrected" that to loam on the strength of HWSD's 50% sand and 25% clay, and argued the
disagreement was the database's porosity against ours. The field-scale survey says silt
loam and silty clay loam, and puts saturation where ISMN does. HWSD was wrong about the
texture, and the revision was wrong to trust it.

One sensor dominates the generic agreement figure: Allen Farms at 1.02 m reads above both
limits for 60% of its record. The soil survey says it sits in a horizon (76–119 cm) that
saturates at **0.30** — so whatever it is measuring, it is not reading that soil's water
content correctly. Without it, generic range agreement is about 42%.

### A starting range from the soil map

Replacing the generic 0.46 with each probe's soil-survey saturation at its own depth, plus
0.02:

| | generic 0.46 | from the soil map |
| --- | --- | --- |
| ISMN above-saturation readings caught | 74% | **89%** |
| readings ISMN rates good, flagged | 0.00% | 1.30% |

99% of that 1.30% is the Allen Farms 1.02 m probe, where the map and ISMN agree something is
wrong and the map is simply stricter. Without it, the map-derived limit flags **0.02%** of
good readings. A limit read off the soil map is a better starting point than any generic
number; [tools/soil_survey.py](../../tools/soil_survey.py) produces one for any US location
and depth.

### "Saturated plateaus" are mostly wet soil

ISMN's D10 runs at shallow depth last 40–69 hours and move through 7–12 distinct values:
soil sitting near saturation through a wet winter, not a frozen sensor. Our flatline, which
needs identical values, is right not to call them stuck. ISMN marks them questionable, not
bad. At depth, where values really are identical for days, both systems flag — which is where
the 31% plateau agreement comes from, and also where Q24's false alarms come from.

### What we cannot see at all, and one thing we could

D01–D05 use soil temperature, air temperature and precipitation, which a single moisture
series does not carry. **D01 — soil below 0 °C — is within reach:** capacitance probes read
only liquid water, so frozen soil reads falsely dry, and our soil probes now report
temperature on the same device (§4.1). A frozen-soil check is a candidate for §4.2. D04, a
rise with no rain, needs a rain gauge on the farm.

## Beyond Tennessee: soil texture, and the size of a jump

**The dwell depends on soil as much as on depth.** 99.9th-percentile run of one identical
value on good readings, in hours, for every humid-subtropical (Köppen Cfa) SCAN station —
87 stations, 1,720 probes — grouped by the **soil-survey texture at each probe's own depth**
(sandy ≥ 70% sand, clayey ≥ 35% clay, loamy otherwise; probe counts in brackets):

| depth | sandy | loamy | clayey |
| --- | --- | --- | --- |
| top 20 cm | 9 h (166) | 11 h (682) | 19 h (200) |
| 51 cm | 15 h (27) | 22 h (161) | 32 h (154) |
| 1 m | 22 h (29) | 40 h (179) | 64 h (123) |

The dwell grows with depth and with clay, cleanly in both directions. 18 hours is right for
sandy and loamy soil near the surface and wrong almost everywhere else. Q24 now recommends a
threshold learned from each series' own history, starting from this table looked up by the
soil survey; `tools/soil_survey.py` does the lookup.

**And climate, for sand.** The same measurement over every SCAN station with a climate
class and a soil-survey horizon at the probe's depth — 210 stations, by Köppen main class:

| depth | dry (B): sandy | loamy | clayey | temperate (C): sandy | loamy | clayey | cold (D): sandy | loamy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| top 20 cm | 14 h (126) | 7 h (410) | 8 h (31) | 11 h (214) | 11 h (799) | 19 h (202) | 10 h (35) | 12 h (154) |
| 51 cm | 32 h (37) | 25 h (126) | 28 h (17) | 23 h (44) | 21 h (207) | 31 h (160) | 17 h (8) | 24 h (68) |
| 1 m | **71 h** (38) | 34 h (103) | 45 h (28) | 27 h (42) | 38 h (202) | 58 h (128) | 16 h (13) | 38 h (59) |

63 dry, 113 temperate and 34 cold stations; probe counts in brackets; cold-climate clay
had five probes or fewer per cell and is left out. Cells under ten probes take the
temperate value in the tool. Temperate reproduces the Cfa table above and cold is
close to it. Dry climates reverse the ordering for sand: dry sandy soil sits unchanged
for days, so at 1 m it dwells longest of all. `tools/soil_survey.py` now takes the climate
class (`--climate B|C|D`); without one it uses the longest dwell any climate showed, so an
unknown climate errs towards quiet. 144 probes had no soil-survey horizon at their depth
and are not counted.

*An earlier version of this table was wrong twice.* It grouped stations by HWSD texture,
which misclassifies at field scale — it calls Tennessee's silt loams loam and Starkville,
Mississippi, 55% clay where the survey finds a sandy loam over 28%-clay loam. And a first
rerun had a bug in reading the climate class that dropped most stations, leaving 15. This
table replaces both.

**A spike is not a big step.** One hourly step in the top 20 cm, 8 million good readings:

| | median | 99th | 99.9th | 99.99th |
| --- | --- | --- | --- | --- |
| good | 0.001 | 0.016 | 0.069 | 0.167 |
| ISMN spike (D06) | 0.006 | 0.072 | 0.225 | 0.362 |
| ISMN jump (D07, D08) | 0.074 | 0.337 | 0.524 | 0.856 |

Healthy soil can rise 0.17 in an hour after heavy rain on sand, and ISMN's spike flags sit
mostly on small steps, because its detector marks the region around an excursion rather than
the jump. No step-size threshold separates these. Q23 was revised to recommend detecting the
*shape* — an excursion that returns within a sample or two, which rain does not do. That
has since been measured on every SCAN probe in the top 21 cm, in
[spikes-and-jumps.md](spikes-and-jumps.md): the shape check is quiet on healthy probes and
finds broken sensors ISMN rates good, a cap on *falls* catches most of ISMN's negative
jumps, and a cap on rises turned out not to be worth keeping.

## A second network: NOAA's Climate Reference Network

*Scored 2026-10-11.* The same archive carries NOAA's Climate Reference Network (USCRN).
In the same box it has five stations' worth of probes: Crossville in Tennessee, and two
at Asheville, on its North Carolina edge. That is 15 probes and 1.9 million readings.

USCRN is a different operator, with three probes at each depth and its own quality
control before ISMN's. The probes are Stevens Hydra Probe II on SDI-12, the same make as
SCAN's. The thresholds are the ones above, unchanged:

    python3 -I ismn_score.py ~/Downloads/ISMN_archive_20261008.zip \
        --network USCRN --box 34.98,36.68,-90.31,-81.65

| ISMN family | readings | we flag | agreement |
| --- | --- | --- | --- |
| good | 1,534,449 | 13,106 flags: stuck 10,994, suspect 1,009, rate 577, range 526 | — |
| plateau | 120,027 | 2,247 | 2% |
| range | 110,656 | 75,777 | 68% |
| spike (D06) | 571 | 298 | **52%** |
| fall | 133 | 67 | 50% |
| rise | 393 | 0 | 0% |

What we raise on readings ISMN rates good, by depth (the 1,009 `suspect` flags are not split by depth):

| depth | good readings | stuck | out of range | rate | share |
| --- | --- | --- | --- | --- | --- |
| 5 cm | 298,840 | 211 | 12 | 39 | 0.09% |
| 10 cm | 321,408 | 403 | 436 | 105 | 0.29% |
| 20 cm | 337,199 | 292 | 0 | 177 | 0.14% |
| 50 cm | 306,612 | 2,439 | 78 | 185 | 0.88% |
| 1 m | 270,390 | 7,649 | 0 | 71 | 2.86% |

* **The root zone holds up on a second operator's probes.** At 0.09% to 0.29% of good
  readings in the top 20 cm, it is within SCAN's 0.02% to 0.27%.
* **The deep disagreement is the same `stuck`**, and the flatline limit learned per soil
  and depth (Q24) is its answer, as on SCAN.
* **ISMN's spikes on USCRN are mostly real glitches.** The shape check agrees on 52% of
  them, against 8% on SCAN, where D06 mostly marked dry-soil noise.
* No rise is capped, by design (Q23).

## Caveats

- **One region, one sensor make, for the agreement figures.** The scoring is three
  Tennessee stations, all Stevens Hydraprobes. The dwell tables reach further — 210 United
  States stations across three climate classes — but are still one network's sensors.
- **ISMN's flags are not ground truth.** They are another automated system's judgement, with
  its own thresholds and its own soil database.
- **Our thresholds were Harrow Bend's**, chosen for a fictional farm before any of this data
  existed. That they hold in the root zone is evidence for them; that they fail at depth is
  the point of running this.

## Attribution

ISMN data is used under CC-BY-4.0; this note publishes only derived statistics, not the
data. The quality flags are described in:

> Dorigo, W.A., Xaver, A., Vreugdenhil, M., Gruber, A., Hegyiová, A., Sanchis-Dufau, A.D.,
> Zamojski, D., Cordes, C., Wagner, W., and Drusch, M. (2013). Global Automated Quality
> Control of In Situ Soil Moisture data from the International Soil Moisture Network.
> *Vadose Zone Journal* 12(3). doi:10.2136/vzj2012.0097

> Dorigo, W. et al. (2021). The International Soil Moisture Network: serving Earth system
> science for over a decade. *Hydrology and Earth System Sciences* 25, 5749–5804.

The SCAN stations are operated by the USDA Natural Resources Conservation Service.

## Reproducing

```sh
cd /tmp
python3 -I ~/dev/fieldmesh/tools/ismn_score.py ~/Downloads/ISMN_archive_20261008.zip \
    --network SCAN --box 34.98,36.68,-90.31,-81.65
```

About 15 minutes for all 49 files. Run from a neutral directory with `-I`, because the
archive is downloaded data.
