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
pip install -r modules/rules/requirements.txt          # cel-python, Apache-2.0
python3 modules/rules/frost_backtest.py --cache NBM_CACHE --from 2025-10-15 --to 2026-04-30
cd modules/rules && python3 -m unittest discover -p 'test_*.py'
```

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
