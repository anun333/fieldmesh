#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A frost watch for covered crops: tonight's forecast through the twin (Q28, step 2).

The frost watch in modules/rules answers for open beds: will tonight's forecast low reach
the farm's warning point? Under a tunnel the answer is different. It depends on the film,
on how clear the sky is (a clear sky draws heat out through polyethylene) and on how much
the day stored in the soil. The open-bed watch warns a tunnel grower on nights the tunnel
will hold, and on a clear night under clear film it can say nothing about the hours the
tunnel runs colder than the air outside.

So the twin runs the night. It warms up on the last 36 hours of observed weather, from
soil temperatures taken from the weeks before, then runs dusk to dawn on the forecast:
air temperature, humidity, wind and cloud cover. Cloud becomes the long-wave sky the
tunnel radiates to (Brutsaert's clear-sky emissivity, raised toward a black body by
cloud), and the morning's sun is a clear sky dimmed by cloud (Kasten and Czeplak). The
inside low is judged by a CEL rule through modules/rules, so the decision carries its
inputs and the twin's own numbers, like every other decision here.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import io
import math
import os
import sys
import tempfile
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
import i18n  # noqa: E402
import twin as T  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "twin")
HOUR = _dt.timedelta(hours=1)
SPINUP_H = 36
NIGHT_H = 14                       # 6 pm to 8 am local standard time
KNOT = 0.514444                    # m s-1


def clear_sky_emissivity(t_c: float, rh_pct: float) -> float:
    """Brutsaert (1975): 1.24 (e/T)^(1/7), e in hPa, T in K."""
    e_hpa = T.vapour_pressure(t_c, rh_pct) / 100.0
    return 1.24 * (e_hpa / (t_c + 273.15)) ** (1.0 / 7.0)


def sky_longwave(t_c: float, rh_pct: float, cloud: float) -> float:
    """W m-2 from the sky: clear-sky emissivity raised toward 1 by the cloud fraction
    (Crawford and Duchon 1999)."""
    eps = cloud + (1.0 - cloud) * clear_sky_emissivity(t_c, rh_pct)
    return eps * T.SIGMA * (t_c + 273.15) ** 4


def solar_elevation(when: _dt.datetime, lat: float, lon: float) -> float:
    """Degrees above the horizon, to within a degree — enough for a morning's sun."""
    day = when.timetuple().tm_yday
    decl = math.radians(23.44) * math.sin(math.radians(360.0 * (284 + day) / 365.0))
    solar_h = when.hour + when.minute / 60.0 + lon / 15.0
    hour_angle = math.radians(15.0 * (solar_h - 12.0))
    phi = math.radians(lat)
    s = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def sky_shortwave(when: _dt.datetime, lat: float, lon: float, cloud: float) -> float:
    """W m-2: Haurwitz's clear sky dimmed by cloud as Kasten and Czeplak (1980) have it."""
    e = solar_elevation(when + 0.5 * HOUR, lat, lon)
    if e <= 0:
        return 0.0
    s = math.sin(math.radians(e))
    return 1098.0 * s * math.exp(-0.057 / s) * (1.0 - 0.75 * cloud ** 3.4)


def forecast_hours(series: dict, *, lat: float, lon: float, ps_kpa: float = 98.5) -> list:
    """Hourly `Hour`s from a forecast's series, interpolated between its valid times.

    `series` maps `t_c`, `rh_pct`, `wind_m_s` and `cloud` (a fraction) to
    `[(valid UTC, value)]`."""
    def at(name, when):
        pts = series[name]
        if when <= pts[0][0]:
            return pts[0][1]
        for (a, va), (b, vb) in zip(pts, pts[1:]):
            if a <= when <= b:
                return va + (vb - va) * (when - a) / (b - a)
        return pts[-1][1]
    start = min(series["t_c"])[0]
    end = max(series["t_c"])[0]
    out, when = [], start
    while when <= end:
        t, rh, cloud = at("t_c", when), at("rh_pct", when), min(1.0, max(0.0, at("cloud", when)))
        out.append(T.Hour(when, t, rh, at("wind_m_s", when), sky_shortwave(when, lat, lon, cloud),
                          sky_longwave(t, rh, cloud), 0.0, ps_kpa))
        when += HOUR
    return out


def initial_state(observed: list, start: _dt.datetime, *, deep_c: float) -> dict:
    """The tunnel at the start of the warm-up: air and surfaces at the outside air, and
    the soil layers at the mean air of the last week, fortnight and month, sinking toward
    the deep soil — rather than GreenLight's 16.5 °C glasshouse floor in January."""
    def mean_over(days):
        xs = [h.t for h in observed if start - _dt.timedelta(days=days) <= h.when < start]
        return sum(xs) / len(xs) if xs else deep_c
    before = [h for h in observed if h.when <= start]
    now = max(before, key=lambda h: h.when).t if before else deep_c
    w1, w2, w4 = mean_over(7), mean_over(14), mean_over(30)
    surfaces = {k: now for k in ("tAir", "tTop", "tCan", "tCovIn", "tCovE", "tThScr", "tPipe")}
    return {**surfaces, "tFlr": w1, "tSo1": w1, "tSo2": w2, "tSo3": w4,
            "tSo4": (w4 + deep_c) / 2, "tSo5": deep_c}


