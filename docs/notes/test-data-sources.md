<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Real devices to test against, without owning them

*Written 2026-10-13, from a question: are there sites, vendors' or others', that give free
access to hardware's data, so fieldmesh can be tested before a farm has any? Each was
tried, or its documentation read, on that day.*

| source | what it gives | access | in fieldmesh |
| --- | --- | --- | --- |
| **[openSenseMap](https://docs.opensensemap.org/)** | every reading of thousands of citizen stations, some with soil probes: on 2026-10-13, 19 had reported soil water in the last day, from TRUEBNER SMT50s and Dragino LSE01s | open REST API, no key; data under the Open Data Commons Public Domain Dedication and Licence 1.0 | **built**: `tools/opensensemap_collect.py` reads a station's soil series into a log, through the quality checks |
| **OpenSprinkler's own firmware, demo build** | the real controller firmware, run on Linux with no hardware: its web API and its MQTT messages | GPL-3.0 source; `make VERSION=DEMO`, or its Dockerfile with `BUILD_VERSION=DEMO` | **checked**: the MQTT bridge's OpenSprinkler profile against what 2.2.1(6) published (`tools/fixtures/opensprinkler-demo-mqtt.log`) |
| **[Synoptic Data](https://synopticdata.com/mesonet-api), Open Access** | public weather networks' stations, current and past, including state mesonets' and SCAN's soil moisture | free account and token | not built; NRCS SCAN is already read directly (`tools/scan_collect.py`) |
| **The Things Stack Sandbox** | a LoRaWAN network server; its command line simulates a device's uplinks | free, for non-commercial testing | not built; the bridge's ChirpStack profile is the LoRaWAN path today |
| **CWOP, through APRS-IS and findU** | live reports of thousands of home weather stations, many of them Davis and Ambient | free | not built |
| **ThingSpeak public channels** | anyone's published channels, some with soil probes | no key for a public channel | not built: quality varies, and the soil channel found had stopped in 2019 |

**Makers whose APIs need their own device or account**, with no public demonstration found:
Ecowitt, Davis WeatherLink, Tempest, METER ZENTRA Cloud, Onset HOBOlink. Their stations'
**local** protocols are read already (`sdk/station_adapters.py`: Tempest's UDP broadcast,
the WeatherLink Live's HTTP API, an Ecowitt gateway's custom upload), and those are tested
against the makers' published examples.

## What the first runs showed

* **openSenseMap's LSE01 station labels its conductivity in ohms**, which a conductivity
  is not. The reader leaves it out and says why, rather than guess a unit.
* **That LSE01 reads 2.1 to 2.4% soil water**: very dry sand, or a probe out of the soil.
  It passes the checks, being in range and moving. A probe out of the ground is a check
  fieldmesh does not have yet.
* **The SMT50's 34 readings** in six hours, thinned to one each ten minutes, all passed.
* **OpenSprinkler's firmware published** a station opening and closing with its duration,
  a rain delay set and cleared, and a program starting with its water level and its
  weather, sensor and total scales. The bridge parsed every one. It had not mapped the
  weather scale (`wa`), which its own description promised; it does now. The firmware's
  `availability` message is a plain word, `online`, not JSON. Changing the water level by
  hand and asking for a reboot published nothing in the demo build, so those topics are
  still unchecked.

## Running OpenSprinkler's demo firmware

    git clone https://github.com/OpenSprinkler/OpenSprinkler-Firmware fw
    cd fw && git submodule update --init --recursive
    docker build --build-arg BUILD_VERSION=DEMO -t opensprinkler-demo .

Its own Dockerfile adds the Raspberry Pi package repository even for the demo; a smaller
image is Debian with `g++ make libmosquittopp-dev libssl-dev`, `make VERSION=DEMO`, and the
binary run as `OpenSprinkler -d /data`. The demo build serves HTTP on port 80, not the
8080 its README gives for the Raspberry Pi build. The default password is `opendoor`,
sent as its MD5. MQTT is set with `/co?pw=…&mqtt={"en":1,"host":…,"port":1883,"pubt":"opensprinkler",…}`,
and nothing is published until the notification options `ife` and `ife2` enable it.
