# `sim/` — the virtual farm

Build-order steps 2–4 from [docs/VIRTUAL_FARM.md](../docs/VIRTUAL_FARM.md). Stdlib
only (plus `cbor2`, via the SDK), Apache-2.0.

```sh
cd sim && python3 -m unittest discover -p 'test_*.py'   # 87 tests
python3 world_demo.py                                   # a day of Harrow Bend
python3 world_demo.py --stuck-float                     # the fault, and the catch
python3 world_demo.py --outage 10 --days 2              # buffer, evict, report
python3 world_demo.py --dr 3                            # a better link
```

| Module | What it is |
| --- | --- |
| `physics.py` | Ground truth: a seeded seasonal climate, a soil water balance, a trough with a float valve |
| `node.py` | A duty-cycled node: sampling, buffering, transmit-time restamping, eviction, cumulative ack, reboot |
| `world_demo.py` | The whole chain — physics → node → wire → gateway → observations |

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

`test_world.py` is where that first one is pinned: a clean day must produce a clean
record, *and* every reading must still be assessed — silence because nothing was
checked is not the same as silence because nothing was wrong.

## Not here yet

Faults the sim cannot inject: drift, clock skew, node reboot, and duplicated or
reordered frames. Those need a link layer between the node and the gateway that can
lose, delay and repeat — currently `world_demo.py` hands frames over directly, so
every message arrives exactly once and in order. That link is what step 3 still
wants, and it is the prerequisite for a scored drill (step 6).

Harrow Bend itself is not assembled: this is one bed and one trough, not the six
beds, paddock, research plot, hoop house and well of the completeness matrix.
