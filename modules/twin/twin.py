#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A physics twin for a hoop house: GreenLight, configured as an unheated tunnel
(open-questions Q28; layer 3, spec v0.1 §11).

GreenLight (Katzin et al., Wageningen University & Research; BSD-3-Clause-Clear;
github.com/davkat1/GreenLight) is a process-based model of a greenhouse's climate: the
cover's shortwave and long-wave exchanges, the air and the space above it, ventilation by
wind and buoyancy, the soil, the crop's transpiration. It was built for a heated, lit
Dutch glasshouse. This module configures it as what the farms here have — a single-poly
high tunnel with roll-up sides, no heating, no lamps, no screen, no CO2 — and drives it
with the farm's real weather.

The first use is a check on our own physics. The virtual farm's hoop house
(`sim/physics.Tunnel`) is a few plausible numbers, written down so a tool has something
to recover; neither it nor this configuration has met a real tunnel. Run side by side on
the same real weather, where they agree is a little more believable, and where they
disagree says which assumption to measure first. Later uses (Q28): tonight's inside low
from tonight's forecast, and the twin as a second probe a tunnel's own sensor can be held
against.

GreenLight pins numpy 1.26 and needs scipy, pandas and matplotlib, so it runs in this
module's own environment (requirements.txt) — as its own process, which is what §8.3's
module isolation is for. Nothing here imports it except `run_greenlight`.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import math
import os
import statistics
import sys
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
UTC = _dt.timezone.utc
SIGMA = 5.670374419e-8          # Stefan–Boltzmann, W m-2 K-4
CO2_PPM = 420.0

#: The tunnel: 30 by 96 feet (9.1 by 29.3 m), a Gothic arch about 4 m at the ridge, one
#: layer of 6-mil greenhouse polyethylene, roll-up sides 1.2 m high along both long walls,
#: a soil floor. Typical of the high tunnels NRCS cost-shares (EQIP practice 325). Values
#: GreenLight's glasshouse parameters are replaced with; each is a physical estimate, not
#: a measurement, and the two cover variants below are the one assumption that matters
#: most at night.
TUNNEL = {
    "aFlr": 267.0,              # m2, floor
    "aCov": 520.0,              # m2, cover including the end walls
    "hAir": 2.4,                # m, the main air space
    "hGh": 3.0,                 # m, mean height
    "psi": 45.0,                # degrees, mean slope of an arch
    "aRoof": 0.0,               # no roof vents
    "aSide": 70.3,              # m2, both roll-up sides fully open
    "hVent": 1.2,               # m, height of a side opening
    "hSideRoof": 0.0,
    # Leakier than sealed glass: end walls, doors, the curtain seams of rolled-down
    # sides. 1e-3 is about 1.2 air changes an hour at 1 m/s of wind and 4 at 3.3 m/s;
    # the stock 1e-4 is a sealed Venlo glasshouse.
    "cLeakage": 1e-3,
    "rhoRf": 920.0,             # kg m-3, polyethylene
    "hRf": 1.5e-4,              # m, 6 mil
    "lambdaRf": 0.33,           # W m-1 K-1
    "cPRf": 2300.0,             # J kg-1 K-1
    "tauRfPar": 0.87, "rhoRfPar": 0.10,
    "tauRfNir": 0.87, "rhoRfNir": 0.10,
    "rhoFlrPar": 0.15, "rhoFlrNir": 0.30,   # bare soil, not white concrete
    # No thermal screen. Vanthoor's model always has the layer, so it is made absent:
    # transparent in every band, emitting nothing, and held open (CONTROLS).
    "tauThScrPar": 1.0, "rhoThScrPar": 0.0, "tauThScrNir": 1.0, "rhoThScrNir": 0.0,
    "tauThScrFir": 1.0, "rhoThScrFir": 0.0, "epsThScrFir": 0.0,
    "pBoil": 0.0,               # no heating
    "phiExtCo2": 0.0,           # no CO2 enrichment
    "hElevation": 243.0,        # m, McAllister Farm
}

