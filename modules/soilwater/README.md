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
| **untrusted** | the newest readings failed the health checks, or read drier than the bed's soil can be ([below](#a-probe-out-of-the-soil)) |
| **by the weather**: water now, rain coming, enough, or the station unseen | the bed has no probe, or its probes have gone silent or untrusted, and the farm's station is given ([below](#by-the-weather-with-no-probe)) |
| **out of the soil**, beside the morning's advice | a probe reads drier than its soil can be, and the advice came from the bed's other probes or the weather ([below](#a-probe-out-of-the-soil)) |
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

**Each simulated probe draws its own noise** (`noise_streams`, since 2026-10-14). Before,
all of a backtest's probes drew from one stream, so a run with a probe more or less, or with
one probe silent for a while, read different noise on the probes it shared with another, and
two runs set side by side differed by more than the probe. Now each draws from its own; the
first keeps the seed's, so a run with one probe reads exactly as before, to the last bit. The
tables here with more than one probe were made with the shared stream; those re-measured on
the new streams say so.

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
(`crop_day`), with the 2025 revision's values (FAO-56 Rev.1,
[data/fao56rev-crops.csv](data/fao56rev-crops.csv)) and the 1998 edition's stage days
([data/fao56-crops.csv](data/fao56-crops.csv)):

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
| 1998's 0.95 | 0.95 (`turf_cool`) | 262 mm, 0, 0 | 288 mm, 1, 12 |
| 1998's 0.95 | 0.70 (`turf_lawn`) | 164 mm, **10, 165** | 185 mm, **7, 87** |
| the revision's 0.70 | 0.95 | 262 mm, 0, 0 (93 mm more drained) | 288 mm, 0, 0 (95 mm more drained) |
| the revision's 0.70 | 0.70 | 164 mm, 0, 0 | 185 mm, 0, 0 |

So `turf_cool` stays the default: told 0.95, a lawn is never short whichever is true, at
the cost of drained water if the revision is right; told 0.70, it saves a third if the
revision is right and is short in a third of summers if it is not. By a probe the value
makes no difference at all, to the millimetre: the probe measures what the lawn used. A
lawn with a probed bed nearby as its reference learns its own rate (`Bed.reference`,
[below](#a-probe-nearby-corrects-the-balance)), which is how to find out, lawn by lawn.
A lawn led by one probe at 7 cm was itself short in 13 summers of 30 (255 hours) where
the same lawn by the weather never was: a shallow root zone's trouble, not the
coefficient's ([UNTESTED](../../docs/UNTESTED.md)).

The day's root depth sets the root zone the probes are weighed over and the water it
holds, and the day's coefficient drives the weather balance; an established lawn
(`turf_cool`, `turf_warm`) holds its mid-season values all year. A probe below a
seedling's roots counts for nothing until the roots reach it: ten days after sowing,
tomatoes' 15 cm of roots do not reach a probe at 20 cm. **Nor does a probe at the root
zone's very bottom** count (`weights`): it reads the soil the roots are only reaching,
half of it below them. With tomatoes' roots at their deepest, 60 cm, a probe at 60 cm
counted as a quarter of the root zone left them short in 13 summers of 30 for 1,303
hours; left out until the roots are past it, in 3 for 91.

The revision's depletion fractions are in the file; the advice keeps a third, lower than
its tables as it says suits frequent watering, and with `Bed.adjust_p` lowers it on a
hot day as the revision's Eq. 8.5 does ([below](#hot-days-and-beds-under-cover)).

**Backtested** on McAllister Farm's thirty summers, sown on 1 May, the virtual crop
growing by the same curve in the 1998 days, in a silt loam 1.5 m deep, probes at 10 and
30 cm. "Not known" is the bed as it was before: 30 cm of roots and a coefficient of 1 all
season.

| | water, mean a season | summers short | hours short, in all | worst season |
| --- | --- | --- | --- | --- |
| tomatoes by the weather, crop not known | 360 mm | 0 | 0 | 0 |
| **tomatoes by the weather, crop known** | **302 mm** | **0** | **0** | **0** |
| tomatoes by probes, crop not known | 205 mm | 5 | 382 | 150 h |
| **tomatoes by probes, crop known** | **262 mm** | **3** | **178** | **143 h** |
| **the same, with a third probe at 60 cm** | **257 mm** | **3** | **91** | **44 h** |
| lettuce by the weather, crop not known | 159 mm | 0 | 0 | 0 |
| **lettuce by the weather, crop known** | **149 mm** | **0** | **0** | **0** |
| lettuce by probes, crop not known | 191 mm | 0 | 0 | 0 |
| **lettuce by probes, crop known** | **144 mm** | **0** | **0** | **0** |

* **By the weather**, a crop not known is charged a full canopy's water from sowing: it
  was given a fifth more than it needed (360 mm against 302 for tomatoes), drained below
  the roots.
* **By probes, a crop not known** is advised for 30 cm of roots, and its probe at 30 cm,
  at that root zone's bottom, does not count: only the one at 10 cm does. For lettuce,
  whose roots never pass 30 cm, that is close to right, though it waters a third more
  than knowing the crop; for tomatoes, whose roots draw down to 60 cm, it waits too long
  and refills too little.
* **Knowing the crop**, tomatoes were short in 3 summers; a third probe at 60 cm, in the
  deeper half of their roots, halved the hours and cut the worst season from 143 to 44.

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
| tomatoes, the advice on the calendar | 302 mm | 0 | |
| **tomatoes, the advice by warmth** | **301 mm** | **0** | −18% (2009) to +13% (2014) |
| lettuce, the advice on the calendar | 149 mm | 0 | |
| **lettuce, the advice by warmth** | **149 mm** | **0** | −17% (1995) to +11% (1991) |

On average it changes nothing; in a single year it moves the water by up to a sixth
either way, toward what the virtual crop used. The calendar's advice was never short
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

| | water, mean a season | tomatoes' summers short | the lettuce's summers short | the lettuce's hours short |
| --- | --- | --- | --- | --- |
| by the weather, told the tomatoes alone | 302 mm | 0 | 9 | 204 |
| **by the weather, told both** | **333 mm** | **0** | **0** | **0** |
| probes at 10, 30 and 60 cm among the tomatoes, told the tomatoes alone | 257 mm | 3 | 30 | 2,960 |
| the same, told both | 255 mm | 0 | 29 | 1,771 |
| the one at 10 cm moved among the lettuce, told both | 478 mm | 0 | 1 | 14 |
| a fourth at 10 cm among the lettuce, told both | 340 mm | 0 | 5 | 70 |
| **the same, each probe named for its planting** | **347 mm** | **0** | **2** | **17** |

* **By the weather**, the advice for the tomatoes alone waited for their 60 cm of roots and
  left the lettuce's 15 short in nearly a third of the summers. Told both, it waters on
  the lettuce's account and is never short, for a tenth more water.
* **By probes, they must see the young roots' soil.** Among the tomatoes they read soil
  the tomatoes are drying, slower than the lettuce's, and the lettuce is short most
  summers whatever the advice is told. Moved among the lettuce, the shallow probe keeps it
  watered, but the tomatoes' top 20 cm is then read by the lettuce's probe: every
  watering for the lettuce brings the tomatoes' root zone back to field capacity, for
  nearly twice the water, much of it drained.
* **A probe for each, named for its planting, does both**: the lettuce short twice in
  thirty summers for 17 hours, the tomatoes never, for 2% more water than the same four
  probes unnamed, whose two at 10 cm are averaged and hide the lettuce's dry soil. Two
  plantings this far apart in age are still better on two valves.

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
taking them to 60 cm. A real soil's water also creeps up to drier soil above it, which the
simulator's does not unless asked (`unsaturated_mm_per_h`, here 0.01 mm an hour): then
the probe under the pan dries a little too, as a real one would.

| | water, mean a season | summers short | hours short, in all | worst season |
| --- | --- | --- | --- | --- |
| *the pan:* the crop's curve alone | 197 mm | 30 | 8,116 | 677 h |
| **the curve and root signs, by field capacity** | **309 mm** | **2** | **50** | **38 h** |
| the curve and root signs, by the stair-step | 308 mm | 2 | 50 | 38 h |
| **the rooting limit set at 30 cm** | **311 mm** | **0** | **0** | **0** |
| *the pan, water creeping up:* the crop's curve alone | 306 mm | 21 | 705 | 85 h |
| **the curve and root signs, by field capacity** | **340 mm** | **0** | **0** | **0** |
| the curve and root signs, by the stair-step | 338 mm | 0 | 0 | 0 |
| **the rooting limit set at 30 cm** | **313 mm** | **0** | **0** | **0** |
| *no pan:* the curve and root signs, by field capacity | 257 mm | 3 | 91 | 44 h |
| the curve and root signs, by the stair-step | 255 mm | 2 | 77 | 44 h |
| *no pan, water creeping up:* by field capacity | 253 mm | 2 | 54 | 38 h |
| by the stair-step | 257 mm | 1 | 38 | 38 h |

* **The curve alone starves a crop on a pan.** It counts 60 cm of roots, and the probe at
  30 cm, which no root reaches, holds the bed's average up. It was short every summer,
  for eleven days on average.
* **Root signs find the pan unaided**, once the curve is 15 cm past the probe at 30 cm;
  they did on about 85 of a season's 145 mornings, and cut the hours short by more than
  99%. The water they give is the rooting limit's.
* **The two tests did as well as each other.** With the 1998 curve, roots to 70 cm, water
  creeping up from below the pan fooled the test by field capacity, 507 hours short
  against the stair-step's 130. With the revision's 60 cm both found the pan.
* **Without a pan the signs cost the crop nothing**: the hours short are the crop's own,
  as with no signs at all, and the water the same. But the stair-step saw a stop that
  was not there on about 15 mornings a season, the test by field capacity on 3 or 4,
  through the simulator's noisy probes (0.01 a reading), where a slow drinker's steps are
  hard to see. A stop seen wrongly only times the watering, but its note asks the farmer
  to set a rooting limit, which would cut the deep roots' refills. **So the test by field
  capacity is the default**, and the stair-step an option.
* **The limit set by hand is best.** A first version still counted the probe at 30 cm, set
  into the pan; leaving it out, and now any probe at the roots' front, fixed it.

## Hot days, and beds under cover

**On a hot day.** FAO-56 adjusts the depletion fraction for how fast a crop is drying
(the 2025 revision's Eq. 8.5): `p + 0.04 (5 − ETc)`, ETc in mm a day. With
`Bed.adjust_p`, the advice lowers its third that way on a day drying faster than 5 mm,
from the probes' drying rate or, by the weather, the day's Kc · ETo, so the crop is
watered with more water left. FAO-56 also raises p on a mild day; that is not done here.
On the thirty summers:

| | water, mean a summer | summers short | hours short, in all | worst summer |
| --- | --- | --- | --- | --- |
| the backtest bed | 189 mm | 3 | 72 | 40 h |
| **the backtest bed, `adjust_p`** | **195 mm** | **2** | **33** | **20 h** |
| the backtest bed, Eq. 8.5 both ways | 179 mm | 7 | 102 | 29 h |
| the shallow yard, each layer's values | 202 mm | 8 | 141 | 35 h |
| the shallow yard, `adjust_p` | 202 mm | 8 | 141 | 35 h |
| the shallow yard, Eq. 8.5 both ways | 201 mm | 7 | 111 | 35 h |

On the backtest bed it halved the hours short for 3% more water; on the shallow yard it
changed nothing, the look-ahead ([above](#the-beds-own-soil)) already watering it a day
early on those days. Raising p on mild days too, as FAO-56 does, saved water on the
backtest bed and left it short in more summers.

**Whether to make it the default** was tried across the backtests above, each run again
with it on (thirty summers each; water, summers short, hours short):

| | off | `adjust_p` |
| --- | --- | --- |
| tomatoes by probes at 10 and 30 cm | 262 mm, 3, 178 | 354 mm, 0, 0 |
| tomatoes by probes at 10, 30 and 60 cm | 257 mm, 3, 91 | 329 mm, 1, 13 |
| lettuce among tomatoes, probes among the tomatoes: the lettuce | 255 mm, 29, 1,771 | 330 mm, 8, 311 |
| lettuce among tomatoes, a probe named for each | 347 mm, 2, 17 | 375 mm, 2, 17 |
| tomatoes over a pan at 30 cm, root signs | 309 mm, 2, 50 | 383 mm, 2, 50 |
| the same, water creeping up below the pan | 340 mm, 0, 0 | 422 mm, 0, 0 |
| the backtest bed under a tunnel, told | 376 mm, 3, 45 | 381 mm, 0, 0 |
| lettuce by probes at 10 and 30 cm | 144 mm, 0, 0 | 154 mm, 0, 0 |
| tomatoes or lettuce by the weather | 302 and 149 mm, 0, 0 | 303 and 150 mm, 0, 0 |
| a lawn, by its probe or by the weather | the same | the same |

It only acts where the crop draws well over 5 mm a day, which on this farm is tomatoes at
mid-season; a lawn seldom does. There it ends most shortages, but at a quarter to a third
more water, most of it drained, and costs that even where nothing was short: over a pan,
a quarter more water for the same hours. **So it stays off by default**: a bed whose
probes show it running short in hot spells can be given it.

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
| not told it is covered | 375 mm | 6 | 91 | 98 |
| covered, learned from the probes | 376 mm | 5 | 65 | 68 |
| **told it is covered** | **376 mm** | **3** | **45** | **0** |
| *in the open*, the gauge and the learning on | 189 mm | 3 | 72 | 29 |

Told, it was never held for rain that could not reach it. Learning took the first part
of each summer to see three storms, and held it on a third fewer mornings. In the open
the learning never took the bed for covered: the water and the hours short are the
open bed's without it.

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
LSE01 reading 2.1 to 2.4% ([notes/test-data-sources](../../docs/notes/test-data-sources.md)):
out of the soil in a loam, possible in a dry sand, and its keeper has not said which.
Not built: the other sign, a probe that rises after neither the rain the gauge recorded nor
the watering the valve did, which would catch it in sand too.

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
  sensor beside the probe could read it off the retention curve at 1500 kPa, which needs
  one that reads past 1000 kPa (a TEROS 21, not a Watermark) and a bed let dry that far;
* a safe run length learned from the bed: comparing short runs with long ones, as a valve
  reports them, cycle-and-soak worked out from the bed itself;
* a share of the rain between none and all, learned (a covered bed is: above);
* the degree-days of the ten crops the 2025 revision gives only approximate ranges for
  (its Table 6.12), in place of the 1998 days taken at the farm's normal year;
* which lawn coefficient is right for a real lawn, 1998's or the revision's
  (`turf_lawn`): a lawn's own rate, learned from a probed bed nearby, would say;
* why a lawn led by one probe at 7 cm was short in 13 summers of 30 where the weather's
  advice for it never was;
* a check for a probe out of the ground: openSenseMap's LSE01 reading 2% soil water passes
  every check there is ([test data sources](../../docs/notes/test-data-sources.md)).
