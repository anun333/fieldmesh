#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""NASA POWER daily weather for a point: fetch, cache, read.

Layer zero's, because recorded weather is input data like a forecast: the simulator
replays it (tools/weather_csv.py, sim/physics.py `RecordedClimate`) and the advisor
module builds a site's climate from it (modules/advise/site_profile.py). Both import it
from here, so the module depends on layer zero and never the reverse.

NASA POWER is CC BY 4.0; data used from it is credited where it appears.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import urllib.request

POWER = ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters="
         "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,ALLSKY_SFC_SW_DWN,RH2M,WS2M&community=AG"
         "&longitude={lon}&latitude={lat}&start={start}0101&end={end}1231&format=JSON")
FILL = -999.0


def fetch_power(lat: float, lon: float, start: int, end: int, cache: str | None) -> dict:
    url = POWER.format(lat=round(lat, 4), lon=round(lon, 4), start=start, end=end)
    file = None
    if cache:
        os.makedirs(cache, exist_ok=True)
        file = os.path.join(cache, hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")
        if os.path.exists(file):
            with open(file, encoding="utf-8") as h:
                return json.load(h)
    with urllib.request.urlopen(url, timeout=300) as response:
        doc = json.loads(response.read().decode("utf-8"))
    if file:
        with open(file, "w", encoding="utf-8") as h:
            json.dump(doc, h)
    return doc


def days_of(doc: dict) -> list:
    """[(date, {T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, ALLSKY_SFC_SW_DWN, RH2M, WS2M})], with
    fill values left out per parameter."""
    params = doc["properties"]["parameter"]
    dates = sorted(next(iter(params.values())))
    out = []
    for d in dates:
        values = {k: v[d] for k, v in params.items() if v.get(d, FILL) != FILL}
        out.append((_dt.date(int(d[:4]), int(d[4:6]), int(d[6:])), values))
    return out
