-- R.poi — observe MAP GENERATION.
--
-- WHAT THIS IS FOR. Whether a mod-added tile is ever actually PLACED has been
-- the open question behind every custom-POI attempt, and nothing inside the
-- process could answer it: the engine PRELOADS every tile listed in the map
-- cache whether or not it is ever chosen, so "the level was opened" does not
-- mean "the tile was placed", and no log line separates them. The only readout
-- left was a person looking at the screen.
--
-- `oCDtEntityCpntTileSpawner` vftable slot 7 (symbol `TileSpawner_Spawn`) is
-- the seam. It is `void(this)`: it takes the game-scene context, runs the
-- placement driver and its constraint solver, runs a post-placement pass, and
-- returns. So a POST-detour fires exactly ONCE PER MAP GENERATION, after the
-- map exists, holding the object that owns the result.
--
--     R.poi.on_generated(function(spawner)
--         R.debug.find_arrays(spawner)      -- one launch, then read it back
--     end)
--
-- ⚠ WHAT IS AND IS NOT PROVEN. The class, the slot, the callgraph and the ABI
-- are established statically against the shipped exe. The spawner's MEMBER
-- LAYOUT is not: where the chosen tiles are recorded is unknown, so this
-- module hands over a pointer and nothing more. It is a probe, deliberately —
-- the way to learn the layout is one launch with `R.debug.find_arrays` on this
-- pointer, and inventing an offset first is how the last three struct hunts
-- went wrong. Do not add a `R.poi.placed_tiles()` here until that has run.
--
-- THREAD. The callback runs INSIDE the detour, on the game's main thread, in
-- the middle of level load. Reads are fine (they are page-guarded); do not do
-- heavy work and do not call back into the engine from here — schedule it.

local M = {}

local R, I

local _hooked = false
local _cbs = {}

