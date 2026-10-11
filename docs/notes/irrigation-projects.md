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

1. **Read the valves into the log: buildable now, no commands.** OpenSprinkler publishes
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
2. **Score their methods on recorded summers, and give the numbers back.** Add OpenSprinkler's
   Zimmerman and ETo adjustments and Smart Irrigation's evapotranspiration bucket to the
   irrigation drill, beside the timer and the soil probe, over thirty McAllister summers.
   That gives water applied, drained and stress for each. It is a comparison none of those
   projects can easily make for itself, and the kind they could use to set defaults. Shared
   as a note and an issue in each project, it is a contribution of evidence, not code.
3. **Take pyfao56's water balance where a bed has no probe.** It is public domain and
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
