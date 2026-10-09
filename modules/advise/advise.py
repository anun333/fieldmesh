#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What grows at a farm, and why not — one command, one report.

    python3 modules/advise/advise.py 35.06445 -86.59137 --cache CACHE --out report-dir [--lang es] [--windows]

Runs the whole of modules/advise/notes/plant-conditions.md for a point: the site profile (NASA
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
REPO = os.path.join(HERE, os.pardir, os.pardir)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "sdk"))
import dssat_crops  # noqa: E402
import i18n  # noqa: E402
import fruit_bloom  # noqa: E402
import module  # noqa: E402
import plant_match  # noqa: E402
import site_profile  # noqa: E402

module.register_packs()

DATA = os.path.join(HERE, "data")
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


#: The crops of modules/advise/data/chill-requirements.csv and chill-requirements-pome.csv, in
#: report order, and their pack keys.
FRUIT = (("almond", "almond"), ("European apricot", "apricot_eu"), ("Japanese apricot", "apricot_jp"),
         ("peach", "peach"), ("nectarine", "nectarine"), ("flat peach", "flat_peach"),
         ("European plum", "plum_eu"), ("Japanese plum", "plum_jp"), ("cherry (sweet or sour)", "cherry"),
         ("apple", "apple"), ("pear", "pear"))

#: Uses a fruit grower plants for fruit. The apple table also lists rootstocks and crab
#: apples (pollinisers and ornamentals) and some cultivars with no use given; counting
#: them would say more about rootstock breeding than about what fruits here.
ORCHARD_USES = ("dessert", "cider")


def orchard(requirements: list) -> list:
    """The rows for trees grown for their fruit; a table without a use column is all fruit."""
    return [r for r in requirements if r.get("usage") is None or r["usage"] in ORCHARD_USES]


def need_upper(value: str):
    """The top of a published chill requirement: a range's upper end, a mean plus its
    spread, the bound of "<300". None where there is none, or it is open (">1100")."""
    v = value.strip().replace("−", "-")
    if v in ("", "-", "–") or v.startswith(">"):
        return None
    if v.startswith("<"):
        return float(v[1:].strip())
    if m := re.fullmatch(r"([\d.]+)\s*±\s*([\d.]+)", v):
        return float(m.group(1)) + float(m.group(2))
    if m := re.fullmatch(r"([\d.]+)\s*[–-]\s*([\d.]+)", v):
        return float(m.group(2))
    try:
        return float(v)
    except ValueError:
        return None


def chill_fit(requirements: list, site_chill: float) -> list:
    """Per crop: (pack key, cultivars with a chill-hour requirement, how many this site's
    chill meets). A cultivar measured in several studies is held to the highest."""
    need = {}
    for r in requirements:
        top = need_upper(r["chill_hours"])
        if top is not None:
            k = (r["crop"], r["cultivar"])
            need[k] = max(top, need.get(k, 0.0))
    out = []
    for crop, key in FRUIT:
        tops = [v for (c, _), v in need.items() if c == crop]
        if tops:
            out.append((key, len(tops), sum(1 for v in tops if v <= site_chill)))
    return out


def bloom_lines(r: "Report", bloom: dict, north: bool) -> list:
    """Per crop with bloom estimates: when it blooms and how often frost follows."""
    out = []
    for crop, key in FRUIT:
        s = bloom.get(crop)
        if not s or s["bloom_median"] is None:
            continue
        when = {k: r.date(fruit_bloom.as_date(s[f"bloom_{k}"], north)) for k in ("early", "late", "median")}
        args = dict(crop=r.tr(f"advise.fruit.{key}"), early=when["early"], late=when["late"],
                    median=when["median"], frost=s["frost_in_10"], count=s["estimates"], unmet=s["unmet"])
        out.append("- " + r.tr("advise.bloom.crop_unmet" if s["unmet"] else "advise.bloom.crop", **args))
    return out


