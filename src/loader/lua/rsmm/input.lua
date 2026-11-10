-- R.input — mouse-wheel notches from the game's own input poll.
--
-- WHERE THE WHEEL GOES. The window procedure stores +1 or -1 on the input
-- manager, and the per-frame poll (Input_Poll) turns it into two virtual
-- buttons, "Mouse wheel up" and "Mouse wheel down" (key ids 92 and 93), that
-- read pressed for exactly one frame. By default only UI reads them (menu lists,
-- page next/prev, the hero story book, scroll panels); nothing in a run does.
-- The loader counts a notch on the frame it happens (hook_input.cpp) and posts
-- the "input:wheel" event. Nothing is swallowed: the game's UI still gets every
-- notch, so a mod that acts on the wheel should stay out of menus.
--
--   R.input.available()        --> true | false, reason
--   R.input.on_wheel(fn)       --> handle; fn(steps, ev)
--   R.input.off(handle)
--   R.input.wheel_totals()     --> up, down (since launch)
--   R.input.wheel_bindings()   --> { {action=, key="up"|"down", slot="primary"|"pad"}, ... } | nil, reason
--   R.input.wheel_free()       --> true | false, action | nil, reason
--
-- `steps` is the net number of notches since the last delivery, positive for
-- wheel up. `ev` also carries `up`, `down` (totals) and `blocked` (the game had
-- input blocked when the newest notch arrived, e.g. during a transition).
--
-- Handlers run on the GAME THREAD, inside the input poll. Keep them short: read
-- a value, queue a change, return.
--
-- Totals rather than a drain: every mod has its own Lua state, and a drain
-- would let the first mod to ask take the others' notches. Diff against your
-- own last reading instead.

local M = {}

local R, I, options_obj

local EVENT = "input:wheel"
local KEY_WHEEL_UP, KEY_WHEEL_DOWN = 92, 93
-- Above this a key id is not a key: the layout moved. Keyboard ids run 1-84,
-- mouse 85-93 (wheel 92/93), pad 94 up; the live pad bindings reach 117.
local KEY_MAX = 0xff

-- Key options inside the g_GameOptions object (the registry R.options reads).
-- Each is a 0x30-byte InputKeyGameOption: name ptr +0x10, name length +0x18
-- (high bit set), current key id (u32) +0x28. +0x340 / +0xb20 hold the keyboard
-- and mouse bindings; +0x730 / +0xd00 hold the gamepad bindings (pad key ids,
-- read live 2026-11-09) in the same order, so their names come from the first.
local SLOT, NAME_PTR, NAME_LEN, KEY = 0x30, 0x10, 0x18, 0x28
local ARRAYS = {
    { off = 0x340, n = 21, names = 0x340, prefix = "Menu::",  slot = "primary" },
    { off = 0x730, n = 21, names = 0x340, prefix = "Menu::",  slot = "pad"     },
    { off = 0xb20, n = 10, names = 0xb20, prefix = "Explo::", slot = "primary" },
    { off = 0xd00, n = 10, names = 0xb20, prefix = "Explo::", slot = "pad"     },
}
-- The shipped wheel bindings, which act only in menus.
local SHIPPED = {
    ["Menu::AlternativePageNext"] = "up",
    ["Menu::AlternativePagePrev"] = "down",
}

--- Is the wheel hook live? false + reason when it is not.
function M.available()
    if not (I and I.input_armed) then return false, "loader too old (no wheel hook)" end
    if I.input_armed() then return true end
    if I.va_trusted and I.va_trusted() == false then
        return false, "VA globals not trusted on this game build"
    end
    return false, "input poll hook failed to install (see the loader log)"
end

--- Call fn(steps, ev) for every delivery of wheel notches. Returns a handle.
function M.on_wheel(fn)
    assert(type(fn) == "function", "R.input.on_wheel: fn must be a function")
    return R.on(EVENT, function(ev)
        fn(tonumber(ev and ev.steps) or 0, ev)
    end)
end

function M.off(handle) return R.off(handle) end

--- Notches counted since launch: up, down. nil when the hook is not live.
function M.wheel_totals()
    if not (I and I.input_wheel_totals and I.input_armed and I.input_armed()) then return nil end
    return I.input_wheel_totals()
end

-- obj -> { [names offset] = { [i] = name } }. Names are static strings, so one
-- read per options object is enough.
local _names = {}

local function _name(obj, base, i)
    local per = _names[obj]
    if not per then per = {}; _names = { [obj] = per } end
    local arr = per[base]
    if not arr then arr = {}; per[base] = arr end
    local cached = arr[i]
    if cached ~= nil then return cached end
    local s = obj + base + i * SLOT
    local p = I.read_u64(s + NAME_PTR)
    local len = I.read_u32(s + NAME_LEN)
    if not p or p < 0x10000 or not len then return nil end
    len = len % 0x80000000
    if len == 0 or len > 64 then return nil end
    local name = I.read_cstr(p, len + 1)
    if type(name) ~= "string" or #name < len then return nil end
    name = name:sub(1, len)
    arr[i] = name
    return name
end

--- Every key option currently bound to the wheel:
--- { {action = "Explo::Dash", key = "up"|"down", slot = "primary"|"pad"}, ... }.
--- nil + reason when the options registry cannot be read or its layout moved
--- (a name that does not start with Menu:: / Explo::, or a key id out of range).
--- 62 guarded reads, so it is cheap enough to call on every notch, which also
--- picks up a rebind made from the pause menu mid-run.
function M.wheel_bindings()
    local obj = options_obj and options_obj()
    if not obj then return nil, "options registry not readable" end
    local out = {}
    for _, a in ipairs(ARRAYS) do
        for i = 0, a.n - 1 do
            local name = _name(obj, a.names, i)
            if not name or name:sub(1, #a.prefix) ~= a.prefix then
                return nil, "key options moved"
            end
            local key = I.read_u32(obj + a.off + i * SLOT + KEY)
            if key == nil or key > KEY_MAX then return nil, "key options moved" end
            if key == KEY_WHEEL_UP or key == KEY_WHEEL_DOWN then
                out[#out + 1] = {
                    action = name,
                    key = key == KEY_WHEEL_UP and "up" or "down",
                    slot = a.slot,
                }
            end
        end
    end
    return out
end

--- true when the wheel does nothing in a run: the only bindings on it are the
--- shipped menu page alternates. false + the first other action holding it.
--- nil + reason when the bindings cannot be read.
function M.wheel_free()
    local list, why = M.wheel_bindings()
    if not list then return nil, why end
    for _, b in ipairs(list) do
        if not (b.slot == "primary" and SHIPPED[b.action] == b.key) then
            return false, b.action
        end
    end
    return true
end

return function(env)
    R, I, options_obj = env.R, env.I, env.options_obj
    return M
end
