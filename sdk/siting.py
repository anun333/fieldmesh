#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Is a probe where its installation record says it is? (spec v0.1 §4.1, §4.2)

An `Installation` is a claim a person made. This checks it against physics. Soil damps
and delays the daily temperature wave with depth — each damping depth down (about
10–15 cm) the daily swing shrinks by a factor of e and the peak arrives roughly 3.8
hours later — so a probe's own temperature record says how deep it is. The failure this
catches is the one the move-and-close machinery cannot: **the move nobody logged.** Frost
heave, a cultivator catching a cable, a probe pulled to look at and pushed back
shallower.

## How

1. Fit `mean + trend + A cos(ωt − φ)` to each probe's last two days of temperature.
   The phase `φ` gives the hour of the daily peak; `A` the daily swing.
2. **Calibrate on the peers.** Every other probe with a recorded depth shares the same
   weather, so the peak hour across them is a straight line in depth: `h0 + k·z`,
   where `h0` is the surface peak and `k` is 24/2π hours per damping depth. Fitting it
   from peers absorbs the day's weather and the soil's diffusivity, neither of which a
   fixed constant could know.
3. Invert the line for this probe: the depth its own peak hour implies. Compare with
   the recorded depth.

Phase is primary because the hour of the peak does not depend on how sunny the day was,
while the size of the swing does. Amplitude is fitted too and carried as corroboration.

## What it cannot see — said plainly, because a check that hides its blind spots is
## worse than none

* **Below the daily wave.** Past three or four damping depths the swing is smaller than
  the sensor's resolution and there is no phase to read. A deep probe in a dry bed is
  `indeterminate`, not `consistent`.
* **A move to another bed at the same depth.** Every bed shares the weather, so the
  daily wave is the same in all of them. Only depth leaves a thermal signature; a
  lateral move needs the moisture record instead (which bed's irrigation does it
  answer to?).
* **Anything in the first day or so after installation**, while the wave establishes.
* **Peers that are themselves misplaced.** The fit is robust to one, not to many.
* **A cover nobody recorded.** Mulch, sod and plastic insulate the ground and damp and
  delay the daily wave as extra soil would, so a probe under a cover looks deeper than it
  is against peers in bare beds. Peers are therefore taken only under the same recorded
  surface as the probe (`Installation.surface`); with too few, the check says it cannot
  tell. Unrecorded covers are all alike to it, so a farm that mulches some beds and records
  none can still be told a mulched probe moved when it did not. Record the cover.
"""
from __future__ import annotations

import datetime as _dt
import math
import statistics
from dataclasses import dataclass, field, replace
from uuid import UUID

import i18n
import project as P
import vocab as V
from ids import uuid7
from model import (Assertor, DatastreamKind, QualityAssertion, QualityFlag,
                   derive_usable)

OMEGA = 2 * math.pi / 86400.0
HOURS_PER_RADIAN = 24.0 / (2 * math.pi)

#: Two days: long enough to separate the daily wave from the seasonal trend and from
#: one cloudy afternoon, short enough to notice a displacement within the week.
DEFAULT_WINDOW = _dt.timedelta(days=2)

#: Below this fitted daily swing there is no phase worth reading. Set against a
#: 0.1 C sensor: over two days of hourly samples the fit resolves well under a tenth
#: of a degree, but a swing this small is mostly quantisation dither.
MIN_AMPLITUDE_C = 0.10

#: The smallest disagreement worth calling a displacement. Widened automatically when
#: the peers themselves disagree — see `assess_siting`.
DEFAULT_TOLERANCE_M = 0.08

#: The tolerance when only two peers calibrate the line. Two points fix a line exactly,
#: so there is no scatter to widen the tolerance by and no way to outvote a peer that is
#: itself displaced; the margin has to come from somewhere else.
TWO_PEER_TOLERANCE_M = 0.12

#: How many daily assessments `assess_siting_persistent` looks back over, and how many
#: of them must say `displaced`. Measured on ISMN's three Tennessee profiles, 169
#: probe-years with no move: one window at a time, a correctly placed probe raised 3.9
#: false episodes a year; 2 of 3 days, 0.76; 3 of 5, 0.29; 5 of 7, 0.04 — while a probe
#: lifted 15 cm was still caught on every day the check could decide. Siting is not
#: urgent, so the week this costs is cheap. See docs/notes/siting-real-soil.md.
PERSIST_COUNT = 7
PERSIST_REQUIRED = 5
PERSIST_EVERY = _dt.timedelta(days=1)

#: The weekly assessment, `assess_siting_weekly`. Over two days only the top three
#: depths carry a wave above MIN_AMPLITUDE_C, so a real station's probe has two peers,
#: none to outvote a displaced one, and a 12 cm tolerance. Over fourteen days the fit
#: resolves a far smaller wave, and the 51 cm probe every such station already has
#: becomes a third peer: the fit is robust and the tolerance 8 cm. Measured on the same
#: profiles with no known disturbance, 3 of the last 4 weeks raised 0.04 false episodes
#: per probe-year — as few as the daily assessment — and called about four in five 10 cm
#: moves within six months (median five to nine weeks), which the daily assessment almost
#: never does; and McAllister Farm's real 2023 change stopped being blamed on the wrong
#: probe.
WEEKLY_WINDOW = _dt.timedelta(days=14)
WEEKLY_PEER_AMPLITUDE_C = 0.03
WEEKLY_COUNT = 4
WEEKLY_REQUIRED = 3
WEEKLY_EVERY = _dt.timedelta(days=7)

#: How far back from the onset of a non-robust alarm to look for a record change on
#: any probe in the profile, and how long a silence in a probe's readings counts as
#: one (Q25). At McAllister Farm the replacement went in on 17 January and winter
#: hid the change until April — eleven weeks — so the window is generous.
ATTRIBUTION_LOOKBACK = _dt.timedelta(days=120)
ATTRIBUTION_GAP = _dt.timedelta(days=7)

CONSISTENT = "consistent"
DISPLACED = "displaced"
INDETERMINATE = "indeterminate"


# ----------------------------------------------------------------- the fit

@dataclass(frozen=True, slots=True)
class DiurnalFit:
    """`mean + trend·days + amplitude·cos(ω t − phase)`, least squares."""

    mean: float
    trend_per_day: float
    amplitude: float
    peak_hour: float           # UTC hour of the daily maximum, [0, 24)
    samples: int
    residual_rms: float


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting. Four unknowns; no numpy needed."""
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("singular system: the samples cannot separate the terms")
        a[col], a[pivot] = a[pivot], a[col]
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            for k in range(col, n + 1):
                a[row][k] -= factor * a[col][k]
    out = [0.0] * n
    for row in range(n - 1, -1, -1):
        out[row] = (a[row][n] - sum(a[row][k] * out[k]
                                    for k in range(row + 1, n))) / a[row][row]
    return out


