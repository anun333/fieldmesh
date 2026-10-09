<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Weather forecasts as input data, and real weather in the virtual farm

**2026-10-09.** Two additions, built together because each tests the other: layer zero
takes weather forecasts as data (Q26), and the virtual farm can live through a real
place's recorded weather instead of only its seeded climate.

## Why forecasts belong in the log

The decisions a farm makes ahead of the weather — cover the bloom, close the tunnel, skip
tonight's irrigation, move stock before the storm — rest on a forecast, and §1 promises
that any action can be traced to why it happened. A forecast kept in a cache somewhere
above layer zero cannot answer "why did it skip watering on the 12th?". It also cannot be
scored, and a forecast's skill *at this farm* is unknown until the farm's own sensors have
scored it: the grid cell is kilometres across and the frost pocket is not.

## How a forecast is stored

A forecast has two times and is re-issued every few hours, so it cannot be filed as a
measurement: either the issue time is lost or several values sit at one
`phenomenonTime`, which §3.2 forbids. Q26 lays out five ways; the one built:

* a datastream of **`kind = forecast`**, one per variable and source, whose sensor is the
  forecast model and which derives from nothing on the farm;
* each observation carries **`issued_at`** — served as SensorThings `resultTime`, the case
  O&M defines it for — and `measured_at` is the hour it is valid for;
* for each valid time the **live** value is the **latest issue**. No `supersedes` is
  written: a newer run does not correct an older one, it replaces it as the best guess,
  and a run that arrives late cannot take over from a newer one. Every run stays in the
  log;
* the datastream's health is judged from its latest issue, since its newest valid time is
  always in the future;
* a measurement's encoding is unchanged, byte for byte: `issued_at` is written only when
  present.

`sdk/forecast.py` ingests a run (idempotently — a run fetched twice is written once) and
scores every stored run against a measured series by lead time.

## Where forecasts come from

| source | covers | licence | built |
| --- | --- | --- | --- |
| **NWS**, api.weather.gov gridded forecast (NDFD: 2.5 km, about 7 days, updated about hourly) | the United States | public domain | yes |
| **MET Norway**, api.met.no locationforecast 2.0 (ECMWF-based outside the Nordics, about 9 days) | the world | CC BY 4.0 / NLOD 2.0, commercial use allowed; requires a User-Agent with the caller's contact, and caching | yes — the contact is the user's to give, so none is sent by default |
| Open-Meteo | the world | data CC BY 4.0, but the free API is non-commercial | no |
| ECMWF open data | the world | CC BY 4.0 | not yet — GRIB2 needs a decoding library |

`tools/forecast_sources.py nws 35.0645 -86.5914` fetches McAllister Farm's grid cell (HUN
62,57) and summarises it by local day; `--json` keeps the run. Values are kept as sent —
NWS temperatures are whole Fahrenheit degrees converted to Celsius, so `18.888…` stays
that — hours that ended before the issue are dropped, and six-hour rain is spread over its
hours so the total is kept.

## Real weather in the virtual farm

`RecordedClimate` (sim/physics.py) replays daily records — NASA POWER's minimum and
maximum temperature, rain, humidity and sunshine — at the simulator's 5-minute tick:
temperature on half-cosines between the day's extremes at 05:00 and 17:00 (the synthetic
climate's own phase, so every check calibrated against it sees the same shape), each
day's rain exact and in one spell, Hargreaves reference ET from the sunshine. Everything
built on the world — soil water, soil heat, troughs, the tunnel — now runs on a real
season. The bundled one is McAllister Farm's spring of 2007: a warm March, then −5.5 °C
on April 7 and −4.3 on the 8th, the Easter freeze that took much of the region's fruit
and damaged its wheat.

## The drill

`make forecast` puts a forecaster (sim/forecaster.py) on that spring. It reads the world's
own future and adds an error of declared size, growing with lead time — 1.2 °C at the
start plus 0.35 a day, wandering smoothly from hour to hour, and rain missed or invented
more often further out. A run every six hours, 172 of them, goes through `sdk/forecast.py`
into one log beside a weather station's readings. Then, from the log alone:

**The forecasts were as good as they were made to be.** Every stored run scored against
the station gives back the declared spread at each lead day — 1.45 °C on the first day
against 1.38 declared, 3.56 on the seventh against 3.47 — which is the test that the two
times, the late runs and the projection are all right: get any of them wrong and the
errors come out by the wrong lead.

**A frost watch would have helped.** At each issue a watch reads the live forecast for the
next 48 hours and warns when it reaches a threshold; each frost night the station recorded
(−2.2 °C, what kills open bloom) is scored by its warning time, and each warning no frost
followed is a false alarm. Over five seeds of the 2007 spring:

| forecast | warn at | frosts warned 12 h or more ahead | warnings with no frost after |
| --- | --- | --- | --- |
| default | 0 °C | 12 of 12 | 98 of 180 |
| default | −1 °C | 12 of 12 | 69 of 147 |
| default | −2.2 °C | 12 of 12 | 35 of 105 |
| worse: 2.5 °C + 0.6 a day | 0 °C | 12 of 12 | 140 of 218 |
| runs 1.5 °C warm | 0 °C | 12 of 12 | 51 of 129 |

Every damaging frost that spring was deep — the Easter freeze reached −5.5 — so every
setting warned in time, and the only difference was false alarms, the cost that teaches a
farmer to ignore the next warning. A season of marginal frosts, a degree either side of the
damage line, is where a margin buys misses back; one spring cannot show it. The drill can
run on any recorded season, and the next step is thirty of them.

The watch is a stand-in: rules and alerts are layer 1, which is not built. It is here to
show a forecast arriving as data, being acted on, and being scored the way such a rule will
have to be before it goes live (§11).

## Next

* Run the frost watch over thirty recorded springs, for a threshold chosen on evidence.
* Score NWS's real forecasts against a station: fetch a run every hour into a log next to a
  SCAN station's air temperature, and after a season the farm knows how far to trust them —
  likely a warm bias on still, clear nights in low ground, which is the frost that matters.
* Put rain forecasts to work where they pay: an irrigation rule that skips a watering when
  enough rain is forecast, backtested on the virtual farm's soil water.
* A forecast's quality: none of §4.2's sensor checks runs on a forecast; a range check
  would be honest, the rest would mislead (Q26).
