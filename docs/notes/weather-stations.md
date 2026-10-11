<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Weather stations to recommend

Which weather stations a farm on fieldmesh should be pointed to, and the ideas around
them: what to measure, where to put it, how to check it, and how it gets into the log.
Nothing here has been run on a real station yet ([UNTESTED](../UNTESTED.md)).

## What a farm's station is for

* **Watering by the weather.** In the [lawn study](lawn-sprinklers.md), adjusting the
  timer by reference evapotranspiration (ET) was the best single add-on: a third less
  water, no dry hours. ET needs four things:
  * air temperature;
  * humidity;
  * sunshine;
  * wind, at 2 m.

  These come from the farm's own station, or from a forecast (Q26). The
  [irrigation note](irrigation-projects.md) found the probe-less advisory waiting on
  exactly this: humidity is collected already, sunshine is not.
* **Rain.** It tells the soil advisory that rain arrived, and it is the rain sensor a
  controller can skip on.
* **Frost.** The frost watch is scored against a station's air temperature
  ([forecasts](forecasts.md)), and a farm's own low spot is colder than any forecast
  grid.

FAO-56 wants the measurements "at 2 m above an extensive surface of grass or short
crop". Neither a roof nor a fence by the barn will do.

## What makes a station worth recommending

1. **The data stays on the farm.** A local API, or a radio anyone can decode, rather than
   a vendor's cloud the farm reads back from. This is fieldmesh's first principle, and it
   also keeps the station working when the internet is down.
2. **It measures sunshine properly.** Solar radiation is the largest term in ET, and the
   weakest sensor on cheap stations. Some measure light (lux) and convert it to W/m² with
   a fixed factor. Fine Offset's WH24 and WH65B send `light_lux` (`rtl_433`'s decoder,
   `src/devices/fineoffset.c`), and their app shows it as W/m². A pyranometer measures
   the energy itself.
3. **Parts can be replaced**: cups, bearings, the rain funnel, the humidity element.
4. **It speaks an open protocol, or is open hardware.**

## The candidates

| | what it is | measures | reaches fieldmesh | open? | caveat |
| --- | --- | --- | --- | --- | --- |
| **Build it: ESPHome** | An ESP32 with a cup anemometer, vane and tipping bucket, such as SparkFun's Weather Meter Kit: passive reed switches, 0.2794 mm per tip. Add a temperature and humidity sensor in a radiation shield. | wind, rain, temperature, humidity; sunshine only with a pyranometer added | **Today**, through the MQTT bridge's ESPHome profile | firmware and wiring yours | you calibrate and maintain it; the shield matters |
| **Build it: 3D-PAWS** | UCAR and the National Weather Service's international office's 3D-printed station, built locally for a few hundred dollars, with "open-source electronics", used by weather services in many countries | wind, wind direction, rain, temperature, humidity, pressure; no solar sensor in the typical build | Through MQTT or its own outputs (to build) | open designs | a project to build, not a product to buy |
| **Ready-made, cheap: the Fine Offset family** | Sold as Ecowitt, Ambient, Misol and others, read through an Ecowitt gateway (GW1100, GW2000 and others, which serve a local HTTP API with no cloud account) or straight off the air by `rtl_433` | temperature, humidity, wind, rain, light/UV; some models add more | **Today**: off the air through `rtl_433` and the bridge's `rtl_433` profile, or through Home Assistant's MQTT state stream | protocols decoded openly (`rtl_433`, GPL-2.0, 386 device protocols) | sunshine from a light sensor; plastic mechanics |
| **Ready-made: WeatherFlow Tempest** | One unit, no moving parts; the hub broadcasts each minute's observation on the local network (UDP port 50222) | temperature, humidity, pressure, wind, rain by impact, solar radiation | Through Home Assistant today; a UDP listener to build | documented local broadcast | the maker calls the local broadcast a backup to its cloud |
| **Ready-made, durable: Davis Vantage Pro2 with WeatherLink Live** | A long-serving station whose WeatherLink Live unit serves current conditions over local HTTP and broadcasts wind and rain over UDP, both documented | temperature, humidity, wind, rain; solar with the optional sensor | Through Home Assistant today; an HTTP poller to build | documented local API | Davis's AirLink is an air-quality monitor, not this |
| **Research grade: METER ATMOS 41 Gen 2** | All-in-one, no moving parts, SDI-12 or Modbus RTU over RS-485 on enabled units, with its registers documented | solar radiation (±5%), temperature (±0.2 °C at 25 °C), humidity, pressure, wind, rain, lightning | Through fieldmesh's Modbus RTU driver, which reads holding and input registers; the register binding is to build | documented protocol | the most to buy; the way to a pilot's reference station |

