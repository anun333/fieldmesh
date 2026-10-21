<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/probewatch/` — a soil probe gone off (layer 2, optional add-on)

> **Experimental, frozen since 2026-10-20** ([GOVERNANCE](../../GOVERNANCE.md#which-modules-are-maintained)): kept working and tested, with fixes, but no new features until a pilot farm asks for one.

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

A drift in one probe moves the forecast of the probe beside it, so the healthy one may be
said to be off too. In a bed of two, each is the other's only neighbour: on Tennessee's
records the healthy probe was said off beside a drifting one 27 to 57% of the time, so a bed
of two cannot tell which probe is off. In a bed of three it was 10 to 40% for the probe
just above, and 3 to 10% for the one below. Nor do the points tell which: when both were
said off, the drifting probe was off by more only 15 times in 32 in a bed of three, 8 in 40
in a bed of two.

**In a bed of two the watch says which is the likelier one off** (since 2026-10-20, rule
version 2), where the bed has the station's rain or air. Both said off, each is judged
again against the rain and the air alone: the one still off while the other is not is
named, and if both or neither are, the message says to check both. Chosen by rules written
before it was tried: it named the drifting probe in 94% of 90 such days on six stations
and in 93% of 27 on three stations held out, never the wrong one there.

> For 13 of the last 24 hours, bed 3's probe at 5 cm read drier than the probe beside it,
> the rain and the air say it should, by about 3.9 points of water content. But the other,
> at 10 cm, is the likelier one off: judged against the rain and the air alone, it is, and
> this one is not. Check that one first.

**What it does not see: a slow drift.** A probe drifting 0.02 over two weeks or 0.03 over
eight was said off under 1% of the time: the model reads the drift in the weeks before the
day it judges, and forecasts it. A week's look did no better (3 to 7%). Judging against a
stretch kept from 60 days before did not serve either: a regression on the other probes
caught 74% of slow drifts but called half of all clean stretches drifts too, the model 45%
and 39%, readings after soaking rain 18% and 11%. In two months the season changes how the
probes read against each other. A second probe at the same depth, or a reference probe now
and then, would be needed
([docs/notes/timestral.md](../../docs/notes/timestral.md#a-slow-drift-against-a-stretch-kept-from-before-it-2026-10-20)).

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

Run through this module's own code with the real model (`verify_timestral.py`,
2026-10-19), 30 days at each of six stations, three in Tennessee and three in the
Southwest
([docs/notes/timestral.md](../../docs/notes/timestral.md#tried-further-six-stations-two-probes-rain-the-day-ahead-2026-10-19)):

* a clean day was said off 0 to 3% of the time, in the Southwest as in Tennessee;
* a drift of 0.0025 an hour put in was caught 93 to 100% of the time;
* on a day with rain, 25 drifts in 28 (89%), against 99% on dry days.

**Not tried:** a real farm's probes and faults; soils other than these stations'; probes
below 20 cm. Whether three hours outside the band is the right line for a farm is a
season's question ([docs/UNTESTED.md](../../docs/UNTESTED.md)).

## Tests

`python3 -m unittest discover -p 'test_*.py'` here, with cel-python
(`requirements.txt`). The tests use a stand-in model (`sdk/test_tsfm.py`), so neither
Timestral nor NumPy is needed.

AGPL-3.0-or-later, as the other layer-2 modules are.
