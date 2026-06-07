-- Example: react to in-game events.
--
-- The loader detours the game's central telemetry sink and re-publishes
-- every named analytics event to the Lua bus by its raw name, so a mod can
-- just R.on("<name>", cb) without any per-event wiring. This is the building
-- block for "when X happens in-game, do Y" mod logic.
--
-- Requires the loader DLL and RSMM_ENABLE_GAME_EVENTS=1 (add it to the Steam
-- launch options). These events are observation-grade: the callback fires
-- AFTER the action with the analytics payload (ev.event, ev.seq), not a live
-- entity handle.

local R = require "rsmm"
R.health.checkpoint("per_mod:ExampleEvents")

-- A counter every kill is the classic demo (R.counter is sugar over R.kv).
R.counter.on("enemy_killed")

-- Or handle events directly. Subscribe to as many as you like.
local watched = {
    "game_start", "run_start", "enemy_killed",
    "level_up_reach", "unlock_hero", "run_end",
}

for _, name in ipairs(watched) do
    R.on(name, function(ev)
        R.log(("[Events] %s (#%d)"):format(ev.event or name, ev.seq or 0))
    end)
end

R.on("ready", function()
    R.log("[Events] subscribed; play the game with RSMM_ENABLE_GAME_EVENTS=1 to see events fire")
end)
