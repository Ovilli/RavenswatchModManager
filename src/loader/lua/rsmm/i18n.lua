-- R.i18n — translation lookup. Loader publishes the active locale's
-- string table; this module wraps it with format() substitution.

local M = {}

local function _table()
    if _G.rsmm and _G.rsmm._internal.i18n_table then
        return _G.rsmm._internal.i18n_table() or {}
    end
    return {}
end

local function _interp(s, vars)
    if not vars then return s end
    return (s:gsub("{(%w+)}", function(k)
        local v = vars[k]
        if v == nil then return "{" .. k .. "}" end
        return tostring(v)
    end))
end

function M.t(key, vars)
    local tbl = _table()
    local v = tbl[key]
    if v == nil then
        return key
    end
    return _interp(v, vars)
end

function M.has(key)
    return _table()[key] ~= nil
end

function M.locale()
    if _G.rsmm and _G.rsmm._internal.i18n_locale then
        return _G.rsmm._internal.i18n_locale()
    end
    return "EN"
end

return M
