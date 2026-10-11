#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The farm's board: one read-only page of what stands now — layer 4 (spec v0.1 §11).

The thinnest slice of an app. A notification says something happened; the board says
what is still the case: which alerts stand, who was told and whether anyone said
"on it", what the modules advise today, and what cleared since yesterday. It is one
static page per language, in large type, readable in sun and with gloves on, with no
script it needs, nothing loaded from elsewhere, and nothing on it a person can change.

**It says when it was made.** A board that stopped updating looks exactly like a quiet
farm, which is the failure §4.2 forbids for sensors ("no news is not good news"). So
the page carries the minute it was made, refreshes itself every minute, and says so
plainly when it is more than ten minutes old: the farm's computer, or the board, has
stopped.

Like the notifier it reads any module's decisions without importing any module (§7.7,
`rules.render`), and it never writes the log. Its grant reads decisions, notifications
and acknowledgements, and the names of what decisions are about; nothing else.

    python3 modules/board/board.py --socket /run/fieldmesh/modules.sock \\
        --config board.json --out /var/lib/fieldmesh-board --serve 127.0.0.1:8080
"""
from __future__ import annotations

import base64
import datetime as _dt
import glob
import hashlib
import html
import ipaddress
import json
import os
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, os.pardir, "sdk"))
sys.path.insert(0, os.path.join(HERE, os.pardir, "rules"))
import i18n  # noqa: E402
import rules as R  # noqa: E402

for _packs in sorted(glob.glob(os.path.join(HERE, os.pardir, "*", "packs"))):
    try:
        i18n.register(_packs, os.path.basename(os.path.dirname(_packs)))
    except ValueError as _exc:
        print(f"board: a language pack was skipped: {_exc}", file=sys.stderr)

KINDS = ("decision", "notification", "acknowledgement")
#: How long a cleared alert stays on the board.
CLEARED_FOR = _dt.timedelta(hours=24)
#: Older than this, the page says it has stopped updating.
STALE_AFTER_S = 600


@dataclass(frozen=True)
class Board:
    farm: str
    timezone: str = "UTC"
    languages: tuple = ("en",)
    #: Names of the people acknowledgements and notifications name by id. Names only:
    #: how to reach them is the notifier's business.
    people: dict = field(default_factory=dict)
    #: The series whose newest reading the page shows — troughs, beds, the tunnel's air —
    #: by datastream id. The board's grant must name them.
    series: tuple = ()

    @classmethod
    def from_json(cls, doc: dict) -> "Board":
        from uuid import UUID
        return cls(doc.get("farm", ""), doc.get("timezone", "UTC"),
                   tuple(doc.get("languages", ("en",))), dict(doc.get("people", {})),
                   tuple(UUID(s) for s in doc.get("series", ())))

    def local(self, at: _dt.datetime) -> _dt.datetime:
        from zoneinfo import ZoneInfo
        return at.astimezone(ZoneInfo(self.timezone))


# ------------------------------------------------------------------- what stands

@dataclass
class Item:
    decision_id: str
    decision: dict
    told: list = field(default_factory=list)         # (person id, via, at, outcome)
    acked: tuple | None = None                       # (person id, at)
    cleared_at: _dt.datetime | None = None


def snapshot(events, at: _dt.datetime) -> dict:
    """What the board shows at `at`, from the events alone: `{"alerts": [...],
    "standing": [...], "cleared": [...]}`, each a list of `Item`, newest first.

    An *alert* is a standing answer someone was sent; the rest of what stands —
    today's advice, a status — is *standing*. Answers past their `valid_until` are gone.
    """
    decisions, told, acks = [], {}, {}
    for e in events:
        p = e.payload
        if e.kind == "decision" and "evaluated_at" in p:
            if _dt.datetime.fromisoformat(p["evaluated_at"]) <= at:
                decisions.append((str(e.id), p))
        elif e.kind == "notification" and p.get("decision"):
            if _dt.datetime.fromisoformat(p["at"]) <= at:
                told.setdefault(p["decision"], []).append(
                    (p.get("person"), p.get("via"), _dt.datetime.fromisoformat(p["at"]),
                     p.get("outcome"), p.get("reason")))
        elif e.kind == "acknowledgement" and p.get("decision"):
            when = _dt.datetime.fromisoformat(p["at"])
            if when <= at and p["decision"] not in acks:
                acks[p["decision"]] = (p.get("by"), when)
    by_payload = {id(p): d for d, p in decisions}
    standing = R.standing([p for _, p in decisions], at)
    alerts, other = [], []
    for p in standing.values():
        if not p.get("alert") or not p.get("message"):
            continue
        d = by_payload[id(p)]
        item = Item(d, p, [t for t in told.get(d, []) if t[4] in ("raised", "escalated")],
                    acks.get(d))
        (alerts if item.told else other).append(item)
    # Cleared: an alert answered "no longer" on its own topic within the last day.
    cleared, last = [], {}
    for d, p in decisions:
        key = (p.get("module"), R.topic_of(p))
        prev = last.get(key)
        when = _dt.datetime.fromisoformat(p["evaluated_at"])
        stale = prev[1].get("valid_until") if prev is not None else None
        if prev is not None and prev[1].get("alert") and not p.get("alert") \
                and at - when <= CLEARED_FOR \
                and not (stale and _dt.datetime.fromisoformat(stale) <= when):
            cleared.append(Item(prev[0], prev[1], acked=acks.get(prev[0]), cleared_at=when))
        last[key] = (d, p)
    newest = lambda i: i.cleared_at or _dt.datetime.fromisoformat(i.decision["evaluated_at"])
    return {"alerts": sorted(alerts, key=newest, reverse=True),
            "standing": sorted(other, key=newest, reverse=True),
            "cleared": sorted(cleared, key=newest, reverse=True)}


def latest_readings(state, series, at: _dt.datetime) -> list[dict]:
    """The newest reading of each series received by `at`, with its quality as asserted
    by then and whether it is late: more than three of its intervals old."""
    from model import Usable
    out = []
    for ds_id in series:
        ds = state.datastreams.get(ds_id)
        row = {"datastream": ds_id, "found": ds is not None}
        if ds is None:
            out.append(row)
            continue
        rows = [o for o in state.live_observations_of(ds_id)
                if o.received_at <= at and o.measured_at <= at
                and isinstance(o.result, (int, float)) and not isinstance(o.result, bool)]
        row["unit"] = ds.unit
        if not rows:
            out.append({**row, "value": None})
            continue
        latest = max(rows, key=lambda o: o.measured_at)
        usable, flags = state.quality_as_of(latest.id, at)
        every = ds.expected_interval or ds.max_latency or 3600.0
        age_h = (at - latest.measured_at).total_seconds() / 3600.0
        out.append({**row, "value": float(latest.result), "measured_at": latest.measured_at,
                    "good": usable is Usable.GOOD, "flags": sorted(f for f in flags),
                    "late": age_h * 3600.0 > 3 * every, "age_h": age_h})
    return out


def prune(events: list, at: _dt.datetime) -> list:
    """What the board still needs of what it has read: on each question its last two
    answers (the standing one and what it replaced, for "cleared"), every decision of the
    last day, and what was sent and acknowledged about those. A board that runs for
    years holds days of decisions, not years."""
    decisions = [e for e in events if e.kind == "decision" and "evaluated_at" in e.payload]
    by_topic = {}
    for e in decisions:
        by_topic.setdefault((e.payload.get("module"), R.topic_of(e.payload)), []).append(e)
    keep = {str(e.id) for es in by_topic.values() for e in es[-2:]}
    since = at - CLEARED_FOR - _dt.timedelta(hours=2)
    keep |= {str(e.id) for e in decisions
             if _dt.datetime.fromisoformat(e.payload["evaluated_at"]) >= since}
    return [e for e in events if (str(e.id) in keep if e.kind == "decision"
                                   else e.payload.get("decision") in keep)]


# ---------------------------------------------------------------------- render

#: Units as a page shows them; a fraction — a trough's level, a soil's water — as a
#: percentage.
SYMBOLS = {"Cel": "°C", "[degF]": "°F", "%": "%", "mm": "mm", "m/s": "m/s", "kPa": "kPa",
           "L": "L", "V": "V"}
FRACTIONS = {"1", "cm3/cm3", "m3/m3"}

STYLE = """
:root{--ink:#111;--paper:#fff;--line:#999;--alert:#b00020;--ok:#1b5e20;--quiet:#555}
@media (prefers-color-scheme:dark){:root{--ink:#f2f2f2;--paper:#000;--line:#777;--alert:#ff6b6b;--ok:#7bd88f;--quiet:#bbb}}
*{box-sizing:border-box}
body{margin:0;padding:1rem;background:var(--paper);color:var(--ink);font:1.25rem/1.45 system-ui,sans-serif;max-width:44rem}
h1{font-size:1.8rem;margin:0 0 .25rem}
h2{font-size:1.35rem;margin:1.75rem 0 .5rem;border-bottom:2px solid var(--line)}
article{border:3px solid var(--line);border-radius:.5rem;padding:.75rem 1rem;margin:.75rem 0}
article.alert{border-color:var(--alert)}
article.alert.acked{border-color:var(--ok)}
p{margin:.35rem 0}
.meta{color:var(--quiet);font-size:1.05rem}
.state{font-weight:700}
.alert .state{color:var(--alert)}
.acked .state{color:var(--ok)}
#stale{border:3px solid var(--alert);color:var(--alert);font-weight:700;padding:.75rem;border-radius:.5rem}
nav a{margin-right:1rem;color:var(--ink)}
""".strip()

#: Shows the stale warning once the page is older than it should be. The page says
#: when it was made without this; the script only says it louder.
SCRIPT = ("(function(){var b=document.body,m=Date.parse(b.dataset.made),"
          "s=document.getElementById('stale');function c(){if(Date.now()-m>"
          f"{STALE_AFTER_S * 1000}){{s.hidden=false}}}}c();setInterval(c,30000)}})();")
INDEX_SCRIPT = ("(function(){var l=document.body.dataset.langs.split(' '),"
                "w=(navigator.languages||[navigator.language||'en']);"
                "for(var i=0;i<w.length;i++){var p=w[i].split('-')[0];"
                "if(l.indexOf(p)>=0){location.replace('index.'+p+'.html');return}}})();")


def _hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def _csp(script: str) -> str:
    return (f"default-src 'none'; style-src {_hash(STYLE)}; script-src {_hash(script)}; "
            "base-uri 'none'; form-action 'none'")


def _head(lang: str, direction: str, title: str, script: str, *, refresh: bool) -> str:
    return ("<!doctype html>\n"
            f'<html lang="{html.escape(lang)}" dir="{direction}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{_csp(script)}">'
            '<meta name="referrer" content="no-referrer">'
            + ('<meta http-equiv="refresh" content="60">' if refresh else "")
            + f"<title>{html.escape(title)}</title><style>{STYLE}</style></head>")


def render(board: Board, snap: dict, language: str, at: _dt.datetime, state=None) -> str:
    """One language's page. Everything a farm or a module wrote is escaped."""
    t = i18n.Translator(language)
    e = html.escape

    def say(key, **params):
        return e(str(t.text(key, **params)))

    def clock(when):
        local = board.local(when)
        today = board.local(at).date()
        return local.strftime("%H:%M") if local.date() == today else local.strftime("%Y-%m-%d %H:%M")

    def who(person_id):
        return board.people.get(person_id) or str(t.text("board.someone"))

    def said(item):
        return e(R.render(item.decision, language, state) or item.decision.get("rule", "?"))

    out = [_head(language, t.direction, board.farm or "fieldmesh", SCRIPT, refresh=True),
           f'<body data-made="{e(at.isoformat())}">',
           f"<header><h1>{e(board.farm or 'fieldmesh')}</h1>",
           f'<p class="meta">{say("board.made", time=clock(at))}</p>',
           f'<p id="stale" hidden>{say("board.stale", minutes=STALE_AFTER_S / 60)}</p>']
    if len(board.languages) > 1:
        links = []
        for tag in board.languages:
            pack = i18n.load(tag)
            links.append(f'<a href="index.{e(tag)}.html" hreflang="{e(tag)}">'
                         f"{e(pack.native_name if pack else tag)}</a>")
        out.append(f"<nav>{''.join(links)}</nav>")
    out.append("</header><main>")

    out.append(f"<section><h2>{say('board.alerts')}</h2>")
    if not snap["alerts"]:
        out.append(f'<p class="meta">{say("board.no_alerts")}</p>')
    for item in snap["alerts"]:
        since = _dt.datetime.fromisoformat(item.decision["evaluated_at"])
        cls = "alert acked" if item.acked else "alert"
        state_line = (say("board.acked", who=who(item.acked[0]), time=clock(item.acked[1]))
                      if item.acked else say("board.nobody_yet"))
        reached = [f"{e(who(p))} ({say('board.via.' + (via or 'none'))} {clock(when)})"
                   for p, via, when, outcome, _ in item.told if outcome == "sent"]
        out.append(f'<article class="{cls}"><p>{said(item)}</p>'
                   f'<p class="state">{state_line}</p>'
                   f'<p class="meta">{say("board.since", time=clock(since))}'
                   + (f" · {say('board.told')} {', '.join(reached)}" if reached else "")
                   + "</p></article>")
    out.append("</section>")

    if snap.get("readings"):
        out.append(f"<section><h2>{say('board.readings')}</h2>")
        for r in snap["readings"]:
            entity = r["datastream"]
            label = state.label_for(entity, language) if state is not None and r["found"] else None
            name = e(label.name if label is not None else str(entity)[:8])
            if not r["found"] or r.get("value") is None:
                out.append(f'<article><p><strong>{name}</strong></p>'
                           f'<p class="state">{say("board.no_reading")}</p></article>')
                continue
            # Numbers through the pack, so each language writes its own decimal mark.
            shown = (say("board.percent", value=r["value"] * 100.0) if r["unit"] in FRACTIONS
                     else say("board.value", value=r["value"],
                              unit=SYMBOLS.get(r["unit"], r["unit"] or "")))
            notes = []
            if not r["good"]:
                from model import QualityFlag
                names = ", ".join(str(t.enum(QualityFlag(f))) for f in r["flags"]) or "?"
                notes.append(say("board.flagged", flags=names))
            if r["late"]:
                notes.append(say("board.late_reading", hours=r["age_h"]))
            cls = ' class="alert"' if notes else ""
            out.append(f'<article{cls}><p><strong>{name}</strong>: {shown}'
                       f' <span class="meta">· {clock(r["measured_at"])}</span></p>'
                       + "".join(f'<p class="state">{n}</p>' for n in notes) + "</article>")
        out.append("</section>")

    if snap["standing"]:
        out.append(f"<section><h2>{say('board.standing')}</h2>")
        for item in snap["standing"]:
            since = _dt.datetime.fromisoformat(item.decision["evaluated_at"])
            out.append(f'<article><p>{said(item)}</p>'
                       f'<p class="meta">{say("board.since", time=clock(since))}</p></article>')
        out.append("</section>")

    if snap["cleared"]:
        out.append(f"<section><h2>{say('board.cleared')}</h2>")
        for item in snap["cleared"]:
            out.append(f'<article><p class="meta">{say("board.cleared_at", time=clock(item.cleared_at))}'
                       f"</p><p>{said(item)}</p></article>")
        out.append("</section>")

    out.append(f"</main><script>{SCRIPT}</script></body></html>\n")
    return "".join(out)


def render_index(board: Board) -> str:
    """Sends a browser to its own language; without scripts, a list to choose from."""
    e = html.escape
    links = "".join(f'<li><a href="index.{e(tag)}.html" hreflang="{e(tag)}">'
                    f"{e(i18n.load(tag).native_name if i18n.load(tag) else tag)}</a></li>"
                    for tag in board.languages)
    return (_head(board.languages[0], "ltr", board.farm or "fieldmesh", INDEX_SCRIPT, refresh=False)
            + f'<body data-langs="{e(" ".join(board.languages))}"><h1>{e(board.farm or "fieldmesh")}</h1>'
            + f"<ul>{links}</ul><script>{INDEX_SCRIPT}</script></body></html>\n")


def write(board: Board, events, at: _dt.datetime, out_dir: str, state=None) -> list[str]:
    """Every page, each replaced whole so a reader never sees half of one."""
    snap = snapshot(events, at)
    if board.series and state is not None:
        snap["readings"] = latest_readings(state, board.series, at)
    pages = {f"index.{tag}.html": render(board, snap, tag, at, state) for tag in board.languages}
    pages["index.html"] = render_index(board)
    os.makedirs(out_dir, exist_ok=True)
    for name, text in pages.items():
        path = os.path.join(out_dir, name)
        with open(path + ".tmp", "w", encoding="utf-8") as h:
            h.write(text)
        os.replace(path + ".tmp", path)
    return sorted(pages)


# ----------------------------------------------------------------------- serve

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
}


def is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def tls_context(cert: str, key: str):
    """A server context, TLS 1.2 at least, as the data service's."""
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


def make_server(out_dir: str, host: str = "127.0.0.1", port: int = 8080, *, tls=None):
    """Serves the board's pages and nothing else, read-only. The data service's rule
    (server/serve.py): beyond this machine, only with TLS, since the page names the
    farm's troughs and its people."""
    import http.server
    if not is_loopback(host) and tls is None:
        raise SystemExit(f"refusing to serve the board on {host} without TLS: give "
                         "--tls-cert and --tls-key, or bind 127.0.0.1 behind a proxy that holds one")
    allowed = {"/": "index.html"}

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "fieldmesh-board"
        sys_version = ""
        timeout = 20

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            name = allowed.get(path) or (path[1:] if path.startswith("/index.")
                                         and path.endswith(".html") and "/" not in path[1:] else None)
            full = os.path.join(out_dir, name) if name else None
            if not full or not os.path.isfile(full):
                return self._send(404, b"not found\n", "text/plain; charset=utf-8")
            with open(full, "rb") as h:
                self._send(200, h.read(), "text/html; charset=utf-8")

        def do_HEAD(self):
            self.do_GET()

        def _refuse(self):
            self._send(405, b"read-only\n", "text/plain; charset=utf-8", {"Allow": "GET, HEAD"})

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuse

        def _send(self, code, body, kind, extra=None):
            self.send_response(code)
            for k, v in {"Content-Type": kind, "Content-Length": str(len(body)),
                         **SECURITY_HEADERS, **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def log_message(self, *a):
            pass

    class Server(http.server.ThreadingHTTPServer):
        """TLS negotiated in each connection's own thread, as the data service does, so
        a client that stalls its handshake stalls only itself."""

        daemon_threads = True

        def finish_request(self, request, client_address):
            request.settimeout(20)
            if tls is None:
                return super().finish_request(request, client_address)
            try:
                wrapped = tls.wrap_socket(request, server_side=True)
            except (OSError, ValueError):
                request.close()
                return
            try:
                super().finish_request(wrapped, client_address)
            finally:
                wrapped.close()

        def handle_error(self, request, client_address):
            pass

    return Server((host, port), Handler)


# --------------------------------------------------------------------- process

def main(argv=None) -> int:
    """The board as its own process (§8.3): follows the log through the host, writes
    the pages every minute, and serves them if asked."""
    import argparse
    import threading
    import time
    import modhost as M

    ap = argparse.ArgumentParser(description="The farm's board: what stands now, read-only")
    ap.add_argument("--socket", required=True)
    ap.add_argument("--config", required=True, help="farm, timezone, languages, people's names (JSON)")
    ap.add_argument("--out", required=True, help="the directory the pages are written to")
    ap.add_argument("--every", type=float, default=60.0)
    ap.add_argument("--once", action="store_true", help="write the pages once and exit")
    ap.add_argument("--serve", help="HOST:PORT to serve the pages on")
    ap.add_argument("--tls-cert")
    ap.add_argument("--tls-key")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as h:
        board = Board.from_json(json.load(h))
    if args.serve:
        host, _, port = args.serve.rpartition(":")
        tls = tls_context(args.tls_cert, args.tls_key) if args.tls_cert else None
        server = make_server(args.out, host or "127.0.0.1", int(port), tls=tls)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    with M.ModuleClient(args.socket, M.token_from_environment()) as client:
        events, cursor = [], 0
        while True:
            while True:
                new, nxt = client.follow(cursor, kinds=KINDS)
                events += new
                if not new or nxt == cursor:
                    cursor = nxt
                    break
                cursor = nxt
            now = _dt.datetime.now(tz=_dt.timezone.utc)
            write(board, events, now, args.out, client.state(now))
            events = prune(events, now)
            if args.once:
                return 0
            time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
