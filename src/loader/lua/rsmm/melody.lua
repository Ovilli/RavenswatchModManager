-- R.melody — give or take the hero's melodies through the game's own events
-- choose() DOES NOT WORK (in game 2026-10-10): choose("Reveal_Map") plus 13 notes
-- filled the bar twice and granted two melodies, neither Reveal_Map — the game's
-- random pick wins. Notes (R.ingredient.add("Note")) do fill the bar. remove()
-- is sent without error; its effect is unseen.
--
--     R.melody.choose("Fully_Heal")    -- CHOOSE_MELODY: start COLLECTING it
--     R.melody.remove("Fully_Heal")    -- REMOVE_MELODY
--     R.melody.names()                 -- the melodies loaded this session
--
-- choose() does NOT play the melody: the apply routine 0x1403988c0 gets the
-- melody's component (0x1403abed0) and sets its state to 1 = COLLECTING
-- (0x1402db390); the effect fires when notes complete it (state 2). Notes are
-- the "Note" ingredient, so R.ingredient.add("Note", n) moves it along.
--
-- A melody is named by its DEFINITION'S NAME STRING, not a GUID. Both hero
-- handlers (CHOOSE 0x140399090, REMOVE 0x140399150) check the event class,
-- take the oCString at +0x50 {ptr, len|flags @+0x58}, and pass it to
-- 0x1403afa90, which walks the live MelodyDefinitions comparing it with
-- *(*(def+0x48)+0x18) — the definition's own resource-name string; the match
-- goes to the registry lookup 0x14025ac40 and then the apply/remove. This
-- replaces the first R.melody.choose(lo, hi), which wrote a GUID into
-- +0x38/+0x48 (a guess; the class is only built by a network factory) and
-- left +0x50 empty — the lookup of an empty name finds nothing.
--
-- So names() reads those strings from the live defs, and choose/remove accept
-- either that exact string or its bare stem ("Fully_Heal" for
-- "...\Fully_Heal.entity.ot"), and send the live string verbatim.
--
-- Events (0x60 bytes; ctors 0x1402da150 / 0x1402da320): the standard header,
-- +0x38/+0x48 = -1, +0x40 = 0, then the name oCString at +0x50/+0x58/+0x5c.
--
-- MAIN THREAD only (R.schedule.next_main), like every engine-mutating call.
return function(env)
    local R, I = env.R, env.I
    local NE = env.named_event                   -- rsmm/named_event.lua
    local M = {}

    local CHOOSE_VFT_VA = 0x140f25c48            -- oCGameNamedEventChooseMelody_vftable
    local REMOVE_VFT_VA = 0x140f22608            -- oCGameNamedEventRemoveMelody_vftable
    local EV_SIZE, DEF_NAME_OFF, NAME_STR_OFF = 0x60, 0x48, 0x18

    local function stem(s)
        return (s:gsub("^.*[\\/]", ""):gsub("%..*$", ""))
    end

    -- { { name = live string, stem = bare name } ... } from the live defs.
    local function catalog()
        local out = {}
        if not (R.defs and R.defs.instances) then return out end
        for _, def in ipairs(R.defs.instances("MelodyDefinition")) do
            local o = I.read_u64(def + DEF_NAME_OFF)
            local sp = o and R.ptr.plausible(o) and I.read_u64(o + NAME_STR_OFF) or nil
            local s = sp and R.ptr.plausible(sp) and I.read_cstr(sp, 256) or nil
            if s and s ~= "" then out[#out + 1] = { name = s, stem = stem(s) } end
        end
        return out
    end

    function M.names()
        local out = {}
        for _, e in ipairs(catalog()) do out[#out + 1] = e.stem end
        table.sort(out)
        return out
    end

    local function resolve(which, fn)
        if type(which) ~= "string" or which == "" then
            R.log("[rsmm.melody] " .. fn .. ": name a melody (R.melody.names())")
            return nil
        end
        local want = which:lower()
        for _, e in ipairs(catalog()) do
            if e.name:lower() == want or e.stem:lower() == want then return e.name end
        end
        local known = M.names()
        R.log("[rsmm.melody] " .. fn .. ": no melody named " .. which
            .. (#known > 0 and (" (loaded: " .. table.concat(known, ", ") .. ")")
                or " (no melody definitions are loaded yet)"))
        return nil
    end

    local function send(event, vft_va, which, fn)
        local live = resolve(which, fn)
        if not live then return false end
        -- The melody name lives in the same scratch block, after the event
        -- (NE.begin puts the event-name tail after `size`).
        -- Padded to 8: the event name goes right after it, and R.engine.event_name
        -- only accepts an aligned string pointer (unaligned logged "dispatched ?").
        local ev, disp = NE.begin("R.melody", vft_va, event, EV_SIZE + ((#live + 1 + 7) & ~7))
        if not ev then return false end
        local s = ev + EV_SIZE
        for i = 1, #live do I.write_u8(s + i - 1, live:byte(i)) end
        I.write_u8(s + #live, 0)
        I.write_u64(ev + 0x50, s)
        I.write_u32(ev + 0x58, 0x80000000 + #live)   -- unowned: never freed by the engine
        I.write_u32(ev + 0x5c, 0)
        return NE.send("R.melody", ev, disp, stem(live))
    end

    function M.choose(which) return send("CHOOSE_MELODY", CHOOSE_VFT_VA, which, "choose") end
    function M.remove(which) return send("REMOVE_MELODY", REMOVE_VFT_VA, which, "remove") end

    return M
end
