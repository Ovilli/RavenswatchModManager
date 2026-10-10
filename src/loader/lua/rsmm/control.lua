-- R.control — freeze and release the hero's input through the game's own
-- LOCK_CONTROL / UNLOCK_CONTROL events. PROVEN IN GAME 2026-10-10: lock() froze
-- the hero and release() gave control back.
--
--     R.control.lock()       -- one lock (the game counts them)
--     R.control.unlock()     -- one unlock
--     R.control.release()    -- every lock THIS SDK took, undone
--     R.control.held()       -- how many locks this SDK holds
--
-- Hero handlers (subscribed in NamedEvent_HeroSubscribeAll, no payload):
--   LOCK_CONTROL    0x1403a7580: ++hero+0xc50; if byte hero+0xc54 ~= 0 -> 0x1403a1380
--   UNLOCK_CONTROL  0x1403a75a0: if hero+0xc50 > 0 then --; once it is 0 and
--                   byte hero+0xc54 == 0 -> 0x1403a12c0
-- The lock is a COUNT, so a mod that locks and then errors would leave the
-- player frozen. This module counts its own locks, never sends an unlock it
-- does not owe, and forgets them when a run or chapter ends (that destroys the
-- hero entity the counter lives on). release() undoes them mid-run.
-- What +0xc54 means (the two handlers branch on it in opposite senses) is not
-- established statically — the in-game test decides what lock() visibly does.
--
-- MAIN THREAD only (R.schedule.next_main), like every engine-mutating call.
return function(env)
    local R = env.R
    local NE = env.named_event                   -- rsmm/named_event.lua
    local M = {}
    local held = 0

    local function send(name)
        return NE.send_value("R.control", name, NE.T_BOOL, true)
    end

    function M.held() return held end

    function M.lock()
        if not send("LOCK_CONTROL") then return false end
        held = held + 1
        return true
    end

    function M.unlock()
        if held == 0 then
            R.log("[rsmm.control] unlock: this SDK holds no lock — not sending one it does not owe")
            return false
        end
        if not send("UNLOCK_CONTROL") then return false end
        held = held - 1
        return true
    end

    function M.release()
        local n = 0
        while held > 0 and M.unlock() do n = n + 1 end
        return n
    end

    -- A run boundary destroys the hero entity the counter lives on; the next
    -- hero starts unlocked, so the debt is void rather than owed.
    R.on("run:end", function() held = 0 end)
    R.on("run:start", function() held = 0 end)
    R.on("gameplay:GAME_END_NEXT_CHAPTER", function() held = 0 end)

    return M
end
