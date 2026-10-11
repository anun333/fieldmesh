# `sim/` — the virtual farm

Build-order steps 2–4 from [docs/VIRTUAL_FARM.md](../docs/VIRTUAL_FARM.md). Stdlib
only (plus `cbor2`, via the SDK), Apache-2.0.

```sh
cd sim && python3 -m unittest discover -p 'test_*.py'   # 240 tests (~95 s; the drills are slow)
python3 drill.py --compare                              # one probe against two
python3 world_demo.py                                   # a day of Harrow Bend
python3 world_demo.py --stuck-float                     # the fault, and the catch
python3 world_demo.py --outage 10 --days 2              # buffer, evict, report
python3 world_demo.py --dr 3                            # a better link
python3 forecast_drill.py                               # forecasts on real 2007 weather, scored
python3 forecast_drill.py --springs 1991-2020 --weather W.csv --ensemble 20   # heavy: ~1.6 GB a spring
python3 irrigation_drill.py                             # watering by timer, forecast and probe
```

| Module | What it is |
| --- | --- |
| `physics.py` | Ground truth: a seeded seasonal climate — or `RecordedClimate`, a real place's daily weather replayed at the 5-minute tick — a soil water balance, a trough with a float valve, an unheated tunnel fitted to GreenLight per film (tested by modules/advise/tunnel_gain.py). Given the sky's cloud, from its long-wave (`cloud_from_longwave`), the tunnel's nights follow it, and a clear night under plain polyethylene is colder inside than out |
| `data/` | Recorded weather from NASA POWER (CC BY 4.0): McAllister Farm's spring of 2007, the Easter freeze in it; its summer of 2013, the wettest of thirty; and its summer of 2012, kept to test what was tuned on 2013. `tools/weather_csv.py` writes any site's years |
| `forecaster.py` | Forecast runs read from the world's own future, with an error of declared size that grows with lead time; and ensembles whose members share the run's error and spread about it |
| `forecast_drill.py` | Forecasts through layer zero (Q26) on recorded weather: scored against the farm's station by lead day, and a frost watch scored on the alert standing 12 h before each frost and on false alert episodes; `--springs` over many years, and `--ensemble` to warn at a chance of frost rather than a margin |
| `harrow_bend.py` | **Harrow Bend**, the canonical farm: built from a seed, every device and series declared, a season lived through; the completeness matrix (`test_harrow_bend.py`) is enforced against it |
| `siting_drill.py` | The depth and two-peer siting checks scored on a control farm and on one where five probes are moved, pulled or swapped and nobody logs it |
| `export_demo.py` | A season exported and verified, printing what a farmer would receive |
| `irrigation_drill.py` | Five watering rules on identical recorded summers and forecasts — timer, skip on forecast rain, skip knowing the rain, soil probe, probe with skip — by water applied, drained and transpired, and stress |
| `node.py` | A duty-cycled node: sampling, buffering, transmit-time restamping, eviction, resend, reboot |
| `link.py` | A radio that loses, delays, duplicates, drops acks and goes out — seeded |
| `faults.py` | Injectable sensor faults: drift, sticking, bias, noise, death, out-of-range |
| `harness.py` | The loop, in §5.1's order, shared by the demo and the tests |
| `drill.py` | Seeded faults scored against ground truth: recall, precision, false alarms, latency |
| `world_demo.py` | The whole chain — physics → node → link → gateway → observations |

## Ground truth lives in `physics.py`, and only there

Sensors, their quantisation and their faults belong to `node.py`. That separation is
the producer/detector doctrine: a detector is only honestly scored if the thing that
produced the fault and the thing meant to notice it were written apart. `physics.py`
has never heard of `checks.py`.

Fidelity, stated plainly: plausible physics with the right *shape*, not a validated
agronomic model. A single-layer soil bucket with FAO-56-flavoured stress and drainage,
ET as a seasonal curve scaled by temperature rather than Penman-Monteith, rain as a
seeded two-state process. Enough to exercise every clause in the spec and to make
drift look like drift. Not enough to tell a farmer when to irrigate.

Rain is the climate's only stochastic input, so two seeds produce identical output
over a window that is dry in both — a property, not a bug, and the reason seed
sensitivity is tested over three days rather than one.

