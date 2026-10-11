<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# What has not been tested

This page lists, in one place, every claim this repository makes that has not been
checked. For each it gives:

* what was checked instead;
* what would close the gap;
* where the gap is noted alongside the code.

A claim that is tested only on the simulated farm is marked as such, because a simulator
never satisfies §9.2. When an item is checked, move it to the end with the date and a
link to the evidence; do not delete it.

## Needs hardware or a farm

| Not tested | Checked instead | What would check it | Noted in |
| --- | --- | --- | --- |
| **Sending and receiving SMS through a real modem**: `mmcli` creating, sending and deleting a message; reading replies; a long Spanish text arriving as one joined message; the sender's number in the format a real network gives it | The commands and their JSON as ModemManager 1.23's source defines them (`cli/mmcli-output.c`, `cli/mmcli-modem-messaging.c`), against a fake that answers the same way | A modem ModemManager supports, with a SIM, on the gateway: send to a phone and reply to it (Q29's first step) | [modules/notify](../modules/notify/README.md) |
| **ModemManager letting the notifier's service user send**, which polkit decides | Nothing | The same modem, with the notifier running as its own systemd service rather than as a person | [modules/notify](../modules/notify/README.md), [deploy/systemd](../deploy/systemd/README.md) |
| **A real radio and a real device driver** (build step 7) | Meshtastic chosen on paper (Q6); a Modbus RTU driver over a pseudo-terminal; a real station's feed (McAllister Farm's SCAN station) through layer zero every six hours | One Meshtastic node with one sensor, through a season | [README](../README.md) |
| **A growing season on a real farm** (§9.2), which every reliability claim waits on | The simulated farm, Harrow Bend, and recorded seasons from public stations | The pilot (Q1): two sites, decided by February 2027 to install before spring | [README](../README.md), [Q1](spec/open-questions.md) |
| **The thresholds**: a trough's empty, low and refill marks; the soil advisory's readily available water; the frost watch's 0 °C | Simulated troughs; one recorded summer for the soil advisory (2013); one frost season (2025–26) | A season of a real farm's troughs and beds, with the farmer saying which alerts were right | [§15](spec/v0.1.md), [modules/water](../modules/water/README.md), [modules/soilwater](../modules/soilwater/README.md) |
| **A real ensemble forecast at the farm** | A simulated ensemble on thirty recorded springs: its chance of frost beat a single forecast's margin at every setting. Its error and spread are the simulator's own | A season of ECMWF's open ensemble or NOAA's GEFS collected for McAllister Farm and scored against the SCAN station | [notes/forecasts.md](notes/forecasts.md#ensembles-a-chance-in-place-of-a-margin-q26) |
| **The watering check on a real bed**: whether half the expected rise is the right line for a real drip line, soil and probe depth | Two recorded summers through the simulated bed, with waterings blocked on purpose: every blocked one caught, none falsely flagged; but on 2012 a watered bed came within 0.05 of the line | A season of a real bed's waterings, with the farmer noting the ones that did not arrive | [modules/soilwater](../modules/soilwater/README.md#did-the-water-arrive) |
| **GreenLight's tunnel against a real tunnel**: the covered-crop frost watch's "inside low", and the twin-against-sensor check's idea of how far apart a model and a thermometer usually sit | GreenLight against the virtual farm's tunnel; the watch on forecasts against the twin run on the weather that came, and the check against a second model with faults put in. The "truth" inside is a model each time, and the twin runs about 1.1 °C warm on forecasts | A tunnel's inside and outside air logged on clear spring nights, with its film type written down | [modules/twin](../modules/twin/README.md), [Q28](spec/open-questions.md) |

## Needs root, a phone or the open internet

| Not tested | Checked instead | What would check it | Noted in |
| --- | --- | --- | --- |
| **The sandbox's filesystem protections** (`ProtectSystem`, `ProtectHome`) | Runs under a *user* systemd manager, which skips mount-namespace options without saying so | `systemd-run -p ProtectSystem=strict … touch /usr/x` under the system manager, on the gateway | [deploy/systemd](../deploy/systemd/README.md) |
| **Dropping capabilities** (`CapabilityBoundingSet=`) | Nothing: a user manager is refused it. The notifier's live run on 2026-10-11 had to leave it out | The unit started by the system manager, then `grep Cap /proc/<pid>/status` | [deploy/systemd](../deploy/systemd/README.md) |
| **Push reaching a real phone**: the ntfy app showing the alert, and its "I'm on it" button sending the acknowledgement | A real ntfy server (v2.11.0), open and locked down. The button was pressed by making the exact request its action describes. Per ntfy's documentation, an iPhone gets instant notifications from a self-hosted server only when that server relays through ntfy.sh (`upstream-base-url`); not tried | The ntfy app on an Android phone and an iPhone, subscribed to a test topic on the server the pilot will use | [modules/notify](../modules/notify/README.md) |
| **The data service facing the internet** | Real sockets on this machine: tokens, grants, TLS with a generated certificate, rate limits, timeouts | Someone outside trying to break it | [README](../README.md), [server](../server/README.md) |

## Needs a person

| Not tested | Checked instead | What would check it | Noted in |
| --- | --- | --- | --- |
| **Every Spanish string**: messages, the board, the advisor. The notifier's lists of yes and no words matter most, because they decide whether a reply stops an alert climbing | `make packs`: every key present, every field matching English | A native-speaking agronomist's review, and the yes and no lists tried on the people who will text back | [LANGUAGE_PACKS](LANGUAGE_PACKS.md), each module's README |
| **The advisor's crops without a model**: chill and bloom for blueberries, heat at fruit set in any crop but tomato, oats, and the 255 plants with neither source | The 28 crops with a crop model, and 625 fruit cultivars for chill | Sources for them, or a grower's records | [site-match-tennessee](../modules/advise/notes/site-match-tennessee.md#not-checked-yet) |

## Smaller gaps in the tests

None open at the moment.

## Checked since this list began

| Checked | How | Evidence |
| --- | --- | --- |
| **The farm page served with TLS** (2026-10-11) | A generated certificate: the pages over TLS, nothing over plain HTTP, an untrusted certificate refused, and a client that stalls its handshake stalling only itself | [modules/board/test_board.py](../modules/board/test_board.py), `TestTls` |
| **The module host and the other writers of the farm's log** (2026-10-11) | The notes said the host "runs inside the gateway", but no gateway process exists (it waits on the radio, build step 7). The real gap was worse: the host never read what other processes appended, so a revocation made at the command line was not seen until a restart, nor a new grant, nor a reading from the ingest. It now reads the file back every two seconds; tests show each counts, and fail on the old host. Found on the way: the first event after a power cut was glued to the cut line and lost; it now starts a fresh line | [sdk/test_modhost.py](../sdk/test_modhost.py) `TestOtherWritersOfTheLog`, [sdk/test_log.py](../sdk/test_log.py) `TestOtherWritersOfOneFile`, `test_the_first_event_after_a_power_cut_is_not_lost` |
| **Quiet hours across a change of hour, and a notifier that runs for a year** (2026-10-11) | The autumn change in Tennessee: a frost watch held overnight goes out at 6 am by the farm's clock both sides of it, which a fixed offset would get wrong by an hour. A year of daily alerts leaves about a week of them in the notifier's memory, and every alert and clear still went out | [modules/notify/test_notify.py](../modules/notify/test_notify.py): `test_quiet_hours_keep_the_farm_s_clock_across_the_change_of_hour`, `test_a_year_of_alerts_is_not_a_year_of_memory` |
