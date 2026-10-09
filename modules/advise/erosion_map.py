#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Soil erosion across a field, cell by cell: where it loses more soil than it can spare.

    python3 modules/advise/erosion_map.py field.geojson --cover row_crop --out field-erosion.geojson
    python3 modules/advise/erosion_map.py --bbox -86.596,35.061,-86.587,35.068 --cover hay

The site profile estimates erosion at one point from the soil survey's representative
slope. A field is not one slope. This applies RUSLE, A = R K LS C P, to every 10 m cell:

* **slope** from USGS 3DEP 1/3 arc-second elevation (public domain), read for just the
  field's window from the national cloud tiles with GDAL;
* **K**, erodibility, and **T**, the tolerable loss, from the USDA soil survey's own map-unit
  polygons (Soil Data Access): the dominant component's surface horizon, by the polygon each
  cell falls in;
* **R**, rainfall erosivity, from the site's annual rain (Renard and Freimund 1994), as the
  site profile does — or the county's official value with `--r` (US units, as the RUSLE2
  database and NRCS guides give it), which is better: at McAllister the estimate from
  rain is about 390 where Tennessee's published values are nearer 250 to 300;
* **LS** by McCool's equations from each cell's slope over a slope length you give
  (default 30 m) — the same length everywhere, which is the simplification: a flow-routed
  length would lengthen it in hollows and shorten it on ridges;
* **C** from a cover preset or a number, and **P**, practices, 1 unless given.

The C presets are orders of magnitude for a year's average — bare fallow 1, clean-tilled
row crops 0.3, no-till row crops 0.1, hay and pasture 0.01, woodland 0.001 — not a field's
own; RUSLE2 works one out from its rotation and tillage. The answer is a map of where to
look first, not a conservation plan.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "tools"))
import site_profile as SP  # noqa: E402

SDA = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
TILE = ("/vsicurl/https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/"
        "{ns}{lat:02d}{ew}{lon:03d}/USGS_13_{ns}{lat:02d}{ew}{lon:03d}.tif")
COVER = {"bare": 1.0, "row_crop": 0.3, "no_till": 0.1, "hay": 0.01, "pasture": 0.01, "woodland": 0.001}
T_TO_T_HA = 2.2417            # US ton per acre to metric tonne per hectare
K_TO_SI = 0.1317              # K from US customary to t·ha·h/(ha·MJ·mm)
R_US_TO_SI = 17.02            # R from hundreds of ft·tonf·in/(ac·h·yr) to MJ·mm/(ha·h·yr)


# ------------------------------------------------------------------ geometry

def parse_wkt(wkt: str) -> list:
    """POLYGON or MULTIPOLYGON WKT -> [polygon], each [ring], each [(lon, lat)]."""
    body = wkt[wkt.index("("):].strip()
    multi = wkt.strip().upper().startswith("MULTIPOLYGON")
    def ring(text):
        return [tuple(float(x) for x in p.split()) for p in text.split(",")]
    def polygon(text):
        return [ring(r.strip().strip("()")) for r in _split_parens(text.strip()[1:-1])]
    return [polygon(p) for p in _split_parens(body[1:-1])] if multi else [polygon(body)]


def _split_parens(text: str) -> list:
    out, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                out.append(text[start:i + 1])
    return out


def _in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def contains(polygons: list, x: float, y: float) -> bool:
    """Inside an outer ring and outside its holes, for any of the polygons."""
    return any(_in_ring(x, y, p[0]) and not any(_in_ring(x, y, h) for h in p[1:]) for p in polygons)


