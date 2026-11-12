-- R.input — mouse-wheel notches, the middle-button drag and mouse-look from the
-- game's own input poll.
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
-- WHERE A MIDDLE DRAG COMES FROM. The same poll writes the middle button's key
-- record (id 89) every frame, and the game's UI update keeps the cursor in a
-- record of its own. While the game reports the button held, the loader adds
-- up how far the cursor moved between two polls and posts "input:drag": one
-- "start", any number of "move", one "end". By default nothing in a run reads
-- the middle button (only the UI does), unless the player binds an action to
-- it; middle_free() reads that. The cursor stops at the window edge, so a drag
-- does too.
--
--   R.input.available()        --> true | false, reason
--   R.input.on_wheel(fn)       --> handle; fn(steps, ev)
--   R.input.off(handle)
--   R.input.wheel_totals()     --> up, down (since launch)
--   R.input.wheel_bindings()   --> { {action=, key="up"|"down", slot="primary"|"pad"}, ... } | nil, reason
--   R.input.wheel_free()       --> true | false, action | nil, reason
--
--   R.input.drag_available()   --> true | false, reason
--   R.input.on_drag(fn)        --> handle; fn(phase, dx, dy, ev), phase "start"|"move"|"end"
--   R.input.drag_state()       --> { held, x, y, w, h, drags, dx, dy } | nil, reason
--   R.input.middle_bindings()  --> { {action=, key="middle", slot="primary"|"pad"}, ... } | nil, reason
--   R.input.middle_free()      --> true | false, action | nil, reason
--
--   R.input.mouse_look_available()  --> true | false, reason
--   R.input.mouse_look(on, opts)    --> true | nil, reason; opts.hide (default false)
--   R.input.mouse_look_state()      --> { requested, active, paused, hidden } | nil, reason
--   R.input.on_mouse_move(fn)       --> handle; fn(dx, dy, ev)
--
-- `steps` is the net number of notches since the last delivery, positive for
-- wheel up. `ev` also carries `up`, `down` (totals) and `blocked` (the game had
-- input blocked when the newest notch arrived, e.g. during a transition).
--
-- A drag's `dx`, `dy` are the pixels moved since the last delivered move (0 on
-- start and end). `ev` also carries `x`, `y` (the game's cursor), `w`, `h` (its
-- client size, to scale by), `blocked` and `button` ("middle"). A handler that
-- subscribes mid-drag sees nothing until the next start.
--
-- MOUSE-LOOK. The game's UI update has a cursor-lock mode nothing turns on:
-- with a lock byte set it reads the cursor, takes dx/dy against a centre point
-- and moves the cursor back to the centre. mouse_look(true) asks the loader to
-- write the game window's centre there and set the byte (on the game thread, in
-- the input poll). on_mouse_move(fn) gets the game's own dx/dy in pixels, once
-- per poll in which either is non-zero (merged only with a same-labelled poll if the Lua lock was busy); `ev`
-- carries x, y, w, h, `locked` (the game's lock was on for that poll) and
-- `blocked`. With opts.hide the OS cursor is hidden while the lock is engaged.
-- The lock PAUSES (released, cursor shown) while the game wants the cursor (the
-- pause menu, talent choice, Sandman shop, magical-object menu, cinematic,
-- loading screen or main menu; CURSOR_FLAGS) or the game window is not the
-- foreground window, and resumes when that ends. Each pause and resume is logged
-- with the flag that caused it. The window check is native and per frame. The
-- menu check is pushed to the loader from two places. Every mouse move (game
-- thread) reads the flags live through R.game.flag, so a menu releases within a
-- frame of the next move. The 500 ms tick runs on a loader thread, which must
-- not call into the scene map, so it reads R.game.cached instead (memory reads
-- of the records the last move found): a menu that opens while the mouse is
-- still releases within 500 ms, but only after one mouse move in the current
-- scene (and again after a scene change, which drops the cache); until then it
-- releases on the next move. While the lock is on, middle drags are suppressed (no
-- start; one in progress ends). The request is a lease: it lapses a few seconds
-- after this Lua state stops refreshing it (reload, unload), leaving the lock
-- off and the cursor shown. It is one global state, last caller wins: each
-- request gets an id, this Lua state refreshes only its own, so a mod that was
-- superseded stops renewing the lease.
-- Hero mouse-aim probably reads the window cursor, so a centred cursor aims at
-- the screen centre (inferred, not traced).
--
-- Handlers run on the GAME THREAD, inside the input poll. Keep them short: read
-- a value, queue a change, return.
--
-- Totals rather than a drain: every mod has its own Lua state, and a drain
-- would let the first mod to ask take the others' notches. Diff against your
-- own last reading instead (wheel_totals, drag_state().dx / .dy).

local M = {}

local R, I, options_obj

local EVENT = "input:wheel"
local DRAG_EVENT = "input:drag"
local KEY_WHEEL_UP, KEY_WHEEL_DOWN = 92, 93
local KEY_MOUSE_MIDDLE = 89
local MOVE_EVENT = "input:mouse_move"
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
local WHEEL_KEYS = { [KEY_WHEEL_UP] = "up", [KEY_WHEEL_DOWN] = "down" }
local MIDDLE_KEYS = { [KEY_MOUSE_MIDDLE] = "middle" }

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

--- Is the middle drag live? false + reason when it is not.
function M.drag_available()
    if not (I and I.input_drag_state) then return false, "loader too old (no drag)" end
    if I.input_drag_state() ~= nil then return true end
    local ok, why = M.available()
    if not ok then return false, why end
    return false, "middle-button or cursor record not readable (see the loader log)"
end

--- Call fn(phase, dx, dy, ev) for every drag delivery, in order: "start",
--- then "move" (dx, dy = pixels since the last move), then "end". Returns a handle.
function M.on_drag(fn)
    assert(type(fn) == "function", "R.input.on_drag: fn must be a function")
    return R.on(DRAG_EVENT, function(ev)
        ev = ev or {}
        fn(ev.phase, tonumber(ev.dx) or 0, tonumber(ev.dy) or 0, ev)
    end)
end

--- The drag right now: { held, x, y, w, h, drags, dx, dy }. x, y, w, h are the
--- game's cursor and client size; drags counts starts since launch; dx, dy are
--- the total movement while held since launch. nil + reason when not live.
function M.drag_state()
    if not (I and I.input_drag_state) then return nil, "loader too old (no drag)" end
    local held, x, y, w, h, drags, dx, dy = I.input_drag_state()
    if held == nil then
        local _, why = M.drag_available()
        return nil, why
    end
    return { held = held, x = x, y = y, w = w, h = h, drags = drags, dx = dx, dy = dy }
end

--- Is mouse-look live? true | false, reason.
function M.mouse_look_available()
    if not (I and I.input_look_state and I.input_look_set) then
        return false, "loader too old (no mouse-look)"
    end
    if I.input_look_state() ~= nil then return true end
    local ok, why = M.available()
    if not ok then return false, why end
    return false, "cursor lock byte, centre or cursor record not accessible (see the loader log)"
end

--- Call fn(dx, dy, ev) with the game's mouse movement (pixels since the last
--- delivery). ev: x, y, w, h, locked, blocked. Returns a handle.
function M.on_mouse_move(fn)
    assert(type(fn) == "function", "R.input.on_mouse_move: fn must be a function")
    return R.on(MOVE_EVENT, function(ev)
        ev = ev or {}
        fn(tonumber(ev.dx) or 0, tonumber(ev.dy) or 0, ev)
    end)
