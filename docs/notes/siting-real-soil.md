<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# The siting check on real soil

**2026-10-08.** The §4.1 depth-from-temperature siting check (`sdk/siting.py`) had only
ever met the simulator's heat model. ISMN carries real soil temperature at five depths at
each Tennessee SCAN station, so this note runs the check against real soil — and then lies
to it, to see whether it notices.

## Method

[tools/ismn_siting.py](../../tools/ismn_siting.py) assembles a farm of real probes from one
station's record, each **recorded at its true depth**, for one 48-hour window, and asks
the check about each.

* **Control.** Every probe is where its record says. Anything but `consistent` is either
  a false alarm (`displaced`) or the check admitting it cannot see (`indeterminate`).
* **Unlogged moves.** A probe recorded at one depth is fed the readings actually taken at
  another. The real probe at that other depth stays, as a second probe at that depth would
  on a farm with redundancy. The check should say `displaced`, and the depth it implies
  should be near the true one.

Only readings ISMN rates good are used. Three stations (Allen Farms, Eastview Farm,
McAllister Farm), 2003–2026, weekly windows — about 10,000 in all.

## What the real soil gives the check to read

A real station is one profile with one probe per depth. Only the top three depths carry a
daily temperature wave strong enough to read:

| depth | daily amplitude |
| --- | --- |
| 5 cm | ±1.4 °C |
| 10 cm | ±0.9 °C |
| 20 cm | ±0.45 °C |
| 51 cm | ±0.06 °C |
| 1.02 m | ±0.01 °C |

So every shallow probe has exactly **two** usable peers. The check first required three —
which the simulated farm's twelve probes always met — and on real soil it said "cannot
tell" 73–100% of the time. Two peers at two depths is the minimum that fixes the line, so
the check now accepts two, widens its tolerance to 12 cm (two points give no scatter to set
it from, and cannot outvote a displaced peer), and marks the finding `robust: false`.

The real wave is also about four times weaker than the simulator's, whose bare-soil solar
gain is generous for vegetated ground. Simulator results on this check overstate it.

## Control: probes where their record says

| season | depth | consistent | displaced | cannot tell | median depth error |
| --- | --- | --- | --- | --- | --- |
| winter | 5 cm | 73% | 6% | 21% | 2.7 cm |
| winter | 10 cm | 80% | 3% | 17% | 1.7 cm |
| winter | 20 cm | 74% | 3% | 23% | 4.0 cm |
| spring | 5 cm | 93% | 3% | 4% | 2.5 cm |
| spring | 10 cm | 96% | 2% | 2% | 1.6 cm |
| spring | 20 cm | 91% | 4% | 6% | 3.5 cm |
| summer | 5 cm | 92% | 3% | 4% | 2.3 cm |
| summer | 10 cm | 97% | 2% | 1% | 1.6 cm |
| summer | 20 cm | 92% | 2% | 6% | 3.1 cm |
| autumn | 5 cm | 86% | 3% | 11% | 2.5 cm |
| autumn | 10 cm | 93% | 2% | 5% | 1.6 cm |
| autumn | 20 cm | 85% | 2% | 13% | 3.6 cm |

At 51 cm and 1 m the check says "cannot tell" 87–98% of the time, which is correct: there
is no wave there to read.

**The depth estimate works** — 1.6 to 4 cm median error in the root zone. **The false
alarms do not pass**: 2–4% per window, 6% at 5 cm in winter. Assessed once a day, that is
roughly one false `displaced` per probe per month.

## Unlogged moves

| move | recorded → really | caught (`displaced`) | median implied depth |
| --- | --- | --- | --- |
| lifted 15 cm | 20 → 5 cm | 86% winter, 92–96% otherwise | 5 cm |
| lifted 10 cm | 20 → 10 cm | 4–7% | 10 cm |
| pushed 10 cm | 10 → 20 cm | 3–11% | 20 cm |
| lifted 5 cm | 10 → 5 cm | 0% | 5 cm |
| pushed 31 cm | 20 → 51 cm | 4–13%; otherwise "cannot tell" | 51 cm |

