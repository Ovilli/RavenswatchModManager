-- R.health — read crash history + report current step to the boot canary.
-- The loader DLL backs this with file IO; here we just expose the API.

local M = {}

-- `_G.rsmm and _G.rsmm._internal.health_count` looks like a guard but indexes
-- nil when `rsmm` exists without `_internal`, raising inside the mod that
-- called. The SDK ships independently of the DLL and must degrade against an
-- older loader, which is the whole reason these checks exist.
local function _native()
    local g = _G.rsmm
    return g and g._internal or nil
end

function M.crash_count(mod_id)
    local I = _native()
    if not I or not I.health_count then return 0 end
    return I.health_count(mod_id)
end

function M.last_error(mod_id)
    local I = _native()
    if not I or not I.health_last_error then return nil end
    return I.health_last_error(mod_id)
end

function M.disable(mod_id, reason)
    local I = _native()
    if I and I.health_disable then
        I.health_disable(mod_id, reason or "")
    end
end

-- Called by each mod's init.lua entry-point shim. The loader updates
-- the canary's `last_step` field to `per_mod:<id>` so a crash inside
-- the mod's first frame can be attributed to it on the next launch.
function M.checkpoint(step)
    local I = _native()
    if I and I.health_checkpoint then
        I.health_checkpoint(tostring(step))
    end
end

return M
