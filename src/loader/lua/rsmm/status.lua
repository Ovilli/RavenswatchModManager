-- R.status — cleanse the hero through the game's own events (EXPERIMENTAL,
-- static RE 2026-10-10). Sent in game 2026-10-10 without error, but the run had
-- no status effect or stagger to clear, so the EFFECT is still unproven.
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
-- Deliberately NOT wrapped: CLEAR_CHILLED / CLEAR_ROSE_SEED (0x1403cbc40 /
-- 0x1403cbc60) pass this+0x4c8 to 0x140749720 with no null check, while
-- CLEAR_STATUS checks the same pointer — so it can be null, and they would
-- crash on it; FORCE_DEATH (kills the hero); and the revive events, which are
-- the multiplayer revive flow and are unread.
--
-- MAIN THREAD only (R.schedule.next_main), like every engine-mutating call.
return function(env)
    local NE = env.named_event                   -- rsmm/named_event.lua
    local M = {}

    local function send(name)
        return NE.send_value("R.status", name, NE.T_BOOL, true)
    end

    function M.clear() return send("CLEAR_STATUS") end
    function M.clear_stagger() return send("CLEAR_STAGGER") end
    function M.reset_stagger_resilience() return send("RESET_STAGGER_RESILIENCE") end

    return M
end
