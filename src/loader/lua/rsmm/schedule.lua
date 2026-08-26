-- R.schedule — frame-based coroutine helpers. Built on R.on("tick", ...).

local M = {}
local _next_frame = {}
local _timers = {}        -- { fire_at, fn }
local _main_q = {}        -- main-thread immediate callbacks
-- Streak holders for the two fire-and-forget queues. Each callback there is
-- one-shot, so the streak is per QUEUE: it catches "every next_frame callback
-- this mod queues raises", which is the shape that floods the log.
local _frame_errs, _main_errs = {}, {}
local _main_timers = {}   -- main-thread { fire_at, fn }

-- Monotonic, sub-second clock. os.time() is the fallback ONLY for a loader
-- too old to provide _internal.now(): it has one-second resolution, so with it
-- `after(0.25, ...)` really means "some time in the next second or two" and a
-- burst of sub-second polls all fire in the same tick.
local _now = function()
    local I = _G.rsmm and _G.rsmm._internal
    if I and I.now then return I.now() end
    return os.time()
end

-- Traceback-carrying message handler. The loader sandbox removes `debug` from
-- every mod state, so `xpcall(fn, debug.traceback)` is unavailable here; the
-- native binding is luaL_traceback, which lives in the C library. Falls back to
-- the bare message on a loader older than the binding — the Lua SDK ships
-- independently of the DLL and routinely runs against one.
local _msgh = _G.rsmm and _G.rsmm._internal and _G.rsmm._internal.traceback
              or function(e) return tostring(e) end

-- Consecutive raises a callback may log before it is silenced. A repeater is
-- deliberately NOT killed by a raising callback (a transient failure — hero not
-- spawned yet — must not silently stop the poll), but `every(0.1, broken)` then
-- writes ten identical lines a second for the rest of the session, which pushes
-- the loader log past its size cap and rotates away everything useful. Keep the
-- timer, drop the noise.
local LOG_LIMIT = 3
local SILENCE_AT = 20

-- Run one scheduled callback, reporting at most LOG_LIMIT consecutive failures.
-- `slot` is any table used to hold the streak (the timer entry, or a shared
-- table for the fire-and-forget queues).
local function _run(slot, label, fn)
    local ok, err = xpcall(fn, _msgh)
    if ok then
        slot.err_streak = nil
        return true
    end
    local n = (slot.err_streak or 0) + 1
    slot.err_streak = n
    if not _G.rsmm then return false end
    if n <= LOG_LIMIT then
        _G.rsmm.log("schedule." .. label .. " error (" .. n .. "): " .. tostring(err))
    elseif n == SILENCE_AT then
        _G.rsmm.log("schedule." .. label .. " has raised " .. n ..
                    " times in a row; SILENCING further reports (the timer "
                    .. "still runs — cancel it if that is not what you want)")
    end
    return false
end

function M.next_frame(fn)
    assert(type(fn) == "function", "R.schedule.next_frame: fn must be a function")
    table.insert(_next_frame, fn)
end

-- Timers carry a handle so they can be cancelled, and `every` repeats until
-- you do. Before this the only way to stop a repeating poll was a flag the
-- callback checked itself, and every `on_guid`/`item.behavior` poller
-- re-armed itself by hand.
local _next_timer = 0
-- Every live timer by handle. Cancellation marks the ENTRY through this table
-- instead of mutating a list: a drain in progress is iterating one of those
-- lists by index, so a `table.remove` under it shifts entries past the cursor
-- and silently drops them.
local _by_id = {}
local function _add(list, seconds, fn, repeating)
    _next_timer = _next_timer + 1
    local t = { id = _next_timer, fire_at = _now() + seconds,
                every = repeating and seconds or nil, fn = fn }
    _by_id[t.id] = t
    table.insert(list, t)
    return t.id
end

function M.after(seconds, fn)
    assert(type(seconds) == "number", "R.schedule.after: seconds must be a number")
    assert(type(fn) == "function", "R.schedule.after: fn must be a function")
    return _add(_timers, seconds, fn, false)
end

-- Repeat every `seconds` until cancelled. Returns a handle for M.cancel.
function M.every(seconds, fn)
    assert(type(seconds) == "number" and seconds > 0,
           "R.schedule.every: seconds must be a positive number")
    assert(type(fn) == "function", "R.schedule.every: fn must be a function")
    return _add(_timers, seconds, fn, true)
end

-- Main-thread variant of `every` (see next_main for the threading rules).
function M.every_main(seconds, fn)
    assert(type(seconds) == "number" and seconds > 0,
           "R.schedule.every_main: seconds must be a positive number")
    assert(type(fn) == "function", "R.schedule.every_main: fn must be a function")
    return _add(_main_timers, seconds, fn, true)
