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

    return M
end
