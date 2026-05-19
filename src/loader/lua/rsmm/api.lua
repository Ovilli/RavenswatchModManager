-- R.api — inter-mod API registry. Producer exposes a table; consumer
-- requires by name + optional semver spec. Errors caught at the boundary
-- so a producer crash never escapes to the consumer.

local M = {}
local _registry = {}   -- name -> { mod_id, version, table }

local function _parse_ver(s)
    local out = {}
    for p in tostring(s or "0"):gmatch("%d+") do table.insert(out, tonumber(p)) end
    if #out == 0 then return {0} end
    return out
end

local function _cmp(a, b)
    local n = math.max(#a, #b)
    for i = 1, n do
        local ai, bi = a[i] or 0, b[i] or 0
        if ai ~= bi then return ai < bi and -1 or 1 end
    end
    return 0
end

local function _match(have, op, want)
    local c = _cmp(_parse_ver(have), _parse_ver(want))
    if op == ">="  then return c >= 0 end
    if op == "<="  then return c <= 0 end
    if op == ">"   then return c >  0 end
    if op == "<"   then return c <  0 end
    if op == "=="  or op == "=" then return c == 0 end
    if op == "!="  then return c ~= 0 end
    return true
end

local function _satisfies(have, spec)
    if not spec or spec == "" then return true end
    for clause in tostring(spec):gmatch("[^,]+") do
        local op, ver = clause:match("^%s*([<>=!]+)%s*(.+)%s*$")
        op = op or ">="
        ver = ver or clause:match("(%S+)")
        if not _match(have, op, ver) then return false end
    end
    return true
end

function M.expose(tbl)
    local self_id = _G.rsmm and _G.rsmm._internal.self_id and _G.rsmm._internal.self_id() or "?"
    local version = tbl.version or "0.0.0"
    local api_name = tbl.api_name or self_id
    if _registry[api_name] then
        error("rsmm.api.expose: name already taken: " .. api_name, 2)
    end
    _registry[api_name] = { mod_id = self_id, version = version, table = tbl }
end

function M.require(name, spec)
    local entry = _registry[name]
    if not entry then error("rsmm.api: not found: " .. name, 2) end
    if spec and not _satisfies(entry.version, spec) then
        error(("rsmm.api: %s %s does not satisfy %s"):format(
            name, entry.version, spec), 2)
    end
    local proxy = {}
    setmetatable(proxy, { __index = function(_, k)
        local fn = entry.table[k]
        if type(fn) ~= "function" then return fn end
        return function(...)
            local ok, r = pcall(fn, ...)
            if not ok then
                error(("rsmm.api: %s.%s raised: %s"):format(entry.mod_id, k, r), 2)
            end
            return r
        end
    end, __newindex = function() error("rsmm.api: proxy is read-only", 2) end })
    return proxy
end

function M.has(name) return _registry[name] ~= nil end
function M.list()
    local out = {}
    for n, e in pairs(_registry) do out[n] = { mod_id = e.mod_id, version = e.version } end
    return out
end

return M
