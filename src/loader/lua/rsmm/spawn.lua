-- R.spawn — put a new entity into the world at runtime.
--
-- WHY THIS EXISTS. Every mod that ADDS something to a run — a summon, a pet, an
-- extra enemy, an event encounter — needs to instantiate an entity from a
-- template. The game has no global `spawn(template, pos)`; it spawns through
-- spawner components, and the routine they end in was mis-read twice (June:
-- "statically unreachable"; July: "template-agnostic"). Both were wrong.
--
-- THE CALL, read off the engine's own spawners (Ghidra, 2026-09-13):
--
--     entity = EntityStore_CreateEntity(spawner, settings, &spawnData, nullptr)
--
--   * `settings` is an oCEntitySettings — the template. It embeds its own
--     oCSpawnablePool at +0x18 whose owner (+0x20) is the settings itself, and
--     EntityPool_AllocNode constructs through that owner's vtable (+0x50 ->
--     FUN_1406f9920 = new oCEntity(settings), which stores the template at
--     entity+0x28). That is where the template reaches the constructor, and why
--     the July note calling this level "template-agnostic" was wrong. A loaded
--     oCEntitySettingsResource embeds its settings at +0x98 (ctor FUN_1406e68d0
--     calls the settings ctor on param_1 + 0x13); every engine caller passes
--     `resource + 0x98`, and EntitySpawner_SpawnOne passes `*(ref + 0x1a8) + 0x98`.
--
--   * `spawner` is the SCENE's oCEntitySpawner, embedded at +0xa0 in the scene's
--     oCEntitySceneContext (ctor FUN_140702450 writes oCEntitySpawner::vftable at
--     param_1[0x14]). FUN_140730860 fetches exactly this, from `*(entity+0x30)`
--     (an entity's scene) through GameScene_FindContextByTester. We walk the
--     same two context arrays that function walks (+0x58/+0x60, +0x68/+0x70) and
--     match by RTTI instead of stack-building a tester, so no build-specific VA
--     is involved anywhere in this module.
--     Its place method (vtable +0x18, FUN_1406f5ef0) links the entity into the
--     spawner, defaults spawnData+0x08 to spawner+0x58 when it is null, then
--     calls entity->vtbl[+0x28](entity, spawnData).
--
--   * `spawnData` is an oCEntitySpawnData, laid out by its one consumer,
--     FUN_1406e41e0 (the entity's spawn method), which reads fields only:
--        +0x08  scene           -> entity+0x30  (0 = take the spawner's)
--        +0x10  position vec3   -> SetPosition  (entity+0x324)
--        +0x1c  rotation quat   -> SetRotation  (x, y, z, w)
--        +0x2c  scale vec3      -> SetScale
--        +0x38  parent entity   -> SetParent    (0 = world space)
--        +0x40  / +0x48         -> entity+0x240 / +0x248
--        +0x50  on-spawned functor {obj, manager, invoker}, copied, all-zero = none
--     The heap allocator FUN_1407343a0 and both stack builders (FUN_140435720,
--     FUN_140452a50) initialise exactly these: identity quaternion, unit scale,
--     everything else zero. Nothing on the path vcalls the spawn data, so it is
--     built in a scratch buffer and forgotten once the call returns.
--
-- PROVEN IN-GAME 2026-09-13 (session 3636): a copy of a camp enemy spawned beside
-- the hero, landed on the scene spawner's list with the enemy controller, and was
-- hit by the player. Still unmeasured: AI behaviour, y placement on uneven
-- ground (the hero's y is used as-is), and co-op. `R.spawn.probe()` walks the
-- whole chain and logs every link without calling the engine — run it first on a
-- new build.
--
-- ⚠ MULTIPLAYER. The engine's own spawner gates on network authority
-- (FUN_140727550) and does extra replication work for networked templates
-- (EntitySpawner_SpawnOne, the settings+0x19f0 branch) that this path does not
-- do. A spawn is therefore refused on a session CLIENT, and on the host it is
-- not known to reach other players. Solo is the case this is built for.
--
--     R.spawn.template_of(entity)      -> settings | nil, why
--     R.spawn.probe(anchor)            -> true | false, why   (read-only, logs)
--     R.spawn.at(template, pos, opts)  -> true | false, why   (queued to main)
--     R.spawn.near(template, opts)     -> same, at the hero (+ opts.offset)
--     R.spawn.copy(entity, opts)       -> same, another of entity's template
--     R.spawn.now(template, pos, opts) -> entity | nil, why   (main thread ONLY)
--     R.spawn.entities()               -> { {entity, template}, ... }  (read-only)
--     R.spawn.enemies()                -> { {template, entity, count, name}, ... }
--     R.spawn.describe(entity)         -> enemy tests + owning spawner (diagnostics)
--     R.spawn.why()                    -> last refusal, or nil
return function(env)
    local R, I = env.R, env.I
    local M = {}

    local ENTITY_TEMPLATE  = 0x28    -- oCSpawnable: settings the entity was built from
    local ENTITY_SCENE     = 0x30
    local ENTITY_POS       = 0x324   -- SetPosition's store (local to any parent)
    local COMPONENT_ENTITY = 0x08    -- every entity component: owning entity
    local SETTINGS_POOL    = 0x18    -- embedded oCSpawnablePool
    local POOL_OWNER       = 0x08    -- pool -> settings
    local RESOURCE_SETTINGS = 0x98   -- oCEntitySettingsResource -> embedded settings
    local SCENE_CTX_ARRAYS = { { 0x58, 0x60 }, { 0x68, 0x70 } }
    local SCENE_CTX_MAX    = 64
    local CTX_SPAWNER      = 0xa0
    local SPAWNER_SCENE    = 0x58    -- what place() defaults spawnData+0x08 to
    local SPAWN_DATA_SIZE  = 0x80    -- FUN_1407343a0 allocates 0x88 = 8 + this

    local _why

    local function refuse(msg)
        _why = msg
        R.log("[rsmm.spawn] " .. msg)
        return nil, msg
    end

    local function is(obj, class)
        return R.ptr.has_vtable(obj) and R.rtti.name(obj) == class
    end

    -- An oCEntity, or a component of one (R.entity.hero() hands out the hero
    -- CONTROLLER component, not the entity).
    local function entity_of(p)
        if type(p) ~= "number" or p == 0 then return nil end
        if is(p, "oCEntity") then return p end
        if not R.ptr.has_vtable(p) then return nil end
        local e = I.read_u64(p + COMPONENT_ENTITY)
        if is(e, "oCEntity") then return e end
        return nil
    end

    -- The template structure EntityPool_AllocNode traverses: a live
    -- oCEntitySettings whose embedded pool names it as owner. A resource is
    -- accepted and unwrapped, because that is what a resolved entity ref holds.
    local function settings_of(t)
        if type(t) ~= "number" or t == 0 then return nil, "no template given" end
        if is(t, "oCEntitySettingsResource") then t = t + RESOURCE_SETTINGS end
        if not is(t, "oCEntitySettings") then
            return nil, string.format("0x%x is not an oCEntitySettings (rtti %s)",
                t, tostring(R.rtti.name(t)))
        end
        local pool = t + SETTINGS_POOL
        if not is(pool, "oCSpawnablePool") or I.read_u64(pool + POOL_OWNER) ~= t then
            return nil, string.format("template 0x%x has no intact spawnable pool", t)
        end
        return t
    end

    local function hero_entity()
        local h = R.entity and R.entity.hero and R.entity.hero() or nil
        return h and entity_of(h) or nil
    end

    -- The scene's own entity spawner, found from any live entity in that scene.
    local function scene_spawner(anchor)
        local e = entity_of(anchor)
        if not e then return nil, "anchor is not a live entity" end
        local scene = I.read_u64(e + ENTITY_SCENE)
        if not R.ptr.plausible(scene) then return nil, "anchor entity has no scene" end
        for _, a in ipairs(SCENE_CTX_ARRAYS) do
            if R.ptr.vector_valid(scene, a[1], a[2], { max = SCENE_CTX_MAX }) then
                local data, n = I.read_u64(scene + a[1]), I.read_u32(scene + a[2])
                -- Re-read after the check, so re-checked: a teardown in between
                -- turns these into nil, and `n - 1` on nil raises.
                if type(n) ~= "number" or n > SCENE_CTX_MAX
                   or not R.ptr.plausible(data) then n = 0 end
                for i = 0, n - 1 do
                    local ctx = I.read_u64(data + i * 8)
                    if is(ctx, "oCEntitySceneContext") then
                        local sp = ctx + CTX_SPAWNER
                        if not is(sp, "oCEntitySpawner") then
                            return nil, "scene context found but its +0xa0 is not an oCEntitySpawner"
                        end
                        if not R.ptr.plausible(I.read_u64(sp + SPAWNER_SCENE)) then
                            return nil, "scene spawner has no scene to hand a new entity"
                        end
                        return sp
                    end
                end
            end
        end
        return nil, "no oCEntitySceneContext in the anchor's scene"
    end

    local function session_client()
        if not (R.game and R.game.flag) then return false end
        local ok, connected = pcall(R.game.flag, "is_connected_to_session")
        if not ok or connected ~= true then return false end
        local ok2, host = pcall(R.game.flag, "is_session_host")
        return not (ok2 and host == true)
    end

    local function vec3(v, dx, dy, dz)
        if type(v) ~= "table" then return nil end
        local x, y, z = v.x or v[1], v.y or v[2], v.z or v[3]
        if type(x) ~= "number" or type(y) ~= "number" or type(z) ~= "number" then return nil end
        return x + (dx or 0), y + (dy or 0), z + (dz or 0)
    end

    --- The template an entity (or entity component) was built from.
    function M.template_of(entity)
        local e = entity_of(entity)
        if not e then return nil, "not a live entity" end
        return settings_of(I.read_u64(e + ENTITY_TEMPLATE))
    end

    --- An entity's position as x, y, z (local to its parent, if it has one).
    function M.position_of(entity)
        local e = entity_of(entity)
        if not e then return nil end
        return I.read_f32(e + ENTITY_POS), I.read_f32(e + ENTITY_POS + 4),
               I.read_f32(e + ENTITY_POS + 8)
    end

    --- Walk the chain a spawn would use and log each link. Calls nothing.
    function M.probe(anchor)
        anchor = anchor or (R.entity and R.entity.hero and R.entity.hero())
        local e = entity_of(anchor)
        R.log(string.format("[rsmm.spawn] probe anchor=0x%x entity=%s", anchor or 0,
            e and string.format("0x%x", e) or "NOT AN ENTITY"))
        if not e then return false, "anchor is not a live entity" end
        local t, twhy = M.template_of(e)
        R.log("[rsmm.spawn]   template " .. (t and string.format("0x%x ok", t) or tostring(twhy)))
        local sp, swhy = scene_spawner(e)
        R.log("[rsmm.spawn]   scene spawner " .. (sp and string.format("0x%x ok", sp) or tostring(swhy)))
        R.log(string.format("[rsmm.spawn]   create symbol %s, session client %s",
            R.engine.resolve("EntityStore_CreateEntity") and "resolved" or "UNRESOLVED",
            tostring(session_client())))
        if not (t and sp) then return false, twhy or swhy end
        return true
    end

    --- Spawn now. Only from the game's main thread (a gameplay event handler or
    --- an R.schedule.*_main callback) — the engine mutates the scene's lists.
    ---
    --- opts: yaw (radians about Y), scale (number or {x,y,z}), parent (entity),
    ---       anchor (an entity in the target scene; default the hero),
    ---       allow_hero (spawn the local hero's own template — off by default).
    function M.now(template, pos, opts)
        opts = opts or {}
        local settings, why = settings_of(template)
        if not settings then return refuse(why) end
        local x, y, z = vec3(pos)
        if not x then return refuse("position must be {x, y, z}") end
        if session_client() then
            return refuse("refused on a session client: spawns are host-authoritative")
        end
        local hero = hero_entity()
        if not opts.allow_hero and hero then
            if I.read_u64(hero + ENTITY_TEMPLATE) == settings then
                return refuse("that is the local hero's template (pass allow_hero = true)")
            end
        end
        local anchor = opts.anchor or hero
        if not anchor then return refuse("no anchor entity: the hero is not captured yet") end
        local spawner, swhy = scene_spawner(anchor)
        if not spawner then return refuse(swhy) end
        local parent = 0
        if opts.parent ~= nil then
            parent = entity_of(opts.parent)
            if not parent then return refuse("parent is not a live entity") end
        end
        if not R.engine.resolve("EntityStore_CreateEntity") then
            return refuse("EntityStore_CreateEntity does not resolve on this build")
        end

        local okm, sd = pcall(I.scratch, SPAWN_DATA_SIZE)
        if not okm or not sd then return refuse("no scratch memory for spawn data") end
        for off = 0, SPAWN_DATA_SIZE - 8, 8 do I.write_u64(sd + off, 0) end
        I.write_f32(sd + 0x10, x); I.write_f32(sd + 0x14, y); I.write_f32(sd + 0x18, z)
        local half = (opts.yaw or 0) * 0.5
        I.write_f32(sd + 0x1c, 0.0); I.write_f32(sd + 0x20, math.sin(half))
        I.write_f32(sd + 0x24, 0.0); I.write_f32(sd + 0x28, math.cos(half))
        local sx, sy, sz = 1.0, 1.0, 1.0
        if type(opts.scale) == "number" then
            sx, sy, sz = opts.scale, opts.scale, opts.scale
        elseif type(opts.scale) == "table" then
            sx, sy, sz = vec3(opts.scale)
            if not sx then return refuse("scale must be a number or {x, y, z}") end
        end
        I.write_f32(sd + 0x2c, sx); I.write_f32(sd + 0x30, sy); I.write_f32(sd + 0x34, sz)
        I.write_u64(sd + 0x38, parent)

        local ok, ent = pcall(R.engine.call_safe, "EntityStore_CreateEntity",
            { { 1, function(p) return is(p, "oCEntitySpawner") end },
              { 2, function(p) return settings_of(p) ~= nil end },
              3 },
            spawner, settings, sd, 0)
        if not ok then return refuse("engine call raised: " .. tostring(ent)) end
        if not is(ent, "oCEntity") then
            return refuse(string.format("the engine returned 0x%x, not an entity", ent or 0))
        end
        _why = nil
        R.log(string.format("[rsmm.spawn] spawned 0x%x from template 0x%x at (%.2f, %.2f, %.2f)",
            ent, settings, x, y, z))
        return ent
    end

    --- Queue a spawn onto the main thread. opts.on_spawned(entity) runs after it.
    function M.at(template, pos, opts)
        opts = opts or {}
        local settings, why = settings_of(template)
        if not settings then _why = why; return false, why end
        if not vec3(pos) then _why = "position must be {x, y, z}"; return false, _why end
        R.schedule.next_main(function()
            local ent = M.now(settings, pos, opts)
            if ent and type(opts.on_spawned) == "function" then opts.on_spawned(ent) end
        end)
        return true
    end

    --- Queue a spawn at the hero's position plus opts.offset ({x, y, z}).
    function M.near(template, opts)
        opts = opts or {}
        local hero = hero_entity()
        if not hero then _why = "the hero is not captured yet"; return false, _why end
        local x, y, z = M.position_of(hero)
        if not x then _why = "the hero's position is unreadable"; return false, _why end
        local dx, dy, dz = 0, 0, 0
        if opts.offset then
            dx, dy, dz = vec3(opts.offset)
            if not dx then _why = "offset must be {x, y, z}"; return false, _why end
        end
        return M.at(template, { x + dx, y + dy, z + dz }, opts)
    end

    --- Queue another entity built from `entity`'s template, at its position
    --- plus opts.offset.
    function M.copy(entity, opts)
        opts = opts or {}
        local t, why = M.template_of(entity)
        if not t then _why = why; return false, why end
        local x, y, z = M.position_of(entity)
        local dx, dy, dz = 0, 0, 0
        if opts.offset then
            dx, dy, dz = vec3(opts.offset)
            if not dx then _why = "offset must be {x, y, z}"; return false, _why end
        end
        return M.at(t, { x + dx, y + dy, z + dz }, opts)
    end

    -- WHERE TEMPLATES COME FROM. Not enemy definitions: the enemy picker
    -- (FUN_1403316b0) resolves def+0x288 into def+0x2b8, hands the pointer to
    -- the spawn entry, then RELEASES AND NULLS def+0x2b8 — a definition never
    -- holds its template (measured in-game 2026-09-13: 0 found). Live entities
    -- do, at entity+0x28, and the scene spawner keeps every entity it placed on
    -- an intrusive list (unlink FUN_140691780): head spawner+0x28, count +0x18,
    -- next entity+0x10, prev entity+0x08 with -1 as the first entry's prev.
    local SPAWNER_COUNT, SPAWNER_HEAD, ENTITY_NEXT = 0x18, 0x28, 0x10
    local LIST_MAX = 8192
    local ENEMY_CTRL_CLASS_ID = 0x1561073c     -- oCDtEntityCpntEnemyController

    --- Every entity the scene spawner has placed: { {entity, template}, ... }.
    --- Read-only; the list is re-validated link by link, so an entity destroyed
    --- mid-walk ends the walk instead of misleading it.
    function M.entities(anchor)
        local out = {}
        local sp = scene_spawner(anchor or hero_entity())
        if not sp then return out end
        local n = I.read_u32(sp + SPAWNER_COUNT)
        if not n or n > LIST_MAX then return out end
        local e, seen = I.read_u64(sp + SPAWNER_HEAD), 0
        while e and e ~= 0 and seen < n and is(e, "oCEntity") do
            seen = seen + 1
            local t = settings_of(I.read_u64(e + ENTITY_TEMPLATE))
            if t then out[#out + 1] = { entity = e, template = t } end
            e = I.read_u64(e + ENTITY_NEXT)
        end
        return out
    end

    -- An oCEntity keeps its components in a class-id hash map (+0x5e8), not the
    -- +0x190 array R.entity.components walks (that one is oCEntitySpawnerGo's).
    -- R.net.component is the page-guarded walk of that map.
    local function is_enemy(e)
        if R.damage and R.damage.is_enemy then
            local ok, v = pcall(R.damage.is_enemy, e)
            if ok and v ~= nil then return v end
        end
        return R.net and R.net.component
               and R.net.component(e, ENEMY_CTRL_CLASS_ID) ~= nil or false
    end

    -- A template carries no name field anyone has read, and its resource path is
    -- not inline at settings+0x70 (tried by rsmm.damage: noise). Offer the first
    -- path-like string the RESOURCE points at. Best effort, for logs only.
    local SETTINGS_RESOURCE = 0x70
    local function name_of(t)
        if not (R.debug and R.debug.strings) then return nil end
        local res = I.read_u64(t + SETTINGS_RESOURCE)
        if not is(res, "oCEntitySettingsResource") then return nil end
        for _, hit in ipairs(R.debug.strings(res, { max_off = 0x98, log = false })) do
            if hit.text:find("[\\/]") then return hit.text end
        end
        return nil
    end
    M.name_of = name_of
    M.is_enemy = is_enemy

    --- Diagnostics for one entity: how each enemy test answers, and which
    --- spawner placed it. The place method (FUN_1406f5ef0) writes the owning
    --- spawner into entity+0x38, so a camp enemy names its camp's own store
    --- here instead of the scene spawner.
    local ENTITY_SPAWNER = 0x38
    function M.describe(entity)
        local e = entity_of(entity)
        if not e then return { entity = entity, live = false } end
        local owner = I.read_u64(e + ENTITY_SPAWNER)
        local by_damage
        if R.damage and R.damage.is_enemy then
            local ok, v = pcall(R.damage.is_enemy, e)
            by_damage = ok and v or nil
        end
        return {
            entity = e, live = true,
            template = settings_of(I.read_u64(e + ENTITY_TEMPLATE)),
            enemy_damage = by_damage,
            enemy_component = R.net and R.net.component
                              and R.net.component(e, ENEMY_CTRL_CLASS_ID) ~= nil or false,
            owner = owner,
            owner_class = R.ptr.has_vtable(owner) and R.rtti.name(owner) or nil,
            scene_spawner = (scene_spawner(e)),
        }
    end

    --- Live enemies in the hero's scene, one row per template:
    --- { {template, entity, count, name}, ... }, most numerous first.
    function M.enemies(anchor)
        local by_t, out = {}, {}
        for _, row in ipairs(M.entities(anchor)) do
            local r = by_t[row.template]
            if r then
                r.count = r.count + 1
            elseif is_enemy(row.entity) then
                r = { template = row.template, entity = row.entity, count = 1 }
                by_t[row.template] = r
                out[#out + 1] = r
            end
        end
        for _, r in ipairs(out) do r.name = name_of(r.template) end
        table.sort(out, function(a, b) return a.count > b.count end)
        return out
    end

    function M.why() return _why end

    -- TEMPLATES BY PATH, for an entity nothing has spawned yet (a mod enemy
    -- before its first camp). Every loaded resource sits in the default
    -- archive's path index, the SwissTable Resource_LookupByPath probes (see
    -- ResourceArchive_Default in data/symbols.json): control bytes +0x38, 0x18
    -- slots +0x40 = {oCString key, ..., resource @+0x10}, mask +0x50, more
    -- archives through +0xb8. The table is READ, never called: the engine's
    -- lookup lowercases its argument in place and takes the archive's lock.
    -- A linear scan with a length filter: once per call, not per frame.
    local ARCHIVE_VA, IMG_BASE = R.engine.va("ResourceArchive_Default"), 0x140000000
    local A_CTRL, A_SLOTS, A_MASK, A_NEXT = 0x38, 0x40, 0x50, 0xb8
    local SLOT, SLOT_LEN, SLOT_RES = 0x18, 0x08, 0x10
    local MASK_MAX, ARCHIVES_MAX = 0x100000, 8

    -- Every full slot of every archive in the chain: fn(key, resource) for
    -- each; stops when fn returns true. Returns archives walked, slots full.
    local function each_resource(fn)
        local base = I.module_base and I.module_base()
        if not base or base == 0 then return nil, "module base unknown" end
        local arch, hops, full = base + (ARCHIVE_VA - IMG_BASE), 0, 0
        while R.ptr.plausible(arch) and hops < ARCHIVES_MAX do
            local ctrl, slots = I.read_u64(arch + A_CTRL), I.read_u64(arch + A_SLOTS)
            local mask = I.read_u64(arch + A_MASK)
            if ctrl and slots and mask and mask > 0 and mask < MASK_MAX
               and R.ptr.plausible(slots) then
                for i = 0, mask do
                    local c = I.read_u8(ctrl + i)
                    if c and c < 0x80 then
                        full = full + 1
                        local sl = slots + i * SLOT
                        if fn(sl, I.read_u32(sl + SLOT_LEN)) then return hops + 1, full end
                    end
                end
            end
            arch, hops = I.read_u64(arch + A_NEXT), hops + 1
        end
        return hops, full
    end

    local function key_of(sl) return I.read_cstr(I.read_u64(sl) or 0) end

    --- The loaded oCEntitySettingsResource for a decoded path
    --- ("Enemies\\Wolves\\Kuma.entity.ot"), or nil and why. Read-only. A key
    --- that carries a root in front ("EntitySettings\\...") matches too.
    function M.template_named(path)
        if type(path) ~= "string" or path == "" then
            _why = "template_named(path): path must be a non-empty string"; return nil, _why
        end
        if not (env._va_ok and env._va_ok("R.spawn.template_named")) then
            _why = "va-gate closed (build != symbol map)"; return nil, _why
        end
        local want = path:gsub("/", "\\"):lower()
        local hit, bad
        local hops, full = each_resource(function(sl, n)
            n = n and (n & 0x7fffffff) or 0
            if n < #want then return false end
            local key = key_of(sl)
            if type(key) ~= "string" then return false end
            key = key:lower()
            if key ~= want and key:sub(-#want - 1) ~= "\\" .. want then return false end
            local res = I.read_u64(sl + SLOT_RES)
            if is(res, "oCEntitySettingsResource") then hit = res; return true end
            bad = res
            return false
        end)
        if hit then return hit end
        if hops == nil then _why = full; return nil, _why end
        _why = bad and string.format("%s is loaded but not an entity (rtti %s)", path,
                                     tostring(R.rtti.name(bad)))
               or string.format("%s is not loaded (%d archive(s), %d resources)", path,
                                hops, full)
        return nil, _why
    end

    --- Diagnostics: up to `max` loaded resource paths containing `substr`
    --- (case-insensitive), plus how many archives and resources were walked.
    function M.loaded_like(substr, max)
        substr, max = tostring(substr or ""):lower(), max or 20
        local out = {}
        local hops, full = each_resource(function(sl)
            local key = key_of(sl)
            if type(key) == "string" and key:lower():find(substr, 1, true) then
                out[#out + 1] = key
            end
            return #out >= max
        end)
        return out, hops, full
    end

    -- LOADING AN ENEMY NO CAMP HAS BUILT YET. A definition's preload closure and
    -- its body are not resident after the level loads; they arrive when a camp
    -- first picks it. Enemy_RuntimeSpawnPicker does exactly two things to the
    -- def it picks (Ghidra 2026-10-29, b9c3642884a8):
    --     Definition_LoadPreloadSet(def + 0x68, NULL)
    --     ResourceRef_Resolve(def + 0x288, classDesc, def + 0x2b8, NULL)
    -- classDesc = *(def + 0x2a8), else EntitySettings_ClassDescDefault. The
    -- picker then takes its own reference and releases def + 0x2b8; this leaves
    -- that one reference in place, so the body stays loaded for the session.
    -- Everything each call dereferences is proven first.
    local DEF_PRELOAD, DEF_REF, DEF_REF_CLASS = 0x68, 0x288, 0x2a8
    local DEF_REF_MODE, DEF_REF_OUT = 0x2b0, 0x2b8      -- ref block +0x28, +0x30
    local PRELOAD_COUNT, PRELOAD_STRIDE, PRELOAD_MAX = 0x200, 0x10, 64
    local PROVIDER_ID, PROVIDERS_MAX = 0x53b64d, 64
    local CLASSDESC_VA = R.engine.va("EntitySettings_ClassDescDefault")

    local function path_is(s, want)
        if type(s) ~= "string" then return false end
        s = s:gsub("/", "\\"):lower()
        return s == want or s:sub(-#want - 1) == "\\" .. want
    end

    -- The live enemy definition whose entity ref names `want` (lowercased).
    local function enemy_def(want)
        if not (R.defs and R.defs.instances) then return nil end
        for _, d in ipairs(R.defs.instances("oCDtEnemyDefinition") or {}) do
            -- ref block: {char* name, u32, char* parentPath, u32, ...}
            if path_is(I.read_cstr(I.read_u64(d + DEF_REF) or 0), want)
               or path_is(I.read_cstr(I.read_u64(d + DEF_REF + 0x10) or 0), want) then
                return d
            end
        end
    end

    -- ResourceRef_Resolve dereferences NULL when no provider matches, so the
    -- descriptor must carry one: array at +0x30, count at +0x38, entry id at
    -- +0x8, provider object (with a vtable) at entry +0x10.
    local function has_provider(cd)
        if not R.ptr.plausible(cd) then return false end
        local arr, n = I.read_u64(cd + 0x30), I.read_u32(cd + 0x38)
        if not n or n == 0 or n > PROVIDERS_MAX or not R.ptr.plausible(arr) then return false end
        for i = 0, n - 1 do
            local e = I.read_u64(arr + i * 8)
            if R.ptr.plausible(e) and I.read_u32(e + 8) == PROVIDER_ID then
                return R.ptr.has_vtable(I.read_u64(e + 0x10))
            end
        end
        return false
    end

    -- {u32 n, ptr cache entry} records, count at set + 0x200; each entry's
    -- archive id is read at +0x20.
    local function preload_set_ok(set)
        local n = I.read_u32(set + PRELOAD_COUNT)
        if not n or n > PRELOAD_MAX then return false end
        for i = 0, n - 1 do
            local e = I.read_u64(set + i * PRELOAD_STRIDE + 8)
            if not R.ptr.plausible(e) or I.read_u64(e + 0x20) == nil then return false end
        end
        return true
    end

    --- MAIN THREAD ONLY. Load the body of the enemy whose definition names the
    --- entity at `path`, the way a camp does on its first pick, and return it
    --- (an oCEntitySettingsResource), or nil and why.
    function M.load_enemy(path)
        if type(path) ~= "string" or path == "" then return refuse("load_enemy(path): no path") end
        if not (env._va_ok and env._va_ok("R.spawn.load_enemy")) then
            return refuse("load_enemy: va-gate closed (build != symbol map)")
        end
        local want = path:gsub("/", "\\"):lower()
        local def = enemy_def(want)
        if not def then
            return refuse(path .. ": no enemy definition for it is loaded "
                          .. "(its tribe is not on this map)")
        end
        local cur = I.read_u64(def + DEF_REF_OUT)
        if is(cur, "oCEntitySettingsResource") then return cur end
        if cur ~= 0 then return refuse(string.format("%s: def+0x2b8 holds 0x%x", path, cur or -1)) end
        if I.read_u8(def + DEF_REF_MODE) ~= 0 then
            return refuse(path .. ": the entity ref is in release mode")
        end
        local cd = I.read_u64(def + DEF_REF_CLASS)
        if not cd or cd == 0 then
            local base = I.module_base and I.module_base()
            if not base or base == 0 then return refuse("load_enemy: module base unknown") end
            cd = base + (CLASSDESC_VA - IMG_BASE)
        end
        -- Validated here rather than through call_safe: both callees return
        -- void, and call_safe's nil cannot tell a refusal from a void return.
        if not preload_set_ok(def + DEF_PRELOAD) then
            return refuse(path .. ": its preload set does not have the shipped layout")
        end
        if not has_provider(cd) then
            return refuse(path .. ": its entity class has no resource provider")
        end
        R.engine.call("Definition_LoadPreloadSet", def + DEF_PRELOAD, 0)
        R.engine.call("ResourceRef_Resolve", def + DEF_REF, cd, def + DEF_REF_OUT, 0)
        local res = I.read_u64(def + DEF_REF_OUT)
        if is(res, "oCEntitySettingsResource") then return res end
        return refuse(string.format("%s: resolved to 0x%x (rtti %s), not an entity yet",
                      path, res or 0, tostring(R.rtti.name(res))))
    end

    --- Queue a spawn of the entity at `path`, at the hero (+ opts.offset). An
    --- enemy no camp has built yet is loaded first, on the main thread, so a
    --- true return means QUEUED: opts.on_spawned(entity) is what says it worked,
    --- and M.why() says why not.
    function M.named(path, opts)
        local res, why = M.template_named(path)
        if res then return M.near(res, opts) end
        if not (env._va_ok and env._va_ok("R.spawn.load_enemy")) then return false, why end
        R.schedule.next_main(function()
            local r = M.load_enemy(path)
            if r then M.near(r, opts) end
        end)
        return true
    end

    return M
end
