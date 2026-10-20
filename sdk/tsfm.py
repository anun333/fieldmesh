# SPDX-License-Identifier: Apache-2.0
"""A time-series foundation model as an optional source: Timestral (docs/notes/timestral.md).

Optional, twice over. It needs the `timestral` package (Apache-2.0), PyTorch and NumPy,
none of them fieldmesh's own dependencies; and its weights, on Hugging Face, are under a
"Modified MIT" licence that gives **no rights at all to anyone whose company, or whose
employer, had global revenue over $20 million in the preceding month**. A farm that uses
it says so (`load(accept_weights_licence=True)`); nothing here downloads or runs it
otherwise.

What it is used for, as tried on ISMN's records of six SCAN stations: forecasting a probe
gone silent from its neighbours, the rain and the air, for a person to read
(`tools/probe_forecast.py`; the soil advice does not take it, having lost the crop more
with it in the backtests), and seeing a probe drift from what they say it should read
(`modules/probewatch`). This module
reads the farm's state into the model's inputs, runs it, and writes the receipt a
decision resting on it carries: which model and weights, which series and hours, a hash of
the inputs, and how far the forecast moves with each input taken away. The model is
deterministic, so anyone holding the log can run it again and check.

Plain Python but for `Timestral`, which imports NumPy and PyTorch when it is loaded.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
from dataclasses import dataclass, field

from model import DatastreamKind, Usable
import vocab as V

HOUR = _dt.timedelta(hours=1)
LICENCE_NOTE = (
    "Timestral's weights are under Mistral AI's Modified MIT licence: no rights to anyone "
    "whose company, or whose employer, had global revenue over $20 million in the "
    "preceding month. Pass accept_weights_licence=True only if that is not you "
    "(https://huggingface.co/mistralai/Timestral-28M/blob/main/LICENSE).")
#: The model tried (docs/notes/timestral.md): the 209M was hardly better, seven times slower.
DEFAULT_MODEL = "mistralai/Timestral-28M"
#: Hours of a series' history the model reads, and of a probe's neighbours'.
CONTEXT_H = 1024
#: The files the model is loaded from (`TimestralForecaster.from_pretrained`): all a cache
#: needs, so a farm's offline cache need not hold the repository's README.
WEIGHT_FILES = ["config.json", "model.safetensors"]


class LicenceNotAccepted(Exception):
    """The weights' licence was not accepted (`LICENCE_NOTE`)."""


@dataclass
class Forecast:
    """Quantiles for each hour ahead: `quantiles[h]` a list, at `levels`."""
    hours: list
    quantiles: list
    levels: tuple

    def at(self, level: float) -> list:
        k = self.levels.index(level)
        return [q[k] for q in self.quantiles]

    @property
    def median(self) -> list:
        return self.at(0.5)


@dataclass
class Timestral:
    """A loaded model: its Hugging Face repo, the weights' commit, the package's version,
    and the forecaster. `forecast` takes plain lists."""
    repo: str
    weights: str
    package: str
    forecaster: object = field(repr=False)

    def forecast(self, target: list, covariates: list, horizon: int) -> tuple:
        """`(quantiles per hour ahead, levels)`: `target` the series' hours, None for a
        missing one; `covariates` rows over the same hours and the `horizon` after them."""
        import numpy as np
        t = np.array([[[math.nan if v is None else v for v in target]]], dtype=np.float64)
        kw = {}
        if covariates:
            kw["known_covariates"] = np.array(
                [[[math.nan if v is None else v for v in row] for row in covariates]], dtype=np.float64)
        fc = self.forecaster.forecast(t, prediction_length=horizon, **kw)
        q = np.asarray(fc.quantiles)[0, 0]
        return [list(map(float, row)) for row in q], tuple(fc.quantile_levels)


def load(repo: str = DEFAULT_MODEL, *, accept_weights_licence: bool = False,
         revision: str | None = None, offline: bool = False, threads: int = 4) -> Timestral:
    """The model, its weights from the Hugging Face cache (downloaded once unless
    `offline`), on `threads` threads. Refuses without `accept_weights_licence`."""
    if not accept_weights_licence:
        raise LicenceNotAccepted(LICENCE_NOTE)
    import os
    from importlib import metadata

    import torch
    from huggingface_hub import snapshot_download
    from timestral import TimestralForecaster
    torch.set_num_threads(threads)
    path = snapshot_download(repo, revision=revision, local_files_only=offline,
                             allow_patterns=WEIGHT_FILES)
    package = metadata.version("timestral")
    try:
        direct = json.loads(metadata.distribution("timestral").read_text("direct_url.json") or "{}")
        package += "@" + direct.get("vcs_info", {}).get("commit_id", "")[:12]
    except (FileNotFoundError, ValueError):
        pass
    return Timestral(repo=repo, weights=os.path.basename(path.rstrip("/")), package=package,
                     forecaster=TimestralForecaster.from_pretrained(path))


