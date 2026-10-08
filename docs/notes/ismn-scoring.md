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

### Range disagreements are about porosity

ISMN's C03 — "above the saturation point" — uses saturation derived from the global HWSD soil
database. At McAllister Farm, 5 cm, that puts saturation at **0.427**: every C03 reading is
at or above it, and every good reading below. The flagged readings run from 0.427 to 0.492
and cluster in wet winters, while a silt loam's actual porosity is typically 0.45–0.50. Our
0.46 limit catches those above 0.46. Neither number knows this soil. The disagreement is over
the site's porosity, not over the sensor.

One sensor dominates the agreement figure: Allen Farms at 1.02 m reads above both limits for
60% of its record — a waterlogged subsoil or a calibration fault, and the data alone cannot
say which. Without it, range agreement is about 42%.

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

## Caveats

- **One region, one sensor make.** Three Tennessee stations, all Stevens Hydraprobes. The
  Q24 depth curve is one soil's; a sandy soil drains faster and a clay slower.
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
python3 -I ~/dev/librefarm/tools/ismn_score.py ~/Downloads/ISMN_archive_20261008.zip \
    --network SCAN --box 34.98,36.68,-90.31,-81.65
```

About 15 minutes for all 49 files. Run from a neutral directory with `-I`, because the
archive is downloaded data.