def field_polygons(path: str | None, bbox: str | None) -> list:
    if bbox:
        x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
        return [[[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]]
    doc = json.load(open(path, encoding="utf-8"))
    geoms = [f["geometry"] for f in doc.get("features", [doc])] if doc.get("type") != "Polygon" else [doc]
    out = []
    for g in geoms:
        if g["type"] == "Polygon":
            out.append([[tuple(c[:2]) for c in r] for r in g["coordinates"]])
        elif g["type"] == "MultiPolygon":
            out += [[[tuple(c[:2]) for c in r] for r in p] for p in g["coordinates"]]
    return out


def bounds(polygons: list) -> tuple:
    xs = [x for p in polygons for r in p for x, _ in r]
    ys = [y for p in polygons for r in p for _, y in r]
    return min(xs), min(ys), max(xs), max(ys)


def wkt_of(polygons: list) -> str:
    x0, y0, x1, y1 = bounds(polygons)
    return f"POLYGON(({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"


# ------------------------------------------------------------------ sources

def dem(x0: float, y0: float, x1: float, y1: float, pad: float = 0.0003) -> dict:
    """{(col, row): elevation} and the grid's step, from the 3DEP tile covering the window."""
    lat_tile, lon_tile = math.ceil(y1), math.ceil(-x0) if x0 < 0 else math.floor(x0)
    src = TILE.format(ns="n" if lat_tile >= 0 else "s", lat=abs(lat_tile),
                      ew="w" if x0 < 0 else "e", lon=abs(lon_tile))
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "w.xyz")
        subprocess.run(["gdal_translate", "-q", "-of", "XYZ", "-projwin", str(x0 - pad), str(y1 + pad),
                        str(x1 + pad), str(y0 - pad), src, out], check=True)
        pts = [tuple(float(v) for v in line.split()) for line in open(out) if line.strip()]
    return grid(pts)


def grid(points: list) -> dict:
    xs = sorted({p[0] for p in points})
    ys = sorted({p[1] for p in points}, reverse=True)
    xi, yi = {x: i for i, x in enumerate(xs)}, {y: j for j, y in enumerate(ys)}
    return {"z": {(xi[x], yi[y]): z for x, y, z in points}, "xs": xs, "ys": ys,
            "dx": (xs[-1] - xs[0]) / (len(xs) - 1), "dy": (ys[0] - ys[-1]) / (len(ys) - 1)}


def soil_units(polygons: list) -> list:
    """[(polygons, {mukey, muname, k, t})] for the map units under the field."""
    def q(sql):
        body = json.dumps({"query": sql, "format": "JSON+COLUMNNAME"}).encode()
        req = urllib.request.Request(SDA, data=body, headers={"Content-Type": "application/json"})
        rows = json.load(urllib.request.urlopen(req, timeout=120)).get("Table", [])
        return [dict(zip(rows[0], r)) for r in rows[1:]] if rows else []
    shapes = q(f"""SELECT P.mukey, P.mupolygongeo.STAsText() AS wkt FROM mupolygon P WHERE P.mupolygonkey IN
        (SELECT * FROM SDA_Get_Mupolygonkey_from_intersection_with_WktWgs84('{wkt_of(polygons)}'))""")
    keys = sorted({s["mukey"] for s in shapes})
    if not keys:
        return []
    props = {r["mukey"]: r for r in q(f"""SELECT mu.mukey, mu.muname, c.comppct_r, c.tfact, ch.kwfact
        FROM mapunit mu JOIN component c ON c.mukey = mu.mukey AND c.majcompflag = 'Yes'
        JOIN chorizon ch ON ch.cokey = c.cokey AND ch.hzdept_r = 0 WHERE mu.mukey IN ({','.join(keys)})
        ORDER BY c.comppct_r DESC""")[::-1]}
    out = []
    for s in shapes:
        p = props.get(s["mukey"])
        if p and p.get("kwfact") and p.get("tfact"):
            out.append((parse_wkt(s["wkt"]), {"mukey": s["mukey"], "muname": p["muname"],
                                              "k": float(p["kwfact"]), "t": float(p["tfact"])}))
    return out


# ------------------------------------------------------------------ RUSLE

def slope_pct(g: dict, i: int, j: int) -> float | None:
    """Central differences, in metres from degrees at the cell's latitude."""
    z = g["z"]
    need = [(i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)]
    if any(n not in z for n in need):
        return None
    lat = math.radians(g["ys"][j])
    dx_m = g["dx"] * 111320.0 * math.cos(lat)
    dy_m = g["dy"] * 110540.0
    dzdx = (z[(i + 1, j)] - z[(i - 1, j)]) / (2 * dx_m)
    dzdy = (z[(i, j - 1)] - z[(i, j + 1)]) / (2 * dy_m)
    return 100.0 * math.hypot(dzdx, dzdy)