#: Long-wave behaviour of the film, the night's decisive number. Plain polyethylene lets
#: most thermal radiation through to a clear sky; an IR ("thermic") film, which most
#: greenhouse film sold for high tunnels now is, holds much of it. Each row sums to 1.
COVERS = {
    "thermic": {"tauRfFir": 0.20, "epsRfFir": 0.70, "rhoRfFir": 0.10},
    "clear": {"tauRfFir": 0.70, "epsRfFir": 0.25, "rhoRfFir": 0.05},
}

#: The grower's rule the virtual farm's tunnel uses: sides up past 27 °C, down below 20.
#: GreenLight's control is proportional, so the sides open across that band.
CONTROLS = {
    "uThScr": "0",              # the absent screen, open
    "uRoof": "0",
    "uSide": "proportionalControl(tAir, 23.5, 7, 0, 1)",
    "uBlScr": "0",
    "uExtCo2": "0",
    "uBoil": "0",
    "uBoilGro": "0",
}


#: Formulas replaced, and why.
#:
#: The crop's CO2 compensation point (Vanthoor 2011, ch. 9) scales the leaf's by the
#: ratio of leaf to canopy electron-transport capacity, `j25LeafMax / j25CanMax`, which
#: is 1/LAI. The formula holds for LAI of 1 and more. A young crop — a tunnel's
#: transplants, LAI 0.13 here — makes the ratio near 8, and the compensation point
#: negative: -150 ppm. Gross photosynthesis divides by (Cs + 2 gamma), which is then
#: nought at Cs = 300 ppm, and a house that is not enriched with CO2 crosses 300 ppm
#: every sunny morning. That pole, not the tunnel, was what stopped GreenLight's solver at
#: the first sunrise in every configuration tried: an enriched glasshouse stays far above
#: it. Capped at 1, a canopy thinner than one leaf layer has the leaf's own compensation
#: point, cGamma per degree — about 34 ppm at 20 °C.
FORMULAS = {
    "gamma": "min(1, j25LeafMax / j25CanMax) * cGamma * tCan"
             " + 20 * cGamma * (1 - min(1, j25LeafMax / j25CanMax))",
}


@dataclass(frozen=True)
class Hour:
    when: _dt.datetime          # UTC, the start of the hour
    t: float                    # air temperature at 2 m, °C
    rh: float                   # relative humidity at 2 m, %
    wind: float                 # m s-1 at 10 m
    sw: float                   # global radiation, W m-2
    lw: float                   # downward long-wave, W m-2
    rain: float                 # mm in the hour
    ps: float                   # kPa


def load_power_hourly(path: str) -> list:
    """NASA POWER's hourly point JSON. Its irradiances are MJ per hour per square metre,
    not W m-2; a mistake there is a factor of 3600."""
    with open(path, encoding="utf-8") as h:
        doc = json.load(h)
    p = doc["properties"]["parameter"]
    out = []
    for key in sorted(p["T2M"]):
        when = _dt.datetime.strptime(key, "%Y%m%d%H").replace(tzinfo=UTC)
        vals = {k: p[k][key] for k in p}
        if any(v == -999 for v in vals.values()):
            continue
        out.append(Hour(when, vals["T2M"], vals["RH2M"], vals["WS10M"],
                        vals["ALLSKY_SFC_SW_DWN"] * 1e6 / 3600.0,
                        vals["ALLSKY_SFC_LW_DWN"] * 1e6 / 3600.0,
                        vals["PRECTOTCORR"], vals["PS"]))
    return out


