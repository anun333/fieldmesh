#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A starting range for a probe, from the USDA soil survey at its location and depth.

    python3 soil_survey.py 35.06445 -86.59137 --depths 0.05,0.2,0.5,1.0

Asks Soil Data Access — the public query service behind the USDA NRCS soil survey
(SSURGO), mapped county by county at field scale — for the dominant soil at a point, and
reads each horizon's sand, clay, saturated water content, field capacity and wilting
point. From those it proposes the two thresholds the ISMN scoring showed a generic
default gets wrong:

* **a range limit**, the soil's saturated water content at the probe's depth plus a
  margin. Scored on 2.2 million Tennessee readings, a limit taken this way agreed with 89%
  of ISMN's above-saturation flags, against 74% for a generic 0.46, while flagging 0.02%
  of the readings ISMN rates good — outside one probe where map and ISMN agree something
  is wrong (docs/notes/ismn-scoring.md);
* **a flatline duration**, from the measured dwell for the soil's texture at that depth:
  the 99.9th-percentile run of one identical value on healthy readings across 1,720
  probes at 87 humid-subtropical SCAN stations, grouped by the soil survey at each probe's
  own depth.

**These are starting values, not answers.** A soil-survey figure is representative of a
map unit, not measured at the probe, and the climate behind the dwell table is one class
(Köppen Cfa). Open questions Q24 and Q23 recommend learning each series' own thresholds
once it has a season of history; this is the default it starts from.

Field capacity and wilting point come back too, because vocab.py already names them as
CF terms and an irrigation module will want them.

