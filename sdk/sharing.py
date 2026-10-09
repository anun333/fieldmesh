#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Sharing grants (spec v0.1 §7.6; Q16).

A grant is a log record like any other: what data (datastreams), to whom, for what
purpose, until when, whether it covers observations that **arrive after it was made**,
and whether the grantee may share on. A revocation is another record. Nothing is
deleted, so "who could see this, and when" has an answer years later.

**The default covers what has already arrived, and nothing after** (Q16, decided
2026-10-09). `includes_future` must be asked for, and then the grant must end
(`Grant` refuses one that does not). "Arrived" means `received_at`: a backlog that
reaches the gateway the day after the grant is new to the farm too, and a grant made
before it did not see it.

**Revocation stops future access and does not retract what was delivered.** So
`may_read` is asked *at* a moment: before a revocation, the grantee could read; after,
not — and nothing here pretends a copy already taken can be called back.
"""
from __future__ import annotations

import datetime as _dt

import project as P
from model import Grant, Observation


def revoked_at(state: P.State, grant: Grant) -> _dt.datetime | None:
    """The earliest revocation of `grant`, or None."""
    times = [r.at for r in state.revocations if r.grant == grant.id]
    return min(times) if times else None


def in_force(state: P.State, grant: Grant, at: _dt.datetime) -> bool:
    if at < grant.issued_at:
        return False
    if grant.until is not None and at >= grant.until:
        return False
    stop = revoked_at(state, grant)
    return stop is None or at < stop


def covers(grant: Grant, obs: Observation) -> bool:
    """Whether the grant's terms take in this observation, whenever it is asked."""
    if obs.datastream not in grant.datastreams:
        return False
    return grant.includes_future or obs.received_at <= grant.issued_at


def grants_for(state: P.State, grantee: str, at: _dt.datetime) -> list[Grant]:
    return [g for g in state.grants.values() if g.grantee == grantee and in_force(state, g, at)]


def may_read(state: P.State, grantee: str, obs: Observation, at: _dt.datetime) -> bool:
    return any(covers(g, obs) for g in grants_for(state, grantee, at))


def shared(state: P.State, grantee: str, at: _dt.datetime) -> list[Observation]:
    """Every live observation `grantee` may read at `at`, in display order."""
    grants = grants_for(state, grantee, at)
    out = []
    for ds in {d for g in grants for d in g.datastreams}:
        for obs in state.live_observations_of(ds):
            if any(covers(g, obs) for g in grants):
                out.append(obs)
    return P.order_observations(out)


def describe(grant: Grant) -> str:
    """What to tell the farmer at the moment they grant, in plain words (§7.6)."""
    scope = ("observations already received and those that arrive until "
             f"{grant.until:%Y-%m-%d}" if grant.includes_future
             else f"observations received by {grant.issued_at:%Y-%m-%d %H:%M} UTC, and none after")
    end = f" until {grant.until:%Y-%m-%d}" if grant.until else ""
    onward = "may share it on" if grant.reshare else "may not share it on"
    return (f"{grant.grantee} may read {len(grant.datastreams)} series — {scope} — for "
            f"{grant.purpose}{end}, and {onward}. Revoking stops access from then on; it "
            f"cannot take back what was already delivered.")
