-- Smoke test for rsmm.hook. Hooks the engine resource-by-path lookup,
-- counts calls, prints the first few, then keeps silent. Always lets
-- the original run by returning nil (= "pass through, call original").
--
-- Verifies end-to-end:
--   * fn_resolve("name") -> runtime VA
--   * rsmm.hook(va, "sig", cb) -> slot handle
--   * dispatcher reaches the Lua callback with unpacked args
--   * `next` closure (5th arg here) is callable -- but we don't, the nil
--     return makes the dispatcher call the trampoline for us
--   * unhook on mod disable: covered by hook_lua_unregister_mod which
--     fires from script_reload_changed / script_shutdown_all
--
-- Pure observation. No game-state mutation.

local TARGET = "FUN_140487040"   -- resource hashmap lookup
local SIG    = "llll"            -- ret = int64; args = 4x int64 (this, key, ?, ?)
local MAX    = 5

local hits        = 0
local slot_handle = nil

local function on_install()
    if slot_handle then return end
    local va = rsmm.resolve(TARGET)
    if not va or va == 0 then
        rsmm.log("[HookSmoke] resolve failed for " .. TARGET)
        return
    end
    slot_handle = rsmm.hook(va, SIG, function(a, b, c, d, _next)
        hits = hits + 1
        if hits <= MAX then
            rsmm.log(("[HookSmoke] hit #%d  a=0x%x  b=0x%x"):format(hits, a or 0, b or 0))
        end
        -- nil return = dispatcher invokes the original for us.
        return nil
    end)
    if slot_handle then
        rsmm.log(("[HookSmoke] hook installed slot=%d on %s"):format(slot_handle, TARGET))
    end
end

-- Run on "ready" so the loader has settled before we MH_CreateHook.
rsmm.on_event("ready", on_install)
