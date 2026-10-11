<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Security

fieldmesh will hold farms' data and, later, command pumps and valves. A flaw in it can expose
a farm's records or, eventually, act on its equipment, so please report one privately.

**How:** use GitHub's private vulnerability reporting — the **Report a vulnerability** button
under this repository's Security tab. Please do not open a public issue for a security problem.

**What is in scope:** the SDK (`sdk/`), especially the gateway, wire format, sharing grants,
erasure (`erasure.py`) and the module host (`modhost.py`), which decides what each module may
read and write; the reference server (`server/`); the modules (`modules/`), above all the
notifier, the one module given the network, which holds phone numbers and acts on SMS
replies and ntfy button presses, and the board, which serves a page; and the systemd units
(`deploy/`).

**What to expect:** an acknowledgement within a week, and an advisory credited to you, if you
wish, once a fix is out.

The current state, plainly: the first release ships observations only, no commands. The
HTTP server is read-only and asks every request for a token. It answers a sharing grantee
from what their grant covers and nothing else, refuses to listen beyond the machine without
TLS, and rate-limits and times out its clients, but nobody outside has tried to break it.
What has not been checked, the sandbox's filesystem protections under the system manager
included, is listed in [docs/UNTESTED.md](docs/UNTESTED.md).
