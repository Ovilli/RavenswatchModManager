-- R.ability — the hero's cooldowns and charges, through the game's own events
-- PROVEN IN GAME 2026-10-10: reset_cooldown() made the ultimate ready again
-- at once, and ADD_DASH_CHARGE dispatched (its on-screen effect is not yet
-- confirmed). reduce_cooldown / remove_charge follow the same handlers but
-- have not been exercised in game.
--
--     R.ability.reset_cooldown()             every ability off cooldown
--     R.ability.reset_cooldown("dash")       one slot
--     R.ability.reduce_cooldown(2.5)         every ability, seconds
--     R.ability.reduce_cooldown(2.5, "ultimate")
--     R.ability.add_charge("dash", 2)        abilities that HAVE charges only
--     R.ability.remove_charge("dash")
--     R.ability.slots                        { "basic", "primary", ... }
--     R.ability.ready()                      false until the hero has acted once
--
-- Each call sends one of the game's ability events to the hero's event
-- dispatcher (entity + 0x4d8, the one R.give / R.reroll use). Every ability
-- controller subscribes to them there in its ctor (AbilityController_Ctor):
-- CLEAR_CD / REDUCE_CD for every ability, then CLEAR_<SLOT>_CD,
-- REDUCE_<SLOT>_CD, ADD_<SLOT>_CHARGE and REMOVE_<SLOT>_CHARGE for its own
-- slot. They are oCNamedEventNetworkWithData events: the standard header plus
-- ONE typed value, an oCEntityValueUnion at +0x50 (storage @+0x58, 4 = inline;
-- value @+0x60, or a heap pointer for type 1; type byte @+0x68: 0 = f32,
-- 1 = a 16-byte type whose first int32 is read, 2 = bool). The handlers
-- check the class, then the type:
--   CLEAR_*   bool, must be true          (0x1402cce40)
--   REDUCE_*  seconds, f32 or int32       (0x1402cd140)
--   ADD_*     int32 count, default 1      (0x1402ccf30)
--   REMOVE_*  no payload, removes one     (0x1402cd040)
-- The layout is the one the game's own sender writes (HeroStats_OnDamageTaken
-- builds a CLEAR_PRIMARY_CD exactly this way and dispatches it to an entity).
--
-- MAIN THREAD only (R.schedule.next_main), like every engine-mutating call.
return function(env)
    local R, I = env.R, env.I
    local NE = env.named_event                   -- rsmm/named_event.lua
    local M = {}

    local EVENT_VFT_VA = 0x140f0f180             -- oCNamedEventNetworkWithData_vftable
    local EV_SIZE, UNION_OFF = 0x70, 0x50
    local T_F32, T_INT, T_BOOL = 0, 1, 2

    -- Slot names as the event names spell them, in the controller's own order.
    local SLOTS = { "basic", "primary", "secondary", "defensive", "trait", "ultimate", "dash" }
    local SLOT_SET = {}
    for _, s in ipairs(SLOTS) do SLOT_SET[s] = s:upper() end
    M.slots = SLOTS

    function M.ready() return NE.ready() end

    -- Build and dispatch one with-data event. `vtype` is T_F32/T_INT/T_BOOL.
    local function send(name, vtype, value)
        local ev, disp = NE.begin("R.ability", EVENT_VFT_VA, name, EV_SIZE,
            { "EntityValueUnion_DefaultCtor", "EntityValueUnion_InitAsType",
              "EntityValueUnion_Destruct" })
        if not ev then return false end
        -- The value goes through the engine's own union routines: the bus
        -- CLONES the event before delivering it, and the clone copies the
        -- union through its vftable, which only the ctor sets.
        local u = ev + UNION_OFF
        R.engine.call("EntityValueUnion_DefaultCtor", u)
        if vtype ~= T_F32 then R.engine.call("EntityValueUnion_InitAsType", u, vtype) end
        -- Storage is 4 = inline at +0x10, or else a heap pointer (low bit is a
        -- flag): type 1 is a 16-byte type the engine allocates out of line
        -- (measured in game 2026-10-10, storage=0x6247d230), and the charge
        -- handler reads its first int32 there — the same either-or it uses.
        local storage = I.read_u64(u + 0x08) or 0
        local data = storage == 4 and u + 0x10 or (storage & ~1)
        if I.read_u8(u + 0x18) ~= vtype or (storage ~= 4 and not R.ptr.plausible(data)) then
            R.log(string.format("[rsmm.ability] value union did not initialise as type %d "
                .. "(storage=0x%x type=%s) — refusing", vtype, storage,
                tostring(I.read_u8(u + 0x18))))
            R.engine.call("EntityValueUnion_Destruct", u)
            return false
        end
        if vtype == T_F32 then
            I.write_f32(data, value)
        elseif vtype == T_INT then
            I.write_u32(data, value & 0xffffffff)
        else
            I.write_u8(data, value and 1 or 0)
        end
        local sent = NE.send("R.ability", ev, disp, "value=" .. tostring(value))
        -- Delivery went to the engine's clone; free what InitAsType allocated
        -- for ours (a no-op for an inline value).
        R.engine.call("EntityValueUnion_Destruct", u)
        return sent
    end

    -- `slot` nil = every ability, where the engine has an all-slots event.
    local function slot_event(fmt, all, slot, fn)
        if slot == nil then
            if not all then
                R.log("[rsmm.ability] " .. fn .. ": a slot is required (one of R.ability.slots)")
                return nil
            end
            return all
        end
        local up = type(slot) == "string" and SLOT_SET[slot:lower()] or nil
        if not up then
            R.log("[rsmm.ability] " .. fn .. ": unknown slot " .. tostring(slot)
                .. " (one of " .. table.concat(SLOTS, ", ") .. ")")
            return nil
        end
        return string.format(fmt, up)
    end

    function M.reset_cooldown(slot)
        local name = slot_event("CLEAR_%s_CD", "CLEAR_CD", slot, "reset_cooldown")
        return name ~= nil and send(name, T_BOOL, true)
    end

    function M.reduce_cooldown(seconds, slot)
        if type(seconds) ~= "number" or seconds ~= seconds or seconds <= 0 then
            R.log("[rsmm.ability] reduce_cooldown: seconds must be a positive number")
            return false
        end
        local name = slot_event("REDUCE_%s_CD", "REDUCE_CD", slot, "reduce_cooldown")
        return name ~= nil and send(name, T_F32, seconds)
    end

    function M.add_charge(slot, n)
        n = n == nil and 1 or n
        if type(n) ~= "number" or n ~= math.floor(n) or n < 1 or n > 0x7fffffff then
            R.log("[rsmm.ability] add_charge: n must be a whole number >= 1")
            return false
        end
        local name = slot_event("ADD_%s_CHARGE", nil, slot, "add_charge")
        return name ~= nil and send(name, T_INT, n)
    end

    function M.remove_charge(slot)
        local name = slot_event("REMOVE_%s_CHARGE", nil, slot, "remove_charge")
        -- The handler reads no payload; a bool keeps the event inline.
        return name ~= nil and send(name, T_BOOL, true)
    end

    return M
end
