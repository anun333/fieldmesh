#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regimens: steps, waits and checks — layer 1 (spec v0.1 §11; open-questions Q10).

A condition is one expression (CEL, `rules.py`). A regimen is a sequence: water bed 3,
wait for it to soak in, check the probe saw it; dose the herd, wait three days, check the
withdrawal is logged. Q10 decided **Starlark for regimens**: Python-like enough to read,
and, like CEL, unable to touch the world. There is no file, no network, no clock, no
`load`, no `while` and no recursion, and every evaluation runs under an instruction
budget. So a plan depends only on what it was given, and a backtest replays it exactly.

A regimen is a Starlark file defining `plan(ctx, params)`, which returns a list of
steps built with three functions it is given:

* `say(key, subject=None, label=None, **params)` — a message for a person, now;
* `wait(minutes)` — the time before the next step;
* `check(condition, key, subject=None, label=None, show=[...], **params)` — a CEL
  condition over what the module knows then (its context, plus these params); when it
  fails, the message `key`, with the context values named in `show`.

`subject` is what the step is about, by id, and `label` the message parameter its name
fills, in the reader's language (`rules.render`).

Starlark plans; CEL checks; this file keeps time. Nothing here acts — §6's commands are
deferred — so every step is **advisory**, and every step's outcome is a decision event
(§7.7) with the regimen's version and the SHA-256 of its source. A run's plan is written
into the log when it starts, so a runner that restarts carries on from the log without
re-planning on data that has since changed.

    regimen = load("modules/soilwater/regimens/watering_check.star", params={...})
    runner = Runner(log)
    runner.start(regimen, ctx, at, subject=bed_id)
    runner.tick(later, context_fn)       # writes each step's decision as it falls due
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rules as R  # noqa: E402

MIN = _dt.timedelta(minutes=1)
#: About a million Starlark instructions: the check is made roughly every thousand.
BUDGET_CHECKS = 1000
MAX_STEPS = 100
MAX_WAIT_MIN = 14 * 24 * 60
KEY = re.compile(r"[a-z][a-z0-9_]*(\.[a-z0-9_]+)+")

#: What a regimen is given to build its steps with, written in Starlark itself.
PRELUDE = '''
def say(key, subject = None, label = None, **params):
    return {"kind": "say", "key": key, "subject": subject, "label": label, "params": params}

def wait(minutes):
    return {"kind": "wait", "minutes": minutes}

def check(condition, key, subject = None, label = None, show = [], **params):
    return {"kind": "check", "condition": condition, "key": key, "subject": subject,
            "label": label, "show": show, "params": params}
'''


class RegimenError(Exception):
    """A regimen that would not plan, or planned something that is not a plan."""


@dataclass(frozen=True)
class Regimen:
    id: str
    version: str
    source: str
    params: dict = field(default_factory=dict)
    trust: str = "advisory"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.source.encode()).hexdigest()


def load(path: str, *, id: str | None = None, version: str = "1", params=None) -> Regimen:
    with open(path, encoding="utf-8") as h:
        source = h.read()
    return Regimen(id or os.path.splitext(os.path.basename(path))[0].replace("_", "-"),
                   version, source, dict(params or {}))


def plan(regimen: Regimen, ctx: dict) -> list[dict]:
    """The regimen's steps for this context, checked. Deterministic: the same regimen and
    context give the same steps, every time and on every machine."""
    import starlark as sl                  # starlark-pyo3: Apache-2.0, the one dependency
    dialect = sl.Dialect.standard()
    try:
        ast = sl.parse(f"{regimen.id}.star", PRELUDE + regimen.source + "\nplan(ctx, params)\n",
                       dialect)
        module = sl.Module()
        module["ctx"] = ctx
        module["params"] = dict(regimen.params)
        spent = [0]

        def over_budget() -> bool:
            spent[0] += 1
            return spent[0] > BUDGET_CHECKS

        steps = sl.eval_with(sl.EvalOptions(check_cancelled=over_budget), module, ast,
                             sl.Globals.standard()).value
    except sl.StarlarkError as exc:
        raise RegimenError(f"{regimen.id}: {str(exc).strip().splitlines()[0]}") from None
    return _checked(regimen, steps)


def _checked(regimen: Regimen, steps) -> list[dict]:
    if not isinstance(steps, list):
        raise RegimenError(f"{regimen.id}: plan() returns a list of steps")
    if len(steps) > MAX_STEPS:
        raise RegimenError(f"{regimen.id}: {len(steps)} steps; at most {MAX_STEPS}")
    for n, s in enumerate(steps):
        kind = s.get("kind") if isinstance(s, dict) else None
        where = f"{regimen.id}: step {n}"
        if kind == "wait":
            m = s.get("minutes")
            if isinstance(m, bool) or not isinstance(m, (int, float)) or not 0 <= m <= MAX_WAIT_MIN:
                raise RegimenError(f"{where}: a wait is 0 to {MAX_WAIT_MIN} minutes")
            continue
        if kind not in ("say", "check"):
            raise RegimenError(f"{where}: a step is say(), wait() or check()")
        if not isinstance(s.get("key"), str) or not KEY.fullmatch(s["key"]):
            raise RegimenError(f"{where}: a message key looks like module.name")
        if not all(isinstance(v, (int, float, str, bool)) for v in s.get("params", {}).values()):
            raise RegimenError(f"{where}: a parameter is a number, a truth or text")
        if s.get("subject") is not None and not isinstance(s["subject"], str):
            raise RegimenError(f"{where}: a subject is an id, as text")
        if s.get("label") is not None and not isinstance(s["label"], str):
            raise RegimenError(f"{where}: a label names a message parameter")
        if not isinstance(s.get("show", []), list) or \
                not all(isinstance(k, str) for k in s.get("show", [])):
            raise RegimenError(f"{where}: show lists the context's names")
        if kind == "check":
            if not isinstance(s.get("condition"), str):
                raise RegimenError(f"{where}: a check's condition is CEL text")
            try:
                import celpy
                env = celpy.Environment()
                env.compile(s["condition"])
            except Exception as exc:          # noqa: BLE001 — celpy's own error types vary
                raise RegimenError(f"{where}: the condition does not compile: {exc}") from None
    return steps


