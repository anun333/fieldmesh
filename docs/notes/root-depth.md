<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# How deep the roots are, through a season

*Written 2026-10-13. Two questions: how a well-watered crop's root depth runs with time,
and what on a farm shows how deep the roots actually are. The [soil-moisture
advisory](../../modules/soilwater/README.md#a-crop-that-grows) needs the answer every morning:
the root depth sets how much water the bed holds for the crop, and so when to water and
how much.*

## The curves

Three ways root depth is modelled over a season, for a crop that is not short of water:

| | clock | shape | from, to | full depth reached |
| --- | --- | --- | --- | --- |
| **FAO-56** (Allen et al., 1998), what fieldmesh uses | days | a straight line | 0.15–0.20 m at sowing (Annex 8) to Table 22's maximum | when mid-season begins (Annex 8, Eq. 8-1, taken by time) |
| **AquaCrop** (FAO, reference manual ch. 3) | days, or growing degree-days | the *n*th root of time: fast early, slowing towards the end | from the minimum effective depth, 0.2–0.3 m, to the crop's maximum | at the crop's own time *t*x, which is set apart from the canopy's |
| **Pedersen and Thorup-Kristensen** | degree-days | a straight line after a lag | `Rz = (ΣT − Tlag)·kr + zmin`, at most `zmax` | when the line reaches `zmax` |

**AquaCrop** (Eq. 3.6a): `Z = Zo + (Zx − Zo)·((t − t0/2) / (tx − t0/2))^(1/n)`. The roots
start deepening at half the time to emergence, `t0/2`. With `n` = 1 they deepen at a
steady rate; above 1 they deepen fastest just after planting. Their average rate is capped
at 5 cm a day. The manual keeps roots and canopy apart: the time to the full canopy is set
independently of the time to the deepest roots, so "the interdependence between root and
shoot is not tight". A crop's height or cover is therefore no measure of its roots. Across
the 65 crops with both in FAO-56's Tables 12 and 22, maximum height and maximum root depth
correlate only loosely (r = 0.52).

**Pedersen and Thorup-Kristensen** fitted the straight line to the roots of vegetables at
the Danish Institute of Agricultural Sciences, leek, carrot, cabbage and beetroot among
them. Their crops' rates are not legible in the archived copy, so none are quoted here.

### Tomatoes, side by side

* **FAO-56 in fieldmesh:** 15 cm at sowing to 70 cm on day 70, of a 145-day season.
* **AquaCrop's parameters, as AquaCrop-OSPy ships them** (`TomatoGDD`, transplanted):
  0.3 m to 1.0 m by 891 degree-days, of 1933 to maturity. The base is 7 °C and the upper
  limit 28 °C.

The two end their rooting at nearly the same point in the season: 48% of FAO-56's days
and 46% of AquaCrop's degree-days. The difference is the clock. On McAllister Farm's
thirty recorded summers, planted 1 May, 891 degree-days came after:

* 56 days at the earliest (2018);
* 69 days at the latest (1997);
* 62 days in the median summer.

These counts use the manual's methods 2 and 3, which give the same days here. FAO-56's
fixed 70 days would be:

* about a week late in a typical summer;
* two weeks late in a warm one.

Running late is the safe direction for watering: a root zone counted shallower than it is
gets watered a little sooner.

### "Watered properly" matters to the curve

The curves describe roots growing unhindered. AquaCrop slows root growth in three cases:

* when water stress starts to cut the crop's transpiration;
* when the soil below the roots is too dry;
* in a soil horizon the roots cannot easily penetrate.

That last case is set as a horizon's penetrability: at 0% the roots stop there. A
watering that only ever refills the root zone leaves the soil just below it as it was. In
a dry year that soil can be too dry for roots to enter, which no curve on its own shows.

## What shows how deep they are

* **The stair-step.** Where roots draw water, a probe's reading falls by day and stays
  level at night. As the crop grows, the steps show up at deeper probes. This is how growers
  read root depth off a multi-depth probe (Barrett, *Specialty Crop Grower*, 2018). A probe
  the roots have not reached does not step.
* **Soil well below field capacity.** Drainage slows to almost nothing near field capacity.
  So soil that keeps drying well below it, on days nothing wets it, is soil roots are
  drawing on. Near the surface, the sun dries it too.
* **A spade, a soil probe, a penetrometer.** These find a hardpan, the plough's pan, the
  compacted fill under a new garden, or the bottom of a raised bed. They are direct, and
  worth doing once per bed.
* **Not the canopy.** As above, the canopy's size is no measure of its roots.

## What fieldmesh does with it (built 2026-10-13)

* **`Bed.rooting_limit_mm`:** how deep the soil lets roots go. The crop's curve stops there,
  and a probe set into the pan is not counted.
* **Root signs from the probes** (`root_signs`), over the last two weeks of dry days. A
  probe whose soil stays level has no roots. One that falls has roots if it falls by day
  (the stair-step, where the farm's timezone is known), or, without the clock, if it goes
  0.02 under field capacity; one that falls as fast by night is draining, not drunk.
  Where a probe the curve passed at least 15 cm ago has no roots, under one that has,
  the roots likely stop between the two, and a note asks for the rooting limit.
* **A range of roots, not one depth.** When to water is timed by the shallow end, how much
  by the deep end: each probe's own deficit down to the deepest roots. A stop the probes
  find moves only the shallow end. So does a young planting beside an older one
  (`Bed.plantings`), which is the same problem: plants at different stages side by side.
* **Degree-days as the crop's clock** (`thermal.py`). FAO-56's days are taken as right
  for the farm's normal year, from its past years' weather, and a warm season runs the
  crop ahead of them, a cool one behind, by Paredes et al.'s (2025a) degree-days and their
  review's base and upper temperatures for each crop.

The backtests are in the [advisory's README](../../modules/soilwater/README.md#by-the-seasons-warmth):
the clock, plantings at different stages, and roots that stop. In brief, on thirty
simulated summers: over a pan at 30 cm the curve alone left tomatoes short every summer
for a month, and the root signs cut that by 98% or more, the stair-step alone still
finding the pan where water creeps up beneath it; a young planting of lettuce among
tomatoes, short in 16 summers on the weather's advice for the tomatoes, was never short
once the advice knew both. Timing the curve by degree-days moved a season's water by
−16% to +24% with the season's warmth, and on this farm's margins left no crop short
either way.

## Next

* **Each crop's degree-days for each stage** as the FAO-56 revision gives them (Paredes et
  al., 2025b), in place of FAO-56's days taken at the farm's normal year. That paper is
  open access but its repository would not serve it to a script.
* **Probes for each planting**: a probe that says which planting it is among, so a young
  planting's shallow probe times the watering for it alone.
* **Real beds:** the curve's shape, straight or the *n*th root, the stair-step's
  thresholds against a real probe's noise, and a pan found by its probes and then dug.

## Sources

* R. G. Allen, L. S. Pereira, D. Raes and M. Smith, [*Crop evapotranspiration*](https://www.fao.org/4/x0490e/x0490e0b.htm),
  FAO Irrigation and Drainage Paper 56, 1998: Table 22, and Annex 8.
* FAO, [AquaCrop reference manual, chapter 3: calculation procedures](https://www.fao.org/docs/devbuildingforwardbetterlibraries/default-document-library/chapter3aquacropv73.pdf),
  version 7.3: section 3.6, the effective rooting depth; section 3.3, growing degree-days.
* [AquaCrop-OSPy](https://github.com/aquacropos/aquacrop), `crop_params.py`, Apache 2.0.
* A. Pedersen and K. Thorup-Kristensen, [*Modelling root distribution and rooting depth to
  analyse crop N exploration from different soil depths*](https://orgprints.org/4634/),
  Danish Institute of Agricultural Sciences, archived at Organic Eprints.
* C. Barrett, [Soil moisture sensors improve irrigation](https://specialtycropgrower.com/soil-moisture-sensors-improve-irrigation/),
  *Specialty Crop Grower*, 2018-07-31.
* P. Paredes et al., [Base and upper temperature thresholds to support the calculation of
  growing degree days aiming at their use with the FAO56rev crop coefficients curve: a
  review](https://doi.org/10.1016/j.agwat.2025.109755), *Agricultural Water Management*
  319 (2025) 109755, open access, CC BY 4.0 (2025a).
* P. Paredes et al., [Estimating the lengths of crop growth stages to define the crop
  coefficient curves using growing degree days (GDD): application of the revised FAO56
  guidelines](https://doi.org/10.1016/j.agwat.2025.109758), *Agricultural Water
  Management* 319 (2025) 109758 (2025b); its abstract only, here.
* McAllister Farm's weather: NASA POWER daily, 1991 to 2020, CC BY 4.0.
