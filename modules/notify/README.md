<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/notify/` — alerts to people, escalating until someone answers (layer 1)

Every module so far ends at a decision in the log (§7.7): a trough is empty, bed 3 needs
water, it will frost in the tunnel tonight. A decision nobody reads protects nothing.
[notify.py](notify.py) carries decisions to people, in each person's language, on the phone
they have:

* **Push**, through [ntfy](https://ntfy.sh): free software (Apache-2.0 and GPL-2.0),
  self-hostable, with an app on F-Droid, Google Play and the App Store. Each message has
  an **I'm on it** button.
* **SMS**, through a cellular modem on the farm's own computer, driven by ModemManager
  (`mmcli`). A basic phone gets the alert, and no internet is needed. Replying **OK 417**
  acknowledges it.

§11 asks that alerts **escalate and need acknowledgement**. A *route* says which rules go
to whom, in tiers. Escalation works like this:

1. The first tier is told at once.
2. If nobody in it says "on it" within the route's time, the next tier is told.
3. If nobody in a tier could be reached at all, the next tier is told without waiting.
4. Once someone acknowledges, escalation stops, and everyone else who was told hears who
   took it.
5. When the module that raised the alert clears it, everyone who was told hears that too.

An alert ends when a newer answer to the same question arrives (tonight's frost warning
replaces last night's) or when its answer goes stale (`valid_until`; see
[modules/rules](../rules/README.md#a-decision-anyone-can-read)).

The notifier never imports the module whose decision it carries. Each decision names its
own sentence and what it is about, and each module's language pack is data.

## The roster

Who gets what is the farm's private configuration, not the log:

```json
{"farm": "Harrow Bend", "timezone": "America/Chicago",
 "channels": {"ntfy": {"server": "https://ntfy.example.org", "ack_topic": "hb-acks"},
              "sms": {"modem": "any"}},
 "people": {
   "maria": {"id": "0192…", "name": "María", "language": "es",
             "contacts": [{"via": "sms", "address": "+16155550101"}]},
   "sam":   {"id": "0192…", "name": "Sam", "language": "en", "quiet": ["21:00", "06:00"],
             "contacts": [{"via": "ntfy", "address": "hb-sam"},
                          {"via": "sms", "address": "+16155550102"}]}},
 "routes": [
   {"rules": ["water-*"], "tiers": [["maria"], ["sam"]], "escalate_after_min": 30, "urgent": true},
   {"rules": ["frost-watch", "covered-frost-watch"], "tiers": [["sam", "maria"]], "notify_clear": false},
   {"rules": ["soil-water-now"], "tiers": [["maria"]]}]}
