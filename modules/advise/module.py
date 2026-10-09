#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The advisor module's identity: its version, its data, its strings.

A layer-3 module (spec v0.1 §11: "models versioned"), so every report says which version
of the code and which data made it — enough to reproduce it, and to explain a changed
recommendation as a change of code, of data, or of the farm.
"""
from __future__ import annotations

import csv
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
import i18n  # noqa: E402

NAME = "advise"
VERSION = "0.1.0"
DATA = os.path.join(HERE, "data")
MANIFEST = os.path.join(DATA, "MANIFEST.csv")


def register_packs() -> None:
    """The module's own `advise.*` strings, merged over layer zero's packs."""
    i18n.register(os.path.join(HERE, "packs"), NAME)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def manifest() -> list[dict]:
    with open(MANIFEST, encoding="utf-8") as h:
        return list(csv.DictReader(line for line in h if not line.startswith("#")))


def manifest_problems() -> list[str]:
    """Every data file listed, every listed file present and unchanged since it was
    recorded. A data file edited without its manifest line is a report nobody can
    reproduce."""
    rows = manifest()
    listed = {r["file"] for r in rows}
    out = []
    for name in sorted(os.listdir(DATA)):
        if name != "MANIFEST.csv" and name not in listed:
            out.append(f"{name} is in data/ but not in MANIFEST.csv")
    for r in rows:
        path = os.path.join(DATA, r["file"])
        if not os.path.exists(path):
            out.append(f"{r['file']} is in MANIFEST.csv but not in data/")
        elif sha256(path) != r["sha256"]:
            out.append(f"{r['file']} changed since MANIFEST.csv recorded it")
    return out


def data_version() -> str:
    """A short hash of the manifest: changes whenever any data file does."""
    return sha256(MANIFEST)[:12]