end

-- Fire everything due in `list`, re-arming repeaters and dropping one-shots.
-- `store` writes the surviving list back (the pumps own the upvalues).
local function _drain(list, label, store)
    -- Snapshot the length FIRST. `_add` appends to this very table, so an
    -- unbounded `ipairs` walks straight into work a callback just scheduled
    -- and runs it in the same pass. With a zero delay that never terminates:
    -- `R.schedule.after(0, poll)` from inside `poll` — the obvious way to
    -- write "poll as fast as possible" — spun forever inside one tick and hung
    -- the loader's pump thread, taking every mod's timers, the hero capture
    -- and the health canary with it. Work scheduled during a drain therefore
    -- waits for the next tick, which also gives `after(0, ...)` a consistent
    -- meaning.
    local n0 = #list
    if n0 == 0 then return end
    local now = _now()
    local keep = {}
    for i = 1, n0 do
        local t = list[i]
        -- `cancelled` is what counts, not list membership. A callback that
        -- stops its OWN repeater — the canonical "repeat until done" — cannot
        -- be seen by this loop any other way: the drain already holds the
        -- entry and would write it straight back, so the timer ran forever.
        if t and not t.cancelled then
            if t.fire_at <= now then
                _run(t, label, t.fn)
                -- A repeater survives a raising callback: a transient failure
                -- (hero not spawned yet, say) shouldn't silently kill it.
                -- Re-arm off `now`, not fire_at, so a stalled pump doesn't
                -- queue a burst of catch-up fires. Re-check `cancelled` — the
                -- callback may have just stopped it.
                if t.every and not t.cancelled then
                    t.fire_at = now + t.every
                    keep[#keep + 1] = t
                else
                    _by_id[t.id] = nil
                end
            else
                keep[#keep + 1] = t
            end
        elseif t then
            _by_id[t.id] = nil
        end
    end
    -- Carry over anything scheduled during this drain (appended past the
    -- snapshot) without running it; dropping these would lose every
    -- self-rescheduling poll.
    for i = n0 + 1, #list do
        local t = list[i]
        if t and not t.cancelled then keep[#keep + 1] = t end
    end
    store(keep)
end

-- Cancel a timer from either queue. Returns true if it was still pending.
function M.cancel(handle)
    local t = _by_id[handle]
    if not t or t.cancelled then return false end
    -- Mark only. The next drain of whichever list holds it does the removal,
    -- so this is safe to call from inside a timer callback (including the
    -- timer's own) while that list is being iterated.
    t.cancelled = true
    _by_id[handle] = nil
    return true
end

-- MAIN-THREAD variants. The regular tick pump (M._tick) runs on the loader's
-- BACKGROUND thread. Engine calls that mutate game state — anything routing
-- through NamedEvent_Dispatch (R.give.*, R.combat.*) — MUST run on the game's
-- main thread or they race the engine and crash (proven: a give that crashes
-- from M.after survives identically from a gameplay-event handler). These queue
-- onto lists drained by M._main_tick, which rsmm.lua drives off the gameplay
-- bus (those handlers run on the main thread). Requires the gameplay bus
-- (RSMM_ENABLE_GAMEPLAY_EVENTS=1) — the only main-thread heartbeat available.
function M.next_main(fn)
    assert(type(fn) == "function", "R.schedule.next_main: fn must be a function")
    table.insert(_main_q, fn)
end

function M.after_main(seconds, fn)
    assert(type(seconds) == "number", "R.schedule.after_main: seconds must be a number")
    assert(type(fn) == "function", "R.schedule.after_main: fn must be a function")
    return _add(_main_timers, seconds, fn, false)
end

-- Pending work, for diagnostics: {next_frame, timers, next_main, main_timers}.
function M.pending()
    return { next_frame = #_next_frame, timers = #_timers,
             next_main = #_main_q, main_timers = #_main_timers }
end

-- Main-thread pump. Driven by rsmm.lua from gameplay-bus events only.
function M._main_tick()
    if #_main_q > 0 then
        local cur = _main_q
        _main_q = {}
        for _, fn in ipairs(cur) do
            _run(_main_errs, "next_main", fn)
        end
    end
    _drain(_main_timers, "after_main", function(t) _main_timers = t end)
end

-- Frame pump. rsmm.lua subscribes this to the "tick" event so timers fire
-- without the module needing to subscribe at load time.
function M._tick()
    if #_next_frame > 0 then
        local cur = _next_frame
        _next_frame = {}
        for _, fn in ipairs(cur) do
            _run(_frame_errs, "next_frame", fn)
        end
    end
    _drain(_timers, "after", function(t) _timers = t end)
end

return M