end

local _look_on, _look_driver, _look_id

-- Every game state that wants the cursor. The pause menu sets the first two;
-- the talent choice, the Sandman shop, the magical-object menu, cinematics,
-- loading screens and the main menu each have their own flag. is_book_open is
-- left out: it reads true in ordinary play, so it would hold the lock off.
local CURSOR_FLAGS = {
    "is_game_menu_open", "is_menu_open", "is_skill_menu_open", "is_in_sandman_shop",
    "is_mos_menu_open", "is_in_cinematic", "is_in_loading_screen",
    "is_in_main_menu", "is_in_pause",
}

-- The first flag that wants the cursor, or nil. `live` reads through the engine
-- (R.game.flag -> SceneContextValue_Find) and is only for the game thread; the
-- loader's "tick" thread must not touch the scene map, so everything else reads
-- R.game.cached, which is page-guarded memory reads of the record the last
-- game-thread read found (nil until one has run in this scene context).
local function _menu_open(live)
    local G = R and R.game
    if not G then return nil end
    for _, name in ipairs(CURSOR_FLAGS) do
        if live then
            if G.flag then
                local ok, v = pcall(G.flag, name)
                if ok and v == true then return name end
            end
        elseif G.cached then
            local ok, v = pcall(G.cached, name)
            if ok and type(v) == "number" and v ~= 0 then return name end
        end
    end
    return nil
