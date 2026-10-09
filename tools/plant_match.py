#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""What grows well at a site, and why not — plants against a site profile.

    python3 tools/plant_match.py docs/notes/plant-list.csv \\
        docs/notes/plant-characteristics-usda.csv site.json --out match.csv

Each plant's USDA PLANTS requirements are checked one condition at a time against the
site from `site_profile.py`, and the answer says **which** condition decides, never one
opaque score:

* **rules out** — the frost-free season (8 years in 10) is under 75% of what PLANTS lists;
  for a perennial, the average winter low is more than 15 °F below PLANTS' minimum.
  The margins are wide because PLANTS' values are guidance for conservation plantings,
  not limits — it lists white clover as needing 250 frost-free days — and narrower
  shortfalls are cautions that quote what PLANTS lists;
* **fixable** — rainfall below its range (irrigate), topsoil pH outside its range (lime
  or sulfur);
* **caution** — rainfall above its range, a soil texture PLANTS calls it unadapted to,
  waterlogging it does not tolerate on a poorly drained soil, salt it does not tolerate,
  or a winter low within the 5 °F margin.

**Under cover** (`--cover high-tunnel`), the site is changed only as far as is defensible:
the frost-free season is lengthened by two weeks at each end — the low end of the two to
four weeks extension services commonly give — and rainfall stops mattering, because
nothing under cover gets rain and everything must be irrigated. How much warmer an
unheated tunnel keeps a winter night varies by tunnel and by night, so the winter low is
left as it is outside unless a measured gain is given (`--winter-gain-f`): a sensor
inside and one outside measure it (docs/notes/hoop-houses.md).

Plants on the do-not-plant list are refused before anything else. A plant PLANTS has no
characteristics for is reported as such. Heat, chill hours and day length are not in
PLANTS and are not checked yet — a known gap, listed in the output.

It also lays the suited plants' **bloom periods** over the site's months and marks the
"hunger gaps" — months warm enough for bees to fly (mean daily maximum 10 °C or more)
with nothing on the list in flower. PLANTS gives one bloom period per species for the
whole United States, so the calendar is a first approximation of a local one.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
#: PLANTS bloom-period words → months, northern hemisphere (shifted six in the south).
BLOOM = {"Late Winter": [2], "Winter": [12, 1, 2], "Early Spring": [3], "Mid Spring": [4],
         "Late Spring": [5], "Spring": [3, 4, 5], "Early Summer": [6], "Mid Summer": [7],
         "Late Summer": [8], "Summer": [6, 7, 8], "Early Fall": [9], "Fall": [9, 10],
         "Late Fall": [11]}
PERENNIAL = {"perennial", "short-lived perennial"}
COLD_MARGIN_F = 5.0
#: Days a high tunnel adds to the frost-free season: two weeks at each end.
COVER_SEASON_DAYS = {"high-tunnel": 28}
#: What is grown under cover. Timber, pasture and windbreaks are not, whatever the
#: arithmetic says — the first run happily put bur oak in a hoop house.
COVER_CATEGORIES = {"vegetable", "spice/herb", "cut flower", "edible flower",
                    "berry/vine fruit", "temperate fruit", "tropical/subtropical fruit",
                    "root/tuber", "pulse", "pseudocereal", "beverage/stimulant"}
#: PLANTS' frost-free days and minimum temperatures are conservation-planting guidance,
#: not hard limits: it lists white clover as needing 250 frost-free days and dying below
#: 22 °F, and both it and bermudagrass are staples of Tennessee pasture at 207 days and
#: 11 °F. So a plant is ruled out only when the shortfall is overwhelming — under 75% of
#: the season, or more than 15 °F below the minimum — which still excludes every
#: tropical crop; anything less is a caution that says what PLANTS lists.
SEASON_RULES_OUT = 0.75
WINTER_RULES_OUT_F = 15.0
#: A frost-free "season" this long is no season: on a crop grown as an annual it is a
#: perennial-range value or an error, not a requirement.
IMPLAUSIBLE_SEASON_DAYS = 300
BEE_FLIGHT_MAX_C = 10.0


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def texture_word(texture: str | None) -> str | None:
    return {"sandy": "Coarse", "loamy": "Medium", "clayey": "Fine"}.get(texture or "")


