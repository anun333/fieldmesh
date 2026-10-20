# SPDX-License-Identifier: AGPL-3.0-or-later
"""Probe watch (layer 2): each soil probe against what the probes beside it, the rain and
the air say it should read. An optional add-on: it runs Timestral (`sdk/tsfm.py`), whose
package and weights are not fieldmesh's, and whose weights' licence a farm must accept.

Each look, for each bed with two or more probes reading: each probe's last `WINDOW_H`
hours are forecast from its own 1,024 hours before them, with the bed's other probes and
the station's rain and air through those hours. A probe whose readings lie outside the
forecast's 1-99% band for `RUN_H` hours running is off, and a decision says so: wetter or
drier, for how many of the hours, and by how much, with the receipt of the forecast it
rests on (`tsfm.run`): the model and weights, the series and hours, a hash of the inputs,
and how far each input moved it. A decision is written when a probe goes off and when it
comes back. With two probes in a bed, each is the other's only neighbour, and both may be
said to be off; a third tells which.

What it was tried on (docs/notes/timestral.md): on ISMN's records of Tennessee SCAN
stations, a drift put into a 10 cm probe was seen in 9 hours, where the reading against a
regression on its neighbours took 35, with 6% false alarms over clean days to the
regression's 14%; a sudden step in 2 hours, as both did; a stuck probe, in 73%, where
layer zero's flatline check sees all of them. Spikes of an hour it does not see, and on
the jumps ISMN's own quality control flagged it did worse than the regression.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from dataclasses import dataclass
from uuid import UUID

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
import i18n  # noqa: E402
import rules as R  # noqa: E402
import tsfm as TS  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "probewatch")

HOUR = _dt.timedelta(hours=1)
#: The hours each look judges, and how many running outside the band make a probe off.
WINDOW_H = 24
RUN_H = 3
#: The band: the forecast's 1% and 99% quantiles.
BAND = (0.01, 0.99)
#: A probe counts as reading when it gave a good reading within this many hours.
READING_H = 6


@dataclass(frozen=True)
class WatchBed:
    """A bed to watch, and the station's rain and air temperature series, if any."""
    feature: UUID
    rain: UUID | None = None
    air: UUID | None = None


def probe_context(model, state, bed: WatchBed, probe, depth_m: float, others: list,
                  at: _dt.datetime, *, ablate: bool = True) -> tuple:
    """`(context, inputs)` for one probe: its last `WINDOW_H` hours against the band.
    Without `ablate` the receipt does not say how far each input moved the forecast, and
    the model runs once, not once and again for each input."""
    end = at.replace(minute=0, second=0, microsecond=0)
    start = end - WINDOW_H * HOUR
    covariates = {f"probe at {round(d * 100)} cm": p.id for p, d in others}
    covariates.update({name: ds for name, ds in (("rain", bed.rain), ("air", bed.air)) if ds})
    forecast, receipt = TS.run(model, state, probe.id, covariates, start, WINDOW_H, at,
                               ablate=ablate)
    readings = TS.hourly(state, probe.id, start, WINDOW_H, at)
    lo, hi, mid = forecast.at(BAND[0]), forecast.at(BAND[1]), forecast.median
    outside = [r is not None and not a <= r <= b for r, a, b in zip(readings, lo, hi)]
    longest = run = 0
    for o in outside:
        run = run + 1 if o else 0
        longest = max(longest, run)
    off = [r - m for r, m, o in zip(readings, mid, outside) if o]
    departure = sum(off) / len(off) if off else 0.0
    context = {"off": longest >= RUN_H, "longest_run_h": longest, "hours_outside": sum(outside),
               "readings": sum(1 for r in readings if r is not None),
               "depth_cm": round(depth_m * 100), "wetter": departure > 0,
               "departure_points": round(abs(departure) * 100.0, 1),
               "band_points": round(sum(b - a for a, b in zip(lo, hi)) / WINDOW_H * 100.0, 1)}
    return context, {"probe": str(probe.id), "receipt": receipt}


