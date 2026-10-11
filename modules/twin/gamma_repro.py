#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The negative CO2 compensation point, on GreenLight's own test data (Q28; README).

    python3 -I gamma_repro.py        # in this module's environment (requirements.txt)

Runs the Vanthoor (2011) greenhouse and crop with the Katzin (2021) controls on the
Bleiswijk weather GreenLight ships, three days each: stock, without CO2 enrichment,
without enrichment or heating, and the last with the canopy-to-leaf ratio capped at 1.
Prints the range of `gamma`, LAI and inside CO2 for each. Below one leaf layer the stock
formula's `gamma` is negative, which puts a pole in gross photosynthesis at a leaf CO2
of −2·gamma.
"""
from __future__ import annotations

import contextlib
import csv
import io
import os
import re
import sys
import tempfile
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import twin as T  # noqa: E402


def run(label: str, over: dict, days: int = 3) -> None:
    from importlib import resources
    from pathlib import PurePath
    import greenlight
    d = resources.files("greenlight") / "models" / "katzin_2021"
    base = d / "definition" / "vanthoor_2011"
    weather = str(PurePath(d / "input_data" / "test_data" / "Bleiswijk_from_20091020.csv"))
    prompt = [str(PurePath(base / "greenhouse_vanthoor_2011_chapter_8.json")),
              str(PurePath(base / "crop_vanthoor_2011_chapter_9_simplified.json")),
              str(PurePath(base / "controls_katzin_2021.json")), weather,
              {"X": {k: {"definition": v} for k, v in over.items()}},
              {"options": {"t_start": "0", "t_end": str(days * 86400)}}]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out.csv")
        buf = io.StringIO()
        with warnings.catch_warnings(), contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            warnings.simplefilter("ignore")
            greenlight.GreenLight(base_path="", input_prompt=prompt, output_path=out).run()
        failed = re.search(r"Simulation failed at time t=([0-9.]+)", buf.getvalue())
        with open(out, encoding="utf-8-sig") as h:
            rows = [r for r in csv.DictReader(h) if r["Time"].replace(".", "").isdigit()]
    g = [float(r["gamma"]) for r in rows]
    lai = [float(r["lai"]) for r in rows]
    co2 = [float(r["co2InPpm"]) for r in rows]
    status = f"ran {days} days" if not failed else f"failed at {float(failed.group(1)) / 3600:.2f} h"
    print(f"{label:42} {status:16} gamma {min(g):7.1f} to {max(g):5.1f}   LAI {min(lai):.2f}-{max(lai):.2f}"
          f"   CO2 {min(co2):.0f}-{max(co2):.0f} ppm", flush=True)


def main() -> int:
    unheated = {"phiExtCo2": "0", "pBoil": "0"}
    run("stock", {})
    run("no CO2 enrichment", {"phiExtCo2": "0"})
    run("no CO2 enrichment, no heating", unheated)
    run("the same, ratio capped at 1", {**unheated, **T.FORMULAS})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
