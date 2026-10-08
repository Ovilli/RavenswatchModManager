-- R.daynight — the chapter TIMER: day/night lengths and when the boss wakes.
--
-- WHERE IT LIVES. ApplicationSettings.ot's `m_oDayNightCycleParams` block is
-- loaded into the engine's DarkTalesAppSettingsSection, and every chapter load
-- copies it into that chapter's day/night component (DayNightCycle_InitCycle,
-- static read 2026-10-08):
--
--   section+0x1a0  u8   start_day      m_bStartDay                     1
--   section+0x1a4  f32  day            m_fDayDuration                  180 s
--   section+0x1a8  f32  night          m_fNightDuration                180 s
--   section+0x1ac  f32  dawn_dusk      m_fDawnAndDuskHalfDuration      5 s
--   section+0x1b0  u32  half_cycles    m_uHalfCycleCountBeforeBossAwakens 6
--   section+0x1b4  f32  boss_warning   m_fBossTimeWarningDuration      60 s
--   section+0x1b8  f32  overtime       m_fOvertimeDuration             180 s
--
-- The engine then applies the run modifiers (Day only / Night only, the
-- half-cycle +/- modifiers) to its COPY and works out the boss time itself:
--
--   boss_time = half_cycles * (day + night) * 0.5 + overtime    (1260 s shipped)
--
-- So writing the SECTION between chapters changes the NEXT chapter's timer,
-- and every derived number (the clock UI, boss warning, modifiers) follows,
-- because the engine computes them from what we wrote. A chapter that is
-- already running keeps the timer it started with.
--
-- These are plain memory writes, never an engine call, so any thread may make
-- them. Nothing persists: the section is rebuilt from the file every launch.
--
-- ⚠ UNPROVEN IN GAME. The section list and offsets are a static read; the
-- section is found by RTTI name and every field is range-checked before a
-- write, so a wrong guess refuses instead of corrupting memory.

local M = {}

local R, I, _va_ok, _ptr_plausible

-- data/symbols.json: AppSettings_SectionList -- { void** data; u32 count }.
local SECTION_LIST_VA = 0x1412f5aa8
local IMG_BASE        = 0x140000000
local SECTION_MAX     = 256
local SECTION_CLASS   = "DarkTalesAppSettingsSection"   -- oe::dt:: in RTTI

--- The fields, in file order. `kind` drives the read/write width and the
--- range a write must fall in (seconds for durations).
M.FIELDS = {
    start_day    = { off = 0x1a0, kind = "bool" },
    day          = { off = 0x1a4, kind = "f32", min = 1,  max = 36000 },
    night        = { off = 0x1a8, kind = "f32", min = 1,  max = 36000 },
    dawn_dusk    = { off = 0x1ac, kind = "f32", min = 0,  max = 600 },
    half_cycles  = { off = 0x1b0, kind = "u32", min = 0,  max = 100 },
    boss_warning = { off = 0x1b4, kind = "f32", min = 0,  max = 36000 },
    overtime     = { off = 0x1b8, kind = "f32", min = 0,  max = 36000 },
}
M.ORDER = { "start_day", "day", "night", "dawn_dusk", "half_cycles",
            "boss_warning", "overtime" }

local _section            -- cached pointer; re-validated on every use
local _defaults           -- first good read: what the game shipped
local _why = "not looked up yet"

--- Why the last call returned nil/false.
function M.why() return _why end

-- Does `p` hold a sane cycle block? Checked on the values, not just the class:
-- a section whose durations read as garbage is not one to write into.
local function _block_ok(p)
    local sd = I.read_u8(p + 0x1a0)
    if sd ~= 0 and sd ~= 1 then return false end
    for _, name in ipairs({ "day", "night" }) do
        local v = I.read_f32(p + M.FIELDS[name].off)
        if type(v) ~= "number" or v ~= v or v <= 0 or v > 1e6 then return false end
    end
    local hc = I.read_u32(p + 0x1b0)
    return type(hc) == "number" and hc <= 10000
end