def rule() -> R.Rule:
    return R.Rule("soil-probe-off", "1", "off", {}, alert_key="probewatch.probe_drier",
                  message_params={"depth": "depth_cm", "hours": "hours_outside",
                                  "points": "departure_points"},
                  message_variants=(("wetter", "probewatch.probe_wetter"),),
                  subject_param="bed", unit_params={"depth": "cm"})


class Watch:
    """Judges each probe and writes a decision only where it changed: off, or back. Which
    probes are off is read back from the log when it starts."""

    def __init__(self, log, model) -> None:
        self.log, self.model = log, model
        self._standing: dict = {}
        for event in log.events:
            self._learn(event)

    def _learn(self, event) -> None:
        p = event.payload
        if event.kind == R.DECISION and p.get("rule") == "soil-probe-off" and p.get("subject"):
            key = (p["subject"], p.get("context", {}).get("depth_cm"))
            if p.get("alert"):
                self._standing[key] = event
            else:
                self._standing.pop(key, None)

    def check(self, state, beds, at: _dt.datetime) -> list:
        written = []
        for bed in beds:
            probes = TS.soil_probes(state, bed.feature, at)
            reading = [(p, d) for p, d in probes if TS.last_good(state, p.id, at, READING_H)]
            for probe, depth in reading:
                others = [(p, d) for p, d in reading if p.id != probe.id]
                if not others:
                    continue
                context, inputs = probe_context(self.model, state, bed, probe, depth, others, at)
                if context["readings"] < RUN_H:
                    continue
                d = R.judge(rule(), context, inputs, at)
                key = (str(bed.feature), context["depth_cm"])
                if d["alert"] == (key in self._standing):
                    continue
                d["subject"] = str(bed.feature)
                d["topic"] = f"probewatch/{bed.feature}/{context['depth_cm']}"
                event = self.log.append(R.DECISION, d)
                self._learn(event)
                written.append(event)
        return written


def render(decision: dict, language: str = "en", state=None, units: str | None = None) -> str | None:
    return R.render(decision, language, state, units)


def main(argv=None) -> int:
    """The watch as its own process (§8.3; Q11), over the host's socket."""
    import argparse
    import json
    import time
    import modhost as M

    ap = argparse.ArgumentParser(description="Probe watch, as a module process (optional add-on)")
    ap.add_argument("--socket", required=True)
    ap.add_argument("--config", required=True,
                    help='JSON: {"accept_weights_licence": true, "beds": [{"feature": id, '
                         '"rain": id, "air": id}], "model": ..., "revision": ..., "offline": true}')
    ap.add_argument("--at", help="judge this one moment (ISO 8601) and exit")
    ap.add_argument("--every", type=float, default=3600.0, help="seconds between looks")
    ap.add_argument("--language", default="en")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as h:
        config = json.load(h)
    try:
        model = TS.load(config.get("model", TS.DEFAULT_MODEL),
                        accept_weights_licence=bool(config.get("accept_weights_licence")),
                        revision=config.get("revision"), offline=bool(config.get("offline")))
    except TS.LicenceNotAccepted as e:
        print(e, file=sys.stderr)
        return 2
    beds = [WatchBed(UUID(b["feature"]), *(UUID(b[k]) if b.get(k) else None for k in ("rain", "air")))
            for b in config["beds"]]
    with M.ModuleClient(args.socket, M.token_from_environment()) as client:
        watch = Watch(client.log(), model)
        while True:
            at = (_dt.datetime.fromisoformat(args.at) if args.at
                  else _dt.datetime.now(tz=_dt.timezone.utc))
            # The model reads 1,024 hours of each series before the day it judges.
            state = client.state(at, lookback=(TS.CONTEXT_H + WINDOW_H + 24) * HOUR)
            for event in watch.check(state, beds, at):
                print(json.dumps({"rule": event.payload["rule"], "alert": event.payload["alert"],
                                  "message": render(event.payload, args.language, state)},
                                 ensure_ascii=False), flush=True)
            if args.at:
                return 0
            time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
