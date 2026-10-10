-- Shared builder for the game's own named events, sent to the local hero.
--
-- Not a public namespace: rsmm.lua builds one of these and hands it to the
-- submodules that send events by hand (rsmm/ability.lua, rsmm/resources.lua),
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

    return M
end
