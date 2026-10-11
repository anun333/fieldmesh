<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Contributing

Thank you for looking. fieldmesh is free software, and a farmer-owned farm-data stack: a specification, an SDK
that implements it, a simulated farm that tests it, a reference server, and modules above it.
Start with [README.md](README.md) and the specification, [docs/spec/v0.1.md](docs/spec/v0.1.md).

## Ways in

* **A language.** Farmers read the reports and flags in their own language, and adding one
  needs no code — one JSON file. See [docs/LANGUAGE_PACKS.md](docs/LANGUAGE_PACKS.md). The
  Spanish pack is a draft waiting for a native speaker who knows farming.
* **A question in the spec.** Open design questions, each with every option considered, are in
  [docs/spec/open-questions.md](docs/spec/open-questions.md). Argue with a recommendation
  there; a reversal is cheap when the reasoning is written down.
* **Data.** Measurements that test a check against real sensors are worth more than code.
  The validations so far are in [docs/notes/](docs/notes/).
* **Code.** Bugs, drivers, adapters, modules.

## Before a pull request

```sh
pip install -r requirements-tools.txt -r modules/rules/requirements.txt   # what CI installs
make test     # every test: sdk, tools, sim, server, modules (about five minutes)
make packs    # language packs complete and sound
```

Tests that need a dependency you have not installed skip and say which; GreenLight's runs
need the twin's own environment (`modules/twin/requirements.txt`).

* Write code that reads like the code around it.
* A change to the specification is recorded as an amendment in §17 of
  [docs/spec/v0.1.md](docs/spec/v0.1.md), with the evidence that motivated it.
* Data that enters `modules/advise/data/` carries its source and licence in
  [MANIFEST.csv](modules/advise/data/MANIFEST.csv), and the manifest's test must pass. Only
  data under terms that allow commercial reuse is accepted — the reason is in
  [LICENSING.md](LICENSING.md).
* Nothing in `sdk/`, `server/`, `sim/` or `tools/` may import from `modules/`
  (`tools/test_layering.py` checks).
* Never commit credentials, personal data or a farm's private records.

## Licences

A contribution is taken under the licence of the directory it lands in — the specification
and prose CC BY 4.0, the SDK, simulator and tools Apache-2.0, the server and modules
AGPL-3.0-or-later — and its author keeps their copyright. There is no contributor licence
agreement. See [LICENSING.md](LICENSING.md).

## Written with an AI tool

Welcome, disclosed: add a `Co-Authored-By:` trailer naming the tool, as every commit here
does. The same tests and evidence apply. Why it is disclosed is in
[GOVERNANCE.md](GOVERNANCE.md#written-with-ai).

## Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
