<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Spikes and jumps on real soil

**2026-10-08.** Open question [Q23](../spec/open-questions.md) found that §4.2's rate check
cannot fire at hourly sampling — it caught none of 1,849 readings ISMN flags as spikes or
jumps at the three Tennessee stations — and recommended detecting the *shape* of a spike
rather than the size of a step. That recommendation had not been tested. This note tests it
on every SCAN soil-moisture probe in the top 21 cm in the ISMN archive.

| | |
| --- | --- |
| Probes | 1,797, at every SCAN station, 5–20 cm |
| Record | 11,520 probe-years, hourly; 71.7 million readings ISMN rates good |
| ISMN events | spike (D06) 188,697; negative jump (D07) 5,575; positive jump (D08) 21,251 |
| Tool | [tools/ismn_spikes.py](../../tools/ismn_spikes.py) |

An *event* is a run of flagged readings; a detector catches it if it flags any reading in
it, or one either side, because ISMN marks a region. This measures agreement, not
accuracy — and the first finding is that for spikes, agreement is the wrong target.

## ISMN's "spike" is not a glitch

The step into a D06-flagged reading has a **median of 0.005 m³/m³** — smaller than ordinary
hour-to-hour noise. ISMN describes the test as spectrum-based; in the data it behaves like
a relative one, firing on wiggles in dry soil, where a 0.005 change is 15% of the
reading. Typical D06 readings look like `0.032 0.037 0.038 0.029*
0.036`, at 0.03 m³/m³. It does sometimes mark a real dip (`0.289 0.287 0.220* 0.286`), and
any shape detector catches that one. But no glitch detector will "agree" with D06, and none
should try.

ISMN's jumps are another matter. The step into a D07 reading is a fall in 5,694 of 5,749
cases, median **0.084**; into a D08 reading, a rise in 21,193 of 21,251, median 0.074.

## Soil fills fast and empties slowly

One-hour steps between two readings ISMN rates good, by sign:

| | count | 99th | 99.9th | 99.99th | 99.999th |
| --- | --- | --- | --- | --- | --- |
| rises | 42.5 million | 0.014 | 0.073 | 0.176 | 0.271 |
| falls | 27.7 million | 0.013 | **0.032** | 0.109 | 0.254 |

Water arrives by infiltration, which can be fast; it leaves by drainage and evaporation,
which are slow. At the 99.9th percentile a fall is less than half the size of a rise. So a
cap on *falls* can be much tighter than any cap on steps — though the extreme tails
converge, and some of the healthy-rated extremes are themselves glitches (below).

## The candidates

| detector | D06 | D07 | D08 | flags on good readings per probe-year | median probe | probes never flagged | share from the worst 5% of probes | at 2 h | at 3 h |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **spike** ≥ 0.05, out and back in one sample | 1% | 21% | 0% | **0.46** | 0 | 77% | 85% | 0.41 | 0.34 |
| spike ≥ 0.03 | 2% | 22% | 0% | 1.00 | 0 | 62% | 75% | 0.79 | 0.69 |
| **fall** > 0.05 per hour | 1% | **61%** | 0% | 1.21 | 0 | 56% | 66% | 0.34 | 0.16 |
| fall > 0.03 per hour | 2% | 66% | 0% | 3.20 | 0.48 | 37% | 52% | 0.81 | 0.39 |
| fall > 0.05 from a steady level | 0% | 28% | 0% | 0.29 | 0 | 78% | 76% | 0.15 | 0.10 |
| rise > 0.17 per hour | 0% | 5% | 12% | 0.40 | 0 | 55% | 48% | 0.01 | 0.00 |
| rise > 0.25 per hour | 0% | 1% | 3% | 0.06 | 0 | 85% | 69% | 0.00 | 0.00 |
| §4.2's rate check today | — | 0 of 1,849 Tennessee spikes and jumps | | | | | | | |

A *spike* leaves both neighbours by at least the threshold, in the same direction, and its
neighbours agree to within 30% of the excursion. A *fall* or *rise* cap scales with the gap
up to three hours; beyond that nothing is decided. "From a steady level" means no rise of
0.02 in the six hours before. The 2 h and 3 h columns re-score every probe at those
intervals.