def fit_diurnal(samples) -> DiurnalFit | None:
    """Fit the daily wave to `(epoch_seconds, value)` pairs, or None if it cannot be.

    Needs at least twelve samples spanning most of a day. The linear trend term is not
    decoration: over two days in early summer the soil warms by a degree or more, and
    without the trend that drift leaks into the cosine and shifts the peak.
    """
    samples = [(float(t), float(v)) for t, v in samples]
    if len(samples) < 12:
        return None
    times = [t for t, _ in samples]
    if max(times) - min(times) < 20 * 3600:
        return None
    mid = (max(times) + min(times)) / 2.0
    rows = [[1.0, (t - mid) / 86400.0, math.cos(OMEGA * t), math.sin(OMEGA * t)]
            for t in times]
    values = [v for _, v in samples]
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(4)] for i in range(4)]
    xty = [sum(r[i] * v for r, v in zip(rows, values)) for i in range(4)]
    try:
        a, b, c, s = _solve(xtx, xty)
    except ValueError:
        return None
    amplitude = math.hypot(c, s)
    phase = math.atan2(s, c) % (2 * math.pi)     # radians after UTC midnight
    fitted = [a + b * r[1] + c * r[2] + s * r[3] for r in rows]
    rms = math.sqrt(sum((v - f) ** 2 for v, f in zip(values, fitted)) / len(values))
    return DiurnalFit(mean=a, trend_per_day=b, amplitude=amplitude,
                      peak_hour=(phase * HOURS_PER_RADIAN) % 24.0,
                      samples=len(samples), residual_rms=rms)


# --------------------------------------------------------------- the check

@dataclass(frozen=True, slots=True)
class SitingFinding:
    device: UUID
    at: _dt.datetime
    verdict: str
    reason: str
    recorded_depth_m: float | None = None
    implied_depth_m: float | None = None
    implied_depth_amplitude_m: float | None = None
    damping_depth_m: float | None = None
    tolerance_m: float | None = None
    fit: DiurnalFit | None = None
    peers_used: int = 0
    evidence: dict = field(default_factory=dict)
    #: The message key and parameters `reason` was rendered from, for any language.
    key: str | None = None
    params: dict = field(default_factory=dict)

    @property
    def displaced(self) -> bool:
        return self.verdict == DISPLACED


def _temperature_stream(state: P.State, device_id: UUID, prop: str):
    for ds in state.datastreams_of_sensor(device_id):
        if ds.kind is DatastreamKind.DERIVED and ds.observed_property == prop:
            return ds
    return None


def _window_fit(state: P.State, datastream_id: UUID, at: _dt.datetime,
                window: _dt.timedelta) -> DiurnalFit | None:
    since = at - window
    samples = [(o.measured_at.timestamp(), o.result)
               for o in state.live_observations_of(datastream_id)
               if since <= o.measured_at <= at and isinstance(o.result, (int, float))]
    return fit_diurnal(samples)


def _unwrap(hour: float, reference: float, *, earliest: float = 3.0) -> float:
    """`hour` moved by whole days to sit near `reference`: up to `earliest` hours
    before it, or up to `24 - earliest` after.

    A deeper probe's peak can land past midnight, and comparing 23:00 with 02:00 as
    plain numbers would put it shallower than it is. How much *earlier* to allow
    depends on the reference. Against the surface, a little — nothing in the ground
    peaks before the surface does. Against the shallowest recorded probes, much more,
    because a probe lifted out of the ground peaks hours before them; with only three
    hours allowed, a lifted peer unwrapped to the following day and looked a metre
    deep.
    """
    delta = (hour - reference) % 24.0
    if delta > 24.0 - earliest:
        delta -= 24.0
    return reference + delta


