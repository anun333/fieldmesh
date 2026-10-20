<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# The soil-moisture advisory's backtests, 2026-10-11 to 2026-10-19

*The record of what the [soil-moisture advisory](../../modules/soilwater/README.md) was
tried on, on the virtual farm as each day had it, and what each try showed: the tables
that once stood in its README, kept here as they were last written. The README holds what
the advisory does now and the evidence for it as it is now, from `trials.py`; this keeps
how it got there.*

*Read each table with its date. The simulator changed under them: on 2026-10-15 its soil
began to move water below field capacity; on 2026-10-16 its crop began to use its water as
FAO-56's does, from the top of its roots, and its bare soil to dry; on 2026-10-17 its crop
began to slow by the water near its roots; on 2026-10-18 its roots began to make up for each
other, its crop to run short sooner on a hot day, and the backtests to water probe-led beds
at the weather beds' rate, with forecasts as they stood ([the audit](#the-audit-of-2026-10-18)). And the advice changed with what they showed.
Since retired, and so found here only: `Bed.adjust_p` (FAO-56's lower refill point on a hot
day), the root signs' stair-step, learning field capacity by the median of the drain-downs
or from soakings alone, and the simulator's soil before 2026-10-15.*

## The backtest bed, 2013

§11 asks for it before anything goes live. On McAllister Farm's recorded summer of 2013
(June to August), a 30 cm root zone in a silt loam, the drill's forecasts in the log, the
advisory followed to the letter, beside the drip timer most farms run
([sim/irrigation_drill.py](../../sim/irrigation_drill.py)). The backtests are
[backtest.py](../../modules/soilwater/backtest.py), `backtest` with probes and `weather_backtest` by the weather,
kept apart from the advisory, which never imports the simulator:

| | water applied | drained past the roots | hours stressed ≥ 0.5 | mean stress |
| --- | --- | --- | --- | --- |
| drip timer, every second morning | 552 mm | 580 mm | 0 | 0.06 |
| timer, skipping when rain is forecast | 444 mm | 472 mm | 0 | 0.06 |
| **the advisory** | **208 mm** | **235 mm** | **0** | **0.12** |

62% less water and 59% less drained, with no hour of real stress. The cost is a drier
root zone on average — mean stress 0.12 against 0.06 — which is the trade a refill point
makes, and the reason `p` is the crop's to set. (On the simulator of 2026-10-16,
[below](#the-crops-water-use-and-the-soils-surface); on the earlier one the advisory used
156 mm. The drought of 2012 took the timer to 51 hours short; the advisory, on 319 mm, to
none.)

**Each simulated probe draws its own noise** (`noise_streams`, since 2026-10-14). Before,
all of a backtest's probes drew from one stream, so a run with a probe more or less, or with
one probe silent for a while, read different noise on the probes it shared with another, and
two runs set side by side differed by more than the probe. Now each draws from its own; the
first keeps the seed's, so a run with one probe reads exactly as before, to the last bit. The
tables here with more than one probe were made with the shared stream; those re-measured on
the new streams say so.

