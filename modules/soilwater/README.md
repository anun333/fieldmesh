<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/soilwater/` — soil-moisture advisory (layer 2)

The second layer-2 module (spec v0.1 §11), and Q12's other read-only choice: every
morning, for every bed, what to do about water — and when it cannot say, why not. A
season of its advice, kept in the log as decision events (§7.7), is the irrigation
module's evidence base before that module exists.

| advice | when |
| --- | --- |
| **water now**, and how many millimetres | the root zone has lost its crop's share of the plant-available water (FAO-56's `p`, a third by default): back up to field capacity |
| **rain coming** | it is due, but 10 mm or more is forecast in the next 24 hours |
| **water soon** | at the rate it has dried since it was last wetted, it is due within two days |
| **too wet** | wetter than field capacity: water is draining past the roots |
| **enough** | and how much of the available water is left |
| **no probe** | nothing is installed within the root zone |
| **unseen** | no reading for six hours |
| **untrusted** | the newest readings failed the health checks |
| **by the weather**: water now, rain coming, enough, or the station unseen | the bed has no probe, or its probes have gone silent or untrusted, and the farm's station is given ([below](#by-the-weather-with-no-probe)) |
| **layered**, beside the morning's advice | two of its probes learned field capacities far apart, and the bed was given one soil's values ([below](#the-beds-own-soil)) |

The arithmetic is FAO-56's root-zone balance read from the probes rather than modelled:
`TAW = (field capacity − wilting point) × root depth`, depletion
`Dr = (field capacity − θ) × root depth`, water when `Dr ≥ p × TAW`, `Dr` millimetres.
The soil's limits come from a soil test or the survey (`tools/soil_survey.py`), by layer
where the soil changes with depth. The field capacity is then learned from the probes
themselves ([below](#the-beds-own-soil)).

**The probes are found, not configured.** A bed's probes are the soil-moisture series
whose device was installed in it when the reading was taken (§4.1), at the depth its
installation says. Each stands for the soil from halfway to the probe above to halfway to
the one below, and only the part inside the root zone counts. A probe moved from one bed
to another changes both beds' advice on the day it moves; one deeper than the roots counts
for nothing.

**Only readings that had passed the health checks by that morning count**
(`State.quality_as_of`), so a stuck or drifting probe never waters a bed, and a silent one
is dropped rather than averaged in. Rain coming is read from a forecast datastream in the
log (Q26), so the forecast an advice rested on sits beside it.

## Backtested

§11 asks for it before anything goes live. On McAllister Farm's recorded summer of 2013
(June to August), a 30 cm root zone in a silt loam, the drill's forecasts in the log, the
advisory followed to the letter, beside the drip timer most farms run
([sim/irrigation_drill.py](../../sim/irrigation_drill.py)):

| | water applied | drained past the roots | hours stressed ≥ 0.5 | mean stress |
| --- | --- | --- | --- | --- |
| drip timer, every second morning | 552 mm | 600 mm | 0 | 0.05 |
| timer, skipping when rain is forecast | 444 mm | 493 mm | 0 | 0.06 |
| **the advisory** | **156 mm** | **241 mm** | **0** | **0.13** |

72% less water and 60% less drained, with no hour of real stress. The cost is a drier
root zone on average — mean stress 0.13 against 0.05 — which is the trade a refill point
makes, and the reason `p` is the crop's to set.

On Harrow Bend, eight days, six beds: the beds are told apart on the first morning; the far
bed node's radio outage turns its beds' advice into "unseen" and no one else's; and a probe
lifted out of bed 6 into bed 2 leaves bed 6 with "no probe" and keeps bed 2 advised through
its own probe's outage.

```sh
pip install -r modules/soilwater/requirements.txt      # cel-python, via modules/rules
cd modules/soilwater && python3 -m unittest discover -p 'test_*.py'
```

```python
advisor = soilwater.Advisor(log)
beds = [soilwater.Bed(land_id, field_capacity=0.30, wilting_point=0.12),
        soilwater.Bed(yard_id, 0.38, 0.25, layers=((0.10, 0.20, 0.09),),
                      root_depth_mm=150, surface="turf", planting="turf")]
