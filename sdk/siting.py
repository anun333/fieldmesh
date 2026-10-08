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
"""
from __future__ import annotations

import datetime as _dt
import math
import statistics
from dataclasses import dataclass, field
from uuid import UUID

import i18n
import project as P
import vocab as V
from model import DatastreamKind

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
                  prop: str = V.SOIL_TEMPERATURE) -> SitingFinding:
    """Judge whether `device_id` sits at its recorded depth, as of `at`.

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

    own = _window_fit(state, stream.id, at, window)
    if own is None:
        return unknown("siting.too_few_readings", recorded_depth_m=recorded)
    if own.amplitude < min_amplitude_c:
        return unknown("siting.below_wave",
                       {"amplitude": own.amplitude, "floor": min_amplitude_c},
                       recorded_depth_m=recorded, fit=own)

    # --- calibrate on the peers ---------------------------------------------
    peers = []
    for other_id in state.devices:
        if other_id == device_id:
            continue
        other_stream = _temperature_stream(state, other_id, prop)
        if other_stream is None:
            continue
        other_install = state.installation_of(other_id, at)
        if other_install is None or other_install.depth_m is None:
            continue
        other_fit = _window_fit(state, other_stream.id, at, window)
        if other_fit is None or other_fit.amplitude < min_amplitude_c:
            continue
        peers.append((other_install.depth_m, other_fit))

    depths = {round(z, 3) for z, _ in peers}
    if len(peers) < 3 or len(depths) < 2:
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
