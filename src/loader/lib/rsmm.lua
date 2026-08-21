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
            if hit then
                if s.once then expired = expired or {}; expired[#expired + 1] = id end
                local ok, err = pcall(s.cb, ev, name)
                if not ok then
                    R.log("[rsmm.on] handler error on '" .. name .. "': " .. tostring(err))
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

-- entity / combat -------------------------------------------------------
--
-- Read and modify the local hero's health. The hero CHARACTER object (the one
-- carrying HP) is NOT the bus dispatcher and can't be derived from it — the
-- engine bakes the hero into each event subscription as the handler's first
-- arg. So we capture it by hooking two hero-bound handlers read-only (the
-- GAIN_HEALTH handler and the give-item handler) and grabbing param_1 the
-- first time either fires (i.e. the hero heals/regens or picks something up).
-- Health is then applied through the engine's own modify-health routine
-- (Entity_ModifyHealth), so clamping, the UI bar, on-heal/on-damage triggers
-- and analytics all fire exactly as if the game did it.
--
--   R.entity.hp()        -- current HP (float) or nil (hero not captured yet)
--   R.entity.max_hp()    -- max HP or nil
--   R.entity.hp_frac()   -- hp/max in 0..1 or nil
--   R.entity.ready()     -- true once the hero is captured
--   R.combat.heal(20)    -- heal 20
--   R.combat.damage(15)  -- self-damage 15
--   R.combat.set_hp(50)  -- set HP to an absolute value

R.entity = {}
R.combat = {}

local ENTITY_HP_OFF      = 0x15c8        -- f32 current HP on the hero character
local ENTITY_MAXHP_OFF   = 0x15cc        -- f32 max HP
-- Function addresses are resolved at runtime through the pattern DB
-- (I.resolve on the semantic symbol name) so a game patch that shifts code
-- can never leave us hooking/calling a stale VA: an unresolved symbol fails
-- closed instead. Only data addresses (vftable) stay link-time constants.
local FLAGLIST_VFT_VA    = 0x140f01650   -- oCCustomFlagList::vftable (re-derived 2026-07-10)
local ENTITY_IMG_BASE    = 0x140000000

local _hero_char = nil
-- Last hero pointer announced in the log. A capture is worth one line; the
-- same capture re-announced on every poll is not. A 4-player session produced
-- ~500 identical "hero CAPTURED" lines in ninety seconds, which buried every
-- other diagnostic in the file.
local _hero_logged = nil
local function _log_capture(fmt, hero, ...)
    if _hero_logged == hero then return end
    _hero_logged = hero
    R.log(string.format(fmt, hero, ...))
end          -- captured hero character object (HP@+0x15c8)
-- Spawn-init candidate whose HP/mirror fields are not populated yet. The Lua
-- mirror of the native pending slot: stashed by the hero's post-load init hook
-- and promoted by the tick pump the first time it reads plausible.
local _hero_pending = nil
local _hero_capture_armed = false
-- Process-global shared slots (see hook_events.cpp install_hero_capture):
--   0 = hero character pointer (published by native capture)
--   1 = native "authoritative seen" flag (give handler fired)
--   2 = native capture active sentinel (loader owns the capture hooks)
local SHARED_HERO_SLOT = 0
local HERO_AUTH_SLOT = 1
local NATIVE_CAPTURE_SLOT = 2
local HERO_PENDING_SLOT = 3   -- spawn-init candidate whose fields weren't live yet
-- Whether capture is PERMITTED (RSMM_ENABLE_HERO_CAPTURE), as opposed to
-- whether the native path armed. 0 = loader too old to say, 1 = yes, 2 = no.
local HERO_PERMIT_SLOT = 4
local PERMIT_NO = 2
-- Set once when the HP-field scan below has run. Every mod gets its own Lua
-- state and they all poll, so without a process-wide latch the scan would be
-- repeated (and re-logged) five times over.
local HERO_SCAN_SLOT = 5
-- Ring of spawn-init candidates published by the native hook; see the
-- promotion loop in R.entity.hero() for why one slot was not enough.
local HERO_RING_FIRST = 8
local HERO_RING_COUNT = 8

-- ⚠ THE SHARED SLOT MAP IS FULL — there are 16 slots and 15 are spoken for.
--
--   0..4   native: hero ptr / auth / capture-active / pending / permit
--   5      Lua: HP-field scan latch
--   6      Lua: hero rejection-diagnostic budget
--   7      Lua: name-probe latch (the only free slot left)
--   8..15  native: hero candidate RING — POINTERS, written by the loader
--
-- Slots 8..15 hold live hero pointers. Taking one for a Lua latch does not
-- merely collide, it EVICTS a spawn candidate: on 2026-08-16 the name probe
-- claimed slot 9, wrote 1 into it, and `hero CAPTURED` stopped appearing in
-- every subsequent session. Lua reads the ring (below) and must never write
-- it; `lua_shared_set` now refuses that range outright. Adding another latch
-- means growing g_shared, not borrowing a slot.
-- Slot 7 is the last free shared slot (8..15 are the native hero ring).
local LOBBY_REFRESH_SLOT = 7

-- When this state first saw ANY hero candidate, so a capture can report the
-- wait the player actually experienced. The native side reports its own
-- captures, but promotion usually happens HERE (the fields go live long after
-- the stash), and that path printed no timing at all — so the one number the
-- "capture takes ages" question needs was missing from the log.
local _hero_first_seen = nil

local function _note_hero_candidate()
    if not _hero_first_seen and I.now then
        local ok, t = pcall(I.now)
        if ok and type(t) == "number" then _hero_first_seen = t end
    end
end

--- "N.Ns after the first candidate appeared", or "" when unmeasurable.
local function _capture_latency()
    if not I.now then return "" end
    local ok, t = pcall(I.now)
    if not ok or type(t) ~= "number" then return "" end
    -- Prefer the RUN start. Measuring from the first candidate answered the
    -- wrong question: candidates are stashed in the menu, so a player who sat
    -- in the menu for ten minutes and then captured within seconds of pressing
    -- start was reported as a 443.9s capture, which reads as a loader bug and
    -- is not one.
    local started = R.run and R.run.started_at and R.run.started_at()
    if type(started) == "number" then
        return string.format(" (%.1fs after the run started)", t - started)
    end
    if not _hero_first_seen then return "" end
    return string.format(" (%.1fs after the first candidate appeared)",
                         t - _hero_first_seen)
end

-- True when the loader's native hero-capture is installed. When it is, the Lua
-- side must not arm its own per-state capture hooks (they'd collide with the
-- native ones, MH_ERROR_ALREADY_CREATED) — it just reads the shared slot.
-- The flag was never actually a gate. It stopped the NATIVE hooks, and then
-- this fallback installed detours on the SAME handlers the first time any mod
-- touched R.entity — a playtest log showed two `[hook] slot N installed` lines
-- directly beneath "[hero-capture] disabled", while the loader claimed
-- R.combat/R.entity/R.stat/R.xp were unavailable. The flag exists because
-- these detours have correlated with load-time crashes, so "off" has to mean
-- off everywhere, not just in C++.
--
-- Only an EXPLICIT denial refuses. A loader too old to publish the slot leaves
-- it 0, and those builds keep the previous behaviour rather than silently
-- losing capture (rsmm.lua is disk-loaded, so it can be newer than the DLL).
local function _capture_denied()
    if not I.shared_get then return false end
    local ok, v = pcall(I.shared_get, HERO_PERMIT_SLOT)
    return ok and v == PERMIT_NO
end

local function _native_capture_active()
    if not I.shared_get then return false end
    local ok, v = pcall(I.shared_get, NATIVE_CAPTURE_SLOT)
    return ok and v == 1
end

-- A captured pointer is "hero-like" if its max-HP field reads as a sane float
-- AND it carries a valid HUD HP-mirror pointer at +0x1d80. The mirror is the
-- hero discriminator: Entity_ModifyHealth dereferences **(hero+0x1d80) on every
-- heal/damage, so a pointer that lacks a live mirror would crash R.combat.
-- Non-player entities (GAIN_HEALTH fires for enemies too) have no HUD mirror,
-- so requiring it rejects false captures and keeps every captured pointer
-- ModifyHealth-safe. Verified in Ghidra (FUN_140391d30 / FUN_140399a10). All
-- reads are fault-safe (return nil on a bad address).
local function _hero_plausible(e)
    if not e or e == 0 then return false end
    local mx = I.read_f32(e + ENTITY_MAXHP_OFF)
    local cur = I.read_f32(e + ENTITY_HP_OFF)
    -- cur may legitimately EXCEED mx (overheal / shields / HP-boost items), so
    -- only bound it as finite+non-negative, not cur <= mx. mx must be a sane
    -- positive bar size — that's the real garbage-pointer discriminator, and
    -- the floor is 0.5 rather than >0 because the 2026-07-19 misfire's "max"
    -- was the DENORMAL 1.6e-43, which a bare >0 accepts.
    if not (type(mx) == "number" and mx >= 0.5 and mx < 1e6
        and type(cur) == "number" and cur >= 0 and cur < 1e6) then
        return false
    end
    local mirror = I.read_u64(e + ENTITY_HUDMIRROR_OFF)
    if type(mirror) ~= "number" or mirror == 0 then return false end
    -- mirror is dereferenced as *(mirror) (the HUD-rendered HP) by the engine;
    -- bound the value like cur so a random-but-readable pointer can't pass.
    local mv = I.read_f32(mirror)
    return type(mv) == "number" and mv >= 0 and mv < 1e6
end

-- Is this candidate THIS machine's player?
--
-- The HUD-mirror gate in _hero_plausible is a local-only test by RE (only the
-- local player owns a HUD HP mirror), and that is the whole defence against
-- publishing an ALLY as the hero. It is not much of a defence to rest on alone:
-- the spawn-init hook that feeds the candidate ring fires once per HERO, not
-- once per machine — the 2026-08-18 four-player session stashed three candidates
-- inside 5 ms and four more at the next chapter — so the ring is full of remote
-- allies and the mirror is the only thing between them and R.combat writing to
-- somebody else's HP.
--
-- The engine's own answer is the byte at +0x1d88. It is used to PREFER a
-- candidate, never to refuse one: a hero object mid-load reads 0 there, and
-- refusing on that would trade an ally-capture risk for never capturing at all.
--
-- ⚠ THESE LIVE ON R.entity, NOT IN LOCALS. rsmm.lua's module chunk is one Lua
-- function and Lua caps a function at 200 locals; this section is already at the
-- limit, so four more `local`s here stopped the whole SDK from compiling (every
-- mod dead — the same wall the DMG table exists to work around). Table fields
-- cost nothing, and none of this is on a per-hit path.
function R.entity._is_local(p)
    if not p or p == 0 then return false end
    return I.read_u8(p + ENTITY_ISLOCAL_OFF) == 1
end

-- CHAPTER INVALIDATION -----------------------------------------------------
--
-- The engine rebuilds every hero controller when a chapter loads (R.damage's
-- epoch/rebind machinery exists for the same reason). Nothing retired the
-- published capture, so after a chapter change slot 0 still held the PREVIOUS
-- chapter's hero — freed memory, which keeps reading plausible for a long time
-- (see the hero-switch note in R.entity.hero) — and every R.combat/R.stat/R.xp
-- write went into a dead object with nothing in the log to say so. The
-- 2026-08-18 session is exactly that: captured @71611030 at 17:24:48, two
-- chapter epochs later that pointer was still the published hero and no second
-- capture line ever appeared.
--
-- The native candidate RING (slots 8..15) has the same staleness and cannot be
-- cleared the same way: `lua_shared_set` refuses that range outright (a mod that
-- wrote a latch into slot 9 broke capture in every later session), and the
-- native stash DEDUPES, so a retired pointer is never overwritten either. So the
-- ring is retired on the Lua side: each entry is remembered with a FINGERPRINT
-- of the fields capture reads, and a retired entry is skipped only while that
-- fingerprint still matches. If the allocator hands the same address to the next
-- chapter's hero the fingerprint moves and the candidate is adopted normally, so
-- this cannot make a live hero permanently invisible.
R.entity._stale = {}

function R.entity._fingerprint(p)
    if not p or p == 0 then return "" end
    return table.concat({
        tostring(I.read_u64(p + ENTITY_HUDMIRROR_OFF)),
        tostring(I.read_f32(p + ENTITY_MAXHP_OFF)),
        tostring(I.read_f32(p + ENTITY_HP_OFF)),
        tostring(I.read_u8(p + ENTITY_ISLOCAL_OFF)),
    }, "/")
end

--- Was `p` retired at a chapter boundary, and is it still the same object?
function R.entity._retired(p)
    local fp = R.entity._stale[p]
    if fp == nil then return false end
    if R.entity._fingerprint(p) ~= fp then
        R.entity._stale[p] = nil        -- a new object at a recycled address
        return false
    end
    return true
end

--- Retire the captured hero and every pending candidate.
---
--- Called on the chapter teardown event, where the controller the capture points
--- at is about to be freed. Deliberately NOT called on MAP_GENERATION_DONE: the
--- next chapter's hero can be stashed and published before that event lands, and
--- retiring then would throw away the capture it just made.
---
--- Public because a mod that knows the hero is gone (a hero switch it drove
--- itself) can say so rather than waiting for a rejection to be noticed.
function R.entity.invalidate_capture(why)
    if not (I.shared_get and I.shared_set) then return false end
    local retired = 0
    local function retire(slot)
        local ok, v = pcall(I.shared_get, slot)
        if ok and type(v) == "number" and v ~= 0 then
            R.entity._stale[v] = R.entity._fingerprint(v)
            retired = retired + 1
        end
    end
    retire(SHARED_HERO_SLOT)
    retire(HERO_PENDING_SLOT)
    -- The ring is read-only from Lua (see above), so its entries are retired by
    -- fingerprint instead of by being zeroed.
    for i = 0, HERO_RING_COUNT - 1 do retire(HERO_RING_FIRST + i) end
    pcall(I.shared_set, SHARED_HERO_SLOT, 0)
    pcall(I.shared_set, HERO_AUTH_SLOT, 0)
    pcall(I.shared_set, HERO_PENDING_SLOT, 0)
    _hero_char = nil
    _hero_pending = nil
    if retired > 0 then
        R.log(("[rsmm.entity] hero capture retired (%s) — %d candidate(s) belong "
               .. "to the chapter being torn down; the next spawn re-captures")
              :format(tostring(why or "chapter change"), retired))
    end
    return true
end

-- Chapter teardown only; see R.entity.invalidate_capture for why
-- MAP_GENERATION_DONE is not subscribed.
R.on("gameplay:GAME_END_NEXT_CHAPTER",
     function() R.entity.invalidate_capture("GAME_END_NEXT_CHAPTER") end)
R.on("run:end", function() R.entity.invalidate_capture("run:end") end)

-- NOTE: ev.entity (= dispatcher - 0x4d8 from the gameplay bus) is NOT the hero
-- HP-carrier. Empirically _hero_plausible(ev.entity) fails: the dispatch entity
-- (dispatcher owner) and the HP-carrier are separate sub-objects — the hero is
-- bound into each subscription as functor context, not reachable from the event
-- by a fixed offset. So capture stays hook-based (param_1 of the hero handlers),
-- which needs one hero action (heal/lifesteal/pickup) but reads the right object.

-- Install the read-only capture hooks once. Both handlers take pointer args
-- only (no float), so hooking them is safe; the callback returns nil to replay
-- the original unchanged. Called lazily so R.hook is defined by first use.
local function _arm_hero_capture()
    if _hero_capture_armed then return end
    if _capture_denied() then
        _hero_capture_armed = true   -- refuse once, quietly thereafter
        R.log("[rsmm.entity] hero capture is disabled "
              .. "(RSMM_ENABLE_HERO_CAPTURE off) — not installing the capture "
              .. "hooks. R.combat/R.entity/R.stat/R.xp stay unavailable.")
        return
    end
    local base = I.module_base()
    if not base or base == 0 or not R.hook then return end
    _hero_capture_armed = true
    -- The GAIN_HEALTH handler fires for ANY entity that heals (incl. enemies),
    -- so its capture is only tentative (taken if nothing better seen yet). The
    -- give-item handler is hero-only (only the local player picks up MOs), so it
    -- is authoritative and overwrites any tentative capture.
    local function capture(p1, authoritative)
        if not _hero_plausible(p1) then return end
        if _hero_char == p1 then return end
        if _hero_char ~= nil and not authoritative then return end
        _hero_char = p1
        -- Publish to the process-global slot so other mods' Lua states (which
        -- lose the MinHook install with ALREADY_CREATED) still see this hero.
        if I.shared_set then pcall(I.shared_set, SHARED_HERO_SLOT, p1) end
        R.log(string.format("[rsmm.entity] hero captured @0x%x (hp %.0f/%.0f)%s",
            p1, I.read_f32(p1 + ENTITY_HP_OFF), I.read_f32(p1 + ENTITY_MAXHP_OFF),
            authoritative and " [authoritative]" or " [tentative]"))
    end
    -- Best-effort: a failed capture hook must NEVER abort the mod that
    -- required rsmm. Handler addresses come from the pattern DB (nil when the
    -- symbol is unverified for this game build — fail closed, never hook a
    -- stale VA), and R.hook can still raise on install failure, so guard each
    -- with pcall — capture just stays unavailable; everything else still runs.
    local gain_va = I.resolve and I.resolve("Entity_GainHealthHandler")
    local give_va = I.resolve and I.resolve("Entity_GiveHandler")
    -- Both handlers take pointer-only args (ptr,ptr,ptr). Either one captures
    -- the hero (the mirror plausibility check inside capture() rejects any
    -- non-hero entity that also fires them), so capture survives as long as ONE
    -- resolves; only warn when BOTH are unresolved for this build.
    -- ARG SEMANTICS differ: the gain-health handler's param_1 is the hero
    -- entity, but the give handler's param_1 is the hero's VALUE CONTEXT
    -- (*(hero+0x2f8)) and its param_2 is the hero entity (decompile-verified
    -- 2026-07-15; the ctx never passes _hero_plausible, which is why the
    -- authoritative capture silently never fired).
    -- R.hook returns (nil, "already-hooked") when another mod's lua_State got
    -- there first. That is the NORMAL case with more than one mod installed and
    -- the hook is live — the hero still arrives through the shared slot — so it
    -- must not be counted as a failure. Reporting it as one is what produced
    -- "both handlers unresolved for this game build" in a log where the
    -- handlers had resolved perfectly well and another mod owned the hook.
    local function arm(va, sig, fn)
        if not va then return false end
        local ok, slot, why = pcall(R.hook, va, sig, fn)
        if not ok then return false end
        if slot == nil and why == "already-hooked" then return true end
        return slot ~= nil
    end
    -- SPAWN-INIT source. This is what makes capture instant instead of
    -- "whenever you next heal or pick something up".
    --
    -- The other two handlers only fire on a hero ACTION, so with the native
    -- capture off a run could go a minute or more before anything was
    -- captured — measured at 73 seconds in one playtest, and the result was
    -- only [tentative] because it came from the heal path. This routine is the
    -- hero's own post-load init: it runs once, at spawn, before the hero acts,
    -- and it is hero-only (enemies have no HUD mirror), so its capture is
    -- authoritative.
    --
    -- Its param_1 is the HP-carrier, but the fields are NOT live yet — this
    -- function is what populates the HUD mirror the plausibility gate checks.
    -- So stash the identity and let the tick pump promote it the moment it
    -- reads plausible, exactly as the native path does with its pending slot.
    local sub_va = I.resolve and I.resolve("NamedEvent_HeroSubscribeAll")
    local ok0 = arm(sub_va, "vp", function(p1)
        if p1 and p1 ~= 0 then _hero_pending = p1 end
        return nil
    end)
    local ok1 = arm(gain_va, "vppp", function(p1) capture(p1, false); return nil end)
    local ok2 = arm(give_va, "vppp", function(_, p2) capture(p2, true); return nil end)
    ok1 = ok1 or ok0
    if not (ok1 or ok2) then
        local why = (gain_va or give_va)
            and "could not be hooked (another mod may own them, or the install failed)"
            or "unresolved for this game build"
        R.log("[rsmm.entity] hero-capture handlers " .. why
            .. "; R.combat/R.entity/R.stat/R.xp disabled this run, "
            .. "other mods unaffected")
    end
end

--- One-shot: find where the HP pair really lives on a rejected hero.
--
-- The 2026-08-13 playtest narrowed the failure precisely. The pending pointer
-- IS the hero (the spawn-init routine is hero-only), the HUD-mirror pointer at
-- +0x1d80 reads as a valid heap address — so the object and its size are what
-- we expect — and yet `hp`/`max` at +0x15c8/+0x15cc read 0.0 for 18+ seconds
-- of live play. Readable, plausible object, zero fields: that is a MOVED
-- FIELD, not a bad pointer, and no amount of waiting fixes it.
--
-- So sweep the object for the pair instead of hardcoding a guess: adjacent
-- f32s where the second is a sane bar size and the first sits inside it. The
-- hero's real HP pair must appear; anything else that matches is noise the
-- offsets and values let us reject by eye. All reads are page-guarded (bad
-- address -> nil, never a fault), and the whole thing runs once per PROCESS
-- via a shared latch, not once per mod.
-- Scan a given pointer at these rejection counts, not on the first one. The
-- fields fill DURING the load sequence, and the 19:56 log shows two different
-- pending heroes six seconds apart — the menu character, then the run's. A
-- true one-shot would have measured the wrong object while it was still blank
-- and latched. Ticks are ~500ms, so these are roughly 5s and 20s in.
-- One table, not four locals: the main chunk is at Lua's 200-local ceiling, so
-- every new top-level `local` here costs a "too many local variables" compile
-- failure of the whole SDK.
local HERO_SCAN = {
    -- Rejection counts that trigger a scan. Ticks are ~500ms, so 10/40 are
    -- roughly 5s and 20s after the candidate was stashed -- and session 914f
    -- (2026-08-18) showed that is entirely inside the LOAD: both scans fired
    -- before the hero existed in the map (the second one 5s after
    -- MAP_GENERATION_DONE), found nothing, and no scan ever ran while the hero
    -- was alive and taking damage. 200 and 800 are ~100s and ~400s in, which is
    -- mid-fight, and the process-wide budget of MAX still caps the total.
    AT   = { [10] = true, [40] = true, [200] = true, [800] = true },
    MAX  = 6,                        -- total scans per process, all mods
    LO   = 0x1000, HI = 0x2400,
    seen = {},                       -- pointer -> rejections observed here
}

