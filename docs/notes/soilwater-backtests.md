<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# The soil-moisture advisory's backtests, 2026-10-11 to 2026-10-17

*The record of what the [soil-moisture advisory](../../modules/soilwater/README.md) was
tried on, on the virtual farm as each day had it, and what each try showed: the tables
that once stood in its README, kept here as they were last written. The README holds what
the advisory does now and the evidence for it as it is now, from `trials.py`; this keeps
how it got there.*

*Read each table with its date. The simulator changed under them: on 2026-10-15 its soil
began to move water below field capacity; on 2026-10-16 its crop began to use its water as
FAO-56's does, from the top of its roots, and its bare soil to dry; on 2026-10-17 its crop
began to slow by the water near its roots. And the advice changed with what they showed.
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
