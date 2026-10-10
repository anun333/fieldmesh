<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Security

fieldmesh will hold farms' data and, later, command pumps and valves. A flaw in it can expose
a farm's records or, eventually, act on its equipment, so please report one privately.

**How:** use GitHub's private vulnerability reporting — the **Report a vulnerability** button
under this repository's Security tab. Please do not open a public issue for a security problem.

**What is in scope:** the SDK (`sdk/`), especially the gateway, wire format, sharing grants and
erasure (`erasure.py`); the reference server (`server/`); the modules (`modules/`).

**What to expect:** an acknowledgement within a week, and an advisory credited to you, if you
wish, once a fix is out.

The current state, plainly: the first release ships observations only — no commands — and the
HTTP server is single-threaded, read-only and has not been hardened for the internet
([README.md](README.md), "What is not done").