def _line(xs, ys):
    """A **robust** line `y = a + b x`, and a robust scatter of the residuals.

    Theil–Sen: the slope is the median of every pairwise slope, the intercept the
    median offset. It tolerates roughly three in ten points being wrong, which is the
    property that matters here, because **the points are other probes and some of them
    may be displaced too**.

    The first version used ordinary least squares and set the tolerance from the RMS
    residual. Measured on a farm with two unlogged moves, the two displaced probes sat
    in each other's calibration set at depths they no longer had, dragged the line,
    inflated the RMS, and widened the tolerance to 2.8 m — so the check passed nearly
    every probe on the farm, including one pushed 16 cm deeper. One bad peer disabling
    the check for everyone is the opposite of failing safe.

    The scatter is 1.4826 times the median absolute residual, the consistent estimate
    of a standard deviation that one outlier cannot move.
    """
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i])
              for i in range(len(xs)) for j in range(i + 1, len(xs))
              if abs(xs[j] - xs[i]) > 1e-9]
    if not slopes:
        return None
    b = statistics.median(slopes)
    a = statistics.median(y - b * x for x, y in zip(xs, ys))
    residuals = [abs(y - a - b * x) for x, y in zip(xs, ys)]
    scatter = 1.4826 * statistics.median(residuals)
    return a, b, scatter


def assess_siting(state: P.State, device_id: UUID, at: _dt.datetime, *,
                  window: _dt.timedelta = DEFAULT_WINDOW,
                  tolerance_m: float = DEFAULT_TOLERANCE_M,
                  min_amplitude_c: float = MIN_AMPLITUDE_C,
                  min_peer_amplitude_c: float | None = None,
                  prop: str = V.SOIL_TEMPERATURE) -> SitingFinding:
    """Judge whether `device_id` sits at its recorded depth, as of `at`.

    `min_peer_amplitude_c` lets a peer calibrate with a weaker wave than the probe being
    judged needs — over a long window, a deep probe's small swing still fixes a point on
    the line. None means the same floor for both.

    Always returns a finding. `indeterminate` is a real answer with a reason — the
    honest result for a probe below the reach of the daily wave, or one with too few
    peers to calibrate against — and never a silent `consistent`.
    """
    def unknown(key, params=None, **kw):
        params = params or {}
        return SitingFinding(device=device_id, at=at, verdict=INDETERMINATE,
                             reason=i18n.english(key, **params), key=key,
                             params=params, **kw)

    stream = _temperature_stream(state, device_id, prop)
    if stream is None:
        return unknown("siting.no_channel")
    installed = state.installation_of(device_id, at)
    if installed is None or installed.depth_m is None:
        return unknown("siting.no_depth")
    recorded = installed.depth_m

    # Never judge the current installation by readings taken under the previous one.
    # Right after a logged move, a window reaching back past the move holds readings
    # from the old siting, which correctly disagree with the new record — the drill
    # caught exactly that as a false alarm on a properly recorded move.
    own_window = min(window, at - installed.installed_at)
    own = _window_fit(state, stream.id, at, own_window)
    if own is None:
        return unknown("siting.too_few_readings", recorded_depth_m=recorded)
    if own.amplitude < min_amplitude_c:
        return unknown("siting.below_wave",
                       {"amplitude": own.amplitude, "floor": min_amplitude_c},
                       recorded_depth_m=recorded, fit=own)

    # --- calibrate on the peers ---------------------------------------------
    peers = []
    peer_devices = []
    other_covers = 0
    for other_id in state.devices:
        if other_id == device_id:
            continue
        other_stream = _temperature_stream(state, other_id, prop)
        if other_stream is None:
            continue
        other_install = state.installation_of(other_id, at)
        if other_install is None or other_install.depth_m is None:
            continue
        if other_install.surface != installed.surface:
            other_covers += 1               # a different cover damps the wave differently
            continue
        other_fit = _window_fit(state, other_stream.id, at,
                                min(window, at - other_install.installed_at))
        peer_floor = min_amplitude_c if min_peer_amplitude_c is None else min_peer_amplitude_c
        if other_fit is None or other_fit.amplitude < peer_floor:
            continue
        peers.append((other_install.depth_m, other_fit))
        peer_devices.append(other_id)

    depths = {round(z, 3) for z, _ in peers}
    # Two peers at two depths is the minimum: they fix the depth-to-phase line, and the
    # probe is read against it. The first version required three, which the simulator's
    # twelve-probe farm always met and a real station never does: scored on ISMN's
    # Tennessee profiles — one probe per depth, and only 5, 10 and 20 cm with a daily
    # wave strong enough to read — every shallow probe had exactly two usable peers, and
    # the check said "cannot tell" about 80% of the time. With two, the line is exact and
    # cannot be robust, so the tolerance widens and the evidence says so.
    if len(peers) < 2 or len(depths) < 2:
        if other_covers:
            return unknown("siting.too_few_peers_same_surface",
                           {"peers": len(peers), "depths": len(depths),
                            "surface": installed.surface or "unrecorded",
                            "others": other_covers},
                           recorded_depth_m=recorded, fit=own, peers_used=len(peers))
        return unknown("siting.too_few_peers",
                       {"peers": len(peers), "depths": len(depths)},
                       recorded_depth_m=recorded, fit=own, peers_used=len(peers))

    shallowest = min(z for z, _ in peers)
    reference = statistics.median(f.peak_hour for z, f in peers
                                  if abs(z - shallowest) < 1e-6)
    zs = [z for z, _ in peers]
    hours = [_unwrap(f.peak_hour, reference, earliest=7.0) for _, f in peers]
    phase_line = _line(zs, hours)
    if phase_line is None or phase_line[1] <= 0:
        return unknown("siting.no_lag", recorded_depth_m=recorded, fit=own,
                       peers_used=len(peers))
    h0, k, rms_h = phase_line
    damping = HOURS_PER_RADIAN / k

    amp_line = _line(zs, [math.log(f.amplitude) for _, f in peers])
    implied_amp = None
    if amp_line is not None and amp_line[1] < 0:
        ln_a0, slope, _ = amp_line
        implied_amp = (math.log(own.amplitude) - ln_a0) / slope

    implied = _unwrap(own.peak_hour, h0) - h0
    implied = implied / k

    # The peers' own scatter sets a floor on what can be resolved: if probes at the
    # same recorded depth disagree by 3 cm, a 2 cm discrepancy here is not evidence.
    # Robust scatter, so a displaced peer widens this by almost nothing.
    peer_scatter_m = rms_h / k
    tol = max(tolerance_m, 3.0 * peer_scatter_m)
    robust = len(peers) >= 3
    if not robust:
        tol = max(tol, TWO_PEER_TOLERANCE_M)
    off_by = implied - recorded

    evidence = {
        "recorded_depth_m": round(recorded, 3),
        "implied_depth_m": round(implied, 3),
        "implied_depth_from_amplitude_m": (round(implied_amp, 3)
                                           if implied_amp is not None else None),
        "peak_hour_utc": round(own.peak_hour, 2),
        "daily_swing_c": round(2 * own.amplitude, 3),
        "damping_depth_m": round(damping, 3),
        "surface_peak_hour_utc": round(h0 % 24.0, 2),
        "peers": len(peers),
        "peer_scatter_m": round(peer_scatter_m, 3),
        # The cover the peers share with this probe; probes under other covers were left
        # out, since mulch or sod reads as depth.
        "surface": installed.surface,
        "peers_under_other_covers": other_covers,
        # False when two peers fixed the line: then a displaced peer cannot be outvoted,
        # and a flag here may mean "something in this profile moved" rather than "this
        # probe moved".
        "robust": robust,
        # Which probes calibrated the line: when the fit is not robust, a displaced
        # verdict may belong to any of them (Q25), and the persistent assessment
        # looks through their records to say which.
        "peer_devices": [str(d) for d in peer_devices],
        "tolerance_m": round(tol, 3),
        "window_h": window.total_seconds() / 3600.0,
    }
    common = dict(recorded_depth_m=recorded, implied_depth_m=implied,
                  implied_depth_amplitude_m=implied_amp, damping_depth_m=damping,
                  tolerance_m=tol, fit=own, peers_used=len(peers),
                  evidence=evidence)
    if abs(off_by) <= tol:
        params = {"implied": implied, "recorded": recorded}
        return SitingFinding(device=device_id, at=at, verdict=CONSISTENT,
                             reason=i18n.english("siting.consistent", **params),
                             key="siting.consistent", params=params, **common)
    # Two keys rather than a "shallower"/"deeper" word dropped into one sentence: in
    # many languages the comparative is not a word that slots in, and in some it
    # changes the grammar around it.
    key = "siting.shallower" if off_by < 0 else "siting.deeper"
    params = {"peak": own.peak_hour, "implied": implied, "off": abs(off_by),
              "recorded": recorded}
    return SitingFinding(device=device_id, at=at, verdict=DISPLACED,
                         reason=i18n.english(key, **params), key=key, params=params,
                         **common)


