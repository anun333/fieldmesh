#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rules and alerts — layer 1 (spec v0.1 §11), starting with a frost watch.

A rule is a **CEL condition** (Q10, decided 2026-10-09) over a small context the rule
builds from the log, plus a version and a trust level. Evaluating it writes a **decision
event** (§7.7): the observations it read, the rule and its version, the condition as
written, what it concluded and the trust level it ran under — so "why did it warn on the
12th?" is answered from the log alone. CEL refuses I/O, so a condition cannot reach past
the context it was given; that is what makes the event's claim about its inputs true.

Every rule here runs as **advisory**: it says, it never acts. §11 asks that a rule be
backtested on past seasons before it goes live, so `backtest` replays one over a log that
holds both the forecast it would have read and the station that says what happened.

    rule = frost_watch(warn_at_c=0.0)
    decision = evaluate(rule, state, forecast_id, at=dusk)   # -> dict, and log it
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
import i18n  # noqa: E402

i18n.register(os.path.join(HERE, "packs"), "rules")
UTC = _dt.timezone.utc
HOUR = _dt.timedelta(hours=1)
DECISION = "decision"          # the log event kind (§7.7)


@dataclass(frozen=True)
class Rule:
    id: str
    version: str
    condition: str             # CEL, over the context's names and `params`
    params: dict = field(default_factory=dict)
    trust: str = "advisory"    # §11's trust ramp: advisory, approval, autonomous
    alert_key: str = ""        # the message a true condition raises, for any language
    #: The message's parameters, each named for a value in the context or `params`.
    message_params: dict = field(default_factory=dict)


def frost_watch(warn_at_c: float = 0.0, *, window_h: tuple = (2.0, 16.0)) -> Rule:
    """At dusk: will tonight's forecast low reach `warn_at_c`? 0 °C is McAllister Farm's
    threshold on evidence — on NOAA's forecasts for 2025-26 it warned of all 38 frost
    nights with six false alerts (docs/notes/forecasts.md)."""
    return Rule(id="frost-watch", version="1",
                condition="has_forecast && night_low_c <= warn_at_c",
                params={"warn_at_c": warn_at_c, "window_start_h": window_h[0],
                        "window_end_h": window_h[1]},
                alert_key="rules.frost.alert",
                message_params={"low": "night_low_c", "warn": "warn_at_c"})


def frost_context(state, forecast_id, at: _dt.datetime, params: dict) -> tuple[dict, list]:
    """The live forecast's low over the night ahead, from the issue standing at `at`:
    `(context, ids of the observations read)`."""
    start = at + _dt.timedelta(hours=params["window_start_h"])
    end = at + _dt.timedelta(hours=params["window_end_h"])
    standing = [o for o in state.observations_of(forecast_id)
                if o.issued_at is not None and o.issued_at <= at]
    if not standing:
        return {"has_forecast": False, "night_low_c": 99.0, "issued_hours_ago": -1.0}, []
    issued = max(o.issued_at for o in standing)
    night = [o for o in standing if o.issued_at == issued and start <= o.measured_at <= end
             and isinstance(o.result, (int, float))]
    if not night:
        return {"has_forecast": False, "night_low_c": 99.0, "issued_hours_ago": -1.0}, []
    low = min(night, key=lambda o: o.result)
    return ({"has_forecast": True, "night_low_c": float(low.result),
             "low_at": low.measured_at.isoformat(),
             "issued_hours_ago": (at - issued).total_seconds() / 3600.0},
            [str(o.id) for o in night])


def _cel(condition: str, values: dict) -> bool:
    import celpy                      # the one dependency, needed only to evaluate
    env = celpy.Environment()
    program = env.program(env.compile(condition))
    return bool(program.evaluate({k: celpy.json_to_cel(v) for k, v in values.items()}))


