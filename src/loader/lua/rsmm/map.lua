-- R.map — reveal the chapter map.
--
-- WHY THIS EXISTS. Ravenswatch does not show POI icons at the start of a run;
-- the map is fogged and markers are revealed by approaching them or by a crow
-- reveal. That makes "I see no icon" unreadable as evidence — measured
-- 2026-09-05, an Altar of Heroes planted as a control showed no icon at run
-- start either, which invalidated four earlier "the mod's marker is broken"
-- observations. Until the map can be revealed on demand, a missing mod marker
-- and un-explored fog look exactly the same.
--
-- The fog itself is out of reach from assets: `Dt_MinimapFogOfWarEraser`'s
-- `u_CircleRadius` is in the erase stamp's own UV space and saturates at 1.0
-- (0.75 -> 64 grew the cleared area ~20% and no further), the quad is sized
-- engine-side, and the combine step is a compiled shader. So this goes through
-- the game's own mechanic instead.
--
--     R.map.reveal()      fire CROWS_MAP_REVEAL on the local hero's dispatcher
--     R.map.can_reveal()  false when no hero dispatcher has been captured yet
--
-- `CROWS_MAP_REVEAL` is a catalogued gameplay event and
-- `Common_Settings\Minimap_Marker_Reveal_Model` carries a listener for it that
-- drives `State Minimap Marker Displayed` — the state that actually draws the
-- two marker components. So this reveals MARKERS, which is the thing worth
-- seeing; whether it also clears terrain fog is the engine's business.
return function(env)
    local R, I = env.R, env.I
    local give_hero = env.give_hero              -- () -> dispatcher or nil
    local obj_has_vtable = env.obj_has_vtable
    local M = {}
    local _warned_vtable = false

    local EVENT = "CROWS_MAP_REVEAL"

    -- Standard reflected CRC32 (poly 0xEDB88320, init 0xffffffff, final
    -- invert). The engine interns an event name as
    -- `NamedEvent_Id_FromCrc(0, crc32(name))` — that symbol is status=ok, so
    -- only the string hash is done here. `Id_HashString` is the engine's
    -- one-call form and is deliberately NOT used: it is `unverified`, which
    -- means its pattern is pruned and it would resolve to nothing.
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
        for i = 1, #s do
            crc = _crc_table[(crc ~ s:byte(i)) & 0xff] ~ (crc >> 8)
        end
        return (~crc) & 0xffffffff
    end

    --- Has a hero dispatcher been captured yet? The bus learns it from the
    --- first hero-anchored event, so it is nil until the hero has acted once.
    function M.can_reveal()
        local d = give_hero and give_hero() or nil
        return d ~= nil and d ~= 0
    end

    --- Fire CROWS_MAP_REVEAL. Returns true when the event was dispatched.
    ---
    --- MAIN THREAD ONLY — this calls into the engine, so a caller off the game
    --- thread must wrap it in `R.schedule.next_main`.
    --- Clear the once-per-map diagnostic latch.
    function M.rearm() _warned_vtable = false end

    --- Fire the reveal on `disp_override` instead of the hero's dispatcher.
    ---
    --- `NamedEvent_Dispatch` is ENTITY-SCOPED: it reaches the listeners
    --- registered on the dispatcher it is handed. POI markers sit on their own
    --- entities, so dispatching on the hero reveals only hero-scoped listeners
    --- — measured 2026-09-05, one dispatch revealed part of the map and no
    --- amount of repeating it revealed the rest. A world-scoped dispatcher
    --- (the one run/map events arrive on) reaches everything.
    function M.reveal(disp_override)
        local disp = disp_override or (give_hero and give_hero() or nil)
        if not disp or disp == 0 then
            R.log("[rsmm.map] no hero dispatcher yet — the hero must act once first")
            return false
        end
        -- The dispatcher is a raw engine pointer that outlives nothing: a run
        -- ending or a hero switch frees it, and the capture is only refreshed
        -- when an anchor event happens to fire. Native reads are page-guarded,
        -- but the instant a pointer is a call ARGUMENT the engine owns the
        -- deref — this is the loader's #1 crash class. Require a vtable.
        if obj_has_vtable and not obj_has_vtable(disp) then
            -- Report WHY, once. The bus itself accepted this pointer as a hero
            -- dispatcher (that is how it came to be stored), so a refusal here
            -- means the liveness test and the capture disagree — and the same
            -- test guards R.give, so whatever is wrong is wrong there too.
            -- Print the pointer, the qword the test reads as a vtable, and the
            -- module bounds it is compared against; that is the whole test.
            if not _warned_vtable then
                _warned_vtable = true
                local base = I.module_base and I.module_base() or 0
                R.log(string.format(
                    "[rsmm.map] dispatcher 0x%x rejected: [disp]=0x%x, module "
                    .. "base=0x%x — the bus accepted this pointer but "
                    .. "_obj_has_vtable does not, so R.give is refusing too",
                    disp, I.read_u64(disp) or 0, base))
            end
            return false
        end
        if not (R.engine.resolve("NamedEvent_GiveMagicalObject_Ctor")
                and R.engine.resolve("NamedEvent_Id_FromCrc")
                and R.engine.resolve("NamedEvent_Dispatch")) then
            R.log("[rsmm.map] event primitives unresolved on this build — refusing")
            return false
        end

        -- ONE scratch allocation for the event AND its name tail. Never take a
        -- second while the first is live: the native arena may hand back an
        -- overlapping block and zero its front, which once wiped an event's
        -- vftable and crashed the engine mid-dispatch.
        local buf = I.scratch(0x80)
        if not buf or buf == 0 then return false end
        local ev = R.engine.call("NamedEvent_GiveMagicalObject_Ctor", buf)
        if not ev or ev == 0 then
            R.log("[rsmm.map] event ctor failed"); return false
        end

        -- Constructed through the GiveMagicalObject ctor because it is the one
        -- event ctor with a status=ok pattern; the base `oCGameNamedEvent`
        -- vftable is not mined (the payload miner drops the base by
        -- construction-site count). Dispatch routes by the interned id at
        -- +0x30, and the reveal listener reads no payload, so the subclass
        -- vftable is inert here. The MO GUID is zeroed regardless: a
        -- zero-GUID lookup is a documented graceful no-op, so even if a give
        -- handler did run it would grant nothing.
        I.poke(ev + 0x50, 0, 8)
        I.poke(ev + 0x58, 0, 8)

        local tail = buf + 0x60
        for i = 1, #EVENT do I.write_u8(tail + i - 1, EVENT:byte(i)) end
        I.write_u8(tail + #EVENT, 0)
        I.write_u64(ev + 0x20, tail)
        -- len | 0x80000000 marks the string UNOWNED, which is what stops the
        -- engine's destructor from freeing a pointer into our scratch arena.
        I.write_u32(ev + 0x28, 0x80000000 + #EVENT)
        I.write_u32(ev + 0x2c, 0)
        I.write_u32(ev + 0x30, R.engine.call("NamedEvent_Id_FromCrc", 0, crc32(EVENT)) or 0)

        R.engine.call("NamedEvent_Dispatch", disp, ev)
        R.log("[rsmm.map] dispatched " .. EVENT)
        return true
    end

    return M
end