## What running it has already found

The sim earns its keep by failing. Four defects, each now a spec amendment:

1. **A healthy farm flagged 228 of 384 readings.** A working float holds a trough at
   one value for 226 consecutive samples, and a soil probe at three decimals repeats
   for eight hours overnight when ET is near zero. Both are *correct* readings.
   Flatline is a category error on a regulated quantity, and a flatline threshold has
   to exceed the quantisation dwell (§4.2).
2. **A node inside its latency ceiling lost data permanently and looked healthy.** It
   sampled twelve readings an hour and sent one frame an hour carrying five.
   `max_latency` is a ceiling, not a schedule; a node must drain on backlog, and an
   infeasible sample-rate/link combination must be refused at registration (§5.3.1).
3. **Derived values carried IEEE 754 noise** — `0.08600000000000001` — into the
   SensorThings output. A calibration may now declare its output resolution (§3.2).
4. **Two readings could land on one instant**, violating §3.2's uniqueness. Wire ages
   are whole seconds, so that bounds the minimum sample interval per channel (§5.2).
5. **A resend took a fresh sequence number**, so the gateway could not recognise it and
   wrote the same readings again at timestamps a rounding apart — 2498 observations
   where 768 were expected. §6.3 states this rule for commands; it was never stated for
   readings, and now is (§5.2).
6. **Without an acknowledgement deadline, one lost frame stalled delivery forever.**
   The gateway's highest contiguous sequence cannot pass a hole, so the node held every
   later reading until it began evicting — healthy-looking and delivering nothing (§5.2).
7. **Two mixed-clock bugs, both in this harness rather than the SDK.** Sampling against
   true time while transmitting against a skewed clock, and polling the link for
   acknowledgements on the node's clock instead of the medium's. Neither raised an
   error; the first silently destroyed §2's offset cancellation and the second made the
   node resend forever. A node has one clock and the link has another, and the spec now
   says so.

`test_world.py` is where that first one is pinned: a clean day must produce a clean
record, *and* every reading must still be assessed — silence because nothing was
checked is not the same as silence because nothing was wrong.

## Why clock skew is not an injectable fault

Because §2 makes it a non-event, and that is worth demonstrating rather than
asserting. A node reports **ages**, computed from its own clock at both ends, so a
constant offset subtracts out exactly: `(t2 + e) - (t1 + e)` is `t2 - t1`. A node six
hours wrong still produces a correct `measured_at`, and
`test_faults.py::TestClockOffsetCancels` proves it. Only drift across the buffer dwell
survives, and over the minutes or hours a reading actually waits it is far below the
uncertainty the node already declares.

What *does* corrupt times is stamping the age when the reading is taken rather than
when the frame leaves — the mistake §2 warns about. `Node.stamp_at_sample` models it
so the damage is visible: without an outage it is invisible, which is exactly why it
would ship, and after a six-hour outage the entire window collapses onto the recovery
instant and nothing in the record says so.

## What the drills measured

`make drill`. Onset at a third of the way in, scored against `Sensor.injected()`:

| fault | 1 probe | 2 probes |
| --- | --- | --- |
| control (nothing wrong) | 0 flags | 0 flags |
| disconnected, reads its rail | 100% | 100% |
| frozen probe | 87% | 87% |
| **drift +0.05/day** | **0%** | **79%** |
| **noise sigma 0.03** | **0%** | **19%** |
| **bias +0.08** | **0%** | **100%** |
| dead (absence, not a wrong value) | no flags — correct | no flags — correct |

**A single probe on a feature cannot see drift, bias or noise at all.** Every reading
is individually plausible and the series looks healthy. Drift is the commonest real
failure of the three, so this is an installation decision, not a tuning one.

The first scored run reported a **99.8% false-alarm rate on a clean farm**, which is
how the cross-check's unit error was found: it was comparing a derived series in
physical units against a neighbour's raw series in wire units, 0.280 against 280. No
amount of fault-detection recall would have revealed that — only the control did.

## Not here yet

**Harrow Bend itself is not assembled** — this is one bed and one trough, not the six
beds, paddock, research plot, hoop house and well of the completeness matrix (step 5).
