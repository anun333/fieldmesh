#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Livestock water monitor — layer 2 (spec v0.1 §11, §15; open-questions Q12).

A dry trough on a hot afternoon is an emergency, and the reason Q12 put this module
first: it is read-only, so it ships without commands and carries no liability, and it
leans on exactly the parts of layer zero most likely to be wrong — store-and-forward,
backlog order, quality assertions. It watches each trough's level and says, in the
farmer's language, one of five things:

* **empty** — below a tenth of capacity, where stock cannot drink (§4.2);
* **empty, unconfirmed** — the same, from a reading the health checks flagged only as
  out of range on the low side. A dry trough and a failed sensor both need someone to
  go and look, so this is never dropped as a sensor problem;
* **low** — below the farm's low mark;
* **not refilling** — below the float's setpoint for longer than a working float allows,
  which is the float stuck shut or the supply off, with the hours left at the rate the
  stock are drinking;
* **unseen** — no reading for longer than this trough's data is allowed to be late. No
  news from an urgent series is not good news;
* and **untrusted** when the newest reading carries any other flag.

Each is a CEL rule (Q10) judged through layer 1 (`modules/rules`), so a decision carries
its inputs, the condition as written, its version and the trust level. Everything runs
as *advisory*. A decision is written to the log (§7.7) only when an alert is raised or
cleared, not on every look, and a person acknowledges a raised alert in the log too.

**It judges what the gateway knew at the time, not what arrived later.** Readings count
only once received, and quality only once asserted. That is what makes a backtest over a
season honest, and what lets §15's acceptance clause be tested at all: after an outage,
the monitor must see the trough as it is *now*, which is what a node draining its
backlog newest-first (`drain_order: fresh_first`, §5.3) delivers.

    monitor = Monitor(log)
    monitor.check(state, troughs, at=now)    # writes raised and cleared decisions
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
from model import QualityFlag, Usable  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "water")

HOUR = _dt.timedelta(hours=1)
ACKNOWLEDGEMENT = "acknowledgement"     # the log event kind for a person's "seen it"
#: How far under the setpoint counts as under it, so a float holding a hair low or a
#: noisy reading does not start the clock.
SETPOINT_MARGIN = 0.03
#: The window the drinking rate is measured over.
RATE_WINDOW_H = 2.0
#: Hours standing for "no estimate": never heard from, or not falling.
NO_ESTIMATE = 1e6


@dataclass(frozen=True)
class Trough:
    """One trough the monitor watches: its calibrated level series, a fraction of
    capacity (the `vessel_fill_fraction` term), and the farm's marks for it."""

    datastream: UUID
    capacity_l: float
    empty_at: float = 0.10          # §4.2: below a tenth, stock cannot drink
    low_at: float = 0.30
    float_setpoint: float | None = 0.92   # None for a trough filled by hand
    #: How long under the float's mark before "not refilling". A working float refills
    #: far faster than stock drink — on Harrow Bend's healthy trough the level did not
    #: sit under the mark for a single five-minute reading in ten days — so an hour is
    #: twelve readings of margin, and the warning still comes hours before dry.
    refill_hold_h: float = 1.0
    #: Twice the five-minute latency an urgent series is held to, and then some.
    stale_after_h: float = 0.5

    def __post_init__(self) -> None:
        if self.capacity_l <= 0:
            raise ValueError("a trough holds something")
        if not 0 <= self.empty_at < self.low_at <= 1:
            raise ValueError("0 <= empty_at < low_at <= 1")
        if self.float_setpoint is not None and not self.low_at < self.float_setpoint <= 1:
            raise ValueError("a float holds the level above the low mark")
        if self.refill_hold_h <= 0 or self.stale_after_h <= 0:
            raise ValueError("hold and staleness are positive hours")


