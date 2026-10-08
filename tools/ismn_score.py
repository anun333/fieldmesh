#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Score layer zero's health checks against ISMN's quality flags (spec v0.1 §9.2).

The International Soil Moisture Network keeps flagged readings rather than deleting
them, so a series comes with an independent judgement on every value. Running our §4.2
checks over the same values and comparing is the strongest validation available
without hardware: real sensors, real faults, someone else's labels.

**This measures agreement, not correctness.** Where we and ISMN disagree, either could
be right — their checks use ancillary data ours do not, and ours use thresholds theirs
do not. The report says "agreement" and never "accuracy".

## The flag mapping is provisional

From the ISMN documentation and the HESS 2021 paper, *not yet from the data*. The
research note that recommended this tool said to verify the vocabulary against a real
download before relying on it, and this module records which families it expects so
that an unexpected one is reported loudly rather than counted as clean.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from collections import Counter
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "sdk"))
import checks as C  # noqa: E402
import log as L  # noqa: E402
import project as P  # noqa: E402
import vocab as V  # noqa: E402
from ids import uuid7  # noqa: E402
from model import (ClockQuality, Datastream, DatastreamKind,  # noqa: E402
                   Observation, QualityFlag)

UTC = _dt.timezone.utc

#: ISMN flag -> (family, the §4.2 flag that would be the counterpart, or None).
#: PROVISIONAL — see the module docstring.
ISMN_FLAGS = {
    "G": ("good", None),
    "C01": ("range", QualityFlag.OUT_OF_RANGE),     # below 0 m3/m3
    "C02": ("range", QualityFlag.OUT_OF_RANGE),     # above 0.6 m3/m3
    "C03": ("range", QualityFlag.OUT_OF_RANGE),     # above saturation
    "D01": ("ancillary", None),     # negative soil temperature
    "D02": ("ancillary", None),     # negative air temperature
    "D03": ("ancillary", None),     # modelled soil temperature below zero
    "D04": ("ancillary", None),     # rise without precipitation (in situ)
    "D05": ("ancillary", None),     # rise without precipitation (modelled)
    "D06": ("spike", QualityFlag.RATE_EXCEEDED),
    "D07": ("break", QualityFlag.RATE_EXCEEDED),    # negative break
    "D08": ("break", QualityFlag.RATE_EXCEEDED),    # positive break
    "D09": ("plateau", QualityFlag.STUCK),          # low constant values
    "D10": ("plateau", QualityFlag.STUCK),          # saturated plateau
}

#: Our thresholds, not ISMN's. Scoring the range check with their own 0 and 0.6 would
#: make range agreement true by construction and tell us nothing.
OUR_THRESHOLDS = {"min": 0.02, "max": 0.46, "flat_seconds": 18 * 3600, "flat_n": 4,
                  "max_rate_per_s": 0.00015}


def families(flag_text: str) -> set[str]:
    """ISMN flags on one reading, possibly several, as families. Unknown ones are
    returned as `unknown:<flag>` so a vocabulary surprise is visible, not silent."""
    out = set()
    for part in (flag_text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        known = ISMN_FLAGS.get(part)
        out.add(known[0] if known else f"unknown:{part}")
    return out or {"unknown:<none>"}


@dataclass
class Score:
    readings: int = 0
    by_family: Counter = field(default_factory=Counter)
    caught: Counter = field(default_factory=Counter)
    ours_on_good: Counter = field(default_factory=Counter)

    def agreement(self, family: str) -> float | None:
        n = self.by_family.get(family, 0)
        return self.caught.get(family, 0) / n if n else None


def score_series(rows, *, interval_s: float = 3600.0,
                 thresholds: dict | None = None) -> Score:
    """Run the §4.2 suite over one sensor's `(utc time, value, ismn flags)` rows.

    Readings land on a raw datastream exactly as ISMN published them (m3/m3), the way
    `csv_import` would land them, and each is assessed in time order with the history
    before it — which is how the gateway sees a series arrive.
    """
    thresholds = dict(thresholds or OUR_THRESHOLDS)
    ds = Datastream(id=uuid7(), thing=uuid7(), sensor=uuid7(),
                    observed_property=V.SOIL_WATER, feature=uuid7(),
                    kind=DatastreamKind.RAW, unit="m3/m3",
                    expected_interval=interval_s, thresholds=thresholds)
    log = L.Log()
    log.append_record(ds)
    state = P.state_from_log(log)
    score = Score()
    received = _dt.datetime.now(tz=UTC)
    for when, value, flag_text in sorted(rows, key=lambda r: r[0]):
        if value is None:
            continue
        obs = Observation(id=uuid7(), datastream=ds.id, measured_at=when,
                          measured_at_uncertainty=interval_s / 2, received_at=received,
                          result=value, clock_quality=ClockQuality.NETWORK)
        state.add(obs)
        ours = C.assess(state, obs, asserted_at=received).flags
        score.readings += 1
        for family in families(flag_text):
            score.by_family[family] += 1
            expected = next((flag for code, (fam, flag) in ISMN_FLAGS.items()
                             if fam == family and flag is not None), None)
            if family == "good":
                for flag in ours:
                    score.ours_on_good[flag.value] += 1
            elif expected is not None and expected in ours:
                score.caught[family] += 1
    return score
