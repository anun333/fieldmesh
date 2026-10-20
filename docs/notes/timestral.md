<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Timestral on real probe records: a silent probe, and a probe gone wrong

*Written 2026-10-19.* Mistral released Timestral, a family of time-series forecasting models,
on 2026-10-15. This note tries it, zero-shot, on what a farm's soil-moisture probes need from a
forecaster: carrying a probe that has fallen silent, and telling a probe that has gone wrong
from a soil that has changed. One thing it showed is now in fieldmesh's own code
(`soilwater`, [below](#what-fieldmesh-took)). The model itself is only an optional add-on
([below](#using-it-as-an-add-on)), never a dependency.

## What it is

Four sizes, 5M, 28M, 123M and 209M parameters, one recipe. Each takes a series' history, up to
32,768 steps, and forecasts 21 quantiles for each step ahead. Other series can go in beside
it: past-only inputs, and known-future ones, seen through the horizon too. It runs on a CPU;
here the 28M model forecast three days of hourly soil water, with four inputs, in about a
third of a second, on four threads of a laptop's Ryzen 5.

**Licences.** The code (`mistralai/timestral`) is Apache-2.0. The weights, on Hugging Face,
are under a "Modified MIT" licence: MIT with an attribution notice, and **no rights at all for
anyone whose company, or whose employer, had global revenue over $20 million in the preceding
month**. So it can never be a dependency of fieldmesh itself, which anyone may run; at most an
optional add-on that a farm, knowing the licence, chooses to install.

## How it reads a series

The inference code says what the announcement does not:

* **Shapes, not levels.** The history is cut into patches of 32 steps, each rescaled on its
  own, past readings only, and squashed; a reading's absence is its own input. It learns the
  form of a drying curve or a day's rhythm, not that 0.30 is a soil's field capacity.
* **Inputs that cannot leak.** Each series is a target, a past-only input or a known-future
  input. In its attention an input never reads a target, and a known-future input, which sees
  ahead, never reads one that does not, so no target's future reaches its own forecast.
* **A band, not a line.** A median and 20 quantiles fanned out from it, never crossing.
* **No reasons given.** Nothing in it says why. What it responded to can be read from
  outside: the same forecast with an input taken away, or changed.

**Receipts.** A forecast returns its quantiles and their levels, nothing else. But it is
deterministic: run twice at four threads and once at one, the 28M model's forecasts were the
same to the bit. A fieldmesh decision resting on it could carry the model and its weights'
commit (`mistralai/Timestral-28M@180698b`), the package's commit (`a534bdb`), the datastreams
and hours fed in with a hash of the arrays, the quantiles, and the forecast again with each
input taken away; and anyone holding the log could run it again and check.

## A silent probe

**The records.** Hourly soil water at 5, 10 and 20 cm, rain and air temperature from the
International Soil Moisture Network's archive (downloaded 2026-10-08), readings it flags good
only: three Tennessee SCAN stations (Allen Farms, Eastview Farm, McAllister Farm) and three
in the dry Southwest (Cochora Ranch, California; Jornada Experimental Range and Los Lunas
Plant Materials Center, New Mexico), the growing seasons, 15 April to 15 October, of 2015 to
2025.

**The test.** At about 200 random hours a station, one probe's next 72 hours are hidden and
filled: by its last reading; by fieldmesh's rule as it was, its last reading less what the
other probes dried since; by the same moved both ways; by a regression on the others over the
last 1,024 hours; and by Timestral from the probe's last 1,024 hours, alone, with the rain and
the air, and with those and the other two probes, which go on reading. Each is scored against
the hidden readings, the mean absolute error over the 72 hours, in volume of water (0.01 is a
point of soil water):

| hidden probe | records | its last reading | fieldmesh's rule as it was | moved both ways | regression | Timestral alone | + rain, air | + the other probes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 cm | Tennessee, 596 | 0.017 | 0.0086 | 0.0062 | 0.011 | 0.011 | 0.0071 | **0.0040** |
| 5 cm | Tennessee, 596 | 0.023 | 0.015 | 0.012 | 0.015 | 0.016 | 0.0086 | **0.0068** |
| 20 cm | Tennessee, 595 | 0.011 | 0.011 | 0.012 | 0.012 | 0.0069 | 0.0052 | **0.0038** |
| 10 cm | the Southwest, 588 | 0.0075 | 0.0066 | 0.0068 | 0.0090 | 0.0048 | 0.0043 | **0.0037** |

All with the 28M model. At 10 cm in Tennessee the 5M scored 0.0052 with the other probes and
the 209M 0.0037, seven times slower than the 28M. Its 10-90% band held the truth 79 to 84% of
the time. Where rain fell in the gap (5 mm or more), errors were two to three times these.

**What it reads.** With the other probes beside it, taking the gap's rain away moved its
forecast little (0.0015 of a 0.025 rise at 10 cm): it reads the rain from the 5 cm probe's
rise. Without them, the rain and the air brought its error in wet gaps from 0.028 to 0.017.

**Checked four ways.** A second script, scoring apart from the first, matched every gap's
error to the bit. Gaps printed hour by hour behaved as a soil does: the band widening as rain
came, close on dry days; at a sharp wetting front it hedged, lagged, and once the truth left
its 10-90% band. With the other probes taken from a week earlier its error rose from 0.0040 to
0.0075, its level with the rain and the air alone: its edge is their real readings, not an
accident of alignment. And fieldmesh's rule was run through `soilwater.bed_context` itself,
not a copy: worse than the copy, 0.018 off three days in at 10 cm, because it counted the
others' drying only within its two-day drying window.

## A probe gone wrong

**Faults put in.** On 600 three-day stretches at 10 cm, Tennessee, a reading made stuck, or
stepped up 0.05, or drifting up to 0.06; and 600 left clean. Caught when the reading left the
model's 1-99% band three hours running (with the rain, the air and the other probes), or the
regression's estimate by 0.03 three hours running ("peer"), or did not change for 18 hours
(layer zero's flatline check):

| | Timestral | peer | flatline |
| --- | --- | --- | --- |
| false alarms, clean | 6% | 14% | 0% |
| stuck | 73% (16 h) | 54% (40 h) | 100% (17 h) |
| step | 100% (2 h) | 97% (2 h) | 0% |
| drift | 97% (9 h) | 98% (35 h) | 0% |

**Faults the archive flagged.** Readings ISMN's own quality control flagged at 10 cm in
2015 to 2025 (Dorigo et al. 2013), judged hour by hour over a day: in Tennessee, 46 events
(30 jumps, 10 readings above what the soil holds, and a few others), Timestral caught 30% of
the jumps and the peer check 57%, with 7% and 4% false alarms on clean days; in the Southwest,
383 spikes, Timestral caught 23% with 24% false alarms, no better than chance, the peer 1%.
ISMN's flags are its algorithm's, not a person's, and a jump on an irrigated field may be a
watering. Still: the model's band catches a drift sooner than anything fieldmesh has, and
not a one-hour spike.

## What fieldmesh took

The test showed fieldmesh's own rule for a silent probe was the weak one, and how to fix it
without any model: a silent probe now dries as the probes still reading have dried since its
own last reading, from their whole records, and wets only as those at or below it have wetted
(2026-10-19, `soilwater._from_probes`). Moved both ways as all of them moved, a 20 cm probe
under two shallower ones was carried wetter than it got after rain. Through `bed_context`,
three days into a silence: 5 cm 0.020 off the truth, where the old rule's copy was 0.023;
10 cm 0.011 (0.013, and the code itself 0.018); 20 cm 0.018 (0.018). Over the whole three
days the rule as it now is averaged 0.012, 0.007 and 0.011 off; the model 0.007, 0.004 and
0.004.

## Whether to use it

As an add-on, for two things: carrying a silent probe from its neighbours, the rain and the
air, and watching for a probe drifting off its soil. The 28M model; the 209M was hardly better
for seven times the time. A decision resting on it would carry the receipt above. Not for
spikes, which layer zero's own checks see, nor in place of the advice's water balance, which
says why. The licence makes it a farm's choice, never fieldmesh's default.

**Not tried:** a real farm's probes, with their own faults; soils other than these stations';
probes below 20 cm; forecasting ahead, not filling in; fine-tuning on a farm's own records.

## Using it, as an add-on

Added 2026-10-19. Nothing here installs Timestral or downloads its weights. A farm that
wants it installs the package (`pip install "git+https://github.com/mistralai/timestral.git"`,
which brings PyTorch and NumPy) and accepts the weights' licence in so many words. Each
of the three parts below refuses to load the model otherwise.

* [`sdk/tsfm.py`](../../sdk/tsfm.py) reads the farm's state into the model's inputs: good
  readings only, as they stood at the moment asked about, an hour at a time, with None
  for an hour with none. It runs the model and writes the receipt.
* [`tools/probe_forecast.py`](../../tools/probe_forecast.py), run from cron (hourly, say),
  forecasts each silent probe. A probe counts as silent when it has given no good reading
  for six hours but did within a week, while another probe in its bed still reads. The
  forecast covers the hours from its last good reading to a day ahead, and goes into the
  log as a forecast on a datastream of its own. That datastream is installed in the bed at
  the probe's depth (a forecast is never written as a measurement, Q26).
  `soilwater` takes such a forecast in place of its own rule when carrying the probe. It
  takes one only if it names that probe, was issued since the probe's last good reading and
  passed its range check. The decision says which carried it (`carried[].by`: `forecast` or `rule`).
* [`modules/probewatch/`](../../modules/probewatch/), a layer-2 module, says when a probe
  has read outside the band for three hours running in the last day, and says when it is
  back.

**The receipt.** Each forecast value's provenance, and each probe-watch decision's inputs,
carry:

* the model, the weights' commit and the package's version;
* each series by its datastream id, and the hours read;
* a SHA-256 of the inputs;
* how far the median moved with each input taken away (`moved_by`).

The model is deterministic, so anyone holding the log and the same weights can check a
decision.

**Run through this code, with the real model** (2026-10-19,
[`modules/probewatch/verify_timestral.py`](../../modules/probewatch/verify_timestral.py)).
McAllister Farm's record gave 30 stretches, each built into a fieldmesh state.

* **The silent probe.** The 10 cm probe was hidden 72 hours and forecast by
  `probe_forecast.forecast_silent`. Over the 72 hours it was 0.0046 off the truth on average,
  where its last reading held was 0.018 off.
* **The same as the trial.** Each forecast matched the forecaster called directly, as the
  trial called it, bit for bit.
* **The day ahead.** The hours past the run's time, which the model forecasts without its
  inputs, were finite in all 30. How good they are was not tried.
* **The probe watch.** On the day before each silence, `probewatch.probe_context` said a
  probe off in 1 of the 30 clean days. With a drift put in, 0.0025 an hour, it said 29 of
  the 30, all wetter. The one it missed came in a wet spell, its band 8.9 points wide.
* **Speed.** 1.4 seconds a silent probe on four threads, the receipt's ablations included.

The run also found that loading the weights had asked the cache for the whole repository,
its README too, and failed offline on a cache holding only the two files the model is made
from. It now asks for those two (`tsfm.WEIGHT_FILES`).

## Reproducing

The scripts are [tools/timestral/](../../tools/timestral/). The archive is downloaded data:
read with `-I`, from a neutral directory, never extracted. The model runs in a container,
without the network once its weights are cached.

```sh
cd /tmp && mkdir -p tsfm/data tsfm/out tsfm/hf
python3 -I ~/dev/fieldmesh/tools/timestral/extract.py ~/Downloads/ISMN_archive_20261008.zip \
    tsfm/data McAllister_Farm,Allen_Farms,Eastview_Farm
docker build -t fieldmesh-timestral ~/dev/fieldmesh/tools/timestral
FETCH=1 ~/dev/fieldmesh/tools/timestral/run.sh tsfm/data tsfm/out tsfm/hf \
    gapfill.py /data /out/gap-28M.json mistralai/Timestral-28M 200 1024 sm_10
python3 -I ~/dev/fieldmesh/tools/timestral/summarize.py tsfm/out/gap-28M.json
```

The check through fieldmesh's own code mounts the repository in the same container:

```sh
docker run --rm --network none --cpus 4 --memory 6g -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 \
    -v "$PWD/tsfm/data":/data:ro -v "$PWD/tsfm/out":/out -v "$PWD/tsfm/hf":/hf:ro \
    -v ~/dev/fieldmesh:/repo:ro fieldmesh-timestral \
    python /repo/modules/probewatch/verify_timestral.py /data/McAllister_Farm.csv /out/verify.json 30
```

`faults.py` and `faults_real.py` run as `gapfill.py` does; `verify.py` and `determinism.py`
check it; [`modules/soilwater/verify_timestral.py`](../../modules/soilwater/verify_timestral.py)
and `rule_variants.py` run outside the container, beside the repository.

## Sources

* Mistral AI, [Introducing Timestral](https://mistral.ai/news/timestral), 2026-10-15; the code,
  [mistralai/timestral](https://github.com/mistralai/timestral), commit a534bdb; the weights'
  [licence](https://huggingface.co/mistralai/Timestral-28M/blob/main/LICENSE).
* W. A. Dorigo et al., "Global automated quality control of in situ soil moisture data from the
  International Soil Moisture Network", *Vadose Zone Journal* 12(3), 2013,
  [doi:10.2136/vzj2012.0097](https://doi.org/10.2136/vzj2012.0097).
* W. Dorigo et al., "The International Soil Moisture Network: serving Earth system science for
  over a decade", *Hydrology and Earth System Sciences* 25, 2021, 5749–5804. ISMN's data is
  used under CC-BY-4.0; this note publishes derived statistics only.
* G. L. Schaefer, M. H. Cosh and T. J. Jackson, "The USDA Natural Resources Conservation
  Service Soil Climate Analysis Network (SCAN)", *Journal of Atmospheric and Oceanic
  Technology* 24, 2007, 2073–2077, [doi:10.1175/2007JTECHA930.1](https://doi.org/10.1175/2007JTECHA930.1).