def render(site: dict, rows: list, cal: dict, language: str, today: str,
           chill: list | None = None, bloom: dict | None = None,
           fruit_chill: float | None = None) -> str:
    r = Report(language)
    c = site["climate"]
    out = [f"# {r.tr('advise.title', lat=site['lat'], lon=site['lon'])}", "",
           r.tr("advise.preface", date=today), "", f"## {r.tr('advise.section.site')}", ""]
    out.append("- " + r.tr("advise.site.climate", koppen=c["koppen"], mean=c["annual_mean_c"],
                           rain=c["annual_rain_mm"], zone=c["hardiness_zone"]))
    out.append("- " + r.tr("advise.site.frost", last=r.date(c["last_spring_frost_median"]),
                           first=r.date(c["first_fall_frost_median"]),
                           ffd=c["frost_free_days_8_in_10"]))
    out.append("- " + r.tr("advise.site.heat", gdd=c["growing_degree_days_c"], chill=c["chill_hours_est"],
                           chill8=c.get("chill_hours_8_in_10", c["chill_hours_est"])))
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

    if chill:
        # The fruit's own season — chill to the end of March — unless none is given.
        have = fruit_chill if fruit_chill is not None else c["chill_hours_8_in_10"]
        out += [f"## {r.tr('advise.section.chill')}", "",
                r.tr("advise.chill.preface", chill=have), ""]
        for key, known, fit in chill_fit(chill, have):
            out.append("- " + r.tr("advise.chill.crop", crop=r.tr(f"advise.fruit.{key}"), fit=fit, known=known))
        out.append("")
        if bloom:
            out += [r.tr("advise.bloom.preface", count=sum(s["estimates"] for s in bloom.values())), ""]
            out += bloom_lines(r, bloom, site["lat"] >= 0) + [""]

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
            f"## {r.tr('advise.section.sources')}", "", r.tr("advise.sources"), "",
            stamp(r), ""]
    return "\n".join(out)


def stamp(r: "Report") -> str:
    """What made this report (§11: models versioned): the module's version, its data (the
    manifest's hash) and the crop models' pinned commit — enough to reproduce it, and to
    tell a changed recommendation from a changed program."""
    return "*" + r.tr("advise.stamp", version=module.VERSION, data=module.data_version(),
                      dssat=dssat_crops.COMMIT[:7]) + "*"


