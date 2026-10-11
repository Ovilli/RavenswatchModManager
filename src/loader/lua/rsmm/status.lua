-- R.status — cleanse the hero through the game's own events (static RE
-- 2026-10-10). clear() PROVEN IN GAME 2026-10-10; clear_stagger() and
-- reset_stagger_resilience() RUN (the hooked handler zeroed the hero's gauge in
-- game 2026-10-10) but heroes never build stagger: 4 min of play polled at
-- 0.1 s kept the hero's gauge and resilience at exactly 0, and the user saw no
-- stagger. The stagger bar belongs to elites/bosses on the same controller class.
--
--     R.status.clear()                    every status effect (CLEAR_STATUS)
--     R.status.clear_stagger()            the stagger gauge (CLEAR_STAGGER)
--     R.status.reset_stagger_resilience() (RESET_STAGGER_RESILIENCE)
--
-- Subscribed by the hero's character controller on the hero dispatcher (its
-- channel map, entity+0x500 = dispatcher+0x28). None reads a payload:
--   CLEAR_STATUS              0x1403bfb00 -> 0x1403c8d40: finds its settings
--                             section, then clears each listed status key
--                             (+0x6c) from the value store at this+0x4c8;
--                             skips everything when that store is null
--   CLEAR_STAGGER             0x1403cc1d0: this+0x33c = 0, then refreshes
--   RESET_STAGGER_RESILIENCE  0x1403cc1c0: this+0x344 = 0
--
-- Reading the gauge (for proving clear_stagger from the log): the handler
-- CharacterController_ClearStagger is a .pdata function, so watch_stagger()
-- hooks it read-only to capture the controller and log +0x33c before and after
-- the clear. RESET_STAGGER_RESILIENCE's handler is a 2-instruction leaf with no
-- .pdata entry and is not hookable.
--
-- Both fields are f32 on the controller. A staggering hit ADDS to +0x33c
-- (0x1403c688c), capped at the threshold 0x1403c9ab0(this); it decays once the
-- delay at +0x348 runs out (0x1403c90f3). When the hero is actually STAGGERED
-- (0x1403c92a0, state 1) +0x33c is zeroed and +0x344 (resilience) GROWS — so a
-- rising resilience, not the gauge, is the record that a stagger happened.
--
--     R.status.watch_stagger()   -- arm the read-only hook (idempotent)
--     R.status.stagger()         -- gauge, resilience (both f32) — nil until a
--                                -- clear_stagger() has run once (that is what
--                                -- captures the controller)
--
-- Deliberately NOT wrapped: CLEAR_CHILLED / CLEAR_ROSE_SEED (0x1403cbc40 /
-- 0x1403cbc60) pass this+0x4c8 to 0x140749720 with no null check, while
-- CLEAR_STATUS checks the same pointer — so it can be null, and they would
-- crash on it; FORCE_DEATH (kills the hero); and the revive events, which are
-- the multiplayer revive flow and are unread.
--
-- MAIN THREAD only (R.schedule.next_main), like every engine-mutating call.
return function(env)
    local R, I = env.R, env.I
    local NE = env.named_event                   -- rsmm/named_event.lua
    local M = {}

    local STAGGER_OFF    = 0x33c                 -- f32, accumulated stagger
    local RESILIENCE_OFF = 0x344                 -- f32, grows per stagger
    local ctl, watched = nil, false

    local function read(c)
        return I.read_f32(c + STAGGER_OFF), I.read_f32(c + RESILIENCE_OFF)
    end

    function M.stagger()
        if not ctl then return nil end
        return read(ctl)
    end

    function M.watch_stagger()
        if watched then return true end
        if not (R.hook and I.resolve and I.read_f32) then return false end
        local va = I.resolve("CharacterController_ClearStagger")
        if not va or va == 0 then
            R.log("[rsmm.status] CharacterController_ClearStagger unresolved — run `rsmm update-data`; watch_stagger unavailable")
            return false
        end
        local ok, slot, why = pcall(R.hook, va, "vp", function(this, next)
            local g0, r0
            if this and this ~= 0 then g0, r0 = read(this) end
            next(this)
            if g0 == nil then return end
            ctl = this
            local g1, r1 = read(this)
            R.log(("[rsmm.status] CLEAR_STAGGER on controller 0x%x: stagger %s -> %s, resilience %s -> %s")
                :format(this, tostring(g0), tostring(g1), tostring(r0), tostring(r1)))
        end)
        if not ok or not slot then
            R.log("[rsmm.status] watch_stagger hook failed: " .. tostring(ok and why or slot))
            return false
        end
        watched = true
        return true
    end

    local function send(name)
        return NE.send_value("R.status", name, NE.T_BOOL, true)
    end

    function M.clear() return send("CLEAR_STATUS") end
    function M.clear_stagger() return send("CLEAR_STAGGER") end
    function M.reset_stagger_resilience() return send("RESET_STAGGER_RESILIENCE") end

    return M
end
