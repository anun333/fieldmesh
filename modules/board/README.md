<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/board/` — the farm's page (layer 4)

The thinnest slice of an app (spec v0.1 §11, layer 4). A notification says that something
happened; [board.py](board.py) shows what is still the case, on one read-only page per
language:

* **Needs someone:** every alert that stands and was sent to someone, with who was told,
  by what, when, and who said they are on it, or that nobody has yet. Red until someone
  takes it, then green.
* **Also standing:** what the modules say now that went to nobody, such as this morning's
  soil advice.
* **Cleared in the last day:** what stopped being the case, and when.

Like the [notifier](../notify/), it reads any module's decisions without importing any
module (`rules.render`), and it never writes the log. Its grant reads decisions,
notifications and acknowledgements, plus the names of what decisions are about.

**It says when it was made.** A page that stopped updating looks exactly like a quiet
farm, the failure §4.2 forbids for sensors ("no news is not good news"). So the page:

* states the minute it was made;
* reloads itself every minute;
* says plainly, once it is ten minutes old, that the farm's computer or the board has
  stopped and that what follows may no longer be true.

**For a phone in a field:**

* large type and strong contrast, light or dark as the phone is set;
* nothing loaded from anywhere else;
* no script it needs: the only script makes the "stopped" warning appear;
* a content-security policy that lets that script and the style run, by hash, and
  nothing else.

Everything a farm or a module wrote, labels included, is escaped.

```sh
python3 -I modules/board/board.py --socket /run/fieldmesh/modules.sock \
    --config board.json --out /var/lib/fieldmesh-board --serve 127.0.0.1:8080
```

`board.json` names the farm, its time zone, the languages to write pages in, and the names
of the people acknowledgements refer to by id (names only; reaching people is the
notifier's business):

```json
{"farm": "Harrow Bend", "timezone": "America/Chicago", "languages": ["en", "es"],
 "people": {"0192…": "María", "0192…": "Sam"}}
```

**Serving it:**

* It writes `index.html` and one `index.<language>.html` per language, each replaced
  whole so nobody reads half a page. `index.html` sends a browser to its own language.
* `--serve` serves those pages and nothing else, read-only.
* Like the data service, it refuses to serve beyond this machine without TLS, because the
  page names the farm's troughs and its people. On the farm computer, open
  `http://127.0.0.1:8080/`. For phones on the farm's Wi-Fi, give it `--tls-cert` and
  `--tls-key`, or put it behind a proxy that holds a certificate.
* Under systemd it is `fieldmesh-module@board` with its drop-in
  ([deploy/systemd/](../../deploy/systemd/README.md)), scored 1.2 ("OK") by
  `systemd-analyze security`.

Code AGPL-3.0-or-later ([LICENSE](LICENSE)); strings in [packs/](packs/) under the
`board.` prefix, with the Spanish an unreviewed draft.

**Next:** the troughs' and beds' latest readings beside their alerts, which needs a grant
of those datastreams; a certificate story for the farm's own network that does not ask a
farmer to run a certificate authority.
