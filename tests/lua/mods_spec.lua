-- Smoke tests for the shipped example mods, run against the SAME mocked native
-- layer rsmm_spec.lua uses. Each mod's init.lua is loaded for real and then
-- driven by firing the events it subscribes to.
--
-- What this catches, which `rsmm lint` cannot: a mod that references an R.*
-- function that does not exist, subscribes to an event with the wrong name, or
-- throws the first time its handler runs. All three are silent in-game — the
-- handler simply never fires, or the error is swallowed by the dispatcher's
-- pcall — so without this they would only surface as "the mod does nothing".
--
--   lua tests/lua/mods_spec.lua [libdir] [modsdir]

local LIB  = (arg and arg[1]) or "src/loader/lib"
local MODS = (arg and arg[2]) or "mods"
package.path = LIB .. "/?.lua;" .. LIB .. "/../lua/?.lua;" .. package.path

local fails, checks = 0, 0
local function ok(cond, msg)
    checks = checks + 1
    if not cond then
        fails = fails + 1
        io.write("FAIL: ", msg, "\n")
    end
end

-- ---------------------------------------------------------------------------
-- minimal native mock: enough for event routing, config, kv and logging
-- ---------------------------------------------------------------------------
local events, logs, kvblob = {}, {}, nil
local calls = {}          -- engine-mutating calls the mods attempted

local I = {
    self_id      = function() return "spec_mod" end,
    now          = function() return os.clock() end,
    state_read   = function() return kvblob end,
    state_write  = function(s) kvblob = s; return true end,
    resolve      = function() return 0 end,
    module_base  = function() return 0x140000000 end,
    shared_get   = function() return 0 end,
    shared_set   = function() end,
}

local function fire(name, payload)
    payload = payload or {}
    for _, cb in ipairs(events[name] or {}) do
        local good, err = pcall(cb, payload, name)
        if not good then
            fails = fails + 1
            io.write("FAIL: handler for '", name, "' raised: ", tostring(err), "\n")
        end
    end
    for _, cb in ipairs(events["*"] or {}) do pcall(cb, payload, name) end
end