- **A shape spike check is quiet on healthy probes and does not degrade with the
  interval.** At 0.05 it raises 0.46 flags per probe-year on readings ISMN rates good, but
  the median probe is never flagged, 77% of probes never are, and 85% of the flags come
  from the worst 5% of probes. At 2- and 3-hourly sampling its rate falls slightly, as
  some glitches fall between samples, rather than rising. That is the property Q23 asked
  for.
- **A cap on falls catches most of ISMN's negative jumps.** At 0.05 per hour, 61% of D07
  events, with the median probe again never flagged. Requiring a steady level first
  quarters the flags but halves what it catches: many of ISMN's negative jumps come
  within six hours of a rise.
- **Rises cannot be told from rain** without a rain gauge. A rise cap catches few of
  ISMN's positive jumps at any setting. Scaled with the gap, as these are, it goes blind at
  3-hourly sampling: the Q23 defect again, in miniature.

## What the shape check finds that ISMN rates good

The "false" spike flags concentrate on a few probes, so those were inspected. They are
sensors that are plainly broken:

| probe | spikes on good readings | what the readings do |
| --- | --- | --- |
| Spickard — 5, 10 and 20 cm | 371–433 each, 2007 | flip between two levels hour by hour: `0.470 0.305 0.468 0.305 0.468` — a bistable logger or channel fault, at all three depths at once |
| Goshute — 20 cm | 818 in five years | swing 0.1–0.3 every hour: `0.472 0.427 0.481 0.216 0.463` |
| Orchard Range Site — 20 cm | 121 | a dead sensor reading 0.000, with occasional `0.265` |
| Mahantango Creek — 10 cm | 84, Oct–Nov 2017 | alternates `0.000 0.035 0.000 0.035` |
| McAllister Farm, Tennessee — 5 cm | the 2026 digital probe | `0.135 0.139 0.144 0.304 0.150`; `0.098 0.082 0.280 0.029 0.292` — the probe installed in February 2026, in its first summer |
| Tuskegee — 20 cm | 183, winters only | dips of 0.03–0.05 that return; the least clear case |

ISMN rates every one of these readings good. Why its detector passes them is not
established; a plausible reason is that a test judging change against a series' own
recent behaviour does not see a sensor that misbehaves all the time. A shape test judges
each excursion on its own.

## What it recommends

Recorded in [Q23](../spec/open-questions.md), still open:

- **A shape spike check at 0.05 m³/m³**, raising `rate_exceeded` (questionable). It
  needs the reading after the spike, so it judges each reading **one reading late**: when
  reading *n + 1* arrives, an assertion on reading *n* is appended — the same pattern the
  siting check already uses to flag past readings.
- **A cap on falls of 0.05 m³/m³ per hour**, raising `suspect` rather than
  `rate_exceeded`, because a wetting front draining at 5 cm can legitimately exceed it:
  Mammoth Cave, 5 cm, `0.286 0.334 0.430 0.370 0.335`, rated good.
- **No cap on rises** from the rate check for soil water; a per-step backstop is optional,
  and its behaviour at coarse sampling is unmeasured.

## Caveats

- **One network, one country.** SCAN, mostly Stevens Hydraprobes, hourly. Other sensors
  have other failure shapes.
- **Agreement, not accuracy, in both directions.** The examples show ISMN rating broken
  sensors good; they do not show that every flag on a good reading is a fault. Tuskegee's
  winter dips are unexplained.
- **The thresholds are absolute.** A 0.05 excursion is large in a sandy soil at 0.08 and
  small in a clay at 0.45. Whether a threshold relative to the probe's own range does
  better is unmeasured.

## Attribution

ISMN data is used under CC-BY-4.0; this note publishes only derived statistics and short
excerpts of individual readings. See [ismn-scoring.md](ismn-scoring.md#attribution) for
the citations. The SCAN stations are operated by the USDA Natural Resources Conservation
Service.

## Reproducing

```sh
cd /tmp
python3 -I ~/dev/librefarm/tools/ismn_spikes.py ~/Downloads/ISMN_archive_20261008.zip
```

About an hour: every probe is scored three times, at 1, 2 and 3 hours. The step
percentiles and the inspected examples were scratch analyses on the same archive.
