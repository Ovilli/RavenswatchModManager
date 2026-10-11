-- R.give.remove_random / remove_all / duplicate_random — take items away or
-- copy one, through the game's own item events. PROVEN IN GAME 2026-10-10:
-- duplicate_random(), remove_random() and remove_all() (any rarity) changed
-- the item bar +1, -1 and to zero. The per-rarity variants use the same picker
-- and remover with another rarity code; they have not been exercised in game.
--
--     R.give.remove_random("cursed")    -- one random cursed item
--     R.give.remove_random()            -- one random item of any rarity
--     R.give.remove_all("cursed")       -- every cursed item
--     R.give.duplicate_random("epic")   -- a second copy of a random epic
--     R.give.rarities                   -- { "common", "rare", ... }
--
-- Each sends one event to the hero (REMOVE_RANDOM_<R>_OBJECT,
-- REMOVE_ALL_<R>_OBJECT, DUPLICATE_RANDOM_<R>_OBJECT; "any" = MAGICAL). Their
-- hero handlers (0x1403a8a50.., 0x1403a8c70.., 0x1403a80c0..) read NO payload:
-- they pass a rarity code (0 common, 1 rare, 2 epic, 3 legendary, 4 cursed,
-- 6 any) to a picker that walks the hero's owned items (hero+0xd80) and
-- returns a random one's GUID, then remove it — or, for duplicate, grant it
-- again through Hero_GrantMagicalObject tagged "Duplicate". So the event is
-- sent in the same with-data shape the ability events use, carrying a bool.
-- With nothing of that rarity owned, the engine does nothing.
--
-- Duplicate exists for common, rare and epic only; "any" duplicates one of
-- those three, never a legendary or cursed item (the engine's own rule).
--
-- MAIN THREAD only (R.schedule.next_main), like every engine-mutating call.
return function(env)
    local R = env.R
    local NE = env.named_event                   -- rsmm/named_event.lua
    local M = {}

    local RARITIES = { "common", "rare", "epic", "legendary", "cursed" }
    local NAME = { common = "COMMON", rare = "RARE", epic = "EPIC",
                   legendary = "LEGENDARY", cursed = "CURSED", any = "MAGICAL" }
    local DUPLICABLE = { common = true, rare = true, epic = true, any = true }
    M.rarities = RARITIES

    local function event_for(fmt, rarity, fn, allowed)
        local key = rarity == nil and "any" or (type(rarity) == "string" and rarity:lower() or nil)
        if not key or not NAME[key] or (allowed and not allowed[key]) then
            local ok = {}
            for _, r in ipairs(RARITIES) do
                if not allowed or allowed[r] then ok[#ok + 1] = r end
            end
            R.log("[rsmm.give] " .. fn .. ": unknown rarity " .. tostring(rarity)
                .. " (one of " .. table.concat(ok, ", ") .. ", or nil for any)")
            return nil
        end
        return string.format(fmt, NAME[key])
    end

    local function send(name)
        return name ~= nil and NE.send_value("R.give", name, NE.T_BOOL, true)
    end

    function M.remove_random(rarity)
        return send(event_for("REMOVE_RANDOM_%s_OBJECT", rarity, "remove_random"))
    end

    function M.remove_all(rarity)
        return send(event_for("REMOVE_ALL_%s_OBJECT", rarity, "remove_all"))
    end

    function M.duplicate_random(rarity)
        return send(event_for("DUPLICATE_RANDOM_%s_OBJECT", rarity, "duplicate_random", DUPLICABLE))
    end

    return M
end
