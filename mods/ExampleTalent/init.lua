local R = require "rsmm"

R.on("ready", function()
    R.talent.allow_stack(true)
    R.talent.extra_at_level(11)
    R.talent.extra_at_level(16)
    R.talent.extra_at_level(21)

    R.log("[ExampleTalent] Talent stacking allowed, extra picks granted at levels 11, 16, 21 (TODO: not yet wired to game)")
end)
