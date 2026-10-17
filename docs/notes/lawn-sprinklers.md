<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Lawn sprinklers: the add-ons, and what each is worth

A home lawn on an in-ground system usually has a timer, a few zones of spray heads and
nothing else. This note asks which small additions to that hardware save water and keep
the lawn healthy, and scores each on the virtual farm.

Most come from published studies and manufacturers. The scores come from
[sim/lawn_drill.py](../../sim/lawn_drill.py), on thirty recorded summers. It follows the
[irrigation projects](irrigation-projects.md) note, which covers the open controllers.

## The add-ons

From cheapest:

| add-on | what it does | what has been found |
| --- | --- | --- |
| **Settings** (free) | Water early in the morning, twice a week, deeply. Turn the seasonal adjustment down when it cools. Split runs on clay or slopes. | UT Extension: about ½ inch "no more than twice each week" in loam; on slopes or heavy clay, run each zone "several times to avoid runoff"; water from 5:00 to 9:00, because "excessively wet turfs are prone to disease" (W161-F, 2008) |
| **Rain sensor** | A switch on the controller's sensor terminals that bypasses watering after rain | UF/IFAS: set it at ⅛ inch, never above ¼; it dries out about 19 hours after rain stops (AE221). On UF's plots from July to December 2004, the same timer applied 696 mm without one and 495 mm with one (Dukes, Cardenas-Lailhacar and Miller 2005). Florida requires a shutoff device on every automatic system (Statute 373.62). |
| **Soil moisture sensor, bypass** | A probe in the driest zone and a switch on the same terminals: when the soil is above the set point, the scheduled run is skipped | Probe centre about 3 inches deep. The sensor calibrates itself a day after a soaking and sets its point at 50 to 75% of that reading (AE437). On UF's plots it used 59% less water on average than an ET-set timer with a rain sensor (range 5 to 88%). In 58 homes in southwest Florida, 65% less than timer homes (Haley and Dukes 2012). EPA estimates a WaterSense sensor saves an average home more than 15,000 gallons a year. |
| **Soil moisture sensor, on demand** | The probe starts watering at a low point and stops it at a high one, rather than only skipping | The less common kind (AE437) |
| **Weather-based adjustment** | Either a WaterSense controller, or an add-on that sets the existing controller's seasonal percentage each day from the weather. Hunter's Solar Sync is one: it measures sunlight and temperature and includes rain and freeze shutoff. | EPA: a WaterSense weather-based controller in place of a clock saves an average home nearly 7,600 gallons a year |
| **Rotary nozzles** | Screw into the existing spray bodies | Rain Bird's RN puts down 0.6 in/h (15 mm/h), against 1.58 in/h (40 mm/h) for its 15 Series spray nozzle at 30 psi. The maker says it "reduces or eliminates run-off on slopes and hard clay soils" and improves efficiency "by up to 30%". |
| **Pressure-regulating spray bodies** | Hold each head at its design pressure | High pressure means "excessive flow rates, misting, fogging, and uneven coverage". EPA estimates nearly 5,600 gallons a year for a home at 60 psi or more. |
| **Flow sensor** | Counts the water each zone takes, so a broken head or a leak shows | OpenSprinkler takes one on its sensor input. No study of its savings was found. Which meters, and the arithmetic of a clogged head: [water meters](water-meters.md) |

**One warning about soil sensors.** UF tested four commercial bypass sensors buried 7 to
10 cm deep. Only one brand's readings tracked the soil's water closely, and one more
partly. Two brands "did not produce readings related to" it. Yet three of the four still cut
watering by 63 to 92% "while maintaining an acceptable turf quality" (Cardenas-Lailhacar
and Dukes, UF Water Institute poster).

A sensor can save water by failing in the wet direction. On Florida's bermudagrass
plots that did no harm. Elsewhere it might.

## Scored on a virtual lawn

