#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Salt building up in a bed's soil — layer 2 (spec v0.1 §11).

Under a tunnel no soaking rain washes salts below the roots, while fertilizer, compost and
hard water keep adding them, so salt builds up season after season. A soil test sees it a
few times a year; a probe that reports electrical conductivity sees it climb between them.
This sets a bed's salt beside its crop's tolerance and says when it is climbing toward it
and when it is past it, with the share of the yield lost.

**From the probe's reading to the crop's scale**, as METER's TEROS 11/12 manual gives it:

* A probe reports the **bulk** soil's conductivity, which rises with the water in the soil
  and its temperature as well as with salt. The **pore water's** is Hilhorst's (2000)
  `σp = εp·σb / (εb − 4.1)`, with the pore water's permittivity `εp = 80.3 − 0.37 (T − 20)`
  and the bulk soil's `εb`. Not below 0.10 water content, where the denominator is small;
  about ±20% in moist soil.
* `εb` is the probe's own measurement, which it does not send on; it is recovered from the
  water content it does send, by Topp, Davis and Annan's (1980) curve, the one most probes'
  water content was calibrated by. That is an approximation on top of Hilhorst's.
* Crop tolerances are in the conductivity of a **saturated paste's extract**, ECe. The
  pore water diluted to saturation is `σp · θ / φ`, the porosity `φ = 1 − ρb / 2.65` from
  the bed's bulk density.

**The tolerances are Maas and Grattan's (1999)**, as FAO Irrigation and Drainage Paper 61
(2002, Annex 1) prints them: for each crop the ECe up to which its yield does not fall, and
the share lost per dS/m beyond it (`data/salt-tolerance-maas-grattan.csv`).