class Remote:
    """A model served by another process over a Unix socket (`tools/timestral/serve.py`),
    as a gateway without PyTorch reaches one in a container. Its `forecast` is a loaded
    model's; its repo, weights and package are the server's, for the receipt. One JSON
    message a line each way: `{"target", "covariates", "horizon"}`, missing hours null."""

    def __init__(self, path: str, timeout_s: float = 120.0) -> None:
        import socket
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(timeout_s)
        self._sock.connect(path)
        self._file = self._sock.makefile("rwb")
        about = self._call({"about": True})
        self.repo, self.weights, self.package = about["repo"], about["weights"], about["package"]

    def _call(self, message: dict) -> dict:
        self._file.write(json.dumps(message).encode() + b"\n")
        self._file.flush()
        reply = json.loads(self._file.readline())
        if "error" in reply:
            raise RuntimeError(f"the model's server: {reply['error']}")
        return reply

    def forecast(self, target: list, covariates: list, horizon: int) -> tuple:
        clean = lambda row: [None if v is None or (isinstance(v, float) and math.isnan(v)) else v
                             for v in row]
        reply = self._call({"target": clean(target), "covariates": [clean(r) for r in covariates],
                            "horizon": horizon})
        return reply["quantiles"], tuple(reply["levels"])

    def close(self) -> None:
        self._file.close()
        self._sock.close()


def hourly(state, datastream_id, first: _dt.datetime, hours: int, at: _dt.datetime) -> list:
    """A series' good readings by `at`, one an hour from `first`, the hour's mean, None
    for an hour with none."""
    sums: dict = {}
    for o in state.live_observations_of(datastream_id):
        if o.received_at > at or o.measured_at > at or not first <= o.measured_at < first + hours * HOUR:
            continue
        if not isinstance(o.result, (int, float)) or isinstance(o.result, bool):
            continue
        if state.quality_as_of(o.id, at)[0] is not Usable.GOOD:
            continue
        k = int((o.measured_at - first) / HOUR)
        s, n = sums.get(k, (0.0, 0))
        sums[k] = (s + float(o.result), n + 1)
    return [sums[k][0] / sums[k][1] if k in sums else None for k in range(hours)]


def soil_probes(state, feature, at: _dt.datetime) -> list:
    """`(datastream, depth_m)` of each calibrated soil-moisture series whose device is
    installed in `feature` at `at`, shallowest first."""
    out = []
    for ds in state.datastreams.values():
        if ds.kind is not DatastreamKind.DERIVED or ds.observed_property != V.SOIL_WATER:
            continue
        inst = state.installation_of(ds.sensor, at)
        if inst is not None and inst.feature == feature and inst.depth_m is not None:
            out.append((ds, inst.depth_m))
    return sorted(out, key=lambda p: (p[1], p[0].id.int))


def last_good(state, datastream_id, at: _dt.datetime, within_h: int):
    """The newest good reading of a series by `at`, within `within_h` hours: its hour."""
    newest = None
    for o in state.live_observations_of(datastream_id):
        if o.received_at > at or o.measured_at > at or o.measured_at < at - within_h * HOUR:
            continue
        if state.quality_as_of(o.id, at)[0] is Usable.GOOD and (newest is None or o.measured_at > newest):
            newest = o.measured_at
    return newest.replace(minute=0, second=0, microsecond=0) if newest else None


def run(model, state, target, covariates: dict, context_end: _dt.datetime, horizon: int,
        at: _dt.datetime, *, context_h: int = CONTEXT_H, ablate: bool = True) -> tuple:
    """Forecast `target` (a datastream id) for the `horizon` hours after `context_end`,
    from its `context_h` hours before it and `covariates` (`{name: datastream id}`, read
    through the horizon, so far as they have read by `at`). Returns `(Forecast, receipt)`."""
    first = context_end - context_h * HOUR
    target_rows = hourly(state, target, first, context_h, at)
    rows = {name: hourly(state, ds, first, context_h + horizon, at) for name, ds in covariates.items()}
    q, levels = model.forecast(target_rows, list(rows.values()), horizon)
    hours = [context_end + h * HOUR for h in range(horizon)]
    forecast = Forecast(hours, q, levels)
    moved = {}
    if ablate:
        for name in rows:
            others = [r for n, r in rows.items() if n != name]
            qa, _ = model.forecast(target_rows, others, horizon)
            mid = levels.index(0.5)
            moved[name] = round(sum(abs(a[mid] - b[mid]) for a, b in zip(q, qa)) / horizon, 4)
    digest = hashlib.sha256(json.dumps({"target": target_rows, "covariates": rows},
                                       sort_keys=True).encode()).hexdigest()
    receipt = {"model": getattr(model, "repo", type(model).__name__),
               "weights": getattr(model, "weights", None), "package": getattr(model, "package", None),
               "target": str(target), "covariates": {n: str(d) for n, d in covariates.items()},
               "context": [first.isoformat(), context_end.isoformat()], "horizon_h": horizon,
               "inputs_sha256": digest, "moved_by": moved}
    return forecast, receipt