def rules_for(trough: Trough) -> list:
    """The six rules, versioned, with this trough's marks as their parameters."""
    p = {"empty_at": trough.empty_at, "low_at": trough.low_at,
         "refill_hold_h": trough.refill_hold_h, "stale_after_h": trough.stale_after_h}
    fresh = "has_reading && hours_since_reading <= stale_after_h"
    return [
        R.Rule("water-unseen", "1",
               "!has_reading || hours_since_reading > stale_after_h", p,
               alert_key="water.unseen", message_params={"hours": "hours_since_reading"}),
        R.Rule("water-untrusted", "1", f"{fresh} && !usable && !low_side_range", p,
               alert_key="water.untrusted", message_params={}),
        R.Rule("water-empty", "1", f"{fresh} && usable && level < empty_at", p,
               alert_key="water.empty", message_params={"percent": "level_percent"}),
        R.Rule("water-empty-unconfirmed", "1", f"{fresh} && low_side_range", p,
               alert_key="water.empty_unconfirmed",
               message_params={"percent": "level_percent"}),
        R.Rule("water-low", "1",
               f"{fresh} && usable && level >= empty_at && level < low_at", p,
               alert_key="water.low", message_params={"percent": "level_percent"}),
        R.Rule("water-not-refilling", "1",
               f"{fresh} && (usable || low_side_range) && below_setpoint_h >= refill_hold_h",
               p, alert_key="water.not_refilling",
               message_params={"hours": "below_setpoint_h", "rate": "fall_l_per_h",
                               "left": "hours_to_empty"}),
    ]


# ----------------------------------------------------------------- context

def _slope_per_h(points) -> float:
    """Least-squares slope of (hours, level) points."""
    n = len(points)
    if n < 2:
        return 0.0
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in points) / sxx


def trough_context(state, trough: Trough, at: _dt.datetime) -> tuple[dict, dict]:
    """What the monitor knew about a trough at `at`: `(context, inputs)`.

    The newest reading is the newest *measured*, among those received by `at` — not
    the last to arrive, which after an outage may be hours old.
    """
    rows = [o for o in state.live_observations_of(trough.datastream)
            if o.received_at <= at and o.measured_at <= at
            and isinstance(o.result, (int, float)) and not isinstance(o.result, bool)]
    inputs = {"datastream": str(trough.datastream), "observations": []}
    if not rows:
        return ({"has_reading": False, "usable": False, "low_side_range": False,
                 "level": 0.0, "level_percent": 0.0, "hours_since_reading": NO_ESTIMATE,
                 "below_setpoint_h": 0.0, "fall_l_per_h": 0.0,
                 "hours_to_empty": NO_ESTIMATE},
                inputs)
    rows.sort(key=lambda o: o.measured_at)
    latest = rows[-1]
    usable, flags = state.quality_as_of(latest.id, at)
    level = float(latest.result)
    low_side_range = (usable is not Usable.GOOD and flags == {QualityFlag.OUT_OF_RANGE}
                      and level < trough.empty_at)

    def counts(o):
        u, f = state.quality_as_of(o.id, at)
        return u is Usable.GOOD or (f == {QualityFlag.OUT_OF_RANGE}
                                    and o.result < trough.empty_at)

    below_h = 0.0
    start = None
    if trough.float_setpoint is not None:
        mark = trough.float_setpoint - SETPOINT_MARGIN
        for o in reversed(rows):
            if not counts(o):
                continue
            if o.result < mark:
                start = o.measured_at
            else:
                break
        if start is not None:
            below_h = (latest.measured_at - start) / HOUR

    # The rate the stock are drinking it down at, over the last two hours — or, once
    # the level is under the float's mark, over that stretch only, since the flat
    # level before it is the float working, not the stock drinking less.
    since = latest.measured_at - RATE_WINDOW_H * HOUR
    if start is not None and start > since:
        since = start
    window = [o for o in rows if o.measured_at >= since and counts(o)]
    slope = _slope_per_h([((o.measured_at - since) / HOUR, float(o.result)) for o in window])
    fall_l_per_h = max(0.0, -slope * trough.capacity_l)

    left_l = max(0.0, (level - trough.empty_at) * trough.capacity_l)
    hours_to_empty = left_l / fall_l_per_h if fall_l_per_h > 0.5 else NO_ESTIMATE
    inputs["observations"] = [str(o.id) for o in window] or [str(latest.id)]
    return ({"has_reading": True, "usable": usable is Usable.GOOD,
             "low_side_range": low_side_range, "flags": ",".join(sorted(f.value for f in flags)),
             "level": level, "level_percent": round(level * 100.0, 1),
             "latest_at": latest.measured_at.isoformat(),
             "hours_since_reading": (at - latest.measured_at) / HOUR,
             "below_setpoint_h": round(below_h, 2),
             "fall_l_per_h": round(fall_l_per_h, 1),
             "hours_to_empty": round(hours_to_empty, 1)}, inputs)


