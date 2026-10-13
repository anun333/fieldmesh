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
| **soil water tension** | how hard roots must pull, the same in any soil; with a moisture probe beside it, the bed's own field capacity and stress point | tensiometer, Irrometer Watermark, METER TEROS 21 | not yet: a term and a reader |
| **electrical conductivity** | salt, which builds up where no rain washes it out | in the TEROS 12, the HydraProbe and the LoRaWAN probes already | not yet: a term, and pore-water EC from the bulk reading |
| **a drainage gauge** | the water that escapes below the roots | a pan or drain gauge under the root zone | a pilot's reference, not a farm's sensor |

## Soil temperature

**Built**, as the [sowing advisory](../../modules/sowing/README.md): each morning, for each
bed and crop, whether the soil at seed depth is warm enough for the seed to germinate, and
about how many days to emergence, from J. F. Harrington's tables (1954). The probe is found
by its installation, as the moisture advisory finds its probes.

Other uses, not built:

* **Under a tunnel**, the soil's stored heat carries the crop through a cold night. The
  [hoop-house twin's](../../modules/twin/) frost watch starts each night from soil
  temperatures estimated from the weeks before; a probe in the tunnel's soil would give
  it the real ones.
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

What fieldmesh needs: a term for soil water potential (already the fourth item in
[soil sensors](soil-sensors.md)), a reader for one of these, and then the pairing.

## Electrical conductivity: salt

Under a tunnel no soaking rain washes salts below the roots, while fertilizer, compost and
hard water keep adding them, so salt builds up season after season; electrical
conductivity is how it is measured ([University of Maryland Extension, Little and
Ristvey, 2021](https://extension.umd.edu/resource/salinity-matters-high-tunnels-and-growing-media-how-interpret-salinity-test-results)).
A soil test sees it a few times a year; a probe sees it climb between them.

The probes that report it give the **bulk** soil's conductivity, which rises with the
water in the soil and its temperature as well as with salt. Crop limits are in the
conductivity of the soil's water, so the reading has to be converted first, from the
moisture and temperature the same probe reports. What fieldmesh needs: a term, that
conversion, and a check for a tunnel bed whose salt is climbing.

## A drainage gauge

It measures what drains past the roots: the "drained" column of every backtest in this
repository, and the one thing nothing on a real farm measures. It belongs at a pilot's
reference bed, to check the simulator against, rather than on every farm.

## Not worth it yet

* **Nitrate and pH electrodes left in the soil** drift and do not last; a lab test a few
  times a season is cheaper and more trustworthy.
* **Soil oxygen and carbon dioxide** sensors are research instruments in price, for narrower
  questions: waterlogging, soil respiration.

## For a first real bed

Choose moisture probes that report temperature and conductivity too (a TEROS 12, or a
LoRaWAN probe), not the bare capacitive boards, and put one tension sensor beside one of
them. That one bed then feeds the moisture advisory, the sowing advisory, and, once their
terms exist, the soil's own retention curve and its salt.

## Sources

* J. F. Harrington, University of California at Davis, Agricultural Extension Leaflet,
  1954, as reproduced by [Oregon State University Extension](https://extension.oregonstate.edu/gardening/soil-compost/soil-temperature-conditions-vegetable-seed-germination)
  (2013, reviewed 2024) and a [University of California handout](https://ccfruitandnuts.ucanr.edu/sites/default/files/2021-01/343966.pdf).
* N. Little and A. Ristvey, [Salinity matters in high tunnels and growing media](https://extension.umd.edu/resource/salinity-matters-high-tunnels-and-growing-media-how-interpret-salinity-test-results),
  University of Maryland Extension, updated 2021-01-27.
* Watermark: [Oregon State University, granular matrix sensors](https://agsci.oregonstate.edu/mes/irrigation/granular-matrix-sensors).
