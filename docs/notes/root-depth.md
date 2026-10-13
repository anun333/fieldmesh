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
* **Root signs from the probes** (`root_signs`), over the last two weeks. On the days a
  probe's soil started at or below field capacity and nothing wetted it:
  * a probe whose soil stayed level has no roots;
  * one whose soil fell and went 0.02 below field capacity has roots.

  Where a probe the curve says the roots passed at least 10 cm ago stays level, under one
  that has roots, the advice counts the roots only to halfway between the two. It also
  writes a note asking for the bed's rooting limit.
* **The probes only make the advice water sooner.** Roots seen deeper than the curve are
  not counted, because soil can also dry by other routes.

On thirty simulated summers of tomatoes over a pan at 30 cm, the curve alone left the
crop short every summer, for a month on average. The root signs cut that by 99%, and the
limit set by hand cut it further, to 20 hours in thirty summers. With no pan, the signs
changed nothing. The full table is in the [advisory's
README](../../modules/soilwater/README.md#roots-that-stop).

## Next

* **Degree-days as the crop's clock**, in place of FAO-56's fixed days. AquaCrop-OSPy's
  crop parameters are under Apache 2.0, so they can be used with attribution. The
  air-temperature series that weather stations already report is enough for them.
* **The stair-step itself as the sign**, a fall by day greater than the fall by night. It
  is a stronger test than the fall below field capacity, because drainage runs day and
  night. It needs to know when the farm's day is: the station's settings carry its
  timezone, so a farm with a station has it.
* Deciding the curve's shape, straight or the *n*th root, with real probes at several
  depths through a season.

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
* McAllister Farm's weather: NASA POWER daily, 1991 to 2020, CC BY 4.0.