def save_hours(hours: list, path: str, source: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as h:
        h.write(f"# {source}\n")
        w = csv.writer(h)
        w.writerow(["utc", "t2m_c", "rh2m_pct", "ws10m_m_s", "sw_w_m2", "lw_w_m2",
                    "rain_mm", "ps_kpa"])
        for x in hours:
            w.writerow([x.when.strftime("%Y-%m-%dT%H:%MZ"), x.t, x.rh, x.wind, round(x.sw, 2),
                        round(x.lw, 2), x.rain, x.ps])


def read_hours(path: str) -> list:
    out = []
    with open(path, encoding="utf-8") as h:
        rows = csv.DictReader(line for line in h if not line.startswith("#"))
        for r in rows:
            out.append(Hour(_dt.datetime.strptime(r["utc"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC),
                            float(r["t2m_c"]), float(r["rh2m_pct"]), float(r["ws10m_m_s"]),
                            float(r["sw_w_m2"]), float(r["lw_w_m2"]), float(r["rain_mm"]),
                            float(r["ps_kpa"])))
    return out


def vapour_pressure(t_c: float, rh_pct: float) -> float:
    """Pa, from Tetens over water."""
    return rh_pct / 100.0 * 610.78 * math.exp(17.27 * t_c / (t_c + 237.3))


def sky_temperature(lw_w_m2: float) -> float:
    """°C: the black body that would send down the measured long-wave."""
    return (lw_w_m2 / SIGMA) ** 0.25 - 273.15


def co2_mg_m3(t_c: float, ps_kpa: float, ppm: float = CO2_PPM) -> float:
    return ppm * 44.01 / 22.414 * 273.15 / (t_c + 273.15) * (ps_kpa / 101.325)


def greenlight_weather(hours: list, path: str, *, soil_c: float, elevation_m: float) -> None:
    """The weather file GreenLight reads: seconds from the first hour, then outdoor air
    and vapour pressure, CO2, wind, sky temperature, soil at 2 m, global radiation, the
    day's radiation sum, day and night, and elevation; names, descriptions and units in
    the first three rows."""
    by_day = {}
    for x in hours:
        by_day.setdefault(x.when.date(), 0.0)
        by_day[x.when.date()] += x.sw * 3600.0 / 1e6
    t0 = hours[0].when
    with open(path, "w", encoding="utf-8", newline="") as h:
        w = csv.writer(h)
        w.writerow(["Time", "tOut", "vpOut", "co2Out", "wind", "tSky", "tSoOut", "iGlob",
                    "dayRadSum", "isDay", "isDaySmooth", "hElevation"])
        w.writerow(["Time since start of data", "Outdoor temperature", "Outdoor vapor pressure",
                    "Outdoor CO2 concentration", "Outdoor wind speed", "Apparent sky temperature",
                    "Soil temperature at 2 m depth", "Outdoor global solar radiation",
                    "Daily sum of outdoor global solar radiation", "Day or night",
                    "Smooth day or night", "Elevation at location"])
        w.writerow(["s", "°C", "Pa", "mg m**-3", "m s**-1", "°C", "°C", "W m**-2", "MJ m**-2",
                    "-", "-", "m above sea level"])
        for x in hours:
            day = 1 if x.sw > 0.5 else 0
            w.writerow([int((x.when - t0).total_seconds()), round(x.t, 3),
                        round(vapour_pressure(x.t, x.rh), 2), round(co2_mg_m3(x.t, x.ps), 2),
                        round(x.wind, 3), round(sky_temperature(x.lw), 3), round(soil_c, 2),
                        round(x.sw, 2), round(by_day[x.when.date()], 4), day,
                        round(min(1.0, x.sw / 50.0), 4), elevation_m])


def tunnel_definition(cover: str = "thermic") -> dict:
    """GreenLight's overrides for the tunnel, as one model component."""
    params = {**TUNNEL, **COVERS[cover]}
    return {"Info": {"About": f"An unheated single-poly high tunnel ({cover} film), fieldmesh "
                              "modules/twin. Replaces the Vanthoor (2011) glasshouse's design "
                              "and climate control."},
            "Tunnel design": {k: {"definition": repr(float(v))} for k, v in params.items()},
            "Tunnel control": {k: {"definition": v} for k, v in CONTROLS.items()},
            "Tunnel formulas": {k: {"definition": v} for k, v in FORMULAS.items()}}


def run_greenlight(weather_csv: str, days: float, out_csv: str, *, cover: str = "thermic") -> str:
    """Run GreenLight's Vanthoor (2011) greenhouse and crop, configured as the tunnel, on
    `weather_csv`. Needs this module's environment (requirements.txt)."""
    from importlib import resources
    from pathlib import PurePath
    import greenlight
    base = resources.files("greenlight") / "models" / "katzin_2021" / "definition" / "vanthoor_2011"
    prompt = [str(PurePath(base / "greenhouse_vanthoor_2011_chapter_8.json")),
              str(PurePath(base / "crop_vanthoor_2011_chapter_9_simplified.json")),
              str(PurePath(base / "controls_katzin_2021.json")),
              os.path.abspath(weather_csv),
              tunnel_definition(cover),
              {"options": {"t_start": "0", "t_end": str(int(days * 86400))}}]
    mdl = greenlight.GreenLight(base_path="", input_prompt=prompt, output_path=out_csv)
    mdl.run()
    return out_csv


def read_greenlight(out_csv: str, start: _dt.datetime) -> dict:
    """Hourly inside air temperature from a GreenLight output file: {UTC hour: °C}."""
    sums = {}
    with open(out_csv, encoding="utf-8-sig") as h:
        rows = csv.reader(h)
        header = next(rows)
        ti, ta = header.index("Time"), header.index("tAir")
        for r in rows:
            try:
                s, t = float(r[ti]), float(r[ta])
            except ValueError:
                continue                       # description and unit rows
            hour = (start + _dt.timedelta(seconds=s)).replace(minute=0, second=0, microsecond=0)
            acc = sums.setdefault(hour, [0.0, 0])
            acc[0] += t
            acc[1] += 1
    return {k: v[0] / v[1] for k, v in sums.items()}


def run_sim_tunnel(hours: list, *, lon: float, film: str = "thermic", sky: bool = True) -> dict:
    """The virtual farm's tunnel on the same weather, stepped every five minutes as the
    farm steps it: {UTC hour: mean inside °C}. Its daylight is the farm's — a sine of
    local solar time. With `sky`, its nights know the cloud from the sky's long-wave
    (`physics.cloud_from_longwave`); without, rain is its only sign of cloud, as on the
    seeded farm."""
    sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sim"))
    import physics as ph
    tunnel = ph.Tunnel.of("hoop", film)
    out = {}
    offset = _dt.timedelta(hours=lon / 15.0)
    for a, b in zip(hours, hours[1:] + hours[-1:]):
        acc = []
        for k in range(12):
            f = k / 12.0
            t = a.t + (b.t - a.t) * f
            solar = a.when + _dt.timedelta(minutes=5 * k) + offset
            hour = solar.hour + solar.minute / 60.0
            daylight = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0))
            raining = a.rain > 0.1
            w = ph.Weather(air_temp_c=t, relative_humidity=a.rh, rain_mm=a.rain / 12.0,
                           et0_mm=0.0, raining=raining,
                           cloud=ph.cloud_from_longwave(a.t, a.rh, a.lw) if sky else None)
            acc.append(tunnel.step(w, daylight))
        out[a.when] = sum(acc) / len(acc)
    return out


