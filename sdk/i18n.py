#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Language packs (spec v0.1 §11 layer 4: bilingual, and beyond).

A university deploying this for its own farmers should be able to add their language
**without writing code**: one JSON file in `sdk/packs/`, checked by `make packs`. That
is the whole design constraint, and everything below follows from it.

## The rule that comes before any translation

**The log, the API and every export carry codes, never translated text.** A quality
flag is `suspect`, an observed property is a CF URI, a unit is `cm3/cm3`, a decimal
point is a dot. Only *presentation* is localised. The alternative breaks things that
are not visibly about language: a CSV written with `0,292` in a Spanish locale does not
round-trip; a log whose notes are in whichever language the gateway was set to cannot
be read by the next maintainer; a flag stored as `sospechosa` is invisible to a query
for `suspect`.

So a finding stores a **message key and its parameters** — `check.range.above` with
`{"value": 0.52, "max": 0.46}` — and the English sentence is one rendering of it. A
Swahili interface renders the same log entry in Swahili, years later, from the same
record.

## Packs

Each pack is `{"_meta": {...}, "strings": {key: template}}`. Templates use named
fields with optional format specs, `"{value} above max {max}"`, `"{rate:.6g}/s"`.
`en.json` is the source: every key exists there, and a test fails if an enum value or
a vocabulary term has no English string.

A translation must use **exactly the same fields** as the English template. One that
drops `{depth}` silently loses a number; one that writes `{dept}` crashes at render
time in front of a farmer. `check_pack` enforces it, and rendering never raises — a
broken translation falls back to English and the fallback is recorded.

## Falling back, and saying so

`Translator("sw-KE")` tries `sw-KE`, then `sw`, then English. Every rendering reports
the language it actually came from, so an interface can mark an untranslated string
instead of passing English off as Swahili — the same rule `Label` follows.

## Numbers are regional, not linguistic

