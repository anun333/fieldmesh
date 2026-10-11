<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `modules/water/` — livestock water monitor (layer 2)

The first layer-2 module (spec v0.1 §11), and the first of §15's three acceptance apps.
Q12 chose it to ship first: a dry trough on a hot afternoon is an emergency, the module
is read-only so it needs no commands and carries no liability, and it leans on the parts
of layer zero most likely to be wrong — store-and-forward, backlog order, quality
assertions.

For each trough it says one of these, in the farmer's language:

| alert | when |
| --- | --- |
| **empty** | under a tenth of capacity, where stock cannot drink (§4.2) |
| **empty, unconfirmed** | the same, from a reading the health checks flagged *only* as out of range on the low side. A dry trough and a failed sensor both need someone to go and look, so it is never dropped as a sensor fault |
| **low** | under the farm's low mark (30% by default) |
| **not refilling** | under the float's mark for an hour: the float stuck shut or the supply off, with the rate the stock are drinking and the hours left before it is too low to drink from |
| **unseen** | no reading for half an hour. No news from an urgent series is not good news |
| **untrusted** | the newest reading carries any other flag |

Each alert is a CEL rule judged through layer 1 ([modules/rules](../rules/)), so its
decision event (§7.7) carries the readings it used, the condition as written, the rule's
version and the trust level — always *advisory* here. A decision is written when an alert
is raised or cleared, not on every look, and a person's acknowledgement goes in the log
too. A monitor that restarts reads which alerts stand from the log.

**It judges what the gateway knew at the time.** A reading counts once received and a
quality verdict once asserted, so a backtest over a past season is honest, and a person's
later override never reaches back into what the monitor knew then.

## The acceptance test, and what it found

§15 asks one thing of layer zero for this app: **the newest reading first after an
outage** (`drain_order: fresh_first`, §5.3). The test runs Harrow Bend for ten days with
the paddock radio out for twelve hours on day 2 and the south trough's float stuck shut
on day 9, the monitor looking every ten minutes.

Its first run failed the clause. The first readings to arrive after the outage were from
midnight, eight to twelve hours stale, and 21 of the outage's 144 readings never arrived.
Two defects in the simulated node, both now fixed and recorded in §17:

* **Resends went before everything.** Through a long outage every frame goes
  unacknowledged, so when the link returned the node resent its oldest frames first and
  `fresh_first` never ran. Now, under `fresh_first`, readings newer than every frame
  awaiting resend go first, and resends go newest-first; a resend still keeps its
  sequence number.
* **A frame's own confirmation was read as cumulative.** On a link that confirms each
  frame, confirming the first fresh frame released every older frame still awaiting
  resend, as if delivered. That loss predates the reordering — it happened whenever a
  lost frame was followed by a confirmed one — and the reordering made it systematic.

Now the current level arrives within minutes of the radio returning, all 144 readings
arrive, the outage is an alert within 50 minutes and clears when the radio returns, the
healthy trough raises nothing else in ten days, and the stuck float is reported about an
hour after the level first falls — eight hours before the trough is too low to drink from.

```sh
pip install -r modules/water/requirements.txt          # cel-python, via modules/rules
cd modules/water && python3 -m unittest discover -p 'test_*.py'
```

```python
monitor = water.Monitor(log)
troughs = [water.Trough(datastream_id, capacity_l=400.0)]
monitor.check(state, troughs, at=now)        # the decisions it wrote, if any changed
water.render(event.payload, "es", state)     # "bebedero sur no se ha vuelto a llenar…"
```

Code AGPL-3.0-or-later ([LICENSE](LICENSE)); strings in [packs/](packs/) under the
`water.` prefix, the Spanish an unreviewed draft like the rest. It imports layer zero and
layer 1, and nothing below imports it.

**Not yet:** escalation of an alert nobody acknowledges (layer 1's job, §11); per-trough
marks learned from a trough's own history, as Q24 did for flatlines; a message channel
to a phone (layer 4).