**Software that sits between.**

* **WeeWX** (GPL-3.0) drives more than fifty kinds of station and can publish to MQTT
  through an extension.
* **`rtl_433`** decodes 433, 868 and 915 MHz stations through a cheap USB radio dongle
  (an RTL2832 TV stick) and publishes JSON to MQTT.

Either can feed fieldmesh's MQTT bridge, once the bridge has a profile for its topics.

**What I'd recommend:**

| for | station | why |
| --- | --- | --- |
| a farm that builds | ESPHome, with a silicon pyranometer | it works with fieldmesh now |
| a farm that buys cheaply | the Fine Offset family through an Ecowitt gateway | the data stays local |
| a pilot's reference station | ATMOS 41 Gen 2 on Modbus | its sunshine and temperature are what scores everything else |
| a community or school network | 3D-PAWS | it is open, local and built to be maintained |

## Ideas worth doing whatever the station

* **Site it for the question.** For ET, put it 2 m up over grass, away from buildings and
  pavement. For frost, add one cheap temperature node in the farm's lowest, coldest
  spot: that is where frost starts, and the station on the mast will not see it first.
* **Put a manual rain gauge beside the electronic one.** A standard 4-inch gauge is what
  CoCoRaHS volunteers read each morning; the network does not accept electronic gauges.
  It checks the tipping bucket, and a farm can join CoCoRaHS with it.
* **Add rain gauges where the rain differs.** One station gives ET for the whole farm;
  rain varies more over a farm than ET does. A tipping bucket on an ESPHome or Meshtastic
  node per field is cheap.
* **Check the sunshine against the sky.** On a clear day, measured solar radiation should
  come close to FAO-56's clear-sky value, `Rso = (0.75 + 2×10⁻⁵ z) Ra` (eq. 37), and
  never far above it. A reading far above that is wrong. A clear-day ratio sliding down
  over weeks is a dirty or ageing sensor. This is a quality check fieldmesh can run from
  the site's latitude and elevation alone, like its siting check.
* **When there is no sunshine sensor, estimate it.** FAO-56's Hargreaves formula,
  `Rs = 0.16 √(Tmax − Tmin) Ra` (eq. 50; 0.19 near the coast), estimates it from the
  day's temperature range. A pyranometer beats it.
