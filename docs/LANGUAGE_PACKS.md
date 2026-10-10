<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Language packs

**For a university, extension service or farmer organisation that wants fieldmesh to
speak its people's language.** No programming is needed: a language is one JSON file.

```sh
make packs                                   # every language, how complete, how sound
cd tools && python3 packs.py new sw --name Swahili --native Kiswahili
cd tools && python3 packs.py new ar --name Arabic --native "العربية" --rtl
cd tools && python3 packs.py missing sw      # what is left to translate
```

`new` writes `sdk/packs/<tag>.json` with every string empty. Fill in the `strings`,
run `make packs` and `make test`, and the file is ready to contribute.

## The one rule that is not about language

**The farm's records never contain translated text.** A quality flag is stored as
`suspect`, a measured property as a CF vocabulary address, a unit as `cm3/cm3`, a
decimal as `0.29`. Translation happens only when something is *shown* to a person.

This is what lets your pack work on records written before it existed, by people who
never chose your language. A reading flagged three seasons ago on a farm in Tennessee
renders in Swahili today, from the same record. It is also what keeps exports, the API
and queries working everywhere: a flag stored as `sospechosa` would be invisible to a
search for `suspect`, and a CSV written with `0,29` would not read back in.

So you translate **what people see** — the names of flags and states, measured
properties, units, and the sentences that explain why a reading was flagged. You never
translate a code, a key, or a field name.

## What a pack contains

```json
{
 "_meta": {
  "language": "pt-BR",
  "name": "Portuguese (Brazil)",
  "native_name": "português",
  "direction": "ltr",
  "status": "draft",
  "decimal_separator": ",",
  "regions": {},
  "maintainers": ["Departamento de Ciência do Solo, ..."],
  "license": "Apache-2.0",
  "note": "What it still needs before farmers see it."
 },
 "strings": {
  "enum.QualityFlag.suspect": "suspeita",
  "check.range.above": "{value} acima do máximo de {max}",
  "term.http://vocab.nerc.ac.uk/standard_name/soil_temperature/": "temperatura do solo"
 }
}
```

Four families of string:

| prefix | what it is | example |
| --- | --- | --- |
| `enum.` | a code shown to a person | `enum.Usable.questionable` |
| `term.` | a measured property, by its vocabulary address | soil temperature |
| `unit.` | a unit's name (its symbol stays `cm3/cm3`) | degree Celsius |
| `check.`, `siting.` | why something was flagged, as a sentence | "0.52 above max 0.46" |

## Rules a check will hold you to

**Use exactly the fields the English uses.** `{value}`, `{max}`, `{depth}` — the same
names, each one present. Move them anywhere in the sentence; your grammar decides the
order. A dropped field silently loses a number a farmer needed; a misspelt one would
crash an interface, so `make packs` refuses both. Format specs like `{span:.0f}` may be
kept or changed.

**Whole sentences, never fragments.** Where English differs only by one word — "0.17 m
shallower" against "0.17 m deeper" — there are two complete strings, because in many
languages the comparative is not a word that slots in. If a sentence still forces your
grammar into an awkward shape, say so in an issue; the right fix is a new key, not a
contorted translation.

**Decimals belong to the region, not the language.** Set `decimal_separator` for your
language and override it per region. Spanish does this: a comma by default, a point for
`es-MX`, `es-GT` and `es-US`. It changes only what is displayed, never the data.

**Right-to-left languages set `"direction": "rtl"`.** Arabic, Urdu, Hebrew, Persian,
Pashto. Interfaces read it rather than guessing.

## Falling back, honestly

A missing string falls back — `sw-KE` to `sw`, then to English — and the interface is
told it happened. A UI should mark a fallback rather than pass English off as your
language, which is how untranslated strings get found and fixed instead of shipped.
A half-finished pack is therefore safe to use: every gap is visible.

## Status: say how far it can be trusted

| status | meaning |
| --- | --- |
| `draft` | translated but unreviewed. **Must** carry a `note` saying what it needs |
| `reviewed` | checked by a native speaker who knows the agronomy |
| `endorsed` | adopted by an institution that will maintain it |

**The review is the important part.** A wrong agronomic word is worse than an English
one, because nobody can tell it is wrong. "Stuck", "suspect", "field capacity" and
"wilting point" all have plausible translations that mean something different to a
soil scientist. Machine translation is a fine way to start a draft and the wrong way to
finish one. The Spanish pack shipped here is a draft for exactly this reason, and it is
looking for a maintainer.

## Where good translations already exist

**AGROVOC**, maintained by the FAO, carries agricultural concepts in more than forty
languages and is already the vocabulary fieldmesh uses for crops, practices and records
(see [open-questions Q4](spec/open-questions.md)). For those terms, start from AGROVOC
rather than translating from scratch — your farmers' extension materials probably
already use its words. The CF names for physical measurements have no official
translations, which is why packs carry them.

## Modules have their own packs

A module above layer zero ships its own strings, in its own `packs/<tag>.json`, every key
starting with the module's name — the advisor's are all `advise.*`, in
[modules/advise/packs/](../modules/advise/packs/). They are merged over layer zero's pack
of the same language when the module loads, and a module key can never replace one of
layer zero's. `make packs` checks both. A translator can take on layer zero's ~100 strings
— the ones a farmer meets in every quality flag and unit — without also taking on a crop
report, and the other way round.

## Licence

Packs live in `sdk/` and are Apache-2.0 like the SDK, so a device maker can ship your
translation inside a product without a second licence. A module's packs carry the module's
licence — the advisor's are AGPL-3.0-or-later. JSON cannot carry a comment, so the licence
is the `_meta.license` field. See [LICENSING.md](../LICENSING.md).
