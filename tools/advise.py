#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""What grows at a farm, and why not — one command, one report.

    python3 tools/advise.py 35.06445 -86.59137 --cache CACHE --out report-dir [--lang es] [--windows]

Runs the whole of docs/notes/plant-conditions.md for a point: the site profile (NASA
POWER climate and sun, the USDA soil survey in the US), the plant list matched against it
(USDA PLANTS), the food crops simulated on the site's own weather (DSSAT), the bee forage
calendar, livestock heat stress and erosion risk. Writes `report.<lang>.md` — in any
language with a pack in sdk/packs, falling back to English where a string is missing —
plus the match, the crop seasons and the site profile as data.

The report's words come from the language pack; its numbers, names and codes from the
data. Plant names are English until AGROVOC's multilingual names are added.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, "sdk"))
import dssat_crops  # noqa: E402
import i18n  # noqa: E402
import plant_match  # noqa: E402
import site_profile  # noqa: E402

NOTES = os.path.join(HERE, os.pardir, "docs", "notes")
MONTH = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                                     "Sep", "Oct", "Nov", "Dec"], 1)}


class Report:
    def __init__(self, language: str):
        self.t = i18n.Translator(language)

    def tr(self, key: str, **params) -> str:
        return str(self.t.text(key, **params))

    def month(self, n: int) -> str:
        return self.tr(f"advise.month.{n}")

    def date(self, text: str | None) -> str:
        """"Mar 31" -> "March 31" / "31 de marzo"."""
        if not text:
            return "—"
        m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{1,2})", text.strip())
        if not m:
            return text
        return self.tr("advise.date", month=self.month(MONTH[m.group(1)]), day=int(m.group(2)))

    def windows(self, text: str) -> str:
        if text.strip() in ("Jan 01–Dec 31", "Jan 01–Dec 24"):
            return self.tr("advise.window.all_year")
        parts = []
        for span in (s.strip() for s in text.split(";") if s.strip()):
            a, _, b = span.partition("–")
            parts.append(self.tr("advise.window", start=self.date(a), end=self.date(b)))
        return "; ".join(parts)

    def months(self, names: list) -> str:
        return ", ".join(self.month(MONTH[n]) for n in names)


def plant_line(row: dict) -> str:
    return f"{row['common_name']} (*{row['scientific_name']}*)"