The bed's salt is the median of the last week's hours whose three readings (water,
conductivity, temperature, from one probe's body) the checks passed. Read-only and
advisory; a decision is written when an alert is raised or cleared, as the zone flow
check writes them, and the crop is named in the reader's language.

    monitor = Monitor(log)
    monitor.check(state, beds, at=now)
"""
from __future__ import annotations

import csv
import datetime as _dt
import os
import statistics
import sys
from dataclasses import dataclass
from uuid import UUID

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
import i18n  # noqa: E402
import rules as R  # noqa: E402
import vocab as V  # noqa: E402
from model import DatastreamKind, Usable  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "salinity")

HOUR = _dt.timedelta(hours=1)
DATA = os.path.join(HERE, "data", "salt-tolerance-maas-grattan.csv")
#: Hilhorst's (2000) generic offset: the dry soil's permittivity, near enough.
DRY_PERMITTIVITY = 4.1
#: Below this water content the pore water's conductivity is not computed (METER).
MIN_WATER = 0.10
PARTICLE_DENSITY = 2.65
#: The bulk conductivity's units, to dS/m.
TO_DS_M = {"dS/m": 1.0, "mS/cm": 1.0, "uS/cm": 0.001, "S/m": 10.0}


def _load(path: str = DATA) -> dict:
    with open(path, encoding="utf-8") as h:
        return {r["crop"]: {"threshold": float(r["threshold_ds_m"]),
                            "slope": float(r["slope_percent_per_ds_m"]),
                            "rating": r["rating"]} for r in csv.DictReader(h)}


CROPS = _load()


def topp_water(permittivity: float) -> float:
    """Topp, Davis and Annan (1980): water content from the bulk soil's permittivity."""
    e = permittivity
    return -5.3e-2 + 2.92e-2 * e - 5.5e-4 * e ** 2 + 4.3e-6 * e ** 3


def topp_permittivity(theta: float) -> float:
    """The permittivity Topp's curve gives a water content, by bisection (the curve rises
    throughout 1 to 80)."""
    lo, hi = 1.0, 80.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if topp_water(mid) < theta:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def pore_water_ec(bulk_ds_m: float, theta: float, soil_c: float) -> float | None:
    """The pore water's conductivity, dS/m (Hilhorst 2000), or None below `MIN_WATER`."""
    if theta < MIN_WATER:
        return None
    bulk_permittivity = topp_permittivity(theta)
    if bulk_permittivity <= DRY_PERMITTIVITY:
        return None
    water_permittivity = 80.3 - 0.37 * (soil_c - 20.0)
    return water_permittivity * bulk_ds_m / (bulk_permittivity - DRY_PERMITTIVITY)


def saturation_extract_ec(pore_ds_m: float, theta: float, bulk_density: float) -> float:
    """The pore water diluted to saturation with pure water, dS/m: the scale crop
    tolerances are in (METER's TEROS 11/12 manual, equations 4 and 5)."""
    porosity = 1.0 - bulk_density / PARTICLE_DENSITY
    return pore_ds_m * theta / porosity


@dataclass(frozen=True)
class SaltBed:
    """A bed whose salt is watched: its land (where the probe is installed), the crop
    growing in it, its soil's bulk density (Mg/m3; a loam's 1.4 if not measured), the
    share of the crop's threshold at which a rise is said, and the days its salt is the
    median of."""

    feature: UUID
    crop: str
    bulk_density: float = 1.4
    rising_share: float = 0.8
    window_days: float = 7.0

    def __post_init__(self) -> None:
        if self.crop not in CROPS:
            raise ValueError(f"unknown crop {self.crop!r}; known: {', '.join(sorted(CROPS))}")
        if not 0.8 <= self.bulk_density <= 2.0:
            raise ValueError("a mineral soil's bulk density is about 1 to 1.8 Mg/m3")
        if not 0 < self.rising_share < 1:
            raise ValueError("the rising share is a share of the threshold, between 0 and 1")


def probe_of(state, bed: SaltBed, at: _dt.datetime):
    """`{"water", "conductivity", "temperature"}` datastreams from one probe's body
    installed in the bed at `at`, the shallowest with all three; or None."""
    by_sensor = {}
    for ds in state.datastreams.values():
        if ds.kind is not DatastreamKind.DERIVED:
            continue
        role = {V.SOIL_WATER: "water", V.BULK_EC: "conductivity",
                V.SOIL_TEMPERATURE: "temperature"}.get(ds.observed_property)
        if role is None:
            continue
        inst = state.installation_of(ds.sensor, at)
        if inst is None or inst.feature != bed.feature or inst.depth_m is None:
            continue
        by_sensor.setdefault((inst.depth_m, ds.sensor.int), {})[role] = ds
    whole = [(k, v) for k, v in by_sensor.items() if len(v) == 3]
    return min(whole, key=lambda kv: kv[0])[1] if whole else None


def salt_context(state, bed: SaltBed, at: _dt.datetime):
    """What the monitor knew of the bed's salt at `at`: `(context, inputs)`."""
    crop = CROPS[bed.crop]
    ctx = {"has_probe": False, "hours": 0.0, "ece": 0.0, "threshold": crop["threshold"],
           "slope": crop["slope"], "share_percent": 0.0, "loss_percent": 0.0,
           "rising_share_percent": round(100.0 * bed.rising_share, 1),
           "crop_key": f"salinity.crop.{bed.crop}"}
    inputs = {"bed": str(bed.feature), "crop": bed.crop, "datastreams": None}
    found = probe_of(state, bed, at)
    if found is None:
        return ctx, inputs
    ctx["has_probe"] = True
    inputs["datastreams"] = {k: str(v.id) for k, v in found.items()}
    since = at - _dt.timedelta(days=bed.window_days)
    hourly = {}
    for role, ds in found.items():
        scale = TO_DS_M.get(ds.unit, None) if role == "conductivity" else 1.0
        if scale is None:
            return ctx, inputs
        for o in state.live_observations_of(ds.id):
            if not (since <= o.measured_at <= at and o.received_at <= at):
                continue
            if not isinstance(o.result, (int, float)) or isinstance(o.result, bool):
                continue
            if state.quality_as_of(o.id, at)[0] is not Usable.GOOD:
                continue
            hour = o.measured_at.replace(minute=0, second=0, microsecond=0)
            hourly.setdefault(hour, {})[role] = float(o.result) * scale
    values = []
    for reading in hourly.values():
        if len(reading) < 3:
            continue
        pore = pore_water_ec(reading["conductivity"], reading["water"], reading["temperature"])
        if pore is not None:
            values.append(saturation_extract_ec(pore, reading["water"], bed.bulk_density))
    if not values:
        return ctx, inputs
    ece = statistics.median(values)
    ctx.update({"hours": float(len(values)), "ece": round(ece, 2),
                "share_percent": round(100.0 * ece / crop["threshold"], 0),
                "loss_percent": round(min(100.0, max(0.0, crop["slope"] * (ece - crop["threshold"]))), 0)})
    return ctx, inputs


#: The fewest hours of whole readings in the window before anything is said.
MIN_HOURS = 24.0


def rules_for(bed: SaltBed) -> list:
    p = {"min_hours": MIN_HOURS, "rising_share": bed.rising_share}
    params = {"crop": "crop_key", "ece": "ece", "threshold": "threshold",
              "loss": "loss_percent", "share": "share_percent"}
    seen = "has_probe && hours >= min_hours"
    rules = [
        R.Rule("salt-over", "1", f"{seen} && ece > threshold", p,
               alert_key="salinity.over", message_params=params),
        R.Rule("salt-rising", "1",
               f"{seen} && ece >= rising_share * threshold && ece <= threshold", p,
               alert_key="salinity.rising", message_params=params),
    ]
    return [R.Rule(r.id, r.version, r.condition, r.params, alert_key=r.alert_key,
                   message_params=r.message_params, subject_param="bed",
                   key_params=("crop",)) for r in rules]


class Monitor:
    """Judges beds and writes a decision only where an alert changed: raised, or cleared.
    Which alerts stand is read back from the log when it starts."""

    def __init__(self, log) -> None:
        self.log = log
        self._standing: dict[tuple, object] = {}
        for event in log.events:
            self._learn(event)

    def _learn(self, event) -> None:
        p = event.payload
        if event.kind == R.DECISION and p.get("subject") and str(p.get("rule", "")).startswith("salt-"):
            key = (p["rule"], p["subject"])
            if p.get("alert"):
                self._standing[key] = event
            else:
                self._standing.pop(key, None)

    def check(self, state, beds, at: _dt.datetime) -> list:
        written = []
        for bed in beds:
            context, inputs = salt_context(state, bed, at)
            subject = str(bed.feature)
            for rule in rules_for(bed):
                d = R.judge(rule, context, inputs, at)
                if d["alert"] == ((rule.id, subject) in self._standing):
                    continue
                d["subject"] = subject
                d["topic"] = f"{rule.id}/{subject}"
                event = self.log.append(R.DECISION, d)
                self._learn(event)
                written.append(event)
        return written

    def standing(self) -> list:
        return sorted(self._standing.values(), key=lambda e: (e.stamp, e.id.int))


def render(decision: dict, language: str = "en", state=None, units: str | None = None) -> str | None:
    return R.render(decision, language, state, units)


def main(argv=None) -> int:
    """The monitor as its own process (§8.3; Q11), over the host's socket."""
    import argparse
    import json
    import time
    import modhost as M

    ap = argparse.ArgumentParser(description="Soil salinity monitor, as a module process")
    ap.add_argument("--socket", required=True)
    ap.add_argument("--config", required=True,
                    help="JSON: {\"beds\": [{\"feature\": id, \"crop\": \"tomato\", \"bulk_density\": 1.3}]}")
    ap.add_argument("--at", help="judge this one moment (ISO 8601) and exit")
    ap.add_argument("--every", type=float, default=86400.0, help="seconds between looks")
    ap.add_argument("--language", default="en")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as h:
        config = json.load(h)
    beds = [SaltBed(**{**b, "feature": UUID(b["feature"])}) for b in config["beds"]]
    with M.ModuleClient(args.socket, M.token_from_environment()) as client:
        monitor = Monitor(client.log())
        while True:
            at = (_dt.datetime.fromisoformat(args.at) if args.at
                  else _dt.datetime.now(tz=_dt.timezone.utc))
            state = client.state(at)
            for event in monitor.check(state, beds, at):
                print(json.dumps({"rule": event.payload["rule"], "alert": event.payload["alert"],
                                  "message": render(event.payload, args.language, state)},
                                 ensure_ascii=False), flush=True)
            if args.at:
                return 0
            time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