`decimal_separator` lives in a pack's metadata, with per-region overrides, because
Spanish does not decide it: Spain, Argentina and Colombia write `0,29`; Mexico and
Guatemala write `0.29`. It applies only to rendered text, never to data.
"""
from __future__ import annotations

import json
import os
import string
from dataclasses import dataclass, field
from enum import Enum

PACK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs")
SOURCE = "en"

#: The maturity a pack declares, in order. A farmer-facing deployment should not ship
#: a `draft` without saying so: a wrong agronomic term is worse than an English one,
#: because nobody can tell it is wrong.
STATUSES = ("source", "draft", "reviewed", "endorsed")


@dataclass(frozen=True, slots=True)
class Pack:
    tag: str
    name: str
    native_name: str
    direction: str
    status: str
    strings: dict
    decimal_separator: str = "."
    regions: dict = field(default_factory=dict)
    maintainers: tuple = ()
    note: str | None = None

    def separator_for(self, tag: str) -> str:
        return self.regions.get(tag, {}).get("decimal_separator",
                                             self.decimal_separator)


_CACHE: dict[str, Pack | None] = {}

#: Module pack directories, each with the key prefix its strings must carry. A module
#: (layer 1 and up) ships its own strings and registers them; layer zero never imports a
#: module, it only reads the files a module points it to.
_MODULES: list[tuple[str, str]] = []


def register(directory: str, prefix: str) -> None:
    """Merge a module's packs into every language that has one (§11).

    Every key in them must start with `prefix.` — a module's strings are its own and
    cannot shadow layer zero's, so a check message never changes because a module was
    installed. Idempotent; registering clears the cache so the next load sees them."""
    entry = (os.path.abspath(directory), prefix)
    if entry in _MODULES:
        return
    _MODULES.append(entry)
    _CACHE.clear()
    global ENGLISH
    try:
        ENGLISH = Translator(SOURCE)
    except ValueError:
        # Refused, and not left half-registered: every later load would fail too.
        _MODULES.remove(entry)
        _CACHE.clear()
        ENGLISH = Translator(SOURCE)
        raise


def _module_strings(tag: str, base: dict) -> dict:
    out = {}
    for directory, prefix in _MODULES:
        path = os.path.join(directory, f"{tag}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            strings = json.load(handle).get("strings", {})
        for key, value in strings.items():
            if not key.startswith(prefix + "."):
                raise ValueError(f"{path}: {key} is outside the module's prefix {prefix!r}")
            if key in base:
                raise ValueError(f"{path}: {key} would shadow layer zero's string")
            out[key] = value
    return out


def available() -> list[str]:
    """Every pack on disk, by tag."""
    if not os.path.isdir(PACK_DIR):
        return []
    return sorted(name[:-5] for name in os.listdir(PACK_DIR)
                  if name.endswith(".json"))


def load(tag: str) -> Pack | None:
    """The pack for exactly `tag`, or None if there is no such file."""
    if tag not in _CACHE:
        path = os.path.join(PACK_DIR, f"{tag}.json")
        if not os.path.exists(path):
            _CACHE[tag] = None
        else:
            with open(path, encoding="utf-8") as handle:
                doc = json.load(handle)
            meta = doc.get("_meta", {})
            _CACHE[tag] = Pack(
                tag=meta.get("language", tag), name=meta.get("name", tag),
                native_name=meta.get("native_name", tag),
                direction=meta.get("direction", "ltr"),
                status=meta.get("status", "draft"),
                strings={**doc.get("strings", {}),
                         **_module_strings(tag, doc.get("strings", {}))},
                decimal_separator=meta.get("decimal_separator", "."),
                regions=dict(meta.get("regions", {})),
                maintainers=tuple(meta.get("maintainers", ())),
                note=meta.get("note"))
    return _CACHE[tag]


def fields_of(template: str) -> set[str]:
    """The named fields a template uses, without their format specs."""
    out = set()
    for _, name, _, _ in string.Formatter().parse(template):
        if name is not None:
            out.add(name.split(".")[0].split("[")[0])
    return out


class _Number:
    """A number that formats with a pack's decimal separator — in text only."""

    __slots__ = ("value", "separator")

    def __init__(self, value, separator):
        self.value = value
        self.separator = separator

    def __format__(self, spec):
        text = format(self.value, spec)
        if self.separator == ".":
            return text
        # A template asking for thousands (`{n:,.0f}`) gets Python's comma, which in a
        # language that writes decimals with a comma reads as a decimal point: "20,696" is
        # twenty in Spain. Group with a point there, and the decimal is the comma.
        grouping = "." if self.separator == "," else ","
        return "".join(grouping if c == "," else self.separator if c == "." else c for c in text)

    def __str__(self):
        return self.__format__("")


@dataclass(frozen=True, slots=True)
class Rendered:
    """A rendered string and the language it actually came from."""

    text: str
    language: str
    fell_back: bool = False

    def __str__(self) -> str:
        return self.text


