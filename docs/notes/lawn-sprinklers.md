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
| timer | 513 mm | 418 mm | 0 | 22 |
| twice a week instead | 342 | 279 | 15 (87) | 13 |
| + rain sensor | 416 | 330 | 0 | 17 |
| + cycle and soak | 513 | 422 | 0 | 26 |
| + rotary nozzles | 513 | 420 | 0 | 27 |
| **+ weather-based adjustment** | **342** | **258** | **0** | **12** |
| + soil sensor, set at 62.5% | 75 | 104 | 407 (659) | 1 |
| + soil sensor, set at 75% | 127 | 119 | 149 (311) | 2 |
| **+ soil sensor, set at 85%** | **211** | **160** | **19 (145)** | **7** |
| on-demand sensor, set at 85% | 173 | 135 | 13 (73) | 2 |
| all four hardware add-ons, 85% | 197 | 152 | 29 (170) | 5 |

| yard: sandy topsoil over clay | applied | drained | dry h (worst summer) | soggy h |
| --- | --- | --- | --- | --- |
| timer | 513 mm | 407 mm | 1 (14) | 71 |
| twice a week instead | 342 | 271 | 56 (153) | 49 |
| **+ rain sensor** | **416** | **319** | **2 (20)** | **33** |
| + cycle and soak | 513 | 406 | 1 (13) | 64 |
| + rotary nozzles | 513 | 406 | 1 (14) | 68 |
| **+ weather-based adjustment** | **342** | **248** | **3 (36)** | **29** |
| + soil sensor, set at 62.5% | 130 | 124 | 304 (564) | 22 |
| + soil sensor, set at 75% | 208 | 159 | 99 (226) | 26 |
| + soil sensor, set at 85% | 306 | 222 | 10 (74) | 29 |
| **on-demand sensor, set at 85%** | **322** | **233** | **0** | **38** |
| all four hardware add-ons, 85% | 294 | 213 | 10 (74) | 28 |

Runoff was small throughout: at most 9 mm a summer on average. It is covered below.

## What it shows

1. **The plain timer wastes most of its water.** On the native soil, 418 of its 513 mm
   drained below the roots. Most of the saving on offer is simply not watering after
   rain or through cool spells.
2. **Weather-based adjustment is the best single add-on here.** It used a third less
   water, with no dry hours on the native soil and three on the yard. The soggy hours
   fell by almost half on the native soil and by more on the yard. It needs no probe and no wiring into the soil. The add-on kind
   leaves the existing controller in place.
3. **The rain sensor is the cheapest, and costs the lawn nothing.** It used a fifth less
   water, and on the yard it halved the soggy hours (71 to 33).
4. **A soil sensor can save the most, or starve the lawn: the set point decides.**
   * At 85% of its calibrated reading, a bypass sensor used 59% less water on the native
     soil than the timer, with 19 dry hours a summer.
   * At the middle of AE437's range, 62.5%, the same lawn was dry for 407 hours a summer.
     In a silt loam that holds 0.30 and gives up its last water at 0.12, that set point
     waits until the lawn is nearly dry.
   * Florida's plot studies, which found no harm, were on bermudagrass in Florida's
     soils. A sensor's set point should be set for its own soil and grass, not left at
     a default.
5. **Calibrating from one soaking can go badly wrong on layered soil.** In 2013 the yard's
   sensor calibrated while water still perched in its topsoil, so "full" read near
   saturation. The probe never read full again, and the on-demand controller ran every
   cycle it was allowed, every morning: 860 mm, against the timer's 507. Over thirty
   summers, set at 85%, the on-demand sensor gave the yard its best result for dryness
   (no dry hours) on 322 mm, though it left the turf soggier than the weather adjustment
   or the rain sensor did.
6. **Nozzles and cycle-and-soak stop spray-head runoff, but do not save water on their
   own here.** At 40 mm an hour, spray heads outran the silt loam once its surface was
   wet: 6 mm a summer on average, 15 mm in 2013. Both brought that to nothing. But the
   timer still put the same water down, so what did not run off drained instead.
   * On the yard, the runoff was rain on topsoil already holding water over the clay, and
     neither helped.
   * Even coverage is what they are mostly bought for, and the simulator cannot score
     it. On slopes, and when paired with an add-on that waters less, they matter more
     than here.
7. **"Twice a week" is free and saves a third, but leaves the lawn dry in droughts** on
   these 15 cm roots: 87 hours in the worst summer on the native soil, 153 on the yard.
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
  it saved a third of the water when that is the lawn's true rate, and left it short in
  a third of summers when it is not ([soil advisory](../../modules/soilwater/README.md#a-crop-that-grows)).

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