def schedule(steps: list, started_at: _dt.datetime) -> list[tuple[int, _dt.datetime]]:
    """When each say and check step falls due: `(index, time)`."""
    t, out = started_at, []
    for n, s in enumerate(steps):
        if s["kind"] == "wait":
            t += s["minutes"] * MIN
        else:
            out.append((n, t))
    return out


# --------------------------------------------------------------------- runs

@dataclass
class Run:
    id: str
    regimen: str
    version: str
    sha256: str
    trust: str
    steps: list
    started_at: _dt.datetime
    subject: str | None
    done: set = field(default_factory=set)

    @property
    def finished(self) -> bool:
        return all(n in self.done for n, _ in schedule(self.steps, self.started_at))


class Runner:
    """Regimen runs, kept in the log: a run's start decision carries its plan, and each
    step's outcome is a decision of its own. Learns what it has done from the log, so a
    runner that restarts writes nothing twice."""

    def __init__(self, log) -> None:
        self.log = log
        self.runs: dict[str, Run] = {}
        for event in log.events:
            self._learn(event)

    def _learn(self, event) -> None:
        p = event.payload
        if event.kind != R.DECISION or "regimen_run" not in p:
            return
        if p.get("step") == "start":
            self.runs[p["regimen_run"]] = Run(
                p["regimen_run"], p["rule"], p["version"], p["regimen_sha256"], p["trust"],
                p["plan"], _dt.datetime.fromisoformat(p["evaluated_at"]), p.get("subject"))
        elif p["regimen_run"] in self.runs:
            self.runs[p["regimen_run"]].done.add(p["step"])

    def start(self, regimen: Regimen, ctx: dict, at: _dt.datetime, *, subject=None,
              inputs=None):
        """Plan and log the start of a run. A regimen that plans no steps starts nothing
        and returns None."""
        run_id = hashlib.sha256(f"{regimen.id}|{subject}|{at.isoformat()}".encode()).hexdigest()[:16]
        if run_id in self.runs:
            return None                     # started already, before a restart
        steps = plan(regimen, ctx)
        if not steps:
            return None
        payload = {"rule": regimen.id, "version": regimen.version,
                   "regimen_sha256": regimen.sha256, "regimen_run": run_id, "step": "start",
                   "params": dict(regimen.params), "trust": regimen.trust,
                   "evaluated_at": at.isoformat(), "inputs": inputs or {}, "context": ctx,
                   "plan": steps, "alert": False, "message": None,
                   "topic": f"regimen/{run_id}"}
        if subject is not None:
            payload["subject"] = str(subject)
        event = self.log.append(R.DECISION, payload)
        self._learn(event)
        return event

    def tick(self, at: _dt.datetime, context_fn) -> list:
        """Write every step that has fallen due by `at`. `context_fn(subject, run) ->
        dict` is what the module knows now, for a check's condition."""
        written = []
        for run in list(self.runs.values()):
            for n, due in schedule(run.steps, run.started_at):
                if n in run.done or due > at:
                    continue
                step = run.steps[n]
                subject = step.get("subject") or run.subject
                if step["kind"] == "say":
                    alert, context, message = True, {}, self._message(step, {}, subject)
                else:
                    context = {**context_fn(subject, run), **step["params"]}
                    passed = R._cel(step["condition"],
                                    {k: v for k, v in context.items() if not isinstance(v, str)})
                    alert = not passed
                    message = self._message(step, context, subject) if alert else None
                payload = {"rule": run.regimen, "version": run.version,
                           "regimen_sha256": run.sha256, "regimen_run": run.id, "step": n,
                           "due_at": due.isoformat(), "trust": run.trust,
                           "evaluated_at": at.isoformat(), "context": context,
                           "condition": step.get("condition"), "alert": alert,
                           "message": message, "topic": f"regimen/{run.id}"}
                if subject is not None:
                    payload["subject"] = str(subject)
                event = self.log.append(R.DECISION, payload)
                self._learn(event)
                written.append(event)
        return written

    @staticmethod
    def _message(step: dict, context: dict, subject) -> dict:
        params = dict(step["params"])
        params.update({k: context[k] for k in step.get("show", []) if k in context})
        out = {"key": step["key"], "params": params}
        if subject is not None and step.get("label"):
            out["subject_param"] = step["label"]
        return out
