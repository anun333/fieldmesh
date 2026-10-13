#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Is the soil warm enough to sow? — layer 2 (spec v0.1 §11).

Each morning, for each bed and each crop the farmer means to sow in it: the soil's
temperature at seed depth over the last three days, against the temperatures that crop's
seed germinates at, and about how many days the seedlings take to come up. A seed sown
into soil too cold for it rots or waits; too warm, it comes up thin.

**The temperatures are J. F. Harrington's** (University of California at Davis, 1954),
the table extension services still print: for each crop the soil temperature below which
the seed hardly germinates, the range it germinates best in, and the temperature above
which it hardly germinates; and the days to emergence at nine soil temperatures, from 0 to
40 °C, with the seed half an inch deep (`data/germination-harrington.csv`).

* **Days to emergence between Harrington's temperatures** are interpolated in germination
  *rate*, one over the days, which rises roughly in proportion to temperature above a
  base; days do not. Between a temperature where the seed hardly germinated and one where
  it did, there is no estimate.
* **His temperatures were held constant**; a field's soil is warm by day and cool by
  night. The advice reads the mean, so a day that swings either side of a limit reads as
  its middle. That is how extension advice reads a soil thermometer too.

**The probe is found, not configured**, as for the soil-moisture advisory: the soil
temperature series whose device is installed in the bed, at no more than 10 cm, the
shallowest there is. Only readings the health checks had passed by the morning count.

Read-only and advisory. Each advice is a CEL rule judged through layer 1 (`modules/rules`),
and one decision a crop a bed a morning is written: the morning's answer on its topic. The
crop is named in the reader's language when it is rendered (`Rule.key_params`).

    advisor = Advisor(log)
    advisor.advise(state, beds, at=morning)
