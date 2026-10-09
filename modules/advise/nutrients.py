#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manure against crops: what the farm's animals supply, what its harvests remove.

    python3 modules/advise/nutrients.py \\
        --animals "dairy slurry:60:1375" "broiler litter:20000:4.5" \\
        --crops "corn silage:20:tons:40" "tall fescue:3.5:tons:30" \\
        [--soil-test-p high] [--organic] [--lang es]

`--animals` is system:head:average live weight in lb; `--crops` is crop:yield:unit:acres,
unit being bu, tons or lb (wet tons for silage, as farmers weigh it). Both tables are the
USDA NRCS Agricultural Waste Management Field Handbook's, public domain: manure as it
leaves each handling system (Table 4-16b) and nutrients removed in the harvested crop
(Table 6-6). Phosphorus and potassium are given as the oxides a fertilizer bag uses.

**A balance, not a recommendation.** It says how much nitrogen, phosphate and potash the
manure carries and the harvests remove, and so how many acres the manure needs to be
spread at what the crops take away. How much of the manure's nitrogen a crop gets in its
first year depends on how and when it is spread; how much the soil needs depends on its
own test. With a soil test that reads phosphorus high, the plan is held to the crops'
phosphate removal, as NRCS nutrient management does where phosphorus already builds up;
otherwise to their nitrogen. The certified organic rule (7 CFR 205.203(c)) is shown with
`--organic`: raw manure 120 days before a harvest that touches the soil, 90 otherwise.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, HERE)
import i18n  # noqa: E402
import module  # noqa: E402

module.register_packs()
DATA = os.path.join(HERE, "data")
P_TO_P2O5, K_TO_K2O = 2.29, 1.20          # Table 4-2's factors, elemental to oxide
#: Crops whose eaten part touches the soil, for the organic 120-day interval.
SOIL_CONTACT = {"carrots", "potatoes", "sweet potatoes", "table beets", "onions", "lettuce",
                "cabbage", "cucumbers", "cantaloupe", "peanuts", "bell peppers", "tomatoes",
                "snap beans", "peas"}


def _read(name: str) -> list:
    with open(os.path.join(DATA, name), encoding="utf-8") as h:
        return list(csv.DictReader(line for line in h if not line.startswith("#")))


def manure_table() -> dict:
    return {r["system"]: r for r in _read("manure-nutrients-awmfh.csv")}


def crop_table() -> dict:
    return {r["crop"]: r for r in _read("crop-removal-awmfh.csv")}


def manure_supply(system: dict, head: float, weight_lb: float, days: float = 365.0) -> dict:
    """lb a year of N (as TKN), P2O5 and K2O from `head` animals of `weight_lb`."""
    au = head * weight_lb / 1000.0
    return {"n": au * float(system["tkn_lb_per_au_day"]) * days,
            "p2o5": au * float(system["p_lb_per_au_day"]) * days * P_TO_P2O5,
            "k2o": au * float(system["k_lb_per_au_day"]) * days * K_TO_K2O}


def harvested_lb(crop: dict, amount: float, unit: str) -> float:
    """The harvest in lb of the material the concentrations refer to, per acre."""
    if unit == "bu":
        if not crop["lb_per_bu"]:
            raise ValueError(f"{crop['crop']}: the handbook gives no bushel weight; give lb or tons")
        return amount * float(crop["lb_per_bu"])
    lb = amount * (2000.0 if unit == "tons" else 1.0)
    typical = crop["typical_yield"]
    if "wet/" in typical:
        # Silage is weighed wet, the concentrations are of its dry matter.
        wet, dry = (float(x.split()[0]) for x in typical.replace(" tons", "").split("/"))
        lb *= dry / wet
    return lb


