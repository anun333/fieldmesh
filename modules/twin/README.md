<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/twin/` — a physics twin for the hoop house (layer 3, Q28)

[GreenLight](https://github.com/davkat1/GreenLight) (Katzin et al., Wageningen University &
Research; BSD-3-Clause-Clear) models a greenhouse's climate from first principles: the
cover's shortwave and long-wave exchanges, the air and the space above it, ventilation by
wind and buoyancy, the soil, a crop's transpiration and photosynthesis. It was built for a
heated, lit Dutch glasshouse. [twin.py](twin.py) configures it as what the farms here have:
a 30 × 96 ft single-poly high tunnel with roll-up sides and no heating, lamps, screen or CO2.
It then drives the model with the farm's real weather.

Q28's first step is a check on our own physics. The virtual farm's hoop house
(`sim/physics.Tunnel`) is a few plausible numbers. Run on the same real weather (McAllister
Farm, NASA POWER hourly, March–April and two weeks of July 2025), [tunnel_compare.py](tunnel_compare.py)
sets the two side by side.

## What it found

| spring 2025, 60 nights, 6 frosts outside | mean night gain | worst night | frosts inside | inside ≤ −2.2 °C | daytime excess | hottest |
| --- | --- | --- | --- | --- | --- | --- |
| the virtual farm's tunnel | +3.1 °C | +1.6 | 2 | 1 | +9.5 | 32.6 °C |
| GreenLight, thermic (IR) film | +1.4 °C | −0.4 | 1 | 0 | +7.3 | 29.3 °C |
| GreenLight, clear film | +0.3 °C | −1.1 | 5 | 1 | +6.7 | 29.2 °C |

* **The virtual farm's tunnel is too kind at night.** It is 1.6 °C warmer than GreenLight's
  tunnel under IR film and 2.7 °C warmer than under clear film. It has no long-wave
  radiation and knows cloud only by rain, so it barely tells a clear night from a cloudy
  one.
* **The film decides the frost.** Under clear polyethylene five of the six frosts still got
  in, and on clear nights the tunnel was colder than the open air: thermal radiation goes
  straight through to the sky. That is the inversion growers report under single poly.
  Under IR film one frost got in, and none hard.
* **By day they are closer.** Two July weeks put the hottest hour within 1.6 °C across all
  three.

Neither GreenLight's tunnel nor the virtual farm's has met a real one, so this says what to
measure first, not who is right: a tunnel's inside and outside air on clear spring nights,
with its film type written down. `modules/advise/tunnel_gain.py` already turns paired
sensors into a measured gain.

## What it took to run GreenLight as a tunnel

Every unheated configuration failed at the first sunrise, in the solver, whatever its film
or vents. The cause was in the crop model. The CO2 compensation point
(Vanthoor 2011, ch. 9) scales the leaf's by `j25LeafMax / j25CanMax`, which is 1/LAI. That
holds for a canopy of one leaf layer or more. A tunnel's young transplants (LAI 0.13 here)
make the ratio near 8 and the compensation point **negative**, about −150 ppm. Gross
photosynthesis divides by `(Cs + 2Γ)`, so the model has a pole at a leaf CO2 of about
300 ppm, and a house that is not enriched passes through 300 ppm every sunny morning. An
enriched glasshouse never comes near it, which is presumably why it was never hit.
Capping the ratio at 1 (one formula override, `FORMULAS` in [twin.py](twin.py)) runs every
configuration; without it, every one fails. The test
`test_it_runs_a_tunnel_through_sunrise_only_with_the_compensation_point_fixed` keeps both
halves of that true, and will say when an upstream fix makes the override unnecessary.

## Running it

GreenLight pins numpy 1.26 and brings scipy, pandas and matplotlib, so it gets its own
environment, and as a live twin it will be its own module process (§8.3):

```sh
python3 -m venv twin-env && twin-env/bin/pip install -r modules/twin/requirements.txt
twin-env/bin/python -I modules/twin/tunnel_compare.py --run    # about 3½ minutes; rewrites data/
python3 modules/twin/tunnel_compare.py                          # anywhere: from the saved runs
```

Sixty-one days of the tunnel take about 80 seconds here.

| file | what it is |
| --- | --- |
| [data/mcallister-2025-spring-hourly.csv](data/), [july](data/) | the weather: NASA POWER hourly, CC BY 4.0, irradiance converted from MJ/h |
| [data/greenlight-tunnel-*.csv](data/) | GreenLight's hourly inside air, per film and period |

Code AGPL-3.0-or-later ([LICENSE](LICENSE)), like the other modules; GreenLight is
BSD-3-Clause-Clear and is installed, not copied.

**Next (Q28):** a frost watch for covered crops, from tonight's forecast through the twin;
then twin against a tunnel's own sensor, as advice. The virtual farm's tunnel should take
GreenLight's night gains, by film type, before anything is built on it.
