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

local fails, checks, skipped = 0, 0, 0
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
_G.__spec_now = 0
local function advance(sec)
    _G.__spec_now = _G.__spec_now + sec
end
local calls = {}          -- engine-mutating calls the mods attempted

local I = {
    self_id      = function() return "spec_mod" end,
    -- Controllable clock. R.schedule.after() measures against this, so a real
    -- clock would mean a 15s timer never fires inside a test run.
    now          = function() return _G.__spec_now end,
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
R.shards = R.shards or {}
R.shards.add = function(n) calls[#calls + 1] = "shards:" .. tostring(n); return true end
R.hp = R.hp or {}
R.hp.heal = function(n) calls[#calls + 1] = "hp.heal:" .. tostring(n); return true end
-- A mod that acts on the hero needs BOTH: ready() to gate, hero() to compare
-- an event payload against. Stubbing only ready() sent the real hero() into
-- the un-mocked native layer.
local HERO_PTR = 0x2770aa98
R.entity.hero  = function() return HERO_PTR end
R.entity.ready = function() return R.entity.hero() ~= nil end
R.entity.capture_enabled = function() return true end
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
    -- ABSENT is not FAILING. `mods/` is gitignored, user-owned content: a
    -- developer may delete or never create any given mod, and a checkout has
    -- none of them at all. A spec in this repo therefore cannot require a
    -- particular mod to be on disk — it can only assert that one which IS
    -- present behaves. Hard-failing here made an ordinary "I deleted a mod"
    -- look like a broken build.
    local probe = io.open(path, "r")
    if not probe then
        skipped = skipped + 1
        io.write("SKIP: ", dir, " is not present in ", MODS, "/\n")
        return false
    end
    probe:close()
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

-- Saga's challenge roll announces the set it drew one line per entry, so the
-- log is the only place a test can see WHICH rules were picked.
local function logged(needle)
    for _, l in ipairs(logs) do if l:find(needle, 1, true) then return l end end
    return nil
end

-- Config is loaded from the mod's own config.toml by the loader, which this
-- harness does not do. Overriding the reader is how a test drives a setting.
local _config_get, _cfg_override = R.config.get, {}
R.config.get = function(k, d)
    local v = _cfg_override[k]
    if v ~= nil then return v end
    return _config_get(k, d)
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
    ok(had("hp.heal:") ~= nil, "second-wind: first down triggers a heal")
    calls = {}
    fire("gameplay:HERO_DEATH_DOOR")
    ok(had("hp.heal:") == nil, "second-wind: second down in the same run does nothing")
    calls = {}
    fire("run:start")
    fire("gameplay:HERO_DEATH_DOOR")
    ok(had("hp.heal:") ~= nil, "second-wind: a new run restores the rescue")
end

-- ---------------------------------------------------------------------------
-- 2b. per-run state must clear even when run:start NEVER fires
--
-- run:start is derived from the analytics firehose. If that bus is off, or the
-- game uses a raw name the SDK does not normalise, it never arrives — and a
-- mod that only resets there carries the previous run's state forever. For
-- Second Wind that is one rescue per SESSION instead of per run.
-- ---------------------------------------------------------------------------
if load_mod("second-wind") then
    fire("ready")
    fire("gameplay:HERO_DEATH_DOOR")
    ok(had("hp.heal:") ~= nil, "second-wind: rescued once")

    -- End the run and start the next one WITHOUT a run:start anywhere.
    fire("run:end")
    calls = {}
    fire("gameplay:HERO_DEATH_DOOR")
    ok(had("hp.heal:") ~= nil,
       "second-wind: run:end alone restores the rescue (no run:start needed)")

    -- And again via the menu boundary only.
    fire("menu:enter")
    calls = {}
    fire("gameplay:HERO_DEATH_DOOR")
    ok(had("hp.heal:") ~= nil, "second-wind: menu:enter alone restores the rescue")
end

-- ---------------------------------------------------------------------------
-- 2c. the 15s nag must fire ONLY when the setting is the problem
--
-- A playtest with RSMM_ENABLE_HERO_CAPTURE correctly ON was still told to go
-- and enable it, because the mod could not tell "capture is off" from "the
-- hero has not spawned yet". Capture legitimately took ~3 minutes there.
-- ---------------------------------------------------------------------------
if load_mod("bloodlust") then
    local _hero, _cap = R.entity.hero, R.entity.capture_enabled
    local function nags()
        local before = #logs
        fire("ready"); fire("run:start")
        advance(20)                                -- past the 15s deadline
        fire("tick")                               -- drives R.schedule.after
        for i = before + 1, #logs do
            if logs[i]:find("capture is OFF", 1, true) then return true end
        end
        return false
    end

    R.entity.hero = function() return nil end       -- not captured...
    R.entity.capture_enabled = function() return true end   -- ...but enabled
    ok(not nags(), "no nag when capture is enabled and the hero is merely late")

    R.entity.capture_enabled = function() return false end  -- actually off
    ok(nags(), "nags when capture is genuinely disabled")

    R.entity.hero, R.entity.capture_enabled = _hero, _cap
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

-- ---------------------------------------------------------------------------
-- 5. hero-unlock: opens progression gates, never the ownership one
-- ---------------------------------------------------------------------------
if load_mod("hero-unlock") then
    local asked = {}
    local _unlock = R.hero.unlock_progression
    R.hero.unlock_progression = function()
        -- Mirror the SDK: resolve each gate symbol, count what it would hook.
        for _, n in ipairs({ "HeroProgressionUnlock_IsUnlocked",
                             "HeroRankLock_IsUnlocked",
                             "HeroStoryUnlock_IsUnlocked",
                             "ChallengeUnlock_IsUnlocked" }) do
            asked[#asked + 1] = n
        end
        return #asked
    end
    fire("ready")
    ok(#asked == 4, "hero-unlock: opens all four progression gates")
    local joined = table.concat(asked, ",")
    ok(not joined:find("AdditionalContent", 1, true),
       "hero-unlock: never touches the ownership gate")
    R.hero.unlock_progression = _unlock
end

-- ---------------------------------------------------------------------------
-- 6. saga: abandoning a run is not losing it, and an ambiguous end never eats
--    a win
-- ---------------------------------------------------------------------------
if load_mod("saga") then
    local function n(k) return R.kv.get(k, 0) end
    -- The mocked lobby is empty and there is no Steam name, so every run here
    -- books as solo with an unknown hero — which is exactly the degraded path
    -- a real solo session takes when the lobby attributes never parse.
    local W = "hero.Unknown.solo.wins"
    local L = "hero.Unknown.solo.losses"
    local A = "hero.Unknown.solo.abandons"
    local w0, l0, a0 = n(W), n(L), n(A)
    fire("ready")

    fire("run:start")
    fire("gameplay:GAME_END_SUCCESS")
    fire("menu:enter")
    ok(n(W) == w0 + 1, "saga: a won run is a win")

    -- Session e304: the chapter-1 boss died, GAME_END_SUCCESS fired two
    -- seconds before GAME_END_NEXT_CHAPTER, and the run carried on. Acting on
    -- the success booked a win and unlocked "Dawn At Last" at the end of
    -- chapter one.
    fire("run:start")
    fire("gameplay:GAME_END_SUCCESS")
    fire("gameplay:GAME_END_NEXT_CHAPTER")
    fire("menu:enter")
    ok(n(W) == w0 + 1, "saga: clearing a chapter is not winning the run")
    ok(n(A) == a0 + 1, "saga: ...it settles as the abandon it was")

    -- The regression this block exists for. `run:end` rides the analytics
    -- firehose and GAME_END_SUCCESS the gameplay bus; nothing orders the two,
    -- and the outcome latch is one-shot. Booking the abandon on the spot filed
    -- a won run as a walk-away and took the win, the flawless and every win
    -- feat with it.
    -- run:end rides the analytics firehose and GAME_END_SUCCESS the gameplay
    -- bus; nothing orders them, and whichever arrived first used to win
    -- outright.
    fire("run:start")
    fire("gameplay:GAME_END_SUCCESS")
    fire("run:end")
    ok(n(W) == w0 + 2, "saga: a win settled by run:end is still a win")

    fire("run:start")
    fire("gameplay:GAME_END_FAILED")
    fire("menu:enter")
    ok(n(L) == l0 + 1, "saga: running out of feathers is a defeat")

    fire("run:start")
    fire("menu:enter")
    ok(n(A) == a0 + 2, "saga: quitting with no claim at all is an abandon")
    ok(n(L) == l0 + 1, "saga: ...and leaves the defeat count where it was")

    ok(#calls == 0, "saga: made ZERO engine-mutating calls, saw: "
       .. table.concat(calls, ", "))

    -- Co-op attribution. R.hero.handle() reads live memory the mock has none
    -- of, so it answers nil here — which is itself the case that matters most:
    -- with no local hero known, NOTHING may be filtered, or solo counts zero.
    local k0 = R.kv.get("total_kills", 0)
    fire("gameplay:ENEMY_KILLED", { dispatcher = "0x2000" })
    ok(R.kv.get("total_kills", 0) == k0 + 1,
       "saga: with no local hero known, attribution fails OPEN")

    local _handle = R.hero.handle
    R.hero.handle = function() return 0x1000 end
    -- An ally is LEARNED from a hero-anchored event at a dispatcher that is
    -- not ours. Nothing is filtered until one has been.
    fire("gameplay:ABILITY_EXIT", { dispatcher = "0x2000" })

    k0 = R.kv.get("total_kills", 0)
    fire("gameplay:ENEMY_KILLED", { dispatcher = "0x2000" })
    ok(R.kv.get("total_kills", 0) == k0, "saga: an ally's kill is not mine")
    fire("gameplay:ENEMY_KILLED", { dispatcher = "0x1000" })
    ok(R.kv.get("total_kills", 0) == k0 + 1, "saga: my own kill still counts")
    -- The world dispatcher belongs to nobody and must not be mistaken for an
    -- ally's: dropping world-anchored events would zero the mod out in solo.
    fire("gameplay:ENEMY_KILLED", { dispatcher = "0x9999" })
    ok(R.kv.get("total_kills", 0) == k0 + 2,
       "saga: an unattributable event still counts")
    R.hero.handle = _handle
end


-- ---------------------------------------------------------------------------
-- 6b. saga challenges: the roll is deterministic, the trackers only fire on
--     evidence, and NOTHING is written to the engine unless asked.
--
-- The roll is the part a test has to pin: it is seeded on purpose so a group
-- can share a weekly, and "same seed, same set" is the whole contract. The
-- trackers are the part most likely to rot — an event renamed in the catalog
-- turns a watched rule into an unwatched one with no symptom at all.
-- ---------------------------------------------------------------------------
local function saga_with(over)
    for k in pairs(_cfg_override) do _cfg_override[k] = nil end
    for k, v in pairs(over) do _cfg_override[k] = v end
    logs = {}
    return load_mod("saga")
end

-- Same seed, same set. Different seed, a different one (over a pool this size
-- a collision would mean the seed is not reaching the draw at all).
if saga_with{ challenge_tier = "hard", challenge_seed = "spec-seed" } then
    fire("gameplay:GAME_START")
    local first = {}
    for _, l in ipairs(logs) do if l:find("[Saga]   ", 1, true) then first[#first + 1] = l end end
    ok(#first > 0, "saga/chal: a HARD set was rolled")
    local banner = logged("[Saga] CHALLENGE HARD")
    ok(banner ~= nil, "saga/chal: the set announces its tier")

    saga_with{ challenge_tier = "hard", challenge_seed = "spec-seed" }
    fire("gameplay:GAME_START")
    local second = {}
    for _, l in ipairs(logs) do if l:find("[Saga]   ", 1, true) then second[#second + 1] = l end end
    ok(#first == #second and table.concat(first, "|") == table.concat(second, "|"),
       "saga/chal: the same seed rolls the same set")

    saga_with{ challenge_tier = "hard", challenge_seed = "spec-other" }
    fire("gameplay:GAME_START")
    local third = {}
    for _, l in ipairs(logs) do if l:find("[Saga]   ", 1, true) then third[#third + 1] = l end end
    ok(table.concat(first, "|") ~= table.concat(third, "|"),
       "saga/chal: a different seed rolls a different set")

    -- A HARD set takes no boons (TIER_TABLE caps them at zero), so no entry may
    -- announce a negative score.
    local boon = nil
    for _, l in ipairs(third) do if l:find("%(%-%d") then boon = l end end
    ok(boon == nil, "saga/chal: HARD draws no boons, saw: " .. tostring(boon))
end

-- The score band is the generator's only hard promise, and the one most easily
-- broken by a data edit: draw probability IS difficulty here, so adding a heavy
-- entry pushes every tight tier over its ceiling. HARD is the tight one — 500
-- points wide with a three-malus floor, and it landed in band 12 times in 30
-- before the trim pass existed.
do
    local BANDS = { flavor = { 150, 300 }, light = { 301, 650 },
                    standard = { 651, 1000 }, hard = { 1001, 1500 },
                    brutal = { 1501, 2200 } }
    local out, bad = 0, nil
    for tier, band in pairs(BANDS) do
        for i = 1, 6 do
            if not saga_with{ challenge_tier = tier, challenge_seed = "band-" .. i } then break end
            fire("gameplay:GAME_START")
            local line = logged("[Saga] CHALLENGE " .. tier:upper())
            local score = line and tonumber(line:match("score (%-?%d+)"))
            if score and (score < band[1] or score > band[2]) then
                out = out + 1; bad = ("%s seed %d scored %d"):format(tier, i, score)
            end
        end
    end
    ok(out == 0, "saga/chal: every rolled set lands in its tier band, worst: " .. tostring(bad))
end

-- The trackers. A rolled set is random, so the test hunts for a seed that
-- contains the rule it wants rather than asserting on one particular draw.
local function seed_containing(name, tier)
    for i = 1, 80 do
        local seed = "spec-hunt-" .. i
        if saga_with{ challenge_tier = tier or "brutal", challenge_seed = seed } then
            fire("gameplay:GAME_START")
            if logged(name) then return seed end
        else
            return nil
        end
    end
    return nil
end

local seed = seed_containing("Fountains Sealed")
if seed then
    ok(logged("[Saga] CHALLENGE BROKEN") == nil, "saga/chal: a fresh set is unbroken")
    fire("gameplay:USE_HEAL_FOUNTAIN")
    ok(logged("CHALLENGE BROKEN \u{2014} Fountains Sealed") ~= nil,
       "saga/chal: drinking from a fountain breaks Fountains Sealed")

    -- ...and it stays broken. A later goal check must not clear it.
    fire("gameplay:GAME_END_FAILED")
    fire("menu:enter")
    ok(logged("[Saga] CHALLENGE BROKEN") ~= nil,
       "saga/chal: the run settles as broken")
    ok(logged("[Saga] CHALLENGE KEPT") == nil,
       "saga/chal: ...and is not also reported as kept")
else
    io.write("SKIP: saga/chal: no seed in 80 tries contained Fountains Sealed\n")
end

-- An untouched set is KEPT, and pays its score. This is the other half of the
-- tracker contract: nothing may fail a rule it has seen no evidence for.
if seed and saga_with{ challenge_tier = "brutal", challenge_seed = seed } then
    fire("gameplay:GAME_START")
    fire("gameplay:GAME_END_FAILED")
    fire("menu:enter")
    ok(logged("[Saga] CHALLENGE KEPT") ~= nil,
       "saga/chal: a set nothing broke is kept")
end

-- Auto-apply is OFF by default, and that is load-bearing: Saga's whole claim is
-- that it touches nothing. With it on, the modifier entries — and only those —
-- reach R.modifier.set.
if saga_with{ challenge_tier = "brutal", challenge_seed = "spec-apply" } then
    fire("gameplay:GAME_START")
    ok(#calls == 0, "saga/chal: no engine write with auto-apply off, saw: "
       .. table.concat(calls, ", "))
end

local _set, _enable, _next = R.modifier.set, R.modifier.enable_writes, R.schedule.next_main
R.modifier.set = function(name, value)
    calls[#calls + 1] = ("modifier.set:%s:%s"):format(name, tostring(value))
    return true
end
R.modifier.enable_writes = function() return true end
-- next_main defers to the game's main pump, which this harness has no tick for.
R.schedule.next_main = function(fn) fn() end
do
    local hit, ran = nil, false
    for i = 1, 80 do
        if not saga_with{ challenge_tier = "brutal", challenge_seed = "spec-apply-" .. i,
                          challenge_apply = true } then break end
        ran = true
        fire("gameplay:GAME_START")
        if had("modifier.set:") then hit = had("modifier.set:"); break end
    end
    -- Saga lives in the untracked mods/ tree, so CI has none: saga_with()
    -- declines on the first try and the check has nothing to measure. Every
    -- other saga block skips on that; this one used to report it as a failure.
    if ran then
        ok(hit ~= nil, "saga/chal: auto-apply writes the modifiers it can, saw: " .. tostring(hit))
    end
end
R.modifier.set, R.modifier.enable_writes, R.schedule.next_main = _set, _enable, _next
for k in pairs(_cfg_override) do _cfg_override[k] = nil end

-- The spend rules. There is no spend event on the bus at all — only
-- GAIN_DREAM_SHARDS — so the mod reads a FALL in the polled balance as a
-- purchase. That inference is the whole mechanism and it has two ways to be
-- wrong, both tested here: a first sample must not read as a spend (the
-- balance starts unsampled, not at zero), and a rise must not either.
local _statget = R.stat.get
local balance = nil
R.stat.get = function(name)
    if name == "dream_shards" then return balance end
    return _statget and _statget(name)
end

-- Drive the 3s poll. It is registered with every_main, which rsmm.lua pumps
-- from the gameplay bus, so a gameplay event plus a clock advance is what a
-- frame looks like to this mod.
local function poll(n)
    for _ = 1, (n or 1) do
        advance(4)
        fire("gameplay:GAME_CHRONO_START", { source = "gameplay" })
    end
end

local sseed = seed_containing("Savings First")
if sseed then
    balance = 400
    poll(2)
    ok(logged("CHALLENGE BROKEN \u{2014} Savings First") == nil,
       "saga/spend: the first sample of a balance is not a spend")
    balance = 900
    poll()
    ok(logged("CHALLENGE BROKEN \u{2014} Savings First") == nil,
       "saga/spend: earning shards is not a spend")
    balance = 700
    poll()
    ok(logged("CHALLENGE BROKEN \u{2014} Savings First") ~= nil,
       "saga/spend: spending below 1000 breaks Savings First")
else
    io.write("SKIP: saga/spend: no seed in 80 tries contained Savings First\n")
end

-- Reaching the target first makes the rule safe to spend against.
if sseed and saga_with{ challenge_tier = "brutal", challenge_seed = sseed } then
    fire("gameplay:GAME_START")
    balance = 1200
    poll(2)
    ok(logged("CHALLENGE DONE \u{2014} Savings First") ~= nil,
       "saga/spend: holding 1000 completes Savings First")
    balance = 100
    poll()
    ok(logged("CHALLENGE BROKEN \u{2014} Savings First") == nil,
       "saga/spend: ...and spending afterwards does not break it")
end

local fseed = seed_containing("Shard Fast")
if fseed then
    balance = 500
    poll(2)
    balance = 300
    poll()
    ok(logged("CHALLENGE BROKEN \u{2014} Shard Fast") ~= nil,
       "saga/spend: spending in chapter 1 breaks Shard Fast")
else
    io.write("SKIP: saga/spend: no seed in 80 tries contained Shard Fast\n")
end

-- Leaving chapter 1 with the balance untouched completes it instead.
if fseed and saga_with{ challenge_tier = "brutal", challenge_seed = fseed } then
    fire("gameplay:GAME_START")
    balance = 500
    poll(2)
    fire("gameplay:GAME_END_NEXT_CHAPTER")
    ok(logged("CHALLENGE DONE \u{2014} Shard Fast") ~= nil,
       "saga/spend: clearing chapter 1 unspent completes Shard Fast")
end

R.stat.get = _statget
balance = nil
for k in pairs(_cfg_override) do _cfg_override[k] = nil end

-- The R.game rules. These read the engine's own values through the global
-- entity-value context, which an older loader does not publish — so the thing
-- most worth pinning is that their ABSENCE is silent. A rule that cannot see
-- its signal must stay open, never fail.
local _game = R.game
local gvals = nil                       -- nil = no context published
R.game = {
    keys = (_game and _game.keys) or {},
    get  = function(n) return gvals and gvals[n] or nil end,
}

local shopseed = seed_containing("One Shop Visit Per Chapter")
if shopseed then
    gvals = nil
    poll(2)
    ok(logged("CHALLENGE BROKEN") == nil,
       "saga/game: with no global context published, nothing is judged")

    -- Two rising edges in one chapter breaks it; staying inside does not.
    gvals = { is_in_sandman_shop = 1 }
    poll()
    gvals = { is_in_sandman_shop = 1 }
    poll()
    ok(logged("CHALLENGE BROKEN \u{2014} One Shop Visit Per Chapter") == nil,
       "saga/game: staying in the shop is still one visit")
    gvals = { is_in_sandman_shop = 0 }
    poll()
    gvals = { is_in_sandman_shop = 1 }
    poll()
    ok(logged("CHALLENGE BROKEN \u{2014} One Shop Visit Per Chapter") ~= nil,
       "saga/game: a second visit in one chapter breaks One Shop Per Chapter")
else
    io.write("SKIP: saga/game: no seed in 80 tries contained One Shop Visit Per Chapter\n")
end

-- Drawn at IMPOSSIBLE: the brutal band did not contain it in 80 seeds.
local rrseed = seed_containing("No Rerolls", "impossible")
if rrseed then
    gvals = { reroll_count = 3 }
    poll(2)
    ok(logged("CHALLENGE BROKEN \u{2014} No Rerolls") == nil,
       "saga/game: the first sample of the reroll counter is a baseline")
    gvals = { reroll_count = 4 }
    poll()
    ok(logged("CHALLENGE BROKEN \u{2014} No Rerolls") ~= nil,
       "saga/game: the counter going up breaks No Rerolls")
else
    io.write("SKIP: saga/game: no seed in 80 tries contained No Rerolls\n")
end

local bcseed = seed_containing("Beat the Clock")
if bcseed then
    gvals = { is_boss_awaken = 0 }
    poll(2)
    ok(logged("CHALLENGE BROKEN \u{2014} Beat the Clock") == nil,
       "saga/game: a sleeping boss does not break Beat the Clock")
    gvals = { is_boss_awaken = 1 }
    poll()
    ok(logged("CHALLENGE BROKEN \u{2014} Beat the Clock") ~= nil,
       "saga/game: the Nightmare waking breaks Beat the Clock")
end

R.game = _game
gvals = nil
for k in pairs(_cfg_override) do _cfg_override[k] = nil end

-- Analytics-bus rules. These arrive under the RAW event name (no "gameplay:"
-- prefix) and carry their fields on `ev`, which is the whole point: the
-- gameplay bus never names the article you bought.
-- IMPOSSIBLE: No Shop conflicts with E02 and did not appear in a brutal draw.
local shopseed2 = seed_containing("No Shop", "impossible")
if shopseed2 then
    ok(logged("CHALLENGE BROKEN \u{2014} No Shop") == nil, "saga/analytics: a fresh set is unbroken")
    fire("sandman_buy", { article_name = "Dreamcatcher", article_price = 120,
                          article_rarity = "Common" })
    ok(logged("CHALLENGE BROKEN \u{2014} No Shop") ~= nil,
       "saga/analytics: buying from the Sandman breaks No Shop")
else
    io.write("SKIP: saga/analytics: no seed in 80 tries contained No Shop\n")
end

-- The probe prints each identity-carrying event ONCE, with its fields.
if saga_with{ challenge_tier = "brutal", challenge_seed = "probe" } then
    fire("gameplay:GAME_START")
    fire("object_selected", { object_name = "Healing_Effect", object_quality = 1 })
    fire("object_selected", { object_name = "Second_One", object_quality = 2 })
    local hits = 0
    for _, l in ipairs(logs) do
        if l:find("PROBE object_selected", 1, true) then hits = hits + 1 end
    end
    ok(hits == 1, "saga/analytics: the payload probe fires exactly once, saw " .. hits)
    ok(logged("object_name=Healing_Effect") ~= nil,
       "saga/analytics: ...and prints the fields the emitter carries")
end
for k in pairs(_cfg_override) do _cfg_override[k] = nil end

-- ---------------------------------------------------------------------------
-- 7. steamroller: pins on the main thread only, and in STORE units
-- ---------------------------------------------------------------------------
if load_mod("steamroller") then
    local stuck = {}
    local _stick, _ready = R.stat.stick, R.entity.ready
    R.stat.stick = function(name, value) stuck[name] = value; return true end
    R.entity.ready = function() return true end

    -- "tick" is the loader's BACKGROUND thread. An engine-mutating write from
    -- there is the documented way to crash the game, so nothing may pin here.
    fire("tick")
    ok(next(stuck) == nil, "steamroller: does not write from the background thread")

    fire("gameplay:ENEMY_KILLED", { source = "gameplay" })
    ok(stuck.attack_power ~= nil, "steamroller: pins once the gameplay bus runs")
    -- Store units are the displayed value / 100. Passing 4000 straight through
    -- asks the engine for 400000 attack power.
    ok(stuck.attack_power == 40,
       "steamroller: converts displayed attack power to store units, got "
       .. tostring(stuck.attack_power))
    ok(stuck.crit_chance == 1.0, "steamroller: crit chance is a fraction, not a percent")

    -- Health writes require a LANDED stat pin. Session 8c4f adopted a wrong
    -- object through the give-handler; the value store refused every stat, but
    -- R.entity.hp() is an unvalidated fixed-offset read that still returned
    -- plausible floats, and Entity_ModifyHealth then faulted on that pointer.
    local healed = false
    R.hp = R.hp or {}
    local _sethp, _frac, _max = R.hp.set, R.hp.frac, R.hp.max
    R.hp.set  = function() healed = true; return true end
    R.hp.frac = function() return 0.1 end   -- "hurt", as the bad read looked
    R.hp.max  = function() return 100 end

    R.stat.stick = function() return false end     -- value store refuses
    stuck = {}
    fire("run:start")                              -- clears the pinned latch
    fire("gameplay:ENEMY_KILLED", { source = "gameplay" })
    ok(not healed, "steamroller: no health write when every stat pin was refused")

    R.stat.stick = function(name, value) stuck[name] = value; return true end
    fire("run:start")
    fire("gameplay:ENEMY_KILLED", { source = "gameplay" })
    ok(healed, "steamroller: tops up real HP (R.hp) once the pins land")

    R.hp.set, R.hp.frac, R.hp.max = _sethp, _frac, _max

    -- STATS MUST NOT REQUIRE A CAPTURED HERO.
    --
    -- R.stat's store hangs off the hero's value CONTEXT, which the loader
    -- publishes straight off the give handler, so a stat can be written from
    -- the first item pickup even when the hero ENTITY is never captured — and
    -- capture is the part that keeps failing. Session ef4f: the give handler
    -- fired 8 times, the context was published, R.stat was ready to write, and
    -- steamroller's pin() returned at an `R.entity.ready()` check without a
    -- single attempt. The mod did nothing for a whole run and logged not one
    -- [rsmm.stat] line. Fixing R.stat was not enough while its caller still
    -- gated on the thing the fix routes around.
    R.entity.ready = function() return false end   -- no hero, ever
    stuck = {}
    fire("run:start")
    fire("gameplay:ENEMY_KILLED", { source = "gameplay" })
    ok(stuck.attack_power ~= nil,
       "steamroller: pins stats with NO captured hero (value-context path)")

    -- ...but health still does: R.hp needs the captured hero to reach its
    -- HitPoint component, and a value context alone has none.
    healed = false
    R.hp.set  = function() healed = true; return true end
    R.hp.frac = function() return 0.1 end
    R.hp.max  = function() return 100 end
    fire("run:start")
    fire("gameplay:ENEMY_KILLED", { source = "gameplay" })
    ok(not healed,
       "steamroller: still refuses the health top-up without a captured hero")
    R.hp.set, R.hp.frac, R.hp.max = _sethp, _frac, _max

    -- A refused pin must NOT latch: the context arrives on the first pickup,
    -- so an early attempt fails and a later one has to succeed. Latching on the
    -- first try would make the mod dead for the rest of the run.
    R.entity.ready = function() return false end
    R.stat.stick = function() return false end
    stuck = {}
    fire("run:start")
    fire("gameplay:ENEMY_KILLED", { source = "gameplay" })
    R.stat.stick = function(name, value) stuck[name] = value; return true end
    fire("gameplay:ENEMY_KILLED", { source = "gameplay" })
    ok(stuck.attack_power ~= nil,
       "steamroller: retries after a refused pin instead of latching")

    R.stat.stick, R.entity.ready = _stick, _ready
end

io.write(("mods_spec: %d passed, %d failed, %d mod(s) skipped (not present)\n")
    :format(checks - fails, fails, skipped))
os.exit(fails == 0 and 0 or 1)
