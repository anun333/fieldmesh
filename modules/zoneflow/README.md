<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/zoneflow/` — irrigation zone flow: a clogged head, a broken one (layer 2)

A zone's flow is the sum of its heads' flows. With a flow meter on the irrigation line,
every run of every zone has a measured flow. OpenSprinkler reports it as each zone closes
(`station/<n>`, `"flow"`: the run's average, in the unit its flow pulse rate implies).
The MQTT bridge writes it to the log. This module sets each run beside two references
and says what is wrong, in the farmer's language:

| alert | when | what it means |
| --- | --- | --- |
| **low** | two runs in a row more than 10% under the zone's **usual flow** | a clogged nozzle, screen or filter; a valve not opening fully |
| **low, sized in heads** | the same, when the missing flow matches a whole number of one of the zone's heads | "the missing flow is about what 1 half-circle spray head of 15 feet gives" |
| **high** | two runs in a row more than 10% over it | a broken head, a lost nozzle, a leak |
| **drift** | the usual flow itself has fallen more than 10% under what the zone's **heads should give** | emitters or nozzles clogging slowly; a filter filling |

**OpenSprinkler's own flow alert only looks up.** It fires above a set point taken from
the station's name, so it sees a broken head and never a clog
([notes/water-meters](../../docs/notes/water-meters.md)). That is the gap this fills.

Read-only and advisory: it never touches a valve. Each alert is a CEL rule judged through
layer 1 ([modules/rules](../rules/)), so its decision event (§7.7) carries the runs it
used and the condition as written. A decision is written when an alert is raised or
cleared, as the [livestock water monitor](../water/) writes them, and a monitor that
restarts reads which alerts stand from the log.

## The two references

**The usual flow is learned, from normal runs only.** Each run is set beside the median of
the last seven runs that were themselves within tolerance. A clog that lasts never becomes
the new usual, so its alert stands until the flow comes back. A zone changed on purpose
(heads added, nozzles swapped) is given a `since`, and its usual flow is learned afresh
from then. It is the [soil advisory's](../soilwater/) learned field capacity applied to
pipes.

**What the heads should give** comes from the zone's inventory: its heads, from the
makers' charts, scaled by √P to the pressure they run at. A nozzle is an orifice; Rain
Bird's chart gives the 15F 2.60 gpm at 15 psi and 3.70 at 30, and √(15/30) of 3.70 is
2.62. A pressure-compensating emitter does not scale. The inventory does three jobs:

* with fewer than three runs yet, it stands in for the usual flow;
* a slow drift, which the usual flow follows run by run, shows against it;
* a shortfall is sized in the zone's own heads.

The inventory is optional. Without it there is no drift alert and no sizing.

The heads it knows, each from its maker's chart: Rain Bird MPR spray nozzles (8, 10, 12
and 15 feet; full, half and quarter; 30 psi), Rain Bird 5000 rotor nozzles (#1.5 to #8.0,
45 psi) and Xeri-Bug emitters (0.5, 1 and 2 gph). Another head is a line in `HEADS`.

## The drill: 300 seasons of 40 runs

`zoneflow.drill()` runs the check over simulated seasons. The supply pressure wanders
±10% (two standard deviations), moving every head by its square root, and the meter reads
±2%. Three zones:

* a lawn zone of six 15-foot half heads and two quarters, 12.94 gpm;
* four rotors with #3.0 nozzles, 12.36 gpm;
* a hundred 1-gph emitters, 1.67 gpm.

Each fault starts at run 20 (drip silts up 1% a run from the first). "Runs to catch" counts
the faulty runs before the alert; 1 means the second faulty run.

| | healthy lawn zone | half head clogged (−14%) | quarter head clogged (−7%) | rotor stuck (−25%) | head broken off | drip silting |
| --- | --- | --- | --- | --- | --- | --- |
| **confirm on 2 runs** (default) | **0 false alerts** in 12,000 runs | 300/300; median 1 run, max 6 | 60/300; median 3 | 300/300; 1 run | 300/300; 1 run | 300/300; median 14 runs, max 21 |
| confirm on 1 run | 60 false runs, in 54 of 300 seasons | 300/300; median 0 | 150/300 | 300/300; 0 | 300/300; 0 | 300/300; median 13 |

So, on flow alone:

* **a whole half head shows**, by its second run;
* **a quarter head is at the edge**: caught in a fifth of seasons;
* **a partly clogged nozzle does not show**;
* **drip shows as drift**, in about two weeks of daily runs, when a seventh of the line's
  flow has gone.

One run out is a pressure dip as often as a fault: confirming on one run raised a false
alert in 54 of 300 healthy seasons, so the default waits for two. A pressure
series on the line, dividing each run by √(P/P₀), would remove most of the pressure
term; that is not built.

## Using it

Bind the controller's `station.<n>.flow` to a datastream of ODM2 `discharge`
(`sdk/vocab.py` `FLOW_RATE`) in `[gal_us]/min`, `L/min`, `m3/h` or `m3/s`, one per zone.
Then name the zone's land and its heads:

```json
{"zones": [{"feature": "…the zone's land…", "flow": "…its flow datastream…",
            "heads": [["rainbird-mpr-15H", 6], ["rainbird-mpr-15Q", 2]],
            "pressure_psi": 30}]}
```

```sh
pip install -r modules/zoneflow/requirements.txt       # cel-python, via modules/rules
cd modules/zoneflow && python3 -m unittest discover -p 'test_*.py'
python3 zoneflow.py --socket … --config zones.json     # as a module process (§8.3)
```

The bridge also reads OpenSprinkler 2.2.1(6)'s `program/<n>` messages: whether a
program ran or was skipped, and the watering percentage and weather, sensor and total
scales it ran at.

## Not tested

No meter, controller or zone has been on the air ([UNTESTED](../../docs/UNTESTED.md)):

* the drill is simulated, with even pressure noise and no pressure sensor;
* the head flows are the makers' charts, not measured heads;
* OpenSprinkler's station flow is read from its firmware source, not from a controller.