--- True while the main menu is up (best-effort; false when unknowable).
--
-- There is no run hero on the menu, so a candidate the spawn-init hook stashed
-- there is the menu's preview character and its HP fields are blank BY DESIGN.
-- Polling it is harmless, but LOGGING it is not: the 2026-08-16 session spent
-- its entire process-wide budget -- all six field scans and 40+ rejection lines
-- -- sitting in menus, so the one measurement worth having ("still zero during
-- LIVE play => the offsets moved") could never be taken, and every scan
-- correctly reported "no candidate pair found" about an object that had none
-- yet. Rejections are only counted, and only printed, outside the menu.
--
-- The binding is IO-hook derived and answers false whenever it cannot tell
-- (loader still booting, IO hook off), so this degrades to the previous
-- always-log behaviour instead of going silent.
local function _in_main_menu()
    if not I.is_in_main_menu then return false end
    local ok, v = pcall(I.is_in_main_menu)
    return (ok and v) or false
end

--- Is it worth spending diagnostics on a hero candidate right now?
---
--- There is no hero to find in the main menu, so every rejection line and
--- field scan emitted there is noise that also burns a process-wide budget:
--- session 6c4f sat in the menu for eleven minutes, spent all six scans on a
--- blank object, and then reported the capture as taking 443.9s — a number
--- measured from a candidate that appeared while nobody was playing.
---
--- The run boundary is the right signal. `is_in_main_menu` is NOT: it is
--- derived from MainMenu asset READS, so it goes false about five seconds
--- after the menu finishes loading and stays false while you sit in it, which
--- is exactly the window this is meant to suppress.
---
--- Which is what session ba4f (2026-08-18) hit: the whole process sat in the
--- menu and the lobby looking for a team, no run boundary had EVER fired, so
--- the fallback ran — and the fallback answered "in play" five seconds in. The
--- entire process-wide budget (all six field scans, 40+ rejection lines) was
--- spent on the character-select preview hero, whose HP fields are blank by
--- design, before a run ever started. Same outcome as session 6c4f, re-entered
--- through the fallback the 6c4f fix installed.
---
--- Three sources now, strongest first:
---   1. the analytics run boundary (run_start / run_end) — exact, but it rides
---      the firehose and a session can legitimately not have it;
---   2. the gameplay bus (GAME_START / MAP_GENERATION_DONE vs GAME_END_*) —
---      the same question asked of a different hook, so a build missing one
---      usually still has the other. NOT routed into run:start/run:end, which
---      mods reset counters on: MAP_GENERATION_DONE fires per CHAPTER;
---   3. nothing at all — then SUPPRESS. Diagnostics whose budget is spent
---      before the measurement can be taken are worse than no diagnostics, and
---      the suppression says so once, in the log, with the reason.
function HERO_SCAN.in_play()
    local rr = R.run
    if rr and rr.signalled and rr.signalled() then
        return (rr.active and rr.active()) and true or false
    end
    if rr and rr._play_signalled then return rr._play_active == true end
    if not HERO_SCAN.quiet_logged then
        HERO_SCAN.quiet_logged = true
        R.log("[rsmm.entity] hero diagnostics suppressed: no run signal on this "
              .. "build (neither the analytics run boundary nor the gameplay "
              .. "bus has fired). They arm themselves the moment a run starts.")
    end
    return false
end

-- Internals, for the spec: `in_play` decides whether a whole class of
-- diagnostics runs, so its three states are worth testing directly.
R.entity._scan = HERO_SCAN

local function _scan_hp_fields(p)
    if not (I.shared_get and I.shared_set) then return end
    local n = (HERO_SCAN.seen[p] or 0) + 1
    HERO_SCAN.seen[p] = n
    if not HERO_SCAN.AT[n] then return end
    -- Process-wide budget: every mod has its own Lua state and all of them
    -- poll, so the cap has to live in the shared slot, not in this state.
    local oks, used = pcall(I.shared_get, HERO_SCAN_SLOT)
    used = (oks and type(used) == "number") and used or 0
    if used >= HERO_SCAN.MAX then return end
    pcall(I.shared_set, HERO_SCAN_SLOT, used + 1)

    local hits = {}
    for off = HERO_SCAN.LO, HERO_SCAN.HI, 4 do
        local cur = I.read_f32(p + off)
        local mx = I.read_f32(p + off + 4)
        if type(cur) == "number" and type(mx) == "number"
            and mx >= 20.0 and mx < 5000.0 and cur > 0.0 and cur <= mx then
            hits[#hits + 1] = string.format("+0x%x %.1f/%.1f", off, cur, mx)
            if #hits >= 12 then break end
        end
    end
    R.log(string.format(
        "[rsmm.entity] HP-FIELD SCAN #%d on 0x%x after %d rejections "
        .. "(expected +0x%x): %s",
        used + 1, p, n, ENTITY_HP_OFF,
        #hits > 0 and table.concat(hits, "  ") or "no candidate pair found"))
end

-- The captured local hero character pointer, or nil if not seen yet. The
-- loader's native capture publishes it to the shared slot at hero spawn (it
-- hooks the hero's spawn/post-load init, NamedEvent_HeroSubscribeAll, whose
-- param_1 is the HP-carrier) — so it's available almost immediately, no longer
-- gated on the hero's first heal/pickup. Read fresh every call so a hero-switch
-- (which clears the slot) is picked up automatically.
-- Rejection diagnostics are capped PER MOD STATE, and every installed mod has
-- its own state — so a 6-line cap became 6 x N identical lines (37 in one
-- measured session, all the same pointer and the same zero fields). The reason
-- to print them at all is "a rejection that persists into live play means the
-- offsets moved", which one state answers as well as seven. `HERO_DIAG_SLOT`
-- is a cross-state claim: the first state to log takes it, the rest stay quiet.
local _hero_diag_n = 0
local HERO_DIAG_SLOT = 6

--- True at most `limit` times across ALL mod states, not per state.
local function _diag_budget(limit)
    if _hero_diag_n >= limit then return false end   -- this state has had its say
    local ok, n = pcall(I.shared_get, HERO_DIAG_SLOT)
    n = (ok and type(n) == "number") and n or 0
    if n >= limit then return false end
    if I.shared_set then pcall(I.shared_set, HERO_DIAG_SLOT, n + 1) end
    _hero_diag_n = _hero_diag_n + 1
    return true
end
function R.entity.hero()
    if I.shared_get then
        local ok, h = pcall(I.shared_get, SHARED_HERO_SLOT)
        h = (ok and type(h) == "number") and h or 0

        -- HERO SWITCH: a spawn-init candidate that is BOTH different from the
        -- published hero and already plausible means the hero changed, and it
        -- has to win over the published one.
        --
        -- Without this the published slot shadows it completely: the check
        -- below returns early while `h` still reads plausible, so the pending
        -- branch is never reached and the new hero is invisible until the give
        -- path happens to notice its dispatcher changed. Measured 2026-08-13
        -- switching characters mid-run — the new hero sat pending for 95
        -- seconds with not one rejection logged, because the code never looked
        -- at it. (Freed memory keeps reading plausible for a long time, so
        -- "the old pointer still validates" is not evidence it is still the
        -- hero.) The first capture of a run is NOT this case: there the slot
        -- is empty and the wait is the hero's own fields going live.
        local okp, pend = pcall(I.shared_get, HERO_PENDING_SLOT)
        if okp and type(pend) == "number" and pend ~= 0 and pend ~= h
            and not R.entity._retired(pend) and _hero_plausible(pend) then
            if I.shared_set then
                pcall(I.shared_set, SHARED_HERO_SLOT, pend)
                pcall(I.shared_set, HERO_AUTH_SLOT, 1)
                pcall(I.shared_set, HERO_PENDING_SLOT, 0)
            end
            _log_capture("[rsmm.entity] hero CAPTURED 0x%x (was 0x%x)%s", pend, h,
                         _capture_latency())
            return pend
        end

        if h ~= 0 then
            if _hero_plausible(h) then return h end
            -- DIAG (first few only): the native capture published a pointer the
            -- Lua plausibility gate now rejects — log the raw reads so a
            -- playtest log shows WHY (stale/freed entity? moved offsets?).
            if HERO_SCAN.in_play() and _diag_budget(6) then
                R.log(string.format(
                    "[rsmm.entity] slot hero 0x%x REJECTED: hp=%s max=%s mirror=%s",
                    h, tostring(I.read_f32(h + ENTITY_HP_OFF)),
                    tostring(I.read_f32(h + ENTITY_MAXHP_OFF)),
                    tostring(I.read_u64(h + ENTITY_HUDMIRROR_OFF))))
            end
        end
        -- Pending spawn candidate: the native spawn-init hook stashes the hero
        -- identity BEFORE its HP/mirror fields are populated (they fill during
        -- the load sequence). Promote it to the real slot the first time it
        -- reads plausible — instant capture with no combat prerequisite.
        -- Every spawn-init candidate, not just the latest. The native side
        -- keeps them in a ring (slots 8..15) because a single slot meant each
        -- spawn-init discarded the previous candidate: measured 2026-08-14,
        -- five stashes collapsed to one whose HP fields never went live, so
        -- the pending path was dead for the entire run and capture fell back
        -- to waiting ~94s for a gain-health fire. They are all hero-identity
        -- (the routine is hero-only); they simply go live at different times,
        -- so promote whichever validates first.
        --
        -- TWO passes, local players first. The ring holds one candidate per HERO
        -- in a co-op run, not one per machine, so "first plausible entry wins"
        -- means "whichever ally the allocator happened to place in a lower ring
        -- slot wins" — and R.combat would then heal, damage and buff somebody
        -- else's character. The engine's is-local byte decides it when it is
        -- readable; when nothing claims to be local the old behaviour stands,
        -- so a build where that byte moved still captures.
        local fallback, fallback_slot = nil, nil
        for i = 0, HERO_RING_COUNT - 1 do
            local okr, cand = pcall(I.shared_get, HERO_RING_FIRST + i)
            if okr and type(cand) == "number" and cand ~= 0 then
                _note_hero_candidate()
            end
            if okr and type(cand) == "number" and cand ~= 0 and cand ~= h
                and not R.entity._retired(cand) and _hero_plausible(cand) then
                if R.entity._is_local(cand) then
                    fallback, fallback_slot = cand, i
                    break
                elseif not fallback then
                    fallback, fallback_slot = cand, i
                end
            end
        end
        if fallback then
            if I.shared_set then
                pcall(I.shared_set, SHARED_HERO_SLOT, fallback)
                pcall(I.shared_set, HERO_AUTH_SLOT, 1)
                pcall(I.shared_set, HERO_PENDING_SLOT, 0)
            end
            _log_capture("[rsmm.entity] hero CAPTURED 0x%x from ring slot %d "
                         .. "(local_byte=%s)%s",
                         fallback, fallback_slot,
                         tostring(I.read_u8(fallback + ENTITY_ISLOCAL_OFF)),
                         _capture_latency())
            return fallback
        end

        local okp, p = pcall(I.shared_get, HERO_PENDING_SLOT)
        if okp and type(p) == "number" and p ~= 0 and not R.entity._retired(p) then
            if _hero_plausible(p) then
                if I.shared_set then
                    pcall(I.shared_set, SHARED_HERO_SLOT, p)
                    pcall(I.shared_set, HERO_AUTH_SLOT, 1)
                    pcall(I.shared_set, HERO_PENDING_SLOT, 0)
                end
                _log_capture("[rsmm.entity] hero CAPTURED 0x%x from the pending slot%s",
                             p, _capture_latency())
                return p
            end
            -- DIAG (first few only). A rejection here is NORMAL for a while:
            -- the candidate is authoritative by construction (the spawn-init
            -- routine is hero-only) but its HP fields do not populate until
            -- the run actually starts, so every tick spent in character select
            -- logs one. Measured 2026-08-13: ~58s from first stash to
            -- promotion on a fresh run, with the field sweep below finding no
            -- HP pair anywhere on the object in the meantime — the fields are
            -- genuinely blank, not moved.
            --
            -- What it is still worth printing for: a rejection that persists
            -- INTO live play means the offsets really did move, and rejecting
            -- silently is how that failed invisibly before (every downstream
            -- API no-ops with nothing in the log to say why).
            --
            -- Both the line and the field sweep are MENU-GATED: a rejection in
            -- the menu carries no information (see `_in_main_menu`), and
            -- spending the shared scan budget there is what made the 2026-08-16
            -- log six scans of a blank preview character.
            if HERO_SCAN.in_play() then
                if _diag_budget(6) then
                    local mirror = I.read_u64(p + ENTITY_HUDMIRROR_OFF)
                    R.log(string.format(
                        "[rsmm.entity] pending hero 0x%x REJECTED: hp=%s max=%s "
                        .. "mirror=%s mirror[0]=%s",
                        p, tostring(I.read_f32(p + ENTITY_HP_OFF)),
                        tostring(I.read_f32(p + ENTITY_MAXHP_OFF)),
                        tostring(mirror),
                        tostring(mirror and mirror ~= 0 and I.read_f32(mirror) or nil)))
                end
                _scan_hp_fields(p)
            end
        end
    end
    -- Legacy fallback: an older loader without native capture, or the native
    -- capture switched off. Arm the per-state Lua hooks (safe only when native
    -- capture is NOT present — otherwise it would collide on the same
    -- addresses).
    if not _native_capture_active() then
        if not _hero_char then _arm_hero_capture() end
        -- Promote the spawn-init candidate as soon as its fields go live. The
        -- tick pump calls through here every 500ms, so this lands within one
        -- tick of the hero becoming readable rather than waiting for the first
        -- heal or pickup.
        if not _hero_char and _hero_pending and _hero_plausible(_hero_pending) then
            _hero_char = _hero_pending
            _hero_pending = nil
            if I.shared_set then pcall(I.shared_set, SHARED_HERO_SLOT, _hero_char) end
            R.log(string.format(
                "[rsmm.entity] hero captured @0x%x (hp %.0f/%.0f) [spawn-init]",
                _hero_char, I.read_f32(_hero_char + ENTITY_HP_OFF),
                I.read_f32(_hero_char + ENTITY_MAXHP_OFF)))
        end
        return _hero_char
    end
    return nil
end

-- True once the hero has been captured (hp/max/heal/damage will work).
function R.entity.ready() return R.entity.hero() ~= nil end

--- Is hero capture PERMITTED this session (RSMM_ENABLE_HERO_CAPTURE)?
--
-- Distinct from R.entity.ready(), which asks whether the hero has been
-- captured YET. A mod needs both to give useful advice: "not captured" during
-- loading or a menu is normal and resolves itself, while "not permitted" needs
-- the player to change a setting. A playtest with the flag correctly ON still
-- told the user to go and enable it, because the mods had no way to tell the
-- two apart — capture legitimately took ~3 minutes there, since the hero's HUD
-- mirror is not populated until the run is actually under way.
--
-- False ONLY on an explicit refusal; a loader too old to publish the answer
-- reports true, matching what it will actually do.
function R.entity.capture_enabled() return not _capture_denied() end

function R.entity.hp()
    local e = R.entity.hero(); if not e then return nil end
    return I.read_f32(e + ENTITY_HP_OFF)
end

function R.entity.max_hp()
    local e = R.entity.hero(); if not e then return nil end
    return I.read_f32(e + ENTITY_MAXHP_OFF)
end

function R.entity.hp_frac()
    local cur, mx = R.entity.hp(), R.entity.max_hp()
    if not cur or not mx or mx <= 0 then return nil end
    return cur / mx
end

-- Apply a raw health delta (delta>0 heals, delta<0 damages). Returns true on
-- dispatch, false if the hero isn't captured yet, the module base is
-- unavailable, or health reads implausible (guards against a bad pointer).
local function _modify_health(delta)
    local e = R.entity.hero()
    if not e then
        R.log("[rsmm.combat] no hero yet — wait until the hero heals/regens or "
            .. "picks something up once (R.entity.ready())")
        return false
    end
    if not _hero_plausible(e) then
        R.log("[rsmm.combat] hero health reads implausible — refusing modify")
        return false
    end
    if not _va_ok("R.combat") then return false end
    local base = I.module_base()
    if not base or base == 0 then return false end
    -- empty oCCustomFlagList ctx { vftable, list=0, count=0 } in scratch
    local ctx = I.scratch(0x20)
    I.poke(ctx + 0x00, base + (FLAGLIST_VFT_VA - ENTITY_IMG_BASE), 8)
    I.poke(ctx + 0x08, 0, 8)
    I.poke(ctx + 0x10, 0, 8)
    local fn = I.resolve and I.resolve("Entity_ModifyHealth")
    if not fn then
        R.log("[rsmm.combat] Entity_ModifyHealth unresolved for this game build "
            .. "— refusing modify (regenerate function_patterns.json)")
        return false
    end
    R.engine.call_raw(fn, "vpfp", e, delta + 0.0, ctx)
    return true
end

function R.combat.heal(amount)   return _modify_health(math.abs(amount or 0)) end
function R.combat.damage(amount) return _modify_health(-math.abs(amount or 0)) end

-- Set HP to an absolute value by applying the difference from current.
function R.combat.set_hp(value)
    local cur = R.entity.hp()
    if not cur then return false end
    return _modify_health((value or 0) - cur)
end

-- Wire the forward-declared invalidator now that _hero_char + the shared slot
-- exist. On hero switch / new run the captured HP-carrier is stale; drop it and
-- clear the process-global slot so the next heal/pickup re-captures cleanly.
_hero_capture_is_live = function()
    if not I.shared_get then return false end
    local ok, h = pcall(I.shared_get, SHARED_HERO_SLOT)
    return ok and type(h) == "number" and h ~= 0 and _hero_plausible(h)
end

_invalidate_hero_capture = function()
    _hero_char = nil
    if I.shared_set then
        pcall(I.shared_set, SHARED_HERO_SLOT, 0)  -- drop stale hero pointer
        pcall(I.shared_set, HERO_AUTH_SLOT, 0)    -- let native re-capture new hero
    end
end

-- entity values (generic CRC-keyed run/stat store) ----------------------
--
-- Each hero carries a generic keyed value store on its value context. The
-- context is a POINTER field: ctx = *(hero+0x2f8), and the store hangs off it
-- at *(ctx+0x4c8). The engine's own reader (FUN_140399d00, the damage-taken
-- handler) loads the pointer first — `ctx = *(hero+0x2f8)` — then calls
-- EntityValue_Get(ctx, out, crcKey). Passing hero+0x2f8 (the field's ADDRESS)
-- instead makes EntityValue_Get read *(hero+0x7c0) as the store — a float
-- field, not a pointer — and EntityValue_Lookup then faults dereferencing it
-- (the 2026-07-15 in-run crash: store=0xbf800000, i.e. -1.0f, read at +0xc8).
-- EntityValue_Get reads one key into a ~0x20-byte oCEntityValueUnion: type tag
-- @+0x8 (4 = inline f32), value @+0x10. A missing key yields value 0 (safe —
-- never faults). We only read INLINE numeric values (every modifier/difficulty
-- key is numeric); a non-inline (string/vector) key returns nil rather than
-- deref an unknown-typed pointer, so no union destructor is needed.
-- See docs/_re/kinds/entity-values.md and docs/_re/kinds/stats.md.
local ENTITY_VALCTX_OFF = 0x2f8   -- hero -> POINTER to entity value context
local EV_STORE_OFF      = 0x4c8   -- ctx -> POINTER to value store
local EV_TAG_OFF        = 0x08    -- oCEntityValueUnion type tag
local EV_VAL_OFF        = 0x10    -- inline f32 when tag == EV_TAG_INLINE
local EV_TAG_INLINE     = 4

-- Resolve the hero's value CONTEXT pointer, fail-closed. Validates the whole
-- chain the engine will dereference unguarded inside EntityValue_Get /
-- EntityValue_Lookup before we hand it a pointer:
--   ctx   = *(hero+0x2f8)  must be a plausible, readable pointer
--   store = *(ctx+0x4c8)   may be 0 (engine handles it) — but if non-zero it
--                          must be plausible AND its hot fields readable:
--                          count u32 @store+0xc8 (read unconditionally), the
--                          override array ptr @store+0xc0 (read when count>0)
--                          and the base hashmap ptr @store+0x80 (deref'd
--                          unconditionally on a cache miss).
-- Every probe is page-guarded (nil on unmapped), so validation cannot fault.
-- Returns ctx, or nil if any link is implausible.
local function _ev_ctx(hero)
    local ctx = I.read_u64(hero + ENTITY_VALCTX_OFF)
    if not ctx or not _ptr_plausible(ctx) then return nil end
    local store = I.read_u64(ctx + EV_STORE_OFF)
    if store == nil then return nil end                     -- ctx page unreadable
    if store ~= 0 then
        if not _ptr_plausible(store) then return nil end
        local count = I.read_u32(store + 0xc8)
        if count == nil or count > 0x10000 then return nil end
        if count > 0 then
            local data = I.read_u64(store + 0xc0)
            if not data or not _ptr_plausible(data) then return nil end
        end
        local hmap = I.read_u64(store + 0x80)
        if not hmap or not _ptr_plausible(hmap) then return nil end
    end
    return ctx
end

-- Read one entity-value by raw CRC key from the current hero's store.
-- Returns a Lua number (inline f32) or nil (no hero / missing / non-inline).
function R.entity.value(key)
    assert(type(key) == "number", "R.entity.value: key must be a number (CRC id)")
    local e = R.entity.hero(); if not e then return nil end
    local ctx = _ev_ctx(e); if not ctx then return nil end
    local out = I.scratch(0x20)               -- zeroed; tag starts at 0
    local ok = pcall(R.engine.call, "EntityValue_Get", ctx, out, key)
    if not ok then return nil end
    if I.read_u32(out + EV_TAG_OFF) ~= EV_TAG_INLINE then return nil end
    return I.read_f32(out + EV_VAL_OFF)
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

-- stats (generic keyed value store — read/grant any per-hero stat) -------
--
-- Beyond HP (R.combat) and XP (R.xp), most hero stats — max health, attack
-- power, crit chance/damage, move speed, cooldown reduction, life steal,
-- dream shards, xp multipliers — live in the engine's generic CRC-keyed
-- entity-value store (the same store R.entity.value / R.modifier read). The
-- keys are decompile-verified from EntityValueRegistry_RegisterAll; full
-- catalog + provenance in docs/_re/kinds/stats.md.
--
--   R.stat.get("attack_power")     -- current value (number) or nil
--   R.stat.names()                 -- known stat names (sorted)
--   R.stat.enable_writes()         -- opt in to the EXPERIMENTAL write path
--   R.stat.set("move_speed", 1.5)  -- set a stat (see caveats)
--   R.stat.add("attack_power", 10) -- current + delta
--
-- READS are always safe. WRITES are EXPERIMENTAL + engine-mutating: run them
-- on the MAIN thread (from a gameplay-event handler or R.schedule.next_main —
-- see [[loader-thread-model]]) and opt in with R.stat.enable_writes() first.
-- DURABILITY: a write lands in the store's override cache, which the engine
-- rebuilds from base+modifiers on the next stat recompute (item pickup, level
-- up, ...), so a set() is not necessarily permanent. HP has its own committed
-- path (R.combat); prefer it for health. Pending in-game verification.
R.stat = {}

-- name -> { key = <crc id>, kind = "f32"|"int" }. Decompile-verified 2026-07-13
-- (agent RE batch; see docs/_re/kinds/stats.md for the full ~40-key table).
R.stat.keys = {
    max_health         = { key = 0x188671a6, kind = "f32" },  -- base "Vitality"
    max_health_pct     = { key = 0x15c9296d, kind = "f32" },  -- default 1.0
    attack_power       = { key = 0x15a486c4, kind = "f32" },
    crit_chance        = { key = 0x15c7d482, kind = "f32" },
    crit_damage        = { key = 0x15c82d13, kind = "f32" },
    move_speed         = { key = 0x044dadde, kind = "f32" },  -- "Move Speed Ratio"
    cooldown_reduction = { key = 0x15b45d80, kind = "f32" },
    life_steal         = { key = 0x15c028c2, kind = "f32" },
    life_on_hit        = { key = 0x1894f1a2, kind = "f32" },
    dream_shards       = { key = 0x171c27b5, kind = "int" },  -- currency count
    xp_multiplier      = { key = 0x187afd1d, kind = "f32" },  -- "Global Xp Modifier"
    difficulty_xp_mult = { key = 0x19bddb2e, kind = "f32" },
}

-- Ability slot order, as registered by EntityValueRegistry_RegisterAll.
R.stat.slots = { primary = 0, secondary = 1, defensive = 2, trait = 3, ultimate = 4 }

-- Per-slot stat families: the key is `base + 2*slot` (adjacent stats differ by
-- 2; see docs/_re/kinds/stats.md). These let a mod touch ONE ability's damage /
-- crit / cooldown instead of the hero-wide stat.
--
-- NOTE for attack_power: the hero-wide key (0x15a486c4) is NOT this family's
-- base -- the per-slot family starts at 0x15a5cf40. For crit_chance and
-- cooldown_reduction the family base IS the hero-wide key, so `*_primary`
-- resolves to the same key as the bare name; that mirrors the registry and is
-- not a bug.
local _slot_families = {
    attack_power       = 0x15a5cf40,
    crit_chance        = 0x15c7d482,
    cooldown_reduction = 0x15b45d80,
}
for family, base in pairs(_slot_families) do
    for slot_name, slot in pairs(R.stat.slots) do
        R.stat.keys[family .. "_" .. slot_name] = { key = base + 2 * slot, kind = "f32" }
    end
end

-- Off-family specials. `basic` sits +0x11 from the attack-power family base
-- (NOT a `+2*slot` member), and the dash keys live in a different range
-- entirely, so they are listed explicitly rather than derived.
R.stat.keys.attack_power_basic      = { key = 0x15a5cf51, kind = "f32" }
R.stat.keys.attack_power_dash       = { key = 0x183a609a, kind = "f32" }
R.stat.keys.crit_chance_dash        = { key = 0x183a60b6, kind = "f32" }
R.stat.keys.cooldown_reduction_dash = { key = 0x183a5fc9, kind = "f32" }

-- Status-effect family (FUN_1401d9070): `0x16ede056 + 2*i`, in registration
-- order. Stacks are ints.
local _status_family = {
    "strength", "regen", "haste", "concealed", "resistant",
    "rooted", "vulnerable", "ignite", "chilled", "poison",
}
for i, name in ipairs(_status_family) do
    R.stat.keys["status_" .. name] = { key = 0x16ede056 + 2 * (i - 1), kind = "int" }
end

-- Status effects registered outside that family.
R.stat.keys.status_shield = { key = 0x173fcd75, kind = "int" }
R.stat.keys.status_bleed  = { key = 0x173fcdac, kind = "int" }
R.stat.keys.status_cursed = { key = 0x1a5d3d69, kind = "int" }
R.stat.keys.status_marked = { key = 0x1a40367d, kind = "int" }

-- Resolve a family + slot to its key spec: R.stat.key("attack_power", "trait")
-- or R.stat.key("attack_power", 3). Returns nil for an unknown pair.
function R.stat.key(name, slot)
    if slot == nil then return R.stat.keys[name] end
    local slot_name = slot
    if type(slot) == "number" then
        slot_name = nil
        for n, i in pairs(R.stat.slots) do
            if i == slot then slot_name = n break end
        end
        if not slot_name then return nil end
    end
    return R.stat.keys[name .. "_" .. slot_name]
end

-- oCEntityValueUnion is a 0x20-byte tagged value. In the caller-provided read
-- buffer it starts at +0; inside a 0x38-byte override entry it starts at +0x08.
local EV_INLINE_OFF = 0x08   -- union: inline sentinel (== 4 => value is inline)
local EV_VALUE_OFF  = 0x10   -- union: inline value (f32 or int32)
local EV_TAG_OFF    = 0x18   -- union: type-tag byte (0 = int/float)
local EV_INLINE     = 4
local ENTRY_UNION_OFF = 0x08 -- override entry: embedded union offset
local ENTRY_KEY_OFF   = 0x00 -- override entry: u32 key
local OVR_DATA_OFF  = 0xc0   -- store -> override vector data ptr (vec base)
local OVR_COUNT_OFF = 0xc8   -- store -> override count (vec+8)
local OVR_STRIDE    = 0x38   -- override entry stride

-- Resolve the value-store pointer for a captured hero: *(ctx+0x4c8) where
-- ctx = *(hero+0x2f8). _ev_ctx (entity-values section above) has already
-- validated the whole chain — plausible ctx, plausible store, readable hot
-- fields — so a non-nil ctx with a non-zero store slot is usable as-is.
-- Returns the store ptr or nil.
local function _stat_store(hero)
    local ctx = _ev_ctx(hero)
    if not ctx then return nil end
    local s = I.read_u64(ctx + EV_STORE_OFF)
    if not s or s == 0 then return nil end
    return s
end

-- Read one stat by its spec ({key,kind}) from the current hero. Always safe:
-- the engine call is made only with an _ev_ctx-validated context pointer.
local function _stat_read(spec)
    local e = R.entity.hero(); if not e then return nil end
    local ctx = _ev_ctx(e); if not ctx then return nil end
    local out = I.scratch(0x20)                               -- zeroed union buffer
    local ok = pcall(R.engine.call, "EntityValue_Get", ctx, out, spec.key)
    if not ok then return nil end
    if I.read_u32(out + EV_INLINE_OFF) ~= EV_INLINE then return nil end
    if spec.kind == "int" then return I.read_u32(out + EV_VALUE_OFF) end
    return I.read_f32(out + EV_VALUE_OFF)
end

-- Current value of a named stat, or nil (unknown name / no hero / non-inline).
function R.stat.get(name)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return nil end
    return _stat_read(spec)
end

-- The known stat names, sorted.
function R.stat.names()
    local t = {}
    for k in pairs(R.stat.keys) do t[#t + 1] = k end
    table.sort(t)
    return t
end

-- EXPERIMENTAL write opt-in (default off — writes mutate live engine state).
local _stat_writes_enabled = false
-- Opt in to the experimental stat write path. Returns TRUE, always: this is a
-- consent flag, not a capability probe, and whether a write lands depends on
-- the hero being captured later. It used to return nothing, which reads as a
-- probe at every call site — the shipped Bloodlust mod did
-- `local ok = R.stat.enable_writes()` at load, got nil, and disabled itself for
-- the whole session. Ask R.entity.ready() if you want to know whether a write
-- can land right now.
-- Throttled logging for messages emitted from PER-EVENT paths.
--
-- R.stat.modify / R.xp.grant are called from gameplay-event handlers, so their
-- refusal messages run at the rate the game fires events. A playtest with
-- Bloodlust installed and hero capture off logged "[rsmm.stat] no hero captured
-- yet" once every three kills, forever — a real condition, reported so often it
-- buried everything else in the file.
--
-- Logs the first occurrence immediately, then at most once per REPEAT_SECONDS,
-- carrying the number suppressed so the reader still sees it is ongoing.
local _log_seen = {}
local REPEAT_SECONDS = 30

local function _log_throttled(key, msg)
    local now = (I.now and I.now()) or os.time()
    local st = _log_seen[key]
    if st == nil then
        _log_seen[key] = { at = now, n = 0 }
        R.log(msg)
        return
    end
    st.n = st.n + 1
    if now - st.at < REPEAT_SECONDS then return end
    R.log(("%s (%d more since last report)"):format(msg, st.n))
    st.at, st.n = now, 0
end

function R.stat.enable_writes()
    _stat_writes_enabled = true
    return true
end

-- Find the override entry for `key` in the store (entry addr, or nil).
local function _stat_find_entry(store, key)
    local data  = I.read_u64(store + OVR_DATA_OFF)
    local count = I.read_u32(store + OVR_COUNT_OFF)
    if not data or data == 0 or not count then return nil end
    for i = 0, count - 1 do
        local entry = data + i * OVR_STRIDE
        if I.read_u32(entry + ENTRY_KEY_OFF) == key then return entry end
    end
    return nil
end

-- Write an inline numeric value into an override entry's embedded union. Uses
-- only page-guarded pokes (a bad address no-ops rather than faults).
local function _stat_write_union(entry, spec, value)
    local u = entry + ENTRY_UNION_OFF
    I.write_u64(u + EV_INLINE_OFF, EV_INLINE)                 -- mark inline
    if spec.kind == "int" then
        I.write_u32(u + EV_VALUE_OFF, math.floor((value or 0) + 0.5))
    else
        I.write_f32(u + EV_VALUE_OFF, (value or 0) + 0.0)
    end
    I.write_u8(u + EV_TAG_OFF, 0)                             -- type tag: int/float
end

-- Set a named stat. EXPERIMENTAL, engine-mutating, MAIN-THREAD ONLY. Finds the
-- hero's override entry for the key (creating one via the engine allocator on a
-- miss) and writes the value into its union. Returns true on write. Fails
-- closed (logs, no-op) if writes aren't enabled, the hero/store is implausible,
-- or a symbol is unresolved.
function R.stat.set(name, value)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return false end
    if not _stat_writes_enabled then
        R.log("[rsmm.stat] writes are experimental and off — call R.stat.enable_writes() first")
        return false
    end
    if not _va_ok("R.stat") then return false end
    local e = R.entity.hero()
    if not e then _log_throttled("stat.nohero", "[rsmm.stat] no hero captured yet"); return false end
    if not _hero_plausible(e) then R.log("[rsmm.stat] hero reads implausible — refusing"); return false end
    local store = _stat_store(e)
    if not store then R.log("[rsmm.stat] value store not found for this build — refusing"); return false end
    local entry = _stat_find_entry(store, spec.key)
    if not entry then
        -- Miss: grow the override vector via the engine allocator, init the slot.
        local count = I.read_u32(store + OVR_COUNT_OFF) or 0
        local ok, slot = pcall(R.engine.call, "EntityValueOverride_Alloc", store + OVR_DATA_OFF, count, 1)
        if not ok or not slot or slot == 0 then R.log("[rsmm.stat] override alloc failed"); return false end
        I.write_u32(slot + ENTRY_KEY_OFF, spec.key)
        pcall(R.engine.call, "EntityValueUnion_DefaultCtor", slot + ENTRY_UNION_OFF)
        I.write_u32(slot + 0x28, 0); I.write_u16(slot + 0x2c, 0); I.write_u64(slot + 0x30, 0)
        entry = slot
    end
    _stat_write_union(entry, spec, value)
    R.log(string.format("[rsmm.stat] set %s = %s (override cache — TRANSIENT; use R.stat.stick to keep it)",
        name, tostring(value)))
    return true
end

-- current + delta (reads then sets). EXPERIMENTAL (see R.stat.set).
function R.stat.add(name, delta)
    local cur = R.stat.get(name); if not cur then return false end
    return R.stat.set(name, cur + (delta or 0))
end

-- native engine modifier (composes with the game's own math) -------------
--
-- R.stat.modify(name, amount [, duration]) inserts a REAL engine modifier for
-- the stat's key: it builds an oCGameEventNetworkModifier (layout decompile-
-- verified from FUN_1403c7560's inline construction + ModifierEvent_Ctor
-- FUN_140389fb0) and calls EntityValueStore_ApplyModifierEvent(store, ev, 0, 0)
-- directly. Unlike R.stat.set (cache poke, wiped by recompute) and R.stat.stick
-- (re-assertion, pins the FINAL value), a modifier lives in the store's
-- modifier registry (store+0x88) and is folded together with the game's own
-- item/talent modifiers on every recompute — it COMPOSES and SURVIVES.
--
-- Event layout (0x98 bytes):
--   +0x00 vftable (oCGameEventNetworkModifier)  +0x08 state u32 (0 = ready)
--   +0x20 name oCString {ptr,cap|0x80000000,len} +0x30 name hash (bus only —
--   unused on the direct call)                   +0x38 modifier id (-1 = fresh)
--   +0x50 serial u32   +0x54 stat CRC key u32    +0x58 counter u32
--   +0x60 oCEntityValueUnion (0x20B) carrying the AMOUNT (engine-ctor'd)
--   +0x80 duration f32 (<0 = permanent; give-handler uses 5.0 for its 5s buff)
--   +0x84/+0x88 multipliers f32 (1.0)            +0x8c flag u8 (1)
--   +0x90 source entity (0 = no lifetime binding)
--
-- How the amount folds (add/mul/replace) is DATA-DRIVEN per key: the value
-- def in the store's base map picks the typed modifier (def+0x74) and the
-- merge op (def+0x70: 1=add-stack 2=set 3=match-replace 4=min-remaining) and
-- caps the count (def+0x68). We can't choose the op — the engine applies its
-- native semantics for that stat, which is exactly what "compose correctly"
-- means. In co-op non-authority the engine relays the event to the host
-- instead of applying locally (its own code path, not ours).
--
-- EXPERIMENTAL + engine-mutating: MAIN THREAD only, R.stat.enable_writes()
-- required, fail-closed on any unresolved symbol / implausible pointer.
-- Pending in-game verification. Don't combine with R.stat.stick on the same
-- stat (stick pins the final value and would fight the modifier).
local MODIFIER_EVENT_VFT_VA = 0x140f322d0  -- oCGameEventNetworkModifier_vftable (symbol map)
local _mod_serial = 0

function R.stat.modify(name, amount, duration)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return false end
    if type(amount) ~= "number" then
        R.log("[rsmm.stat] modify: amount must be a number"); return false
    end
    if not _stat_writes_enabled then
        R.log("[rsmm.stat] writes are experimental and off — call R.stat.enable_writes() first")
        return false
    end
    if not _va_ok("R.stat.modify") then return false end
    local e = R.entity.hero()
    if not e then _log_throttled("stat.nohero", "[rsmm.stat] no hero captured yet"); return false end
    if not _hero_plausible(e) then R.log("[rsmm.stat] hero reads implausible — refusing"); return false end
    local store = _stat_store(e)
    if not store then R.log("[rsmm.stat] value store not found — refusing"); return false end

    -- Rebase the vftable va and sanity-probe it: slot 0 must hold a pointer
    -- into the game module (a wrong build / stale va reads as garbage and we
    -- refuse rather than hand the engine a fake object with a bad vtable).
    local base = I.module_base()
    if not base or base == 0 then return false end
    local vft = base + (MODIFIER_EVENT_VFT_VA - GIVE_IMG_BASE)
    local slot0 = I.read_u64(vft)
    if not slot0 or slot0 < base or slot0 >= base + 0x1600000 then
        R.log("[rsmm.stat] modifier-event vftable implausible on this build — refusing")
        return false
    end

    -- ONE scratch alloc for event + trailing ""-buffer. NEVER take a second
    -- scratch while the first is live: the native arena may hand back an
    -- overlapping block and zero its front — a second call here wiped the
    -- event's vftable and crashed the engine's virtual fill with a null
    -- vtable (2026-07-16, minidumps 25815b01/0425b5d9: READ @0x20 at
    -- ModifierEvent_Ctor+0xb9).
    local ev = I.scratch(0xb0)                     -- 0x98 event + 0x10 name tail
    local empty = ev + 0xa0                        -- zeroed tail doubles as ""
    I.write_u64(ev + 0x00, vft)
    I.write_u32(ev + 0x08, 0)                      -- state: ready
    I.write_u64(ev + 0x20, empty)                  -- name: empty, UNOWNED
    I.write_u32(ev + 0x28, 0x80000000)             -- (cap flag = engine won't free)
    I.write_u32(ev + 0x2c, 0)
    I.write_u32(ev + 0x30, 0)                      -- name hash: direct call, unused
    I.write_u64(ev + 0x38, 0xffffffffffffffff)     -- modifier id: fresh
    I.write_u32(ev + 0x40, 0)
    I.write_u64(ev + 0x48, 0xffffffffffffffff)
    _mod_serial = _mod_serial + 1
    I.write_u32(ev + 0x50, _mod_serial)
    I.write_u32(ev + 0x54, spec.key)
    I.write_u32(ev + 0x58, 0)
    -- The amount rides in the embedded union at +0x60. Construct it through
    -- the engine's own ctors (exactly the sequence the give-handler and
    -- ApplyModifierEvent use for their locals: default-ctor, destruct,
    -- re-init as numeric type 0) — then write the inline value.
    local u = ev + 0x60
    local okc, uret = pcall(R.engine.call, "EntityValueUnion_DefaultCtor", u)
    if not okc or not uret then
        R.log("[rsmm.stat] union ctor unresolved — refusing"); return false
    end
    pcall(R.engine.call, "EntityValueUnion_Destruct", u)
    pcall(R.engine.call, "EntityValueUnion_InitAsType", u, 0)
    if spec.kind == "int" then
        I.write_u32(u + 0x10, math.floor(amount + 0.5))
    else
        I.write_f32(u + 0x10, amount + 0.0)
    end
    I.write_f32(ev + 0x80, duration or -1.0)       -- default: permanent
    I.write_f32(ev + 0x84, 1.0)
    I.write_f32(ev + 0x88, 1.0)
    I.write_u8(ev + 0x8c, 1)
    I.write_u64(ev + 0x90, 0)                      -- no entity-lifetime binding
    -- Resolve BEFORE calling: ApplyModifierEvent returns void, so a nil from
    -- R.engine.call can't distinguish success from an unresolved symbol.
    if not R.engine.resolve("EntityValueStore_ApplyModifierEvent") then
        R.log("[rsmm.stat] ApplyModifierEvent unresolved on this build — refusing"); return false
    end
    local ok = pcall(R.engine.call, "EntityValueStore_ApplyModifierEvent", store, ev, 0, 0)
    if not ok then
        R.log("[rsmm.stat] ApplyModifierEvent raised — modifier NOT applied"); return false
    end
    R.log(string.format("[rsmm.stat] modify %s %+g (native modifier, %s)", name, amount,
        (duration and duration >= 0) and (tostring(duration) .. "s") or "permanent"))
    return true
end

-- durable stats (sticky re-assertion) -----------------------------------
--
-- R.stat.set writes the override CACHE, which EntityValueStore_Recompute
-- (FUN_140749a90) rebuilds from base + engine modifiers whenever the key goes
-- dirty (item pickup, level-up, ...). So a bare set is TRANSIENT. R.stat.stick
-- makes a value DURABLE by re-asserting it on the main-thread gameplay pump:
-- once a recompute clobbers the key, the next gameplay event re-applies it. The
-- re-assert is DRIFT-GATED — it only re-pokes when the live value has actually
-- moved off the target — so steady-state cost is one page-guarded read per
-- pinned stat per gameplay event and zero writes.
--
-- This is re-assertion over the existing (gated) poke, NOT a native engine
-- modifier: it pins the FINAL value and does not compose with the game's own
-- modifier math. For "set attack to X and keep it" that is exactly right. A true
-- additive modifier that composes with item/talent modifiers needs the
-- oCGameEventNetworkModifier dispatch path (symbols EntityValueStore_ApplyModifierEvent
-- / ModifierEvent_Ctor) whose event payload is not yet decoded — see
-- docs/_re/kinds/stats.md.
--
--   R.stat.stick("attack_power", 500)   -- set + keep it there
--   R.stat.unstick("attack_power")      -- stop pinning (engine restores base)
--   R.stat.sticky()                     -- table of currently-pinned {name=value}
local _stat_sticky = {}
local _stat_reassert_installed = false
local _STAT_DRIFT = 1e-4

-- Re-apply every pinned stat whose live value has drifted. Runs on the main
-- thread (called only from the gameplay-bus handler installed below).
local function _stat_reassert()
    if not _stat_writes_enabled then return end
    if not R.entity.hero() then return end
    for name, value in pairs(_stat_sticky) do
        local cur = R.stat.get(name)
        if cur == nil or math.abs(cur - value) > _STAT_DRIFT then
            R.stat.set(name, value)
        end
    end
end

-- Subscribe the re-assert to the gameplay bus once. The gameplay-bus wildcard
-- runs on the game's MAIN thread (same pump as the schedule main tick below);
-- gating on ev.source == "gameplay" keeps engine-mutating writes off the loader
-- background thread ("tick"/"ready"), per [[loader-thread-model]].
local function _stat_install_reassert()
    if _stat_reassert_installed then return end
    _stat_reassert_installed = true
    R.on("*", function(ev)
        if ev and ev.source == "gameplay" then _stat_reassert() end
    end)
end

-- Pin a stat to `value` durably. Applies immediately through R.stat.set (so all
-- its gates apply: enable_writes, main-thread, hero/store plausibility) and
-- re-asserts after every recompute. Returns the immediate-apply result.
function R.stat.stick(name, value)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return false end
    _stat_sticky[name] = value
    _stat_install_reassert()
    return R.stat.set(name, value)
end

-- Stop pinning a stat. The engine's next recompute restores its computed value.
-- Returns true if it was pinned.
function R.stat.unstick(name)
    local had = _stat_sticky[name] ~= nil
    _stat_sticky[name] = nil
    return had
end

-- Shallow copy of the currently-pinned {name = value} table.
function R.stat.sticky()
    local t = {}
    for k, v in pairs(_stat_sticky) do t[k] = v end
    return t
end

-- experience (level / xp grant) -----------------------------------------
--
-- XP lives on its own hero component (the XpComponent), not the value store.
-- R.xp reads level/xp and (EXPERIMENTAL) grants XP through the engine's own
-- gain-experience routine, which runs the level-up loop and fires _XP_LEVEL_UP.
-- Grant is engine-mutating: MAIN THREAD + R.stat.enable_writes() opt-in.
--
--   R.xp.level() / R.xp.xp()   -- current level / xp-within-level, or nil
--   R.xp.grant(100)            -- add XP (levels up as needed)
R.xp = {}

-- CORRECTED 2026-07-18: was 0x140f23200, which is not a vtable at all -- it
-- lands 0x50 inside this one (slot 10 of 30), so `*(comp) == VA` could never
-- match and R.xp returned nil on every build. Real class is
-- oCDtEntityCpntGroupLevel. Keep in sync with symbols.json XpComponent_vftable
-- -- this literal mirrors the symbol map by hand.
local XP_VFTABLE_VA      = 0x140f231b0  -- oCDtEntityCpntGroupLevel::vftable
local XP_TESTER_VA       = 0x141476e00  -- XpComponent_TypeTester (data global)
local XP_ARR_OFF         = 0x190        -- entity -> component ptr array
local XP_ARR_COUNT_OFF   = 0x198        -- entity -> component count
local XP_OWNER_OFF       = 0x08         -- component -> owner entity (back-ptr)
local XP_PROGRESS_OFF    = 0x108        -- xpComp -> {level u32 @+0, xp u32 @+4}
local XP_GAIN_AMOUNT_OFF = 0x50         -- xpGain struct -> amount (int)

local _xp_cache_hero, _xp_cache_comp = nil, nil
local _xp_diag_done = false

-- Candidate component-array owners. The two direct candidates —
-- *(hero+0x2f8) and the captured object itself — both had EMPTY component
-- arrays in the 2026-07-17 playtest (diag: arr=0 count=0), so the
-- component-owning oCEntity hangs off some OTHER field of the captured
-- controller. Probe every pointer-sized field of the hero and of the value
-- ctx for an object with a plausible component array @+0x190/+0x198
-- (Entity_GetComponentByTester's walk, decompile-reconfirmed 2026-07-17).
-- Pure page-guarded reads, cached per hero — tick-thread safe.
-- An owner is accepted ONLY if its ENTIRE component array validates: every
-- entry is a plausible pointer whose vftable lies inside the game image and
-- whose owner back-ptr points back at the entity. This is the gate that
-- makes it safe to hand the entity to engine code later — the 2026-07-17
-- crash (null deref at Entity_GetComponentByTester+0x36) was the engine
-- walking a false-positive "array" the loose probe had accepted.
local function _xp_owner_valid(entity, _mbase)
    return _vector_valid(entity, XP_ARR_OFF, XP_ARR_COUNT_OFF, {
        min = 1, max = 0x100,
        check_entry = function(comp, owner)
            -- component: vtable in image AND owner back-ptr matches the entity.
            return _obj_has_vtable(comp) and I.read_u64(comp + XP_OWNER_OFF) == owner
        end,
    })
end

local _xp_owners_hero, _xp_owners = nil, nil
local function _xp_entities(hero)
    if hero == _xp_owners_hero and _xp_owners then return _xp_owners end
    local mbase = I.module_base(); if not mbase or mbase == 0 then return {} end
    local owners, seen = {}, {}
    local function consider(P)
        if not P or P == 0 or seen[P] or not _ptr_plausible(P) then return end
        seen[P] = true
        if _xp_owner_valid(P, mbase) then owners[#owners + 1] = P end
    end
    local ctx = I.read_u64(hero + ENTITY_VALCTX_OFF)
    consider(ctx); consider(hero)
    for _, base in ipairs({ hero, ctx }) do
        if base and base ~= 0 and _ptr_plausible(base) then
            for off = 0, 0x7f8, 8 do
                consider(I.read_u64(base + off))
            end
        end
    end
    _xp_owners_hero, _xp_owners = hero, owners
    return owners
end

-- Engine-call-free XP detection: the XpComponent is recognizable by shape —
-- +0x108 points at a {level u32, xp u32} block with sane values and +0x10
-- holds the curve object pointer. Accepted only when exactly ONE component
-- across all validated owners matches (ambiguity falls through to the
-- engine-tester path rather than risking a grant on the wrong component).
local function _xp_heuristic(hero, mbase)
    local hit, hits = nil, 0
    for _, entity in ipairs(_xp_entities(hero)) do
        local arr = I.read_u64(entity + XP_ARR_OFF)
        local n   = I.read_u32(entity + XP_ARR_COUNT_OFF)
        for i = 0, n - 1 do
            local comp = I.read_u64(arr + i * 8)
            local prog = I.read_u64(comp + XP_PROGRESS_OFF)
            if prog and prog ~= 0 and _ptr_plausible(prog)
               and _ptr_plausible(I.read_u64(comp + 0x10)) then
                local lvl = I.read_u32(prog)
                local xpv = I.read_u32(prog + 4)
                if lvl and xpv and lvl >= 1 and lvl <= 200 and xpv < 10000000 then
                    hits = hits + 1
                    hit = comp
                end
            end
        end
    end
    if hits == 1 then
        local vft = I.read_u64(hit)
        R.log(string.format(
            "[rsmm.xp] heuristic found XpComponent 0x%x (vft 0x%x; map expects 0x%x)",
            hit, vft and (vft - mbase + ENTITY_IMG_BASE) or 0, XP_VFTABLE_VA))
        return hit
    end
    if hits > 1 then
        R.log(string.format("[rsmm.xp] heuristic ambiguous (%d progress-shaped components) — deferring to engine tester", hits))
    end
    return nil
end

-- Pure-memory fallback: scan the component array for the exact XpComponent
-- vftable. Misses if the live component is a SUBCLASS (different vftable) —
-- the suspected cause of the 2026-07-16 "XP component not found". Kept as the
-- thread-safe read path; each hit validated by the owner back-ptr.
local function _xp_scan(hero)
    local base = I.module_base(); if not base or base == 0 then return nil end
    local want = base + (XP_VFTABLE_VA - ENTITY_IMG_BASE)
    for _, entity in ipairs(_xp_entities(hero)) do
        if entity and entity ~= 0 then
            local arr   = I.read_u64(entity + XP_ARR_OFF)
            local count = I.read_u32(entity + XP_ARR_COUNT_OFF)
            if arr and arr ~= 0 and count and count <= 0x400 then
                for i = 0, count - 1 do
                    local comp = I.read_u64(arr + i * 8)
                    if comp and comp ~= 0 and I.read_u64(comp) == want
                       and I.read_u64(comp + XP_OWNER_OFF) == entity then
                        return comp
                    end
                end
            end
        end
    end
    return nil
end

-- One-shot diagnostic when everything misses: log each candidate's component
-- count and the rebased vftables of its first few components, so the real
-- XpComponent vftable can be identified from the log without a debugger.
local function _xp_diag(hero)
    if _xp_diag_done then return end
    _xp_diag_done = true
    local base = I.module_base(); if not base or base == 0 then return end
    local owners = _xp_entities(hero)
    R.log(string.format("[rsmm.xp] diag: %d component-array owner(s) probed from hero 0x%x",
        #owners, hero))
    for ci = 1, math.min(#owners, 8) do
        local entity = owners[ci]
        local arr   = I.read_u64(entity + XP_ARR_OFF)
        local count = I.read_u32(entity + XP_ARR_COUNT_OFF)
        -- The candidate's OWN class matters as much as its components: the
        -- 2026-07-18 runs showed the probed owners are plain oCEntity, and the
        -- target is absent from all of them.
        local ovft = I.read_u64(entity)
        R.log(string.format("[rsmm.xp] diag cand%d entity=0x%x arr=0x%x count=%s entity_vft=%s",
            ci, entity, arr or 0, tostring(count),
            (ovft and ovft > base) and string.format("0x%x", ovft - base + ENTITY_IMG_BASE)
                or "?"))
        -- Scan EVERY component and report a verdict rather than dumping a
        -- prefix: a 12-entry cap hid the answer for five playtests.
        if arr and arr ~= 0 and count and count <= 0x400 then
            local found = nil
            for i = 0, count - 1 do
                local comp = I.read_u64(arr + i * 8)
                local vft  = comp and comp ~= 0 and I.read_u64(comp) or nil
                if vft and vft - base + ENTITY_IMG_BASE == XP_VFTABLE_VA then
                    found = i; break
                end
            end
            R.log(string.format("[rsmm.xp] diag cand%d target 0x%x: %s",
                ci, XP_VFTABLE_VA,
                found and ("FOUND at index " .. found) or "absent from all " ..
                    tostring(count) .. " components"))
            for i = 0, math.min(count, 64) - 1 do
                local comp = I.read_u64(arr + i * 8)
                local vft  = comp and comp ~= 0 and I.read_u64(comp) or nil
                if vft and vft > base then
                    R.log(string.format("[rsmm.xp] diag cand%d comp[%d]=0x%x vft=0x%x",
                        ci, i, comp, vft - base + ENTITY_IMG_BASE))
                end
            end
        end
    end
end

-- ---------------------------------------------------------------------------
-- Constructor capture — the component is NOT on the hero.
--
-- Five playtests scanned the hero's component array and found nothing; the
-- 2026-07-19 run settled it with a full scan (absent from all 227 components
-- of all 3 probed owners, every owner a genuine oCEntity). The reason is
-- structural: exactly one oCDtEntityCpntGroupLevel is authored in the whole
-- corpus, on EntitySettings/Common_Settings/Group_Scaling.entity.ot — the
-- party-wide scaling entity. No amount of walking the hero can reach it.
--
-- So stop searching and let the engine hand it over: detour its constructor
-- and keep `this`.
--
-- The ctor can run MORE THAN ONCE, and not every instance is the live one:
-- session 5f36 captured an instance whose curve config was empty (max_level
-- clamps to 1, xp_for_level=0xffffffff) and whose level/xp never moved while
-- the party demonstrably gained XP — a template/menu construction, not the
-- run's tracker. So keep the last few constructed pointers and, at read
-- time, prefer the one with a USABLE curve; an instance may also gain its
-- config after construction (settings deserialize post-ctor), so the choice
-- is re-evaluated whenever the current pick has no curve.
local _gl_seen, _gl_comp = {}, nil
local _gl_armed = false
local GL_SEEN_MAX = 8

--- Pure-memory (tick-thread-safe) probe: does this component have a level
-- curve the engine would actually honor? Mirrors what XpForLevel/GetMaxLevel
-- read: curve table at *(comp+0x10)+0x1d8 (enable flag +0x1d0, count +0x1e0)
-- or the "Max Hero Level" signal object at comp+0x70.
local function _gl_curve_usable(p)
    local cfg = I.read_u64(p + 0x10)
    if cfg and cfg ~= 0 and _ptr_plausible(cfg) then
        local flag  = I.read_u8(cfg + 0x1d0)
        local count = I.read_u32(cfg + 0x1e0)
        if flag and flag ~= 0 and count and count > 0 and count < 0x1000 then
            return true
        end
    end
    local sig = I.read_u64(p + 0x70)
    return sig ~= nil and sig ~= 0 and _ptr_plausible(sig)
end

--- True if `p` looks like a fully-constructed GroupLevel component.
-- Checked lazily rather than at hook time: the hook callback runs BEFORE the
-- original, so at capture the object is raw memory with no vftable yet (the
-- same reason hero capture stashes "pending" and promotes on first valid
-- read). Every read here is page-guarded, so a bad pointer yields nil.
local function _gl_valid(p)
    if not p or p == 0 or not _ptr_plausible(p) then return false end
    local base = I.module_base()
    if not base or base == 0 then return false end
    if I.read_u64(p) ~= base + (XP_VFTABLE_VA - ENTITY_IMG_BASE) then return false end
    -- +0x108 is the {level u32, xp u32} progress pointer (the destructor just
    -- below the ctor releases exactly this field, which is how it was pinned).
    local prog = I.read_u64(p + XP_PROGRESS_OFF)
    if not prog or prog == 0 or not _ptr_plausible(prog) then return false end
    local lvl = I.read_u32(prog)
    return lvl ~= nil and lvl >= 1 and lvl <= 200
end

-- MUST be armed before the run starts, unlike every other hook here.
--
-- First playtest (session 974f) proved it: the hook resolved and installed
-- correctly on the right function, but lazily — on the first R.xp read, which
-- the demo does about a minute into a run:
--
--   11:43:03  StatGrantDemo init OK
--   11:43:17  hero spawn-init            <- Group_Scaling built around here
--   11:44:18  [hook] slot 0 installed    <- 61s too late; ctor already ran
--
-- The component is constructed once, at run start. A hook installed after
-- that never fires, so capture is not "flaky", it is guaranteed to miss.
-- `setup` (all mods' init.lua ran) is the earliest lifecycle point that is
-- still safely after module load — arming at module load would let a failure
-- abort require"rsmm" for every mod, which is why the other hooks are lazy.
local function _arm_group_level_capture()
    if _gl_armed then return end
    if not R.hook or not I.resolve then return end
    _gl_armed = true
    -- nil when the symbol is unverified for this build — fail closed rather
    -- than hooking a stale VA (a mid-function detour corrupts the stream).
    local va = I.resolve("GroupLevelComponent_Ctor")
    if not va or va == 0 then
        R.log("[rsmm.xp] GroupLevelComponent_Ctor unresolved for this build; "
            .. "level/xp unavailable this run")
        return
    end
    -- Signature is `void*(void* self)`: return + one pointer arg, no floats.
    --
    -- The callback could instead call the supplied `next(self)` to run the
    -- ctor and validate immediately. Deliberately NOT done: if anything in
    -- this callback then raised, the loader's error path replays the
    -- trampoline itself, so the CONSTRUCTOR would run twice on the same
    -- object — double-initialising it and leaking whatever the first pass
    -- allocated. Stashing and returning nil keeps the original running
    -- exactly once, at the cost of validating on the next read instead.
    local ok, slot, why = pcall(R.hook, va, "pp", function(self)
        -- Stash only. Returning nil replays the original, which is what
        -- actually writes the vftable and allocates the progress block.
        -- Newest first; dedupe; bounded (the ctor may run per menu/run).
        if self and self ~= 0 then
            for i = #_gl_seen, 1, -1 do
                if _gl_seen[i] == self then table.remove(_gl_seen, i) end
            end
            table.insert(_gl_seen, 1, self)
            for i = #_gl_seen, GL_SEEN_MAX + 1, -1 do table.remove(_gl_seen, i) end
        end
        return nil
    end)
    -- (nil, "already-hooked") means another mod's state armed the same ctor
    -- hook first. The hook is live and its captures land in this state too, so
    -- that is a success — reporting it as "level/xp unavailable" once per extra
    -- mod is how a working four-mod install came to look like three broken ones.
    if ok and slot == nil and why == "already-hooked" then return end
    if not ok or slot == nil then
        R.log("[rsmm.xp] could not install GroupLevelComponent_Ctor hook; "
            .. "level/xp unavailable this run")
    end
end

--- The live party-wide level/XP component, or nil.
-- Selection order: (1) a valid captured instance WITH a usable curve — the
-- one the engine's grant path would honor; (2) the newest valid instance
-- otherwise (reads still work; grant's gate pre-flight refuses honestly).
-- The pick is re-evaluated while it has no curve, because settings
-- deserialize after the ctor and a better instance (or this one's config)
-- can appear on a later read.
local function _group_level()
    if _gl_comp and _gl_valid(_gl_comp) and _gl_curve_usable(_gl_comp) then
        return _gl_comp
    end
    _arm_group_level_capture()
    local fallback = nil
    for _, p in ipairs(_gl_seen) do
        if _gl_valid(p) then
            if _gl_curve_usable(p) then
                if _gl_comp ~= p then
                    _gl_comp = p
                    R.log(string.format("[rsmm.xp] group-level component "
                        .. "captured @0x%x (level %d, curve present)", p,
                        I.read_u32(I.read_u64(p + XP_PROGRESS_OFF)) or 0))
                end
                return p
            end
            fallback = fallback or p
        end
    end
    if fallback then
        if _gl_comp ~= fallback then
            _gl_comp = fallback
            R.log(string.format("[rsmm.xp] group-level component captured "
                .. "@0x%x (level %d, NO curve config yet — grant will refuse "
                .. "until it appears)", fallback,
                I.read_u32(I.read_u64(fallback + XP_PROGRESS_OFF)) or 0))
        end
        return fallback
    end
    _gl_comp = nil                      -- entity torn down between runs
    return nil
end

-- Arm at `setup` so the hook is live before the run builds the component.
-- Subscribing cannot fail the way hooking can, and the arm itself is
-- pcall-guarded internally, so this cannot abort require"rsmm".
native.on_event("setup", function() pcall(_arm_group_level_capture) end)

-- Locate the hero's XpComponent. `allow_engine` (MAIN THREAD ONLY — the
-- engine walk calls each component's virtual IsKindOf) uses the engine's own
-- Entity_GetComponentByTester with the XpComponent type-tester, which
-- resolves subclasses the exact-vftable scan can't. The result is cached per
-- hero so the tick-thread readers (level/xp) never touch engine code.
local function _xp_component(hero, allow_engine)
    -- Constructor capture first: it returns the authored instance directly,
    -- so it is both cheaper and correct where the hero scan is structurally
    -- incapable of succeeding. The scans below remain as a fallback in case a
    -- future build does put a level component on the hero.
    local captured = _group_level()
    if captured then return captured end
    if not hero then return nil end
    if hero == _xp_cache_hero and _xp_cache_comp then return _xp_cache_comp end
    local comp = _xp_scan(hero)
    if not comp then
        local mb = I.module_base()
        if mb and mb ~= 0 then comp = _xp_heuristic(hero, mb) end
    end
    if not comp and allow_engine then
        local base = I.module_base()
        local tester = base and base ~= 0 and (base + (XP_TESTER_VA - ENTITY_IMG_BASE)) or nil
        if tester and _ptr_plausible(I.read_u64(tester)) then
            for _, entity in ipairs(_xp_entities(hero)) do
                -- entity already passed _xp_owner_valid (full component-array
                -- validation) inside _xp_entities — safe to hand to the engine
                -- walk. call_safe re-guards both pointer args as belt-and-braces.
                if entity and entity ~= 0 and _ptr_plausible(entity) then
                    local ok, got = pcall(R.engine.call_safe, "Entity_GetComponentByTester",
                                          { 1, { 2, _in_image } }, entity, tester)
                    local prog = ok and type(got) == "number" and got ~= 0
                                 and I.read_u64(got + XP_PROGRESS_OFF) or 0
                    if prog and prog ~= 0 then
                        local vft = I.read_u64(got)
                        R.log(string.format(
                            "[rsmm.xp] engine lookup found XpComponent 0x%x (vft 0x%x; map scan expects 0x%x)",
                            got, vft and (vft - base + ENTITY_IMG_BASE) or 0, XP_VFTABLE_VA))
                        comp = got
                        break
                    end
                end
            end
        end
        if not comp then _xp_diag(hero) end
    end
    if comp then _xp_cache_hero, _xp_cache_comp = hero, comp end
    return comp
end

local function _xp_progress(field)
    local comp = _xp_component(R.entity.hero()); if not comp then return nil end
    local prog = I.read_u64(comp + XP_PROGRESS_OFF)
    if not prog or prog == 0 then return nil end
    return I.read_u32(prog + field)
end

function R.xp.level() return _xp_progress(0) end
function R.xp.xp()    return _xp_progress(4) end

-- Grant XP through the engine's gain-experience routine. EXPERIMENTAL,
-- MAIN-THREAD ONLY, gated by R.stat.enable_writes(). Fails closed on any guard.
function R.xp.grant(amount)
    if not _stat_writes_enabled then
        R.log("[rsmm.xp] grant is experimental and off — call R.stat.enable_writes() first")
        return false
    end
    if not _va_ok("R.xp") then return false end
    amount = math.floor(amount or 0)
    if amount <= 0 then return false end
    local hero = R.entity.hero()
    if not hero then _log_throttled("xp.nohero", "[rsmm.xp] no hero captured yet"); return false end
    -- grant runs on the MAIN thread (schedule.next_main contract) — the only
    -- place the engine-walk lookup is safe.
    local comp = _xp_component(hero, true)
    if not comp then R.log("[rsmm.xp] XP component not found for this build — refusing"); return false end
    -- Snapshot progress so a silent engine no-op is detectable afterwards.
    local prog = I.read_u64(comp + XP_PROGRESS_OFF)
    local lvl0 = prog and prog ~= 0 and I.read_u32(prog) or nil
    local xp0  = prog and prog ~= 0 and I.read_u32(prog + 4) or nil
    -- Pre-flight the engine's own gate. Hero_GainExperience starts with an
    -- is-max-level check and returns WITHOUT touching anything when the
    -- (chain-last) level >= max level — and a component with no max-level
    -- config clamps max to 1, so a level-1 hero is "at max" and every grant
    -- silently no-ops (the 2026-07-19 playtest: "granted 200 xp", xp stayed
    -- 0). Surface that instead of reporting success. The gate returns via
    -- `setae al`, so only the low byte of the return is defined.
    local okg, gate = pcall(R.engine.call, "XpComponent_IsMaxLevel", comp)
    if okg and type(gate) == "number" and (gate & 0xff) ~= 0 then
        local _, maxl = pcall(R.engine.call, "XpComponent_GetMaxLevel", comp)
        local _, need = pcall(R.engine.call, "XpComponent_XpForLevel", comp, lvl0 or 1)
        R.log(string.format(
            "[rsmm.xp] grant refused by engine max-level gate: level=%s xp=%s "
            .. "max_level=%s xp_for_level=%s next_link=0x%x — the captured "
            .. "component has no usable level curve, so the engine would "
            .. "silently drop the grant",
            tostring(lvl0), tostring(xp0), tostring(maxl), tostring(need),
            I.read_u64(comp + 0x110) or 0))
        return false
    end
    -- The routine reads only *(int*)(xpGain+0x50); a zeroed scratch is enough.
    local gain = I.scratch(0x60)
    I.write_u32(gain + XP_GAIN_AMOUNT_OFF, amount)
    local ok = pcall(R.engine.call, "Hero_GainExperience", comp, gain)
    if not ok then R.log("[rsmm.xp] Hero_GainExperience unresolved/failed"); return false end
    -- Read back: the call returning is not proof anything landed.
    local lvl1 = prog and prog ~= 0 and I.read_u32(prog) or nil
    local xp1  = prog and prog ~= 0 and I.read_u32(prog + 4) or nil
    if lvl1 == lvl0 and xp1 == xp0 then
        R.log(string.format(
            "[rsmm.xp] grant NO-OP: level/xp unchanged (level=%s xp=%s) after "
            .. "Hero_GainExperience — engine dropped it past the max-level gate",
            tostring(lvl1), tostring(xp1)))
        return false
    end
    R.log(string.format("[rsmm.xp] granted %d xp (level %s->%s, xp %s->%s)",
        amount, tostring(lvl0), tostring(lvl1), tostring(xp0), tostring(xp1)))
    return true
end

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
            -- PROVEN at runtime rather than assumed -- see F._dmg_session_join.
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
    local ok, slot, why = pcall(R.hook, va, "ppp", function(self, blob)
        local pok, perr = pcall(on_parse, self, blob)
        if not pok and not LOBBY_HOOK.err_said then
            LOBBY_HOOK.err_said = true
            R.log("[rsmm.lobby] parse callback raised (names keep arriving on "
                .. "later parses): " .. tostring(perr))
        end
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
-- Per-player damage attribution: who is carrying the run. Three sources feed
-- one board, in priority order, and each one is disjoint from the others by
-- construction so a hit is never counted twice (all three re-confirmed against
-- the live decompile 2026-08-15).
--
-- 1. HeroStats_OnDamageDealt — PRIMARY. The engine's own per-hero damage
--    bookkeeping, called once per damage application with the DEALING HERO's
--    controller as its first argument. It is hero-scoped (enemies never reach
--    it), it sees every path that lands damage rather than one producer, and
--    it fires for ALLIES too: the engine only skips its own totalling for a
--    non-local hero (the `+0x1d88` gate), it still runs the function. That is
--    what makes an ally's damage countable at all — the game itself never
--    totals it.
-- 2. Entity_ResolveAttackHits — the local attack resolver. Used for damage
--    TAKEN (an enemy swinging at a hero reaches it, and it is the only "I got
--    hit" signal that works in single player), and as the dealt-damage
--    fallback if the primary symbol is unavailable on a future build.
-- 3. gameplay:NETWORK_DAMAGE — replicated damage, keyed by the attacker's NET
--    id (every pointer in that event belongs to the sending machine). Only
--    credited when the same player's hit did not already arrive through source
--    1 on this machine; rows are merged by net id, and a matching amount
--    inside a short window is dropped as the same hit seen twice.
--
-- MULTIPLAYER SCOPE. A peer counts what its own machine applies plus what
-- other machines replicate to it. The host applies enemy damage, so a host's
-- board is complete; a client is complete for its own damage and as complete
-- as replication allows for allies. Nothing here is networked by the mod and
-- no game state is touched — every hook replays the original untouched.
--
--     R.damage.enable{ window = 10 }
--     for rank, row in ipairs(R.damage.board()) do
--         R.log(rank, row.label, row.dealt, row.share, row.dps)
--     end

R.damage = {}

-- Constants and helpers are grouped into two tables ON PURPOSE. Lua caps a
-- function at 200 live locals and the module chunk is one function; as flat
-- locals this section pushed rsmm.lua over the limit and it stopped compiling
-- altogether — every mod dead, for a damage meter. Two tables cost two locals.
local DMG = {
    -- Engine literals that sit inside the serialized lobby member list, found
    -- next to the local display name in session 6c4f. Anchoring the name hunt
    -- on these rather than on a player's name needs no config and cannot
    -- collide with an asset path.
    -- Bytes `mem_find` may examine per needle. Was 512 MB, and EVERY hit in
    -- sessions 5736/274f sat below ~0x1b000000 — the scan was exhausting its
    -- budget inside the low heap (where Lua's own strings live) and returning
    -- before it ever reached the game's allocations. The searches were finding
    -- the probe and the config because those are the only things in the part
    -- of the address space the probe could afford to look at.
    NAME_SCAN_MB    = MEM_SCAN_MB,
    -- Strings that exist ONLY in this SDK. Lua interns every literal in the
    -- module, so the scan finds rsmm.lua's own string table and reports it as
    -- a record — most of session 5736's output was the probe finding itself,
    -- including the marker literals above. A window containing any of these is
    -- our Lua heap, never a game structure.
    STATS_SYMBOL    = "HeroStats_OnDamageDealt",
    TAKEN_SYMBOL    = "HeroStats_OnDamageTaken",
    ATTACK_SYMBOL   = "Entity_ResolveAttackHits",
    -- oCDtEntityCpntHeroController
    HERO_ENTITY_OFF  = 0x08,     -- owning oCEntity
    HERO_ISLOCAL_OFF = 0x1d88,   -- 1 = this machine's player
    HERO_MIRROR_OFF  = 0x1d80,   -- HUD HP mirror; LOCAL player only
    HERO_STATS_OFF   = 0x1db0,   -- per-run stats record (end-screen source)
    STATS_TOTAL_OFF  = 0xa8,     -- u32 total damage — LOCAL hero only
    STATS_BEST_OFF   = 0xcc,     -- f32 biggest single hit
    -- oCDtProcessedDamage
    PD_VALUE_OFF     = 0x10,     -- -> hit-value object
    VALUE_AMOUNT_OFF = 0x08,     -- f32 damage inside it
    PD_SOURCE_OFF    = 0xa0,     -- -> hit-def / source info
    SOURCE_TYPE_OFF  = 0xc8,     -- u16 attack-type enum
    -- Entity_ResolveAttackHits arguments
    CTX_ENTITY_OFF   = 0x08,     -- attacker context -> attacking entity
    TGT_COUNT_OFF    = 0x00,
    TGT_DATA_OFF     = 0x08,
    MAX_TARGETS      = 32,
    NET_AUTHORITY_OFF = 0x130,   -- net component: 0 = locally owned
    SAMPLE_CAP       = 4096,     -- rolling-window entries per actor
    DEDUPE_WINDOW    = 0.4,      -- seconds a replicated echo can lag by
    -- REBIND SAFETY. A row is only re-adopted by a new controller when the old
    -- controller can no longer be alive. Primary evidence is the CHAPTER EPOCH
    -- (bumped by the engine's own chapter/map events); this is the fallback for
    -- a build where those events never arrive -- a row nobody has credited for
    -- this long has plausibly lost its controller. Only the EXACT hero-id join
    -- may use it; the is-local guess never may.
    REBIND_IDLE      = 45,       -- seconds a row must be silent to be adopted
    -- VICTIM CLASSIFICATION (the enemy-vs-scenery test).
    --
    -- The bookkeeping hook's 2nd argument is the VICTIM ENTITY -- not a stats
    -- block, which is what symbols.json claimed until 2026-08-17. Its sole
    -- caller hands the same pointer to Entity_GetNetComponent, and this
    -- function reads the victim's definition at +0x28 to stamp the analytics
    -- record with the target's resource path. So the victim is already in our
    -- hands on the primary source; classifying it needs no extra hook.
    --
    -- An entity is a gameplay ENEMY when it carries an
    -- oCDtEntityCpntEnemyController component. Fences, jars, vegetation and
    -- mission props are Hittable + HitPoint with no controller at all
    -- (EntitySettings/Destructible_Common/* vs Enemies/NPC_Common/Enemy_Model).
    -- The test is a pure page-guarded READ of the component array -- never an
    -- engine call, so a stale offset yields a wrong answer, never a crash.
    -- Components on an oCEntity live in an F14/SwissTable map keyed by CLASS
    -- ID, not in the +0x190 pointer array — that array belongs to an
    -- oCEntitySpawnerGo (Entity_GetComponentByTester's parameter), which is
    -- why session c536 read `n/a` for every enemy it probed and found the
    -- controller on nobody. Layout from Entity_GetNetComponent
    -- (FUN_140312db0), which does this exact lookup for oCEntityCpntNetwork.
    CPNT_CTRL_OFF    = 0x5e8,    -- entity -> F14 control bytes
    CPNT_SLOTS_OFF   = 0x5f0,    -- entity -> slot array
    CPNT_MASK_OFF    = 0x600,    -- entity -> bucket mask (capacity - 1)
    CPNT_SLOT_STRIDE = 0x10,     -- slot = { u32 class id @+0, cpnt* @+8 }
    CPNT_SLOT_PTR    = 0x08,
    MAX_SLOTS        = 0x4000,   -- refuse an implausible capacity outright
    -- Engine class ids, stamped by each class registrar as
    -- `mov [desc+0x28], <id>`. A content hash of the class NAME, so it is far
    -- more patch-stable than a vftable VA — and the same key the engine's own
    -- component map is indexed by. Mined by tools/mine_class_ids.py; the
    -- miner is confirmed by 0x154fce5c resolving to oCEntityCpntNetwork,
    -- the literal Entity_GetNetComponent hardcodes.
    ENEMY_CTRL_CLASS_ID = 0x1561073c,   -- oCDtEntityCpntEnemyController
    HERO_CTRL_CLASS_ID  = 0x155aac59,   -- oCDtEntityCpntHeroController
    ENEMY_CTRL_VFT_VA = 0x140f30b78,    -- symbols.json EnemyController_vftable
    CPNT_OWNER_OFF   = 0x08,     -- component -> owner entity (back-ptr)
    VICTIM_DEF_OFF   = 0x28,     -- entity -> oCEntitySettings (confirmed live)
    SETTINGS_RSRC_OFF = 0x70,    -- settings -> resource the engine stringifies
    VICTIM_CACHE_CAP = 512,      -- entity -> class cache entries before reset
    -- How many times ONE entity may be re-scanned after an inconclusive read.
    -- A victim whose component map cannot be read answers `unknown` on every
    -- hit, and `unknown` is fail-open — so a DoT ticking on it re-ran the full
    -- linear slot walk on the MAIN THREAD, per tick, for the whole run. Three
    -- attempts is enough to catch an entity that was merely mid-construction.
    VICTIM_RETRIES   = 3,
    -- Reason string for the stale-ally rebind. A GUESS, not an identity: it
    -- must never unlock the idle-adoption path in F._dmg_may_rebind.
    STALE_ALLY = "the only ally row whose controller died with the last chapter",
    PROBE_VICTIMS    = 12,       -- distinct victims the probe reports, then off
    PROBE_VFTS       = 6,        -- component vftables logged per victim
    -- The engine's own attack-type names, read out of the table at
    -- 0x1412ed7d0 that the bookkeeping routine indexes with the enum.
    TYPES = { [0] = "attack", "power", "special", "defense",
              "trait", "ultimate", "dash" },
}

F = {}   -- populate the table declared at the top of the chunk
local _dmg = {
    on       = false,
    window   = 10,        -- seconds behind `dps`
    min      = 0,         -- ignore hits at or below this
    names    = {},        -- slot -> player-supplied label
    actors   = {},        -- key -> row
    by_netid = {},        -- net id -> row (merges the replicated view in)
    by_hero  = {},        -- lobby hero id -> row (survives a chapter change)
    order    = {},        -- slot -> row, stable join order
    seen     = {},        -- entity -> true: known NOT a hero, stop asking
    subs     = {},        -- per-hit callbacks
    stats_hooked = false,
    taken_hooked = false,
    hooked   = false,     -- resolver
    local_id = nil,       -- local hero net id (false = unavailable)
    started  = nil,
    -- CHAPTER EPOCH. Incremented by the engine's chapter/map-generation events.
    -- Rows record the epoch they were last bound in, and a row may only be
    -- re-adopted by a NEW controller in a LATER epoch -- inside one chapter,
    -- an unseen hero controller is a different player, never a rebuild.
    epoch    = 0,
    refusals = 0,         -- merges declined (logged, bounded)
    -- Victim classification. `ignore_scenery` is OPT-IN: the engine's own
    -- end-screen total counts prop damage, so counting it is what MATCHES the
    -- game, and dropping it is a deliberate divergence a mod asks for.
    ignore_scenery = false,
    -- The identity hunt (whole-address-space scan + the 24k-probe blind sweep).
    -- OPT-IN, and off by default since 2026-08-20.
    --
    -- Not because it is slow -- because it is a COINCIDENCE GENERATOR. Every
    -- ally name it has ever produced, across every shipped log, came through a
    -- DIFFERENT offset chain:
    --
    --     entity+0x610 -> +0x140    "Gennadiy Tiger`s лапки"
    --     entity+0x678 -> +0x2d0    "Ovili"        (the LOCAL row)
    --     entity+0xad8 -> +0x1c0    "yjukih"
    --     entity+0x440 -> +0x2f0    "Shingaro Miamada"
    --     entity+0xff0 -> +0x8      "Yume"
    --     member+0x360 -> +0xd0     "Ovili"        (the LOCAL row)
    --     member+0x920 -> +0x2a8    "Timattttttt"  (the LOCAL row -- and WRONG)
    --     member+0x1138 -> +0x248   "gaetemp91"
    --     member+0x210              "exs1stenz"
    --
    -- Nine successes, nine offsets, no repeat. A real field answers at the SAME
    -- offset every time; this is finding whatever copy of a roster string
    -- happens to be reachable from the object, and which row it lands on is
    -- arbitrary. Session 6136 is the proof it can be wrong rather than merely
    -- unlucky: it named the LOCAL row "Timattttttt" with Ovili at the keyboard,
    -- which then consumed that name and left its real owner on a placeholder.
    -- Ghidra (2026-08-20) closed the question for two of those chains: the exe
    -- contains ZERO sites that walk entity+0x678 -> +0x2d0 or +0xad8 -> +0x1c0.
    --
    -- It also costs: 89s of blind sweeping across 12 row-passes in session 174f
    -- (~3.2M guarded reads) for zero names. But the cost is the lesser reason.
    --
    -- Turn it on with `R.damage.enable{ identity_hunt = true }` when RE'ing the
    -- identity itself. `R.damage.sweep_identity()` still works either way --
    -- that is the explicit call, and gating it would break the one entry point
    -- a person uses deliberately. To LABEL a run reliably, use player_1..4.
    identity_hunt = false,
    probe    = false,     -- log the class of the first few distinct victims
    probes   = 0,
    vprobed  = {},        -- victim entity -> already reported
    -- entity -> session id of the machine driving it (see
    -- F._dmg_note_session). Empty until an event proves the join.
    sess_by_entity = {},
    vclass   = {},        -- victim entity -> true (enemy) / false (scenery)
    vclass_n = 0,
    -- Victim SETTINGS pointer -> enemy/scenery, learned from the entities whose
    -- component map DID read. Victims of the same type share one settings
    -- object (see F._dmg_probe_victim), so one conclusive scan of a jar
    -- classifies every other jar — including the instances whose own component
    -- map cannot be read, which is the leak this table closes.
    sclass   = {},
    sclass_n = 0,
    scenery  = 0,         -- damage dropped by the filter, session-wide
}

function F._dmg_now()
    if I.now then
        local ok, t = pcall(I.now)
        if ok and type(t) == "number" then return t end
    end
    return os.time()
end

-- An entity we are willing to hand to an engine lookup: plausible, and its
-- component store at +0x8 is a plausible pointer too. Both engine helpers used
-- below dereference that store unconditionally, so this gate is what keeps a
-- stale pointer from faulting the game instead of returning false.
function F._dmg_entity_ok(e)
    if not _ptr_plausible(e) then return false end
    return _ptr_plausible(I.read_u64(e + 8))
end

-- Heroes (including remote ones) own a magical-object component; summons, pets
-- and enemies do not. Same discriminator R.give uses on a dispatcher.
function F._dmg_is_hero(e)
    if type(I.is_grant_target) ~= "function" then return false end
    -- Plausibility only. The native discriminator page-guards every read it
    -- makes (entity header, the component store at +0x8, the F14 tables) and
    -- answers false on a bad pointer, so gating it on OUR idea of a valid
    -- store is redundant — and it was wrong: a live 4-player log showed the
    -- hero's +0x8 reading as the -1 sentinel, so this gate refused every
    -- victim and `taken` stayed 0 for the whole run.
    if not _ptr_plausible(e) then return false end
    local ok, v = pcall(I.is_grant_target, e)
    return ok and v == true
end

-- Victim classification: enemy vs scenery ---------------------------------
--
-- Everything here is READS. The component array is the same one
-- Entity_GetComponentByTester (FUN_1406e3210) walks, so the offsets are the
-- engine's own; the vftable comparison is the same shape R.xp uses to find the
-- XP component. Nothing is handed to the engine, so the worst a stale offset
-- can do is answer "unknown" -- and unknown NEVER filters (fail-open, so a
-- wrong offset under-filters instead of hiding a player's real damage).

-- Rebased EnemyController vftable, or nil when the module base is unavailable.
function F._dmg_enemy_vft()
    local base = I.module_base()
    if not base or base == 0 then return nil end
    return base + (DMG.ENEMY_CTRL_VFT_VA - ENTITY_IMG_BASE)
end

--- Scan an entity's components for the enemy controller.
--- Returns nil when the entity could not be inspected at all, else a table
--- { enemy, count, slot, owner_ok } — `owner_ok` records whether the matched
--- component's back-pointer at +0x8 points at the entity, which the probe
--- reports so the back-ptr assumption is confirmed in-game rather than
--- assumed (it is NOT required for the match; see _dmg_is_enemy).
function F._dmg_scan_components(entity)
    if not _ptr_plausible(entity) then return nil, "entity implausible" end
    local slots = I.read_u64(entity + DMG.CPNT_SLOTS_OFF)
    local mask  = I.read_u64(entity + DMG.CPNT_MASK_OFF)
    -- A NULL map is an answer, not a failure: the entity owns no components at
    -- all, so it certainly owns no EnemyController. Session ec1d hit this on
    -- two of twelve victims (both 1.0-damage props) and calling them "unknown"
    -- would have let exactly the damage this filter exists for through.
    -- A non-null but implausible pointer is a genuine failed read.
    if (slots == 0 or slots == nil) and (mask == 0 or mask == nil) then
        return { enemy = false, count = 0, empty = true }
    end
    -- The decline REASON matters: session c536 reported "no components" for
    -- every enemy and there was no way to tell an empty map from a bad read.
    if not _ptr_plausible(slots) then
        return nil, ("slots=0x%x implausible"):format(slots or 0)
    end
    if type(mask) ~= "number" or mask < 0 or mask + 1 > DMG.MAX_SLOTS then
        return nil, ("mask=%s over cap"):format(tostring(mask))
    end
    -- The map is walked LINEARLY rather than hashed: the engine's own probe
    -- computes an F14 hash to find one key fast, but we are reading a handful
    -- of slots on a bounded table, and a linear pass needs no hash function to
    -- stay correct across a game patch.
    local want = F._dmg_enemy_vft()
    for i = 0, mask do
        local slot = slots + i * DMG.CPNT_SLOT_STRIDE
        local id   = I.read_u32(slot)
        if id == DMG.ENEMY_CTRL_CLASS_ID then
            local comp = I.read_u64(slot + DMG.CPNT_SLOT_PTR)
            if _ptr_plausible(comp) then
                return { enemy = true, count = mask + 1, slot = i,
                         -- Reported, never required: both are corroboration
                         -- for the class id, which is the actual test.
                         vft_ok   = want ~= nil and I.read_u64(comp) == want,
                         owner_ok = I.read_u64(comp + DMG.CPNT_OWNER_OFF) == entity }
            end
        end
    end
    return { enemy = false, count = mask + 1 }
end

--- The victim's oCEntitySettings pointer, which is its TYPE identity.
---
--- Every jar shares one settings object, every gnoll hunter shares another (the
--- victim probe logs it for exactly this reason). That makes it the key the
--- classification should be remembered under: a per-ENTITY answer has to be
--- re-derived for each instance, and an instance whose component map does not
--- read is unclassifiable forever, while the TYPE was already answered by a
--- sibling that read fine.
function F._dmg_settings(entity)
    local set = I.read_u64(entity + DMG.VICTIM_DEF_OFF)
    return _ptr_plausible(set) and set or nil
end

--- true = gameplay enemy, false = scenery/prop/mission object, nil = unknown.
---
--- Cached per victim pointer because a multi-hit ability re-classifies the
--- same target several times a frame. The cache is validated against the
--- entity's own vftable: pointers ARE recycled inside a run (an enemy dies, a
--- prop lands on its memory), and two reads to re-check beat believing a
--- stale answer.
---
--- THREE tiers, because `unknown` is fail-open and therefore expensive: a
--- victim that answers unknown has its damage counted, so a family of props
--- whose component map cannot be read lands on the board as carry damage. The
--- 2026-08-18 co-op log is that failure — one player at 11,612 hits for 613k
--- damage (59 per hit, against 353 for the top row), long runs of exactly 1.0
--- (the flat per-hit prop value), and a `scenery` column frozen for the last
--- four minutes of the run while their hit count kept climbing.
---
---   1. the per-ENTITY cache (vftable-validated), for the multi-hit case;
---   2. the per-TYPE map, keyed by the settings pointer — filled only from
---      CONCLUSIVE scans, and consulted when this entity's own scan declines;
---   3. give up and answer unknown, but stop re-scanning after
---      DMG.VICTIM_RETRIES attempts. The walk runs on the main thread inside a
---      damage detour, so re-running it per DoT tick for a whole run is not
---      free.
function F._dmg_is_enemy(entity)
    if not _ptr_plausible(entity) then return nil end
    local vft = I.read_u64(entity)
    local hit = _dmg.vclass[entity]
    if hit and hit.vft == vft then
        -- A cached `unknown` still gets a bounded number of retries: the first
        -- read may simply have caught the entity mid-construction.
        if hit.enemy ~= nil or (hit.tries or 0) >= DMG.VICTIM_RETRIES then
            -- The type map may have learned the answer from a sibling since.
            if hit.enemy == nil then
                -- `set and _dmg.sclass[set] or nil` would turn a learned
                -- SCENERY answer (false) back into nil, which is the fail-open
                -- branch this whole table exists to close.
                local set = F._dmg_settings(entity)
                if set ~= nil and _dmg.sclass[set] ~= nil then
                    return _dmg.sclass[set]
                end
            end
            return hit.enemy
        end
    end
    local scan = F._dmg_scan_components(entity)
    if _dmg.vclass_n >= DMG.VICTIM_CACHE_CAP then
        _dmg.vclass, _dmg.vclass_n = {}, 0
        hit = nil
    end
    local set = F._dmg_settings(entity)
    if scan then
        -- Conclusive. Teach the TYPE, so every sibling instance is answered
        -- even when its own component map is unreadable.
        if set and _dmg.sclass[set] == nil then
            if _dmg.sclass_n >= DMG.VICTIM_CACHE_CAP then
                _dmg.sclass, _dmg.sclass_n = {}, 0
            end
            _dmg.sclass[set] = scan.enemy
            _dmg.sclass_n = _dmg.sclass_n + 1
        end
        _dmg.vclass[entity] = { vft = vft, enemy = scan.enemy }
        _dmg.vclass_n = _dmg.vclass_n + 1
        return scan.enemy
    end
    -- Inconclusive: remember the attempt so the walk is not repeated forever,
    -- then fall back to what this victim's TYPE already answered elsewhere.
    local tries = ((hit and hit.vft == vft) and (hit.tries or 0) or 0) + 1
    _dmg.vclass[entity] = { vft = vft, enemy = nil, tries = tries }
    _dmg.vclass_n = _dmg.vclass_n + 1
    if set ~= nil and _dmg.sclass[set] ~= nil then return _dmg.sclass[set] end
    return nil
end

function F._dmg_img_rel(p)
    local base = I.module_base()
    if not p or p == 0 or not base or base == 0 or p < base then return nil end
    return p - base + ENTITY_IMG_BASE
end

--- One-shot diagnostic: what IS this victim?
---
--- Round 1 (2026-08-17, session c536) proved the plumbing and killed the
--- theory: every victim read back as oCEntity (vft 0x140f743b0) with
--- oCEntitySettings at +0x28 and real components at +0x190 — but NOT ONE of
--- twelve carried the EnemyController, and most reported no component array at
--- all. So this round reports (a) WHY the array read declined, (b) EVERY
--- component vftable, not the first six, and (c) the settings' resource path,
--- read as inline strings — that names the victim ("Gnoll_Hunter" vs
--- "Destructible_Jar") instead of leaving it an address, which is the only
--- way to tell a wrong offset from a wrong theory.
---
--- Bounded (DMG.PROBE_VICTIMS victims per process) because it runs on the MAIN
--- THREAD inside the damage detour. Reads only — no engine calls, so nothing
--- here can fault the game.
function F._dmg_probe_victim(entity, amount)
    if not _dmg.probe or _dmg.probes >= DMG.PROBE_VICTIMS then return end
    if not _ptr_plausible(entity) or _dmg.vprobed[entity] then return end
    _dmg.vprobed[entity] = true
    _dmg.probes = _dmg.probes + 1
    local n = _dmg.probes
    local scan, why = F._dmg_scan_components(entity)
    -- Image-relative, so the numbers in the log line up with the addresses in
    -- data/symbols.json across launches (ASLR moves the module, not the RVAs).
    local function hex(p)
        local v = F._dmg_img_rel(p)
        return v and string.format("0x%x", v) or "?"
    end
    local slots = I.read_u64(entity + DMG.CPNT_SLOTS_OFF)
    local mask  = I.read_u64(entity + DMG.CPNT_MASK_OFF)
    local set   = I.read_u64(entity + DMG.VICTIM_DEF_OFF)
    R.log(string.format(
        "[rsmm.damage] victim probe #%d: ent=0x%x vft=%s slots=0x%x mask=%s "
        .. "enemy=%s slot=%s vft_ok=%s owner_ok=%s settings=0x%x dmg=%.1f%s",
        n, entity, hex(I.read_u64(entity)), slots or 0, tostring(mask),
        scan and tostring(scan.enemy) or "unknown",
        scan and scan.slot and tostring(scan.slot) or "-",
        scan and scan.slot and tostring(scan.vft_ok) or "-",
        scan and scan.slot and tostring(scan.owner_ok) or "-",
        set or 0, amount or 0, why and (" declined: " .. why) or ""))
    -- Every OCCUPIED slot's class id. These decode offline against
    -- data/class_ids.json, so one log says exactly which components a fence
    -- and a gnoll each carry — the thing round 1 could not answer.
    if scan then
        local line = {}
        for i = 0, scan.count - 1 do
            local slot = slots + i * DMG.CPNT_SLOT_STRIDE
            local id   = I.read_u32(slot)
            if id and id ~= 0 and _ptr_plausible(I.read_u64(slot + DMG.CPNT_SLOT_PTR)) then
                line[#line + 1] = string.format("0x%x", id)
            end
            if #line == 8 then
                R.log(("[rsmm.damage] probe #%d class ids: %s")
                      :format(n, table.concat(line, " ")))
                line = {}
            end
        end
        if #line > 0 then
            R.log(("[rsmm.damage] probe #%d class ids: %s")
                  :format(n, table.concat(line, " ")))
        end
    end
    -- No string dump here. Reading the victim's asset path out of the settings
    -- object was tried in session ec1d and returned noise ("JAT_I", "0cbuJ^"):
    -- the path is not inline at settings+0x70, the engine reaches it through a
    -- resource handle it resolves with a call. The class ids answer the
    -- question anyway — an enemy's map holds EnemyController +
    -- CharacterController + RemoteDamageOwner + ModifierHolder, a prop's holds
    -- oCEntityCpntNetwork and nothing else — so the string hunt has no
    -- remaining job. `settings` is still logged as an identity: victims of the
    -- same TYPE share one settings pointer, which is what makes it usable as a
    -- classification cache key.
end

-- The engine's local/remote test: net component +0x130 is 0 when this machine
-- controls the entity; no net component at all means it is not replicated.
function F._dmg_entity_is_local(e)
    -- The engine's is-local byte — see _dispatcher_is_local for why it is
    -- neither the net component (crashes) nor the HUD mirror (allies have one).
    if not _ptr_plausible(e) then return false end
    return I.read_u8(e + DMG.HERO_ISLOCAL_OFF) == 1
end

-- NO net-id lookup here, deliberately.
--
-- This used to call Entity_GetNetId to key rows by a replication-stable id.
-- It crashed the game (2026-08-15, dump a97c76fe): that function calls
-- Entity_GetNetComponent, which walks the entity's component map with no
-- guard, and a hero object whose store slot holds the -1 sentinel takes the
-- process down. `is_grant_target` accepting an object proves it is a grantable
-- hero — NOT that a different subsystem can traverse it.
--
-- Nothing needed it badly enough to risk that. The replicated path already
-- carries a net id in its own payload (a plain number off the wire, no engine
-- call), the local player is identified by its HUD mirror, and cross-source
-- double counting is caught by the amount+time echo filter.

-- Net id: the identity that survives replication. nil when unavailable.
function F._dmg_net_id(_e)
    -- Intentionally always nil: see the note above. Kept as a seam so the
    -- callers read the same whether or not a SAFE net-id source ever appears.
    return nil
end

function F._dmg_label_for(slot, is_local)
    if _dmg.names[slot] then return _dmg.names[slot] end
    if is_local then
        -- The local player's real name, when Steam can tell us. "You" is the
        -- fallback, not the goal: a scoreboard full of "Player 2" is what this
        -- avoids for at least one row.
        local ok, name = pcall(R.player.name)
        if ok and type(name) == "string" then return name end
        return "You"
    end
    -- A real name from the LOBBY beats "Player 2". Cache-only (R.lobby.members
    -- never scans) because this runs on the MAIN THREAD inside a damage hook.
    -- If the roster is not resolved yet the row gets a placeholder and
    -- F._dmg_relabel fixes it as soon as the background scan lands.
    --
    -- ⚠ A name is only taken here when there is exactly ONE ally it could
    -- belong to and this is the first ally row — that case is exact by
    -- elimination. The old code matched allies in JOIN ORDER (`allies[rank]`),
    -- which is the order they first dealt damage in and has nothing to do with
    -- the lobby's order, so with 3+ players it attached real names to the wrong
    -- damage totals (reported 2026-08-19, 4p co-op: the local row was right and
    -- every ally row was shuffled). A wrong name on a real number is worse than
    -- no name, so everything else waits for the hero-id join in F._dmg_relabel.
    local ok, allies = pcall(R.lobby.allies)
    if ok and type(allies) == "table" and #allies == 1 then
        local others = 0
        for _, row in ipairs(_dmg.order) do
            if not row.is_local then others = others + 1 end
        end
        if others == 0 then return allies[1] end
    end
    return "Player " .. tostring(slot)
end

--- Re-label ally rows once the lobby roster is known.
---
--- Rows are created the instant an ally deals damage, which is usually before
--- the background scan has found the lobby. Without this they would keep the
--- "Player N" placeholder for the whole run even though the name is available
--- seconds later.
--- Find the row-side field that carries the lobby's `RequestedHero` id.
---
--- Names are matched to rows BY POSITION today: `allies[rank]`, i.e. the order
--- allies happened to first deal damage in, which is not the lobby's order and
--- is wrong as often as it is right (rows carry `label_guess` for exactly this
--- reason). The join that would be exact is the hero: every lobby member record
--- carries `RequestedHero` (+0x10), so if the row's own object holds the same
--- id at some offset, name and row line up with no guessing at all.
---
--- Rather than hand-RE that offset over several launches, let one session find
--- it: sweep each row's controller for a dword that equals one of the known
--- hero ids, and keep only the offsets where EVERY row reads a DIFFERENT known
--- id. A field that is constant across players, or that only matches for one of
--- them, is not the hero id — the discriminator is the same "must differ across
--- siblings" trick that finds abstract vtable slots.
---
--- Pure page-guarded reads, once per session, and only when a co-op lobby has
--- actually produced two identified members and two rows.
local HERO_ID_PROBE = { done = false, LO = 0, HI = 0x2000,
                        HOP_HI = 0x800,   -- how far into a hero definition
                        BUDGET = 20000,   -- probes per background tick; the deep scan is ~900k,
                                          -- so this finishes it inside a minute
                        cursor = nil, hits = nil, rows_n = 0, hop = nil,
                        off = nil, w = 4, attempts = 0, MAX_ATTEMPTS = 6 }

--- Read a hero id of width `w` at `va`.
---
--- WIDTH MATTERS. The first version read dwords only, and a hero id is a small
--- number (session ea68's lobby: 2, 4, 5, 6) — exactly the kind of value an
--- engine stores in a BYTE. A dword read over a byte field picks up whatever
--- the next three bytes hold, so the id is invisible unless those happen to be
--- zero. That sweep reported "no offset distinguishes the rows" on a real
--- 4-player run; it was never in a position to see a u8 or u16 field.
function F._dmg_read_id(va, w)
    if w == 1 then return I.read_u8(va) end
    if w == 2 then return I.read_u16 and I.read_u16(va) end
    return I.read_u32(va)
end

--- @param wide  also sweep BYTE and WORD fields. ~3x the reads, so only the
---              background tick asks for it; the boarding path stays dword-only.
function F._dmg_probe_hero_field(wide)
    if HERO_ID_PROBE.done then return end
    local okm, members = pcall(R.lobby.members)
    if not okm or type(members) ~= "table" then return end
    local ids, n = {}, 0
    for _, m in ipairs(members) do
        if m.hero_id and not ids[m.hero_id] then
            ids[m.hero_id] = m.name
            n = n + 1
        end
    end
    if n < 2 then return end
    local rows = {}
    for _, row in ipairs(_dmg.order) do
        -- Rows are keyed by controller, entity OR net id; only the pointer
        -- keys are objects we can read fields out of.
        if _ptr_plausible(row.key) then rows[#rows + 1] = row end
    end
    -- SAMPLE SIZE. Two rows is the minimum that can discriminate anything, but
    -- in a four-player lobby it is also the sample most likely to leave an
    -- unrelated field looking unique — and adopting a wrong offset MERGES two
    -- players (2026-08-18, session 29a8: four players, two rows). So wait for a
    -- third row whenever the lobby says a third player exists; a two-player
    -- lobby still adopts on two, since that is every row there will ever be.
    local need = n >= 3 and 3 or 2
    if #rows < need then return end
    -- A NEW row is new evidence: restart the scan so every offset is judged
    -- against the biggest sample available. Otherwise an offset that looked
    -- unique against three rows is adopted while a fourth would have vetoed it.
    local c = HERO_ID_PROBE.cursor
    -- A WIDER call is new evidence too. The damage path probes u32 only; the
    -- background tick probes u8/u16/u32. Resuming the narrow scan's cursor
    -- would skip the byte and word passes entirely — and a byte-sized hero id
    -- is the case this sweep exists for.
    if not c or HERO_ID_PROBE.rows_n ~= #rows
       or ((wide and true or false) and not c.wide) then
        c = { phase = 1, wi = 1, off = HERO_ID_PROBE.LO, hop = 0, ptrs = nil,
              wide = wide and true or false }
        HERO_ID_PROBE.cursor, HERO_ID_PROBE.hits = c, {}
        HERO_ID_PROBE.rows_n = #rows
    end

    local hits = HERO_ID_PROBE.hits
    -- Widths, each with its own stride: a byte field can start anywhere, a word
    -- field on any even address.
    local widths = wide and { 1, 2, 4 } or { 4 }

    -- Two phases. DIRECT looks for the id as a field on the controller —
    -- which three live four-player sessions have now reported as "no offset
    -- distinguishes the rows", at every width. HOP looks one pointer deep,
    -- because that is where an engine of this shape actually keeps it: the
    -- controller holds a pointer to the hero DEFINITION, and the id is a field
    -- of the definition. Same evidence test either way, and it is a strong one
    -- — three or more rows reading DISTINCT ids that are all on the roster, at
    -- one offset. Resumable and budgeted: the hop space is ~900k probes, which
    -- is a few minutes of background ticks, not a frame.
    -- One FIELD, not one width. A byte holding 4 reads as 4 through u8, u16 and
    -- u32 whenever the bytes after it happen to be zero, so the same location
    -- was landing in `hits` three times and every deep scan ended "ambiguous"
    -- — the one outcome that adopts nothing. Widths are tried narrowest first
    -- and the narrowest wins: a byte field read as a dword only works while the
    -- neighbours stay zero, which is exactly the trap the wide sweep was added
    -- to escape.
    local function record(off, hop, w, text)
        for _, h in ipairs(hits) do
            if h.off == off and h.hop == hop then return end
        end
        hits[#hits + 1] = { off = off, hop = hop, w = w, text = text }
    end

    -- GROUND TRUTH, free. Row 1 is the local player, Steam already told us who
    -- that is, and their lobby blob carries their RequestedHero — so any offset
    -- claiming to be the hero id MUST read exactly that id on the local row.
    --
    -- Without this the test only asks that the rows read DISTINCT ids that are
    -- on the roster, and a 0x2000-byte controller scanned at strides 1/2/4 is
    -- thousands of small-int fields, plenty of which satisfy that by accident.
    -- Session 174f did exactly that: it adopted `+0x1b60/u32`, and a sweep of
    -- the shipped exe (2026-08-20) finds ZERO reads or writes at +0x1b60 on any
    -- object base — while every offset this meter uses that IS proven in-game
    -- (+0x15c8 HP, +0x1d80 mirror, +0x1d88 is-local, +0x1db0 stats) shows 11 to
    -- 58. The engine never touches +0x1b60; it was uninitialised memory that
    -- happened to hold three roster hero ids, and every ally name on that board
    -- came from it.
    --
    -- The anchor is exactly as sound as the join it guards: `ids` maps
    -- RequestedHero -> name, so if the local row does not read the local
    -- member's RequestedHero, the join is meaningless for every other row too.
    local anchor_row, anchor_id
    do
        local okme, me = pcall(R.player.name)
        if okme and type(me) == "string" and me ~= "" then
            for _, m in ipairs(members) do
                if m.name == me and m.hero_id then anchor_id = m.hero_id break end
            end
            if anchor_id then
                for _, row in ipairs(rows) do
                    if row.is_local then anchor_row = row break end
                end
            end
        end
    end
    HERO_ID_PROBE.anchored = anchor_row ~= nil

    local function judge(read, strict)
        local seen, matched = {}, 0
        for i, row in ipairs(rows) do
            local v = read(i, row)
            -- The anchor is a veto, not a vote: a wrong value here disqualifies
            -- the offset outright, however well every other row reads.
            if anchor_row and row == anchor_row and v ~= anchor_id then
                return false
            end
            if type(v) == "number" and ids[v] then
                if seen[v] then return false end   -- two rows, one player
                seen[v] = true
                matched = matched + 1
            end
        end
        -- `strict` demands EVERY row, not just `need` of them. The deep scan
        -- searches ~900k offsets instead of 24k, so the coincidence rate is
        -- ~40x higher and "three rows agreed" stops being rare — a scan that
        -- ends ambiguous adopts nothing and the run stays on placeholders.
        -- Requiring the whole board to read a distinct roster id is a test
        -- almost nothing passes by accident.
        --
        -- ⚠ UNTESTED BRANCH. It only differs from the quorum once there are
        -- MORE rows than `need` (four players, quorum three), and a four-row
        -- fixture would not board cleanly in the spec harness. The three-row
        -- deep-scan test exercises this path with strict == need.
        return matched >= (strict and #rows or need)
    end

    -- PHASE 1, the field on the controller itself. Runs to completion in this
    -- call: it is ~24k probes, and the rest of the meter depends on the answer
    -- being ready the moment the second row boards.
    if c.phase == 1 then
        for _, w in ipairs(widths) do
            for off = HERO_ID_PROBE.LO, HERO_ID_PROBE.HI, w do
                if judge(function(_, row)
                        return F._dmg_read_id(row.key + off, w)
                    end) then
                    record(off, nil, w, string.format("+0x%x/u%d", off, w * 8))
                    if #hits >= 8 then break end
                end
            end
            if #hits >= 8 then break end
        end
        -- Anything at all here settles it, one way or the other. The deep scan
        -- below is for the case three live four-player sessions actually
        -- produced: nothing on the controller, at any width.
        c.phase = (#hits == 0) and 2 or 3
    end

    -- PHASE 2, one pointer deep. The controller holds a pointer to the hero
    -- DEFINITION and the id is a field of that — which is why every direct
    -- sweep so far reported "no offset distinguishes the rows". ~900k probes,
    -- so it is budgeted and resumable across background ticks; the evidence
    -- test is the same strong one (three or more rows reading DISTINCT roster
    -- ids at one offset).
    -- ⛔ PHASE 2 IS RE-ONLY, gated on `identity_hunt`.
    --
    -- ~900k page-guarded reads, budgeted at 20k per BACKGROUND TICK, i.e. ~45
    -- ticks of solid probing on every single run. It was ungated, and it is the
    -- heaviest thing the SDK does -- the "lags sometimes hard" the board was
    -- blamed for. What makes it waste rather than cost is that the answer is
    -- already known: three live four-player sessions found no hero id on the
    -- controller at any width, and Ghidra (2026-08-20) showed why -- there are
    -- no fixed component slots on oCEntity, so session 7068's chains were heap
    -- coincidence. The peer table now supplies names by a different route.
    --
    -- Phase 1 stays on for everyone: it is a bounded direct sweep and it is
    -- what would notice if a patch ever DID put the id back on the controller.
    if c.phase == 2 and not _dmg.identity_hunt then
        c.phase = 3
        if not HERO_ID_PROBE.deep_said then
            HERO_ID_PROBE.deep_said = true
            R.log("[rsmm.damage] hero-id deep scan skipped (no id on the "
                .. "controller on this build; enable identity_hunt to re-run it)")
        end
    end
    local budget = HERO_ID_PROBE.BUDGET
    while budget > 0 and c.phase == 2 do
        budget = budget - 1
        local w = widths[c.wi]
        -- One pointer read per OFFSET, reused across every hop and width;
        -- per-probe would triple the cost of the phase.
        if not c.ptrs then
            c.ptrs = {}
            local live = 0
            for i, row in ipairs(rows) do
                local ptr = I.read_u64(row.key + c.off)
                c.ptrs[i] = _ptr_plausible(ptr) and ptr or false
                if c.ptrs[i] then live = live + 1 end
            end
            c.live = live
        end
        if c.live >= need
           and c.live == #rows
           and judge(function(i)
                   local ptr = c.ptrs[i]
                   return ptr and F._dmg_read_id(ptr + c.hop, w) or nil
               end, true) then
            record(c.off, c.hop, w, string.format("+0x%x -> +0x%x/u%d",
                                                  c.off, c.hop, w * 8))
        end
        c.hop = c.hop + w
        if c.hop > HERO_ID_PROBE.HOP_HI then
            c.hop, c.wi = 0, c.wi + 1
            if c.wi > #widths then
                c.wi, c.ptrs = 1, nil
                c.off = c.off + 8                  -- pointer slots are aligned
                if c.off > HERO_ID_PROBE.HI then c.phase = 3 end
            end
        end
        if #hits >= 8 then c.phase = 3 end
    end
    -- Still scanning: say nothing. The version that re-ran the whole sweep
    -- every tick logged the same "no offset distinguishes the rows" line each
    -- time, which buried the log without adding one fact.
    if c.phase <= 2 then return end
    HERO_ID_PROBE.cursor = nil

    local known = {}
    for id, nm in pairs(ids) do known[#known + 1] = string.format("%s=%d", nm, id) end
    table.sort(known)
    -- ADOPT the offset, do not just report it. A confirmed hero id is the only
    -- identity a player keeps across a CHAPTER TRANSITION: the engine builds a
    -- fresh hero controller for the next chapter, so rows keyed by the
    -- controller pointer fork — the same player appears twice, the slot counter
    -- runs past the player count ("Player 6", "Player 7"), and the abandoned
    -- rows sit at 0.0 dps for the rest of the run. That is exactly what the
    -- 2026-08-17 evening log shows: seven rows for a four-player lobby, "Juice"
    -- twice, both marked as the local player.
    --
    -- Only an UNAMBIGUOUS sweep is adopted. With two rows several offsets can
    -- coincidentally hold two distinct known ids; keying identity on the wrong
    -- one would merge two different players into one row, which is worse than
    -- the duplicate it fixes. Ambiguity re-arms the probe instead: a later
    -- sweep with more rows narrows it.
    if #hits == 1 then
        HERO_ID_PROBE.off, HERO_ID_PROBE.w = hits[1].off, hits[1].w
        HERO_ID_PROBE.hop = hits[1].hop
        HERO_ID_PROBE.done = true
        HERO_ID_PROBE.text = hits[1].text   -- so a withdrawal can name it
        -- BACKFILL every row that was boarded before the identity existed.
        -- The sweep cannot run until two rows and two named lobby members are
        -- in hand, so the FIRST row — often an ally, since the sweep fires when
        -- the second player deals damage — would otherwise carry no hero id and
        -- fork at the next chapter anyway. That is the residual duplicate the
        -- first version of this fix would still have produced.
        F._dmg_backfill_ids()
    else
        HERO_ID_PROBE.done = false
        HERO_ID_PROBE.attempts = (HERO_ID_PROBE.attempts or 0) + 1
        if HERO_ID_PROBE.attempts >= HERO_ID_PROBE.MAX_ATTEMPTS then
            HERO_ID_PROBE.done = true          -- give up; pointer keys only
        end
    end
    R.log(("[rsmm.damage] hero-id field probe: %d row(s), lobby ids {%s} -> %s")
          :format(#rows, table.concat(known, ", "),
                  #hits == 1 and (hits[1].text .. " ADOPTED as the row identity")
                  or (#hits > 1
                      and ("ambiguous (" .. (function()
                              local ts = {}
                              for _, h in ipairs(hits) do ts[#ts + 1] = h.text end
                              return table.concat(ts, " ")
                          end)() .. "), retrying")
                      or ("no offset distinguishes the rows (widths tried: %s)")
                         :format(wide and "u8 u16 u32" or "u32"))))
end

--- Re-check the adopted hero-id offset against the CURRENT board.
---
--- The probe adopts on the first sample big enough to discriminate (three rows
--- when the lobby seats four) and then sets `done`, whose first act is to make
--- the probe return immediately. So a FOURTH row — the one piece of evidence
--- that could still veto the offset — arrives after the decision and is never
--- consulted. Session 174f: `+0x1b60/u32` adopted at 17:39:54 on three rows,
--- row 4 boarded at 17:40:11, and the offset was never questioned again.
---
--- Withdrawing matters more than mislabelling suggests: `by_hero` is also the
--- chapter-change rebind key, so a wrong identity MERGES two players' rows at
--- the next boundary, which deletes a player's damage rather than misnaming it.
---
--- Cheap: one guarded read per row, on the background tick.
function F._dmg_recheck_hero_field()
    if not HERO_ID_PROBE.off then return end
    local okm, members = pcall(R.lobby.members)
    if not okm or type(members) ~= "table" or #members == 0 then return end
    local ids, anchor_id = {}, nil
    for _, m in ipairs(members) do
        if m.hero_id and m.name then ids[m.hero_id] = m.name end
    end
    local okme, me = pcall(R.player.name)
    if okme and type(me) == "string" and me ~= "" then
        for _, m in ipairs(members) do
            if m.name == me and m.hero_id then anchor_id = m.hero_id break end
        end
    end
    -- Only POSITIVE contradictions count. A row whose fields are not live yet
    -- reads nil, and nil is not evidence against the offset.
    local seen, why = {}, nil
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) then
            local v = F._dmg_hero_id(row.key)
            if type(v) == "number" then
                if row.is_local and anchor_id and v ~= anchor_id then
                    why = ("the local row reads hero %d but this machine's "
                           .. "player is hero %d"):format(v, anchor_id)
                elseif seen[v] then
                    why = ("rows %d and %d both read hero %d"):format(
                        seen[v], row.slot, v)
                elseif not ids[v] then
                    why = ("row %d reads hero %d, which is nobody on the "
                           .. "roster"):format(row.slot, v)
                end
                seen[v] = row.slot
            end
        end
        if why then break end
    end
    if not why then return end

    R.log(("[rsmm.damage] WITHDRAWING the hero-id offset %s: %s. Every name it "
           .. "handed out is unproven, so those rows go back to placeholders.")
          :format(HERO_ID_PROBE.text or "?", why))
    HERO_ID_PROBE.off, HERO_ID_PROBE.hop, HERO_ID_PROBE.w = nil, nil, nil
    HERO_ID_PROBE.text, HERO_ID_PROBE.done = nil, false
    HERO_ID_PROBE.cursor, HERO_ID_PROBE.hits, HERO_ID_PROBE.rows_n = nil, {}, nil
    _dmg.by_hero = {}
    for _, row in ipairs(_dmg.order) do
        row.hero_id = nil
        -- A name the SWEEP proved (`row.player`) or one the player configured
        -- stands; only the hero-join's guesses are taken back.
        if not row.player and not _dmg.names[row.slot] then
            row.label = F._dmg_label_for(row.slot, row.is_local)
            row.label_guess = false
        end
    end
end

--- Give every row an identity it is missing. Rows boarded before the sweep
--- adopted an offset have none, and a row without one forks at the next
--- chapter — so this runs when the offset lands AND on the tick, because a
--- controller's fields are not always live the first time it is seen.
function F._dmg_backfill_ids()
    if not HERO_ID_PROBE.off then return end
    for _, r in ipairs(_dmg.order) do
        if not r.hero_id and _ptr_plausible(r.key) then
            r.hero_id = F._dmg_hero_id(r.key)
            if r.hero_id then _dmg.by_hero[r.hero_id] = r end
        end
    end
end

--- The player's identity, stable across chapter transitions. nil until the
--- sweep above has confirmed an offset, or when the value read there is not a
--- hero id the lobby knows about (a re-created controller can be read before
--- its fields are live — the same "not live yet" window hero-capture handles).
function F._dmg_hero_id(hero)
    local off = HERO_ID_PROBE.off
    if not off or not _ptr_plausible(hero) then return nil end
    local base = hero
    -- An adopted HOP offset means the id lives in the object the controller
    -- points at (the hero definition), not on the controller itself.
    if HERO_ID_PROBE.hop then
        base = I.read_u64(hero + off)
        if not _ptr_plausible(base) then return nil end
        off = HERO_ID_PROBE.hop
    end
    local id = F._dmg_read_id(base + off, HERO_ID_PROBE.w)
    if type(id) ~= "number" or id <= 0 or id >= 0x1000 then return nil end
    -- Cross-check against the roster when there is one: the offset was chosen
    -- from a two-row sample, so a value that is not a known hero id means the
    -- field has been re-used and the identity must not be trusted.
    local ok, members = pcall(R.lobby.members)
    if ok and type(members) == "table" and #members > 0 then
        for _, m in ipairs(members) do
            if m.hero_id == id then return id end
        end
        return nil
    end
    return id
end

-- Identity by the player's OWN NAME, found in their controller's memory graph.
--
-- The hero-id join needs the lobby's `RequestedHero` to sit as a dword on the
-- hero controller, and a four-player playtest (2026-08-19, session 5a1d) proved
-- it does not: `4 row(s), lobby ids {...} -> no offset distinguishes the rows`,
-- repeated all run, every ally on a "Player N" placeholder. A placeholder is
-- honest but it is not the point of a damage meter — "who did 3252" has to have
-- an answer.
--
-- So stop hunting the id and hunt the thing already in hand: the gamertag. A
-- player's display name appearing inside their own controller — inline, behind
-- a pointer, or as the heap data of an MSVC std::string — is SELF-EVIDENT
-- identity. It needs no cross-row corroboration the way a bare integer does,
-- because no unrelated field coincidentally spells "Keif_Buddings". One row
-- identified also yields the offset chain, which names every later row in two
-- reads.
--
-- Bounded, resumable, background-thread only: a fixed read budget per tick, a
-- cursor that survives across ticks, and page-guarded reads throughout (a bad
-- address returns nil, it does not fault).
-- (a field on `F`, not a local: rsmm.lua sits at Lua's 200-live-locals cap
-- for the module chunk — one more `local` here fails to COMPILE the whole SDK.)
F._own = {
    WIN = 0x2000,        -- how far into an object a name may sit
    HOP = 0x400,         -- and how far into an object one pointer away. 0x100
                         -- was too shallow to reach a name held deep inside the
                         -- HUD mirror (+0x1d80) or the stats block (+0x1db0),
                         -- which are the two objects on a controller most
                         -- likely to carry one.
    STRIDE = 8,
    BUDGET = 24000,      -- probes per tick. A full row is ~264k over both
                         -- bases, so at 6000 a four-player board took ~3
                         -- minutes to even finish its FIRST pass — longer than
                         -- session fb4f's whole run, which is why nothing was
                         -- named. The reads are page-guarded and cheap.
    -- Every { base = 1|2, off = n, hop = n|nil } that has named a row, learned
    -- on THIS board. Deliberately EMPTY at startup.
    --
    -- It was briefly seeded with the two chains session 7068 recorded
    -- (`entity+0x678 -> +0x2d0`, `entity+0xad8 -> +0x1c0`) on the theory that an
    -- offset chain is a property of the build. Ghidra says otherwise, and the
    -- theory was wrong because those are not offsets into anything:
    --
    --   * Across all 65,347 .pdata functions of the shipped exe there is not a
    --     single site that loads [X+0x678] and then reads [+0x2d0], nor one for
    --     [X+0xad8] -> [+0x1c0]. (The same sweep does find real chains, e.g.
    --     [X+0xb8] -> [+0x20], so it is not blind.)
    --   * +0xad8 is never touched on any register that also walks an entity.
    --   * The one qword-pointer write at +0x678 near entity-shaped code belongs
    --     to `oe::dt::EntityCpntRecapBookPageSettings::~dtor` (FUN_140419aa0),
    --     an unrelated UI settings class; the other site stores a FLOAT there.
    --   * There are no fixed component slots on oCEntity to be found anyway:
    --     Entity_GetNetComponent reaches components through a hash map at
    --     entity+0x5e8/+0x5f0/+0x600 keyed by class id. See its symbol note.
    --
    -- So session 7068's two chains were heap COINCIDENCE — a pointer that
    -- happened to sit at that offset in that run's hero entity, landing that
    -- far before a string that happened to hold the id. Seeding a coincidence
    -- makes it a prior that runs BEFORE every corroborating check, on every
    -- board, forever. A chain is only trustworthy once it has been observed on
    -- THIS board and survived the one-owner rule below.
    chains = {},
    addrs = nil,         -- where each roster name lives in memory
    addrs_key = nil,     -- the roster those addresses were scanned for
    MAX_HITS = 20000,    -- copies of one needle worth collecting. Both 24 and
                         -- 512 were CEILINGS, not limits: sessions 314f and
                         -- a84f truncated every needle, and a truncated scan
                         -- keeps whichever copies sit LOWEST in the address
                         -- space — never the game-heap object that owns the
                         -- player. A peer id turns up in hundreds of network
                         -- buffers, so the cap has to be far above that or it
                         -- silently decides the answer.
    -- Bytes of address space one tick may examine. `mem_find`'s own default
    -- is 512 MB, which is a debug-probe figure: it is seconds of wall time and
    -- the player feels it as a stall. The lobby sweep has run at 48 MB a tick
    -- all along without a single report, so this sits beside it. The sweep
    -- takes MINUTES to cross the address space at this rate, and that is the
    -- intended trade — it runs on the background thread against a board the
    -- guessed names have already labelled, so finishing sooner buys nothing a
    -- player can see, while finishing louder costs a frame.
    SLICE_MB = 48,
    cursor_va = 0,       -- resume address for the needle at the head of `queue`
    hits_n = 0,          -- hits collected for THAT needle, across its slices
    PAGE = 12,           -- address index granularity (4 KiB), see _dmg_index
    -- There is no time-based rescan, and the `SCAN_EVERY`/`scan_at` pair that
    -- claimed to be one was set and never read by anything. What actually
    -- bounds the scan is `addrs_key` (the roster) plus the chapter epoch, which
    -- drops the cache in F._dmg_next_epoch — a timer would only reintroduce
    -- the periodic address-space walk this all exists to avoid.
    queue = nil,         -- needles still to scan, one per tick
    TRIES = 4,           -- full sweeps per row before it is given up on
    RETRY_AFTER = 20,    -- seconds between them. A chapter is shorter than
                         -- the old 45s, so a row could miss its whole run.
    cursor = nil,        -- { row = <row>, base = 1, off = 0, hop = nil }
    found = 0, swept = 0,
}

--- Where in the process does each player's identity string actually live?
---
--- The blind sweep asks the wrong question. It walks ~264k offsets PER ROW
--- reading a string at every one, which is ~44s of background ticks per row —
--- session fb4f's whole run finished before the first pass did, and nothing
--- was named. The engine can answer the question directly: `mem_find` is a
--- native scan for a byte pattern, so ONE scan per player yields every address
--- that player's peer id is stored at.
---
--- That turns identification into arithmetic. A row owns a name when one of
--- its pointers lands just before one of that name's addresses — the chain
--- session 7068 found by brute force (`entity+0x678 -> +0x2d0`) is exactly the
--- statement "a pointer at entity+0x678 points 0x2d0 bytes before the string".
--- Testing that costs 2048 pointer reads and some subtraction, not 264k string
--- reads, and it is the same evidence.
---
--- Cached against the roster: re-scanning the address space every tick would
--- be far worse than the sweep it replaces.
function F._dmg_find_needles(names)
    if type(I.mem_find) ~= "function" then return nil end
    -- PEER IDS ONLY. A gamertag turns up in chat, the friends list and every
    -- piece of UI text that mentions the player, so scanning for it doubles
    -- the work to produce the noisiest half of the results. The id is not
    -- human-facing, so its copies are the objects that actually own the
    -- player — and it is what named a row in session 314f.
    local keys = {}
    for needle, m in pairs(names) do
        if needle ~= m.name then keys[#keys + 1] = needle end
    end
    table.sort(keys)
    local key = table.concat(keys, "\1")
    if F._own.addrs_key == key and not F._own.queue then return F._own.addrs end
    if #keys == 0 then return nil end

    -- ONE needle per tick, and ONE SLICE of that needle per tick. Each scan is
    -- a native walk of the whole user address space; eight back to back on a
    -- single tick is the stutter session a84f reported, and even ONE unsliced
    -- call is gigabytes of ReadProcessMemory holding the process VM lock —
    -- session a14f's two hard hitches were this call, at the 512 MB default,
    -- three needles at 11:37:03 and two more at 11:40:01.
    --
    -- Dropping `mem_find`'s second return was also a CORRECTNESS bug, and the
    -- quieter one. That value is the resume address, and the whole reason the
    -- native side has one. Without it the sweep stopped dead at the default
    -- budget and never continued, so it searched the low heap — where Lua's
    -- own strings live — and never reached the game's allocations at all.
    -- `capped` counts hits, not bytes, so the log called that a clean scan.
    -- It is the exact failure NAME_SCAN_MB documents for sessions 5736/274f,
    -- reintroduced one layer up, and it is why this scan has never once
    -- claimed a row.
    if F._own.addrs_key ~= key then
        F._own.addrs_key, F._own.addrs = key, {}
        F._own.queue, F._own.capped = {}, 0
        -- The slice cursor belongs to the needle at the head of the queue
        -- being dropped here. Left behind, the first needle of the NEXT
        -- roster resumes from a stranger's address and never scans anything
        -- below it. This is also the chapter-epoch path: `_dmg_next_epoch`
        -- clears `addrs_key`, so the very next call lands in this branch.
        F._own.cursor_va, F._own.hits_n = 0, 0
        for i = #keys, 1, -1 do F._own.queue[#F._own.queue + 1] = keys[i] end
    end
    local q = F._own.queue
    if q and #q > 0 then
        -- PEEK, don't pop: the needle stays at the head until its sweep
        -- reaches the end of the address space. Popping here is what made the
        -- unsliced call look complete.
        local needle = q[#q]
        local left = F._own.MAX_HITS - (F._own.hits_n or 0)
        local nxt = 0
        if left <= 0 then
            F._own.capped = (F._own.capped or 0) + 1
        else
            local ok, hits, resume = pcall(I.mem_find, needle, left,
                                           F._own.SLICE_MB,
                                           F._own.cursor_va or 0)
            if ok and type(hits) == "table" then
                local m = names[needle]
                for _, va in ipairs(hits) do
                    if va and va > 0x10000 then
                        F._own.addrs[#F._own.addrs + 1] = { va = va,
                                                            name = m.name }
                        F._own.hits_n = (F._own.hits_n or 0) + 1
                    end
                end
                nxt = (type(resume) == "number") and resume or 0
                if F._own.hits_n >= F._own.MAX_HITS then
                    F._own.capped, nxt = (F._own.capped or 0) + 1, 0
                end
            end
            -- A raise leaves nxt at 0, which retires the needle. Carrying the
            -- cursor forward instead would re-raise on the same slice every
            -- tick for the rest of the run.
        end
        F._own.cursor_va = nxt
        if nxt == 0 then
            table.remove(q)
            F._own.hits_n = 0
        end
        if #q == 0 then
            F._own.queue = nil
            -- Say when a needle hit the ceiling. A truncated scan looks
            -- exactly like a healthy one in the totals, which is how two
            -- sessions were spent chasing the wrong thing.
            R.log(("[rsmm.damage] identity scan: %d needle(s) -> %d "
                   .. "address(es) in memory%s"):format(
                #keys, #F._own.addrs,
                (F._own.capped or 0) > 0
                    and (", %d TRUNCATED at the %d cap"):format(
                        F._own.capped, F._own.MAX_HITS) or ""))
        end
    end
    return F._own.addrs
end

--- Index the found addresses by page.
---
--- With the cap raised, a four-player lobby can have a couple of thousand
--- addresses, and the naive test (every pointer against every address) is
--- 2048 x 2000 comparisons per row. Bucketing by page makes each test a
--- constant handful: a string within +0x400 of a pointer is on that pointer's
--- page or the next one.
function F._dmg_index(addrs)
    -- MEMOISED on the address list's identity and length. `addrs` is
    -- F._own.addrs, which is append-only while the needle queue drains and
    -- frozen for the rest of the run -- but the caller runs on every
    -- background tick, and with `guess_names` on a row keeps `row.player ==
    -- nil` even once it has a label, so "every tick" means "for the whole
    -- session". Rebuilding a couple of thousand buckets each time is pure
    -- waste, and it is waste that scales with the number of players.
    if F._own.page_src == addrs and F._own.page_n == #addrs then
        return F._own.page_idx
    end
    local by_page = {}
    for _, a in ipairs(addrs) do
        local k = a.va >> F._own.PAGE
        local b = by_page[k]
        if not b then b = {}; by_page[k] = b end
        b[#b + 1] = a
    end
    F._own.page_src, F._own.page_n, F._own.page_idx = addrs, #addrs, by_page
    return by_page
end

--- Every roster name this row's own memory reaches, as a set.
---
--- Direct (the string is inside the row's object) or one hop (a pointer in the
--- row's object lands within +0x%x of it). Both are the same test against a
--- known address, so neither costs a string read.
function F._dmg_row_names(row, by_page)
    local found, n = {}, 0
    -- STRUCTURED, not a log string. `_dmg_chain_name` replays a
    -- {base, off, hop} in two reads and names every later row for free, but it
    -- can only do that if this pass hands the chain back as numbers. Recording
    -- the formatted text alone left that replay unreachable — `if chain.base`
    -- was false for every chain this path found — so a board with one unnamed
    -- row paid for a full address-space scan every tick for the rest of the
    -- session. The names came out right; the game hitched for the whole run.
    local function note(name, how, base, off, hop)
        if not found[name] then
            found[name] = { how = how, base = base, off = off, hop = hop }
            n = n + 1
        end
    end
    -- Every address within `span` bytes after `from`, via the page index.
    -- `mk(d)` returns the human text AND the chain that produced it.
    local function near(from, span, mk)
        local first, last = from >> F._own.PAGE, (from + span) >> F._own.PAGE
        for k = first, last do
            local b = by_page[k]
            if b then
                for _, a in ipairs(b) do
                    if a.va >= from and a.va - from <= span then
                        note(a.name, mk(a.va - from))
                    end
                end
            end
        end
    end
    local bases = { { row.key, "ctrl" } }
    local ent = I.read_u64(row.key + 0x08)
    if _ptr_plausible(ent) then bases[#bases + 1] = { ent, "entity" } end
    -- `bi` IS `chain.base`: 1 = the controller (row.key), 2 = the entity at
    -- row.key+0x08 — the same two bases `_dmg_chain_name` re-derives.
    for bi, b in ipairs(bases) do
        local base, tag = b[1], b[2]
        near(base, F._own.WIN, function(d)
            return ("%s+0x%x"):format(tag, d), bi, d, nil
        end)
        for off = 0, F._own.WIN, 8 do
            local p = I.read_u64(base + off)
            if _ptr_plausible(p) then
                near(p, F._own.HOP, function(d)
                    return ("%s+0x%x -> +0x%x"):format(tag, off, d), bi, off, d
                end)
            end
        end
    end
    return found, n
end

--- Name every row that can be named, in one pass. Background thread only.
---
--- The correctness rule is the same one the whole meter is built on: a name is
--- only used when it can belong to exactly ONE row. A string that several rows
--- reach is a shared table (the lobby roster, a UI list), not an owner — and
--- claiming from it would put a real player's damage under someone else's
--- name, which is the bug this all started with.
function F._dmg_probe_owner_fast()
    local names, _ = F._dmg_name_set()
    if not names or not I.read_u64 then return false end
    -- Nothing to identify, nothing to scan for. Without this the address
    -- space is walked again on every roster change of a lobby whose rows are
    -- all already named.
    local wanted = false
    for _, row in ipairs(_dmg.order) do
        if not row.player and _ptr_plausible(row.key) then wanted = true break end
    end
    if not wanted then return false end

    local addrs = F._dmg_find_needles(names)
    if not addrs or #addrs == 0 then return false end

    local by_page = F._dmg_index(addrs)
    local rows, cand = {}, {}
    for _, row in ipairs(_dmg.order) do
        if not row.player and _ptr_plausible(row.key) then
            local found, n = F._dmg_row_names(row, by_page)
            if n > 0 then
                rows[#rows + 1] = row
                cand[row] = found
            end
        end
    end
    if #rows == 0 then return false end

    -- How many rows reach each name. More than one = shared, so it identifies
    -- nobody.
    local owners = {}
    for _, row in ipairs(rows) do
        for name in pairs(cand[row]) do owners[name] = (owners[name] or 0) + 1 end
    end
    local named = false
    for _, row in ipairs(rows) do
        local only, hit, count = nil, nil, 0
        for name, h in pairs(cand[row]) do
            if owners[name] == 1 then only, hit, count = name, h, count + 1 end
        end
        if count == 1 then
            if F._dmg_claim(row, names, only, hit.how) then
                -- The chain, not just its text. This is the whole point of the
                -- scan: one row identified yields the offsets that name every
                -- later row — and every later RUN — in two reads.
                F._dmg_note_chain(hit.base, hit.off, hit.hop, hit.how)
                named = true
            end
        elseif count > 1 then
            R.log(("[rsmm.damage] row %d reaches %d different players' "
                   .. "identities — shared memory, so it names nobody")
                  :format(row.slot, count))
        end
    end
    return named
end

--- Remember a chain that produced a hit, once.
function F._dmg_note_chain(base, off, hop, text)
    for _, ch in ipairs(F._own.chains) do
        if ch.base == base and ch.off == off and ch.hop == hop
           and ch.text == text then return end
    end
    F._own.chains[#F._own.chains + 1] = { base = base, off = off, hop = hop,
                                          text = text }
end

--- The roster as a printable list of NAMES. (Distinct from
--- _dmg_roster_text, which formats a members table the caller already has.)
---
--- Deliberately not the needle set: the sweep searches for peer ids as well as
--- gamertags, and session 7068's dead-end line printed four raw EOS GUIDs
--- alongside the four players, which reads as a corrupt roster.
function F._dmg_roster_names()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return "?" end
    local t, ids = {}, 0
    for _, m in ipairs(members) do
        t[#t + 1] = tostring(m.name)
        if type(m.eos) == "string" and #m.eos > 0 then ids = ids + 1 end
    end
    table.sort(t)
    -- The COUNT of peer ids, because a sweep with no needle to look for and a
    -- sweep that looked and found nothing are the same log line otherwise —
    -- which is exactly why session fb4f could not be explained. Printing the
    -- ids themselves (the first version) made the roster read as corrupt.
    return ("%s — %d of %d carry a peer id"):format(
        table.concat(t, ", "), ids, #members)
end

--- The lobby names as a lookup set, plus the longest one. nil when the roster
--- is still empty (solo, or names have not arrived yet).
function F._dmg_name_set()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    local set, longest = {}, 0
    local function needle(text, m)
        if type(text) ~= "string" or #text == 0 or #text > 64 then return end
        -- Every needle resolves to the member, and every hit is reported under
        -- the member's NAME — a row must never end up labelled with a peer id.
        set[text] = m
        if #text > longest then longest = #text end
    end
    for _, m in ipairs(members) do
        if type(m.name) == "string" and #m.name > 0 then
            needle(m.name, m)
            needle(m.eos, m)
        end
    end
    if longest == 0 then return nil end
    return set, longest
end

--- Does a known player name start at `va`? Returns the name, or nil.
---
--- One `read_cstr` per address, not one per candidate name: the read stops at
--- the first NUL, so a stored name comes back whole and the set does the rest.
--- That keeps a 70k-probe sweep to 70k reads rather than 70k x roster size.
function F._dmg_name_at(va, names, longest)
    if not I.read_cstr or not _ptr_plausible(va) then return nil end
    local s = I.read_cstr(va, longest + 1)
    -- Return the member's NAME, not the string that matched: the needle may
    -- have been their peer id.
    if type(s) == "string" and names[s] then return names[s].name end
    return nil
end

--- Read the adopted chain on `row`. Two reads once the chain is known.
function F._dmg_chain_name(row, chain, names, longest)
    local base = chain.base == 2 and I.read_u64(row.key + 0x08) or row.key
    if not _ptr_plausible(base) then return nil end
    if not chain.hop then return F._dmg_name_at(base + chain.off, names, longest) end
    local p = I.read_u64(base + chain.off)
    if not _ptr_plausible(p) then return nil end
    return F._dmg_name_at(p + chain.hop, names, longest)
end

--- Would some OTHER unnamed row resolve this same chain to this same name?
---
--- The blind sweep walks ONE row at a time, so on its own it has no way to
--- tell an owner from a shared table — it claimed whatever it reached first,
--- and `_dmg_claim`'s duplicate refusal then only stopped the SECOND row, long
--- after the first had taken a name that may not be its own. That is the same
--- failure `_dmg_probe_owner_fast`'s one-owner rule and the chain replay's both
--- refuse, and the sweep undercut both of them by running after them.
---
--- Costs two pointer reads per other row, and only at the instant of a claim.
function F._dmg_chain_shared(row, chain, name, names, longest, me)
    for _, other in ipairs(_dmg.order) do
        if other ~= row and not other.player and _ptr_plausible(other.key) then
            -- The local row is never a rival claimant for somebody else's name:
            -- Steam already said who is at this keyboard, so a gamertag inside
            -- YOUR object (session 6136) must not make the real owner's name
            -- look shared and strand that player on a placeholder.
            local rival = not (other.is_local and type(me) == "string"
                               and me ~= "" and name ~= me)
            if rival
               and F._dmg_chain_name(other, chain, names, longest) == name then
                return true
            end
        end
    end
    return false
end

--- Bind `row` to the lobby member called `name`.
---
--- Refuses a name another row already holds. Two rows resolving to one player
--- means the chain is reading something shared (a lobby array, the local
--- player's own copy), and merging two players is the one failure that DELETES
--- damage from the board — always fail toward the placeholder.
--- Who is at this keyboard, remembered.
---
--- `R.player.name` is a Steam call and it can come back empty on a background
--- tick even when it answered a moment earlier on the main thread. Session
--- d536 is that window: the local row's LABEL was resolved at boarding (Steam
--- fine), then every sweep tick asked again, got nothing, and so skipped the
--- steam claim -- which left row 1 unclaimed and the duplicate guard with
--- nothing to compare against. An ally then claimed "Ovilli" off a global the
--- engine hangs on every entity, and the board showed two of them.
---
--- So the answer is cached the first time anyone gets it, and the LOCAL ROW's
--- own label is the fallback: it was resolved from Steam already, and it is
--- the one name on the board that was never inferred.
function F._dmg_me()
    if _dmg.me then return _dmg.me end
    local ok, nm = pcall(R.player.name)
    if ok and type(nm) == "string" and nm ~= "" and nm ~= "You" then
        _dmg.me = nm
        return nm
    end
    for _, row in ipairs(_dmg.order) do
        if row.is_local then
            local lbl = row.player or row.label
            if type(lbl) == "string" and lbl ~= "" and lbl ~= "You"
               and not lbl:match("^Player %d+$") then
                _dmg.me = lbl
                return lbl
            end
        end
    end
    return nil
end

function F._dmg_claim(row, names, name, how)
    local m = names[name]
    -- Steam is authoritative for the LOCAL row, and does not depend on the
    -- roster sweep having seen that player. Session d536 is the roster WITHOUT
    -- the local member in it, so `names[me]` was nil, the steam claim never
    -- ran, `row.player` stayed unset on row 1 -- and the duplicate guard below,
    -- which is what stops a second row taking a name, had nothing to compare
    -- against. Two rows finished the run labelled "Ovilli".
    if not m and not (row.is_local and how == "steam") then return false end
    -- The local row is the ONE row whose name is not an inference: Steam told
    -- us. Session 6136 renamed it anyway, off a stack frame masquerading as a
    -- member object. The visible label survived (the local row keeps its Steam
    -- name below), but `row.player` did not — and that CONSUMED a real
    -- player's name: row 3 was refused "Timattttttt" twice as a duplicate and
    -- finished the run as "Player 3". A wrong claim here costs two rows.
    if row.is_local then
        local me = F._dmg_me()
        if me and me ~= name then
            R.log(("[rsmm.damage] refusing row %d -> %q (%s): that row is this "
                   .. "machine's player, and Steam calls them %q")
                  :format(row.slot, name, how, me))
            return false
        end
    end
    -- AND THE MIRROR: an ally may never be named after this machine's player.
    -- There is exactly one local player and Steam names them before any sweep
    -- runs, so a NON-local row resolving to that name is proof the chain is
    -- shared -- the local player's name is reachable from a global the engine
    -- hangs off every entity -- not proof of ownership. Session d536 claimed
    -- `entity+0xcc8 -> +0x39b` for an ally that way and the board showed two
    -- "Ovilli" rows while the ally's real name, InsertCoin2Start, vanished.
    --
    -- This does not depend on the local row having been claimed first, which
    -- is the whole point: the ordering is what failed.
    if not row.is_local then
        local me = F._dmg_me()
        if me and me == name then
            if not _dmg.self_claim_said then
                _dmg.self_claim_said = true
                R.log(("[rsmm.damage] refusing row %d -> %q (%s): that is this "
                       .. "machine's player and this row is not them, so the "
                       .. "chain is shared memory, not ownership")
                      :format(row.slot, name, how))
            end
            return false
        end
    end
    for _, other in ipairs(_dmg.order) do
        if other ~= row and other.player == name then
            R.log(("[rsmm.damage] refusing row %d -> %q (%s): row %d already "
                   .. "holds that name"):format(row.slot, name, how, other.slot))
            return false
        end
    end
    row.player = name
    if m and m.hero_id and not row.hero_id then
        row.hero_id = m.hero_id
        _dmg.by_hero[m.hero_id] = row
    end
    -- The local row keeps the name Steam gave it; they are the same person and
    -- the Steam persona is the one the player recognises as themselves.
    if not row.is_local then
        row.label = name
        row.label_guess = false
    end
    F._own.found = F._own.found + 1
    R.log(("[rsmm.damage] row %d IS %q (%s)%s"):format(
        row.slot, name, how, row.is_local and " [local]" or ""))
    return true
end

--- Advance the owner-name sweep by one budget's worth. Background thread only.
function F._dmg_probe_owner()
    local names, longest = F._dmg_name_set()
    if not names or not I.read_cstr or not I.read_u64 then return end

    -- The local row is not a mystery: Steam named it before the run started.
    -- Leaving it unclaimed made every sweep spend a quarter of its budget, and
    -- four retries, re-deriving a fact already in hand — session 314f swept
    -- row 1 three times for nothing.
    -- No `names[me]` gate. The roster is a SWEEP result and it drops members
    -- that stop being re-parsed, so the local player is routinely absent from
    -- it (session d536, and the two "not in this lobby - dropped" lines in
    -- a14f). Gating the local claim on the roster meant the one name the meter
    -- knows for certain went unclaimed, which in turn disarmed the duplicate
    -- guard in `_dmg_claim`. Steam is the source here, not the roster.
    local me = F._dmg_me()
    if me then
        for _, row in ipairs(_dmg.order) do
            if row.is_local and not row.player then
                F._dmg_claim(row, names, me, "steam")
            end
        end
    end

    -- CHAINS FIRST. A chain is two pointer reads and a string compare; the
    -- scan below is a native walk of the WHOLE address space, and the lobby
    -- sweep above already documents why that is felt even from the background
    -- thread — ReadProcessMemory at that volume saturates memory bandwidth
    -- and the process VM lock, which stalls the game's threads too. Scanning
    -- first meant the cheap answer was only ever consulted after the expensive
    -- one had already been paid for, on every tick with an unnamed row.
    --
    -- ALL of them are tried, not just the last — session 7068 named two rows
    -- through two DIFFERENT chains (`entity+0x678 -> +0x2d0` and
    -- `entity+0xad8 -> +0x1c0`), so a single remembered chain would have been
    -- the wrong one for half the board.
    -- Resolve every chain against every unnamed row FIRST, claim second, under
    -- the same one-owner rule the scan uses. A chain is a GUESS about where a
    -- name lives, and two of them are now SEEDED from an older session rather
    -- than learned on this board — so if two rows resolve a chain to the SAME
    -- name, that chain is reading something shared (the lobby roster, a UI
    -- list) and it identifies nobody. Claiming row-by-row in slot order, which
    -- is what this loop used to do, would hand that name to whichever row came
    -- first: a real player's damage under another player's name, the one
    -- failure the whole meter is built to refuse.
    local cand, hits = {}, 0
    for _, chain in ipairs(F._own.chains) do
        if chain.base then
            for _, row in ipairs(_dmg.order) do
                if not row.player and _ptr_plausible(row.key) then
                    local nm = F._dmg_chain_name(row, chain, names, longest)
                    if nm then
                        local c = cand[row]
                        if not c then c = {}; cand[row] = c end
                        if not c[nm] then c[nm] = chain; hits = hits + 1 end
                    end
                end
            end
        end
    end
    -- The local row is not a claimant for anybody else's name, so it must not
    -- count as an OWNER of one either. Session 6136's gamertag sat inside the
    -- local player's own object; `_dmg_claim` already refuses to rename row 1
    -- off it, but leaving it in the tally makes the real owner's name look
    -- shared, and the player who actually owns it is then stranded on a
    -- placeholder — which is the second half of that same bug.
    if hits > 0 and me then
        for row, c in pairs(cand) do
            if row.is_local then
                for nm in pairs(c) do
                    if nm ~= me then c[nm] = nil; hits = hits - 1 end
                end
            end
        end
    end
    if hits > 0 then
        local owners = {}
        for _, c in pairs(cand) do
            for nm in pairs(c) do owners[nm] = (owners[nm] or 0) + 1 end
        end
        -- Over `_dmg.order`, not `pairs(cand)`: claim order must not depend on
        -- table iteration order, or which row wins an ambiguity changes between
        -- runs and the board stops being reproducible.
        for _, row in ipairs(_dmg.order) do
            local c = cand[row]
            if c then
                local only, chain, n = nil, nil, 0
                for nm, ch in pairs(c) do
                    if owners[nm] == 1 then only, chain, n = nm, ch, n + 1 end
                end
                if n == 1 then
                    -- Name the chain that claimed the row, so the log tells a
                    -- seeded offset that still works apart from one a scan had
                    -- to rediscover.
                    F._dmg_claim(row, names, only,
                                 "chain " .. (chain.text or "?"))
                elseif n > 1 then
                    R.log(("[rsmm.damage] row %d resolves %d different players "
                           .. "through its chains — ambiguous, so it names "
                           .. "nobody"):format(row.slot, n))
                end
            end
        end
    end

    -- Only now ask the process where the names ARE, and check which row owns
    -- each. Costs one native scan per player and 2048 pointer reads per row.
    -- `_dmg_probe_owner_fast` gates itself on there still being an unnamed
    -- row, so a board the chains finished never reaches this at all. The blind
    -- sweep below stays as the fallback for a loader without `mem_find`.
    if F._dmg_probe_owner_fast() then return end

    local c = F._own.cursor
    if not c or c.row.player or c.row.own_done or c.row.dropped then
        -- Pick the next row that has neither an identity nor a completed sweep.
        c = nil
        for _, row in ipairs(_dmg.order) do
            if not row.player and _ptr_plausible(row.key)
               and (not row.own_done
                    or (row.own_retry_at and F._dmg_now() >= row.own_retry_at)) then
                row.own_done, row.own_retry_at = false, nil
                c = { row = row, base = 1, off = 0, hop = nil }
                break
            end
        end
        F._own.cursor = c
        if not c then return end
    end

    local row = c.row
    local budget = F._own.BUDGET
    while budget > 0 do
        local base = c.base == 2 and I.read_u64(row.key + 0x08) or row.key
        if _ptr_plausible(base) then
            if c.hop == nil then
                -- Direct: the name lives in the object itself (an inline
                -- std::string, a fixed char buffer).
                local nm = F._dmg_name_at(base + c.off, names, longest)
                budget = budget - 1
                if nm then
                    local ch = { base = c.base, off = c.off, hop = nil }
                    -- Record it either way: a shared chain is still a fact
                    -- about this build, and the cross-row rule above is where
                    -- it gets judged.
                    F._dmg_note_chain(c.base, c.off, nil)
                    if F._dmg_chain_shared(row, ch, nm, names, longest, me) then
                        R.log(("[rsmm.damage] row %d reaches %q at %s, but so "
                               .. "does another unnamed row — shared memory, "
                               .. "so it names nobody"):format(row.slot, nm,
                            ("%s+0x%x"):format(
                                c.base == 2 and "entity" or "ctrl", c.off)))
                    else
                        F._dmg_claim(row, names, nm,
                            ("%s+0x%x"):format(c.base == 2 and "entity" or "ctrl", c.off))
                    end
                    F._own.cursor = nil
                    return
                end
            else
                -- One hop: the field is a pointer and the name is behind it —
                -- a `char*`, a `std::string*`, or the heap buffer of an MSVC
                -- std::string (whose data pointer sits at +0x8, which this
                -- reaches as hop 0 of that offset).
                local p = I.read_u64(base + c.off)
                if _ptr_plausible(p) then
                    local nm = F._dmg_name_at(p + c.hop, names, longest)
                    budget = budget - 1
                    if nm then
                        local ch = { base = c.base, off = c.off, hop = c.hop }
                        F._dmg_note_chain(c.base, c.off, c.hop)
                        local how = ("%s+0x%x -> +0x%x"):format(
                            c.base == 2 and "entity" or "ctrl", c.off, c.hop)
                        if F._dmg_chain_shared(row, ch, nm, names, longest, me) then
                            R.log(("[rsmm.damage] row %d reaches %q at %s, but "
                                   .. "so does another unnamed row — shared "
                                   .. "memory, so it names nobody")
                                  :format(row.slot, nm, how))
                        else
                            F._dmg_claim(row, names, nm, how)
                        end
                        F._own.cursor = nil
                        return
                    end
                else
                    c.hop = F._own.HOP        -- nothing to walk; skip the hops
                    budget = budget - 1
                end
            end
        else
            budget = budget - 1
            c.off = F._own.WIN                    -- unreadable base: end this pass
        end

        -- Cursor advance: hops, then offsets, then base, then the hop stage.
        if c.hop ~= nil then
            c.hop = c.hop + F._own.STRIDE
            if c.hop > F._own.HOP then c.hop = 0; c.off = c.off + F._own.STRIDE end
        else
            c.off = c.off + F._own.STRIDE
        end
        if c.off > F._own.WIN then
            c.off = 0
            if c.base == 1 then
                c.base = 2
            elseif c.hop == nil then
                c.base, c.hop = 1, 0       -- direct pass done; walk pointers
            else
                -- Both passes done on both bases: this controller does not
                -- reach any lobby name. Say so ONCE, with everything needed to
                -- take it further (the next step is RE, not a wider sweep).
                row.own_done = true
                row.own_tries = (row.own_tries or 0) + 1
                F._own.swept = F._own.swept + 1
                F._own.cursor = nil
                -- RETRY, do not retire. A row is swept the moment it deals its
                -- first damage, and the fields that identify it are not
                -- necessarily populated yet — session 7068 named rows 1 and 2
                -- and dead-ended rows 3 and 4, which had boarded seconds
                -- earlier. Retiring a row after one pass makes that permanent
                -- for the whole run.
                -- ⚠ UNTESTED BRANCH. Reaching it in the spec needs a full
                -- ~264k-probe pass to COMPLETE before the fixture populates
                -- the row, and a shorter pass simply continues instead. The
                -- behaviour it guards (a row is not retired after one dead
                -- end) is covered; the countdown itself is not.
                if row.own_tries < F._own.TRIES then
                    row.own_retry_at = F._dmg_now() + F._own.RETRY_AFTER
                end
                R.log(("[rsmm.damage] owner-name sweep: row %d (%s, ctrl=0x%x) "
                       .. "holds no lobby id within +0x%x, direct or one hop "
                       .. "(attempt %d of %d) — roster was {%s}"):format(
                    row.slot, row.label, row.key, F._own.WIN,
                    row.own_tries, F._own.TRIES, F._dmg_roster_names()))
                return
            end
        end
    end
end

--- Advance the identity sweep by ONE slice.
---
--- The meter already drives this from its background tick; this exists so a
--- diagnostic ("who is row 3?") or a test can push it along without waiting.
--- BACKGROUND THREAD ONLY — it walks thousands of addresses.
function R.damage.sweep_identity()
    -- Re-check FIRST: a withdrawal clears `done`, so the probe below can start
    -- looking again in the same call, with whatever rows have since boarded.
    F._dmg_recheck_hero_field()
    F._dmg_probe_hero_field(true)     -- byte and word widths too
    F._dmg_backfill_ids()
    return F._dmg_probe_owner()
end

--- What the identity sweep has found. For diagnostics and the spec.
--- Mark every row as identified. Spec-only: it makes "there is nothing left
--- to look for" reachable without faking a memory layout for each row.
function R.damage._name_all()
    for _, row in ipairs(_dmg.order) do row.player = row.player or row.label end
end

function R.damage.identity()
    -- `chain` is the FIRST chain this board learned. Nothing is pre-seeded (see
    -- F._own.chains), so a non-nil value here means the scan actually ran and
    -- found something on this build — which is the number worth reading.
    return { chain = F._own.chains[1], chains = F._own.chains,
             found = F._own.found, swept = F._own.swept,
             hero_id_offset = HERO_ID_PROBE.off }
end

function F._dmg_relabel()
    local ok, allies = pcall(R.lobby.allies)
    if not ok or type(allies) ~= "table" or #allies == 0 then return end
    -- Name by HERO when the row's identity is known: each lobby member record
    -- carries its RequestedHero, so this is an exact join.
    --
    -- There is NO positional fallback. `allies[rank]` — the old fallback — ranks
    -- rows by the order allies first dealt damage, which is unrelated to the
    -- lobby's order, so from three players up it printed a real name against
    -- another player's damage. What remains is ELIMINATION: once every row that
    -- has a hero id is named, a single unnamed ally row facing a single unclaimed
    -- ally name can only be that player. Everything else keeps its "Player N"
    -- placeholder until the hero-id probe lands.
    -- HERO IDS ARE NOT UNIQUE. Session 8f36 (2026-08-20) is a four-player
    -- lobby with TWO players on hero 10: "PigGoesQuack(hero 10)" and
    -- "Ovilli(hero 10)". Ravenswatch does not force distinct heroes, so the
    -- whole hero-id join is only ever valid for the ids that happen to be
    -- unique in THIS lobby -- and a duplicate id silently kept the last writer,
    -- which is a real player's damage under another real player's name.
    --
    -- Any id that more than one member claims is dropped outright. The rows
    -- that would have been named from it keep their placeholders, which is the
    -- correct answer: the roster genuinely cannot tell those two apart.
    local by_hero, okm, members = {}, pcall(R.lobby.members)
    if okm then
        local list, dup = members, {}
        if type(list) == "table" then
            for _, m in ipairs(list) do
                if m.hero_id and m.name then
                    if by_hero[m.hero_id] and by_hero[m.hero_id] ~= m.name then
                        dup[m.hero_id] = true
                    end
                    by_hero[m.hero_id] = m.name
                end
            end
            for id in pairs(dup) do
                by_hero[id] = nil
                if not _dmg.dup_hero_said then
                    _dmg.dup_hero_said = true
                    R.log(("[rsmm.damage] hero %d is claimed by more than one "
                           .. "player this run %s the hero id cannot identify "
                           .. "either of them, so it names neither")
                          :format(id, "\u{2014}"))
                end
            end
        end
    end
    -- Pass 1: the exact joins, plus the names they account for. `row.player` is
    -- the owner-name sweep's answer and outranks the hero id — it read the
    -- player's own gamertag out of the player's own object.
    local claimed, ally_rows, pending = {}, {}, {}
    for _, row in ipairs(_dmg.order) do
        if not row.is_local then
            local exact = row.player or (row.hero_id and by_hero[row.hero_id]) or nil
            local entry = { row = row, name = exact, guess = false }
            if exact then claimed[exact] = true else pending[#pending + 1] = entry end
            ally_rows[#ally_rows + 1] = entry
        end
    end
    -- Pass 2: elimination. Guarded on `#ally_rows <= #allies` because a row that
    -- forked at a chapter change is a duplicate player, not a new one, and would
    -- otherwise swallow the name of someone who has not dealt damage yet.
    local unclaimed = {}
    for _, nm in ipairs(allies) do
        if not claimed[nm] then unclaimed[#unclaimed + 1] = nm end
    end
    -- STABLE ORDER. `allies` follows R.lobby.members(), which is sorted by
    -- PARSE RECENCY -- and the engine re-parses every member several times a
    -- second, so that order flips constantly. Session a34f logged 192 renames
    -- in one run, `EvilMurray, fruktik_kiwi` and `fruktik_kiwi, EvilMurray`
    -- alternating once a second, which swapped the two players' names across
    -- their damage totals for the whole match. A guess may be wrong; it must
    -- not be wrong DIFFERENTLY every second.
    table.sort(unclaimed)
    if #pending == 1 and #ally_rows <= #allies and #unclaimed == 1 then
        pending[1].name = unclaimed[1]
        pending[1].guess = true              -- exact by count, not by hero id
    elseif _dmg.guess_names then
        -- Hands the leftover names to the leftover rows in JOIN ORDER, which is
        -- a guess: every row it touches is flagged `label_guess` and a UI that
        -- shows the name must show the flag (the board prints a trailing "?").
        --
        -- ⚠ This branch was made opt-in on 2026-08-20 because the silent
        -- version put a real name on another player's damage. Turning it OFF BY
        -- DEFAULT was the wrong half of that fix: the lobby hook reliably learns
        -- all four names (sessions 6136/5636/0a36/7068/fb4f/314f/a84f/174f/304f/
        -- 8f36/c536/014f/e736/2c36/9e4f all logged a full four-name roster), but
        -- no join on this build can say which row is which -- the hero id is
        -- dead here because players pick duplicate heroes, and the owner-GUID
        -- key has no member bridge yet. So the default produced a board that
        -- KNEW every name and printed "Player 1..4" anyway. A marked guess
        -- beats that; an unmarked one does not. `player_1..player_4` in the
        -- config remain the way to get names that are never guesses.
        -- STICKY. A row keeps the guess it was first given for as long as
        -- that name is still in the lobby, so the board settles instead of
        -- re-dealing the same names on every tick. Cleared per epoch with the
        -- rest of the board.
        _dmg.guessed = _dmg.guessed or {}
        local live, taken = {}, {}
        for _, nm in ipairs(allies) do live[nm] = true end
        for _, entry in ipairs(pending) do
            local prev = _dmg.guessed[entry.row.slot]
            if prev and live[prev] and not claimed[prev] and not taken[prev] then
                entry.name, entry.guess, taken[prev] = prev, true, true
            end
        end
        for _, entry in ipairs(pending) do
            if not entry.name then
                for _, nm in ipairs(unclaimed) do
                    if not taken[nm] then
                        entry.name, entry.guess, taken[nm] = nm, true, true
                        _dmg.guessed[entry.row.slot] = nm
                        break
                    end
                end
            end
        end
    end
    local changed = 0
    for _, entry in ipairs(ally_rows) do
        local row = entry.row
        local nm = _dmg.names[row.slot] or entry.name
        if nm and row.label ~= nm then
            row.label = nm
            row.label_guess = _dmg.names[row.slot] == nil and entry.guess
            changed = changed + 1
        end
    end
    if changed > 0 then
        R.log(("[rsmm.damage] lobby roster: %s (%d row(s) renamed)")
              :format(table.concat(allies, ", "), changed))
    end
end

--- Apply the lobby roster to the board's ally rows.
---
--- Public because the roster resolves asynchronously: a UI that wants names
--- the moment they land can call this instead of waiting for the next tick.
--- Cheap — no scan (see R.lobby.members).
function R.damage.relabel() return F._dmg_relabel() end

--- Resolve the lobby roster on the BACKGROUND thread, then re-label.
---
--- Never call the scan from a gameplay path: it walks the address space and
--- costs seconds. This is the only place allowed to trigger it.
function F._dmg_lobby_refresh()
    if not (R.schedule and R.schedule.every) then return end
    -- One resolver for the whole process, not one per mod state.
    if I.shared_get and I.shared_set then
        local ok, n = pcall(I.shared_get, LOBBY_REFRESH_SLOT)
        if ok and type(n) == "number" and n > 0 then return end
        pcall(I.shared_set, LOBBY_REFRESH_SLOT, 1)
    end
    -- DEMAND-DRIVEN. The scan is only worth its ~4 s when there is actually a
    -- row it could name, which makes the common cases free: a solo run never
    -- scans at all, and a co-op run stops scanning the moment every ally has a
    -- real name.
    --
    -- The previous shape — scan on a 30 s timer, then refuse to rescan for
    -- 120 s — managed to be both wasteful and too slow: its one scan landed
    -- during loading, before anyone had joined, found nothing, and the retry
    -- was still 6 s away when session 1e36 ended. Ticking often but scanning
    -- rarely is the right way round.
    -- One SLICE per tick. `refresh` walks a bounded number of bytes and
    -- returns; the sweep spans many ticks, so nothing ever blocks long enough
    -- to be felt. The demand gate still applies, so a solo run does no work at
    -- all beyond the (free) relabel.
    R.schedule.every(1, function()
        local ok, err = pcall(function()
            -- Cheap every time: re-read the known blocks and apply names.
            F._dmg_relabel()
            -- Before the probe, not after: a withdrawal has to clear `done` so
            -- the same tick can start looking again with the bigger sample.
            F._dmg_label_hint()
            F._dmg_recheck_hero_field()
            F._dmg_probe_hero_field(true)     -- background: byte and word too
            F._dmg_backfill_ids()
            -- Bounded and one-shot per row: 0x400 bytes of the row's net
            -- component plus 0x120 at each pointer it holds, looking for a
            -- 32-hex-character session id. Once a locator is adopted this is
            -- two reads per unnamed row. Not gated behind `identity_hunt`,
            -- because unlike the name sweep it cannot answer by coincidence.
            F._dmg_netid_pass()
            -- REAL NAMES, and NOT part of `identity_hunt`.
            --
            -- This asks the process where each player's peer id physically is
            -- (one native `mem_find` per player, ONE needle per tick) and then
            -- checks which row reaches a copy of it, under the one-owner rule.
            -- It is the path that actually produced names, and it is already
            -- rate-limited -- the back-to-back scans that caused session a84f's
            -- stutter were fixed inside it, by spreading the needles.
            --
            -- ⚠ It used to sit INSIDE `F._dmg_probe_owner`, so switching
            -- `identity_hunt` off to stop the blind sweep's stutter switched
            -- this off too and the board went back to "Player 2". That was a
            -- regression, not a decision: the expensive part is the sweep
            -- below, not this.
            --
            -- Self-gating: with no unnamed row it returns immediately, so a
            -- named board and a solo run both cost nothing.
            F._dmg_probe_owner_fast()
            -- The BLIND cursor sweep: hundreds of thousands of probes at every
            -- offset of every row. That is the stutter, and it answered at a
            -- different offset every time it "worked", so it stays opt-in.
            if _dmg.identity_hunt then F._dmg_probe_owner() end
            if F._dmg_wants_lobby() then
                local before = #R.lobby.members()
                local members = R.lobby.refresh()
                if #members ~= before then
                    R.log(("[rsmm.damage] lobby scan: %d member(s)%s")
                          :format(#members, #members > 0
                              and (" — " .. F._dmg_roster_text(members)) or ""))
                end
                F._dmg_relabel()
            end
        end)
        if not ok then
            R.log("[rsmm.damage] lobby refresh failed: " .. tostring(err))
        end
    end)
end

--- "Alice (Aladdin), Bob (Scarlet)" — the roster as one log line.
function F._dmg_roster_text(members)
    local parts = {}
    for _, m in ipairs(members) do
        -- Prefer the hero NAME over the raw id: "Yume (Juliet)" is something a
        -- player can match against what they saw on screen; "Yume (hero 4)" is
        -- not. Display only -- see R.lobby.HERO_NAMES.
        local hero = m.hero or R.lobby.hero_name(m.hero_id)
        parts[#parts + 1] = hero and (m.name .. " (" .. hero .. ")") or m.name
    end
    return table.concat(parts, ", ")
end

--- Record a member's session id without a live lobby. Spec and diagnostics
--- only: in game this comes from the attribute-parser detour, which recovers
--- the member as `blob - 0x28`.
function R.lobby._note_session(name, sid)
    for _, e in ipairs(LOBBY_HOOK.order) do
        if e.name == name then e.session = sid; return true end
    end
    return false
end

--- Record the member OBJECT the hook saw for `name`, and snapshot the pointers
--- it holds (diagnostics and the spec). The hook does both on every parse --
--- and the SNAPSHOT is the part that matters: the member is destroyed after
--- the call, so nothing may read it later.
function R.lobby._note_member(name, addr)
    for _, e in ipairs(LOBBY_HOOK.order) do
        if e.name == name then
            e.member = addr
            if _ptr_plausible(addr) and I.read_u64 then
                local ptrs, n, words = {}, 0, {}
                for off = 0, F._netid.MEMWIN - 8, 8 do
                    local v = I.read_u64(addr + off)
                    if type(v) == "number" and v ~= 0 and v ~= -1 then words[v] = true end
                    if _ptr_plausible(v) and not ptrs[v] then
                        ptrs[v] = true; n = n + 1
                    end
                end
                if n > 0 then e.ptrs, e.nptrs = ptrs, n end
                if next(words) then e.words = words end
            end
            return true
        end
    end
    return false
end

--- Expose the session matcher for the spec and for diagnosing a build where
--- the representations do not line up.
function R.damage._session_matches(n, text)
    return F._dmg_session_matches(n, text)
end

--- Drive the session join directly. Spec and diagnostics only; in game the
--- gameplay bus feeds it (see the R.on("*") handler below).
function R.damage._session_join(entity, session)
    return F._dmg_note_session(entity, session)
end

--- Drive the cheap identity paths by hand, exactly as the 1 Hz tick does
--- (the spec). Does NOT include the blind sweep, which is opt-in.
function R.damage._identity_tick()
    F._dmg_relabel()
    F._dmg_backfill_ids()
    F._dmg_netid_pass()
    return F._dmg_probe_owner_fast()
end

--- Record a member's peer id (the spec); the lobby hook does this from the
--- parsed attribute blob.
function R.lobby._note_eos(name, id)
    for _, e in ipairs(LOBBY_HOOK.order) do
        if e.name == name then e.eos = id; return true end
    end
    return false
end

--- Drive the label hint by hand (the spec); the meter's tick calls it.
function R.damage._label_hint()
    return F._dmg_label_hint()
end

--- Drive one net-id pass by hand (diagnostics and the spec); the meter's own
--- tick already calls this once a second.
--- The engine's peer table as the join sees it (test/diagnostic seam).
function R.damage._peer_join() return F._dmg_peer_join() end

function R.damage._netid_pass()
    return F._dmg_netid_pass()
end

--- The adopted net-id locator, or a table with `off == nil` while discovery is
--- still running. Read-only: a caller must not be able to adopt one by hand.
function R.damage._netid()
    local path
    if F._netid.path then
        path = {}
        for i, v in ipairs(F._netid.path) do path[i] = v end
    end
    -- A COPY of the path: the adopted locator is the one thing a caller must
    -- not be able to edit from outside.
    return { off = F._netid.off, path = path, kind = F._netid.kind }
end

--- Does the int64 session id `n` and the member's session STRING refer to the
--- same session? Exact match against every plausible text form, never a
--- "close enough". The point of this whole path is that it cannot invent an
--- answer; a fuzzy compare would hand that property straight back.
function F._dmg_session_forms(n)
    local hex = ("%016x"):format(n)
    -- Byte-reversed, for a little-endian half of a GUID printed big-endian.
    local swapped = hex:gsub("(%x%x)", function(b) return b end)
    local rev = {}
    for i = 15, 1, -2 do rev[#rev + 1] = hex:sub(i, i + 1) end
    swapped = table.concat(rev)
    return { ("%d"):format(n), ("%x"):format(n), ("%X"):format(n),
             ("0x%x"):format(n), ("0x%X"):format(n),
             hex, hex:upper(), swapped, swapped:upper() }
end

--- Does the member's session id `text` contain this int64 as one of its halves?
---
--- The lobby's session id is a 128-bit GUID STRING, not an int64: session 8f36
--- logged "Ovilli" as "31b1a3aef8ce46e9a4d76be3c7526757", 32 hex characters.
--- The netcode path deals in 8 bytes (NamedEvent_NetSend stores a single
--- qword at ev+0x38), so if the two are the same identity at all, the qword
--- can only be one HALF of that GUID. Both halves and both byte orders are
--- tried; anything else would be a guess, and a guess is what this design
--- exists to refuse.
function F._dmg_session_halves(n, text)
    if type(text) ~= "string" or #text ~= 32 or text:find("[^0-9a-fA-F]") then
        return false
    end
    local lo, hi = text:sub(1, 16):lower(), text:sub(17, 32):lower()
    for _, form in ipairs(F._dmg_session_forms(n)) do
        local f = form:lower()
        if #f == 16 and (f == lo or f == hi) then return true end
    end
    return false
end

function F._dmg_session_matches(n, text)
    if type(n) ~= "number" or type(text) ~= "string" then return false end
    for _, form in ipairs(F._dmg_session_forms(n)) do
        if form == text then return true end
    end
    return F._dmg_session_halves(n, text)
end

--- The lobby member whose session id is `n`, or nil.
---
--- Requires EXACTLY ONE match. Two members answering to one session id means
--- the representation guess is wrong (e.g. a truncated form colliding), and a
--- collision must name nobody -- same rule the rest of the meter runs on.
function F._dmg_session_member(n)
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    local hit, count = nil, 0
    for _, m in ipairs(members) do
        if type(m.session) == "string" and F._dmg_session_matches(n, m.session) then
            hit, count = m, count + 1
        end
    end
    if count == 1 then return hit end
    return nil
end

-- net-component peer id ----------------------------------------------------
--
-- The join the gameplay bus could not give us.
--
-- Sessions c536 and e736 settled ev+0x38: every event the bus dispatched in
-- either run carried the SAME vftable (0xf05aa8), i.e. the base
-- oCGameNamedEvent, and on the base class +0x38 is not a peer. The values it
-- held are handles (0x8146_00xx_00000004, 0x8075_00xx_000y_0004) and in one
-- case a raw code address (0x1463b00a2). So no gameplay event on this build
-- carries a sender, and F._dmg_note_session can never fire from it.
--
-- What DOES have to know the owner is the entity's NET COMPONENT: replication
-- routes by peer, so whatever replicates a remote hero must name the machine
-- driving it. The component is a separate allocation reached through the
-- component map, so the entity+0x2000 sweep never looked at it.
--
-- The needle is the lobby member's session id -- 32 hex characters, the same
-- string LobbyMembers_Local compares to find "everyone but me". A 128-bit
-- value matching by accident is not a risk worth modelling, and that is what
-- makes this different in kind from sweeping memory for a display name.
F._netid = {
    WIN    = 0x800,    -- bytes of the net component to inspect
    HOPWIN = 0x180,    -- bytes at each pointer the component holds
    off    = nil,      -- adopted offset, once a row's own session proves one
    path   = nil,      -- pointer path from the component, or nil for a direct read
    kind   = nil,      -- "string" | "qword-lo" | "qword-hi"
    hits   = {},       -- row.key -> hit list, from the one-shot discovery
    probed = {},       -- row.key -> true
    said   = false,
    counted = false,
    vft_said = false,
    guid_said = false,
    guid_proven = false,
    guid_done = false,   -- a refusal is final for the run: the gates said no
    -- The net component fields NamedEvent_NetSend dereferences by name.
    DEEP    = { 0xb8, 0xc0, 0xc8 },
    -- oCSLNetworkObject::vft[0x18]: *(*(*(C+0xb8)+0x100)+0x28) is the session
    -- this entity replicates to. Read straight off the decompile.
    OWNER_PATH = { 0xb8, 0x100, 0x28 },
    owner_said = 0,
    owner_vft_said = false,
    DEEPWIN = 0x200,   -- bytes of each of those objects to inspect
    MEMWIN = 0x100,    -- bytes of the lobby member object to harvest
    -- Netcode_PeerSlots / Netcode_PeerCount, the engine's own list of the
    -- other machines in the run. Baked VAs, so every read is gated on
    -- _va_ok(): a stale global is a plausible-looking pointer, not a nil.
    --
    -- ⚠ The base is 0x14143f600, NOT 0x14143f650. The tick's `lea rax,
    -- [rip+...]` lands on 0x14143f650 because it indexes slot+0x50 (the
    -- tunnel pointer) directly, so reading the array from there is off by
    -- 0x50 and every string comes back from the NEXT slot. The true base is
    -- what the slot ctor FUN_1402aedf0 zeroes, field by field.
    PEER_SLOTS  = 0x14143f600,
    PEER_COUNT  = 0x14143f780,
    PEER_STRIDE = 0x60,        -- `lea rax,[rax+rax*2]; shl rax,5` in the tick
    PEER_MAX    = 32,          -- refuse an implausible count outright
    -- Slot fields, all decompile-confirmed (FUN_1402aedf0 fills them,
    -- FUN_1402b5db0 frees them, FUN_1402b0170/FUN_1402b0230 look up by them).
    PEER_NAME    = 0x00,       -- PlayerName, straight off the parsed record
    PEER_SESSION = 0x10,       -- the lobby member's +0x00 session id
    PEER_EOS     = 0x20,       -- m_sEosUserId — the engine's "P2P User"
    PEER_HASH    = 0x30,       -- u64 hash of the EOS id (FUN_1402aed50)
    PEER_TUNNEL  = 0x50,       -- the P2P connection: +0xc0 port, +0xcc state
    PEER_STR    = { 0x00, 0x10, 0x20 },
    peer_said   = false,
    peer_done   = false,
    peer_gen    = nil,   -- #peers the memo below was built for
    peer_scanned = {},   -- row.key -> true: its window has been walked once
    peer_hit    = {},    -- row.key -> peer slot, kept after the one-shot scan
}

--- The lobby MEMBER OBJECTS as pointer needles: every plausible pointer the
--- member holds, plus the member's own address, mapped back to the member.
---
--- Session 2c36 settled the value search: all four rows resolved a real net
--- component and NONE of them held a session id within +0x400, direct or one
--- hop. So the peer is not identified there by its GUID -- which is what you
--- would expect if the engine keys peers by a connection OBJECT rather than by
--- the id string the lobby exposes.
---
--- A pointer both structures hold is a much stronger claim than a matching
--- integer: it says the member and the net component reference the SAME
--- allocation. Combined with the anchor and distinctness gates, a coincidence
--- would have to be a pointer that (a) one member alone holds, (b) one row
--- alone holds, (c) pairs the local row with the local player, and (d) pairs
--- every other row with a different member. Nothing shared satisfies that.
---
--- A value two members share is poisoned, exactly like a session needle.
function F._dmg_member_ptrs()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" or not I.read_u64 then return nil end
    local by, n, total = {}, 0, 0
    for _, m in ipairs(members) do
        if type(m.ptrs) == "table" then
            for v in pairs(m.ptrs) do
                if by[v] == nil then by[v] = m
                elseif by[v] and by[v] ~= m then by[v] = false end
                total = total + 1
            end
            n = n + 1
        end
    end
    -- HOW MANY members contributed, once. Session 9e4f reported 30 hits that
    -- all named one player, and "every row holds a shared pointer" and "only
    -- one member had any needles at all, so nothing could poison one" look
    -- identical in the log without this. They are a different bug each.
    -- Latch on the first NON-EMPTY answer. Session c236 latched on "0 of 0"
    -- five seconds into the process, before a single member had been parsed,
    -- and then never spoke again for the rest of the run -- so the one number
    -- this line exists to report was the one number it could not report.
    if not F._netid.counted and n > 0 then
        F._netid.counted = true
        R.log(("[rsmm.damage] net id: %d of %d lobby member(s) contributed "
               .. "%d pointer needle(s)"):format(n, #members, total))
    end
    if n == 0 then return nil end
    return by
end

--- Both needle sets in one table, so a scan reads each qword once.
function F._dmg_netid_targets()
    local hex = F._dmg_session_needles()
    local ptr = F._dmg_member_ptrs()
    if not hex and not ptr then return nil end
    return { hex = hex or {}, ptr = ptr or {} }
end

--- The lobby's session ids as needles, keyed by the hex text a read would
--- produce. Text, not integers: a GUID half can exceed the signed 64-bit range
--- Lua 5.4 parses, and a float compare would match its neighbours too.
---
--- Both halves and both byte orders, because the netcode deals in qwords and a
--- half stored little-endian prints reversed. A needle two members share is
--- poisoned rather than dropped -- it must never name the first one found.
function F._dmg_session_needles()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    local function rev(h)
        local t = {}
        for i = 15, 1, -2 do t[#t + 1] = h:sub(i, i + 1) end
        return table.concat(t)
    end
    local by, n = {}, 0
    for _, m in ipairs(members) do
        local s = m.session
        if type(s) == "string" and #s == 32 and not s:find("[^0-9a-fA-F]") then
            s = s:lower()
            local lo, hi = s:sub(1, 16), s:sub(17, 32)
            local add = function(key, kind)
                if by[key] == nil then
                    by[key] = { m = m, kind = kind }
                elseif by[key] and by[key].m ~= m then
                    by[key] = false           -- shared by two members: useless
                end
            end
            add(s, "string")
            add(lo, "qword-lo")
            add(hi, "qword-hi")
            add(rev(lo), "qword-lo")
            add(rev(hi), "qword-hi")
            n = n + 1
        end
    end
    if n == 0 then return nil end
    return by
end

--- Every match for a member needle in `base[0 .. win)`: a session id as a
--- qword or a std::string, or a pointer the member itself holds. Guarded
--- reads only, so an unmapped page costs a nil.
--- `path` is how `base` was reached from the net component: nil for the
--- component itself, {a} for `*(nc+a)`, {a,b} for `*(*(nc+a)+b)`. Recorded on
--- every hit so an adopted locator can be RE-READ on another row -- a hit
--- nobody can reproduce is not a locator.
function F._dmg_scan_session(base, win, targets, path)
    local out = {}
    if not _ptr_plausible(base) or not I.read_u64 then return out end
    for off = 0, win - 8, 8 do
        local q = I.read_u64(base + off)
        if type(q) == "number" then
            local h = targets.hex[("%016x"):format(q)]
            if h then
                out[#out + 1] = { off = off, path = path, kind = h.kind, m = h.m }
            else
                local m = targets.ptr[q]
                if m then out[#out + 1] = { off = off, path = path, kind = "ptr", m = m } end
            end
        end
        -- A std::string read is up to three more guarded reads, and this
        -- loop runs tens of thousands of times per row. Only bother where one
        -- could actually start: the heap form begins with a pointer, and the
        -- inline form begins with hex characters.
        local looks = _ptr_plausible(q)
        if not looks and type(q) == "number" then
            local c = q & 0xff
            looks = (c >= 0x30 and c <= 0x39) or (c >= 0x61 and c <= 0x66)
                    or (c >= 0x41 and c <= 0x46)
        end
        local s = looks and R.debug.stdstring_at and R.debug.stdstring_at(base + off)
        if type(s) == "string" and #s == 32 then
            local h = targets.hex[s:lower()]
            if h then out[#out + 1] = { off = off, path = path, kind = "string", m = h.m } end
        end
    end
    return out
end

--- The owning peer's RakNetGUID for a row, or nil.
---
--- `oCSLNetworkObject::vft[0x18]` (0x1408c0d40) is one line:
---
---     *out = *(*(netobj + 0x100) + 0x28);
---
--- netobj+0x100 is the oCSLNetReplica (set in its ctor, FUN_1408c0890's
--- param_2), and the replica is a RakNet::Replica3 whose +0x28 is
--- `creatingSystemGUID` -- the peer that created it, i.e. the machine whose
--- player owns this hero. Read, never called: three guarded loads.
function F._dmg_owner_guid(row)
    if not I.read_u64 or not _ptr_plausible(row.key) then return nil end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return nil end
    local nc = R.net.component(ent)
    if not nc then return nil end
    local inner = F._dmg_netid_walk(nc, { 0xb8, 0x100 })
    if not inner then return nil end
    local g = I.read_u64(inner + 0x28)
    if type(g) ~= "number" or g == 0 or g == -1 then return nil end
    return g
end

--- One engine string/buffer descriptor: {void* ptr @+0x0; int32 len @+0x8;
--- uint32 cap @+0xc}. Same shape as LobbyAttributes_Parse's StringDesc, and
--- the shape the peer-slot destructor frees three of.
function F._peer_str(va)
    if not (I.read_u64 and I.read_u32 and I.read_cstr) then return nil end
    local ptr = I.read_u64(va)
    if not _ptr_plausible(ptr) then return nil end
    local len = I.read_u32(va + 8)
    if type(len) ~= "number" then return nil end
    len = len & 0x7fffffff                 -- bit 31 is the "not owned" flag
    if len < 1 or len > 128 then return nil end
    local t = I.read_cstr(ptr, len + 1)
    if type(t) ~= "string" or #t ~= len then return nil end
    if t:find("[^\32-\126]") then return nil end
    return t
end

--- The engine's own peer table — one entry per OTHER machine in the run.
---
--- Read-only, no engine call, ~`count` * a handful of guarded loads. This is
--- the only structure that holds one record per remote player, which is what a
--- row->player join has been missing: the board knows every NAME (lobby
--- attributes) and a distinct per-row owner RakNetGUID, and nothing joined them.
---
--- Layout in `Netcode_PeerSlots`'s note. Returns `{}` rather than guessing when
--- the va gate is closed or the count is implausible.
function R.net.peers()
    if not _va_ok("the netcode peer table") then return {} end
    if not (I.module_base and I.read_u32 and I.read_u64) then return {} end
    local base = I.module_base()
    if not base or base == 0 then return {} end
    local slots = base + (F._netid.PEER_SLOTS - 0x140000000)
    local n = I.read_u32(base + (F._netid.PEER_COUNT - 0x140000000))
    if type(n) ~= "number" or n < 1 or n > F._netid.PEER_MAX then return {} end
    local out = {}
    for i = 0, n - 1 do
        local slot = slots + i * F._netid.PEER_STRIDE
        local e = { index = i, slot = slot, text = {} }
        e.name    = F._peer_str(slot + F._netid.PEER_NAME)
        e.session = F._peer_str(slot + F._netid.PEER_SESSION)
        e.eos     = F._peer_str(slot + F._netid.PEER_EOS)
        e.hash    = I.read_u64(slot + F._netid.PEER_HASH)
        if e.hash == 0 or e.hash == -1 then e.hash = nil end
        local ptr = I.read_u64(slot + F._netid.PEER_TUNNEL)
        if _ptr_plausible(ptr) then
            e.peer  = ptr
            -- ntohs'd in FUN_1402aa470 (Ordinal_15 = ntohs), so this is a
            -- UDP PORT in network order, NOT a RakNet system index.
            e.port  = I.read_u16 and I.read_u16(ptr + 0xc0)
            e.state = I.read_u32(ptr + 0xcc)
        end
        for _, off in ipairs(F._netid.PEER_STR) do
            local t = F._peer_str(slot + off)
            if t then e.text[#e.text + 1] = t end
        end
        out[#out + 1] = e
    end
    return out
end

--- The owner GUID's SYSTEM INDEX, the other half of the RakNetGUID.
---
--- `RakNetGUID` is `{uint64 g; uint16 systemIndex}` — the replica ctor
--- initialises 16 bytes at +0x28 — so the index sits at replica+0x30. It is
--- the candidate bridge to the peer table, whose peer objects carry a u16 at
--- +0xc0 that Netcode_DropPeer's finder matches on.
function F._dmg_owner_index(row)
    if not I.read_u16 or not _ptr_plausible(row.key) then return nil end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return nil end
    local nc = R.net.component(ent)
    if not nc then return nil end
    local inner = F._dmg_netid_walk(nc, { 0xb8, 0x100 })
    if not inner then return nil end
    local ix = I.read_u16(inner + 0x30)
    if type(ix) ~= "number" or ix == 0xffff then return nil end
    return ix
end

--- Join rows to players through the ENGINE'S OWN PEER TABLE.
---
--- `Netcode_PeerSlots` is one 0x60-byte slot per other machine in the run, and
--- the slot already carries the player's display NAME (+0x00), their lobby
--- session id (+0x10), their EOS ProductUserId (+0x20) and a 64-bit hash of
--- that id (+0x30). It is a better name source than the lobby roster: the
--- roster is append-only history, this is current membership.
---
--- The unsolved half is which SLOT owns which row. The engine's own join is by
--- the +0x30 hash -- FUN_140272700 walks the slots and matches each against
--- `hash(member.m_sEosUserId)`, logging "No party member found for P2P User"
--- when it cannot -- so that hash is the shape an ownership record would take
--- on the hero side too. This scans each row's controller and entity for it.
---
--- A hit is an EQUALITY on a 64-bit engine-computed id, which is what separates
--- it from `guess_names`. No hit names nobody, and the report below still says
--- what both halves held.
function F._dmg_peer_join()
    if F._netid.peer_done then return false end
    -- Nothing unnamed, nothing to look for. Without this the window walk below
    -- runs on a board that is already fully named, forever.
    local wanted = false
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not row.player and _ptr_plausible(row.key) then
            wanted = true
            break
        end
    end
    if not wanted then return false end
    local peers = R.net.peers()
    if #peers == 0 then return false end
    -- ONE-SHOT PER ROW, re-armed only when the peer set changes.
    --
    -- The scan below is 0x800 bytes of the controller plus 0x800 of the entity,
    -- read a qword at a time through the page guard: ~512 native calls per row.
    -- The first version ran it on EVERY background tick for every unnamed row
    -- and never stopped, because a miss returns false rather than latching --
    -- four rows is ~2000 guarded reads a tick, forever. That is the "lags
    -- sometimes hard" shape: invisible while it happens to match, brutal while
    -- it does not. A row's controller does not sprout the key later, so once is
    -- the right number of times; a NEW peer is the only thing that can change
    -- the answer, so that is what re-arms it.
    local gen = #peers
    if F._netid.peer_gen ~= gen then
        F._netid.peer_gen, F._netid.peer_scanned = gen, {}
    end

    -- The engine's own key. FUN_1402aed50 hashes the EOS id into slot+0x30 and
    -- FUN_140272700 joins a lobby member to a peer by comparing that hash --
    -- so if anything on the hero side records which player owns it, this
    -- 64-bit value is the shape it would take. A value two peers share
    -- identifies neither.
    local by_hash = {}
    for _, e in ipairs(peers) do
        if e.hash then
            by_hash[e.hash] = (by_hash[e.hash] == nil) and e or false
        end
    end

    local hit, found = {}, {}
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) and not F._netid.peer_scanned[row.key] then
            F._netid.peer_scanned[row.key] = true
            row._peer_ix = F._dmg_owner_index(row)
            local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
            for _, obj in ipairs({ row.key, _ptr_plausible(ent) and ent or nil }) do
                for off = 0, F._netid.WIN - 8, 8 do
                    local v = I.read_u64(obj + off)
                    local e = type(v) == "number" and by_hash[v]
                    if e then
                        F._netid.peer_hit = F._netid.peer_hit or {}
                        F._netid.peer_hit[row.key] = e
                        found[#found + 1] = ("row %d +0x%x -> %s"):format(
                            row.slot, off, tostring(e.name))
                    end
                end
            end
        end
        -- Carried across ticks: the scan happened once, its answer has to
        -- outlive it or the join can never act on a row it already solved.
        local e = F._netid.peer_hit and F._netid.peer_hit[row.key]
        if e then hit[row] = e end
    end

    if not F._netid.peer_said then
        F._netid.peer_said = true
        local pp = {}
        for _, e in ipairs(peers) do
            pp[#pp + 1] = ("#%d %s eos=%s port=%s state=%s hash=%s"):format(
                e.index, tostring(e.name), tostring(e.eos), tostring(e.port),
                tostring(e.state), e.hash and ("0x%x"):format(e.hash) or "nil")
        end
        local rr = {}
        for _, row in ipairs(_dmg.order) do
            local g = F._dmg_owner_guid(row)
            rr[#rr + 1] = ("row %d guid=%s ix=%s"):format(
                row.slot, g and ("0x%x"):format(g) or "nil",
                tostring(row._peer_ix))
        end
        -- Both halves, always. A silent failure costs a playtest to work out
        -- which side was empty; this line says so outright.
        R.log(("[rsmm.damage] peer table: %d peer(s) [%s]; rows [%s]; hash hits [%s]")
              :format(#peers, table.concat(pp, ", "), table.concat(rr, ", "),
                      #found > 0 and table.concat(found, ", ") or "none"))
    end
    if not next(hit) then return false end

    -- Same two gates as every other join. The anchor is the one that catches a
    -- plausible-but-wrong bridge: if this machine's own row comes back as
    -- somebody else, the mapping is not an identity.
    local me
    local okn, nm = pcall(R.player.name)
    if okn and type(nm) == "string" and nm ~= "" then me = nm end
    for row, e in pairs(hit) do
        if row.is_local and me and e.name and e.name ~= me then
            R.log(("[rsmm.damage] peer join REFUSED: this machine's row resolves "
                   .. "to %q but Steam calls this player %q"):format(e.name, me))
            F._netid.peer_done = true
            return false
        end
    end
    local by = {}
    for row, e in pairs(hit) do
        if e.name then
            if by[e.name] then
                R.log(("[rsmm.damage] peer join REFUSED: rows %d and %d both "
                       .. "resolve to %q"):format(by[e.name].slot, row.slot, e.name))
                F._netid.peer_done = true
                return false
            end
            by[e.name] = row
        end
    end

    local named = 0
    for row, e in pairs(hit) do
        if e.name and not row.is_local and _dmg.names[row.slot] == nil
           and row.label ~= e.name then
            row.label, row.label_guess, row.player = e.name, false, e.name
            named = named + 1
        end
    end
    if named > 0 then
        F._netid.peer_done = true
        R.log(("[rsmm.damage] PEER JOIN PROVEN: %d row(s) named from the engine's "
               .. "own peer table — exact, not a guess"):format(named))
    end
    return named > 0
end

--- Name rows by matching the owner GUID against the lobby members' own words.
---
--- The engine has to know which peer each lobby member is, and a RakNetGUID is
--- a plain 64-bit number, so if it records that anywhere on the member this
--- finds it. Same two gates as everything else: the local row must resolve to
--- the Steam persona, and no two rows may resolve to the same member.
---
--- Costs one table lookup per (row, member) pair. Nothing is searched.
function F._dmg_guid_join()
    if F._netid.guid_done then return false end
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return false end
    -- NOT gated on the roster size. The GUID report below is about the ROWS --
    -- distinct values prove the field is the per-player key whether or not any
    -- member carries one -- and gating the whole function on `#members >= 2`
    -- suppressed it in exactly the sessions where it was worth having.
    if #members < 1 then return false end
    local guid, hit, rows = {}, {}, 0
    for _, row in ipairs(_dmg.order) do
        local g = F._dmg_owner_guid(row)
        if g then
            guid[row] = g
            rows = rows + 1
            local found, count = nil, 0
            for _, m in ipairs(members) do
                if type(m.words) == "table" and m.words[g] then
                    found, count = m, count + 1
                end
            end
            -- A GUID two members claim identifies neither.
            if count == 1 then hit[row] = found end
        end
    end
    if rows == 0 then return false end
    -- Report the GUIDs once, whatever happens. Four different values is the
    -- proof that the field is the owner key even when no member carries it.
    if not F._netid.guid_said and rows > 1 then
        F._netid.guid_said = true
        local seen, n = {}, 0
        local parts = {}
        for _, row in ipairs(_dmg.order) do
            if guid[row] then
                if not seen[guid[row]] then seen[guid[row]] = true; n = n + 1 end
                parts[#parts + 1] = ("row %d = 0x%x%s"):format(
                    row.slot, guid[row], hit[row] and (" -> " .. hit[row].name) or "")
            end
        end
        R.log(("[rsmm.damage] owner GUIDs: %s (%d distinct across %d row(s))")
              :format(table.concat(parts, ", "), n, rows))
    end
    if not next(hit) then return false end
    -- ANCHOR: the local row must resolve to this machine's player.
    local me
    local okn, nm = pcall(R.player.name)
    if okn and type(nm) == "string" and nm ~= "" then me = nm end
    for row, m in pairs(hit) do
        if row.is_local and me and m.name ~= me then
            R.log(("[rsmm.damage] owner GUID join REFUSED: this machine's row "
                   .. "resolves to %q but Steam calls this player %q")
                  :format(m.name, me))
            F._netid.guid_done = true
            return false
        end
    end
    -- DISTINCTNESS: two rows resolving to one member means the match is not an
    -- identity, so it names nobody.
    local by = {}
    for row, m in pairs(hit) do
        if by[m.name] then
            R.log(("[rsmm.damage] owner GUID join REFUSED: rows %d and %d both "
                   .. "resolve to %q"):format(by[m.name].slot, row.slot, m.name))
            F._netid.guid_done = true
            return false
        end
        by[m.name] = row
    end
    local names, named = F._dmg_name_set(), false
    if not names then return false end
    for row, m in pairs(hit) do
        if not row.player and names[m.name] then
            if F._dmg_claim(row, names, m.name, "owner GUID") then named = true end
        end
    end
    if named and not F._netid.guid_proven then
        F._netid.guid_proven = true
        R.log("[rsmm.damage] OWNER GUID JOIN PROVEN: rows are named from "
              .. "RakNet::Replica3::creatingSystemGUID -- the peer the engine "
              .. "itself says created the hero, matched against the lobby "
              .. "member that carries the same GUID.")
    end
    return named
end

--- One-shot: what session ids does this row's net component reach?
---
--- Logs every hit AND the empty result. "The component holds no session id"
--- and "the probe never ran" are the same silence otherwise, and that
--- ambiguity is what cost session 8f36 a whole playtest.
function F._dmg_probe_netid(row, targets)
    if F._netid.probed[row.key] then return F._netid.hits[row.key] end
    if not targets or not I.read_u64 then return nil end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return nil end
    local nc = R.net.component(ent)
    if not nc then
        if not F._netid.said then
            F._netid.said = true
            R.log(("[rsmm.damage] net id: row %d has no net component — the "
                   .. "peer-id join cannot be probed"):format(row.slot))
        end
        return nil
    end
    F._netid.probed[row.key] = true
    local hits = F._dmg_scan_session(nc, F._netid.WIN, targets, nil)
    for off = 0, F._netid.WIN - 8, 8 do
        local p = I.read_u64(nc + off)
        if _ptr_plausible(p) then
            for _, h in ipairs(F._dmg_scan_session(p, F._netid.HOPWIN, targets, { off })) do
                hits[#hits + 1] = h
            end
        end
    end
    -- TWO hops, but only down the three pointers the disassembly names.
    --
    -- NamedEvent_NetSend (0x140721630) and NamedEvent_NetSendToPeer say where
    -- identity actually lives on this component:
    --
    --     [C+0xc0]->vft[0x88](&out)  -> ptr whose [0] is the LOCAL session
    --     [C+0xb8]->vft[0x18](&out)  -> ptr to the session this entity talks to
    --     [C+0xc8]                   -> the scene that sends to a session
    --
    -- Two things follow. Sessions are compared as a single QWORD
    -- (`local_res20 != *param_3`), so the netcode's session is 8 bytes and the
    -- lobby's is a 32-character string -- they are not the same value, which
    -- is why no scan for the GUID could ever hit. And the value is reached
    -- through a VCALL, so it sits deeper than the one hop above. If that qword
    -- is a pointer to a peer object, the object is where a name or a GUID
    -- would be, and that is exactly two hops down these three fields.
    --
    -- Bounded to the named fields on purpose: this is a read of a known
    -- structure, not a wider sweep.
    for _, field in ipairs(F._netid.DEEP) do
        local obj = I.read_u64(nc + field)
        if _ptr_plausible(obj) then
            for _, h in ipairs(F._dmg_scan_session(obj, F._netid.DEEPWIN, targets, { field })) do
                hits[#hits + 1] = h
            end
            for off = 0, F._netid.DEEPWIN - 8, 8 do
                local p = I.read_u64(obj + off)
                if _ptr_plausible(p) then
                    for _, h in ipairs(F._dmg_scan_session(p, F._netid.HOPWIN,
                                                           targets, { field, off })) do
                        hits[#hits + 1] = h
                    end
                end
            end
        end
    end
-- THE OWNER FIELD, read exactly where the engine reads it.
    --
    -- oCSLNetworkObject::vft[0x18] (0x1408c0d40) is one line:
    --
    --     *out = *(*(netobj + 0x100) + 0x28);
    --
    -- so the session an entity replicates to is `*(*(*(C+0xb8)+0x100)+0x28)`,
    -- a plain three-hop field path. No vcall needed, and nothing here is a
    -- guess about WHICH offsets -- the disassembly names all three.
    --
    -- The qword itself is logged per row whatever it is. If the four rows hold
    -- four different values it is the owner key, and the only open question is
    -- what maps it to a name; if they are all equal it is not.
    do
        local owner = F._dmg_netid_walk(nc, F._netid.OWNER_PATH)
        local raw
        local o = F._dmg_netid_walk(nc, { 0xb8, 0x100 })
        if o then raw = I.read_u64(o + 0x28) end
        if raw and F._netid.owner_said < 4 then
            F._netid.owner_said = F._netid.owner_said + 1
            R.log(("[rsmm.damage] net id: row %d owner session = 0x%x%s")
                  :format(row.slot, raw,
                          _ptr_plausible(raw) and " (a pointer)" or ""))
        end
        -- If it is a pointer, the object behind it is where a session STRING
        -- would live -- one hop past what any earlier pass reached.
        if owner then
            for _, h in ipairs(F._dmg_scan_session(owner, F._netid.DEEPWIN,
                                                   targets, F._netid.OWNER_PATH)) do
                hits[#hits + 1] = h
            end
            if not F._netid.owner_vft_said then
                local mb = I.module_base and I.module_base()
                local vft = I.read_u64(owner)
                if mb and mb ~= 0 and _ptr_plausible(vft) and vft > mb then
                    F._netid.owner_vft_said = true
                    R.log(("[rsmm.damage] net id: owner object vftable rva 0x%x")
                          :format(vft - mb))
                end
            end
        end
    end
    -- The net object's VFTABLE, once. Its slot 0x18 returns the session this
    -- entity replicates to; decompiling that one function statically answers
    -- the whole question, and the RVA is the only thing the exe cannot tell me
    -- without a live instance.
    if not F._netid.vft_said then
        local obj = I.read_u64(nc + 0xb8)
        local mb = I.module_base and I.module_base()
        if _ptr_plausible(obj) and mb and mb ~= 0 then
            local vft = I.read_u64(obj)
            if _ptr_plausible(vft) and vft > mb then
                F._netid.vft_said = true
                R.log(("[rsmm.damage] net id: net object vftable rva 0x%x "
                       .. "(slot 0x18 = the session this entity replicates to)")
                      :format(vft - mb))
            end
        end
    end
    F._netid.hits[row.key] = hits
    -- Cap the per-row detail. Session 9e4f printed thirty of these, which is
    -- a lot of log for one fact ("this row reaches N locators naming M
    -- players"); the counts are what a reader acts on, the first few lines are
    -- enough to see the shape.
    local who, nwho = {}, 0
    for _, h in ipairs(hits) do
        if h.m and not who[h.m.name] then who[h.m.name] = true; nwho = nwho + 1 end
    end
    for i, h in ipairs(hits) do
        if i > 4 then break end
        R.log(("[rsmm.damage] net id: row %d (%s) netcomp%s +0x%x is %q (%s)")
              :format(row.slot, tostring(row.label),
                      F._dmg_netid_path_text(h.path),
                      h.off, tostring(h.m.name), h.kind))
    end
    if #hits > 4 then
        R.log(("[rsmm.damage] net id: row %d has %d locator(s) naming %d "
               .. "player(s) (showing 4)"):format(row.slot, #hits, nwho))
    end
    if #hits == 0 then
        R.log(("[rsmm.damage] net id: row %d (%s) netcomp 0x%x carries no lobby "
               .. "session id and no member pointer within +0x%x, direct or one hop")
              :format(row.slot, tostring(row.label), nc, F._netid.WIN))
    end
    return hits
end

--- Read the ADOPTED locator on one row and claim the member it names.
function F._dmg_apply_netid(row, targets)
    local L = F._netid
    if not L.off or not targets or not I.read_u64 then return false end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return false end
    local nc = R.net.component(ent)
    if not nc then return false end
    local base = F._dmg_netid_walk(nc, L.path)
    if not base then return false end
    local m
    if L.kind == "string" then
        local s = R.debug.stdstring_at and R.debug.stdstring_at(base + L.off)
        local hit = (type(s) == "string") and targets.hex[s:lower()] or nil
        m = hit and hit.m or nil
    elseif L.kind == "ptr" then
        local q = I.read_u64(base + L.off)
        -- The member table is rebuilt every pass, so a pointer that has since
        -- become shared stops naming anyone rather than keeping a stale answer.
        m = (type(q) == "number") and targets.ptr[q] or nil
    else
        local q = I.read_u64(base + L.off)
        local hit = (type(q) == "number") and targets.hex[("%016x"):format(q)] or nil
        m = hit and hit.m or nil
    end
    if not m then return false end
    local names = F._dmg_name_set()
    if not names or not names[m.name] then return false end
    return F._dmg_claim(row, names, m.name, ("net id +0x%x (%s)"):format(L.off, L.kind))
end

--- "netcomp +0xb8 -> +0x40 ->" -- the pointer path, for the log.
function F._dmg_netid_path_text(path)
    if not path then return "" end
    local t = {}
    for _, v in ipairs(path) do t[#t + 1] = ("+0x%x ->"):format(v) end
    return " " .. table.concat(t, " ")
end

--- A locator key, so hits from different rows can be compared. The PATH is
--- part of the identity: the same offset reached two different ways is two
--- different locators.
function F._dmg_netid_key(h)
    local p = h.path and table.concat(h.path, ",") or "-"
    return ("%s|%s|%x"):format(p, tostring(h.kind), h.off)
end

--- Walk an adopted locator's pointer path from the net component. Guarded, so
--- a path that no longer resolves returns nil instead of faulting.
function F._dmg_netid_walk(nc, path)
    local base = nc
    if not path then return base end
    for _, v in ipairs(path) do
        base = I.read_u64(base + v)
        if not _ptr_plausible(base) then return nil end
    end
    return base
end

--- Discovery, adoption and use, one pass. Background thread only.
---
--- Adoption needs BOTH gates, and both exist because a single-row agreement is
--- exactly what the hero-id probe had when it adopted +0x1b60, an offset the
--- engine never touches:
---
---   1. ANCHOR. The locator must name the LOCAL player on the local row.
---      Steam already told us who that is, so this is a fact to check against,
---      not another inference.
---   2. DISTINCTNESS. Read on every probed row, the locator must name a
---      DIFFERENT member each time. A field that answers the same on two rows
---      is a lobby-wide pointer, not an owner.
function F._dmg_netid_pass()
    -- The GUID join FIRST: it is the only one of these built on a field the
    -- disassembly names outright, and it costs a table lookup per (row,
    -- member) pair. Everything below is a search.
    if F._dmg_guid_join() then return true end
    if F._dmg_peer_join() then return true end
    local targets = F._dmg_netid_targets()
    if not targets then return false end

    -- Adopted: two reads per unnamed row and nothing else.
    if F._netid.off then
        local named = false
        for _, row in ipairs(_dmg.order) do
            if not row.player and _ptr_plausible(row.key) then
                if F._dmg_apply_netid(row, targets) then named = true end
            end
        end
        return named
    end

    -- Discovery. Every row, once each; rows board over the first minute of a
    -- run, so this keeps running until a candidate survives both gates.
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) then F._dmg_probe_netid(row, targets) end
    end

    local me
    local ok, nm = pcall(R.player.name)
    if ok and type(nm) == "string" and nm ~= "" then me = nm end
    if not me then return false end

    -- The anchor row's candidate locators: those that read the local player.
    local anchor
    for _, row in ipairs(_dmg.order) do
        if row.is_local then anchor = row break end
    end
    if not anchor or not F._netid.hits[anchor.key] then return false end
    local cand = {}
    for _, h in ipairs(F._netid.hits[anchor.key]) do
        if h.m and h.m.name == me then cand[F._dmg_netid_key(h)] = h end
    end
    if next(cand) == nil then return false end

    -- Distinctness across every other probed row.
    local seen = { [me] = true }
    local rows = 0
    for _, row in ipairs(_dmg.order) do
        if row ~= anchor and F._netid.hits[row.key] then
            rows = rows + 1
            local got = {}
            for _, h in ipairs(F._netid.hits[row.key]) do
                got[F._dmg_netid_key(h)] = h
            end
            for key, _ in pairs(cand) do
                local h = got[key]
                if not h or not h.m or seen[h.m.name] then
                    cand[key] = nil
                else
                    seen[h.m.name] = true
                end
            end
        end
    end
    -- One ally row is the minimum: agreeing with itself proves nothing.
    if rows == 0 then return false end

    local key, hit = next(cand)
    if not key then return false end
    if next(cand, key) ~= nil then
        -- Several locators survived. Any of them would work, but picking one
        -- at random makes the log unreproducible; take the lowest offset.
        for k, h in pairs(cand) do
            if h.off < hit.off then key, hit = k, h end
        end
    end
    F._netid.off, F._netid.path, F._netid.kind = hit.off, hit.path, hit.kind
    R.log(("[rsmm.damage] NET ID JOIN PROVEN: netcomp%s +0x%x (%s) holds the "
           .. "owning player's session id — it reads %q on this machine's own "
           .. "row and a different lobby member on every other row. Rows are "
           .. "named from the engine's replication data, not from a search.")
          :format(F._dmg_netid_path_text(hit.path), hit.off, hit.kind, me))
    return F._dmg_netid_pass()
end

--- Learn "this entity is driven by this session" from a networked event.
---
--- SELF-VERIFYING, and that is the entire design. The engine stamps ev+0x38
--- with the session id of the machine that raised the event
--- (NamedEvent_NetSend), and the lobby hands us each member's session id as a
--- string. Whether those two are the same value in different clothes is NOT
--- assumed: this only ever fires when a member's string matches the int64
--- EXACTLY. If the representations never line up, nothing matches, nobody is
--- named, and the board stays on placeholders -- which is the correct failure.
---
--- Contrast with every earlier mechanism: the memory sweep answered at a
--- different offset every time it "worked", and the hero-id probe adopted an
--- offset the engine never touches. Neither could tell you it was wrong. This
--- one is wrong only if it stays silent.
function F._dmg_note_session(entity, session)
    if not _ptr_plausible(entity) or type(session) ~= "number" then return end
    local prev = _dmg.sess_by_entity[entity]
    if prev == session then return end
    _dmg.sess_by_entity[entity] = session
    local m = F._dmg_session_member(session)
    if not m then
        -- Say it ONCE. "The join never matched" and "no events carried a
        -- session" are the same silence otherwise, and telling them apart is
        -- what a playtest is for.
        if not _dmg.sess_warned then
            _dmg.sess_warned = true
            R.log(("[rsmm.damage] event session 0x%x matches no lobby member "
                   .. "session id -- the join is not proven on this build, so "
                   .. "no row will be named from it"):format(session))
        end
        return
    end
    if not _dmg.sess_proven then
        _dmg.sess_proven = true
        R.log(("[rsmm.damage] SESSION JOIN PROVEN: event session 0x%x == lobby "
               .. "member %q. Rows are now named from the engine's own peer "
               .. "id, not from anything found by searching memory.")
              :format(session, m.name))
    end
    -- Bind every row whose controller owns this entity.
    for _, row in ipairs(_dmg.order) do
        if not row.player and _ptr_plausible(row.key) then
            local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
            if ent == entity then
                local names = F._dmg_name_set()
                if names and names[m.name] then
                    F._dmg_claim(row, names, m.name, "session")
                end
            end
        end
    end
end

--- The ev+0x38 feeder, RETIRED.
---
--- Sessions c536, e736 and 014f all agree: every event the gameplay bus
--- dispatches is the base oCGameNamedEvent (one vftable, 0xf05aa8), and on the
--- base class +0x38 is not a peer -- the values are handles
--- (0x8146_00xx_00000004) and in one case a raw code address. It is the sender
--- only on oCGameNamedEventNetwork subclasses, which this bus never sees.
---
--- So this callback ran on EVERY gameplay event, for a field that could never
--- answer. On the analytics firehose that is the one place per-event Lua work
--- is actually felt, and the meter is the mod that gets blamed for it. The
--- owner lives at *(*(*(netcomp+0xb8)+0x100)+0x28) instead -- read once per
--- row, on the background tick, by F._dmg_probe_netid.
---
--- `R.net.event_session(ev)` is kept: a mod hooking a genuine network event
--- subclass can still read it, and that is where the field IS the sender.


--- Say ONCE how to put real names on this run's board.
---
--- The board cannot work it out on its own. The engine hands us a set of
--- players and a set of hero objects and nothing linking the two: the hero
--- entity carries no hero id, no player id and no name, so every row->player
--- answer the meter ever produced by searching memory was a coincidence (nine
--- "successes", nine different offsets, one of them provably the wrong person).
--- player_1..player_4 IS the mechanism, not a workaround for a missing one.
function F._dmg_label_hint()
    if _dmg.hinted then return end
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return end
    -- MORE ROWS THAN PLAYERS ON THE ROSTER. Session c236: four rows fighting,
    -- one lobby member all run -- this client parsed its OWN attributes three
    -- times and was never sent anybody else's. No join can help there, because
    -- there is no name to assign; the meter is missing the input, not the
    -- link. That case used to fall out of the `#members < 2` guard below and
    -- say nothing at all, which reads exactly like a broken join.
    if #members < 2 then
        local allies = 0
        for _, row in ipairs(_dmg.order) do
            if not row.is_local then allies = allies + 1 end
        end
        if allies > 0 and not _dmg.roster_warned then
            _dmg.roster_warned = true
            R.log(("[rsmm.damage] %d ally row(s) on the board but %d lobby "
                   .. "member(s) known — this client was never sent the other "
                   .. "players' lobby attributes, so no ally NAME exists to "
                   .. "assign this run (set player_1..player_4 in the config "
                   .. "to label them)"):format(allies, #members))
        end
        return
    end
    local unnamed = 0
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not _dmg.names[row.slot] then unnamed = unnamed + 1 end
    end
    if unnamed == 0 then return end
    _dmg.hinted = true
    R.log(("[rsmm.damage] %d row(s) have no proven name. This run's lobby: %s")
          :format(unnamed, F._dmg_roster_text(members)))
    R.log("[rsmm.damage] to label the board, set player_1..player_4 in the "
          .. "damage-meter config, in JOIN ORDER (row N = player_N). Those "
          .. "always win, and they are the only EXACT method: the engine gives "
          .. "the meter nothing that links a hero object to a player.")
end

--- True when a scan could actually change something: some ally row is still
--- wearing a "Player N" placeholder. Solo runs never qualify, so they never
--- pay for a scan.
function F._dmg_wants_lobby()
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not _dmg.names[row.slot]
            and row.label:find("^Player %d") then
            return true
        end
    end
    return false
end

function F._dmg_new_row(key, is_local)
    local slot = #_dmg.order + 1
    local row = {
        key = key, slot = slot, is_local = is_local or false,
        label = F._dmg_label_for(slot, is_local),
        dealt = 0, taken = 0, hits = 0, best = 0, by_type = {},
        -- Damage the scenery filter dropped. Kept per row so a UI can show
        -- "and 4.2k into the furniture" instead of silently losing it.
        scenery = 0, scenery_hits = 0,
        -- Damage credited even though the victim could NOT be classified. The
        -- filter is fail-open on purpose (never hide a player's damage on a bad
        -- read), which means an unreadable prop family is counted as carry
        -- damage — so the amount that rests on that assumption is counted too,
        -- and a board that looks wrong can be checked against it instead of
        -- argued about.
        unknown = 0, unknown_hits = 0,
        -- Has ANY source ever reported damage taken for this row? `taken` is 0
        -- both for a player who was never hit and for a player this machine
        -- cannot observe, and those are not the same claim (see R.damage.board).
        taken_seen = false,
        first = F._dmg_now(), last = 0, samples = {}, recent = {},
        -- The chapter this row's controller was bound in. See F._dmg_rebind.
        epoch = _dmg.epoch,
    }
    _dmg.actors[key] = row
    _dmg.order[slot] = row
    return row
end

-- A player is reachable under several keys — its hero CONTROLLER (the engine's
-- bookkeeping hands us that), its ENTITY (the attack resolver hands us that),
-- and its NET id (replication hands us that). They must all land on ONE row, or
-- the same player shows up two or three times on the board and every share is
-- wrong. Alias keys point at the row; the net id gets its own index.
function F._dmg_alias(row, key)
    if key and _dmg.actors[key] == nil then _dmg.actors[key] = row end
end

function F._dmg_bind_netid(row, entity)
    if row.netid ~= nil or not entity then return end
    local id = F._dmg_net_id(entity)
    row.netid = id or false
    if id then _dmg.by_netid[id] = row end
end

--- May `prev` be handed to a controller it has never been bound to?
---
--- Only when its own controller cannot still be alive. See F._dmg_rebind for
--- why this is the whole safety of that function.
function F._dmg_may_rebind(prev, why)
    local newer = (prev.epoch or 0) < _dmg.epoch
    -- The exact join may also adopt a row that has gone quiet for longer than a
    -- chapter load; a GUESS may not, because a wrong match would then merge
    -- live allies the moment one of them stops attacking for 45 seconds.
    --
    -- Two reasons are guesses: the is-local byte, and the stale-ally rule
    -- below (which infers "same player" from "exactly one ally row's
    -- controller died over this chapter change"). The stale rule is safe
    -- BECAUSE it needs a chapter boundary -- a player who simply leaves
    -- mid-run also leaves a dead controller, and letting the idle path adopt
    -- that row would hand the next player to join their name and their total.
    local exact = why ~= "local flag" and why ~= DMG.STALE_ALLY
    local idle = exact and prev.last and prev.last > 0
                 and (F._dmg_now() - prev.last) >= DMG.REBIND_IDLE
    if newer or idle then return true end
    -- Say it, but not once per hit: this is the branch that keeps a player on
    -- the board, and a silent refusal looks exactly like the bug it prevents.
    _dmg.refusals = _dmg.refusals + 1
    if _dmg.refusals <= 4 then
        R.log(("[rsmm.damage] refused to merge a new controller into %s (%s) — "
               .. "same chapter (epoch %d) and that row is still active, so this "
               .. "is a DIFFERENT player, not a rebuilt controller")
              :format(prev.label or "?", why or "?", _dmg.epoch))
    end
    return false
end

--- Adopt an existing row for a hero controller we have not seen before.
---
--- The meter used to key rows by the controller pointer alone, which is stable
--- only WITHIN a chapter. Crossing into the next chapter rebuilds every hero
--- controller, so every player forked a second row: the 2026-08-17 evening log
--- shows seven rows for a four-player lobby, "Juice" listed twice (both flagged
--- as the local player), placeholder labels running to "Player 7", and the
--- abandoned rows frozen at 0.0 dps while the run continued. Nothing was lost
--- exactly — it was double-counted into two halves, which is worse, because
--- every `share` on the board is then wrong.
---
--- Two joins, strongest first:
---   1. the HERO ID, when the sweep has confirmed where it lives. Each player
---      in a run has a distinct hero, so this is exact.
---   2. the engine's is-local byte. There is exactly ONE local player, so a
---      second local controller is always the same person. This needs no RE at
---      all and fixes the duplicate that matters most (your own row).
---
--- BOTH joins are gated on the row's controller being GONE, which is the part
--- the first version left out — and a merge is far worse than the fork it
--- replaced. A four-player run (2026-08-18, session 29a8) boarded TWO rows: an
--- unseen controller inside the SAME chapter is another player standing next to
--- you, and this function adopted it as "the same person, new object". A
--- rebuild only happens at a chapter boundary, so that is what is required:
---
---   * hero-id join (exact): a later EPOCH, or a row nothing has credited for
---     REBIND_IDLE seconds (the fallback for a build whose chapter events never
---     arrive — a live player is never silent across a whole chapter load).
---   * is-local join (a guess — one misread byte at +0x1d88 folds every ally
---     onto your row): a later EPOCH, and nothing else.
---
--- Refusing costs a duplicate row, which is visible, self-explanatory and
--- keeps every player's damage. Merging silently deletes a player.
--- Returns the adopted row, or nil to let the caller board a new player.
function F._dmg_rebind(hero, is_local, entity)
    local id = F._dmg_hero_id(hero)
    local prev = id and _dmg.by_hero[id] or nil
    local why = prev and "hero " .. tostring(id) or nil
    -- No fallback scan over the rows here: every path that sets `hero_id` also
    -- writes `by_hero` (see F._dmg_backfill_ids), so a scan could only find what
    -- the index already has. It was written, could not be made to fail in the
    -- spec, and was deleted rather than shipped unexercised.
    if not prev and is_local then
        for _, r in ipairs(_dmg.order) do
            if r.is_local then prev, why = r, "local flag"; break end
        end
    end
    -- STALE-ROW ADOPTION, for the case that has neither key: an ALLY after a
    -- chapter change.
    --
    -- Session a34f, measured against the game's own end-of-run scoreboard:
    -- Ovilli 898436 vs 898071 (exact -- the local row rebinds on the is-local
    -- flag), but the two allies came out as FIVE rows, one player's damage
    -- split across three of them, because an ally has no hero id on this build
    -- and is not local, so every chapter handed them a fresh controller and
    -- `prev` stayed nil.
    --
    -- The rule is deliberately narrow, and refuses rather than guesses:
    -- the new controller must belong to a LATER epoch than the row, the row's
    -- own controller must no longer read as a live hero, and there must be
    -- EXACTLY ONE such row. Two stale rows means two allies respawned and
    -- nothing here can say which is which -- that forks, as before. In a34f
    -- only one ally's controller moved per chapter (the others kept their
    -- address), which is precisely the unambiguous case.
    if not prev and not is_local then
        local stale, n = nil, 0
        for _, r in ipairs(_dmg.order) do
            if not r.is_local and (r.epoch or 0) < _dmg.epoch
               and not (_ptr_plausible(r.key) and F._dmg_is_hero(r.key)) then
                stale, n = r, n + 1
            end
        end
        if n == 1 then
            prev, why = stale, DMG.STALE_ALLY
        elseif n > 1 then
            if not _dmg.stale_said then
                _dmg.stale_said = true
                R.log(("[rsmm.damage] %d ally row(s) went stale over this "
                       .. "chapter change — cannot say which is which, so the "
                       .. "new controller starts its own row"):format(n))
            end
        end
    end
    if not prev then return nil end
    if not F._dmg_may_rebind(prev, why) then return nil end
    _dmg.actors[hero] = prev
    prev.key = hero
    prev.epoch = _dmg.epoch          -- bound HERE now; see F._dmg_may_rebind
    prev.hero_id = id or prev.hero_id
    if prev.hero_id then _dmg.by_hero[prev.hero_id] = prev end
    -- New controller, so a sweep that came up empty on the old one deserves
    -- another go: the name may live on this object even though it did not live
    -- on the last. (A row that already knows who it is keeps that answer.)
    prev.own_done = nil
    F._dmg_alias(prev, entity)
    F._dmg_bind_netid(prev, entity)
    R.log(("[rsmm.damage] rebound %s to controller 0x%x (%s) — chapter change, "
           .. "not a new player"):format(prev.label, hero,
              id and ("hero " .. id) or "local flag"))
    return prev
end

-- Row for a hero CONTROLLER (source 1). The controller is what the SDK already
-- captures for the local player, and its +0x1d88 byte is the engine's own
-- "this is my player" flag — cheaper and more direct than a net lookup.
function F._dmg_row_for_hero(hero)
    if not _ptr_plausible(hero) then return nil end
    local row = _dmg.actors[hero]
    if row then return row end
    local is_local = I.read_u8(hero + DMG.HERO_ISLOCAL_OFF) == 1
    local entity = I.read_u64(hero + DMG.HERO_ENTITY_OFF)
    -- ONE line, once per session. The 2026-08-15 co-op run showed the net-id
    -- lookup refusing this entity, which also explains an empty `taken` column:
    -- if controller+0x8 is not the entity the rest of the SDK recognises, rows
    -- cannot be merged with the resolver's view of the same player. Dump the
    -- raw chain so the next session says which link is wrong instead of
    -- guessing.
    if not _dmg.probed then
        _dmg.probed = true
        R.log(string.format(
            "[rsmm.damage] identity probe: controller=0x%x hero?=%s inner=%s "
            .. "inner_hero?=%s mirror=%s local_byte=%s",
            hero, tostring(F._dmg_is_hero(hero)), tostring(entity),
            tostring(_ptr_plausible(entity) and F._dmg_is_hero(entity) or false),
            tostring(I.read_u64(hero + DMG.HERO_MIRROR_OFF)),
            tostring(I.read_u8(hero + DMG.HERO_ISLOCAL_OFF))))
    end
    -- The resolver may have boarded this player by entity already (it sees
    -- damage TAKEN before the hero deals any). Reuse that row.
    local existing = _ptr_plausible(entity) and _dmg.actors[entity] or nil
    if existing then
        _dmg.actors[hero] = existing
        return existing
    end
    -- A CHAPTER TRANSITION rebuilds every hero controller, so an unknown
    -- pointer usually means "same player, new object" — not a new player.
    -- Adopt the existing row instead of forking a second one for them.
    existing = F._dmg_rebind(hero, is_local, entity)
    if existing then return existing end
    row = F._dmg_new_row(hero, is_local)
    F._dmg_alias(row, entity)
    -- One line per player BOARDED, bounded. Session 29a8 was a four-player run
    -- that produced two rows, and the log could not say which join collapsed
    -- them: whether the is-local byte reads 1 for an ally (it must not — there
    -- is one local player) is a two-byte question that otherwise costs a whole
    -- playtest, in a timezone eight hours away.
    _dmg.boarded = (_dmg.boarded or 0) + 1
    if _dmg.boarded <= 8 then
        R.log(("[rsmm.damage] boarded row %d (%s): controller=0x%x local_byte=%s "
               .. "hero_id=%s epoch=%d"):format(
                  row.slot, row.label or "?", hero,
                  tostring(I.read_u8(hero + DMG.HERO_ISLOCAL_OFF)),
                  tostring(F._dmg_hero_id(hero)), _dmg.epoch))
    end
    -- Sweep for the hero-id field as soon as a SECOND row exists, rather than
    -- waiting for the next tick: the identity is needed by the time the next
    -- chapter loads, and a row boarded in the meantime would be un-rebindable.
    -- Self-gating (needs two rows and two identified lobby members) and
    -- bounded, so this is a no-op on all but a couple of calls per session.
    F._dmg_probe_hero_field()
    row.hero_id = F._dmg_hero_id(hero)
    if row.hero_id then _dmg.by_hero[row.hero_id] = row end
    F._dmg_bind_netid(row, entity)
    if is_local and _dmg.local_id == nil then
        _dmg.local_id = (row.netid ~= false and row.netid) or false
    end
    return row
end

-- Row for an ENTITY seen through the attack resolver (source 2). The negative
-- answer is cached: an enemy attacks hundreds of times a run and each miss
-- would otherwise be an engine lookup.
function F._dmg_row_for_entity(e)
    if not _ptr_plausible(e) then return nil end
    local row = _dmg.actors[e]
    if row then return row end
    if _dmg.seen[e] then return nil end
    if not F._dmg_is_hero(e) then _dmg.seen[e] = true; return nil end
    local id = F._dmg_net_id(e)
    if id and _dmg.by_netid[id] then
        row = _dmg.by_netid[id]
        F._dmg_alias(row, e)
        return row
    end
    local is_local = F._dmg_entity_is_local(e)
    row = F._dmg_new_row(e, is_local)
    row.netid = id or false
    if id then _dmg.by_netid[id] = row end
    if is_local and _dmg.local_id == nil then
        _dmg.local_id = (row.netid ~= false and row.netid) or false
    end
    return row
end

function F._dmg_publish(row, amount, target, source, kind)
    if #_dmg.subs == 0 then return end
    local hit = { label = row.label, slot = row.slot, is_local = row.is_local,
                  amount = amount, target = target, source = source,
                  kind = kind or "dealt" }
    for _, cb in ipairs(_dmg.subs) do pcall(cb, hit) end
end

-- Has this row just been credited the same amount BY THE LOCAL APPLY PATH?
-- Sources 1 and 3 are disjoint in theory (the machine that applies a hit is not
-- the machine that receives its replication), but "in theory" is not a good
-- enough reason to risk double-counting a player's damage, which is the one
-- number this whole feature exists to get right.
--
-- Only cross-source echoes are dropped, never repeats within one source: a
-- multi-hit ability lands several IDENTICAL amounts inside a few frames, and an
-- amount-based filter that ignored the source would silently eat most of a
-- flurry's damage — the exact opposite of the bug it is there to prevent.
function F._dmg_is_echo(row, amount, now)
    local r = row.recent
    for i = #r, 1, -1 do
        if now - r[i].t > DMG.DEDUPE_WINDOW then
            table.remove(r, i)
        elseif math.abs(r[i].a - amount) < 0.01 then
            return true
        end
    end
    return false
end

-- Did ANY player's locally-applied hit just land for this amount?
--
-- Without a net id we cannot ask "is this replicated event about me", so the
-- test widens from one row to all of them: if this machine applied a hit of
-- the same size a moment ago, the event is that hit coming back, and crediting
-- it would invent a phantom player. Four rows and a 0.4s window — cheaper than
-- the engine call it replaces, and it cannot crash the game.
function F._dmg_echo_of_local(amount, now)
    for _, row in ipairs(_dmg.order) do
        if F._dmg_is_echo(row, amount, now) then return true end
    end
    return false
end

function F._dmg_credit(row, amount, target, source, kind)
    local now = F._dmg_now()
    row.dealt = row.dealt + amount
    row.hits  = row.hits + 1
    row.last  = now
    if amount > row.best then row.best = amount end
    if kind then row.by_type[kind] = (row.by_type[kind] or 0) + amount end
    local s = row.samples
    s[#s + 1] = { t = now, a = amount }
    -- Bound the window buffer: a long run at high APM would grow it without
    -- limit. Dropping the oldest half keeps the recent window (all `dps` reads)
    -- honest.
    if #s > DMG.SAMPLE_CAP then
        local keep = {}
        for i = #s // 2, #s do keep[#keep + 1] = s[i] end
        row.samples = keep
    end
    -- Only the local apply path seeds the echo filter; see F._dmg_is_echo.
    if source == "hero-stats" then
        local r = row.recent
        r[#r + 1] = { t = now, a = amount }
        if #r > 32 then table.remove(r, 1) end
    end
    F._dmg_publish(row, amount, target, source, "dealt")
end

-- One resolved hit from the attack resolver. `attacker` may be nil (an enemy
-- swinging), `target` may be nil. Damage landing on a HERO is never carry
-- damage — it is that hero's `taken`, and its attacker does not join the board.
function F._dmg_record(attacker, target, amount, source)
    if type(amount) ~= "number" or amount ~= amount then return end   -- NaN
    if amount <= _dmg.min then return end
    local victim = target and F._dmg_row_for_entity(target) or nil
    if victim then
        victim.taken = victim.taken + amount
        victim.taken_seen = true
        victim.last_hurt = F._dmg_now()
        F._dmg_publish(victim, amount, target, source, "taken")
        return
    end
    if not attacker then return end
    F._dmg_probe_victim(target, amount)
    -- With the hero-stat hook armed, dealt damage is counted there for EVERY
    -- hero (allies included); crediting it here as well would double it.
    if _dmg.stats_hooked then return end
    -- Same scenery filter as the bookkeeping path — this branch is the SOLO
    -- fallback on a build where the stat hook is unresolved, and it would
    -- otherwise keep counting fences on exactly the builds that need it most.
    local cls
    if _dmg.ignore_scenery and target then cls = F._dmg_is_enemy(target) end
    if cls == false then
        attacker.scenery = attacker.scenery + amount
        attacker.scenery_hits = attacker.scenery_hits + 1
        _dmg.scenery = _dmg.scenery + amount
        return
    end
    if _dmg.ignore_scenery and target and cls == nil then
        attacker.unknown = attacker.unknown + amount
        attacker.unknown_hits = attacker.unknown_hits + 1
    end
    F._dmg_credit(attacker, amount, target, source)
end

-- Source 1: the engine's per-hero bookkeeping. Observation only.
function F._dmg_observe_stats(hero, target, pd)
    if not _ptr_plausible(hero) or not _ptr_plausible(pd) then return end
    local valobj = I.read_u64(pd + DMG.PD_VALUE_OFF)
    if not _ptr_plausible(valobj) then return end
    local amount = I.read_f32(valobj + DMG.VALUE_AMOUNT_OFF)
    if type(amount) ~= "number" or amount ~= amount or amount <= _dmg.min then return end
    local row = F._dmg_row_for_hero(hero)
    if not row then return end
    -- What did they hit? The probe reports the first few distinct victims so
    -- the classification can be confirmed from a log rather than trusted.
    F._dmg_probe_victim(target, amount)
    -- Fences, jars, vegetation and mission props inflate a damage board
    -- without meaning anything. `unknown` (nil) counts: never drop a player's
    -- damage on a failed read.
    -- NOT `_dmg.ignore_scenery and F._dmg_is_enemy(target) or nil`: in Lua that
    -- idiom turns a classified `false` (the scenery answer this filter exists
    -- for) into `nil`, which is the fail-open branch.
    local cls
    if _dmg.ignore_scenery then cls = F._dmg_is_enemy(target) end
    if cls == false then
        row.scenery = row.scenery + amount
        row.scenery_hits = row.scenery_hits + 1
        _dmg.scenery = _dmg.scenery + amount
        return
    end
    if _dmg.ignore_scenery and cls == nil then
        -- Counted (fail-open), but counted SEPARATELY as well: this is the only
        -- number that says how much of a row rests on a victim the filter could
        -- not read.
        row.unknown = row.unknown + amount
        row.unknown_hits = row.unknown_hits + 1
    end
    -- Which ability landed it, for the per-ability breakdown. A source object
    -- that does not read back cleanly just means "other" — never a reason to
    -- drop the damage.
    local kind = "other"
    local src = I.read_u64(pd + DMG.PD_SOURCE_OFF)
    if _ptr_plausible(src) then
        local t = I.read_u16(src + DMG.SOURCE_TYPE_OFF)
        if type(t) == "number" and DMG.TYPES[t] then kind = DMG.TYPES[t] end
    end
    F._dmg_credit(row, amount, target, "hero-stats", kind)
end

-- Source 1b: the engine's per-hero damage-RECEIVED bookkeeping.
--
-- The resolver's victim path cannot name a hero on this build (is_grant_target
-- answers false for the controller AND for controller+0x8 — probed live on
-- 2026-08-15), so `taken` was empty for every player. This hook hands the
-- victim over as the same hero object the rows are already keyed by, so it
-- merges with no translation and covers allies too.
function F._dmg_observe_taken(victim, pd)
    if not _ptr_plausible(victim) or not _ptr_plausible(pd) then return end
    -- Same processed-damage record as the dealt side: hit-value object at
    -- +0x10, its f32 at +0x8. The one-shot probe reports the alternative
    -- (+0xa0) too, so a layout difference shows up as data in the log rather
    -- than as another silently empty column.
    local valobj = I.read_u64(pd + DMG.PD_VALUE_OFF)
    local amount = _ptr_plausible(valobj)
        and I.read_f32(valobj + DMG.VALUE_AMOUNT_OFF) or nil
    if not _dmg.probed_taken then
        _dmg.probed_taken = true
        local alt = I.read_u64(pd + DMG.PD_SOURCE_OFF)
        R.log(string.format(
            "[rsmm.damage] taken probe: victim=0x%x local=%s value@+0x10=%s "
            .. "alt@+0xa0=%s",
            victim, tostring(I.read_u8(victim + DMG.HERO_ISLOCAL_OFF)),
            tostring(amount),
            tostring(_ptr_plausible(alt) and I.read_f32(alt + 8) or nil)))
    end
    if type(amount) ~= "number" or amount ~= amount or amount <= 0 then return end
    local row = F._dmg_row_for_hero(victim)
    if not row then return end
    row.taken = row.taken + amount
    row.taken_seen = true
    row.last_hurt = F._dmg_now()
    F._dmg_publish(row, amount, victim, "hero-stats", "taken")
end

function F._dmg_arm_taken()
    if _dmg.taken_hooked then return true end
    if not (R.hook and I.resolve) then return false end
    local va = I.resolve(DMG.TAKEN_SYMBOL)
    if not va or va == 0 then return false end
    -- void(victim, processedDamage). Observation only: return nil without
    -- calling next, and the loader replays the original with the raw arguments.
    local ok, slot, why = pcall(R.hook, va, "vpp", function(victim, pd)
        if _dmg.on then pcall(F._dmg_observe_taken, victim, pd) end
        return nil
    end)
    if not ok then return false end
    if slot == nil and why ~= "already-hooked" then return false end
    _dmg.taken_hooked = true
    return true
end

function F._dmg_arm_stats()
    if _dmg.stats_hooked then return true end
    if not (R.hook and I.resolve) then return false end
    local va = I.resolve(DMG.STATS_SYMBOL)
    if not va or va == 0 then return false end
    -- void(hero, target, processedDamage, char). Read-only: return nil without
    -- calling next, and the loader replays the original with the raw arguments
    -- it received, so the engine's own bookkeeping is bit-for-bit unchanged.
    local ok, slot, why = pcall(R.hook, va, "vpppi", function(hero, target, pd)
        if _dmg.on then pcall(F._dmg_observe_stats, hero, target, pd) end
        return nil
    end)
    if not ok then return false end
    if slot == nil and why ~= "already-hooked" then return false end
    _dmg.stats_hooked = true
    return true
end

-- Source 2: the local attack resolver.
--
-- The signature must carry ALL FIVE arguments ("fpupff", matching the symbol's
-- cabi). The 5th is base damage, which the Windows x64 ABI passes on the
-- STACK; a 4-argument signature would still install, but `next()` would replay
-- the original with whatever happened to be in that stack slot — i.e. a random
-- base damage on every attack in the game.
function F._dmg_observe_attack(ctx, targets, amount)
    if type(amount) ~= "number" or amount <= 0 then return end
    if not _ptr_plausible(ctx) or not _ptr_plausible(targets) then return end
    local attacker = I.read_u64(ctx + DMG.CTX_ENTITY_OFF)
    -- `row` is nil when the attacker is not a hero — an enemy swinging. That is
    -- NOT a reason to stop: the swing may be landing on a hero, and that hero's
    -- `taken` is the other half of the board (and the "I just got hit" signal
    -- other mods subscribe to). F._dmg_record handles a nil attacker.
    local row = F._dmg_row_for_entity(attacker)
    local n = I.read_u32(targets + DMG.TGT_COUNT_OFF)
    local data = I.read_u64(targets + DMG.TGT_DATA_OFF)
    if type(n) ~= "number" or n <= 0 or not _ptr_plausible(data) then
        if row then F._dmg_record(row, nil, amount, "local") end
        return
    end
    if n > DMG.MAX_TARGETS then n = DMG.MAX_TARGETS end
    -- ONE line, once per session, for the other half of the board: `taken`
    -- was 0 for everyone in the 2026-08-15 co-op run, and the two candidate
    -- explanations (enemy attacks never reach this hook / the victim is not
    -- recognised as a hero) look identical from outside. Report the first
    -- swing that is NOT from a boarded hero, with what we make of its target.
    if not _dmg.probed_victim and not row then
        _dmg.probed_victim = true
        local first = I.read_u64(data)
        R.log(string.format(
            "[rsmm.damage] victim probe: attacker=%s target=%s hero?=%s boarded=%s",
            tostring(attacker), tostring(first),
            tostring(F._dmg_is_hero(first)),
            tostring(_dmg.actors[first] ~= nil)))
    end
    for i = 0, n - 1 do
        F._dmg_record(row, I.read_u64(data + i * 8), amount, "local")
    end
end

function F._dmg_arm_resolver()
    if _dmg.hooked then return true end
    if not (R.hook and I.resolve) then return false end
    local va = I.resolve(DMG.ATTACK_SYMBOL)
    if not va or va == 0 then return false end
    local ok, slot, why = pcall(R.hook, va, "fpupff",
        function(ctx, hitdef, targets, mul, base, nxt)
            local dmg = nxt(ctx, hitdef, targets, mul, base)
            if _dmg.on then pcall(F._dmg_observe_attack, ctx, targets, dmg) end
            return dmg
        end)
    if not ok then return false end
    if slot == nil and why ~= "already-hooked" then return false end
    _dmg.hooked = true
    return true
end

-- CHAPTER EPOCH. The engine rebuilds every hero controller when a chapter
-- loads, which is the ONLY moment a row may legitimately change controller (see
-- F._dmg_rebind). Both events are subscribed because neither is guaranteed:
-- GAME_END_NEXT_CHAPTER fires as the old chapter tears down, MAP_GENERATION_DONE
-- as the new one is built, and a build that emits only one of them still gets a
-- bump. Extra bumps are harmless — the epoch only ever UNLOCKS a rebind that a
-- pointer change already asked for.
function F._dmg_next_epoch(name)
    _dmg.epoch = _dmg.epoch + 1
    -- The identity scan's ADDRESSES die with the chapter. Every object it
    -- recorded is torn down here, so holding them is both useless (a rebuilt
    -- controller reaches none of them) and unsafe (freed memory is handed back
    -- out, so a stale address can come to sit next to an unrelated row and name
    -- it wrongly). Nothing else would ever have dropped them: `addrs_key` is
    -- the ROSTER, and a chapter change does not touch the roster, so an ally
    -- still unnamed at the boundary was served a dead cache for the rest of
    -- the run.
    --
    -- The CHAINS are deliberately KEPT. An offset into a rebuilt object is the
    -- one thing about a player that a chapter change does not move, so they are
    -- exactly what names the new controllers — in two reads, with no scan.
    F._own.addrs, F._own.addrs_key, F._own.queue = nil, nil, nil
    -- The net-id DISCOVERY cache dies with them, for the same reason and one
    -- worse: it is keyed by controller ADDRESS, and the allocator hands those
    -- addresses back out. A rebuilt controller landing where a previous row
    -- sat would read as already probed and inherit the OTHER player's hits,
    -- which is precisely how a locator gets adopted against the wrong person.
    -- The ADOPTED locator is kept on purpose -- an offset is what survives a
    -- chapter change; only the per-controller findings are stale.
    F._netid.probed, F._netid.hits = {}, {}
    -- The GUID report is per RUN, and a refusal must not outlive the rows it
    -- was about: new chapter, new controllers, new chance to resolve.
    F._netid.guid_said, F._netid.guid_done = false, false
    F._netid.peer_said, F._netid.peer_done = false, false
    F._netid.peer_gen, F._netid.peer_scanned, F._netid.peer_hit = nil, {}, {}
    -- Sticky guesses belong to the board that made them: a chapter change
    -- re-adopts every controller, so slot N is not the same player it was.
    _dmg.guessed = {}
    -- Per RUN, not per process: a later run that also never receives the other
    -- players' attributes deserves to be told so too.
    _dmg.roster_warned = false
    if _dmg.on then
        R.log(("[rsmm.damage] chapter epoch %d (%s) — hero controllers may now "
               .. "be re-adopted"):format(_dmg.epoch, name))
    end
end
R.on("gameplay:GAME_END_NEXT_CHAPTER",
     function() F._dmg_next_epoch("GAME_END_NEXT_CHAPTER") end)
R.on("gameplay:MAP_GENERATION_DONE",
     function() F._dmg_next_epoch("MAP_GENERATION_DONE") end)

-- Source 3: replicated damage. Identity is the net id; the victim is the
-- entity the event was dispatched INTO, which the SDK can reach once it has
-- learned where a dispatcher sits inside its entity (R.give's
-- _learn_dispatcher_offset). Until then the victim is unknown and the hit is
-- credited to the attacker — the right default, since the overwhelming
-- majority of replicated damage is a player hitting an enemy.
R.on("gameplay:NETWORK_DAMAGE", function(ev)
    if not _dmg.on then return end
    local amount = tonumber(ev.value)
    local id = tonumber(ev.source_id or "")
    if not amount or amount <= _dmg.min or not id or id == -1 then return end
    -- Already counted here? Then it is this machine's own hit echoing back via
    -- another peer, not a new player's damage. (There is no net id to compare
    -- against any more — asking the engine for one crashed the game.)
    if F._dmg_echo_of_local(amount, F._dmg_now()) then return end
    -- VICTIM: prefer the payload's own `target_entity` (+0x60 of the embedded
    -- oCEntityHitData, decoded by event_fields.gen.h) over deriving it from the
    -- dispatcher. The derived guess was the only source here, which is part of
    -- why `taken` stayed 0 for every ally: the engine hands us the target
    -- outright and we were reconstructing it.
    local victim
    local target = tonumber(ev.target_entity or "")
    if target and target ~= 0 and _ptr_plausible(target) then victim = target end
    if not victim and _DISPATCHER_ENTITY_OFF and type(ev.dispatcher) == "string" then
        local disp = tonumber(ev.dispatcher)
        if disp then victim = disp - _DISPATCHER_ENTITY_OFF end
    end
    -- One line, once: does the target we now decode actually correspond to a
    -- player row? If it never does, ally `taken` is not reachable from this
    -- event either and the answer is netcode, not attribution — but that has
    -- been ASSERTED in the symbol note without ever being measured.
    _dmg.net_victim_probes = (_dmg.net_victim_probes or 0) + 1
    if _dmg.net_victim_probes <= 4 then
        -- Lookup and classify ONLY, never create. _dmg_row_for_hero and
        -- _dmg_row_for_entity both CREATE a row for a plausible pointer, and
        -- most NETWORK_DAMAGE targets are enemies — probing with either would
        -- have put enemies on the scoreboard.
        --
        -- `hero?` is the question that decides the whole feature: if a hit on
        -- an ALLY never reaches this machine as NETWORK_DAMAGE, then ally
        -- `taken` is genuinely unavailable here (owner-side only, as the symbol
        -- note claims) and the column should say so rather than read 0. If it
        -- does arrive, the row just needs joining — the ally's row is keyed by
        -- net id, and entity->net-id is dead (see F._dmg_net_id), so that join
        -- has to be built deliberately rather than by creating a second row.
        local known = victim ~= nil and _dmg.actors[victim] or nil
        R.log(string.format(
            "[rsmm.damage] net victim probe #%d: target=%s row=%s hero?=%s",
            _dmg.net_victim_probes,
            target and string.format("0x%x", target) or "nil",
            known and (known.label or "?") or "none",
            tostring(victim ~= nil and F._dmg_is_hero(victim) or false)))
    end
    if victim and _dmg.actors[victim] then
        local row = _dmg.actors[victim]
        row.taken = row.taken + amount
        row.taken_seen = true
        row.last_hurt = F._dmg_now()
        F._dmg_publish(row, amount, victim, "net", "taken")
        return
    end
    local row = _dmg.by_netid[id]
    if not row then
        row = F._dmg_new_row("net:" .. string.format("%x", id), false)
        row.netid = id
        _dmg.by_netid[id] = row
    end
    F._dmg_credit(row, amount, victim, "net")
end)

--- Start metering. Idempotent; safe to call from `ready` or from run:start.
---   opts.window          seconds behind the rolling `dps` figure (default 10)
---   opts.min             ignore hits at or below this value (default 0)
---   opts.names           { [slot] = "Alice", ... } fixed labels by join order
---   opts.ignore_scenery  drop damage dealt to destructible props and mission
---                        objects (fences, jars, dream-shard nodes), counting
---                        only hits on gameplay enemies. Default FALSE, which
---                        is what matches the game's own end-screen total.
---                        Dropped damage is still totalled per row (`scenery`).
---   opts.probe           log the class of the first few distinct victims, so
---                        the enemy test can be confirmed from a log
function R.damage.enable(opts)
    opts = opts or {}
    if type(opts.window) == "number" and opts.window > 0 then _dmg.window = opts.window end
    if type(opts.min) == "number" then _dmg.min = opts.min end
    if opts.ignore_scenery ~= nil then _dmg.ignore_scenery = opts.ignore_scenery and true or false end
    -- Let unidentified rows borrow the leftover lobby names by join order. OFF
    -- by default: the mapping is a guess, and a wrong name on a real damage
    -- total cannot be spotted from inside the game.
    if opts.guess_names ~= nil then _dmg.guess_names = opts.guess_names and true or false end
    if opts.probe ~= nil then _dmg.probe = opts.probe and true or false end
    if opts.identity_hunt ~= nil then
        _dmg.identity_hunt = opts.identity_hunt and true or false
    end
    -- Seconds before a row whose sweep found nothing is swept again. A row is
    -- swept the moment it first deals damage and the object that identifies it
    -- may not be populated yet, so one pass is not an answer. 0 retries on the
    -- next tick, which is what the spec uses.
    if type(opts.retry_after) == "number" and opts.retry_after >= 0 then
        F._own.RETRY_AFTER = opts.retry_after
    end
    if type(opts.names) == "table" then
        for k, v in pairs(opts.names) do
            if type(k) == "number" and type(v) == "string" then _dmg.names[k] = v end
        end
    end
    if _dmg.on then return true end
    _dmg.on = true
    _dmg.started = F._dmg_now()
    local stats = F._dmg_arm_stats()
    local taken = F._dmg_arm_taken()
    local resolver = F._dmg_arm_resolver()
    R.log(("[rsmm.damage] metering on (window %ds, sources: %s, victims: %s%s)")
          :format(_dmg.window, R.damage.mode(),
                  _dmg.ignore_scenery and "enemies only" or "everything the game counts",
                  _dmg.probe and ", probe on" or ""))
    if _dmg.ignore_scenery and not F._dmg_enemy_vft() then
        R.log("[rsmm.damage] module base unavailable — the enemy test cannot "
              .. "run, so nothing is filtered (damage is never dropped on a "
              .. "failed read)")
    end
    F._dmg_lobby_refresh()
    if not stats then
        R.log("[rsmm.damage] " .. DMG.STATS_SYMBOL .. " unresolved on this game "
              .. "build — ALLY damage will only be counted where the engine "
              .. "replicates it to this machine")
    end
    if not taken then
        R.log("[rsmm.damage] " .. DMG.TAKEN_SYMBOL .. " unresolved on this game "
              .. "build — the `taken` column will stay empty")
    end
    if not resolver then
        R.log("[rsmm.damage] " .. DMG.ATTACK_SYMBOL .. " unresolved — solo "
              .. "damage has no fallback source on this build")
    end
    return true
end

--- Which sources are live, e.g. "hero-stats+resolver+net".
function R.damage.mode()
    local parts = {}
    if _dmg.stats_hooked then parts[#parts + 1] = "hero-stats" end
    if _dmg.taken_hooked then parts[#parts + 1] = "hero-taken" end
    if _dmg.hooked then parts[#parts + 1] = "resolver" end
    parts[#parts + 1] = "net"
    return table.concat(parts, "+")
end

--- Stop counting. The detours stay installed (uninstalling a hook another mod
--- may be using is worse than an early return in a callback) but nothing is
--- recorded while metering is off.
function R.damage.disable() _dmg.on = false end

function R.damage.enabled() return _dmg.on end

--- True when the engine's per-hero bookkeeping is hooked — the source that
--- makes ALLY damage countable. False means ally numbers depend on replication.
function R.damage.tracks_allies() return _dmg.stats_hooked end

--- True when the local attack resolver is hooked (damage taken, solo damage).
function R.damage.resolver_armed() return _dmg.hooked end

--- Is the scenery filter on? Pass a boolean to turn it on or off mid-run
--- (rows keep both totals, so toggling never loses a number).
function R.damage.ignore_scenery(on)
    if on ~= nil then _dmg.ignore_scenery = on and true or false end
    return _dmg.ignore_scenery
end

--- Damage the scenery filter dropped this run, across every player. 0 when
--- the filter is off — nothing is classified unless it is asked for.
function R.damage.scenery_total() return _dmg.scenery end

--- Offset of the controller field that carries the player's hero id, once the
--- sweep has confirmed ONE candidate — the identity that lets a row survive a
--- chapter change. nil while unknown or ambiguous, in which case rows fall back
--- to pointer identity (and the local player to the engine's is-local byte).
--- Worth putting in a bug report: it is the field a game patch is most likely
--- to move.
function R.damage.hero_id_offset() return HERO_ID_PROBE.off end

--- Classify a victim entity: true = gameplay enemy, false = scenery / prop /
--- mission object, nil = could not tell (and therefore never filtered).
function R.damage.is_enemy(entity) return F._dmg_is_enemy(entity) end

--- Per-hit callback: cb{ label, slot, is_local, amount, target, source, kind }.
--- `kind` is "dealt" (they damaged something that is not a hero) or "taken"
--- (they were damaged) — the reliable "I just got hit" signal, since the local
--- resolver sees enemy attacks on heroes too.
function R.damage.on(cb)
    assert(type(cb) == "function", "R.damage.on: cb must be function")
    _dmg.subs[#_dmg.subs + 1] = cb
    return #_dmg.subs
end

--- Name a player by join order (1 = first actor seen). Applies retroactively.
function R.damage.name(slot, label)
    assert(type(slot) == "number", "R.damage.name: slot must be number")
    assert(type(label) == "string", "R.damage.name: label must be string")
    _dmg.names[slot] = label
    local row = _dmg.order[slot]
    if row then row.label = label end
end

--- Clear every counter. Called on run boundaries by the meter mod; call it
--- yourself for per-chapter or per-fight scores.
function R.damage.reset()
    _dmg.actors, _dmg.order, _dmg.seen, _dmg.by_netid = {}, {}, {}, {}
    _dmg.by_hero = {}
    -- The sweep's CURSOR points at a row that no longer exists; the CHAIN is a
    -- fact about the engine's layout and stays.
    F._own.cursor = nil
    -- Same split for the member link: the cursor and the per-member "already
    -- swept" set point at dead rows, the learned OFFSET is layout and stays.
    -- The candidate table goes too — a hit is only evidence while the row it
    -- named still exists.
    _dmg.local_id, _dmg.started = nil, F._dmg_now()
    -- Victim pointers do not survive a run boundary: the next run reuses the
    -- addresses for different objects, so a kept cache would answer for the
    -- wrong entity. (The per-entry vftable check would catch most of that;
    -- dropping the table is cheaper and exact.)
    _dmg.vclass, _dmg.vclass_n, _dmg.scenery = {}, 0, 0
    -- The TYPE map is dropped with the entity cache: settings objects are
    -- reloaded per run, so a kept answer could be about a different asset.
    _dmg.sclass, _dmg.sclass_n = {}, 0
end

--- Total damage dealt to non-hero targets by everyone on the board.
function R.damage.total()
    local sum = 0
    for _, row in ipairs(_dmg.order) do sum = sum + row.dealt end
    return sum
end

--- The scoreboard, highest damage first — the ranking, recomputed on every
--- call so a caller polling it always shows the current order. Each row:
---   rank, label, slot, is_local, dealt, taken, hits, best, dps, share, by_type
---   scenery, scenery_hits, unknown, unknown_hits, taken_known, dps_window
--- `dps` is over the configured window (`dps_window`) and `share` is the
--- fraction of all damage dealt — the "who is carrying" number.
---
--- Three keys exist so a UI can say what it does NOT know, instead of printing
--- a confident zero: `unknown`/`unknown_hits` (damage counted against a victim
--- the scenery filter could not classify) and `taken_known` (false when nothing
--- has ever reported damage taken for this player, which is the normal state
--- for an ally).
function R.damage.board()
    local now = F._dmg_now()
    local cutoff = now - _dmg.window
    local total = R.damage.total()
    local out = {}
    for _, row in ipairs(_dmg.order) do
        local recent, keep = 0, {}
        for _, s in ipairs(row.samples) do
            if s.t >= cutoff then recent = recent + s.a; keep[#keep + 1] = s end
        end
        row.samples = keep
        local by_type = {}
        for k, v in pairs(row.by_type) do by_type[k] = v end
        out[#out + 1] = {
            label = row.label, slot = row.slot, is_local = row.is_local,
            -- The player's hero, when the identity sweep has found it. A UI can
            -- show the character, and it is what makes a row survive a chapter
            -- change, so it is worth surfacing rather than keeping internal.
            hero_id = row.hero_id, label_guess = row.label_guess,
            -- The lobby name this row was PROVEN to be (owner-name sweep), as
            -- opposed to `label`, which may still be a placeholder.
            player = row.player,
            dealt = row.dealt, taken = row.taken, hits = row.hits,
            best = row.best, last = row.last, by_type = by_type,
            scenery = row.scenery, scenery_hits = row.scenery_hits,
            -- Damage credited to a victim the filter could not classify. A UI
            -- that shows `hits` should show this too: it is the part of the row
            -- that may be prop chip damage counted as carry (see F._dmg_is_enemy).
            unknown = row.unknown, unknown_hits = row.unknown_hits,
            -- Is `taken = 0` a MEASUREMENT or an absence of one? On this build
            -- the per-hero damage-RECEIVED bookkeeping only fires for heroes
            -- this machine owns, so an ally reads 0 all run whether or not they
            -- were ever hit — and a scoreboard column that cannot tell the two
            -- apart is a wrong number, not a missing one. False until some
            -- source has actually reported a hit on this player.
            taken_known = row.taken_seen == true,
            dps = recent / _dmg.window,
            -- The window `dps` covers, so a caller can LABEL it. A report
            -- printed every 15s off a 10s window has a 5s blind spot, and a
            -- player who stopped attacking 11s ago reads 0.0 dps in a report
            -- that also shows their damage rising — which reads as a bug.
            dps_window = _dmg.window,
            share = total > 0 and (row.dealt / total) or 0,
            idle = row.last > 0 and (now - row.last) or nil,
        }
    end
    table.sort(out, function(a, b)
        if a.dealt ~= b.dealt then return a.dealt > b.dealt end
        return a.slot < b.slot
    end)
    for i, row in ipairs(out) do row.rank = i end
    return out
end

--- The player currently on top (or nil when nothing has been recorded).
function R.damage.leader()
    local board = R.damage.board()
    return board[1]
end

--- The engine's OWN run totals for the local player, straight off the hero's
--- stats record (+0x1db0) — the numbers the end-of-run summary shows. Useful
--- as a cross-check that the meter is counting the same fight the game is.
--- Returns nil when there is no captured hero yet; ally records exist but the
--- engine never fills them, which is the whole reason this module accumulates.
function R.damage.engine_totals()
    local hero = R.entity and R.entity.hero and R.entity.hero()
    if not _ptr_plausible(hero) then return nil end
    local rec = I.read_u64(hero + DMG.HERO_STATS_OFF)
    if not _ptr_plausible(rec) then return nil end
    return {
        dealt = I.read_u32(rec + DMG.STATS_TOTAL_OFF),
        best  = I.read_f32(rec + DMG.STATS_BEST_OFF),
    }
end


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
