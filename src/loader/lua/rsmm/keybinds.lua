-- R.input.keybinds — mod key bindings as rows in the game's own Controls menu.
--
-- A keybind is a key the player sets in Settings > Controls, on the Keyboard
-- tab and on the Gamepad tab, next to the game's own actions. The game saves it
-- in GameSettings.ini under "<mod id>::<id>", its duplicate-key rule applies to
-- it (binding a key that something else holds clears the other one), and a
-- rebind, also from the pause menu mid-run, takes effect on the next frame.
--
--   local K = R.input.keybinds
--   local zin = K.add{ id = "ZoomIn", label = "Zoom in", key = 92 }  --> handle | nil, reason
--   K.on_press(zin, function(n, ev) ... end)   --> handle for K.off
--   K.off(handle)
--   K.keys(zin)                                --> keyboard key id, pad key id (0 = unbound)
--   K.list()                                   --> { {id=, label=, key=, pad=}, ... }
--   K.available()                              --> true | false, reason
--   K.on_ready(function(ok, reason) ... end)   --> once: did the keybinds go live?
--
-- add{} fields: id (1-32 letters, digits or _; unique within the mod), label
-- (the row title, 1-32 characters), key (the Keyboard tab's default: keyboard
-- 1-84, mouse buttons 85-91, wheel up 92 / down 93), pad (the Gamepad tab's
-- default: gamepad key ids 94 and up) and menus (true to get presses in menus
-- too; see on_press). key and pad default to 0, unbound. Handles also take
-- methods: zin:on_press(fn), zin:keys().
--
-- Declare keybinds from init.lua, at load. The loader registers them with the
-- game once, on the first input poll after every mod has loaded, and has the
-- game read GameSettings.ini again so saved keys apply; a keybind added after
-- that is refused. Re-adding an id this mod already declared returns the same
-- handle, so a hot reload of init.lua keeps working.
--
-- add() during init.lua QUEUES a declaration. It returns nil + reason when
-- keybinds cannot work here at all (an old loader, an untrusted game build,
-- hooks that already failed), but whether a queued keybind goes live is only
-- settled after every init.lua, when the loader installs its hooks and then
-- registers the keybinds with the game. on_ready(fn) reports that outcome
-- once: fn(true) when they are live, fn(false, reason) when they never will
-- be. A mod with a fallback runs it from both places:
--
--   local zin, why = K.add{ ... }
--   if not zin then fallback(why) else K.on_ready(function(ok, why2)
--       if not ok then fallback(why2) end end) end
--
-- available() is true while that outcome is still pending and nothing rules
-- it out, true once the keybinds are live, and false + reason otherwise.
--
-- on_press handlers run on the GAME THREAD, inside the input poll, like
-- R.input.on_wheel: keep them short. `n` is the number of presses since the
-- last delivery (a wheel notch is one press); `ev` also carries `key` / `pad`
-- (the current keys). A handler gets only presses made in play: presses made
-- while a menu is open or while the game had input blocked (e.g. during a
-- transition) are dropped, since the game's UI gets those keys, and so are
-- presses that had to wait for the Lua lock (the menu check is only true of
-- the frame it runs on). A keybind added with `menus = true` gets every press;
-- its `ev.blocked_presses` and `ev.late_presses` count the blocked and the
-- waiting ones within `n`.

local M = {}

local R, I

local EVENT = "input:keybind"
local READY_EVENT = "input:keybinds_ready"
local KEY_MAX = 0xff
-- Key id ranges by device (0 = unbound for either).
local KEYBOARD_MAX, PAD_MIN = 93, 94
local MAX_ID, MAX_LABEL = 32, 32

local Keybind = {}
Keybind.__index = Keybind

local _mine = {}    -- id -> handle, this mod's keybinds
local _order = {}   -- declaration order, for list()

local function _self()
    return I and I.self_id and I.self_id() or nil
end

local function _resolve(b)
    if type(b) == "string" then return _mine[b] end
    -- A handle is the exact table add() stored, so identity is the whole check.
    if type(b) == "table" and b.id ~= nil and _mine[b.id] == b then return b end
    return nil
end

local function _key(v, lo, hi, what)
    if v == nil or v == 0 then return 0 end
    if math.type(v) ~= "integer" or v < lo or v > hi then
        return nil, what .. " (" .. lo .. "-" .. hi .. "), or 0"
    end
    return v
end

--- Is a game menu open? Read through R.game; false when it cannot tell.
local function _in_menu()
    local G = R and R.game
    if not (G and G.flag) then return false end
    local ok, open = pcall(function()
        return G.flag("is_game_menu_open") == true or G.flag("is_menu_open") == true
    end)
    return ok and open == true
end

--- Do keybinds work here? false + reason when they do not. During init.lua,
--- true when the loader will install them once every mod has loaded.
function M.available()
    if not (I and I.keybinds_state) then return false, "loader too old (no keybinds)" end
    local armed, _, failed, open = I.keybinds_state()
    if failed then
        return false, "registration with the game's settings failed (see the loader log)"
    end
    if armed then return true end
    if I.va_trusted and I.va_trusted() == false then
        return false, "VA globals not trusted on this game build"
    end
    if open then return true end   -- installed after every init.lua
    if I.input_armed and not I.input_armed() then
        return false, "input poll hook not live (see the loader log)"
    end
    return false, "keybind hooks failed to install (see the loader log)"
