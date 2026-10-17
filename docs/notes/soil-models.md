<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Soil water models: how others do it, and what the simulator takes

*Written 2026-10-16. The soil advisory is backtested on a simulated farm
([sim/physics.py](../../sim/physics.py)), and its results turn on how that soil moves
water: on 2026-10-15 the simulator's layered soil began to move water below field
capacity, and several results changed ([soil advisory](../../modules/soilwater/README.md#water-below-field-capacity)).
This note sets the simulator beside the models agriculture already uses, and lists what
it lacked. Found through Semantic Scholar and the models' own documentation and source.
On 2026-10-16 the simulator took what the list [below](#what-the-simulator-took-2026-10-16)
asked for, and was checked against HYDRUS-1D and a real profile.*

## The models

| model | water below field capacity | root uptake | evaporation from the soil | code and licence |
| --- | --- | --- | --- | --- |
| FAO-56 / pyfao56 | none: one bucket | from the root zone | the dual crop coefficient: an evaporation layer of 0.10 to 0.15 m | [pyfao56](https://github.com/kthorp/pyfao56), CC0 |
| AquaCrop / AquaCrop-OSPy | none: a compartment drains only above field capacity (`drainage.py`); capillary rise only from a water table | by root zone | its own evaporation layer | [AquaCrop-OSPy](https://github.com/aquacropos/aquacrop), Apache-2.0 |
| DSSAT | a tipping bucket drains each layer above its drained upper limit; capillary rise | by root length in each layer and the water it holds (Ritchie 1998) | Ritchie's first stage, or Suleiman and Ritchie | [dssat-csm-os](https://github.com/DSSAT/dssat-csm-os), BSD-3-Clause |
| APSIM | the SoilWater bucket, with an unsaturated flow term (`DiffusConst`, `DiffusSlope`); or SWIM, Richards' equation | each layer's extraction rate (`kl`) where roots are | yes | [ApsimX](https://github.com/APSIMInitiative/ApsimX), its own general use licence |
| PCSE / WOFOST | a bucket, in classic WOFOST | from the root zone | yes | [PCSE](https://github.com/ajwdewit/pcse), EUPL-1.1 |
| HYDRUS-1D | Richards' equation, van Genuchten and Mualem | Feddes' function, with root density | yes | freeware from PC-Progress; [phydrus](https://github.com/phydrus/phydrus) and its adapted Fortran, LGPL-3.0 |
| SWAP | Richards' equation | Feddes', or de Jong van Lier's matric flux potential | yes | an [unofficial mirror](https://github.com/SWAP-model/SWAP), GPL-2.0 |
| **fieldmesh's simulator** | **Darcy's law between layers, van Genuchten fitted to each horizon's limits with Rosetta3's residual water, Mualem's conductivity with Rosetta3's `L`, their geometric mean, since 2026-10-15** | **FAO-56's: whole to the crop's `p`, then less; by root density, falling in a line to none at the roots' depth (Prasad 1988), since 2026-10-16** | **FAO-56's dual coefficient, from the top 0.10 m, since 2026-10-16** | Apache-2.0 |

So the simulator's soil before 2026-10-15 was the crop models' bucket: FAO-56's,
AquaCrop's, near enough DSSAT's. Since then it moves water as the Richards models do,
though layer by layer and explicitly rather than by solving the equation.

## What the literature says about the choices made

* **Leaving out flow below field capacity matters.** Chen, Huo and Xu (2019) name the
  Williams–Ritchie model, AquaCrop and Hydrobal as omitting it, and show the omission
  misstates water productivity where groundwater is deep. Faria and Bowen (2003) found
  DSSAT's unsaturated flux poor on bare soil, and better with Darcy's law on the
  potential gradient between layers, the simulator's approach now. EPIC gained a Richards
  option for the same reason (Longo et al. 2021), and DSSAT has been coupled to HYDRUS-1D
  (Shelia et al. 2018).
* **The conductivity between two layers.** Of eight ways to average it, the arithmetic,
  geometric and triadic means did well for infiltration into layered soil (Chen, Mao and
  Barry 2019). The simulator takes the geometric mean; the arithmetic would move water
  faster, the harmonic slower ([soil advisory](../../modules/soilwater/README.md#water-below-field-capacity)).
* **An explicit layered balance can match the full equation.** Ruiz-Hermo et al. (2026)
  built one with infiltration, evaporation, capillary redistribution, transpiration and
  drainage: it matched HYDRUS-1D to 1.19 mm over a 120-day strawberry season, in 3% of the
  time, and was then checked against a greenhouse's probes at several depths.
* **Root uptake.** Feddes et al. (1976) reduce uptake with the soil's suction; de Jong van
  Lier et al. (2008) spread it by the matric flux potential; DSSAT by root length in each
  layer. Until 2026-10-16 the simulator drew from each layer by the water it could give,
  and the crop slowed its use as soon as the root zone was below field capacity
  (`1 − stress`), where FAO-56 keeps it whole until the crop's `p`. Both made the virtual
  crop gentler than these. It now keeps FAO-56's, and draws by Prasad's (1988) linear root
  density, most at the top.
* **Evaporation from the soil.** FAO-56's dual coefficient dries an evaporation layer of
  0.10 to 0.15 m apart from the crop (Allen et al. 2005). Until 2026-10-16 the simulator
  had none, so a bare patch lost nothing and the top centimetres dried only by roots; it
  now dries its top 0.10 m so. Evaporation also lowers
  the level a soil drains to after a wetting (Aldrees and Hafsi 2020): a probe near the
  surface reads field capacity low.
* **Field capacity, measured.** Ottoni et al. (2014) define it as the water held 48 hours
  after a ponded soaking, and found it depended little on how much water went in or how
  wet the soil had been. The advisory learns it from every drain-down; on the simulator's
  soil since 2026-10-15, the drain-downs after light waterings over drier soil read low.
  Learning from soakings alone, or from the [soak test](../../modules/soilwater/README.md#a-soak-test-field-capacity-on-the-day),
  is what the definition asks.
* **Learning a soil from its probes.** Gong et al. (2025) find wettings and fit each
  drydown automatically from probe series, as the advisory's `drain_downs` does. Sonkar et
  al. (2019) found probe readings alone did not pin down both a soil's hydraulic
  properties and its root uptake; deep percolation as well did.
* **Where probes go, and what their error costs.** Soulis et al. (2015) and Soulis and
  Elmaloglou (2018, layered soils) placed probes with simulations of drip irrigation;
  Sharma, Irmak and Kukal (2021) carried nine sensors' errors through to irrigation
  triggers. Paraskevopoulos and Singels (2014) combined probes with a weather-driven
  crop model, as the advisory's probe correction does.

## Where a soil's own parameters come from

The simulator fits each horizon's curve through three points of its own: saturation, field
capacity at 33 kPa, the wilting point at 1500 kPa. Since 2026-10-16 the residual water and
Mualem's `L` are Rosetta3's for each of its soils' texture and bulk density; before, no
residual and `L` 0.5. Better sources for all of it:

* **Rosetta** (Schaap et al. 2001; recalibrated by Zhang and Schaap 2017): van Genuchten's
  parameters and the saturated conductivity from texture, and bulk density or the 33 and
  1500 kPa water contents where known, with their uncertainty. [rosetta-soil](https://github.com/usda-ars-ussl/rosetta-soil),
  CC0. `tools/soil_survey.py` already reads a field's texture from the soil survey.
* **POLARIS** (Chaney et al. 2019): van Genuchten and Brooks–Corey parameters, texture
  and conductivity mapped at 30 m over the contiguous United States, as distributions; its
  in-situ evaluation gave an average R² of 0.41. Its data licence was not found; check it
  before redistributing anything from it.

## What the simulator took, 2026-10-16

The list this note first ended with, in order, and what each did:

1. **Checked against a reference model and a real profile.** HYDRUS-1D, through phydrus
   in a container (an outside benchmark, not a dependency of fieldmesh), on the same
   soils: the simulator's water content was within 0.0002 to 0.002 of it, as root mean
   square error, while water spread and rose by capillarity, and 0.002 to 0.012 while a
   watering soaked in. The soil before 2026-10-15 was 0.012 to 0.040 out. USCRN's
   Crossville, Tennessee station, under grass: the simulated soil followed its
   probes hour by hour, correlation 0.85 to 0.96.
2. **The crop's use whole to its `p`, drawn by root density.** On Crossville's 98
   rain-free summer days, the soil before this dried at 5 cm at 0.56 of the rate the
   probes saw, at 10 cm 0.71, at 20 cm 1.12. FAO-56's use took 5 and 10 cm to 0.71 and
   0.90; drawing by root density, 5 cm to 0.75 and 20 cm from 1.37 to 1.31. With the
   evaporation below as well: 0.74, 0.85 and 1.26.
3. **Evaporation, FAO-56's dual coefficient.** In the simulator, and in the advisory's
   weather balance for a bed whose crop is named, so that a young crop's wet soil is
   counted. FAO-56's estimate of a canopy's cover from its basal coefficient (Eq. 76)
   leaves a mown lawn a third bare, and so evaporating a quarter more than FAO-56's own
   coefficients for turf; a lawn is taken to cover 0.95 of its ground.
4. **A pan that passes little water**: a 5 cm horizon of compacted silt loam, saturated
   conductivity 0.5 mm an hour, as an option of the growing bed (`growing_bed(pan_mm=…)`).
5. **Rosetta3's residual water and `L`** for each of the simulator's soils, in the three-point
   fit; not yet its whole curve.

At Crossville the simulated top 5 cm still dried at three quarters of the observed rate,
and 20 cm a quarter faster: the roots' depth and shape under that grass, and the probes'
own calibration, are not known. Every table in the [soil advisory](../../modules/soilwater/README.md)
was run again on it, three draws of the noise each.

## Sources

* R. G. Allen, L. S. Pereira, D. Raes and M. Smith, *Crop evapotranspiration: guidelines for
  computing crop water requirements*, FAO Irrigation and Drainage Paper 56, Rome, 1998.
* R. G. Allen, L. S. Pereira, M. Smith, D. Raes and J. L. Wright, "FAO-56 dual crop
  coefficient method for estimating evaporation from soil and application extensions",
  *Journal of Irrigation and Drainage Engineering* 131(1), 2005, 2–13, [doi:10.1061/(ASCE)0733-9437(2005)131:1(2)](https://doi.org/10.1061/(ASCE)0733-9437(2005)131:1(2)).
* A. Aldrees and A. Hafsi, "Impact of evaporation on field capacity during water drainage
  redistribution in a soil", *Hydrological Processes* 35, 2020, [doi:10.1002/hyp.14028](https://doi.org/10.1002/hyp.14028).
* N. W. Chaney et al., "POLARIS soil properties: 30-m probabilistic maps of soil properties
  over the contiguous United States", *Water Resources Research* 55, 2019, 2916–2938,
  [doi:10.1029/2018WR022797](https://doi.org/10.1029/2018WR022797).
* S.-L. Chen, Z. Huo, X. Xu and G.-H. Huang, "A conceptual agricultural water productivity model
  considering under field capacity soil water redistribution", *Agricultural Water
  Management*, 2019, [doi:10.1016/j.agwat.2018.10.024](https://doi.org/10.1016/j.agwat.2018.10.024).
* S. Chen, X. Mao, D. A. Barry and J. Yang, "Model of crop growth, water flow, and solute transport
  in layered soil" (LAWSTAC), *Agricultural Water Management*, 2019,
  [doi:10.1016/j.agwat.2019.04.031](https://doi.org/10.1016/j.agwat.2019.04.031).
* R. T. de Faria and W. T. Bowen, "Evaluation of DSSAT soil-water balance module under
  cropped and bare soil conditions", *Brazilian Archives of Biology and Technology* 46(4),
  2003, 489–498, [doi:10.1590/S1516-89132003000400001](https://doi.org/10.1590/S1516-89132003000400001).
* Q. de Jong van Lier, J. C. van Dam, K. Metselaar, R. de Jong and W. H. M. Duijnisveld,
  "Macroscopic root water uptake distribution using a matric flux potential approach",
  *Vadose Zone Journal* 7, 2008, 1065–1078,
  [doi:10.2136/vzj2007.0083](https://doi.org/10.2136/vzj2007.0083).
* DSSAT, [Soil water](https://dssat.net/soil-water/), the module's description.
* R. A. Feddes, P. Kowalik, K. Kolinska-Malinka and H. Zaradny, "Simulation of field water
  uptake by plants using a soil water dependent root extraction function", *Journal of
  Hydrology* 31, 1976, 13–26, [doi:10.1016/0022-1694(76)90017-2](https://doi.org/10.1016/0022-1694(76)90017-2).
* M. Gong, J. Davies, R. Killick et al., "A changepoint approach to automated estimation of soil
  moisture drydown parameters from time series data", *Scientific Reports* 15, 2025,
  [doi:10.1038/s41598-025-27067-w](https://doi.org/10.1038/s41598-025-27067-w).
* M. Longo, C. Jones, R. C. Izaurralde et al., "Testing the EPIC Richards submodel for
  simulating soil water dynamics under different bottom boundary conditions", *Vadose
  Zone Journal* 20, 2021, [doi:10.1002/vzj2.20142](https://doi.org/10.1002/vzj2.20142).
* T. B. Ottoni, M. V. Ottoni, M. B. de Oliveira, J. R. de Macedo and K. Reichardt,
  "Revisiting field capacity (FC): variation of definition of FC and its estimation from
  pedotransfer functions", *Revista Brasileira de Ciência do Solo* 38, 2014, 1750–1764, [doi:10.1590/S0100-06832014000600010](https://doi.org/10.1590/S0100-06832014000600010).
* A. Paraskevopoulos and A. Singels, "Integrating soil water monitoring technology and
  weather based crop modelling to provide improved decision support for sugarcane
  irrigation management", *Computers and Electronics in Agriculture* 105, 2014, 44–53,
  [doi:10.1016/j.compag.2014.04.007](https://doi.org/10.1016/j.compag.2014.04.007).
* R. Prasad, "A linear root water uptake model", *Journal of Hydrology* 99, 1988, 297–306,
  [doi:10.1016/0022-1694(88)90055-8](https://doi.org/10.1016/0022-1694(88)90055-8).
* D. Raes, P. Steduto, T. C. Hsiao and E. Fereres, "AquaCrop — the FAO crop model to
  simulate yield response to water: II. Main algorithms and software description",
  *Agronomy Journal* 101, 2009, 438–447, [doi:10.2134/agronj2008.0140s](https://doi.org/10.2134/agronj2008.0140s).
* A. Ruiz-Hermo, L. Orihuela, E. Pacheco and L. Miranda Enamorado, "Modelo de balance hídrico multicapa:
  validación frente a HYDRUS-1D y datos reales", *Jornadas de Automática*, 2026,
  [doi:10.17979/ja-cea.2026.47.13771](https://doi.org/10.17979/ja-cea.2026.47.13771).
* M. G. Schaap, F. J. Leij and M. Th. van Genuchten, "ROSETTA: a computer program for
  estimating soil hydraulic parameters with hierarchical pedotransfer functions", *Journal
  of Hydrology* 251, 2001, 163–176, [doi:10.1016/S0022-1694(01)00466-8](https://doi.org/10.1016/S0022-1694(01)00466-8).
* K. Sharma, S. Irmak and M. S. Kukal, "Propagation of soil moisture sensing uncertainty
  into estimation of total soil water, evapotranspiration and irrigation decision-making",
  *Agricultural Water Management* 243, 2021, 106454, [doi:10.1016/j.agwat.2020.106454](https://doi.org/10.1016/j.agwat.2020.106454).
* V. Shelia, J. Šimůnek, K. Boote and G. Hoogenboom, "Coupling DSSAT and HYDRUS-1D for
  simulations of soil water dynamics in the soil-plant-atmosphere system", *Journal of
  Hydrology and Hydromechanics* 66(2), 2018, 232–245, [doi:10.1515/johh-2017-0055](https://doi.org/10.1515/johh-2017-0055).
* I. Sonkar, H. P. S. R. Kotnoor and S. Sen, "Estimation of root water uptake and soil
  hydraulic parameters from root zone soil moisture and deep percolation", *Agricultural
  Water Management*, 2019, [doi:10.1016/j.agwat.2019.05.037](https://doi.org/10.1016/j.agwat.2019.05.037).
* K. X. Soulis, S. Elmaloglou and N. Dercas, "Investigating the effects of soil moisture
  sensors positioning and accuracy on soil moisture based drip irrigation scheduling
  systems", *Agricultural Water Management* 148, 2015, 258–268, [doi:10.1016/j.agwat.2014.10.015](https://doi.org/10.1016/j.agwat.2014.10.015).
* K. X. Soulis and S. Elmaloglou, "Optimum soil water content sensors placement for surface
  drip irrigation scheduling in layered soils", *Computers and Electronics in Agriculture*,
  152, 2018, 1–8, [doi:10.1016/j.compag.2018.06.052](https://doi.org/10.1016/j.compag.2018.06.052).
* Y. Zhang and M. G. Schaap, "Weighted recalibration of the Rosetta pedotransfer model with
  improved estimates of hydraulic parameter distributions and summary statistics
  (Rosetta3)", *Journal of Hydrology* 547, 2017, 39–53, [doi:10.1016/j.jhydrol.2017.01.004](https://doi.org/10.1016/j.jhydrol.2017.01.004).