def assess_siting_persistent(state: P.State, device_id: UUID, at: _dt.datetime, *,
                             count: int = PERSIST_COUNT, required: int = PERSIST_REQUIRED,
                             every: _dt.timedelta = PERSIST_EVERY,
                             **kwargs) -> SitingFinding:
    """`assess_siting` at `at` and every `every` before it, `count` times in all;
    `displaced` only if at least `required` of them said so. With the defaults, once a day
    for a week. This, or `assess_siting_weekly`, is the one to act on.

    A single window is too noisy to flag a reading on. The depth it implies is good —
    median error 1.6–3.6 cm in the root zone on real soil — but an overcast spell, a
    rain front or a layered soil sends one window astray two to four times in a hundred,
    and assessed daily that is a false `displaced` per probe per month or so. A real move
    is permanent and shows up every day; noise rarely does.

    * `displaced` — persistent. The finding is the latest displaced assessment's, with
      `evidence["persistence"]` saying how many agreed, and `window_h` covering the
      whole span, so `suspect_assertions` flags every reading the move casts doubt on.
    * `consistent` — the latest window agrees, and too few disagreed.
    * `indeterminate` — the latest cannot tell, or says `displaced` but not yet often
      enough (`siting.unconfirmed`). Never a quiet `consistent` for that.

    `kwargs` go to each `assess_siting` call. Each window still never reaches back past
    a logged installation, so a recorded move starts the count afresh.
    """
    runs = [assess_siting(state, device_id, at - i * every, **kwargs)
            for i in range(count)]                                   # newest first
    displaced = [f for f in runs if f.verdict == DISPLACED]
    decided = sum(1 for f in runs if f.verdict != INDETERMINATE)
    persistence = {"count": count, "required": required,
                   "every_h": every.total_seconds() / 3600.0,
                   "displaced": len(displaced), "decided": decided}
    today = runs[0]
    if len(displaced) >= required:
        latest = displaced[0]
        window_h = float(latest.evidence.get("window_h", DEFAULT_WINDOW.total_seconds()
                                             / 3600.0))
        span_h = window_h + (at - displaced[-1].at).total_seconds() / 3600.0
        evidence = dict(latest.evidence, persistence=persistence, window_h=span_h)
        found = replace(latest, at=at, evidence=evidence)
        if latest.evidence.get("robust", True):
            return found
        return _attribute(state, found, onset=displaced[-1].at,
                          prop=kwargs.get("prop", V.SOIL_TEMPERATURE))
    if today.verdict == DISPLACED:
        params = {"days": len(displaced), "of": count, "required": required}
        return replace(today, verdict=INDETERMINATE, key="siting.unconfirmed",
                       params=params, reason=i18n.english("siting.unconfirmed", **params),
                       evidence=dict(today.evidence, persistence=persistence))
    return replace(today, evidence=dict(today.evidence, persistence=persistence))


