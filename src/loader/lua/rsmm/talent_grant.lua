-- R.talent grant — give the local hero a talent, for testing.
--
-- WHY THIS EXISTS. A talent can only be tested by playing until the game
-- happens to offer it on a level-up card. For a modded talent that turns every
-- iteration into a lottery, so there was no dependable way to check whether a
-- change did anything at all.
--
-- WHAT A GRANT IS. The level-up card confirm (FUN_14039cf80) makes these
-- calls, and a grant has to make all of them:
--   1. `SkillController_SetTier(ctrl, tier)`   the rarity (the offer did this)
--   2. `EntityComponent_Activate(0, *(ctrl+0x80))`   ENTER THE TALENT'S STATE
--   3. `HeroController_AddSkill(hero, ctrl)`   fill a held slot, wire the HUD
--   4. `EntityEventTrigger_Fire(ctrl+0x260)`   the "acquired" event
-- Each one was learned by leaving it out:
--   * tier alone changed nothing — every controller already carries one;
--   * tier + slot gave the talent and its tier-driven damage scaling, but the
--     talent's STATE was never entered, so anything gated on "is this talent's
--     state active" (the POWER finisher clip) never happened. Both measured
--     in-game 2026-09-12. `*(ctrl+0x80)` is the resolved `[State]` target; the
--     game's ADD_ALL_SKILLS cheat activates exactly that pointer after SetTier.
--
--     R.talent.controllers()        -> { {ptr, category, tier, name, held}, ... }
--     R.talent.dump()               -> log the list (run this first on a new build)
--     R.talent.grant("Quick Bombs", 0)  -> queue a real grant of one talent
--     R.talent.revoke("Quick Bombs")    -> queue its removal from the held slots
--     R.talent.grant_all()          -> fire ADD_ALL_SKILLS (every talent active, no held slots)
--
-- WHERE THE CONTROLLERS ARE. Every skill controller registers itself, when it
-- activates, in a per-category `{data, u32 count}` vector on the hero controller
-- at `hero + 0xf98 + category * 0x10` (FUN_1402ed820). The hero controller is
-- the object R.entity.hero() captures — `NamedEvent_HeroSubscribeAll` starts
-- `mov r14, rcx` and that same object's `+0xff0` holds the held-skill slots the
-- tier setter updates. Category 1 is the normal talent pool.
--
-- ⚠ WHAT IS NOT PROVEN. The layout above is read statically; the NAME is not.
-- No engine code read so far says where a controller keeps its name, so `name`
-- is found by scanning the controller and its settings object for a string that
-- looks like a talent name. `dump()` prints what it found. If names come back
-- nil on a build, that scan is what needs a new offset — nothing is guessed, a
-- grant by name simply refuses.
--
-- HELD SLOTS. `hero + 0xff0 + slot * 0x20` holds the controller of slot 0..9
-- (the slot's category pool is at +0xfe0, its UI object at +0xfe8). A hero with
-- ten talents already has no room, and a grant is refused rather than attempted.
return function(env)
    local R, I = env.R, env.I
    local give_hero = env.give_hero            -- () -> hero dispatcher or nil
    local dispatcher_live = env.dispatcher_live
    local M = {}

    local CAT_BASE, CAT_STRIDE, CAT_COUNT = 0xf98, 0x10, 5
    local C_ENTITY, C_SETTINGS, C_TIER, C_HERO = 0x08, 0x10, 0x68, 0x78
    local MAX_PER_CATEGORY = 64
    local HELD_BASE, HELD_STRIDE, HELD_SLOTS = 0xff0, 0x20, 10
    local H_HUD = 0x1db0          -- replicated HUD copy AddSkill writes through
    local C_STATE = 0x80          -- resolved [State] component of the talent
    local C_ACQUIRED = 0x260      -- inline "acquired" event trigger

    local function hero()
        return R.entity and R.entity.hero and R.entity.hero() or nil
    end

    -- Read the tier through the controller's int pointer; nil when unreadable.
    local function tier_of(c)
        local p = I.read_u64(c + C_TIER)
        if not R.ptr.plausible(p) then return nil end
        local t = I.read_u32(p)
        if t == nil then return nil end
        return (t >= 0x80000000) and (t - 0x100000000) or t
    end

    -- The full structure SkillController_SetTier traverses: a live object, the
    -- same hero behind it, the same entity as the hero, and a readable tier
    -- pointer holding a sane value. This is the gate in front of the one engine
    -- call — every loader crash so far was a pointer handed over unchecked.
    local function controller_ok(c, h)
        if not R.ptr.has_vtable(c) then return false end
        if I.read_u64(c + C_HERO) ~= h then return false end
        local ent = I.read_u64(h + C_ENTITY)
        if not ent or I.read_u64(c + C_ENTITY) ~= ent then return false end
        local t = tier_of(c)
        return t ~= nil and t >= -1 and t <= 4
    end

    -- Slot index holding `c`, the first free slot, on hero `h`.
    local function held_slot(h, c)
        local free
        for i = 0, HELD_SLOTS - 1 do
            local v = I.read_u64(h + HELD_BASE + i * HELD_STRIDE)
            if v == c then return i, free end
            if (v == nil or v == 0) and free == nil then free = i end
        end
        return nil, free
    end

    -- What HeroController_AddSkill traverses on the HERO: a live object with its
    -- replicated HUD copy in place and a readable held-slot table.
    local function hero_ok(h)
        if not R.ptr.has_vtable(h) then return false end
        if not R.ptr.plausible(I.read_u64(h + H_HUD)) then return false end
        return I.read_u64(h + HELD_BASE) ~= nil
    end

    local function norm(s)
        return (tostring(s):lower():gsub("[^%w]", ""))
    end

    -- A talent name is ASCII and reads like one. Prefer the controller's own
    -- "Skill Controller <X>" name, then a Skill_<X> text key, then any string
    -- mentioning a skill, so a build that stores only one of them still resolves.
    local function name_of(c)
        local best, rank = nil, 99
        local objs = { c }
        local settings = I.read_u64(c + C_SETTINGS)
        if R.ptr.plausible(settings) then objs[#objs + 1] = settings end
        for _, obj in ipairs(objs) do
            for _, hit in ipairs(R.debug.strings(obj, { max_off = 0x200, log = false })) do
                local t = hit.text
                local r = (t:find("^Skill Controller ") and 1)
                       or (t:find("^Skill_") and 2)
                       or (t:lower():find("skill", 1, true) and 3)
                if r and r < rank then best, rank = t, r end
            end
        end
        return best
    end

    --- Every skill controller on the local hero, with its category, current
    --- tier and resolved name. Empty when no hero is captured yet.
    function M.controllers()
        local h = hero()
        if not h then return {} end
        local out = {}
        for cat = 0, CAT_COUNT - 1 do
            local off = CAT_BASE + cat * CAT_STRIDE
            if R.ptr.vector_valid(h, off, off + 8, { max = MAX_PER_CATEGORY }) then
                local data, n = I.read_u64(h + off), I.read_u32(h + off + 8)
                for i = 0, n - 1 do
                    local c = I.read_u64(data + i * 8)
                    if c and c ~= 0 and controller_ok(c, h) then
                        out[#out + 1] = { ptr = c, category = cat, tier = tier_of(c),
                                          name = name_of(c), held = held_slot(h, c) ~= nil }
                    end
                end
            end
        end
        return out
    end

    --- Log every controller. Run this once on a new build before trusting a
    --- grant by name: it is how a stale offset shows up.
    function M.dump()
        local list = M.controllers()
        R.log(string.format("[rsmm.talent] %d skill controller(s) on the hero", #list))
        for _, e in ipairs(list) do
            local st = I.read_u64(e.ptr + C_STATE)
            local stname = (R.rtti and R.rtti.name and st and st ~= 0) and R.rtti.name(st) or nil
            R.log(string.format("[rsmm.talent]   cat=%d tier=%s %s %s  @0x%x  state=%s",
                  e.category, tostring(e.tier), e.held and "HELD" or "    ",
                  tostring(e.name), e.ptr, tostring(stname)))
        end
        return list
    end

    --- Find the one controller whose name contains `query` (case, spaces and
    --- underscores ignored). Returns it, or nil and a reason.
    function M.find(query)
        local q = norm(query)
        if q == "" then return nil, "empty query" end
        local hits = {}
        for _, e in ipairs(M.controllers()) do
            if e.name and norm(e.name):find(q, 1, true) then hits[#hits + 1] = e end
        end
        if #hits == 0 then return nil, "no talent matches " .. tostring(query) end
        if #hits > 1 then
            local names = {}
            for _, e in ipairs(hits) do names[#names + 1] = e.name end
            return nil, "ambiguous: " .. table.concat(names, " | ")
        end
        return hits[1]
    end

    local function grant_now(query, tier)
        local e, why = M.find(query)
        if not e then
            R.log("[rsmm.talent] grant refused: " .. why)
            return false
        end
        local h = hero()
        if not (h and hero_ok(h)) then
            R.log("[rsmm.talent] grant refused: hero controller not in a usable state")
            return false
        end
        local already, free = held_slot(h, e.ptr)
        if not already and not free then
            R.log("[rsmm.talent] grant refused: all ten talent slots are full")
            return false
        end
        local ctrl_check = { 1, function(p) return controller_ok(p, h) end }

        -- Validate EVERYTHING the sequence will touch before the first call, so
        -- a refusal leaves the talent exactly as it was. Activation reads
        -- *(state+0x08) and calls the state's own can-activate virtual.
        local state = I.read_u64(e.ptr + C_STATE)
        if not already
           and not (R.ptr.has_vtable(state) and R.ptr.plausible(I.read_u64(state + 0x08))) then
            R.log("[rsmm.talent] grant refused: " .. e.name .. " has no live state to enter")
            return false
        end

        -- Rarity first: AddSkill copies the tier into the HUD as it adds.
        R.engine.call_safe("SkillController_SetTier", { ctrl_check }, e.ptr, tier)
        if not already then
            -- Enter the talent's state: the step that switches its behaviour on.
            R.engine.call_safe("EntityComponent_Activate",
                { { 2, function(p) return p == state and R.ptr.has_vtable(p) end } }, 0, state)
            R.engine.call_safe("HeroController_AddSkill",
                { { 1, function(p) return p == h and hero_ok(p) end },
                  { 2, function(p) return controller_ok(p, h) end } }, h, e.ptr)
            -- The trigger object is inline in the controller; firing it reads
            -- through its first qword, so require that to be a real pointer.
            if R.ptr.plausible(I.read_u64(e.ptr + C_ACQUIRED)) then
                R.engine.call_safe("EntityEventTrigger_Fire",
                    { { 1, function(p) return controller_ok(p - C_ACQUIRED, h) end } },
                    e.ptr + C_ACQUIRED)
            end
        end

        -- call_safe returns nil for a refusal AND for a void call, so the only
        -- honest success test is the state itself: in a slot, at the tier.
        local slot = held_slot(h, e.ptr)
        local after = tier_of(e.ptr)
        if slot and after == tier then
            R.log(string.format("[rsmm.talent] granted %s at tier %d in slot %d%s",
                  e.name, tier, slot, already and " (was already held)" or ""))
            return true
        end
        R.log(string.format("[rsmm.talent] grant of %s did NOT take: slot=%s tier=%s",
              e.name, tostring(slot), tostring(after)))
        return false
    end

    local function revoke_now(query)
        local e, why = M.find(query)
        if not e then
            R.log("[rsmm.talent] revoke refused: " .. why)
            return false
        end
        local h = hero()
        if not (h and hero_ok(h)) or not held_slot(h, e.ptr) then
            R.log("[rsmm.talent] revoke refused: " .. tostring(e.name) .. " is not held")
            return false
        end
        R.engine.call_safe("HeroController_RemoveSkill",
            { { 1, function(p) return p == h and hero_ok(p) end },
              { 2, function(p) return controller_ok(p, h) end } }, h, e.ptr, 1)
        local gone = held_slot(h, e.ptr) == nil
        R.log(string.format("[rsmm.talent] revoke %s %s", e.name, gone and "done" or "did NOT take"))
        return gone
    end

    --- Grant one talent by name at `tier` (0 Common .. 3 Legendary, default 0).
    --- Always queued onto the game's MAIN thread: this mutates engine state,
    --- and engine mutations off the main thread crash. Returns true if queued.
    function M.grant(query, tier)
        tier = math.max(0, math.min(3, math.floor(tonumber(tier) or 0)))
        if not (R.engine.resolve("SkillController_SetTier")
                and R.engine.resolve("EntityComponent_Activate")
                and R.engine.resolve("HeroController_AddSkill")
                and R.engine.resolve("EntityEventTrigger_Fire")) then
            R.log("[rsmm.talent] grant symbols unresolved on this build — refusing")
            return false
        end
        R.schedule.next_main(function() grant_now(query, tier) end)
        return true
    end

    --- Remove a held talent by name. Queued onto the main thread.
    function M.revoke(query)
        if not R.engine.resolve("HeroController_RemoveSkill") then
            R.log("[rsmm.talent] HeroController_RemoveSkill unresolved on this build — refusing")
            return false
        end
        R.schedule.next_main(function() revoke_now(query) end)
        return true
    end

    -- Standard reflected CRC32; the engine interns an event name as
    -- NamedEvent_Id_FromCrc(0, crc32(name)). Same derivation as rsmm/map.lua.
    local _crc_table
    local function crc32(s)
        if not _crc_table then
            _crc_table = {}
            for i = 0, 255 do
                local c = i
                for _ = 1, 8 do
                    if c % 2 == 1 then c = 0xEDB88320 ~ (c >> 1) else c = c >> 1 end
                end
                _crc_table[i] = c
            end
        end
        local crc = 0xffffffff
        for i = 1, #s do crc = _crc_table[(crc ~ s:byte(i)) & 0xff] ~ (crc >> 8) end
        return (~crc) & 0xffffffff
    end

    local function fire_now(name)
        local disp = give_hero and give_hero() or nil
        if not disp or disp == 0 then
            R.log("[rsmm.talent] no hero dispatcher yet — the hero must act once first")
            return false
        end
        if dispatcher_live and not dispatcher_live(disp) then
            R.log("[rsmm.talent] hero dispatcher is not live — refusing")
            return false
        end
        if not (R.engine.resolve("NamedEvent_GiveMagicalObject_Ctor")
                and R.engine.resolve("NamedEvent_Id_FromCrc")
                and R.engine.resolve("NamedEvent_Dispatch")) then
            R.log("[rsmm.talent] event primitives unresolved on this build — refusing")
            return false
        end
        -- One scratch block for event + name tail (see rsmm/map.lua for why a
        -- second allocation while this one is live is unsafe).
        local buf = I.scratch(0x80)
        if not buf or buf == 0 then return false end
        local ev = R.engine.call("NamedEvent_GiveMagicalObject_Ctor", buf)
        if not ev or ev == 0 then return false end
        -- The give subclass is the one event ctor with an ok pattern. Dispatch
        -- routes by the id at +0x30; ADD_ALL_SKILLS reads a tier only from the
        -- value-event subclass, which this is not, so every talent lands at
        -- Common. The MO GUID is zeroed: a zero-GUID give is a no-op.
        I.poke(ev + 0x50, 0, 8)
        I.poke(ev + 0x58, 0, 8)
        local tail = buf + 0x60
        for i = 1, #name do I.write_u8(tail + i - 1, name:byte(i)) end
        I.write_u8(tail + #name, 0)
        I.write_u64(ev + 0x20, tail)
        I.write_u32(ev + 0x28, 0x80000000 + #name)   -- unowned: never freed by the engine
        I.write_u32(ev + 0x2c, 0)
        I.write_u32(ev + 0x30, R.engine.call("NamedEvent_Id_FromCrc", 0, crc32(name)) or 0)
        R.engine.call("NamedEvent_Dispatch", disp, ev)
        R.log("[rsmm.talent] dispatched " .. name)
        return true
    end

    --- Fire the game's own ADD_ALL_SKILLS cheat: every normal-pool talent gets
    --- a tier AND has its state entered, but none is put in a held slot, so the
    --- HUD and the slot count do not reflect them.
    function M.grant_all()
        R.schedule.next_main(function() fire_now("ADD_ALL_SKILLS") end)
        return true
    end

    return M
end