local function _is_section(p)
    if not _ptr_plausible(p) then return false end
    local cls = R.rtti and R.rtti.name and R.rtti.name(p)
    return type(cls) == "string" and cls:sub(-#SECTION_CLASS) == SECTION_CLASS
end

--- The live settings section, or nil + reason.
function M.section()
    if _section and _is_section(_section) and _block_ok(_section) then
        return _section
    end
    _section = nil
    if not _va_ok("R.daynight") then
        _why = "game build differs from the symbol map (rsmm update-data)"
        return nil, _why
    end
    local base = I.module_base and I.module_base()
    if not base or base == 0 then _why = "module base unknown"; return nil, _why end
    local list = base + (SECTION_LIST_VA - IMG_BASE)
    local data, n = I.read_u64(list), I.read_u32(list + 8)
    if not _ptr_plausible(data) or type(n) ~= "number" or n == 0 or n > SECTION_MAX then
        _why = ("settings section list unreadable (data=%s count=%s)")
               :format(tostring(data), tostring(n))
        return nil, _why
    end
    for i = 0, n - 1 do
        local p = I.read_u64(data + i * 8)
        if _is_section(p) then
            if not _block_ok(p) then
                _why = ("found %s but its day/night block reads implausible -- "
                        .. "refusing (offsets moved?)"):format(SECTION_CLASS)
                return nil, _why
            end
            _section = p
            return p
        end
    end
    _why = ("no %s among %d settings section(s)"):format(SECTION_CLASS, n)
    return nil, _why
end

local function _read(p, f)
    if f.kind == "bool" then
        local b = I.read_u8(p + f.off); return b and b ~= 0
    elseif f.kind == "u32" then
        return I.read_u32(p + f.off)
    end
    return I.read_f32(p + f.off)
end

--- The current values as `{ start_day=, day=, night=, ... }`, or nil + reason.
--- The first successful read is also kept as the game's own defaults.
function M.get()
    local p, why = M.section()
    if not p then return nil, why end
    local out = {}
    for _, name in ipairs(M.ORDER) do out[name] = _read(p, M.FIELDS[name]) end
    if not _defaults then
        _defaults = {}
        for k, v in pairs(out) do _defaults[k] = v end
    end
    return out
end

--- The values the game started with this launch (a copy), or nil until the
--- section has been read once.
function M.defaults()
    if not _defaults then M.get() end
    if not _defaults then return nil end
    local t = {}
    for k, v in pairs(_defaults) do t[k] = v end
    return t
end

--- Seconds until the boss wakes for `t` (default: the current values),
--- before run modifiers -- the engine's own formula.
function M.boss_time(t)
    t = t or M.get()
    if not t then return nil end
    return (t.half_cycles or 0) * ((t.day or 0) + (t.night or 0)) * 0.5
           + (t.overtime or 0)
end

--- Set any subset of the fields. Every value is checked BEFORE anything is
--- written, so a bad table changes nothing. Returns true, or false + reason.
--- Takes effect at the next chapter load.
function M.set(t)
    if type(t) ~= "table" then _why = "R.daynight.set expects a table"; return false, _why end
    for name, v in pairs(t) do
        local f = M.FIELDS[name]
        if not f then
            _why = ("unknown field %q (have: %s)"):format(tostring(name),
                    table.concat(M.ORDER, ", "))
            return false, _why
        end
        if f.kind == "bool" then
            if type(v) ~= "boolean" then
                _why = name .. " must be true or false"; return false, _why
            end
        else
            if type(v) ~= "number" or v ~= v or v < f.min or v > f.max then
                _why = ("%s must be a number from %s to %s, got %s")
                       :format(name, f.min, f.max, tostring(v))
                return false, _why
            end
            if f.kind == "u32" and math.type(v) ~= "integer" and v ~= math.floor(v) then
                _why = name .. " must be a whole number"; return false, _why
            end
        end
    end
    local p, why = M.section()
    if not p then return false, why end
    M.get()                                  -- capture the defaults first
    for name, v in pairs(t) do
        local f = M.FIELDS[name]
        if f.kind == "bool" then
            I.write_u8(p + f.off, v and 1 or 0)
        elseif f.kind == "u32" then
            I.write_u32(p + f.off, math.floor(v))
        else
            I.write_f32(p + f.off, v + 0.0)
        end
    end
    _why = nil
    return true
end

--- Put back what the game started with. Returns true when it did.
function M.restore()
    local d = M.defaults()
    if not d then return false, _why end
    return M.set(d)
end

--- One line for a log: "day 180 / night 180 / dawn-dusk 5 / 6 half-cycles /
--- warning 60 / overtime 180 -> boss at 1260 s".
function M.describe(t)
    t = t or M.get()
    if not t then return "unreadable: " .. tostring(_why) end
    return ("day %g / night %g / dawn-dusk %g / %d half-cycles / warning %g / "
            .. "overtime %g / starts %s -> boss at %g s")
           :format(t.day, t.night, t.dawn_dusk, t.half_cycles, t.boss_warning,
                   t.overtime, t.start_day and "day" or "night", M.boss_time(t))
end

return function(env)
    R, I = env.R, env.I
    _va_ok, _ptr_plausible = env._va_ok, env._ptr_plausible
    return M
end
