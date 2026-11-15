-- The Settings > Mods page: one category per installed mod (its Off/On row and
-- one row per config_schema.toml field). A core RSMM feature, not a mod: it runs
-- only in the loader-owned Lua state (I.mods_menu_owner), which exists whether
-- or not any mod is installed. It uses nothing but the public R.ui.menus API
-- plus the I.mods_* model natives; the loader keeps the data and writes the
-- files (hook_settings_menu.cpp). The page id must match kModsPageId there.

local PAGE = "rsmm.mods"
local WRAP = 32          -- the book's header text is narrow
local EDIT_IN_APP = "Edit in the desktop app"

local R, I
local _handles = {}      -- our R.on subscriptions, dropped if the factory runs again

local function log(s) R.log("[mods-menu] " .. s) end

-- Word-wrap to lines of at most `width` chars; a word longer than that is split.
local function wrap(text, width)
    local lines, line = {}, ""
    local function flush()
        if line ~= "" then lines[#lines + 1] = line; line = "" end
    end
    for w in tostring(text):gmatch("%S+") do
        local word = w   -- a for-loop variable is read-only in the loader's Lua 5.5
        while #word > width do
            flush()
            lines[#lines + 1] = word:sub(1, width)
            word = word:sub(width + 1)
        end
        if line == "" then
            line = word
        elseif #line + 1 + #word <= width then
            line = line .. " " .. word
        else
            flush()
            line = word
        end
    end
    flush()
    return table.concat(lines, "\n")
end

local function nonempty(s) return type(s) == "string" and s ~= "" end

local function header_of(m)
    local parts = {}
    if nonempty(m.version) then
        local v = "v" .. m.version
        if nonempty(m.author) then v = v .. " - by " .. m.author end
        parts[#parts + 1] = v
    elseif nonempty(m.author) then
        parts[#parts + 1] = "by " .. m.author
    end
    local state = m.wanted and "Enabled" or "Disabled"
    if (m.wanted and true or false) ~= (m.enabled and true or false) then
        state = state .. " (next launch)"
    end
    parts[#parts + 1] = state
    local h = { title = m.name, subtitle = table.concat(parts, " - ") }
    if nonempty(m.description) then h.text = wrap(m.description, WRAP) end
    return h
end

local function row_of(r)
    if r.readonly then
        return { id = r.id, label = r.label, readonly = true, readonly_text = EDIT_IN_APP }
    end
    local row = { id = r.id, label = r.label, choices = r.choices,
                  value = r.value, default = r.default }
    if r.id == "@enabled" then row.reset = false end   -- Reset leaves the Off/On row alone
    return row
end

local function categories()
    local model = I.mods_model()
    local out = {}
    for _, m in ipairs(model and model.mods or {}) do
        local rows = {}
        for i, r in ipairs(m.rows or {}) do rows[i] = row_of(r) end
        out[#out + 1] = { id = m.id, label = m.name, header = header_of(m), rows = rows }
    end
    return out
end

local function on_change(e)
    if type(e) ~= "table" or e.page ~= PAGE then return end
    local ok, why = I.mods_menu_set(e.category, e.row, e.index)
    if not ok then log("set " .. tostring(e.category) .. "." .. tostring(e.row) .. " failed: " .. tostring(why)) end
end

local function on_reset(e)
    if type(e) ~= "table" or e.page ~= PAGE then return end
    local model = I.mods_model()
    for _, m in ipairs(model and model.mods or {}) do
        if m.id == e.category then
            for _, r in ipairs(m.rows or {}) do
                if r.id ~= "@enabled" and not r.readonly then
                    local ok, why = I.mods_menu_set(m.id, r.id, r.default)
                    if not ok then log("reset " .. m.id .. "." .. r.id .. " failed: " .. tostring(why)) end
                end
            end
            return
        end
    end
end

return function(env)
    if R then for _, h in ipairs(_handles) do R.off(h) end end   -- re-run: drop the old state's
    _handles = {}
    R, I = env.R, env.I
    if not (I.mods_menu_owner and I.mods_menu_owner()) then return end
    local model, why = I.mods_model()
    if not model or #(model.mods or {}) == 0 then
        log("no Mods page: " .. (model and "no mods installed" or tostring(why)))
        return
    end
    local page, pwhy = R.ui.menus.page(PAGE, { title = "Mods", kind = "categories", categories = categories })
    if not page then log("page not registered: " .. tostring(pwhy)) end
    local entry, ewhy = R.ui.menus.entry{ id = PAGE, title = "Mods", page = PAGE }
    if not entry then log("entry not registered: " .. tostring(ewhy)) end
    _handles[#_handles + 1] = R.on("ui:menus_change", on_change)
    _handles[#_handles + 1] = R.on("ui:menus_reset", on_reset)
end