def removal(crop: dict, amount: float, unit: str) -> dict:
    """lb an acre of N, P2O5 and K2O removed by a harvest of `amount` `unit`."""
    lb = harvested_lb(crop, amount, unit)
    return {"n": lb * float(crop["n_pct"]) / 100.0,
            "p2o5": lb * float(crop["p_pct"]) / 100.0 * P_TO_P2O5,
            "k2o": lb * float(crop["k_pct"]) / 100.0 * K_TO_K2O}


def balance(animals: list, crops: list, soil_test_p: str | None = None) -> dict:
    """`animals`: [(system, head, weight lb)], `crops`: [(crop, yield, unit, acres)]."""
    systems, table = manure_table(), crop_table()
    supply = {"n": 0.0, "p2o5": 0.0, "k2o": 0.0}
    for system, head, weight in animals:
        if system not in systems:
            raise ValueError(f"unknown system {system!r}; the handbook's are: {', '.join(systems)}")
        for k, v in manure_supply(systems[system], head, weight).items():
            supply[k] += v
    removed, acres = {"n": 0.0, "p2o5": 0.0, "k2o": 0.0}, 0.0
    per_acre = []
    for name, amount, unit, area in crops:
        if name not in table:
            raise ValueError(f"unknown crop {name!r}")
        r = removal(table[name], amount, unit)
        per_acre.append((name, r, area))
        for k, v in r.items():
            removed[k] += v * area
        acres += area
    limit = "p2o5" if (soil_test_p or "").lower() in ("high", "very high", "excessive") else "n"
    need = (supply[limit] / (removed[limit] / acres)) if removed[limit] else None
    return {"supply": supply, "removed": removed, "acres": acres, "per_acre": per_acre,
            "limit": limit, "acres_needed": need}


def render(result: dict, *, organic: bool = False, language: str = "en") -> str:
    t = i18n.Translator(language)
    tr = lambda key, **kw: str(t.text(key, **kw))
    s, r = result["supply"], result["removed"]
    out = [f"## {tr('advise.nutrients.title')}", "",
           "- " + tr("advise.nutrients.supply", n=s["n"], p=s["p2o5"], k=s["k2o"]),
           "- " + tr("advise.nutrients.removed", n=r["n"], p=r["p2o5"], k=r["k2o"], acres=result["acres"])]
    for name, per, area in result["per_acre"]:
        out.append("  - " + tr("advise.nutrients.crop", crop=name, n=per["n"], p=per["p2o5"], k=per["k2o"]))
    if result["acres_needed"] is not None:
        key = "advise.nutrients.acres_p" if result["limit"] == "p2o5" else "advise.nutrients.acres_n"
        out.append("- " + tr(key, need=result["acres_needed"], have=result["acres"]))
    out.append("")
    out.append("*" + tr("advise.nutrients.caveat") + "*")
    if organic:
        out += ["", "- " + tr("advise.nutrients.organic")]
        for name, _, _ in result["per_acre"]:
            days = 120 if name in SOIL_CONTACT else 90
            out.append("  - " + tr("advise.nutrients.organic_crop", crop=name, days=days))
    out += ["", tr("advise.nutrients.source"), ""]
    return "\n".join(out)


def _split(text: str, n: int) -> list:
    parts = text.split(":")
    if len(parts) != n:
        raise argparse.ArgumentTypeError(f"{text!r}: expected {n} fields separated by ':'")
    return parts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--animals", nargs="+", default=[], help="system:head:weight_lb")
    ap.add_argument("--crops", nargs="+", required=True, help="crop:yield:unit:acres")
    ap.add_argument("--soil-test-p", choices=("low", "medium", "high", "very high"))
    ap.add_argument("--organic", action="store_true")
    ap.add_argument("--lang", default="en")
    args = ap.parse_args(argv)
    animals = [(s, float(h), float(w)) for s, h, w in (_split(a, 3) for a in args.animals)]
    crops = [(c, float(y), u, float(a)) for c, y, u, a in (_split(x, 4) for x in args.crops)]
    print(render(balance(animals, crops, args.soil_test_p), organic=args.organic, language=args.lang))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
