<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Water meters and head flows: the arithmetic of a clogged head

*Forward intents, saved 2026-10-11, not built.*

A zone's flow is the sum of its heads' flows. With a meter on the irrigation line, each
run of each zone has a measured flow, which can be set beside the flow its heads should
give.

* **Too little** means a clogged nozzle or filter, a valve not opening fully, or low
  pressure.
* **Too much** means a broken head, a missing nozzle or a leak.

This note lists the meters a farm or a home can add easily, and the makers' flow figures
per head. It then works through how small a fault the arithmetic can see.

## What exists already

* **OpenSprinkler** counts a 2-wire pulse flow meter on its sensor input and reports each
  zone's flow as the zone closes. fieldmesh's MQTT bridge already reads that into the log
  as `station.<n>.flow` ([irrigation projects](irrigation-projects.md)).
* **Its flow alert only looks up.** In its firmware (`services_notifier.cpp`), the alert
  fires when a zone's flow **exceeds** a set point, read from the last five characters
  of the station's name. A broken head can trip it. A clogged head, which lowers the
  flow, never does. That is the gap this note is about.

## Meters that install easily

| meter | how it goes in | output | reaches fieldmesh | open? | caveat |
| --- | --- | --- | --- | --- | --- |
| **A pulse-output meter on the irrigation line**, such as Hunter's HC Flow, a Dwyer multi-jet with pulse output, or Rain Bird's FS with a pulse transmitter | Plumbed in after the backflow preventer, on the irrigation line only | A dry contact pulsing per volume. Hunter lists 1 pulse per 0.1 gallon on the ¾-inch HC and 1 per gallon on the larger, ±2% of reading (as resellers reproduce Hunter's listing) | **Today**: through OpenSprinkler's flow input and the bridge; or an ESPHome pulse counter and the bridge | the protocol is a pulse; the meters are proprietary | it needs a plumber, or a homeowner who solders PVC; the meter's pulse rate goes in a calibration (§3.2) |
| **A sensor on the utility meter's dial**: an inductive proximity sensor (such as the LJ18A3-8-Z/BX) over the meter's turning metal target, counted by ESPHome's pulse meter | Strapped on, no plumbing, nothing cut | Pulses, one per turn of the target | **Today**: through ESPHome and the bridge | the firmware is open (ESPHome) | It measures the whole house, so irrigation is told apart only by when a zone runs. Not every meter has a metal target. The meter is the utility's: a sensor beside it alters nothing, but nothing should be opened |
| **A camera reading the dial**: AI-on-the-edge, an ESP32-CAM and a neural network | Clipped over the meter's face | The reading, by MQTT | Through MQTT, under a profile to write | **Not open source since January 2025**: its Dual Use License allows private, non-commercial use only | A home lawn may use it. A farm is a business, and would need the author's commercial licence |
| **A small turbine flow sensor** (Hall-effect, for small pipe) | Cut into a drip zone's line | Pulses | Through ESPHome and the bridge | open in practice | uncalibrated; calibrate with a bucket and a stopwatch before trusting it |

## Flow per head, from the makers' charts

**Fixed spray nozzles**: Rain Bird MPR, 4-inch pop-ups, at 30 psi.

| series (radius) | full circle | half | quarter |
| --- | --- | --- | --- |
| 8 Series (8 ft) | 1.05 gpm | 0.52 | 0.26 |
| 10 Series (10 ft) | 1.58 | 0.79 | 0.39 |
| 12 Series (12 ft) | 2.60 | 1.30 | 0.65 |
| 15 Series (15 ft) | 3.70 | 1.85 | 0.92 |

**Rotor nozzles**: Rain Bird 5000 / 5000 Plus Rain Curtain, at 45 psi.

| nozzle | 1.5 | 2.0 | 2.5 | 3.0 | 4.0 | 5.0 | 6.0 | 8.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpm | 1.54 | 2.07 | 2.51 | 3.09 | 4.01 | 5.09 | 6.01 | 8.03 |

**Drip emitters**: Rain Bird Xeri-Bug, pressure-compensating from 15 to 50 psi. 0.5,
1.0 and 2.0 gallons an hour, which is 0.008, 0.017 and 0.033 gpm.

**Pressure changes every head at once, as its square root.** A nozzle is an orifice, so
its flow goes as √P. The charts bear it out: the 15F gives 2.60 gpm at 15 psi and 3.70
at 30, a ratio of 1.42, where √2 is 1.41. A pressure drop lowers every head together,
by a share that does not depend on the head. A clog takes one head's whole share. That
difference is how the two can be told apart, especially with a pressure sensor on the
line.

## The arithmetic: how small a fault can be seen

**A lawn zone**: six 15-foot half heads and two quarters, at 30 psi.

* Expected: 6 × 1.85 + 2 × 0.92 = **12.94 gpm**.
* One half head fully clogged: 11.09 gpm, **−14%**.
* One quarter head clogged: −7%.
* A head knocked off its riser: far **more**. The riser runs open, beyond any chart.

**What hides a fault:**

* the meter's own error, ±2% on Hunter's HC;
* the supply's pressure. Pressure swinging ±10% swings the flow about ±5%, by the square
  root.

So on flow alone:

* **a whole half head shows**;
* **a quarter head is at the edge**;
* **a partly clogged nozzle does not show**.

A pressure sensor on the line, dividing the flow by √(P/P₀), removes most of the
pressure term, and quarter heads come into view.

**A rotor zone**: four 5000s with #3.0 nozzles at 45 psi, 12.36 gpm. One clogged rotor is
**−25%**, plain at any pressure.

**A drip zone**: a hundred 1-gph emitters, 1.67 gpm.

* One clogged emitter is −1%, invisible to any meter.
* A quarter of a line silted up is −25%, plain.
* Drip clogs slowly, so the zone's flow drifting down over weeks is the sign, more than
  any one run.

**Counting is not the limit, if the meter is sized to the zone.**

* The lawn zone through a ¾-inch HC (0.1 gallon a pulse) for ten minutes is about 1,290
  pulses, a counting error under 0.1%.
* The drip zone through a 1-gallon-a-pulse meter for ten minutes is 17 pulses, ±6% from
  counting alone. That needs the finer meter, or a longer run.

## What fieldmesh would build, when this is picked up

1. **A zone's inventory as a record**: its heads and nozzles, and the pressure they were
   set for. From it, the zone's expected flow from the makers' charts, scaled by √P.
2. **Each zone's own flow, learned**: the median of its recent runs, from OpenSprinkler's
   station flow already in the log. It is the bed's-own-soil idea applied to pipes. The
   inventory is the check on what was learned, not the other way round.
3. **An advisory decision for low flow and for high flow**, sized in heads: "zone 3 ran at
   11.1 gpm where it usually runs 12.9: about one half-circle head's worth is not
   flowing". And for drip, a drift over weeks.
4. **A pressure series on the line**, so a pressure drop is not called a clog.

These are notes for later. Nothing here is built ([UNTESTED](../UNTESTED.md) will carry
it when it is).

## Sources

* Rain Bird: [MPR spray nozzle performance charts](https://rainbird.com/sites/default/files/media/documents/2020-09/mpr-spray-nozzle-performance-charts_0.pdf);
  [5000 / 5000 Plus nozzle chart](https://www.rainbird.com/sites/default/files/media/documents/2017-07/chart_5000.pdf);
  [Xeri-Bug drip emitters](https://rainbird.com/products/xeri-bug-drip-emitters).
* Hunter HC Flow meter, pulse rates and accuracy as resellers list them:
  [HC-075-FLOW](https://cheapsprinklers.com/products/hunter-hc-075-flow-3-4-hc-flow-meter-for-hydrawise-npt).
* OpenSprinkler's flow input: [forum, flow meter wiring](https://opensprinkler.com/forums/topic/flow-meter-wiring/);
  its flow alert: the firmware's `services_notifier.cpp` (read 2026-10-11).
* ESPHome and an inductive sensor on a water meter: [example](https://www.bujarra.com/leyendo-el-contador-de-agua-de-casa-con-esphome-y-home-assistant/?lang=en).
* AI-on-the-edge-device and its Dual Use License (2025-01-05):
  [github.com/jomjol/AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device).