def render_future(site: dict, rows: list, site2: dict, rows2: list, language: str,
                  label: str, warm: float, rain: float, source: str, chill: list | None = None,
                  bloom: dict | None = None, bloom2: dict | None = None,
                  fruit_chill: tuple | None = None) -> str:
    """Now against then: the site's numbers, the plants whose verdict changes, and each
    modelled crop's cultivars and sowing windows."""
    r = Report(language)
    c, c2 = site["climate"], site2["climate"]
    out = [f"# {r.tr('advise.future.title', label=label)}", "",
           r.tr("advise.future.preface", warm=warm, rain=rain, source=source or "—"), "",
           f"## {r.tr('advise.section.site')}", ""]
    for key, a, b in (("advise.future.ffd", c["frost_free_days_8_in_10"], c2["frost_free_days_8_in_10"]),
                      ("advise.future.zone", c["hardiness_zone"], c2["hardiness_zone"]),
                      ("advise.future.gdd", round(c["growing_degree_days_c"]), round(c2["growing_degree_days_c"])),
                      ("advise.future.chill", round(c["chill_hours_est"]), round(c2["chill_hours_est"])),
                      ("advise.future.heat", round(c["heat_stress_days_dairy_est"]["high"]),
                       round(c2["heat_stress_days_dairy_est"]["high"])),
                      ("advise.future.hot", round(c["days_over_35c"]), round(c2["days_over_35c"]))):
        out.append("- " + r.tr(key, now=a, then=b))
    out.append("")
    good = lambda v: v.startswith("suits")
    then = {x["scientific_name"]: x for x in rows2}
    gains = [x for x in rows if not good(x["verdict"]) and good(then[x["scientific_name"]]["verdict"])]
    losses = [x for x in rows if good(x["verdict"]) and not good(then[x["scientific_name"]]["verdict"])]
    for key, chosen in (("advise.future.gains", gains), ("advise.future.losses", losses)):
        out += [f"## {r.tr(key, count=len(chosen))}", ""]
        out += [f"- {plant_line(x)}" for x in sorted(chosen, key=lambda y: y["common_name"])] or ["—"]
        out.append("")
    modelled = [x for x in rows if x.get("_season")]
    if modelled:
        out += [f"## {r.tr('advise.section.crops')}", ""]
        for x in sorted(modelled, key=lambda y: y["common_name"]):
            s, s2 = x["_season"], then[x["scientific_name"]].get("_season") or {}
            win = lambda w: r.windows(w) if w and w != "none" else "—"
            out.append("- " + r.tr("advise.future.crop", crop=x["common_name"],
                                   now=s["cultivars_maturing_8_in_10"], then=s2.get("cultivars_maturing_8_in_10", "—"),
                                   total=s["cultivars"], now_window=win(s.get("sowing_windows_8_in_10")),
                                   then_window=win(s2.get("sowing_windows_8_in_10"))))
        out.append("")
    if chill:
        out += [f"## {r.tr('advise.section.chill')}", ""]
        have, have2 = fruit_chill or (c["chill_hours_8_in_10"], c2["chill_hours_8_in_10"])
        now = chill_fit(chill, have)
        then = {k: fit for k, _, fit in chill_fit(chill, have2)}
        for key, known, fit in now:
            out.append("- " + r.tr("advise.future.fruit", crop=r.tr(f"advise.fruit.{key}"),
                                   now=fit, then=then[key], known=known))
        out.append("")
    if bloom and bloom2:
        north = site["lat"] >= 0
        for crop, key in FRUIT:
            a, b = bloom.get(crop), bloom2.get(crop)
            if not a or not b or a["bloom_median"] is None or b["bloom_median"] is None:
                continue
            out.append("- " + r.tr("advise.future.bloom", crop=r.tr(f"advise.fruit.{key}"),
                                   now=r.date(fruit_bloom.as_date(a["bloom_median"], north)),
                                   then=r.date(fruit_bloom.as_date(b["bloom_median"], north)),
                                   fnow=a["frost_in_10"], fthen=b["frost_in_10"]))
        out.append("")
    out += [stamp(r), ""]
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
    ap.add_argument("--warm", type=float, help="also compare a climate this many °C warmer (delta method)")
    ap.add_argument("--rain-change", type=float, default=0.0, help="with --warm: rain change, percent")
    ap.add_argument("--future-label", help="with --warm: what to call it, e.g. '2050s'")
    ap.add_argument("--future-source", default="", help="with --warm: where the change comes from")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    power = os.path.join(args.cache, "power")
    site = site_profile.profile(args.lat, args.lon, cache=power)
    days = site_profile.days_of(site_profile.fetch_power(args.lat, args.lon, 1991, 2020, power))
    seasons, _ = dssat_crops.seasons_for(args.lat, args.lon, args.cache, args.windows, days=days)
    rows, cal = plant_match.match(read_csv(os.path.join(DATA, "plant-list.csv")),
                                  read_csv(os.path.join(DATA, "plant-characteristics-usda.csv")),
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
    chill = orchard(read_csv(os.path.join(DATA, "chill-requirements.csv"))
                    + read_csv(os.path.join(DATA, "chill-requirements-pome.csv")))
    bloom = fruit_bloom.summarize(fruit_bloom.simulate(chill, days, args.lat))
    eight = lambda xs: sorted(xs)[int(0.2 * len(xs))] if xs else 0.0
    fruit_chill = eight(fruit_bloom.winter_chill(days, args.lat))
    for lang in args.lang.split(","):
        path = os.path.join(args.out, f"report.{lang}.md")
        with open(path, "w", encoding="utf-8") as h:
            h.write(render(site, rows, cal, lang, today, chill, bloom, fruit_chill))
        print(f"wrote {path}")
    if args.warm is not None:
        site2 = site_profile.profile(args.lat, args.lon, cache=power, warm_c=args.warm,
                                     rain_pct=args.rain_change)
        days2 = site_profile.shift(days, args.warm, args.rain_change)
        seasons2, _ = dssat_crops.seasons_for(args.lat, args.lon, args.cache, args.windows, days=days2)
        rows2, _ = plant_match.match(read_csv(os.path.join(DATA, "plant-list.csv")),
                                     read_csv(os.path.join(DATA, "plant-characteristics-usda.csv")),
                                     site2, [{k: str(v) for k, v in s.items()} for s in seasons2])
        label = args.future_label or f"{args.warm:+.1f} °C"
        bloom2 = fruit_bloom.summarize(fruit_bloom.simulate(chill, days2, args.lat))
        fruit_chill2 = eight(fruit_bloom.winter_chill(days2, args.lat))
        for lang in args.lang.split(","):
            path = os.path.join(args.out, f"future.{lang}.md")
            with open(path, "w", encoding="utf-8") as h:
                h.write(render_future(site, rows, site2, rows2, lang, label, args.warm,
                                      args.rain_change, args.future_source, chill, bloom, bloom2,
                                      (fruit_chill, fruit_chill2)))
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
