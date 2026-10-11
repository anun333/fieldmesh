# SPDX-License-Identifier: AGPL-3.0-or-later
# After the morning's advice to water a bed: did the water arrive?
#
# Started when the soil-moisture advisory says "water today". It waits for the watering
# (params["water_after_min"] after the advice, at params["mm_per_hour"]) and for the water
# to soak down to the probes (params["soak_min"]), then checks that the root zone rose by
# at least params["share"] of what the watering should add. A blocked drip line and a bed
# nobody watered look the same to a probe, so the message says both.

def plan(ctx, params):
    if ctx["advice"] != "soil-water-now":
        return []
    mm = ctx["refill_mm"]
    expected = mm / ctx["root_depth_mm"]
    minutes = params["water_after_min"] + mm / params["mm_per_hour"] * 60.0 + params["soak_min"]
    return [
        wait(minutes),
        check("has_reading && rise >= expected * share", "soilwater.regimen.no_response",
              subject = ctx["bed"], label = "bed", show = ["rise_percent"],
              expected = expected, expected_percent = expected * 100.0,
              share = params["share"], mm = mm),
    ]
