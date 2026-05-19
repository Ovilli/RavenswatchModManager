-- R.health — read crash history + report current step to the boot canary.
-- The loader DLL backs this with file IO; here we just expose the API.

local M = {}

function M.crash_count(mod_id)
    if not _G.rsmm or not _G.rsmm._internal.health_count then return 0 end
    return _G.rsmm._internal.health_count(mod_id)
end

function M.last_error(mod_id)
    if not _G.rsmm or not _G.rsmm._internal.health_last_error then return nil end
    return _G.rsmm._internal.health_last_error(mod_id)
end

function M.disable(mod_id, reason)
    if _G.rsmm and _G.rsmm._internal.health_disable then
        _G.rsmm._internal.health_disable(mod_id, reason or "")
    end
end

-- Called by each mod's init.lua entry-point shim. The loader updates
-- the canary's `last_step` field to `per_mod:<id>` so a crash inside
-- the mod's first frame can be attributed to it on the next launch.
function M.checkpoint(step)
    if _G.rsmm and _G.rsmm._internal.health_checkpoint then
        _G.rsmm._internal.health_checkpoint(tostring(step))
    end
end

return M