`python3 sim/lawn_drill.py --weather FILE --summers 1991-2020 --workers 3 --soil-set S`
runs a cool-season lawn (tall fescue, crop coefficient 0.95 from FAO-56 Table 12, roots in
the top 15 cm). It uses McAllister Farm's thirty recorded summers, June to August, with
NASA POWER weather.

**The starting system:**

* a timer that waters three mornings a week, 13 mm from spray heads each time, whatever
  the weather;
* that is about 1.5 inches a week, the top of UT Extension's 1 to 1.5.

Each add-on is then put on it alone, and the four hardware add-ons together.

**Two soils:**

* `native`: the silt loam the soil survey maps there;
* `yard`: what a builder leaves, 10 cm of sandy loam brought in over compacted clay.

The soils' values, intake rates and wetting-front suctions are typical ones, assumed.

**The scores, means per summer:**

* water applied;
* water drained below the roots;
* **dry hours**: half the available water gone;
* **soggy hours**: the top 5 cm within 0.02 of saturation, when turf is short of air and
  prone to disease.

| native silt loam | applied | drained | dry h (worst summer) | soggy h |
| --- | --- | --- | --- | --- |
| timer | 513 mm | 397 mm | 0 | 23 |
| twice a week instead | 342 | 231 | 9 (164) | 14 |
| + rain sensor | 416 | 307 | 0 | 18 |
| + cycle and soak | 513 | 403 | 0 | 27 |
| + rotary nozzles | 513 | 400 | 0 | 28 |
| **+ weather-based adjustment** | **342** | **231** | **0** | **13** |
| + soil sensor, set at 62.5% | 94 | 15 | 522 (956) | 0 |
| + soil sensor, set at 75% | 138 | 38 | 122 (422) | 0.4 |
| + soil sensor, set at 85% | 181 | 75 | 11 (72) | 5 |
| **on-demand sensor, set at 85%** | **191** | **84** | **0** | **4** |
| all four hardware add-ons, 85% | 180 | 74 | 11 (73) | 2 |

| yard: sandy topsoil over clay | applied | drained | dry h (worst summer) | soggy h |
| --- | --- | --- | --- | --- |
| timer | 513 mm | 394 mm | 38 (110) | 63 |
| twice a week instead | 342 | 240 | 237 (432) | 43 |
| + rain sensor | 416 | 304 | 42 (110) | 28 |
| + cycle and soak | 513 | 393 | 28 (101) | 58 |
| + rotary nozzles | 513 | 394 | 36 (106) | 61 |
| + weather-based adjustment | 342 | 230 | 49 (122) | 25 |
| + soil sensor, set at 62.5% | 206 | 112 | 325 (562) | 21 |
| + soil sensor, set at 75% | 277 | 169 | 129 (282) | 24 |
| + soil sensor, set at 85% | 348 | 238 | 63 (234) | 27 |
| **on-demand sensor, set at 85%** | **429** | **315** | **0** | **36** |
| all four hardware add-ons, 85% | 334 | 223 | 52 (208) | 26 |

Runoff was small throughout: at most 8 mm a summer on average. It is covered below.

