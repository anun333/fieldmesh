<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/twin/` — a physics twin for the hoop house (layer 3, Q28)

[GreenLight](https://github.com/davkat1/GreenLight) (Katzin et al., Wageningen University &
Research; BSD-3-Clause-Clear) models a greenhouse's climate from first principles: the
cover's shortwave and long-wave exchanges, the air and the space above it, ventilation by
wind and buoyancy, the soil, a crop's transpiration and photosynthesis. It was built for a
heated, lit Dutch glasshouse. [twin.py](twin.py) configures it as what the farms here have:
a 30 × 96 ft single-poly high tunnel with roll-up sides and no heating, lamps, screen or CO2.
It then drives the model with the farm's real weather.

Q28's first step is a check on our own physics. The virtual farm's hoop house
(`sim/physics.Tunnel`) is a few plausible numbers. Run on the same real weather (McAllister
Farm, NASA POWER hourly, March–April and two weeks of July 2025), [tunnel_compare.py](tunnel_compare.py)
sets the two side by side.

## What it found

| spring 2025, 60 nights, 6 frosts outside | mean night gain | worst night | frosts inside | inside ≤ −2.2 °C | daytime excess | hottest |
| --- | --- | --- | --- | --- | --- | --- |
| the virtual farm's tunnel, as first guessed | +3.1 °C | +1.6 | 2 | 1 | +9.5 | 32.6 °C |
| the virtual farm's tunnel, fitted to GreenLight (IR film) | +1.2 °C | +1.0 | 3 | 1 | +7.5 | 31.1 °C |
| the same, knowing the sky from its long-wave (IR film) | +1.4 °C | +1.1 | 3 | 1 | +7.5 | 31.1 °C |
| the same, knowing the sky (clear film) | +0.2 °C | −0.4 | 6 | 1 | +6.5 | 30.6 °C |
| GreenLight, thermic (IR) film | +1.4 °C | −0.4 | 1 | 0 | +7.3 | 29.3 °C |
| GreenLight, clear film | +0.3 °C | −1.1 | 5 | 1 | +6.7 | 29.2 °C |

* **The virtual farm's tunnel was too kind at night.** It ran 1.6 °C warmer than
  GreenLight's tunnel under IR film and 2.7 °C warmer than under clear film. Its defaults
  are now fitted to GreenLight per film (`sim/physics.FILMS`: night-low error 0.87 °C, down
  from 1.95), and agree with it on average by night and day. Knowing only rain, it cannot be
  colder inside than out. Given the sky's long-wave, as recorded hourly weather carries it
  (`physics.cloud_from_longwave`), it can: under clear film it was colder inside than out on
  22 of the spring's nights, against GreenLight's 23, though by less (at worst −0.4 °C against
  −1.1). Under IR film the sky barely matters, to either model. The seeded farm still knows
  cloud only by rain.
* **The film decides the frost.** Under clear polyethylene five of the six frosts still got
  in, and on clear nights the tunnel was colder than the open air: thermal radiation goes
  straight through to the sky. That is the inversion growers report under single poly.
  Under IR film one frost got in, and none hard.
* **By day, the peak is where the fit gives way.** The two films agree on the hottest July
  hour within a degree (37–38 °C). The fitted virtual tunnel runs about 3.4 °C cooler at the
  peak; fitted mainly to the nights, its sun is gentler. A heat warning should come from the
  twin, not from it.

Neither GreenLight's tunnel nor the virtual farm's has met a real one, so this says what to
measure first, not who is right: a tunnel's inside and outside air on clear spring nights,
with its film type written down. `modules/advise/tunnel_gain.py` already turns paired
sensors into a measured gain.

## Step 2: a frost watch for covered crops

[frostwatch.py](frostwatch.py) runs tonight through the twin. It warms up on the last 36
hours, starting from soil temperatures taken from the weeks before (not GreenLight's
16.5 °C glasshouse floor). It then runs dusk to dawn on the forecast's air temperature,
humidity, wind and cloud. The cloud becomes the long-wave sky the tunnel radiates to
(Brutsaert's clear-sky emissivity, raised toward a black body by cloud), and the morning
sun is a clear sky dimmed by cloud (Kasten and Czeplak). The inside low is judged by a CEL
rule through modules/rules, in English and Spanish.

Live, everything comes from the forecast log the farm's cron keeps (`tools/forecast_collect.py`,
which now keeps humidity, wind and cloud as well), each hour its latest issue (Q26). The
warm-up hours are forecasts made a few hours ahead, near enough to what happened. It runs by
hand on a log, or as a module process through the host (§8.3, [module.json](module.json)):

```sh
twin-env/bin/python -I modules/twin/frostwatch.py --log forecasts.jsonl --lat 35.06 --lon -86.59 --cover thermic
```

On a farm it runs each evening at 17:30 as its own module process, from a systemd timer
([deploy/systemd/](../../deploy/systemd/README.md)), with its place, film and tunnel in a
config file. Its decision names the tunnel and stands until dawn, so the
[notifier](../notify/) can send it and the [board](../board/) can show it. Run so on McAllister
Farm's forecast log on 2026-10-11, it said 14.4 °C inside a thermic-film tunnel against
12.8 °C outside: no warning.

**The 2025–26 season at McAllister Farm** ([covered_backtest.py](covered_backtest.py)): 194
nights, mid-October to the end of April. Each night uses NOAA's National Blend of Models
issued at 6 pm, after a warm-up on what the weather did (NASA POWER). The same night is
run on what the weather did as the twin's own answer; the farm's SCAN station is the truth
outside. A damaging frost is −2.2 °C or below, as in the open-bed watch's backtest.

| | damaging frosts | caught | missed | false alarms | open-bed warnings spared |
| --- | --- | --- | --- | --- | --- |
| open-bed watch, outside | 38 | 38 | 0 | 7 | — |
| covered watch, IR film, warn at 0 °C | 28 inside | 28 | 0 | 8 | 9 of 45 |
| covered watch, clear film, warn at 0 °C | 36 inside | 35 | **1** | 6 | 4 of 45 |
| covered watch, clear film, warn at +0.5 °C | 36 inside | 36 | 0 | 7 | 3 of 45 |

* **A Tennessee winter gets into an unheated tunnel.** Of the 38 damaging frosts outside,
  28 were damaging inside under IR film and 36 under clear film. The tunnel stretches the
  shoulders of the season; it is not frost protection in January.
* **The twin on the forecast runs about 1.1 °C warm** against the twin on the weather that
  came, which is the dangerous direction. Under clear film 0 °C let one damaging night
  through. The defaults are therefore by film (`WARN_BY_COVER`): 0 °C for IR film and
  +0.5 °C for clear, the highest thresholds that missed nothing this season. That is one
  season's evidence, as the open-bed watch's 0 °C is.
* **What a tunnel grower gains is specificity, not a warmer number:** 9 of the 45 outdoor
  warnings spared under IR film, with the inside low named. Four of those nine still
  touched 0 °C inside without reaching −2.2: a light frost for hardy crops, which the
  message says.

Neither "truth" inside is a thermometer in a tunnel. The twin run on the weather that came
is the best available while no real tunnel is logged.

## Step 3: the twin against the tunnel's own sensor

A tunnel has one air sensor more often than two, and one sensor cannot see its own fault.
[twin_check.py](twin_check.py) sets the twin beside it, and says, as an advisory decision,
when the two part company and stay apart:

> hoop house's air sensor and the twin have disagreed by -8.4 °C for 3 hours. Check the
> sensor and its sun shield, and whether the sides or a door are open.

That is what it said two hours after the sensor was knocked outside on the morning of
April 16 (the backtest below).

It never marks a reading bad. A module does not write quality verdicts (§8.3), and the twin
may be the one that is wrong.

**What counts as apart is learned.** Two models of one tunnel never agree. On the spring of
2025, GreenLight and the virtual farm's tunnel, lit by the measured sunshine, differ by about
1 °C at night and up to 2 °C at midday. So the check first learns the usual difference and
its spread for each four hours of the solar day over two weeks of good data, after the
sensor is installed or serviced. After that, an hour departs when its difference lies
further from the usual one than the larger of 2 °C and three spreads. The alert stands once
three such hours run in a row.

**Backtested** on the spring of 2025, with GreenLight's saved run as the twin and the
virtual farm's tunnel as the sensor, with faults put in:

| fault | said after |
| --- | --- |
| none, seven weeks; five noise seeds | never: no false alert |
| the sensor reads 4 °C high (miscalibrated, replaced) | 12 h; across five placings, 8 to 40 h |
| its sun shield is gone, reading up to 8 °C high in full sun | 8 h |
| the sides are left up for two days | 15 h, at the first sunny midday |
| it reads the outside air (knocked down, moved) | 2 h by day; at night a tunnel is barely warmer than outside |

**What it cannot see:** a sensor 1.5 °C off (no case in five), 2 °C off (one in five) or 3 °C
off (four in five). The twin is a second opinion for gross faults; a sensor slowly
going wrong is a second sensor's to catch. And the "sensor" here is a second model, not a
thermometer in a tunnel: what a real one's residuals look like is
[untested](../../docs/UNTESTED.md).

## What it took to run GreenLight as a tunnel

Every unheated configuration failed at the first sunrise, in the solver, whatever its film
or vents. The cause was in the crop model. The CO2 compensation point
(Vanthoor 2011, ch. 9) scales the leaf's by `j25LeafMax / j25CanMax`, which is 1/LAI. That
holds for a canopy of one leaf layer or more. A tunnel's young transplants (LAI 0.13 here)
make the ratio near 8 and the compensation point **negative**, about −150 ppm. Gross
photosynthesis divides by `(Cs + 2Γ)`, so the model has a pole at a leaf CO2 of about
300 ppm, and a house that is not enriched passes through 300 ppm every sunny morning. An
enriched glasshouse never comes near it, which is presumably why it was never hit.
Capping the ratio at 1 (one formula override, `FORMULAS` in [twin.py](twin.py)) runs every
configuration; without it, every one fails. The test
`test_it_runs_a_tunnel_through_sunrise_only_with_the_compensation_point_fixed` keeps both
halves of that true, and will say when an upstream fix makes the override unnecessary.
Reported upstream as [davkat1/GreenLight#23](https://github.com/davkat1/GreenLight/issues/23).

## Running it

GreenLight pins numpy 1.26 and brings scipy, pandas and matplotlib, so it gets its own
environment, and as a live twin it will be its own module process (§8.3):

```sh
python3 -m venv twin-env && twin-env/bin/pip install -r modules/twin/requirements.txt
twin-env/bin/python -I modules/twin/tunnel_compare.py --run    # about 3½ minutes; rewrites data/
python3 modules/twin/tunnel_compare.py                          # anywhere: from the saved runs
```

Sixty-one days of the tunnel take about 80 seconds here.

| file | what it is |
| --- | --- |
| [data/mcallister-2025-spring-hourly.csv](data/), [july](data/) | the weather: NASA POWER hourly, CC BY 4.0, irradiance converted from MJ/h |
| [data/greenlight-tunnel-*.csv](data/) | GreenLight's hourly inside air, per film and period |
| [data/mcallister-2025-26-frost-season-hourly.csv](data/) | the 2025–26 frost season's weather, NASA POWER hourly |
| [data/frost-backtest-2025-26-*.csv](data/) | the covered-crop watch per night, per film: NBM's outside low, the station's, and the twin's inside low on the forecast and on the weather |

Code AGPL-3.0-or-later ([LICENSE](LICENSE)), like the other modules; GreenLight is
BSD-3-Clause-Clear and is installed, not copied.

**Next (Q28):** the twin run live on a farm's weather beside a real tunnel's sensor, as
a module process; the twin's warm bias on forecasts, which a season of a real tunnel's lows
would let the watch correct rather than pad; step 4 waits on §6.