The median implied depth is exactly right for **every** move. What fails to catch the
10 cm moves is the decision, not the estimate: 10 cm is under the 12 cm two-peer tolerance,
so the check knows where the probe is and declines to call it. A move to 51 cm goes where
the wave is too weak to read, and the check correctly says it cannot tell.

## A week, not a window

One window at a time, a correctly placed probe is called `displaced` often enough to
matter. A real move is permanent and shows on every day after it; a bad window rarely
repeats. So the check was run **every day** at all three stations — about 22,000 daily
windows per scenario — and scored under rules that require several of the last few days
to agree. Counted as *episodes*, runs of consecutive alarmed days, because that is what a
farmer is told about.

On profiles with no move — 169 probe-years, leaving out the McAllister period in the
next section:

| rule | false episodes per probe-year | 5 cm | 10 cm | 20 cm | 15 cm lift caught |
| --- | --- | --- | --- | --- | --- |
| one window | 3.87 | 5.94 | 1.49 | 4.17 | 100% |
| 2 of last 3 days | 0.76 | 1.28 | 0.20 | 0.82 | 100% |
| 3 of last 5 days | 0.29 | 0.59 | 0.00 | 0.28 | 100% |
| 4 of last 7 days | 0.15 | 0.37 | 0.00 | 0.09 | 100% |
| **5 of last 7 days** | **0.04** | 0.09 | 0.00 | 0.02 | **100%** |

"Caught" is the share of days on which the check could decide. **Five of the last seven**
takes false alarms from about four a year per probe to one in 25 probe-years, and still
catches a 15 cm lift on every day it can see one. It costs about a week — from any start
date, a 15 cm move is called after a median of 8 days, and always within 8 weeks — which
siting can afford: a probe at the wrong depth misleads slowly, and the
finding flags every reading from the first displaced day, not just the last two.

**Adopted** as `siting.assess_siting_persistent`, the function to act on. It returns
`displaced` only when five of the last seven daily assessments are, and widens the flagged
span to cover all of them. When today's window alone says `displaced`, it returns
`indeterminate` with the reason `siting.unconfirmed` ("displaced in 2 of the last 7 days")
rather than a quiet `consistent`.

**What persistence does not buy is resolution.** Two ways to use a week of windows to call
smaller moves were tried and rejected:

- *The median implied depth over 7 or 14 days, against a tighter tolerance.* At 5 or 6 cm
  it would catch a 10 cm move, but correctly recorded probes then alarm one to three times
  a year, because some implied depths sit 3–6 cm from the record for a decade. At Allen
  Farms before 2023 the 5 cm probe read as −1 cm and the 20 cm as 15 cm, year after year.
  The geometry in the next section traces both to the 10 cm probe sitting about 3 cm
  deeper than recorded — an installation error nobody would notice, amplified by
  extrapolation. That is a bias, and averaging does not remove a bias.
- *Change from the probe's own baseline* — the last 14 days against the half-year before.
  The implied depth also wanders with the season, as water content changes the soil's
  diffusivity: 0.3–1.7 false episodes per probe-year at 3–6 cm.

For a two-peer profile the practical floor is a little over 10 cm, set by how precisely
probes are really installed — and amplified by extrapolation — rather than by noise.

## The check found a real one

All of McAllister Farm's long "false alarm" episodes fall after **January 2023**, on the
20 cm probe. Through 2012–2021 the check implied 0.15–0.16 m for it; from 2023,
0.25–0.30 m. The cause turned out not to be the 20 cm probe.

The 10 cm temperature record has a gap from **2021-07-23 to 2023-01-15**, and ISMN's
metadata logs a **new sensor** at that position on **2023-01-17**, recorded at the same
depth, 10.16 cm. Suppose that probe alone changed, and the 5 and 20 cm probes are where
their records say. Then each probe's implied depth is fixed by geometry — each is read
against the line through the other two. With the 10 cm probe really at 12.0 cm before the
gap and 7.9 cm after (the depths the check itself implied for it, from the 5 and 20 cm
line), the check's yearly medians for 2012–2021 and 2023–2026 are reproduced:

| the probe recorded at | before 2023: predicted | observed | from 2023: predicted | observed |
| --- | --- | --- | --- | --- |
| 5 cm | 1.3 cm | 0–2 cm | 7.6 cm | 7–8 cm |
| 10 cm | 12.0 cm | 12 cm | 7.9 cm | 8 cm |
| 20 cm | 15.7 cm | 15–16 cm | 31 cm | 25–30 cm |

The last cell is an extrapolation, and sensitive: each millimetre of the 10 cm probe's
depth moves it by about a centimetre.

The amplitude, an independent reading of depth, says the same. Placed by its daily swing
against the 20 and 51 cm probes, whose swings did not change, the 10 cm probe sat at
**11.5–11.9 cm every summer 2015–2020** and **7.0–8.2 cm every summer 2023–2026**.

So the replacement 10 cm probe has read, since the day it went in, like one about 4 cm
shallower than the probe before it. The simplest explanation is that it was installed
shallower. Disturbed soil around a new installation could contribute, though it would be
expected to damp the wave rather than strengthen it. ISMN rates every one of these
readings good, and nothing in the record says the depth changed.

The check noticed — and **blamed the wrong probe**. The 10 cm probe's own offset, 2 cm
from its record, is within tolerance. But the 20 cm probe is judged by extrapolating a
line through the 5 and 10 cm probes, and that line now spanned 3 cm of real depth where the
record said 5. A 4 cm change in a peer became a 10–15 cm change in the probe extrapolated
from it. With two peers there is nothing to outvote, which is what the finding's
`robust: false` was written to say: *something in this profile moved*. Under 5 of 7 the
profile first alarmed on 2023-04-08, once spring brought the wave back, and on 8% of days
after. Which probe moved, and how to tell, is now
[open question Q25](../spec/open-questions.md), and largely answered in the next section.

The same arithmetic explains the bias before the gap: a 10 cm probe actually at 12 cm is
why McAllister's 5 cm probe read as 0–2 cm for a decade.

**Allen Farms shows the same thing, below the threshold.** Its 10 cm probe also went silent
in late July 2021 and was also replaced in January 2023 — the same week as McAllister's,
one field visit by the look of it. The same geometry says it went from about 13 cm to
about 11 cm, nearer its record, and every implied depth in the profile moved as that
predicts:

| the probe recorded at | before 2023: predicted | observed | from 2023: predicted | observed |
| --- | --- | --- | --- | --- |
| 5 cm | −1.4 cm | −3 to 2 cm | 3.3 cm | 3–6 cm |
| 10 cm | 13 cm | 12–14 cm | 11 cm | 10–11 cm |
| 20 cm | 14.4 cm | 14–16 cm | 17.5 cm | 18–22 cm |

A 2 cm change stays within tolerance, and nothing alarmed. Eastview Farm, where nothing was
replaced in 2023, is the control: its three probes imply 3–6, 9–11 and 18–22 cm in every
year from 2003 to 2026. (Amplitude placement is too noisy to use at Allen Farms, whose
51 cm swing is 0.04 °C.)

Both replacements went in at a different depth from the probe before. A replacement is
exactly when a depth error is most likely, and the record at both stations kept the old
depth.

## A deeper peer, over two weeks

The fix for a two-peer profile turned out to be already in the ground. Over two days only
5, 10 and 20 cm carry a wave above the check's 0.10 °C floor. Over fourteen days a fit
resolves a far smaller one, and the 51 cm probe every one of these stations has — its swing
0.04–0.10 °C — becomes a third peer. Three peers make the fit robust, so one displaced
peer is outvoted instead of blamed on its neighbour, and the tolerance tightens from 12 cm
to 8.

**Adopted** as `siting.assess_siting_weekly`: two-week windows, once a week, `displaced`
on 3 of the last 4. A peer needs a swing of 0.03 °C; the probe being judged still needs
0.10. Measured through the SDK, on profiles with no known disturbance:

| schedule | false episodes per probe-year | 15 cm move called | 10 cm move called within six months |
| --- | --- | --- | --- |
| daily, 5 of 7 | 0.04 | median 8 days; always within 8 weeks | 7–8% |
| weekly, 3 of 4 | 0.04 | median 5 weeks; always within 8 weeks | **78–83%**, median 5–9 weeks |