def _record_changes(state: P.State, device_id: UUID, since: _dt.datetime,
                    until: _dt.datetime, prop: str,
                    profile_start: _dt.datetime) -> list:
    """What changed in one probe's records between `since` and `until`: a new
    installation, a maintenance event, a recalibration, or its readings resuming
    after a silence of ATTRIBUTION_GAP or more. Each as `(when, what)`.

    An installation or calibration made with the rest of the profile — within a day
    of its first installation — is how the profile began, not a change in it; a later
    one is a replacement, a move or a recalibration."""
    changes = []
    for inst in state.installations_of(device_id):
        if (since <= inst.installed_at <= until
                and inst.installed_at > profile_start + _dt.timedelta(days=1)):
            changes.append((inst.installed_at, "installed"))
    for event in state.maintenance_of(device_id):
        if since <= event.at <= until:
            changes.append((event.at, event.action.value))
    for cal in state.calibrations.values():
        if (cal.sensor == device_id and since <= cal.valid_from <= until
                and cal.valid_from > profile_start + _dt.timedelta(days=1)):
            changes.append((cal.valid_from, "recalibrated"))
    stream = _temperature_stream(state, device_id, prop)
    if stream is not None:
        times = sorted(o.measured_at for o in state.live_observations_of(stream.id)
                       if since - ATTRIBUTION_GAP <= o.measured_at <= until)
        for before, after in zip(times, times[1:]):
            if after - before >= ATTRIBUTION_GAP and since <= after <= until:
                changes.append((after, "readings resumed"))
    return sorted(changes)


def _name(state: P.State, device_id: UUID) -> str:
    label = state.label_for(device_id)
    return label.name if label is not None else str(device_id)[:8]


def _attribute(state: P.State, found: SitingFinding, *, onset: _dt.datetime,
               prop: str) -> SitingFinding:
    """A persistent displacement from a two-peer fit: say *which* probe (Q25).

    With two peers the line is exact, so any one probe's move fits the readings
    equally well, and an error in a peer is amplified in the probe extrapolated from
    it. At McAllister Farm a replacement 10 cm probe went in about 4 cm shallow and
    the check blamed the 20 cm probe. So the finding reports the profile, and names
    the probe whose own records changed before the alarm began — exactly right at both
    stations where it happened. If none or several did, it says so rather than guess.
    The verdict stays `displaced`: something in the profile moved.
    """
    profile = [found.device] + [UUID(d) for d in found.evidence.get("peer_devices", [])]
    since = onset - ATTRIBUTION_LOOKBACK
    starts = [i.installed_at for d in profile for i in state.installations_of(d)]
    profile_start = min(starts) if starts else since
    changed = []
    for device_id in profile:
        for when, what in _record_changes(state, device_id, since, onset, prop,
                                          profile_start):
            changed.append({"device": str(device_id), "at": when.isoformat(),
                            "change": what})
    devices = {c["device"] for c in changed}
    named = UUID(devices.pop()) if len(devices) == 1 else None
    attribution = {"profile": [str(d) for d in profile], "changed": changed,
                   "named": str(named) if named is not None else None}
    evidence = dict(found.evidence, attribution=attribution,
                    displacement={"key": found.key, "params": found.params})
    if named is not None and named != found.device:
        last = [c for c in changed if c["device"] == str(named)][-1]
        key = "siting.profile_named"
        params = {"device": _name(state, named), "change": last["change"],
                  "date": last["at"][:10]}
    elif named is None:
        key = "siting.profile_unnamed"
        params = {"count": len(profile)}
    else:
        return replace(found, evidence=evidence)     # its own records changed
    return replace(found, key=key, params=params, evidence=evidence,
                   reason=i18n.english(key, **params))


def assess_siting_weekly(state: P.State, device_id: UUID, at: _dt.datetime,
                         **kwargs) -> SitingFinding:
    """Two-week windows, once a week for four weeks; `displaced` on three of them.

    The slower complement to the daily `assess_siting_persistent`, not a replacement:
    the daily one calls a 15 cm move within about a week, this one within about five.
    What this one adds is a deeper peer. On a real station, where only the top three
    depths carry a two-day wave, the 51 cm probe joins over two weeks — so the fit is
    robust, a displaced peer is outvoted rather than blamed on its neighbour, and the
    tolerance tightens from 12 cm to 8, which brings 10 cm moves within reach.
    """
    options = dict(count=WEEKLY_COUNT, required=WEEKLY_REQUIRED, every=WEEKLY_EVERY,
                   window=WEEKLY_WINDOW, min_peer_amplitude_c=WEEKLY_PEER_AMPLITUDE_C)
    options.update(kwargs)
    return assess_siting_persistent(state, device_id, at, **options)


