#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Language packs: coverage, checks, and a starting file for a new language.

    python3 packs.py                       # every pack, how complete, how sound
    python3 packs.py new sw --name Swahili --native Kiswahili
    python3 packs.py new ar --name Arabic --native "العربية" --rtl
    python3 packs.py missing es            # the untranslated keys, for a translator

See docs/LANGUAGE_PACKS.md. No Python is needed to contribute a language — only the
JSON file this writes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "sdk"))
import i18n  # noqa: E402


def report() -> int:
    rows = []
    failures = 0
    for tag in i18n.available():
        pack = i18n.load(tag)
        done, total, _ = i18n.coverage(tag)
        problems = i18n.check_pack(tag)
        failures += bool(problems)
        rows.append((tag, pack.native_name, pack.status, pack.direction,
                     f"{done}/{total}", f"{done / total:.0%}",
                     "sound" if not problems else f"{len(problems)} problem(s)"))
    print(f"  {'tag':<7}{'language':<16}{'status':<10}{'dir':<5}"
          f"{'strings':>9}{'':>6}  checks")
    for tag, native, status, direction, frac, pct, verdict in rows:
        print(f"  {tag:<7}{native:<16}{status:<10}{direction:<5}"
              f"{frac:>9}{pct:>6}  {verdict}")
    for tag in i18n.available():
        for problem in i18n.check_pack(tag):
            print(f"  {tag}: {problem}")
    return 1 if failures else 0


def new(tag: str, name: str, native: str, rtl: bool) -> int:
    path = os.path.join(i18n.PACK_DIR, f"{tag}.json")
    if os.path.exists(path):
        print(f"{path} already exists; not overwriting someone's translation")
        return 1
    doc = i18n.scaffold(tag, name=name, native_name=native,
                        direction="rtl" if rtl else "ltr")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print(f"wrote {path}: {len(doc['strings'])} strings to translate, using "
          f"en.json as the source")
    return 0


def missing(tag: str) -> int:
    source = i18n.load("en").strings
    _, _, keys = i18n.coverage(tag)
    for key in keys:
        print(f"{key}\n    en: {source[key]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")
    n = sub.add_parser("new", help="start a pack for a new language")
    n.add_argument("tag", help="BCP 47 tag: sw, ar, hi, pt-BR")
    n.add_argument("--name", required=True, help="the language's name in English")
    n.add_argument("--native", required=True, help="its name in itself")
    n.add_argument("--rtl", action="store_true", help="written right to left")
    m = sub.add_parser("missing", help="list untranslated strings")
    m.add_argument("tag")
    args = ap.parse_args(argv)
    if args.command == "new":
        return new(args.tag, args.name, args.native, args.rtl)
    if args.command == "missing":
        return missing(args.tag)
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
