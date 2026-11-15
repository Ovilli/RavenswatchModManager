-- Smallest possible mod using SDK v3.
-- Demonstrates: require "rsmm", R.health.checkpoint, R.on, R.log, R.kv.

local R = require "rsmm"
R.health.checkpoint("per_mod:ExampleSdkHello")

R.on("ready", function()
    R.log("[Hello] loaded; SDK ready")
end)

R.on("tick", function()
    local n = R.kv.inc("tick_count")
    if n == 1 or n % 20 == 0 then
        R.log("[Hello] tick #" .. n)
    end
end)
