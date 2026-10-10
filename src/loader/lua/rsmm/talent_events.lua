-- R.talent.reset / upgrade_random / upgrade_lowest / upgrade / add_random_ultimate
-- — change the hero's talents through the game's own events. PROVEN IN GAME
-- 2026-10-10: upgrade(1), upgrade_random(2) and upgrade_lowest(true) raised the
-- tiers, add_random_ultimate() added an ultimate, reset() removed the talents.
-- upgrade_lowest() without `true` shares its handler's pick but is unexercised.
-- Two observations from that run: the ultimate it adds is NOT one of the 10
-- slots owned() counts (8 -> 8), and reset() leaves one talent — the hero's
-- starting one (8 -> 1; 1 was owned before any pick).
--
--     R.talent.reset()                       remove every talent
--     R.talent.upgrade_random(2)             +1 tier on 2 different random talents
--     R.talent.upgrade_lowest()              +1 tier on a random lowest-tier talent
--     R.talent.upgrade_lowest(true)          ...straight to legendary instead
--     R.talent.upgrade(1)                    +1 tier on the 1st talent you own
--     R.talent.add_random_ultimate()         a random ultimate talent
--     R.talent.owned()                       how many talents you own (nil = no hero)
--
-- All are hero-bound (subscribed in NamedEvent_HeroSubscribeAll) and sent in
-- the with-data shape. The hero keeps 10 talent slots at hero+0xff0, 0x20
-- apart; a talent's tier is *(*(slot+0x68)), 0..3 (3 = legendary), and a tier
-- change goes through SkillController_SetTier. Handlers:
--   RESET_SKILLS                      0x1403a7f60  no payload; HeroController_RemoveSkill on every slot
--   UPGRADE_RANDOM_SKILL              0x1403a77e0  int count (default 1), distinct talents below tier 3
--   UPGRADE_LOWER_SKILL               0x1403a7ba0  no payload; a random one of the lowest tier, +1
--   UPGRADE_LOWER_SKILL_TO_LEGENDARY  0x1403a7d80  no payload; same pick, set to 3
--   UPGRADE_SPECIFIC_SKILL            0x1403a79e0  int index into the owned talents (slot order)
--   ADD_RANDOM_ULTI_SKILL             0x1403a75d0  no payload
--
-- Two of them crash the game in states the engine does not guard, so the SDK
-- checks first (with the hero captured, RSMM_ENABLE_HERO_CAPTURE):
--   * UPGRADE_SPECIFIC_SKILL with NO talent owned indexes entry -1 of a null
--     list. upgrade(i) needs 1 <= i <= owned().
--   * ADD_RANDOM_ULTI_SKILL draws from hero+0xfb8 (count +0xfc0), dropping
--     candidates that do not qualify and re-rolling with `div count` — no zero
--     check, so with no qualifying candidate it divides by zero (the Sandman
--     shop crash, same rand). It also reads *(cand+0x70)+0x10 then +0xc0 with
--     a null fallback of address 0xc8. add_random_ultimate() replays that test
--     and sends only when every candidate is readable and one qualifies
--     (+0x10 object's +0xc0 byte == 0, +0x70 object's +0x40 byte ~= 0).
--
-- MAIN THREAD only (R.schedule.next_main), like every engine-mutating call.
return function(env)
    local R, I = env.R, env.I
    local NE = env.named_event                   -- rsmm/named_event.lua
    local M = {}

    local SLOTS_OFF, SLOT_STRIDE, SLOT_COUNT = 0xff0, 0x20, 10
    local ULTI_LIST_OFF, ULTI_COUNT_OFF = 0xfb8, 0xfc0

    local function send(name, vtype, value)
        return NE.send_value("R.talent", name, vtype, value)
    end

    local function hero_or_log(fn)
        local hero = R.entity and R.entity.hero and R.entity.hero()
        if not hero then
            R.log("[rsmm.talent] " .. fn .. ": needs the hero captured (RSMM_ENABLE_HERO_CAPTURE) "
                .. "to check the engine will not crash — refusing")
        end
        return hero
    end

    -- Talents the hero owns, in slot order (the order UPGRADE_SPECIFIC_SKILL indexes).
    function M.owned()
        local hero = R.entity and R.entity.hero and R.entity.hero()
        if not hero then return nil end
        local n = 0
        for k = 0, SLOT_COUNT - 1 do
            local s = I.read_u64(hero + SLOTS_OFF + k * SLOT_STRIDE)
            if s == nil then return nil end
            if s ~= 0 then n = n + 1 end
        end
        return n
    end

    function M.reset()
        return send("RESET_SKILLS", NE.T_BOOL, true)
    end

    function M.upgrade_random(n)
        n = n == nil and 1 or n
        if type(n) ~= "number" or n ~= math.floor(n) or n < 1 or n > SLOT_COUNT then
            R.log("[rsmm.talent] upgrade_random(n): n must be a whole number from 1 to " .. SLOT_COUNT)
            return false
        end
        return send("UPGRADE_RANDOM_SKILL", NE.T_INT, n)
    end

    function M.upgrade_lowest(to_legendary)
        return send(to_legendary and "UPGRADE_LOWER_SKILL_TO_LEGENDARY" or "UPGRADE_LOWER_SKILL",
            NE.T_BOOL, true)
    end

    function M.upgrade(i)
        if type(i) ~= "number" or i ~= math.floor(i) or i < 1 then
            R.log("[rsmm.talent] upgrade(i): i must be a whole number >= 1 (1 = first talent owned)")
            return false
        end
        if not hero_or_log("upgrade") then return false end
        local owned = M.owned()
        if not owned or owned < 1 then
            R.log("[rsmm.talent] upgrade: no talent owned — the engine would index a null list; refusing")
            return false
        end
        if i > owned then
            R.log(string.format("[rsmm.talent] upgrade(%d): only %d talent(s) owned", i, owned))
            return false
        end
        return send("UPGRADE_SPECIFIC_SKILL", NE.T_INT, i - 1)
    end

    function M.add_random_ultimate()
        local hero = hero_or_log("add_random_ultimate")
        if not hero then return false end
        local list = I.read_u64(hero + ULTI_LIST_OFF)
        local count = I.read_u32(hero + ULTI_COUNT_OFF)
        if not count or count == 0 or count > 256 or not R.ptr.plausible(list) then
            R.log("[rsmm.talent] add_random_ultimate: no ultimate candidates — the engine "
                .. "would divide by zero; refusing")
            return false
        end
        local qualifying = 0
        for k = 0, count - 1 do
            local cand = I.read_u64(list + k * 8)
            if cand == nil then return false end
            if cand ~= 0 then
                local a = I.read_u64(cand + 0x70)
                local d = a and R.ptr.plausible(a) and I.read_u64(a + 0x10) or nil
                if not (d and R.ptr.plausible(d)) then
                    R.log(string.format("[rsmm.talent] add_random_ultimate: candidate %d is unreadable "
                        .. "(the engine would read address 0xc8) — refusing", k))
                    return false
                end
                if I.read_u8(d + 0xc0) == 0 and (I.read_u8(a + 0x40) or 0) ~= 0 then
                    qualifying = qualifying + 1
                end
            end
        end
        if qualifying == 0 then
            R.log(string.format("[rsmm.talent] add_random_ultimate: none of %d candidate(s) qualifies "
                .. "— the engine would divide by zero; refusing", count))
            return false
        end
        return send("ADD_RANDOM_ULTI_SKILL", NE.T_BOOL, true)
    end

    return M
end
