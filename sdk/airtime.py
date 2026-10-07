#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""LoRa airtime and the duty-cycle budget (spec v0.1 §5.2).

§5.2 says LoRa airtime is the binding limit and that a link driver supplies the real
budget. This is that arithmetic, in the SDK rather than in a measurement script,
because a node has to obey it at runtime: a fleet that reports too often must fail
loudly here before anyone buys a radio, not quietly exceed a legal limit in a field.

The formula is the Semtech SX127x datasheet's (§4.1.1.7). Both reference points are
hand-derived and pinned to the microsecond in `test_airtime.py`, because every claim
about what a node can send rests on it.

The EU868 numbers are the worst case worth designing against: a 1% duty-cycle
sub-band is about 36 seconds of transmit time per hour, per sub-band, per device.
EU868 also defines 0.1% and 10% sub-bands, and LoRaWAN deployments add a network
fair-use policy on top, so 36 s is the common case and not the limit — take the real
one from the link driver.
"""
from __future__ import annotations

import math

#: LoRaWAN PHY overhead: MHDR + DevAddr + FCtrl + FCnt + FPort + MIC.
LORAWAN_OVERHEAD = 13

#: EU868 maximum application payload by data rate (LoRaWAN regional parameters).
MAX_APP_PAYLOAD = {0: 51, 1: 51, 2: 51, 3: 115, 4: 222, 5: 222}
SF_FOR_DR = {0: 12, 1: 11, 2: 10, 3: 9, 4: 8, 5: 7}

#: 1% of an hour, per sub-band per device.
DUTY_CYCLE_BUDGET_S = 36.0


def time_on_air(payload_bytes: int, sf: int, *, bw_hz: int = 125_000,
                coding_rate: int = 1, preamble: int = 8, crc: int = 1,
                explicit_header: bool = True) -> float:
    """Time on air in seconds for a LoRa frame.

    `payload_bytes` is the PHY payload — for LoRaWAN that is the application payload
    plus `LORAWAN_OVERHEAD`.

    The low-data-rate optimisation is mandatory on 125 kHz at SF11 and SF12, and it
    costs airtime, which is why the jump from SF10 to SF11 is worse than the
    spreading factor alone would suggest.
    """
    t_sym = (2 ** sf) / bw_hz
    t_preamble = (preamble + 4.25) * t_sym
    low_rate_opt = 1 if sf >= 11 else 0
    numerator = (8 * payload_bytes - 4 * sf + 28 + 16 * crc
                 - (0 if explicit_header else 20))
    denominator = 4 * (sf - 2 * low_rate_opt)
    payload_symb = 8 + max(math.ceil(numerator / denominator) * (coding_rate + 4), 0)
    return t_preamble + payload_symb * t_sym


def frame_airtime(app_payload_bytes: int, *, dr: int = 0) -> float:
    """Airtime for an application payload at an EU868 data rate."""
    return time_on_air(app_payload_bytes + LORAWAN_OVERHEAD, SF_FOR_DR[dr])


class DutyCycle:
    """A rolling duty-cycle budget a node must stay inside.

    §5.2's limit is not advice. A node that exceeds it is breaking a radio
    regulation, so `allows` is a precondition and not a hint — the node delays the
    message and keeps it buffered (§5.3), which costs latency rather than data.
    """

    __slots__ = ("budget_s", "window_s", "_sent")

    def __init__(self, *, budget_s: float = DUTY_CYCLE_BUDGET_S,
                 window_s: float = 3600.0):
        self.budget_s = budget_s
        self.window_s = window_s
        self._sent: list[tuple[float, float]] = []   # (when, airtime)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        self._sent = [(t, a) for (t, a) in self._sent if t > cutoff]

    def used(self, now: float) -> float:
        self._prune(now)
        return sum(a for (_, a) in self._sent)

    def remaining(self, now: float) -> float:
        return max(0.0, self.budget_s - self.used(now))

    def allows(self, airtime_s: float, now: float) -> bool:
        return airtime_s <= self.remaining(now)

    def record(self, airtime_s: float, now: float) -> None:
        self._prune(now)
        self._sent.append((now, airtime_s))
