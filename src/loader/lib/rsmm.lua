-- rsmm — Ravenswatch Mod Manager SDK (Lua).
--
-- This is the documented surface for mod authors. Drop an init.lua in
-- your mod directory, start with:
--
--     local R = require "rsmm"
--
-- and use the R.* namespace. Everything below is a stable contract.
-- The raw engine bindings (memory read/write, native call, pattern
-- resolve) live under `R._internal` and are NOT covered by the contract;
-- they're an escape hatch for power users + the SDK itself.
--
-- TODO markers indicate features whose game-side wiring is still being
-- reverse-engineered. The API shape is fixed; the implementation lands
-- as the engine work catches up.

local native = rawget(_G, "rsmm")
assert(native, "rsmm.lua: native bindings missing (loader did not run)")
local I = native._internal or native

local R = {}

-- `F` is the SDK's private helper table. It is DECLARED here, at the top of
-- the chunk, and only POPULATED much further down (see "local F" -> "F = {}"
-- below the damage-meter constants). The declaration has to come first
-- because closures capture locals LEXICALLY: the LobbyAttributes_Parse detour
-- is defined above the old declaration site, so `F` compiled there as a
-- GLOBAL read and was nil at runtime -- "attempt to index a nil value
-- (global 'F')" on every parse, 20 in a row, after which the hook layer
-- DISABLED the callback. That killed ally names for the whole session,
-- because members other than the local one are parsed later (when they join),
-- long after the callback was switched off.
local F = {}

-- mod identity ----------------------------------------------------------

function R.mod_dir()  return native.mod_dir() end

-- logging ---------------------------------------------------------------

function R.log(...)
    local parts = {}
    for i = 1, select("#", ...) do
        parts[i] = tostring(select(i, ...))
    end
    native.log(table.concat(parts, " "))
end

-- events ----------------------------------------------------------------
--
-- Built-in events:
--   "ready" — loader has finished init; safe to query game state
--   "tick"  — fires every 500ms; cheap polling slot
--   "exit"  — DLL is being unloaded
--
-- Typed gameplay events (from data/symbols.json kind="event"; run
-- `rsmm symbols events` for the live list). Enable with
-- RSMM_ENABLE_GAME_EVENTS=1:
--   "level_up" -> { level },  "run_end"
--
-- Analytics firehose (same RSMM_ENABLE_GAME_EVENTS=1 gate). The game
-- funnels ~37 named analytics events through one telemetry sink
-- (Analytics_SubmitNamedEvent); the loader detours it once and
-- re-publishes EVERY event to this bus by its raw name — no per-event
-- wiring, and new names the game adds appear automatically. Confirmed:
--   "game_start" "run_start" "matchmaking_start" "matchmaking_end"
--   "chapter_end" "level_up_reach" "level_up_book" "enemy_killed"
--   "unlock_skill" "unlock_object" "unlock_hero" "unlock_level_nightmare"
--   "event_start" "event_end"
-- OBSERVATION-grade: they fire after the action and carry the analytics
-- payload, not a live entity handle. Great for "when X happens, do Y"
-- triggers; to mutate the actor use the oCGameNamedEvent gameplay bus
-- below.
--
-- Gameplay bus events (RSMM_ENABLE_GAMEPLAY_EVENTS=1) arrive as
-- "gameplay:<NAME>" — entity-context events the game itself dispatches
-- (NETWORK_DAMAGE, GIVE_MAGICAL_OBJECT, GAIN_REROLL, REMOVE_*_OBJECT,
-- CINE_START/STOP, ...; full map in docs/_re/kinds/events-bus.md). Their
-- payload carries live handles (dispatcher/entity as "0x..." strings) plus
-- decoded fields for verified layouts (NETWORK_DAMAGE: value + source_id, the
-- attacker's NET id — the victim is the `dispatcher` the event was delivered
-- to; GIVE_MAGICAL_OBJECT: mo_guid_lo/hi). R.damage turns the damage events
-- into a per-player scoreboard; prefer it over hand-rolling this payload.
--
-- The callback receives a payload table:
--   ev.event  (string)  the event name
--   ev.seq    (number)  per-event fire counter (ordering signal)
--   ev.source (string)  "analytics" firehose / "gameplay" bus
--   ev.ctx/ev.arg       raw arg handles "0x..." (typed-event envelope only)
-- Lifecycle events (ready/tick/exit) pass an empty table.
--
-- Wildcard: R.on("*", function(ev, name) ... end) receives EVERY event;
-- the event name arrives as a second argument.

-- ── event router ──────────────────────────────────────────────────────────
--
-- Every subscription in this state is routed by ONE native "*" handler rather
-- than one native registration per call. The native registry is append-only
-- (there is no unsubscribe binding), so routing in Lua is what makes R.off,
-- R.once and pattern subscriptions possible at all — previously a handler,
-- once added, fired for the rest of the session.
--
-- It also gives one place to keep the event CATALOG (R.events), so a mod
-- author can find out what the game actually fires instead of guessing.

local _subs, _order, _next_sub, _dead_subs = {}, {}, 0, 0
local _seen, _seen_n = {}, 0
local SEEN_CAP = 512          -- distinct event names remembered

local function _record(name, ev)
    local e = _seen[name]
    if not e then
        if _seen_n >= SEEN_CAP then return end
        _seen_n = _seen_n + 1
        e = { count = 0, keys = {} }
        _seen[name] = e
    end
    e.count = e.count + 1
    if type(ev) == "table" then
        for k in pairs(ev) do
            if type(k) == "string" then e.keys[k] = true end
        end
    end
end

-- Message handler for handler calls. `debug` is removed from every mod state by
-- the loader's sandbox, so `debug.traceback` — the idiom this would otherwise
-- use — does not exist here; the native binding is luaL_traceback, which lives
-- in the C library and needs no `debug` table. Falls back to the bare message
-- on an older loader that predates the binding, because a Lua SDK ships
-- independently of the DLL and routinely runs against one.
local _msgh = native and native._internal and native._internal.traceback
              or function(e) return tostring(e) end

-- Consecutive raises before a subscription is latched off. A handler that
-- raises on gameplay:tick raises hundreds of times a second: without a latch
-- that is hundreds of log lines a second, which pushes the loader log past its
-- size cap and rotates away the history that explains anything. Same shape and
-- limit the native hook bridge uses for detour callbacks.
local ERR_LIMIT = 20