def run_twin(hours: list, *, cover: str, init: dict, soil_c: float, elevation_m: float) -> dict:
    """GreenLight as the tunnel over `hours`: {UTC hour: inside °C}."""
    from importlib import resources
    from pathlib import PurePath
    import greenlight
    base = resources.files("greenlight") / "models" / "katzin_2021" / "definition" / "vanthoor_2011"
    with tempfile.TemporaryDirectory() as d:
        w = os.path.join(d, "w.csv")
        T.greenlight_weather(hours, w, soil_c=soil_c, elevation_m=elevation_m)
        days = (hours[-1].when - hours[0].when).total_seconds() / 86400.0
        prompt = [str(PurePath(base / "greenhouse_vanthoor_2011_chapter_8.json")),
                  str(PurePath(base / "crop_vanthoor_2011_chapter_9_simplified.json")),
                  str(PurePath(base / "controls_katzin_2021.json")), w, T.tunnel_definition(cover),
                  {"Initial state": {k: {"init": repr(round(v, 3))} for k, v in init.items()}},
                  {"options": {"t_start": "0", "t_end": str(int(days * 86400))}}]
        buf = io.StringIO()
        with warnings.catch_warnings(), contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            warnings.simplefilter("ignore")
            greenlight.GreenLight(base_path="", input_prompt=prompt,
                                  output_path=os.path.join(d, "o.csv")).run()
        if "Simulation failed" in buf.getvalue():
            raise RuntimeError("GreenLight did not finish the night")
        return T.read_greenlight(os.path.join(d, "o.csv"), hours[0].when)


def night(observed: list, tonight: list, *, dusk: _dt.datetime, dawn: _dt.datetime,
          cover: str = "thermic", soil_c: float = 16.05, elevation_m: float = 243.0) -> dict:
    """The tunnel's night: warmed up on `observed` up to dusk, then run on `tonight`.
    Returns the inside low, its hour and the outside low over dusk to dawn."""
    start = dusk - SPINUP_H * HOUR
    past = [h for h in observed if start <= h.when < dusk]
    ahead = [h for h in tonight if dusk <= h.when <= dawn]
    if len(past) < SPINUP_H - 2 or not ahead:
        raise ValueError("a night needs the 36 hours before it and a forecast for it")
    inside = run_twin(past + ahead, cover=cover, soil_c=soil_c, elevation_m=elevation_m,
                      init=initial_state(observed, start, deep_c=soil_c))
    window = {w: t for w, t in inside.items() if dusk <= w <= dawn}
    low_at = min(window, key=window.get)
    return {"inside_low_c": round(window[low_at], 2), "low_at": low_at.isoformat(),
            "outside_low_c": round(min(h.t for h in ahead), 2), "cover": cover}


#: Where the watch warns, by film, from the 2025-26 backtest (covered_backtest.py): the
#: highest threshold that missed no damaging frost inside. The twin run on the forecast is
#: about 1.1 °C warmer at its low than on the weather that came, and under clear film
#: 0 °C let one damaging night through; +0.5 °C caught all 36.
WARN_BY_COVER = {"thermic": 0.0, "clear": 0.5}


def covered_frost_watch(warn_at_c: float | None = None, *, cover: str = "thermic"):
    """The rule: warn when the twin puts tonight's inside low at or below `warn_at_c`,
    by default the film's threshold from the backtest."""
    import rules as R
    if warn_at_c is None:
        warn_at_c = WARN_BY_COVER[cover]
    return R.Rule(id="covered-frost-watch", version="1",
                  condition="has_forecast && inside_low_c <= warn_at_c",
                  params={"warn_at_c": warn_at_c}, alert_key="twin.frost.alert",
                  message_params={"low": "inside_low_c", "outside": "outside_low_c",
                                  "warn": "warn_at_c"})


def judge(rule, result: dict | None, at: _dt.datetime, inputs: dict) -> dict:
    import rules as R
    context = {"has_forecast": result is not None,
               "inside_low_c": result["inside_low_c"] if result else 99.0,
               "outside_low_c": result["outside_low_c"] if result else 99.0,
               "cover": result["cover"] if result else ""}
    return R.judge(rule, context, inputs, at)


# ---------------------------------------------------------------- live

#: The forecast series the watch reads, by observed property.
LIVE = {"t_c": "air_temperature", "rh_pct": "relative_humidity", "wind_m_s": "wind_speed",
        "cloud": "cloud_area_fraction"}
_TO_SI = {"Cel": lambda v: v, "[degF]": lambda v: (v - 32) * 5 / 9, "K": lambda v: v - 273.15,
          "%": lambda v: v, "km/h": lambda v: v / 3.6, "m/s": lambda v: v,
          "[mi_i]/h": lambda v: v * 0.44704, "1": lambda v: v}