def render(site: dict, rows: list, cal: dict, language: str, today: str) -> str:
    r = Report(language)
    c = site["climate"]
    out = [f"# {r.tr('advise.title', lat=site['lat'], lon=site['lon'])}", "",
           r.tr("advise.preface", date=today), "", f"## {r.tr('advise.section.site')}", ""]
    out.append("- " + r.tr("advise.site.climate", koppen=c["koppen"], mean=c["annual_mean_c"],
                           rain=c["annual_rain_mm"], zone=c["hardiness_zone"]))
    out.append("- " + r.tr("advise.site.frost", last=r.date(c["last_spring_frost_median"]),
                           first=r.date(c["first_fall_frost_median"]),
                           ffd=c["frost_free_days_8_in_10"]))
    out.append("- " + r.tr("advise.site.heat", gdd=c["growing_degree_days_c"], chill=c["chill_hours_est"]))
    out.append("- " + r.tr("advise.site.trend", change=c["trend"]["mean_c_change"]))
    soil = site.get("soil")
    if soil:
        out.append("- " + r.tr("advise.site.soil", soil=soil["map_unit"], drainage=soil["drainage"],
                               slope=soil["slope_pct"], ph=soil["topsoil_ph"],
                               om=soil["topsoil_organic_matter_pct"]))
    else:
        out.append("- " + r.tr("advise.site.nosoil"))
    erosion = site.get("erosion")
    if erosion and erosion.get("times_tolerable_if_bare") and erosion["times_tolerable_if_bare"] >= 2:
        out.append("- " + r.tr("advise.site.erosion", times=erosion["times_tolerable_if_bare"]))
    out += ["", f"*{r.tr('advise.site.caution')}*", ""]

    modelled = [row for row in rows if row.get("_season")]
    if modelled:
        out += [f"## {r.tr('advise.section.crops')}", ""]
        for row in sorted(modelled, key=lambda x: x["common_name"]):
            s = row["_season"]
            fit = int(s["cultivars_maturing_8_in_10"])
            if fit == 0:
                out.append("- " + r.tr("advise.crop.fails", crop=row["common_name"]))
            elif s.get("sowing_windows_8_in_10") and s["sowing_windows_8_in_10"] != "none":
                out.append("- " + r.tr("advise.crop.fits", crop=row["common_name"], fit=fit,
                                       total=s["cultivars"], fast=s["best_days_to_maturity"],
                                       slow=s["longest_days_to_maturity"],
                                       windows=r.windows(s["sowing_windows_8_in_10"])))
            else:
                out.append("- " + r.tr("advise.crop.fits_nowindow", crop=row["common_name"], fit=fit,
                                       total=s["cultivars"], fast=s["best_days_to_maturity"],
                                       slow=s["longest_days_to_maturity"]))
        out.append("")

    def reasons(row, kinds):
        return "; ".join(r.tr(key, **params) for kind, key, params in row.get("_keys", [])
                         if kind in kinds)

    groups = [("advise.section.suits", lambda v: v in ("suits", "suits (crop model)"), None),
              ("advise.section.fixes", lambda v: v.startswith("suits, with") and "caution" not in v,
               ("fixable",)),
              ("advise.section.cautions", lambda v: v == "suits, with cautions", ("caution",)),
              ("advise.section.unsuited", lambda v: v == "unsuited", ("rules_out",)),
              ("advise.section.refused", lambda v: v.startswith("do not plant"), ("rules_out",))]
    for key, test, kinds in groups:
        chosen = sorted((row for row in rows if test(row["verdict"])), key=lambda x: x["common_name"])
        if not chosen:
            continue
        out += [f"## {r.tr(key)} ({len(chosen)})", ""]
        if kinds is None:
            out.append(", ".join(plant_line(row) for row in chosen))
        else:
            out += [f"- {plant_line(row)}" + (f" — {why}" if (why := reasons(row, kinds)) else "")
                    for row in chosen]
        out.append("")

    out += [f"## {r.tr('advise.section.bees')}", "",
            "- " + r.tr("advise.bees.flight", months=r.months(cal["bee_flight_months"]))]
    out.append("- " + (r.tr("advise.bees.gaps", months=r.months(cal["hunger_gaps"]))
                       if cal["hunger_gaps"] else r.tr("advise.bees.nogaps")))
    heat = c["heat_stress_days_dairy_est"]
    out += ["", f"## {r.tr('advise.section.livestock')}", "",
            "- " + r.tr("advise.livestock.heat", low=heat["low"], high=heat["high"]), ""]
    nodata = sum(1 for row in rows if row["verdict"].startswith("no data"))
    out += [f"## {r.tr('advise.section.nodata')}", "", r.tr("advise.nodata", count=nodata),
            "", f"*{r.tr('advise.names_note')}*", "",
            f"## {r.tr('advise.section.sources')}", "", r.tr("advise.sources"), ""]
    return "\n".join(out)


def read_csv(path: str) -> list:
    with open(path, encoding="utf-8") as h:
        return list(csv.DictReader(line for line in h if not line.startswith("#")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True, help="directory for the report and its data")
    ap.add_argument("--lang", default="en", help="report language(s), comma-separated")
    ap.add_argument("--windows", action="store_true", help="also find sowing windows (slower)")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    power = os.path.join(args.cache, "power")
    site = site_profile.profile(args.lat, args.lon, cache=power)
    days = site_profile.days_of(site_profile.fetch_power(args.lat, args.lon, 1991, 2020, power))
    seasons, _ = dssat_crops.seasons_for(args.lat, args.lon, args.cache, args.windows, days=days)
    rows, cal = plant_match.match(read_csv(os.path.join(NOTES, "plant-list.csv")),
                                  read_csv(os.path.join(NOTES, "plant-characteristics-usda.csv")),
                                  site, [{k: str(v) for k, v in s.items()} for s in seasons])
    with open(os.path.join(args.out, "site.json"), "w", encoding="utf-8") as h:
        json.dump(site, h, indent=1)
    for name, data in (("match.csv", rows), ("seasons.csv", seasons)):
        with open(os.path.join(args.out, name), "w", newline="", encoding="utf-8") as h:
            fields = [k for k in data[0] if not k.startswith("_")]
            w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
    today = _dt.date.today().isoformat()
    for lang in args.lang.split(","):
        path = os.path.join(args.out, f"report.{lang}.md")
        with open(path, "w", encoding="utf-8") as h:
            h.write(render(site, rows, cal, lang, today))
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
