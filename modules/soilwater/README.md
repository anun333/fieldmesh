<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/soilwater/` — soil-moisture advisory (layer 2)

The second layer-2 module (spec v0.1 §11), and Q12's other read-only choice: every
morning, for every bed, what to do about water — and when it cannot say, why not. A
season of its advice, kept in the log as decision events (§7.7), is the irrigation
module's evidence base before that module exists.

| advice | when |
| --- | --- |
| **water now**, and how many millimetres | the root zone has lost its crop's share of the plant-available water (FAO-56's `p`, a third by default): back up to field capacity |
| **rain coming** | it is due, but 10 mm or more is forecast in the next 24 hours |
| **water soon** | at the rate it has dried since it was last wetted, it is due within two days |
| **too wet** | wetter than field capacity: water is draining past the roots |
| **enough** | and how much of the available water is left |
| **no probe** | nothing is installed within the root zone |
| **unseen** | no reading for six hours |
| **untrusted** | the newest readings failed the health checks |

The arithmetic is FAO-56's root-zone balance read from the probes rather than modelled:
`TAW = (field capacity − wilting point) × root depth`, depletion
`Dr = (field capacity − θ) × root depth`, water when `Dr ≥ p × TAW`, `Dr` millimetres.
The soil's limits come from a soil test or the survey (`tools/soil_survey.py`).

**The probes are found, not configured.** A bed's probes are the soil-moisture series
whose device was installed in it when the reading was taken (§4.1), at the depth its
installation says. Each stands for the soil from halfway to the probe above to halfway to
the one below, and only the part inside the root zone counts. A probe moved from one bed
to another changes both beds' advice on the day it moves; one deeper than the roots counts
for nothing.

**Only readings that had passed the health checks by that morning count**
(`State.quality_as_of`), so a stuck or drifting probe never waters a bed, and a silent one
is dropped rather than averaged in. Rain coming is read from a forecast datastream in the
log (Q26), so the forecast an advice rested on sits beside it.

## Backtested

§11 asks for it before anything goes live. On McAllister Farm's recorded summer of 2013
(June to August), a 30 cm root zone in a silt loam, the drill's forecasts in the log, the
advisory followed to the letter, beside the drip timer most farms run
([sim/irrigation_drill.py](../../sim/irrigation_drill.py)):

| | water applied | drained past the roots | hours stressed ≥ 0.5 | mean stress |
| --- | --- | --- | --- | --- |
| drip timer, every second morning | 552 mm | 600 mm | 0 | 0.05 |
| timer, skipping when rain is forecast | 444 mm | 493 mm | 0 | 0.06 |
| **the advisory** | **155 mm** | **241 mm** | **0** | **0.13** |

72% less water and 60% less drained, with no hour of real stress. The cost is a drier
root zone on average — mean stress 0.13 against 0.05 — which is the trade a refill point
makes, and the reason `p` is the crop's to set.

On Harrow Bend, eight days, six beds: the beds are told apart on the first morning; the far
bed node's radio outage turns its beds' advice into "unseen" and no one else's; and a probe
lifted out of bed 6 into bed 2 leaves bed 6 with "no probe" and keeps bed 2 advised through
its own probe's outage.

```sh
pip install -r modules/soilwater/requirements.txt      # cel-python, via modules/rules
cd modules/soilwater && python3 -m unittest discover -p 'test_*.py'
```

```python
advisor = soilwater.Advisor(log)
beds = [soilwater.Bed(land_id, field_capacity=0.30, wilting_point=0.12)]
advisor.advise(state, beds, at=morning, forecast=rain_forecast_id)
soilwater.render(event.payload, "es", state)   # "Riegue cama 3 hoy: …"
```

Code AGPL-3.0-or-later ([LICENSE](LICENSE)); strings in [packs/](packs/) under the
`soilwater.` prefix, the Spanish an unreviewed draft. It imports layer zero and layer 1.

**Not yet:** the dose as a duration for a given drip line; the crop's `p` and root depth
from the farm's planting records; a probe's own field capacity learned from how far it
drains after a soaking.
