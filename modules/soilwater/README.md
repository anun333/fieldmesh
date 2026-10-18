<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/soilwater/` — soil-moisture advisory (layer 2)

The second layer-2 module (spec v0.1 §11), and Q12's other read-only choice: every
morning, and again early in the afternoon, for every bed, what to do about water — and
when it cannot say, why not. A
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

**Two looks a day.** The advice is given at 04:00, before the morning's watering, and again
at 13:00 (`SECOND_CHECK_HOUR`; [deploy/systemd/](../../deploy/systemd/) runs the module at
both). A bed with little water to spare, a lawn or a shallow topsoil over clay, can be past
half of it by the afternoon of a hot day; the second look waters it then rather than the
next morning. The afternoon's look counts the morning's watering, recorded or advised, so it
never asks for the same water twice.

**Only readings that had passed the health checks by that morning count**
(`State.quality_as_of`), so a stuck or drifting probe never waters a bed, and a silent one
is dropped rather than averaged in. Rain coming is read from a forecast datastream in the
log (Q26), so the forecast an advice rested on sits beside it.

## Backtested

§11 asks for it before anything goes live. The advisory is backtested on a virtual farm
([sim/physics.py](../../sim/physics.py)): a bed's soil in layers that drain, soak up water
and pass it between them by Darcy's law; a crop that grows through FAO-56's curve, uses its
water whole until its own `p` and draws it most from the top of its roots; bare soil that
dries in the sun; probes read through the same health checks a farm's are. The harness is
[backtest.py](backtest.py), `backtest` with probes and `weather_backtest` by the weather,
kept apart from the advisory, which never imports the simulator. How the virtual farm's
soil and crop compare with the models agriculture uses, and how they were checked against
HYDRUS-1D and a real station's probes, is in [soil models](../../docs/notes/soil-models.md).

**Scored by** the water given and what drained past the roots; the hours the bed had lost
half its available water; and, since 2026-10-17, the transpiration its dryness cost the
crop (FAO-33's measure of lost yield), the hours it used less than its full demand, and the
hours its root zone held less than a tenth air, overwatering's harm (`backtest.Score`).

**On the farm as it is written** (`backtest.NOMINAL`): McAllister Farm's recorded summer of
2013, June to August, a 30 cm root zone in a silt loam, the drill's forecasts in the log,
the advisory followed to the letter, beside the drip timer most farms run
([sim/irrigation_drill.py](../../sim/irrigation_drill.py)):

| | water applied | drained past the roots | hours stressed ≥ 0.5 | mean stress |
| --- | --- | --- | --- | --- |
| drip timer, every second morning | 552 mm | 580 mm | 0 | 0.06 |
| timer, skipping when rain is forecast | 444 mm | 472 mm | 0 | 0.06 |
| **the advisory** | **208 mm** | **235 mm** | **0** | **0.12** |

62% less water and 59% less drained, with no hour of real stress. The cost is a drier root
zone on average, which is the trade a refill point makes, and the reason `p` is the crop's
to set. The tests run this and a dozen other single summers once each (`BACKTESTS` in
test_soilwater.py), say what must stay true of them, and hold their exact figures in
[golden.json](golden.json): a change that moves one shows there.

**On a farm that departs from what the advice is told** (`backtest.VirtualFarm`): its crop
using more or less than its curve, running early or late, rooting deeper or shallower; its
soil's limits off; each probe off by its own calibration error; its water loss
Penman–Monteith with the day's own wind, where the farm's station assumes 2 m/s. The
advisory's defaults were tried so in [trials.py](trials.py), on McAllister's summers and on
Davis, California's, dry and windier, each on two farms drawn for it
([below](#what-the-trials-show)). How each table here came to be, and the advice changed
for what it showed, from 2026-10-11, is in
[the backtests' record](../../docs/notes/soilwater-backtests.md).

## What the trials show

The advisory's defaults were tried by [trials.py](trials.py) on a virtual farm that departs
from what the advice is told (`backtest.VirtualFarm`): ten beds, each with the choices that
bear on it, through McAllister Farm's recorded summers of 1991 to 2025 and those of Davis,
California, dry and windier, each summer on two farms drawn for it, 5,320 backtests
(code 4475640, 2026-10-17). The defaults were chosen on McAllister's 1991 to 2020
("tuned"); McAllister's 2021 to 2025 and all of Davis's are "held out", nearly all of them
Davis. Water and lost transpiration are the mean a summer, the transpiration being what
the crop could not draw for want of water. Each bed as built:

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

* **Held out, in a dry summer, the probes lose more than the weather.** By the weather, with
  its margin, the beds lost 3 to 10 mm of transpiration a summer held out; by probes, the
  crops and the lawn 14 to 75, though the backtest bed, one bucket, only 1. Learning reads
  a hot, dry soil's field capacity low: in one Davis summer checked, the lawn's probe
  learned 0.21 from 14 drain-downs where its soil holds what that probe would read as 0.28,
  each watering spreading on into drier soil below as the grass drew hard, and watered back
  only to 0.21 the lawn lost 37 mm. A soak test ([below](#a-soak-test-field-capacity-on-the-day)),
  wetting the root zone well past field capacity on purpose, may read it better; it has not
  been tried on the simulator.
* **The weather's margin earns its keep where it was not tuned.** Without it the beds
  were given 36 to 130 mm a summer less and, held out, lost 6 to 53 mm more transpiration;
  at a tenth, half the saving for a fifth to a third of the loss. On the summers it was
  chosen on, going without it lost them almost nothing.
* **A young crop's refill point held by its roots** kept lettuce by probes from losing 1.3
  mm a summer (tuned) and 5.7 (held out) that the initial stage alone lost; for tomatoes it
  made little difference.
* **The root signs earn their place**, by timing the watering by the soil above a stop
  they may or may not have found: without them, tomatoes over a dense pan lost 6 and 36 mm
  more, and tomatoes by probes with no pan 0.6 and 4.2.
* **A shallow bed watered at a fifth gone** (`Bed.depletion_fraction` 0.2) kept the lawn
  by its probe from 57 mm of the 75 it lost at Davis, and the yard from 15 of its 22, for 20
  to 90 mm more water; at McAllister it bought next to nothing for 30 to 105 mm, and the
  lawns hundreds of hours of a root zone short of air. It is a setting for a shallow bed in
  a dry, hot place, not a default.

Every choice against its default, the difference's mean and its 90% interval, is in
[the backtests' record](../../docs/notes/soilwater-backtests.md#the-trials-of-2026-10-17).

## The bed's own soil

A soil survey maps the native soil. A landscaped yard, a raised bed or a market garden
on an old house lot is often something else: topsoil brought in over a subsoil the builders
compacted, sod with its own soil over the yard's, a compost mix over the ground. Set up
with the survey's values, the advisory misjudges such a bed. So each probe **learns its own
field capacity from its own drain-downs** (`learned_capacity`):

* **A wetting** is the probe's reading, smoothed by a running median of three, rising
  0.04 or more within four hours.
* **A drain-down** runs from the wetting's peak to the next wetting, or 72 hours. It
  counts when it is at least 16 hours long with no gap over three hours.
* **Each drain-down is fitted** as water above field capacity draining away while the
  crop dries the soil steadily: `θ(t) = fc + a·exp(−t/τ) − r·t`, counting only from
  clearly above field capacity (`a ≥ 0.02`) and only drainage that can be told from the
  crop's drying (`SLOW_DRAIN_MIN_EXCESS`).
* **The probe's field capacity** is the upper quartile of the levels the last 60 days'
  drain-downs settled to, once there are three. On a soil that goes on moving water after
  it has drained, a light watering over drier soil spreads on down, and the sun dries the
  top: such drain-downs settle below the soil's field capacity, and their median read it
  low, enough to leave a lawn short in nearly every summer on the simulator.

Until then, and for a value within 0.03 of its soil's wilting point, the configured value
stands. `Bed(learn=False)` turns learning off. What it learns is the level the bed
actually holds a day or two after a soaking, the in-place sense of field capacity (Twarakavi,
Sakai and Šimůnek 2009, *Water Resources Research* 45,
[doi:10.1029/2009WR007944](https://doi.org/10.1029/2009WR007944)).

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

**Looking ahead to tomorrow.** The advice also waters a bed that, drying as it has been,
would pass `Bed.short_fraction` of its water (half) before the next look.

**A tension sensor beside a probe** measures field capacity instead of learning it. Each
hour the two at one depth give a point on the soil's own retention curve. Over the tensions
a Watermark is calibrated for, 10 to 75 kPa (`sdk/tension.py`), water falls close to
linearly with the logarithm of tension, so the points are fitted and field capacity read at
`Bed.capacity_kpa`, 33 kPa by default (`retention.py`). It needs 24 hours of points
spanning a factor of two in tension and reaching to within half again of 33, and no
soaking. A measured value stands before a learned one for that probe's slice; the decision
says which (`"how": "measured"`).

**What the backtests showed** ([record](../../docs/notes/soilwater-backtests.md#the-beds-own-soil)):
on the builder's yard, sandy loam over compacted clay, one probe in the topsoil on the
survey's values drowned it, and learning cut the water by three fifths; with a probe in
each layer, learning alone did not help, and each layer's values did. Learning leaves a
correctly set-up bed alone, to the millimetre. A probe that reads low is forgiven, since
its drain-downs read low too; one that reads high is not, since it is watered too little to
learn from, and a second probe in the bed is what catches it
([soil sensors](../../docs/notes/soil-sensors.md)).

## A crop that grows

A seedling draws little water from a few centimetres of soil; a full canopy draws more
than the reference grass, from deep. A bed told its crop and the day it was sown
(`Bed.crop`, `Bed.planted`) follows FAO-56's curve for that crop through its season
(`crop_day`), with the 2025 revision's values (FAO-56 Rev.1,
[data/fao56rev-crops.csv](data/fao56rev-crops.csv)) and the 1998 edition's stage days
([data/fao56-crops.csv](data/fao56-crops.csv)):

* **its crop coefficient** by stage (the revision's Tables 6.1 and 6.2), and by the
  weather FAO-56's dual coefficient, the crop's basal coefficient and its wet soil's
  evaporation apart (`basal_day`);
* **its roots** from 15 cm at sowing to the shallow end of the revision's range of maximum
  depth as mid-season begins, growing in a line over the development stage;
* **its own `p`**, the share of its water it uses freely, for the weather's balance; the
  advice waters sooner, at a third gone;
* **its stages** in the revision's degree-days for the 10 crops it has them for
  ([below](#by-the-seasons-warmth)); otherwise the 1998 edition's days.

**A young crop is watered at a fifth of its water gone** (`Bed.young_fraction`) through its
initial stage and until its roots pass 25 cm (`YOUNG_ROOTS_MM`), its few roots in the soil
the sun dries. Among older plantings, that is the refill point of the young one's roots
alone. Without the root depth, the crops' shortages by probes fell in the days just after
the initial stage ended, the roots still the 15 cm they were sown with.

**Lawns: the 1998 values by default, and the revision's as `turf_lawn`.** The revision
gives a mown lawn 0.50 to 0.70 through its season (Table 6.4), against the 1998 edition's
0.95 for cool-season turf; `turf_lawn` holds its 0.70 all year. By a probe the value makes
no difference; by the weather, a lawn told 0.70 that truly uses 0.95 went short in nearly
every summer on a sandy yard, so `turf_cool` stays the default. A lawn with a probed bed
nearby as its reference can learn that its rate is faster still ([below](#a-probe-nearby-corrects-the-balance)).

The day's root depth sets the root zone the probes are weighed over and the water it holds.
A probe below a seedling's roots counts for nothing until the roots reach it, **nor does a
probe at the root zone's very bottom** (`weights`): it reads the soil the roots are only
reaching.

**What the backtests showed** ([record](../../docs/notes/soilwater-backtests.md#a-crop-that-grows)):
not knowing the crop costs it, by the weather and by probes; knowing it, by the weather
neither tomatoes nor lettuce was short in any summer of thirty on the farm as written.

### By the season's warmth

The 1998 edition's stages are days, for a typical season; a warm year runs a crop through
them sooner and a cool one later. Given the farm's station, the advisory times them by
growing degree-days instead (`thermal.py`, `Advisor.clocked`), each crop's base and upper
thresholds from the revision's Table 6.10: for the 10 crops with field-observed degree-days
(its Table 6.11) each stage ends when they are gathered; for the other ten the 1998 days are
taken as right for the farm's normal year (`climate` in the config). Each decision says
how far through its curve the crop is (`crop_gdd`, or `crop_days`) beside the calendar. On
the thirty summers it moved a single season's water by up to an eighth, toward what the
virtual crop used, and left no crop short either way.

### Plantings at different stages

A bed often holds plants at different stages side by side: a succession, a replant in a
gap, lettuce under tomatoes. A bed can name each (`Bed.plantings`), each on its own clock:

* **When to water is set by the youngest roots**, the soil as deep as the shallowest
  planting's roots having used its share of its water.
* **How much is set by the oldest**: the refill brings the soil back to field capacity
  down to the deepest roots, so watering on the young plants' account never shorts the
  old ones.
* **A planting can name the probes set among it** (`(crop, planted, (sensor id, …))`): the
  youngest planting's own probes then time the watering, and count for nothing until it
  is sown.

> Water tunnel bed 3 today: its shallowest roots, in the top 15 cm, have used 39% of the
> water they can reach. About 20 mm brings the bed back to field capacity, down to its
> deepest roots at 50 cm.

**What the backtests showed** ([record](../../docs/notes/soilwater-backtests.md#plantings-at-different-stages)):
told the tomatoes alone, lettuce sown among them went short in most summers, by the
weather and by probes; told both, by the weather never. Two plantings this far apart in age
are still better on two valves.

### Roots that stop

The crop's curve is for a soil that lets roots go. A hardpan, compacted fill, rock or a
raised bed's floor can stop them sooner, and advice that follows the curve then counts
water the roots cannot reach. How deep roots run, and what shows it, is in
[the root-depth note](../../docs/notes/root-depth.md). Two ways to give the advice the
right depth:

* **`Bed.rooting_limit_mm`**, set by hand once the farmer has dug and found the pan. The
  crop's curve stops at it, and a probe at or below it is not counted.
* **Root signs from the probes** (`root_signs`, `rooted`), over the last two weeks. A
  probe's dry days are those that started no wetter than its field capacity, with nothing
  wetting it. A probe whose soil fell less than 0.002 a day over three or more of them is
  **level**; one that went 0.02 under field capacity **has roots**. A level probe that the
  curve says the roots passed at least 15 cm ago, under one with roots, likely marks a
  stop, and a note says so; the watering is then timed by the soil above, the refill still
  measured to the curve's depth.

**What the backtests showed** ([record](../../docs/notes/soilwater-backtests.md#roots-that-stop)):
over a pan that passes water slowly, the rooting limit set by hand left the crop short least,
on less water. With roots densest at the top, as on the simulator since 2026-10-16, a probe
at 30 cm is drawn on lightly and reads near level with no pan at all, and the root signs
see a stop on about half of a season's mornings with or without one; whether they are
worth their place is not known ([UNTESTED](../../docs/UNTESTED.md)).

## Hot days, and beds under cover

**On a hot day** the refill point stays where it is: FAO-56's lower `p` for a bed drying
faster than 5 mm a day (Rev.1 Eq. 8.5) was an option until 2026-10-17, and on the simulator
it ended no shortage, which fell before mid-season, for half again the water
([record](../../docs/notes/soilwater-backtests.md#hot-days-and-beds-under-cover)).

**A bed under cover.** Rain forecast for the farm does not reach a bed under a tunnel or
a roof, and "rain is coming: wait" is the wrong advice for it. `Bed.rain_share` says how
much of the rain reaches the bed, 0 under cover; the forecast that holds a watering, and
the weather balance's rain, are scaled by it (`rain_reaching_mm`). Left unset, it is all
of the rain, unless the bed's probes show it covered: through the last three storms of
15 mm or more in the farm's rain gauge that fell while its valve stayed shut, none moved a
probe in its root zone by 0.03 within 12 hours of the rain's end (`covered_by_its_probes`).
Only a bed whose valve reports its waterings is judged. Told, a covered bed was never held
for rain that could not reach it; learning took the first part of each summer to see three
storms; an open bed was never taken for covered.

## Water below field capacity

The virtual farm's soil moves water below field capacity, since 2026-10-15: each horizon
holds its water along van Genuchten's curve, fitted through its own saturation, field
capacity at 33 kPa and wilting point at 1500 kPa with Rosetta3's residual water, and passes
it by Darcy's law at Mualem's conductivity (`physics.Horizon`). Water held near capacity at
the top reaches the bottom of the roots on its own, and water below the roots rises to
them. Checked against HYDRUS-1D on the same soils ([soil models](../../docs/notes/soil-models.md#what-the-simulator-took-2026-10-16)).
Before it, the soil moved no water below field capacity, and several early results were
that soil's ([record](../../docs/notes/soilwater-backtests.md#water-below-field-capacity)).

## The crop's water use and the soil's surface

The virtual farm's crop, since 2026-10-16: it uses its whole demand until it has used its
own `p` of its water, then less in a line to the wilting point (FAO-56's `Ks`), layer by
layer, weighed by its roots, densest at the top (Prasad 1988), since 2026-10-17; the top
10 cm of its soil evaporates apart from it by FAO-56's dual coefficient, a mown lawn
covering 0.95 of its ground. At USCRN's Crossville station it dried a soil under grass at
0.74 to 1.26 of the rate the probes saw at 5 to 20 cm
([soil models](../../docs/notes/soil-models.md#what-the-simulator-took-2026-10-16)). Every
crop takes about twice the water it did on the crop before, which slowed as soon as its soil
was below field capacity; what that showed, and the advice changed for it, is in
[the record](../../docs/notes/soilwater-backtests.md#the-crops-water-use-and-the-soils-surface).

## By the weather, with no probe

A bed with no probe, given the farm's own station (`eto.Station`: its site and the series
it keeps), is advised by FAO-56's daily root-zone balance instead (`weather_balance`):

* **Each day's reference ET** is FAO-56 Penman–Monteith from the station's readings that
  the checks passed (`sdk/eto.py`, which reproduces FAO-56's Example 18: 3.88 mm). Missing
  sunshine, humidity or wind are replaced by FAO-56's own stand-ins, and each decision
  lists which it used.
* **The balance**: each day the depletion falls by the gauge's rain and the watering, and
  rises by the crop's use, `Ks · Kc · ETo`, `Ks` slowing the crop once it has used its own
  `p`; for a bed whose crop is named, `(Ks Kcb + Ke) ETo`, FAO-56's dual coefficient.
* **A margin**: with nothing measured, the crop's use is counted a fifth above FAO-56's
  estimate (`WEATHER_MARGIN`). The estimate is not the bed: the station's reference ET and
  the crop's coefficient can each be a tenth or more out, and a balance that counts low
  waters late and short, its shortfall adding up until rain, since each watering refills
  only what it counted. Counted high, it waters a little early and a little over, and the
  excess drains.
* **Watering is the valve's recorded minutes** times the bed's `application_mm_per_h`.
  Without that record, the advisory's own advice to water is taken as followed, and the
  advice says so.
* **Two of the last three days without a full day of weather**, and it says it cannot
  tell, rather than guess.

> Water bed 3 today, by the farm's weather: about 50% of the water its plants can use is
> gone, with no probe to confirm it. About 27 mm brings it back to field capacity.

**When a bed's probes go silent or untrusted**, it is carried on the weather from their
last good readings, the mean of each probe's good ones in the three hours before it fell
silent (`ANCHOR_HOURS`), for up to sixty days, and every advice says to check the probes:

> bed 3's probes have given no reading to trust for 81 hours. By the farm's weather since
> their last good one, about 55% of the water its plants can use is gone: water it today,
> about 30 mm. And check the probes.

**What the backtests showed** ([record](../../docs/notes/soilwater-backtests.md#by-the-weather-with-no-probe)):
on the farm as written, whose crop used about a fifth more than the balance counted, the
bed with no margin was short in 21 summers of 30, and with the fifth, in none; where the
balance was not low, the margin cost a sixth to a quarter more water. Through the 2012
drought with its probe silent for two weeks, the bed carried on the weather was never short.

### A probe nearby corrects the balance

A probe lends the balance only what carries from bed to bed: **its rate, not its level**. A
bed with no probe can name a bed nearby, of the same crop on the same station, as its
`reference`. Each morning `reference_factor` reads that bed's probes over the last 30 days,
on the days with no rain on the gauge, no watering, a start no wetter than field capacity
and less than the readily available water gone: how much the water missing below field
capacity grew, midnight to midnight, against the balance's `Kc · ETo`. The ratio corrects
the bed's crop coefficient all the way when the probe sees it drying faster, half way when
slower, because more water is the safe error, and **never below the margin**: a rate read
truly does not make a balance stepped once a day safe on its own. It is not used with
fewer than five such days, until every probe in the reference has learned its own field
capacity, or outside 0.5 to 1.5. The same rate, read from a bed's own probes before they
fell silent, carries the fallback above.

> bed 3 is due water by the farm's weather, with its water use set at 125% of the weather's
> estimate from a probe in a bed nearby: about 19 mm. Its watering is not recorded, so this
> takes the last advice to water as followed; if it was not, it needs more.

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

Read-only like everything here: it asks a person, and checks what the probes saw.

## Did the water arrive?

The first **regimen** (Q10; [modules/rules](../rules/README.md#regimens)):
[regimens/watering_check.star](regimens/watering_check.star), a few lines of Starlark. When
the advice is "water today", it waits for the watering to happen and soak in, then checks
that the root zone rose by at least half of what that watering should add. If not, it says
so, and says both things a probe cannot tell apart:

> bed 3's probes show almost no new water since this morning: the root zone rose 0.4
> points, where 18 mm of watering should add about 6.0. If it was watered, check the drip
> line and its emitters; if it was not, it still needs water.

**With the valve reporting, it says which.** A bed can name the series of the valve that
waters it (`Bed.valve`, the `valve_open` term). An OpenSprinkler controller reports each
station opening and shutting over MQTT, and the bridge puts that in the log
([sdk/mqtt_bridge.py](../../sdk/mqtt_bridge.py)):

> bed 3's valve ran 60 minutes this morning, but its probes show almost no new water: the
> root zone rose 0.4 points, where 18 mm should add about 6.0. Check the drip line and its
> emitters for a blockage, and the line for a leak.

> bed 3 was due 18 mm of water this morning, and its valve did not open. It still needs
> water.

**What the backtests showed** ([record](../../docs/notes/soilwater-backtests.md#did-the-water-arrive)):
on McAllister's 2013 and 2012 with waterings blocked on purpose, every blocked one was
caught; on 2012 one watering of 61 that did arrive rose only 0.47 of its expected rise and
was wrongly flagged. A bed that soaks its water up slowly, a probe set deep, or a crop that
draws hard in the hours after a watering can fall below half on a day the water did arrive.
The share is a parameter, and a season of a real bed's waterings is what would set it.

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
* field capacity in a hot, dry soil: learning reads it low there ([above](#what-the-trials-show)),
  and whether a soak test reads it better is not yet tried;
* a shallow bed's earlier refill point where the crop dries it fast: at a fifth gone, it
  spared a lawn and a yard most of what they lost at Davis, and cost water for nothing at
  McAllister ([above](#what-the-trials-show)); it might follow the bed's own drying rate;
* root signs that judge a probe's level against what the roots' density predicts at its
  depth: with roots densest at the top, a deep probe reads near level with no pan at all
  ([above](#roots-that-stop));
* the other sign of a probe out of the soil: no rise after the rain the gauge recorded or
  the watering the valve did, which would catch it in sand too
  ([above](#a-probe-out-of-the-soil)).