Run again on 2026-10-16, when the simulator's lawn began to use its water as FAO-56's does,
whole until half is gone, and from the top of its roots first
([soil advisory](../../modules/soilwater/README.md#the-crops-water-use-and-the-soils-surface)).
On the native soil little moved but the soil sensors, which now leave it dry for some
hours even at 85%. The yard's 15 cm of roots in sandy topsoil, which on the simulator
before held through every policy but twice-weekly watering, now go dry under the timer
itself, 38 hours a summer, and under every add-on that waters less. Before that, on
2026-10-15, the simulator's soil had begun to move water below field capacity, which left
the native lawn dry for far fewer hours under the soil sensors.

## What it shows

1. **The plain timer wastes most of its water.** On the native soil, 397 of its 513 mm
   drained below the roots. Most of the saving on offer is simply not watering after
   rain or through cool spells.
2. **Weather-based adjustment is the best single add-on on the native soil.** It used a
   third less water with no dry hours, and the soggy hours fell by almost half. It needs
   no probe and no wiring into the soil, and the add-on kind leaves the existing controller
   in place. On the yard it saves the same third, and the lawn is dry for 49 hours a
   summer against the timer's 38: a shallow topsoil has nothing to spare for the cool
   spells it waters less in.
3. **The rain sensor is the cheapest, and costs the native lawn nothing.** It used a fifth
   less water, and on the yard it more than halved the soggy hours (63 to 28), the dry ones
   about the timer's.
4. **A soil sensor can save the most, or starve the lawn: the set point decides.**
   * At 85% of its calibrated reading, a bypass sensor used two thirds less water on the
     native soil than the timer, with 11 dry hours a summer (72 in the worst).
   * At the middle of AE437's range, 62.5%, the same lawn was dry for 522 hours a summer.
     In a silt loam that holds 0.30 and gives up its last water at 0.12, that set point
     waits until the lawn is nearly dry.
   * **The on-demand kind, set at 85%, was never dry on either soil**: it starts the
     watering when the probe reads low, rather than waiting for the timer's next day. On
     the native soil it used 191 mm, three fifths less than the timer; on the yard, 429.
   * Florida's plot studies, which found no harm, were on bermudagrass in Florida's
     soils. A sensor's set point should be set for its own soil and grass, not left at
     a default.
5. **Calibrating from one soaking can go badly wrong on layered soil.** In 2013 the yard's
   sensor calibrated while water still perched in its topsoil, so "full" read near
   saturation, and the on-demand controller ran every cycle it was allowed, every morning,
   far more than the timer. Over thirty summers, set at 85%, it still gave the yard its
   only result with no dry hours, on 429 mm, though it left the turf soggier than the
   weather adjustment or the rain sensor did.
6. **Nozzles and cycle-and-soak stop spray-head runoff, but do not save water on their
   own here.** At 40 mm an hour, spray heads outran the silt loam once its surface was
   wet: 5 mm a summer on average. Both brought that to nothing. But the timer still put
   the same water down, so what did not run off drained instead.
   * On the yard, the runoff was rain on topsoil already holding water over the clay, and
     neither helped.
   * Even coverage is what they are mostly bought for, and the simulator cannot score
     it. On slopes, and when paired with an add-on that waters less, they matter more
     than here.
7. **"Twice a week" is free and saves a third.** On the native soil it left the lawn dry
   for 9 hours a summer, 164 in the worst, but on the yard's shallow topsoil for 237, 432
   in the worst: on these 15 cm roots a drought outlasts the gap between waterings there.
   Deep, infrequent watering is meant to grow deeper roots that ride out such spells.
   The simulator does not grow roots, so this is its least favourable case.

## What it does not show

* **Uniformity.** A real zone waters some spots twice as much as others, and a timer is
  set for the driest. Pressure regulation and better nozzles help there.
* **Roots that grow, and the grass itself.**
* **Cost.** Prices change, and are left out.
* **A forecast.** The weather adjustment's baseline is the site's own thirty-summer mean,
  and it scales by yesterday's weather, as OpenSprinkler's ETo method does
  ([irrigation projects](irrigation-projects.md#their-methods-on-thirty-summers)).

* **How much water a lawn really uses.** The virtual lawn uses FAO-56's 1998 0.95. The
  2025 revision gives a mown lawn 0.50 to 0.70 through its season (its Table 6.4), a
  third less. Every policy here would water as it does, but the lawn would need less,
  and the timer's waste would be larger still. fieldmesh's soil advisory keeps the 1998
  value by default and offers the revision's as `turf_lawn`: told 0.70, by the weather,
  it saved a third of the water when that is the lawn's true rate, and when it is not,
  left the yard's lawn short in 27 or 28 summers of 30 on the simulator of 2026-10-16
  ([soil advisory](../../modules/soilwater/README.md#a-crop-that-grows)).

The soils are assumed, and the "dry" and "soggy" lines are this note's, not agronomy's.
Every number here is the simulator's ([UNTESTED](../UNTESTED.md)).

## Where fieldmesh fits

* **Its probe answers the soil sensor's two weak points.**
  * Readings are checked before they count, so a probe that fails wet or stuck is
    flagged, not obeyed.
  * The bed's field capacity is learned from many drain-downs, not one soaking, so a
    perched layer does not set "full" ([the bed's own soil](../../modules/soilwater/README.md#the-beds-own-soil)).
  * The refill point comes from the bed's own soil and the crop's depletion fraction,
    not a brand's default.
* **It already reads a controller.** The MQTT bridge reads an OpenSprinkler's stations,
  flow and rain delay ([irrigation projects](irrigation-projects.md)).
* **The smallest add-on it could become is a switch on the sensor terminals.** Nearly
  every controller already understands one, so a fieldmesh node with a relay could be the
  controller's "rain sensor", driven by the probe's advice.
  * It can only skip a watering, never start one.
  * Wired so that a dead node leaves the switch closed, its failure gives back the
    timer, not a lawn that is never watered.
  * It still changes how much water flows, so it is a command, and it waits for §6 and
    the trust ramp (§11). Until then the same signal stands as advice on the board.

## Sources

* UT Extension W161-F, *Turfgrass Maintenance: Irrigation*, T. Samples and J. Sorochan,
  2008. [PDF](https://uthort.tennessee.edu/wp-content/uploads/sites/228/2023/11/W161-F.pdf)
* UF/IFAS AE221, *Residential Irrigation System Rainfall Shutoff Devices, or Rain
  Sensors*, M. D. Dukes and B. Cardenas. [EDIS](https://ask.ifas.ufl.edu/publication/AE221)
* UF/IFAS AE437, *Smart Irrigation Controllers: How Do Soil Moisture Sensor (SMS)
  Systems Work?*, B. Cardenas-Lailhacar, M. D. Dukes and M. L. Shedd. [EDIS](https://ask.ifas.ufl.edu/publication/AE437)
* M. D. Dukes, B. Cardenas-Lailhacar and G. L. Miller, "Residential irrigation based on
  soil moisture", *Resource* (ASABE), June/July 2005, 4–6. [PDF](https://aws.sjrwmd.com/FWS/pdfs/residential_irrig_soilmoisture.pdf)
* M. B. Haley and M. D. Dukes, "Validation of landscape irrigation reduction with soil
  moisture sensor irrigation controllers", *Journal of Irrigation and Drainage
  Engineering* 138(2), 135–144, 2012. [doi:10.1061/(ASCE)IR.1943-4774.0000391](https://doi.org/10.1061/(ASCE)IR.1943-4774.0000391)
* B. Cardenas-Lailhacar and M. D. Dukes, "Water conservation potential and performance of
  soil moisture sensor irrigation controllers", UF Water Institute symposium poster.
  [PDF](https://archives.waterinstitute.ufl.edu/symposium/downloads/poster-4C045EAB.pdf)
* US EPA WaterSense: [weather-based controllers](https://www.epa.gov/watersense/weather-based-irrigation-controllers),
  [soil moisture-based controllers](https://www.epa.gov/watersense/soil-moisture-based-irrigation-controllers),
  [spray sprinkler bodies](https://www.epa.gov/watersense/spray-sprinkler-bodies)
  (pages dated March 2026).
* Rain Bird: [MPR spray nozzle performance charts](https://rainbird.com/sites/default/files/media/documents/2020-09/mpr-spray-nozzle-performance-charts_0.pdf);
  [RN rotary nozzles](https://www.rainbird.com/products/rn-high-efficiency-rotary-nozzles-0).
* Hunter: [Solar Sync](https://www.hunterirrigation.com/irrigation-product/sensors/solar-syncr-sensor).
* FAO-56, R. G. Allen et al., 1998, Table 12. [FAO](http://www.fao.org/4/x0490e/x0490e0b.htm)