def nights(hours: list, inside: dict, *, lon: float) -> list:
    """Per local night (18:00 to 08:00 solar time): outside low, inside low, and whether
    the sky was clear (long-wave below the night's clear-sky threshold)."""
    offset = _dt.timedelta(hours=lon / 15.0)
    groups = {}
    for x in hours:
        solar = x.when + offset
        if solar.hour >= 18 or solar.hour < 8:
            night = (solar - _dt.timedelta(hours=8)).date()
            if x.when in inside:
                groups.setdefault(night, []).append((x.t, inside[x.when], x.lw, x.when))
    out = []
    for night, rows in sorted(groups.items()):
        if len(rows) < 12:
            continue
        t_out = min(r[0] for r in rows)
        t_in = min(r[1] for r in rows)
        # Clear sky: the long-wave a clear sky sends is well below what the air would.
        coldest = min(rows, key=lambda r: r[0])
        clear = coldest[2] < 0.80 * SIGMA * (coldest[0] + 273.15) ** 4
        out.append({"night": night.isoformat(), "out_low": t_out, "in_low": t_in,
                    "gain": t_in - t_out, "clear": clear})
    return out


def summarise(rows: list) -> dict:
    def stats(sel):
        g = [r["gain"] for r in sel]
        return {"n": len(g), "mean_gain": round(statistics.mean(g), 2) if g else None,
                "min_gain": round(min(g), 2) if g else None}
    frost_out = [r for r in rows if r["out_low"] <= 0.0]
    return {"all": stats(rows), "clear": stats([r for r in rows if r["clear"]]),
            "cloudy": stats([r for r in rows if not r["clear"]]),
            "frost_nights_outside": len(frost_out),
            "frost_nights_inside": sum(1 for r in rows if r["in_low"] <= 0.0),
            "hard_frost_inside": sum(1 for r in rows if r["in_low"] <= -2.2)}
