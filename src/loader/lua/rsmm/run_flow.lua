-- R.run.next_chapter / win / lose — end the current chapter or the whole run
-- through the game's own GAME_END_* events. PROVEN IN GAME 2026-10-10:
-- next_chapter() loaded the next chapter and win() ended the run as won (before
-- the current-chapter guards below were added; those are spec-tested). lose()
-- is unexercised.
--
--     R.run.next_chapter()    -- finish the chapter as a success (GAME_END_SUCCESS):
--                             -- the next chapter loads, or the run is won after the last
--     R.run.win()             -- end the run as won now (GAME_END_SUCCESS_SKIP_NEXT)
--     R.run.lose()            -- end the run as lost (GAME_END_FAILED)
--     R.run.world_ready()     -- false until the world dispatcher has been seen
--
-- These are WORLD events, not hero events: the game-mode controller subscribes
-- them (0x140284db0) on the channel map of the oCEntitySceneContext's own
-- dispatcher — context + 0x340, the "world+0x340" in NamedEvent_Dispatch's
-- note. The SDK learns that dispatcher from the bus: any gameplay event whose
-- dispatcher sits 0x340 into an object RTTI-named oCEntitySceneContext.
-- Handlers (no payload): SUCCESS 0x140289000 / SKIP_NEXT 0x140289010 ->
-- 0x140288f30, FAILED 0x140289020. Each returns at once if the game already
-- ended (byte this+0x213), and only acts when a scene context's vtable slot
-- +0xd8 agrees (most likely session authority — so a co-op CLIENT's call does
-- nothing). SUCCESS goes to the next chapter (0x140289d20) when there is one,
-- else to end state 2 (won) through 0x140287930; FAILED is end state 1.
--
-- Current chapter only: the world dispatcher OUTLIVES the chapter, so an end
-- sent while a chapter closes or loads would land on the next one. The SDK
-- learns it only inside a live chapter (after GAME_START / MAP_GENERATION_DONE /
-- GAME_CHRONO_START), forgets it at every GAME_END_* and run boundary, takes one
-- end per chapter, and refuses in a menu, a loading screen or a victory/defeat
-- sequence when the game's location values say so.
--
-- Not wrapped: GAME_END_NEXT_CHAPTER (the level-load step that follows a
-- success — sending it directly skips the chapter-end sequence) and
-- TELEPORT_SUBMAP_ENTER/EXIT, which only RECORD a move that already happened
-- (they set the player-location flags; nothing is teleported).
--
-- MAIN THREAD only (R.schedule.next_main), like every engine-mutating call.
return function(env)
    local R = env.R
    local NE = env.named_event                   -- rsmm/named_event.lua
    local M = {}

    local WORLD_DISPATCHER_OFF = 0x340
    local OWNER_CLASS = "oCEntitySceneContext"
    local world, seen, seen_n = nil, {}, 0

    -- THE CURRENT CHAPTER, NOT THE NEXT ONE. The world dispatcher outlives the
    -- chapter (measured 2026-10-10: the same pointer before and after a chapter
    -- switch), so an end sent while a chapter is closing or loading would land
    -- on the NEXT one. So: the dispatcher is learned only inside a live chapter
    -- and forgotten at every boundary, and each chapter takes at most one end.
    local CHAPTER_START = { ["gameplay:GAME_START"] = true, ["gameplay:MAP_GENERATION_DONE"] = true,
                            ["gameplay:GAME_CHRONO_START"] = true }
    local CHAPTER_END = { ["gameplay:GAME_END_SUCCESS"] = true, ["gameplay:GAME_END_SUCCESS_SKIP_NEXT"] = true,
                          ["gameplay:GAME_END_FAILED"] = true, ["gameplay:GAME_END_CHANGE_STATE"] = true,
                          ["gameplay:GAME_END_NEXT_CHAPTER"] = true }
    local live, ended = false, false

    -- Fresh RTTI check: the scene context is rebuilt with each scene, so a
    -- cached yes is only a hint.
    local function owner_is_world(d)
        local owner = d - WORLD_DISPATCHER_OFF
        if not (R.ptr.plausible(owner) and R.ptr.has_vtable(owner)) then return false end
        local name = R.rtti.name(owner)
        return type(name) == "string" and name:sub(-#OWNER_CLASS) == OWNER_CLASS
    end

    local function forget() world, seen, seen_n = nil, {}, 0 end

    R.on("*", function(ev, name)
        if type(name) ~= "string" or name:sub(1, 9) ~= "gameplay:" then return end
        if CHAPTER_END[name] then live, ended = false, false; forget(); return end
        if CHAPTER_START[name] and not live then live, ended = true, false; forget() end
        if not live then return end
        local d = type(ev) == "table" and type(ev.dispatcher) == "string" and tonumber(ev.dispatcher) or nil
        if not d or d == 0 or d == world or seen[d] == false then return end
        if owner_is_world(d) then
            R.log(string.format("[rsmm.run] world dispatcher 0x%x (from %s)", d, name))
            world = d
        else
            if seen_n > 256 then seen, seen_n = {}, 0 end
            seen[d], seen_n = false, seen_n + 1
        end
    end)
    R.on("run:start", function() live, ended = false, false; forget() end)
    R.on("run:end", function() live, ended = false, false; forget() end)

    function M.world_ready() return live and world ~= nil and owner_is_world(world) end

    -- The game's own location values, when readable: never end a chapter from
    -- a menu, a loading screen, or a victory/defeat that is already playing.
    local BLOCKING = { "is_in_main_menu", "is_in_loading_screen",
                       "is_in_victory_sequence", "is_in_defeat_sequence" }
    local function blocked_by_location()
        if not (R.game and R.game.ready and R.game.ready()) then return nil end
        for _, k in ipairs(BLOCKING) do
            local ok, v = pcall(R.game.get, k)
            if ok and v == 1 then return k end
        end
        return nil
    end

    local function send(name)
        if not live then
            R.log("[rsmm.run] " .. name .. ": no chapter is in play (between chapters, in a "
                .. "menu, or the chapter already ended) — refusing")
            return false
        end
        if ended then
            R.log("[rsmm.run] " .. name .. ": this chapter has already been ended once — "
                .. "refusing, or it would land on the next chapter")
            return false
        end
        local where = blocked_by_location()
        if where then
            R.log("[rsmm.run] " .. name .. ": the game reports " .. where .. " — refusing")
            return false
        end
        if not world then
            R.log("[rsmm.run] " .. name .. ": the world dispatcher has not been seen in this "
                .. "chapter yet (it arrives with the chapter's first world event) — refusing")
            return false
        end
        if not owner_is_world(world) then
            R.log("[rsmm.run] " .. name .. ": the world dispatcher went stale (scene changed) — refusing")
            world = nil
            return false
        end
        local ok = NE.send_value("R.run", name, NE.T_BOOL, true, world)
        if ok then ended = true end
        return ok
    end

    function M.next_chapter() return send("GAME_END_SUCCESS") end
    function M.win() return send("GAME_END_SUCCESS_SKIP_NEXT") end
    function M.lose() return send("GAME_END_FAILED") end

    return M
end