```

* **Contacts are tried in order.** If push fails, the SMS goes out, and the log records
  both attempts.
* **Quiet hours** hold anything not marked `urgent` until morning. An empty trough is
  urgent; tomorrow's watering is not.
* **A rule no route names goes nowhere.** It still stands on the [board](../board/).

**The log names people and never their numbers.** Each message sent or tried is written
back as a `notification` event, and each acknowledgement as an `acknowledgement` event,
the same kind the water monitor writes. A notification event records:

* the decision, and the person by the id the log uses everywhere (§7.4);
* the channel kind, the outcome and the SMS segments it cost.

Phone numbers and topics stay in the roster. An export, or a view of the log shared with a
researcher, carries who was told, never how to reach them.

**It restarts where the log says it was.** A restarted notifier neither sends everything
again nor forgets an alert half-escalated, and escalation keeps its original clock. It
sends first and writes second, so a crash in between can repeat a message, never lose one.

**Which replies count.** A reply acknowledges alerts in three cases:

* it says yes in the sender's language or in English and gives an alert's number;
* it is one or more numbers alone;
* it says yes with no number: then it takes every open alert its sender was told about.
  Two troughs on one silent radio are one errand, sent as one message, and "Sí, voy"
  covers both.

A reply that says no is never an acknowledgement, whatever else it contains. "No puedo
417", "si no puedo" and "can't 417" are all ignored, and the alert keeps climbing. The
yes and no words are lists in each language pack (`notify.ack_words`,
`notify.no_words`), so a new language brings its own.

## On Harrow Bend

[test_notify.py](test_notify.py) runs the water monitor's §15 season on the virtual farm
alongside the notifier, looking every ten minutes. The radio is out for twelve hours on
day 2, and the south trough's float sticks on day 9. María reads Spanish on a basic
phone; Sam has the push app. Nobody answers, so every alert climbs to Sam.

| ten days, two troughs | |
| --- | --- |
| alerts raised | 5 (two for the outage, three as the float failed) |
| messages | 12: 4 to María on raising, 4 escalated to Sam, 2 clears to each |
| SMS segments | 22. Spanish needs "á", which is outside the GSM alphabet, so each SMS holds 70 characters, not 160. The longest, the outage's two alerts together, is 6 |
| first message after a decision | at the next look, within 10 minutes |
| escalation | exactly 30 minutes after the first message |

**Alerts due together go as one message.** When the radio both troughs hang off went
quiet, María got one SMS listing both, with a number for each, and Sam got one push with
one button that takes both. Sent one alert at a time, the same season was 16 messages
and 23 segments. The log still holds one notification per alert, tied by a `batch` id,
with the message's cost counted once.

## What was checked, and what was not

* **Unit and process tests:** escalation, restart, quiet hours, replies, both channels,
  and the notifier as a module process. Its grant reads every module's decisions and
  nothing of the farm's readings, and it publishes over real HTTP.
* **A real ntfy server** (v2.11.0, in a container on this machine), in two setups:
  * *Open:* publish, press the button the way the phone app does, and read the
    acknowledgement back.
  * *Deny-by-default, with the recommended tokens:* the notifier's token publishes and
    reads; the button's token can write the acknowledgement topic and gets 403 on
    anything else. Anonymous access gets 403.
* **The sandboxed service:** run live under a user systemd manager with
  [the drop-in's](../../deploy/systemd/fieldmesh-module@notify.service.d/channels.conf)
  settings. It read its token and roster as credentials, fell back to no ntfy token when
  that file was missing, reached the host over its socket, and published to the ntfy
  server. `systemd-analyze security` scores the unit at 1.3 ("OK"), against 0.4 for a
  module with no network.
* **Not checked: SMS on a real modem.** There is none here. The `mmcli` commands and the
  JSON they return are taken from ModemManager 1.23's source (`cli/mmcli-output.c`,
  `cli/mmcli-modem-messaging.c`) and tested against a fake that answers the same way.
  Also unchecked: whether the service's user may send through ModemManager, which polkit
  decides and which may need a rule. Check both on the first gateway with a SIM.

```sh
FIELDMESH_NTFY_SERVER=http://127.0.0.1:18432 python3 -m unittest test_notify.TestAgainstARealNtfyServer
```

## Running it

```sh
python3 sdk/modhost.py grant --log farm.jsonl --manifest modules/notify/module.json \
    --token-out /etc/fieldmesh/modules/notify.token
python3 -I modules/notify/notify.py --socket /run/fieldmesh/modules.sock --config roster.json
```

The grant reads decisions and acknowledgements from every module, and the grant record
says so. Under systemd it is `fieldmesh-module@notify` with its drop-in
([deploy/systemd/](../../deploy/systemd/README.md)). No dependencies beyond Python's
standard library, plus `mmcli` for SMS.

**Choosing a push server ([Q29](../../docs/spec/open-questions.md)):**

* *ntfy.sh* works today, but there the topic name is the only lock.
* *A self-hosted server* with `auth-default-access: deny-all` and two tokens is the
  setup checked above:
  * the notifier's: read-write on `hb-*`;
  * the phones': write-only on the acknowledgement topic, read-only on their own topic.

  The server must be one the phones can reach, which a farm's own computer often is not.

Code AGPL-3.0-or-later ([LICENSE](LICENSE)); strings in [packs/](packs/) under the
`notify.` prefix, with the Spanish an unreviewed draft.

**Next:** a weekly digest of what was sent and what it cost; SMS checked on a real modem.
