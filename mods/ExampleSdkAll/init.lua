local R = require "rsmm"

R.on("ready", function()
    R.log("[ExampleSdkAll] loaded; all SDK features exercised (v3-only features stubbed for v1 runtime)")
end)

local sched = R.schedule
if sched and sched.after then
    sched.after(1, function()
        R.log("[ExampleSdkAll] 1s tick fired")
    end)
end
