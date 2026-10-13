# SPDX-License-Identifier: AGPL-3.0-or-later
"""A bed's own field capacity, read off its soil's retention curve.

Beside a moisture probe, at the same depth, a tension sensor gives each hour a point on the
soil's water retention curve: this much water, held this hard. Field capacity is
conventionally the water held at a tension of 33 kPa (a third of a bar; nearer 10 kPa in a
sand), so with points around it, it is read off the curve rather than inferred from
drain-downs (`soilwater.learned_capacity`), and it needs no soaking to read it.

Over the tensions a Watermark is calibrated for (10 to 75 kPa, `sdk/tension.py`), water
content falls close to linearly with the logarithm of tension, so the points are fitted as

    θ = a + b · ln(tension),   b < 0,

and field capacity is θ at `capacity_kpa`. The fit needs `MIN_PAIRS` points spanning a
factor of `MIN_SPAN` in tension, and `capacity_kpa` within `REACH` of the tensions seen: a
bed kept wetter than 15 kPa all summer has not shown where 33 kPa is.
"""
from __future__ import annotations

import math

CAPACITY_KPA = 33.0
MIN_PAIRS = 24
MIN_SPAN = 2.0
REACH = 1.5
CALIBRATED_KPA = (10.0, 75.0)


def capacity_from_tension(pairs: list, capacity_kpa: float = CAPACITY_KPA):
    """`{"field_capacity", "pairs", "kpa_low", "kpa_high", "slope"}` from `[(tension kPa,
    θ)]`, or None: too few points, too narrow a span, a curve that does not dry as tension
    rises, or `capacity_kpa` beyond the points' reach."""
    lo, hi = CALIBRATED_KPA
    points = [(t, w) for t, w in pairs if lo <= t <= hi]
    if len(points) < MIN_PAIRS:
        return None
    seen_lo, seen_hi = min(t for t, _ in points), max(t for t, _ in points)
    if seen_hi / seen_lo < MIN_SPAN:
        return None
    if not seen_lo / REACH <= capacity_kpa <= seen_hi * REACH:
        return None
    xs = [math.log(t) for t, _ in points]
    ys = [w for _, w in points]
    n = len(points)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    if b >= 0:
        return None
    a = my - b * mx
    return {"field_capacity": a + b * math.log(capacity_kpa), "pairs": n,
            "kpa_low": round(seen_lo, 1), "kpa_high": round(seen_hi, 1), "slope": b}