end

local _paused_by

-- Tells the loader whether a menu is open and keeps the lease alive. Only the
-- game-thread caller (the mouse-move event) passes live = true.
local function _drive(live)
    if not (_look_on and I and I.input_look_refresh) then return end
    local why = _menu_open(live == true)
    if why ~= _paused_by then
        R.log("[input] mouse-look " .. (why and ("paused: " .. why) or "resumed"))
        _paused_by = why
    end
    I.input_look_refresh(why ~= nil, _look_id)
end

--- Request mouse-look on or off. opts.hide (default false) hides the OS cursor
--- while the lock is engaged. true | nil, reason.
function M.mouse_look(on, opts)
    if type(on) ~= "boolean" then return nil, "mouse_look(on, opts): on must be a boolean" end
    if opts ~= nil and type(opts) ~= "table" then return nil, "opts must be a table" end
    local hide = opts and opts.hide == true or false
    local ok, why = M.mouse_look_available()
    if not ok then return nil, why end
    local id = I.input_look_set(on, hide)
    if not id then return nil, "mouse-look not armed" end
    -- The request id binds every refresh to this request: once another mod
    -- asks, ours stop renewing the lease. (An older loader returns true.)
    _look_id = math.type(id) == "integer" and id or nil
    _look_on = on
    if on then
        _drive(false)
        if not _look_driver then
            _look_driver = {
                R.on("tick", function() _drive(false) end),
                R.on(MOVE_EVENT, function() _drive(true) end),
            }
        end
    end
    return true
end

--- { requested, active, paused, hidden } | nil, reason.
function M.mouse_look_state()
    if not (I and I.input_look_state) then return nil, "loader too old (no mouse-look)" end
    local requested, active, paused, hidden = I.input_look_state()
    if requested == nil then
        local _, why = M.mouse_look_available()
        return nil, why
    end
    return { requested = requested, active = active, paused = paused, hidden = hidden }
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

-- Every key option whose current key is in `keys` ({[id] = label}):
-- { {action =, key = label, slot =}, ... }, or nil + reason.
local function _bindings(keys)
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
            local label = keys[key]
            if label then
                out[#out + 1] = { action = name, key = label, slot = a.slot }
            end
        end
    end
    return out
end

--- Every key option currently bound to the wheel:
--- { {action = "Explo::Dash", key = "up"|"down", slot = "primary"|"pad"}, ... }.
--- nil + reason when the options registry cannot be read or its layout moved
--- (a name that does not start with Menu:: / Explo::, or a key id out of range).
--- 62 guarded reads, so it is cheap enough to call on every notch, which also
--- picks up a rebind made from the pause menu mid-run.
function M.wheel_bindings()
    return _bindings(WHEEL_KEYS)
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

--- Every key option currently bound to the middle mouse button (key id 89):
--- { {action =, key = "middle", slot =}, ... }. Same reads and failures as
--- wheel_bindings(). Mod keybinds (R.input.keybinds) are not in these slots.
function M.middle_bindings()
    return _bindings(MIDDLE_KEYS)
end

--- true when no game action is bound to the middle button (nothing ships bound
--- to it). false + the first action holding it. nil + reason when unreadable.
function M.middle_free()
    local list, why = M.middle_bindings()
    if not list then return nil, why end
    if list[1] then return false, list[1].action end
    return true
end

return function(env)
    R, I, options_obj = env.R, env.I, env.options_obj
    return M
end
