-- R.ui.menus — the game's book menu pages (a Settings entry that opens a page of
-- categories and rows, built from Lua data).
--
--     R.ui.menus.page("my.page", {
--         title = "My Mod", kind = "categories",
--         categories = function(ctx)
--             return { { id = "a", label = "Alpha",
--                        header = { title = "Alpha", text = "line one\nline two" },
--                        rows = { { id = "speed", label = "Speed",
--                                   choices = { "Slow", "Normal", "Fast" },
--                                   value = 2, default = 2 } } } }
--         end,
--         on_back = function(ctx) return true end,     -- false vetoes the pop
--     })
--     R.ui.menus.entry{ id = "my", title = "My Mod", page = "my.page" }
--     R.on("ui:menus_change", function(e) ... e.page, e.category, e.row, e.index end)
--
-- WHAT IT HOLDS. Nothing but pages: `value` is the initial choice index, `default`
-- the index a reset restores (both 1-BASED, clamped to 1..#choices), and a consumer
-- writes the result wherever it likes from the events. Design and RE facts:
-- docs/2026-11-12-r-ui-menus.md.
--
-- HOW. Lua evaluates `categories(ctx)` and pushes the result to the loader as a JSON
-- snapshot (I.ui_menus_set_page); the loader's detours build the page from that
-- snapshot. The loader emits events back to every mod state.
--
-- THREADING. `categories()` and `on_back()` run in two places: at registration (the
-- caller's thread) AND inside the loader's game-thread detour, as the synchronous
-- internal events `ui:_menus_refresh` (re-evaluate with the new ctx and push a new
-- snapshot) and `ui:_menus_back` (consult on_back; false calls I.ui_menus_veto_back).
-- Keep both fast, free of yields and free of calls that wait on other threads. A
-- throw is caught and logged; the page keeps its last good snapshot (or, if the
-- first evaluation threw, is registered empty).
--
-- PUBLIC EVENTS (not re-emitted here; use R.on): ui:menus_open / ui:menus_close
-- { page, ctx, depth }, ui:menus_select { page, category }, ui:menus_change
-- { page, category, row, index }, ui:menus_reset { page, category }. Indices are
-- 1-based.
--
-- SOFT FAILURE. On a loader without I.ui_menus_* (or with the feature off),
-- available() is false + why and every call returns nil + why.

local M = {}

local R, I

local TOO_OLD = "loader too old for R.ui.menus"

local _pages = {}     -- id -> { def = def, json = last pushed snapshot }
local _entries = {}   -- id -> true

local function log(s) R.log("[R.ui.menus] " .. s) end

-- ── minimal JSON ────────────────────────────────────────────────────────────
-- The SDK's own encoder (rsmm.lua) handles flat rows only and nothing decodes.

local OBJ = setmetatable({}, { __mode = "k" })   -- tables to encode as JSON objects even when empty

local ESC = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r',
              ['\t'] = '\\t', ['\b'] = '\\b', ['\f'] = '\\f' }

local function enc_str(s)
    local body = s:gsub('[%c"\\]', function(c)
        return ESC[c] or string.format("\\u%04x", c:byte())
    end)
    return '"' .. body .. '"'
end

local function encode(v)
    local t = type(v)
    if t == "nil" then return "null" end
    if t == "boolean" then return tostring(v) end
    if t == "number" then
        if v ~= v or v == math.huge or v == -math.huge then return "null" end
        if math.type(v) == "integer" then return tostring(v) end
        return string.format("%.14g", v)
    end
    if t == "string" then return enc_str(v) end
    if t ~= "table" then error("cannot encode " .. t .. " as JSON", 0) end
    local n, count = #v, 0
    for _ in pairs(v) do count = count + 1 end
    local out = {}
    if not OBJ[v] and count == n then
        for i = 1, n do out[i] = encode(v[i]) end
        return "[" .. table.concat(out, ",") .. "]"
    end
    local keys = {}
    for k in pairs(v) do
        if type(k) ~= "string" and type(k) ~= "number" then
            error("cannot encode a table key of type " .. type(k) .. " as JSON", 0)
        end
        keys[#keys + 1] = k
    end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    for i, k in ipairs(keys) do out[i] = enc_str(tostring(k)) .. ":" .. encode(v[k]) end
    return "{" .. table.concat(out, ",") .. "}"
end

-- BMP code point to UTF-8 (4-hex escapes only; surrogate pairs are not recombined).
local function utf8_char(cp)
    if cp < 0x80 then return string.char(cp) end
    if cp < 0x800 then return string.char(0xC0 | (cp >> 6), 0x80 | (cp & 0x3F)) end
    return string.char(0xE0 | (cp >> 12), 0x80 | ((cp >> 6) & 0x3F), 0x80 | (cp & 0x3F))
end

local function decode(s)
    local pos = 1
    local function ws() pos = s:find("%S", pos) or #s + 1 end
    local value
    local function str()
        local out, i = {}, pos + 1
        while true do
            local j = s:find('["\\]', i)
            if not j then error("unterminated string", 0) end
            out[#out + 1] = s:sub(i, j - 1)
            if s:sub(j, j) == '"' then pos = j + 1; return table.concat(out) end
            local e = s:sub(j + 1, j + 1)
            if e == "u" then
                out[#out + 1] = utf8_char(tonumber(s:sub(j + 2, j + 5), 16) or 63)
                i = j + 6
            else
                out[#out + 1] = ({ n = "\n", r = "\r", t = "\t", b = "\b", f = "\f" })[e] or e
                i = j + 2
            end
        end
    end
    function value()
        ws()
        local c = s:sub(pos, pos)
        if c == "{" then
            local t = {}
            pos = pos + 1; ws()
            if s:sub(pos, pos) == "}" then pos = pos + 1; return t end
            while true do
                ws()
                if s:sub(pos, pos) ~= '"' then error("expected a string key", 0) end
                local k = str(); ws()
                if s:sub(pos, pos) ~= ":" then error("expected ':'", 0) end
                pos = pos + 1
                t[k] = value(); ws()
                local d = s:sub(pos, pos); pos = pos + 1
                if d == "}" then return t end
                if d ~= "," then error("expected ',' or '}'", 0) end
            end
        elseif c == "[" then
            local t = {}
            pos = pos + 1; ws()
            if s:sub(pos, pos) == "]" then pos = pos + 1; return t end
            while true do
                t[#t + 1] = value(); ws()
                local d = s:sub(pos, pos); pos = pos + 1
                if d == "]" then return t end
                if d ~= "," then error("expected ',' or ']'", 0) end
            end
        elseif c == '"' then
            return str()
        end
        if s:sub(pos, pos + 3) == "true" then pos = pos + 4; return true end
        if s:sub(pos, pos + 4) == "false" then pos = pos + 5; return false end
        if s:sub(pos, pos + 3) == "null" then pos = pos + 4; return nil end
        local num = s:match("^-?%d+%.?%d*[eE]?[+-]?%d*", pos)
        if not num or num == "" then error("unexpected character at " .. pos, 0) end
        pos = pos + #num
        return tonumber(num)
    end
    local v = value()
    ws()
    if pos <= #s then error("trailing characters at " .. pos, 0) end
    return v
end

M._json = { encode = encode, decode = decode }

-- ── snapshot ────────────────────────────────────────────────────────────────

local function obj(t) OBJ[t] = true; return t end

local function clamp_index(v, n, fallback)
    if type(v) ~= "number" or v ~= v then v = fallback end
    v = math.floor(v)
    if v < 1 then return 1 end
    if v > n then return n end
    return v
end

local function norm_row(row, where)
    assert(type(row) == "table", where .. ": row must be a table")
    assert(type(row.id) == "string", where .. ": row.id must be a string")
    assert(type(row.label) == "string", where .. ": row.label must be a string")
    local out = { id = row.id, label = row.label, readonly = row.readonly == true }
    if out.readonly then
        out.choices = {}
        out.value, out.default = 1, 1
        if row.readonly_text ~= nil then
            assert(type(row.readonly_text) == "string", where .. ": readonly_text must be a string")
            out.readonly_text = row.readonly_text
        end
        return obj(out)
    end
    local ch = row.choices
    assert(type(ch) == "table" and #ch > 0,
           where .. ": choices must be a non-empty list of strings (or readonly = true)")
    out.choices = {}
    for i, c in ipairs(ch) do
        assert(type(c) == "string", where .. ": choice " .. i .. " must be a string")
        out.choices[i] = c
    end
    local n = #out.choices
    out.default = clamp_index(row.default, n, 1)
    out.value = clamp_index(row.value, n, out.default)
    return obj(out)
end

local function norm_category(cat, i)
    local where = "category " .. i
    assert(type(cat) == "table", where .. " must be a table")
    assert(type(cat.id) == "string", where .. ": id must be a string")
    assert(type(cat.label) == "string", where .. ": label must be a string")
    where = "category " .. cat.id
    local header = {}
    if cat.header ~= nil then
        assert(type(cat.header) == "table", where .. ": header must be a table")
        for _, k in ipairs({ "title", "subtitle", "text" }) do
            local v = cat.header[k]
            if v ~= nil then
                assert(type(v) == "string", where .. ": header." .. k .. " must be a string")
                header[k] = v
            end
        end
    end
    local rows = {}
    for j, row in ipairs(cat.rows or {}) do rows[j] = norm_row(row, where) end
    return obj({ id = cat.id, label = cat.label, header = obj(header), rows = rows })
end

-- Evaluate def.categories(ctx) and build the snapshot JSON. Throws on bad data.
local function build(def, ctx)
    local cats = def.categories(ctx)
    assert(type(cats) == "table", "categories() must return a list")
    local out = {}
    for i, cat in ipairs(cats) do out[i] = norm_category(cat, i) end
    return encode(obj({ title = def.title or "", categories = out }))
end

-- Re-evaluate and push. false = categories() threw (last snapshot kept).
local function push(id, ctx)
    local pg = _pages[id]
    local ok, json = pcall(build, pg.def, ctx)
    if not ok then
        log("page " .. id .. ": categories() failed, keeping last snapshot: " .. tostring(json))
        return false
    end
    local pushed, why = I.ui_menus_set_page(id, json)
    if not pushed then return nil, why end
    pg.json = json
    return true
end

-- ── API ─────────────────────────────────────────────────────────────────────

--- true, or false + why (loader too old, a symbol failed to resolve, flag off).
function M.available()
    if type(I) ~= "table" or not I.ui_menus_available then return false, TOO_OLD end
    return I.ui_menus_available()
end

local function usable(fn)
    if type(I) ~= "table" or not I[fn] then return false, TOO_OLD end
    return true
end

--- Register (or replace) a page. Returns a handle for off(), or nil + why.
function M.page(id, def)
    assert(type(id) == "string" and id ~= "", "R.ui.menus.page: id must be a non-empty string")
    assert(type(def) == "table", "R.ui.menus.page: def must be a table")
    assert(type(def.categories) == "function", "R.ui.menus.page: def.categories must be a function")
    assert(def.kind == nil or def.kind == "categories", 'R.ui.menus.page: kind is "categories"')
    assert(def.on_back == nil or type(def.on_back) == "function", "R.ui.menus.page: on_back must be a function")
    local ok, why = usable("ui_menus_set_page")
    if not ok then return nil, why end
    _pages[id] = { def = def }
    local pushed, pwhy = push(id, nil)
    if pushed == false then
        -- the first evaluation threw: register the page empty so entries still resolve
        local empty = encode(obj({ title = def.title or "", categories = {} }))
        pushed, pwhy = I.ui_menus_set_page(id, empty)
        if pushed then _pages[id].json = empty end
    end
    if not pushed then _pages[id] = nil; return nil, pwhy end
    return { kind = "page", id = id }
end

--- Add a Settings entry (after = "settings") or an entry inside another page's
--- column (after = that page's id) that opens `page`. Returns a handle, or nil + why.
function M.entry(spec)
    assert(type(spec) == "table", "R.ui.menus.entry: spec must be a table")
    assert(type(spec.id) == "string" and spec.id ~= "", "R.ui.menus.entry: id must be a non-empty string")
    assert(type(spec.title) == "string", "R.ui.menus.entry: title must be a string")
    assert(type(spec.page) == "string", "R.ui.menus.entry: page must be a string")
    local after = spec.after
    if after == nil then after = "settings" end
    assert(type(after) == "string", "R.ui.menus.entry: after must be a string")
    local ok, why = usable("ui_menus_set_entry")
    if not ok then return nil, why end
    local set, swhy = I.ui_menus_set_entry(spec.id, spec.title, spec.page, after)
    if not set then return nil, swhy end
    _entries[spec.id] = true
    return { kind = "entry", id = spec.id }
end

--- Open `page_id` from the current leaf; ctx (JSON-encodable) reaches categories()
--- and on_back(). true, or nil + why.
function M.open(page_id, ctx)
    assert(type(page_id) == "string", "R.ui.menus.open: page_id must be a string")
    local ok, why = usable("ui_menus_open")
    if not ok then return nil, why end
    local json
    if ctx ~= nil then
        local eok, e = pcall(encode, ctx)
        if not eok then return nil, "ctx is not JSON-encodable: " .. tostring(e) end
        json = e
    end
    return I.ui_menus_open(page_id, json)
end

--- Pop one level, like the Back button. true, or nil + why.
function M.back()
    local ok, why = usable("ui_menus_back")
    if not ok then return nil, why end
    return I.ui_menus_back()
end

--- { page, ctx, depth } of the leaf when it is one of ours, else nil.
function M.current()
    if not usable("ui_menus_current") then return nil end
    local c = I.ui_menus_current()
    if type(c) ~= "table" then return nil end
    local ctx
    if c.ctx_json ~= nil and c.ctx_json ~= "" then
        local ok, v = pcall(decode, c.ctx_json)
        if ok then ctx = v else log("current(): bad ctx json: " .. tostring(v)) end
    end
    return { page = c.page, ctx = ctx, depth = c.depth }
end

--- Remove a page or entry by handle (takes effect for the next open).
function M.off(handle)
    if type(handle) ~= "table" or type(handle.id) ~= "string" then
        return nil, "not a R.ui.menus handle"
    end
    if handle.kind == "page" then
        local ok, why = usable("ui_menus_remove_page")
        if not ok then return nil, why end
        _pages[handle.id] = nil
        I.ui_menus_remove_page(handle.id)
        return true
    elseif handle.kind == "entry" then
        local ok, why = usable("ui_menus_remove_entry")
        if not ok then return nil, why end
        _entries[handle.id] = nil
        I.ui_menus_remove_entry(handle.id)
        return true
    end
    return nil, "not a R.ui.menus handle"
end

-- ── loader -> Lua internal events (game thread, synchronous) ────────────────

local _handles = {}   -- our R.on subscriptions, dropped if the factory runs again

local function install_events()
    for _, h in ipairs(_handles) do R.off(h) end
    _handles = {}
    _handles[#_handles + 1] = R.on("ui:_menus_refresh", function(e)
        local pg = type(e) == "table" and _pages[e.page]
        if pg then push(e.page, e.ctx) end
    end)
    _handles[#_handles + 1] = R.on("ui:_menus_back", function(e)
        local pg = type(e) == "table" and _pages[e.page]
        if not (pg and pg.def.on_back) then return end
        local ok, res = pcall(pg.def.on_back, e.ctx)
        if not ok then
            log("page " .. e.page .. ": on_back failed, allowing Back: " .. tostring(res))
        elseif res == false and I.ui_menus_veto_back then
            I.ui_menus_veto_back()
        end
    end)
end

return function(env)
    if R then for _, h in ipairs(_handles) do R.off(h) end end   -- re-run: drop the old state's
    _handles = {}
    _pages, _entries = {}, {}
    R, I = env.R, env.I
    install_events()
    return M
end