end

--- Declare a keybind. Returns its handle, or nil + reason.
function M.add(spec)
    if type(spec) ~= "table" then return nil, "add takes a table: { id =, label =, key =, pad = }" end
    local id, label = spec.id, spec.label
    if type(id) ~= "string" or #id == 0 or #id > MAX_ID or id:find("[^%w_]") then
        return nil, "id must be 1-" .. MAX_ID .. " letters, digits or _"
    end
    if type(label) ~= "string" or #label == 0 or #label > MAX_LABEL then
        return nil, "label must be 1-" .. MAX_LABEL .. " characters"
    end
    local key, why = _key(spec.key, 1, KEYBOARD_MAX, "key must be a keyboard or mouse key id")
    if not key then return nil, why end
    local pad
    pad, why = _key(spec.pad, PAD_MIN, KEY_MAX, "pad must be a gamepad key id")
    if not pad then return nil, why end
    if spec.menus ~= nil and type(spec.menus) ~= "boolean" then
        return nil, "menus must be true or false"
    end

    local live
    live, why = M.available()
    if not live then return nil, why end
    if _mine[id] then return _mine[id] end
    if not (I and I.keybind_add) then return nil, "loader too old (no keybinds)" end
    local index, err = I.keybind_add(id, label, key, pad)
    if not index then return nil, err end
    local h = setmetatable({ id = id, label = label, index = index, menus = spec.menus == true,
                             default_key = key, default_pad = pad }, Keybind)
    _mine[id] = h
    _order[#_order + 1] = h
    return h
end

--- Call fn(n, ev) when the keybind's key (keyboard or pad) is pressed, in
--- play (every press for a keybind added with menus = true).
--- Returns a handle for off(), or nil + reason.
function M.on_press(b, fn)
    local h = _resolve(b)
    if not h then return nil, "not a keybind this mod added" end
    if type(fn) ~= "function" then return nil, "on_press needs a function" end
    local me = _self()
    return R.on(EVENT, function(ev)
        if type(ev) ~= "table" or ev.id ~= h.id then return end
        if me and ev.mod ~= me then return end
        local play = math.tointeger(ev.presses) or 0
        local n
        if h.menus then
            n = play + (math.tointeger(ev.blocked_presses) or 0)
                + (math.tointeger(ev.late_presses) or 0)
        else
            -- Only this frame's unblocked presses, and only out of menus. A
            -- loader without blocked_presses marks a blocked batch instead.
            if ev.blocked_presses == nil and ev.blocked == true then return end
            if play <= 0 or _in_menu() then return end
            n = play
        end
        if n > 0 then fn(n, ev) end
    end)
end

function M.off(handle) return R.off(handle) end

-- Has the outcome of this session's keybinds been settled? true, ok, reason
-- when it has; false while it is still pending.
local function _outcome()
    if not (I and I.keybinds_state) then return true, false, "loader too old (no keybinds)" end
    local armed, registered, failed, open = I.keybinds_state()
    if registered and not failed then return true, true end
    local ok, why = M.available()
    if not ok then return true, false, why end
    if open or armed then return false end   -- installing, or registering on the first poll
    return true, false, why or "keybinds unavailable"
end

--- Call fn(ok, reason) once, when this session's keybinds have gone live
--- (ok = true) or when they never will (ok = false + reason). Right away when
--- that is already settled. Returns true, or nil + reason.
function M.on_ready(fn)
    if type(fn) ~= "function" then return nil, "on_ready needs a function" end
    local settled, ok, why = _outcome()
    if settled then
        fn(ok, why)
        return true
    end
    local done, h = false, nil
    h = R.on(READY_EVENT, function(ev)
        if done then return end
        done = true
        if h then R.off(h) end
        local live = type(ev) == "table" and ev.ok == true
        fn(live, (not live) and (type(ev) == "table" and ev.reason or "keybinds unavailable") or nil)
    end)
    return true
end

--- The keybind's current keys: keyboard, pad (0 = unbound). nil + reason for
--- an unknown keybind. Before the game has the keybind, the defaults.
function M.keys(b)
    local h = _resolve(b)
    if not h then return nil, "not a keybind this mod added" end
    if I and I.keybind_keys then
        local kb, pad = I.keybind_keys(h.index)
        if kb then return kb, pad end
    end
    return h.default_key, h.default_pad
end

--- Every keybind this mod declared, in order: { {id, label, key, pad}, ... }.
function M.list()
    local out = {}
    for _, h in ipairs(_order) do
        local kb, pad = M.keys(h)
        out[#out + 1] = { id = h.id, label = h.label, key = kb, pad = pad }
    end
    return out
end

function Keybind:on_press(fn) return M.on_press(self, fn) end
function Keybind:keys() return M.keys(self) end

return function(env)
    R, I = env.R, env.I
    return M
end