The United States only. Elsewhere the nearest equivalent is ISRIC's SoilGrids, which
gives texture globally at 250 m but needs a pedotransfer function to turn texture into
the water contents SSURGO reports directly.
"""
from __future__ import annotations

import argparse
import json
import urllib.request

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"

QUERY = """SELECT TOP 40 mu.muname, c.compname, c.comppct_r, ch.hzdept_r, ch.hzdepb_r,
 ch.sandtotal_r, ch.claytotal_r, ch.wsatiated_r, ch.wthirdbar_r, ch.wfifteenbar_r
 FROM mapunit mu JOIN component c ON c.mukey = mu.mukey
 JOIN chorizon ch ON ch.cokey = c.cokey
 WHERE mu.mukey IN (SELECT * FROM
   SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon} {lat})'))
 AND c.majcompflag = 'Yes'
 ORDER BY c.comppct_r DESC, c.compname, ch.hzdept_r"""

#: Above the saturated water content, in m3/m3. Small, because the scoring showed the
#: map's own figure is already close to what ISMN treats as the physical limit.
RANGE_MARGIN = 0.02

#: Measured: 99.9th-percentile hours of one identical value on readings ISMN rates good,
#: by soil-survey texture at the probe's depth. 1,720 probes, 87 SCAN stations, Köppen
#: Cfa. See docs/notes/ismn-scoring.md.
DWELL_P999_H = {
    ("sandy", "top"): 9, ("loamy", "top"): 11, ("clayey", "top"): 19,
    ("sandy", "mid"): 15, ("loamy", "mid"): 22, ("clayey", "mid"): 32,
    ("sandy", "deep"): 22, ("loamy", "deep"): 40, ("clayey", "deep"): 64,
}
#: How far above the healthy 99.9th percentile a flatline waits. A judgement, stated:
#: twice the dwell keeps the false-alarm rate well under one in a thousand runs while a
#: probe in a bucket is still caught within a day or three.
DWELL_FACTOR = 2.0


def query(lat: float, lon: float, *, timeout: float = 60.0) -> dict:
    """The dominant major component's horizons at a point, from Soil Data Access."""
    body = json.dumps({"query": QUERY.format(lat=lat, lon=lon),
                       "format": "JSON+COLUMNNAME"}).encode()
    request = urllib.request.Request(SDA_URL, data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse(json.loads(response.read().decode()))


def parse(doc: dict) -> dict:
    table = doc.get("Table") or []
    if len(table) < 2:
        return {"map_unit": None, "component": None, "horizons": []}
    rows = [dict(zip(table[0], row)) for row in table[1:]]
    dominant = rows[0]["compname"]

    def number(value):
        return None if value in (None, "") else float(value)

    horizons = [{"top_cm": number(r["hzdept_r"]), "bottom_cm": number(r["hzdepb_r"]),
                 "sand_pct": number(r["sandtotal_r"]), "clay_pct": number(r["claytotal_r"]),
                 "saturated": _fraction(r["wsatiated_r"]),
                 "field_capacity": _fraction(r["wthirdbar_r"]),
                 "wilting_point": _fraction(r["wfifteenbar_r"])}
                for r in rows if r["compname"] == dominant]
    return {"map_unit": rows[0]["muname"], "component": dominant,
            "component_pct": number(rows[0]["comppct_r"]), "horizons": horizons}


def _fraction(percent):
    """SSURGO reports water contents as volume percent; the farm stores m3/m3."""
    return None if percent in (None, "") else round(float(percent) / 100.0, 4)


def horizon_at(soil: dict, depth_m: float) -> dict | None:
    cm = depth_m * 100.0
    for h in soil["horizons"]:
        if (h["top_cm"] is not None and h["bottom_cm"] is not None
                and h["top_cm"] <= cm < h["bottom_cm"] and h["clay_pct"] is not None):
            return h
    return None


def texture(h: dict) -> str:
    if h["sand_pct"] is not None and h["sand_pct"] >= 70:
        return "sandy"
    return "clayey" if h["clay_pct"] >= 35 else "loamy"


def band(depth_m: float) -> str:
    return "top" if depth_m <= 0.21 else "mid" if depth_m <= 0.6 else "deep"


def proposed_limits(soil: dict, depth_m: float) -> dict | None:
    """Starting thresholds for a probe at `depth_m`, with where each came from."""
    h = horizon_at(soil, depth_m)
    if h is None:
        return None
    kind = texture(h)
    dwell = DWELL_P999_H[(kind, band(depth_m))]
    return {
        "depth_m": depth_m,
        "horizon_cm": (h["top_cm"], h["bottom_cm"]),
        "texture": kind,
        "max": (round(h["saturated"] + RANGE_MARGIN, 3)
                if h["saturated"] is not None else None),
        "flat_seconds": int(dwell * DWELL_FACTOR * 3600),
        "field_capacity": h["field_capacity"],
        "wilting_point": h["wilting_point"],
        "source": {"map_unit": soil["map_unit"], "component": soil["component"],
                   "survey": "USDA NRCS SSURGO via Soil Data Access"},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--depths", default="0.05,0.1,0.2,0.5,1.0")
    args = ap.parse_args(argv)
    soil = query(args.lat, args.lon)
    if not soil["horizons"]:
        print("No soil-survey data at that point (outside the United States, water, or "
              "an unsurveyed area).")
        return 1
    print(f"{soil['map_unit']}  —  {soil['component']} ({soil['component_pct']:.0f}% of "
          f"the map unit)\n")
    print(f"  {'depth':>6} {'horizon':>10} {'texture':>8} {'range max':>10} "
          f"{'flatline':>9} {'FC':>6} {'WP':>6}")
    for depth in (float(d) for d in args.depths.split(",")):
        limits = proposed_limits(soil, depth)
        if limits is None:
            print(f"  {depth:>5.2f}m  no horizon at this depth (bedrock, or below the "
                  f"described profile)")
            continue
        top, bottom = limits["horizon_cm"]
        print(f"  {depth:>5.2f}m {top:>4.0f}-{bottom:<4.0f}cm {limits['texture']:>8} "
              f"{limits['max'] or '-':>10} {limits['flat_seconds'] / 3600:>8.0f}h "
              f"{limits['field_capacity'] or '-':>6} {limits['wilting_point'] or '-':>6}")
    print("\nStarting values from a map unit, not measurements at the probe. Refine from "
          "the series' own history (open-questions Q23, Q24).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