"""
from __future__ import annotations

import csv
import datetime as _dt
import os
import sys
from dataclasses import dataclass, replace
from uuid import UUID

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
import i18n  # noqa: E402
import rules as R  # noqa: E402
import vocab as V  # noqa: E402
from model import DatastreamKind, Usable  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "sowing")

HOUR = _dt.timedelta(hours=1)
DATA = os.path.join(HERE, "data", "germination-harrington.csv")
#: Harrington's temperatures for days to emergence, °F; exactly 0, 5, … 40 °C.
EMERGENCE_F = (32, 41, 50, 59, 68, 77, 86, 95, 104)
NO_ESTIMATE = 1e6


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def _load(path: str = DATA) -> dict:
    """`{crop: {"min_c", "low_c", "high_c", "optimum_c", "max_c", "days"}}`, the days a
    list of `(°C, days)` for each temperature tested: days 0 where the seed hardly
    germinated, None where it was not tested."""
    out = {}
    with open(path, encoding="utf-8") as h:
        for row in csv.DictReader(h):
            days = []
            for f in EMERGENCE_F:
                cell = row[f"days_{f}f"]
                days.append((round(f_to_c(f), 6), float(cell) if cell else None))
            out[row["crop"]] = {
                "min_c": f_to_c(float(row["minimum_f"])),
                "low_c": f_to_c(float(row["optimum_low_f"])),
                "high_c": f_to_c(float(row["optimum_high_f"])),
                "optimum_c": f_to_c(float(row["optimum_f"])),
                "max_c": f_to_c(float(row["maximum_f"])),
                "days": days}
    return out


CROPS = _load()


def days_to_emergence(crop: str, soil_c: float) -> float | None:
    """About how many days a crop's seedlings take to come up at a soil temperature,
    interpolated in rate between Harrington's two nearest tested temperatures; None
    outside them, or next to one where the seed hardly germinated."""
    points = [(t, d) for t, d in CROPS[crop]["days"] if d is not None]
    for (t0, d0), (t1, d1) in zip(points, points[1:]):
        if t0 <= soil_c <= t1:
            if not d0 or not d1:
                return None
            rate = 1.0 / d0 + (1.0 / d1 - 1.0 / d0) * (soil_c - t0) / (t1 - t0)
            return 1.0 / rate
    return None


@dataclass(frozen=True)
class Seedbed:
    """A bed to be sown: its land (the feature its probes are installed in), the crops
    meant for it, by their names in `CROPS`, and how deep a soil temperature probe may sit
    and still speak for the seed."""

    feature: UUID
    crops: tuple = ()
    max_depth_m: float = 0.10
    stale_after_h: float = 6.0
    #: The readings the morning's mean is taken over, and the fewest hours of them it
    #: needs: a probe installed yesterday has not seen a night and a day.
    window_h: float = 72.0
    min_cover_h: float = 24.0

    def __post_init__(self) -> None:
        if not self.crops:
            raise ValueError("a seedbed names at least one crop to be sown")
        unknown = [c for c in self.crops if c not in CROPS]
        if unknown:
            raise ValueError(f"unknown crop(s) {unknown}; known: {', '.join(sorted(CROPS))}")
        if not 0 < self.max_depth_m <= 0.30:
            raise ValueError("a seed lies in the top few centimetres; max_depth_m is in metres")


def probe_of(state, bed: Seedbed, at: _dt.datetime):
    """`(datastream, depth_m)` for the shallowest soil temperature series installed in the
    bed at `at` within `max_depth_m`, or None."""
    found = []
    for ds in state.datastreams.values():
        if ds.kind is not DatastreamKind.DERIVED or ds.observed_property != V.SOIL_TEMPERATURE:
            continue
        inst = state.installation_of(ds.sensor, at)
        if inst is None or inst.feature != bed.feature or inst.depth_m is None:
            continue
        if inst.depth_m <= bed.max_depth_m:
            found.append((inst.depth_m, ds.id.int, ds))
    if not found:
        return None
    depth, _, ds = min(found, key=lambda x: (x[0], x[1]))
    return ds, depth


def _celsius(value: float, unit: str | None) -> float:
    return value - 273.15 if unit == "K" else value


def soil_context(state, bed: Seedbed, at: _dt.datetime):
    """What the advisory knew of the bed's seed-depth soil at `at`: `(context, inputs)`,
    shared by its crops."""
    ctx = {"has_probe": False, "has_reading": False, "usable": False, "flags": "",
           "hours_since_reading": NO_ESTIMATE, "covered_h": 0.0, "mean_c": 0.0,
           "low_c_seen": 0.0, "depth_cm": round(bed.max_depth_m * 100.0, 1)}
    inputs = {"bed": str(bed.feature), "datastream": None, "observations": 0}
    found = probe_of(state, bed, at)
    if found is None:
        return ctx, inputs
    ds, depth = found
    ctx.update({"has_probe": True, "depth_cm": round(depth * 100.0, 1)})
    inputs["datastream"] = str(ds.id)
    inst = state.installation_of(ds.sensor, at)
    since = at - _dt.timedelta(hours=bed.window_h)
    rows = sorted((o for o in state.live_observations_of(ds.id)
                   if o.received_at <= at and o.measured_at <= at
                   and o.measured_at >= inst.installed_at
                   and isinstance(o.result, (int, float)) and not isinstance(o.result, bool)),
                  key=lambda o: o.measured_at)
    if not rows:
        return ctx, inputs
    newest = rows[-1]
    ctx.update({"has_reading": True,
                "hours_since_reading": round((at - newest.measured_at) / HOUR, 2)})
    usable, flags = state.quality_as_of(newest.id, at)
    if usable is not Usable.GOOD:
        ctx["flags"] = ",".join(sorted(f.value for f in flags)) or "questionable"
        return ctx, inputs
    good = [o for o in rows if o.measured_at >= since
            and state.quality_as_of(o.id, at)[0] is Usable.GOOD]
    values = [_celsius(float(o.result), ds.unit) for o in good]
    ctx.update({"usable": True, "mean_c": round(sum(values) / len(values), 2),
                "low_c_seen": round(min(values), 2),
                "covered_h": round((good[-1].measured_at - good[0].measured_at) / HOUR, 1)})
    inputs["observations"] = len(good)
    return ctx, inputs


def crop_context(base: dict, crop: str) -> dict:
    """The bed's soil beside one crop's temperatures."""
    c = CROPS[crop]
    ctx = dict(base)
    ctx.update({"crop_key": f"sowing.crop.{crop}", "min_c": round(c["min_c"], 1),
                "low_c": round(c["low_c"], 1), "high_c": round(c["high_c"], 1),
                "max_c": round(c["max_c"], 1), "has_days": False, "days": 0.0})
    if base["usable"]:
        days = days_to_emergence(crop, base["mean_c"])
        if days is not None:
            ctx.update({"has_days": True, "days": round(days, 1)})
    return ctx


def rules_for(bed: Seedbed) -> list:
    """The advice for one crop, the first that holds is the morning's."""
    p = {"stale_after_h": bed.stale_after_h, "min_cover_h": bed.min_cover_h}
    soil = {"crop": "crop_key", "depth": "depth_cm", "mean": "mean_c", "min": "min_c",
            "lo": "low_c", "hi": "high_c", "max": "max_c", "days": "days",
            "hours": "hours_since_reading", "flags": "flags"}
    seen = "has_probe && has_reading && usable && covered_h >= min_cover_h"
    rules = [
        R.Rule("sowing-no-probe", "1", "!has_probe", p, alert_key="sowing.no_probe",
               message_params=soil),
        R.Rule("sowing-unseen", "1", "!has_reading || hours_since_reading > stale_after_h",
               p, alert_key="sowing.unseen", message_params=soil,
               message_variants=((f"hours_since_reading >= {NO_ESTIMATE!r}",
                                  "sowing.never_seen"),)),
        R.Rule("sowing-untrusted", "1", "!usable", p, alert_key="sowing.untrusted",
               message_params=soil),
        R.Rule("sowing-too-new", "1", "covered_h < min_cover_h", p, alert_key="sowing.too_new",
               message_params=soil),
        R.Rule("sowing-cold", "1", f"{seen} && mean_c < min_c", p, alert_key="sowing.cold",
               message_params=soil),
        R.Rule("sowing-hot", "1", f"{seen} && mean_c > max_c", p, alert_key="sowing.hot",
               message_params=soil),
        R.Rule("sowing-good", "1", f"{seen} && mean_c >= low_c && mean_c <= high_c", p,
               alert_key="sowing.good", message_params=soil,
               message_variants=(("has_days", "sowing.good_days"),)),
        R.Rule("sowing-cool", "1", f"{seen} && mean_c < low_c", p, alert_key="sowing.cool",
               message_params=soil, message_variants=(("has_days", "sowing.cool_days"),)),
        R.Rule("sowing-warm", "1", seen, p, alert_key="sowing.warm", message_params=soil,
               message_variants=(("has_days", "sowing.warm_days"),)),
    ]
    return [replace(r, subject_param="bed", key_params=("crop",)) for r in rules]


