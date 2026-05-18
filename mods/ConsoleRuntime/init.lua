-- File-watched in-game console for Ravenswatch.
--
-- Mechanism: every loader "tick" (~500 ms) we read <game>/mods/_console.txt,
-- dispatch any /commands found, and append their results to
-- <game>/mods/_console_out.txt. The input file is truncated after each
-- batch so the same command does not re-fire.
--
-- Input via `./rsmm cmd '/list_items'` (the host CLI writes to
-- _console.txt). Output read via `./rsmm cmd --tail` or `./rsmm log`.
--
-- Extending: other mods can register commands by setting
--     _G.rsmm_console = _G.rsmm_console or {}
--     _G.rsmm_console.register("mycmd", function(args) ... end)
-- before "ready" or in their own init.lua. The console runtime exposes
-- the registry as a process-global so cross-state registration works.
--
-- Caveats:
--   - No real keyboard hook yet. Real overlay (D3D11/ImGui) is gated
--     on MinHook restoration (see docs/ROADMAP.md).
--   - Commands needing game-fn calls (/spawn_item, /heal, ...) carry
--     placeholders until the relevant function addresses are RE'd.
--     They report `not-yet-resolved` when called rather than crashing.

local CMD_PATH = rsmm.game_dir() .. "/mods/_console.txt"
local OUT_PATH = rsmm.game_dir() .. "/mods/_console_out.txt"

-- Read this mod's own manifest.toml and look for `dev_mode = true`.
-- Off by default — /eval (arbitrary-Lua escape hatch) is gated on it.
local function read_dev_mode()
    local mf = rsmm.game_dir() .. "/mods/ConsoleRuntime/manifest.toml"
    local f = io.open(mf, "r")
    if not f then return false end
    local txt = f:read("*a") or ""
    f:close()
    -- Simple `dev_mode = true` (or `true,` / surrounded by spaces).
    return txt:find("dev_mode%s*=%s*true") ~= nil
end
local DEV_MODE = read_dev_mode()

-- Append-only output writer. We never overwrite, so external tailers
-- see every emit.
local function emit(line)
    local f = io.open(OUT_PATH, "a")
    if not f then return end
    f:write(os.date("[%H:%M:%S] ") .. line .. "\n")
    f:close()
end

local function emit_block(lines)
    local f = io.open(OUT_PATH, "a")
    if not f then return end
    local stamp = os.date("[%H:%M:%S] ")
    for _, ln in ipairs(lines) do
        f:write(stamp .. ln .. "\n")
    end
    f:close()
end

-- Read + truncate the command file atomically-enough. Two races we
-- accept: (a) host CLI writes a partial line at the moment we read
-- (rare; CLI buffers a full line before flush), and (b) two ticks
-- racing across mods — only one of them is THIS state.
local function drain_cmd_file()
    local f = io.open(CMD_PATH, "r")
    if not f then return {} end
    local body = f:read("*a") or ""
    f:close()
    if body == "" then return {} end
    -- truncate
    local w = io.open(CMD_PATH, "w"); if w then w:close() end
    local lines = {}
    for raw in body:gmatch("[^\r\n]+") do
        local trimmed = raw:match("^%s*(.-)%s*$")
        if trimmed ~= "" then table.insert(lines, trimmed) end
    end
    return lines
end

-- ----- player + entity helpers (best-effort) -----------------------------

local function link_to_runtime(va)
    return rsmm.module_base() + (va - 0x140000000)
end

-- Resolve once, cache. Returns address or nil.
local resolved_cache = {}
local function resolve(name)
    local v = resolved_cache[name]
    if v ~= nil then return v end
    v = rsmm.resolve(name) or false
    resolved_cache[name] = v
    return v or nil
end

-- ----- command registry --------------------------------------------------

_G.rsmm_console = _G.rsmm_console or {}
local cmds = _G.rsmm_console
cmds._registry = cmds._registry or {}
cmds._aliases  = cmds._aliases  or {}