def judge(rule: Rule, context: dict, inputs: dict, at: _dt.datetime) -> dict:
    """The decision event's payload (§7.7) for any rule over a context its caller built.

    A module above layer 1 builds its own context — a trough's level, a bed's water —
    and judges it here, so every module's decisions carry the same provenance: the
    inputs, the rule and its version, the condition as written, the trust level. Pure:
    the caller logs it. Text values in the context are kept in the record but not
    offered to the condition, which is written over numbers and truths.
    """
    values = {**context, **rule.params}
    alert = _cel(rule.condition, {k: v for k, v in values.items() if not isinstance(v, str)})
    return {"rule": rule.id, "version": rule.version, "condition": rule.condition,
            "params": dict(rule.params), "trust": rule.trust,
            "evaluated_at": at.isoformat(), "inputs": inputs,
            "context": context, "alert": alert,
            "message": ({"key": rule.alert_key,
                         "params": {name: values[source]
                                    for name, source in rule.message_params.items()}}
                        if alert else None)}


def evaluate(rule: Rule, state, forecast_id, at: _dt.datetime) -> dict:
    """The frost watch's decision event payload for one evaluation (§7.7)."""
    context, inputs = frost_context(state, forecast_id, at, rule.params)
    return judge(rule, context, {"forecast": str(forecast_id), "observations": inputs}, at)


def decide(log, rule: Rule, state, forecast_id, at: _dt.datetime):
    """Evaluate and append the decision event to the log."""
    return log.append(DECISION, evaluate(rule, state, forecast_id, at))


def render(decision: dict, language: str = "en") -> str | None:
    if not decision.get("message"):
        return None
    m = decision["message"]
    return str(i18n.Translator(language).text(m["key"], **m["params"]))


def backtest(rule: Rule, state, forecast_id, measured_id, *, to_c=lambda v: v,
             forecast_to_c=lambda v: v, damage_c: float = -2.2, dusk_utc_hour: int = 22) -> dict:
    """§11's backtest: the rule at each dusk against the night the station recorded.
    A night is a frost when the measured low over the rule's window reaches `damage_c`.
    Returns hits (frosts warned), misses, false alerts and quiet nights."""
    measured = [(o.measured_at, to_c(o.result)) for o in state.observations_of(measured_id)
                if isinstance(o.result, (int, float))]
    if not measured:
        return {"hits": 0, "misses": 0, "false": 0, "quiet": 0}
    first, last = min(t for t, _ in measured), max(t for t, _ in measured)
    out = {"hits": 0, "misses": 0, "false": 0, "quiet": 0}
    converted = _ConvertedForecast(state, forecast_id, forecast_to_c)
    day = _dt.datetime(first.year, first.month, first.day, dusk_utc_hour, tzinfo=UTC)
    while day + _dt.timedelta(hours=rule.params["window_end_h"]) <= last:
        lo = day + _dt.timedelta(hours=rule.params["window_start_h"])
        hi = day + _dt.timedelta(hours=rule.params["window_end_h"])
        night = [v for t, v in measured if lo <= t <= hi]
        d = evaluate(rule, converted, forecast_id, day)
        if night and d["context"]["has_forecast"]:
            frost = min(night) <= damage_c
            key = ("hits" if d["alert"] and frost else "misses" if frost
                   else "false" if d["alert"] else "quiet")
            out[key] += 1
        day += 24 * HOUR
    return out


class _ConvertedForecast:
    """A view of a state whose forecast results read in °C, for a forecast kept in °F."""

    def __init__(self, state, forecast_id, to_c):
        self._state, self._id, self._to_c = state, forecast_id, to_c
        self._cache = None

    def observations_of(self, ds):
        if ds != self._id:
            return self._state.observations_of(ds)
        if self._cache is None:
            from dataclasses import replace
            self._cache = [replace(o, result=self._to_c(o.result))
                           if isinstance(o.result, (int, float)) else o
                           for o in self._state.observations_of(ds)]
        return self._cache
