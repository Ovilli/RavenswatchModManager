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
--
-- add{} fields: id (1-32 letters, digits or _; unique within the mod), label
-- (the row title, 1-32 characters), key (keyboard / mouse key id, default 0 =
-- unbound), pad (gamepad key id, default 0). Key ids: keyboard 1-84, mouse
-- buttons 85-91, wheel up 92 / down 93, gamepad 94 and up. Handles also take
-- methods: zin:on_press(fn), zin:keys().
--
-- Declare keybinds from init.lua, at load. The loader registers them with the
-- game once, on the first input poll after every mod has loaded, and has the
-- game read GameSettings.ini again so saved keys apply; a keybind added after
-- that is refused. Re-adding an id this mod already declared returns the same
-- handle, so a hot reload of init.lua keeps working.
--
-- on_press handlers run on the GAME THREAD, inside the input poll, like
-- R.input.on_wheel: keep them short. `n` is the number of presses since the
-- last delivery (a wheel notch is one press); `ev` also carries `key` / `pad`
-- (the current keys) and `blocked` (the game had input blocked, e.g. during a
-- transition). Presses arrive in menus too: the game's UI still gets the key,
-- so a mod that acts on one should stay out of menus.

local M = {}

local R, I

local EVENT = "input:keybind"
local KEY_MAX = 0xff
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

local function _key(v, field)
    if v == nil then return 0 end
    if math.type(v) ~= "integer" or v < 0 or v > KEY_MAX then
        return nil, field .. " must be a key id from 0 to " .. KEY_MAX
    end
    return v
end

--- Are keybinds live? false + reason when they are not.
function M.available()
    if not (I and I.keybinds_state) then return false, "loader too old (no keybinds)" end
    local armed = I.keybinds_state()
    if armed then return true end
    if I.va_trusted and I.va_trusted() == false then
        return false, "VA globals not trusted on this game build"
    end
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
    local key, why = _key(spec.key, "key")
    if not key then return nil, why end
    local pad
    pad, why = _key(spec.pad, "pad")
    if not pad then return nil, why end

    if _mine[id] then return _mine[id] end
    if not (I and I.keybind_add) then return nil, "loader too old (no keybinds)" end
    local index, err = I.keybind_add(id, label, key, pad)
    if not index then return nil, err end
    local h = setmetatable({ id = id, label = label, index = index,
                             default_key = key, default_pad = pad }, Keybind)
    _mine[id] = h
    _order[#_order + 1] = h
    return h
end

--- Call fn(n, ev) when the keybind's key (keyboard or pad) is pressed.
--- Returns a handle for off(), or nil + reason.
function M.on_press(b, fn)
    local h = _resolve(b)
    if not h then return nil, "not a keybind this mod added" end
    if type(fn) ~= "function" then return nil, "on_press needs a function" end
    local me = _self()
    return R.on(EVENT, function(ev)
        if type(ev) ~= "table" or ev.id ~= h.id then return end
        if me and ev.mod ~= me then return end
        fn(tonumber(ev.presses) or 1, ev)
    end)
end

function M.off(handle) return R.off(handle) end

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
