-- Native overhead nameplates. Engine pointers never leave this module.
-- b9c3: live tree proof 2026-11-14, see docs/_re/NATIVE_NAMEPLATE.md.
return function(env)
    local R, I = env.R, env.I
    local M = {}
    R.nameplate = M
    local CROWN, FRAME = "RSMM_Host_Crown", "Game_UI_Main_Frame"
    local function plausible(p)
        return type(p) == "number" and p >= 0x10000 and p < 0x800000000000 and p % 8 == 0
    end
    local function ptr(p) return I.read_u64(p) end
    local function named_vtable(p, symbol)
        local preferred = R.engine.va(symbol)
        local base = I.module_base()
        return plausible(p) and type(preferred) == "number" and plausible(base)
            and ptr(p) == base + preferred - 0x140000000
    end
    local function widget_name(p)
        local length = I.read_u32(p + 0x288)
        local text = ptr(p + 0x280)
        if type(length) ~= "number" or not plausible(text) then return nil end
        length = length & 0x7fffffff
        if length == 0 then return "" end
        if length > 128 then return nil end
        return I.read_cstr(text, length + 1)
    end
    local function component_name(p)
        local settings = ptr(p + 0x10)
        local text = plausible(settings) and ptr(settings + 0xe8)
        return plausible(text) and I.read_cstr(text, 80) or nil
    end
    local function find_component(entity, name, class, limit)
        if not plausible(entity) or R.rtti.name(entity) ~= "oCEntity" then return nil end
        local data, count = ptr(entity + 0x190), I.read_u32(entity + 0x198)
        if not plausible(data) or type(count) ~= "number" or count < 1 or count > limit then return nil end
        local found
        for i = 0, count - 1 do
            local p = ptr(data + i * 8)
            if not plausible(p) then return nil end
            if component_name(p) == name and R.rtti.name(p) == class then
                if found or ptr(p + 8) ~= entity then return nil end
                found = p
            end
        end
        return found
    end
    local function find_main_frame(ui)
        local component = find_component(ui, "Life Bar Game Ui", "oCEntityCpntGameUi", 512)
        local root = component and ptr(component + 0x88)
        if not named_vtable(root, "UiLayoutWindow_vftable") then return nil end
        local seen, count, frame = {}, 0, nil
        local pending = { root }
        while #pending > 0 do
            local parent = table.remove(pending)
            if widget_name(parent) == FRAME then
                if frame then return nil end
                frame = parent
            end
            local child = ptr(parent + 0x2a8)
            while child ~= -1 do
                if not plausible(child) or seen[child] or count >= 256
                    or ptr(child + 0x298) ~= parent then return nil end
                seen[child], count = true, count + 1
                if named_vtable(child, "UiLayoutWindow_vftable") then
                    pending[#pending + 1] = child
                end
                child = ptr(child + 8)
            end
        end
        return frame
    end
    local function crown_for(hero)
        local entity = ptr(hero + 8)
        local spawner = find_component(entity, "Life Bar Spawner", "oCEntityCpntEntitySpawner", 4096)
        if not spawner then return nil, "life bar unavailable" end
        local ui = ptr(spawner + 0x88)
        local frame = find_main_frame(ui)
        if not frame then return nil, "HP frame unavailable" end
        if not named_vtable(frame, "UiLayoutWindow_vftable") or widget_name(frame) ~= FRAME then
            return nil, "HP frame identity mismatch"
        end
        -- The renderer traverses an intrusive sibling list, NOT the separate
        -- window/controller vector at +0x310. Validate every direct child.
        local p, seen, crown, count = ptr(frame + 0x2a8), {}, nil, 0
        while p ~= -1 and p ~= 0xffffffffffffffff do
            if not plausible(p) or seen[p] or count >= 64 or ptr(p + 0x298) ~= frame then
                return nil, "invalid HP-frame children"
            end
            seen[p], count = true, count + 1
            if widget_name(p) == CROWN then
                if crown or not named_vtable(p, "UiPicture_vftable") then
                    return nil, "crown identity mismatch"
                end
                local first = ptr(p + 0x2a8)
                if first ~= -1 and first ~= 0xffffffffffffffff then return nil, "crown is not a leaf" end
                crown = p
            end
            p = ptr(p + 8)
        end
        if not crown then return nil, "crown asset not loaded" end
        return { widget = crown, frame = frame, entity = entity }
    end
    local function heroes()
        local result, seen = {}, {}
        local function add(p)
            if plausible(p) and not seen[p] and not R.entity._retired(p)
                and R.entity._is_live(p) and R.entity._is_hero_object(p) then
                seen[p] = true
                result[#result + 1] = p
            end
        end
        add(R.entity.hero())
        if I.shared_get then
            -- Native spawn capture ring. Never infer host from ring order.
            for slot = 8, 15 do add(I.shared_get(slot)) end
        end
        return result
    end
    local function inspect()
        if not I.va_trusted or I.va_trusted() ~= true then
            return { status = "unavailable", reason = "game build is not trusted", players = {} }, {}
        end
        if R.entity._scene() ~= true then
            return { status = "unavailable", reason = "not in a game scene", players = {} }, {}
        end
        local state, host = R.net.session_state(), R.net.session_host()
        local result, resolved = { status = "unavailable", players = {}, session_state = state }, {}
        local function id(v) return type(v) == "number" and string.format("%x", v) or nil end
        result.host = id(host)
        for _, hero in ipairs(heroes()) do
            local target, reason = crown_for(hero)
            local row = { status = target and "found" or "unavailable", reason = reason }
            if target then
                local owner = R.net.owner(target.entity)
                row.owner = id(owner)
                row.host_known = state == 5 and host ~= nil and owner ~= nil
                row.is_host = row.host_known and owner == host
                local flags = I.read_u8(target.widget + 0x234)
                row.visible = type(flags) == "number" and (flags & 0x10) ~= 0 or false
                row.alpha = I.read_f32(target.widget + 0x2dc)
                target.row = row
                resolved[#resolved + 1] = target
            end
            result.players[#result.players + 1] = row
        end
        if #resolved > 0 then result.status = "captured"
        else result.reason = "no live crown found" end
        return result, resolved
    end
    --- A fresh, read-only snapshot; no addresses or widget handles are exposed.
    --- Unknown host identity is explicit. This function never changes visibility.
    function M.inspect()
        local result = inspect()
        return result
    end

    --- Reconcile native host crowns on the gameplay thread. Call from every_main.
    --- Solo, disconnected, and unknown owners all resolve to hidden.
    function M.update_host_crowns()
        local result, targets = inspect()
        if #targets == 0 then return result end
        if not R.engine.resolve("UiElement_SetVisible") then
            result.status = "unavailable"
            result.reason = "native visibility symbol unavailable"
            return result
        end
        result.changed = 0
        for _, target in ipairs(targets) do
            local widget = target.widget
            local flags = I.read_u8(widget + 0x234)
            if flags ~= nil and ((flags & 0x10) ~= 0) ~= target.row.is_host then
                R.engine.call_safe("UiElement_SetVisible", {{1, function(p)
                    return named_vtable(p, "UiPicture_vftable")
                        and ptr(p + 0x298) == target.frame and ptr(p + 0x2a8) == -1
                        and widget_name(p) == CROWN
                end}}, widget, target.row.is_host and 1 or 0, 1)
                flags = I.read_u8(widget + 0x234)
                if flags ~= nil and ((flags & 0x10) ~= 0) == target.row.is_host then
                    result.changed = result.changed + 1
                end
            end
            if flags ~= nil then
                target.row.visible = (flags & 0x10) ~= 0
                target.row.alpha = I.read_f32(widget + 0x2dc)
            end
        end
        return result
    end
end
