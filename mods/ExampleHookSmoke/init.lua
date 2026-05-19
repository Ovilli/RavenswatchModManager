-- Smoke test for R.hook bridge. Hooks the engine's resource-by-path
-- lookup, counts calls, prints the first few, then stays silent.
-- Returns nil from the callback to let the original run.
--
-- Demonstrates: require "rsmm", R.health.checkpoint, R.hook, R.resolve,
-- R.kv.

local R = require "rsmm"
R.health.checkpoint("per_mod:ExampleHookSmoke")

local TARGET = "FUN_140487040"   -- resource hashmap lookup
local SIG    = "llll"            -- ret int64 + 4 int64 args
local MAX    = 5

local slot_handle = nil

R.on("ready", function()
    if slot_handle then return end
    local va = R.resolve(TARGET)
    if not va or va == 0 then
        R.log("[HookSmoke] resolve failed for " .. TARGET)
        return
    end
    local ok, handle = pcall(R.hook, va, SIG, function(a, b, c, d, _next)
        local n = R.kv.inc("hits")
        if n <= MAX then
            R.log(("[HookSmoke] hit #%d  a=0x%x  b=0x%x"):format(n, a or 0, b or 0))
        end
        return nil   -- pass-through: dispatcher calls the original
    end)
    if not ok then
        R.log("[HookSmoke] R.hook unavailable: " .. tostring(handle))
        return
    end
    slot_handle = handle
    if slot_handle then
        R.log(("[HookSmoke] hook installed slot=%d on %s"):format(slot_handle, TARGET))
    end
end)
