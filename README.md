<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# fieldmesh

**Layer zero of a farmer-owned farm stack:** the data and device contract underneath
everything else. It covers what a reading is, what a device is, how a reading crosses an
unreliable radio link, how its quality is judged, and how a farmer gets all of it back
out.

*Formerly librefarm; renamed on 2026-10-10.*

It is **free software**: anyone may run it, study it, change it and share it, and the parts
a farm runs as a service stay free when someone changes them. Who decides, and how much of
it an AI wrote, is in [GOVERNANCE.md](GOVERNANCE.md).

Everything here is designed for the farm that cannot afford a good answer. That means
intermittent connectivity, battery power, cheap radios, and a log the farmer owns
outright.

> **Status: pre-release, built against a simulated farm.** There is no hardware in the
> loop yet, and no pilot farm. Commands — actually driving a pump or valve — are
> deliberately out of the first release (§6). See [What is not done](#what-is-not-done).
> Since 2026-10-20 the work is on what a pilot farm needs; choosing the advice's defaults
> on the simulator is paused until a real season's data exists.

## For a pilot farm

What a farm would run first, and what is still missing. The pilot itself (Q1) is two sites,
an extension or university plot and one working farm with poor connectivity, to be chosen
by February 2027 so the hardware goes in before spring.

* **On the farm:** a small Linux computer as the gateway, running the farm's log and each
  module as its own sandboxed service ([deploy/systemd](deploy/systemd/README.md)); soil
  probes in the beds, two per bed at least, so each can catch the other's drift
  ([which probes](docs/notes/soil-sensors.md#what-id-recommend)); a weather station or the
  nearest public one; phones for the alerts.
* **What it does today:** the soil-moisture advice each morning, per bed; the livestock
  water monitor; alerts to people by push, in their language, climbing until someone
  answers; the farm's own page; every reading's quality judged and kept; everything out
  in open formats.
* **What is missing before a pilot:** a real radio and device driver (build step 7); SMS
  through a real modem (Q29, which blocks the pilot); an install guide tried on one real
  bed; the legal entity and the liability cover (Q9).

## Try it

Tested on Python 3.12. The SDK has **two dependencies**: `cbor2`, for the CBOR wire format,
and `cryptography`, for erasure by key destruction (`pip install -r requirements.txt`, or
`python3-cbor2` and `python3-cryptography` on Debian and Ubuntu). Everything else is the
standard library. The modules' rules need `cel-python` and `starlark-pyo3`
(`modules/rules/requirements.txt`); the tests that need them skip without them. The
hoop-house twin runs GreenLight in an environment of its own (`modules/twin/requirements.txt`).
`make test` also runs the Q5 measurement tool's tests, which need `protobuf`:
`pip install -r requirements-tools.txt -r modules/rules/requirements.txt` installs what CI
installs. On Windows the `zoneinfo` module also wants `tzdata`.

```sh
make test       # every test, about ten minutes
make fast       # every test but the whole seasons, about two (the pre-push hook's)
make demo       # a log becomes derived state becomes a SensorThings document
make serve      # a SensorThings 1.1 endpoint over two simulated days, on this machine's :8080
make drill      # seed sensor faults, score the detectors against ground truth
make siting     # score the depth check against probe moves nobody logged
make export     # a week out in open formats, then verify it replays identically
make help       # everything else
```

`make serve` is readable by **QGIS 3.36+** through its SensorThings provider, and by
Fraunhofer's `frost-sta-client`. Both were used to find defects — see
[docs/notes/qgis-validation.md](docs/notes/qgis-validation.md).

## What is here

| | |
| --- | --- |
| [docs/spec/v0.1.md](docs/spec/v0.1.md) | **The contract.** §17 records every amendment, and most were found by running code rather than by reading |
| [docs/spec/open-questions.md](docs/spec/open-questions.md) | Every open decision, with every option and its trade-offs |
| [docs/UNTESTED.md](docs/UNTESTED.md) | Every claim not yet tested, in one place: what was checked instead, and what would close it |
| [GOVERNANCE.md](GOVERNANCE.md) | Who decides today, what is meant to change, and how much of this an AI wrote |
| [docs/VIRTUAL_FARM.md](docs/VIRTUAL_FARM.md) | Why the build is simulator-first, and the completeness matrix that turns a spec clause with nothing exercising it into a failing test |
| [docs/LANGUAGE_PACKS.md](docs/LANGUAGE_PACKS.md) | For a university adding its farmers' language — one JSON file, no code |
| [docs/notes/](docs/notes/) | Measurements and validations behind decisions: encoding, power, FROST, QGIS, public datasets, validation sites |
| [sdk/](sdk/) | The contract as code: model, append-only log, projection, farm records with offline edits, quality checks, wire format, gateway, SensorThings view, export, subscriptions, siting checks, CSV and MQTT adapters, language packs |
| [sim/](sim/) | **Harrow Bend**, a fictional farm on the prime meridian: soil water and heat physics, troughs, simulated nodes and radio links, fault injection, scored drills |
| [server/](server/) | A read-only SensorThings 1.1 HTTP service — the reference implementation |
| [deploy/](deploy/) | systemd units that run each module as its own sandboxed service, reaching the farm's data only through the module host's socket (§8.3, Q11), with the notifier's network, the board's page and the frost watch's evening timer as stated exceptions |
| [tools/](tools/) | The measurements behind decisions, weather and forecast adapters, and the language-pack tool |
| [modules/rules/](modules/rules/) | **Layer 1, rules and alerts**: CEL conditions over the log, each evaluation a logged decision, and Starlark regimens of steps, waits and checks. First rule: a frost watch, backtested on NOAA's forecasts against McAllister Farm's station. First regimen: did the watering reach the bed? |
| [modules/notify/](modules/notify/) | **Layer 1, alerts to people**: any module's alerts by push (ntfy) or SMS through the farm's own modem, in each person's language, climbing a route's tiers until someone answers "on it" by reply or button; alerts due together go as one message, and a weekly digest says what was sent and what it cost. Checked against a real ntfy server; SMS checked only against ModemManager's documented output, for want of a modem |
| [modules/board/](modules/board/) | **Layer 4, the farm's page**: one read-only page per language of the alerts that stand, who was told and who is on it, today's advice, the latest readings and what cleared. It says so when it has stopped updating |
| [modules/water/](modules/water/) | **Layer 2, the livestock water monitor**: empty, low, not refilling, unseen, untrusted, per trough, as advisory decisions in English and Spanish. Passes §15's acceptance test on the virtual farm, whose first run found two defects in the node's backlog handling |
| [modules/soilwater/](modules/soilwater/) | **Layer 2, the soil-moisture advisory**: each morning, per bed, water now and how much, rain coming, water soon, too wet, enough — or why it cannot say. Backtested on a recorded summer: 72% less water than a drip timer with no hour of stress. Its watering check, the first regimen, says when a watering never reached the bed: 25 of 25 such waterings caught on two summers, no false alarm |
| [modules/zoneflow/](modules/zoneflow/) | **Layer 2, the zone flow check** *(experimental)*: each irrigation zone's runs beside its usual flow and its heads, a clogged or broken head said; drilled on simulated seasons |
| [modules/sowing/](modules/sowing/) | **Layer 2, sowing** *(experimental)*: each morning, whether a bed's soil at seed depth is warm enough to sow each crop meant for it, from Harrington's germination tables |
| [modules/salinity/](modules/salinity/) | **Layer 2, salt** *(experimental)*: a bed's salt from its probe's bulk conductivity, beside its crop's tolerance |
| [modules/probewatch/](modules/probewatch/) | **Layer 2, the probe watch** *(experimental, optional add-on)*: each soil probe against what its neighbours, the rain and the air say it should read, by Timestral, whose weights' licence the farm must accept; in a bed of two, which probe is the likelier one off. It does not see a slow drift |
| [modules/twin/](modules/twin/) | **Layer 3, a physics twin for the hoop house** *(experimental)* (Q28): Wageningen's GreenLight configured as an unheated single-poly tunnel, on the farm's real weather. It found the virtual farm's tunnel too warm at night (now refitted) and a defect in GreenLight's crop model. Its covered-crop frost watch, backtested on a season, warned of every damaging frost inside a tunnel, and found that a Tennessee winter gets into one most nights; it runs each evening on the farm's forecast. Set beside a tunnel's own sensor, it says when the two part company: a sensor off by 4 °C, a lost sun shield, sides left open |
| [modules/advise/](modules/advise/) | **The first module above layer zero** *(experimental)* (layer 3, decision support): for any point, what grows and when to sow it, which fruit cultivars get their chill and how often frost follows bloom, what the soil needs, bees, livestock heat, and the 2050s — in English and Spanish |

About 1,700 tests. The simulator runs a 180-day season in under eight minutes.

**Maintained** are layer zero (`sdk/`, `server/`, `sim/`, `tools/`, `deploy/`) and the
modules a pilot runs: rules, notify, board, water and soilwater. **Experimental, frozen
since 2026-10-20** are advise, twin, zoneflow, sowing, salinity and probewatch with its
optional Timestral add-on: kept working and tested, no new features until a pilot asks for
one ([GOVERNANCE](GOVERNANCE.md#which-modules-are-maintained)).

## A few things this does that are easy to get wrong

- **Nothing is overwritten.** Readings, calibrations, quality judgements, device
  sitings and even names are append-only. A correction is a new record. A recalibration
  supersedes, and the raw reading stays the archival truth.
- **Quality is a judgement with provenance**, not a column. It records who or what
  asserted it, under which threshold version, with the evidence. A person outranks the
  machine, and a retune never silently re-flags history.
- **The offline case is the main case.** Readings are stamped by when they were taken,
  not when they arrived. A delayed batch keeps the calibration that was in force when it
  was measured. A subscriber's cursor cannot miss an edit that syncs late.
- **The installation record is checked against physics.** A probe's daily temperature
  wave shows its depth, and a GPS-timed node's fix shows where it stands. A move nobody
  logged gets flagged — with the check's blind spots stated rather than hidden.
- **Two phones, one record, no signal.** An edit names what its writer had already
  seen, so a later edit follows an earlier one whatever either clock said. Concurrent
  changes to a harvest's weight, a spray's rate or an animal's withdrawal keep both
  values and ask a person, and the withdrawal check reads the longer of the two meanwhile.
- **Records store codes, never translated text.** Interfaces render them in the
  reader's language, including languages that had no pack when the record was written.
- **Every export verifies.** The archive replays into an identical log, and each file
  says whether it is lossless. Losslessness is checked by decoding, not assumed.

## Licensing

Three licences, one per kind of artifact, all of them free-software and free-culture
licences. The full reasoning is in [LICENSING.md](LICENSING.md).

| | |
| --- | --- |
| `docs/` — the spec and all prose | CC-BY-4.0 |
| `sdk/`, `sim/`, `tools/`, `deploy/` | Apache-2.0 — embeddable in firmware |
| `server/` | AGPL-3.0-or-later — so a hosting vendor cannot enclose a farmer-owned stack |
| `modules/rules/` | AGPL-3.0-or-later, as the reference server |
| `modules/notify/`, `modules/water/`, `modules/soilwater/`, `modules/zoneflow/`, `modules/sowing/`, `modules/salinity/`, `modules/probewatch/`, `modules/twin/`, `modules/board/` | AGPL-3.0-or-later, the same; GreenLight, which the twin installs, is BSD-3-Clause-Clear; Timestral's weights, which the probe watch can load, are under Mistral AI's Modified MIT licence and are not part of fieldmesh |
| `modules/advise/` | AGPL-3.0-or-later for code, the same reasoning; its data under each source's licence ([MANIFEST](modules/advise/data/MANIFEST.csv)) |

Some of `sdk/` derives from **campus_twin**, by the same author. See
[sdk/PROVENANCE.md](sdk/PROVENANCE.md).

## What is not done

Plainly, so nobody has to discover it:

- **No hardware.** Build step 7 — one real radio and one real device driver — is decided
  ([Q6](docs/spec/open-questions.md): Meshtastic first, a wired Modbus control) and waits
  on the hardware itself.
- **No pilot farm** ([Q1](docs/spec/open-questions.md)). The approach is decided and the
  letters drafted; nobody has been asked yet. Seasons do not reschedule.
- **No commands.** §6 is deferred until a season of field evidence exists. Of the three
  acceptance apps, the livestock water monitor is built (read-only, so it needs none);
  the irrigation controller waits on §6 and the research logger is not built.
- **Little above layer zero that a farm has run.** Eleven modules exist. Five are
  maintained: rules and the notifier (layer 1), the livestock water monitor and the
  soil-moisture advisory (layer 2), and a read-only farm page (layer 4). Six are
  experimental and frozen: the zone flow check, sowing, salt and the probe watch (layer
  2), the advisor and the hoop-house twin (layer 3). There is no field app, and the
  ecosystem (5) is described in §11 and does not exist; no app writes the farm's records
  yet. SMS has not met a real modem.
- **The advice's defaults are chosen on the simulator alone.** Every trial, its sealed
  sites included, runs on a virtual farm whose physics fieldmesh wrote, so the sealed
  sites change the weather and not the physics. Choosing more defaults that way is paused
  (2026-10-20) until a pilot season's data can say whether the simulator is right.
- **Two rows of the completeness matrix are skipped**, the two that need §6. The farm's
  records exist (land, animals, inputs, treatments, harvests, with offline conflicts), but
  no app writes them yet and nothing projects them to farmOS (Q8).
- **The Spanish language pack is an unreviewed draft.** It needs a native-speaking
  agronomist before farmers see it.
- **Hardened, but never yet faced the internet.** The HTTP server asks every request for
  a token, answers a sharing grantee from what their grant covers and nothing else,
  refuses to listen beyond the machine without TLS, and rate-limits and times out its
  clients. Nobody outside has tried to break it.
- **Everything not yet tested is listed in [docs/UNTESTED.md](docs/UNTESTED.md)**, with
  what was checked instead and what would close each gap.
