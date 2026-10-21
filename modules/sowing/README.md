<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/sowing/` — is the soil warm enough to sow? (layer 2)

> **Experimental, frozen since 2026-10-20** ([GOVERNANCE](../../GOVERNANCE.md#which-modules-are-maintained)): kept working and tested, with fixes, but no new features until a pilot farm asks for one.

Each morning, for each bed and each crop the farmer means to sow in it: the soil's
temperature at seed depth over the last three days, against the temperatures that crop's
seed germinates at, and about how many days the seedlings take to come up. A seed sown
into soil too cold for it rots or waits; into soil too warm, it comes up thin.

| advice | when the soil at seed depth has averaged, over three days |
| --- | --- |
| **not yet** | below the temperature under which the seed hardly germinates |
| **slow**, and the days to emergence | above that, below the range it germinates best in |
| **good**, and the days | within that range |
| **warm**: it will come up, but less well | above the range, below the limit |
| **too warm** | above the temperature over which it hardly germinates |
| **no advice**, and why | no soil temperature probe within 10 cm of the surface; nothing heard for six hours; under a day of readings; the newest reading flagged |

> Not yet for beans in bed 3: the soil at 5 cm has averaged 11.9 °C over the last three
> days, and the seed needs at least 16 °C to germinate.

> Sown in bed 3 now, tomatoes would come up slowly: the soil at 5 cm has averaged 11.9 °C,
> below the seed's best range of 16 to 29 °C. Seedlings in about 23 days.

> Buen suelo para sembrar lechuga en bancal 3: 11,9 °C a 5 cm en los últimos tres días,
> dentro del mejor rango de la semilla, de 4 a 27 °C. Plántulas en unos 5 días.

(The test's bed, its soil swinging 4 °C either side of 12 °C each day.)

## Where the temperatures come from

**J. F. Harrington's tables** (University of California at Davis, Agricultural Extension
Leaflet, 1954), still printed by extension services:

* for 24 vegetables, the soil temperature below which the seed hardly germinates, the range
  it germinates best in, its optimum, and the temperature above which it hardly
  germinates;
* for 21 of them, the days to emergence at nine soil temperatures from 0 to 40 °C, the
  seed half an inch deep.

`data/germination-harrington.csv` holds both, in Harrington's degrees Fahrenheit, built
from Oregon State University Extension's copy of the first table and a University of
California handout's copy of the second, which gives the days to a tenth
([data/MANIFEST.csv](data/MANIFEST.csv)). One cell differs from Oregon State's page:
cabbage's best range is 45 to 95 °F, as other copies of the table print it, where that
page prints "45–5". The numbers are facts, reproduced with credit.

* **Days between Harrington's temperatures** are interpolated in germination *rate*, one
  over the days, which rises roughly in proportion to the temperature above a base; days
  do not. Half way from 20 °C to 25 °C, tomatoes take 6.9 days, not the 7.05 the days'
  mean would say. Next to a temperature where the seed hardly germinated, there is no
  estimate.
* **His temperatures were held constant; a field's soil is not.** It is warm by day and
  cool by night, more so near the surface. The advice reads the three days' mean, so a
  soil swinging either side of a limit reads as its middle. That is how extension advice
  reads a soil thermometer too, and it is the place this is most likely to be wrong.

## How the bed's soil is read

**The probe is found, not configured**, as for the [soil-moisture advisory](../soilwater/):
the soil temperature series whose device is installed in the bed, no deeper than 10 cm,
the shallowest there is. Most soil-moisture probes report temperature from the same body
(TEROS 12, HydraProbe, the LoRaWAN probes); a bare temperature probe is cheap. Only
readings the health checks had passed by the morning count.

Read-only and advisory. Each advice is a CEL rule judged through layer 1
([modules/rules](../rules/)), and one decision is written a crop a bed a morning, the
morning's answer on its topic (`sowing/<bed>/<crop>`). The crop is named in the reader's
language when the decision is rendered: the rule marks it as a language-pack key
(`Rule.key_params`), so the board and the notifier say "beans" or "frijoles" without
knowing this module.

```sh
pip install -r modules/sowing/requirements.txt          # cel-python, via modules/rules
cd modules/sowing && python3 -m unittest discover -p 'test_*.py'
python3 sowing.py --socket … --config beds.json         # as a module process (§8.3)
```

with `beds.json` as `{"beds": [{"feature": "…the bed's land…", "crops": ["bean", "lettuce"]}]}`.
The crops are the CSV's names: asparagus, bean, beet, cabbage, carrot, cauliflower,
chard, corn (sweet), cucumber, eggplant, lettuce, muskmelon, onion, parsley, parsnip,
pea, pepper, pumpkin, radish, spinach, squash, tomato, turnip, watermelon.

## Not tested

It has not met a real bed ([UNTESTED](../../docs/UNTESTED.md)):

* the temperatures are Harrington's constant-temperature figures, not a field's daily swing;
* his days are for seed half an inch deep; a probe at 5 cm reads cooler by day and
  warmer by night than the seed;
* no season has been sown by it and the emergence dates counted.