local function _dispatch(name, ev)
    _record(name, ev)
    local expired
    -- Iterate a snapshot length: a handler may subscribe while we dispatch,
    -- and the new one must not fire for the event that created it.
    local n = #_order
    for i = 1, n do
        local id = _order[i]
        local s = id and _subs[id]
        if s then
            local hit
            if s.match then
                -- pcall the MATCH, not just the callback. `find` raises on a
                -- malformed pattern ("%", "[", ...), and that raise happens
                -- here in the router — outside the callback's pcall — so it
                -- unwinds the whole dispatch loop. One mod with a bad pattern
                -- would silently stop every OTHER mod's handlers from running,
                -- for every event, with the error surfacing far from its
                -- cause. R.on_match rejects such patterns at subscribe time;
                -- this is the belt to that braces (a pattern can also come
                -- from mod config read at runtime).
                local ok, found = pcall(name.find, name, s.match)
                if not ok then
                    if not s.match_broken then
                        s.match_broken = true
                        R.log("[rsmm.on_match] disabling subscription: pattern "
                              .. string.format("%q", tostring(s.match))
                              .. " is malformed (" .. tostring(found) .. ")")
                    end
                    hit = false
                else
                    hit = found ~= nil
                end
            else
                hit = (s.event == name) or (s.event == "*")
            end
            if hit and not s.cb_disabled then
                if s.once then expired = expired or {}; expired[#expired + 1] = id end
                local ok, err = xpcall(s.cb, _msgh, ev, name)
                if ok then
                    -- Only CONSECUTIVE failures latch: a handler that raises on
                    -- one odd payload and works the rest of the time must not
                    -- accumulate its way to being switched off.
                    s.err_streak = nil
                else
                    local n = (s.err_streak or 0) + 1
                    s.err_streak = n
                    if n <= 3 or n == ERR_LIMIT then
                        R.log("[rsmm.on] handler error on '" .. name .. "' ("
                              .. n .. "): " .. tostring(err))
                    end
                    if n >= ERR_LIMIT then
                        s.cb_disabled = true
                        R.log("[rsmm.on] DISABLING subscription " .. tostring(id)
                              .. " for '" .. tostring(s.event or s.match)
                              .. "': raised " .. n .. " times in a row. Fix it and "
                              .. "re-subscribe (or save the mod to hot-reload).")
                    end
                end
            end
        end
    end
    if expired then for _, id in ipairs(expired) do R.off(id) end end
end

local function _add_sub(s)
    _next_sub = _next_sub + 1
    _subs[_next_sub] = s
    _order[#_order + 1] = _next_sub
    return _next_sub
end

-- Subscribe to one event name ("*" = every event). Returns a handle for R.off.
-- The callback receives (payload, event_name).
function R.on(event, cb)
    assert(type(event) == "string", "R.on: event must be string")
    assert(type(cb) == "function",  "R.on: cb must be function")
    return _add_sub{ event = event, cb = cb }
end

-- Subscribe by LUA PATTERN against the event name — the practical way to take
-- a whole family at once, e.g. every ability event or every network event:
--     R.on_match("^gameplay:ABILITY_", function(ev, name) ... end)
function R.on_match(pattern, cb)
    assert(type(pattern) == "string", "R.on_match: pattern must be string")
    assert(type(cb) == "function",    "R.on_match: cb must be function")
    -- Reject a malformed pattern HERE, where the mod that wrote it is on the
    -- stack. Left to the router, the raise lands in the shared dispatch loop
    -- and reads as "the event bus broke", with nothing pointing at the author.
    local ok, err = pcall(string.find, "", pattern)
    assert(ok, "R.on_match: malformed Lua pattern " ..
               string.format("%q", pattern) .. " (" .. tostring(err) .. ")")
    return _add_sub{ match = pattern, cb = cb }
end

-- Fire at most once, then unsubscribe.
function R.once(event, cb)
    assert(type(event) == "string", "R.once: event must be string")
    assert(type(cb) == "function",  "R.once: cb must be function")
    return _add_sub{ event = event, cb = cb, once = true }
end

-- Cancel a subscription. Returns true if it was live.
function R.off(handle)
    if _subs[handle] == nil then return false end
    _subs[handle] = nil
    _dead_subs = _dead_subs + 1
    -- Compact lazily: a mod that subscribes/unsubscribes per run would
    -- otherwise walk an ever-growing list of holes on every event.
    if _dead_subs > 64 then
        local live = {}
        for _, id in ipairs(_order) do
            if _subs[id] then live[#live + 1] = id end
        end
        _order, _dead_subs = live, 0
    end
    return true
end

-- Number of live subscriptions in this mod (diagnostics).
function R.subscriptions()
    local n = 0
    for _ in pairs(_subs) do n = n + 1 end
    return n
end

-- Publish a loader-derived event locally (source = "loader"). Not exposed to
-- mods: R.emit is the mod-facing door and it refuses these reserved names.
local function _publish(name, ev)
    ev = ev or {}
    ev.event, ev.source = name, "loader"
    _dispatch(name, ev)
end

-- The single native subscription that feeds the router.
native.on_event("*", function(ev, name) _dispatch(name, ev) end)

-- ── event catalog ─────────────────────────────────────────────────────────
--
-- "What events can I even hook?" used to need a Ghidra session. Every event
-- this state has seen is recorded with its fire count and the payload keys it
-- carried, so one play session produces the list.
--
--     R.on("ready", function() R.schedule.after(60, R.events.dump) end)

R.events = {}

-- { name = { count = n, keys = { "k", ... } }, ... }
function R.events.seen()
    local out = {}
    for name, e in pairs(_seen) do
        local keys = {}
        for k in pairs(e.keys) do keys[#keys + 1] = k end
        table.sort(keys)
        out[name] = { count = e.count, keys = keys }
    end
    return out
end

-- Sorted list of event names seen so far, optionally filtered by Lua pattern.
function R.events.list(pattern)
    local out = {}
    for name in pairs(_seen) do
        if not pattern or name:find(pattern) then out[#out + 1] = name end
    end
    table.sort(out)
    return out
end

-- How many times `name` has fired this session.
function R.events.count(name) return (_seen[name] or { count = 0 }).count end

-- The STATIC catalog: every event name mined from the shipped exe, available
-- before anything has fired. R.events.list() answers "what have I seen?";
-- this answers "what exists?".
--
--     for _, n in ipairs(R.events.known("gameplay")) do ... end   -- 150 names
--     R.events.known()            -- every group, fully-qualified
--     R.events.category("BOSS_DEFEATED")  -- "boss"
--
-- Groups: "lifecycle", "derived", "analytics", "gameplay". Gameplay names are
-- returned bare; prefix with "gameplay:" to subscribe. NOT a whitelist — the
-- bus forwards any name the game dispatches, including ones added by a patch.
local _catalog
local function catalog()
    if _catalog == nil then
        local ok, t = pcall(require, "events_gen")
        _catalog = (ok and type(t) == "table") and t or {}
    end
    return _catalog
end

function R.events.known(group)
    local c = catalog()
    if group then
        local out = {}
        for i, n in ipairs(c[group] or {}) do out[i] = n end
        return out
    end
    local out = {}
    for _, g in ipairs({ "lifecycle", "derived", "analytics" }) do
        for _, n in ipairs(c[g] or {}) do out[#out + 1] = n end
    end
    for _, n in ipairs(c.gameplay or {}) do out[#out + 1] = "gameplay:" .. n end
    table.sort(out)
    return out
end

-- Engine-assigned family of a gameplay event name ("combat", "items", ...).
function R.events.category(name)
    local c = catalog()
    return (c.gameplay_category or {})[(name:gsub("^gameplay:", ""))]
end

-- Log the catalog: one line per event with its count and payload keys. This
-- is the discovery tool — run it after playing and the log names every event
-- the game fired, with the fields each carried.
function R.events.dump(pattern)
    local names = R.events.list(pattern)
    R.log(string.format("[rsmm.events] %d event(s) seen this session%s",
        #names, pattern and (" matching '" .. pattern .. "'") or ""))
    local seen = R.events.seen()
    for _, name in ipairs(names) do
        local e = seen[name]
        R.log(string.format("[rsmm.events]   %-44s x%-5d %s",
            name, e.count, table.concat(e.keys, ",")))
    end
    return names
end

-- Publish an event to EVERY mod (including this one). This is the signalling
-- half of cross-mod communication: R.api carries data CALLS, but each mod runs
-- in its own lua_State so a callback cannot be handed across — a producer says
-- "something happened" by emitting, and consumers subscribe with R.on.
--
--     R.emit("mymod:boss_died", { name = "Wolf", chapter = 2 })
--     R.on("mymod:boss_died", function(ev) R.log(ev.name, ev.from) end)
--
-- The payload must be DATA (nil/boolean/number/string/tables of those) since
-- it is marshalled between states. The loader stamps `event`, `source="mod"`
-- and `from=<mod id>` onto every payload, overwriting whatever you set: that
-- is what keeps a mod from impersonating the gameplay bus, whose `source`
-- field is how R.schedule and R.stat know they are on the game's MAIN thread.
--
-- Names are yours except for the loader's own: "gameplay:", "ui:", "rsmm:"
-- and the lifecycle events (setup/ready/tick/exit) are refused. Prefix with
-- your mod id to stay clear of other mods.
function R.emit(event, payload)
    assert(type(event) == "string", "R.emit: event must be string")
    assert(payload == nil or type(payload) == "table",
           "R.emit: payload must be a table or nil")
    if not native.emit then
        R.log("[rsmm] R.emit needs a newer loader; event dropped:", event)
        return false
    end
    return native.emit(event, payload) and true or false
end

-- named engine functions ------------------------------------------------
--
-- The symbol map (data/symbols.json) gives engine functions stable
-- semantic names + a `cabi` (return + arg types). R.engine lets a mod call
-- them by name with the right marshalling — no raw FUN_xxxxxxxx addresses,
-- no manual signature strings. Two equivalent forms:
--
--     local rsc = R.engine.call("Resource_LookupByPath", path, 0, 0, 0)
--     local rsc = R.engine.fn.Resource_LookupByPath(path, 0, 0, 0)
--
-- `R.engine.fn.<Name>` exposes every callable symbol as a method (built
-- lazily from the map, so new symbols appear automatically). Browse the
-- set with `R.engine.names()` or `rsmm symbols list`. The address is
-- resolved at runtime by byte pattern (survives game updates), and the
-- native call signature comes from the symbol's cabi (see engine_gen.lua).
--
-- For an address the map doesn't know yet, drop to the escape hatch:
--     R.engine.call_raw(va, "psppp", path, 0, 0, 0)  -- explicit sig
-- (sig codes: v=void i=int32 u=uint32 p/l=ptr/int64 f=float d=double s=string)

R.engine = {}

local _engine_map
local function engine_map()
    if _engine_map == nil then
        local ok, t = pcall(require, "engine_gen")
        _engine_map = (ok and type(t) == "table") and t or {}
        if not ok then R.log("[rsmm.engine] engine_gen table missing; names unavailable") end
    end
    return _engine_map
end

-- Resolve a semantic name to its runtime virtual address (or nil).
function R.engine.resolve(name)
    assert(type(name) == "string", "R.engine.resolve: name must be string")
    local e = engine_map()[name]
    if not e then R.log("[rsmm.engine] unknown symbol:", name); return nil end
    local base = I.resolve(e.pattern)
    if not base then return nil end
    return base + (e.offset or 0)
end

-- Call a named engine function. The native call signature is taken from the
-- symbol's `cabi` (generated into engine_gen.lua), so a mod just passes the
-- actual arguments — no manual signature string:
--
--     local res = R.engine.call("Resource_LookupByPath", path, 0, 0, 0)
--
-- Arg/return marshalling per the symbol's sig codes (v/i/u/p/l/f/d/s):
-- integers for i/u/p/l, numbers for f/d, Lua strings for s. Returns the
-- typed result (nil for void or if the symbol can't be resolved).
function R.engine.call(name, ...)
    local e = engine_map()[name]
    if not e then R.log("[rsmm.engine] unknown symbol:", name); return nil end
    local va = R.engine.resolve(name)
    if not va then return nil end
    if not e.sig then
        R.log("[rsmm.engine] no cabi/sig for", name, "-- use R.engine.call_raw(va, sig, ...)")
        return nil
    end
    return I.call(va, e.sig, ...)
end

-- Escape hatch: call any resolved address with an explicit signature string.
function R.engine.call_raw(va, sig, ...)
    return I.call(va, sig, ...)
end

-- The native call signature string for a named symbol (or nil).
function R.engine.sig(name)
    local e = engine_map()[name]
    return e and e.sig or nil
end

-- List the semantic names available to R.engine.call.
function R.engine.names()
    local out = {}
    for k in pairs(engine_map()) do out[#out + 1] = k end
    table.sort(out)
    return out
end

-- Named accessors: every callable symbol is exposed as
-- R.engine.fn.<Name>(...) so mods can call engine functions like methods
-- instead of stringly-typed names. Built lazily from the generated map, so
-- new symbols appear automatically with no edits here.
R.engine.fn = setmetatable({}, {
    __index = function(_, name)
        local fn = function(...) return R.engine.call(name, ...) end
        rawset(R.engine.fn, name, fn)  -- memoize
        return fn
    end,
})

-- give-item ----------------------------------------------------------------
--
-- Grant magical objects at runtime by dispatching GIVE_MAGICAL_OBJECT on the
-- gameplay bus. Requires the bus to be armed (RSMM_ENABLE_GAMEPLAY_EVENTS=1),
-- because the hero dispatcher is captured from live hero-anchored events.
--
-- The engine grants the item straight to the hero's inventory (no world orb)
-- and fires a SPAWN_MO cascade. Item identity is the GUID at def+0x88/+0x90 of
-- a g_MagicalObjectPool source entry — see docs/_re/kinds/events-bus.md.
--
--     R.give.random()            -- grant a random loaded item
--     R.give.by_index(0)         -- grant pool source slot 0
--     R.give.by_guid(lo, hi)     -- grant an explicit identity GUID
--     for i, lo, hi in R.give.each() do ... end   -- enumerate the pool

R.give = {}

-- One-time warning when absolute data addresses are disabled because the
-- game build no longer matches the symbol map (loader va-gate). Reads then
-- return nil instead of garbage; see loader.h va_globals_trusted().
local _va_warned = false
local function _va_ok(feature)
    if not I.va_trusted then return true end   -- older loader: no gate
    local ok, trusted = pcall(I.va_trusted)
    if not ok or trusted ~= false then return true end
    if not _va_warned then
        _va_warned = true
        R.log("[rsmm] game build != symbol-map build — " .. feature ..
              " (and other va-global features) disabled until data is updated")
    end
    return false
end

-- A heap pointer read out of a baked va slot is only build-trustworthy after
-- _va_ok. Even then, guard the dereference: a mis-derived va can hold a
-- consistent-but-wrong pointer that the build byte-check cannot catch (get
-- reads are fault-safe and degrade to nil, but a set WRITE to a wrong-but-mapped
-- address silently corrupts engine memory). _ptr_plausible rejects the obvious
-- garbage — null, non-canonical (outside the x64 user-space range), unaligned —
-- so a bad pointer degrades to a no-op instead of a fault or a stray write.
local function _ptr_plausible(p)
    if type(p) ~= "number" then return false end
    if p < 0x10000 then return false end               -- null / low reserved page
    if p > 0x00007fffffffffff then return false end     -- non-canonical user-space
    if (p % 8) ~= 0 then return false end               -- heap objects are 8-aligned
    return true
end

-- ── pointer-safety library ────────────────────────────────────────────────
-- Every loader crash this class (ctx-deref 2026-07-15, probe→engine walk
-- 2026-07-17) was the same mistake: handing a pointer the SDK never fully
-- validated to engine code, which then dereferences it without a guard.
-- `read_*` in the native layer is page-guarded (bad read → nil, no fault) so
-- probing is safe — but the moment a pointer becomes an ARGUMENT to
-- R.engine.call, the engine owns the deref and a bad value faults hard.
--
-- Rule (also in CLAUDE.md): never pass a probed or baked pointer to
-- R.engine.call without validating the full structure the callee will
-- traverse. Use the helpers below to build that validator, and prefer
-- R.engine.call_safe so the guard can't be forgotten.
local IMG_SPAN = 0x1600000                              -- .text+.rdata+.data span

-- Pointer lands inside the loaded game module (a vftable / static global).
local function _in_image(p)
    if not _ptr_plausible(p) then return false end
    local base = I.module_base()
    if not base or base == 0 then return false end
    return p >= base and p < base + IMG_SPAN
end

-- `obj` looks like a live C++ object: plausible, and *(obj) (its vftable) is
-- a pointer into the game image. Cheap first gate before any vcall.
local function _obj_has_vtable(obj)
    if not _ptr_plausible(obj) then return false end
    return _in_image(I.read_u64(obj))
end

-- A {data, u32 count} pointer-vector at obj+data_off/obj+count_off is fully
-- traversable: plausible data ptr, sane count, and (when check_entry is given)
-- every element passes check_entry(elem, obj). Bound caps the count so a
-- garbage length can't spin. This is the generic form of the Xp component
-- array gate — use it before handing `obj` to any engine walker.
local function _vector_valid(obj, data_off, count_off, opts)
    opts = opts or {}
    if not _ptr_plausible(obj) then return false end
    local data = I.read_u64(obj + data_off)
    local n    = I.read_u32(obj + count_off)
    if not data or data == 0 or not _ptr_plausible(data) then return false end
    if not n or n < (opts.min or 0) or n > (opts.max or 0x400) then return false end
    local check = opts.check_entry
    if check then
        for i = 0, n - 1 do
            if not check(I.read_u64(data + i * 8), obj, i) then return false end
        end
    end
    return true
end

-- Guarded engine call: `ptr_args` is a list of 1-based argument indices that
-- MUST be plausible pointers (or a validator fn) before the call is allowed.
-- On any failure the call is REFUSED (returns nil) instead of faulting the
-- game — the fail-closed contract every mutating path already promises.
function R.engine.call_safe(name, ptr_args, ...)
    local args = { ... }
    for _, spec in ipairs(ptr_args or {}) do
        local idx, validate
        if type(spec) == "table" then idx, validate = spec[1], spec[2] else idx = spec end
        local v = args[idx]
        if validate then
            if not validate(v) then
                R.log("[rsmm.engine] call_safe refused " .. tostring(name)
                      .. ": arg " .. tostring(idx) .. " failed validator")
                return nil
            end
        elseif not _ptr_plausible(v) then
            R.log("[rsmm.engine] call_safe refused " .. tostring(name)
                  .. ": arg " .. tostring(idx) .. " not a plausible pointer")
            return nil
        end
    end
    return R.engine.call(name, ...)
end

-- Expose the primitives to advanced mods / the SDK's own paths.
R.ptr = {
    plausible    = _ptr_plausible,
    in_image     = _in_image,
    has_vtable   = _obj_has_vtable,
    vector_valid = _vector_valid,
}

-- g_MagicalObjectPool: pointer global; *ptr = { source array @+0,
-- u32 source count @+8, runtime array @+0x10, u32 runtime count @+0x18 }.
-- Re-derived 2026-07-10 after the 2026-07-09 game patch (readers of the new
-- slot dereference +0x10/+0x18 exactly like the old pool, e.g. FUN_1402b3030).
local GIVE_POOL_VA = 0x14143cc18
local GIVE_IMG_BASE = 0x140000000

-- Hero dispatcher, captured from any hero-anchored gameplay event. These all
-- fire at the local hero's own dispatcher (unlike GAIN_HEALTH, which fires at
-- the heal source). Verified in-game 2026-06-12.
local _give_hero = nil
local _GIVE_ANCHORS = {
    ["gameplay:GAIN_DREAM_SHARDS"] = true,
    ["gameplay:ABILITY_EXIT"] = true,
    ["gameplay:ENERGY_COUNTER_DEC"] = true,
    ["gameplay:ENERGY_COUNTER_INC"] = true,
    ["gameplay:COMBO_LINK"] = true,
    ["gameplay:INTERACTION_VALIDATE"] = true,
}

-- Forward-declared; assigned once the entity section (which owns _hero_char and
-- the shared slot) is defined below. Called when the live hero dispatcher
-- changes (hero switch / new run) to drop the now-stale HP-carrier capture.
local _invalidate_hero_capture
-- True while the natively captured hero still reads live. Used to tell a hero
-- SWITCH (capture is stale, re-capture) from an ALLY acting (capture is fine,
-- leave it alone) — see the anchor handler below.
local _hero_capture_is_live

-- The NamedEventDispatcher sub-object lives at some fixed offset inside its
-- owning entity; subtract it to reach the entity and test whether that entity
-- is a grantable hero.
--
-- LEARNED, NOT HARDCODED. It used to be the literal 0x4d8, which was correct
-- until the 2026-07-09 game patch moved it — after which `disp - 0x4d8` landed
-- in the middle of nothing, the component-store slot read a -1 sentinel, and
-- the discriminator rejected the ONE real hero in the session. The symptom was
-- "give only works on Aladdin", and it took a live diag to find. A constant
-- that silently goes wrong on a patch and degrades a feature is worth spending
-- a few lines to stop hardcoding.
--
-- Both ends are observable at runtime: the hero entity is captured natively
-- (spawn-init -> shared slot, validated against its own HP/mirror fields, a
-- path that never goes through a dispatcher), and hero-anchored gameplay
-- events hand us the dispatcher. Their difference IS the offset.
local _DISPATCHER_ENTITY_OFF = nil       -- nil until corroborated (below)
local _DISP_OFF_MAX   = 0x4000           -- a sub-object, not a separate alloc

--- Learn the offset from a dispatcher whose owning entity we already know.
--
-- The candidate is `disp - hero`, and it is accepted only once TWO different
-- hero pointers have produced the same value.
--
-- Corroboration is the only evidence available here, and the obvious
-- alternative does not work: asking the engine `is_grant_target(disp - off)`
-- proves nothing, because `disp - off` IS `hero` by construction, so it merely
-- re-confirms the hero we already trusted. Any dispatcher sitting 8-aligned
-- within `_DISP_OFF_MAX` above the hero would have latched — including a
-- summon's, which also fires anchor events. Latching a wrong offset is
-- permanent (there is no re-learn) and turns `_dispatcher_is_hero` into a
-- rejector of the real hero: precisely the "give only works on Aladdin"
-- failure this code exists to prevent.
--
-- The hero pointer changes between runs and on a character switch, so a fixed
-- layout offset reproduces across those boundaries and a coincidental heap
-- delta does not. The cost is that the strict summon filter stays dormant
-- until a second hero has been seen; until then the caller fails OPEN, which
-- is exactly the behaviour that shipped before, so nothing regresses while it
-- waits.
local _disp_off_seen = {}        -- candidate offset -> hero it came from

local function _learn_dispatcher_offset(disp)
    if _DISPATCHER_ENTITY_OFF or type(disp) ~= "number" then return end
    local hero = R.entity and R.entity.hero and R.entity.hero()
    if type(hero) ~= "number" or hero == 0 or disp <= hero then return end
    local off = disp - hero
    if off > _DISP_OFF_MAX or off % 8 ~= 0 then return end
    -- Both ends must look like live objects before their difference means
    -- anything: the dispatcher is a sub-object with its own vtable.
    if not _ptr_plausible(hero) or not _obj_has_vtable(disp) then return end

    local prev = _disp_off_seen[off]
    if prev == nil then
        _disp_off_seen[off] = hero
        return
    end
    if prev == hero then return end      -- same hero twice is not independent
    _DISPATCHER_ENTITY_OFF = off
    R.log(string.format(
        "[rsmm.give] dispatcher sits at entity+0x%x (corroborated by two "
        .. "distinct heroes; the hardcoded 0x4d8 went stale on 2026-07-09)",
        off))
end

-- True iff `disp`'s owning entity is a grantable hero (not a summon/pet). Uses
-- the native, page-guarded magical-object-component lookup when available; if
-- the native side is older and lacks the binding, fall back to accepting the
-- dispatcher (prior behavior) rather than breaking give outright.
local function _dispatcher_is_hero(disp)
    if type(I.is_grant_target) ~= "function" then return true end
    -- Until the offset has been learned there is no way to get from a
    -- dispatcher to its entity, so accept the dispatcher. See below on why
    -- accepting is the safe direction.
    if not _DISPATCHER_ENTITY_OFF then
        _learn_dispatcher_offset(disp)
        -- Fall through when that call is the one that corroborated it: the
        -- offset is usable immediately, and returning early here would skip
        -- the discriminator for the very dispatcher that taught us.
        if not _DISPATCHER_ENTITY_OFF then return true end
    end
    local entity = disp - _DISPATCHER_ENTITY_OFF
    -- Fail OPEN, not closed. Only TRUST a positive native signal; when the
    -- check cannot run (implausible entity or empty store), accept the
    -- dispatcher. The game's own grant handler (FUN_140397030) re-checks
    -- grantability and safely no-ops a non-hero target, so accepting a summon
    -- here cannot crash — worst case a grant is a silent no-op until the
    -- hero's own anchor event re-captures. Rejecting wrongly is the expensive
    -- direction: that is what "give only works on Aladdin" was.
    if not _ptr_plausible(entity) then return true end
    local store = I.read_u64(entity + 8)
    if not _ptr_plausible(store) then return true end
    return I.is_grant_target(entity) == true
end

-- Is this dispatcher's entity controlled by THIS machine?
--
-- Returns true/false, or nil when it cannot be told (offset not learned yet,
-- no net component — i.e. single player, where everything is local).
--
-- CO-OP CORRECTNESS, learned from a 4-player session on 2026-08-15: allies
-- fire every one of the anchor events below from their OWN dispatchers. With
-- no local test, `_give_hero` flip-flopped to whichever ally last acted, and
-- each flip invalidated the captured hero — the log filled with a re-capture
-- twice a second, and R.give / R.combat / R.stat spent the run pointed at
-- somebody else's character.
-- Offset of the HUD HP mirror pointer on a hero object. Declared HERE, above
-- its first use, not down in the entity section: a Lua local is invisible to
-- code written earlier in the file, so referencing it from this function
-- resolved to a nil GLOBAL and every anchor event raised inside the event
-- router — which pcalls handlers, so the ally guard silently did nothing and
-- the hero capture stopped updating. Caught by the spec, not in-game.
local ENTITY_HUDMIRROR_OFF = 0x1d80      -- ptr to the HUD HP mirror (hero-only)
local ENTITY_ISLOCAL_OFF   = 0x1d88      -- 1 = this machine's player

local function _dispatcher_is_local(d)
    if not _DISPATCHER_ENTITY_OFF then return nil end
    local e = d - _DISPATCHER_ENTITY_OFF
    if not _ptr_plausible(e) then return nil end
    -- The engine's OWN is-local byte, read directly.
    --
    -- Not Entity_GetNetComponent: that walks the entity component map with no
    -- guard, and on an object whose store slot holds the -1 sentinel it took
    -- the whole game down (2026-08-15, dump a97c76fe — AV reading
    -- 0xffff…ffff at +0x62). Probing is safe; handing a probed pointer to
    -- engine code is not.
    --
    -- Not the HUD mirror either, which was the first replacement: a live probe
    -- showed an ALLY (is-local byte 0) carrying a non-null mirror pointer, so
    -- "has a mirror" is not the same question. The byte at +0x1d88 is what the
    -- engine itself branches on (hero vs ally kill streak in the damage
    -- bookkeeping), and reading it costs one guarded byte.
    local flag = I.read_u8(e + ENTITY_ISLOCAL_OFF)
    if flag == 1 then return true end
    if flag == 0 then return false end
    return nil                                   -- unreadable: cannot tell
end

R.on("*", function(ev, name)
    if _GIVE_ANCHORS[name] and type(ev.dispatcher) == "string" then
        local d = tonumber(ev.dispatcher)
        -- An ally's dispatcher is not ours to capture.
        if d and _dispatcher_is_local(d) == false then return end
        if d and d ~= 0 and d ~= _give_hero and _dispatcher_is_hero(d) then
            -- Only a dispatcher whose entity is a real hero reaches here. Summon
            -- and pet entities also fire anchor events (ABILITY_EXIT, ...) from
            -- their OWN dispatcher; accepting one would clobber _give_hero to a
            -- non-hero with no GIVE_MAGICAL_OBJECT subscriber, so every grant
            -- would silently no-op. That is the "give only works on Aladdin" bug
            -- (Aladdin has no persistent summon to clobber the capture).
            --
            -- A different (valid hero) dispatcher than last seen USUALLY means
            -- the local hero changed — switched character, or a fresh run
            -- reallocated the entity — so the captured HP-carrier is stale.
            --
            -- But not always: in co-op an ally's dispatcher reaches here too
            -- whenever the local test above cannot answer (offset not learned
            -- yet). Only drop the capture when it has actually gone stale;
            -- throwing away a LIVE hero because somebody else cast a spell is
            -- what made every R.combat call in a 4-player run target a random
            -- character.
            if _give_hero ~= nil and _invalidate_hero_capture
                and not (_hero_capture_is_live and _hero_capture_is_live()) then
                _invalidate_hero_capture()
            end
            _give_hero = d
        end
    end
end)

-- True once a hero dispatcher has been seen (i.e. give will work). Until the
-- hero acts at least once in a run, grants are deferred.
function R.give.ready() return _give_hero ~= nil end

-- The hero dispatcher pointer (or nil). Advanced; most mods want the helpers.
function R.give.hero() return _give_hero end

local function _give_pool_vec()
    if not _va_ok("R.give") then return nil end
    local base = I.module_base()
    if not base or base == 0 then return nil end
    local vec = I.read_u64(base + (GIVE_POOL_VA - GIVE_IMG_BASE))
    if not _ptr_plausible(vec) then return nil end
    -- A mis-derived pool pointer reads an absurd source count; a real pool is a
    -- small non-negative number of loaded definitions. Refuse the outliers so a
    -- bad va can never drive an inject/enumerate off a garbage base.
    local n = I.read_u32(vec + 8)
    if type(n) ~= "number" or n > 100000 then return nil end
    return vec
end

-- Number of loaded magical-object definitions (pool source count), or 0.
function R.give.count()
    local vec = _give_pool_vec()
    if not vec then return 0 end
    local data = I.read_u64(vec)
    local n = I.read_u32(vec + 8)
    if not data or data == 0 or not n then return 0 end
    return n
end

-- The identity GUID (lo, hi) of pool source slot `i` (0-based), plus the def
-- pointer; nil if out of range or the pool can't be read.
function R.give.guid_at(i)
    local vec = _give_pool_vec()
    if not vec then return nil end
    local data = I.read_u64(vec)
    local n = I.read_u32(vec + 8)
    if not data or data == 0 or not n or i < 0 or i >= n then return nil end
    local def = I.read_u64(data + i * 8)
    if not def or def == 0 then return nil end
    return I.read_u64(def + 0x88), I.read_u64(def + 0x90), def
end

-- Iterator over (index, guid_lo, guid_hi) for every loaded item.
function R.give.each()
    local n = R.give.count()
    local i = -1
    return function()
        i = i + 1
        if i >= n then return nil end
        local lo, hi = R.give.guid_at(i)
        return i, lo, hi
    end
end

-- Grant the item with identity GUID (lo, hi). Returns true on dispatch.
-- Fails (false) if the bus hasn't armed a hero dispatcher yet.
function R.give.by_guid(lo, hi)
    if not _give_hero then
        R.log("[rsmm.give] no hero dispatcher yet — the hero must act once first")
        return false
    end
    local ev = R.engine.call("NamedEvent_GiveMagicalObject_Ctor", I.scratch(0x60))
    if not ev or ev == 0 then
        R.log("[rsmm.give] GiveMagicalObject ctor failed (symbol unresolved?)")
        return false
    end
    I.poke(ev + 0x50, lo or 0, 8)
    I.poke(ev + 0x58, hi or 0, 8)
    -- Validate the dispatcher AT THE CALL, not just when it was captured.
    -- `_give_hero` is a raw engine pointer that outlives nothing: a run ending
    -- or a character switch frees the hero, and the capture is only refreshed
    -- when an anchor event happens to fire. Handing a stale one to the engine
    -- is the loader's #1 crash class — native reads are page-guarded, but the
    -- instant a pointer is a call ARGUMENT the engine owns the deref. A dead
    -- dispatcher no longer looks like a live object, so require the vtable.
    -- Checked here rather than through `call_safe`: NamedEvent_Dispatch is
    -- declared "vpp" — void — so a successful call and a refusal both come
    -- back nil, and there would be no way to tell them apart.
    if not _obj_has_vtable(_give_hero) then
        R.log(string.format(
            "[rsmm.give] dispatcher 0x%x no longer looks live (run ended or "
            .. "hero switched?); dropping the grant and clearing the capture",
            _give_hero or 0))
        _give_hero = nil
        if _invalidate_hero_capture then _invalidate_hero_capture() end
        return false
    end
    R.engine.call("NamedEvent_Dispatch", _give_hero, ev)
    return true
end

-- Grant pool source slot `i` (0-based). Returns true on dispatch.
function R.give.by_index(i)
    local lo, hi = R.give.guid_at(i)
    if not lo then
        R.log("[rsmm.give] no item at pool index", i)
        return false
    end
    return R.give.by_guid(lo, hi)
end

-- Grant a random loaded item. Returns the granted index, or nil.
function R.give.random()
    local n = R.give.count()
    if n == 0 then return nil end
    local i = math.random(0, n - 1)
    if R.give.by_index(i) then return i end
    return nil
end

-- Number of magical objects currently in the runtime (owned/active) pool array.
function R.give.owned_count()
    local vec = _give_pool_vec()
    if not vec then return 0 end
    local data = I.read_u64(vec + 0x10)
    local n = I.read_u32(vec + 0x18)
    if not data or data == 0 or not n then return 0 end
    return n
end

-- Iterator over the hero's currently-owned magical objects (runtime pool
-- array @vec+0x10/+0x18), yielding (index, guid_lo, guid_hi, def_ptr). The
-- runtime entries mirror the source-array def layout (GUID @def+0x88/+0x90).
-- EXPERIMENTAL: confirm the owned-set semantics in-game.
function R.give.owned()
    local vec = _give_pool_vec()
    local data = vec and I.read_u64(vec + 0x10) or 0
    local n = (vec and I.read_u32(vec + 0x18)) or 0
    local i = -1
    return function()
        i = i + 1
        if not data or data == 0 or i >= n then return nil end
        local def = I.read_u64(data + i * 8)
        if not def or def == 0 then return nil end
        return i, I.read_u64(def + 0x88), I.read_u64(def + 0x90), def
    end
end

-- True if the hero currently owns the magical object with identity GUID (lo,hi).
function R.give.owns(lo, hi)
    for _, glo, ghi in R.give.owned() do
        if glo == lo and ghi == hi then return true end
    end
    return false
end

-- The second submodule shape: a module that returns a FUNCTION, called with an
-- env of the parent values it needs, and which populates R (and F) in place
-- rather than handing back a table to merge. That is what a namespace lifted
-- out of this chunk needs — it owns private helpers and installs its own
-- hooks, neither of which survives the merge-a-table contract.
--
-- The function's own return value comes back as the SECOND result: a lifted
-- namespace that other parts of this chunk still read locals from (R.entity's
-- offsets, its capture predicates) hands them back that way, and the caller
-- assigns them to the parent locals the old inline code declared.
--
-- Failure is LOGGED AND SURVIVED, exactly like _submodule: a missing or broken
-- module must cost its own namespace, never `require "rsmm"` for every mod.
local function _submodule_fn(name, env)
    local ok, m = pcall(require, "rsmm." .. name)
    if not ok or type(m) ~= "function" then
        R.log("[rsmm] submodule rsmm." .. name .. " unavailable: " .. tostring(m))
        return false
    end
    local ran, res = pcall(m, env)
    if not ran then
        R.log("[rsmm] submodule rsmm." .. name .. " failed to install: " .. tostring(res))
        return false
    end
    return true, res
end

-- entity / combat -------------------------------------------------------
--
-- Lives in rsmm/entity.lua. R.entity reads the local hero's health, R.combat
-- changes it through the engine's own Entity_ModifyHealth, and the same file
-- owns the hero CAPTURE (the character object is not the bus dispatcher and
-- cannot be derived from it, so it is grabbed from a hero-bound handler's
-- first argument) and the entity-value store R.stat / R.modifier read through.
--
--   R.entity.hp() / max_hp() / hp_frac() / ready()
--   R.combat.heal(20) / damage(15) / set_hp(50)
--
-- Unlike rsmm/damage.lua this namespace is not self-contained: the rest of
-- this chunk reads its offsets and predicates as plain locals, so it hands
-- them back and they are assigned here. Two of them (_hero_capture_is_live,
-- _invalidate_hero_capture) are forward-declared far above, because the give
-- path calls them through those upvalues.
local ENTITY_IMG_BASE, SHARED_HERO_SLOT, LOBBY_REFRESH_SLOT

-- Cross-state flag: "report every lobby member as having picked no hero".
--
-- It CANNOT be a Lua variable. Every mod gets its own lua_State with its own
-- copy of this file, and only ONE state can own the detour on
-- LobbyAttributes_Parse — whichever mod armed it first. In practice that is
-- steamroller, so duplicate-heroes was setting a flag in a state whose
-- callback never runs, and the blanking was a no-op for three playtests while
-- looking correctly installed in the log ("attribute parser hooked" is printed
-- by the OWNING state, and the owner logs it whether or not anyone else
-- wanted anything from it).
--
-- g_shared is the one channel every state sees. Slots 0-7 are mod-writable
-- (0 = hero handle, 7 = lobby refresh); 6 is free.
local DUPE_BLANK_SLOT = 6

-- HeroSelect_ValidateBlockedPtr, as an RVA off the module base.
--
-- The byte at *(this) + 0x11a8 is what greys the book's "Validate Hero
-- Button". TWO sites read it and set the same widget pair from it — one calls
-- HeroSelect_SetConfirmEnabled, the other inlines the identical pair — which
-- is why hooking one setter left the button dead. It also writes the '*'
-- padlock glyph. One byte, two copies of the same decision.
local VALIDATE_BLOCKED_RVA = 0x143cb58
local VALIDATE_BLOCKED_OFF = 0x11a8
local ENTITY_VALCTX_OFF, EV_STORE_OFF
local _native_capture_active, _hero_plausible, _ev_ctx, _ctx_chain_ok
do
    local ok, x = _submodule_fn("entity", {
        I = I, R = R,
        _va_ok = _va_ok, _ptr_plausible = _ptr_plausible,
        ENTITY_HUDMIRROR_OFF = ENTITY_HUDMIRROR_OFF,
        ENTITY_ISLOCAL_OFF   = ENTITY_ISLOCAL_OFF,
    })
    -- Fail LOUD. R.damage can be absent and the SDK is merely poorer; R.entity
    -- is what R.stat, R.xp, R.give and R.damage all resolve the hero through,
    -- so a silent nil here surfaces much later as "the hero was never
    -- captured" with nothing pointing at the cause.
    assert(ok and type(x) == "table",
           "rsmm: rsmm/entity.lua failed to install -- the SDK cannot run without it")
    ENTITY_IMG_BASE, SHARED_HERO_SLOT = x.ENTITY_IMG_BASE, x.SHARED_HERO_SLOT
    LOBBY_REFRESH_SLOT = x.LOBBY_REFRESH_SLOT
    ENTITY_VALCTX_OFF, EV_STORE_OFF = x.ENTITY_VALCTX_OFF, x.EV_STORE_OFF
    _native_capture_active = x._native_capture_active
    _hero_plausible        = x._hero_plausible
    _ev_ctx                = x._ev_ctx
    _ctx_chain_ok          = x._ctx_chain_ok
    -- Into the forward declarations near the top of the chunk, not new locals.
    _hero_capture_is_live    = x._hero_capture_is_live
    _invalidate_hero_capture = x._invalidate_hero_capture
    -- Check against an explicit LIST, not `pairs(x)`. A nil value is not a key
    -- in Lua, so `{ EV_STORE_OFF = nil }` iterates as an empty entry and a
    -- pairs() sweep sees nothing wrong — which is exactly how a dropped export
    -- would reach a use site as a silent nil.
    for _, k in ipairs({ "ENTITY_IMG_BASE", "SHARED_HERO_SLOT",
                         "LOBBY_REFRESH_SLOT", "ENTITY_VALCTX_OFF",
                         "EV_STORE_OFF", "_native_capture_active",
                         "_hero_plausible", "_ev_ctx", "_ctx_chain_ok",
                         "_hero_capture_is_live", "_invalidate_hero_capture" }) do
        assert(x[k] ~= nil, "rsmm/entity.lua did not export " .. k)
    end
end

-- game modifiers ("negative modes" / run mutators) ----------------------
--
-- The toggleable run mutators (No boss timer, No minimap, More experience,
-- Day only, ...) plus the difficulty / XP scalars each have a CRC-keyed value in
-- the entity-value store. R.modifier reads them by name. The keys are the literal
-- ids the engine registers them under (Ghidra: EntityValueRegistry_RegisterAll,
-- FUN_1401d9b70); full map + provenance in docs/_re/kinds/game-modifiers.md.
--
--   R.modifier.value("Game Difficulty")  -- numeric value (or nil)
--   R.modifier.active("No minimap")      -- true if the toggle is on this run
--   R.modifier.names()                   -- known modifier/scalar names (sorted)
--
-- NOTE: read-only and pending in-game verification that the modifier state lives
-- on the hero's value store (vs a global game entity); a wrong store just makes
-- every read return 0/nil, never faults.
R.modifier = {}

local _MODIFIER_KEYS = {
    -- toggles (bool: value ~= 0 => active)
    ["No boss timer"]                            = 0x1a7945fc,
    ["Less day/night half cycle"]                = 0x1a77d42d,
    ["More experience"]                          = 0x1a77e2e4,
    ["No revive token"]                          = 0x1a793d1a,
    ["No minimap"]                               = 0x99f27eac,
    ["One chapter"]                              = 0x1a8a3688,
    ["Day only"]                                 = 0x1a8b53b4,
    ["Night only"]                               = 0x1a8b53bc,
    ["Random hero at map start"]                 = 0x1ab183ab,
    ["All same heroes"]                          = 0x1ab58780,
    -- difficulty / xp scalars
    ["Game Difficulty"]                          = 0x18700873,
    ["Difficulty Xp Modifier"]                   = 0x19bddb2e,
    ["Global Xp Modifier"]                       = 0x187afd1d,
    ["Rare Skill Chance Modifier"]               = 0x1871c2fa,
    ["Dream Shard Costs Modifier"]               = 0x187310ec,
    ["Half Cycle Count Before Boss Awakens"]     = 0x187443de,
    ["Camp Difficulty Modifier"]                 = 0x187aaecf,
    ["Camp Difficulty Modifier Chance To Apply"] = 0x187ab36e,
}

-- Numeric value of a named modifier/scalar, or nil (unknown name / no hero).
function R.modifier.value(name)
    local key = _MODIFIER_KEYS[name]
    if not key then
        R.log("[rsmm.modifier] unknown modifier name: " .. tostring(name))
        return nil
    end
    return R.entity.value(key)
end

-- True if a toggle modifier is active this run (value present and non-zero).
function R.modifier.active(name)
    local v = R.modifier.value(name)
    return type(v) == "number" and v ~= 0
end

-- The known modifier / scalar names, sorted (for listing / iteration).
function R.modifier.names()
    local t = {}
    for k in pairs(_MODIFIER_KEYS) do t[#t + 1] = k end
    table.sort(t)
    return t
end

-- Read a raw entity-value key the name table doesn't cover (forward-compat).
function R.modifier.value_by_key(key) return R.entity.value(key) end

-- stats + experience ----------------------------------------------------
--
-- Both live in rsmm/progression.lua. R.stat reads and grants any per-hero stat
-- out of the engine's CRC-keyed entity-value store (max health, attack power,
-- crit, move speed, dream shards, xp multipliers); R.xp reads level/xp off the
-- XpComponent and grants through the engine's own gain-experience routine.
--
--   R.stat.get("attack_power") / R.stat.grant("crit_chance", 0.1)
--   R.stat.enable_writes()          -- opt-in; writes are engine-mutating
--   R.xp.level() / R.xp.xp() / R.xp.grant(100)
--
-- One file for two namespaces because R.xp reads the stat section's write flag
-- and log throttle, and those are the only values either shares. That is also
-- why this module exports nothing: everything crossing the boundary goes IN.
_submodule_fn("progression", {
    native = native, I = I, R = R,
    _va_ok = _va_ok, _ptr_plausible = _ptr_plausible,
    _in_image = _in_image, _obj_has_vtable = _obj_has_vtable,
    _vector_valid = _vector_valid,
    GIVE_IMG_BASE     = GIVE_IMG_BASE,
    ENTITY_IMG_BASE   = ENTITY_IMG_BASE,
    ENTITY_VALCTX_OFF = ENTITY_VALCTX_OFF,
    EV_STORE_OFF      = EV_STORE_OFF,
    _hero_plausible   = _hero_plausible,
    _ev_ctx           = _ev_ctx,
    _ctx_chain_ok     = _ctx_chain_ok,
})

-- hero (identity / per-hero scope) --------------------------------------
--
-- Every hero has its own ability/event vocabulary (Piper's rats, Juliet's
-- mechanics, Scarlet's crows, ...). REACTING to those events already works —
-- they arrive on the gameplay bus by name, e.g.:
--
--     R.on("gameplay:ENCHANTED_BLADES_HEAVY_IMPACT", function(ev) ... end)
--
-- and only ever fire when the hero that owns the ability acts, so subscribing
-- is implicitly per-hero. R.hero adds the missing piece: a stable handle to the
-- CURRENT hero plus identity, so a mod can scope its logic ("only for Juliet")
-- and so we can build a per-hero event catalog.
--
--   R.hero.handle()   -- live hero dispatcher pointer (instant; nil pre-act)
--   R.hero.ready()    -- true once the hero has acted once this run
--   R.hero.name()     -- "Piper"/"Scarlet"/... from event signature, or nil
--   R.hero.is("Piper")-- true if the current hero matches (case-insensitive)
--   R.hero.catalog()  -- dump this hero's distinctive events (seeds signatures)
--   R.hero.on(name, cb) -- R.on("gameplay:"..name) gated to fire only when a
--                          hero is active this run (convenience for ability hooks)
R.hero = {}

-- IDENTITY MODEL: event-signature. Ghidra confirmed the hero entity has no
-- type/def field — it's a generic oe::Entity component aggregate (carrier
-- vtable 0x140f2b930, ctor FUN_14038e320: dozens of component arrays, no
-- herodef). So "which hero" is inferred from the EXCLUSIVE ability events the
-- hero fires on the gameplay bus (Piper -> rat/flute events, Scarlet -> crows,
-- ...). Robust (no fragile offsets) and engine-aligned. The name<->event map
-- is seeded from observed play (R.hero.catalog dumps a hero's distinctive
-- events; fold them into _HERO_SIGNATURES below).

-- Live hero dispatcher (instant — captured from the first hero-anchored event,
-- shared with R.give). This is the right "current hero" handle for emitting
-- events at the hero; it does NOT require the heal/pickup capture R.combat does.
--- Unlock the PROGRESSION gates on the hero-select screen.
--
-- Every oIGameUnlockConditionData subclass answers "may the player use this?"
-- through vftable slot 14, `bool IsUnlocked(this)`. The hero picker calls it
-- per condition when it draws a portrait, so forcing the progression-flavoured
-- ones to true makes progression-locked heroes selectable without touching the
-- save — Profile_*.ob is checksummed and Steam Cloud would fight an edit
-- anyway, so a runtime hook is the durable answer.
--
-- WHAT THIS DELIBERATELY DOES NOT TOUCH
-- oe::AdditionalContentGameUnlockConditionData::vftable[14] is the same slot on
-- the same base, and its body is `return *(int*)(this+0x28) == 3` — the
-- OWNERSHIP check. Forcing that would hand out content the player has not
-- bought, so it has no symbol in data/symbols.json and cannot be reached from
-- here. A hero gated on ownership stays locked; only progression, rank, story
-- and challenge gates open.
--
-- Returns the number of gates opened (0 if the symbols are unavailable on this
-- build, which fails closed rather than guessing at an address).
local PROGRESSION_GATES = {
    "HeroProgressionUnlock_IsUnlocked",
    "HeroRankLock_IsUnlocked",
    "HeroStoryUnlock_IsUnlocked",
    "ChallengeUnlock_IsUnlocked",
}
local _gates_hooked = false

function R.hero.unlock_progression()
    if _gates_hooked then return 0 end
    if not (R.hook and I.resolve) then return 0 end
    _gates_hooked = true
    local n = 0
    for _, name in ipairs(PROGRESSION_GATES) do
        local va = I.resolve(name)
        -- nil/0 when the symbol is unverified for this build: fail closed
        -- rather than hooking a stale address.
        if va and va ~= 0 then
            -- bool(this): one pointer arg, integer return. Returning 1 short
            -- circuits the gate; returning nil would replay the original.
            local ok, slot, why = pcall(R.hook, va, "up", function() return 1 end)
            if ok and (slot ~= nil or why == "already-hooked") then n = n + 1 end
        end
    end
    R.log(("[rsmm.hero] progression gates opened: %d/%d "
           .. "(ownership gates untouched)"):format(n, #PROGRESSION_GATES))
    return n
end

--- Let two players in a lobby pick the SAME hero.
--
-- `HeroSelect_IsHeroAvailable` decides whether a hero index may be picked. It
-- enumerates the lobby with `LobbyMembers_List` and reads each member's blob
-- through `LobbyAttributes_Parse` — whose JSON carries `RequestedHero` (see
-- [[lobby-attribute-parser]]) — so "someone already took that hero" is
-- decided here. Both of its call sites read only the boolean return
-- (0x14026dcec maps true to status 0 / false to 2; 0x1403e8474 to a bool), so
-- short-circuiting it to true cannot leave a caller holding a half-computed
-- result.
--
-- Returning 1 also SKIPS the original, which is what makes this safe rather
-- than merely convenient: `LobbyMembers_List` hands the caller members it
-- must destroy one by one, and never running it is the only way to not owe
-- that teardown.
--
-- ⚠ HOST-AUTHORITATIVE. Every player in the lobby needs this, or the ones
-- without it still refuse the duplicate pick on their own screen.
--
-- ⚠ The function is 1330 bytes and only its lobby half is understood. Forcing
-- true bypasses whatever ELSE it gates; an unlock check inside it is a live
-- possibility and is NOT ruled out. Treat a hero that becomes selectable but
-- was never unlocked as this hook, not as a bonus.
--
-- Returns true when the hook is in place (including when another mod already
-- installed it), false when the symbol is unresolved on this build — which
-- fails closed rather than guessing at an address.
local _dupes_hooked = false
local _confirm_hooked = false
local _reason_hooked = false
local _press_logged = false
local _unblock_armed, _unblock_said = false, 0
local _validate_widget = nil            -- the Validate Hero Button widget
local _widget_said = nil

-- Report the button's own live state once it changes.
--
-- The block byte is cleared and the control is asked for enabled=1, and the
-- press still does nothing — so the next question is about the WIDGET, not the
-- page. The book's input poll refuses to dispatch a press when the widget's
-- state is 4, and the driver vcalls a listener at *(widget+0x570); a null
-- listener is a button wired to nothing. Both are plain guarded reads of a
-- pointer the engine handed us, so this costs nothing and risks nothing.
local function _report_validate_widget()
    local w = _validate_widget
    if not w or not _ptr_plausible(w) then return end
    local state    = I.read_u32(w + 0x328)
    local state2   = I.read_u32(w + 0x32c)
    local listener = I.read_u64(w + 0x570)
    local flags    = I.read_u32(w + 0x234)
    local key = string.format("%s/%s/%s/%s", tostring(state), tostring(state2),
                              tostring(listener), tostring(flags))
    if key == _widget_said then return end
    _widget_said = key
    R.log(string.format(
        "[rsmm.hero] Validate Hero Button @%x: state=%s/%s listener=%s "
        .. "flags=%s (poll refuses a press while state==4; a null listener is "
        .. "a button wired to nothing)",
        w, tostring(state), tostring(state2),
        listener and string.format("0x%x", listener) or "nil", tostring(flags)))
end

-- Clear the byte that greys the book's Validate Hero Button.
--
-- BLUNT, and the honest description is: nothing found what WRITES this byte
-- (a scan of every access to +0x11a8 turned up a struct copy and an unrelated
-- dword store, and the global has 48 referencing functions), so this clears it
-- on a tick instead of intercepting a writer. That means the button is
-- ungreyed for every reason the page might grey it, not only a duplicate hero.
-- Acceptable for a mod the player opts into; it would not be acceptable as
-- default behaviour, and the symbol note says the same.
--
-- A plain byte write, never an engine call, so it does not need the main
-- thread ([[loader-thread-model]] governs CALLS). The page polls this byte
-- every frame, so a racy write is at worst one frame late.
local function _unblock_validate_tick()
    if not (I.module_base and I.read_u64 and I.read_u8 and I.write_u8) then return end
    local g = I.module_base() + VALIDATE_BLOCKED_RVA
    local obj = I.read_u64(g)
    if not obj or obj == 0 or not _ptr_plausible(obj) then return end
    local blocked = I.read_u8(obj + VALIDATE_BLOCKED_OFF)
    if blocked == nil then return end
    if blocked == 0 then _report_validate_widget() return end
    I.write_u8(obj + VALIDATE_BLOCKED_OFF, 0)
    _report_validate_widget()
    if _unblock_said < 3 then
        _unblock_said = _unblock_said + 1
        R.log("[rsmm.hero] cleared the Validate Hero Button block flag "
              .. "(was " .. tostring(blocked) .. ")")
    end
end

-- INSTRUMENT, not a fix: does a confirm press reach the function this whole
-- investigation has been treating as the click handler?
--
-- Three hooks read off that assumption — the availability check, the button's
-- widget setter, the block code — all install, all fire where predicted, and
-- the press still does nothing. That pattern says the model is wrong
-- somewhere, and no further static reading of the same call graph can say
-- where. A press is a rare event, so a handful of log lines settles it.
--
-- Replays the original untouched. It changes nothing; it only reports.
local function _watch_confirm_press()
    if _press_logged then return end
    if not (R.hook and I.resolve) then return end
    local va = I.resolve("HeroSelect_ConfirmPressed")
    if not va or va == 0 then return end
    local n = 0
    local ok, slot, why = pcall(R.hook, va, "ip", function()
        if n < 8 then
            n = n + 1
            R.log(("[rsmm.hero] confirm press handler reached (#%d) — the "
                   .. "button IS invoking it"):format(n))
        end
        return nil   -- replay: this is an instrument, it must not change flow
    end)
    if ok and (slot ~= nil or why == "already-hooked") then _press_logged = true end
end

-- Force the hero-select CONFIRM refusal code to "go ahead".
--
-- This is the gate, and the two hooks that came before it are not. The click
-- handler does `call HeroSelect_ConfirmBlockReason; test eax,eax; jne ->bail`,
-- so a non-zero return is a button press that visibly does nothing — which is
-- exactly what was measured after the first two hooks were in:
--
--   0  go ahead
--   1  a type check on the screen state failed, BEFORE anything was asked
--   2  HeroSelect_IsHeroAvailable said the hero is taken
--
-- Forcing the availability check only removes reason 2. Reason 1 returns
-- before the callee is ever consulted, so no amount of work on that callee can
-- reach it. Forcing the CODE covers both.
--
-- Its other two callers are the draw paths that decide the padlock, so this
-- also keeps the button's appearance and its behaviour telling the same story.
local function _force_confirm_allowed()
    if _reason_hooked then return end
    if not (R.hook and I.resolve) then return end
    local va = I.resolve("HeroSelect_ConfirmBlockReason")
    if not va or va == 0 then
        R.log("[rsmm.hero] HeroSelect_ConfirmBlockReason unresolved — confirm "
              .. "stays gated by the game")
        return
    end
    local ok, slot, why = pcall(R.hook, va, "ip", function() return 0 end)
    if ok and (slot ~= nil or why == "already-hooked") then
        _reason_hooked = true
    else
        R.log("[rsmm.hero] confirm-reason hook failed: "
              .. tostring(ok and why or slot))
    end
end

-- Keep the hero-select CONFIRM control enabled.
--
-- Forcing HeroSelect_IsHeroAvailable to true is NOT enough, which is a
-- measured fact rather than a guess: with that hook installed and firing (it
-- logs the hero it is asked about) the button stays locked. The picker takes
-- a second route.
--
-- HeroSelect_SetConfirmEnabled is that route, and it is the screen's ONLY
-- widget-enable call. Its argument is computed three instructions before the
-- call from a single boolean, which also writes the '*' glyph the player sees
-- as a padlock — so the lock icon and the dead button are one decision.
--
-- The hook does the least it can: when the screen asks for DISABLED it skips
-- the original, so the control keeps the enabled state it already had; when
-- the screen asks for enabled it replays the original untouched. Nothing is
-- called on the engine's behalf and no widget pointer is dereferenced from
-- Lua, which is what keeps this off the "handed a probed pointer to the
-- engine" path that every in-game crash so far has been.
--
-- ⚠ Blunt on purpose. The control stays enabled for EVERY reason the screen
-- might disable it, not only a duplicate hero. Fine for a mod the player opts
-- into; it would not be fine as default behaviour.
local function _force_confirm_enabled()
    if _confirm_hooked then return end
    if not (R.hook and I.resolve) then return end
    local va = I.resolve("HeroSelect_SetConfirmEnabled")
    if not va or va == 0 then
        R.log("[rsmm.hero] HeroSelect_SetConfirmEnabled unresolved — the "
              .. "confirm button is left as the game sets it")
        return
    end
    local logged = {}
    local ok, slot, why = pcall(R.hook, va, "vpi", function(screen, enabled)
        -- `enabled` IS A BOOL IN DL, not an int in EDX. A caller that does
        -- `mov dl, 1` leaves the upper 24 bits as whatever was in the register,
        -- so the raw slot came through as -1607667455 in a real session while
        -- meaning "true". Comparing the whole word made the disable-suppression
        -- fire only on the one caller that happened to `xor edx, edx` first.
        enabled = enabled & 0xff
        -- Remember the widgets so their live state can be read: +0x230 is the
        -- lock overlay, +0x238 the button itself.
        if I.read_u64 and _ptr_plausible(screen) then
            _validate_widget = I.read_u64(screen + 0x238)
        end
        local key = tostring(enabled)
        if not logged[key] then
            logged[key] = true
            R.log(("[rsmm.hero] hero-select confirm control asked for "
                   .. "enabled=%s"):format(key))
        end
        -- Non-nil skips the original; nil replays it. Only the DISABLE is
        -- suppressed.
        if enabled == 0 then return 0 end
        return nil
    end)
    if ok and (slot ~= nil or why == "already-hooked") then
        _confirm_hooked = true
    else
        R.log("[rsmm.hero] confirm-button hook failed: "
              .. tostring(ok and why or slot))
    end
end

function R.hero.allow_duplicates()
    if _dupes_hooked then return true end
    if not (R.hook and I.resolve) then return false end
    local va = I.resolve("HeroSelect_IsHeroAvailable")
    -- nil/0 when the symbol is unresolved for this build: fail closed rather
    -- than hooking a stale address.
    if not va or va == 0 then
        R.log("[rsmm.hero] HeroSelect_IsHeroAvailable unresolved for this "
              .. "game build — duplicate heroes not enabled")
        return false
    end
    -- "i" + "pii": bool(menu, hero_index, flag). Three args, as called —
    -- rcx = menu, edx = hero index, r8b = a bool. Declaring a fourth would
    -- read garbage out of r9.
    -- Log each DISTINCT hero index the gate is asked about, once, up to a cap.
    --
    -- "The hook installed" and "the picker actually asks this function about
    -- the hero you are trying to take" are different claims, and only the
    -- second one explains a refusal. A first-fire-only line cannot separate
    -- them: the picker asks about the LOCAL hero while merely drawing the
    -- screen, so it fires immediately and proves nothing about confirm.
    --
    -- Bounded by construction — one line per index, and the index space is the
    -- roster — so this cannot become a per-frame firehose the way an unbounded
    -- hot-path log would.
    local seen, n = {}, 0
    local ok, slot, why = pcall(R.hook, va, "ipii", function(_, hero_index)
        local key = tostring(hero_index)
        if not seen[key] and n < 24 then
            seen[key], n = true, n + 1
            R.log(("[rsmm.hero] availability gate asked about hero %s -> "
                   .. "forcing available"):format(key))
        end
        return 1
    end)
    if not (ok and (slot ~= nil or why == "already-hooked")) then
        R.log("[rsmm.hero] duplicate-hero hook failed: "
              .. tostring(ok and why or slot))
        return false
    end
    _dupes_hooked = true
    -- Ask the lobby parser to report every member as "has not picked yet".
    -- This is the one that does not depend on knowing WHICH check refuses.
    --
    -- Through the SHARED SLOT, because the state that owns the parse detour
    -- is almost never this one. A plain Lua flag here reaches nobody.
    if I.shared_set then pcall(I.shared_set, DUPE_BLANK_SLOT, 1) end
    if R.lobby then R.lobby.blank_hero = true end
    _force_confirm_allowed()
    _force_confirm_enabled()
    _watch_confirm_press()
    if not _unblock_armed then
        _unblock_armed = true
        R.on("tick", _unblock_validate_tick)
    end
    R.log("[rsmm.hero] duplicate heroes enabled (every player in the lobby "
          .. "needs this mod)")
    return true
end

function R.hero.handle() return _give_hero end
function R.hero.ready()  return _give_hero ~= nil end

-- Substrings marking events that EVERY hero fires (movement, items, UI, charge
-- counters, ...). These carry no identity, so they're excluded from a hero's
-- signature set, leaving only ability-distinctive events.
local _GENERIC_EVENT_PATTERNS = {
    "ABILITY_MAX", "ABILITY_EXIT", "COUNTER", "OPTIMIZE", "MODIFIER", "LIFE_BAR",
    "SHOW", "HIDE", "TILE", "INTERACT", "NETWORK", "REFUGEE", "MASTER", "TAB",
    "BORDER", "DREAM", "REROLL", "ENERGY", "COMBO", "COLLECT", "IMPACT",
    "STAGGER", "KILL", "DEAD", "DEATH", "PROJECTILE", "SPAWN", "BARK", "RESET",
    "CLEAR", "LEGENDARY", "GIVE_MAG", "POSITION", "PRIMARY_", "SECONDARY_",
    "DEFENSIVE_", "ULTIMATE_", "DASH_", "HEALTH", "TELEPORT", "MAP", "GAME_",
    "CHEST", "FOUNTAIN", "INGREDIENT", "TRAIT_CHARGE", "AMMO", "TRIGGER",
    "DUPLICATE", "OBJECT", "REWARD", "WISH", "XP_LEVEL", "ACTIVITY", "BHV",
    "BUTTON", "MENU", "CHRONO", "GENERATE", "FEEDBACK", "GLOBE",
}
local function _is_generic(gp)
    for _, pat in ipairs(_GENERIC_EVENT_PATTERNS) do
        if gp:find(pat, 1, true) then return true end
    end
    return false
end

-- name -> { signature event names }. A hero matches when ALL its signature
-- events have been seen this session. Seed from R.hero.catalog() output (play
-- each hero, read the distinctive list, paste the hero-exclusive ones here).
-- Empty entries are placeholders to be filled; an unmatched hero yields nil.
local _HERO_SIGNATURES = {
    -- Seeded from in-game catalogs. Each entry = events the hero fires that no
    -- other hero does; a hero matches when ALL its signature events are seen.
    -- SHATTER = Snow Queen's freeze->shatter payoff (her core ice mechanic).
    -- Excluded as non-exclusive: START_DAYMARE/START_NIGHTMARE (global day/night
    -- cycle), SUMMON_DEAD_ENTITIES/TEARING_SLASHES (talent/object effects).
    SnowQueen = { "SHATTER" },
    -- Piper   = { ... },  -- play Piper, read R.hero.catalog(), seed here
    -- Scarlet = { ... },
}

-- Gameplay events seen (with fire counts) for the CURRENT hero session. Reset
-- when the live hero dispatcher changes (switch character / new run). We record
-- ALL events here; _is_generic only labels them in the catalog so the
-- hero-distinctive ones are easy to spot for seeding signatures.
local _hero_events = {}
local _sig_last_hero = nil
R.on("*", function(ev, name)
    if type(name) ~= "string" then return end
    local gp = name:match("^gameplay:(.+)$")
    if not gp then return end
    if _give_hero ~= _sig_last_hero then
        _hero_events = {}
        _sig_last_hero = _give_hero
    end
    _hero_events[gp] = (_hero_events[gp] or 0) + 1
end)

-- Short hero name (e.g. "Piper") inferred from the events seen this session, or
-- nil if no signature has matched yet (early in a run, or hero not yet mapped).
function R.hero.name()
    for who, sig in pairs(_HERO_SIGNATURES) do
        local all = true
        for _, evname in ipairs(sig) do
            if not _hero_events[evname] then all = false; break end
        end
        if all and #sig > 0 then return who end
    end
    return nil
end

-- True if event `gp` is fired by all heroes (no identity value). Used only to
-- LABEL catalog output; collection records everything.
local function _generic(gp) return _is_generic(gp) end

-- True if the current hero is `who` (case-insensitive short name).
function R.hero.is(who)
    local n = R.hero.name()
    return n ~= nil and who ~= nil and n:lower() == tostring(who):lower()
end

-- Dump the distinctive (non-generic) events seen for the current hero this
-- session — the raw material for seeding _HERO_SIGNATURES. Play one hero, fire
-- its abilities, then call this; the hero-exclusive lines become its signature.
function R.hero.catalog()
    local names = {}
    for k in pairs(_hero_events) do names[#names + 1] = k end
    table.sort(names)
    R.log(string.format("[rsmm.hero] catalog: %d event(s) this session (hero=%s) "
        .. "— '*' = hero-distinctive candidate, '.' = generic",
        #names, tostring(R.hero.name())))
    for _, k in ipairs(names) do
        R.log(string.format("[rsmm.hero]   %s %s (x%d)",
            _generic(k) and "." or "*", k, _hero_events[k]))
    end
end

-- Subscribe to a hero ability event by bare NAME, only firing while a hero is
-- active this run. cb(ev) gets the gameplay payload. Thin sugar over R.on that
-- documents intent ("this is a hero ability hook") and skips menu-time noise.
function R.hero.on(name, cb)
    assert(type(name) == "string", "R.hero.on: name must be string")
    assert(type(cb) == "function", "R.hero.on: cb must be function")
    return R.on("gameplay:" .. name, function(ev)
        if _give_hero ~= nil then cb(ev) end
    end)
end

-- netcode (advanced / experimental) -------------------------------------
--
-- Replication-authority observation, for host-migration research. The
-- per-entity replication setup (Netcode_EntityReplSetup) decides master vs
-- client; the role lives behind the net manager. Offsets are SDK-internal — a
-- mod only sees (netmgr, role) and may return a number to overwrite role
-- (DANGEROUS: a live netcode write, can crash). See docs/_re/MULTIPLAYER.md.
--
--   R.net.on_repl_setup(function(netmgr, role, ctx)
--       R.log("role", role)        -- 1 = client/non-master
--       -- return 0 to force the master path (Phase 2; can crash)
--   end)

R.net = {}

local NET_CTX_TO_NETMGR_OFF = 0x10         -- netmgr = *(ctx + 0x10)
local NET_ROLE_OFF          = 0xf8         -- role   = *(netmgr + 0xf8); 1=client

-- Hook the per-entity replication setup. cb(netmgr, role, ctx) fires for each
-- entity; return a number from cb to OVERWRITE role (dangerous), or nil to
-- leave it. Returns the hook handle, or nil if Netcode_EntityReplSetup is
-- unresolved for this game build (pattern DB fail-closed — never hook stale).
function R.net.on_repl_setup(cb)
    assert(type(cb) == "function", "R.net.on_repl_setup: cb must be function")
    local va = I.resolve and I.resolve("Netcode_EntityReplSetup")
    if not va then
        R.log("[rsmm.net] Netcode_EntityReplSetup unresolved for this game "
            .. "build — on_repl_setup unavailable")
        return nil
    end
    return R.hook(va, "vp", function(ctx)
        if not ctx or ctx == 0 then return nil end
        local netmgr = I.read_u64(ctx + NET_CTX_TO_NETMGR_OFF)
        if not netmgr or netmgr == 0 then return nil end
        local role = I.read_u32(netmgr + NET_ROLE_OFF)
        local newrole = cb(netmgr, role, ctx)
        if type(newrole) == "number" then
            I.write_u32(netmgr + NET_ROLE_OFF, newrole)
        end
        return nil
    end)
end

-- game options ----------------------------------------------------------
--
-- The engine keeps every persisted setting in one inline registry object
-- (g_GameOptions). Each option stores its current value at +0x28 of its
-- 0x30-byte slot; consumers read that field directly, so writing it from Lua
-- takes effect without any save/reload. This exposes the debug/cheat toggles
-- the retail build ships but never surfaces in the UI, plus normal settings.
--
--   R.options.set("Forced seed", 12345)      -- reproducible run gen
--   R.options.set("Show enemy debug info", true)
--   R.options.get("Force epilogue")          -- -> false
--   for name in R.options.list() do ... end
--
-- NOTE: a few pure-debug toggles may be additionally gated by g_bEnableDebug
-- (a runtime cvar we can't resolve), so writing them can be a no-op in retail.
-- The non-debug options (Forced seed, screen shake, damage numbers, ...) are
-- unconditional. Test per option.

R.options = {}

-- Re-derived 2026-07-10 after the 2026-07-09 game patch (ctor is now
-- FUN_1401ca130, found via the "Forced seed" string xref; it stores the
-- singleton to this slot as its first write).
local OPT_GAMEOPTIONS_VA = 0x14143cb58
local OPT_IMG_BASE = 0x140000000
local OPT_VALUE_OFF = 0x28

-- name -> { off = byte offset of the option's slot from the object base,
--           type = "bool" | "uint" | "int" | "float" }
-- Offsets transcribed from the options ctor (FUN_1401ca130, 2026-07-09 build);
-- value at off+0x28. The patch added "Delay before can unpause" / "Max pause
-- per player", which moved "Pause during choices" (0x10f8 -> 0x10f0); every
-- other slot is unchanged.
local _OPT = {
    ["Forced seed"]                                 = { off = 0x0000, type = "uint"  },
    -- "Dev" is the build-type flag the ctor seeds from a baked constant; the
    -- engine honours "Forced seed" only while it is true (this is what the
    -- old seeded-runs raw poke at +0x58 was flipping).
    ["Dev"]                                         = { off = 0x0030, type = "bool"  },
    ["Test"]                                        = { off = 0x0060, type = "bool"  },
    ["Dash at cursor"]                              = { off = 0x0e80, type = "bool"  },
    ["Screen shake"]                                = { off = 0x1090, type = "bool"  },
    ["Pause during choices"]                        = { off = 0x10f0, type = "bool"  },
    ["Show damage and healing numbers"]             = { off = 0x11b0, type = "bool"  },
    ["Select random skin when using random heroes"] = { off = 0x11e0, type = "bool"  },
    ["Show enemy debug info"]                       = { off = 0x1210, type = "bool"  },
    ["Sectorize enemy camps"]                       = { off = 0x1240, type = "bool"  },
    ["Display fake unlock in recap"]                = { off = 0x1270, type = "bool"  },
    ["Show social options debug"]                   = { off = 0x12a0, type = "bool"  },
    ["Show hourglass debug info"]                   = { off = 0x12d0, type = "bool"  },
    ["Force epilogue"]                              = { off = 0x1300, type = "bool"  },
    ["Force end credits"]                           = { off = 0x1330, type = "bool"  },
}

-- Accept the GameOptions singleton pointer only if a couple of known bool slots
-- read as real booleans (0/1). A wrong-but-mapped pointer will almost always
-- fail this, turning a mis-derived va into a safe no-op instead of a stray write
-- into unrelated engine memory. Reads are fault-safe (nil on a bad address),
-- and `nil ~= 0 and nil ~= 1` is true, so an unmapped obj also fails closed.
local function _options_obj_valid(obj)
    local dev  = I.read_u8(obj + 0x0030 + OPT_VALUE_OFF)   -- "Dev"
    if dev ~= 0 and dev ~= 1 then return false end
    local test = I.read_u8(obj + 0x0060 + OPT_VALUE_OFF)   -- "Test"
    if test ~= 0 and test ~= 1 then return false end
    return true
end

local _opt_bad_warned = false
local function _opt_value_addr(name)
    local o = _OPT[name]
    if not o then return nil, nil end
    if not _va_ok("R.options") then return nil, nil end
    local base = I.module_base()
    if not base or base == 0 then return nil, nil end
    local obj = I.read_u64(base + (OPT_GAMEOPTIONS_VA - OPT_IMG_BASE))
    if not _ptr_plausible(obj) or not _options_obj_valid(obj) then
        if not _opt_bad_warned then
            _opt_bad_warned = true
            R.log("[rsmm.options] g_GameOptions pointer failed validation — "
                .. "refusing reads/writes this run (regenerate the symbol map)")
        end
        return nil, nil
    end
    return obj + o.off + OPT_VALUE_OFF, o.type
end

-- Read an option's current value. Returns bool/number, or nil if the name is
-- unknown or the registry isn't initialised yet.
function R.options.get(name)
    local addr, ty = _opt_value_addr(name)
    if not addr then return nil end
    if ty == "bool"  then return I.read_u8(addr) ~= 0 end
    if ty == "float" then return I.read_f32(addr) end
    return I.read_u32(addr)
end

-- Write an option's current value. Bools accept true/false; numeric options
-- accept a number. Returns true on success, false if unknown/unavailable.
function R.options.set(name, value)
    local addr, ty = _opt_value_addr(name)
    if not addr then
        R.log("[rsmm.options] unknown option or registry not ready:", name)
        return false
    end
    -- Type-check before writing: `value + 0.0` on a nil/string raised out of
    -- the setter (aborting the caller) instead of reporting a refused write,
    -- and math.floor(nil) did the same for the integer path.
    if ty == "bool" then
        I.write_u8(addr, value and 1 or 0)
    elseif type(value) ~= "number" then
        R.log("[rsmm.options] '" .. tostring(name) .. "' needs a number, got "
              .. type(value))
        return false
    elseif ty == "float" then
        I.write_f32(addr, value + 0.0)
    else
        I.write_u32(addr, math.floor(value))
    end
    return true
end

-- Iterator over every known option name.
function R.options.list()
    local names = {}
    for k in pairs(_OPT) do names[#names + 1] = k end
    table.sort(names)
    local i = 0
    return function()
        i = i + 1
        return names[i]
    end
end

-- hooks (low-level escape valve; users should prefer R.* abstractions) -

R.hook   = native.hook
R.unhook = native.unhook

-- Hero-capture is armed lazily on first R.entity / R.combat use (see
-- R.entity.hero) — NOT eagerly here. Arming touches R.hook, which can fail on
-- handler-address drift; doing it at module load would abort require"rsmm" for
-- EVERY mod, not just ones using combat. Lazy + pcall-guarded keeps it contained.

-- key-value store -------------------------------------------------------
--
-- Per-mod persistent state. Scalar values (string/number/boolean) are saved
-- to <mod_dir>/.rsmm_state and reloaded next launch, so counters and flags
-- survive game restarts. Loaded lazily on first access; flushed automatically
-- on the "exit" event, and on demand via R.kv.save(). Non-scalar values
-- (tables/functions) are kept in memory but skipped when saving.

R.kv = {}

local _kv
local _kv_dirty = false

-- line format, one entry per line: "<s|n|b>\t<key>\t<value>"; key and string
-- values are escaped so embedded TAB/newline/backslash round-trip safely.
local function _esc(s)
    return (s:gsub("[\\\n\t]", { ["\\"] = "\\\\", ["\n"] = "\\n", ["\t"] = "\\t" }))
end

local function _unesc(s)
    return (s:gsub("\\(.)", { ["\\"] = "\\", n = "\n", t = "\t" }))
end

local function _serialize(tbl)
    local out = {}
    for k, v in pairs(tbl) do
        local t = type(v)
        if t == "string" then
            out[#out + 1] = "s\t" .. _esc(k) .. "\t" .. _esc(v)
        elseif t == "number" then
            out[#out + 1] = "n\t" .. _esc(k) .. "\t" .. tostring(v)
        elseif t == "boolean" then
            out[#out + 1] = "b\t" .. _esc(k) .. "\t" .. (v and "1" or "0")
        end  -- tables/functions: in-memory only, not persisted
    end
    return table.concat(out, "\n")
end

local function _deserialize(str)
    local tbl = {}
    for line in (str .. "\n"):gmatch("(.-)\n") do
        local t, k, v = line:match("^(%a)\t(.-)\t(.*)$")
        if t then
            k = _unesc(k)
            if t == "s" then
                tbl[k] = _unesc(v)
            elseif t == "n" then
                tbl[k] = tonumber(v)
            elseif t == "b" then
                tbl[k] = (v == "1")
            end
        end
    end
    return tbl
end

local _exit_hooked = false
local function _kv_load()
    if _kv ~= nil then return end
    local ok, raw = pcall(function() return I.state_read() end)
    _kv = (ok and type(raw) == "string") and _deserialize(raw) or {}
    if not _exit_hooked then
        _exit_hooked = true
        native.on_event("exit", function() R.kv.save() end)
    end
end

-- Flush the store to disk now. Returns true on success (or if nothing
-- changed since the last save). Pass force=true to write regardless.
function R.kv.save(force)
    if _kv == nil then return true end
    if not _kv_dirty and not force then return true end
    local ok, wrote = pcall(function() return I.state_write(_serialize(_kv)) end)
    if ok and wrote then _kv_dirty = false end
    return ok and wrote or false
end

function R.kv.get(k, default)
    _kv_load()
    local v = _kv[k]
    if v == nil then return default end
    return v
end

function R.kv.set(k, v)
    _kv_load()
    _kv[k] = v
    _kv_dirty = true
end

function R.kv.inc(k, by)
    _kv_load()
    _kv[k] = (_kv[k] or 0) + (by or 1)
    _kv_dirty = true
    return _kv[k]
end

function R.kv.all()
    _kv_load()
    local out = {}
    for k, v in pairs(_kv) do out[k] = v end
    return out
end

-- player identity -------------------------------------------------------
--
-- The LOCAL player's real display name, straight from Steam
-- (steam_api64.dll's flat API, resolved by the loader). No netcode RE and no
-- game structures involved, so it survives game patches.
--
--     R.player.name()            --> "Ovilli"   (nil if Steam is unavailable)
--     R.player.name_of(steamid)  --> a known account's name, or nil
--
-- REMOTE players are not covered yet. The game resolves their names from the
-- party member's user-data JSON (steam.personaName / gamertag / Nickname /
-- pseudo) in FUN_140929940, and stores the result in the party-slot UI model,
-- but nothing yet links a slot to the hero entity a damage row is keyed by.
-- That link can only be pinned in a live co-op session; until then a mod
-- should label unknown players by join order and let the player rename them.

R.player = {}

--- The local player's display name (cached; nil when Steam is not present).
function R.player.name()
    if R.player._name ~= nil then
        return R.player._name or nil          -- false = looked up, unavailable
    end
    if type(I.steam_name) ~= "function" then
        R.player._name = false
        return nil
    end
    local ok, name = pcall(I.steam_name)
    R.player._name = (ok and type(name) == "string" and name ~= "" and name) or false
    return R.player._name or nil
end

--- Another account's display name by SteamID64. Steam only knows accounts it
--- has seen (a friend, a lobby member), so this is nil more often than not.
function R.player.name_of(steamid)
    if type(I.steam_name) ~= "function" or type(steamid) ~= "number" then return nil end
    local ok, name = pcall(I.steam_name, steamid)
    if ok and type(name) == "string" and name ~= "" then return name end
    return nil
end

-- overlay ---------------------------------------------------------------
--
-- Publish a table of rows for the desktop app to draw as an on-top HUD.
--
-- The SHAPE of the overlay (title, columns, sorting) is declared by the mod's
-- manifest `[overlay]` block; this is only the live DATA. The split is
-- deliberate and matches the rest of the project: a mod ships data, and the
-- client owns the pixels. A mod cannot hand HTML or script to the desktop
-- app's webview — that webview can spawn the CLI, so mod-supplied code there
-- would be arbitrary code execution on the player's machine, and every
-- overlay would look like whatever its author felt like that day.
--
--     R.overlay.publish{
--         rows = { { label = "You", dealt = 4821, share = 0.57 } },
--         meta = { total = 8410 },
--     }
--     R.overlay.clear()
--
-- Rows are written to this mod's own kv state, which the CLI reads back
-- (`rsmm overlay`). Publish at whatever cadence suits the mod — a write is a
-- few hundred bytes through a temp-file rename, and an unchanged payload is
-- skipped entirely.

R.overlay = {}

do

local OV = { last = nil }

-- Minimal JSON encoder: rows are flat records of string/number/boolean, which
-- is the entire contract. Anything else (a table value, a function) is dropped
-- rather than guessed at, so a mod cannot smuggle a nested structure the
-- reader has no column type for.
local function esc(s)
    return (s:gsub('[%c"\\]', function(c)
        if c == '"' then return '\\"' end
        if c == '\\' then return '\\\\' end
        if c == '\n' then return '\\n' end
        if c == '\t' then return '\\t' end
        if c == '\r' then return '\\r' end
        return string.format('\\u%04x', string.byte(c))
    end))
end

local function scalar(v)
    local t = type(v)
    if t == "string" then return '"' .. esc(v) .. '"' end
    if t == "boolean" then return v and "true" or "false" end
    if t == "number" then
        -- NaN/inf are not JSON. A meter that divides by zero once should not
        -- poison the whole payload.
        if v ~= v or v == math.huge or v == -math.huge then return "0" end
        if v == math.floor(v) and math.abs(v) < 1e15 then return string.format("%d", v) end
        return string.format("%.4f", v)
    end
    return nil
end

local function object(tbl)
    local keys = {}
    for k, v in pairs(tbl) do
        if type(k) == "string" and scalar(v) then keys[#keys + 1] = k end
    end
    -- Sorted so an unchanged payload serialises byte-identically and the
    -- "did anything change?" check below actually works.
    table.sort(keys)
    local parts = {}
    for _, k in ipairs(keys) do
        parts[#parts + 1] = '"' .. esc(k) .. '":' .. scalar(tbl[k])
    end
    return "{" .. table.concat(parts, ",") .. "}"
end

function OV.encode_rows(rows)
    local parts = {}
    for _, row in ipairs(rows or {}) do
        if type(row) == "table" then parts[#parts + 1] = object(row) end
    end
    return "[" .. table.concat(parts, ",") .. "]"
end

--- Replace the overlay's contents.
---   spec.rows  array of flat records (string/number/boolean values)
---   spec.meta  optional flat record shown in the footer
--- Returns true when something was written (false = unchanged, nothing to do).
function R.overlay.publish(spec)
    assert(type(spec) == "table", "R.overlay.publish: expects a table")
    local rows = OV.encode_rows(spec.rows)
    local meta = object(type(spec.meta) == "table" and spec.meta or {})
    local payload = rows .. meta
    if payload == OV.last then return false end
    OV.last = payload
    R.kv.set("overlay.rows", rows)
    R.kv.set("overlay.meta", meta)
    R.kv.set("overlay.updated", os.time())
    R.kv.save()
    return true
end

--- Empty the overlay (e.g. at a run boundary) without tearing it down.
function R.overlay.clear()
    return R.overlay.publish{ rows = {}, meta = {} }
end

--- The payload last written, for debugging.
function R.overlay.last() return OV.last end

end

-- item registry ---------------------------------------------------------
--
-- R.item.register{ id=, name=, description=, rarity=, base= }
--   * `base` clones the bytes of an existing MO entity (e.g.
--     "Common/Armor_Per_Object") as a starting template.
--   * `name` and `description` populate the corresponding text-bank
--     keys via Text/Magical_Objects~GAM.xls.LocalText.gen overrides.
--
-- Custom LOGIC for an item is attached separately with R.item.behavior (below),
-- so a mod's item does whatever the mod's Lua says — not just a cloned game
-- effect. The two compose: register the carrier, then bind behavior to its GUID.

R.item = {}

local _registered_items = {}

function R.item.register(spec)
    assert(type(spec) == "table",       "R.item.register: spec must be table")
    assert(type(spec.id) == "string",   "R.item.register: spec.id required")
    if _registered_items[spec.id] then
        R.log("[rsmm.item] duplicate id, ignoring:", spec.id)
        return false
    end
    _registered_items[spec.id] = spec

    local entity_path = spec.entity_path
        or ("EntitySettings/Objects/Magical_Objects/"
            .. (spec.rarity or "Common") .. "/"
            .. spec.id .. ".entity.ot.EntitySettingsResource")

    local ok = I.register_item(
        spec.id,
        spec.name or "",
        spec.description or "",
        spec.base or "",
        entity_path,
        -- arg 6 is the NUMERIC rarity index; spec.rarity doubles as the path
        -- tier name (a string like "Common"), so only forward it when numeric.
        type(spec.rarity) == "number" and spec.rarity or 0
    )
    if ok then
        R.log("[rsmm.item] registered and wired:", spec.id)
        return true
    else
        R.log("[rsmm.item] native rejected duplicate:", spec.id)
        return false
    end
end

function R.item.list()
    local out = {}
    for _, s in pairs(_registered_items) do out[#out+1] = s end
    return out
end

-- R.item.guid(id) -> lo, hi  (or nil until the item's def loads into the pool).
-- Resolves a registered custom item's runtime identity GUID so the SAME mod can
-- bind R.item.behavior to its OWN item without precomputing the cook-derived
-- GUID. nil until the magical-object pool has the definition, so callers poll
-- (e.g. R.item.on_guid below, or retry on a tick).
function R.item.guid(id)
    assert(type(id) == "string", "R.item.guid: id must be a string")
    if not (I and I.item_guid) then return nil end
    return I.item_guid(id)
end

-- R.item.on_guid(id, cb) — poll until R.item.guid(id) resolves, then cb(lo, hi)
-- once. The clean way to wire behaviour to a freshly-registered custom item:
--   R.item.register{ id = "MyTalent", ... }
--   R.item.on_guid("MyTalent", function(lo, hi)
--       R.item.behavior{ guid = { lo, hi }, on_tick = ... }
--   end)
function R.item.on_guid(id, cb, opts)
    assert(type(cb) == "function", "R.item.on_guid: cb must be a function")
    opts = opts or {}
    local every = opts.every or 1.0
    local tries, limit = 0, opts.tries or 120
    if not (R.schedule and R.schedule.every) then
        R.log("[rsmm.item] on_guid needs the tick pump (R.schedule)")
        return nil
    end
    local handle
    handle = R.schedule.every(every, function()
        local lo, hi = R.item.guid(id)
        if lo then
            R.schedule.cancel(handle)
            cb(lo, hi)
            return
        end
        tries = tries + 1
        if tries >= limit then
            R.schedule.cancel(handle)
            R.log("[rsmm.item] on_guid timed out for", id)
        end
    end)
    return handle   -- pass to R.schedule.cancel to stop polling early
end

-- Bind custom logic to ownership of a magical object — the core of a
-- mod-defined item that runs the mod's OWN behaviour, not a cloned game effect.
-- The item is identified by its definition identity GUID (lo, hi); pair this
-- with a carrier created by R.item.register / the item SDK kind.
--
--   R.item.behavior{
--       guid = { lo, hi },          -- or guid_lo=, guid_hi=
--       every = 1.0,                -- on_tick cadence in seconds (default 1)
--       on_acquire = function(c) R.log("got it") end,
--       on_tick    = function(c) R.combat.heal(4) end,   -- while owned
--       on_lose    = function(c) end,
--   }
--
-- The callbacks receive ctx = { lo, hi } and may use R.combat / R.entity /
-- R.give freely — that is where the mod's logic lives. Ownership is polled from
-- R.give.owned() on the tick pump (R.schedule), so it needs the hero to have
-- acted once (R.give.ready()). EXPERIMENTAL: owned-set semantics confirmed in
-- game per the runtime pool array.
function R.item.behavior(spec)
    assert(type(spec) == "table", "R.item.behavior: spec must be table")
    local lo, hi = spec.guid_lo, spec.guid_hi
    if type(spec.guid) == "table" then lo, hi = spec.guid[1], spec.guid[2] end
    assert(type(lo) == "number" and type(hi) == "number",
        "R.item.behavior: needs guid {lo,hi} (or guid_lo/guid_hi)")
    local every = spec.every or 1.0
    local owned = false
    local function ctx() return { lo = lo, hi = hi } end

    if not (R.schedule and R.schedule.every) then
        R.log("[rsmm.item] behavior needs the tick pump (R.schedule) — unavailable")
        return false
    end
    -- Returns the timer handle: pass it to R.schedule.cancel to unbind the
    -- behavior. (It used to re-arm itself through `after`, which meant there
    -- was no way to stop it short of a game restart.)
    return R.schedule.every(every, function()
        local now = R.give.owns(lo, hi)
        if now and not owned then
            owned = true
            if spec.on_acquire then spec.on_acquire(ctx()) end
        elseif (not now) and owned then
            owned = false
            if spec.on_lose then spec.on_lose(ctx()) end
        end
        if now and spec.on_tick then spec.on_tick(ctx()) end
    end)
end

-- NOT-YET-IMPLEMENTED stubs ---------------------------------------------
--
-- R.scaling and R.talent have a fixed API shape but NO game-side effect yet
-- (gated on RE of the value-modifier-computer and the skill-grant path). They
-- record the request and warn once so a mod author isn't misled into thinking
-- an override took. `R.scaling.pending()` / `R.talent.pending()` expose what
-- was requested, for when the wiring lands.

local _warned = {}
local function _warn_unimpl(api)
    if _warned[api] then return end
    _warned[api] = true
    R.log("[rsmm." .. api .. "] NOT IMPLEMENTED yet — calls are recorded but "
        .. "have no in-game effect. Track: docs/_re/HOOKPOINTS.md")
end

-- scaling: R.scaling.set("enemy_damage", function(act) return ({1,1.5,2})[act] end)
R.scaling = {}
local _scaling = {}

function R.scaling.set(field, fn)
    assert(type(field) == "string",   "R.scaling.set: field must be string")
    assert(type(fn)    == "function", "R.scaling.set: fn must be function")
    _scaling[field] = fn
    _warn_unimpl("scaling")
end

function R.scaling.get(field) return _scaling[field] end
function R.scaling.pending() return _scaling end

-- talent: R.talent.allow_stack(true) / R.talent.extra_at_level(11)
R.talent = {}
local _talent_cfg = { allow_stack = false, extra_at = {} }

function R.talent.allow_stack(b)
    _talent_cfg.allow_stack = b and true or false
    _warn_unimpl("talent")
end

function R.talent.extra_at_level(lvl)
    table.insert(_talent_cfg.extra_at, lvl)
    _warn_unimpl("talent")
end

function R.talent.pending() return _talent_cfg end

-- PICKABLE talents: react to the player choosing a level-up / reward card.
-- The gameplay bus fires "gameplay:POWER_UP_COLLECT_REQUEST" when a card is
-- picked; the loader attaches ev.card (the picked card's identity GUID, the
-- "0xlo:0xhi" payload slot the GIVE-event template fixes at +0x50/+0x58) plus a
-- confirm window ev.p38..ev.p58. `card` selects WHICH pick fires the callback:
--   nil / "*"        -> any card pick
--   function(ev)     -> custom predicate (inspect ev.card / ev.p38..ev.p58)
--   string id        -> match ev.card (a "0xlo:0xhi" GUID read from the probe;
--                       see docs/_re/kinds/talents-pick.md)
local function _pick_matches(card, ev)
    if card == nil or card == "*" then return true end
    if type(card) == "function" then
        local ok, keep = pcall(card, ev)
        return ok and keep and true or false
    end
    return ev ~= nil and tostring(ev.card) == tostring(card)
end

-- R.talent.on_pick(card, cb) — run cb(ev) when a matching card is picked.
-- POWER_UP_COLLECT_REQUEST fires on the game's main thread, so cb may call
-- R.combat / R.give / R.entity directly. cb is pcall-guarded.
-- IMPORTANT: this event fires for EVERY power-up collect — level-up CARDS and
-- world orbs/globes alike. Pass a specific `card` GUID to target one talent
-- card; nil/"*" fires on ANY power-up (use a `function(ev)` predicate if you
-- need finer discrimination than the identity).
function R.talent.on_pick(card, cb)
    if type(card) == "function" and cb == nil then card, cb = nil, card end
    assert(type(cb) == "function", "R.talent.on_pick: cb must be a function")
    R.on("gameplay:POWER_UP_COLLECT_REQUEST", function(ev)
        if not _pick_matches(card, ev) then return end
        local ok, err = pcall(cb, ev)
        if not ok then
            R.log("[rsmm.talent] on_pick callback error: " .. tostring(err))
        end
    end)
    return true
end

-- Define a CUSTOM TALENT: bind your own effect to a gameplay trigger. This is
-- the tier-2 "build your own talent" entry point — the `effect` callback is the
-- mod's own logic (heal, grant, buff, count, ...), not a cloned game talent.
--
--   R.talent.define{
--       id     = "lifesteal_on_ability",
--       hero   = "Juliet",                     -- optional: scope to ONE hero
--       on     = "gameplay:ABILITY_EXIT",      -- a gameplay event, or a list
--       when   = function(ev) return true end, -- optional predicate
--       effect = function(ev) R.combat.heal(5) end,
--   }
--
-- HERO-SPECIFIC: most talents belong to one hero. Set `hero="<ShortName>"` and
-- the effect fires only when that hero is active (gated through R.hero.is). This
-- depends on the hero's signature being seeded in R.hero; the signature-free way
-- to be hero-specific is a `pickable` talent bound to a hero-exclusive skill-card
-- GUID (only that hero's herodef has it). See R.talent.for_hero below.
--
-- Threading is handled for you: gameplay-event handlers run on the game's MAIN
-- thread, so an effect there may call R.combat / R.give / R.entity directly;
-- if you trigger off a non-gameplay event (e.g. "tick", background thread) the
-- effect is deferred onto the main-thread pump so engine calls stay safe (see
-- [[loader-thread-model]]). Each effect is pcall-guarded — a buggy talent logs
-- and is skipped, it never breaks the event bus for other mods.
--
-- PICKABLE talent (the effect arms only after the player chooses its card in
-- the level-up book, instead of being an always-on passive):
--
--   R.talent.define{
--       id       = "vampiric_casting",
--       pickable = true,                  -- dormant until picked
--       card     = "0x1a92...:0x0",       -- card GUID from TalentPickProbe; omit
--                                         -- (or "*") to arm on ANY card pick
--       on       = "gameplay:ABILITY_EXIT",
--       effect   = function() R.combat.heal(5) end,
--   }
--
-- `pickable = "<card>"` is shorthand for `pickable = true, card = "<card>"`.
-- Arming resets per run (run_start). Omit `pickable` for the always-on form.
local _talents = {}
function R.talent.define(spec)
    assert(type(spec) == "table",            "R.talent.define: spec must be table")
    assert(type(spec.id) == "string",        "R.talent.define: spec.id required")
    assert(type(spec.effect) == "function",  "R.talent.define: spec.effect must be function")
    if _talents[spec.id] then
        R.log("[rsmm.talent] duplicate id, ignoring:", spec.id)
        return false
    end
    local events = spec.on or "gameplay:ABILITY_EXIT"
    if type(events) == "string" then events = { events } end
    assert(type(events) == "table", "R.talent.define: spec.on must be a string or list of strings")
    _talents[spec.id] = spec

    -- `pickable = "<card>"` is shorthand for `pickable = true, card = "<card>"`.
    if type(spec.pickable) == "string" then
        if spec.card == nil then spec.card = spec.pickable end
        spec.pickable = true
    end

    -- Pickable talents stay DORMANT until the player picks their card; `card`
    -- selects which pick arms it (see R.talent.on_pick). A picked talent is
    -- permanent for the whole RUN (all chapters/islands), so arming resets only
    -- on "run_start" — NOT on GAME_START / GAME_CHRONO_START, which re-fire per
    -- chapter and would silently disarm the talent mid-run.
    if spec.pickable then
        spec._armed = false
        R.talent.on_pick(spec.card, function()
            -- Hero-scoped pickable: only arm when the matching hero is active.
            -- (Mostly redundant when `card` is a hero-exclusive skill GUID — that
            -- GUID exists in one herodef — but matters for card=nil/"*".)
            if spec.hero and not R.hero.is(spec.hero) then return end
            if not spec._armed then
                spec._armed = true
                R.log("[rsmm.talent] '" .. spec.id .. "' armed (card picked)")
            end
        end)
        R.on("run_start", function() spec._armed = false end)
    end

    for _, ev_name in ipairs(events) do
        R.on(ev_name, function(ev)
            -- HERO-SPECIFIC gate: most talents belong to one hero. `hero=` fires
            -- the effect only when that hero is active (via R.hero.is, which
            -- infers the hero from its exclusive ability events). NOTE: needs the
            -- hero's signature seeded in R.hero (_HERO_SIGNATURES) — if it isn't,
            -- prefer a pickable talent bound to a hero-exclusive card GUID, which
            -- is hero-specific without any signature. See skills-system.md.
            if spec.hero and not R.hero.is(spec.hero) then return end
            if spec.pickable and not spec._armed then return end
            if spec.when then
                local okc, keep = pcall(spec.when, ev)
                if not okc or not keep then return end
            end
            local function run()
                local ok, err = pcall(spec.effect, ev)
                if not ok then
                    R.log("[rsmm.talent] '" .. spec.id .. "' effect error: " .. tostring(err))
                end
            end
            -- gameplay events already fire on the main thread; anything else is
            -- deferred there so engine-mutating effects don't race the engine.
            if ev_name:sub(1, 9) == "gameplay:" then
                run()
            elseif R.schedule and R.schedule.next_main then
                R.schedule.next_main(run)
            else
                run()
            end
        end)
    end
    R.log("[rsmm.talent] defined:", spec.id)
    return true
end

function R.talent.list()
    local out = {}
    for _, s in pairs(_talents) do out[#out + 1] = s end
    return out
end

-- True once a pickable talent's card has been picked this run (nil if no such
-- talent, false if defined-but-not-yet-picked). Non-pickable talents read true.
function R.talent.armed(id)
    local s = _talents[id]
    if not s then return nil end
    if not s.pickable then return true end
    return s._armed and true or false
end

-- Scoped builder for a hero's talent file: stamps hero="<name>" onto every
-- talent so hero-specific talent code reads cleanly and can't leak to other
-- heroes. Per-talent `hero` still wins if set explicitly.
--   local J = R.talent.for_hero("Juliet")
--   J{ id = "bleed_on_dash", on = "gameplay:ABILITY_EXIT", effect = ... }
function R.talent.for_hero(hero)
    assert(type(hero) == "string", "R.talent.for_hero: hero must be a string")
    return function(spec)
        if type(spec) == "table" and spec.hero == nil then spec.hero = hero end
        return R.talent.define(spec)
    end
end

-- counters --------------------------------------------------------------
--
-- The simplest demo of the SDK: bump a counter every time an event
-- fires. Backed by R.kv, so counts persist across game restarts.
--
-- R.counter.on("run_end")  -- registers a "<event>_count" KV bump

R.counter = {}

function R.counter.on(event)
    R.on(event, function()
        local key = event .. "_count"
        R.kv.inc(key)
        R.log("[rsmm.counter]", key, "=", R.kv.get(key))
    end)
end

-- modular submodules ----------------------------------------------------
--
-- The remaining namespaces live in their own files under rsmm/ (installed
-- alongside this entrypoint) and are merged onto R here, so a mod gets them
-- via the single `require "rsmm"`:
--   R.health   — crash history + per-mod boot canary checkpoints
--   R.config   — typed per-mod config (get/set/on_change/all)
--   R.i18n     — translation lookup with {var} interpolation
--   R.api      — inter-mod API registry (expose/require with semver)
--   R.schedule — next_frame / after(seconds) timers (driven on "tick")
-- Each degrades gracefully if its backing native binding is absent.

local function _submodule(name)
    local ok, m = pcall(require, "rsmm." .. name)
    if ok and type(m) == "table" then return m end
    R.log("[rsmm] submodule rsmm." .. name .. " unavailable: " .. tostring(m))
    return nil
end

R.health   = _submodule("health")
R.config   = _submodule("config")
R.i18n     = _submodule("i18n")
R.api      = _submodule("api")
R.schedule = _submodule("schedule")

-- Drive the schedule module's frame pump off the one true event bus.
if R.schedule and R.schedule._tick then
    R.on("tick", function() R.schedule._tick() end)
end

-- Drive the MAIN-thread schedule pump off the gameplay bus. Those handlers run
-- inside the NamedEvent_Dispatch detour = the game's main thread, unlike "tick"
-- (loader background thread). Gating on ev.source == "gameplay" is essential:
-- the wildcard also fires for "tick"/"ready" on the background thread, and
-- running engine-mutating callbacks there is exactly the race we're avoiding.
if R.schedule and R.schedule._main_tick then
    R.on("*", function(ev)
        if ev and ev.source == "gameplay" then R.schedule._main_tick() end
    end)
end

-- R.mods — mod list + host-side lifecycle intents (in-game mod menu) -----
--
-- The game runs under Proton while the rsmm CLI lives on the host, so the
-- loader cannot enable/disable/uninstall a mod itself. Instead an intent is
-- queued to <cooking>/.rsmm_intents.jsonl (next to .rsmm_state.json) and the
-- HOST consumes it: `rsmm intents apply` (or the desktop app) performs the
-- operation and re-runs apply. Ops take effect on the next apply+restart.

R.mods = {}

-- Installed mods as {id, name, version, author, enabled} rows.
function R.mods.list()
    if not I.list_mods then return {} end
    return I.list_mods()
end

local _INTENT_OPS = { enable = true, disable = true, uninstall = true }

-- Queue a lifecycle intent for the host CLI. Returns true when queued.
function R.mods.request(op, mod_id)
    if not I.intent_write then
        R.log("[mods] intent_write unavailable (loader too old)")
        return false
    end
    if not _INTENT_OPS[op] then
        R.log("[mods] bad intent op: " .. tostring(op))
        return false
    end
    if type(mod_id) ~= "string" or mod_id == "" then
        R.log("[mods] bad mod id: " .. tostring(mod_id))
        return false
    end
    return I.intent_write(op, mod_id) and true or false
end

-- struct introspection (RE aid) -----------------------------------------
--
-- Turns "probe a struct across many game launches" into one launch: dump a
-- pointer's fields to the log with each qword CLASSIFIED (image vftable /
-- global, plausible heap pointer, small int, float, ASCII), and scan a struct
-- for pointer fields that look like component-array holders. All reads are
-- page-guarded (bad address → nil, never a fault), so this is safe to point
-- at a half-captured or wrong pointer. Reads only — never mutates.
-- hook inventory ----------------------------------------------------------
--
-- "Is this capability actually live?" was, until now, a question you answered
-- by reading _log.txt and inferring. Installing a detour proves the pattern
-- matched, the address is a .pdata function entry and MinHook enabled it — it
-- does NOT prove the target is on a live code path. A routine that moved to a
-- different caller still resolves, still verifies, still installs, and never
-- runs; that reads as "the feature is broken" with nothing to say why.
--
-- So each armed hook counts its fires, and `installed but fires == 0 after a
-- run` is the signal `fn_verify` cannot give you.
R.hooks = {}

--- Every armed engine hook: { {tag=, what=, va=, fires=}, ... }
function R.hooks.status()
    if type(I.hook_report) ~= "function" then return {} end
    local ok, list = pcall(I.hook_report)
    return (ok and type(list) == "table") and list or {}
end

--- Hooks that armed but have never fired. The interesting half.
function R.hooks.silent()
    local out = {}
    for _, h in ipairs(R.hooks.status()) do
        if (h.fires or 0) == 0 then out[#out + 1] = h end
    end
    return out
end

--- Log the inventory, one line per hook plus a summary. Call it from a mod, or
--- after a run, to see what actually ran.
function R.hooks.dump()
    local list = R.hooks.status()
    if #list == 0 then
        R.log("[rsmm.hooks] no armed hooks reported (loader too old?)")
        return
    end
    local silent = 0
    for _, h in ipairs(list) do
        if (h.fires or 0) == 0 then silent = silent + 1 end
        R.log(string.format("[rsmm.hooks]   %-16s %-28s @0x%x  fires=%d%s",
            tostring(h.tag), tostring(h.what), h.va or 0, h.fires or 0,
            (h.fires or 0) == 0 and "   <-- never fired" or ""))
    end
    R.log(string.format("[rsmm.hooks] %d armed, %d never fired", #list, silent))
end

R.debug = {}

local function _classify(v)
    if not v or v == 0 then return "0" end
    if _in_image(v) then
        local base = I.module_base()
        return string.format("IMG +0x%x", v - base + ENTITY_IMG_BASE)
    end
    if _ptr_plausible(v) then
        -- does *(v) look like a vtable? then v is likely a live object.
        local vt = I.read_u64(v)
        if _in_image(vt) then
            return string.format("ptr->obj (vt IMG +0x%x)",
                vt - I.module_base() + ENTITY_IMG_BASE)
        end
        return "ptr"
    end
    if v < 0x10000000 then return "int " .. tostring(v) end
    return nil
end

-- Dump `len` bytes (default 0x200, capped 0x1000) of *ptr as classified
-- qwords. `label` tags the log lines.
function R.debug.dump(ptr, len, label)
    label = label or "dump"
    if not _ptr_plausible(ptr) then
        R.log(string.format("[rsmm.debug] %s: 0x%s not a plausible pointer",
            label, tostring(ptr))); return
    end
    len = math.min(len or 0x200, 0x1000)
    R.log(string.format("[rsmm.debug] %s @ 0x%x (%d bytes):", label, ptr, len))
    for off = 0, len - 8, 8 do
        local v = I.read_u64(ptr + off)
        if v ~= nil then
            local cls = _classify(v)
            local f = I.read_f32(ptr + off)
            local extra = ""
            if f and f == f and f ~= 0 and math.abs(f) > 1e-6 and math.abs(f) < 1e9 then
                extra = string.format("  f32=%.4g", f)
            end
            R.log(string.format("[rsmm.debug]   +0x%03x  0x%016x  %s%s",
                off, v, cls or "-", extra))
        end
    end
end

-- Scan every pointer field of `obj` (0..max_off) for objects that hold a
-- {data,count} pointer-vector at data_off/count_off (default the component
-- array 0x190/0x198). Returns a list of {off, holder, count}; logs each.
-- This is the generalized form of the XP-owner hunt — reuse it whenever a
-- captured pointer's real payload lives on some sub-object.
function R.debug.find_arrays(obj, opts)
    opts = opts or {}
    local data_off  = opts.data_off  or 0x190
    local count_off = opts.count_off or 0x198
    local max_off   = opts.max_off   or 0x800
    local found = {}
    if not _ptr_plausible(obj) then return found end
    for off = 0, max_off - 8, 8 do
        local P = I.read_u64(obj + off)
        if _vector_valid(P, data_off, count_off, {
            min = 1, max = opts.max_count or 0x100,
            check_entry = opts.check_entry,
        }) then
            local n = I.read_u32(P + count_off)
            found[#found + 1] = { off = off, holder = P, count = n }
            R.log(string.format(
                "[rsmm.debug] find_arrays: obj+0x%x -> 0x%x has %d-entry vector @+0x%x",
                off, P, n, data_off))
        end
    end
    if #found == 0 then
        R.log("[rsmm.debug] find_arrays: no matching vectors found")
    end
    return found
end

-- Find every offset in `obj` holding a given u32 — the read half of locating
-- an unmapped field.
--
-- The engine names things by string, but NUMBERS are how a def's scalar fields
-- are found: a tiledef whose cooked bytes say width=20 has a 20 somewhere in
-- the live object, and the cooked file tells you what to look for. Returns
-- { {off=, }, ... }; `opts.pairs_with` additionally requires the NEXT u32 to
-- equal that value, which is what separates a real {width,height} pair from
-- the dozens of stray 20s in a 0x400-byte object.
function R.debug.find_u32(obj, value, opts)
    opts = opts or {}
    local max_off = math.min(opts.max_off or 0x400, 0x4000)
    local found = {}
    if not _ptr_plausible(obj) then return found end
    for off = 0, max_off - 4, 4 do
        if I.read_u32(obj + off) == value then
            local ok = true
            if opts.pairs_with then
                ok = (I.read_u32(obj + off + 4) == opts.pairs_with)
            end
            if ok then
                found[#found + 1] = { off = off }
                if opts.log ~= false then
                    R.log(string.format("[rsmm.debug] find_u32: obj+0x%x = %d%s",
                        off, value, opts.pairs_with and
                        (string.format(" (next = %d)", opts.pairs_with)) or ""))
                end
            end
        end
    end
    return found
end

-- Temporarily set a u32 field, run `fn`, then put the original back.
--
-- The write half of field discovery, scoped so a wrong guess cannot outlive
-- the call. A mod cannot poke memory (rsmm lint refuses `write_*` / `poke` in
-- mod Lua, and rightly: an unscoped write to a mis-derived offset corrupts
-- engine state with no way back). This is the sanctioned form — the value is
-- restored before returning, on the error path too — and it exists so a
-- candidate offset can be CONFIRMED by an observable effect rather than
-- argued about.
--
-- Returns whatever `fn` returned, or nil plus a reason when the write is
-- refused. Engine-mutating: MAIN THREAD only.
function R.debug.with_u32(obj, off, value, fn)
    if not _ptr_plausible(obj) then return nil, "not a plausible pointer" end
    if type(off) ~= "number" or off < 0 or off > 0x4000 then
        return nil, "offset out of range"
    end
    if type(fn) ~= "function" then return nil, "fn must be a function" end
    local prev = I.read_u32(obj + off)
    if prev == nil then return nil, "field unreadable" end
    I.write_u32(obj + off, value)
    local ok, res = pcall(fn)
    I.write_u32(obj + off, prev)          -- restore, error path included
    if not ok then return nil, tostring(res) end
    return res
end

-- Harvest the readable C strings an object points at.
--
-- The engine names everything it loads by string path (see the POI reference
-- chain: mapdef -> tiledef -> prefab -> level -> prop entity are all string
-- refs, no GUIDs), so the fastest way to answer "WHICH object is this pointer"
-- is to look for a resource path hanging off it. This walks `obj`'s pointer
-- fields one level deep and reads each target as a NUL-terminated string.
--
-- Every read is page-guarded on the native side (`read_cstr` stops at the
-- first byte outside a readable page), so pointing this at a non-object is a
-- miss, not a fault. `min_len` and the printable filter are what keep binary
-- garbage out — a 2-char "string" off a float field is noise, not a name.
--
-- Returns { {off=, ptr=, text=}, ... } and logs each hit when `opts.log`.
function R.debug.strings(obj, opts)
    opts = opts or {}
    local max_off = opts.max_off or 0x400
    local min_len = opts.min_len or 4
    local out = {}
    if type(I.read_cstr) ~= "function" then
        R.log("[rsmm.debug] strings: this loader has no read_cstr binding")
        return out
    end
    if not _ptr_plausible(obj) then return out end
    for off = 0, max_off - 8, 8 do
        local p = I.read_u64(obj + off)
        if _ptr_plausible(p) then
            local s = I.read_cstr(p, opts.max_len or 160)
            -- Printable-ASCII only. A resource path is ASCII by construction,
            -- and anything with control bytes in it is a struct we misread as
            -- a string.
            if type(s) == "string" and #s >= min_len and not s:find("[^\32-\126]") then
                out[#out + 1] = { off = off, ptr = p, text = s }
                if opts.log ~= false then
                    R.log(string.format("[rsmm.debug] strings: +0x%03x -> %q", off, s))
                end
            end
        end
    end
    if #out == 0 and opts.log ~= false then
        R.log("[rsmm.debug] strings: none found")
    end
    return out
end

--- Every string laid out INLINE in a byte window, narrow and wide, by offset.
---
--- The complement to `R.debug.strings`, which follows POINTERS at 8-byte
--- offsets and so only ever finds heap-allocated strings. A short name lives
--- inline (MSVC keeps under 16 characters in the object itself), and a record
--- full of inline names is exactly what a player-slot table looks like.
---
--- Reports OFFSETS relative to `va`, because that is the reusable fact: once
--- you know a name sits at `+0x30` of a 0x90-byte record you can walk the
--- whole array, whereas a bare address is true only for this session.
---
---   opts.before / opts.after   window around `va` (default 0x40 / 0x100)
---   opts.min_len               characters (default 3)
---
--- Returns { { off = <signed>, text = "...", wide = <bool> }, ... }.
--- Wide runs are `printable, 0x00` pairs; the narrow pass cannot swallow one
--- because a UTF-16 run is single characters split by NULs, which never reach
--- min_len.
function R.debug.strings_at(va, opts)
    opts = opts or {}
    local before = opts.before or 0x40
    local after = opts.after or 0x100
    local min_len = opts.min_len or 3
    local out = {}
    if not _ptr_plausible(va) then return out end

    local function printable(b)
        return type(b) == "number" and b >= 32 and b < 127
    end

    local run, start = {}, nil
    local function flush()
        if start and #run >= min_len then
            out[#out + 1] = { off = start, text = table.concat(run), wide = false }
        end
        start, run = nil, {}
    end

    local i = -before
    while i < after do
        local b = I.read_u8(va + i)
        if printable(b) and I.read_u8(va + i + 1) == 0 then
            local w, j = {}, i
            while j < after do
                local c = I.read_u8(va + j)
                if not (printable(c) and I.read_u8(va + j + 1) == 0) then break end
                w[#w + 1] = string.char(c)
                j = j + 2
            end
            if #w >= min_len then
                flush()
                out[#out + 1] = { off = i, text = table.concat(w), wide = true }
                i = j
                goto continue
            end
        end
        if printable(b) then
            if not start then start, run = i, {} end
            run[#run + 1] = string.char(b)
        else
            flush()
        end
        i = i + 1
        ::continue::
    end
    flush()
    if opts.log then
        for _, s in ipairs(out) do
            R.log(string.format("[rsmm.debug] strings_at: %+d %s%q",
                s.off, s.wide and "w" or "", s.text))
        end
    end
    return out
end

--- Decode an MSVC `std::string` at `va`, or nil if it is not one.
---
--- Layout is 32 bytes: a 16-byte union (the characters themselves when they
--- fit) followed by size @+0x10 and capacity @+0x18. Capacity below 16 means
--- the text is INLINE; at or above, +0x0 is a pointer to the heap buffer.
--- Both forms are checked, so a key/value pair can be read as strings rather
--- than guessed at from a printable smear.
---
--- Validating `size <= cap` and a sane capacity is what makes this usable as a
--- PROBE: run it over arbitrary offsets and the ones that are not strings say
--- so instead of returning garbage.
function R.debug.stdstring_at(va)
    if not _ptr_plausible(va) then return nil end
    local size = I.read_u64(va + 0x10)
    local cap = I.read_u64(va + 0x18)
    if type(size) ~= "number" or type(cap) ~= "number" then return nil end
    if cap < 15 or cap > 0x10000 or size > cap or size == 0 then return nil end
    local text
    if cap == 15 then
        text = I.read_cstr and I.read_cstr(va, 16) or nil
    else
        local p = I.read_u64(va)
        if not _ptr_plausible(p) then return nil end
        text = I.read_cstr and I.read_cstr(p, math.min(size + 1, 256)) or nil
    end
    if type(text) ~= "string" or #text ~= size then return nil end
    if text:find("[^\32-\126]") then return nil end
    return text
end

-- netcode identity ---------------------------------------------------------
--
-- The engine's own per-entity network state, read with GUARDED reads only.
--
-- Why not just call Entity_GetNetId: it reaches Entity_GetNetComponent, which
-- walks the component map with no guard of its own, so an entity whose store
-- slot holds the -1 sentinel is an access violation rather than a nil return.
-- That is the 2026-08-15 crash (dump a97c76fe) and it is banned from the SDK.
--
-- It does not need to be called. The component map is a plain open-addressed
-- table and its shape is recorded (Entity_GetNetComponent, verified in Ghidra
-- 2026-08-20): control bytes @entity+0x5e8, slot array @entity+0x5f0, bucket
-- mask @entity+0x600, slots 0x10 bytes of { u32 class_id; u64 value }. Walking
-- that array with `I.read_*` gives the same answer and CANNOT fault: a bad page
-- reads nil. Slower than the engine's SIMD probe and completely safe, which is
-- the right trade for something a mod calls.

-- EXTEND, never re-create: R.net already exists (on_repl_setup, above). A bare
-- `R.net = {}` here silently deleted that function for every mod.
R.net = R.net or {}

-- Fields of R.net, not five `local`s: the module chunk is ONE Lua function and
-- Lua caps a function at 200 live locals. rsmm.lua already sits at that ceiling
-- -- five more here stopped the whole SDK compiling, which kills every mod.
R.net._k = {
    CLASS = 0x154fce5c,   -- oCEntityCpntNet, per Entity_GetNetComponent
    AUTH  = 0x130,        -- 0 = this machine owns the entity
    SLOTS = 0x5f0,        -- component slot array  { u32 class_id; u64 value }
    MASK  = 0x600,        -- bucket mask; capacity = mask + 1
    MAX   = 1024,         -- refuse an implausible capacity outright
    -- The owner chain, netcomp -> network object -> holder -> id. See
    -- R.net.owner for the two Ghidra sites this was read off.
    NETOBJ     = 0xb8,    -- netcomp -> oCSLNetworkObject
    OWNER_HOP  = 0x100,   -- netobj  -> owner holder
    OWNER_OFF  = 0x28,    -- holder  -> u64 identity
}

--- The entity's component of `class_id`, or nil. Never faults, never calls the
--- engine. Bounded by R.net._k.MAX so a corrupt mask cannot spin.
function R.net.component(entity, class_id)
    class_id = class_id or R.net._k.CLASS
    if not (I.read_u64 and I.read_u32) or not _ptr_plausible(entity) then return nil end
    local slots = I.read_u64(entity + R.net._k.SLOTS)
    local mask  = I.read_u64(entity + R.net._k.MASK)
    if not _ptr_plausible(slots) then return nil end
    if type(mask) ~= "number" or mask < 0 or mask >= R.net._k.MAX then return nil end
    for i = 0, mask do
        local slot = slots + i * 0x10
        if I.read_u32(slot) == class_id then
            local v = I.read_u64(slot + 8)
            if _ptr_plausible(v) then return v end
            return nil
        end
    end
    return nil
end

--- The OWNER identity of `entity` — the same 64-bit value the engine itself
--- stamps into every hit it resolves. nil when unavailable.
---
--- Ghidra 2026-08-24, from the two ends that matter:
---
---   Entity_ResolveAttackHits (FUN_1403dd540), per target:
---       netcomp = Entity_GetNetComponent(attacker_entity)
---       if netcomp and *(netcomp+0xb8) then
---           (*(netcomp+0xb8))->vft[0x18](obj, &out)     -- this chain
---       else fallback *(*(entity+0x30)+0x230)->vft[0x88](&out), else -1
---       hitdata+0x18 = out
---
---   oCSLNetworkObject::vft[0x18] (FUN_1408c0d40) is one line:
---       *out = *(*(obj+0x100) + 0x28)
---
--- So this is not a heuristic: it is the field the engine uses to answer "who
--- dealt this" for its own bookkeeping, read the same way. Two entities that
--- answer with the SAME id belong to the same owner — which is what makes a
--- transformed or cloned hero attributable to the player it came from, for
--- ALLIES as well as the local player (nothing else on this build does that;
--- the hero-id join is dead here and the name sweep answers by coincidence).
---
--- Guarded reads only, no engine call. `Entity_GetNetId` — the engine's own
--- accessor for this — is BANNED from the SDK: it walks the component map
--- unguarded and a hero whose store slot holds the -1 sentinel takes the
--- process down (2026-08-15, dump a97c76fe). R.net.component reimplements the
--- lookup as a bounded scan that returns nil instead of faulting.
function R.net.owner(entity)
    local c = R.net.component(entity)
    if not c or not I.read_u64 then return nil end
    local obj = I.read_u64(c + R.net._k.NETOBJ)
    if not _ptr_plausible(obj) then return nil end
    local inner = I.read_u64(obj + R.net._k.OWNER_HOP)
    if not _ptr_plausible(inner) then return nil end
    local id = I.read_u64(inner + R.net._k.OWNER_OFF)
    -- 0 and the -1 sentinel are the engine's own "no owner" answers (the
    -- fallback branch above returns -1 outright), never an identity.
    if type(id) ~= "number" or id == 0 or id == -1
       or id == 0xffffffffffffffff then return nil end
    return id
end

--- Does THIS machine own `entity`? true / false / nil when unknown.
---
--- The engine's own test, not a guess: NamedEvent_NetSend refuses to emit a
--- networked event when this byte is non-zero ("remotely owned, someone else
--- speaks for it"), and both damage hit paths gate their network emit on it.
--- Distinct from the hero controller's +0x1d88, which answers "is this the
--- player at this keyboard" for a HERO; this answers "does this client have
--- authority over this entity" for anything replicated.
function R.net.is_local(entity)
    local c = R.net.component(entity)
    if not c or not I.read_u8 then return nil end
    local b = I.read_u8(c + R.net._k.AUTH)
    if type(b) ~= "number" then return nil end
    return b == 0
end

--- The session id an incoming networked event was stamped with, or nil.
---
--- `NamedEvent_NetSend` writes the SENDER's session id (int64) to ev+0x38
--- before handing the event to NamedEvent_NetSendToPeer, so every replicated
--- event carries the identity of the machine that raised it. This is the only
--- engine-provided per-player key that reaches gameplay code, and it is what a
--- sound entity->player join has to be built on -- as opposed to searching the
--- heap for a name string, which is what the identity sweep did and why it
--- answered at a different offset every single time it "worked".
---
--- ⚠ NOT YET JOINED TO A NAME. The lobby member's key is a std::string session
--- id at member+0x00 (LobbyMembers_Local); whether that string is this int64's
--- text form is unproven, and proving it needs one co-op launch with
--- `R.net.diag(true)`. Until then this returns the raw id and nothing consumes
--- it -- an unproven join must not be allowed to label a row.
function R.net.event_session(ev)
    if not I.read_u64 or not _ptr_plausible(ev) then return nil end
    local id = I.read_u64(ev + 0x38)
    if type(id) ~= "number" or id == 0 or id == 0xffffffffffffffff then return nil end
    return id
end

-- lobby roster ------------------------------------------------------------
--
-- The session's players, by their real display names.
--
-- Ravenswatch identifies players through EPIC (the exe imports
-- EOSSDK-Win64-Shipping.dll and not steam_api64.dll) and imports no
-- `EOS_UserInfo_*` at all, so no name can come from the platform SDK. Steam
-- can name the LOCAL account and nothing else. Remote names instead arrive as
-- LOBBY ATTRIBUTES, and that is what this reads.
--
-- Layout, from session 364f (`0x62fceb40`, `0x6301bce0`): a flat table of
-- 32-byte entries, key at +0 and value at +0x10, both NUL-terminated inline:
--
--     -0x60  "RequestedHero"  -0x40 "RequestedSkin"  -0x20 "InLobby"
--     +0x00  "PlayerName"     +0x10 <the name>       +0x20 "LobbyState"
--     +0xa0  "m_sEosUserId"   +0x100 "m_ePlatform"
--
-- Located by searching for the `PlayerName` key, then REQUIRING
-- `RequestedHero` at -0x60. That neighbour check is what separates a real
-- lobby block from the copy of the literal that Lua interns for this very
-- search — every earlier session drowned in those.
-- Bytes a whole-address-space search may examine. Declared HERE, above its
-- first use: a Lua local is invisible to code written earlier in the file, and
-- R.lobby sits ahead of the damage section that also wants it.
local MEM_SCAN_MB = 4096
local LOBBY_KEY_STRIDE = 0x20
local LOBBY_VALUE_OFF = 0x10
local LOBBY_ANCHOR_OFF = -0x60          -- "RequestedHero" relative to PlayerName

R.lobby = {}
local _lobby_cache, _lobby_cache_at = nil, 0

--- Inline NUL-terminated string in a fixed-size slot, or nil.
local function _slot_string(va, cap)
    if not I.read_cstr then return nil end
    local s = I.read_cstr(va, cap or 16)
    if type(s) ~= "string" or s == "" then return nil end
    if s:find("[^\32-\126]") then return nil end
    return s
end

--- Read one lobby block, or nil if `va` no longer looks like one.
local function _lobby_read(va)
    if _slot_string(va + LOBBY_ANCHOR_OFF) ~= "RequestedHero" then return nil end
    if _slot_string(va) ~= "PlayerName" then return nil end
    local name = _slot_string(va + LOBBY_VALUE_OFF)
    if not name then return nil end
    return { name = name, addr = va,
             hero = _slot_string(va + LOBBY_ANCHOR_OFF + LOBBY_VALUE_OFF) }
end

-- hook-fed roster ---------------------------------------------------------
--
-- The scan below is a fallback, not the design. Every member's attributes
-- arrive through ONE engine function — `LobbyAttributes_Parse`, whose second
-- argument is a StringDesc { const char* ptr @+0x0; uint32 len|0x80000000
-- @+0x8 } holding the serialized blob — so a detour there sees every player's
-- name at the moment it lands, late joiners included, for the cost of a few
-- reads instead of a 2 GB sweep.
--
-- It also fixes something the sweep cannot: the 32-byte key/value blocks the
-- sweep searches for are that parse's TRANSIENT storage, not a persistent
-- roster. A 4-player session (2026-08-16) scanned back exactly two members,
-- because only two blobs had been parsed recently enough for their buffers to
-- still be intact. Reading the blob as it arrives has no such window.
-- One table, not five locals: the main chunk is at Lua's 200-local ceiling
-- and each new top-level `local` fails compilation of the whole SDK.
local LOBBY_HOOK = {
    BLOB_MAX   = 4096,
    -- Distinct attribute blobs remembered, so a re-parse of an UNCHANGED
    -- member costs one table lookup instead of the full decode + snapshot.
    -- Comfortably more than a lobby's worth of members x their attribute
    -- states; the whole set is dropped and rebuilt when it overflows, which
    -- costs one full-price parse per member and needs no LRU bookkeeping.
    RECENT_BLOBS = 64,
    recent     = {},
    recent_n   = 0,
    RECORD_MAX = 16,               -- plenty for a 4-player lobby, bounded anyway
    state      = 0,                -- 0 not tried, 1 live here, 2 unavailable
    by_name    = {},
    order      = {},
    records    = {},               -- member-record pointers seen by the detour
    fires      = 0,                -- times the detour has been entered
    logged     = 0,                -- roster size at the last log line
    logs       = 0,
    armed_at   = nil,              -- os.time() when the detour went in
    warned     = false,
    -- How long a member stays on the roster after the last time the engine
    -- parsed their attributes. The roster used to be APPEND-ONLY, so a session
    -- that backed out of matchmaking and searched again accumulated everyone it
    -- had ever seen: session 5a1d listed SIX members for a four-player run, two
    -- of whom (TJ, SiggR22) never entered it. The engine re-parses the members
    -- it still has whenever the lobby changes, so a leaver simply stops being
    -- refreshed — age is the signal.
    TTL        = 120,
    MAX_PLAYERS = 4,               -- the game's own party cap
    seq        = 0,                -- parse counter: recency without a clock
    pruned     = {},               -- names already reported as gone
}

--- One attribute's value out of a raw blob, or nil.
---
--- The blob's exact encoding is not pinned down (the writer side builds it
--- through a serializer, and Stormancer traffic is msgpack), so this accepts
--- the three shapes it can plausibly be rather than betting on one: JSON
--- (`"PlayerName":"Akaza"`), plain key/value (`PlayerName=Akaza`), and
--- length-or-type-prefixed binary, where the value is simply the printable run
--- that follows the key. Guessing wrong yields nil and the sweep still runs.
function LOBBY_HOOK.value(text, key)
    local i = text:find(key, 1, true)
    if not i then return nil end
    local rest = text:sub(i + #key, i + #key + 128)
    -- The bare form must stop at a separator. Matching "everything up to the
    -- next quote or brace" instead swallowed the rest of the blob:
    -- `PlayerName=Brig;RequestedHero=Scarlet` came back as the whole tail as
    -- one name, which then never matches the row it is supposed to label.
    local v = rest:match('^"?%s*[:=]%s*"([^"]+)"')
        or rest:match('^"?%s*[:=]%s*([^",}%];&|\n\r\t]+)')
        or rest:match('^[^\32-\126]([\32-\126]+)')
    if not v then return nil end
    v = v:gsub("%s+$", "")
    -- A value that is itself one of the other keys means the match ran off the
    -- end of this attribute into the next one.
    if v == "" or v == "RequestedHero" or v == "RequestedSkin"
        or v == "InLobby" or v == "LobbyState" or v == "PlayerName" then
        return nil
    end
    return v
end

--- Decode the engine's 16-byte compact string at `va`, or nil.
---
--- Not an MSVC `std::string` (see R.debug.stdstring_at for that one). The
--- parser's own key comparison spells the layout out: bit 0x1000 of the word
--- at +0xe means the text is INLINE, in which case the byte at +0xd holds the
--- REMAINING capacity, so the length is 0xd - that; otherwise the length is
--- the dword at +0x0 and the characters live behind the pointer at +0x8.
function LOBBY_HOOK.estring(va)
    if not _ptr_plausible(va) then return nil end
    local flags = I.read_u16 and I.read_u16(va + 0xe)
    if type(flags) ~= "number" then return nil end
    local text, len
    if (flags & 0x1000) ~= 0 then
        local rem = I.read_u8(va + 0xd)
        if type(rem) ~= "number" or rem > 0xd then return nil end
        len = 0xd - rem
        if len == 0 then return nil end
        text = I.read_cstr(va, len + 1)
    else
        len = I.read_u32(va)
        local p = I.read_u64(va + 8)
        if type(len) ~= "number" or len == 0 or len > 256 then return nil end
        if not _ptr_plausible(p) then return nil end
        text = I.read_cstr(p, len + 1)
    end
    if type(text) ~= "string" or #text ~= len then return nil end
    if text:find("[^\32-\126]") then return nil end
    return text
end

--- Read one lobby member RECORD, or nil if `va` does not look like one.
---
--- Layout recovered 2026-08-16 by pairing each attribute key literal in
--- LobbyAttributes_Parse with the store it feeds (param_1 is the record —
--- the prologue homes rcx to [rsp+8], which is the [rbp+0x100] the parser
--- reloads before every field write):
---
---     +0x00 PlayerName (compact string)   +0x10 RequestedHero (u32)
---     +0x14 RequestedSkin (u16)           +0x18 UnlockedGameDifficulty (u32)
---     +0x1c LobbyState (u32)              +0x20 UnlockedHeroFlag (u32)
---     +0xa8 m_sEosUserId (string)         +0xb8 m_sSteamUserId (u64)
---     +0xc0 m_uVoiceChatMode (u32)        +0xc4 InLobby (u8)
---     +0xc5 MemberDataInitialized (u8)    +0xc8 m_ePlatform (u32)
---
--- Reading the record is exact, where reading the blob has to guess at an
--- encoding — and it is the only source of `RequestedHero`, which is what a
--- caller needs to stop matching names to heroes by POSITION.
function LOBBY_HOOK.read(va)
    local name = LOBBY_HOOK.estring(va)
    if not name then return nil end
    local ready = I.read_u8(va + 0xc5)
    if ready == 0 then return nil end       -- MemberDataInitialized
    local hero = I.read_u32(va + 0x10)
    return {
        name     = name,
        hero_id  = (type(hero) == "number" and hero < 0x1000) and hero or nil,
        steam_id = I.read_u64(va + 0xb8),
        in_lobby = (I.read_u8(va + 0xc4) or 0) ~= 0,
        addr     = va,
        src      = "record",
    }
end

--- Record what one parsed blob says. Internal; exposed for the spec.
function R.lobby._note_blob(text)
    if type(text) ~= "string" then return nil end
    local name = LOBBY_HOOK.value(text, "PlayerName")
    if not name then return nil end
    -- RequestedHero is a NUMBER in the blob ("RequestedHero":4), and it is the
    -- exact key that ends positional name<->row matching. Confirmed live
    -- 2026-08-16; the member record carries the same value at +0x10, but the
    -- blob is available on every call whereas param_1 is not always a record.
    local hero = LOBBY_HOOK.value(text, "RequestedHero")
    local hero_id = tonumber(hero)
    -- -1 is "has not picked a hero yet", which every member reads as in the
    -- lobby before the run starts (session 5a1d: `Ovili(hero -1)`). Storing it
    -- makes -1 look like a hero id, and worse, a later blob would overwrite a
    -- REAL id with it when the player re-enters hero select.
    if hero_id and hero_id < 0 then hero, hero_id = nil, nil end
    -- The lobby says whether this member is still in it. A member the engine
    -- re-parses on the way OUT is removed immediately rather than aged out.
    local inlobby = LOBBY_HOOK.value(text, "InLobby")
    -- The player's NETWORK identity. A display name has no reason to be stored
    -- on a hero controller and four sessions of sweeping confirm it is not —
    -- but a peer id does, because that is what the netcode addresses players
    -- by. Same needle machinery, better needle.
    local eos = LOBBY_HOOK.value(text, "m_sEosUserId")
    if type(eos) ~= "string" or #eos < 8 or #eos > 64 then eos = nil end
    local e = LOBBY_HOOK.by_name[name]
    if e then
        e.hero = hero or e.hero
        e.hero_id = hero_id or e.hero_id
        e.eos = eos or e.eos
        e.seen = os.time()
        LOBBY_HOOK.seq = LOBBY_HOOK.seq + 1
        e.seq = LOBBY_HOOK.seq
        if inlobby ~= nil then e.in_lobby = (inlobby ~= "false") end
    else
        LOBBY_HOOK.seq = LOBBY_HOOK.seq + 1
        e = { name = name, hero = hero, hero_id = hero_id, eos = eos,
              in_lobby = (inlobby == nil) or (inlobby ~= "false"),
              seen = os.time(), seq = LOBBY_HOOK.seq, src = "hook" }
        LOBBY_HOOK.by_name[name] = e
        LOBBY_HOOK.order[#LOBBY_HOOK.order + 1] = e
        -- One line the FIRST time a name is seen, for as long as the session
        -- lasts. The full-blob dump above stops after three fires, which in
        -- every logged session so far was three parses of the LOCAL player
        -- inside the first 20 seconds -- so a remote member parsed two minutes
        -- later left no trace at all, and "the hook is working" and "the hook
        -- is working and nobody else's attributes ever arrive" read the same
        -- from outside. They are different problems with different fixes.
        R.log(("[rsmm.lobby] new member %q (hero %s) on parse #%d")
              :format(name, tostring(hero_id or hero or "?"), LOBBY_HOOK.fires))
    end
    -- Rejoining clears the "they left" latch, so a second departure is
    -- reported too.
    if LOBBY_HOOK.pruned[name] then
        LOBBY_HOOK.pruned[name] = nil
    end
    return e
end

-- Internals, for the spec: the record decoder is layout knowledge worth
-- testing directly rather than only through a live lobby.
R.lobby._hook = LOBBY_HOOK

-- ARM AT LOAD, not on demand.
--
-- The first version armed from R.lobby.refresh(), which the damage board only
-- calls once it has an unnamed row — i.e. after somebody has dealt damage.
-- Measured 2026-08-16: the detour went in at 17:20:30, but the members had
-- joined and had their attributes parsed minutes earlier, so every parse call
-- worth seeing was already gone and the board kept "Player 2/3/4" for the
-- whole run. A hook cannot catch an event that has already happened, so the
-- demand gate (right for a 2 GB sweep) is exactly wrong for a detour: install
-- it once, up front, and let it cost nothing until the game calls it.
--
-- Both lifecycle points, because arming is idempotent and neither is
-- guaranteed on its own: `setup` runs after every mod's init.lua, `ready` at
-- the first frame, and a mod loaded late still gets one of them.
function LOBBY_HOOK.blank_requested_hero(rec)
    if not (I.write_u32 and I.read_u8 and I.read_u32) then return end
    if not _ptr_plausible(rec) then return end
    -- NOT gated on MemberDataInitialized. LOBBY_HOOK.read gates on it, and
    -- copying that here made this a no-op for a whole playtest: every real
    -- blob carries `"MemberDataInitialized":false` while still carrying a
    -- perfectly good RequestedHero (measured: four members at heroes 4, 7, 3
    -- and 6, all parsed, none blanked). That byte means "the member's data is
    -- settled", not "this is a record".
    --
    -- What makes it a record is PlayerName reading back as a printable
    -- compact string at +0, plus a hero id in range. Those two are the shape
    -- test; the flag never was.
    if not LOBBY_HOOK.estring(rec) then return end
    local hero = I.read_u32(rec + 0x10)
    if hero == nil or hero == 0xffffffff or hero >= 0x1000 then return end
    I.write_u32(rec + 0x10, 0xffffffff)
    -- Counter on R.lobby, not on the private table: a test that cannot see
    -- the count cannot tell "the guard stopped the write" from "the write
    -- happened and wrote the same value back".
    R.lobby.blanked = (R.lobby.blanked or 0) + 1
    if R.lobby.blanked <= 6 then
        R.log(("[rsmm.lobby] duplicate-heroes: parsed member wanted hero "
               .. "%d, reported as -1 (not picked) so nothing reads it as "
               .. "taken"):format(hero))
    end
end

R.lobby.blank_requested_hero = LOBBY_HOOK.blank_requested_hero

R.on("setup", function() pcall(LOBBY_HOOK.arm) end)
R.on("ready", function() pcall(LOBBY_HOOK.arm) end)

--- Detour the attribute parser. Idempotent; safe to call from the pump.
function LOBBY_HOOK.arm()
    if LOBBY_HOOK.state ~= 0 then return end
    if not (R.hook and I.resolve and I.read_u64 and I.read_u32 and I.read_cstr) then
        LOBBY_HOOK.state = 2
        return
    end
    local va = I.resolve("LobbyAttributes_Parse")
    if not va or va == 0 then
        -- Fail closed onto the sweep rather than hooking a stale VA: a
        -- mid-function detour corrupts the function it lands in.
        LOBBY_HOOK.state = 2
        R.log("[rsmm.lobby] LobbyAttributes_Parse unresolved on this game "
            .. "build — falling back to the memory sweep for player names")
        return
    end
    -- void*(void* self, StringDesc* blob): pointer return, two pointer args.
    local function on_parse(self, blob)
        -- Runs on the GAME thread inside the detour: page-guarded reads and a
        -- table write only, never an engine call. Returning nil replays the
        -- original, so the parse itself is untouched.
        --
        -- param_1 is the member RECORD. Remember it: this call is filling it,
        -- so its fields are only complete once the original returns — which is
        -- why the record is read later (from the pump, through
        -- LOBBY_HOOK.read) rather than here. The blob below is the fallback
        -- for the first pass, when no record has been read back yet.
        if self and self ~= 0 then
            local seen = false
            for _, p in ipairs(LOBBY_HOOK.records) do
                if p == self then seen = true break end
            end
            if not seen then
                LOBBY_HOOK.records[#LOBBY_HOOK.records + 1] = self
                -- Bounded: the parse runs per attribute update, forever.
                while #LOBBY_HOOK.records > LOBBY_HOOK.RECORD_MAX do
                    table.remove(LOBBY_HOOK.records, 1)
                end
            end
        end
        LOBBY_HOOK.fires = LOBBY_HOOK.fires + 1
        if not blob or blob == 0 then return nil end
        -- param_2 is {begin, end}, NOT {ptr, len|0x80000000}: the body does
        -- `rbx=[rdx+8]; rdi=[rdx]; rdx=rbx-rdi` and builds the string from that
        -- RANGE. Reading +0x8 as a length yielded the low bits of the end
        -- POINTER — always larger than BLOB_MAX, so every blob was discarded as
        -- oversized and the fallback never saw a single one.
        local b, e = I.read_u64(blob), I.read_u64(blob + 8)
        if not b or b == 0 or not e or e < b then return nil end
        local len = e - b
        if len < 1 or len > LOBBY_HOOK.BLOB_MAX then return nil end
        local text = I.read_cstr(b, len + 1)
        -- First few fires, spell out what arrived. "Hooked" only proves the
        -- detour went in; a session where it never fires and one where it fires
        -- but decodes to nothing look identical from the outside, and telling
        -- them apart by guesswork costs a playtest each time.
        if LOBBY_HOOK.fires <= 3 then
            R.log(string.format(
                "[rsmm.lobby] parse #%d: record=0x%x blob=%d byte(s) %q",
                LOBBY_HOOK.fires, self or 0, len,
                -- The whole blob, not the first 120 bytes. Every needle the
                -- identity sweep has comes out of this payload, and session
                -- fb4f could not be diagnosed because the half that carries
                -- `m_sEosUserId` was the half being cut off.
                type(text) == "string" and text:sub(1, 512) or "<unreadable>"))
        end
        if type(text) == "string" then
            -- IDENTICAL BLOB = NOTHING CHANGED. Skip the whole body.
            --
            -- Session a34f parsed 92,062 times in three minutes -- ~500/s, on
            -- the GAME THREAD, because the engine re-serialises every member
            -- on every lobby poll whether or not anything moved. Each call was
            -- costing four string.find passes over a 376-byte blob plus a
            -- 0x100-byte member snapshot (32 guarded reads), so this detour
            -- alone was doing millions of reads a minute. That is the hard
            -- stutter, and it is on the thread that draws frames.
            --
            -- Bounded to RECENT_BLOBS entries and keyed by the text itself: if
            -- the bytes are the same, the member's attributes are the same by
            -- definition, so there is nothing for _note_blob to learn and
            -- nothing new to snapshot. A blob that actually changes misses the
            -- cache and takes the full path exactly as before.
            local recent = LOBBY_HOOK.recent
            if recent[text] then return nil end
            recent[text] = true
            LOBBY_HOOK.recent_n = LOBBY_HOOK.recent_n + 1
            if LOBBY_HOOK.recent_n > LOBBY_HOOK.RECENT_BLOBS then
                LOBBY_HOOK.recent, LOBBY_HOOK.recent_n = { [text] = true }, 1
            end
            local e = R.lobby._note_blob(text)
            -- THE MEMBER'S OWN SESSION ID, for the row->player join.
            --
            -- `blob` is the member's attribute field at member+0x28
            -- (LobbyMembers_List: the callers do
            -- `LobbyAttributes_Parse(&rec, *m + 0x28)`), so subtracting 0x28
            -- recovers the member object for free -- the note on that symbol
            -- says exactly this. member+0x00 is its std::string session id,
            -- which LobbyMembers_Local proves is the stable per-player key:
            -- the engine finds "everyone but me" by comparing it.
            --
            -- Stored as TEXT and never parsed into a number here. Whether this
            -- string is the decimal or hex form of the int64 the netcode
            -- stamps on an event (ev+0x38) is exactly the thing that has to be
            -- PROVEN at runtime rather than assumed -- see R.damage._session_join.
            if e and _ptr_plausible(blob) then
                local member = blob - 0x28
                if _ptr_plausible(member) then
                    if not e.session then
                        local sid = R.debug.stdstring_at(member)
                        if type(sid) == "string" and #sid > 0 then
                            e.session = sid
                            if LOBBY_HOOK.fires <= 6 then
                                R.log(("[rsmm.lobby] %q session id %q (member 0x%x)")
                                      :format(tostring(e.name), sid, member))
                            end
                        end
                    end
                    -- SNAPSHOT the member's pointers HERE, inside the detour.
                    --
                    -- Reading them later is reading freed memory: the callers
                    -- do `LobbyMembers_List(scene, &members)` and DESTROY each
                    -- member afterwards (the note on that symbol says so), so
                    -- the member address is dangling by the time the damage
                    -- tick runs. Session 9e4f is what that looks like -- 30
                    -- hits across four rows, every one naming the SAME player,
                    -- because only one stale window still read as pointers and
                    -- nothing was left to poison it.
                    --
                    -- Inside the detour the object is alive by construction.
                    -- The member ADDRESS itself is deliberately not a needle:
                    -- it is a temporary, so a later allocation reusing it
                    -- would match.
                    local ptrs, n, words = {}, 0, {}
                    -- F._netid.MEMWIN, not a local: the module chunk is one Lua
                    -- function and Lua caps it at 200 live locals, which this file
                    -- already sits on. One more stops the whole SDK compiling.
                    for off = 0, F._netid.MEMWIN - 8, 8 do
                        local v = I.read_u64(member + off)
                        if type(v) == "number" and v ~= 0 and v ~= -1 then
                            -- EVERY qword, not only the pointers. The netcode's
                            -- owner key is a RakNetGUID: oCSLNetReplica is a
                            -- RakNet::Replica3 (its ctor installs
                            -- RakNet::NetworkIDObject and RakNet::Replica3
                            -- vftables and initialises two 16-byte GUIDs at
                            -- +0x28 and +0x38), and +0x28 is
                            -- creatingSystemGUID -- the peer that CREATED the
                            -- replica, i.e. the player who owns the hero.
                            -- That is a plain 64-bit number, which a pointer
                            -- filter throws away. If the game records which
                            -- peer a lobby member is, this is what it records.
                            words[v] = true
                        end
                        if _ptr_plausible(v) and not ptrs[v] then
                            ptrs[v] = true; n = n + 1
                        end
                    end
                    if n > 0 then e.ptrs, e.nptrs = ptrs, n end
                    if next(words) then e.words = words end
                end
            end
            -- Pair the member OBJECT with the name this very call wrote into
            -- it. The pair is what makes the reverse link possible: a member
            -- object that points at a hero controller names that controller,
            -- and the objects outlive the lobby screen.
            -- ⚠⚠ NOTHING HERE IS A STABLE IDENTITY. RE of the call
            -- sites (2026-08-19) closed this door for good: the callers do
            --     LobbyMembers_List(scene, &members);
            --     for (m : members) LobbyAttributes_Parse(&stack_rec,
            --                                             *m + 0x28);
            --     for (m : members) { ...; destroy(m); }
            -- so param_1 is a stack local AND the members themselves are
            -- freshly allocated copies that are freed at the end of the same
            -- call. Session 5636 proved it from the other side: the same
            -- address arrived as "tyki07" and minutes later as "Ovili".
            -- Neither argument identifies a player beyond this instant, so the
            -- reverse "member object -> hero controller" link that lived here
            -- has been removed rather than tuned. What survives is what the
            -- blob SAYS: the name and the requested hero, which is what
            -- _note_blob keeps.
        end
    end

    -- The body runs under pcall, and the reason is not defensiveness for its
    -- own sake: the hook layer DISABLES a callback that raises 20 times in a
    -- row, and this callback is the ONLY path a remote player's name reaches
    -- this machine. Session 4c36 is what that costs -- a nil-index bug threw
    -- on all three of the local player's parses inside the first 20 seconds,
    -- the slot was switched off, and every ally who joined 90 seconds later
    -- was parsed by an engine nobody was listening to. Four players on the
    -- board, one name. A raise here must cost the fields that one parse would
    -- have set, never the hook.
    -- DUPLICATE HEROES, fixed at the source instead of at each consumer.
    --
    -- Four gates were hooked before this one — the availability check, the
    -- confirm control's widget setter, the block code, the presumed press
    -- handler. Every one installs, three of them demonstrably fire, and the
    -- button still refuses. Chasing consumers was the wrong shape of fix.
    --
    -- All of them read the same thing: what OTHER lobby members asked to play,
    -- and every member's attributes reach the game through this one parse.
    -- Writing -1 into the record's RequestedHero after the parse fills it
    -- means no consumer can find a match, whichever consumer it turns out to
    -- be. -1 is the value the engine itself uses for "has not picked yet"
    -- (see R.lobby._note_blob), so this is a state the game already handles
    -- rather than a value invented for it.
    --
    -- Guarded three ways before the write: the pointer must be plausible,
    -- MemberDataInitialized must be set, and PlayerName must read back as a
    -- real string — because param_1 is NOT always a record (the note on
    -- LOBBY_HOOK.read says so) and a blind write at +0x10 into something else
    -- is a corruption with no connection to its crash.

    local ok, slot, why = pcall(R.hook, va, "ppp", function(self, blob, next)
        -- Only this path replays the original ITSELF, because the record has
        -- to be full before it can be edited. Everything else returns nil and
        -- lets the loader replay, exactly as before.
        local rv, replayed = nil, false
        -- Read the shared slot, not a local: this callback belongs to
        -- whichever state armed the hook first, which is usually NOT the mod
        -- that asked for blanking.
        local want = R.lobby.blank_hero
        if not want and I.shared_get then
            local sok, v = pcall(I.shared_get, DUPE_BLANK_SLOT)
            want = sok and v == 1
        end
        if want and type(next) == "function" then
            rv = next()
            replayed = true
            pcall(LOBBY_HOOK.blank_requested_hero, self)
        end
        local pok, perr = pcall(on_parse, self, blob)
        if not pok and not LOBBY_HOOK.err_said then
            LOBBY_HOOK.err_said = true
            R.log("[rsmm.lobby] parse callback raised (names keep arriving on "
                .. "later parses): " .. tostring(perr))
        end
        if replayed then return rv end
        return nil
    end)
    -- "already-hooked": another mod's state owns the detour, so OUR callback
    -- never fires and this state keeps sweeping. Not an error, and not worth a
    -- log line — the owning state is collecting the same names.
    if ok and slot ~= nil then
        LOBBY_HOOK.state = 1
        LOBBY_HOOK.armed_at = os.time()
        R.log("[rsmm.lobby] attribute parser hooked — player names arrive "
            .. "without scanning memory")
    else
        LOBBY_HOOK.state = 2
        if not ok then
            R.log("[rsmm.lobby] could not hook the attribute parser ("
                .. tostring(slot or why) .. "); using the memory sweep")
        end
    end
end

--- Every lobby member's display name. NEVER SCANS — cache only.
---
--- Returns `{ { name = "Juice", hero = "...", addr = <va> }, ... }`, empty
--- until `R.lobby.refresh()` has run at least once (and empty forever in a
--- solo session, which has no lobby block).
---
--- The no-scan guarantee is the point. A whole-address-space search costs
--- ~4 SECONDS; this used to be called from the damage board's label path,
--- which runs on the MAIN THREAD inside a damage detour, so the first ally to
--- deal damage froze the game mid-fight and the 30 s cache expiry froze it
--- again on a timer. Reading is now a handful of guarded byte reads against
--- addresses found once, and finding those addresses is a separate, explicitly
--- background-only call.
--- Is this hook entry still part of the CURRENT lobby?
---
--- Age is measured against the NEWEST parse, never against the clock. The
--- engine re-parses the members it still has whenever the lobby changes, so
--- everyone present gets refreshed together and a leaver's timestamp simply
--- stops advancing. Measuring against `os.time()` instead would prune the
--- whole roster two minutes into a run, because a run in progress parses
--- nothing at all.
function LOBBY_HOOK.current(e, newest, rank)
    -- ⚠ `InLobby` is NOT membership. Session ea68 proved it: the flag goes
    -- FALSE for everyone the moment the run starts (it means "sitting in the
    -- lobby menu"), so treating it as "left" pruned all four real players —
    -- Ovili, BombsAway, Luxman, dickydackydoo, every one of them on the
    -- end-of-run scoreboard — and left only `jack`, a leftover from a lobby
    -- that had been abandoned minutes earlier. Elimination then pinned "jack"
    -- on BombsAway's 3.5k damage. Do not read this flag as presence.
    --
    -- What is left is recency, and a hard cap: Ravenswatch runs at most FOUR
    -- players, so the fifth-most-recently-parsed member cannot be in this run
    -- whatever their timestamp says. In ea68 that alone is decisive — the four
    -- real players were parsed 110s before the newest event, `jack` 132s.
    --
    -- The player at this keyboard is exempt from BOTH rules, not just the cap.
    -- Session 6136 dropped "Ovili" mid-run ("last parsed 123s before the
    -- newest member") because a run in progress re-parses the OTHER members
    -- (they are still moving through lobby state) and never re-parses us. The
    -- one member certain to be in the run is the one running the meter.
    if LOBBY_HOOK.is_local(e) then return true end
    if rank and rank > LOBBY_HOOK.MAX_PLAYERS then return false end
    -- ONCE THE RUN STARTS, THE CAP IS THE ONLY RULE. The recency TTL that used to sit here is gone, and
    -- the exemption above says why: mid-run the engine stops re-parsing lobby
    -- attributes, so "last parsed 121s before the newest member" is the normal
    -- state of a player who is present and playing. That was already known for
    -- the LOCAL member (session 6136 dropped "Ovili" mid-run and the exemption
    -- was added) -- the same is true of everyone else, which the exemption
    -- missed because the other members keep being re-parsed for as long as
    -- anybody is still moving through lobby state, and then stop.
    --
    -- Sessions bd68 and 3e36 are the cost. 3e36 evicted three of four players
    -- SIX times across one 86-minute run ("αβ²" twice, "Xiyufeiniao" three
    -- times, "on3pmBR" once), each re-added and evicted again, so the name
    -- pool oscillated the whole run. Guessed labels are drawn from that pool,
    -- so rows were re-drawn from whatever survived and the final board carried
    -- "on3pmBR" on TWO rows while Xiyufeiniao never appeared at all.
    --
    -- The case the TTL was written for is still covered: in session ea68 the
    -- leftover "jack" was the FIFTH most recently parsed member, so the party
    -- cap above rejects it on rank alone. A member who genuinely left and is
    -- inside the cap now lingers as an unused NAME, which costs a placeholder
    -- at worst -- against evicting a live player, which puts a real name on
    -- another player's damage.
    --
    -- `InLobby` is the discriminator, and this file already documents why it
    -- is trustworthy for THIS question even though it is useless as presence:
    -- it means "sitting in the lobby menu" and goes false for EVERYONE the
    -- moment the run starts. So while anyone still reads true the lobby is
    -- live, members are being re-parsed, and one that stopped really did leave
    -- (session 5a1d's abandoned lobby, where the prune is what stops a
    -- leftover name being handed to a row). Once they all read false there is
    -- no lobby left to leave, and a stale timestamp means nothing.
    if LOBBY_HOOK.in_run() then return true end
    if not newest or not e.seen then return true end
    return (newest - e.seen) <= LOBBY_HOOK.TTL
end

--- Has the run started? True when members exist and NONE is in the lobby menu.
---
--- Deliberately not a gameplay-bus signal: session a14f logged "no run signal
--- on this build (neither the analytics run boundary nor the gameplay bus has
--- fired)", so the one reliable statement about run state is the one the lobby
--- blobs carry themselves.
--- Read the FRESHEST parse, not every member. A leftover from an abandoned
--- lobby keeps whatever `InLobby` it was last parsed with -- true, forever,
--- because nothing re-parses it -- so asking "is everyone out of the menu"
--- lets one dead entry hold the answer at false for the whole session, which
--- is precisely the state this is meant to detect. The newest parse is the
--- only one describing the lobby as it is now.
function LOBBY_HOOK.in_run()
    local best
    for _, e in pairs(LOBBY_HOOK.by_name) do
        if not best or (e.seq or 0) > (best.seq or 0) then best = e end
    end
    return best ~= nil and not best.in_lobby
end

--- Is this entry the player at this keyboard? Steam knows our own name, and
--- the one member who is certainly in the run must never be capped out.
function LOBBY_HOOK.is_local(e)
    local ok, me = pcall(R.player.name)
    return ok and type(me) == "string" and me == e.name
end

--- Newest parse timestamp across the hook's entries, or nil.
function LOBBY_HOOK.newest()
    local newest = nil
    for _, e in ipairs(LOBBY_HOOK.order) do
        if e.seen and (not newest or e.seen > newest) then newest = e.seen end
    end
    return newest
end

--- Every lobby member. Pass `all` to include people who have since LEFT.
---
--- The roster is built from a detour, so it accumulates: session 5a1d listed
--- six members for a four-player run because the session had backed out of
--- matchmaking and searched again, and every candidate teammate ever parsed
--- stayed on the list forever. Stale names are not harmless — they are what
--- "name the leftover row" hands out.
function R.lobby.members(all)
    local out, seen = {}, {}
    local newest = LOBBY_HOOK.newest()
    -- Member RECORDS first: read back through the pointers the detour saw, so
    -- the fields are the engine's own (name, RequestedHero, Steam id) rather
    -- than anything recovered from the blob's text.
    for _, va in ipairs(LOBBY_HOOK.records) do
        local m = LOBBY_HOOK.read(va)
        -- NOT filtered on the record's InLobby byte either — same flag, same
        -- meaning ("in the lobby menu"), and it is false for everyone in a run.
        if m and not seen[m.name] then
            seen[m.name] = true
            out[#out + 1] = m
        end
    end
    -- Then whatever the blob told us on the first pass, for anyone whose
    -- record has not read back cleanly yet.
    -- Most recently parsed first, so `rank` is "how many members are fresher
    -- than this one" — the party cap then does the rest.
    local by_recency = {}
    for _, m in ipairs(LOBBY_HOOK.order) do by_recency[#by_recency + 1] = m end
    -- By PARSE SEQUENCE, not by `seen`: os.time() has one-second resolution and
    -- a lobby update parses every member inside the same second, so a
    -- timestamp sort is a coin flip and the tiebreak silently evicts whoever
    -- loses it. The counter is exact.
    table.sort(by_recency, function(a, b) return (a.seq or 0) > (b.seq or 0) end)
    for rank, m in ipairs(by_recency) do
        if not seen[m.name] then
            if all or LOBBY_HOOK.current(m, newest, rank) then
                seen[m.name] = true
                out[#out + 1] = { name = m.name, hero = m.hero,
                                  hero_id = m.hero_id, seen = m.seen,
                                  eos = m.eos, session = m.session,
                                  member = m.member, ptrs = m.ptrs,
                                  words = m.words,
                                  in_lobby = m.in_lobby, src = "hook" }
            elseif not LOBBY_HOOK.pruned[m.name] then
                -- Once per name. A roster that silently shrinks is as hard to
                -- read as one that silently grows.
                LOBBY_HOOK.pruned[m.name] = true
                R.log(("[rsmm.lobby] %q is not in this lobby (%s) — dropped "
                       .. "from the roster"):format(m.name,
                    rank > LOBBY_HOOK.MAX_PLAYERS
                        and ("%d newer members exist and the game seats %d")
                            :format(rank - 1, LOBBY_HOOK.MAX_PLAYERS)
                        or ("last parsed %ds before the newest member")
                           :format((newest or 0) - (m.seen or 0))))
            end
        end
    end
    -- Say it ONCE, the first time names exist. Without this the only way to
    -- tell "the hook is feeding us" from "the sweep quietly found the same two
    -- players again" is to correlate timings by hand across a whole log.
    -- Log on GROWTH, not once. The first version logged the first non-empty
    -- roster and never again: it printed "Brig" while three more players
    -- joined seconds later, so the log claimed one member for a session whose
    -- board correctly showed four.
    if #out > 0 and #out > (LOBBY_HOOK.logged or 0) and (LOBBY_HOOK.logs or 0) < 6 then
        LOBBY_HOOK.logged = #out
        LOBBY_HOOK.logs = (LOBBY_HOOK.logs or 0) + 1
        local parts = {}
        for _, m in ipairs(out) do
            parts[#parts + 1] = m.hero_id
                and string.format("%s(hero %d)", m.name, m.hero_id) or m.name
            parts[#parts] = parts[#parts] .. "[" .. (m.src or "scan") .. "]"
        end
        R.log("[rsmm.lobby] roster: " .. table.concat(parts, ", "))
    end
    -- Re-read through the cached addresses rather than trusting stale text:
    -- a member can leave, and the block is then no longer a block.
    for _, m in ipairs(_lobby_cache or {}) do
        local fresh = _lobby_read(m.addr)
        if fresh and not seen[fresh.name] then
            seen[fresh.name] = true
            out[#out + 1] = fresh
        end
    end
    return out
end

--- Locate the lobby blocks. EXPENSIVE (~4 s) — background thread only.
---
--- Rate-limited: a rescan is only attempted every `RESCAN_SECONDS`, because
--- the honest answer in a solo session is "there is no lobby block", and
--- retrying that at speed would be a permanent stutter.
--- Bytes examined per slice. A FULL sweep copies gigabytes and takes ~4 s;
--- session d44f proved that even one of those, on the background thread, is
--- felt as a hitch — ReadProcessMemory at that volume saturates memory
--- bandwidth and the process VM lock, which stalls the game's threads too.
--- So the sweep is cut into slices small enough to disappear into a tick.
local LOBBY_SLICE_MB = 48
--- Gap between slices. The pump ticks twice a second; one slice per tick keeps
--- the duty cycle low while still finishing a ~2 GB sweep inside a minute.
local LOBBY_SLICE_SECONDS = 1
--- How long a completed roster is taken as final before sweeping again.
---
--- A completed sweep is NOT the last word on who is in the session. Players
--- join while the run is loading, and a sweep that finishes first publishes a
--- roster that is merely current — but the cheap path below then re-validated
--- those blocks, found them all alive, and returned early forever, so the
--- roster froze at whoever had arrived. Measured in a 4-player session
--- (2026-08-16): `lobby scan: 2 member(s) — Akaza, Brig`, and the remaining two
--- rows stayed "Player 3" / "Player 4" for the rest of the log even though the
--- demand gate was asking for a scan every single second. Shrinkage was the
--- only thing that could ever trigger another sweep; growth could not.
local LOBBY_RESCAN_SECONDS = 15
local _lobby_cursor = 0            -- resume address, 0 = start a fresh sweep
local _lobby_found, _lobby_seen = {}, {}
local _lobby_slice_at = -math.huge

--- Advance the lobby sweep by ONE SLICE. Background thread only.
---
--- Returns the roster (possibly from a previous completed sweep) and whether
--- a sweep is still in progress. Call it repeatedly; it is designed to be
--- cheap enough to sit on a timer.
function R.lobby.refresh(force)
    -- Cheapest path of all: let the parser hook feed us instead. Armed here
    -- because this is the one entry point already documented as background-only
    -- and already called on a timer.
    LOBBY_HOOK.arm()
    if LOBBY_HOOK.state == 1 and not force
        and (#LOBBY_HOOK.order > 0 or #LOBBY_HOOK.records > 0) then
        return R.lobby.members()      -- names are arriving; never sweep
    end
    -- Hooked but silent. Installing a detour proves nothing about whether the
    -- game calls it, and "hooked" in the log read as "working" for a whole
    -- session that produced no names at all. Say it once; the sweep below is
    -- already running as the fallback, so this is a diagnosis, not a failure.
    if LOBBY_HOOK.state == 1 and not LOBBY_HOOK.warned and LOBBY_HOOK.armed_at
        and LOBBY_HOOK.fires == 0 and (os.time() - LOBBY_HOOK.armed_at) > 90 then
        LOBBY_HOOK.warned = true
        R.log("[rsmm.lobby] attribute parser hooked but NEVER CALLED in 90s — "
            .. "this build routes member attributes elsewhere; using the sweep")
    end
    if not I.mem_find then return R.lobby.members() end
    local now = os.time()
    -- Cheap path: everything we already know still validates AND the roster is
    -- recent enough to still be the whole story (see LOBBY_RESCAN_SECONDS).
    if _lobby_cache and #_lobby_cache > 0 and not force
        and (now - _lobby_cache_at) < LOBBY_RESCAN_SECONDS then
        local live = R.lobby.members()
        if #live == #_lobby_cache then return live end
    end
    if not force and (now - _lobby_slice_at) < LOBBY_SLICE_SECONDS then
        return R.lobby.members()
    end
    _lobby_slice_at = now
    if force then _lobby_cursor, _lobby_found, _lobby_seen = 0, {}, {} end

    repeat
        local hits, nxt = I.mem_find("PlayerName\0", 16,
                                     force and MEM_SCAN_MB or LOBBY_SLICE_MB,
                                     _lobby_cursor)
        for _, va in ipairs(hits or {}) do
            -- The anchor check: a genuine lobby block has RequestedHero at
            -- -0x60. Lua's interned copy of the literal "PlayerName" — which
            -- this very search creates — does not, and without it the roster
            -- is our own string table.
            local m = _lobby_read(va)
            if m and not _lobby_seen[m.name] then
                _lobby_seen[m.name] = true
                _lobby_found[#_lobby_found + 1] = m
            end
        end
        _lobby_cursor = nxt or 0
    until not force or _lobby_cursor == 0

    if _lobby_cursor == 0 then
        -- Sweep complete: publish, and start the next one from scratch.
        --
        -- A SLICED sweep merges; a FORCED one replaces. Slices span many ticks,
        -- so a member whose block is allocated mid-sweep can be missed by the
        -- slice that already passed its address, and replacing wholesale would
        -- then DROP a player who is still in the session and re-label their row
        -- back to "Player 3". Carried-over entries are re-validated through
        -- `_lobby_read`, so someone who actually left still disappears. `force`
        -- walks the whole address space in one call, so its result IS the
        -- roster — merging there would only preserve ghosts.
        local merged, seen = {}, {}
        local carry = (not force) and _lobby_cache or nil
        for _, m in ipairs(_lobby_found) do
            if not seen[m.name] then
                seen[m.name] = true
                merged[#merged + 1] = m
            end
        end
        for _, m in ipairs(carry or {}) do
            if not seen[m.name] and _lobby_read(m.addr) then
                seen[m.name] = true
                merged[#merged + 1] = m
            end
        end
        _lobby_cache, _lobby_cache_at = merged, now
        _lobby_found, _lobby_seen = {}, {}
        -- Report the first two completed sweeps even when they find NOTHING.
        -- The caller only logs when the count CHANGES, so a sweep that
        -- finishes empty is indistinguishable from a sweep that never
        -- finished — and in the 2b4f session both the hook and the sweep were
        -- silent, which left no way to tell which one to go and fix.
        -- Counter lives on LOBBY_HOOK: the main chunk is at Lua's 200-local
        -- ceiling and one more top-level `local` fails the whole SDK.
        LOBBY_HOOK.sweeps = (LOBBY_HOOK.sweeps or 0) + 1
        if LOBBY_HOOK.sweeps <= 2 then
            R.log(("[rsmm.lobby] address sweep #%d complete: %d attribute "
                   .. "block(s) found"):format(LOBBY_HOOK.sweeps, #_lobby_cache))
        end
        return _lobby_cache
    end
    return R.lobby.members()      -- mid-sweep: whatever the last sweep found
end

--- True while a slice sweep is still walking the address space.
function R.lobby.scanning() return _lobby_cursor ~= 0 end

--- Display names of everyone in the lobby EXCEPT the local player.
function R.lobby.allies()
    local me = nil
    local ok, n = pcall(R.player.name)
    if ok and type(n) == "string" then me = n end
    local out = {}
    for _, m in ipairs(R.lobby.members()) do
        if m.name ~= me then out[#out + 1] = m.name end
    end
    return out
end

--- Hero name for a lobby `RequestedHero` id, or nil.
---
--- The twelve shipped `Definitions\\Heroes\\*.herodef.ot` in load (alphabetical)
--- order. INFERRED, not read from the engine: the id is not stored in the
--- herodef payload, so this is positional. It matches every observation to
--- hand -- session 304f had the local player at RequestedHero 10, and index 10
--- is Snow_Queen, which is also the one hero `_HERO_SIGNATURES` was seeded from
--- (i.e. the hero whose events were catalogued from that very machine).
---
--- DISPLAY ONLY. Nothing may name a damage row from this: knowing that a
--- player picked Juliet does not tell you WHICH ROW is Juliet, because the hero
--- entity carries no hero id to compare against (Ghidra: the hero entity is a
--- generic component aggregate with no type/def field). It exists so a roster
--- line reads "Yume (Juliet)" instead of "Yume (hero 4)", which is what lets a
--- player map slots to people by eye and fill in player_1..player_4.
R.lobby.HERO_NAMES = {
    [0] = "Aladdin", "Beowulf", "Carmilla", "Geppetto", "Juliet", "Melusine",
          "Merlin", "Piper", "Red", "Romeo", "Snow_Queen", "Sun_Wukong",
}

function R.lobby.hero_name(id)
    if type(id) ~= "number" then return nil end
    return R.lobby.HERO_NAMES[id]
end

-- interaction bus ---------------------------------------------------------
--
-- The game already owns a complete interaction system; this is a thin, honest
-- wrapper over it rather than a reimplementation. What ships in the retail
-- exe:
--
--   oCDtEntityCpntInteractionSettings   authored per entity (122 shipped
--                                       entity defs carry one: chests,
--                                       fountains, the wishing well, altars,
--                                       cauldrons, teleporters, ruins, ...)
--   oCDtEntityCpntInteraction           the runtime component
--   oCDtEntityCpntInteractionNetworkData  its replicated half
--   oCDtNamedEventInteraction           the event object, payload at +0x38
--                                       and +0x50 (mined, meaning NOT yet
--                                       confirmed -- exposed raw as `a`/`b`)
--
-- and a seven-name request/validate/commit protocol on the gameplay bus:
--
--   INTERACTION_REQUEST -> INTERACTION_VALIDATE -> INTERACTION_SUCCESS
--                                               \-> INTERACTION_REJECT
--                                               \-> INTERACTION_FAILED
--                                               \-> INTERACTION_CANCELED
--   LOCAL_INTERACTION_SUCCESS  -- the local peer's own copy
--
-- The shape is host-authoritative, which matches the netcode
-- ([[multiplayer-netcode]]): a client ASKS, the host validates, and the
-- outcome comes back. So a mod must treat `request` as an intent it may not
-- get, and hang real effects off `success` / `local_success`.
--
-- WHAT THIS DOES NOT DO YET. It does not tell you WHICH object was
-- interacted with. The dispatcher pointer and the two payload words are
-- published verbatim precisely so one playtest can pin that down
-- (`R.interact.trace(true)` + `R.interact.identify`), rather than the SDK
-- guessing a meaning and mods building on it.
R.interact = {}

--- Bus name -> phase. Also the set of names this module listens to.
local INTERACT_PHASE = {
    ["gameplay:INTERACTION_REQUEST"]       = "request",
    ["gameplay:INTERACTION_VALIDATE"]      = "validate",
    ["gameplay:INTERACTION_SUCCESS"]       = "success",
    ["gameplay:LOCAL_INTERACTION_SUCCESS"] = "local_success",
    ["gameplay:INTERACTION_REJECT"]        = "reject",
    ["gameplay:INTERACTION_FAILED"]        = "failed",
    ["gameplay:INTERACTION_CANCELED"]      = "canceled",
}

local _interact_subs = {}     -- phase (or "*") -> { cb, ... }
local _interact_last = nil
local _interact_trace = false

--- A payload word arrives as a hex STRING (a Lua number is a double and loses
--- the low bits of a 64-bit handle). Numbers pass through unchanged.
local function _word(v)
    if type(v) == "number" then return v end
    if type(v) == "string" then return tonumber(v) end
    return nil
end

--- The most recent interaction seen, or nil. Same table the callbacks get.
function R.interact.last() return _interact_last end

--- Log one line per interaction event. Off by default: this fires on every
--- chest, fountain and teleporter in the run.
function R.interact.trace(on) _interact_trace = (on ~= false) end

--- Subscribe to one phase, or to "*" for all of them.
--
-- The callback gets a table:
--   phase       "request" | "validate" | "success" | "local_success"
--               | "reject" | "failed" | "canceled"
--   name        the raw bus name
--   seq         the loader's dispatch counter
--   dispatcher  the entity dispatcher the event fired at (number)
--   a, b        the event payload words at +0x38 / +0x50, meaning unconfirmed
--   class       the decoded event class, when the loader could decode one
function R.interact.on(phase, cb)
    assert(type(cb) == "function", "R.interact.on: callback must be a function")
    phase = phase or "*"
    _interact_subs[phase] = _interact_subs[phase] or {}
    table.insert(_interact_subs[phase], cb)
    return { phase = phase, index = #_interact_subs[phase] }
end

--- Best-effort "what did I just interact with".
--
-- Reads the strings hanging off a pointer from the interaction payload and
-- keeps the ones that look like an engine resource path. Returns the first
-- such path (and the full list as a second value), or nil.
--
-- Best-effort is meant literally: until a playtest says what `a` and `b`
-- actually point at, this is the tool for FINDING that out, not a stable
-- identifier to key mod behaviour on.
function R.interact.identify(ptr, opts)
    ptr = _word(ptr)
    if not ptr then return nil, {} end
    local hits = R.debug.strings(ptr, opts or { log = false })
    local paths = {}
    for _, h in ipairs(hits) do
        if h.text:find("%.ot") or h.text:find("\\") then
            paths[#paths + 1] = h.text
        end
    end
    return paths[1], paths
end

R.on("*", function(ev, name)
    local phase = INTERACT_PHASE[name]
    if not phase then return end
    -- Typed fields first (`u38`/`u50`, keyed by the event's own vftable), then
    -- the generic RSMM_EVENT_PROBE window (`w38`/`w50`). The typed decode is
    -- gated on the build fingerprint — mined vftable RVAs are build-specific —
    -- so on a game build the schemas were not re-mined for, `u38` is simply
    -- absent and the probe window is the only way to see the payload at all.
    -- Taking both means a mod reads `a`/`b` the same way either way.
    local info = {
        phase      = phase,
        name       = name,
        seq        = ev.seq,
        dispatcher = _word(ev.dispatcher),
        a          = _word(ev.u38) or _word(ev.w38),
        b          = _word(ev.u50) or _word(ev.w50),
        class      = ev.class,
    }
    _interact_last = info
    if _interact_trace then
        R.log(string.format(
            "[rsmm.interact] %-13s seq=%s disp=0x%x a=0x%x b=0x%x %s",
            info.phase, tostring(info.seq), info.dispatcher or 0,
            info.a or 0, info.b or 0, info.class or ""))
    end
    for _, key in ipairs({ phase, "*" }) do
        for _, cb in ipairs(_interact_subs[key] or {}) do
            -- One bad handler must not take the others down with it, and this
            -- runs on the engine's dispatch thread — an error escaping here
            -- unwinds into the game.
            local ok, err = pcall(cb, info)
            if not ok then R.log("[rsmm.interact] handler error: " .. tostring(err)) end
        end
    end
end)

-- loader-derived events --------------------------------------------------
--
-- The engine's own buses say what the GAME did; these say what the LOADER
-- knows. They close the gaps mods used to paper over by polling every tick:
--
--   "hero:captured" { hero }              -- the local hero became readable
--   "hero:changed"  { hero, previous }    -- character switch / new run
--   "hero:lost"     { previous }          -- run ended, capture invalidated
--   "menu:enter" / "menu:leave"           -- main-menu transitions
--   "run:start" / "run:end"               -- run boundaries
--
-- All of them are published from the "tick" pump, i.e. the loader's
-- BACKGROUND thread (`ev.source == "loader"`, never "gameplay"). Engine-
-- mutating work in these handlers must go through R.schedule.next_main —
-- see [[loader-thread-model]].

-- projectile / attack geometry ------------------------------------------
--
-- oCEntityCpntGpnProjectileAttack is the engine's LINE attack: it sweeps a
-- volume from a start point to an end point and damages every hittable Gpn
-- inside it ("Damage all hittable Gpn in line"). Its slot-28 begin call
-- (ProjectileAttack_BeginAttack) seeds that volume once per attack:
--
--   cpnt+0xd0/0xd4/0xd8   start xyz  (the owner entity's position)
--   cpnt+0xdc/0xe0/0xe4   end   xyz  (same at t=0, swept forward as it flies)
--   cpnt+0xe8             WIDTH — full thickness, from settings+0x100
--
-- The width semantics are not a guess: the component's own debug draw (slot
-- 20) renders the volume using `+0xe8 * 0.5` as the half-extent either side of
-- the start->end line, so +0xe8 is the full width and scaling it widens the
-- hit volume symmetrically.
--
-- WHAT THIS IS NOT. Two honest limits, both worth reading before shipping a
-- mod on top of this:
--
--  1. It is the HITBOX, not the art. Nothing here touches the mesh, the
--     particle system or the trail, so a scaled attack hits wider while
--     looking exactly the same. There is no known entity-value ("stat") for
--     projectile size — the registered ~40 keys have no size/area/scale
--     member — so the visual would need a separate, unrelated lever.
--  2. It is the Gpn line attack, not literally every projectile in the game.
--     Attacks built some other way are unaffected.
--
-- THREAD SAFETY. The write lands on an object the engine populated
-- microseconds earlier, from inside that same call, on that same thread. It
-- makes no engine call and allocates nothing, so unlike most of this SDK it
-- needs no R.schedule.next_main. See [[loader-thread-model]].
R.projectile = {}

local PROJ_WIDTH_OFF = 0xe8
local _proj_hooked, _proj_mult = false, 1.0

--- Scale the width of every Gpn line attack by `mult` (1.0 = vanilla).
--
-- Idempotent: the hook installs once and later calls only retune the
-- multiplier, so a mod may call this from a config-reload handler without
-- stacking detours. Passing 1.0 leaves the hook installed but inert.
--
-- Returns true when the hook is live (including when another mod's lua_State
-- already owns it — the multiplier is per-state, so both still apply their
-- own), false when the symbol is unavailable on this build.
function R.projectile.scale_width(mult)
    mult = tonumber(mult) or 1.0
    -- A non-positive width collapses the volume and nothing can ever be hit;
    -- an absurd one turns every attack into a screen-wide sweep. Clamp rather
    -- than refuse, so a bad config value degrades instead of erroring.
    if mult < 0.01 then mult = 0.01 elseif mult > 100 then mult = 100 end
    _proj_mult = mult
    if _proj_hooked then return true end
    if not (R.hook and I.resolve and I.read_f32 and I.write_f32) then return false end

    local va = I.resolve("ProjectileAttack_BeginAttack")
    -- nil/0 when the symbol is unverified for this build: fail closed rather
    -- than detouring a stale address.
    if not va or va == 0 then return false end

    local ok, slot, why = pcall(R.hook, va, "vp", function(this, next)
        -- Run the original FIRST — it is what writes the width we scale. The
        -- pre-call value is the previous attack's, so scaling before the call
        -- would be overwritten and do nothing.
        --
        -- Return a NON-nil value having called next(). Current loaders track
        -- that next() ran and will not replay the trampoline, but loaders
        -- built before that fix replay on any nil return — which would begin
        -- the attack TWICE. Returning 0 is correct under both, and this SDK
        -- is disk-loaded, so it routinely runs against an older DLL.
        next(this)
        if _proj_mult ~= 1.0 and this and this ~= 0 then
            local w = I.read_f32(this + PROJ_WIDTH_OFF)
            -- read_f32 is page-guarded: a bad pointer yields nil, never a
            -- fault. Width is only ever a small positive extent, so a zero,
            -- negative or absurd read means this is not the object we think
            -- it is and the sane response is to leave it alone.
            if w and w > 0 and w < 1e6 then
                I.write_f32(this + PROJ_WIDTH_OFF, w * _proj_mult)
            end
        end
        return 0
    end)
    if not ok then return false end
    -- (nil, "already-hooked") means another mod's lua_State installed the
    -- detour first. The hook is live and this state's callback still runs, so
    -- that is success, not failure.
    if slot == nil and why ~= "already-hooked" then return false end
    _proj_hooked = true
    return true
end

--- Current multiplier (1.0 when unscaled).
function R.projectile.width_scale() return _proj_mult end

-- damage meter --------------------------------------------------------------
--
-- Lives in rsmm/damage.lua (~5000 lines, 45% of what this file used to be).
-- It is required HERE rather than with the other submodules further up because
-- it needs LOBBY_HOOK and MEM_SCAN_MB, which are declared just above.
--
--     R.damage.enable{ window = 10 }
--     for rank, row in ipairs(R.damage.board()) do
--         R.log(rank, row.label, row.dealt, row.share, row.dps)
--     end
--
-- Unlike the plain-table submodules it returns a FUNCTION and populates R and
-- F in place: it owns 86 private F helpers, installs three hooks of its own,
-- and one parent value it reads (_DISPATCHER_ENTITY_OFF) is learned at runtime
-- and so is passed as a getter, not a value.
_submodule_fn("damage", {
    I = I, R = R, F = F,
    _va_ok = _va_ok, _ptr_plausible = _ptr_plausible,
    ENTITY_IMG_BASE      = ENTITY_IMG_BASE,
    LOBBY_REFRESH_SLOT   = LOBBY_REFRESH_SLOT,
    MEM_SCAN_MB          = MEM_SCAN_MB,
    LOBBY_HOOK           = LOBBY_HOOK,
    dispatcher_entity_off = function() return _DISPATCHER_ENTITY_OFF end,
})


R.run = {}

local _last_hero, _last_menu, _run_active = nil, nil, false

local function _derived_poll()
    local ok, hero = pcall(R.entity.hero)
    if not ok then hero = nil end
    if hero ~= _last_hero then
        if hero and _last_hero then
            _publish("hero:changed", { hero = hero, previous = _last_hero })
        elseif hero then
            _publish("hero:captured", { hero = hero })
        else
            _publish("hero:lost", { previous = _last_hero })
        end
        _last_hero = hero
    end

    local in_menu = false
    if I.is_in_main_menu then
        local o, v = pcall(I.is_in_main_menu)
        in_menu = (o and v) or false
    end
    if _last_menu == nil then
        _last_menu = in_menu            -- first poll establishes the baseline
    elseif in_menu ~= _last_menu then
        _last_menu = in_menu
        _publish(in_menu and "menu:enter" or "menu:leave", {})
    end
end

R.on("tick", _derived_poll)

-- Promote the pending spawn-init hero on the tick pump, not on demand.
--
-- The native hook stashes the hero the instant its spawn/post-load init runs,
-- but its HP/mirror fields are not populated yet, so the plausibility gate
-- refuses it and it sits in the pending slot. NOTHING re-checked that slot:
-- promotion happened only inside R.entity.hero(), i.e. only when a mod
-- happened to ask. A mod that asks once at `ready` asks too early and never
-- again; a mod that never asks leaves the hero uncaptured forever. In practice
-- capture then waited for the give/gain handlers, which fire on a hero ACTION
-- (a pickup or a heal) -- measured at ten minutes in one playtest, and it read
-- as "R.stat is broken" rather than "nobody polled".
--
-- Polling here closes that gap for every mod at once: the fields go live a few
-- seconds into the load and the very next tick publishes the hero. Safe on the
-- loader's background thread -- this path only does page-guarded reads and a
-- shared_set, never an engine call (see [[loader-thread-model]]). Gated on
-- native capture being active so it can never trigger the legacy branch's
-- detour install off-thread.
R.on("tick", function()
    if not _native_capture_active() then return end
    if not I.shared_get then return end
    -- The poll itself is NOT gated on run state. It is a handful of
    -- page-guarded reads, and gating it would make capture wait for
    -- `run_start`, which rides the analytics firehose and can arrive per
    -- CHAPTER rather than at hero spawn — trading log noise for a slower
    -- capture, when noise was the only problem. The menu's preview character
    -- cannot be promoted anyway: the plausibility gate needs live HP. Only the
    -- DIAGNOSTICS inside are gated (see HERO_SCAN.in_play).
    local ok, h = pcall(I.shared_get, SHARED_HERO_SLOT)
    if ok and type(h) == "number" and h ~= 0 and _hero_plausible(h) then return end
    R.entity.hero()          -- runs the pending-promotion + REJECT diagnostic
end)

-- Run boundaries, normalised off the analytics firehose so a mod doesn't have
-- to know which raw name the game uses (and gets an idempotent pair: the raw
-- events can repeat per chapter).
R.on("run_start", function()
    R.run._signalled = true
    if not _run_active then
        _run_active = true
        if I.now then
            local ok, t = pcall(I.now)
            R.run._started_at = (ok and type(t) == "number") and t or nil
        end
        _publish("run:start", {})
    end
end)
R.on("run_end", function(ev)
    R.run._signalled = true
    R.run._started_at = nil
    if _run_active then
        _run_active = false
        local copy = {}
        if type(ev) == "table" then for k, v in pairs(ev) do copy[k] = v end end
        _publish("run:end", copy)
    end
end)

-- PLAY STATE, from the gameplay bus — a second opinion on "is a run running",
-- for gating diagnostics when the analytics boundary never fires (see
-- HERO_SCAN.in_play). Deliberately NOT wired into run:start / run:end: mods
-- reset their counters there, and MAP_GENERATION_DONE fires once per CHAPTER,
-- so publishing it would wipe a damage board three times a run.
-- GAME_END_NEXT_CHAPTER is absent on purpose — the chapter ends, the run does
-- not.
--
-- Written out rather than looped: a `for` control variable is a local in the
-- MAIN CHUNK, which is at Lua's 200-local ceiling, and the loop cost the whole
-- SDK its compile.
function R.run._play(on)
    R.run._play_signalled, R.run._play_active = true, on and true or false
end
R.on("gameplay:GAME_START",                 function() R.run._play(true) end)
R.on("gameplay:MAP_GENERATION_DONE",        function() R.run._play(true) end)
R.on("gameplay:GAME_CHRONO_START",          function() R.run._play(true) end)
R.on("gameplay:GAME_END_FAILED",            function() R.run._play(false) end)
R.on("gameplay:GAME_END_SUCCESS",           function() R.run._play(false) end)
R.on("gameplay:GAME_END_SUCCESS_SKIP_NEXT", function() R.run._play(false) end)
R.on("gameplay:GAME_END_CHANGE_STATE",      function() R.run._play(false) end)

--- Is a run running according to the GAMEPLAY BUS? nil when it has said
--- nothing yet — which is a different answer from false, and the reason
--- diagnostics can tell "menus" apart from "we have no idea".
function R.run.playing()
    if not R.run._play_signalled then return nil end
    return R.run._play_active == true
end

-- True between run:start and run:end.
function R.run.active() return _run_active end

--- Has this process ever seen a run boundary at all?
---
--- The difference between "not in a run" and "we have no idea" decides whether
--- anything may be gated on run state. run_start/run_end ride the analytics
--- firehose, which a session can legitimately be missing (the symbol may not
--- resolve, or the capability is off), and a gate that treats "no signal" as
--- "not in a run" would silence the very diagnostics that exist to catch a
--- moved offset. Callers fall back to their old behaviour when this is false.
function R.run.signalled() return R.run._signalled == true end

--- When the current run started (I.now clock), or nil.
function R.run.started_at() return R.run._started_at end

-- ── R.serialize ───────────────────────────────────────────────────────────
--
-- Write engine objects back out through the ENGINE'S OWN serializer.
--
-- oCBinaryLoader and oCBinarySaver implement the same 23-slot oISerializer
-- interface slot-for-slot, and every class's `Serialize` (vftable slot 3 — the
-- same slot the codec work calls "Deserialize") is direction-agnostic: it asks
-- the serializer `IsSaving()` (slot 4) and then transfers each field through
-- the typed slots, which either read the loader's stream or write the saver's.
-- So the routine that PARSES a cooked def also EMITS it, including every
-- payload rsmm's Python codecs still carry as opaque `_tail_hex`.
--
-- `Object_SaveToFile` is the whole cooker in one call: it opens a file stream,
-- stack-builds an oCBinarySaver, writes the `Cooked` header flag, then writes
-- the class table (name/id/version-maj/version-min/parent) and the object
-- graph — the exact shape `rsmm.engine.cooked.parse` reads back.
--
--   R.serialize.ready()            -- is the capability resolvable on this build?
--   R.serialize.can(obj)           -- does `obj` look like a serializable?
--   R.serialize.save(obj, "dump/tile.ot")   -- write it, cooked, under mod_dir
--   R.serialize.clone(dst, src)    -- deep-copy via a memory round-trip (no disk)
--
-- ENGINE-MUTATING + FILE IO: call these from the MAIN thread (a gameplay-event
-- handler, or R.schedule.next_main) — see [[loader-thread-model]]. Destinations
-- are confined to the calling mod's own directory on purpose: this API writes
-- whatever bytes the engine produces, and a mod that can aim it at
-- `<game>/DarkTalesResources` can overwrite retail assets with no backup and no
-- state entry, which is exactly what `rsmm apply`/`restore` exist to prevent.
-- Wrapped in an immediately-called function, not a `do` block: the main
-- chunk is AT Lua's 200-local ceiling, and a do-block's locals still cost
-- registers in the enclosing function. A new function gets its own budget.
;(function()
R.serialize = {}

local SER_LITERAL = 0x80000000     -- oCTString<char> "not owned" flag bit

--- Is the serializer bridge usable on this build?
function R.serialize.ready()
    local ok, va = pcall(R.engine.resolve, "Object_SaveToFile")
    return ok and type(va) == "number" and va ~= 0
end

--- Does `obj` look like an oISerializable — vftable in the image, with the two
--- slots the saver will call (1 = GetClassId, 3 = Serialize) pointing at code?
---
--- This is the whole guard: the saver dereferences `obj` and vcalls both slots
--- before any of our code runs again, so a wrong pointer is a hard fault of the
--- game process, not a nil.
function R.serialize.can(obj)
    if not R.ptr.has_vtable(obj) then return false end
    local vt = I.read_u64(obj)
    if not vt then return false end
    local class_id = I.read_u64(vt + 0x08)     -- slot 1
    local serialize = I.read_u64(vt + 0x18)    -- slot 3
    return R.ptr.in_image(class_id) and R.ptr.in_image(serialize)
end

-- Confine a destination to the calling mod's own directory and hand back the
-- absolute path, WINDOWS-STYLE.
--
-- Backslashes are not cosmetic here. oCFileBinaryStream::Open widens the path
-- and prepends the `\\?\` long-path prefix before CreateFileW, and that prefix
-- turns OFF Win32 path normalisation — forward slashes are no longer accepted
-- as separators. A posix-looking `Z:/home/.../x.ot` therefore fails to open and
-- comes back as a plain "write failure", which is what the first in-game run of
-- this bridge hit.
local function _dest_path(rel)
    if type(rel) ~= "string" or rel == "" then return nil, "path must be a string" end
    local norm = rel:gsub("/", "\\")
    if norm:find("%.%.") then return nil, "path may not contain '..'" end
    if norm:sub(1, 1) == "\\" or norm:find("^%a:") then
        return nil, "path must be relative to the mod directory"
    end
    local dir = R.mod_dir()
    if type(dir) ~= "string" or dir == "" then return nil, "mod directory unknown" end
    return (dir:gsub("/", "\\"):gsub("\\+$", "")) .. "\\" .. norm
end

-- Lay an oCTString<char> out in scratch: { char* ptr, u32 flags|len, u32 }.
-- The engine's own literals use exactly this shape (0x80000000 | length), and
-- Object_SaveToFile takes the string BY ADDRESS. One scratch alloc holds both
-- the header and the bytes — never take a second while the first is live.
local SCRATCH_MAX = 0x1000        -- lua_scratch's kMaxAlloc; over it it THROWS

local function _octstring(str)
    local n = #str
    -- Bound the request rather than let lua_scratch luaL_error out of it: a
    -- long mod dir plus a long relative path is enough to cross kMaxAlloc, and
    -- every caller here is documented to fail closed with `nil, err`.
    if 0x18 + n + 1 > SCRATCH_MAX then return nil end
    -- Alignment needs no fixup: lua_scratch rounds every allocation up to 16
    -- over an alignas(16) arena, so scratch addresses are always 16-aligned and
    -- the header starts aligned for free. (call_safe's pointer guard rejects an
    -- unaligned argument, so this would matter if the arena were byte-granular.)
    local buf = I.scratch(0x18 + n + 1)
    if not buf or buf == 0 then return nil end
    local bytes = buf + 0x10
    for i = 1, n do I.write_u8(bytes + i - 1, str:byte(i)) end
    I.write_u8(bytes + n, 0)
    I.write_u64(buf, bytes)
    I.write_u32(buf + 0x08, SER_LITERAL + n)
    I.write_u32(buf + 0x0c, 0)
    return buf
end

--- Serialize `obj` to `rel_path` (relative to this mod's directory).
---
--- Returns true, path on success and nil, err otherwise — every refusal path is
--- fail-closed.
---
--- ⚠ The engine always writes the TYPE-B container (`uNbFlags = 0`): the
--- prologue of Object_SaveToFile hardcodes the saver's flag byte (saver+0x10)
--- to 0, so the `"Cooked"` header block retail files carry is never emitted,
--- whatever is passed. That is a 15-byte header difference and nothing else —
--- measured 2026-08-23, the body was byte-identical to the shipped file over
--- all 523 bytes. Promote it host-side with
--- `rsmm.engine.cooked.promote_to_cooked` when a retail-shaped file is wanted.
---
--- The engine's file stream OPENS a file; it does not create directories. A
--- `rel_path` with a directory component only works if that directory already
--- exists, and otherwise comes back as a plain write failure.
function R.serialize.save(obj, rel_path)
    if not R.serialize.ready() then return nil, "Object_SaveToFile unresolved on this build" end
    if not R.serialize.can(obj) then return nil, "object is not a plausible oISerializable" end
    local path, err = _dest_path(rel_path)
    if not path then return nil, err end
    local str = _octstring(path)
    if not str then return nil, "scratch allocation failed" end
    -- arg 3 is NOT the cooked flag (see the note above): it is forwarded to a
    -- stream-setup helper. Pass 0 and promote the header host-side.
    local rc = R.engine.call_safe("Object_SaveToFile",
        { { 1, R.serialize.can }, 2 }, obj, str, 0, 0)
    if rc == nil then return nil, "call refused by the pointer guard" end
    if rc == 0 then
        -- Name the path: every failure inside Object_SaveToFile (open refused,
        -- missing directory, wrong separator form) surfaces as this one zero.
        return nil, ("engine write failed for %s (directory missing? path form?)"):format(path)
    end
    return true, path
end

--- Deep-copy `src` into `dst` by round-tripping through a memory stream.
---
--- No disk involved, so this is the cheap smoke test for the bridge: if a def
--- clones, save() is the same path with a file stream behind it. Both objects
--- must already be live instances of the SAME class.
---
--- ⚠ DESTRUCTIVE to `dst`: the second half deserializes over it in place. Every
--- object reachable from R.defs is one the game is still using, so there is no
--- free destination — do not point this at a live definition to "test" it.
function R.serialize.clone(dst, src)
    if not R.serialize.ready() then return nil, "serializer bridge unresolved on this build" end
    if not R.serialize.can(dst) then return nil, "dst is not a plausible oISerializable" end
    if not R.serialize.can(src) then return nil, "src is not a plausible oISerializable" end
    -- args 3 and 4 are IGNORED by the callee, so 0 is safe: the prologue
    -- overwrites r8 (`lea r8d, [rsi+4]`) and r9 without ever reading them in,
    -- and supplies its OWN label literal to BinarySaver_WriteGraph at
    -- 0x1404fe6fd. Unlike Object_SaveToFile, there is no caller-owned string
    -- here to get wrong.
    local rc = R.engine.call_safe("Object_CloneViaSerialize",
        { { 1, R.serialize.can }, { 2, R.serialize.can } }, dst, src, 0, 0)
    if rc == nil then return nil, "call refused by the pointer guard" end
    return rc ~= 0
end
end)()

-- ── R.rtti / R.defs ───────────────────────────────────────────────────────
--
-- Name a live object, and enumerate every definition instance the game has
-- loaded. Together these are what makes R.serialize usable: the saver needs a
-- live oISerializable, and until now the SDK had no way to hand it one.
--
--   R.rtti.name(obj)          -- "oCDtEnemyDefinition" (MSVC RTTI walk)
--   R.defs.classes()          -- every populated registry entry, named
--   R.defs.instances("oCDtEnemyDefinition")  -- live instances of one class
--   R.defs.first("oCDtMapDefinition")        -- the first one, or nil
--   R.defs.dump()             -- log the inventory
--
-- Reads only. The instance registry is an absl SwissTable keyed on the class
-- descriptor, and the engine's own accessor (Registry_EnumInstances) is
-- find-or-INSERT: asking it about a class that has no instances mutates the
-- map and can trigger a rehash — an allocation on the game's heap, from what
-- the caller believed was a look. So this walks the table's three globals
-- directly with page-guarded reads and never calls in.
--
-- Wrapped in an immediately-called function for the same reason R.serialize is:
-- the main chunk is at Lua's 200-local ceiling.
;(function()

R.rtti = {}
R.defs = {}

-- absl control bytes: high bit CLEAR = full slot (h2), 0x80 = empty,
-- 0xfe = deleted. Slot stride 0x18 = { u64 classDesc, u64 data, u32 count }.
-- Baked at the map's image base and REBASED at read time. The game is loaded
-- wherever Windows puts it, so a raw read of 0x1412f0a68 lands in unmapped
-- memory and every read comes back nil — which surfaced as "registry
-- unreadable", indistinguishable from a moved global. Every other va-global in
-- this file does the same rebase (see GIVE_POOL_VA / OPT_GAMEOPTIONS_VA).
local DEFS_IMG_BASE = 0x140000000
local CTRL_VA  = 0x1412f0a68     -- DefinitionRegistry_Ctrl
local SLOTS_VA = 0x1412f0a70     -- DefinitionRegistry_Slots
local MASK_VA  = 0x1412f0a80     -- DefinitionRegistry_Mask
local SLOT_STRIDE = 0x18
local MAX_CAPACITY = 0x40000     -- refuse an implausible mask rather than spin
local MAX_INSTANCES = 0x8000

--- Mangled RTTI name of a live object, e.g. ".?AVoCDtEnemyDefinition@@".
---
--- MSVC x64 layout: *obj = vftable, vftable[-1] = complete object locator,
--- COL+0x0 = signature, COL+0xc = type-descriptor RVA, COL+0x14 = self RVA
--- (signature 1 only), and the type descriptor carries the name at +0x10.
--- Every read is page-guarded, so a non-object pointer yields nil, not a fault.
function R.rtti.raw(obj)
    if not R.ptr.has_vtable(obj) then return nil end
    local vt = I.read_u64(obj)
    -- has_vtable read this once already, but the object can be torn down (or
    -- its page unmapped) between the two reads, and `nil - 8` is an ERROR, not
    -- a nil — it would escape R.defs.classes()/dump(), which are documented as
    -- read-only walks that never fault.
    if not vt then return nil end
    local col = I.read_u64(vt - 8)
    if not col then return nil end
    if not R.ptr.in_image(col) then return nil end
    local sig = I.read_u32(col)
    if sig ~= 0 and sig ~= 1 then return nil end
    local td_rva = I.read_u32(col + 0x0c)
    if not td_rva or td_rva == 0 then return nil end
    -- Signature 1 images store their own RVA, which gives the base without
    -- trusting the loader's idea of it; signature 0 (32-bit-style) does not.
    local base
    if sig == 1 then
        local self_rva = I.read_u32(col + 0x14)
        base = self_rva and (col - self_rva) or nil
    end
    base = base or I.module_base()
    if not base or base == 0 then return nil end
    local td = base + td_rva
    if not R.ptr.in_image(td) then return nil end
    local name = I.read_cstr(td + 0x10)
    if type(name) ~= "string" or name == "" then return nil end
    return name
end

--- Readable class name of a live object: ".?AVoCFoo@bar@@" -> "bar::oCFoo".
--- MSVC stores the qualifiers innermost-first, so the pieces are reversed.
function R.rtti.name(obj)
    local raw = R.rtti.raw(obj)
    if not raw then return nil end
    local body = raw:match("^%.%?A[VU](.+)@@$")
    if not body then return raw end
    local parts = {}
    for piece in body:gmatch("[^@]+") do parts[#parts + 1] = piece end
    for i = 1, #parts // 2 do
        parts[i], parts[#parts - i + 1] = parts[#parts - i + 1], parts[i]
    end
    return table.concat(parts, "::")
end

-- The three globals, validated together. Returns ctrl, slots, mask — or nil
-- plus a REASON, because "unreadable" covers five different failures and a
-- probe that cannot say which one wastes a playtest.
local function _table_view()
    if not _va_ok("R.defs") then return nil, "va-gate closed (build != symbol map)" end
    local base = I.module_base()
    if not base or base == 0 then return nil, "module base unknown" end
    local ctrl  = I.read_u64(base + (CTRL_VA  - DEFS_IMG_BASE))
    local slots = I.read_u64(base + (SLOTS_VA - DEFS_IMG_BASE))
    local mask  = I.read_u64(base + (MASK_VA  - DEFS_IMG_BASE))
    if not (ctrl and slots and mask) then
        return nil, "globals unreadable (moved? too early in boot?)"
    end
    -- Deliberately NOT R.ptr.plausible for the control array: that helper
    -- requires 8-alignment because heap OBJECTS are 8-aligned, and the ctrl
    -- array is a byte array whose start need not be. Range-check it instead;
    -- the slot array holds 0x18-stride records and does get the full check.
    if not ctrl or ctrl < 0x10000 or ctrl > 0x00007fffffffffff then
        return nil, string.format("ctrl pointer implausible (0x%x)", ctrl or 0)
    end
    if not R.ptr.plausible(slots) then
        return nil, string.format("slot pointer implausible (0x%x)", slots or 0)
    end
    -- Capacity is a power of two, so mask is all-ones. A garbage mask would
    -- otherwise turn the walk below into a multi-million-iteration probe.
    if mask < 1 or mask >= MAX_CAPACITY then
        return nil, string.format("capacity mask out of range (0x%x)", mask)
    end
    if (mask & (mask + 1)) ~= 0 then
        return nil, string.format("capacity mask is not capacity-1 (0x%x)", mask)
    end
    return ctrl, slots, mask
end

--- Is the definition registry readable on this build?
function R.defs.ready() return (_table_view()) ~= nil end

--- Why not, in one line. nil when the registry IS readable.
function R.defs.why_not()
    local ok, reason = _table_view()
    if ok then return nil end
    return reason or "unknown"
end

--- Every populated registry entry: { {name=, desc=, data=, count=}, ... }.
---
--- `name` comes from the first instance's RTTI, so an entry whose instances
--- have been torn down reports nil rather than guessing.
function R.defs.classes()
    local out = {}
    local ctrl, slots, mask = _table_view()
    if not ctrl then return out end
    for i = 0, mask do
        local c = I.read_u8(ctrl + i)
        if c and c < 0x80 then                       -- full slot
            local slot  = slots + i * SLOT_STRIDE
            local desc  = I.read_u64(slot)
            local data  = I.read_u64(slot + 8)
            local count = I.read_u32(slot + 0x10)
            if desc and count and count > 0 and count <= MAX_INSTANCES
               and R.ptr.plausible(data) then
                out[#out + 1] = {
                    desc  = desc,
                    data  = data,
                    count = count,
                    name  = R.rtti.name(I.read_u64(data)),
                }
            end
        end
    end
    table.sort(out, function(a, b) return (a.name or "") < (b.name or "") end)
    return out
end

--- Live instances of one class. `which` is a class name (exact, or a suffix
--- match so "EnemyDefinition" finds "oCDtEnemyDefinition") or a class-descriptor
--- pointer from R.defs.classes(). Returns a possibly-empty array of pointers,
--- each one already vetted as a live C++ object.
function R.defs.instances(which, limit)
    local out = {}
    for _, cls in ipairs(R.defs.classes()) do
        local hit
        if type(which) == "number" then
            hit = (cls.desc == which)
        elseif type(which) == "string" then
            hit = (cls.name == which)
                  or (cls.name ~= nil and cls.name:sub(-#which) == which)
        end
        if hit then
            local n = math.min(cls.count, limit or cls.count)
            for i = 0, n - 1 do
                local inst = I.read_u64(cls.data + i * 8)
                if R.ptr.has_vtable(inst) then out[#out + 1] = inst end
            end
            if #out > 0 then return out end
        end
    end
    return out
end

--- First live instance of `which`, or nil.
function R.defs.first(which)
    local list = R.defs.instances(which, 1)
    return list[1]
end

--- Log the inventory: one line per class, instance count, first pointer.
function R.defs.dump()
    local classes = R.defs.classes()
    if #classes == 0 then
        R.log("[rsmm.defs] registry unreadable or empty (build mismatch? too early?)")
        return
    end
    local total = 0
    for _, c in ipairs(classes) do
        total = total + c.count
        R.log(string.format("[rsmm.defs]   %-40s x%-5d first=0x%x",
            tostring(c.name), c.count, I.read_u64(c.data) or 0))
    end
    R.log(string.format("[rsmm.defs] %d classes, %d instances", #classes, total))
end

end)()

-- escape hatch ----------------------------------------------------------
--
-- Last-resort access to the raw engine bindings. Not part of the
-- contract: function names, signatures, and presence may change.

R._internal = I

-- The SDK build stamp is printed by the LOADER (loader.cpp), not from here.
-- It was briefly done in Lua via debug.getinfo + io.open, which broke every
-- mod: apply_sandbox() deliberately removes `debug` and `io` from a mod state,
-- so the SDK raised at load and damage-meter never initialised. Anything the
-- SDK needs from the host filesystem has to come through `I.<binding>`.

return R