class Advisor:
    """Writes one decision a crop a bed each call: the morning's answer on whether to sow."""

    def __init__(self, log) -> None:
        self.log = log

    @staticmethod
    def judge(state, bed: Seedbed, at: _dt.datetime) -> list:
        """The decisions for one bed, one a crop, without writing them."""
        base, inputs = soil_context(state, bed, at)
        out = []
        for crop in bed.crops:
            context = crop_context(base, crop)
            for rule in rules_for(bed):
                d = R.judge(rule, context, {**inputs, "crop": crop}, at)
                if d["alert"]:
                    d["subject"] = str(bed.feature)
                    d["topic"] = f"sowing/{bed.feature}/{crop}"
                    d["valid_until"] = (at + _dt.timedelta(days=1)).isoformat()
                    out.append(d)
                    break
            else:                                                  # pragma: no cover
                raise AssertionError("the last rule holds whenever the soil is seen")
        return out

    def advise(self, state, beds, at: _dt.datetime) -> list:
        """The morning's decisions for every bed and crop, written to the log."""
        return [self.log.append(R.DECISION, d) for bed in beds for d in self.judge(state, bed, at)]


def render(decision: dict, language: str = "en", state=None) -> str | None:
    """A decision's message in `language`: the bed by its label, the crop by its name."""
    return R.render(decision, language, state)


def main(argv=None) -> int:
    """The advisory as its own process (§8.3; Q11), over the host's socket."""
    import argparse
    import json
    import modhost as M

    ap = argparse.ArgumentParser(description="Sowing advisory, as a module process")
    ap.add_argument("--socket", required=True)
    ap.add_argument("--config", required=True,
                    help="JSON: {\"beds\": [{\"feature\": id, \"crops\": [\"bean\", \"carrot\"]}]}")
    ap.add_argument("--at", help="advise for this moment (ISO 8601); default now")
    ap.add_argument("--language", default="en")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as h:
        config = json.load(h)
    beds = [Seedbed(**{**b, "feature": UUID(b["feature"]), "crops": tuple(b["crops"])})
            for b in config["beds"]]
    at = (_dt.datetime.fromisoformat(args.at) if args.at
          else _dt.datetime.now(tz=_dt.timezone.utc))
    with M.ModuleClient(args.socket, M.token_from_environment()) as client:
        state = client.state(at)
        for event in Advisor(client.log()).advise(state, beds, at):
            print(json.dumps({"rule": event.payload["rule"],
                              "message": render(event.payload, args.language, state)},
                             ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
