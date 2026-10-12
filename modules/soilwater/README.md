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
| **the advisory** | **155 mm** | **241 mm** | **0** | **0.13** |

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
| one, 5 cm | the survey | 680 mm, 693 drained, 0 h | 810 mm, 662, 0 h |
| | the survey, **learning** | **178 mm, 232, 0 h** | **272 mm, 196, 16 h** |
| | the topsoil's values | 94 mm, 196, 140 h | 110 mm, 131, 421 h |
| | the topsoil's values, **learning** | **181 mm, 232, 0 h** | **227 mm, 155, 76 h** |
| 5 and 12 cm | the survey | 136 mm, 209, 4 h | 196 mm, 141, 45 h |
| | the survey, learning | 147 mm, 210, 4 h, and the note | 208 mm, 147, 75 h, and the note |
| | each layer's values | 119 mm, 203, 0 h | 183 mm, 145, 68 h |
| | each layer's values, **learning** | **165 mm, 219, 0 h** | **229 mm, 158, 0 h** |

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
  and learning changes little. In the 2012 drought it did slightly worse, 75 stressed
  hours against 45. The trouble is the wilting point: one value for two soils counts
  water the clay holds that the roots cannot take, so the advice waits too long. The note
  is what helps here. Given each layer's values, as the note asks, and with learning on,
  the yard was never short in either summer.
* **Learning leaves a correctly set-up bed alone.** On the advisory's own backtest bed it
  changed the 2013 summer by less than a millimetre (154.5 mm against 155.4) and 2012
  not at all.

A uniform sandy fill, 60 cm of the same sandy loam with a probe at 5 cm, behaves like
the single-probe yard: 725 mm on the survey's values against 177 learning in 2013. On
its nominal values it had 107 stressed hours, and none learning.

**What is still not right.** The 16 to 76 hours left in 2012 come from the morning
cadence on a shallow, sandy root zone. It holds about 17 mm its roots can use, and in
2012 a hot day took up to 7.7 mm. With water at a third gone, one morning's "water soon" can be past
half by the next morning. For such a bed, `p` should be lower.

The 25 mm that ran off the yard in 2013 was rain on topsoil already holding water over the
clay, the same with or without learning. A watering can do the same when it is run
faster than the clay takes water. In the simulator, the same 50 mm given as four
quarter-hour runs an hour apart sheds less than two hours in one go (`sim/test_physics.py`),
which is cycle-and-soak.

**A probe that reads off.** Learning forgives a probe that reads low: one 0.05 low called
for 748 mm unlearned and 256 learned, against a true probe's 155, on 2013. It cannot
forgive one that reads high. That probe says the bed is full, so the bed is not watered,
and the probe sees too few soakings to learn from: 242 hours of stress. A second probe in
the bed is what catches it ([soil sensors](../../docs/notes/soil-sensors.md)).

These results come from the simulator. A real yard's probes are what would check them
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
| 2013 | 157 mm | 155 mm | 0 |
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
| corrected all the way, both ways (not built) | 217 mm | 5, up to 33 hours |
| **corrected as built** | **229 mm**, 5% less | **0** |
| as built, the reference's probe reading 0.05 low | 222 mm | 0 |
| as built, the reference's probe reading 0.05 high | 241 mm: it never corrects | 0 |

The probe-led bed beside it was given 177 mm a summer.

**Why only half way.** The rate a probe saw over a month does not hold through a hot spell,
and the balance's own excess was the bed's margin. Corrected all the way, the bed went
short in one summer in six. A probe reading high, used without the learning check, took
the bed to 397 stressed hours on the 2012 drought. With it, the probe was never used.

On the two summers above: 2012 down from 314 mm to 274, and 2013 up from 157 to 179, one
watering more late in the summer, when the probe saw the bed drying faster than the
balance did. Neither was short. The probe's own fallback through its fortnight's outage
was unchanged, 199 mm. A pyfao56-style reset of the balance from a probe in the same zone
is not built.

The balance's ET is Penman–Monteith, while the virtual bed loses water by Hargreaves'
formula. So it runs on a model of the bed that is not the bed, as it would on a farm.
In the dry summer it watered half again as much as the probe did, and still a fraction
of the 552 mm a drip timer uses. A probe reads the bed itself; this reads only the sky.

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
* the crop's `p` and root depth from the farm's planting records;
* a wilting point learned from the probes: that needs the crop's lower limit, the
  driest its roots take a probe to, which a well-watered bed never shows;
* a safe run length learned from the bed: comparing short runs with long ones,
  cycle-and-soak worked out from the bed itself;
* each bed's drying rate and the share of rain that reaches it, learned, to set beside
  its recorded surface and planting;
* for a bed advised by the weather, the crop's coefficient through the season, rather
  than one number.
