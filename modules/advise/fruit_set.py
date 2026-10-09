#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Heat that stops fruit set, beyond what a crop's development curve sees.

A crop model's temperature curve paces development; it does not say that flowers which
open in a heat wave set no fruit. That needs a measured threshold per crop, and each rule
here carries the study it comes from. Only rules whose conditions a field can be compared
with fairly are kept:

* **Tomato** — Sato, Peet & Thomas (2000), Plant, Cell and Environment 23:719,
  doi:10.1046/j.1365-3040.2000.00589.x: at 32/26 °C day/night four of five cultivars set
  no fruit, where 28/22 was optimal; ten days of relief before flowering restored it. So a
  day is counted when the ten days before it averaged 32 °C by day and 26 °C by night.

Considered and not kept: bell pepper (Erickson & Markhart 2002 held flowers at a constant
33 °C, which no field's daily cycle is), and common bean (the threshold could not be read
from an open copy of the study). They wait for a study whose conditions a field's days
can be held to.
"""
from __future__ import annotations

import collections
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    crop: str
    day_c: float
    night_c: float
    window_days: int
    source: str


RULES = {"Solanum lycopersicum": Rule("tomato", 32.0, 26.0, 10, "Sato et al. 2000")}


def heat_days(days: list, rule: Rule) -> dict:
    """Per year, the days whose preceding window averaged at least the rule's day and night
    temperatures; with the 8-in-10 count and the warmest window's night mean, which says how
    far short a site falls when the count is nothing."""
    by_year, warmest_night = collections.Counter(), -99.0
    years = set()
    w = rule.window_days
    for i in range(w, len(days)):
        window = days[i - w:i]
        if not all("T2M_MAX" in v and "T2M_MIN" in v for _, v in window):
            continue
        hi = statistics.mean(v["T2M_MAX"] for _, v in window)
        lo = statistics.mean(v["T2M_MIN"] for _, v in window)
        year = days[i][0].year
        years.add(year)
        warmest_night = max(warmest_night, lo)
        if hi >= rule.day_c and lo >= rule.night_c:
            by_year[year] += 1
    counts = sorted(by_year[y] for y in years)
    eight = counts[int(0.8 * len(counts))] if counts else 0
    return {"days_8_in_10": eight, "years_with_any": sum(1 for c in counts if c),
            "years": len(counts), "warmest_night_mean_c": round(warmest_night, 1)}