* **Measure wind at 2 m, or convert it.** FAO-56's eq. 47, `u₂ = u_z · 4.87 / ln(67.8 z −
  5.42)`, brings a mast's reading down. A roof-mounted anemometer reads the roof.
* **Share, if the farmer wants to.**
  * The Citizen Weather Observer Program passes stations' data to NOAA's MADIS, which
    checks it and gives quality feedback back.
  * CoCoRaHS maps manual rain reports.

  fieldmesh's grants (§7.6) are how a farm would say yes to either, for a stated
  span, and no to anything else.
* **Avoid a station that only uploads to its maker's cloud.** If the maker goes, the
  station goes with it, and the farm's data was never the farm's.

## What fieldmesh would build next

In the order I'd do them:

1. **The clear-sky check** on solar radiation, beside the range and flatline checks.
   *Built 2026-10-11* (`sdk/checks.clear_sky`, `sdk/sun.py`). On a year of NOAA's
   reference station at Crossville, Tennessee, it raised nothing on healthy readings.
   With faults put in ([tools/clear_sky_scan.py](../../tools/clear_sky_scan.py)):
   * a clock on local time read as UTC was caught on 363 of 366 days;
   * a clock an hour out, on 219;
   * lux sent as watts, every day;
   * a sensor 30% high, on only 46. The check is a ceiling, not a calibration; the
     clear-day ratio over weeks is still to build.
2. **An `rtl_433` profile** in the MQTT bridge. It reaches every cheap station on
   433/868/915 MHz without a vendor's gateway or Home Assistant in between.
   *Built 2026-10-11*:
   * it reads `rtl_433`'s events topic under the decoder's own field names;
   * it takes `-M time:unix` epoch seconds as the reading's time;
   * it reports a station whose id changed with its batteries as unbound, by its new
     name.

   It has been tested against the decoder's source, not yet a station on the air.
3. **A Modbus binding for the ATMOS 41 Gen 2**, for a pilot's reference station.
   *Built 2026-10-11*: [sdk/modbus_collector.py](../../sdk/modbus_collector.py) polls it
   from its register map.
   * It reads input registers 3001–3044 in one burst, as the guide asks, because a read
     resets the station's accumulators.
   * Each reading records the span it covers.
   * Writing the decoder against the guide found a slip in it: its example of the float
     byte order prints 0x471F2000 for 123456.0, which is 0x47F12000.

   Tested with a fake station answering over a pseudo-terminal, not yet a real one.
4. **ET from the farm's own station into the soil advisory**, for beds without a
   probe and for watering by the weather.
5. **Ecowitt's local API, Tempest's broadcast and WeatherLink Live's HTTP API** as
   direct adapters (§10), for farms without Home Assistant.

## Sources

* FAO-56, R. G. Allen et al., 1998, chapter 3 (eqs. 37, 47, 48, 50; station siting).
  [FAO](http://www.fao.org/4/x0490e/x0490e07.htm)
* 3D-PAWS: [UCAR COMET](https://www.comet.ucar.edu/capacity-development/3d-paws-3d-printed-automatic-weather-stations),
  [the station](https://3dpaws.comet.ucar.edu/3d-printed-automatic-weather-station),
  [UCAR RAL](https://ral.ucar.edu/node/4225) ("$200 to $400" to print, at the time).
* `rtl_433`: [github.com/merbanan/rtl_433](https://github.com/merbanan/rtl_433).
* WeeWX: [github.com/weewx/weewx](https://github.com/weewx/weewx); MQTT extension
  [weewx-mqtt](https://github.com/michael-slx/weewx-mqtt).
* Ecowitt's local integration: [github.com/Ecowitt/ha-ecowitt-iot](https://github.com/Ecowitt/ha-ecowitt-iot) (MIT).
* WeatherFlow Tempest UDP broadcast: [apidocs.tempestwx.com](https://apidocs.tempestwx.com/reference/tempest-udp-broadcast).
* Davis WeatherLink Live local API: [weatherlink.github.io](https://weatherlink.github.io/weatherlink-live-local-api/);
  [accessing data from WLL](https://www.manula.com/manuals/pws/davis-kb/1/en/topic/accessing-data-from-wll).
* METER ATMOS 41 Gen 2 Integrator Guide, rev. 05, 2026. [PDF](https://library.metergroup.com/Integrator%20Guide/18036%20ATMOS%2041%20Gen2%20Integrator%20Guide.pdf)
* SparkFun Weather Meter Kit: [sparkfun.com](https://www.sparkfun.com/weather-meter-kit.html).
* Fine Offset's light sensor: `rtl_433`'s [fineoffset.c](https://github.com/merbanan/rtl_433/blob/master/src/devices/fineoffset.c);
  [openHAB Fine Offset binding discussion](https://community.openhab.org/t/fine-offset-weather-station-binding-discussion/134167/56).
* `rtl_433`'s MQTT output and time options: [OPERATION.md](https://github.com/merbanan/rtl_433/blob/master/docs/OPERATION.md).
* CWOP: [NOAA MADIS](https://madis.ncep.noaa.gov/madis_cwop.shtml); CoCoRaHS:
  [NWS](https://www.weather.gov/dtx/cocorahs), [cocorahs.org](https://www.cocorahs.org).