_G.rsmm = {
    _internal = I,
    log       = function(...) logs[#logs + 1] = table.concat({ ... }, " ") end,
    on_event  = function(ev, cb) events[ev] = events[ev] or {}; table.insert(events[ev], cb) end,
    mod_dir   = function() return MODS end,
    hook      = function() return 1 end,
    unhook    = function() end,
    emit      = function(name, payload)
        calls[#calls + 1] = "emit:" .. name
        fire(name, payload or {})
        return true
    end,
}

local R = require "rsmm"

-- Stub the engine-mutating surface. The point is to observe that a mod ASKS
-- for the right thing, not to re-test the SDK's pointer work (rsmm_spec.lua
-- already does that end-to-end against a fake value store).
-- Do NOT stub enable_writes with `return true`. The real one returned nothing
-- for its whole life, and stubbing it generously is what let Bloodlust ship
-- with `local ok = R.stat.enable_writes()` — nil, so the mod disabled itself
-- for the entire session and the spec stayed green. A stub that is kinder than
-- the real API tests the stub.
R.stat.modify = function(name, amount, dur)
    calls[#calls + 1] = ("stat.modify:%s:%s:%s"):format(name, amount, tostring(dur))
    return true
end
R.combat.heal = function(n) calls[#calls + 1] = "heal:" .. tostring(n); return true end
-- A mod that acts on the hero needs BOTH: ready() to gate, hero() to compare
-- an event payload against. Stubbing only ready() sent the real hero() into
-- the un-mocked native layer.
local HERO_PTR = 0x2770aa98
R.entity.hero  = function() return HERO_PTR end
R.entity.ready = function() return R.entity.hero() ~= nil end
R.give.ready = function() return true end
R.give.owned_count = function() return 3 end

-- The loader gives every mod its OWN lua_State, so one mod's subscriptions are
-- invisible to another's. This harness shares a state, and R.on keeps its
-- subscriber list INSIDE rsmm.lua (one native "*" handler feeds the router), so
-- isolation has to be done through R.off. Without it, firing ENEMY_KILLED to
-- test the chronicle also drives bloodlust — the false failure this first hit.
local _R_on, _mod_handles = R.on, {}
R.on = function(...)
    local h = _R_on(...)
    _mod_handles[#_mod_handles + 1] = h
    return h
end

local function load_mod(dir)
    calls = {}
    for _, h in ipairs(_mod_handles) do R.off(h) end
    _mod_handles = {}
    local path = MODS .. "/" .. dir .. "/init.lua"
    local chunk, err = loadfile(path)
    if not chunk then
        fails = fails + 1
        io.write("FAIL: ", dir, " did not load: ", tostring(err), "\n")
        return false
    end
    local good, rerr = pcall(chunk)
    if not good then
        fails = fails + 1
        io.write("FAIL: ", dir, " raised on load: ", tostring(rerr), "\n")
        return false
    end
    return true
end

local function had(prefix)
    for _, c in ipairs(calls) do
        if c:sub(1, #prefix) == prefix then return c end
    end
    return nil
end

-- ---------------------------------------------------------------------------
-- 1. bloodlust: every Nth kill inserts one timed attack-power modifier
-- ---------------------------------------------------------------------------
if load_mod("bloodlust") then
    fire("ready")
    for _ = 1, 2 do fire("gameplay:ENEMY_KILLED") end
    ok(had("stat.modify") == nil, "bloodlust: no stack before the kill threshold")
    fire("gameplay:ENEMY_KILLED")            -- 3rd kill = default threshold
    local c = had("stat.modify")
    ok(c ~= nil, "bloodlust: 3rd kill applies a modifier")
    ok(c and c:find("attack_power", 1, true) ~= nil,
       "bloodlust: modifier targets attack_power")
    -- Store units are displayed/100, and the modifier must be TIMED (a
    -- permanent one would never fade and the frenzy would be free).
    ok(c and c:find(":0.06:", 1, true) ~= nil,
       "bloodlust: 6 displayed units becomes 0.06 store units, got " .. tostring(c))
    ok(c and not c:find(":nil", 1, true), "bloodlust: modifier has a duration")

    -- With no hero captured (the default: loader hero-capture is opt-in), the
    -- mod must go completely quiet rather than asking the engine once every
    -- few kills for the whole run. A playtest logged "[rsmm.stat] no hero
    -- captured yet" on repeat because of exactly this.
    local _hero = R.entity.hero
    R.entity.hero = function() return nil end
    calls = {}
    for _ = 1, 30 do fire("gameplay:ENEMY_KILLED") end
    ok(#calls == 0, "bloodlust: silent when no hero is captured, saw "
       .. table.concat(calls, ", "))
    R.entity.hero = _hero

    -- Taking a hit costs stacks AND the partial streak. NETWORK_DAMAGE fires
    -- for every damaged entity, so a hit on an ENEMY must not touch our count.
    calls = {}
    for _ = 1, 3 do fire("gameplay:ENEMY_KILLED") end   -- back to 1 stack
    ok(had("stat.modify") ~= nil, "bloodlust: re-stacked after the quiet window")
    fire("gameplay:NETWORK_DAMAGE", { target_entity = "0xdeadbeef" })
    calls = {}
    for _ = 1, 3 do fire("gameplay:ENEMY_KILLED") end
    ok(had("stat.modify") ~= nil,
       "bloodlust: damage to someone ELSE does not reset the streak")
    -- Now hit the hero itself (the stub hero pointer).
    fire("gameplay:NETWORK_DAMAGE",
         { target_entity = ("0x%x"):format(R.entity.hero()) })
    calls = {}
    for _ = 1, 2 do fire("gameplay:ENEMY_KILLED") end
    ok(had("stat.modify") == nil,
       "bloodlust: a hit on the hero resets progress toward the next stack")

    -- Cap holds: far more kills must not exceed max_stacks modifiers.
    calls = {}
    for _ = 1, 60 do fire("gameplay:ENEMY_KILLED") end
    local n = 0
    for _, x in ipairs(calls) do if x:sub(1, 11) == "stat.modify" then n = n + 1 end end
    ok(n <= 5, "bloodlust: never exceeds max_stacks (got " .. n .. ")")
end

-- ---------------------------------------------------------------------------
-- 2. second-wind: one rescue per run, and it resets on a new run
-- ---------------------------------------------------------------------------
if load_mod("second-wind") then
    fire("ready")
    fire("run:start")
    fire("gameplay:HERO_DEATH_DOOR")
    ok(had("heal:") ~= nil, "second-wind: first down triggers a heal")
    calls = {}
    fire("gameplay:HERO_DEATH_DOOR")
    ok(had("heal:") == nil, "second-wind: second down in the same run does nothing")
    calls = {}
    fire("run:start")
    fire("gameplay:HERO_DEATH_DOOR")
    ok(had("heal:") ~= nil, "second-wind: a new run restores the rescue")
end

-- ---------------------------------------------------------------------------
-- 3. lucky-chests: asks the ENGINE to duplicate, never invents an item
-- ---------------------------------------------------------------------------
if load_mod("lucky-chests") then
    fire("ready")
    math.randomseed(1)
    for _ = 1, 400 do fire("gameplay:OPEN_CHEST") end
    local c = had("emit:gameplay:DUPLICATE")
    ok(c ~= nil, "lucky-chests: fires a duplicate event over many chests")
    ok(c == nil or c:find("MAGICAL_OBJECT", 1, true) ~= nil,
       "lucky-chests: default rarity maps to the any-object event, got " .. tostring(c))

    -- Pity: a dry streak longer than the threshold must force a drop, so the
    -- mod can never look uninstalled. Verified by making every roll lose.
    local _rand = math.random
    math.random = function() return 100 end        -- always above the chance
    fire("run:start")                              -- clear the streak
    calls = {}
    for _ = 1, 7 do fire("gameplay:OPEN_CHEST") end   -- default pity_after = 6
    local pity = had("emit:gameplay:DUPLICATE")
    ok(pity ~= nil, "lucky-chests: pity forces a drop after the dry streak")
    math.random = _rand
end

-- ---------------------------------------------------------------------------
-- 4. raven-chronicle: counts, persists, and touches nothing
-- ---------------------------------------------------------------------------
if load_mod("raven-chronicle") then
    fire("ready")
    fire("run:start")
    for _ = 1, 7 do fire("gameplay:ENEMY_KILLED") end
    fire("gameplay:BOSS_DEFEATED")
    fire("run:end")
    ok(R.kv.get("total_kills", 0) == 7, "raven-chronicle: counted 7 kills")
    ok(R.kv.get("total_bosses", 0) == 1, "raven-chronicle: counted 1 boss")
    ok(R.kv.get("total_runs", 0) == 1, "raven-chronicle: counted 1 run")
    ok(kvblob ~= nil, "raven-chronicle: persisted its state at run end")
    ok(#calls == 0, "raven-chronicle: made ZERO engine-mutating calls, saw: "
       .. table.concat(calls, ", "))
    ok(#logs > 0, "raven-chronicle: reported something to the log")
    ok(R.kv.get("best_kills", 0) == 7, "raven-chronicle: recorded a personal best")

    -- A weaker run must NOT overwrite the record.
    fire("run:start")
    for _ = 1, 2 do fire("gameplay:ENEMY_KILLED") end
    fire("run:end")
    ok(R.kv.get("best_kills", 0) == 7,
       "raven-chronicle: a worse run leaves the record alone")
    -- A better one must.
    fire("run:start")
    for _ = 1, 11 do fire("gameplay:ENEMY_KILLED") end
    fire("run:end")
    ok(R.kv.get("best_kills", 0) == 11, "raven-chronicle: a better run sets a new record")
end

io.write(("mods_spec: %d passed, %d failed\n"):format(checks - fails, fails))
os.exit(fails == 0 and 0 or 1)