advisor.advise(state, beds, at=morning, forecast=rain_forecast_id)
soilwater.render(event.payload, "es", state)   # "Riegue cama 3 hoy: …"
```

## The bed's own soil

A soil survey maps the native soil. A landscaped yard, a raised bed or a market garden
on an old house lot is often something else:

* topsoil brought in over a subsoil the builders compacted;
* sod with its own soil over the yard's;
* a compost mix over the ground.

Set up with the survey's values, the advisory misjudges such a bed. So each probe
**learns its own field capacity from its own drain-downs** (`learned_capacity`):

* **A wetting** is the probe's reading, smoothed by a running median of three, rising
  0.04 or more within four hours.
* **A drain-down** runs from the wetting's peak to the next wetting, or 72 hours. It
  counts when it is at least 16 hours long with no gap over three hours.
* **Each drain-down is fitted** as water above field capacity draining away while the
  crop dries the soil steadily: `θ(t) = fc + a·exp(−t/τ) − r·t`.
* **Only drain-downs from clearly above field capacity count:** at least 0.02 above it
  (`a ≥ 0.02`). A watering that only refilled the soil part way never drained, and
  says nothing.
* **Only drainage that can be told from the crop's drying counts.** A τ shorter than the
  readings' interval is not tried: on hourly readings, half an hour's "drainage" is one
  noisy reading. And a drainage slower than a quarter of the drain-down's span must carry
  0.06 or more (`SLOW_DRAIN_MIN_EXCESS`). A crop draws by day and less as the soil dries,
  so the soil dries along a gentle curve, and a slow, small "drainage" fits that curve.
  Counted, it put field capacity below the level the bed had been watered to; the next
  watering stopped there, and the learned value sank round by round (below). Water perched
  on clay does drain slowly, and with more: 0.12 and 0.13 in the yard's subsoil.
* **The probe's field capacity** is the median of the last 60 days' drain-downs, once
  there are three. It replaces the configured value for that probe's slice of the root
  zone.

Until then, and for a value within 0.03 of its soil's wilting point, the configured
value stands. `Bed(learn=False)` turns learning off.

What it learns is the level the bed actually holds a day or two after a soaking, the
in-place sense of field capacity: where drainage has become negligible (Twarakavi, Sakai
and Šimůnek 2009, *Water Resources Research* 45, [doi:10.1029/2009WR007944](https://doi.org/10.1029/2009WR007944)).
A laboratory's value can sit below it.

**A layered bed.** Two probes whose learned field capacities differ by 0.08 or more
(`LAYER_GAP`) are in two soils. When the bed was given one soil's values, the advisory
then writes a second decision beside the morning's, `soil-layered`:

> bed 3's soil is layered: its probe at 5 cm drains back to 23% water after a soaking, the
> one at 12 cm to 40%. One soil's values cannot describe it, and the advice may wait too
> long for the layer whose water the roots cannot take. Give the bed each layer's field
> capacity and wilting point, from a soil test of each layer or the soil survey's horizons.

`Bed.layers` takes those values: `(bottom_m, field_capacity, wilting_point)`, top down.
Each probe's slice of the root zone is then judged at its own soil's limits, and the
note stops. `tools/soil_survey.py` gives the survey's values by depth.

**Backtested on the virtual farm.** The test bed is a yard
(`physics.LayeredBed`): 10 cm of brought-in sandy loam over a compacted clay subsoil.
Its roots are in the top 15 cm, and it ran over McAllister Farm's summers of 2013 and 2012
(June to August), with the advisory followed. It was set up three ways:

* with the survey's silt loam, field capacity 0.30 and wilting point 0.12;
* with the topsoil's own nominal values, 0.20 and 0.09;
* with a soil test of each layer: the topsoil as above, the clay 0.38 and 0.25.

The soils' values are round, typical ones, assumed for the simulator rather than
measured. Water applied, drained below the roots, and hours with half the available
water gone:

| probes | set up with | 2013 | 2012, a drought |
| --- | --- | --- | --- |
| one, 5 cm | the survey | 687 mm, 700 drained, 0 h | 810 mm, 662, 0 h |
| | the survey, **learning** | **166 mm, 226, 0 h** | **265 mm, 195, 53 h** |
| | the topsoil's values | 96 mm, 194, 108 h | 134 mm, 143, 406 h |
| | the topsoil's values, **learning** | **163 mm, 220, 0 h** | **237 mm, 166, 26 h** |
| 5 and 12 cm | the survey | 157 mm, 218, 0 h | 205 mm, 147, 45 h |
| | the survey, learning | 141 mm, 207, 0 h, and the note | 202 mm, 147, 31 h, and the note |
| | each layer's values | 122 mm, 198, 3 h | 188 mm, 146, 28 h |
| | each layer's values, **learning** | **163 mm, 218, 0 h** | **217 mm, 150, 16 h** |

**What the table shows:**

* **On the survey's values, a probe in the topsoil drowns the yard.** The topsoil holds
  0.23, which the advisory reads as a quarter short of 0.30, so it waters most mornings.
  Learning cuts the water by two thirds to three quarters.
* **A soil's nominal values can starve it.** Sandy loam's 0.20 is where its drainage
  stops, but in the simulator drainage slows to almost nothing sooner. A day after a
  soaking the bed still holds about 0.23, so refills to 0.20 leave the roots short in hot
  spells. Learning closes most of that.
* **Learning field capacity does not fix a layered bed on its own.** With a probe in
  each layer, the survey's 0.30 happens to sit near the two layers' depth-weighted mix,
  and learning changes little: 31 stressed hours against 45 in the 2012 drought. The
  trouble is the wilting point: one value for two soils counts water the clay holds that
  the roots cannot take, so the advice waits too long. The note is what helps here. Given
  each layer's values, as the note asks, and with learning on, the yard was short for 16
  hours in 2012 and none in 2013.
* **Learning leaves a correctly set-up bed alone.** On the advisory's own backtest bed it
  changed the 2013 summer by about a millimetre (156 mm against 155) and 2012
  not at all.

A uniform sandy fill, 60 cm of the same sandy loam with a probe at 5 cm, behaves like
the single-probe yard: 730 mm on the survey's values against 175 learning in 2013. On
its nominal values it had 87 stressed hours, and none learning.

**What is still not right.** The 16 to 53 hours left in 2012 come from the morning
cadence on a shallow, sandy root zone. It holds about 17 mm its roots can use, and in
2012 a hot day took up to 7.7 mm. With water at a third gone, one morning's "water soon" can be past
half by the next morning. Over McAllister Farm's thirty summers, 1991 to 2020, the yard
set up with each layer's values was short in 18, by up to 57 hours. Two summers do not
show that; thirty do.

**Looking ahead to tomorrow.** So the advice also waters a bed that, drying as it has
been since it was last at field capacity, would pass `Bed.short_fraction` of its water
(half, FAO-56's depletion fraction for most field crops) before the next morning:

> Water bed 3 today: 26% of the water its plants can use is gone, and drying at 8.1 mm a
> day it would be short of water before tomorrow morning. About 7 mm brings it back to
> field capacity.

(A test's bed: 15 cm of roots, 7 mm gone, drying 8 mm a day.) A deep bed rarely dries
that fast, so it changes little; a shallow one is watered a day early. Over the thirty
summers:

| | water, mean a summer | summers short | hours short, in all | worst summer |
| --- | --- | --- | --- | --- |
| the yard, each layer's values, before | 192 mm | 18 | 407 | 57 h |
| **the yard, now** | **202 mm** | **8** | **141** | **35 h** |
| the backtest bed, before | 188 mm | 3 | 72 | 40 h |
| the backtest bed, now | 189 mm | 3 | 72 | 40 h |

The deep bed never dried fast enough to be watered early, which is the point. On single
summers the change is mixed: the table above is with it, and the one-probe yard on the
survey's values went from 16 stressed hours to 53 in 2012, while the two-probe yard on
the survey's values went from 116 to 31.

Looking ahead to the refill point itself (`short_fraction` set to the depletion fraction)
did more, and cost more: in a first run the yard was short in 2 summers, never more than
12 hours, and the backtest bed never, but the backtest bed took 241 mm a summer, 28% more,
as much as the weather alone gives a bed with no probe. The drying rate is timed from the
**The drying rate is a whole day's loss**, each end the mean of the readings within two
hours of it. A crop draws by day and hardly at night, so any part of a day misstates it:
a fit over the night since the soil left field capacity read a heat wave's 8 mm a day as
1.3, and the advice did not look ahead to it. A day with a wetting in it is skipped for the
day before, and a day that began above field capacity begins there, so drainage is not
counted as the crop's.

**A learned value that sank, and why it no longer does.** A bed watered by its probe is
watered back to the field capacity it learned, so after most waterings nothing drains.
The crop then draws by day and less as the soil dries, and the old fit read that gentle
curve as a slow drainage, with field capacity below the level the bed had been watered
to. The next watering stopped there, and round by round the learned value sank: from
0.248 to 0.206 over the 2012 drought, on a probe whose true level was 0.25. Now such a
slow, small "drainage" does not count ([above](#the-beds-own-soil)). On 200 simulated
three-day curves with no drainage at all, the old fit took 34 for drain-downs, down to
0.23 on a bed watered to 0.27; the new one 10, none below 0.253. The advisory's
backtest bed with its probe, over the thirty summers:

| | water, mean a summer | summers short | hours short, in all | learned value at the end, worst |
| --- | --- | --- | --- | --- |
| before | 176 mm | 7 | 186 | 0.048 low |
| **now** | **188 mm** | **3** | **72** | **0.031 low** |
| a probe 0.05 low, before | 306 mm | 0 | 0 | 0.039 low |
| a probe 0.05 low, now | 324 mm | 0 | 0 | 0.025 low |

The 25 mm that ran off the yard in 2013 was rain on topsoil already holding water over the
clay, the same with or without learning. A watering can do the same when it is run
faster than the clay takes water. In the simulator, the same 50 mm given as four
quarter-hour runs an hour apart sheds less than two hours in one go (`sim/test_physics.py`),
which is cycle-and-soak.

**A probe that reads off.** Learning forgives a probe that reads low: one 0.05 low called
for 748 mm unlearned and 268 learned, against a true probe's 156, on 2013. It cannot
forgive one that reads high. That probe says the bed is full, so the bed is not watered,
and the probe sees too few soakings to learn from: 242 hours of stress. A second probe in
the bed is what catches it ([soil sensors](../../docs/notes/soil-sensors.md)).

These results come from the simulator. A real yard's probes are what would check them
([UNTESTED](../../docs/UNTESTED.md)).

**A tension sensor beside a probe** measures field capacity instead of learning it. Each
hour the two at one depth give a point on the soil's own retention curve: this much
water, held this hard. Over the tensions a Watermark is calibrated for, 10 to 75 kPa
(`sdk/tension.py`), water falls close to linearly with the logarithm of tension, so the
points are fitted and field capacity read at `Bed.capacity_kpa`, 33 kPa by default
(`retention.py`). It needs 24 hours of points spanning a factor of two in tension and
reaching to within half again of 33, and no soaking. On a silt loam's curve (Carsel and
Parrish's mean, through van Genuchten's equation) it reads the 0.239 at 33 kPa to within
0.005, and within 0.01 with a probe's noise. A measured value stands before a learned one
for that probe's slice; the decision says which (`"how": "measured"`). A tension sensor
pairs with a probe installed within 2 cm of its depth; its raw series reports tension and
is calibrated with `a = -1`, as fieldmesh records water potential, never above zero.

## A crop that grows

A seedling draws little water from a few centimetres of soil; a full canopy draws more
than the reference grass, from deep. A bed told its crop and the day it was sown
(`Bed.crop`, `Bed.planted`) follows FAO-56's curve for that crop through its season
(`crop_day`, [data/fao56-crops.csv](data/fao56-crops.csv)):

* **its crop coefficient** by stage (Table 12): the initial value through the initial
  stage, rising in a line to the mid-season value over the development stage, holding,
  and falling to the end value over the late season, the stages' days from Table 11;
* **its roots** from 15 cm at sowing (Annex 8: "0.15 to 0.20 m" for many annual crops) to
  the shallow end of Table 22's maximum depth as mid-season begins, growing with the
  crop's development (Annex 8, Eq. 8-1, taken by time, so a crop whose coefficient does
  not rise still roots).

The day's root depth sets the root zone the probes are weighed over and the water it
holds, and the day's coefficient drives the weather balance; an established lawn
(`turf_cool`, `turf_warm`) holds its mid-season values all year. A probe below a
seedling's roots counts for nothing until the roots reach it: ten days after sowing,
tomatoes' 15 cm of roots do not reach a probe at 20 cm.

For each of 22 crops, Table 11's row is the sowing nearest a temperate spring or summer,
named in the file; broccoli, cabbage and cauliflower have only a September sowing there.
A range is taken at its middle. Table 22's depletion fractions are in the file but not
used: the advice keeps a third.

**Backtested** on McAllister Farm's thirty summers, sown on 1 May, the virtual crop
growing by the same curve in a silt loam 1.5 m deep, probes at 10 and 30 cm. "Not known"
is the bed as it was before: 30 cm of roots and a coefficient of 1 all season.

| | water, mean a season | summers short | hours short, in all | worst season |
| --- | --- | --- | --- | --- |
| tomatoes by the weather, crop not known | 360 mm | 0 | 0 | 0 |
| **tomatoes by the weather, crop known** | **293 mm** | **0** | **0** | **0** |
| tomatoes by probes, crop not known | 120 mm | 18 | 2,174 | 623 h |
| **tomatoes by probes, crop known** | **246 mm** | **5** | **391** | **239 h** |
| lettuce by the weather, crop not known | 159 mm | 0 | 0 | 0 |
| **lettuce by the weather, crop known** | **137 mm** | **0** | **0** | **0** |
| lettuce by probes, crop not known | 98 mm | 15 | 566 | 94 h |
| **lettuce by probes, crop known** | **119 mm** | **2** | **30** | **16 h** |

* **By the weather**, a crop not known is charged a full canopy's water from sowing: it
  was given a fifth more than it needed (360 mm against 293 for tomatoes), drained below
  the roots.
* **By probes**, a crop not known is starved. The advice refills the 30 cm it was told
  of, while tomatoes' roots draw on 70 cm and run the deep soil down through the summer;
  lettuce seedlings, with 15 cm, wait too long while the advice counts 30. Knowing the
  crop, it waters more and is short far less.
* **Probes for a deep root zone.** Tomatoes known were still short in 5 summers: probes at
  10 and 30 cm do not see the soil from 30 to 70 cm the roots draw on. With a third at
  60 cm they were never short in thirty summers, given 319 mm a season against 246; only
  11 mm more drained, so the rest went to a crop no longer held back. For a deep-rooted
  crop, a probe in the deeper half of its roots.

The virtual crop grows by the very curve the advice is told, so this shows what knowing
the curve is worth when the curve is right, not how right FAO-56's curve is for a given
field: a real crop's stages run early or late with the season, which is what its probes
are for.

### Roots that stop

The crop's curve is for a soil that lets roots go. Something can stop them sooner:

* a hardpan or plough pan;
* the compacted fill under a new garden;
* rock;
* the floor of a raised bed.

Advice that follows the curve then counts water the roots cannot reach. It waits too
long, and refills less than the roots used. How deep roots run through a season, and what
shows it, is in [the root-depth note](../../docs/notes/root-depth.md). There are two
ways to give the advice the right depth:

* **`Bed.rooting_limit_mm`**, set by hand once the farmer has dug and found the pan. The
  crop's curve stops at it. A probe at that depth or below it sits in the pan, reading soil
  the roots do not enter, so it is not counted.
* **Root signs from the probes** (`root_signs`, `rooted`), over the last two weeks. A
  probe's dry days are those that started no wetter than its field capacity, with nothing
  wetting it. The probe's field capacity is the lower of the bed's and its own.
  * A probe whose soil fell less than 0.002 a day over three or more dry days is **level**:
    nothing draws on it.
  * One whose soil fell faster and went 0.02 under field capacity **has roots**. Just past
    field capacity a soil still drains about that fast, but only roots, or the sun near the
    surface, take it well below.

  Take a level probe that the crop's curve says the roots passed at least 10 cm ago, under
  one that has roots. The roots likely stop between the two, so the advice counts them
  only to halfway, and a note says so:

  > Tunnel bed 3's crop should have roots to about 70 cm by now, but its probe at 30 cm
  > has stayed level through its dry days while the one at 10 cm has dried: something may
  > be stopping the roots, a hardpan or compacted soil. The advice now counts its roots to
  > 20 cm. If you know how deep the soil lets roots go, set the bed's rooting limit.

  **The probes only ever make the root zone shallower than the curve**, so the advice
  waters sooner, never later. Roots seen deeper than the curve are not counted, because
  soil can dry by other routes.

**Backtested** on the thirty summers, tomatoes sown on 1 May with probes at 10, 30 and 60
cm. The virtual roots stop at 30 cm, whatever the curve says:

| | water, mean a season | drained | summers short | hours short, in all | worst season |
| --- | --- | --- | --- | --- | --- |
| the crop's curve alone | 85 mm | 167 mm | 30 | 23,017 | 1,768 h |
| **the curve and root signs** | **215 mm** | 196 mm | **11** | **277** | **46 h** |
| **the rooting limit set at 30 cm** | **313 mm** | 238 mm | **2** | **20** | **12 h** |
| *no pan:* the curve alone | 319 mm | 165 mm | 0 | 0 | 0 |
| *no pan:* the curve and root signs | 318 mm | 164 mm | 0 | 0 | 0 |

* **The curve alone starves a crop on a pan.** It counts 70 cm of roots, and the probes at
  30 and 60 cm, which no root reaches, hold the bed's average up. It was short every
  summer, for a month on average.
* **Root signs find the pan unaided.** They can say so once the curve is 10 cm past the
  probe at 30 cm, seven weeks after sowing, and did on 81 of a season's 145 mornings. That
  cut the hours short by 99%. They count the roots to
  20 cm, short of their true 30, so the advice refills a little less than they use. It is
  still short in some summers, for two days at most.
* **The limit set by hand is better still**, as the note asks. A first version still
  counted the probe at 30 cm, set into the pan: short in 23 summers for 1,528 hours.
  Leaving that probe out fixed it.
* **Without a pan, the signs cost nothing.** About three mornings a season saw a stop that
  was not there, and the water and the hours short were unchanged. The earlier table's
  runs, with probes at 10 and 30 cm, came out the same summer by summer.

The simulator's soil has no capillary rise. Soil under the roots there stays exactly at
field capacity; a real soil's dries a little as water rises into the root zone above it.
On a real pan, a level probe may read as falling slowly
([UNTESTED](../../docs/UNTESTED.md)).

## By the weather, with no probe

A bed with no probe used to get "no probe" and nothing else. Given the farm's own station
(`eto.Station`: its site and the series it keeps), the advisory keeps FAO-56's daily
root-zone balance instead (`weather_balance`).

* **Each day's reference ET** is FAO-56 Penman–Monteith from the station's readings that
  the checks passed (`sdk/eto.py`, which reproduces FAO-56's Example 18: 3.88 mm).
  Missing sunshine, humidity or wind are replaced by FAO-56's own stand-ins, and each
  decision lists which it used.
* **The balance**: each day the depletion falls by the gauge's rain and the watering, and
  rises by `Ks · Kc · ETo`, `Kc` the bed's `crop_coefficient` and `Ks` slowing the crop
  once its readily available water is gone (eq. 84).
* **Watering is the valve's recorded minutes** times the bed's `application_mm_per_h`.
  Without that record, the advisory's own advice to water is taken as followed, and the
  advice says so. A balance that never sees the watering it asked for asks again every
  morning: on the backtest bed that called for 1,027 mm in 2013.
* **Two of the last three days without a full day of weather**, and it says it cannot
  tell, rather than guess.

> Water bed 3 today, by the farm's weather: about 50% of the water its plants can use is
> gone, with no probe to confirm it. About 27 mm brings it back to field capacity.

(The test's bed, five dry days after a soaking.)

Backtested with no probe on the same bed and summers, with an hourly station:

* air temperature, humidity and rain as the virtual farm's recorded weather gives them;
* each day's recorded sunshine spread over its hours;
* no wind sensor;
* the watering unrecorded (`weather_backtest`).

| summer | by the weather | the probe-led advice | stressed hours |
| --- | --- | --- | --- |
| 2013 | 157 mm | 156 mm | 0 |
| 2012, a drought | 314 mm | 208 mm | 0 |

**When a bed's probes go silent or untrusted**, the advisory used to say "unseen" or
"untrusted" and give no advice until they came back. With the station, it now carries the
bed on the weather from the probes' last good readings:

* that reading's depletion, at each probe's soil and learned field capacity, is the
  balance's starting point;
* the days after it are stepped by the weather;
* every advice says to check the probes.

> bed 3's probes have given no reading to trust for 81 hours. By the farm's weather since
> their last good one, about 55% of the water its plants can use is gone: water it today,
> about 30 mm. And check the probes.

(The test's bed, its probe silent from 11 July.)

It runs as long as the balance does, sixty days, because a bed anchored on its last
reading is never worse off than one that never had a probe. On the 2012 drought, with the
backtest bed's probe silent for the two weeks from 1 July:

| | days with no advice | stressed hours |
| --- | --- | --- |
| without the station | 13 | 142 |
| with it | 0 | **0** |

### A probe nearby corrects the balance

The objection to soil probes for lawns and fields is that a probe is a point: one square
metre does not speak for a zone. The balance covers the zone but cannot see the soil. So a
probe lends the balance only what carries from bed to bed: **its rate, not its level**.

A bed with no probe can name a bed nearby, of the same crop on the same station, as its
`reference`. Each morning `reference_factor` reads that bed's probes over the last 30
days. It counts the days with no rain on the gauge, no watering (its valve shut, its
probes not rising) and less than the readily available water gone. On each, it measures
how much the water missing below field capacity grew, midnight to midnight, against the
balance's `Kc · ETo` for the same day. Water held above field capacity after rain is not
depletion, which the probe sees and the balance does not.

The ratio corrects the bed's crop coefficient: **all the way when the probe sees the bed
drying faster than the balance says, half way when slower**, because more water is the
safe error. It is not used:

* with fewer than five such days, or under 10 mm of the balance's ET over them;
* until every probe in the reference has learned its own field capacity
  ([above](#the-beds-own-soil)). A probe reading high sees the first of each spell's
  depletion as water above field capacity, and never learns;
* when the ratio is outside 0.5 to 1.5: then the probe or the station is wrong.

The same rate, read from a bed's own probes before they fell silent, carries the
fallback above, and every decision records the factor, its days and its standard error.

> bed 3 is due water by the farm's weather, with its water use set at 85% of the weather's
> estimate from a probe in a bed nearby: about 19 mm. Its watering is not recorded, so this
> takes the last advice to water as followed; if it was not, it needs more.

(The test's bed, 19 days into a summer with rain every fifth day, its reference's probe
drying at 70% of the balance's rate.)

Backtested on McAllister Farm's thirty summers, 1991 to 2020 (NASA POWER). The backtest
bed has no probe and its watering unrecorded; a bed of the same soil and crop beside it
has a probe at 20 cm and is watered on its own advice (`weather_backtest(reference=True)`):

| the bed with no probe | water, mean a summer | summers with stressed hours |
| --- | --- | --- |
| by the weather alone | 241 mm | 0 of 30 |
| corrected all the way, both ways (not built; measured with the earlier learning) | 217 mm | 5, up to 33 hours |
| **corrected as built** | **237 mm**, 2% less | **0** |
| as built, the reference's probe reading 0.05 low | 228 mm | 0 |
| as built, the reference's probe reading 0.05 high | 241 mm: it never corrects | 0 |

The probe-led bed beside it was given 187 mm a summer. Before learning stopped counting
slow, small drainages ([above](#the-beds-own-soil)), the correction saved 5% (229 mm); the
reference now learns its level less often, and so corrects less often.

**Why only half way.** The rate a probe saw over a month does not hold through a hot spell,
and the balance's own excess was the bed's margin. Corrected all the way, the bed went
short in one summer in six. A probe reading high, used without the learning check, took
the bed to 397 stressed hours on the 2012 drought. With it, the probe was never used.

On the two summers above: 2012 unchanged at 314 mm, because the reference's probe never
saw enough drain-downs that summer to learn its level, and 2013 up from 157 to 179, one
watering more late in the summer, when the probe saw the bed drying faster than the
balance did. Neither was short. The probe's own fallback through its fortnight's outage
used 209 mm, and the bed was never short. A pyfao56-style reset of the balance from a
probe in the same zone is not built.

The balance's ET is Penman–Monteith, while the virtual bed loses water by Hargreaves'
formula. So it runs on a model of the bed that is not the bed, as it would on a farm.
In the dry summer it watered half again as much as the probe did, and still a fraction
of the 552 mm a drip timer uses. A probe reads the bed itself; this reads only the sky.

## A soak test: field capacity on the day

Learning a probe's field capacity takes three soakings it drains from; the soak test makes
one on purpose, and checks the probes on the way ([regimens/soak_test.star](regimens/soak_test.star)).
A person starts it for a bed:

1. It asks for enough water to wet the root zone 0.05 past its field capacity, over a
   square metre centred on the probes, where a millimetre is a litre:

   > Soak test for bed 3: pour 39 litres of water over a square metre centred on its
   > probes, a can at a time, letting each soak in before the next. The probes are
   > checked in 3 hours, and the result comes two days later.

2. Three hours on, the probes must have risen by half what that water should add, and read
   no more water than a mineral soil can hold (0.55). Either failing is said: a probe out
   of contact, water run off, or a probe reading high.
3. Two days on, the level the root zone drained back to, fitted as any drain-down is, is
   reported: the bed's field capacity, measured. Its drain-down also counts toward the
   probes' learning.

(The test's bed at 0.22, field capacity 0.30, 30 cm of roots: 39 litres; drained back to
28%.) Read-only like everything here: it asks a person, and checks what the probes saw.

## Did the water arrive?

The first **regimen** (Q10; [modules/rules](../rules/README.md#regimens)):
[regimens/watering_check.star](regimens/watering_check.star), a few lines of Starlark. When
the morning's advice is "water today", it waits for the watering to happen and soak in,
then checks that the root zone rose by at least half of what that watering should add.
If not, it says so, and says both things a probe cannot tell apart:

> bed 3's probes show almost no new water since this morning: the root zone rose 0.4
> points, where 18 mm of watering should add about 6.0. If it was watered, check the drip
> line and its emitters; if it was not, it still needs water.

It was backtested on the recorded summers with some waterings blocked, as through a
blocked drip line: the person waters, and the bed gets nothing.

| summer | waterings | blocked, caught | watered, wrongly flagged | closest call |
| --- | --- | --- | --- | --- |
| 2013, where the threshold was chosen (five sets of blocked days) | 51 | 16 of 16 | 0 of 35 | watered beds rose at least 0.74 of their expected rise; blocked ones at most 0.27 |
| 2012, a summer not looked at until the threshold was set (four sets) | 46 | 9 of 9 | 0 of 37 | a watered bed at **0.55**, close to the 0.5 line |

**With the valve reporting, it says which.** A bed can name the series of the valve that
waters it (`Bed.valve`, the `valve_open` term). An OpenSprinkler controller reports each
station opening and shutting over MQTT, and the bridge puts that in the log
([sdk/mqtt_bridge.py](../../sdk/mqtt_bridge.py)). The check then tells the two cases apart:

> bed 3's valve ran 60 minutes this morning, but its probes show almost no new water: the
> root zone rose 0.4 points, where 18 mm should add about 6.0. Check the drip line and its
> emitters for a blockage, and the line for a leak.

> bed 3 was due 18 mm of water this morning, and its valve did not open. It still needs
> water.

On the 2013 summer, with three waterings blocked and two forgotten, it named each one
rightly, all five, and said nothing on the seven that arrived. A shutting reported for a valve
never seen opening is a lost message, so the check falls back to saying both rather than
guessing.

The 2012 margin is the honest caveat. A bed that soaks its water up slowly, or a probe set
deep, could fall below half on a day the water did arrive. The share is a parameter, and a
season of a real bed's waterings is what would set it.

As its own process (§8.3, Q11), holding only the grant its [module.json](module.json)
allows: `python3 -I soilwater.py --socket /run/fieldmesh/modules.sock --config beds.json`, the
token from a systemd credential or `FIELDMESH_MODULE_TOKEN` (see
[deploy/systemd/](../../deploy/systemd/)). Through the socket it decides exactly as it
does in-process; the tests run it both ways.

Code AGPL-3.0-or-later ([LICENSE](LICENSE)); strings in [packs/](packs/) under the
`soilwater.` prefix, the Spanish an unreviewed draft. It imports layer zero and layer 1.

A bed can also record what covers its soil (`surface`: bare, organic or inorganic mulch,
plastic, turf) and what grows in it (`planting`). Each decision carries them, so a
season's advice can be read against what the bed was. The probes see what mulch does to
drying; this records why.

**Not yet:**

* the watering check as part of the module's own process, rather than the backtest and
  the library;
* the dose as a duration for a given drip line;
* the crop and its sowing date from the farm's planting records, rather than set by hand
  (`Bed.crop`, `Bed.planted`); and the crop's own depletion fraction, which the file holds;
* a wilting point learned from the probes: that needs the crop's lower limit, the
  driest its roots take a probe to, which a well-watered bed never shows. A tension
  sensor beside the probe could read it off the retention curve at 1500 kPa, beyond a
  Watermark's calibration;
* a safe run length learned from the bed: comparing short runs with long ones,
  cycle-and-soak worked out from the bed itself;
* each bed's drying rate and the share of rain that reaches it, learned, to set beside
  its recorded surface and planting;
* a crop's stages run early or late with the season's warmth: growing degree-days rather
  than FAO-56's fixed days (the [root-depth note](../../docs/notes/root-depth.md): on
  McAllister's summers tomatoes' roots would reach full depth 56 to 69 days after
  planting, not FAO-56's fixed 70);
* the stair-step itself as the root sign, a fall by day greater than the fall by night, so
  a level probe can be told from one draining. The station's timezone says when day is.
