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
--                                   value = 2, default = 2 },
--                                 { id = "mode", label = "Mode", choices = { "A", "B" },
--                                   reset = false } } } }   -- Reset leaves this row alone
--         end,
--         on_back = function(ctx) return true end,     -- false vetoes the pop
--     })
--     R.ui.menus.entry{ id = "my", title = "My Mod", page = "my.page" }
--     R.on("ui:menus_change", function(e) ... e.page, e.category, e.row, e.index end)
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

local _pages = {}     -- id -> { def = def, snapshot = last pushed snapshot }

local function log(s) R.log("[R.ui.menus] " .. s) end

-- ── snapshot ────────────────────────────────────────────────────────────────

local function clamp_index(v, n, fallback)
    if type(v) ~= "number" or v ~= v then v = fallback end
    v = math.floor(v)
    if v < 1 then return 1 end
    if v > n then return n end
    return v
end

-- Asserts t[k] is a string; `name` is how the message calls it (default k).
local function req_str(t, k, where, name)
    assert(type(t[k]) == "string", where .. ": " .. (name or k) .. " must be a string")
end

local function norm_row(row, where)
    assert(type(row) == "table", where .. ": row must be a table")
    req_str(row, "id", where, "row.id")
    req_str(row, "label", where, "row.label")
    local out = { id = row.id, label = row.label, readonly = row.readonly == true }
    if out.readonly then
        out.choices = {}
        out.value, out.default = 1, 1
        if row.readonly_text ~= nil then
            req_str(row, "readonly_text", where)
            out.readonly_text = row.readonly_text
        end
        return out
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
    if row.reset ~= nil then
        assert(type(row.reset) == "boolean", where .. ": row.reset must be a boolean")
    end
    out.reset = (row.reset ~= false)
    return out
end

local function norm_category(cat, i)
    local where = "category " .. i
    assert(type(cat) == "table", where .. " must be a table")
    req_str(cat, "id", where)
    req_str(cat, "label", where)
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
    return { id = cat.id, label = cat.label, header = header, rows = rows }
end

-- Evaluate def.categories(ctx) and build the snapshot table. Throws on bad data.
local function build(def, ctx)
    local cats = def.categories(ctx)
    assert(type(cats) == "table", "categories() must return a list")
    local out = {}
    for i, cat in ipairs(cats) do out[i] = norm_category(cat, i) end
    return { title = def.title or "", categories = out }
end

-- Re-evaluate and push. false = categories() threw (last snapshot kept).
local function push(id, ctx)
    local pg = _pages[id]
    local ok, snap = pcall(build, pg.def, ctx)
    if not ok then
        log("page " .. id .. ": categories() failed, keeping last snapshot: " .. tostring(snap))
        return false
    end
    local pushed, why = I.ui_menus_set_page(id, snap)
    if not pushed then return nil, why end
    pg.snapshot = snap
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
        local empty = { title = def.title or "", categories = {} }
        pushed, pwhy = I.ui_menus_set_page(id, empty)
        if pushed then _pages[id].snapshot = empty end
    end
    if not pushed then _pages[id] = nil; return nil, pwhy end
    return { kind = "page", id = id }
end

--- Add a Settings entry (after = "settings") or an entry inside another page's
--- column (after = that page's id) that opens `page`. Returns a handle, or nil + why.
function M.entry(spec)
    assert(type(spec) == "table", "R.ui.menus.entry: spec must be a table")
    assert(type(spec.id) == "string" and spec.id ~= "", "R.ui.menus.entry: id must be a non-empty string")
    req_str(spec, "title", "R.ui.menus.entry")
    req_str(spec, "page", "R.ui.menus.entry")
    local after = spec.after
    if after == nil then after = "settings" end
    assert(type(after) == "string", "R.ui.menus.entry: after must be a string")
    local ok, why = usable("ui_menus_set_entry")
    if not ok then return nil, why end
    local set, swhy = I.ui_menus_set_entry(spec.id, spec.title, spec.page, after)
    if not set then return nil, swhy end
    return { kind = "entry", id = spec.id }
end

--- Open `page_id` from the current leaf; ctx (JSON-encodable) reaches categories()
--- and on_back(). true, or nil + why.
function M.open(page_id, ctx)
    assert(type(page_id) == "string", "R.ui.menus.open: page_id must be a string")
    local ok, why = usable("ui_menus_open")
    if not ok then return nil, why end
    return I.ui_menus_open(page_id, ctx)
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
    return { page = c.page, ctx = c.ctx, depth = c.depth }
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
    _pages = {}
    R, I = env.R, env.I
    install_events()
    return M
end