# ----------------------------------------------------------------- monitor

class Monitor:
    """Judges troughs and writes a decision only where an alert changed.

    Its memory of which alerts stand is read from the log when it starts, so a monitor
    that restarts carries on where the log says it was, rather than raising every
    standing alert again or, worse, forgetting one.
    """

    def __init__(self, log) -> None:
        self.log = log
        self._standing: dict[tuple, object] = {}       # (rule, trough) -> event
        self._acks: dict[str, dict] = {}
        for event in log.events:
            self._learn(event)

    def _learn(self, event) -> None:
        if event.kind == R.DECISION and event.payload.get("subject"):
            key = (event.payload["rule"], event.payload["subject"])
            if event.payload.get("alert"):
                self._standing[key] = event
            else:
                self._standing.pop(key, None)
        elif event.kind == ACKNOWLEDGEMENT:
            self._acks[event.payload["decision"]] = event.payload

    def check(self, state, troughs, at: _dt.datetime) -> list:
        """Judge every trough at `at`; return the decision events written."""
        written = []
        for trough in troughs:
            context, inputs = trough_context(state, trough, at)
            subject = str(trough.datastream)
            for rule in rules_for(trough):
                d = R.judge(rule, context, inputs, at)
                if d["alert"] == ((rule.id, subject) in self._standing):
                    continue
                d["subject"] = subject
                event = self.log.append(R.DECISION, d)
                self._learn(event)
                written.append(event)
        return written

    def standing(self) -> list:
        """Raised and not yet cleared, oldest first."""
        return sorted(self._standing.values(), key=lambda e: (e.stamp, e.id.int))

    def unacknowledged(self) -> list:
        return [e for e in self.standing() if str(e.id) not in self._acks]

    def acknowledge(self, decision_event, *, by: UUID, at: _dt.datetime, note: str | None = None):
        """A person has seen an alert. It stays raised until the trough says otherwise;
        acknowledging is not clearing."""
        if decision_event.kind != R.DECISION or not decision_event.payload.get("alert"):
            raise ValueError("only a raised alert is acknowledged")
        payload = {"decision": str(decision_event.id), "by": str(by), "at": at.isoformat()}
        if note:
            payload["note"] = note
        event = self.log.append(ACKNOWLEDGEMENT, payload)
        self._learn(event)
        return event


def render(decision: dict, language: str = "en", state=None) -> str | None:
    """A decision's message in `language`, naming the trough by its label there."""
    if not decision.get("message"):
        return None
    m = decision["message"]
    name = None
    if state is not None and decision.get("subject"):
        label = state.label_for(UUID(decision["subject"]), language)
        name = label.name if label is not None else None
    params = {**m["params"], "trough": name or decision.get("subject", "?")}
    key = m["key"]
    # The decision is one per rule; the sentence can still fit the case. A trough the
    # stock are not drinking from has no "hours left", and one never heard from has no
    # "hours since".
    if key == "water.not_refilling" and params.get("left", 0) >= NO_ESTIMATE:
        key = "water.not_refilling_idle"
    elif key == "water.unseen" and params.get("hours", 0) >= NO_ESTIMATE:
        key = "water.never_seen"
    return str(i18n.Translator(language).text(key, **params))
