<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# A real station, live: McAllister Farm's SCAN feed

**2026-10-09.** Build step 7 wants a real device driver before hardware arrives. Q6's Plan B:
read a real station's live feed through layer zero, as a node's readings would arrive. The
NRCS Soil Climate Analysis Network station at McAllister Farm (2075:TN:SCAN) measures soil
water and temperature at 5, 10, 20, 51 and 102 cm, air temperature, rain and its own battery
every hour, and NRCS publishes each hour through its AWDB web service (public domain).

[tools/scan_collect.py](../../tools/scan_collect.py) reads the last few days and appends them
to a layer-zero log: a device and an installation at its depth behind each of the 13 series,
a raw datastream in the unit the station sends, a name for each, and every reading assessed
by the §4.2 checks as it lands. Soil-water series start from the soil survey's thresholds
for their own depth and texture (Q24). It is idempotent, and runs from cron every six hours
into `~/dev/fieldmesh-data/mcallister-scan.jsonl`, about 170 MB a year. To stop: delete its
line from `crontab -e`.

## What the first week showed

**The default flatline was wrong for two of the station's measurands.** Left to the default
— `stuck` after twelve identical readings, a count rather than a duration — the first week
flagged 413 healthy readings: a rain gauge that reads 0 every dry hour, and deep soil
temperature, which in whole °F holds one value for days. §4.2 already says a count-only
flatline is a trap; this is it, met on a live feed. Measured on three Tennessee stations over
two years (2023-10 to 2025-09), the longest healthy run of one soil-temperature value:

| depth | McAllister | Allen Farms | Eastview | flatline set at |
| --- | --- | --- | --- | --- |
| 5 cm | 69 h | 51 h | 95 h | 94 h |
| 10 cm | 54 h | 50 h | 93 h | 94 h |
| 20 cm | 98 h | 81 h | 96 h | 174 h |
| 51 cm | 215 h | 325 h | 366 h | 732 h |
| 102 cm | 596 h | 627 h | 621 h | 1254 h |

(The 5 and 10 cm settings follow the 99.9th percentile, 47 h at most, as Q24 does; the deeper
ones, with only a few runs in two years, follow the longest.) Twice the longest run, as for
soil water: a temperature sensor that dies at 1 m takes seven weeks to show as `stuck`. That
is what a whole-degree reading costs, and it is now written down rather than discovered.
The rain gauge has no flatline at all. With these, the same week raised 6 flags, not 413.

**All six were on the 5 cm soil-water probe, and the probe has a real problem.** In a dry
first week of October it reads 0 % through the night and climbs to 20–25 % every afternoon
with no rain, then drops back by dusk — a daily swing of twenty points in the top 5 cm of a
dry soil, rising with the air temperature. That is not soil water. Either the probe has a
strong temperature artifact (dielectric probes in very dry soil can) or it is failing. The
checks caught its steps — falls of 8 to 16 points in an hour, faster than soil drains, and a
+23 spike straight back — but not the daily swing itself, because no check here compares a
probe with its own temperature or with its neighbours' daily rhythm. The 10 cm probe beside
it does not swing. A cross-check between the two, as §4.2 recommends for any series anyone
acts on, would have seen it; a station profile is one probe per depth, so it has no
redundant neighbour to compare with.

## Next

* A season of this log is the first real test of the learned flatline (Q24's
  `checks.learn_threshold`) on a live feed rather than an archive.
* A check for a moisture series that follows its own soil temperature through the day would
  have caught the 5 cm probe; it is worth building once a second station shows the same.