def judge(plant: dict, chars: dict | None, site: dict) -> dict:
    """-> {verdict, rules_out[], fixable[], caution[]}"""
    out = {"rules_out": [], "fixable": [], "caution": []}
    if plant["category"].startswith("invasive"):
        return {**out, "verdict": "do not plant (invasive)"}
    if site.get("cover") and plant["category"] not in COVER_CATEGORIES:
        return {**out, "verdict": "not grown under cover"}
    if not chars or not chars.get("plants_symbol"):
        return {**out, "verdict": "no data (not in USDA PLANTS)"}
    if "characteristics" in (chars.get("match") or ""):
        return {**out, "verdict": "no data (no characteristics in PLANTS)"}
    c = site["climate"]
    soil = site.get("soil") or {}

    need = number(chars.get("Frost Free Days, Minimum"))
    have = c["frost_free_days_8_in_10"]
    grown_as_annual = "annual" in plant["cycle"]
    if need is not None and have < need:
        if grown_as_annual and need >= IMPLAUSIBLE_SEASON_DAYS:
            # PLANTS gives some crops a year-round frost-free need from their perennial
            # range (eggplant), and some plain annuals a value that cannot be a season
            # (buckwheat, 365). Neither can rule a crop out where it is grown annually.
            if plant["cycle"] == "annual":
                out["caution"].append(f"season: PLANTS lists {need:.0f} frost-free days, "
                                      f"implausible for an annual — not used")
            else:
                out["caution"].append(f"season: PLANTS lists {need:.0f} frost-free days, from its "
                                      f"perennial range; as an annual it needs only its time to "
                                      f"harvest, which PLANTS does not give")
        elif have < SEASON_RULES_OUT * need:
            out["rules_out"].append(f"season: needs {need:.0f} frost-free days, has {have} (8 years in 10)")
        else:
            out["caution"].append(f"season: PLANTS lists {need:.0f} frost-free days, has {have} "
                                  f"(8 years in 10) — a little short")

    if plant["cycle"] in PERENNIAL:
        tmin = number(chars.get("Temperature, Minimum (°F)"))
        low = c["mean_annual_extreme_min_f"]
        if tmin is not None:
            if low < tmin - WINTER_RULES_OUT_F:
                out["rules_out"].append(f"winter: average low {low:.0f} °F, survives {tmin:.0f} °F")
            elif low < tmin:
                out["caution"].append(f"winter: average low {low:.0f} °F, below the {tmin:.0f} °F "
                                      f"PLANTS lists")
            elif low - COLD_MARGIN_F < tmin:
                out["caution"].append(f"winter: average low {low:.0f} °F is within {COLD_MARGIN_F:.0f} °F of its {tmin:.0f} °F limit")

    rain = c.get("annual_rain_in")
    lo, hi = number(chars.get("Precipitation, Minimum")), number(chars.get("Precipitation, Maximum"))
    if rain is not None and lo is not None and rain < lo:
        out["fixable"].append(f"water: {rain:.0f} in of rain, needs {lo:.0f} — irrigate")
    if rain is not None and hi is not None and rain > hi:
        out["caution"].append(f"water: {rain:.0f} in of rain, wetter than its {hi:.0f} in maximum")

    ph = soil.get("topsoil_ph")
    pmin, pmax = number(chars.get("pH, Minimum")), number(chars.get("pH, Maximum"))
    if ph is not None and pmin is not None and ph < pmin:
        out["fixable"].append(f"pH: topsoil {ph}, needs {pmin} or more — lime")
    if ph is not None and pmax is not None and ph > pmax:
        out["fixable"].append(f"pH: topsoil {ph}, needs {pmax} or less — sulfur")

    word = texture_word(soil.get("topsoil_texture"))
    if word and chars.get(f"Adapted to {word} Textured Soils") == "No":
        out["caution"].append(f"soil: PLANTS lists it as not adapted to {word.lower()}-textured soil")
    drainage = (soil.get("drainage") or "").lower()
    if "poorly" in drainage and chars.get("Anaerobic Tolerance") in ("None", None):
        out["caution"].append(f"drainage: {drainage} soil, no tolerance of waterlogging")
    ec = soil.get("topsoil_ec_ds_per_m")
    if ec is not None and ec > 4 and chars.get("Salinity Tolerance") in ("None", "Low"):
        out["caution"].append(f"salt: topsoil {ec} dS/m, low salt tolerance")

    if out["rules_out"]:
        verdict = "unsuited"
    elif out["fixable"]:
        verdict = "suits, with " + " and ".join(sorted({f.split(":")[0] for f in out["fixable"]}))
    elif out["caution"]:
        verdict = "suits, with cautions"
    else:
        verdict = "suits"
    return {**out, "verdict": verdict}