# --------------------------------------------------------- position (GNSS)

#: Larger than a consumer GNSS fix's scatter after averaging, smaller than the gap
#: between two features worth telling apart.
DEFAULT_POSITION_TOLERANCE_M = 20.0
METRES_PER_DEGREE = 111_320.0
DEFAULT_POSITION_WINDOW = _dt.timedelta(days=1)


@dataclass(frozen=True, slots=True)
class PositionFinding:
    device: UUID
    at: _dt.datetime
    verdict: str
    reason: str
    distance_m: float | None = None
    tolerance_m: float | None = None
    fixes: int = 0
    evidence: dict = field(default_factory=dict)
    key: str | None = None
    params: dict = field(default_factory=dict)

    @property
    def displaced(self) -> bool:
        return self.verdict == DISPLACED


def _point_of(geometry):
    """A representative (lon, lat) for a GeoJSON geometry: the point, or the mean of
    a polygon's outer ring."""
    if not geometry:
        return None
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Point":
        return float(coords[0]), float(coords[1])
    if kind == "Polygon" and coords and coords[0]:
        ring = coords[0]
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    return None


def _metres(lon1, lat1, lon2, lat2) -> float:
    """Equirectangular distance — exact enough over a farm, and far simpler than a
    great-circle formula that would add nothing at a scale of hundreds of metres."""
    mean_lat = math.radians((lat1 + lat2) / 2.0)
    dx = (lon2 - lon1) * math.cos(mean_lat) * METRES_PER_DEGREE
    dy = (lat2 - lat1) * METRES_PER_DEGREE
    return math.hypot(dx, dy)


def assess_position(state: P.State, device_id: UUID, at: _dt.datetime,
                    geometries: dict, *,
                    window: _dt.timedelta = DEFAULT_POSITION_WINDOW,
                    tolerance_m: float = DEFAULT_POSITION_TOLERANCE_M,
                    ) -> PositionFinding:
    """Is a node where its installation record says, by its own GNSS fixes?

    Covers the blind spot the temperature check admits: a **lateral** move — a node
    carried to another bed or paddock — leaves no thermal signature but moves the fix.
    Medians rather than means, so one multipath-bounced fix does not move the answer.

    `geometries` comes in as a parameter rather than from the log, on purpose: field
    boundaries are site-private material (§10.1) and are not log records.
    """
    def unknown(key, params=None, **kw):
        params = params or {}
        return PositionFinding(device=device_id, at=at, verdict=INDETERMINATE,
                               reason=i18n.english(key, **params), key=key,
                               params=params, **kw)

    streams = {ds.observed_property: ds
               for ds in state.datastreams_of_sensor(device_id)
               if ds.kind is DatastreamKind.DERIVED}
    lat_ds, lon_ds = streams.get(V.LATITUDE), streams.get(V.LONGITUDE)
    if lat_ds is None or lon_ds is None:
        return unknown("position.no_gnss")
    installed = state.installation_of(device_id, at)
    if installed is None:
        return unknown("position.no_installation")
    expected = _point_of(geometries.get(installed.feature))
    if expected is None:
        return unknown("position.no_geometry")

    since = at - window
    lats = {o.measured_at: o.result for o in state.live_observations_of(lat_ds.id)
            if since <= o.measured_at <= at}
    lons = {o.measured_at: o.result for o in state.live_observations_of(lon_ds.id)
            if since <= o.measured_at <= at}
    paired = [(lons[t], lats[t]) for t in sorted(set(lats) & set(lons))]
    if len(paired) < 4:
        return unknown("position.too_few_fixes", {"fixes": len(paired)},
                       fixes=len(paired))

    lon = statistics.median(p[0] for p in paired)
    lat = statistics.median(p[1] for p in paired)
    distance = _metres(expected[0], expected[1], lon, lat)
    spread = 1.4826 * statistics.median(_metres(lon, lat, p[0], p[1]) for p in paired)
    tol = max(tolerance_m, 4.0 * spread / math.sqrt(len(paired)) + 2.0 * spread)
    evidence = {"distance_m": round(distance, 1), "tolerance_m": round(tol, 1),
                "fixes": len(paired), "fix_spread_m": round(spread, 1),
                "median_fix": [round(lon, 7), round(lat, 7)],
                "recorded_point": [round(expected[0], 7), round(expected[1], 7)],
                "window_h": window.total_seconds() / 3600.0}
    params = {"distance": distance, "tolerance": tol, "fixes": len(paired)}
    verdict, key = ((CONSISTENT, "position.consistent") if distance <= tol
                    else (DISPLACED, "position.displaced"))
    return PositionFinding(device=device_id, at=at, verdict=verdict,
                           reason=i18n.english(key, **params), distance_m=distance,
                           tolerance_m=tol, fixes=len(paired), evidence=evidence,
                           key=key, params=params)


# ------------------------------------------------ findings into quality assertions

SITING_CHECK = "siting"
SITING_VERSION = "1"


@dataclass(frozen=True, slots=True)
class Flagging:
    """What `suspect_assertions` would append, and what it declined to touch."""

    assertions: tuple
    already_flagged: int = 0
    person_outranks: int = 0


