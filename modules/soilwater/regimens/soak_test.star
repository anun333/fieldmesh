# SPDX-License-Identifier: AGPL-3.0-or-later
# A soak test: a measured amount of water on a measured square, to see a bed's probes rise
# and drain back. It measures the bed's field capacity on the day, rather than waiting for
# three soakings to learn it from, and checks the probes on the way.
#
# Started by a person, for one bed. It asks for enough water to wet the root zone past
# field capacity (params["excess"] above it), over a square metre centred on the probes,
# where a millimetre is a litre. After params["soak_min"] it checks the probes rose by at
# least params["share"] of what that water should add, and read no more water than the
# soil can hold (params["saturation"]). After params["drain_min"] more it reports the level
# the root zone drained back to: its field capacity, and how fast it drained.

def plan(ctx, params):
    if not ctx["has_reading"]:
        return []
    expected = max(ctx["capacity"] - ctx["theta"], 0.0) + params["excess"]
    litres = expected * ctx["root_depth_mm"]
    return [
        say("soilwater.soak.pour", subject = ctx["bed"], label = "bed",
            litres = litres, hours = params["soak_min"] / 60.0),
        wait(params["soak_min"]),
        check("has_reading && rise >= expected * share", "soilwater.soak.no_rise",
              subject = ctx["bed"], label = "bed", show = ["rise_percent"],
              expected = expected, expected_percent = expected * 100.0,
              share = params["share"]),
        check("has_reading && peak <= saturation", "soilwater.soak.too_high",
              subject = ctx["bed"], label = "bed", show = ["peak_percent"],
              saturation = params["saturation"],
              saturation_percent = params["saturation"] * 100.0),
        wait(params["drain_min"]),
        # Always reported: the result is the point of the test.
        check("false", "soilwater.soak.drained", subject = ctx["bed"], label = "bed",
              show = ["capacity_percent", "half_drain_h"],
              variants = [["!drained", "soilwater.soak.not_drained"]]),
    ]