**What that showed: hours short are noisy.** The water a bed was given moved by a few per
cent at most; the hours short moved by several times in some rows, from nothing but which
draws of noise each probe read (the code before the change gave the old numbers again,
exactly, for the two rows tried). Over five draws of it, tomatoes led by probes at 10 and 30 cm were short in 1 or 2
summers of thirty, for 16 to 45 hours; on the one draw the tables were first made with, 3 for
178. So a difference of a few summers or a few dozen hours between two rows can be the
noise's, and the comparisons below that rested on one have been said again. The large ones
stood: the pan found by the root signs, the crop known against not, a probe among the young
plants. All of that was on the simulator's earlier soil, which moved no water below field
capacity. The tables below are the simulator of 2026-10-16, three draws each: its soil
moves water below field capacity ([below](#water-below-field-capacity)), and its crop uses
water as FAO-56's does, draws it most from the top, and leaves bare soil to dry in the sun
([below](#the-crops-water-use-and-the-soils-surface)). Several results moved a long way
with it, and the advice was changed for what they showed.

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
* **The probe's field capacity** is the upper quartile of the levels the last 60 days'
  drain-downs settled to, once there are three (`Bed.learn_from`, `"upper"`). It replaces
  the configured value for that probe's slice of the root zone. On a soil that goes on
  moving water after it has drained, a light watering over drier soil spreads down after
  its drain-down ends, and the sun dries the top: such drain-downs settle below the soil's
  field capacity, and their median read it low. On the simulator of 2026-10-16, before the
  second look and the lawn's ground cover ([below](#the-crops-water-use-and-the-soils-surface)),
  a lawn led by one probe at 7 cm and watered back to its median was short in all 30
  summers (14,175 hours); learning from soakings alone, in 29 (8,422); by the upper
  quartile, in 25 (4,125). With those, by the upper quartile, in 1 or 2. `"all"` keeps the
  median, and `"soakings"` the median of the drain-downs from 0.06 or more over it.

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
| one, 5 cm | the survey | 1,130 mm, 1,143 drained, 0 h | 1,252 mm, 1,104, 0 h |
| | the survey, **learning** | **432 mm, 447, 0 h** | **524 mm, 379, 0 h** |
| | the topsoil's values | 186 mm, 207, 0 h | 282 mm, 143, 0 to 17 h |
| | the topsoil's values, **learning** | **270 mm, 285, 0 h** | **376 mm, 231, 0 h** |
| 5 and 12 cm | the survey | 185 mm, 203, 0 to 31 h | 292 mm, 151, 7 to 16 h |
| | the survey, learning | 204 mm, 219, 0 to 2 h, and the note | 293 mm, 159, 8 to 244 h, and the note |
| | each layer's values | 160 mm, 182, 4 to 46 h | 268 mm, 129, 10 to 28 h |
| | each layer's values, **learning** | **208 mm, 226, 0 h** | **325 mm, 183, 0 to 2 h** |

Measured on the simulator of 2026-10-16
([below](#the-crops-water-use-and-the-soils-surface)), three draws of the noise: the
water and drainage are their mean, the hours short the least and most of the three.

**What the table shows:**

* **On the survey's values, a probe in the topsoil drowns the yard.** The topsoil holds
  0.23 to 0.25, which the advisory reads as a sixth to a quarter short of 0.30, so it
  waters most mornings. Learning cuts the water by three fifths.
* **A soil's nominal values can starve it, and here barely did.** Sandy loam's 0.20 is
  where its drainage stops, but in the simulator drainage slows to almost nothing sooner,
  and a day after a soaking the bed still holds about 0.23: refills to 0.20 left the roots
  short in the 2012 drought for up to 17 hours, where on the soil of 2026-10-15 it was 193
  to 286. Learning, by the upper quartile, takes it to none, for a third more water.
* **Learning field capacity does not fix a layered bed on its own.** With a probe in
  each layer, the survey's 0.30 happens to sit near the two layers' depth-weighted mix,
  and learning did not help: 8 to 244 stressed hours against 7 to 16 in the 2012 drought.
  The trouble is the wilting point: one value for two soils counts water the clay holds
  that the roots cannot take, so the advice waits too long. The note is what helps here.
  Given each layer's values, as the note asks, and with learning on, the yard was short for
  at most 2 hours in 2012 and none in 2013.
* **Learning leaves a correctly set-up bed alone.** On the advisory's own backtest bed, a
  bucket of the soil it is set up with, the 2013 summer took 208 mm learning and without,
  and 2012 319 mm both ways, to the millimetre.

A uniform sandy fill, 60 cm of the same sandy loam with a probe at 5 cm, behaved like
the single-probe yard on the earlier soil: 730 mm on the survey's values against 175
learning in 2013. On its nominal values it had 87 stressed hours, and none learning. (Not
measured again: sandy loam passes almost nothing below its field capacity, so the new
soil changes it little.)

**What is still not right.** Over McAllister Farm's thirty summers, 1991 to 2020, the yard
set up with each layer's values and learning was short in 19 to 22 (119 to 222 hours, up
to 32 in one summer) on 275 mm, where on the soil of 2026-10-15 it was 2 to 7. Two summers
do not show that; thirty do. Its root zone holds about 17 mm its roots can use, its roots
are densest at the top, where the sun also dries it, and a hot day can take 8 mm: a third
gone in the morning can be past half by the afternoon. Watering at a fifth gone instead
(`Bed.depletion_fraction` 0.2) left it short in 4 to 7 summers (14 to 32 hours) on 301
mm, 10% more; it is a setting for such a bed, not yet the default.

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
| **the yard, with it** | **199 mm** | **2 to 7** | **24 to 123** | **48 h** |
| the backtest bed, before | 188 mm | 3 | 72 | 40 h |
| the backtest bed, with it | 189 mm | 3 | 72 | 40 h |

Measured on the simulators before 2026-10-16: the yard with it on the soil of 2026-10-15,
three draws (on the earlier soil, one draw, 202 mm, 8 summers, 141 hours), the rest on the
earlier soil. On the simulator of 2026-10-16, with the second look of the day and the
other changes since, the yard was short in 19 to 22 summers on 275 mm
([above](#the-beds-own-soil)), and the backtest bed in 0 to 3 for at most 4 hours, on 289
mm.

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
| **after**, the earlier soil | **188 mm** | **3** | **72** | **0.031 low** |
| a probe 0.05 low, before | 306 mm | 0 | 0 | 0.039 low |
| a probe 0.05 low, after | 324 mm | 0 | 0 | 0.025 low |
| **the simulator of 2026-10-16**, three draws | **289 mm** | **0 to 3** | **0 to 4** | **0.021 low** |
| a probe 0.05 low, the same | 490 mm | 0 | 0 | 0.017 low, or not learned |

On the simulator of 2026-10-16 the probe 0.05 low did not learn its level at all in some
summers, and was watered as an unlearned probe is: hence its water.

The 25 mm that ran off the yard in 2013 was rain on topsoil already holding water over the
clay, the same with or without learning. A watering can do the same when it is run
faster than the clay takes water. In the simulator, the same 50 mm given as four
quarter-hour runs an hour apart sheds less than two hours in one go (`sim/test_physics.py`),
which is cycle-and-soak.

**A probe that reads off.** Learning forgives a probe that reads low: one 0.05 low called
for 1,045 mm unlearned and 422 learned, against a true probe's 208, on 2013. It cannot
forgive one that reads high. That probe says the bed is fuller than it is, so the bed is
watered late and little, 127 mm, and the probe sees too few soakings to learn from: 293
hours of stress. A second probe in
the bed is what catches it ([soil sensors](soil-sensors.md)).

These results come from the simulator. A real yard's probes are what would check them
([UNTESTED](../UNTESTED.md)).

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
(`crop_day`), with the 2025 revision's values (FAO-56 Rev.1,
[data/fao56rev-crops.csv](../../modules/soilwater/data/fao56rev-crops.csv)) and the 1998 edition's stage days
([data/fao56-crops.csv](../../modules/soilwater/data/fao56-crops.csv)):

* **its crop coefficient** by stage (the revision's Tables 6.1 and 6.2): the initial value
  through the initial stage, rising in a line to the mid-season value over the
  development stage, holding, and falling to the end value over the late season;
* **its roots** from 15 cm at sowing (the 1998 Annex 8: "0.15 to 0.20 m" for many annual
  crops) to the shallow end of the revision's range of maximum depth as mid-season
  begins, growing with the crop's development in a line, as the revision's Example 8.3
  still grows them;
* **its stages** in the revision's degree-days (Table 6.11), for the 10 of these crops it
  has field-observed values for, where the farm's station gives the temperatures
  ([below](#by-the-seasons-warmth)); otherwise the 1998 edition's days (its Table 11).

Where the revision gives a crop two seasons, the plain name is the first and the other is
named after a colon: `tomato` is fresh-market tomatoes and `tomato:processing` the
processing crop; `lettuce`, `potato`, `broccoli`, `corn` (sweet corn) and `muskmelon` are
the short season and `…:long` the long; `pea` is fresh peas for market and
`pea:industry` the processing crop. Against the 1998 edition, tomatoes' roots now reach
0.6 m, not 0.7, and their end-of-season coefficient is 1.00 for the fresh market, not
0.80; lettuce's mid and end values are 1.05, not 1.00 and 0.95.

**Lawns: the 1998 values, and the revision's as `turf_lawn`.** The 2025 revision gives a
mown lawn (cut under 10 cm) 0.50, 0.70 and 0.50 through its season (Table 6.4), against
the 1998 edition's 0.95 for cool-season turf and 0.85 for warm; `turf_lawn` holds its
0.70 all year, as the 1998 lawns hold theirs. Which is right for a given lawn matters
only where no probe measures it: by the weather, a lawn told 0.70 is given about a third
less water, and if it truly uses 0.95 it goes short. On the thirty summers, the lawn
drill's tall fescue with 15 cm of roots, the advice by the weather and the virtual lawn
using one value or the other:

| the lawn truly uses | the advice is told | silt loam: water, summers short, hours | the builder's yard: water, summers short, hours |
| --- | --- | --- | --- |
| 1998's 0.95 | 0.95 (`turf_cool`) | 357 mm, 0, 0 | 409 mm, 6 to 7, 90 to 102 |
| 1998's 0.95 | 0.70 (`turf_lawn`) | 232 mm, 1, 7 | 255 mm, **27 to 28, 1,275 to 1,359** |
| the revision's 0.70 | 0.95 | 357 mm, 0, 0 (111 mm more drained) | 409 mm, 0, 0 (109 mm more drained) |
| the revision's 0.70 | 0.70 | 232 mm, 0, 0 | 255 mm, 0, 0 |

Measured on the simulator of 2026-10-16
([below](#the-crops-water-use-and-the-soils-surface)), three draws of the forecasts'
noise. Told 0.70, a lawn is given a third less water either way, and if it truly uses 0.95
the yard's goes short in nearly every summer. On the soil of 2026-10-15 the same was short
in 3 summers for 27 hours, and the case for `turf_cool` as the default looked weak; on the
earlier soil, which moved no water below field capacity, in 7 (87 hours). Now a lawn's
crop uses its water whole until half is gone, as FAO-56's does, and **`turf_cool` stays the
default**: told too little, a lawn by the weather is starved; told too much, it is given
water that drains. Even told rightly, the yard's 15 cm of roots in sandy topsoil over clay
went short in 6 or 7 summers by the weather, its margin ([below](#by-the-weather-with-no-probe))
included. By a probe the value makes no difference at all, to the millimetre: the probe
measures what the lawn used. A lawn with a probed bed nearby as its reference can learn
that its rate is faster still (`Bed.reference`, [below](#a-probe-nearby-corrects-the-balance)).
A lawn led by one probe at 7 cm, short in 13 summers of 30 on the earlier soil and 1 to 8
on the soil of 2026-10-15, was short in 1 or 2, for 7 to 31 hours, on 181 mm: half the
water by the weather.

The day's root depth sets the root zone the probes are weighed over and the water it
holds, and the day's coefficient drives the weather balance; an established lawn
(`turf_cool`, `turf_warm`) holds its mid-season values all year. A probe below a
seedling's roots counts for nothing until the roots reach it: ten days after sowing,
tomatoes' 15 cm of roots do not reach a probe at 20 cm. **Nor does a probe at the root
zone's very bottom** count (`weights`): it reads the soil the roots are only reaching,
half of it below them. On the simulator's earlier soil, which moved no water below field
capacity, tomatoes' roots at their deepest, 60 cm, with a probe at 60 cm counted as a
quarter of the root zone, were short in 13 summers of 30 for 1,303 hours; left out until
the roots are past it, in 0 or 1 over five draws of the probes' noise. On the simulator of
2026-10-16 the probe at 60 cm makes no difference to how often they are short (below).

The revision's depletion fractions are in the file; the advice keeps a third, lower than
its tables as it says suits frequent watering, and with `Bed.adjust_p` lowers it on a
hot day as the revision's Eq. 8.5 does ([below](#hot-days-and-beds-under-cover)).

**Backtested** on McAllister Farm's thirty summers, sown on 1 May, the virtual crop
growing by the same curve in the 1998 days, in a silt loam 1.5 m deep, probes at 10 and
30 cm. "Not known" is the bed as it was before: 30 cm of roots and a coefficient of 1 all
season.

| | water, mean a season | summers short | hours short, in all | worst season |
| --- | --- | --- | --- | --- |
| tomatoes by the weather, crop not known | 492 mm | 9 to 10 | 213 to 237 | 53 h |
| **tomatoes by the weather, crop known** | **569 mm** | **0** | **0** | **0** |
| tomatoes by probes, crop not known | 520 mm | 19 to 22 | 913 to 1,029 | 127 h |
| **tomatoes by probes, crop known** | **595 mm** | **5 to 8** | **21 to 112** | **28 h** |
| the same, with a third probe at 60 cm | 627 mm | 5 to 8 | 21 to 112 | 28 h |
| lettuce by the weather, crop not known | 228 mm | 7 | 143 to 150 | 28 h |
| **lettuce by the weather, crop known** | **292 mm** | **0** | **0** | **0** |
| lettuce by probes, crop not known | 300 mm | 19 to 20 | 749 to 835 | 113 h |
| **lettuce by probes, crop known** | **266 mm** | **8 to 15** | **46 to 366** | **74 h** |

Measured on the simulator of 2026-10-16
([below](#the-crops-water-use-and-the-soils-surface)), three draws of its noise each: the
water is their mean, the summers and hours short the least and most of the three. On the
soil of 2026-10-15 no row was short in any draw, on half the water or less (tomatoes known,
300 mm by the weather and 247 by probes).

* **Not knowing the crop now costs it.** By the weather, a crop not known is charged a
  coefficient of 1 all season: a seedling's wet soil evaporates more than that early on,
  and tomatoes at mid-season use 1.10. It was given less water than knowing the crop, and
  went short in a third of the summers. By probes, a crop not known is advised for 30 cm of
  roots, and its probe at 30 cm, at that root zone's bottom, does not count; tomatoes,
  whose roots draw down to 60 cm, went short in two summers of three.
* **Known, by the weather, neither crop was short in any summer.** The balance's margin
  ([below](#by-the-weather-with-no-probe)) is part of that, and so is the water.
* **Known, by probes, both were short in some summers, all in a few days at the end of the
  initial stage.** The young crop is watered at a fifth of its water gone (`young_fraction`)
  through its initial stage, 30 days for tomatoes and 20 for lettuce; on the day it ends
  the advice goes back to a third, while the roots are still the 15 cm they were sown with
  and the crop begins to use more. In the three summers traced, among the worst, every short
  hour fell within three days of that: tomatoes on days 30 to 33, lettuce on 20 to 23. A third probe at 60 cm,
  in the deeper half of tomatoes' roots, changed nothing in those days.

The virtual crop grows by the very curve the advice is told, so this shows what knowing
the curve is worth when the curve is right, not how right FAO-56's curve is for a given
field: a real crop's stages run early or late with the season, which is what its clock
([below](#by-the-seasons-warmth)) and its probes are for.

### By the season's warmth

The 1998 edition's stages are days, for a typical season; a warm year runs a crop through
them sooner and a cool one later. The 2025 revision gives them in growing degree-days
instead (its section 6.8.1). Given the farm's station, the advisory does the same
(`thermal.py`, `Advisor.clocked`):

* **A day's degree-days** are its mean temperature less the crop's base, nothing below the
  base, and no more than its upper threshold less the base (the revision's Eq. 6.23),
  each crop's thresholds from its Table 6.10: tomatoes 7 and 28 °C, lettuce 4 and 28,
  potatoes 2 and 30, sweet corn 10 and 32.
* **For the 10 of these crops the revision has field-observed degree-days for** (its
  Table 6.11: tomatoes, lettuce, carrots, onions, potatoes, broccoli, peppers, melons,
  peas and sweet corn; its beans are dry beans, not green), each stage ends when the crop
  has gathered its degree-days since sowing. Fresh-market tomatoes reach full cover and full
  rooting at 985 and end at 2,065: on McAllister's summers, sown 1 May, that is 59 to 74
  days (median 66) and 113 to 132 (median 122), against the 1998 edition's 70 and 145.
* **For the other ten**, the 1998 days are taken as right for the farm's normal year:
  the mean of each day of the year over a record of past years (`climate` in the config:
  a daily file as `tools/weather_csv.py` writes from NASA POWER). On any day the crop is
  as far through its curve as a normal year would have taken it to gather the
  degree-days this one has given it since sowing, which is how the revision's own Table
  6.12 turns those days into degree-days, at a representative place rather than this
  farm.

A day the station missed counts as a normal one; without the farm's record, the mean of
the last week's, and a crop is clocked only when the station read nine in ten of its days
since sowing. Each morning's decision says how far through its curve the crop is
(`crop_gdd`, or `crop_days`) beside the calendar (`calendar_days`), and whether by warmth
(`by_warmth`). Without a station it is the calendar.

**Backtested** on the thirty summers, sown on 1 May, by the weather with no probe. The
virtual crop goes through its curve by the season's warmth; the advice either keeps the
calendar or keeps the same clock:

| | water, mean a season | summers short | a single summer's water against the calendar's |
| --- | --- | --- | --- |
| tomatoes, the advice on the calendar | 569 mm | 0 | |
| **tomatoes, the advice by warmth** | **559 mm** | **0** | −13% (2012) to +9% (2009) |
| lettuce, the advice on the calendar | 292 mm | 0 | |
| **lettuce, the advice by warmth** | **292 mm** | **0** | −10% (2016) to +6% (2012) |

Measured on the simulator of 2026-10-16, three draws of the forecasts' noise; the single
summers are the furthest of the three.

On average it changes little; in a single year it moves the water by up to an eighth,
toward what the virtual crop used. The calendar's advice was never short
either: the balance waters to field capacity with margin, so a crop running early or late
on this farm costs drained water rather than stress. Where it would matter more is a crop
whose stages are near their water's limit, and a farm far from its normal year.

### Plantings at different stages

A bed often holds plants at different stages side by side: a succession sown a few weeks
apart, a replant in a gap, lettuce under tomatoes. One curve does not fit them all. A
bed can name each (`Bed.plantings`; in the config
`"plantings": [{"crop": "tomato", "planted": "2026-05-01"}, {"crop": "lettuce", "planted": "2026-06-15"}]`),
each on its own clock, and the advice works to the range of depths their roots span
(`grown`):

* **When to water is set by the youngest roots.** The bed is due when the soil as deep
  as its shallowest planting's roots has used its share of its water, a third, as the
  whole root zone's is.
* **How much is set by the oldest.** The refill brings the soil back to field capacity
  down to the deepest roots, so watering on the young plants' account never shorts the
  old ones.
* **The crop coefficient** for the weather's balance is the plantings' mean.

A planting not yet sown counts for nothing. Each decision gives the depth the watering
was timed by (`timing_depth_cm`) beside the root zone's (`root_depth_cm`), and the
plantings' stages (`inputs.plantings`). When it is the youngest roots that make the bed
due, it says so:

> Water tunnel bed 3 today: its shallowest roots, in the top 15 cm, have used 39% of the
> water they can reach. About 20 mm brings the bed back to field capacity, down to its
> deepest roots at 50 cm.

By probes, the young roots' soil is read by the probes in it, or, where none is that
shallow, by the shallowest. A probe among the young plants, as shallow as their roots, is
what reads them truly. **A planting can name the probes set among it**
(`(crop, planted, (sensor id, …))`; in the config, `"probes": [...]`): the youngest
planting's own probes then time the watering, the oldest's, with any no planting names,
measure the refill, and the refill is at least what the young planting's soil has lost.

**Backtested** on the thirty summers: tomatoes sown on 1 May, lettuce sown among them on
15 June, each in its own patch of the same silt loam, watered whenever the bed is:

| | water, mean a season | tomatoes' summers short, hours | the lettuce's summers short, hours |
| --- | --- | --- | --- |
| by the weather, told the tomatoes alone | 569 mm | 0 | 22, 354 to 384 |
| **by the weather, told both** | **652 mm** | **0** | **0** |
| probes at 10, 30 and 60 cm among the tomatoes, told the tomatoes alone | 627 mm | 5 to 8, 21 to 112 | 22 to 24, 653 to 825 |
| **the same, told both** | **658 mm** | **5 to 8, 21 to 112** | **2 to 5, 10 to 67** |
| the one at 10 cm moved among the lettuce, told both | 783 mm | 5 to 12, 95 to 233 | 4 to 7, 51 to 92 |
| a fourth at 10 cm among the lettuce, told both | 649 mm | 4 to 7, 31 to 102 | 1 to 5, 12 to 46 |
| **the same, each probe named for its planting** | **632 mm** | **5 to 8, 21 to 112** | **2 to 6, 29 to 90** |

Measured on the simulator of 2026-10-16
([below](#the-crops-water-use-and-the-soils-surface)), three draws of the noise: the water
is their mean, the summers and hours short the least and most of the three. The
tomatoes' hours short are the ones at the end of their initial stage
([above](#a-crop-that-grows)). Before 2026-10-15 the backtest grew the lettuce's patch as a
seedling from the start of the season and counted its hours short from then, so lettuce
sown on 15 June was "short" in May, and every table here before then overstated its
shortfall (`backtest`'s `second`).

* **By the weather, the lettuce must be named.** Told the tomatoes alone, the advice left
  it short in 22 summers of 30: its 15 cm of roots, in a patch now drying at its surface,
  use their water long before the tomatoes' deep root zone is due. On the soil of
  2026-10-15 it was never short, water rising from below carrying it. Told both, never, on
  a seventh more water.
* **By probes among the tomatoes**, told the tomatoes alone, the lettuce went short in 22
  to 24 summers; told both, in 2 to 5.
* **A probe in the lettuce's patch.** Until the lettuce is sown its patch is bare. On the
  simulator before 2026-10-16 a bare patch lost no water at all, and a probe there, unnamed,
  read as one of the tomatoes', held their watering back: they went short in 6 to 8
  summers, 477 to 1,266 hours. Now the bare patch dries at its surface, as a real one does,
  and an unnamed probe there misleads far less: moved there, it leaves the tomatoes short
  somewhat more (5 to 12 summers, 95 to 233 hours) on a fifth more water; added as a
  fourth, the plantings fare
  about as well as with each probe named for its planting (`(crop, planted, (sensor id,
  …))`). Naming still keeps a probe from counting before its crop is sown.
* Two plantings this far apart in age are still better on two valves.

### Roots that stop

The crop's curve is for a soil that lets roots go. Something can stop them sooner:

* a hardpan or plough pan;
* the compacted fill under a new garden;
* rock;
* the floor of a raised bed.

Advice that follows the curve then counts water the roots cannot reach. It waits too
long, and refills less than the roots used. How deep roots run through a season, and what
shows it, is in [the root-depth note](root-depth.md). There are two
ways to give the advice the right depth:

* **`Bed.rooting_limit_mm`**, set by hand once the farmer has dug and found the pan. The
  crop's curve stops at it. A probe at that depth or below it sits in the pan, reading soil
  the roots do not enter, so it is not counted.
* **Root signs from the probes** (`root_signs`, `rooted`), over the last two weeks. A
  probe's dry days are those that started no wetter than its field capacity, with nothing
  wetting it; its field capacity is the lower of the bed's and its own. A probe whose soil
  fell less than 0.002 a day over three or more of them is **level**: nothing draws on it.
  One that fell faster has roots, or is draining, and two tests tell which:
  * **by field capacity**, the default: a probe that went 0.02 under field capacity **has
    roots**. Just past field capacity a soil still drains about that fast, but only
    roots, or the sun near the surface, take it well below;
  * **by the stair-step**, with `Advisor(stair_step=True)` and the farm's timezone (its
    station's, or `Advisor(timezone=…)`): roots draw by day, so a probe that does 70% or
    more of its falling per hour between 08:00 and 18:00, rather than between 20:00 and
    04:00, **has roots**, and one that falls at least as fast by night **has none**;
    drainage, and water creeping up to roots above, run day and night alike. Between the
    two it says nothing.

  Take a probe without roots that the crop's curve says the roots passed at least 15 cm
  ago, under one that has them. The roots likely stop between the two, and a note says
  so. A stop seen on three of the last seven mornings stands on mornings that cannot see
  it, when waterings leave too few dry days to judge by.

  > Tunnel bed 3's crop should have roots to about 60 cm by now, but its probe at 30 cm
  > has stayed level through its dry days while the one at 10 cm has dried: something may
  > be stopping the roots, a hardpan or compacted soil. The advice now waters when the top
  > 20 cm has used its share, and still refills to 60 cm. If you know how deep the soil
  > lets roots go, set the bed's rooting limit.

  **A stop only changes when to water, never how much.** The watering is timed by the
  soil above half way to the level probe, as for a young planting (above); the refill is
  still each probe's own deficit down to the curve's depth. Under a real stop the probes
  read wet and add nothing to it; if the roots are there after all, they still get their
  water. Counting the roots only to half way, as a first version did, also cut each
  refill to the top 20 cm: on the thirty summers with no pan at all, the stops it saw
  wrongly then left the crop short in 3 summers, for 714 hours (with the 1998 curve).

**Backtested** on the thirty summers, tomatoes sown on 1 May with probes at 10, 30 and 60
cm, the virtual roots stopped at 30 cm whatever the curve says, the 2025 revision's curve
taking them to 60 cm. Two pans: one that stops the roots alone, the soil below it the
same silt loam; and a dense one, as a plough pan is, 5 cm of compacted silt loam passing
0.5 mm of water an hour (`growing_bed(pan_mm=…)`). Three draws of the noise each; the water
is their mean.

| | water, mean a season | summers short | hours short, in all |
| --- | --- | --- | --- |
| *a pan that stops roots:* the crop's curve alone | 612 mm | 5 to 8 | 25 to 114 |
| the curve and root signs, by field capacity | 734 mm | 5 to 8 | 25 to 114 |
| the curve and root signs, by the stair-step | 735 mm | 5 to 8 | 25 to 114 |
| the rooting limit set at 30 cm | 592 mm | 5 to 8 | 21 to 112 |
| *a dense pan:* the crop's curve alone | 494 mm | 10 to 18 | 120 to 257 |
| the curve and root signs, by field capacity | 614 mm | 9 to 12 | 99 to 134 |
| the curve and root signs, by the stair-step | 616 mm | 9 to 12 | 84 to 135 |
| **the rooting limit set at 30 cm** | **590 mm** | **6 to 9** | **34 to 115** |
| *no pan:* the curve and root signs, by field capacity | 627 mm | 5 to 8 | 21 to 112 |
| the curve and root signs, by the stair-step | 624 mm | 5 to 8 | 21 to 112 |

Measured on the simulator of 2026-10-16
([below](#the-crops-water-use-and-the-soils-surface)). The hours short shared by most rows
fall at the end of the initial stage ([above](#a-crop-that-grows)), before any pan matters.

* **Over a pan that only stops roots, the curve alone does not starve the crop.** The soil
  below the pan dries as water rises out of it to the roots above, so the bed's average
  falls and the advice waters. On the simulator's earlier soil, which moved no water below
  field capacity, the soil under the pan stayed at field capacity, held the average up, and
  the crop was short in 29 summers of 30 for eleven days on average (7,563 hours). That was
  the case the root signs were built for.
* **Over a dense pan it does go short**, in 10 to 18 summers: water rises through the pan
  too slowly. The root signs cut the hours short by up to half, for a quarter more water; the rooting
  limit set by hand does best, on less.
* **But the root signs no longer tell a pan from none.** With or without one, they see a
  stop on 74 to 87 of a season's 145 mornings, the stair-step on 59 to 88. With roots
  densest at the top, as now, the probe at 30 cm is drawn on lightly and reads near level
  in a soil with no pan at all. On the soil of 2026-10-15, roots drawing evenly, the test by
  field capacity saw a stop that was not there on 9 to 12 mornings, the stair-step on 24 to
  29. Where they help, over the dense pan, it is by timing the watering by the top 15 cm,
  which a young crop's or a shallow bed's earlier refill point would do as well
  ([above](#the-beds-own-soil)).

So on the simulator as it now is, the root signs do not do what they were built for:
their stop is right over a pan and wrong without one about as often. Whether a real crop's
roots read so, and whether the level line should be judged against what the roots' own
density predicts, is not known ([UNTESTED](../UNTESTED.md)). The test by field
capacity stays the default, and the stair-step an option, until that is decided; it is
one of the maintainer's open choices. A first version counted the
probe at 30 cm, set into the pan; leaving it out, and now any probe at the roots' front,
fixed that.

## Hot days, and beds under cover

**On a hot day.** FAO-56 adjusts the depletion fraction for how fast a crop is drying
(the 2025 revision's Eq. 8.5): `p + 0.04 (5 − ETc)`, ETc in mm a day. With
`Bed.adjust_p`, the advice lowers its third that way on a day drying faster than 5 mm,
from the probes' drying rate or, by the weather, the day's Kc · ETo, so the crop is
watered with more water left. FAO-56 also raises p on a mild day; that is not done here.
On the thirty summers:

| | water, mean a summer | summers short | hours short, in all | worst summer |
| --- | --- | --- | --- | --- |
| the backtest bed | 289 mm | 0 to 3 | 0 to 4 | 2 h |
| **the backtest bed, `adjust_p`** | **297 mm** | **0 to 1** | **0 to 1** | **1 h** |
| the shallow yard, each layer's values | 275 mm | 19 to 22 | 119 to 222 | 32 h |
| the shallow yard, `adjust_p` | 275 mm | 19 to 22 | 119 to 222 | 32 h |

Measured on the simulator of 2026-10-16, three draws of the noise. On the earlier soil the
backtest bed was short in 3 summers (72 hours), and 2 (33) with `adjust_p`; Eq. 8.5 both
ways, raising p on mild days too as FAO-56 does, saved water there and left it short in
7, and that option was taken out.

On the backtest bed it took the few hours short to about none for 3% more water. On the
shallow yard it changed nothing at all: its 15 cm of roots never dry 5 mm a day, though
they are short often; what that bed needs is an earlier refill point
([above](#the-beds-own-soil)).

**Whether to make it the default** was tried across the backtests above, each run again
with it on (thirty summers each; water, summers short, hours short):

| | off | `adjust_p` |
| --- | --- | --- |
| tomatoes by probes at 10 and 30 cm | 595 mm, 5 to 8, 21 to 112 | 920 mm, 5 to 8, 21 to 112 |
| tomatoes by probes at 10, 30 and 60 cm | 627 mm, 5 to 8, 21 to 112 | 997 mm, 5 to 8, 21 to 112 |
| lettuce among tomatoes, probes among the tomatoes, told both: the lettuce | 658 mm, 2 to 5, 10 to 67 | 990 mm, 1 to 2, 3 to 27 |
| lettuce among tomatoes, a probe named for each: the lettuce | 632 mm, 2 to 6, 29 to 90 | 910 mm, 0 to 2, 0 to 26 |
| tomatoes over a pan at 30 cm, root signs | 734 mm, 5 to 8, 25 to 114 | 1,041 mm, 5 to 10, 21 to 114 |
| the backtest bed under a tunnel, told | 492 mm, 0 to 2, 0 to 1 | 492 mm, 0 to 1, 0 |
| lettuce by probes at 10 and 30 cm | 266 mm, 8 to 15, 46 to 366 | 350 mm, 8 to 15, 46 to 366 |
| tomatoes or lettuce by the weather | 569 and 292 mm, 0, 0 | 576 and 296 mm, 0, 0 |

It only acts where the crop draws well over 5 mm a day, which on this farm is tomatoes at
mid-season; a lawn seldom does. On the simulator of 2026-10-16 it ended none of the
crops' shortages, which fall at the end of their initial stage, before mid-season, and
added a half more water, most of it drained; for the lettuce among tomatoes it cut the
lettuce's hours short to a third, on the tomatoes' extra water. On the simulator's
earlier soil it ended most of the shortages there were, at a fifth to a third more water.
**So it stays off by default**: a bed whose probes show it running short in hot spells
can be given it. (Measured on the simulator of 2026-10-16, three draws of the noise each.)

**A bed under cover.** Rain forecast for the farm does not reach a bed under a tunnel or
a roof, and "rain is coming: wait" is the wrong advice for it. `Bed.rain_share` says how
much of the rain reaches the bed, 0 under cover; the forecast that holds a watering, and
the weather balance's rain, are scaled by it (`rain_reaching_mm`). Left unset, it is all
of the rain, unless the bed's probes show it covered: through the last three storms of
15 mm or more in the farm's rain gauge (`Advisor(rain_gauge=…)`, or the station's) that
fell while its valve stayed shut, none moved a probe in its root zone by 0.03, as a mean
of three readings, within 12 hours of the rain's end (`covered_by_its_probes`). Only a
bed whose valve reports its waterings is judged: without it a watering could not be told
from the rain. A share between none and all is not learned.

On the thirty summers, the backtest bed under a tunnel, its forecasts the open sky's,
watered by a valve that reports:

| | water, mean a summer | summers short | hours short, in all | mornings told rain was coming |
| --- | --- | --- | --- | --- |
| not told it is covered | 488 mm | 0 to 3 | 0 to 55 | 112 to 137 |
| covered, learned from the probes | 489 mm | 0 to 3 | 0 to 55 | 70 to 99 |
| **told it is covered** | **492 mm** | **0 to 2** | **0 to 1** | **0** |
| *in the open*, the gauge and the learning on | 289 mm | 0 to 3 | 0 to 4 | 30 to 49 |

Measured on the simulator of 2026-10-16, three draws of the noise, the mornings over the
thirty summers. Told, it was never held for rain that could not reach it. Learning took
the first part of each summer to see three storms, and held it on a quarter to a third
fewer mornings. In the open the learning never took the bed for covered: the water and
the hours short are the open bed's without it.

## Water below field capacity

**The simulator's soil moves it, since 2026-10-15.** Before, its layered soil
(`physics.LayeredBed`) drained a layer wetter than its field capacity into the one below
and moved no water at all between layers drier than that. A real soil does: slowly, but
not slowly beside a lawn's days. Now each horizon holds its water along van Genuchten's
curve, fitted through its own saturation, its field capacity at 33 kPa and its wilting
point at 1500 kPa, and passes it as Mualem's conductivity from its saturated conductivity
lets it. Water moves between neighbouring layers by Darcy's law, suction and gravity, at
the geometric mean of the two layers' conductivities (`physics.Horizon`). Every table here
with a crop or a lawn was run again on it, three draws of the noise each.

**What found it.** A lawn led by one probe at 7 cm (the lawn drill's tall fescue, 15 cm of
roots, in silt loam) was short in 13 summers of 30, 255 hours, where the same lawn by the
weather never was. Morning by morning in 2008, each watering, sized to what the probe
read, wet the top 10 cm a little past field capacity, and the grass used that before it
drained. The bottom 5 cm of the roots stayed near 0.19 while the probe read 0.28, and the
probe never saw them. Carsel and Parrish's (1988) mean silt loam, through van Genuchten
and Mualem, passes 2.5 to 6 mm a day between such layers 2.5 cm apart; the old soil
passed none.

**What moved then.**

| | the earlier soil | the soil of 2026-10-15, three draws |
| --- | --- | --- |
| a lawn, one probe at 7 cm | 178 mm, 13 summers short, 255 h | 106 mm, 1 to 8 summers, 4 to 137 h |
| a lawn, probes at 7 and 12 cm | 182 mm, 4, 60 h | 99 mm, 4, 46 to 67 h |
| a lawn, one probe at 10 cm | 214 mm, 7, 115 h | 101 mm, 7, 36 to 146 h |
| a lawn told 0.70 that uses 0.95, by the weather | 164 mm, 10, 165 h | 166 mm, 0, 0 |
| tomatoes over a pan, the crop's curve alone | 198 mm, 29, 7,563 h | 324 mm, 0, 0 |
| tomatoes by probes, the crop not known | 192 mm, 8, 636 h | 165 mm, 0, 0 |
| lettuce among tomatoes, probes among the tomatoes, told both: the lettuce | 258 mm, 26, 974 h | 250 mm, 0, 0 |

Led by probes, beds were short far less often, and most took less water. Water held near
capacity at the top reached the bottom of the roots on its own, and water below the roots
rose to them. On the simulator of 2026-10-16 several of those results went back the other
way ([below](#the-crops-water-use-and-the-soils-surface)): the soil was moving water
rightly, but the crop was using it too gently.

**What it rests on.** The conductivity between two layers is their geometric mean, a
choice: the arithmetic mean would move water faster, the harmonic slower. Since 2026-10-16
each soil's residual water and Mualem's `L` are Rosetta3's for its texture and bulk density
(`physics.SANDY_LOAM`, `COMPACTED_CLAY`, the growing bed's silt loam), where they were none
and 0.5. Checked against HYDRUS-1D on the same soils, the simulator's water content was
within 0.0002 to 0.002 while water spread and rose, and 0.002 to 0.012 while a watering
soaked in ([soil models](soil-models.md#what-the-simulator-took-2026-10-16)).

**Learning reads a soil that moves water low.** On this soil a light watering over drier
soil goes on spreading down after it has drained, so the probe settles lower than the
soil's field capacity, and the median of many such drain-downs read low: in 2008 a lawn's
probe learned 0.27 where the soil's is 0.30, and watered back only to that, the lawn sat
near half its water gone. The upper quartile of the drain-downs is now learned instead
([above](#the-beds-own-soil)); learning from the drain-downs after soakings alone was
tried, and read lower still.

**A probe in another soil needs that soil's values.** In the builder's yard, sandy loam
over compacted clay at 10 cm, one probe at 7 cm kept the lawn watered in every summer, on
493 mm. A second at 12 cm, in the clay, with the bed given one soil's values, read wet all
summer: 25 to 26 summers short (1,865 to 2,946 hours). Given each layer's values
(`Bed.layers`, [above](#the-beds-own-soil)), 16 to 20 (45 to 140 hours) on 270 mm. (The
simulator of 2026-10-16.)

## The crop's water use and the soil's surface

**The simulator's crop, since 2026-10-16.** Checked against the models agriculture uses
([soil models](soil-models.md)), its soil moved water well but its crop
was too gentle, and its bare soil never dried. It now has, after FAO-56 (Allen et al.
1998) and its revision:

* **the crop's whole use to its `p`**, then less in a line to the wilting point (FAO-56's
  `Ks`, Eq. 84), each crop's own `p`; before, it used less as soon as the soil was below
  field capacity;
* **its roots densest at the top**, drawing from each layer in a line falling to none at
  the roots' depth (Prasad 1988); before, from each layer by the water it could give;
* **the soil's surface drying**, FAO-56's dual coefficient: the crop's basal coefficient
  drawn by the roots, and the top 10 cm evaporating apart from it as the canopy leaves it
  open (Eqs. 69 to 79); bare soil dries in two stages. A mown lawn covers 0.95 of its
  ground, where FAO-56's estimate from its coefficient (Eq. 76) would leave a third bare;
* **a dense pan** as an option, a horizon that passes water slowly as well as stopping
  roots ([above](#roots-that-stop)).

At USCRN's Crossville station, under grass, the simulated soil followed the probes hour
by hour (correlation 0.85 to 0.96), and dried on rain-free days at 0.74 of the rate the
probes saw at 5 cm, 0.85 at 10 and 1.26 at 20, where the crop before dried them at 0.56,
0.71 and 1.12 ([soil models](soil-models.md#what-the-simulator-took-2026-10-16)).

**What it showed, and what the advice took from it.** A crop that uses its water whole
until its refill point, from the top first, empties a shallow zone faster than the advice
had been built for, and a young crop's wet soil loses more than its coefficient said. So:

* **learning by the upper quartile** of the drain-downs, not their median
  ([above](#the-beds-own-soil));
* **a second look at 13:00**, at the top of this page;
* **a young crop watered at a fifth of its water gone** through its initial stage
  (`Bed.young_fraction`), its few roots in the soil the sun dries: tomatoes' first month
  went short in 25 summers of 30 without it, 9 with it, for 4% more water. Among older
  plantings, it is the refill point of the young one's roots alone;
* **by the weather, the dual coefficient** for a bed whose crop is named, so the balance
  counts a young crop's wet soil, and **the crop's own `p`** for when it slows; and **a
  margin**, the crop's use counted a fifth above FAO-56's estimate where nothing measures
  it ([below](#by-the-weather-with-no-probe));
* **a silent probe's bed carried from the mean of its last three hours** of good
  readings, not from one ([below](#by-the-weather-with-no-probe)).

**What moved**, the lawn drill's tall fescue and the backtest crops, thirty summers, three
draws (water a season; summers short; hours short):

| | the soil of 2026-10-15 | the simulator of 2026-10-16 |
| --- | --- | --- |
| tomatoes by probes, crop known | 247 mm, 0, 0 | 595 mm, 5 to 8, 21 to 112 |
| tomatoes by the weather, crop known | 300 mm, 0, 0 | 569 mm, 0, 0 |
| lettuce by probes, crop known | 104 mm, 0, 0 | 266 mm, 8 to 15, 46 to 366 |
| lettuce by the weather, crop known | 147 mm, 0, 0 | 292 mm, 0, 0 |
| a lawn, one probe at 7 cm | 106 mm, 1 to 8, 4 to 137 | 181 mm, 1 to 2, 7 to 31 |
| a lawn by the weather | 262 mm, 0, 0 | 357 mm, 0, 0 |
| the backtest bed, its probe | 189 mm, 3, 72 | 289 mm, 0 to 3, 0 to 4 |
| the backtest bed by the weather | 241 mm, 0, 0 | 329 mm, 0, 0 |
| the shallow yard, each layer's values | 199 mm, 2 to 7, 24 to 123 | 275 mm, 19 to 22, 119 to 222 |
| tomatoes over a pan that stops roots, the curve alone | 324 mm, 0, 0 | 612 mm, 5 to 8, 25 to 114 |

Every crop takes about twice the water it did: on the simulator before, a crop used less
as soon as its soil was below field capacity, and a bare or young bed lost nothing at its
surface. Most of the new shortages fall in a few days at the end of a crop's initial stage
([above](#a-crop-that-grows)), and on beds with little water to spare. By the weather,
with its margin, no bed whose crop is named went short.

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
  once it has used its own `p` (eq. 84). For a bed whose crop is named, `(Ks Kcb + Ke) ETo`,
  FAO-56's dual coefficient: the crop's basal coefficient and its wet surface's
  evaporation, which runs well above a young crop's single coefficient when the soil is
  wetted every day or two.
* **A margin**: with nothing measured, the crop's use is counted a fifth above FAO-56's
  estimate (`WEATHER_MARGIN`). The estimate is not the bed: the station's reference ET and
  the crop's coefficient can each be a tenth or more out, and a balance that counts low
  waters late and short, and its shortfall adds up until rain, since each watering refills
  only what it counted. Counted high, it waters a little early and a little over, and the
  excess drains.
* **Watering is the valve's recorded minutes** times the bed's `application_mm_per_h`.
  Without that record, the advisory's own advice to water is taken as followed, and the
  advice says so. A balance that never sees the watering it asked for asks again every
  morning: on the backtest bed, on the simulator before 2026-10-15, that called for 1,027 mm
  in 2013.
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
| 2013 | 225 mm | 208 mm | 0 |
| 2012, a drought | 347 mm | 319 mm | 0 |

**Why the margin.** The virtual bed loses water by Hargreaves' formula and a crop
coefficient of 1.05; the balance counts Penman–Monteith and 1. Over the thirty summers the
bed so used about a fifth more than the balance counted, as a farm's real bed may, either
way. With no margin it was short in 21 summers of 30 (1,945 hours) on 249 mm; a tenth, 6
(101 hours) on 287; a fifth, none, on 329. Watering a fifth more each time with the balance
unchanged left 8 (118 hours) on 298 mm: it still watered late. Where the balance was not
low, the margin cost water and nothing else: a lawn 27% more, tomatoes 21%, lettuce 14%.
(The simulator of 2026-10-16; on the one before, whose crop used less as its soil dried,
the bed by the weather alone was never short, the balance's own excess its margin.)

**When a bed's probes go silent or untrusted**, the advisory used to say "unseen" or
"untrusted" and give no advice until they came back. With the station, it now carries the
bed on the weather from the probes' last good readings:

* that reading's depletion, at each probe's soil and learned field capacity, is the
  balance's starting point, the reading the mean of each probe's good ones in the last three
  hours before it fell silent (`ANCHOR_HOURS`): on the 2012 drought one reading 0.027 over
  the soil, taken alone, started the balance at half the depletion the bed had, and it went
  short 15 hours in the outage's first two days;
* the days after it are stepped by the weather;
* every advice says to check the probes.

> bed 3's probes have given no reading to trust for 81 hours. By the farm's weather since
> their last good one, about 55% of the water its plants can use is gone: water it today,
> about 30 mm. And check the probes.

(The test's bed, its probe silent from 11 July.)

It runs as long as the balance does, sixty days, because a bed anchored on its last
reading is never worse off than one that never had a probe. On the 2012 drought, with the
backtest bed's probe silent for the two weeks from 1 July:

| | looks with no advice | stressed hours |
| --- | --- | --- |
| without the station | 27, two a day | 191 |
| with it | 0 | **0** |

(The simulator of 2026-10-16, on 446 mm; before, 13 mornings without advice and 142
hours.)

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
safe error; and **never below the margin**: a probe's rate can raise the balance past
the fifth it counts over FAO-56, but a slower one is recorded and not used
(`margin_held`). It is not used:

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
| by the weather alone | 329 mm | 0 of 30 |
| **with a reference, as built** | **332 mm** | **0** |
| the reference's probe reading 0.05 low | 337 mm | 0 |
| the reference's probe reading 0.05 high | 329 mm: it never corrects | 0 |

The simulator of 2026-10-16, three draws. The probe-led bed beside it was given 398 mm a
summer, more than the bed it corrects, and seldom read a rate above the margin. On the
2012 drought, watered often on its own advice, its probe read its bed drying at 85% to
111% of FAO-56's estimate; taken half way to that, the margin dropped, it left the bed
short 33 hours; held at the margin, never. On the simulator
before, without the margin, the correction saved 2% (237 mm against 241), never short.

**Why only half way, and never below the margin.** The rate a probe saw over a month does
not hold through a hot spell, and a probe whose bed is watered often reads its rate low:
the soil above its learned level after a watering is not counted. Corrected all the way,
on the simulator before, the bed went short in one summer in six. A probe reading high,
used without the learning check, took the bed to 397 stressed hours on the 2012 drought.
With it, the probe was never used.

The balance's ET is Penman–Monteith, while the virtual bed loses water by Hargreaves'
formula. So it runs on a model of the bed that is not the bed, as it would on a farm. In
the dry summer it watered a tenth more than the probe did, and still well under the 552 mm
a drip timer uses. A probe reads the bed itself; this reads only the sky. A pyfao56-style
reset of the balance from a probe in the same zone is not built.

## A soak test: field capacity on the day

Learning a probe's field capacity takes three soakings it drains from; the soak test makes
one on purpose, and checks the probes on the way ([regimens/soak_test.star](../../modules/soilwater/regimens/soak_test.star)).
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

The first **regimen** (Q10; [modules/rules](../../modules/rules/README.md#regimens)):
[regimens/watering_check.star](../../modules/soilwater/regimens/watering_check.star), a few lines of Starlark. When
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
| 2013, where the threshold was chosen (five sets of blocked days) | 77 | 25 of 25 | 0 of 52 | watered beds rose at least 0.57 of their expected rise; blocked ones at most 0.42 |
| 2012, a summer not looked at until the threshold was set (four sets) | 85 | 24 of 24 | **1 of 61** | a watered bed at **0.47**, under the 0.5 line |

On the simulator of 2026-10-16, with the afternoon's look: a watering blocked in the
morning is advised again that afternoon, and blocked again, so a blocked day is often two
checks. On the earlier simulator the closest calls were 0.74 and 0.27 in 2013, and a
watered bed at 0.55 in 2012.

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
rightly, all five, and said nothing on the ten that arrived. A shutting reported for a valve
never seen opening is a lost message, so the check falls back to saying both rather than
guessing.

The 2012 false alarm is the honest caveat, foreseen when it was a near miss on the earlier
simulator. A bed that soaks its water up slowly, a probe set deep, or a crop that draws
hard in the hours after a watering can fall below half on a day the water did arrive. The
share is a parameter, and a season of a real bed's waterings is what would set it.

## A probe out of the soil

A probe lifted by a mower or a frost, or pushed in beside an air gap, reads the air: almost
no water. Every health check passes it, since the reading is in range and still moves, and
the advice would read the driest bed on the farm and ask for a full refill every morning.

Nothing in soil reads that dry. Below the surface only roots dry the soil, and they stop
at its wilting point. The sun dries the top further, and FAO-56 takes that layer, the top
0.10 to 0.15 m, to dry "halfway between oven dry (no water left) and wilting point"
(Rev.1 Eq. 7.5, the 1998 edition's Eq. 73). So a reading more than 0.03 below half the
wilting point within the top 15 cm, or below the wilting point under them (`soil_floor`),
0.03 being a factory calibration's usual error, is not read. With no other probe the
advice says why, and with the farm's station the bed is carried on the weather from the
last reading that was in the soil:

> bed 3's probe at 20 cm reads 2.0% water, drier than its soil can be (9.0% at least): it
> may be out of the soil, or in an air gap beside it. There is no advice for bed 3 today.
> Push the probe back in and firm the soil around it.

With another probe still in the soil, the advice comes from that one, and a note beside it
says the same about the first.

| the bed's soil (wilting point) | the floor, top 15 cm | the floor, below |
| --- | --- | --- |
| silt loam (0.12) | 3% | 9% |
| clay (0.25) | 9.5% | 22% |
| sand (0.05) | none: below zero | 2% |

So it can tell a probe in the air from dry soil only where the soil holds some water at its
wilting point. In sand it cannot, and says nothing. That is the case of the openSenseMap
LSE01 reading 2.1 to 2.4% ([notes/test-data-sources](test-data-sources.md)):
out of the soil in a loam, possible in a dry sand, and its keeper has not said which.
Not built: the other sign, a probe that rises after neither the rain the gauge recorded nor
the watering the valve did, which would catch it in sand too.

## The trials of 2026-10-17

*Before [the audit of 2026-10-18](#the-audit-of-2026-10-18): the probe-led beds' refills went on
within the hour and ran off, the advice read forecasts issued after it, and the crop did not
make up for a dry top. Its figures stand as they were run.*

[trials.py](../../modules/soilwater/trials.py) on code 4475640: ten beds, each with the
choices that bear on it, through McAllister's and Davis's recorded summers of 1991 to 2025,
each summer on two farms drawn for it (`backtest.VirtualFarm`), the farm's water loss
Penman–Monteith with the day's own wind; 5,320 backtests. "Tuned" is McAllister's 1991 to
2020, which the defaults were chosen on; "held out" the rest, nearly all Davis. Made by
`python3 trials.py report`.

| bed | summers | water | lost transpiration | summers losing over 1 mm | hours short of air |
| --- | --- | --- | --- | --- | --- |
| bucket, its probe, tuned | 60 | 239 mm | 0.1 mm | 3 | 0 |
| bucket, its probe, held out | 80 | 645 mm | 1.2 mm | 17 | 0 |
| bucket, by the weather, tuned | 60 | 329 mm | 0.0 mm | 0 | 1 |
| bucket, by the weather, held out | 80 | 660 mm | 10.2 mm | 20 | 0 |
| tomatoes, probes, tuned | 60 | 506 mm | 1.8 mm | 25 | 185 |
| tomatoes, probes, held out | 80 | 1102 mm | 13.8 mm | 74 | 57 |
| tomatoes, by the weather, tuned | 60 | 570 mm | 0.7 mm | 14 | 307 |
| tomatoes, by the weather, held out | 80 | 1057 mm | 5.0 mm | 47 | 174 |
| lettuce, probes, tuned | 60 | 251 mm | 1.8 mm | 29 | 142 |
| lettuce, probes, held out | 80 | 458 mm | 20.8 mm | 73 | 44 |
| lettuce, by the weather, tuned | 60 | 297 mm | 0.5 mm | 12 | 185 |
| lettuce, by the weather, held out | 80 | 528 mm | 2.7 mm | 36 | 120 |
| lawn, its probe, tuned | 60 | 137 mm | 0.4 mm | 7 | 335 |
| lawn, its probe, held out | 80 | 438 mm | 74.5 mm | 70 | 64 |
| lawn, by the weather, tuned | 60 | 357 mm | 0.0 mm | 0 | 529 |
| lawn, by the weather, held out | 80 | 637 mm | 2.5 mm | 11 | 291 |
| yard, its probes, tuned | 60 | 234 mm | 1.5 mm | 26 | 22 |
| yard, its probes, held out | 80 | 547 mm | 21.5 mm | 76 | 2 |
| tomatoes over a dense pan, probes, tuned | 60 | 537 mm | 2.9 mm | 35 | 311 |
| tomatoes over a dense pan, probes, held out | 80 | 1066 mm | 20.1 mm | 78 | 141 |

Each choice against the default it would replace, on the same site, summer and farm: the
difference's mean and its 90% interval over the pairs (water and lost transpiration in mm
a summer, hours a summer with under a tenth of the root zone holding air).

| bed | choice, against the default | summers | water | lost transpiration | hours short of air |
| --- | --- | --- | --- | --- | --- |
| bucket, by the weather | margin 0, tuned | 60 | -79.9 (-86.0 to -73.7) | +0.7 (+0.1 to +1.7) | -0.5 (-0.8 to -0.1) |
| bucket, by the weather | margin 0, held out | 80 | -112.2 (-115.7 to -108.7) | +52.8 (+45.1 to +60.6) | -0.1 (-0.2 to -0.0) |
| bucket, by the weather | margin 0.1, tuned | 60 | -40.5 (-45.7 to -35.6) | +0.0 (+0.0 to +0.1) | +0.0 (-0.2 to +0.3) |
| bucket, by the weather | margin 0.1, held out | 80 | -56.9 (-59.1 to -54.7) | +18.4 (+14.4 to +22.5) | -0.0 (-0.1 to -0.0) |
| tomatoes, probes | signs False, tuned | 60 | -18.6 (-29.4 to -8.5) | +0.6 (+0.3 to +0.9) | -23.8 (-30.6 to -17.4) |
| tomatoes, probes | signs False, held out | 80 | +22.0 (+10.7 to +33.7) | +4.2 (+2.9 to +5.7) | -13.8 (-18.8 to -9.3) |
| tomatoes, probes | young stage, tuned | 60 | -5.3 (-16.2 to +6.0) | +0.2 (+0.1 to +0.3) | -6.5 (-14.0 to -0.2) |
| tomatoes, probes | young stage, held out | 80 | -10.6 (-22.4 to +1.3) | +0.6 (-0.4 to +1.6) | +3.7 (-0.9 to +8.7) |
| tomatoes, by the weather | margin 0, tuned | 60 | -94.4 (-100.4 to -88.6) | +0.3 (+0.2 to +0.4) | -45.3 (-52.1 to -38.6) |
| tomatoes, by the weather | margin 0, held out | 80 | -129.3 (-134.1 to -124.4) | +19.5 (+16.3 to +23.1) | -91.5 (-104.8 to -78.7) |
| tomatoes, by the weather | margin 0.1, tuned | 60 | -52.2 (-58.7 to -45.5) | +0.1 (+0.0 to +0.1) | -22.0 (-27.6 to -16.2) |
| tomatoes, by the weather | margin 0.1, held out | 80 | -65.2 (-69.1 to -61.3) | +3.7 (+2.8 to +4.8) | -58.5 (-68.1 to -49.6) |
| tomatoes, by the weather | young stage, tuned | 60 | -3.1 (-6.8 to +0.2) | +0.0 (+0.0 to +0.0) | -0.4 (-2.1 to +1.4) |
| tomatoes, by the weather | young stage, held out | 80 | -0.5 (-2.0 to +1.0) | +0.2 (+0.1 to +0.3) | -0.8 (-2.0 to +0.2) |
| lettuce, probes | signs False, tuned | 60 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| lettuce, probes | signs False, held out | 80 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| lettuce, probes | young stage, tuned | 60 | -26.4 (-33.9 to -19.1) | +1.3 (+0.9 to +1.9) | -17.2 (-21.9 to -12.8) |
| lettuce, probes | young stage, held out | 80 | -19.1 (-27.1 to -10.3) | +5.7 (+4.1 to +7.6) | -3.9 (-8.2 to +0.2) |
| lettuce, by the weather | margin 0, tuned | 60 | -36.1 (-40.0 to -31.6) | +0.1 (+0.1 to +0.2) | -13.6 (-16.1 to -11.2) |
| lettuce, by the weather | margin 0, held out | 80 | -56.7 (-59.2 to -54.0) | +5.9 (+4.8 to +7.1) | -44.0 (-48.5 to -39.5) |
| lettuce, by the weather | margin 0.1, tuned | 60 | -19.2 (-22.8 to -15.2) | +0.1 (+0.0 to +0.1) | -7.3 (-9.3 to -5.4) |
| lettuce, by the weather | margin 0.1, held out | 80 | -29.7 (-31.6 to -27.7) | +1.4 (+1.1 to +1.8) | -20.2 (-22.4 to -17.9) |
| lettuce, by the weather | young stage, tuned | 60 | -4.4 (-7.4 to -1.3) | +0.1 (+0.1 to +0.2) | -5.7 (-7.7 to -3.8) |
| lettuce, by the weather | young stage, held out | 80 | -3.4 (-5.3 to -1.5) | +0.8 (+0.6 to +1.0) | -1.1 (-3.0 to +1.0) |
| lawn, its probe | p 0.2, tuned | 60 | +104.8 (+89.8 to +119.9) | -0.4 (-0.6 to -0.3) | +263.1 (+232.3 to +295.5) |
| lawn, its probe | p 0.2, held out | 80 | +89.2 (+80.7 to +97.8) | -57.4 (-65.9 to -48.7) | +69.6 (+42.1 to +103.3) |
| lawn, by the weather | margin 0, tuned | 60 | -77.1 (-81.0 to -73.1) | +0.0 (+0.0 to +0.0) | -38.9 (-43.5 to -34.0) |
| lawn, by the weather | margin 0, held out | 80 | -109.4 (-112.1 to -106.5) | +27.4 (+21.9 to +33.1) | -105.9 (-117.3 to -95.4) |
| lawn, by the weather | margin 0.1, tuned | 60 | -43.8 (-47.1 to -40.4) | +0.0 (+0.0 to +0.0) | -21.7 (-25.7 to -17.5) |
| lawn, by the weather | margin 0.1, held out | 80 | -54.8 (-56.6 to -52.7) | +8.4 (+5.8 to +11.5) | -42.1 (-48.3 to -35.7) |
| lawn, by the weather | p 0.2, tuned | 60 | +70.9 (+65.5 to +76.4) | +0.0 (+0.0 to +0.0) | +166.6 (+158.9 to +174.1) |
| lawn, by the weather | p 0.2, held out | 80 | +12.5 (+8.4 to +16.9) | -1.5 (-2.4 to -0.7) | +156.7 (+144.2 to +168.1) |
| yard, its probes | p 0.2, tuned | 60 | +29.3 (+24.6 to +33.9) | -1.2 (-1.5 to -0.9) | +1.4 (+0.9 to +1.9) |
| yard, its probes | p 0.2, held out | 80 | +20.1 (+17.5 to +22.8) | -14.5 (-17.2 to -12.1) | -0.0 (-0.1 to +0.0) |
| tomatoes over a dense pan, probes | signs False, tuned | 60 | -127.9 (-148.7 to -108.1) | +6.0 (+4.8 to +7.2) | -96.5 (-108.7 to -84.3) |
| tomatoes over a dense pan, probes | signs False, held out | 80 | -43.5 (-63.7 to -23.9) | +36.2 (+31.3 to +41.3) | -43.4 (-51.5 to -35.6) |
| tomatoes over a dense pan, probes | young stage, tuned | 60 | -13.3 (-25.5 to -0.9) | +0.2 (-0.0 to +0.4) | -8.3 (-15.8 to -0.7) |
| tomatoes over a dense pan, probes | young stage, held out | 80 | -18.2 (-35.1 to -2.0) | +1.1 (-0.0 to +2.3) | -0.7 (-8.5 to +7.3) |

## Measuring more, 2026-10-18

*Before [the audit of 2026-10-18](#the-audit-of-2026-10-18): the probe-led beds' refills went on
within the hour and ran off, the advice read forecasts issued after it, and the crop did not
make up for a dry top. Its figures stand as they were run.*

The same trial on code c1de215, with what a farm might measure besides (`trials.py`'s
`MEASURES`): the station's wind (`weather_backtest(wind=True)`); the crop's water use, one
number for the season measured to a lognormal 0.07 or 0.15 (`use_measured`); a tension
sensor beside each probe, each sensor a tenth out for good and a twentieth each hour
(`backtest(tension=True)`). Each crossed with the choices it bears on, on the same farms and
summers, 9,380 backtests more; the 5,320 above were not run again, and three of them run
again on c1de215 agreed to the bit. Each against the bed as built, measuring nothing more:
the difference's mean and its 90% interval. Made by `python3 trials.py report`.

| bed | measured, against the bed as built | summers | water | lost transpiration | hours short of air |
| --- | --- | --- | --- | --- | --- |
| bucket, by the weather | wind measured, margin 0, tuned | 60 | -111.0 (-118.9 to -103.3) | +2.2 (+0.7 to +4.0) | -0.5 (-0.9 to -0.2) |
| bucket, by the weather | wind measured, margin 0, held out | 80 | -83.0 (-87.1 to -79.1) | +28.1 (+22.7 to +34.2) | -0.1 (-0.2 to -0.0) |
| bucket, by the weather | use measured, sd 0.07, margin 0, tuned | 60 | -69.5 (-83.3 to -55.2) | +0.0 (+0.0 to +0.0) | -0.4 (-0.8 to +0.0) |
| bucket, by the weather | use measured, sd 0.07, margin 0, held out | 80 | -73.5 (-87.5 to -59.9) | +19.0 (+12.8 to +25.5) | -0.1 (-0.2 to -0.0) |
| bucket, by the weather | use measured, sd 0.07, wind measured, margin 0, tuned | 60 | -94.9 (-110.0 to -81.0) | +0.1 (+0.0 to +0.2) | -0.4 (-0.9 to +0.0) |
| bucket, by the weather | use measured, sd 0.07, wind measured, margin 0, held out | 80 | -41.5 (-56.6 to -25.5) | +0.6 (-4.9 to +5.7) | -0.0 (-0.1 to +0.0) |
| bucket, by the weather | use measured, sd 0.15, margin 0, tuned | 60 | -63.2 (-84.5 to -41.9) | +0.9 (+0.2 to +1.7) | -0.2 (-0.6 to +0.2) |
| bucket, by the weather | use measured, sd 0.15, margin 0, held out | 80 | -62.7 (-83.1 to -42.0) | +29.7 (+20.5 to +40.4) | -0.1 (-0.2 to +0.0) |
| bucket, by the weather | use measured, sd 0.15, wind measured, margin 0, tuned | 60 | -92.8 (-113.2 to -72.5) | +3.2 (+1.6 to +5.0) | -0.3 (-0.7 to +0.2) |
| bucket, by the weather | use measured, sd 0.15, wind measured, margin 0, held out | 80 | -29.1 (-51.1 to -5.9) | +14.4 (+6.4 to +23.5) | -0.0 (-0.1 to +0.0) |
| bucket, by the weather | wind measured, margin 0.1, tuned | 60 | -70.2 (-76.7 to -63.6) | +0.6 (+0.1 to +1.2) | -0.2 (-0.5 to +0.1) |
| bucket, by the weather | wind measured, margin 0.1, held out | 80 | -23.1 (-28.0 to -18.2) | +4.0 (+2.4 to +6.0) | -0.0 (-0.1 to +0.0) |
| bucket, by the weather | use measured, sd 0.07, margin 0.1, tuned | 60 | -25.0 (-40.9 to -8.5) | +0.0 (+0.0 to +0.0) | +0.1 (-0.4 to +0.5) |
| bucket, by the weather | use measured, sd 0.07, margin 0.1, held out | 80 | -13.8 (-29.0 to +1.3) | -3.5 (-8.5 to +1.2) | -0.1 (-0.2 to -0.0) |
| bucket, by the weather | use measured, sd 0.07, wind measured, margin 0.1, tuned | 60 | -56.5 (-71.6 to -40.8) | +0.0 (+0.0 to +0.0) | -0.0 (-0.4 to +0.3) |
| bucket, by the weather | use measured, sd 0.07, wind measured, margin 0.1, held out | 80 | +24.7 (+6.5 to +42.1) | -9.2 (-13.5 to -4.9) | -0.1 (-0.1 to +0.0) |
| bucket, by the weather | use measured, sd 0.15, margin 0.1, tuned | 60 | -22.3 (-44.2 to +1.3) | +0.1 (+0.0 to +0.3) | +0.2 (-0.2 to +0.6) |
| bucket, by the weather | use measured, sd 0.15, margin 0.1, held out | 80 | +0.2 (-23.2 to +26.1) | +9.1 (+1.5 to +16.8) | +0.1 (-0.1 to +0.5) |
| bucket, by the weather | use measured, sd 0.15, wind measured, margin 0.1, tuned | 60 | -53.7 (-75.9 to -31.7) | +0.7 (+0.3 to +1.1) | -0.1 (-0.4 to +0.3) |
| bucket, by the weather | use measured, sd 0.15, wind measured, margin 0.1, held out | 80 | +38.3 (+13.3 to +65.1) | +0.2 (-6.3 to +6.7) | +0.4 (-0.1 to +1.1) |
| bucket, by the weather | wind measured, tuned | 60 | -32.3 (-37.6 to -27.0) | +0.0 (+0.0 to +0.0) | -0.1 (-0.3 to -0.0) |
| bucket, by the weather | wind measured, held out | 80 | +38.0 (+29.9 to +45.3) | -7.3 (-10.2 to -4.6) | -0.0 (-0.0 to +0.0) |
| bucket, by the weather | use measured, sd 0.07, tuned | 60 | +15.9 (-1.6 to +32.5) | +0.0 (+0.0 to +0.0) | +0.2 (-0.2 to +0.7) |
| bucket, by the weather | use measured, sd 0.07, held out | 80 | +47.4 (+30.8 to +66.3) | -9.6 (-14.1 to -5.5) | +0.1 (-0.0 to +0.3) |
| bucket, by the weather | use measured, sd 0.07, wind measured, tuned | 60 | -18.2 (-35.0 to -1.5) | +0.0 (+0.0 to +0.0) | +0.0 (-0.3 to +0.3) |
| bucket, by the weather | use measured, sd 0.07, wind measured, held out | 80 | +88.9 (+68.5 to +108.5) | -10.2 (-14.5 to -6.0) | +0.3 (-0.0 to +0.8) |
| bucket, by the weather | use measured, sd 0.15, tuned | 60 | +21.1 (-5.3 to +47.1) | +0.0 (+0.0 to +0.0) | +0.5 (-0.1 to +1.1) |
| bucket, by the weather | use measured, sd 0.15, held out | 80 | +63.2 (+37.8 to +88.7) | -1.6 (-7.5 to +4.4) | +0.8 (+0.1 to +1.8) |
| bucket, by the weather | use measured, sd 0.15, wind measured, tuned | 60 | -16.6 (-41.6 to +8.9) | +0.0 (+0.0 to +0.1) | +0.0 (-0.3 to +0.4) |
| bucket, by the weather | use measured, sd 0.15, wind measured, held out | 80 | +102.9 (+75.8 to +131.7) | -6.5 (-11.8 to -1.5) | +1.4 (+0.2 to +3.0) |
| tomatoes, probes | tension sensors, tuned | 60 | -198.2 (-229.6 to -168.7) | +1.8 (+1.3 to +2.5) | -70.5 (-82.3 to -58.6) |
| tomatoes, probes | tension sensors, held out | 80 | -111.2 (-136.4 to -87.5) | +1.6 (-0.4 to +3.7) | -26.1 (-34.5 to -18.5) |
| tomatoes, by the weather | wind measured, margin 0, tuned | 60 | -146.1 (-155.4 to -136.9) | +0.4 (+0.2 to +0.6) | -73.6 (-84.0 to -64.0) |
| tomatoes, by the weather | wind measured, margin 0, held out | 80 | -92.3 (-99.7 to -84.7) | +3.3 (+2.6 to +4.1) | -71.4 (-82.1 to -60.9) |
| tomatoes, by the weather | use measured, sd 0.07, margin 0, tuned | 60 | -106.8 (-121.8 to -91.3) | +0.5 (+0.3 to +0.8) | -58.4 (-71.9 to -46.2) |
| tomatoes, by the weather | use measured, sd 0.07, margin 0, held out | 80 | -119.6 (-134.3 to -104.6) | +21.5 (+16.3 to +27.0) | -70.3 (-83.1 to -57.7) |
| tomatoes, by the weather | use measured, sd 0.07, wind measured, margin 0, tuned | 60 | -156.2 (-169.8 to -142.0) | +0.9 (+0.6 to +1.3) | -84.6 (-98.7 to -71.2) |
| tomatoes, by the weather | use measured, sd 0.07, wind measured, margin 0, held out | 80 | -78.9 (-96.6 to -60.8) | +8.5 (+5.3 to +12.1) | -41.8 (-56.0 to -28.0) |
| tomatoes, by the weather | use measured, sd 0.15, margin 0, tuned | 60 | -107.5 (-128.5 to -85.9) | +0.9 (+0.5 to +1.4) | -59.5 (-75.0 to -44.4) |
| tomatoes, by the weather | use measured, sd 0.15, margin 0, held out | 80 | -106.8 (-129.7 to -82.7) | +26.5 (+19.5 to +34.5) | -55.1 (-69.7 to -41.4) |
| tomatoes, by the weather | use measured, sd 0.15, wind measured, margin 0, tuned | 60 | -155.4 (-178.3 to -133.9) | +2.2 (+1.2 to +3.4) | -88.1 (-106.2 to -70.9) |
| tomatoes, by the weather | use measured, sd 0.15, wind measured, margin 0, held out | 80 | -63.8 (-90.1 to -37.7) | +13.5 (+8.4 to +19.2) | -26.5 (-43.1 to -7.8) |
| tomatoes, by the weather | wind measured, margin 0.1, tuned | 60 | -100.1 (-108.1 to -92.5) | +0.3 (+0.1 to +0.4) | -47.9 (-54.7 to -40.7) |
| tomatoes, by the weather | wind measured, margin 0.1, held out | 80 | -18.1 (-26.3 to -9.8) | -0.2 (-0.5 to +0.0) | -1.8 (-9.7 to +6.9) |
| tomatoes, by the weather | use measured, sd 0.07, margin 0.1, tuned | 60 | -63.6 (-80.3 to -47.4) | +0.2 (+0.1 to +0.4) | -32.9 (-43.9 to -22.7) |
| tomatoes, by the weather | use measured, sd 0.07, margin 0.1, held out | 80 | -51.0 (-69.2 to -32.3) | +7.8 (+4.8 to +11.3) | -36.3 (-49.9 to -24.0) |
| tomatoes, by the weather | use measured, sd 0.07, wind measured, margin 0.1, tuned | 60 | -109.2 (-124.1 to -93.9) | +0.5 (+0.3 to +0.7) | -58.3 (-71.4 to -46.7) |
| tomatoes, by the weather | use measured, sd 0.07, wind measured, margin 0.1, held out | 80 | -6.1 (-26.6 to +14.8) | +2.1 (+0.6 to +3.9) | +3.9 (-10.8 to +20.8) |
| tomatoes, by the weather | use measured, sd 0.15, margin 0.1, tuned | 60 | -56.5 (-80.5 to -33.9) | +0.4 (+0.2 to +0.7) | -34.5 (-50.3 to -18.9) |
| tomatoes, by the weather | use measured, sd 0.15, margin 0.1, held out | 80 | -36.6 (-62.8 to -9.4) | +12.4 (+7.5 to +18.2) | -22.5 (-39.2 to -5.6) |
| tomatoes, by the weather | use measured, sd 0.15, wind measured, margin 0.1, tuned | 60 | -108.2 (-130.9 to -84.3) | +0.9 (+0.5 to +1.3) | -59.1 (-75.4 to -43.1) |
| tomatoes, by the weather | use measured, sd 0.15, wind measured, margin 0.1, held out | 80 | +7.6 (-20.3 to +37.6) | +5.4 (+2.1 to +9.4) | +9.4 (-9.0 to +30.2) |
| tomatoes, by the weather | wind measured, tuned | 60 | -60.6 (-67.6 to -53.3) | +0.1 (+0.1 to +0.2) | -27.3 (-32.5 to -22.1) |
| tomatoes, by the weather | wind measured, held out | 80 | +46.9 (+36.7 to +56.5) | -1.1 (-1.4 to -0.8) | +43.3 (+32.9 to +55.2) |
| tomatoes, by the weather | use measured, sd 0.07, tuned | 60 | -14.6 (-33.1 to +2.9) | +0.1 (+0.0 to +0.2) | -4.5 (-15.2 to +6.3) |
| tomatoes, by the weather | use measured, sd 0.07, held out | 80 | +17.8 (-0.9 to +36.7) | +2.4 (+0.7 to +4.3) | +7.7 (-4.7 to +20.9) |
| tomatoes, by the weather | use measured, sd 0.07, wind measured, tuned | 60 | -69.6 (-86.5 to -52.1) | +0.3 (+0.2 to +0.4) | -38.1 (-49.5 to -27.4) |
| tomatoes, by the weather | use measured, sd 0.07, wind measured, held out | 80 | +62.6 (+40.4 to +85.0) | -0.3 (-1.0 to +0.5) | +49.2 (+33.9 to +66.2) |
| tomatoes, by the weather | use measured, sd 0.15, tuned | 60 | -14.1 (-39.4 to +12.5) | +0.2 (+0.1 to +0.3) | -12.0 (-28.8 to +4.0) |
| tomatoes, by the weather | use measured, sd 0.15, held out | 80 | +31.7 (+3.7 to +59.8) | +5.2 (+2.1 to +8.8) | +14.3 (-2.0 to +31.7) |
| tomatoes, by the weather | use measured, sd 0.15, wind measured, tuned | 60 | -57.8 (-83.1 to -32.8) | +0.4 (+0.2 to +0.7) | -35.2 (-51.3 to -20.4) |
| tomatoes, by the weather | use measured, sd 0.15, wind measured, held out | 80 | +79.6 (+49.4 to +111.4) | +1.5 (-0.5 to +3.9) | +50.4 (+31.3 to +70.9) |
| lettuce, probes | tension sensors, tuned | 60 | -109.5 (-127.8 to -90.8) | +2.3 (+1.5 to +3.1) | -56.5 (-64.8 to -48.5) |
| lettuce, probes | tension sensors, held out | 80 | -25.0 (-40.0 to -10.1) | -3.2 (-6.0 to -0.5) | -19.2 (-26.7 to -11.8) |
| lettuce, by the weather | wind measured, margin 0, tuned | 60 | -48.6 (-54.7 to -42.7) | +0.2 (+0.1 to +0.2) | -19.8 (-23.0 to -16.8) |
| lettuce, by the weather | wind measured, margin 0, held out | 80 | -37.4 (-40.7 to -34.0) | +1.1 (+0.9 to +1.4) | -22.2 (-25.1 to -19.0) |
| lettuce, by the weather | use measured, sd 0.07, margin 0, tuned | 60 | -39.6 (-46.5 to -32.7) | +0.3 (+0.2 to +0.5) | -18.1 (-21.9 to -14.4) |
| lettuce, by the weather | use measured, sd 0.07, margin 0, held out | 80 | -52.7 (-59.6 to -45.7) | +7.0 (+5.0 to +9.0) | -37.5 (-43.1 to -31.9) |
| lettuce, by the weather | use measured, sd 0.07, wind measured, margin 0, tuned | 60 | -53.0 (-59.9 to -45.6) | +0.5 (+0.3 to +0.7) | -24.5 (-28.5 to -20.2) |
| lettuce, by the weather | use measured, sd 0.07, wind measured, margin 0, held out | 80 | -31.0 (-38.5 to -23.3) | +2.9 (+1.8 to +4.1) | -19.6 (-25.4 to -13.9) |
| lettuce, by the weather | use measured, sd 0.15, margin 0, tuned | 60 | -38.9 (-48.7 to -28.8) | +0.5 (+0.3 to +0.8) | -20.5 (-26.1 to -15.3) |
| lettuce, by the weather | use measured, sd 0.15, margin 0, held out | 80 | -46.2 (-55.9 to -36.1) | +8.1 (+5.6 to +10.7) | -32.7 (-39.1 to -25.7) |
| lettuce, by the weather | use measured, sd 0.15, wind measured, margin 0, tuned | 60 | -51.2 (-61.6 to -41.4) | +0.8 (+0.4 to +1.2) | -26.3 (-32.1 to -20.3) |
| lettuce, by the weather | use measured, sd 0.15, wind measured, margin 0, held out | 80 | -25.6 (-36.5 to -15.2) | +4.3 (+2.6 to +6.3) | -18.8 (-25.6 to -11.7) |
| lettuce, by the weather | wind measured, margin 0.1, tuned | 60 | -32.6 (-37.8 to -27.6) | +0.1 (+0.1 to +0.2) | -12.6 (-15.6 to -9.8) |
| lettuce, by the weather | wind measured, margin 0.1, held out | 80 | -6.8 (-11.1 to -2.6) | -0.1 (-0.2 to +0.1) | +1.4 (-2.0 to +5.2) |
| lettuce, by the weather | use measured, sd 0.07, margin 0.1, tuned | 60 | -21.1 (-28.4 to -13.6) | +0.1 (+0.1 to +0.2) | -8.9 (-12.2 to -5.7) |
| lettuce, by the weather | use measured, sd 0.07, margin 0.1, held out | 80 | -23.0 (-30.6 to -15.7) | +2.8 (+1.6 to +4.1) | -18.7 (-23.5 to -13.9) |
| lettuce, by the weather | use measured, sd 0.07, wind measured, margin 0.1, tuned | 60 | -35.4 (-42.6 to -27.8) | +0.2 (+0.1 to +0.3) | -16.1 (-19.7 to -12.3) |
| lettuce, by the weather | use measured, sd 0.07, wind measured, margin 0.1, held out | 80 | -1.6 (-10.3 to +6.9) | +0.8 (+0.2 to +1.4) | -0.7 (-5.6 to +4.6) |
| lettuce, by the weather | use measured, sd 0.15, margin 0.1, tuned | 60 | -18.1 (-29.0 to -6.9) | +0.2 (+0.0 to +0.3) | -10.1 (-15.4 to -4.4) |
| lettuce, by the weather | use measured, sd 0.15, margin 0.1, held out | 80 | -16.7 (-27.2 to -5.3) | +4.1 (+2.3 to +6.1) | -16.1 (-22.4 to -9.7) |
| lettuce, by the weather | use measured, sd 0.15, wind measured, margin 0.1, tuned | 60 | -35.2 (-46.1 to -24.1) | +0.3 (+0.2 to +0.6) | -17.3 (-23.2 to -11.6) |
| lettuce, by the weather | use measured, sd 0.15, wind measured, margin 0.1, held out | 80 | +3.7 (-8.2 to +15.9) | +1.7 (+0.6 to +3.0) | -1.3 (-7.9 to +5.1) |
| lettuce, by the weather | wind measured, tuned | 60 | -17.5 (-22.2 to -13.1) | +0.0 (+0.0 to +0.1) | -6.9 (-9.2 to -5.0) |
| lettuce, by the weather | wind measured, held out | 80 | +22.1 (+17.7 to +26.5) | -0.4 (-0.6 to -0.3) | +15.0 (+10.8 to +19.3) |
| lettuce, by the weather | use measured, sd 0.07, tuned | 60 | -2.2 (-10.6 to +6.8) | +0.0 (-0.1 to +0.1) | -0.5 (-4.3 to +3.4) |
| lettuce, by the weather | use measured, sd 0.07, held out | 80 | +6.2 (-1.5 to +14.3) | +1.0 (+0.2 to +1.9) | -0.1 (-4.2 to +4.1) |
| lettuce, by the weather | use measured, sd 0.07, wind measured, tuned | 60 | -18.8 (-27.0 to -10.2) | +0.1 (+0.0 to +0.2) | -8.8 (-12.7 to -4.9) |
| lettuce, by the weather | use measured, sd 0.07, wind measured, held out | 80 | +26.7 (+16.8 to +35.7) | -0.1 (-0.4 to +0.2) | +14.7 (+9.7 to +19.9) |
| lettuce, by the weather | use measured, sd 0.15, tuned | 60 | +0.3 (-11.7 to +12.2) | +0.0 (-0.1 to +0.2) | -1.4 (-6.5 to +4.1) |
| lettuce, by the weather | use measured, sd 0.15, held out | 80 | +11.7 (-0.0 to +22.8) | +1.7 (+0.5 to +3.3) | -0.9 (-7.2 to +5.3) |
| lettuce, by the weather | use measured, sd 0.15, wind measured, tuned | 60 | -15.8 (-27.5 to -3.6) | +0.1 (+0.0 to +0.3) | -7.9 (-13.5 to -2.5) |
| lettuce, by the weather | use measured, sd 0.15, wind measured, held out | 80 | +33.3 (+20.8 to +46.5) | +0.5 (-0.2 to +1.3) | +14.8 (+8.5 to +21.1) |
| lawn, its probe | tension sensors, tuned | 60 | -21.1 (-26.4 to -16.3) | +0.4 (+0.3 to +0.6) | -74.8 (-90.6 to -60.1) |
| lawn, its probe | tension sensors, held out | 80 | +89.7 (+76.6 to +102.9) | -63.8 (-74.0 to -54.2) | +29.6 (+19.0 to +39.3) |
| lawn, its probe | tension sensors, p 0.2, tuned | 60 | +7.3 (+2.2 to +11.9) | -0.4 (-0.5 to -0.2) | -15.3 (-32.5 to +1.3) |
| lawn, its probe | tension sensors, p 0.2, held out | 80 | +106.2 (+93.3 to +119.7) | -71.2 (-81.3 to -60.4) | +23.6 (+15.4 to +31.9) |
| lawn, by the weather | wind measured, margin 0, tuned | 60 | -105.0 (-110.7 to -99.2) | +0.1 (+0.0 to +0.2) | -58.3 (-64.3 to -52.3) |
| lawn, by the weather | wind measured, margin 0, held out | 80 | -80.4 (-83.8 to -77.1) | +13.5 (+9.7 to +17.4) | -65.0 (-73.5 to -56.9) |
| lawn, by the weather | use measured, sd 0.07, margin 0, tuned | 60 | -86.8 (-100.9 to -72.6) | +0.0 (+0.0 to +0.0) | -44.4 (-53.4 to -36.2) |
| lawn, by the weather | use measured, sd 0.07, margin 0, held out | 80 | -99.3 (-112.2 to -85.9) | +16.8 (+12.8 to +21.1) | -90.5 (-104.1 to -76.4) |
| lawn, by the weather | use measured, sd 0.07, wind measured, margin 0, tuned | 60 | -115.4 (-130.0 to -101.6) | +0.0 (+0.0 to +0.0) | -58.8 (-68.1 to -49.1) |
| lawn, by the weather | use measured, sd 0.07, wind measured, margin 0, held out | 80 | -69.2 (-83.4 to -55.2) | +4.3 (+1.6 to +7.1) | -44.0 (-56.5 to -30.9) |
| lawn, by the weather | use measured, sd 0.15, margin 0, tuned | 60 | -86.4 (-106.2 to -66.7) | +0.0 (+0.0 to +0.0) | -50.9 (-64.4 to -37.9) |
| lawn, by the weather | use measured, sd 0.15, margin 0, held out | 80 | -88.1 (-106.9 to -68.9) | +25.6 (+18.1 to +33.5) | -77.9 (-95.1 to -59.8) |
| lawn, by the weather | use measured, sd 0.15, wind measured, margin 0, tuned | 60 | -115.0 (-134.4 to -94.5) | +0.1 (+0.0 to +0.3) | -73.0 (-89.8 to -57.7) |
| lawn, by the weather | use measured, sd 0.15, wind measured, margin 0, held out | 80 | -57.0 (-76.7 to -35.8) | +14.4 (+8.9 to +20.5) | -48.1 (-66.2 to -29.4) |
| lawn, by the weather | wind measured, margin 0.1, tuned | 60 | -70.6 (-74.8 to -66.3) | +0.0 (+0.0 to +0.0) | -34.7 (-38.7 to -30.7) |
| lawn, by the weather | wind measured, margin 0.1, held out | 80 | -22.2 (-26.8 to -17.7) | +1.8 (+0.9 to +2.7) | -14.0 (-17.9 to -10.0) |
| lawn, by the weather | use measured, sd 0.07, margin 0.1, tuned | 60 | -47.5 (-62.0 to -32.7) | +0.0 (+0.0 to +0.0) | -24.7 (-32.9 to -16.4) |
| lawn, by the weather | use measured, sd 0.07, margin 0.1, held out | 80 | -43.7 (-58.1 to -29.5) | +1.5 (-0.7 to +3.8) | -20.2 (-32.6 to -8.1) |
| lawn, by the weather | use measured, sd 0.07, wind measured, margin 0.1, tuned | 60 | -77.0 (-91.2 to -61.8) | +0.0 (+0.0 to +0.0) | -37.1 (-45.9 to -28.1) |
| lawn, by the weather | use measured, sd 0.07, wind measured, margin 0.1, held out | 80 | -9.9 (-25.5 to +6.1) | -1.8 (-3.6 to -0.2) | +9.8 (-2.0 to +22.3) |
| lawn, by the weather | use measured, sd 0.15, margin 0.1, tuned | 60 | -47.9 (-69.5 to -24.9) | +0.0 (+0.0 to +0.0) | -29.6 (-40.9 to -18.3) |
| lawn, by the weather | use measured, sd 0.15, margin 0.1, held out | 80 | -31.8 (-51.8 to -11.8) | +10.6 (+5.7 to +16.1) | -27.9 (-45.3 to -9.7) |
| lawn, by the weather | use measured, sd 0.15, wind measured, margin 0.1, tuned | 60 | -78.6 (-100.7 to -56.5) | +0.0 (+0.0 to +0.0) | -46.0 (-58.9 to -33.7) |
| lawn, by the weather | use measured, sd 0.15, wind measured, margin 0.1, held out | 80 | +1.5 (-20.3 to +23.2) | +4.5 (+0.8 to +8.2) | +1.2 (-16.7 to +20.1) |
| lawn, by the weather | wind measured, tuned | 60 | -33.4 (-37.2 to -29.5) | +0.0 (+0.0 to +0.0) | -13.4 (-16.5 to -10.6) |
| lawn, by the weather | wind measured, held out | 80 | +35.6 (+29.9 to +41.4) | -2.1 (-3.4 to -1.0) | +29.5 (+24.1 to +35.2) |
| lawn, by the weather | use measured, sd 0.07, tuned | 60 | -9.6 (-26.1 to +7.2) | +0.0 (+0.0 to +0.0) | -8.9 (-17.4 to -1.0) |
| lawn, by the weather | use measured, sd 0.07, held out | 80 | +12.4 (-3.6 to +28.2) | -2.1 (-3.9 to -0.6) | +20.8 (+8.8 to +32.5) |
| lawn, by the weather | use measured, sd 0.07, wind measured, tuned | 60 | -40.3 (-55.1 to -24.1) | +0.0 (+0.0 to +0.0) | -20.1 (-28.3 to -11.6) |
| lawn, by the weather | use measured, sd 0.07, wind measured, held out | 80 | +48.1 (+29.7 to +66.8) | -2.5 (-4.1 to -1.1) | +44.9 (+31.9 to +57.3) |
| lawn, by the weather | use measured, sd 0.15, tuned | 60 | -8.0 (-31.5 to +16.0) | +0.0 (+0.0 to +0.0) | -10.3 (-20.9 to +1.1) |
| lawn, by the weather | use measured, sd 0.15, held out | 80 | +25.4 (+2.8 to +48.7) | +3.2 (-0.2 to +6.7) | +17.0 (-0.4 to +34.5) |
| lawn, by the weather | use measured, sd 0.15, wind measured, tuned | 60 | -40.5 (-63.4 to -18.3) | +0.0 (+0.0 to +0.0) | -25.0 (-36.2 to -13.5) |
| lawn, by the weather | use measured, sd 0.15, wind measured, held out | 80 | +62.3 (+37.7 to +87.2) | -0.1 (-2.5 to +2.3) | +43.0 (+24.8 to +59.4) |
| yard, its probes | tension sensors, tuned | 60 | -57.7 (-63.3 to -52.0) | +3.8 (+3.2 to +4.3) | -1.2 (-1.6 to -0.8) |
| yard, its probes | tension sensors, held out | 80 | +7.1 (+1.5 to +12.5) | -10.3 (-13.5 to -7.5) | -0.2 (-0.3 to -0.0) |
| yard, its probes | tension sensors, p 0.2, tuned | 60 | -41.1 (-46.5 to -35.9) | -0.3 (-0.7 to -0.0) | -0.5 (-0.9 to -0.1) |
| yard, its probes | tension sensors, p 0.2, held out | 80 | +19.4 (+13.4 to +25.1) | -18.5 (-22.4 to -15.0) | -0.1 (-0.2 to -0.0) |
| tomatoes over a dense pan, probes | tension sensors, tuned | 60 | -223.0 (-249.5 to -196.2) | +3.2 (+2.3 to +4.2) | -120.4 (-132.9 to -108.0) |
| tomatoes over a dense pan, probes | tension sensors, held out | 80 | -114.7 (-138.2 to -90.6) | +3.1 (+0.0 to +5.8) | -56.5 (-68.9 to -44.7) |

Three of the tomato summers by probes, run again to see each probe's field capacity (the
soil's, plus the probe's own error, as the probe reads it), learned and measured:

| summer | probe | as the probe reads it | learned | measured |
| --- | --- | --- | --- | --- |
| McAllister 2003 | 10 cm | 0.334 | 0.379 | 0.337 |
| | 30 cm | 0.289 | 0.337 | 0.283 |
| McAllister 2011 | 10 cm | 0.296 | 0.331 | 0.299 |
| | 30 cm | 0.292 | 0.338 | 0.293 |
| Davis 2010 | 10 cm | 0.281 | 0.296 | 0.267 |
| | 30 cm | 0.323 | none | 0.311 |

## The audit of 2026-10-18

The simulator, the advice and the trials were each read by someone set to break them, and
each finding checked before anything changed. What was found, and what was done:

### The simulator

* **The crop did not make up for a dry top.** Its use was its demand times its roots' Ks
  layer by layer, so a dry top layer cut the whole crop's use however wet the soil below
  was; the docstring said the deeper roots made it up, and they did not. Swapping in
  FAO-56's Ks on the root zone's mean, a Davis summer's tomatoes by probes lost 1.0 mm for
  16.8. Now the roots in wetter soil make up for those in drier as Jarvis (1989) has it, as
  HYDRUS does (Šimůnek and Hopmans 2009), each farm's crop as far as a compensation drawn for
  it between much (0.5) and none (1) lets it (`physics.LayeredBed.compensation`,
  `VirtualFarm.compensation`).
* **Evaporation took the top 25 mm first, below its residual water.** Its suction was then
  without end, nothing rose into it from below, and the most roots went without. Now it is
  spread through the top 10 cm, the nearer the surface the more, and stops a little above
  the residual water.
* **The crop's p was the table's all summer.** FAO-56 lowers it on a day the crop draws
  fast, `p + 0.04 (5 − ETc)`: at Davis's 8 or 9 mm a day, tomatoes' 0.4 is 0.2 to 0.28. The
  virtual crop's p now follows its day's demand (`SoilBed.p_follows_demand`).
* **A rain day lost a sixth of its reference ET.** The hours it rained had 15% of their
  share and the rest was lost, where the day's Penman–Monteith already counts its cloud; at
  McAllister, a station's balance counted 6% above the farm's water use for no other
  reason. Now the rain hours' share goes to the dry hours.
* **Found and not changed:** above field capacity water drains by a cubic rule, not
  Mualem's conductivity, and a soil at field capacity never drains further; the soil below
  the roots, at field capacity, gave the crop 60 to 86 mm a season; rain always soaks in,
  at 2.5 mm an hour; no canopy catches rain; watering is perfectly even; both start full.
  Each bears on the numbers below and is in UNTESTED.

### The advice

Each of these was a hand-built bed for which the advice was wrong; each is now a test
(`TestWhatTheAuditOf20261018Found`).

* **Rain forecast held a bed with 97% of its water gone**, 11.5 mm against a 102 mm
  deficit, as long as the forecast kept sliding. Now rain holds a watering only if it would
  leave the bed short of half its water by tomorrow.
* **A silent probe left the others to speak for the whole root zone**: a dry top probe 12
  hours stale over a wet one, and the bed had plenty. Now it stands for its slice at its last
  reading, less what the others have dried since, and the decision says so.
* **A wet subsoil cancelled a dry top**: two thirds of the top's water gone over water
  perched at 0.48, and it said too wet. Now each probe's deficit counts on its own.
* **A probe in percent was read as a fraction**, 15 as 15, and the bed never watered. Now a
  series not in a volume fraction is not one of the bed's probes.
* **Read every five minutes, a probe had no drying rate**: the window was a count of
  readings, 18 hours of them. Now it is hours, the readings thinned to one an hour.
* **A reference drying faster than 1.5 times the balance was dropped**, and the bed counted
  at the margin's 1.2. Now it is taken at 1.5.
* **The weather balance's margin, and a probe's correction, scaled the crop's transpiration
  alone**: for a young tomato the 20% margin was 3%. Now they scale the whole of its use.
* **A day whose rain or watering filled the bed counted its whole use besides**: the water
  came off first and stopped at full. Now the day's water and its use are taken together,
  FAO-56's Eq. 85, what the root zone cannot hold draining.
* **The rain since midnight** was in neither the balance nor the forecast. It comes off now.
* **By the weather the advice looked no further than its refill point**, where by probes it
  looks a day ahead. It does now, by the balance's last day.
* **A cover the probes had seen held for the forecast alone**, not for the balance that
  carries the bed when they fall silent. It holds for both now.
* **A bed's layers were left out of the weather balance's available water.** They are in.
* **A bed configured past sense** (no rain skipping a watering, a share of rain over one, a
  crop that uses nothing) gave advice. It is refused.
* **Found and not changed:** the soil above the shallowest probe is read as that probe
  reads (a probe at 3 cm cut one Davis summer's loss from 38 mm to 9, on the simulator
  before the audit; tried again below); a dead or misreporting rain gauge goes unseen; the
  refill reaches past the deepest probe to the roots' depth by assumption; the crop's days
  are counted in UTC. In UNTESTED.

### The trials

* **Watering by probes went on within the hour**, as much as 40 mm an hour on a soil that
  takes 8, and what it could not take ran off: 67 to 89 mm a Davis tomato summer, unscored,
  and none by the weather, watered at 12 mm an hour. Now both water at 12 mm an hour.
* **Each morning's advice read forecasts issued after it**: the season's issues were all in
  the log from its start, and the advice read the latest. Now it reads the forecast as it
  stood (`State.forecast(as_of=...)`).
* **The forecasts all but never missed a day's rain**: each hour's miss was drawn alone.
  Now a rain day in four is missed whole at a day's lead, and a dry day in twelve forecast a
  spell (`backtest.forecast_skill`).
* **The station read the farm's own weather exactly**, so by the weather the advice's only
  errors were the wind and the crop. Now each farm's station is off by its sensors and its
  siting (`VirtualFarm.station_*`).
* **The lawn's and the yard's soils, given whole, did not depart.** They do.
* **Each summer's probe noise and forecasts were drawn from the draw alone**, the same every
  summer. Now from the summer's farm.
* **"Held out" was Davis, and has been spent**: the fixes above were found looking at it.
  The defaults were chosen on McAllister and Davis and then tried, once, on two sites kept
  sealed until then, Bushland, Texas, and Tifton, Georgia.
* **The scores**: runoff, the soil's water at the end against the start, the crop's demand
  (for the share of it lost) and hours waterlogged (under a twentieth of air) are now
  scored. Hours under a tenth of air, a few points above field capacity in these silt
  loams, counted a watering's first day.
* **Fine:** the pairing, the code stamps, the forecast cache; resampling whole summers or
  five-year blocks widened the intervals by up to two-fifths and turned no conclusion.

## The trials of 2026-10-18 and 19

On the code after [the audit](#the-audit-of-2026-10-18): ten beds at McAllister and Davis,
1991 to 2025, one farm a summer (`trials.py`, its `BEDS` and `MEASURES`), 5,880 backtests on
51dffc9; then, its reading of the crop's use fixed, the hot-day refill point's probe
configurations again (1,680, as committed in 735d41f); then, once, the sealed sites (1,330
on 735d41f). Made by `python3 trials.py report`.

### How the defaults were to be chosen

Written before the open sites' trial ran, and amended once, before the rerun, as below.

Groups: McAllister 1991–2020, McAllister 2021–2025, Davis. Pairs are the same summer's
farm, each against the bed as built (margin 0.2, 2 m/s wind, no hot-day refill point, no
bound on learning). "Lost" is lost transpiration, mm a summer.

1. **Weather beds, no anemometer.** Among {margin 0.1, 0.2} × {2 m/s, the wind's monthly
   normal} × {hot-day refill point off, on}, the default is the one using least water
   such that, in every group and for every weather bed, its mean lost is no more than the
   bed as built's + 0.5 mm, and the 90% interval of the difference reaches no higher than
   +1.0 mm. If none beats the bed as built, it stays.
2. **Weather beds, with an anemometer.** The same rule among margins 0.1 and 0.2 with the
   wind measured, giving the advice for a station that has one.
3. **Probe beds.** The hot-day refill point becomes the default if, at Davis, it cuts the
   mean lost of the crop beds (tomatoes, lettuce, dense pan) with the interval below 0, and
   in neither McAllister group raises any probe bed's mean lost by more than 0.5 mm.
   Learning within 0.05 becomes the default if, added to whatever (1)–(3) chose, no probe
   bed's mean lost rises by more than 0.5 mm in any group and it cuts the water or the
   hours waterlogged of at least half the probe beds.
4. **Hardware.** A tension sensor or a probe at 5 cm is recommended where it cuts the bed's
   mean lost at Davis by a third or more of the bed as built's.
5. **Sealed.** Bushland and Tifton are then run once: the bed as built against the defaults
   chosen, and the hardware recommended. Reported as they come; a default that does worse
   there than as built is said so and not quietly kept.

**Amendment, 2026-10-19 01:07, before the hot-day refill point was tried again.**

The open sites' trial showed rule 3 weighed only lost transpiration: the hot-day refill
point, reading the crop's use from the probes' drying, took drainage for use in wet
summers and more than doubled six McAllister tomato summers' water, nearly all of it
drained. Its use is now read only from a day that began at least 0.02 below field
capacity. Tried again on the open sites (its configurations alone), it becomes the
default only if, besides rule 3, in neither McAllister group does it (with learning within
0.05, as chosen) add more than a tenth to any probe bed's mean water; else it stays off,
and the bound alone is the default.

### What the rules chose

* **By the weather, no anemometer:** margin 0.2 and FAO-56's 2 m/s, as built. Margin 0.1
  added 23 mm a summer to Davis's bucket's loss; the site's monthly normal wind at 0.2,
  0.8 mm to McAllister's bucket's (interval to 1.7); the hot-day refill point at 0.2 passed
  but used more water.
* **With an anemometer:** margin 0.2, as built: at 0.2 the measured wind added 1.1 mm to
  McAllister's bucket's loss (interval 0.2 to 2.1).
* **The hot-day refill point by probes:** as first written it passed rule 3 and was set as
  the default; then its water was seen, more than twice the as-built in six McAllister
  tomato summers, nearly all drained, its reading of use having taken drainage for it. Its
  use read only from a day that began 0.02 below the lower of the learned and configured
  field capacity, it cost no water (the amendment), and cut tomatoes' lost transpiration
  at Davis by 1.8 mm (interval −3.5 to −0.3) and the dense pan's by 4.3 (−7.1 to −1.9), and
  lettuce's not (+0.1, −2.5 to +2.6): off.
* **Learning within 0.05:** on its own, it raised Davis's lettuce's mean lost by just over
  0.5 mm (+0.5, −0.1 to +1.4): off. It was also seen, by the tests, to hold a bed whose
  survey is badly wrong short of its own soil.
* **Hardware:** a tension sensor for the lawn, the yard and lettuce, which it cut at Davis
  by 47, 15 and 4 mm of 55, 28 and 11.5; a probe at 5 cm for none.

### The open sites

Code: 51dffc9, 51dffc9+crop-drying. Each summer one farm.

| bed | summers | water | lost transpiration | share of demand | summers losing over 1% | hours waterlogged | ran off | stored at the end |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bucket, its probe, Davis | 35 | 692 mm | 15.8 mm | 2.1% | 13 | 0 | 0 mm | -14 mm |
| bucket, its probe, McAllister 1991–2020 | 30 | 252 mm | 0.3 mm | 0.1% | 0 | 0 | 0 mm | -8 mm |
| bucket, its probe, McAllister 2021–2025 | 5 | 232 mm | 0.4 mm | 0.1% | 0 | 0 | 0 mm | -10 mm |
| bucket, by the weather, Davis | 35 | 711 mm | 14.3 mm | 1.8% | 12 | 0 | 0 mm | -14 mm |
| bucket, by the weather, McAllister 1991–2020 | 30 | 297 mm | 0.2 mm | 0.0% | 0 | 0 | 0 mm | -6 mm |
| bucket, by the weather, McAllister 2021–2025 | 5 | 298 mm | 0.0 mm | 0.0% | 0 | 0 | 0 mm | -6 mm |
| tomatoes, probes, Davis | 35 | 1135 mm | 7.3 mm | 1.0% | 9 | 1 | 0 mm | +5 mm |
| tomatoes, probes, McAllister 1991–2020 | 30 | 551 mm | 0.1 mm | 0.0% | 0 | 13 | 0 mm | +40 mm |
| tomatoes, probes, McAllister 2021–2025 | 5 | 673 mm | 0.1 mm | 0.0% | 0 | 10 | 0 mm | +54 mm |
| tomatoes, by the weather, Davis | 35 | 1213 mm | 0.8 mm | 0.1% | 2 | 5 | 0 mm | +20 mm |
| tomatoes, by the weather, McAllister 1991–2020 | 30 | 564 mm | 0.2 mm | 0.1% | 1 | 12 | 0 mm | +40 mm |
| tomatoes, by the weather, McAllister 2021–2025 | 5 | 530 mm | 0.0 mm | 0.0% | 0 | 2 | 0 mm | +40 mm |
| lettuce, probes, Davis | 35 | 504 mm | 11.5 mm | 3.7% | 15 | 1 | 0 mm | -21 mm |
| lettuce, probes, McAllister 1991–2020 | 30 | 252 mm | 0.3 mm | 0.1% | 1 | 9 | 0 mm | +32 mm |
| lettuce, probes, McAllister 2021–2025 | 5 | 352 mm | 0.0 mm | 0.0% | 0 | 8 | 0 mm | +43 mm |
| lettuce, by the weather, Davis | 35 | 608 mm | 0.6 mm | 0.2% | 2 | 5 | 0 mm | +28 mm |
| lettuce, by the weather, McAllister 1991–2020 | 30 | 285 mm | 0.1 mm | 0.1% | 1 | 12 | 0 mm | +43 mm |
| lettuce, by the weather, McAllister 2021–2025 | 5 | 263 mm | 0.2 mm | 0.1% | 0 | 3 | 0 mm | +38 mm |
| lawn, its probe, Davis | 35 | 515 mm | 54.8 mm | 9.0% | 27 | 0 | 0 mm | -53 mm |
| lawn, its probe, McAllister 1991–2020 | 30 | 162 mm | 0.0 mm | 0.0% | 0 | 31 | 0 mm | -6 mm |
| lawn, its probe, McAllister 2021–2025 | 5 | 159 mm | 0.0 mm | 0.0% | 0 | 36 | 0 mm | +3 mm |
| lawn, by the weather, Davis | 35 | 689 mm | 1.7 mm | 0.2% | 3 | 37 | 0 mm | +0 mm |
| lawn, by the weather, McAllister 1991–2020 | 30 | 301 mm | 0.0 mm | 0.0% | 0 | 61 | 0 mm | +11 mm |
| lawn, by the weather, McAllister 2021–2025 | 5 | 301 mm | 0.0 mm | 0.0% | 0 | 56 | 0 mm | +16 mm |
| yard, its probes, Davis | 35 | 598 mm | 28.4 mm | 4.3% | 23 | 0 | 0 mm | -23 mm |
| yard, its probes, McAllister 1991–2020 | 30 | 246 mm | 0.9 mm | 0.2% | 3 | 6 | 2 mm | +13 mm |
| yard, its probes, McAllister 2021–2025 | 5 | 232 mm | 1.6 mm | 0.4% | 1 | 6 | 3 mm | +23 mm |
| tomatoes over a dense pan, probes, Davis | 35 | 1124 mm | 13.3 mm | 1.9% | 13 | 5 | 0 mm | +13 mm |
| tomatoes over a dense pan, probes, McAllister 1991–2020 | 30 | 557 mm | 0.8 mm | 0.2% | 2 | 37 | 13 mm | +49 mm |
| tomatoes over a dense pan, probes, McAllister 2021–2025 | 5 | 569 mm | 0.5 mm | 0.1% | 0 | 29 | 7 mm | +64 mm |

| bed | against the bed as built | summers | water | lost transpiration | hours waterlogged |
| --- | --- | --- | --- | --- | --- |
| bucket, its probe | hot-day refill point, Davis | 35 | -3.8 (-12.3 to +4.0) | +0.9 (-2.2 to +4.5) | +0.0 (+0.0 to +0.0) |
| bucket, its probe | hot-day refill point, McAllister 1991–2020 | 30 | +5.1 (-2.6 to +13.7) | -0.1 (-0.1 to -0.0) | +0.0 (+0.0 to +0.0) |
| bucket, its probe | hot-day refill point, McAllister 2021–2025 | 5 | +10.9 (-4.7 to +26.4) | +0.2 (-0.1 to +0.6) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | margin 0, Davis | 35 | -119.4 (-123.6 to -115.4) | +59.2 (+48.4 to +69.6) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | margin 0, McAllister 1991–2020 | 30 | -73.3 (-79.9 to -66.6) | +4.3 (+1.3 to +8.1) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | margin 0, McAllister 2021–2025 | 5 | -72.7 (-90.4 to -53.3) | +0.1 (+0.0 to +0.2) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | margin 0.1, Davis | 35 | -59.0 (-62.7 to -55.3) | +23.2 (+17.6 to +29.0) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | margin 0.1, McAllister 1991–2020 | 30 | -40.2 (-46.9 to -33.7) | +1.4 (+0.2 to +3.2) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | margin 0.1, McAllister 2021–2025 | 5 | -42.8 (-49.6 to -35.1) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | wind measured, margin 0.1, Davis | 35 | -17.5 (-26.7 to -8.1) | +6.3 (+2.9 to +10.1) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | wind measured, margin 0.1, McAllister 1991–2020 | 30 | -66.9 (-75.6 to -57.8) | +4.1 (+1.0 to +7.4) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | wind measured, margin 0.1, McAllister 2021–2025 | 5 | -62.5 (-75.4 to -46.9) | +0.0 (+0.0 to +0.1) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | wind measured, Davis | 35 | +47.7 (+37.5 to +58.2) | -6.6 (-10.1 to -3.7) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | wind measured, McAllister 1991–2020 | 30 | -36.5 (-43.3 to -30.0) | +1.1 (+0.2 to +2.1) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | wind measured, McAllister 2021–2025 | 5 | -26.4 (-30.3 to -23.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | the wind's monthly normal, margin 0.1, Davis | 35 | -11.6 (-15.2 to -7.8) | +3.0 (+1.7 to +4.5) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | the wind's monthly normal, margin 0.1, McAllister 1991–2020 | 30 | -63.7 (-71.7 to -54.8) | +3.6 (+1.1 to +6.5) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | the wind's monthly normal, margin 0.1, McAllister 2021–2025 | 5 | -60.6 (-76.5 to -44.9) | +0.0 (+0.0 to +0.1) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | the wind's monthly normal, Davis | 35 | +56.6 (+52.8 to +60.5) | -8.6 (-12.9 to -5.2) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | the wind's monthly normal, McAllister 1991–2020 | 30 | -32.4 (-38.8 to -26.3) | +0.8 (+0.2 to +1.6) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | the wind's monthly normal, McAllister 2021–2025 | 5 | -26.7 (-36.1 to -17.3) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | hot-day refill point, margin 0.1, Davis | 35 | -57.3 (-60.3 to -54.3) | +20.1 (+14.6 to +25.9) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | hot-day refill point, margin 0.1, McAllister 1991–2020 | 30 | -36.5 (-41.2 to -31.7) | +0.8 (+0.1 to +1.8) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | hot-day refill point, margin 0.1, McAllister 2021–2025 | 5 | -43.5 (-55.6 to -31.9) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | hot-day refill point, Davis | 35 | +2.7 (+0.0 to +5.6) | -2.6 (-3.5 to -1.8) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | hot-day refill point, McAllister 1991–2020 | 30 | -0.3 (-3.5 to +2.9) | -0.1 (-0.2 to -0.0) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | hot-day refill point, McAllister 2021–2025 | 5 | +9.1 (+0.8 to +17.8) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| tomatoes, probes | hot-day refill point, Davis | 35 | +4.8 (-16.5 to +27.4) | -1.8 (-3.5 to -0.3) | +0.4 (-0.2 to +1.1) |
| tomatoes, probes | hot-day refill point, McAllister 1991–2020 | 30 | -3.1 (-14.0 to +6.8) | -0.0 (-0.1 to -0.0) | -0.2 (-0.5 to +0.1) |
| tomatoes, probes | hot-day refill point, McAllister 2021–2025 | 5 | -7.1 (-14.3 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| tomatoes, probes | tension sensors, Davis | 35 | -100.7 (-132.4 to -70.1) | -0.1 (-3.9 to +3.3) | -0.3 (-0.6 to -0.1) |
| tomatoes, probes | tension sensors, McAllister 1991–2020 | 30 | -220.0 (-259.6 to -180.8) | +0.4 (+0.1 to +0.9) | -4.0 (-5.9 to -2.4) |
| tomatoes, probes | tension sensors, McAllister 2021–2025 | 5 | -362.1 (-421.0 to -306.7) | +0.9 (+0.2 to +1.5) | -9.3 (-13.3 to -5.3) |
| tomatoes, probes | learning within 0.05, Davis | 35 | -10.5 (-20.9 to -2.3) | -1.4 (-4.4 to +0.3) | -0.1 (-0.1 to -0.0) |
| tomatoes, probes | learning within 0.05, McAllister 1991–2020 | 30 | -40.9 (-56.8 to -26.1) | +0.1 (-0.0 to +0.2) | -1.9 (-3.0 to -1.1) |
| tomatoes, probes | learning within 0.05, McAllister 2021–2025 | 5 | -43.2 (-102.6 to +11.0) | +0.0 (+0.0 to +0.1) | -6.0 (-9.9 to -2.2) |
| tomatoes, probes | hot-day refill point, learning within 0.05, Davis | 35 | -2.9 (-24.7 to +20.7) | -2.4 (-5.4 to -0.3) | +0.2 (-0.3 to +0.7) |
| tomatoes, probes | hot-day refill point, learning within 0.05, McAllister 1991–2020 | 30 | -36.2 (-54.4 to -19.1) | +0.0 (-0.1 to +0.2) | -2.0 (-3.0 to -1.1) |
| tomatoes, probes | hot-day refill point, learning within 0.05, McAllister 2021–2025 | 5 | -50.2 (-105.7 to +2.5) | +0.0 (+0.0 to +0.1) | -6.0 (-10.5 to -2.3) |
| tomatoes, probes | hot-day refill point, tension sensors, Davis | 35 | -90.8 (-122.1 to -60.5) | -2.7 (-6.3 to +0.5) | -0.3 (-0.7 to -0.1) |
| tomatoes, probes | hot-day refill point, tension sensors, McAllister 1991–2020 | 30 | -217.8 (-255.7 to -180.2) | +0.2 (+0.0 to +0.5) | -4.2 (-6.2 to -2.6) |
| tomatoes, probes | hot-day refill point, tension sensors, McAllister 2021–2025 | 5 | -356.9 (-420.2 to -295.3) | +0.9 (+0.2 to +1.6) | -9.3 (-12.9 to -5.3) |
| tomatoes, probes | a probe at 5 cm, Davis | 35 | +6.1 (-16.9 to +31.5) | -1.5 (-2.6 to -0.5) | +0.4 (-0.2 to +1.2) |
| tomatoes, probes | a probe at 5 cm, McAllister 1991–2020 | 30 | -33.8 (-54.9 to -14.2) | -0.0 (-0.1 to +0.1) | -1.8 (-2.7 to -1.0) |
| tomatoes, probes | a probe at 5 cm, McAllister 2021–2025 | 5 | -143.9 (-241.6 to -51.7) | +0.0 (-0.2 to +0.3) | -6.5 (-10.5 to -2.9) |
| tomatoes, probes | hot-day refill point, a probe at 5 cm, Davis | 35 | +3.4 (-18.8 to +24.9) | -3.7 (-5.9 to -1.8) | +0.2 (-0.2 to +0.8) |
| tomatoes, probes | hot-day refill point, a probe at 5 cm, McAllister 1991–2020 | 30 | -35.2 (-54.4 to -16.3) | -0.1 (-0.1 to -0.0) | -1.8 (-2.6 to -0.9) |
| tomatoes, probes | hot-day refill point, a probe at 5 cm, McAllister 2021–2025 | 5 | -135.3 (-206.2 to -64.4) | -0.1 (-0.2 to +0.1) | -5.7 (-8.9 to -2.5) |
| tomatoes, by the weather | margin 0, Davis | 35 | -210.7 (-217.6 to -204.1) | +15.5 (+10.0 to +21.1) | -3.2 (-5.9 to -1.1) |
| tomatoes, by the weather | margin 0, McAllister 1991–2020 | 30 | -141.9 (-152.6 to -131.4) | +0.2 (+0.0 to +0.4) | -2.1 (-3.0 to -1.3) |
| tomatoes, by the weather | margin 0, McAllister 2021–2025 | 5 | -127.5 (-148.0 to -108.2) | +0.0 (+0.0 to +0.1) | -0.7 (-1.3 to -0.2) |
| tomatoes, by the weather | margin 0.1, Davis | 35 | -101.5 (-106.5 to -96.8) | +1.3 (+0.6 to +2.1) | -1.7 (-3.0 to -0.6) |
| tomatoes, by the weather | margin 0.1, McAllister 1991–2020 | 30 | -69.7 (-79.5 to -60.1) | +0.0 (-0.0 to +0.1) | -0.8 (-1.4 to -0.2) |
| tomatoes, by the weather | margin 0.1, McAllister 2021–2025 | 5 | -74.7 (-91.4 to -57.8) | +0.0 (+0.0 to +0.0) | -0.6 (-1.4 to -0.1) |
| tomatoes, by the weather | wind measured, margin 0.1, Davis | 35 | -44.2 (-57.6 to -30.6) | +0.5 (+0.0 to +1.1) | -1.1 (-2.0 to -0.3) |
| tomatoes, by the weather | wind measured, margin 0.1, McAllister 1991–2020 | 30 | -124.0 (-138.1 to -111.4) | +0.1 (+0.0 to +0.2) | -1.3 (-2.2 to -0.5) |
| tomatoes, by the weather | wind measured, margin 0.1, McAllister 2021–2025 | 5 | -120.2 (-143.4 to -99.2) | +0.0 (+0.0 to +0.1) | -0.7 (-1.5 to -0.2) |
| tomatoes, by the weather | wind measured, Davis | 35 | +66.3 (+50.9 to +81.3) | -0.1 (-0.3 to +0.1) | +1.0 (+0.3 to +1.7) |
| tomatoes, by the weather | wind measured, McAllister 1991–2020 | 30 | -53.5 (-64.1 to -43.8) | +0.0 (-0.1 to +0.1) | -0.5 (-1.0 to +0.0) |
| tomatoes, by the weather | wind measured, McAllister 2021–2025 | 5 | -52.1 (-75.3 to -29.0) | +0.0 (+0.0 to +0.0) | -0.1 (-1.1 to +0.9) |
| tomatoes, by the weather | the wind's monthly normal, margin 0.1, Davis | 35 | -28.6 (-33.0 to -24.5) | +0.1 (-0.0 to +0.4) | -0.6 (-1.0 to -0.3) |
| tomatoes, by the weather | the wind's monthly normal, margin 0.1, McAllister 1991–2020 | 30 | -117.5 (-132.0 to -104.6) | +0.1 (+0.0 to +0.2) | -1.2 (-2.1 to -0.4) |
| tomatoes, by the weather | the wind's monthly normal, margin 0.1, McAllister 2021–2025 | 5 | -115.3 (-141.3 to -88.9) | +0.0 (+0.0 to +0.1) | -0.7 (-1.5 to -0.2) |
| tomatoes, by the weather | the wind's monthly normal, Davis | 35 | +81.2 (+76.0 to +86.1) | -0.3 (-0.6 to -0.1) | +1.4 (+0.6 to +2.2) |
| tomatoes, by the weather | the wind's monthly normal, McAllister 1991–2020 | 30 | -48.6 (-57.5 to -39.3) | +0.0 (-0.1 to +0.1) | -0.4 (-0.8 to +0.0) |
| tomatoes, by the weather | the wind's monthly normal, McAllister 2021–2025 | 5 | -34.4 (-66.4 to -6.7) | +0.0 (+0.0 to +0.0) | +0.6 (-0.8 to +2.2) |
| tomatoes, by the weather | hot-day refill point, margin 0.1, Davis | 35 | -96.5 (-101.2 to -91.7) | -0.1 (-0.3 to -0.0) | -2.2 (-4.1 to -0.7) |
| tomatoes, by the weather | hot-day refill point, margin 0.1, McAllister 1991–2020 | 30 | -63.4 (-71.2 to -55.5) | +0.0 (-0.0 to +0.0) | -1.0 (-1.6 to -0.3) |
| tomatoes, by the weather | hot-day refill point, margin 0.1, McAllister 2021–2025 | 5 | -63.7 (-90.3 to -39.4) | +0.0 (+0.0 to +0.0) | -0.5 (-1.2 to +0.3) |
| tomatoes, by the weather | hot-day refill point, Davis | 35 | +9.2 (+5.9 to +12.8) | -0.6 (-1.2 to -0.2) | -0.9 (-2.0 to -0.0) |
| tomatoes, by the weather | hot-day refill point, McAllister 1991–2020 | 30 | +6.3 (+0.1 to +12.6) | -0.1 (-0.2 to -0.0) | -0.0 (-0.4 to +0.4) |
| tomatoes, by the weather | hot-day refill point, McAllister 2021–2025 | 5 | -1.6 (-12.3 to +8.0) | +0.0 (+0.0 to +0.0) | -0.5 (-1.1 to +0.1) |
| lettuce, probes | hot-day refill point, Davis | 35 | -0.7 (-7.6 to +5.9) | +0.1 (-2.5 to +2.6) | +0.1 (+0.0 to +0.3) |
| lettuce, probes | hot-day refill point, McAllister 1991–2020 | 30 | +2.9 (-1.7 to +7.7) | -0.2 (-0.5 to +0.0) | +0.1 (-0.2 to +0.4) |
| lettuce, probes | hot-day refill point, McAllister 2021–2025 | 5 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| lettuce, probes | tension sensors, Davis | 35 | -12.8 (-28.6 to +2.0) | -4.0 (-7.8 to -0.7) | -0.4 (-0.7 to -0.1) |
| lettuce, probes | tension sensors, McAllister 1991–2020 | 30 | -90.6 (-114.4 to -67.7) | +0.3 (-0.1 to +0.8) | -1.5 (-2.3 to -0.7) |
| lettuce, probes | tension sensors, McAllister 2021–2025 | 5 | -199.0 (-241.1 to -156.9) | +1.0 (+0.2 to +2.0) | -6.8 (-10.5 to -3.4) |
| lettuce, probes | learning within 0.05, Davis | 35 | -3.5 (-7.4 to -0.3) | +0.5 (-0.0 to +1.3) | -0.2 (-0.4 to -0.0) |
| lettuce, probes | learning within 0.05, McAllister 1991–2020 | 30 | -12.8 (-20.5 to -6.2) | +0.0 (+0.0 to +0.0) | -0.6 (-1.1 to -0.2) |
| lettuce, probes | learning within 0.05, McAllister 2021–2025 | 5 | -10.7 (-32.2 to +0.0) | +0.0 (+0.0 to +0.0) | -0.5 (-1.5 to +0.0) |
| lettuce, probes | hot-day refill point, learning within 0.05, Davis | 35 | -5.2 (-12.7 to +2.1) | +0.7 (-2.0 to +3.3) | -0.2 (-0.4 to -0.0) |
| lettuce, probes | hot-day refill point, learning within 0.05, McAllister 1991–2020 | 30 | -10.7 (-19.5 to -2.9) | -0.2 (-0.5 to +0.0) | -0.6 (-1.1 to -0.2) |
| lettuce, probes | hot-day refill point, learning within 0.05, McAllister 2021–2025 | 5 | -10.7 (-32.2 to +0.0) | +0.0 (+0.0 to +0.0) | -0.5 (-1.0 to +0.0) |
| lettuce, probes | hot-day refill point, tension sensors, Davis | 35 | -11.7 (-26.8 to +4.3) | -4.3 (-8.0 to -0.8) | -0.4 (-0.7 to -0.1) |
| lettuce, probes | hot-day refill point, tension sensors, McAllister 1991–2020 | 30 | -88.4 (-113.0 to -63.5) | +0.3 (-0.2 to +0.7) | -1.5 (-2.3 to -0.7) |
| lettuce, probes | hot-day refill point, tension sensors, McAllister 2021–2025 | 5 | -194.5 (-236.2 to -151.3) | +0.7 (+0.2 to +1.3) | -6.8 (-10.3 to -3.4) |
| lettuce, probes | a probe at 5 cm, Davis | 35 | -3.7 (-16.6 to +8.2) | -3.1 (-6.4 to +0.1) | -0.3 (-0.7 to -0.0) |
| lettuce, probes | a probe at 5 cm, McAllister 1991–2020 | 30 | -13.4 (-30.2 to +2.7) | -0.2 (-0.6 to -0.0) | -1.0 (-1.9 to -0.3) |
| lettuce, probes | a probe at 5 cm, McAllister 2021–2025 | 5 | -52.3 (-92.5 to -28.3) | -0.0 (-0.1 to -0.0) | -5.7 (-8.4 to -3.0) |
| lettuce, probes | hot-day refill point, a probe at 5 cm, Davis | 35 | +2.4 (-12.1 to +14.6) | -3.8 (-7.1 to -0.6) | -0.3 (-0.7 to -0.1) |
| lettuce, probes | hot-day refill point, a probe at 5 cm, McAllister 1991–2020 | 30 | -11.3 (-27.0 to +3.4) | -0.2 (-0.6 to -0.0) | -1.0 (-1.8 to -0.3) |
| lettuce, probes | hot-day refill point, a probe at 5 cm, McAllister 2021–2025 | 5 | -54.7 (-92.0 to -31.7) | -0.0 (-0.1 to -0.0) | -5.9 (-8.7 to -3.0) |
| lettuce, by the weather | margin 0, Davis | 35 | -103.3 (-108.2 to -97.9) | +5.1 (+3.3 to +7.1) | -3.2 (-5.2 to -1.6) |
| lettuce, by the weather | margin 0, McAllister 1991–2020 | 30 | -68.0 (-74.4 to -60.7) | +0.2 (+0.0 to +0.4) | -2.3 (-3.4 to -1.3) |
| lettuce, by the weather | margin 0, McAllister 2021–2025 | 5 | -49.0 (-66.3 to -31.7) | -0.1 (-0.3 to +0.0) | -1.3 (-2.4 to -0.1) |
| lettuce, by the weather | margin 0.1, Davis | 35 | -53.2 (-56.1 to -50.1) | +0.6 (+0.2 to +1.0) | -1.7 (-2.6 to -0.9) |
| lettuce, by the weather | margin 0.1, McAllister 1991–2020 | 30 | -34.5 (-38.1 to -30.6) | +0.1 (+0.0 to +0.3) | -0.9 (-1.6 to -0.2) |
| lettuce, by the weather | margin 0.1, McAllister 2021–2025 | 5 | -19.7 (-30.2 to -8.4) | -0.0 (-0.1 to +0.0) | -0.5 (-1.9 to +0.8) |
| lettuce, by the weather | wind measured, margin 0.1, Davis | 35 | -27.3 (-34.0 to -20.5) | +0.1 (-0.0 to +0.3) | -1.0 (-1.6 to -0.4) |
| lettuce, by the weather | wind measured, margin 0.1, McAllister 1991–2020 | 30 | -48.6 (-54.4 to -42.7) | +0.1 (+0.0 to +0.3) | -1.6 (-2.4 to -0.8) |
| lettuce, by the weather | wind measured, margin 0.1, McAllister 2021–2025 | 5 | -30.1 (-43.8 to -15.4) | +0.0 (+0.0 to +0.1) | -0.8 (-2.0 to +0.4) |
| lettuce, by the weather | wind measured, Davis | 35 | +28.1 (+21.0 to +35.3) | -0.2 (-0.3 to -0.1) | +0.7 (+0.2 to +1.2) |
| lettuce, by the weather | wind measured, McAllister 1991–2020 | 30 | -15.2 (-19.4 to -11.0) | +0.0 (+0.0 to +0.0) | -0.2 (-0.7 to +0.3) |
| lettuce, by the weather | wind measured, McAllister 2021–2025 | 5 | -5.5 (-13.9 to +3.9) | -0.0 (-0.1 to +0.0) | -0.2 (-1.8 to +1.3) |
| lettuce, by the weather | the wind's monthly normal, margin 0.1, Davis | 35 | -23.2 (-25.9 to -20.6) | +0.0 (-0.1 to +0.1) | -0.6 (-0.9 to -0.4) |
| lettuce, by the weather | the wind's monthly normal, margin 0.1, McAllister 1991–2020 | 30 | -47.3 (-52.8 to -41.8) | +0.1 (+0.0 to +0.3) | -1.6 (-2.5 to -0.8) |
| lettuce, by the weather | the wind's monthly normal, margin 0.1, McAllister 2021–2025 | 5 | -26.4 (-39.3 to -14.3) | +0.0 (+0.0 to +0.1) | -0.7 (-1.7 to +0.5) |
| lettuce, by the weather | the wind's monthly normal, Davis | 35 | +33.9 (+29.7 to +38.0) | -0.2 (-0.4 to -0.1) | +0.9 (+0.5 to +1.3) |
| lettuce, by the weather | the wind's monthly normal, McAllister 1991–2020 | 30 | -14.3 (-18.5 to -10.3) | +0.0 (+0.0 to +0.0) | -0.2 (-0.5 to +0.2) |
| lettuce, by the weather | the wind's monthly normal, McAllister 2021–2025 | 5 | -2.4 (-14.6 to +6.9) | -0.0 (-0.1 to +0.0) | -0.2 (-1.8 to +1.3) |
| lettuce, by the weather | hot-day refill point, margin 0.1, Davis | 35 | -48.5 (-51.2 to -45.7) | -0.1 (-0.3 to +0.0) | -2.2 (-3.5 to -1.1) |
| lettuce, by the weather | hot-day refill point, margin 0.1, McAllister 1991–2020 | 30 | -36.7 (-40.5 to -32.7) | +0.0 (-0.0 to +0.0) | -1.3 (-2.1 to -0.6) |
| lettuce, by the weather | hot-day refill point, margin 0.1, McAllister 2021–2025 | 5 | -17.0 (-23.8 to -7.8) | -0.0 (-0.1 to +0.0) | -1.0 (-2.4 to +0.5) |
| lettuce, by the weather | hot-day refill point, Davis | 35 | +2.8 (+0.4 to +5.2) | -0.4 (-0.6 to -0.2) | -1.1 (-1.8 to -0.5) |
| lettuce, by the weather | hot-day refill point, McAllister 1991–2020 | 30 | +1.3 (-1.8 to +4.4) | -0.0 (-0.1 to -0.0) | -0.3 (-0.7 to +0.1) |
| lettuce, by the weather | hot-day refill point, McAllister 2021–2025 | 5 | +5.2 (-2.0 to +12.0) | -0.1 (-0.2 to +0.0) | -0.5 (-1.8 to +0.7) |
| lawn, its probe | p 0.2, Davis | 35 | +72.5 (+56.8 to +91.2) | -40.2 (-49.9 to -30.9) | +0.6 (+0.1 to +1.3) |
| lawn, its probe | p 0.2, McAllister 1991–2020 | 30 | +89.6 (+73.4 to +105.9) | -0.0 (-0.1 to -0.0) | +10.0 (+7.7 to +12.7) |
| lawn, its probe | p 0.2, McAllister 2021–2025 | 5 | +109.8 (+32.2 to +189.3) | -0.0 (-0.0 to +0.0) | +7.9 (+3.3 to +12.6) |
| lawn, its probe | hot-day refill point, Davis | 35 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| lawn, its probe | hot-day refill point, McAllister 1991–2020 | 30 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| lawn, its probe | hot-day refill point, McAllister 2021–2025 | 5 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| lawn, its probe | hot-day refill point, p 0.2, Davis | 35 | +73.3 (+57.4 to +91.9) | -40.8 (-50.9 to -31.6) | +0.6 (+0.1 to +1.3) |
| lawn, its probe | hot-day refill point, p 0.2, McAllister 1991–2020 | 30 | +89.6 (+72.7 to +106.5) | -0.0 (-0.1 to -0.0) | +10.0 (+7.6 to +12.8) |
| lawn, its probe | hot-day refill point, p 0.2, McAllister 2021–2025 | 5 | +109.8 (+33.1 to +189.3) | -0.0 (-0.1 to +0.0) | +7.9 (+3.3 to +12.7) |
| lawn, its probe | tension sensors, Davis | 35 | +79.2 (+64.3 to +95.3) | -46.8 (-60.5 to -34.2) | +0.3 (-0.1 to +0.6) |
| lawn, its probe | tension sensors, McAllister 1991–2020 | 30 | -25.8 (-37.0 to -15.2) | +0.1 (-0.0 to +0.2) | -2.9 (-4.4 to -1.4) |
| lawn, its probe | tension sensors, McAllister 2021–2025 | 5 | -29.3 (-53.8 to -6.7) | +0.1 (+0.0 to +0.3) | -3.7 (-7.2 to -0.3) |
| lawn, its probe | tension sensors, p 0.2, Davis | 35 | +90.1 (+73.5 to +108.9) | -52.2 (-67.2 to -37.4) | +0.2 (-0.1 to +0.5) |
| lawn, its probe | tension sensors, p 0.2, McAllister 1991–2020 | 30 | +0.7 (-9.6 to +10.2) | -0.0 (-0.1 to -0.0) | +1.5 (+0.1 to +2.8) |
| lawn, its probe | tension sensors, p 0.2, McAllister 2021–2025 | 5 | -9.9 (-36.7 to +13.2) | -0.0 (-0.1 to +0.0) | -2.2 (-6.2 to +1.1) |
| lawn, its probe | learning within 0.05, Davis | 35 | +25.1 (+19.0 to +31.9) | -15.5 (-20.5 to -11.1) | +0.0 (+0.0 to +0.0) |
| lawn, its probe | learning within 0.05, McAllister 1991–2020 | 30 | -0.1 (-0.3 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (-0.0 to +0.1) |
| lawn, its probe | learning within 0.05, McAllister 2021–2025 | 5 | -0.0 (-0.1 to +0.0) | +0.0 (+0.0 to +0.0) | -0.0 (-0.0 to +0.0) |
| lawn, its probe | learning within 0.05, p 0.2, Davis | 35 | +73.9 (+57.2 to +91.3) | -40.8 (-50.5 to -31.4) | +0.6 (+0.1 to +1.3) |
| lawn, its probe | learning within 0.05, p 0.2, McAllister 1991–2020 | 30 | +85.9 (+70.4 to +101.4) | -0.0 (-0.1 to -0.0) | +9.5 (+7.6 to +11.4) |
| lawn, its probe | learning within 0.05, p 0.2, McAllister 2021–2025 | 5 | +90.4 (+32.2 to +150.6) | -0.0 (-0.1 to +0.0) | +6.5 (+2.6 to +11.7) |
| lawn, its probe | hot-day refill point, learning within 0.05, Davis | 35 | +25.1 (+19.1 to +31.0) | -15.5 (-20.2 to -10.9) | +0.0 (+0.0 to +0.0) |
| lawn, its probe | hot-day refill point, learning within 0.05, McAllister 1991–2020 | 30 | -0.1 (-0.3 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (-0.0 to +0.1) |
| lawn, its probe | hot-day refill point, learning within 0.05, McAllister 2021–2025 | 5 | -0.0 (-0.1 to +0.0) | +0.0 (+0.0 to +0.0) | -0.0 (-0.0 to +0.0) |
| lawn, its probe | hot-day refill point, learning within 0.05, p 0.2, Davis | 35 | +74.3 (+58.3 to +92.5) | -41.2 (-51.6 to -31.2) | +0.6 (+0.1 to +1.3) |
| lawn, its probe | hot-day refill point, learning within 0.05, p 0.2, McAllister 1991–2020 | 30 | +85.9 (+71.1 to +101.0) | -0.0 (-0.1 to -0.0) | +9.5 (+7.6 to +11.5) |
| lawn, its probe | hot-day refill point, learning within 0.05, p 0.2, McAllister 2021–2025 | 5 | +90.4 (+32.2 to +147.7) | -0.0 (-0.1 to +0.0) | +6.5 (+2.6 to +10.8) |
| lawn, its probe | hot-day refill point, tension sensors, Davis | 35 | +79.1 (+64.4 to +94.9) | -46.8 (-59.7 to -34.5) | +0.3 (-0.1 to +0.6) |
| lawn, its probe | hot-day refill point, tension sensors, McAllister 1991–2020 | 30 | -25.8 (-36.9 to -14.9) | +0.1 (-0.0 to +0.2) | -2.9 (-4.6 to -1.4) |
| lawn, its probe | hot-day refill point, tension sensors, McAllister 2021–2025 | 5 | -29.3 (-54.5 to -6.7) | +0.1 (+0.0 to +0.3) | -3.7 (-7.2 to -0.3) |
| lawn, its probe | hot-day refill point, tension sensors, p 0.2, Davis | 35 | +90.1 (+73.7 to +108.3) | -52.2 (-66.8 to -38.3) | +0.2 (-0.1 to +0.5) |
| lawn, its probe | hot-day refill point, tension sensors, p 0.2, McAllister 1991–2020 | 30 | +0.7 (-10.0 to +11.0) | -0.0 (-0.1 to -0.0) | +1.5 (+0.1 to +2.9) |
| lawn, its probe | hot-day refill point, tension sensors, p 0.2, McAllister 2021–2025 | 5 | -9.9 (-32.9 to +13.2) | -0.0 (-0.1 to +0.0) | -2.2 (-6.2 to +1.4) |
| lawn, by the weather | margin 0, Davis | 35 | -116.5 (-119.4 to -113.3) | +25.3 (+16.7 to +34.3) | -25.9 (-32.3 to -20.1) |
| lawn, by the weather | margin 0, McAllister 1991–2020 | 30 | -72.8 (-78.5 to -67.2) | +0.1 (+0.0 to +0.3) | -9.5 (-11.7 to -7.5) |
| lawn, by the weather | margin 0, McAllister 2021–2025 | 5 | -68.1 (-79.4 to -56.8) | +0.0 (+0.0 to +0.0) | -6.6 (-9.2 to -4.0) |
| lawn, by the weather | margin 0.1, Davis | 35 | -58.7 (-61.1 to -56.2) | +6.3 (+2.6 to +10.4) | -14.2 (-18.5 to -10.4) |
| lawn, by the weather | margin 0.1, McAllister 1991–2020 | 30 | -35.4 (-38.7 to -32.0) | +0.0 (+0.0 to +0.0) | -4.2 (-5.1 to -3.3) |
| lawn, by the weather | margin 0.1, McAllister 2021–2025 | 5 | -30.8 (-42.1 to -19.3) | +0.0 (+0.0 to +0.0) | -1.3 (-2.8 to +0.1) |
| lawn, by the weather | wind measured, margin 0.1, Davis | 35 | -17.9 (-27.1 to -8.6) | +2.0 (+0.0 to +4.5) | -4.9 (-7.7 to -2.4) |
| lawn, by the weather | wind measured, margin 0.1, McAllister 1991–2020 | 30 | -64.2 (-71.3 to -56.9) | +0.0 (+0.0 to +0.0) | -8.5 (-10.7 to -6.4) |
| lawn, by the weather | wind measured, margin 0.1, McAllister 2021–2025 | 5 | -57.0 (-73.1 to -40.8) | +0.0 (+0.0 to +0.0) | -4.1 (-7.3 to -1.6) |
| lawn, by the weather | wind measured, Davis | 35 | +43.7 (+34.2 to +53.6) | -1.3 (-2.8 to -0.2) | +8.6 (+6.0 to +11.5) |
| lawn, by the weather | wind measured, McAllister 1991–2020 | 30 | -32.6 (-38.3 to -27.2) | +0.0 (+0.0 to +0.0) | -3.7 (-4.9 to -2.6) |
| lawn, by the weather | wind measured, McAllister 2021–2025 | 5 | -31.2 (-46.9 to -17.0) | +0.0 (+0.0 to +0.0) | -0.8 (-2.6 to +0.6) |
| lawn, by the weather | the wind's monthly normal, margin 0.1, Davis | 35 | -9.0 (-10.8 to -7.1) | +0.6 (+0.1 to +1.2) | -2.3 (-3.8 to -0.9) |
| lawn, by the weather | the wind's monthly normal, margin 0.1, McAllister 1991–2020 | 30 | -63.7 (-71.2 to -57.2) | +0.0 (+0.0 to +0.0) | -8.6 (-10.7 to -6.6) |
| lawn, by the weather | the wind's monthly normal, margin 0.1, McAllister 2021–2025 | 5 | -56.8 (-73.0 to -41.7) | +0.0 (+0.0 to +0.0) | -4.3 (-7.7 to -2.0) |
| lawn, by the weather | the wind's monthly normal, Davis | 35 | +53.5 (+50.8 to +56.1) | -1.6 (-3.3 to -0.3) | +9.9 (+8.4 to +11.6) |
| lawn, by the weather | the wind's monthly normal, McAllister 1991–2020 | 30 | -27.8 (-32.7 to -22.9) | +0.0 (+0.0 to +0.0) | -2.6 (-3.4 to -1.9) |
| lawn, by the weather | the wind's monthly normal, McAllister 2021–2025 | 5 | -28.3 (-44.0 to -12.5) | +0.0 (+0.0 to +0.0) | -0.4 (-2.2 to +1.3) |
| lawn, by the weather | hot-day refill point, margin 0.1, Davis | 35 | -58.7 (-61.1 to -56.0) | +6.3 (+2.7 to +10.5) | -14.2 (-18.5 to -10.4) |
| lawn, by the weather | hot-day refill point, margin 0.1, McAllister 1991–2020 | 30 | -35.4 (-39.0 to -32.0) | +0.0 (+0.0 to +0.0) | -4.2 (-5.1 to -3.4) |
| lawn, by the weather | hot-day refill point, margin 0.1, McAllister 2021–2025 | 5 | -30.8 (-42.1 to -19.3) | +0.0 (+0.0 to +0.0) | -1.3 (-2.8 to +0.1) |
| lawn, by the weather | hot-day refill point, Davis | 35 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| lawn, by the weather | hot-day refill point, McAllister 1991–2020 | 30 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| lawn, by the weather | hot-day refill point, McAllister 2021–2025 | 5 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| yard, its probes | p 0.2, Davis | 35 | +23.0 (+17.0 to +29.7) | -17.3 (-23.2 to -11.8) | +0.0 (+0.0 to +0.0) |
| yard, its probes | p 0.2, McAllister 1991–2020 | 30 | +34.6 (+27.2 to +42.5) | -0.8 (-1.2 to -0.4) | +0.3 (+0.0 to +0.7) |
| yard, its probes | p 0.2, McAllister 2021–2025 | 5 | +26.5 (+10.6 to +43.1) | -1.4 (-3.7 to -0.1) | +0.0 (+0.0 to +0.1) |
| yard, its probes | hot-day refill point, Davis | 35 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| yard, its probes | hot-day refill point, McAllister 1991–2020 | 30 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| yard, its probes | hot-day refill point, McAllister 2021–2025 | 5 | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) | +0.0 (+0.0 to +0.0) |
| yard, its probes | hot-day refill point, p 0.2, Davis | 35 | +23.0 (+16.9 to +29.9) | -17.3 (-23.5 to -12.1) | +0.0 (+0.0 to +0.0) |
| yard, its probes | hot-day refill point, p 0.2, McAllister 1991–2020 | 30 | +34.6 (+27.6 to +42.1) | -0.8 (-1.2 to -0.4) | +0.3 (+0.0 to +0.7) |
| yard, its probes | hot-day refill point, p 0.2, McAllister 2021–2025 | 5 | +26.5 (+10.6 to +42.9) | -1.4 (-3.7 to -0.1) | +0.0 (+0.0 to +0.1) |
| yard, its probes | tension sensors, Davis | 35 | +18.6 (+7.4 to +31.7) | -14.6 (-24.7 to -6.0) | +0.0 (+0.0 to +0.0) |
| yard, its probes | tension sensors, McAllister 1991–2020 | 30 | -56.0 (-65.8 to -46.3) | +1.1 (+0.6 to +1.7) | -0.6 (-1.0 to -0.2) |
| yard, its probes | tension sensors, McAllister 2021–2025 | 5 | -63.4 (-75.5 to -51.4) | +3.0 (+1.4 to +4.6) | -0.1 (-0.5 to +0.0) |
| yard, its probes | tension sensors, p 0.2, Davis | 35 | +29.5 (+17.8 to +41.7) | -22.3 (-32.8 to -13.6) | +0.0 (+0.0 to +0.0) |
| yard, its probes | tension sensors, p 0.2, McAllister 1991–2020 | 30 | -42.5 (-54.2 to -31.3) | -0.2 (-0.7 to +0.3) | -0.3 (-0.7 to +0.1) |
| yard, its probes | tension sensors, p 0.2, McAllister 2021–2025 | 5 | -45.6 (-59.9 to -31.0) | -0.3 (-1.7 to +0.7) | -0.1 (-0.4 to +0.0) |
| yard, its probes | learning within 0.05, Davis | 35 | +1.0 (-0.0 to +2.3) | -0.7 (-1.6 to +0.1) | +0.0 (+0.0 to +0.0) |
| yard, its probes | learning within 0.05, McAllister 1991–2020 | 30 | -8.9 (-15.1 to -3.6) | +0.1 (-0.0 to +0.2) | -0.1 (-0.3 to +0.0) |
| yard, its probes | learning within 0.05, McAllister 2021–2025 | 5 | -21.7 (-48.2 to -5.5) | -0.0 (-0.1 to +0.0) | -0.2 (-0.6 to +0.0) |
| yard, its probes | learning within 0.05, p 0.2, Davis | 35 | +22.8 (+16.9 to +28.8) | -17.1 (-23.2 to -11.8) | +0.0 (+0.0 to +0.0) |
| yard, its probes | learning within 0.05, p 0.2, McAllister 1991–2020 | 30 | +16.4 (+9.4 to +22.7) | -0.8 (-1.2 to -0.4) | +0.2 (-0.1 to +0.7) |
| yard, its probes | learning within 0.05, p 0.2, McAllister 2021–2025 | 5 | +12.2 (-15.3 to +39.2) | -1.2 (-3.0 to -0.1) | -0.1 (-0.2 to +0.1) |
| yard, its probes | hot-day refill point, learning within 0.05, Davis | 35 | +1.0 (-0.1 to +2.2) | -0.7 (-1.6 to +0.1) | +0.0 (+0.0 to +0.0) |
| yard, its probes | hot-day refill point, learning within 0.05, McAllister 1991–2020 | 30 | -8.9 (-15.4 to -3.5) | +0.1 (-0.0 to +0.2) | -0.1 (-0.3 to +0.0) |
| yard, its probes | hot-day refill point, learning within 0.05, McAllister 2021–2025 | 5 | -21.7 (-47.3 to -5.9) | -0.0 (-0.1 to +0.0) | -0.2 (-0.6 to +0.0) |
| yard, its probes | hot-day refill point, learning within 0.05, p 0.2, Davis | 35 | +22.8 (+16.9 to +29.1) | -17.2 (-23.0 to -12.0) | +0.0 (+0.0 to +0.0) |
| yard, its probes | hot-day refill point, learning within 0.05, p 0.2, McAllister 1991–2020 | 30 | +16.4 (+9.1 to +22.9) | -0.8 (-1.2 to -0.4) | +0.2 (-0.1 to +0.7) |
| yard, its probes | hot-day refill point, learning within 0.05, p 0.2, McAllister 2021–2025 | 5 | +12.2 (-18.8 to +39.2) | -1.2 (-3.0 to -0.1) | -0.1 (-0.2 to +0.1) |
| yard, its probes | hot-day refill point, tension sensors, Davis | 35 | +18.6 (+7.4 to +30.7) | -14.6 (-24.2 to -6.1) | +0.0 (+0.0 to +0.0) |
| yard, its probes | hot-day refill point, tension sensors, McAllister 1991–2020 | 30 | -56.0 (-65.9 to -45.8) | +1.1 (+0.6 to +1.7) | -0.6 (-1.0 to -0.2) |
| yard, its probes | hot-day refill point, tension sensors, McAllister 2021–2025 | 5 | -63.4 (-75.5 to -50.8) | +3.0 (+1.4 to +4.6) | -0.1 (-0.5 to +0.0) |
| yard, its probes | hot-day refill point, tension sensors, p 0.2, Davis | 35 | +29.5 (+17.9 to +42.3) | -22.3 (-32.5 to -12.9) | +0.0 (+0.0 to +0.0) |
| yard, its probes | hot-day refill point, tension sensors, p 0.2, McAllister 1991–2020 | 30 | -42.5 (-53.3 to -31.3) | -0.2 (-0.7 to +0.3) | -0.3 (-0.7 to +0.1) |
| yard, its probes | hot-day refill point, tension sensors, p 0.2, McAllister 2021–2025 | 5 | -45.6 (-60.1 to -31.0) | -0.3 (-1.7 to +0.7) | -0.1 (-0.4 to +0.0) |
| tomatoes over a dense pan, probes | hot-day refill point, Davis | 35 | +16.8 (+0.5 to +34.9) | -4.3 (-7.1 to -1.9) | -1.3 (-2.6 to +0.1) |
| tomatoes over a dense pan, probes | hot-day refill point, McAllister 1991–2020 | 30 | +6.8 (-3.6 to +18.2) | -0.4 (-0.6 to -0.2) | +0.6 (-1.4 to +3.4) |
| tomatoes over a dense pan, probes | hot-day refill point, McAllister 2021–2025 | 5 | +2.8 (-0.6 to +9.1) | -0.0 (-0.1 to +0.0) | +0.2 (-0.0 to +0.5) |
| tomatoes over a dense pan, probes | tension sensors, Davis | 35 | -72.4 (-97.2 to -48.2) | -2.4 (-7.2 to +1.8) | -3.5 (-5.5 to -1.7) |
| tomatoes over a dense pan, probes | tension sensors, McAllister 1991–2020 | 30 | -206.7 (-243.8 to -171.4) | +0.6 (+0.1 to +1.1) | -10.4 (-13.9 to -7.5) |
| tomatoes over a dense pan, probes | tension sensors, McAllister 2021–2025 | 5 | -243.5 (-283.8 to -201.9) | +1.2 (+0.2 to +2.5) | -8.9 (-15.7 to -2.4) |
| tomatoes over a dense pan, probes | learning within 0.05, Davis | 35 | -2.1 (-5.5 to +0.9) | -0.4 (-0.9 to -0.0) | -0.2 (-0.4 to +0.0) |
| tomatoes over a dense pan, probes | learning within 0.05, McAllister 1991–2020 | 30 | -26.9 (-41.0 to -14.4) | -0.1 (-0.2 to +0.0) | -2.1 (-3.9 to -0.5) |
| tomatoes over a dense pan, probes | learning within 0.05, McAllister 2021–2025 | 5 | -21.0 (-62.9 to +0.0) | -0.0 (-0.0 to +0.0) | +0.4 (+0.0 to +1.1) |
| tomatoes over a dense pan, probes | hot-day refill point, learning within 0.05, Davis | 35 | +13.7 (-1.9 to +31.2) | -4.6 (-7.5 to -2.3) | -1.2 (-2.7 to +0.1) |
| tomatoes over a dense pan, probes | hot-day refill point, learning within 0.05, McAllister 1991–2020 | 30 | -18.6 (-36.4 to -1.4) | -0.4 (-0.6 to -0.2) | -1.4 (-4.1 to +1.7) |
| tomatoes over a dense pan, probes | hot-day refill point, learning within 0.05, McAllister 2021–2025 | 5 | -18.2 (-59.8 to +6.2) | -0.1 (-0.1 to -0.0) | +0.5 (-0.0 to +1.1) |
| tomatoes over a dense pan, probes | hot-day refill point, tension sensors, Davis | 35 | -66.4 (-90.9 to -41.1) | -4.6 (-9.4 to -0.6) | -3.8 (-6.1 to -1.8) |
| tomatoes over a dense pan, probes | hot-day refill point, tension sensors, McAllister 1991–2020 | 30 | -206.5 (-242.9 to -170.3) | +0.1 (-0.2 to +0.5) | -10.2 (-13.6 to -7.2) |
| tomatoes over a dense pan, probes | hot-day refill point, tension sensors, McAllister 2021–2025 | 5 | -244.6 (-277.8 to -205.3) | +1.2 (+0.3 to +2.6) | -8.8 (-15.7 to -2.0) |

### The sealed sites

Bushland, Texas, and Tifton, Georgia, run once, the advice as built against the hardware
recommended. The tension sensor's help for the lawn held at Bushland (−13.4 of 23.5); for
lettuce and the yard it did not, both losing 1 to 2 mm more at Tifton. An anemometer, not
recommended for the calm open sites, cut every bed by the weather's loss at windy Bushland.

Code: 735d41f. Each summer one farm.

| bed | summers | water | lost transpiration | share of demand | summers losing over 1% | hours waterlogged | ran off | stored at the end |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bucket, its probe, Bushland (sealed) | 35 | 542 mm | 19.4 mm | 2.6% | 21 | 0 | 0 mm | -12 mm |
| bucket, its probe, Tifton (sealed) | 35 | 273 mm | 0.6 mm | 0.1% | 1 | 0 | 0 mm | -6 mm |
| bucket, by the weather, Bushland (sealed) | 35 | 529 mm | 27.4 mm | 3.4% | 22 | 0 | 0 mm | -11 mm |
| bucket, by the weather, Tifton (sealed) | 35 | 245 mm | 4.7 mm | 0.8% | 6 | 0 | 0 mm | -8 mm |
| tomatoes, probes, Bushland (sealed) | 35 | 1023 mm | 5.0 mm | 0.7% | 9 | 3 | 0 mm | +23 mm |
| tomatoes, probes, Tifton (sealed) | 35 | 550 mm | 0.4 mm | 0.1% | 0 | 11 | 0 mm | +36 mm |
| tomatoes, by the weather, Bushland (sealed) | 35 | 968 mm | 3.9 mm | 0.5% | 3 | 4 | 0 mm | +4 mm |
| tomatoes, by the weather, Tifton (sealed) | 35 | 550 mm | 0.2 mm | 0.0% | 0 | 11 | 0 mm | +30 mm |
| lettuce, probes, Bushland (sealed) | 35 | 508 mm | 9.4 mm | 2.5% | 14 | 2 | 0 mm | +5 mm |
| lettuce, probes, Tifton (sealed) | 35 | 286 mm | 0.3 mm | 0.1% | 2 | 6 | 0 mm | +27 mm |
| lettuce, by the weather, Bushland (sealed) | 35 | 523 mm | 4.6 mm | 1.2% | 11 | 5 | 0 mm | +13 mm |
| lettuce, by the weather, Tifton (sealed) | 35 | 334 mm | 0.2 mm | 0.1% | 1 | 9 | 0 mm | +34 mm |
| lawn, its probe, Bushland (sealed) | 35 | 406 mm | 23.5 mm | 3.4% | 16 | 12 | 0 mm | -22 mm |
| lawn, its probe, Tifton (sealed) | 35 | 161 mm | 0.3 mm | 0.1% | 1 | 34 | 0 mm | -0 mm |
| lawn, by the weather, Bushland (sealed) | 35 | 520 mm | 5.5 mm | 0.7% | 4 | 41 | 0 mm | -0 mm |
| lawn, by the weather, Tifton (sealed) | 35 | 253 mm | 0.3 mm | 0.1% | 1 | 61 | 0 mm | +9 mm |
| yard, its probes, Bushland (sealed) | 35 | 485 mm | 18.1 mm | 2.5% | 21 | 2 | 0 mm | +0 mm |
| yard, its probes, Tifton (sealed) | 35 | 249 mm | 1.5 mm | 0.3% | 3 | 9 | 7 mm | +15 mm |
| tomatoes over a dense pan, probes, Bushland (sealed) | 35 | 985 mm | 9.3 mm | 1.2% | 14 | 9 | 0 mm | +23 mm |
| tomatoes over a dense pan, probes, Tifton (sealed) | 35 | 592 mm | 1.0 mm | 0.2% | 2 | 37 | 16 mm | +44 mm |

| bed | against the bed as built | summers | water | lost transpiration | hours waterlogged |
| --- | --- | --- | --- | --- | --- |
| bucket, by the weather | wind measured, Bushland (sealed) | 35 | +91.7 (+78.6 to +104.8) | -17.2 (-23.4 to -11.7) | +0.0 (+0.0 to +0.0) |
| bucket, by the weather | wind measured, Tifton (sealed) | 35 | -8.2 (-11.5 to -5.0) | +0.8 (+0.3 to +1.6) | +0.0 (+0.0 to +0.0) |
| tomatoes, probes | tension sensors, Bushland (sealed) | 35 | -147.1 (-187.4 to -111.0) | +1.0 (-0.2 to +2.3) | -1.2 (-1.9 to -0.6) |
| tomatoes, probes | tension sensors, Tifton (sealed) | 35 | -193.4 (-224.6 to -161.9) | +0.6 (+0.1 to +1.1) | -4.0 (-5.5 to -2.7) |
| tomatoes, by the weather | wind measured, Bushland (sealed) | 35 | +201.8 (+166.6 to +237.6) | -3.4 (-6.4 to -1.0) | +8.1 (+5.8 to +10.7) |
| tomatoes, by the weather | wind measured, Tifton (sealed) | 35 | -8.3 (-15.5 to -1.2) | -0.0 (-0.1 to +0.0) | +0.1 (-0.3 to +0.4) |
| lettuce, probes | tension sensors, Bushland (sealed) | 35 | -43.0 (-65.0 to -22.3) | -1.8 (-4.5 to +0.8) | -0.4 (-0.8 to -0.1) |
| lettuce, probes | tension sensors, Tifton (sealed) | 35 | -67.9 (-82.4 to -53.5) | +1.0 (+0.3 to +2.0) | -1.8 (-2.3 to -1.2) |
| lettuce, by the weather | wind measured, Bushland (sealed) | 35 | +122.6 (+98.6 to +147.4) | -4.0 (-7.2 to -1.5) | +6.6 (+4.7 to +8.7) |
| lettuce, by the weather | wind measured, Tifton (sealed) | 35 | -0.7 (-4.4 to +3.3) | +0.0 (-0.0 to +0.1) | +0.0 (-0.2 to +0.3) |
| lawn, its probe | tension sensors, Bushland (sealed) | 35 | +18.7 (+5.1 to +34.9) | -13.4 (-25.3 to -3.2) | +0.5 (-0.2 to +1.4) |
| lawn, its probe | tension sensors, Tifton (sealed) | 35 | -27.3 (-40.4 to -15.0) | +0.3 (+0.1 to +0.5) | -2.6 (-3.8 to -1.4) |
| lawn, by the weather | wind measured, Bushland (sealed) | 35 | +104.5 (+87.1 to +122.7) | -3.9 (-7.1 to -1.2) | +21.2 (+17.4 to +25.5) |
| lawn, by the weather | wind measured, Tifton (sealed) | 35 | -5.6 (-8.8 to -2.3) | -0.0 (-0.1 to +0.0) | -1.5 (-2.6 to -0.4) |
| yard, its probes | tension sensors, Bushland (sealed) | 35 | -21.1 (-30.3 to -11.5) | +1.1 (-2.3 to +4.3) | -0.3 (-0.5 to -0.1) |
| yard, its probes | tension sensors, Tifton (sealed) | 35 | -61.2 (-70.5 to -52.0) | +2.3 (+1.0 to +3.8) | -0.1 (-0.2 to +0.0) |
| tomatoes over a dense pan, probes | tension sensors, Bushland (sealed) | 35 | -95.9 (-128.5 to -65.2) | +1.9 (-1.1 to +4.7) | -3.4 (-5.5 to -1.5) |
| tomatoes over a dense pan, probes | tension sensors, Tifton (sealed) | 35 | -213.7 (-238.5 to -187.5) | +0.8 (+0.4 to +1.4) | -11.5 (-15.4 to -7.9) |

## The top third, 2026-10-19

`Bed.timing_share`: the watering of a sown crop past its young days timed by the top third
of its root zone, the refill to the whole zone; alone and with the hot-day refill point,
on the open sites' farms and summers for the three crop beds by probes (420 backtests, code
948e201), against the bed as built from the trial above (51dffc9, three of its rows run
again on 948e201 and the same to the bit). The rules, written before it ran:

The open sites' trials found the probe-led crops in a dry place short because the top of
the root zone, where most of the roots are, runs short on a hot day before the zone as a
whole reaches its refill point. Candidates, for a sown crop past its young days:

  A  the watering timed by the top third of the root zone at the bed's refill point
     (`Bed.timing_share` 1/3), the refill to the whole zone, as a stop in the roots is
  B  A with the hot-day refill point (`Bed.adjust_p`)

Beds: tomatoes by probes, tomatoes over a dense pan, lettuce by probes. Against the bed as
built on the same summers and farms, in each group (McAllister 1991-2020, McAllister
2021-2025, Davis).

A candidate is eligible if at Davis it cuts each of the three beds' mean lost transpiration
with its 90% interval below 0, and in neither McAllister group raises any of their mean lost
by more than 0.5 mm, or adds more than a tenth to any of their mean water. Of those
eligible, the one giving less water at Davis becomes the default for a sown crop; if none
is, the beds stay as built.

Sealed, their weather fetched after this is written and run once: Yuma, Arizona (32.69 N,
114.62 W, 60 m), hot desert farmland; Kearney, Nebraska (40.70 N, 99.08 W, 650 m),
continental and semi-arid. The bed as built against the choice, reported as they come.

What they found, each candidate against the bed as built, pair by pair:

```
== A, the top third: not eligible; water at Davis +16 mm over the three beds
  tomatoes, probes                   Davis                  lost -3.8 (-7.2 to -1.3) of 7.3 | water +4 (+0%) of 1135
  tomatoes, probes                   McAllister 1991–2020   lost -0.1 (-0.2 to -0.0) of 0.1 | water +30 (+5%) of 551
  tomatoes, probes                   McAllister 2021–2025   lost -0.0 (-0.1 to +0.0) of 0.1 | water -8 (-1%) of 673
  tomatoes over a dense pan, probes  Davis                  lost -2.3 (-5.4 to +0.9) of 13.3 | water +11 (+1%) of 1124  FAILS: not cut at Davis
  tomatoes over a dense pan, probes  McAllister 1991–2020   lost -0.7 (-1.2 to -0.4) of 0.8 | water +10 (+2%) of 557
  tomatoes over a dense pan, probes  McAllister 2021–2025   lost -0.4 (-1.1 to -0.1) of 0.5 | water +66 (+12%) of 569  FAILS: water up a tenth at McAllister
  lettuce, probes                    Davis                  lost +0.0 (+0.0 to +0.0) of 11.5 | water +0 (+0%) of 504  FAILS: not cut at Davis
  lettuce, probes                    McAllister 1991–2020   lost +0.0 (+0.0 to +0.0) of 0.3 | water +1 (+0%) of 252
  lettuce, probes                    McAllister 2021–2025   lost +0.0 (+0.0 to +0.0) of 0.0 | water +0 (+0%) of 352

== B, A with the hot-day refill point: not eligible; water at Davis +17 mm over the three beds
  tomatoes, probes                   Davis                  lost -3.8 (-7.2 to -1.4) of 7.3 | water +0 (+0%) of 1135
  tomatoes, probes                   McAllister 1991–2020   lost -0.1 (-0.2 to -0.0) of 0.1 | water +27 (+5%) of 551
  tomatoes, probes                   McAllister 2021–2025   lost -0.0 (-0.1 to +0.0) of 0.1 | water -5 (-1%) of 673
  tomatoes over a dense pan, probes  Davis                  lost -4.8 (-7.6 to -2.5) of 13.3 | water +16 (+1%) of 1124
  tomatoes over a dense pan, probes  McAllister 1991–2020   lost -0.7 (-1.2 to -0.4) of 0.8 | water +10 (+2%) of 557
  tomatoes over a dense pan, probes  McAllister 2021–2025   lost -0.4 (-1.1 to -0.1) of 0.5 | water +66 (+12%) of 569  FAILS: water up a tenth at McAllister
  lettuce, probes                    Davis                  lost -0.0 (-2.5 to +2.6) of 11.5 | water -0 (-0%) of 504  FAILS: not cut at Davis
  lettuce, probes                    McAllister 1991–2020   lost -0.2 (-0.5 to +0.0) of 0.3 | water +4 (+1%) of 252
  lettuce, probes                    McAllister 2021–2025   lost +0.0 (+0.0 to +0.0) of 0.0 | water +0 (+0%) of 352

-> neither: the beds stay as built
```

Neither passed: the dense pan took 12% more water in McAllister's last five summers, and
lettuce did not change at all. Its roots reach 30 cm, so its probe at 30 cm stands for
nothing (`weights`) and the one at 10 cm reads both the zone and its top third: the same
water, the same decision. Timing by the top third wants a probe in it apart from the rest.
The sealed sites were not run, nothing having been chosen: they wait, sealed, for the next.

## The top third on a hot day, 2026-10-19

`Bed.timing_share_hot`: the top third's timing only on a day the crop draws more than 5 mm,
and only where a probe lies in the top third with another below it, on the same farms and
summers for the three crop beds by probes (210 backtests, code 2bbcde5), against the bed as
built from the open sites' trial (three of its rows run again on this code: the same to the
bit). The rules, written before it ran:

The top third's first trial halved tomatoes' lost transpiration at Davis for no more water,
but gave tomatoes over a dense pan 12% more water in McAllister's last five summers, and
could not change lettuce, whose one probe in the root zone reads the zone and its top third
alike. The candidate now, for a sown crop past its young days:

  C  the watering timed by the top third of the root zone at the bed's refill point
     (`Bed.timing_share` 1/3), the refill to the whole zone, only where a probe lies in
     the top third and another below it in the root zone, and only on a day the crop is
     drawing more than 5 mm (its drying on a day the soil was not draining, as the hot-day
     refill point reads it; `Bed.timing_share_hot`)

Beds: tomatoes by probes and tomatoes over a dense pan, where it can act; lettuce by
probes, where it cannot, as a check that it does nothing there. Against the bed as built,
same summers and farms, in each group (McAllister 1991-2020, 2021-2025, Davis).

C becomes the default (`timing_share` 1/3 with `timing_share_hot`) for a sown crop if at
Davis it cuts both tomato beds' mean lost transpiration with the 90% interval below 0; in
neither McAllister group raises any of the three beds' mean lost by more than 0.5 mm or
adds more than a tenth to its mean water; and lettuce's mean water and lost move by no more
than 1 mm in any group.

Sealed since 2026-10-19 18:11 and run once if C is chosen: Yuma, Arizona, and Kearney,
Nebraska, the bed as built against C, for the three beds; reported as they come, and C
undone if at either it raises a bed's mean lost transpiration with the interval above 0.

What it found, against the bed as built, pair by pair:

```
tomatoes, probes                   Davis                  n  35  lost -2.32 (-5.33 to +0.09) of 7.3 | water +2.0 (+0.2%) of 1135  FAILS 1: not cut at Davis
tomatoes, probes                   McAllister 1991–2020   n  30  lost -0.05 (-0.10 to -0.02) of 0.1 | water -5.7 (-1.0%) of 551
tomatoes, probes                   McAllister 2021–2025   n   5  lost -0.01 (-0.02 to +0.00) of 0.1 | water -7.1 (-1.0%) of 673
tomatoes over a dense pan, probes  Davis                  n  35  lost -3.92 (-8.54 to +0.04) of 13.3 | water +10.6 (+0.9%) of 1124  FAILS 1: not cut at Davis
tomatoes over a dense pan, probes  McAllister 1991–2020   n  30  lost -0.52 (-0.83 to -0.27) of 0.8 | water +0.8 (+0.2%) of 557
tomatoes over a dense pan, probes  McAllister 2021–2025   n   5  lost -0.18 (-0.34 to -0.05) of 0.5 | water +5.4 (+0.9%) of 569
lettuce, probes                    Davis                  n  35  lost +0.00 (+0.00 to +0.00) of 11.5 | water +0.0 (+0.0%) of 504
lettuce, probes                    McAllister 1991–2020   n  30  lost +0.00 (+0.00 to +0.00) of 0.3 | water +0.0 (+0.0%) of 252
lettuce, probes                    McAllister 2021–2025   n   5  lost +0.00 (+0.00 to +0.00) of 0.0 | water +0.0 (+0.0%) of 352

-> C is not chosen: the beds stay as built
```

C is not the default. It mended what sank the first: over the dense pan in McAllister's
last five summers it added 0.9% water, not 12%, and it cut the loss there as before. At
Davis it cut the mean loss of both tomato beds, by 2.3 mm a summer of 7.3 and 3.9 of 13.3,
but each interval reaches just past 0 (to +0.09 and +0.04 mm), and the rule asked for both
below. Timed so on hot days alone, it kept less of plain tomatoes' gain (2.3 mm to the
first's 3.8) and more of the dense pan's (3.9 to 2.3). Lettuce did not move, as it could
not. The sealed sites were not run, nothing having been chosen, and stay sealed. More draws
at Davis might narrow the intervals; run after seeing these, they would not be the test the
rules set, and would need rules of their own written first.

## The top third on a hot day, on more farms, 2026-10-19

The intervals at Davis ending just past 0, more farms were drawn: Davis 1991-2025, draws 2
and 3, never run before, the two tomato beds by probes, the bed as built against C (280
backtests, code 7a496bf). Judged on those draws alone, draw 1 having been seen. The rule,
written before they ran:

    C becomes the default for a sown crop if, on draws 2 and 3, at Davis it cuts both
    tomato beds' mean lost transpiration with the 90% interval below 0. (McAllister's
    rules it passed on draw 1; lettuce it cannot change.) If chosen: Yuma and Kearney,
    sealed, run once, the bed as built against C for the three crop beds by probes, and C
    undone if at either it raises a bed's mean lost transpiration with the interval above 0.

```
tomatoes, probes, Davis, draws 2-3                   n  70  lost -2.13 (-3.29 to -1.17) of 7.3 | water -5.7 (-0.5%) of 1151
tomatoes over a dense pan, probes, Davis, draws 2-3  n  70  lost -5.17 (-6.91 to -3.59) of 13.6 | water -6.3 (-0.6%) of 1135

-> C is chosen: run Yuma and Kearney once for the crop beds
```

C is chosen: on the new farms it cut plain tomatoes' loss by 2.1 mm a summer and the dense
pan's by 5.2, both intervals well below 0, for a little less water.

## Learning held within 0.05, for lawns, 2026-10-19

The open sites' trial found learning held within 0.05 of the configured field capacity cut
the lawn's loss at Davis by 15 mm. That is why it was a candidate, so the open sites could
not decide it. Candidate L: `learn_within` 0.05 the default for a lawn ("lawn, its probe",
"yard, its probes"), crops unchanged. The rule, written before the runs:

    (a) Yuma and Kearney, sealed, run once for the two lawn beds: as built against L.
    (b) A survey badly wrong, new runs at the open sites: each lawn bed's configured field
        capacity 0.06 above and 0.06 below its soil's, learning free against L.

    L becomes the default for lawns if (a) at each sealed site, for each lawn bed, it raises
    neither the mean lost transpiration with the 90% interval above 0 nor the mean water by
    more than a tenth, and at one site at least it cuts the lawn's mean lost with the
    interval below 0 or its mean water by a twentieth; and (b) with the survey 0.06 off
    either way, at either open site, it raises neither lawn bed's mean lost by more than
    2 mm nor its water by more than a tenth.

840 backtests, code 7a496bf:

```
(a) the sealed sites
  lawn, its probe, yuma                                n  35  lost -35.88 (-42.24 to -29.47) of 114.7 | water +51.2 (+9.1%) of 566
  yard, its probes, yuma                               n  35  lost -0.85 (-1.64 to -0.24) of 52.3 | water +1.6 (+0.2%) of 694
  lawn, its probe, kearney                             n  35  lost -0.01 (-0.02 to +0.00) of 3.0 | water +0.3 (+0.1%) of 289
  yard, its probes, kearney                            n  35  lost +0.49 (-0.19 to +1.36) of 5.4 | water -2.7 (-0.8%) of 361
(b) the survey 0.06 off
  lawn, its probe, mcallister, survey +0.06            n  35  lost -0.01 (-0.02 to -0.00) of 0.0 | water +10.3 (+5.6%) of 185
  yard, its probes, mcallister, survey +0.06           n  35  lost -0.01 (-0.03 to +0.01) of 0.4 | water +8.9 (+3.1%) of 284
  lawn, its probe, davis, survey +0.06                 n  35  lost -14.67 (-20.18 to -10.03) of 19.9 | water +49.7 (+8.6%) of 579
  yard, its probes, davis, survey +0.06                n  35  lost -1.74 (-3.26 to -0.61) of 7.2 | water +6.8 (+1.1%) of 645
  lawn, its probe, mcallister, survey -0.06            n  35  lost +0.30 (+0.08 to +0.57) of 0.5 | water -26.5 (-17.2%) of 155
  yard, its probes, mcallister, survey -0.06           n  35  lost +5.38 (+3.42 to +7.51) of 6.1 | water -65.2 (-28.4%) of 229  FAILS lost up over 2 mm
  lawn, its probe, davis, survey -0.06                 n  35  lost -1.48 (-2.70 to -0.36) of 127.5 | water +1.8 (+0.4%) of 429
  yard, its probes, davis, survey -0.06                n  35  lost +2.33 (+0.10 to +5.24) of 97.7 | water -2.8 (-0.5%) of 517  FAILS lost up over 2 mm

-> L is not chosen: lawns stay as built
```

L is not the default. At the sealed sites it did what the open ones said: it cut Yuma's
lawn's loss by 36 mm a summer of 115, for 9% more water, and changed little at Kearney. It
failed where it was feared to. With the survey 0.06 too low, held near that wrong value,
the yard lost 5.4 mm more at McAllister and 2.3 more at Davis, past the 2 mm allowed: held,
it gave the yard 28% less water at McAllister than learning free did. With the survey too
high, holding helped. A farm whose survey
it trusts may set it; fieldmesh cannot know whose is right. Yuma and Kearney are now spent
for the lawn beds, not for the crops.