function cmds.register(name, fn, help, opts)
    -- opts.experimental = true marks a stub gated on game-fn RE.
    -- Hidden from /help unless _G.rsmm_console.show_experimental == true.
    local o = opts or {}
    cmds._registry[name] = {fn = fn, help = help or "",
                            experimental = o.experimental == true}
end
function cmds.alias(short, full)
    cmds._aliases[short] = full
end
cmds.show_experimental = cmds.show_experimental or false

-- ----- built-in commands -------------------------------------------------

local function split_args(s)
    local out = {}
    for tok in s:gmatch("%S+") do table.insert(out, tok) end
    return out
end

cmds.register("help", function(args)
    local lines = {}
    local core_keys, exp_keys = {}, {}
    for k, v in pairs(cmds._registry) do
        if v.experimental then table.insert(exp_keys, k)
        else table.insert(core_keys, k) end
    end
    table.sort(core_keys); table.sort(exp_keys)

    table.insert(lines, "commands:")
    for _, k in ipairs(core_keys) do
        local h = cmds._registry[k].help
        table.insert(lines, ("  /%s%s%s"):format(k,
                                                 h ~= "" and " — " or "", h))
    end
    if cmds.show_experimental and #exp_keys > 0 then
        table.insert(lines, "")
        table.insert(lines, "experimental (need RE work; may print not-yet-resolved):")
        for _, k in ipairs(exp_keys) do
            local h = cmds._registry[k].help
            table.insert(lines, ("  /%s%s%s"):format(k,
                                                     h ~= "" and " — " or "", h))
        end
    elseif #exp_keys > 0 then
        table.insert(lines, "")
        table.insert(lines, ("(%d experimental commands hidden — /show_experimental to reveal)")
                            :format(#exp_keys))
    end
    if next(cmds._aliases) then
        table.insert(lines, "")
        table.insert(lines, "aliases:")
        for short, full in pairs(cmds._aliases) do
            table.insert(lines, ("  /%s -> /%s"):format(short, full))
        end
    end
    emit_block(lines)
end, "list every registered command")

cmds.register("show_experimental", function(args)
    local state = (args[1] or "toggle"):lower()
    if state == "on"  then cmds.show_experimental = true
    elseif state == "off" then cmds.show_experimental = false
    else cmds.show_experimental = not cmds.show_experimental end
    emit("experimental commands: " .. (cmds.show_experimental and "shown" or "hidden"))
end, "toggle experimental command visibility in /help")

cmds.register("ping", function(args)
    emit("pong")
end, "sanity check that the dispatcher is alive")

if DEV_MODE then
    -- Arbitrary-Lua escape hatch. Off unless `dev_mode = true` in
    -- ConsoleRuntime/manifest.toml — leaving it on by default would
    -- give anything that can write `_console.txt` full code execution
    -- inside the game process. Players should never need this; mod
    -- authors who do, opt in.
    cmds.register("eval", function(args)
        local src = table.concat(args, " ")
        if src == "" then emit("eval: usage: /eval <lua expression>"); return end
        local chunk, err = load("return " .. src, "eval", "t", _ENV)
        if not chunk then
            chunk, err = load(src, "eval", "t", _ENV)
        end
        if not chunk then emit("eval: parse error: " .. err); return end
        local ok, ret = pcall(chunk)
        if not ok then emit("eval: runtime error: " .. tostring(ret)); return end
        emit("eval => " .. tostring(ret))
    end, "run arbitrary Lua: /eval rsmm.module_base() [dev_mode only]")
end

cmds.register("list_items", function(args)
    -- Read magic-item registry that rsmm scanned at build time.
    -- The Lua side doesn't have direct access to data/; we route to
    -- a snapshot file the host CLI writes on demand. If absent,
    -- print a hint.
    local snap = rsmm.game_dir() .. "/mods/_magic_items.json"
    local f = io.open(snap, "r")
    if not f then
        emit("list_items: snapshot not present. "
             .. "Run `./rsmm cmd --refresh-snapshots` once on the host.")
        return
    end
    local body = f:read("*a"); f:close()
    -- naive grep: pull every "id": "..." line, filter by args[1]
    local filter = (args[1] or ""):lower()
    local lines = {}
    for id in body:gmatch('"id":%s*"([^"]+)"') do
        if filter == "" or id:lower():find(filter, 1, true) then
            table.insert(lines, "  " .. id)
        end
    end
    table.insert(lines, 1, ("%d magic item(s)%s:"):format(
        #lines, filter ~= "" and (" matching " .. filter) or ""))
    emit_block(lines)
end, "list magic items, optional /list_items <substring>")

cmds.register("list_heroes", function(args)
    -- Heroes live as EntitySettings/Heroes/<Name>/Hero_<Name>.entity.ot.
    -- Same snapshot approach as list_items, but parses Hero_*.
    local snap = rsmm.game_dir() .. "/mods/_heroes.json"
    local f = io.open(snap, "r")
    if not f then
        emit("list_heroes: snapshot not present. "
             .. "Run `./rsmm cmd --refresh-snapshots` once on the host.")
        return
    end
    local body = f:read("*a"); f:close()
    local lines = {}
    for name in body:gmatch('"([^"]+)"') do
        table.insert(lines, "  " .. name)
    end
    table.insert(lines, 1, ("%d hero(es):"):format(#lines))
    emit_block(lines)
end, "list known hero ids")

cmds.register("setseed", function(args)
    -- Re-uses the SeedPin mechanism: write into the GameOptions struct.
    local n = tonumber(args[1])
    if not n then emit("setseed: usage /setseed <integer>"); return end
    local DAT = link_to_runtime(0x14140dd50)
    local opts = rsmm.read_u64(DAT)
    if opts == 0 then
        emit("setseed: GameOptions not initialized yet; try again in-game")
        return
    end
    local id_forced = rsmm.read_u32(opts + 0x08)
    if id_forced ~= 0x1949b098 then
        emit(("setseed: layout drift (id=0x%x); refusing"):format(id_forced))
        return
    end
    rsmm.write_u32(opts + 0x28, n)
    rsmm.write_u8 (opts + 0x58, 1)
    emit(("setseed: forced seed = %d (enable=1)"):format(n))
end, "force the next run's seed: /setseed 12345")

cmds.register("whereami", function(args)
    emit(("module_base = 0x%x"):format(rsmm.module_base()))
    emit(("in_main_menu = %s"):format(tostring(rsmm.is_in_main_menu())))
    emit(("game_dir = %s"):format(rsmm.game_dir()))
end, "print loader/game state for the running session")

cmds.register("list_mods", function(args)
    local mods = rsmm.list_mods() or {}
    local lines = {("%d mod(s):"):format(#mods)}
    for _, m in ipairs(mods) do
        table.insert(lines, ("  [%s] %s %s by %s"):format(
            m.enabled and "on " or "off", m.id, m.version or "?",
            m.author or "?"))
    end
    emit_block(lines)
end, "list mods the loader sees")

-- ----- stub commands gated on game-function RE ---------------------------
--
-- Each of these stubs tries to resolve a known function and falls
-- back to a `not-yet-resolved` message. As function addresses get
-- RE'd, fill in the corresponding `resolve("FUN_...")` + `rsmm.call`.

local function try_resolve_or_complain(name, where_to_find)
    local va = resolve(name)
    if va then return va end
    emit(("command unavailable on this build: %s not resolved. "
          .. "Find it via %s and update mods/_ConsoleRuntime/init.lua")
        :format(name, where_to_find or "docs/_re/CALLING_GAME_FUNCTIONS.md"))
    return nil
end

cmds.register("spawn_item", function(args)
    local item_id = args[1]
    if not item_id then emit("spawn_item: usage /spawn_item <item_id>"); return end
    local fn = try_resolve_or_complain(
        "RW_SpawnMagicalObjectAtPlayer",
        "MagicalObject spawn fn xref from the wishing-well controller")
    if not fn then return end
    -- placeholder signature: int(const char* id) — to be confirmed
    local ok, ret = pcall(rsmm.call, fn, "ls", item_id)
    if not ok then emit("spawn_item: " .. tostring(ret)); return end
    emit(("spawn_item: %s spawned (ret=%s)"):format(item_id, tostring(ret)))
end, "spawn a magical object at player: /spawn_item Armor_Per_Object",
   {experimental = true})

cmds.register("summon", function(args)
    -- RE-blocked. The enemy spawn path goes through the vftable of
    -- oCEntitySpawnerGo (vftable address known — see decompiled
    -- ctor at FUN_1406edb30, line `*ptr = oCEntitySpawnerGo::vftable`)
    -- but the slot index for Spawn() isn't recoverable from the
    -- text-only decompile dump. Two routes a future contributor can
    -- take:
    --
    --   1. Manual Ghidra session: open Ravenswatch.exe, navigate to
    --      oCEntitySpawnerGo::vftable, identify the Spawn vmethod
    --      slot. Edit ConsoleRuntime/init.lua to call:
    --         rsmm.call(vftable + slot*8, "vpls", spawner_ptr, enemy_id)
    --
    --   2. Function-fingerprint pass: compare vftables of similar
    --      games / open-source engines for a Spawn-like signature.
    --
    -- Until then this stub explains the situation rather than
    -- silently failing.
    emit("summon: blocked on engine-RE work. "
         .. "oCEntitySpawnerGo vftable exists (see FUN_1406edb30 "
         .. "decompile) but the Spawn vmethod slot is undisclosed. "
         .. "See docs/_re/CALLING_GAME_FUNCTIONS.md for the discovery "
         .. "procedure; PRs welcome.")
end, "summon an enemy (blocked: needs vftable slot RE)",
   {experimental = true})

cmds.register("heal", function(args)
    local fn = try_resolve_or_complain(
        "RW_HealPlayerFull",
        "player-hp setter via the hp-refill consumable code path")
    if not fn then return end
    local ok = pcall(rsmm.call, fn, "v")
    emit(ok and "heal: player restored" or "heal: call failed")
end, "fully heal the player",
   {experimental = true})

cmds.register("give_gold", function(args)
    local n = tonumber(args[1])
    if not n then emit("give_gold: usage /give_gold <int>"); return end
    local fn = try_resolve_or_complain(
        "RW_AddCurrency_Gold",
        "currency setter via shop-purchase fn")
    if not fn then return end
    local ok, ret = pcall(rsmm.call, fn, "li", n)
    emit(ok and ("give_gold: +%d"):format(n) or ("give_gold: " .. tostring(ret)))
end, "add gold: /give_gold 500",
   {experimental = true})

cmds.register("give_dream_shards", function(args)
    local n = tonumber(args[1])
    if not n then emit("give_dream_shards: usage /give_dream_shards <int>"); return end
    local fn = try_resolve_or_complain(
        "RW_AddCurrency_DreamShards",
        "currency setter via wishing-well purchase fn")
    if not fn then return end
    local ok, ret = pcall(rsmm.call, fn, "li", n)
    emit(ok and ("give_dream_shards: +%d"):format(n) or ("give_dream_shards: " .. tostring(ret)))
end, "add dream shards: /give_dream_shards 100",
   {experimental = true})

cmds.register("godmode", function(args)
    local state = (args[1] or "toggle"):lower()
    local fn = try_resolve_or_complain(
        "RW_SetPlayerInvulnerable",
        "invuln setter via the cheat-debug path or the invuln-frame state")
    if not fn then return end
    local on = state == "on" or (state == "toggle" and not _G._console_godmode)
    _G._console_godmode = on
    pcall(rsmm.call, fn, "vi", on and 1 or 0)
    emit("godmode: " .. (on and "on" or "off"))
end, "toggle player invulnerability: /godmode [on|off]",
   {experimental = true})

cmds.register("noclip", function(args)
    local fn = try_resolve_or_complain(
        "RW_SetPlayerNoclip",
        "collision-disable fn (per-entity collider setter)")
    if not fn then return end
    local on = not _G._console_noclip
    _G._console_noclip = on
    pcall(rsmm.call, fn, "vi", on and 1 or 0)
    emit("noclip: " .. (on and "on" or "off"))
end, "toggle player collision",
   {experimental = true})

cmds.register("kill_all", function(args)
    local fn = try_resolve_or_complain(
        "RW_KillAllEnemies",
        "iterate active enemy list + call entity-destroy fn")
    if not fn then return end
    pcall(rsmm.call, fn, "v")
    emit("kill_all: dispatched")
end, "kill every enemy in the current room",
   {experimental = true})

cmds.register("teleport", function(args)
    local x = tonumber(args[1]); local y = tonumber(args[2]); local z = tonumber(args[3])
    if not (x and y and z) then
        emit("teleport: usage /teleport <x> <y> <z>")
        return
    end
    local fn = try_resolve_or_complain(
        "RW_SetPlayerPosition",
        "player-position setter")
    if not fn then return end
    pcall(rsmm.call, fn, "vfff", x, y, z)
    emit(("teleport: -> (%s, %s, %s)"):format(x, y, z))
end, "warp player: /teleport 12.5 0 -3.1",
   {experimental = true})

cmds.register("speed", function(args)
    local mult = tonumber(args[1])
    if not mult then emit("speed: usage /speed <multiplier>"); return end
    local fn = try_resolve_or_complain(
        "RW_SetPlayerMoveSpeed",
        "movement-speed stat setter")
    if not fn then return end
    pcall(rsmm.call, fn, "vf", mult)
    emit(("speed: x%s"):format(mult))
end, "scale player movement speed: /speed 2.0",
   {experimental = true})

cmds.register("xp", function(args)
    local n = tonumber(args[1])
    if not n then emit("xp: usage /xp <int>"); return end
    local fn = try_resolve_or_complain(
        "RW_AddXP",
        "xp-gain fn via talent-pickup path")
    if not fn then return end
    pcall(rsmm.call, fn, "li", n)
    emit(("xp: +%d"):format(n))
end, "grant XP: /xp 100",
   {experimental = true})

cmds.register("level_up", function(args)
    local fn = try_resolve_or_complain(
        "RW_LevelUpPlayer",
        "level-up handler called by xp threshold")
    if not fn then return end
    pcall(rsmm.call, fn, "v")
    emit("level_up: ok")
end, "force a level up",
   {experimental = true})

cmds.register("reload", function(args)
    -- Cheap escape hatch: re-execute init.lua by writing the file
    -- (hot-reload watches mtime). Practically just a no-op log line
    -- since this state is about to be torn down by the watcher.
    emit("reload: bumping init.lua mtime to trigger hot-reload")
    local p = rsmm.mod_dir() .. "/init.lua"
    local f = io.open(p, "r"); if f then f:close() end
    -- touch:
    os.execute('touch "' .. p .. '"')
end, "re-run this mod's init.lua")

-- ----- short aliases -----------------------------------------------------

cmds.alias("?",    "help")
cmds.alias("h",    "help")
cmds.alias("ls",   "list_items")
cmds.alias("give", "give_gold")
cmds.alias("ds",   "give_dream_shards")
cmds.alias("tp",   "teleport")
cmds.alias("god",  "godmode")

-- ----- dispatcher --------------------------------------------------------

local function dispatch(line)
    -- Accept `/cmd args` or `cmd args`.
    line = line:gsub("^/", "", 1)
    local cmd, rest = line:match("^(%S+)%s*(.*)$")
    if not cmd then return end
    cmd = cmds._aliases[cmd] or cmd
    local entry = cmds._registry[cmd]
    if not entry then
        emit("unknown command: /" .. cmd .. "  (try /help)")
        return
    end
    local args = split_args(rest)
    local ok, err = pcall(entry.fn, args)
    if not ok then emit(("/%s: error: %s"):format(cmd, tostring(err))) end
end

local function pump()
    local lines = drain_cmd_file()
    for _, line in ipairs(lines) do
        dispatch(line)
    end
end

rsmm.on_event("ready", function()
    -- Wipe stale output on first ready so a session starts clean.
    local f = io.open(OUT_PATH, "w"); if f then f:close() end
    emit("console runtime ready. Send commands via `./rsmm cmd '/help'`.")
end)

rsmm.on_event("tick", pump)