def under_cover(site: dict, cover: str, winter_gain_f: float = 0.0) -> dict:
    """The site as a crop under `cover` sees it. Rainfall becomes None — irrigated —
    and the season is lengthened; the winter low moves only by a measured gain."""
    covered = {**site, "cover": cover, "climate": dict(site["climate"])}
    c = covered["climate"]
    c["frost_free_days_8_in_10"] = min(365, c["frost_free_days_8_in_10"] + COVER_SEASON_DAYS[cover])
    c["mean_annual_extreme_min_f"] = c["mean_annual_extreme_min_f"] + winter_gain_f
    c["annual_rain_in"] = None
    return covered


def bloom_months(value: str | None, south: bool) -> list:
    months = BLOOM.get(value or "", [])
    return sorted({((m + 5) % 12) + 1 for m in months}) if south else months


def calendar(rows: list, site: dict) -> dict:
    south = site["lat"] < 0
    flowering = collections.defaultdict(list)
    for r in rows:
        if r["verdict"].startswith("suits"):
            for m in bloom_months(r.get("bloom"), south):
                flowering[m].append(r["common_name"])
    flight = [m for m, month in enumerate(site["climate"]["monthly"], 1)
              if month["mean_max_c"] >= BEE_FLIGHT_MAX_C]
    with_bloom = sum(1 for r in rows if r["verdict"].startswith("suits")
                     and bloom_months(r.get("bloom"), south))
    return {"in_flower": {MONTHS[m - 1]: len(flowering[m]) for m in range(1, 13)},
            "examples": {MONTHS[m - 1]: flowering[m][:6] for m in range(1, 13)},
            "suited_with_bloom_period": with_bloom,
            "bee_flight_months": [MONTHS[m - 1] for m in flight],
            # "Nothing recorded": a gap may be missing data — asters, for one, have no
            # PLANTS characteristics — as easily as missing flowers.
            "hunger_gaps": [MONTHS[m - 1] for m in flight if not flowering[m]]}


def read_csv(path: str) -> list:
    with open(path, encoding="utf-8") as h:
        return list(csv.DictReader(line for line in h if not line.startswith("#")))


def match(plants: list, chars: list, site: dict) -> tuple[list, dict]:
    by_name = {c["scientific_name"]: c for c in chars}
    rows = []
    for p in plants:
        c = by_name.get(p["scientific_name"])
        j = judge(p, c, site)
        rows.append({"common_name": p["common_name"], "scientific_name": p["scientific_name"],
                     "category": p["category"], "verdict": j["verdict"],
                     "rules_out": "; ".join(j["rules_out"]), "fixable": "; ".join(j["fixable"]),
                     "caution": "; ".join(j["caution"]),
                     "bloom": (c or {}).get("Bloom Period") or ""})
    return rows, calendar(rows, site)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plant_list")
    ap.add_argument("characteristics")
    ap.add_argument("site")
    ap.add_argument("--out")
    ap.add_argument("--cover", choices=sorted(COVER_SEASON_DAYS),
                    help="match for a crop under this cover instead of in the open")
    ap.add_argument("--winter-gain-f", type=float, default=0.0,
                    help="measured winter-night gain of the cover, °F (default 0: unmeasured)")
    args = ap.parse_args(argv)
    with open(args.site, encoding="utf-8") as h:
        site = json.load(h)
    if args.cover:
        site = under_cover(site, args.cover, args.winter_gain_f)
    rows, cal = match(read_csv(args.plant_list), read_csv(args.characteristics), site)
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    verdicts = collections.Counter(r["verdict"] for r in rows)
    where = f" under {site['cover']}" if site.get("cover") else ""
    print(f"{site['lat']}, {site['lon']}{where}: " + ", ".join(f"{k} {v}" for k, v in verdicts.most_common()))
    if site.get("cover"):
        print("  under cover: everything needs irrigation; crops that need pollinators need "
              "bees let in or hand pollination")
    reasons = collections.Counter(x.split(":")[0] for r in rows for x in r["rules_out"].split("; ") if x)
    print("  ruled out by: " + ", ".join(f"{k} {v}" for k, v in reasons.most_common()))
    print("  in flower (suited plants): " + "  ".join(f"{m} {n}" for m, n in cal["in_flower"].items()))
    print(f"  bee flight months: {', '.join(cal['bee_flight_months'])}; nothing recorded in flower: "
          f"{', '.join(cal['hunger_gaps']) or 'none'} (from {cal['suited_with_bloom_period']} suited plants with a bloom period)")
    print("  not yet checked: heat, chill hours, day length (not in USDA PLANTS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
