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

Code AGPL-3.0-or-later ([LICENSE](LICENSE)), like the reference server; strings in
[packs/](packs/) under the `rules.` prefix. It imports layer zero (the SDK and
`tools/nbm_verify.py` for the backtest) and nothing in layer zero imports it.
