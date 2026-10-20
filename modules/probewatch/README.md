<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/probewatch/` — a soil probe gone off (layer 2, optional add-on)

A probe can go wrong in ways its own readings do not show. It can be pulled up by a hoe,
lose contact through an air gap after a dry spell, take water down its cable, or drift. Each
reading still looks like soil water. Layer zero's checks see a probe stuck flat, a reading
out of range and a sudden jump. They do not see a probe reading a few points too wet while
the other probes in its bed, the rain and the air say it should be drying.

This watch sets each probe against the forecast made of it from those inputs:

| it says | when |
| --- | --- |
| **off**, wetter or drier, by how much | its readings left the forecast's 1-99% band for three hours running in the last day |
| **back** | a later look finds it inside the band again |

> For 13 of the last 24 hours, bed 3's probe at 20 cm read wetter than the probes beside
> it, the rain and the air say it should, by about 3.9 points of water content. Check it:
> moved, out of the soil, flooded at its cable, or drifting.

(The test's bed, its deepest probe drifting 0.003 an hour.)

## An optional add-on

The forecast comes from Timestral, Mistral AI's time-series model
([docs/notes/timestral.md](../../docs/notes/timestral.md)), through
[`sdk/tsfm.py`](../../sdk/tsfm.py). It is not fieldmesh's own dependency, and nothing in
fieldmesh runs it unless a farm installs it and says so:

* **The package and its runtime.** `timestral` (Apache-2.0), PyTorch and NumPy:
  `pip install "git+https://github.com/mistralai/timestral.git"`.
* **The weights' licence.** The weights, on Hugging Face, are under a "Modified MIT"
  licence. It gives **no rights at all to anyone whose company, or whose employer, had
  global revenue over $20 million in the preceding month**. The watch reads
  `"accept_weights_licence": true` in its configuration. Without it, the watch loads
  nothing, says why and exits with status 2.

```json
{"accept_weights_licence": true, "offline": true,
 "beds": [{"feature": "<bed id>", "rain": "<rain datastream>", "air": "<air temperature datastream>"}]}
```

```sh
python3 modules/probewatch/probewatch.py --socket /run/fieldmesh/modules.sock --config probewatch.json
```

The 28M model makes one forecast in about a third of a second on four threads of a
laptop's CPU. The receipt runs it again with each input taken away, so a bed of three
probes with a station takes a few seconds a look. It is deterministic, so anyone holding
the log can run it again and get the same band.

## What it judges, and the receipt

At each look, for each bed with two or more probes still reading (each with a good reading
within six hours), the model is given:

* each probe's 1,024 hours before the last day;
* the bed's other probes, and the station's rain and air temperature, through that day.

It forecasts the probe's day from these. The decision carries the receipt of that forecast
(`inputs.receipt`):

* the model, the weights' commit and the package's version;
* each series by its datastream id;
* the hours read;
* a hash of the inputs;
* how far the forecast moved with each input taken away (`moved_by`).

With `moved_by`, a reader can see the forecast rested on the probe at 10 cm, say, and not
on the rain.

With only two probes in a bed, each is the other's only neighbour. When one drifts, both
may be said to be off. A third probe tells which one it is.

## What it was tried on

ISMN's records of Tennessee SCAN stations: 600 three-day stretches at 10 cm with a fault
put in, and 600 left clean
([docs/notes/timestral.md](../../docs/notes/timestral.md#a-probe-gone-wrong)). Each cell
gives the share caught and, in brackets, the median hours it took:

| fault | this band, three hours out | a regression on its neighbours, 0.03 out | layer zero's flatline check |
| --- | --- | --- | --- |
| drifting up to 0.06 | 97% (9 h) | 98% (35 h) | 0% |
| a step of 0.05 | 100% (2 h) | 97% (2 h) | 0% |
| stuck | 73% (16 h) | 54% (40 h) | 100% (17 h) |
| false alarms, clean stretches | 6% | 14% | 0% |

On the jumps ISMN's own quality control flagged, it caught 30% to the regression's 57%. On
the Southwest's one-hour spikes it did no better than chance. Spikes are layer zero's. The
trial judged three-day stretches; the watch judges the last day at each look.

Run through this module's own code with the real model on McAllister Farm's record
(`verify_timestral.py`, 2026-10-19): of 30 days, one clean day was said off; with a drift
of 0.0025 an hour put in, 29 of the 30 were, all wetter. The one missed came in a wet
spell, when the band was 8.9 points wide.

**Not tried:** a real farm's probes and faults; soils other than these stations'; probes
below 20 cm. Whether three hours outside the band is the right line for a farm is a
season's question ([docs/UNTESTED.md](../../docs/UNTESTED.md)).

## Tests

`python3 -m unittest discover -p 'test_*.py'` here, with cel-python
(`requirements.txt`). The tests use a stand-in model (`sdk/test_tsfm.py`), so neither
Timestral nor NumPy is needed.

AGPL-3.0-or-later, as the other layer-2 modules are.
