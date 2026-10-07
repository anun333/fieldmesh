# Where a node's battery actually goes

Run 2026-10-07 with [tools/power_budget.py](../../tools/power_budget.py).
Reproduce with `make power`.

The question: if soil moisture does not need updating often, what does slowing it
down save? The intuition is that a less necessary sensor should sample less and the
battery lasts longer. **Mostly wrong, and wrong in a way worth knowing**, because
the saving is real but it is not where it looks.

## What was modelled

A node with one or more channels, each a datastream with its own sample interval and
its own tolerance for staleness. Three costs: the quiescent sleep draw paid every
second, a per-reading cost to wake and settle a sensor, and a per-message cost of the
radio at full current for the whole time-on-air. Airtime comes from the same
Semtech formula as the Q5 measurement, at EU868 DR0 (SF12) with CBOR packed arrays.

Currents are documented assumptions, not measurements: an SX1276-class radio at
14 dBm (120 mA), an STM32L-class MCU (8 mA awake, 10 µA asleep), a capacitive soil
probe (5 mA for 100 ms), one 18650 at 2600 mAh. The *ratios* below survive being
wrong about any of those by a factor; the absolute day counts do not, and a real
figure needs an electrical spec the project does not yet have.

## Result

| Configuration | Transmit | Sampling | Sleep | Total | Days |
| --- | --- | --- | --- | --- | --- |
| A — soil only, hourly | 1.46 (85%) | 0.009 (0.5%) | 0.24 (14%) | 1.71 | **1518** |
| B — soil only, sampled 5 min, sent hourly | 4.50 (93%) | 0.10 (2%) | 0.24 (5%) | 4.85 | 537 |
| C — trough only, 5 min latency | 17.57 (98%) | 0.10 (0.6%) | 0.24 (1.3%) | 17.92 | 145 |
| D — both on one node, soil hourly | 19.15 (98%) | 0.11 (0.6%) | 0.24 (1.2%) | 19.50 | 133 |
| E — both on one node, soil also 5 min | 19.15 (98%) | 0.21 (1.1%) | 0.24 (1.2%) | 19.59 | **133** |

mAh/day.

## Three findings

**Reading a sensor is a rounding error.** Sampling is 0.5–2% of consumption in every
configuration. Slowing a sensor down *to spare the sensor* saves nothing measurable,
so "soil moisture is less necessary, sample it less" does not buy what it seems to.

**But sampling more often is not free, and the reason matters.** A → B nearly
triples consumption for twelve readings an hour instead of one — and almost none of
the increase is the probe. Twelve readings no longer fit one DR0 message, so the node
sends two. **You pay for what you send**, and sample rate matters only through the
data it generates. That is why the intuition half-works: slowing a sensor usually
slows its reporting too, and the reporting is the bill.

**Co-location dominates everything else.** The same hourly soil probe lasts about
1518 days on its own node and about 133 days on a node a five-minute trough float
keeps awake — eleven times, which nothing in the sample-rate or encoding space comes
close to. D → E is the counterpart: once a node is already transmitting every five
minutes, sampling soil twelve times more often costs **0.5%**, because the extra
reading rides in a message that was going anyway.

So the lever the maintainer was reaching for exists, and it is **placement**, not rate. A
sleepy sensor conserves power by being on a node nothing urgent keeps awake. Put a
soil probe on the trough node and its own sample rate stops mattering almost
entirely.

## What changed in the spec

`expected_interval` was doing two jobs — how often a series is sampled, and
implicitly how fast it must arrive. They are different numbers and only the second
one spends the battery, so §3.1 now also carries **`max_latency`**: how stale a
reading may be when it reaches the gateway.

§5.3.1 states the consequence: **a node's transmit interval is the tightest
`max_latency` among the series it carries.** Latency is not a per-series cost; it is
imposed on everything sharing the radio. And the installation rule follows — do not
put a loose-latency series on a node whose tightest latency is short, unless the
wiring makes it unavoidable.

## The tension it exposed

§4.2 runs health checks in the foundation, §5.1 says the node applies nothing, and
the power model says you pay for what you send. Together: **detection resolution
equals transmitted resolution.** Catching a stuck probe within the hour means sending
hourly-resolution data, even for a series a farmer only reads weekly. On a shared
node that is nearly free; on a sleepy node it is most of the budget.

A node could send a compact aggregate instead — sample count, min, max, and the
length of the current unchanged run are enough to keep a flatline and a rate
excursion detectable in a handful of bytes. But then the node has computed something,
which §5.1 forbids and §3.2's "raw is exactly what the node sent" complicates. That
is **open-questions Q20**, with a recommendation (a third datastream `kind`) and the
reason it wants settling before node firmware rather than after.

## Sensitivity

A faster data rate is worth more than any configuration choice here: DR5 instead of
DR0 multiplies a trough node's life by more than five, because the cost is airtime.
And sleep current only matters on a sleepy node — a careless 150 µA halves node A's
life and barely touches node C's, which is already dominated by its radio.
