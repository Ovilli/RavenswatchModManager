-- Shared builder for the game's own named events, sent to the local hero.
--
-- Not a public namespace: rsmm.lua builds one of these and hands it to the
-- submodules that send events by hand (rsmm/ability.lua, rsmm/resources.lua,
-- rsmm/items.lua),
-- so the header layout, the guards and the CRC live in one place.
--
--   local ev = NE.begin("R.ability", VFT_VA, "CLEAR_CD", 0x70)  -- nil = refused (logged)
--   ... write the payload ...
--   NE.send(ev)
--
-- Header, as every named-event ctor writes it (see NamedEvent_GainReroll_Ctor):
-- vft @+0x00, state 2 @+0x08, name oCString {ptr @+0x20, len|0x80000000 @+0x28,
-- 0 @+0x2c}, interned id @+0x30, then +0x38 = -1, +0x40 = 0, +0x48 = -1 (the
-- oCGameNamedEventNetwork fields every subclass here inherits). The name is
-- marked UNOWNED (0x80000000) so the engine never frees our scratch memory.
return function(env)
    local R, I = env.R, env.I
    local give_hero = env.give_hero              -- () -> dispatcher or nil
    local dispatcher_live = env.dispatcher_live  -- (disp) -> bool
    local va_ok = env.va_ok                      -- (feature) -> bool
    local IMG_BASE = env.img_base
    local M = {}

    -- Standard reflected CRC32: the engine interns an event name as
    -- NamedEvent_Id_FromCrc(0, crc32(name)).
    local _crc_table
    function M.crc32(s)
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

    function M.ready()
        local d = give_hero and give_hero() or nil
        return d ~= nil and d ~= 0
    end

    -- Every guard, then a zeroed scratch event with its header written. `extra`
    -- names engine functions the caller will also need. Returns ev, disp.
    function M.begin(feature, vft_va, name, size, extra)
        local tag = "[" .. feature:gsub("^R%.", "rsmm.") .. "] "
        local disp = give_hero and give_hero() or nil
        if not disp or disp == 0 then
            R.log(tag .. "no hero dispatcher yet — the hero must act once first")
            return nil
        end
        if not dispatcher_live(disp) then
            R.log(tag .. "hero dispatcher is not live — refusing")
            return nil
        end
        if not va_ok(feature) then return nil end
        local need = { "NamedEvent_Dispatch", "NamedEvent_Id_FromCrc" }
        for _, n in ipairs(extra or {}) do need[#need + 1] = n end
        for _, n in ipairs(need) do
            if not R.engine.resolve(n) then
                R.log(tag .. "event primitives unresolved on this build (" .. n .. ") — refusing")
                return nil
            end
        end
        local base = I.module_base()
        if not base or base == 0 then return nil end
        local vft = base + (vft_va - IMG_BASE)
        local slot0 = I.read_u64(vft)
        if not slot0 or slot0 < base or slot0 >= base + 0x1600000 then
            R.log(tag .. "event vftable implausible on this build — refusing")
            return nil
        end
        -- ONE scratch block: event + name tail. A second allocation while this
        -- one is live can overlap and zero its front.
        local ev = I.scratch(size + #name + 1)
        if not ev or ev == 0 then return nil end
        local tail = ev + size
        for i = 1, #name do I.write_u8(tail + i - 1, name:byte(i)) end
        I.write_u8(tail + #name, 0)
        I.write_u64(ev + 0x00, vft)
        I.write_u32(ev + 0x08, 2)
        I.write_u64(ev + 0x10, 0)
        I.write_u64(ev + 0x18, 0)
        I.write_u64(ev + 0x20, tail)
        I.write_u32(ev + 0x28, 0x80000000 + #name)
        I.write_u32(ev + 0x2c, 0)
        I.write_u32(ev + 0x30, R.engine.call("NamedEvent_Id_FromCrc", 0, M.crc32(name)) or 0)
        I.write_u64(ev + 0x38, 0xffffffffffffffff)
        I.write_u32(ev + 0x40, 0)
        I.write_u32(ev + 0x44, 0)
        I.write_u64(ev + 0x48, 0xffffffffffffffff)
        return ev, disp
    end

    function M.send(feature, ev, disp, detail)
        R.engine.call("NamedEvent_Dispatch", disp, ev)
        R.log(string.format("[%s] dispatched %s %s disp=0x%x id=0x%x",
            feature:gsub("^R%.", "rsmm."), R.engine.event_name(ev) or "?", detail or "",
            disp, I.read_u32(ev + 0x30) or 0))
        return true
    end

    -- oCNamedEventNetworkWithData: the header plus ONE typed value, an
    -- oCEntityValueUnion at +0x50 (storage @+0x58, 4 = inline; value @+0x60,
    -- or a heap pointer for type 1; type byte @+0x68). The class the ability
    -- events require, and a safe carrier for any event whose handler reads no
    -- payload (the item events).
    local WD_VFT_VA = 0x140f0f180                -- oCNamedEventNetworkWithData_vftable
    local WD_SIZE, UNION_OFF = 0x70, 0x50
    M.T_F32, M.T_INT, M.T_BOOL = 0, 1, 2

    -- Build and dispatch one with-data event. `vtype` is M.T_F32/T_INT/T_BOOL.
    function M.send_value(feature, name, vtype, value)
        local tag = "[" .. feature:gsub("^R%.", "rsmm.") .. "] "
        local ev, disp = M.begin(feature, WD_VFT_VA, name, WD_SIZE,
            { "EntityValueUnion_DefaultCtor", "EntityValueUnion_InitAsType",
              "EntityValueUnion_Destruct" })
        if not ev then return false end
        -- The value goes through the engine's own union routines: the bus
        -- CLONES the event before delivering it, and the clone copies the
        -- union through its vftable, which only the ctor sets.
        local u = ev + UNION_OFF
        R.engine.call("EntityValueUnion_DefaultCtor", u)
        if vtype ~= M.T_F32 then R.engine.call("EntityValueUnion_InitAsType", u, vtype) end
        -- Storage is 4 = inline at +0x10, or else a heap pointer (low bit is a
        -- flag): type 1 is a 16-byte type the engine allocates out of line
        -- (measured in game 2026-10-10, storage=0x6247d230), and the charge
        -- handler reads its first int32 there — the same either-or it uses.
        local storage = I.read_u64(u + 0x08) or 0
        local data = storage == 4 and u + 0x10 or (storage & ~1)
        if I.read_u8(u + 0x18) ~= vtype or (storage ~= 4 and not R.ptr.plausible(data)) then
            R.log(string.format(tag .. "value union did not initialise as type %d "
                .. "(storage=0x%x type=%s) — refusing", vtype, storage,
                tostring(I.read_u8(u + 0x18))))
            R.engine.call("EntityValueUnion_Destruct", u)
            return false
        end
        if vtype == M.T_F32 then
            I.write_f32(data, value)
        elseif vtype == M.T_INT then
            I.write_u32(data, value & 0xffffffff)
        else
            I.write_u8(data, value and 1 or 0)
        end
        local sent = M.send(feature, ev, disp, "value=" .. tostring(value))
        -- Delivery went to the engine's clone; free what InitAsType allocated
        -- for ours (a no-op for an inline value).
        R.engine.call("EntityValueUnion_Destruct", u)
        return sent
    end

    return M
end