def suspect_assertions(state: P.State, finding, *, datastreams=None,
                       asserted_at: _dt.datetime | None = None) -> Flagging:
    """Turn a `displaced` finding into §3.3 assertions on the readings it casts doubt on.

    A probe found at the wrong depth makes every reading it took in the window
    questionable — moisture as well as temperature, because the moisture is attributed
    to a depth it was not measured at. So by default every derived datastream of the
    device is flagged; pass `datastreams` to choose others, such as the probes cabled to
    a node whose position moved.

    Three rules, each pinned by a test:

    * **It adds to the reading's judgement rather than replacing it.** §3.3 has one live
      assertion per reading carrying a set of flags, so this supersedes the current one
      with its flags plus `suspect`, and carries the earlier evidence forward. A stuck
      reading stays `bad`; it does not become merely `questionable` because siting spoke
      last.
    * **A person outranks it.** Where the live judgement is a person's, this declines
      and counts it. Superseding a human override with a machine flag would erase the
      override from the live view, which is exactly what precedence exists to prevent.
    * **It is idempotent.** Assessments run daily over overlapping windows; a reading
      already carrying a siting flag is left alone.

    Pure: returns the assertions; the caller appends them to the log and state.
    """
    if not finding.displaced:
        return Flagging(assertions=())
    window_h = float(finding.evidence.get("window_h", 48.0))
    since = finding.at - _dt.timedelta(hours=window_h)
    if datastreams is None:
        datastreams = [ds.id for ds in state.datastreams_of_sensor(finding.device)
                       if ds.kind is DatastreamKind.DERIVED]
    when = asserted_at or finding.at
    out, already, outranked = [], 0, 0
    for ds_id in datastreams:
        for obs in state.live_observations_of(ds_id):
            if not since <= obs.measured_at <= finding.at:
                continue
            current = state.live_assertion_for(obs.id)
            if current is not None and current.assertor is Assertor.PERSON:
                outranked += 1
                continue
            if current is not None and "siting" in current.evidence:
                already += 1
                continue
            flags = frozenset(current.flags if current else ()) | {QualityFlag.SUSPECT}
            evidence = dict(current.evidence) if current else {}
            messages = dict(evidence.get("messages", {}))
            messages["siting"] = {"key": finding.key, "params": dict(finding.params)}
            evidence.update({"siting": dict(finding.evidence), "messages": messages,
                             "siting_device": str(finding.device),
                             # The normative floor (Q19): what looked, what objected.
                             "checks_run": list(evidence.get("checks_run", [])) + [SITING_CHECK],
                             "fired": dict(evidence.get("fired", {}),
                                           **{SITING_CHECK: finding.reason})})
            note = finding.reason if current is None or not current.note \
                else f"{current.note}; siting: {finding.reason}"
            out.append(QualityAssertion(
                id=uuid7(), observation=obs.id, flags=flags,
                usable=derive_usable(flags), check=SITING_CHECK,
                check_version=SITING_VERSION,
                threshold_version=current.threshold_version if current else None,
                asserted_at=when, assertor=Assertor.FOUNDATION,
                supersedes=current.id if current else None,
                note=note, evidence=evidence))
    return Flagging(assertions=tuple(out), already_flagged=already,
                    person_outranks=outranked)


# --------------------------------------------- lateral siting, from moisture

DEFAULT_LATERAL_WINDOW = _dt.timedelta(days=3)
#: How far ahead the best-matching bed must be before a move is called. Rain wets every
#: bed at once and makes all of them match; only each bed's own irrigation separates
#: them, so a close call is a rainy window, not evidence.
LATERAL_MARGIN = 0.25
LATERAL_MIN_MATCH = 0.6


@dataclass(frozen=True, slots=True)
class LateralFinding:
    device: UUID
    at: _dt.datetime
    verdict: str
    reason: str
    recorded_feature: UUID | None = None
    best_feature: UUID | None = None
    recorded_match: float | None = None
    best_match: float | None = None
    evidence: dict = field(default_factory=dict)
    key: str | None = None
    params: dict = field(default_factory=dict)

    @property
    def displaced(self) -> bool:
        return self.verdict == DISPLACED


