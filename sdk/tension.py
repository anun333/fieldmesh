# SPDX-License-Identifier: Apache-2.0
"""Soil water tension: a Watermark sensor's resistance as the pull the roots must make.

A moisture probe says how much water the soil holds; a tension sensor says how hard it
holds it, which means the same to a root in sand or in clay. fieldmesh records it as ODM2's
water potential (`vocab.SOIL_WATER_POTENTIAL`), in kPa and never above zero; a sensor that
reports tension, a positive number, declares its raw series in kPa and is calibrated with
`a = -1` (§4).

**The Irrometer Watermark** (a granular-matrix sensor) is read as an electrical resistance,
which rises as the soil dries and falls as it warms. Shock, Barnum and Seddigh (1998) fitted
tension to resistance and soil temperature,

    kPa = (4.093 + 3.213 R) / (1 − 0.009733 R − 0.01205 T),   R in kΩ, T in °C,

for 10 to 75 kPa, as Thompson et al. (2005, Irrigation Science 24, doi:10.1007/s00271-005-0009-5)
print it. They found it accurate from 30 to 80 kPa, less so from 10 to 30, and useless
wetter than 10. So a reading outside 10 to 75 kPa is not converted: `watermark_kpa` says
None, and the edge sends nothing rather than a number the equation cannot vouch for.

The conversion belongs where the resistance and the soil's temperature are both known,
on the node; this is the reference its firmware is checked against (`test_tension.py`).
"""
from __future__ import annotations

#: The tensions Shock et al. calibrated, kPa.
CALIBRATED_KPA = (10.0, 75.0)


def watermark_kpa(r_kohm: float, soil_c: float) -> float | None:
    """A Watermark's tension, kPa (positive), from its resistance in kΩ and the soil's
    temperature in °C, or None outside the calibrated 10 to 75 kPa."""
    if r_kohm <= 0:
        return None
    denominator = 1.0 - 0.009733 * r_kohm - 0.01205 * soil_c
    if denominator <= 0:
        return None
    kpa = (4.093 + 3.213 * r_kohm) / denominator
    lo, hi = CALIBRATED_KPA
    return kpa if lo <= kpa <= hi else None
