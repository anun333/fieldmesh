<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/rules/` — rules and alerts (layer 1)

The first layer-1 module (spec v0.1 §11): rules written as **CEL conditions** (open-questions
Q10) over a context built from the log, each evaluation written back as a **decision
event** (§7.7) that names the observations it read, the rule and its version, the
condition as written, the conclusion and the trust level. Everything here runs as
*advisory*: it says, it never acts.

The first rule is the **frost watch**: at dusk, will tonight's forecast low reach the
farm's warning threshold? Backtested as §11 requires, on NOAA's forecasts for McAllister
Farm against its SCAN station, October 2025 to April 2026, through CEL:

| warn at | frosts warned | missed | false alerts |
| --- | --- | --- | --- |
| +1 °C | 38 of 38 | 0 | 8 |
| **0 °C** | **38 of 38** | **0** | **6** |
| −1 °C | 37 of 38 | 1 | 2 |
| −2.2 °C | 34 of 38 | 4 | 0 |

The same numbers the Python scoring gave when the threshold was chosen
([docs/notes/forecasts.md](../../docs/notes/forecasts.md)) — the rule language changes how a
rule is written and logged, not what it concludes.

```sh
pip install -r modules/rules/requirements.txt          # cel-python and starlark-pyo3, Apache-2.0
python3 modules/rules/frost_backtest.py --cache NBM_CACHE --from 2025-10-15 --to 2026-04-30
cd modules/rules && python3 -m unittest discover -p 'test_*.py'
```

## Regimens

A condition is one expression. A *regimen* is a sequence: water bed 3, wait for it to soak
in, check the probe saw it. Q10 chose **Starlark** for these, and
[regimen.py](regimen.py) runs them on starlark-pyo3 (Apache-2.0), a binding to the Rust
implementation. A regimen is a file defining `plan(ctx, params)` that returns steps built
with `say(...)`, `wait(minutes)` and `check(condition, ...)`. Starlark plans, CEL checks,
and the runner keeps time. Each step's outcome is a decision (§7.7) carrying the regimen's
version and the SHA-256 of its source, and a run's plan is logged when it starts, so a
restarted runner carries on without planning again on data that has since changed.

A regimen cannot reach the world, and the tests hold it to that. `open`, `load`,
`import`, `while`, recursion and a hundred-million-step loop are each refused: the last by
an instruction budget of about a million. A plan that is not a plan is refused too: an
unknown step, a malformed message key, a wait into the past or past fourteen days, a
condition that does not compile as CEL. Nothing acts while commands wait on §6, so every
step is advisory. The first regimen is the soil advisory's
[watering check](../soilwater/README.md#did-the-water-arrive).

## A decision anyone can read

A decision carries enough to be said and placed without the module that made it, so a
notifier or a page can carry any module's alerts without importing any module:

* **Its sentence.** `message.key` is chosen when the rule is judged — a rule's
  `message_variants` pick the sentence that fits ("not refilling, and the stock are not
  drinking" has no hours left to give) — and `message.params` fill it.
* **What it is about.** `subject` names an entity and `message.subject_param` the slot
  its label fills, in the reader's language (`rules.render(decision, language, state)`).
* **Which question it answers.** `topic` defaults to the rule and its subject: "is the
  north trough empty?" The soil advisory answers "what does bed 3 need today?" whichever
  rule held, so it names its own. The latest decision on a topic is the standing answer
  (`rules.standing`), and `valid_until` says when an answer goes stale: tonight's frost
  watch stands until dawn, a morning's soil advice for a day, a raised trough alert until
  the monitor clears it.

Code AGPL-3.0-or-later ([LICENSE](LICENSE)), like the reference server; strings in
[packs/](packs/) under the `rules.` prefix. It imports layer zero (the SDK and
`tools/nbm_verify.py` for the backtest) and nothing in layer zero imports it.
