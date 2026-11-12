local R = require("rsmm")
if not R.debug or not R.debug.nameplate_snapshot then
    R.log("[nameplate-probe] Diagnostic SDK is missing; no inspection scheduled.")
    return
end
-- Bounded development capture, on the main thread after hero capture.
-- Retry while loading, stop after two useful samples or five minutes.
local attempts, samples, handle = 0, 0, nil
handle = R.schedule.every_main(10, function()
    attempts = attempts + 1
    local report = R.debug.nameplate_snapshot()
    if report.status == "captured" then samples = samples + 1 end
    if samples == 2 or attempts >= 30 then
        R.schedule.cancel(handle)
        R.log("[nameplate-probe] Finished: " .. samples .. " snapshots. No crown is drawn by this check.")
    elseif attempts == 1 or attempts % 6 == 0 then
        R.log("[nameplate-probe] Waiting: " .. tostring(report.reason or report.status))
    end
end)
R.log("[nameplate-probe] Ready. Enter a run and use one attack; captures are automatic.")