Counting Allen Farms after its 2023 visit as undisturbed, the weekly figure is 0.07 — see
below. The two are complements: the daily check catches a big move in a week, the weekly
one catches a 10 cm move the daily one almost never does, and attributes it.

**McAllister Farm, through the SDK.** The 20 cm probe's implied depth, by year:

| | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2023 | 2024 | 2025 | 2026 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| daily, two peers | 16 | 16 | 16 | 16 | 16 | 17 | 16 | **29** | **24** | **25** | **28** cm |
| weekly, three peers | 21 | 21 | 21 | 21 | 20 | 20 | 20 | 20 | 20 | 20 | 20 cm |

Daily, the 20 cm probe was called displaced in 26% of windows after 2023; weekly, in 1%.
The 10 cm probe, weekly, reads 12–13 cm through 2021 and 8 cm from 2023 — the change now
sits on the probe that changed, at a size, 2 cm from its record, below what either
schedule calls.

**Allen Farms may have a second disturbance.** Weekly, its 20 cm probe reads 20–23 cm
through 2021 and 26–27 cm from 2023, and is called displaced in 28% of windows after the
visit. Its sensor was not replaced. The daily figures fit "both the 10 cm probe (13 → 11
cm) and the 20 cm probe (20 → about 25 cm) changed at the 2023 visit" better than the
10 cm probe alone, which predicted 17.5 cm for the 20 cm probe where 18–23 was observed.
Digging to reach one probe can disturb its neighbour. That is a hypothesis, not a finding.

**Naming the culprit is harder than not blaming the wrong one.** With four probes, the
probe whose omission lets the other three line up best is the obvious candidate. On
constructed moves it is right 78–100% of the time for 10 cm or more, and 57–62% for 5 cm.
It cannot resolve the real 2–4 cm shifts. And with nothing moved, it still names someone —
at Eastview usually the 51 cm probe, which sits in a different soil horizon from the
others — so it may only speak when the profile as a whole fails to line up.

**Phase and amplitude together do not help, by the physics.** In uniform soil the log of
the daily swing and the lag of its peak are both straight lines in depth with the same
damping depth, so they are two noisy readings of one number per probe: any single-culprit
explanation still fits exactly. Measured, amplitude named the culprit about as often as
phase. What the pair does catch is a clock offset, which moves the phase and not the
swing.

## Caveats

- **One region, one sensor make.** Three Tennessee stations, Stevens Hydraprobes, humid
  subtropical climate. Snow cover and long overcast spells weaken the wave further north.
- **One profile per station.** Over two days a real station has two usable peers per
  probe; over two weeks, three. A farm with more probes per profile gets the robust fit
  even daily.
- **The moves are constructed.** Real moves happen once, not in every window; what is
  measured is how often a window would notice one already made. The one real event,
  McAllister's 10 cm replacement, is inferred from the readings: no record says where
  either probe was actually placed.

## Attribution

ISMN data is used under CC-BY-4.0; this note publishes only derived statistics. See
[ismn-scoring.md](ismn-scoring.md#attribution) for the citations. The SCAN stations are
operated by the USDA Natural Resources Conservation Service.

## Reproducing

```sh
cd /tmp
python3 -I ~/dev/librefarm/tools/ismn_siting.py ~/Downloads/ISMN_archive_20261008.zip \
    --stations AllenFarms,EastviewFarm,McAllisterFarm                 # weekly windows
python3 -I ~/dev/librefarm/tools/ismn_siting.py ~/Downloads/ISMN_archive_20261008.zip \
    --persistence --exclude McAllisterFarm:2023-01-17                  # daily, k-of-n
python3 -I ~/dev/librefarm/tools/ismn_siting.py ~/Downloads/ISMN_archive_20261008.zip \
    --persistence --weekly \
    --exclude McAllisterFarm:2023-01-17,AllenFarms:2023-01-20         # weekly, k-of-n
```

Run from a neutral directory with `-I`, because the archive is downloaded data. Each
persistence run takes about twelve minutes a station. The culprit-naming measurement was
a scratch analysis on the same windows and is not in the tool.
