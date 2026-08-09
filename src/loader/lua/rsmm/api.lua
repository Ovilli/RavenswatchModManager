-- R.api — inter-mod API registry.
--
-- Each mod runs in its OWN lua_State, so a table cannot simply be handed from
-- one mod to another: this module used to keep a plain Lua `_registry` table,
-- which meant a consumer only ever saw APIs exposed by ITSELF. The registry
-- now lives in the loader (rsmm._internal.api_*) and calls are marshalled
-- across states by the native bridge.
--
-- Consequence: the API contract is DATA. Arguments and return values must be
-- nil / boolean / number / string / tables of those. A function argument
-- (callback) cannot cross a state boundary and is rejected loudly rather than
-- arriving as nil — use an event (R.on) for provider->consumer signalling.
--
--   -- provider
--   R.api.expose{ api_name = "loot", version = "1.2.0",
--                 roll = function(tier) return { id = "x", tier = tier } end }
--
--   -- consumer
--   local loot = R.api.require("loot", ">= 1.0")
--   local item = loot.roll(3)

local M = {}

local function _native()
    local g = _G.rsmm
    return g and g._internal or nil
end

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

-- Publish `tbl` under tbl.api_name (default: this mod's id). The table is
-- stashed where the native bridge can reach it, then registered by name.
function M.expose(tbl)
    assert(type(tbl) == "table", "rsmm.api.expose: expects a table")
    local I = _native()
    if not I or not I.api_expose then
        error("rsmm.api.expose: loader too old (no api bridge)", 2)
    end
    local self_id = (I.self_id and I.self_id()) or "?"
    local api_name = tbl.api_name or self_id
    local version = tbl.version or "0.0.0"
    -- api_expose stashes the table in this state's registry under the api
    -- name; the bridge fetches it from there when a consumer calls in.
    I.api_expose(api_name, version, tbl)
    return true
end

function M.has(name)
    local I = _native()
    if not I or not I.api_info then return false end
    return I.api_info(name) ~= nil
end

-- Version of an exposed API, or nil.
function M.version(name)
    local I = _native()
    if not I or not I.api_info then return nil end
    local _, version = I.api_info(name)
    return version
end

function M.require(name, spec)
    local I = _native()
    if not I or not I.api_info then error("rsmm.api: loader too old", 2) end
    local mod_id, version = I.api_info(name)
    if not mod_id then error("rsmm.api: not found: " .. tostring(name), 2) end
    if spec and not _satisfies(version, spec) then
        error(("rsmm.api: %s %s does not satisfy %s"):format(name, version, spec), 2)
    end
    -- Every access becomes a native call into the provider's state. Missing
    -- keys surface as a Lua error at CALL time, matching the old proxy.
    return setmetatable({}, {
        __index = function(_, k)
            return function(...)
                for i = 1, select("#", ...) do
                    if type(select(i, ...)) == "function" then
                        error(("rsmm.api: %s.%s: callbacks cannot cross mods "
                            .. "(have the provider R.emit an event and "
                            .. "subscribe with R.on)"):format(name, k), 2)
                    end
                end
                local ok, res = I.api_call(name, k, ...)
                if not ok then
                    error(("rsmm.api: %s.%s raised: %s"):format(mod_id, k,
                        tostring(res)), 2)
                end
                return res
            end
        end,
        __newindex = function() error("rsmm.api: proxy is read-only", 2) end,
    })
end

function M.list()
    local I = _native()
    if not I or not I.api_list then return {} end
    return I.api_list()
end

return M