def _wetting(state, datastream_id, since, until, bin_s, valid_from=None):
    """Positive moisture increments on a fixed grid of `bin_s` seconds.

    Only increases, because wetting is the signature: drying is everywhere at once and
    at the same pace, so it says nothing about *where* a probe is. A bin with no reading
    breaks the chain rather than inventing a step across the gap.
    """
    origin = since.timestamp()
    bins: dict[int, float] = {}
    floor = max(since, valid_from) if valid_from is not None else since
    for obs in state.live_observations_of(datastream_id):
        if not floor <= obs.measured_at <= until or not isinstance(
                obs.result, (int, float)):
            continue
        bins[int((obs.measured_at.timestamp() - origin) // bin_s)] = float(obs.result)
    size = int((until.timestamp() - origin) // bin_s) + 1
    out = [0.0] * size
    for index in range(1, size):
        if index in bins and index - 1 in bins:
            out[index] = max(0.0, bins[index] - bins[index - 1])
    return out


def _correlation(a, b):
    n = len(a)
    if n < 3:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def _best_lagged(a, b, max_lag):
    """The best correlation over lags in either direction — a deep probe answers its
    bed's irrigation later than a shallow one, so lockstep is too strict a test."""
    best = -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x, y = a[lag:], b[:len(b) - lag]
        else:
            x, y = a[:lag], b[-lag:]
        best = max(best, _correlation(x, y))
    return best


def assess_lateral(state: P.State, device_id: UUID, at: _dt.datetime, *,
                   window: _dt.timedelta = DEFAULT_LATERAL_WINDOW,
                   bin_s: float = 900.0, max_lag_bins: int = 4,
                   margin: float = LATERAL_MARGIN,
                   min_match: float = LATERAL_MIN_MATCH,
                   prop: str = V.SOIL_WATER) -> LateralFinding:
    """Is a probe in the bed its record names, judged by whose irrigation it answers?

    The complement of `assess_siting`: depth leaves a thermal signature and bed does
    not, while bed leaves an irrigation signature and depth barely does. Each probe's
    wetting events are correlated with every other probe's, grouped by recorded
    feature; a probe that moves with another bed's timers rather than its own is
    displaced.

    Honest about its limits: it needs a peer at the recorded feature, it sees nothing
    in a window where only rain fell, and a bed irrigated on the same timer as another
    is indistinguishable from it.
    """
    def unknown(key, params=None, **kw):
        params = params or {}
        return LateralFinding(device=device_id, at=at, verdict=INDETERMINATE,
                              reason=i18n.english(key, **params), key=key,
                              params=params, **kw)

    def moisture_stream(device):
        for ds in state.datastreams_of_sensor(device):
            if ds.kind is DatastreamKind.DERIVED and ds.observed_property == prop:
                return ds
        return None

    own_ds = moisture_stream(device_id)
    if own_ds is None:
        return unknown("lateral.no_moisture")
    installed = state.installation_of(device_id, at)
    if installed is None:
        return unknown("lateral.no_installation")
    since = at - window
    # Readings from before this installation belong to a different siting; see the
    # same clip in `assess_siting` for the false alarm that forced it.
    own = _wetting(state, own_ds.id, since, at, bin_s,
                   valid_from=installed.installed_at)
    events = sum(1 for x in own if x > 0)
    if events < 2:
        return unknown("lateral.too_few_events", {"events": events},
                       recorded_feature=installed.feature)

    by_feature: dict[UUID, float] = {}
    for other in state.devices:
        if other == device_id:
            continue
        other_ds = moisture_stream(other)
        other_install = state.installation_of(other, at)
        if other_ds is None or other_install is None:
            continue
        score = _best_lagged(own, _wetting(state, other_ds.id, since, at, bin_s,
                                           valid_from=other_install.installed_at),
                             max_lag_bins)
        feature = other_install.feature
        by_feature[feature] = max(by_feature.get(feature, -1.0), score)

    if installed.feature not in by_feature:
        return unknown("lateral.no_peer", recorded_feature=installed.feature)

    recorded_match = by_feature[installed.feature]
    best_feature = max(by_feature, key=by_feature.get)
    best_match = by_feature[best_feature]

    def name(feature):
        label = state.label_for(feature)
        return label.name if label is not None else str(feature)

    ranked = sorted(by_feature.items(), key=lambda kv: -kv[1])[:4]
    evidence = {"recorded_feature": str(installed.feature),
                "best_feature": str(best_feature),
                "recorded_match": round(recorded_match, 3),
                "best_match": round(best_match, 3),
                "matches": {name(f): round(s, 3) for f, s in ranked},
                "wetting_events": events, "margin": margin,
                "window_h": window.total_seconds() / 3600.0}
    common = dict(recorded_feature=installed.feature, best_feature=best_feature,
                  recorded_match=recorded_match, best_match=best_match,
                  evidence=evidence)
    if (best_feature != installed.feature and best_match >= min_match
            and best_match - recorded_match >= margin):
        params = {"best": name(best_feature), "best_match": best_match,
                  "recorded": name(installed.feature),
                  "recorded_match": recorded_match}
        return LateralFinding(device=device_id, at=at, verdict=DISPLACED,
                              reason=i18n.english("lateral.displaced", **params),
                              key="lateral.displaced", params=params, **common)
    others = [s for f, s in by_feature.items() if f != installed.feature]
    runner_up = max(others) if others else -1.0
    if recorded_match >= min_match and recorded_match - runner_up < margin:
        # The recorded bed matches — but so does another, about as well. That is what
        # a window of rain looks like: every bed wets together, so every bed matches,
        # and a probe moved out of its bed would still "match" the bed it left. A
        # confirmation earned by the weather is not a confirmation.
        params = {"recorded": name(installed.feature), "recorded_match": recorded_match,
                  "runner_up_match": runner_up}
        return LateralFinding(device=device_id, at=at, verdict=INDETERMINATE,
                              reason=i18n.english("lateral.undiscriminating", **params),
                              key="lateral.undiscriminating", params=params, **common)
    if recorded_match < min_match:
        # Nothing at the recorded feature moves with this probe, and nothing elsewhere
        # does convincingly either. That is an absence of evidence, not evidence of
        # being in place — typically because its only bed-mate is the one that moved.
        # The first version called this `consistent` with a match of -0.03.
        params = {"recorded": name(installed.feature), "recorded_match": recorded_match}
        return LateralFinding(device=device_id, at=at, verdict=INDETERMINATE,
                              reason=i18n.english("lateral.unconfirmed", **params),
                              key="lateral.unconfirmed", params=params, **common)
    params = {"recorded": name(installed.feature), "recorded_match": recorded_match}
    return LateralFinding(device=device_id, at=at, verdict=CONSISTENT,
                          reason=i18n.english("lateral.consistent", **params),
                          key="lateral.consistent", params=params, **common)