class Translator:
    """Renders keys in one language, falling back toward English and saying so."""

    __slots__ = ("language", "_chain", "_separator", "fallbacks")

    def __init__(self, language: str = SOURCE):
        self.language = language
        primary = language.split("-")[0]
        chain = []
        for tag in (language, primary, SOURCE):
            pack = load(tag)
            if pack is not None and pack not in chain:
                chain.append(pack)
        self._chain = chain
        regional = next((p for p in chain if p.tag.split("-")[0] == primary), None)
        self._separator = (regional.separator_for(language) if regional
                           else load(SOURCE).decimal_separator)
        #: Every key that had to fall back, so a deployment can report its gaps.
        self.fallbacks: set[str] = set()

    @property
    def direction(self) -> str:
        """`rtl` for Arabic, Urdu, Hebrew — a layout decision a UI must not guess."""
        return self._chain[0].direction if self._chain else "ltr"

    def text(self, key: str, **params) -> Rendered:
        """Render `key`. Never raises: a missing or broken string falls back."""
        wrapped = {k: (_Number(v, self._separator)
                       if isinstance(v, (int, float)) and not isinstance(v, bool)
                       else v)
                   for k, v in params.items()}
        for pack in self._chain:
            template = pack.strings.get(key)
            if not template:
                continue
            try:
                rendered = template.format(**wrapped)
            except (KeyError, IndexError, ValueError):
                # A translation with a wrong field must not reach a farmer as a
                # crash. Fall through to the next language and record why.
                self.fallbacks.add(key)
                continue
            # Judged by language, not by position: when no pack exists for the
            # requested language at all, English is first in the chain, and the first
            # version of this called that "not a fallback" — French rendered silently
            # in English, which is the exact failure this flag exists to expose.
            fell = pack.tag.split("-")[0] != self.language.split("-")[0]
            if fell:
                self.fallbacks.add(key)
            return Rendered(rendered, pack.tag, fell)
        self.fallbacks.add(key)
        return Rendered(key, "", True)

    def enum(self, value: Enum) -> Rendered:
        return self.text(f"enum.{type(value).__name__}.{value.value}")

    def term(self, uri: str) -> Rendered | None:
        """A vocabulary term's display name, or None if no pack names it."""
        rendered = self.text(f"term.{uri}")
        return None if rendered.language == "" else rendered

    def unit(self, code: str) -> Rendered | None:
        rendered = self.text(f"unit.{code}")
        return None if rendered.language == "" else rendered


#: The English translator every finding's `reason` is rendered with, so the readable
#: sentence in the log comes from the same source as every translation of it.
ENGLISH = Translator(SOURCE)


def english(key: str, **params) -> str:
    return ENGLISH.text(key, **params).text


# ------------------------------------------------------------------ tooling

def coverage(tag: str) -> tuple[int, int, list[str]]:
    """`(translated, total, missing)` against the English source."""
    source = load(SOURCE).strings
    pack = load(tag)
    have = pack.strings if pack else {}
    missing = sorted(k for k in source if not have.get(k))
    return len(source) - len(missing), len(source), missing


def check_pack(tag: str) -> list[str]:
    """Everything wrong with a pack that would hurt someone. Empty means sound."""
    problems = []
    pack = load(tag)
    if pack is None:
        return [f"no pack file for {tag}"]
    source = load(SOURCE).strings
    if pack.status not in STATUSES:
        problems.append(f"status {pack.status!r} is not one of {STATUSES}")
    if pack.direction not in ("ltr", "rtl"):
        problems.append(f"direction must be ltr or rtl, not {pack.direction!r}")
    if pack.status != "source" and not pack.note and pack.status == "draft":
        problems.append("a draft pack must say what it needs before it is "
                        "farmer-facing (`_meta.note`)")
    for key, template in pack.strings.items():
        if key not in source:
            problems.append(f"{key}: not a key in the English source — a typo, or "
                            f"a string that was removed")
            continue
        if not template:
            continue
        try:
            got = fields_of(template)
        except ValueError as exc:
            problems.append(f"{key}: malformed template ({exc})")
            continue
        want = fields_of(source[key])
        if got != want:
            problems.append(f"{key}: uses {sorted(got)} but the English uses "
                            f"{sorted(want)} — a dropped field loses a number, an "
                            f"extra one crashes at render time")
    return problems


def scaffold(tag: str, *, name: str, native_name: str,
             direction: str = "ltr") -> dict:
    """An empty pack with every key, for a translator to fill in."""
    source = load(SOURCE)
    return {
        "_meta": {
            "language": tag, "name": name, "native_name": native_name,
            "direction": direction, "status": "draft",
            "decimal_separator": ".", "regions": {}, "maintainers": [],
            "license": "Apache-2.0",
            "note": "Untranslated scaffold. Every string needs a translation reviewed "
                    "by a native speaker who knows the agronomy before this is shown "
                    "to farmers.",
        },
        "strings": {key: "" for key in source.strings},
    }