def live_weather(state, start: _dt.datetime, end: _dt.datetime, *, lat: float, lon: float):
    """Hourly weather from the forecast datastreams in a log, from `start` to `end`.

    Each hour is the latest issue for it (Q26's live value), so the hours already past
    are forecasts made a few hours ahead — near enough to what happened to warm the twin
    up on — and tonight's are tonight's forecast. Works on a `project.State` or on a module
    host's `RemoteState` (§8.3)."""
    from model import DatastreamKind
    streams = {}
    for ds in state.datastreams.values():
        if ds.kind is not DatastreamKind.FORECAST:
            continue
        for key, prop in LIVE.items():
            if ds.observed_property.rstrip("/").endswith("/" + prop):
                streams.setdefault(key, ds)
    if set(streams) != set(LIVE):
        missing = sorted(LIVE[k] for k in set(LIVE) - set(streams))
        raise ValueError(f"the log has no forecast of {', '.join(missing)}")
    series = {}
    for key, ds in streams.items():
        conv = _TO_SI[ds.unit]
        pts = sorted((o.measured_at, conv(float(o.result)))
                     for o in state.forecast(ds.id, start, end + HOUR)   # end included
                     if isinstance(o.result, (int, float)) and not isinstance(o.result, bool))
        if key == "cloud":
            pts = [(t, v / 100.0) for t, v in pts]
        if len(pts) < 2:
            raise ValueError(f"too little {LIVE[key]} between {start} and {end}")
        series[key] = pts
    return forecast_hours(series, lat=lat, lon=lon)


def tonight_from_log(state, dusk: _dt.datetime, *, lat: float, lon: float,
                     cover: str = "thermic", night_h: int = NIGHT_H) -> dict:
    """The covered-crop watch for the night beginning at `dusk`, from a forecast log."""
    hours = live_weather(state, dusk - SPINUP_H * HOUR, dusk + night_h * HOUR, lat=lat, lon=lon)
    past = [h for h in hours if h.when < dusk]
    return night(past, [h for h in hours if h.when >= dusk], dusk=dusk,
                 dawn=dusk + night_h * HOUR, cover=cover)


def main(argv=None) -> int:
    """Tonight's covered-crop watch, from the forecast log by hand or as a module process."""
    import argparse
    import json
    import rules as R

    ap = argparse.ArgumentParser(description="Covered-crop frost watch (Q28): tonight through the twin")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--log", help="a forecast log to read (never written)")
    src.add_argument("--socket", help="the module host's socket (§8.3); the decision is logged")
    ap.add_argument("--config", help="JSON with any of lat, lon, cover, warn_at, tunnel, language: "
                                     "how the evening timer runs it (deploy/systemd)")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--dusk", help="ISO 8601, UTC; default: the coming 00 UTC, about 6 pm in the central US")
    ap.add_argument("--cover", choices=sorted(T.COVERS))
    ap.add_argument("--warn-at", type=float, help="default: the film's, from the backtest")
    ap.add_argument("--tunnel", help="the tunnel's id, so the decision names it")
    ap.add_argument("--language")
    args = ap.parse_args(argv)
    config = {}
    if args.config:
        with open(args.config, encoding="utf-8") as h:
            config = json.load(h)
    # A flag given overrides the file; the file overrides the defaults.
    for name, default in (("lat", None), ("lon", None), ("cover", "thermic"), ("warn_at", None),
                          ("tunnel", None), ("language", "en")):
        if getattr(args, name) is None:
            setattr(args, name, config.get(name, default))
    if args.lat is None or args.lon is None:
        ap.error("the tunnel's place is needed: --lat and --lon, or lat and lon in --config")
    if args.cover not in T.COVERS:
        ap.error(f"cover is one of {sorted(T.COVERS)}")
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    dusk = (_dt.datetime.fromisoformat(args.dusk) if args.dusk
            else now.replace(hour=0, minute=0, second=0, microsecond=0) + _dt.timedelta(days=1))
    rule = covered_frost_watch(args.warn_at, cover=args.cover)
    if args.log:
        import log as L
        import project as P
        state, write = P.state_from_log(L.Log(args.log)), None
    else:
        import modhost as M
        client = M.ModuleClient(args.socket, M.token_from_environment())
        state, write = client.state(now, lookback=_dt.timedelta(days=3)), client.log()
    try:
        result = tonight_from_log(state, dusk, lat=args.lat, lon=args.lon, cover=args.cover)
    except (ValueError, RuntimeError) as exc:
        result = None
        print(f"no watch tonight: {exc}", file=sys.stderr)
    decision = judge(rule, result, now, {"dusk": dusk.isoformat(), "cover": args.cover})
    decision["valid_until"] = (dusk + NIGHT_H * HOUR).isoformat()     # tonight's, until dawn
    if args.tunnel:
        decision["subject"] = str(args.tunnel)
    if write is not None:
        write.append(R.DECISION, decision)
    print(json.dumps({"alert": decision["alert"], "context": decision["context"],
                      "message": R.render(decision, args.language)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
