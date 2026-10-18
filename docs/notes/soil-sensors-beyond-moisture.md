<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# In the soil, besides moisture: temperature, tension, salinity, drainage

*Written 2026-10-12. The soil-moisture probes are in [soil sensors](soil-sensors.md); this
note is the other things worth putting in the ground, in the order they are worth it to
fieldmesh, and what each would let it do.*

Two of them cost nothing new: most good moisture probes already measure them, and fieldmesh
has been throwing the readings away.

| sensor | what it adds | hardware | in fieldmesh |
| --- | --- | --- | --- |
| **soil temperature** | when a seed will germinate; the soil's heat under a tunnel; degree-days | in most moisture probes already; a bare probe is cheap | **built**: the [sowing advisory](../../modules/sowing/README.md); the frozen-soil check |
| **soil water tension** | how hard roots must pull, the same in any soil; with a moisture probe beside it, the bed's own field capacity and stress point | tensiometer, Irrometer Watermark, METER TEROS 21 | **built**: the term, the Watermark's calibration (`sdk/tension.py`), and field capacity read off the curve beside a probe ([soil-moisture advisory](../../modules/soilwater/README.md#the-beds-own-soil)) |
| **electrical conductivity** | salt, which builds up where no rain washes it out | in the TEROS 12, the HydraProbe and the LoRaWAN probes already | **built**: the [salinity monitor](../../modules/salinity/README.md) |
| **a drainage gauge** | the water that escapes below the roots | a pan or drain gauge under the root zone | a pilot's reference, not a farm's sensor |

## Soil temperature

**Built**, as the [sowing advisory](../../modules/sowing/README.md): each morning, for each
bed and crop, whether the soil at seed depth is warm enough for the seed to germinate, and
about how many days to emergence, from J. F. Harrington's tables (1954). The probe is found
by its installation, as the moisture advisory finds its probes.

Other uses, not built:

* **Under a tunnel**, the soil's stored heat carries the crop through a cold night. The
  [hoop-house twin's](../../modules/twin/README.md) frost watch now starts its soil from
  probes in the tunnel where there are any (built 2026-10-12). It moves the predicted low
  less than expected, about 0.2 °C for 3 °C of soil: the twin's 36-hour warm-up lets the
  top soil follow the air.
* **Pests that overwinter in the soil** are often timed by soil degree-days.
* **The plant advisor's** rice model (`modules/advise/dssat_crops.py`) times germination
  by the sowing day's mean temperature from the weather; a season of a farm's soil
  temperatures could check it.

## Soil water tension

A moisture probe says how much water is there; a tension sensor says how hard the roots
must pull for it. The same moisture means plenty in sand and drought in clay; the same
tension means the same to a root in either. So a tension sensor needs no soil's values to
say when to water, and the moisture advisory's hardest problem, knowing a bed's field
capacity and wilting point, is one it does not have.

**Beside a moisture probe at the same depth, it measures the bed's own soil**: each reading
is a point on that soil's water retention curve, so field capacity and the point of stress
are read off it, not inferred from drain-downs. That is the inference the learned field
capacity makes, the one that drifted until 2026-10-12, and the one the layered yard needs
each layer's values for ([soil-moisture advisory](../../modules/soilwater/README.md#the-beds-own-soil)).

* **Tensiometers** read true tension, wet to moderately dry, and need refilling.
* **Watermark** granular-matrix sensors are read by their electrical resistance, which
  rises as the soil dries. They were made to fix the gypsum block's faults, dissolving and
  losing contact with the soil, and growers find them useful in many soils, not all
  ([Oregon State University](https://agsci.oregonstate.edu/mes/irrigation/granular-matrix-sensors)).
* **METER's TEROS 21** reads it digitally over SDI-12, and much drier.

**Built 2026-10-12.** The term is ODM2's water potential (`vocab.SOIL_WATER_POTENTIAL`); a
Watermark's resistance and the soil's temperature become tension by Shock et al.'s (1998)
calibration, inside the 10 to 75 kPa it holds for (`sdk/tension.py`, the reference a node's
firmware is checked against); and a tension sensor within 2 cm of a moisture probe's depth
gives that probe a measured field capacity, read off the fitted curve at 33 kPa
([soil-moisture advisory](../../modules/soilwater/README.md#the-beds-own-soil)). Not built:
the node that reads a Watermark, and the stress point at 1500 kPa, past a Watermark's
calibration.

## Electrical conductivity: salt

Under a tunnel no soaking rain washes salts below the roots, while fertilizer, compost and
hard water keep adding them, so salt builds up season after season; electrical
conductivity is how it is measured ([University of Maryland Extension, Little and
Ristvey, 2021](https://extension.umd.edu/resource/salinity-matters-high-tunnels-and-growing-media-how-interpret-salinity-test-results)).
A soil test sees it a few times a year; a probe sees it climb between them.

The probes that report it give the **bulk** soil's conductivity, which rises with the
water in the soil and its temperature as well as with salt. Crop limits are in the
conductivity of the soil's water, so the reading has to be converted first, from the
moisture and temperature the same probe reports. **Built 2026-10-12**, as the [salinity monitor](../../modules/salinity/README.md): the term
is ODM2's bulk electrical conductivity (`vocab.BULK_EC`); the pore water's conductivity is
Hilhorst's from the probe's water and temperature, then diluted to a saturated paste's
extract, the scale crop tolerances are in; a bed's crop is set against Maas and Grattan's
tolerances, and the monitor says when its salt climbs toward its threshold and when it
passes it, with the share of the yield lost.

## A drainage gauge

It measures what drains past the roots: the "drained" column of every backtest in this
repository, and the one thing nothing on a real farm measures. It belongs at a pilot's
reference bed, to check the simulator against, rather than on every farm.

## Not worth it yet

* **Nitrate and pH electrodes left in the soil** drift and do not last; a lab test a few
  times a season is cheaper and more trustworthy.
* **Soil oxygen and carbon dioxide** sensors are research instruments in price, for narrower
  questions: waterlogging, soil respiration ([below](#dearer-and-optional)).

## Dearer, and optional

Some instruments a farm need not buy would check what fieldmesh's advice rests on, and
what its virtual farm ([sim/physics.py](../../sim/physics.py)) only assumes. They are
optional hardware: a pilot's reference bed, a farm that wants to know, a study. Each is set
here beside what it would test, and whether the simulator could already make its readings,
so a backtest can ask what owning one would change before anyone buys it.

| instrument | what it measures | what it would check | the simulator |
| --- | --- | --- | --- |
| **soil oxygen** (a galvanic cell in the soil air) | oxygen where the roots are | overwatering's harm: the backtests score it as hours with under a tenth of the root zone holding air (`backtest.Score`), a stand-in for oxygen | not yet: a gas module on the layered soil (diffusion through the air-filled pores, roots and microbes using it) would give its timing well and its level roughly; HYDRUS-1D's CO2 module (Šimůnek and Suarez 1993) would benchmark it |
| **soil carbon dioxide** (an infrared cell in the soil air; open builds cost about USD 700, Nguyen et al. 2025) | soil respiration | little for watering; the soil's life | the same module; NEON's soil CO2 profiles would test it |
| **tension past 1000 kPa** (a METER TEROS 21) | how hard the soil holds its water, as dry as a crop takes it | the wilting point a probe cannot learn (README, not yet), and the simulator's retention curves | yes: each layer's curve gives it (`physics.Horizon.suction_at`) |
| **a research weather station** (a METER ATMOS 41, sonic wind and a pyranometer) | the wind and sunshine a cheap station estimates | the weather balance's stand-ins: with no anemometer FAO-56 assumes 2 m/s, where McAllister's summers average 1.0 and Davis's 2.7 ([soilwater trials](../../modules/soilwater/README.md#what-the-trials-show)) | yes: the balance can be given the recorded wind and sunshine |
| **a weighing or drainage lysimeter** | the bed's own water use and drainage | the weather's margin, which guesses how far a station's balance is from a bed's use; the simulator's crop | its own use, so circular: on a farm, the one instrument that measures what the margin guesses |
| **reference probes in pairs** (Stevens HydraProbes) | the soil's water, to a percent | each probe's calibration error, which the backtests now draw (0.015, `backtest.VirtualFarm`), and drift | yes, as error models |
| **a profile probe at many depths** | the water at every 10 cm | the simulator's roots, densest at the top, and the root signs' level line ([roots that stop](../../modules/soilwater/README.md#roots-that-stop)) | yes: every layer's water |
| **canopy temperature or sap flow** | the crop's own stress | whether a crop loses transpiration when the backtests say it does | not without a leaf's energy balance |

## For a first real bed

Choose moisture probes that report temperature and conductivity too (a TEROS 12, or a
LoRaWAN probe), not the bare capacitive boards, and put one tension sensor beside one of
them. That one bed then feeds the moisture advisory, the sowing advisory, and, once their
terms exist, the soil's own retention curve and its salt.

## Sources

* J. Šimůnek and D. L. Suarez, "Modeling of carbon dioxide transport and production in
  soil: 1. Model development", *Water Resources Research* 29(2), 1993, 487–497,
  [doi:10.1029/92WR02225](https://doi.org/10.1029/92WR02225).
* T. T. Nguyen, N. Bekin, A. Altman, M. Maier, N. Agam and E. Levintal, "Overcoming barriers
  in long-term, continuous monitoring of soil CO2 flux: a low-cost sensor system", *SOIL*
  11, 2025, [doi:10.5194/soil-11-639-2025](https://doi.org/10.5194/soil-11-639-2025).

* J. F. Harrington, University of California at Davis, Agricultural Extension Leaflet,
  1954, as reproduced by [Oregon State University Extension](https://extension.oregonstate.edu/gardening/soil-compost/soil-temperature-conditions-vegetable-seed-germination)
  (2013, reviewed 2024) and a [University of California handout](https://ccfruitandnuts.ucanr.edu/sites/default/files/2021-01/343966.pdf).
* N. Little and A. Ristvey, [Salinity matters in high tunnels and growing media](https://extension.umd.edu/resource/salinity-matters-high-tunnels-and-growing-media-how-interpret-salinity-test-results),
  University of Maryland Extension, updated 2021-01-27.
* Watermark: [Oregon State University, granular matrix sensors](https://agsci.oregonstate.edu/mes/irrigation/granular-matrix-sensors).
