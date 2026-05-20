local R = require "rsmm"

R.counter.on("run_end")
R.counter.on("level_up")
R.counter.on("boss_kill")

R.on("ready", function()
    R.log("[ExampleCounter] Counters registered for run_end, level_up, boss_kill")
    R.log("[ExampleCounter] Use R.kv.get('<event>_count') to read values")
end)
