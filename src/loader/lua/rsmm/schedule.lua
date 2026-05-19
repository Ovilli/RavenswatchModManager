-- R.schedule — frame-based coroutine helpers. Built on R.on("tick", ...).

local M = {}
local _next_frame = {}
local _timers = {}        -- { fire_at, fn }

local _now = function()
    if _G.rsmm and _G.rsmm._internal.now then return _G.rsmm._internal.now() end
    return os.time()
end

function M.next_frame(fn)
    table.insert(_next_frame, fn)
end

function M.after(seconds, fn)
    table.insert(_timers, { fire_at = _now() + seconds, fn = fn })
end

-- Hook called by the events module on every frame. Public so the loader
-- can drive it without us needing to subscribe at module load time.
function M._tick()
    if #_next_frame > 0 then
        local cur = _next_frame
        _next_frame = {}
        for _, fn in ipairs(cur) do
            local ok, err = pcall(fn)
            if not ok and _G.rsmm then _G.rsmm.log("schedule.next_frame error: " .. tostring(err)) end
        end
    end
    if #_timers > 0 then
        local now = _now()
        local keep = {}
        for _, t in ipairs(_timers) do
            if t.fire_at <= now then
                local ok, err = pcall(t.fn)
                if not ok and _G.rsmm then _G.rsmm.log("schedule.after error: " .. tostring(err)) end
            else
                table.insert(keep, t)
            end
        end
        _timers = keep
    end
end

return M
