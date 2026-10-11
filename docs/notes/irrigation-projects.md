<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Sprinklers and drip: the open projects, where they meet this one, and what could flow each way

Looked at on 2026-10-11. Licences and activity were read from each repository, and every
claim about OpenSprinkler's messages from its firmware's source.

## Who is out there

| project | what it is | licence | state |
| --- | --- | --- | --- |
| [OpenSprinkler](https://github.com/OpenSprinkler/OpenSprinkler-Firmware) | open-hardware irrigation controllers (ESP8266/ESP32, Raspberry Pi), firmware, a documented local HTTP API and MQTT | firmware GPL-3.0; [app](https://github.com/OpenSprinkler/OpenSprinkler-App) AGPL-3.0 | active: firmware pushed 2026-09-29 |
| [OpenSprinkler Weather](https://github.com/OpenSprinkler/OpenSprinkler-Weather) | the service a controller asks for its watering scale: manual, Zimmerman, rain delay or ETo, from public providers or a local weather station | **none declared** | active: 2026-08-16 |
| [SIP](https://github.com/Dan-in-CA/SIP) (Sustainable Irrigation Platform) | a Raspberry Pi controller in Python 3, with plugins; also runs pumps and lights | "GNU GPL" in its README, **no licence file**, so the version is unstated | active: 2026-07-27 |
| [Smart Irrigation](https://github.com/altmenorg/HAsmartirrigation) for Home Assistant | run times per zone from evapotranspiration, rain and forecasts; a UI in 19 languages | MIT | active: 2026-10-11 |
| [ESPHome sprinkler](https://esphome.io/components/sprinkler/) | a valve controller on an ESP chip: zones, cycles, a run-time multiplier, a pump or main valve upstream | GPL-3.0 for its C++ runtime, MIT for its Python | maintained with ESPHome, pushed 2026-10-11 |
| [pyfao56](https://github.com/kthorp/pyfao56) (USDA ARS) | FAO-56 dual crop coefficient water balance and irrigation scheduling; NWS forecasts; measured soil water profiles | public domain in the US, CC0 elsewhere | active: 2026-09-21 |
| [AquaCrop-OSPy](https://github.com/aquacropos/aquacrop) | FAO's AquaCrop crop-water model in Python: yield's response to irrigation strategies | Apache-2.0 | active: 2026-09-23 |
| [Mycodo](https://github.com/kizniche/Mycodo) | environmental monitoring and regulation, PID loops, irrigation among them | GPL-3.0 | active |
| [FarmBot](https://github.com/FarmBot/Farmbot-Web-App) | a CNC garden robot that waters by plant and reads soil moisture | MIT | active |
| [farmOS](https://github.com/farmOS/farmOS) | farm records; water applied can be an input log | GPL-2.0 | active |

For the farm-scale end — centre pivots and variable-rate irrigation — the search found
patents, not open projects. Pivot controllers are the manufacturers' own.

## Where they meet what is here

All of these are at the scale of the farms this project is for: drip zones in beds, a
tunnel, a garden-sized field. Three things here touch them.

* **The soil-moisture advisory** ([modules/soilwater/](../../modules/soilwater/)) decides
  *whether and how much*, from the farm's own probes, FAO-56's readily available water and
  the rain forecast. Its watering check says when a watering never reached the bed. The
  controllers above decide *when the valves open*, mostly by timer adjusted by weather.
  None of them reads a soil probe as its main input.
* **The irrigation drill** ([sim/irrigation_drill.py](../../sim/irrigation_drill.py))
  scores watering rules on recorded summers by the water applied, the water lost below the
  roots and the hours of crop stress: a timer, skip on forecast rain, the soil rule. It can
  run thirty summers. Nothing in the projects above publishes that kind of comparison for
  its own adjustment methods.
* **The command contract** (§6), deferred, is where an irrigation controller lives: a
  command that survives a reboot without running twice, an acknowledgement or an honest
  "unknown", and no overdrawing one well from two modules (§6.5, §15). The irrigation
  controller is the one of §15's three acceptance apps that waits on it.

## What could flow each way, in the order worth doing

1. **Read the valves into the log: buildable now, no commands.** *Built 2026-10-11: an
   OpenSprinkler profile in the MQTT bridge, a `valve_open` term, and the watering check
   naming a blocked line or a bed nobody watered ([modules/soilwater](../../modules/soilwater/README.md#did-the-water-arrive)).* OpenSprinkler publishes
   each valve's opening and closing over MQTT, under its configured prefix
   (firmware `services/notifier.cpp`):
   * `station/<n>`, `{"state":1,"duration":…}` on opening;
   * `{"state":0,"duration":…,"flow":…}` on closing, the flow from its flow sensor if
     one is fitted;
   * `sensor/flow`, `raindelay`, `weather`, and alerts on flow and current.

   An OpenSprinkler profile in the MQTT bridge ([sdk/mqtt_bridge.py](../../sdk/mqtt_bridge.py)),
   beside its ESPHome and Home Assistant profiles, would put each watering in the log as
   an observation. The watering check could then tell apart the two things a probe cannot:
   *the valve ran for 90 minutes and no water reached the bed* (a blocked line or a leak)
   and *nobody watered*. The board could show the last watering beside each bed. ESPHome's
   sprinkler, and SIP and Home Assistant through MQTT, could be read the same way.
2. **Score their methods on recorded summers, and give the numbers back.** *Scored
   2026-10-11: the results are [below](#their-methods-on-thirty-summers). Giving them back is
   the maintainer's.* Add OpenSprinkler's
   Zimmerman and ETo adjustments and Smart Irrigation's evapotranspiration bucket to the
   irrigation drill, beside the timer and the soil probe, over thirty McAllister summers.
   That gives water applied, drained and stress for each. It is a comparison none of those
   projects can easily make for itself, and the kind they could use to set defaults. Shared
   as a note and an issue in each project, it is a contribution of evidence, not code.
3. **Take pyfao56's water balance where a bed has no probe.** *Scored 2026-10-11, its
   scheduler run as published: [below](#pyfao56-without-a-probe).* It is public domain and
   CC0, so it can be used in an AGPL module outright, with credit. Its dual crop
   coefficient and layered soil go further than the advisory's single bucket. It could
   advise beds without probes, and check the advisory's bucket where they have them.
4. **Licence clarity, two small requests.** OpenSprinkler Weather declares no licence,
   though the firmware and app beside it are GPL and AGPL. SIP says "GNU GPL" without a
   licence file, so which version is unclear. Without a licence, others cannot safely build
   on the code, and asking is a contribution in itself.
5. **A soil-based watering scale for an OpenSprinkler, later.** A controller asks the
   weather service at an address it is configured with (`SOPT_WEATHERURL`, http or https)
   and takes a watering `scale` from the answer. A farm's own fieldmesh could answer that
   request from its soil probes instead of the weather. The controller keeps its own
   schedule, valves, rain delay and limits, and fieldmesh would only say *more* or *less*.
   **That is a command in all but name**: it changes how much water flows. So it waits for
   §6 and the trust ramp (§11: advisory, then approval, then autonomous). Until then the
   same number can stand on the board as advice.
6. **Read their safeguards before freezing §6.** OpenSprinkler's main valve, sequential
   groups, flow alerts and rain delay are a working controller's answers to the questions
   §6.5 asks about shared limits. They are worth reading alongside OGC Connected Systems
   (Q3b) before the contract is frozen.
7. **Yield, not only water: AquaCrop-OSPy** (Apache-2.0) could score the advice by what the
   crop yields under it, as GreenLight scores the tunnel (Q28). This is layer-3 work, after
   the irrigation module exists.

Items 1 to 3 are code that can be written here. Items 2 and 4 involve opening issues in
other projects, which is the maintainer's to do. Item 5 waits on §6.

## Their methods on thirty summers

`sim/irrigation_drill.py --summers 1991-2020 --controllers`, on McAllister Farm's thirty
recorded summers (NASA POWER), puts one bed through each under every rule on identical
weather. The bed is a 30 cm root zone in silt loam under a full canopy. The controllers' rules
are written from their source:

* OpenSprinkler's Zimmerman (`ZimmermanAdjustmentMethod.ts`) and ETo
  (`EToAdjustmentMethod.ts`) methods scale the timer's program, 12 mm every second
  morning, by the day before's weather;
* Home Assistant's Smart Irrigation (`calculation.py`, with its defaults: crop factor 1, a
  24 mm bucket, surplus drained within the day) puts back each day's reference ET less its
  rain.

Reference ET is FAO-56 Penman–Monteith, from each day's recorded extremes, mean humidity and
sunshine, with FAO-56's 2 m/s where no wind is recorded. On FAO-56's own Example 18 it gives
3.79 mm against the published 3.9; the gap is the mean humidity, where the example uses the
day's maximum and minimum.

| rule | water applied | drained below the roots | transpired | hours seriously stressed |
| --- | --- | --- | --- | --- |
| timer | 552 mm | 432 mm | 441 mm | 0 |
| **OpenSprinkler ETo, default annual baseline** | **612** | **490** | 442 | 0 |
| OpenSprinkler Zimmerman | 385 | 271 | 434 | 0 |
| OpenSprinkler ETo, a summer baseline | 367 | 252 | 435 | 0 |
| Home Assistant Smart Irrigation | 294 | 177 | 436 | 0 |
| pyfao56's scheduler, no probe | 322 | 237 | 407 | 0 |
| this project's soil probe rule | 219 | 146 | 395 | 0.3 (8.5 h in 1993) |

The first five rows reproduce the timer's figures in [forecasts.md](forecasts.md#watering-by-forecast-and-by-soil)
exactly, and the soil probe's.

* **OpenSprinkler's ETo method, left at its default baseline, waters more than the plain
  timer**: 11% more, and 13% more lost below the roots. Its baseline is an annual figure, a
  year-round average day of 2.8 mm here, while summer runs at 4.8 mm. So every summer program
  is scaled up by about 1.7, against its cap of 2. Set to a summer baseline, the same method
  saves a third. The baseline matters more than the method, and the default works against
  a grower who set the program in summer. That is the finding worth giving back first.
  Here the annual mean of FAO-56 ET on POWER data stands in for its MOD16 dataset, so the
  exact factor is this place's estimate, not theirs.
* **Zimmerman saves 30%** in this humid climate, where its humidity term pulls the scale
  down. Far drier air would push it the other way.
* **Home Assistant's bucket saves 47%** with the same transpiration as the timer and no
  stress: the closest a weather-only rule comes to the soil probe.
* **The soil probe saves 60%.** Its lower transpiration is an upper bound on its cost,
  because the simulator's stress falls linearly from field capacity, stricter than FAO-56.

One place, one soil and one crop, in a humid climate whose summers average 315 mm of rain.
Over thirty summers the virtual bed's own water use averages 4.8 mm a day, the same as the
reference ET the controllers compute, so none of them is scored against a demand it could not
know. A drier place, a sandier soil or a crop factor other than 1 would move every row.

## pyfao56 without a probe

[tools/pyfao56_schedules.py](../../tools/pyfao56_schedules.py) runs pyfao56 1.4.3's automatic
scheduler (Thorp, DeJonge and Kukal 2025) as published, in its own environment, on each of the
thirty summers. It is configured with the drill's bed: a 30 cm root zone, field capacity 0.30,
wilting point 0.12, a full canopy with a basal crop coefficient of 1.05. It waters when a third
of the available water is gone, the probe rule's refill point, back to field capacity. The
irrigation drill then waters the virtual bed on that schedule
(`sim/data/pyfao56-mcallister-summers.csv`, policy `pyfao56`): 12 waterings a summer of about
25 mm.

* **With no probe it saves 42%** of the timer's water, with no stress. That is more than
  Zimmerman's or the ETo method's savings and less than Home Assistant's bucket, which waters
  every day.
* **It drains more than the probe rule**, 237 mm against 146. It refills by its own model's
  depletion, which runs ahead of what the virtual bed actually lost, so part of each 25 mm
  goes below the roots. An open-loop water balance drifts from the soil. This is where the
  two projects fit together: pyfao56 can update its balance from measured soil water content
  (its `Update` class), and the probes here, each reading with its quality verdict, are that
  input. A probe that is flagged need not reach it.
* **Our reference ET agrees with pyfao56's**: over 10,958 days at McAllister, `sim/physics.fao56_eto`
  ran 0.013 mm a day above pyfao56's ASCE routine (`refet.ascedaily`) on average. The spread
  was 0.04 mm, and the worst single day differed by 0.35 mm. So the controllers above are fed
  the same ET a published implementation computes.
* **A bug worth reporting**: pyfao56 1.4.3 divides by zero for a canopy whose basal crop
  coefficient does not change over the season (`Kcbini == Kcbmid`; `model.py`, the plant
  height step). A turf, a pasture, a bed already in full leaf all hit it. The script steps
  around it with 1.049 and says so.

Still to build: the advisory itself for a bed without a probe, which needs daily
sunshine and humidity in the farm's log to compute ET from. Those are the forecast
collector's `dswrf` and `relative_humidity`, or a station's.

