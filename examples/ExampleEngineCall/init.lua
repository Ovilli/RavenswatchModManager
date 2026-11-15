-- Example: call the game's own engine functions by name.
--
-- data/symbols.json maps semantic names -> engine functions and records
-- each one's `cabi` (return + arg types). The loader resolves the address
-- at runtime by byte pattern (survives game updates) and the SDK supplies
-- the native call signature from the cabi, so a mod just calls the function
-- like any Lua function — no addresses, no signature strings.
--
-- Browse what's callable: `rsmm symbols list`, or R.engine.names() at runtime.
-- Requires the loader DLL.

local R = require "rsmm"
R.health.checkpoint("per_mod:ExampleEngineCall")

R.on("ready", function()
    R.log("[EngineCall] callable symbols: " .. table.concat(R.engine.names(), ", "))

    -- Look up a cooked resource by its decoded path. Two equivalent forms:
    local path = "EntitySettings/Objects/Magical_Objects/Common/Armor_Per_Object"
    local res  = R.engine.fn.Resource_LookupByPath(path, 0, 0, 0)
    -- local res = R.engine.call("Resource_LookupByPath", path, 0, 0, 0)

    if res and res ~= 0 then
        R.log(("[EngineCall] resolved '%s' -> 0x%x"):format(path, res))
    else
        R.log("[EngineCall] resource not loaded (only paths in UsedRscList resolve)")
    end
end)
