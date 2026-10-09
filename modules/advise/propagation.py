#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""When to propagate each plant here: by seed, bare root, container, cuttings, sprigs or
tubers, in windows set by the site's own frost dates.

USDA PLANTS says how each plant is propagated (`Propagated by …`, and whether its seed
needs cold stratification); the site profile says when this place's frosts come. The
windows are the common practice for each method, anchored to those dates — a first
approximation, as the bloom calendar is, and said to be one:

* **seed needing cold** — sown outdoors in the four weeks after the first fall frost, so
  the winter stratifies it (the USDA Forest Service's Woody Plant Seed Manual describes
  fall sowing as natural stratification); or stratified cold and moist and sown at the
  last spring frost;
* **seed** — from the last spring frost. Food crops with a crop model have their own,
  better sowing windows in the report;
* **bare root** — dormant stock, from six weeks before the last spring frost to two weeks
  after it; and, where winters are mild (hardiness zone 7 and warmer), also from the first
  fall frost for six weeks;
* **container** — spring, from the last frost for eight weeks; and fall, the eight weeks
  before the first frost, out of midsummer heat;
* **cuttings** — hardwood cuttings while dormant, from the first fall frost to six weeks
  before the last spring frost;
* **sprigs and sod** — warm soil: from two weeks after the last frost to ten weeks before
  the first;
* **tubers** — at the last spring frost, for four weeks.
"""
from __future__ import annotations

import datetime as _dt

METHODS = ("seed_cold", "seed", "bare_root", "container", "cuttings", "sprigs", "tubers")
YEAR = 2001          # a non-leap year to hold month and day


def _md(text: str) -> _dt.date:
    return _dt.datetime.strptime(f"{text} {YEAR}", "%b %d %Y").date()


def _span(start: _dt.date, days: int) -> tuple:
    end = start + _dt.timedelta(days=days)
    if end.year != YEAR:                      # windows that cross the new year wrap
        end = end.replace(year=YEAR)
    return (start.strftime("%b %d"), end.strftime("%b %d"))


def windows(site: dict) -> dict:
    """{method: [(from, to), ...]} for a site, from its median frost dates."""
    c = site["climate"]
    last, first = _md(c["last_spring_frost_median"]), _md(c["first_fall_frost_median"])
    d = _dt.timedelta
    zone = c.get("hardiness_zone") or "0"
    mild = int("".join(ch for ch in zone if ch.isdigit()) or 0) >= 7
    out = {
        "seed_cold": [_span(first, 28), _span(last, 21)],
        "seed": [_span(last, 60)],
        "bare_root": [_span(last - d(days=42), 56)] + ([_span(first, 42)] if mild else []),
        "container": [_span(last, 56), _span(first - d(days=56), 56)],
        "cuttings": [(first.strftime("%b %d"), (last - d(days=42)).strftime("%b %d"))],
        "sprigs": [_span(last + d(days=14), max(0, (first - last).days - 14 - 70))],
        "tubers": [_span(last, 28)],
    }
    return out


def methods_of(chars: dict) -> list:
    """The propagation methods USDA PLANTS lists for a plant, in calendar terms."""
    if not chars:
        return []
    yes = lambda field: (chars.get(field) or "").strip().lower() == "yes"
    out = []
    if yes("Propagated by Seed"):
        out.append("seed_cold" if yes("Cold Stratification Required") else "seed")
    for field, method in (("Propagated by Bare Root", "bare_root"), ("Propagated by Container", "container"),
                          ("Propagated by Cuttings", "cuttings"), ("Propagated by Sprigs", "sprigs"),
                          ("Propagated by Sod", "sprigs"), ("Propagated by Tubers", "tubers")):
        if yes(field) and method not in out:
            out.append(method)
    return out


def calendar(plants: list, chars: list, site: dict) -> list:
    """[{scientific_name, common_name, method, from, to}] for every plant PLANTS covers."""
    by_name = {c["scientific_name"]: c for c in chars}
    w = windows(site)
    rows = []
    for p in plants:
        for method in methods_of(by_name.get(p["scientific_name"])):
            for start, end in w[method]:
                rows.append({"scientific_name": p["scientific_name"], "common_name": p["common_name"],
                             "method": method, "from": start, "to": end})
    return rows
