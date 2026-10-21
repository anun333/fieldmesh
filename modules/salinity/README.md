<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/salinity/` — salt building up in a bed (layer 2)

> **Experimental, frozen since 2026-10-20** ([GOVERNANCE](../../GOVERNANCE.md#which-modules-are-maintained)): kept working and tested, with fixes, but no new features until a pilot farm asks for one.

Under a tunnel no soaking rain washes salts below the roots, while fertilizer, compost and
hard water keep adding them, so salt builds up season after season
([University of Maryland Extension](https://extension.umd.edu/resource/salinity-matters-high-tunnels-and-growing-media-how-interpret-salinity-test-results)).
A soil test sees it a few times a year. A probe that reports electrical conductivity, as
the TEROS 12, the HydraProbe and the LoRaWAN probes do, sees it climb between them. This
sets a bed's salt beside the tolerance of the crop growing in it:

| alert | when the bed's salt, as a saturated paste's extract would read it |
| --- | --- |
| **climbing** | reaches 80% of the crop's threshold |
| **past it**, with the share of the yield lost | passes the threshold, where the crop's yield starts to fall |

> Salt in tunnel bed 2 is climbing: about 1.1 dS/m, as a saturated paste's extract would
> read, 86% of the 1.3 at which the yield of lettuce starts to fall.

> Salt in tunnel bed 2 has reached about 2.3 dS/m, as a saturated paste's extract would
> read, past the 1.3 at which the yield of lettuce starts to fall: about 13% of it is lost
> at this level. Water deeply to wash it below the roots, or uncover the bed to the
> winter's rain, and have the soil tested.

(The test's bed, its salt raised a week at a time.)

## From the probe's reading to the crop's scale

Three steps, as METER's TEROS 11/12 manual (section 3.3) gives them:

1. **The pore water's conductivity from the bulk soil's.** The probe measures the bulk
   soil's, which rises with the water and the temperature as well as with the salt.
   Hilhorst (2000): `σp = εp·σb / (εb − 4.1)`, with the pore water's permittivity
   `εp = 80.3 − 0.37 (T − 20)`. Not below 0.10 water content, where the denominator is
   small; about ±20% in moist soil.
2. **The bulk soil's permittivity `εb`** is the probe's own measurement, but it sends only
   the water content made from it. It is recovered by Topp, Davis and Annan's (1980)
   curve, the one most probes' water content is calibrated by. That is an approximation on
   top of Hilhorst's.
3. **The saturated paste's extract** is the pore water diluted to saturation:
   `ECe = σp · θ / φ`, the porosity `φ = 1 − ρb / 2.65` from the bed's bulk density (a
   loam's 1.4 Mg/m3 unless measured).

The bed's salt is the median of the last week's hours whose three readings (water,
conductivity, temperature, from one probe's body) the health checks passed. A wetter
soil reads a higher bulk conductivity for the same salt; the estimate does not move (tested
at 0.22 and 0.34).

**The tolerances are Maas and Grattan's (1999)**, as FAO Irrigation and Drainage Paper 61
(Tanji and Kielen, 2002, Annex 1) prints them: for 25 vegetables, the ECe up to which the
yield does not fall, and the share lost per dS/m beyond it
(`data/salt-tolerance-maas-grattan.csv`, [data/MANIFEST.csv](data/MANIFEST.csv)). Beans,
carrots and strawberries start losing at 1.0 dS/m; asparagus at 4.1.

Read-only and advisory. Each alert is a CEL rule judged through layer 1
([modules/rules](../rules/)); a decision is written when an alert is raised or cleared, and
a monitor that restarts reads which stand from the log. The crop is named in the reader's
language (`Rule.key_params`).

```sh
pip install -r modules/salinity/requirements.txt         # cel-python, via modules/rules
cd modules/salinity && python3 -m unittest discover -p 'test_*.py'
python3 salinity.py --socket … --config beds.json        # once a day, as a module process
```

with `beds.json` as `{"beds": [{"feature": "…", "crop": "tomato", "bulk_density": 1.3}]}`.

## Not tested

Nothing here has met a real bed ([UNTESTED](../../docs/UNTESTED.md)):

* the chain is tested against the manual's worked example and Hilhorst by hand, on
  readings made to fit it; a real probe's bulk conductivity has its own errors;
* Hilhorst's offset of 4.1 is generic; he gives a simple way to measure a soil's own,
  which the manual says improves the estimate in most cases;
* the bulk density is assumed unless given;
* no bed's estimate has been set beside a laboratory's saturated paste.
