-- Read-only recon for the native OVERHEAD nameplate, not the teammate HUD.
-- No new hooks, engine calls, writes, or retained pointers. Candidate fields
-- are reported as observations, never used to draw or identify the host.
-- Reusable development API. Keep it opt-in and separate from rendering APIs.
return function(env)
    local R, I = env.R, env.I
    local MAX_COMPONENTS, MAX_READS = 4096, 24000
    local function plausible(p)
        return type(p) == "number" and p >= 0x10000 and p < 0x0000800000000000
            and p % 8 == 0
    end
    R.debug = R.debug or {}
    function R.debug.nameplate_snapshot()
        local result = { status = "unavailable", entities = {}, reads = 0 }
        -- Unlike the legacy SDK helper, unknown trust fails closed here.
        if not I.va_trusted or I.va_trusted() ~= true then
            result.reason = "game build is not trusted"; return result
        end
        local function read(kind, p)
            if result.reads >= MAX_READS then result.truncated = true; return nil end
            result.reads = result.reads + 1
            local fn = I[kind]
            if type(fn) ~= "function" or type(p) ~= "number" then return nil end
            return fn(p)
        end
        local function ptr(p) return read("read_u64", p) end
        local function cls(p)
            if not plausible(p) then return nil end
            -- RTTI uses guarded reads internally; cap its use separately by
            -- charging its maximum walk against our snapshot budget.
            if result.reads + 10 > MAX_READS then result.truncated = true; return nil end
            result.reads = result.reads + 10
            return R.rtti.name(p)
        end
        local function name(p)
            local settings = ptr(p + 0x10)
            if not plausible(settings) then return "?" end
            local text = ptr(settings + 0xe8)
            if not plausible(text) or not I.read_cstr then return "?" end
            result.reads = result.reads + 1
            local value = I.read_cstr(text, 160)
            return type(value) == "string" and value:gsub("[%c]", " ") or "?"
        end
        local function components(entity)
            if cls(entity) ~= "oCEntity" then return nil end
            local data, count = ptr(entity + 0x190), read("read_u32", entity + 0x198)
            if not plausible(data) or type(count) ~= "number" or count < 1
                or count > MAX_COMPONENTS then return nil end
            local out = {}
            for j = 0, count - 1 do
                local p = ptr(data + j * 8)
                if not plausible(p) then return nil end
                out[#out + 1] = p
            end
            return out
        end
        local hero = R.entity.hero()
        if not plausible(hero) then result.reason = "hero not captured"; return result end
        local entity = ptr(hero + 8)
        local all = components(entity)
        if not all then result.reason = "hero entity unreadable"; return result end
        result.status = "partial"
        result.hero = hero
        result.session_state = R.net.session_state()
        result.host = R.net.session_host()
        result.local_owner = R.net.owner(entity)
        -- Owners are compared only when both APIs have real identities.
        result.local_is_host = result.session_state == 5 and result.host ~= nil
            and result.local_owner ~= nil and result.host == result.local_owner
        local seen, queue = {}, { { entity = entity, via = "local hero", depth = 0 } }
        local function enqueue(p, via, depth)
            if depth <= 2 and #queue < 12 and not seen[p] and cls(p) == "oCEntity" then
                seen[p] = true
                queue[#queue + 1] = { entity = p, via = via, depth = depth }
            end
        end
        seen[entity] = true
        local function pointers(p, row, depth)
            row.links = {}
            for off = 0x68, 0x238, 8 do
                local q = ptr(p + off)
                local kind = cls(q)
                if kind then
                    row.links[#row.links + 1] = { offset = off, ptr = q, class = kind }
                    enqueue(q, row.name .. string.format("+%x", off), depth + 1)
                end
                -- A spawner can own a short vector of spawned entities.
                local n = plausible(q) and read("read_u32", p + off + 8) or nil
                if type(n) == "number" and n >= 1 and n <= 8 then
                    for j = 0, n - 1 do
                        local item = ptr(q + j * 8)
                        if plausible(item) then
                            enqueue(item, row.name .. string.format("+%x[%d]", off, j), depth + 1)
                        end
                    end
                end
            end
        end
        local i = 1
        while i <= #queue and not result.truncated do
            local current = queue[i]; i = i + 1
            local parts = components(current.entity)
            if parts then
                local entry = { ptr = current.entity, via = current.via, components = {} }
                result.entities[#result.entities + 1] = entry
                for _, p in ipairs(parts) do
                    if result.truncated then break end
                    local nm = name(p)
                    local lower = nm:lower()
                    -- Restrict detailed scans on the 1,500+ component hero to
                    -- life-bar/nameplate objects. UI child entities are small.
                    if current.depth > 0 or lower == "life bar spawner" then
                        local kind = cls(p)
                        local row = { ptr = p, name = nm, class = kind or "?" }
                        entry.components[#entry.components + 1] = row
                        if current.depth > 0 and lower:find("top bar text", 1, true)
                            and kind == "oCEntityCpntLabelUi" then
                            result.nameplate_found = true
                        end
                        if kind and (lower == "life bar spawner"
                            or kind == "oCEntityCpntGameUi"
                            or lower:find("top bar", 1, true)
                            or lower == "username window ui") then
                            pointers(p, row, current.depth)
                        end
                    end
                end
            end
        end
        if result.nameplate_found and not result.truncated then
            result.status = "captured"
        else
            result.reason = result.truncated and "read budget reached" or "overhead nameplate not found"
        end
        -- Address/identity values stay integers all the way to hex strings;
        -- never round 64-bit network identities through floating-point JSON.
        local function hex(v) return type(v) == "number" and string.format("%x", v) or "unknown" end
        R.log(string.format("[nameplate-probe] status=%s session=%s host=%s owner=%s local_is_host=%s reads=%d truncated=%s",
            result.status, tostring(result.session_state), hex(result.host), hex(result.local_owner),
            tostring(result.local_is_host), result.reads, tostring(result.truncated == true)))
        for _, e in ipairs(result.entities) do
            R.log("[nameplate-probe] entity=" .. hex(e.ptr) .. " via=" .. e.via)
            for _, c in ipairs(e.components) do
                R.log("[nameplate-probe] component=" .. hex(c.ptr) .. " " .. c.class .. " | " .. c.name)
                for _, link in ipairs(c.links or {}) do
                    R.log(string.format("[nameplate-probe]   +%x -> %s %s", link.offset, hex(link.ptr), link.class))
                end
            end
        end
        return result
    end
end