def cells(g: dict, field: list, units: list, r_si: float, c: float, p: float = 1.0,
          length_m: float = 30.0) -> list:
    out = []
    for (i, j), _ in g["z"].items():
        x, y = g["xs"][i], g["ys"][j]
        if not contains(field, x, y):
            continue
        s = slope_pct(g, i, j)
        unit = next((u for polys, u in units if contains(polys, x, y)), None)
        if s is None or unit is None:
            continue
        ls = SP.ls_factor(s, length_m)
        a = r_si * unit["k"] * K_TO_SI * ls * c * p
        t = unit["t"] * T_TO_T_HA
        out.append({"lon": x, "lat": y, "slope_pct": round(s, 1), "ls": round(ls, 2),
                    "loss_t_ha": round(a, 2), "tolerable_t_ha": round(t, 1),
                    "times_tolerable": round(a / t, 2), "mukey": unit["mukey"], "map_unit": unit["muname"]})
    return out


def summary(rows: list) -> dict:
    if not rows:
        return {"cells": 0}
    over = [r for r in rows if r["times_tolerable"] > 1.0]
    return {"cells": len(rows), "share_over_tolerable": round(len(over) / len(rows), 3),
            "mean_loss_t_ha": round(sum(r["loss_t_ha"] for r in rows) / len(rows), 2),
            "worst_times_tolerable": max(r["times_tolerable"] for r in rows),
            "steepest_pct": max(r["slope_pct"] for r in rows)}


def geojson(rows: list, g: dict) -> dict:
    hx, hy = g["dx"] / 2, g["dy"] / 2
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {k: v for k, v in r.items() if k not in ("lon", "lat")},
         "geometry": {"type": "Polygon", "coordinates": [[
             [r["lon"] - hx, r["lat"] - hy], [r["lon"] + hx, r["lat"] - hy],
             [r["lon"] + hx, r["lat"] + hy], [r["lon"] - hx, r["lat"] + hy],
             [r["lon"] - hx, r["lat"] - hy]]]}} for r in rows]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("field", nargs="?", help="GeoJSON polygon of the field (WGS84)")
    ap.add_argument("--bbox", help="lon_min,lat_min,lon_max,lat_max instead of a polygon")
    ap.add_argument("--cover", default="row_crop", help=f"one of {', '.join(COVER)}, or a C value")
    ap.add_argument("--practice", type=float, default=1.0, help="P factor")
    ap.add_argument("--slope-length", type=float, default=30.0)
    ap.add_argument("--rain-mm", type=float, help="annual rain; default from NASA POWER 1991-2020")
    ap.add_argument("--r", type=float, help="the county's R factor in US units; overrides the rain estimate")
    ap.add_argument("--cache", help="NASA POWER cache, for the rain")
    ap.add_argument("--out", help="write the cells as GeoJSON here")
    args = ap.parse_args(argv)
    field = field_polygons(args.field, args.bbox)
    x0, y0, x1, y1 = bounds(field)
    if args.rain_mm is None:
        import nasa_power as NP
        days = NP.days_of(NP.fetch_power((y0 + y1) / 2, (x0 + x1) / 2, 1991, 2020, args.cache))
        years = {d.year for d, _ in days}
        args.rain_mm = sum(v.get("PRECTOTCORR", 0.0) for _, v in days) / len(years)
    c = COVER.get(args.cover) if args.cover in COVER else float(args.cover)
    g = dem(x0, y0, x1, y1)
    r_si = args.r * R_US_TO_SI if args.r else SP.rainfall_erosivity(args.rain_mm)
    rows = cells(g, field, soil_units(field), r_si, c, args.practice, args.slope_length)
    s = summary(rows)
    print(f"{s['cells']} cells of about 10 m; rain {args.rain_mm:.0f} mm a year; cover C = {c}")
    if s["cells"]:
        print(f"mean loss {s['mean_loss_t_ha']} t/ha a year; {s['share_over_tolerable']:.0%} of the field "
              f"loses more than its soil's tolerable rate (worst {s['worst_times_tolerable']}x); "
              f"steepest {s['steepest_pct']}%")
    if args.out:
        json.dump(geojson(rows, g), open(args.out, "w"), indent=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
