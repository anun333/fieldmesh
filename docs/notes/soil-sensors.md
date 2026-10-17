<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Soil moisture sensors to recommend

Which soil probes a farm on fieldmesh should be pointed to, how each reaches the log, and
what fieldmesh's own evidence says about choosing and installing them. It is the soil
side of [weather stations](weather-stations.md). None of the makes below has been run on
a fieldmesh farm yet ([UNTESTED](../UNTESTED.md)).

## What a probe has to give

* **Volumetric water content** (`cm3/cm3`), the quantity the soil advisory works in.
  A probe reports a raw number; the calibration that turns it into water content is its
  own record (§3.2), versioned, so a recalibration never rewrites history.
* **Soil temperature from the same body.** The frozen-soil check needs it: a frozen
  probe reads falsely dry. So does the depth check, which reads a probe's depth from its
  daily temperature wave (§4.1, [siting-real-soil](siting-real-soil.md)).
* **A depth and a cover, recorded on its installation**, so the advice weights it right
  and the depth check compares like with like.
* **A second probe in the bed.** One probe cannot see its own drift. The cross-check
  between two probes on one feature can (§4.2: "a feature with one sensor has no drift
  detection, and drift is the commonest real failure").
* **A way into the log**: MQTT, LoRaWAN through ChirpStack, Modbus, or a node.

## What fieldmesh's checks were proven on

The health checks were scored against ISMN's independent quality flags on two
networks' probes in and around Tennessee ([ismn-scoring](ismn-scoring.md)), both Stevens
Hydra Probes:

* NRCS's SCAN, 2.2 million good readings;
* NOAA's Climate Reference Network, 1.5 million.

In the top 20 cm the checks flagged 0.02% to 0.29% of the readings ISMN rates good.

That is evidence for the checks on that kind of probe. On a cheap capacitive probe, their
thresholds are untested.

## The candidates

| | what | measures | interface | reaches fieldmesh | accuracy | caveat |
| --- | --- | --- | --- | --- | --- | --- |
| **Stevens HydraProbe** | Coaxial impedance at 50 MHz; three at each depth in every USCRN station | water, temperature, conductivity | SDI-12, RS-485 ASCII, or Modbus RS-485 | Modbus version through the Modbus collector, once its register map is written; SDI-12 version through a node (below) | sellers quote ±1.2% between probes | the most proven here; costs the most |
| **METER TEROS 11 / 12** | Capacitance at 70 MHz, a litre of soil sensed | water, temperature; the 12 adds conductivity | SDI-12 | Through an SDI-12 node (below) | ±3% with the generic calibration, ±1–2% calibrated to the soil (maker) | METER's own loggers and cloud are not needed |
| **LoRaWAN probes: Dragino LSE01 / SE01-LB, Milesight EM500-SMTC** | A probe on a battery radio node, years on a battery | water, temperature, conductivity | LoRaWAN | **Today**, through ChirpStack and the bridge's ChirpStack profile, with the maker's payload decoder in ChirpStack | Milesight quotes ±2% from 0 to 50% | the radio is LoRaWAN, not Meshtastic (Q6); the decoder is the maker's |
| **Capacitive v1.2** (DFRobot SEN0193 and its many clones) | A capacitance board with an analog output | water only | analog | **Today**, through an ESPHome node's ADC | 12 tested in a silt loam: 4.5–4.9% RMSE even with that soil's own calibration, and 10–16% variation between units when wet (Abdelmoneim et al. 2025) | a trend, not a measurement, until each is calibrated; no temperature |
| **An open SDI-12 probe** | A 555-timer capacitance design with an AVR, published openly | water | SDI-12, or 0–5 V analog | Through an SDI-12 node | ±5–6% after calibration in three soils (González-Teruel et al. 2019) | a design to build, not a product |
| **Irrometer Watermark** | A granular-matrix sensor | soil water **tension** in kPa (centibars), not water content | resistance, read with AC | Its term and calibration are built (`sdk/tension.py`, Shock et al. 1998), and beside a moisture probe it gives that probe a measured field capacity; the node that reads its resistance is not | Shock et al.'s calibration holds from 10 to 75 kPa | measures what the plant feels; set by kPa thresholds from extension guides |

**The way to SDI-12 probes is a node.** Most research probes speak SDI-12, and fieldmesh
has no SDI-12 driver. EnviroDIY's Arduino-SDI-12 library (LGPL-2.1) talks to them from
an ESP32 with no extra hardware. That node would publish through ESPHome or MQTT, which
the bridge already reads.

## What I'd recommend

| for | probe | why |
| --- | --- | --- |
| a pilot's reference bed | two Stevens HydraProbes (Modbus) or TEROS 12s, at the root zone's middle and below it | the checks were proven on HydraProbes, and two probes catch each other's drift |
| a deep-rooted crop (tomatoes, squash, corn) | a third probe in the deeper half of its roots, at about 60 cm | with probes at 10 and 30 cm, tomatoes were short in 5 summers of 30; with one at 60 cm too, never ([soil advisory](../../modules/soilwater/README.md#a-crop-that-grows)) |
| a farm on LoRaWAN | a Dragino or Milesight probe, two per bed | it works with fieldmesh today |
| a farm that builds | capacitive v1.2 on ESPHome, only in pairs, each calibrated in that soil | it is cheap, but a trend until calibrated |

## What fieldmesh's own evidence says about choosing and installing

* **A probe that reads low is forgiven; one that reads high is not.** On the advisory's
  backtest bed, McAllister Farm's 2013, a true probe's advice used 208 mm (the simulator
  of 2026-10-16).
  * A probe reading 0.05 low, unlearned, called for 1,045 mm. Learning its own field
    capacity from its drain-downs, which are 0.05 low too, it used 422 mm.
  * A probe reading 0.05 high says the bed is fuller than it is, so the bed is watered
    late and little, 127 mm. The probe then sees too few soakings to learn from, and the
    bed went dry: 293 hours of stress.
  * Learning cannot fix this, because the bias stops the very watering it would learn
    from. A second probe can.

  ([TestAProbeThatReadsOff](../../modules/soilwater/test_soilwater.py))
* **Learn the bed's own field capacity rather than trusting the survey's.** In a
  landscaped yard the survey's values drowned the bed. The bed's own drain-downs did not
  ([the bed's own soil](../../modules/soilwater/README.md#the-beds-own-soil)).
* **Probes in two soils say so.** Two probes whose learned capacities differ by 0.08 or
  more raise a note asking for each layer's values.
* **Calibrate a set point to the soil, never to a default.** A soil sensor's set point
  left at the Florida guide's middle starved a silt-loam lawn
  ([lawn sprinklers](lawn-sprinklers.md)).
* **Put the probe where the roots are.** About 3 inches deep for turf (UF/IFAS AE437);
  for beds, the middle of the root zone, with a second probe below it to show water
  leaving.
* **Record the cover.** Mulch and sod read as extra depth to the depth check, unless the
  cover is on the installation.
* **Avoid a probe whose readings only reach its maker's cloud**, for the same reason as
  a weather station.

## What fieldmesh would build next for probes

*Temperature, tension, salinity and drainage, the other things worth putting in the soil, are in
[soil sensors beyond moisture](soil-sensors-beyond-moisture.md); soil temperature is built, as
the [sowing advisory](../../modules/sowing/README.md).*

1. **An SDI-12 node**: an ESP32 with Arduino-SDI-12, publishing through ESPHome. It
   reaches the HydraProbe, the TEROS and most research probes.
2. **A HydraProbe Modbus map** in the Modbus collector, from Stevens' register
   documentation.
3. **A "wet too long" note**: a probe that reads wetter than field capacity for days with
   no rain and no watering is reading high, or the bed is waterlogged. Either needs a
   person.
4. **A term for soil water potential**, for the Watermark and tensiometers. *Built 2026-10-12*
   ([beyond moisture](soil-sensors-beyond-moisture.md#soil-water-tension)).
5. **A calibration by known water.** A measured amount poured over a measured square
   around the probe, say 10 litres on one square metre, is 10 mm. The probe's rise
   against the rise those 10 mm should make measures its gain, and its drain-down
   afterwards measures the level it settles at.
   * *Built 2026-10-12* as the soak test, a regimen that leads a person through it: pour
     this much here, wait, check the rise, and two days later read the level it drained
     back to ([soil-moisture advisory](../../modules/soilwater/README.md#a-soak-test-field-capacity-on-the-day)).
   * The sprinkler doing it on its own is a command, and waits for §6.

   It would also catch a probe reading high, which learning cannot.

## Testing without a probe

openSenseMap's public stations include soil probes, TRUEBNER SMT50s and Dragino LSE01s
among them, readable without a key: `tools/opensensemap_collect.py` brings one station's
soil series into a log through the checks ([test data sources](test-data-sources.md)).

## Sources

* Stevens HydraProbe: [Fondriest](https://www.fondriest.com/stevens-hydraprobe-soil-moisture-sensors.htm) (interfaces, probe-to-probe figure);
  USCRN's use: [NOAA NCEI, Stevens Hydra Probe SDI-12](https://ncei.noaa.gov/pub/data/uscrn/documentation/site/sensors/soil/Descriptions/Soil_StevensHydra-SDI-12.pdf).
* METER TEROS 11/12: [tech specs](https://metergroup.com/products/teros-11/teros-11-tech-specs/).
* Dragino LSE01: [user manual](https://docs.dragino.com/docs/LoRaWAN-End-Node/soil-agriculture-sensors/lse01/);
  Milesight EM500-SMTC: [product docs](https://www.milesight.com/products/docs/en/em500-smtc/steps/em500/em500-smtc-description.html).
* A. A. Abdelmoneim et al., "Calibration of low-cost capacitive soil moisture sensors for
  irrigation management applications", *Sensors* 25(2), 343, 2025.
  [doi:10.3390/s25020343](https://doi.org/10.3390/s25020343)
* J. D. González-Teruel et al., "Design and calibration of a low-cost SDI-12 soil
  moisture sensor", *Sensors* 19(3), 491, 2019. [doi:10.3390/s19030491](https://doi.org/10.3390/s19030491)
* EnviroDIY Arduino-SDI-12: [github.com/EnviroDIY/Arduino-SDI-12](https://github.com/EnviroDIY/Arduino-SDI-12).
* Watermark: [Oregon State University, granular matrix sensors](https://agsci.oregonstate.edu/mes/irrigation/granular-matrix-sensors).
* UF/IFAS AE437 (probe depth for turf): [EDIS](https://ask.ifas.ufl.edu/publication/AE437).