--- Call `cb(spawnerComponent)` after each map generation.
---
--- Returns true once the detour is in place, false when the symbol does not
--- resolve on this build (fails closed rather than detouring a stale address)
--- or when another mod's state already owns the detour — the loader unrefs the
--- callback in that case, so the handlers genuinely would not fire.
function M.on_generated(cb)
    if type(cb) ~= "function" then
        error("R.poi.on_generated: expected a function", 2)
    end
    _cbs[#_cbs + 1] = cb
    if _hooked then return true end
    if not (R.hook and I.resolve) then return false end

    local va = I.resolve("TileSpawner_Spawn")
    -- nil/0 when the pattern is absent from this install's DB. The tile
    -- symbols are new, and the pattern DB ships out of band, so this is the
    -- ORDINARY case on a machine that has not run `rsmm update-data` — it must
    -- read as "not available", never as a reason to guess at an address.
    if not va or va == 0 then return false end

    local ok, slot, why = pcall(R.hook, va, "vp", function(this, next)
        -- Original FIRST: before it runs there is no map to look at, which is
        -- the entire point of the hook. Returning a non-nil value after
        -- calling next() is what stops an older loader replaying the
        -- trampoline and generating the map twice.
        next(this)
        for i = 1, #_cbs do
            -- One mod's bad handler must not take down map generation. This
            -- runs mid-level-load: an error escaping here is a hard fault in
            -- the middle of the thing being measured.
            local ran, err = pcall(_cbs[i], this)
            if not ran then
                R.log("[rsmm.poi] handler error: " .. tostring(err))
            end
        end
        return 0
    end)
    -- `nil, "already-hooked"` means ANOTHER mod's lua_State owns this detour,
    -- and `lua_hook` UNREFS the callback it was handed — so unlike the SDK's
    -- shared capture hooks (rsmm.lua:1254), this one is NOT a soft success:
    -- our handlers would never be called. Say which of the two it is; the old
    -- message printed "could not install ...: nil" for both, which reads as a
    -- broken build rather than a load-order collision.
    if not ok or not slot then
        if ok and why == "already-hooked" then
            R.log("[rsmm.poi] another mod already owns the map-generation "
                  .. "hook, so this mod's handlers will not fire — only one "
                  .. "mod at a time can use R.poi on this loader")
        else
            R.log("[rsmm.poi] could not install the map-generation hook: "
                  .. tostring(ok and why or slot))
        end
        return false
    end
    _hooked = true
    R.log(("[rsmm.poi] watching map generation at 0x%x"):format(va))
    return true
end

--- Name what the spawner recorded, from the offsets the ENGINE itself reads.
---
--- These are not guessed and they are not from a sweep. `find_arrays` scans
--- one vector convention (data@+0x190) and every hit it produced on this
--- object was the scene QUADTREE -- oCBasicQuadTree2Agent, three launches
--- running. The placement output uses a different shape entirely, recovered by
--- reading the post-placement pass at 0x140345410, which walks:
---
---   spawner+0x110  array of {void* data, u32 count} groups, stride 0x10
---   spawner+0x118  how many groups
---   spawner+0x120  a flat vector of the same element
---   spawner+0x128  its count
---
--- Elements are **0x58 bytes**, and the engine skips any whose `+0x10` is
--- null -- so `+0x10` is the payload pointer and a null there means an unused
--- slot, not a bad read. `TileSpawn_PlaceTiles` writes all four offsets.
---
--- Read-only and bounded; every read is page-guarded, so a wrong offset gives
--- nil rather than a fault, and nothing is handed back to the engine.
local GROUPS, GROUP_N = 0x110, 0x118
local FLAT, FLAT_N    = 0x120, 0x128
local STRIDE, PAYLOAD = 0x58, 0x10

-- element+0x18 = the LIVE ENTITY spawned for this tile.
--
-- This is what makes the list a BUILT set rather than a selection, and it was
-- settled by RE rather than by looking at the screen. FUN_1403429d0 (the
-- per-element call the post-placement pass makes) writes it:
--
--     mov  rcx, [r12+0x18]        ; previous entity, if any
--     add  rcx, 0x570 ; call ...  ; DETACH from its back-link vector
--     mov  [r12+0x18], rbx        ; store the new entity
--     lea  rcx, [rbx+0x570] ; call ...   ; ATTACH to the new one's
--
-- `entity+0x570` is the engine's weak-reference back-link vector, named
-- independently elsewhere in the symbol map. A candidate or pool list does not
-- own an entity handle and does not register a death-watch on it; only
-- something that has actually been instantiated does.
local ENTITY = 0x18

-- The resource's NAME, as a char* on the payload.
--
-- Measured 2026-09-04: a deep probe of one live payload found "3x3_Crystal_02"
-- through the pointer at +0xa0. Two more tile names turned up at +0x320 and
-- +0x5a0, but those are almost certainly NEIGHBOURING heap objects -- the walk
-- used a 0x800 window on an object whose size is unknown -- so only +0xa0 is
-- treated as this object's own field.
--
-- That makes the offset a HYPOTHESIS, and it is one that checks itself: read
-- across all ~138 elements it either yields a set of distinct, plausible tile
-- names or it obviously does not. `describe` reports the miss rate so a wrong
-- offset is visible as a result rather than as a confident empty answer.
--
-- ⚠ Do NOT go back to R.interact.identify for this. It filters for strings
-- containing ".ot" or a backslash, and these are BARE tile names with neither,
-- so it returned nil for every element and read as "no name found".
local NAME = 0xa0

-- Resolve a placed element's payload to a resource PATH.
--
-- The payload is an `oCEntitySettingsResource` (measured in-game 2026-09-04:
-- 138 of them across 4 groups). RTTI names the TYPE, which is the same for
-- every entry and therefore says nothing about WHICH tile -- the path is what
-- distinguishes a mod's tile from a shipped one. `R.interact.identify` already
-- does exactly this walk (strings within the object, first one that looks like
-- a resource), so it is reused rather than reimplemented.
local function _name_of(payload)
    if not (payload and payload ~= 0 and I.read_cstr) then return nil end
    local p = I.read_u64(payload + NAME)
    if not p or p == 0 or not R.ptr.plausible(p) then return nil end
    local s = I.read_cstr(p, 160)
    -- Printable ASCII only: a resource name is ASCII by construction, and
    -- anything else means this offset is not a name on this object.
    if type(s) == "string" and #s >= 3 and not s:find("[^\32-\126]") then
        return s
    end
    return nil
end

-- The KIND TABLE — what a tile is competing in, and whether it is competing
-- at all.
--
--   spawner+0x10   the settings object (TileSpawn_PlaceTiles reads exactly
--                  this: `mov r13, [rcx+0x10]` at 0x140343b17)
--   settings+0x170 array of TileKind entry pointers
--   settings+0x178 how many
--   entry+0x50     the kind's tile count. `TileKindPool_ReportEmpty`
--                  (settings vftable slot 19) walks this same array and logs
--                  "TileKind[{}] is empty" for any entry whose +0x50 is ZERO,
--                  which is the engine itself telling you a kind can never be
--                  placed. So a mod tile whose kind reads 0 here is not
--                  unlucky, it is unreachable.
--
-- This is the difference between "my tile probably spawns" and knowing what it
-- is drawing against.
local S_KINDS, S_KIND_N, K_COUNT = 0x170, 0x178, 0x50

-- PER-TIER SLOT COUNTS — how many tiles of a kind the map will place.
--
-- The driver picks between three ints by comparing the kind's tier float
-- (`entry+0x20`) against two constants:
--
--     movss xmm0, [r12+0x20]
--     comiss xmm8, xmm0 ; jbe .. → mov eax, [r13+0x2fc]   (tier 1)
--                                  mov eax, [r13+0x300]   (tier 2)
--                                  mov eax, [r13+0x304]   (tier 3)
--
-- which is the numeric half of the already-documented rule that a tiledef's
-- `weight` is a TIER field (T1 0.0 / T2 0.33 / T3 0.667), not a spawn rate.
--
-- Tracing r13 statically means following it across basic blocks, but
-- FUN_1403429d0 reaches the SAME three fields through `[element+0x48]` --
-- `mov rcx,[r12+0x48]` then `mov r8d,[rcx+0x2fc]` -- and the element is
-- something this module already hands out. So the owner is read at runtime and
-- RTTI names it, which pins the object by evidence instead of by inference.
local E_OWNER = 0x48
local TIER1, TIER2, TIER3 = 0x2fc, 0x300, 0x304

--- `{ {count = n, name = "..."|nil}, ... }` for every tile kind this map's
--- spawner knows about. `name` is best-effort (a strings walk over the entry);
--- `count` is the field the engine's own empty-pool check reads.
function M.kinds(spawner)
    local out = {}
    if not (I.read_u64 and I.read_u32 and R.ptr) then return out end
    if not R.ptr.plausible(spawner) then return out end
    local settings = I.read_u64(spawner + 0x10)
    if not settings or not R.ptr.plausible(settings) then return out end
    local arr = I.read_u64(settings + S_KINDS)
    local n = I.read_u32(settings + S_KIND_N) or 0
    if not arr or arr == 0 then return out end
    for i = 0, math.min(n, 128) - 1 do
        local e = I.read_u64(arr + i * 8)
        if e and e ~= 0 and R.ptr.plausible(e) then
            local name
            local hits = R.debug.strings(e, { max_off = 0x60, log = false })
            if hits and hits[1] then name = hits[1].text end
            out[#out + 1] = { count = I.read_u32(e + K_COUNT) or 0, name = name }
        end
    end
    return out
end

--- Every placed tile: `{ name = "...", entity = <ptr or nil> }`.
---
--- Returns `entries, misses`. `misses` is how many live payloads yielded no
--- readable name, which is what makes a wrong NAME offset visible instead of
--- silently returning an empty answer.
---
--- `element` is the 0x58 record's own address, for a caller that wants to read
--- fields this module does not name yet (a tile's world position among them).
---
--- `entity` non-nil means the tile was INSTANTIATED, not merely chosen — see
--- the ENTITY note above. That is the difference between "the generator picked
--- our tile" and "our tile is in the world", and it is the whole reason this
--- does not need a sighting to be conclusive.
function M.placed(spawner)
    local entries, misses = {}, 0
    if not (I.read_u64 and I.read_u32 and R.ptr) then return entries, misses end
    if not R.ptr.plausible(spawner) then return entries, misses end

    local function harvest(data, count)
        if not data or data == 0 or not count then return end
        for i = 0, math.min(count, 512) - 1 do
            local e = data + i * STRIDE
            local payload = I.read_u64(e + PAYLOAD)
            if payload and payload ~= 0 then
                local n = _name_of(payload)
                if n then
                    local ent = I.read_u64(e + ENTITY)
                    if ent == 0 or not R.ptr.plausible(ent) then ent = nil end
                    -- `element` is handed back so a caller can look at the
                    -- record itself. "Is my tile placed" is answered above;
                    -- "WHERE is it" is not, and wandering a chapter looking
                    -- for one camp is the slowest way to find out.
                    -- The per-tier slot counts and the object that owns
                    -- them. `slots` is {t1,t2,t3}; `slots_class` is what RTTI
                    -- calls the owner, which is the thing that was never
                    -- pinned before.
                    local owner = I.read_u64(e + E_OWNER)
                    local slots, slots_class
                    if owner and owner ~= 0 and R.ptr.plausible(owner) then
                        slots_class = R.rtti.name(owner)
                        slots = { I.read_u32(owner + TIER1),
                                  I.read_u32(owner + TIER2),
                                  I.read_u32(owner + TIER3) }
                    end
                    entries[#entries + 1] = {
                        name = n, entity = ent, element = e,
                        slots = slots, slots_class = slots_class,
                    }
                else
                    misses = misses + 1
                end
            end
        end
    end

    local groups = I.read_u64(spawner + GROUPS)
    local ngroups = I.read_u32(spawner + GROUP_N) or 0
    if groups and groups ~= 0 then
        for g = 0, math.min(ngroups, 32) - 1 do
            harvest(I.read_u64(groups + g * 0x10),
                    I.read_u32(groups + g * 0x10 + 8) or 0)
        end
    end
    harvest(I.read_u64(spawner + FLAT), I.read_u32(spawner + FLAT_N) or 0)
    return entries, misses
end

-- ONE payload, examined every way, once per session.
--
-- The sampled `identify` came back empty for all 138 elements, which says the
-- path is not one pointer hop inside the first 0x400 -- and nothing more.
-- Rather than widen a guess, look at a single object properly: raw bytes, the
-- pointer-hop strings with a wide window, and the INLINE strings, which
-- `R.debug.strings` cannot see at all (it only follows pointers, and MSVC
-- keeps a short string in the object itself).
--
-- Deliberately once and deliberately one object: this runs inside level load.
local _deep_done = false
local function _deep_probe(payload)
    if _deep_done or not payload or payload == 0 then return end
    _deep_done = true
    R.log("[rsmm.poi] deep probe of one oCEntitySettingsResource — raw, "
          .. "pointer-strings, then inline strings")
    if R.debug.dump then R.debug.dump(payload, 0x80, "settings-resource") end
    local hops = R.debug.strings(payload, { max_off = 0x800, log = true })
    if #hops == 0 then
        R.log("[rsmm.poi]   no pointer-reachable string in 0x800")
    end
    if R.debug.strings_at then
        R.debug.strings_at(payload, { before = 0, after = 0x100, log = true })
    end
end

local function _name_elements(data, count, label)
    if not data or data == 0 or not count or count == 0 then return end
    local seen, order, paths = {}, {}, {}
    -- Cap the walk. A huge count is a misread, not a discovery, and a thousand
    -- log lines inside level load makes the run itself unusable.
    for i = 0, math.min(count, 64) - 1 do
        local e = data + i * STRIDE
        local payload = I.read_u64(e + PAYLOAD)
        local what
        if not payload or payload == 0 then
            what = "<empty slot>"
        elseif R.ptr.plausible(payload) then
            what = R.rtti.name(payload) or "<no rtti>"
        else
            what = "<implausible>"
        end
        if not seen[what] then order[#order + 1] = what end
        seen[what] = (seen[what] or 0) + 1
        -- The PATH is the identifying half. Bounded per group: the string walk
        -- is the expensive part and this runs inside level load, so a sample
        -- names the shape while the type histogram above still covers all of
        -- them.
        if payload and payload ~= 0 then
            if #paths < 6 then
                local n = _name_of(payload)
                if n then paths[#paths + 1] = n end
            end
            _deep_probe(payload)
        end
    end
    R.log(("[rsmm.poi] %s: %d element(s) of 0x%x"):format(label, count, STRIDE))
    for _, what in ipairs(order) do
        R.log(("[rsmm.poi]     %dx %s"):format(seen[what], what))
    end
    for _, path in ipairs(paths) do
        R.log(("[rsmm.poi]       %s"):format(path))
    end
end

function M.describe(spawner)
    if not (I.read_u64 and I.read_u32 and R.rtti and R.ptr) then return end
    if not R.ptr.plausible(spawner) then
        R.log("[rsmm.poi] describe: implausible spawner pointer")
        return
    end

    local groups = I.read_u64(spawner + GROUPS)
    local ngroups = I.read_u32(spawner + GROUP_N) or 0
    R.log(("[rsmm.poi] %d placement group(s) @spawner+0x%x"):format(ngroups, GROUPS))
    if groups and groups ~= 0 then
        for g = 0, math.min(ngroups, 32) - 1 do
            _name_elements(I.read_u64(groups + g * 0x10),
                           I.read_u32(groups + g * 0x10 + 8) or 0,
                           ("group %d"):format(g))
        end
    end

    _name_elements(I.read_u64(spawner + FLAT),
                   I.read_u32(spawner + FLAT_N) or 0, "flat list")
end

--- True once the detour is in place. `false` means the symbol did not resolve
--- on this build, so nothing will ever fire — a probe should report that
--- rather than sit silently waiting for an event that cannot come.
function M.armed() return _hooked end

return function(env)
    R, I = env.R, env.I
    return M
end
