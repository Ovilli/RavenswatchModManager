-- rsmm.damage — per-player damage attribution (the run's damage meter).
--
-- Split out of rsmm.lua on 2026-08-23. It was ~5000 lines, 45% of the
-- entrypoint, and the most self-contained namespace in it: 86 private helpers
-- that nothing else reads, and only the handful of parent values below.
--
-- CONTRACT: this module returns a FUNCTION, not a table. The plain-table
-- submodules merged by _submodule are standalone; this one needs
-- the parent's private helper table and pointer guards, and it installs its own
-- hooks, so rsmm.lua calls it with an env and it populates R/F in place.
--
-- Everything below the header is verbatim from rsmm.lua, with two deliberate
-- changes, both marked at their site: F is no longer rebound, and the
-- dispatcher offset arrives as a getter.

return function(env)

-- Validate the env before reading it. A key the parent forgets to pass is nil
-- here, and nil is a legal value for most of what this module does with them:
-- MEM_SCAN_MB silently becomes a nil scan budget, LOBBY_REFRESH_SLOT a nil
-- shared slot. Nothing raises and nothing looks wrong, which is precisely the
-- failure mode the split had to be defended against. Raising instead means
-- _submodule_fn logs "failed to install" and R.damage is absent — loud, and
-- caught by the surface checks in rsmm_spec.
for _, key in ipairs({ "I", "R", "F", "_va_ok", "_ptr_plausible",
                       "ENTITY_IMG_BASE", "LOBBY_REFRESH_SLOT", "MEM_SCAN_MB",
                       "LOBBY_HOOK", "dispatcher_entity_off" }) do
    if env[key] == nil then
        error("rsmm.damage: parent did not pass env." .. key, 0)
    end
end

local I, R, F                = env.I, env.R, env.F
local _va_ok, _ptr_plausible = env._va_ok, env._ptr_plausible
local ENTITY_IMG_BASE        = env.ENTITY_IMG_BASE
local LOBBY_REFRESH_SLOT     = env.LOBBY_REFRESH_SLOT
local MEM_SCAN_MB            = env.MEM_SCAN_MB
local LOBBY_HOOK             = env.LOBBY_HOOK
-- A GETTER. See its use site: the parent learns this at runtime.
local _dispatcher_entity_off = env.dispatcher_entity_off

-- damage meter --------------------------------------------------------------
--
-- Per-player damage attribution: who is carrying the run. Three sources feed
-- one board, in priority order, and each one is disjoint from the others by
-- construction so a hit is never counted twice (all three re-confirmed against
-- the live decompile 2026-08-15).
--
-- 1. HeroStats_OnDamageDealt — PRIMARY. The engine's own per-hero damage
--    bookkeeping, called once per damage application with the DEALING HERO's
--    controller as its first argument. It is hero-scoped (enemies never reach
--    it), it sees every path that lands damage rather than one producer, and
--    it fires for ALLIES too: the engine only skips its own totalling for a
--    non-local hero (the `+0x1d88` gate), it still runs the function. That is
--    what makes an ally's damage countable at all — the game itself never
--    totals it.
-- 2. Entity_ResolveAttackHits — the local attack resolver. Used for damage
--    TAKEN (an enemy swinging at a hero reaches it, and it is the only "I got
--    hit" signal that works in single player), and as the dealt-damage
--    fallback if the primary symbol is unavailable on a future build.
-- 3. gameplay:NETWORK_DAMAGE — replicated damage, keyed by the attacker's NET
--    id (every pointer in that event belongs to the sending machine). Only
--    credited when the same player's hit did not already arrive through source
--    1 on this machine; rows are merged by net id, and a matching amount
--    inside a short window is dropped as the same hit seen twice.
--
-- MULTIPLAYER SCOPE. A peer counts what its own machine applies plus what
-- other machines replicate to it. The host applies enemy damage, so a host's
-- board is complete; a client is complete for its own damage and as complete
-- as replication allows for allies. Nothing here is networked by the mod and
-- no game state is touched — every hook replays the original untouched.
--
--     R.damage.enable{ window = 10 }
--     for rank, row in ipairs(R.damage.board()) do
--         R.log(rank, row.label, row.dealt, row.share, row.dps)
--     end

R.damage = {}

-- Constants and helpers are grouped into two tables ON PURPOSE. Lua caps a
-- function at 200 live locals and the module chunk is one function; as flat
-- locals this section pushed rsmm.lua over the limit and it stopped compiling
-- altogether — every mod dead, for a damage meter. Two tables cost two locals.
local DMG = {
    -- Engine literals that sit inside the serialized lobby member list, found
    -- next to the local display name in session 6c4f. Anchoring the name hunt
    -- on these rather than on a player's name needs no config and cannot
    -- collide with an asset path.
    -- Bytes `mem_find` may examine per needle. Was 512 MB, and EVERY hit in
    -- sessions 5736/274f sat below ~0x1b000000 — the scan was exhausting its
    -- budget inside the low heap (where Lua's own strings live) and returning
    -- before it ever reached the game's allocations. The searches were finding
    -- the probe and the config because those are the only things in the part
    -- of the address space the probe could afford to look at.
    NAME_SCAN_MB    = MEM_SCAN_MB,
    -- Strings that exist ONLY in this SDK. Lua interns every literal in the
    -- module, so the scan finds rsmm.lua's own string table and reports it as
    -- a record — most of session 5736's output was the probe finding itself,
    -- including the marker literals above. A window containing any of these is
    -- our Lua heap, never a game structure.
    STATS_SYMBOL    = "HeroStats_OnDamageDealt",
    TAKEN_SYMBOL    = "HeroStats_OnDamageTaken",
    ATTACK_SYMBOL   = "Entity_ResolveAttackHits",
    -- oCDtEntityCpntHeroController
    HERO_ENTITY_OFF  = 0x08,     -- owning oCEntity
    HERO_ISLOCAL_OFF = 0x1d88,   -- 1 = this machine's player
    HERO_MIRROR_OFF  = 0x1d80,   -- HUD HP mirror; LOCAL player only
    HERO_STATS_OFF   = 0x1db0,   -- per-run stats record (end-screen source)
    STATS_TOTAL_OFF  = 0xa8,     -- u32 total damage — LOCAL hero only
    STATS_BEST_OFF   = 0xcc,     -- f32 biggest single hit
    -- oCDtProcessedDamage
    PD_VALUE_OFF     = 0x10,     -- -> hit-value object
    VALUE_AMOUNT_OFF = 0x08,     -- f32 damage inside it
    PD_SOURCE_OFF    = 0xa0,     -- -> hit-def / source info
    SOURCE_TYPE_OFF  = 0xc8,     -- u16 attack-type enum
    -- Entity_ResolveAttackHits arguments
    CTX_ENTITY_OFF   = 0x08,     -- attacker context -> attacking entity
    TGT_COUNT_OFF    = 0x00,
    TGT_DATA_OFF     = 0x08,
    MAX_TARGETS      = 32,
    NET_AUTHORITY_OFF = 0x130,   -- net component: 0 = locally owned
    SAMPLE_CAP       = 4096,     -- rolling-window entries per actor
    DEDUPE_WINDOW    = 0.4,      -- seconds a replicated echo can lag by
    -- REBIND SAFETY. A row is only re-adopted by a new controller when the old
    -- controller can no longer be alive. Primary evidence is the CHAPTER EPOCH
    -- (bumped by the engine's own chapter/map events); this is the fallback for
    -- a build where those events never arrive -- a row nobody has credited for
    -- this long has plausibly lost its controller. Only the EXACT hero-id join
    -- may use it; the is-local guess never may.
    REBIND_IDLE      = 45,       -- seconds a row must be silent to be adopted
    -- VICTIM CLASSIFICATION (the enemy-vs-scenery test).
    --
    -- The bookkeeping hook's 2nd argument is the VICTIM ENTITY -- not a stats
    -- block, which is what symbols.json claimed until 2026-08-17. Its sole
    -- caller hands the same pointer to Entity_GetNetComponent, and this
    -- function reads the victim's definition at +0x28 to stamp the analytics
    -- record with the target's resource path. So the victim is already in our
    -- hands on the primary source; classifying it needs no extra hook.
    --
    -- An entity is a gameplay ENEMY when it carries an
    -- oCDtEntityCpntEnemyController component. Fences, jars, vegetation and
    -- mission props are Hittable + HitPoint with no controller at all
    -- (EntitySettings/Destructible_Common/* vs Enemies/NPC_Common/Enemy_Model).
    -- The test is a pure page-guarded READ of the component array -- never an
    -- engine call, so a stale offset yields a wrong answer, never a crash.
    -- Components on an oCEntity live in an F14/SwissTable map keyed by CLASS
    -- ID, not in the +0x190 pointer array — that array belongs to an
    -- oCEntitySpawnerGo (Entity_GetComponentByTester's parameter), which is
    -- why session c536 read `n/a` for every enemy it probed and found the
    -- controller on nobody. Layout from Entity_GetNetComponent
    -- (FUN_140312db0), which does this exact lookup for oCEntityCpntNetwork.
    CPNT_CTRL_OFF    = 0x5e8,    -- entity -> F14 control bytes
    CPNT_SLOTS_OFF   = 0x5f0,    -- entity -> slot array
    CPNT_MASK_OFF    = 0x600,    -- entity -> bucket mask (capacity - 1)
    CPNT_SLOT_STRIDE = 0x10,     -- slot = { u32 class id @+0, cpnt* @+8 }
    CPNT_SLOT_PTR    = 0x08,
    MAX_SLOTS        = 0x4000,   -- refuse an implausible capacity outright
    -- Engine class ids, stamped by each class registrar as
    -- `mov [desc+0x28], <id>`. A content hash of the class NAME, so it is far
    -- more patch-stable than a vftable VA — and the same key the engine's own
    -- component map is indexed by. Mined by tools/mine_class_ids.py; the
    -- miner is confirmed by 0x154fce5c resolving to oCEntityCpntNetwork,
    -- the literal Entity_GetNetComponent hardcodes.
    ENEMY_CTRL_CLASS_ID = 0x1561073c,   -- oCDtEntityCpntEnemyController
    HERO_CTRL_CLASS_ID  = 0x155aac59,   -- oCDtEntityCpntHeroController
    ENEMY_CTRL_VFT_VA = 0x140f30b78,    -- symbols.json EnemyController_vftable
    CPNT_OWNER_OFF   = 0x08,     -- component -> owner entity (back-ptr)
    VICTIM_DEF_OFF   = 0x28,     -- entity -> oCEntitySettings (confirmed live)
    SETTINGS_RSRC_OFF = 0x70,    -- settings -> resource the engine stringifies
    VICTIM_CACHE_CAP = 512,      -- entity -> class cache entries before reset
    -- How many times ONE entity may be re-scanned after an inconclusive read.
    -- A victim whose component map cannot be read answers `unknown` on every
    -- hit, and `unknown` is fail-open — so a DoT ticking on it re-ran the full
    -- linear slot walk on the MAIN THREAD, per tick, for the whole run. Three
    -- attempts is enough to catch an entity that was merely mid-construction.
    VICTIM_RETRIES   = 3,
    -- Reason string for the stale-ally rebind. A GUESS, not an identity: it
    -- must never unlock the idle-adoption path in F._dmg_may_rebind.
    STALE_ALLY = "the only ally row whose controller died with the last chapter",
    PROBE_VICTIMS    = 12,       -- distinct victims the probe reports, then off
    PROBE_VFTS       = 6,        -- component vftables logged per victim
    -- The engine's own attack-type names, read out of the table at
    -- 0x1412ed7d0 that the bookkeeping routine indexes with the enum.
    TYPES = { [0] = "attack", "power", "special", "defense",
              "trait", "ultimate", "dash" },
}

-- NB: F is the parent chunk's shared helper table, passed in. Do NOT
-- rebind it here — code above the damage section (the lobby name hunt)
-- reads F._netid through the PARENT's upvalue, and a fresh table here
-- would leave that one empty forever.
local _dmg = {
    on       = false,
    window   = 10,        -- seconds behind `dps`
    min      = 0,         -- ignore hits at or below this
    names    = {},        -- slot -> player-supplied label
    actors   = {},        -- key -> row
    by_netid = {},        -- net id -> row (merges the replicated view in)
    by_hero  = {},        -- lobby hero id -> row (survives a chapter change)
    order    = {},        -- slot -> row, stable join order
    seen     = {},        -- entity -> true: known NOT a hero, stop asking
    subs     = {},        -- per-hit callbacks
    stats_hooked = false,
    taken_hooked = false,
    hooked   = false,     -- resolver
    local_id = nil,       -- local hero net id (false = unavailable)
    started  = nil,
    -- CHAPTER EPOCH. Incremented by the engine's chapter/map-generation events.
    -- Rows record the epoch they were last bound in, and a row may only be
    -- re-adopted by a NEW controller in a LATER epoch -- inside one chapter,
    -- an unseen hero controller is a different player, never a rebuild.
    epoch    = 0,
    refusals = 0,         -- merges declined (logged, bounded)
    -- Victim classification. `ignore_scenery` is OPT-IN: the engine's own
    -- end-screen total counts prop damage, so counting it is what MATCHES the
    -- game, and dropping it is a deliberate divergence a mod asks for.
    ignore_scenery = false,
    -- The identity hunt (whole-address-space scan + the 24k-probe blind sweep).
    -- OPT-IN, and off by default since 2026-08-20.
    --
    -- Not because it is slow -- because it is a COINCIDENCE GENERATOR. Every
    -- ally name it has ever produced, across every shipped log, came through a
    -- DIFFERENT offset chain:
    --
    --     entity+0x610 -> +0x140    "Gennadiy Tiger`s лапки"
    --     entity+0x678 -> +0x2d0    "Ovili"        (the LOCAL row)
    --     entity+0xad8 -> +0x1c0    "yjukih"
    --     entity+0x440 -> +0x2f0    "Shingaro Miamada"
    --     entity+0xff0 -> +0x8      "Yume"
    --     member+0x360 -> +0xd0     "Ovili"        (the LOCAL row)
    --     member+0x920 -> +0x2a8    "Timattttttt"  (the LOCAL row -- and WRONG)
    --     member+0x1138 -> +0x248   "gaetemp91"
    --     member+0x210              "exs1stenz"
    --
    -- Nine successes, nine offsets, no repeat. A real field answers at the SAME
    -- offset every time; this is finding whatever copy of a roster string
    -- happens to be reachable from the object, and which row it lands on is
    -- arbitrary. Session 6136 is the proof it can be wrong rather than merely
    -- unlucky: it named the LOCAL row "Timattttttt" with Ovili at the keyboard,
    -- which then consumed that name and left its real owner on a placeholder.
    -- Ghidra (2026-08-20) closed the question for two of those chains: the exe
    -- contains ZERO sites that walk entity+0x678 -> +0x2d0 or +0xad8 -> +0x1c0.
    --
    -- It also costs: 89s of blind sweeping across 12 row-passes in session 174f
    -- (~3.2M guarded reads) for zero names. But the cost is the lesser reason.
    --
    -- Turn it on with `R.damage.enable{ identity_hunt = true }` when RE'ing the
    -- identity itself. `R.damage.sweep_identity()` still works either way --
    -- that is the explicit call, and gating it would break the one entry point
    -- a person uses deliberately. To LABEL a run reliably, use player_1..4.
    identity_hunt = false,
    -- The TARGETED address scan (`_dmg_probe_owner_fast`), which is what
    -- actually names an ally. Bounded per roster (F._own.SWEEP_TRIES), but it
    -- still reads F._own.SLICE_MB of address space per second while it runs,
    -- and on a machine where that is felt the honest answer is a switch: the
    -- board keeps its lobby names, they are just marked as guesses. Set
    -- player_1..4 in the mod config for names that are never guesses.
    identity_scan = true,
    -- Show every lobby member on the board, even before they have dealt any
    -- damage (see F._dmg_roster_rows). OFF here and ON in the meter, which is
    -- the right layer for it: `board()` without this is a list of MEASUREMENTS,
    -- and every caller that reasons about attribution wants exactly that. A
    -- scoreboard is a presentation, and a presentation is the mod's call.
    roster_rows = false,
    probe    = false,     -- log the class of the first few distinct victims
    probes   = 0,
    vprobed  = {},        -- victim entity -> already reported
    -- entity -> session id of the machine driving it (see
    -- F._dmg_note_session). Empty until an event proves the join.
    sess_by_entity = {},
    vclass   = {},        -- victim entity -> true (enemy) / false (scenery)
    vclass_n = 0,
    -- Victim SETTINGS pointer -> enemy/scenery, learned from the entities whose
    -- component map DID read. Victims of the same type share one settings
    -- object (see F._dmg_probe_victim), so one conclusive scan of a jar
    -- classifies every other jar — including the instances whose own component
    -- map cannot be read, which is the leak this table closes.
    sclass   = {},
    sclass_n = 0,
    scenery  = 0,         -- damage dropped by the filter, session-wide
}

function F._dmg_now()
    if I.now then
        local ok, t = pcall(I.now)
        if ok and type(t) == "number" then return t end
    end
    return os.time()
end

-- An entity we are willing to hand to an engine lookup: plausible, and its
-- component store at +0x8 is a plausible pointer too. Both engine helpers used
-- below dereference that store unconditionally, so this gate is what keeps a
-- stale pointer from faulting the game instead of returning false.
function F._dmg_entity_ok(e)
    if not _ptr_plausible(e) then return false end
    return _ptr_plausible(I.read_u64(e + 8))
end

-- Heroes (including remote ones) own a magical-object component; summons, pets
-- and enemies do not. Same discriminator R.give uses on a dispatcher.
function F._dmg_is_hero(e)
    if type(I.is_grant_target) ~= "function" then return false end
    -- Plausibility only. The native discriminator page-guards every read it
    -- makes (entity header, the component store at +0x8, the F14 tables) and
    -- answers false on a bad pointer, so gating it on OUR idea of a valid
    -- store is redundant — and it was wrong: a live 4-player log showed the
    -- hero's +0x8 reading as the -1 sentinel, so this gate refused every
    -- victim and `taken` stayed 0 for the whole run.
    if not _ptr_plausible(e) then return false end
    local ok, v = pcall(I.is_grant_target, e)
    return ok and v == true
end

-- Victim classification: enemy vs scenery ---------------------------------
--
-- Everything here is READS. The component array is the same one
-- Entity_GetComponentByTester (FUN_1406e3210) walks, so the offsets are the
-- engine's own; the vftable comparison is the same shape R.xp uses to find the
-- XP component. Nothing is handed to the engine, so the worst a stale offset
-- can do is answer "unknown" -- and unknown NEVER filters (fail-open, so a
-- wrong offset under-filters instead of hiding a player's real damage).

-- Rebased EnemyController vftable, or nil when the module base is unavailable.
function F._dmg_enemy_vft()
    local base = I.module_base()
    if not base or base == 0 then return nil end
    return base + (DMG.ENEMY_CTRL_VFT_VA - ENTITY_IMG_BASE)
end

--- Scan an entity's components for the enemy controller.
--- Returns nil when the entity could not be inspected at all, else a table
--- { enemy, count, slot, owner_ok } — `owner_ok` records whether the matched
--- component's back-pointer at +0x8 points at the entity, which the probe
--- reports so the back-ptr assumption is confirmed in-game rather than
--- assumed (it is NOT required for the match; see _dmg_is_enemy).
function F._dmg_scan_components(entity)
    if not _ptr_plausible(entity) then return nil, "entity implausible" end
    local slots = I.read_u64(entity + DMG.CPNT_SLOTS_OFF)
    local mask  = I.read_u64(entity + DMG.CPNT_MASK_OFF)
    -- A NULL map is an answer, not a failure: the entity owns no components at
    -- all, so it certainly owns no EnemyController. Session ec1d hit this on
    -- two of twelve victims (both 1.0-damage props) and calling them "unknown"
    -- would have let exactly the damage this filter exists for through.
    -- A non-null but implausible pointer is a genuine failed read.
    if (slots == 0 or slots == nil) and (mask == 0 or mask == nil) then
        return { enemy = false, count = 0, empty = true }
    end
    -- The decline REASON matters: session c536 reported "no components" for
    -- every enemy and there was no way to tell an empty map from a bad read.
    if not _ptr_plausible(slots) then
        return nil, ("slots=0x%x implausible"):format(slots or 0)
    end
    if type(mask) ~= "number" or mask < 0 or mask + 1 > DMG.MAX_SLOTS then
        return nil, ("mask=%s over cap"):format(tostring(mask))
    end
    -- The map is walked LINEARLY rather than hashed: the engine's own probe
    -- computes an F14 hash to find one key fast, but we are reading a handful
    -- of slots on a bounded table, and a linear pass needs no hash function to
    -- stay correct across a game patch.
    local want = F._dmg_enemy_vft()
    for i = 0, mask do
        local slot = slots + i * DMG.CPNT_SLOT_STRIDE
        local id   = I.read_u32(slot)
        if id == DMG.ENEMY_CTRL_CLASS_ID then
            local comp = I.read_u64(slot + DMG.CPNT_SLOT_PTR)
            if _ptr_plausible(comp) then
                return { enemy = true, count = mask + 1, slot = i,
                         -- Reported, never required: both are corroboration
                         -- for the class id, which is the actual test.
                         vft_ok   = want ~= nil and I.read_u64(comp) == want,
                         owner_ok = I.read_u64(comp + DMG.CPNT_OWNER_OFF) == entity }
            end
        end
    end
    return { enemy = false, count = mask + 1 }
end

--- The victim's oCEntitySettings pointer, which is its TYPE identity.
---
--- Every jar shares one settings object, every gnoll hunter shares another (the
--- victim probe logs it for exactly this reason). That makes it the key the
--- classification should be remembered under: a per-ENTITY answer has to be
--- re-derived for each instance, and an instance whose component map does not
--- read is unclassifiable forever, while the TYPE was already answered by a
--- sibling that read fine.
function F._dmg_settings(entity)
    local set = I.read_u64(entity + DMG.VICTIM_DEF_OFF)
    return _ptr_plausible(set) and set or nil
end

--- true = gameplay enemy, false = scenery/prop/mission object, nil = unknown.
---
--- Cached per victim pointer because a multi-hit ability re-classifies the
--- same target several times a frame. The cache is validated against the
--- entity's own vftable: pointers ARE recycled inside a run (an enemy dies, a
--- prop lands on its memory), and two reads to re-check beat believing a
--- stale answer.
---
--- THREE tiers, because `unknown` is fail-open and therefore expensive: a
--- victim that answers unknown has its damage counted, so a family of props
--- whose component map cannot be read lands on the board as carry damage. The
--- 2026-08-18 co-op log is that failure — one player at 11,612 hits for 613k
--- damage (59 per hit, against 353 for the top row), long runs of exactly 1.0
--- (the flat per-hit prop value), and a `scenery` column frozen for the last
--- four minutes of the run while their hit count kept climbing.
---
---   1. the per-ENTITY cache (vftable-validated), for the multi-hit case;
---   2. the per-TYPE map, keyed by the settings pointer — filled only from
---      CONCLUSIVE scans, and consulted when this entity's own scan declines;
---   3. give up and answer unknown, but stop re-scanning after
---      DMG.VICTIM_RETRIES attempts. The walk runs on the main thread inside a
---      damage detour, so re-running it per DoT tick for a whole run is not
---      free.
function F._dmg_is_enemy(entity)
    if not _ptr_plausible(entity) then return nil end
    local vft = I.read_u64(entity)
    local hit = _dmg.vclass[entity]
    if hit and hit.vft == vft then
        -- A cached `unknown` still gets a bounded number of retries: the first
        -- read may simply have caught the entity mid-construction.
        if hit.enemy ~= nil or (hit.tries or 0) >= DMG.VICTIM_RETRIES then
            -- The type map may have learned the answer from a sibling since.
            if hit.enemy == nil then
                -- `set and _dmg.sclass[set] or nil` would turn a learned
                -- SCENERY answer (false) back into nil, which is the fail-open
                -- branch this whole table exists to close.
                local set = F._dmg_settings(entity)
                if set ~= nil and _dmg.sclass[set] ~= nil then
                    return _dmg.sclass[set]
                end
            end
            return hit.enemy
        end
    end
    local scan = F._dmg_scan_components(entity)
    if _dmg.vclass_n >= DMG.VICTIM_CACHE_CAP then
        _dmg.vclass, _dmg.vclass_n = {}, 0
        hit = nil
    end
    local set = F._dmg_settings(entity)
    if scan then
        -- Conclusive. Teach the TYPE, so every sibling instance is answered
        -- even when its own component map is unreadable.
        if set and _dmg.sclass[set] == nil then
            if _dmg.sclass_n >= DMG.VICTIM_CACHE_CAP then
                _dmg.sclass, _dmg.sclass_n = {}, 0
            end
            _dmg.sclass[set] = scan.enemy
            _dmg.sclass_n = _dmg.sclass_n + 1
        end
        _dmg.vclass[entity] = { vft = vft, enemy = scan.enemy }
        _dmg.vclass_n = _dmg.vclass_n + 1
        return scan.enemy
    end
    -- Inconclusive: remember the attempt so the walk is not repeated forever,
    -- then fall back to what this victim's TYPE already answered elsewhere.
    local tries = ((hit and hit.vft == vft) and (hit.tries or 0) or 0) + 1
    _dmg.vclass[entity] = { vft = vft, enemy = nil, tries = tries }
    _dmg.vclass_n = _dmg.vclass_n + 1
    if set ~= nil and _dmg.sclass[set] ~= nil then return _dmg.sclass[set] end
    return nil
end

function F._dmg_img_rel(p)
    local base = I.module_base()
    if not p or p == 0 or not base or base == 0 or p < base then return nil end
    return p - base + ENTITY_IMG_BASE
end

--- One-shot diagnostic: what IS this victim?
---
--- Round 1 (2026-08-17, session c536) proved the plumbing and killed the
--- theory: every victim read back as oCEntity (vft 0x140f743b0) with
--- oCEntitySettings at +0x28 and real components at +0x190 — but NOT ONE of
--- twelve carried the EnemyController, and most reported no component array at
--- all. So this round reports (a) WHY the array read declined, (b) EVERY
--- component vftable, not the first six, and (c) the settings' resource path,
--- read as inline strings — that names the victim ("Gnoll_Hunter" vs
--- "Destructible_Jar") instead of leaving it an address, which is the only
--- way to tell a wrong offset from a wrong theory.
---
--- Bounded (DMG.PROBE_VICTIMS victims per process) because it runs on the MAIN
--- THREAD inside the damage detour. Reads only — no engine calls, so nothing
--- here can fault the game.
function F._dmg_probe_victim(entity, amount)
    if not _dmg.probe or _dmg.probes >= DMG.PROBE_VICTIMS then return end
    if not _ptr_plausible(entity) or _dmg.vprobed[entity] then return end
    _dmg.vprobed[entity] = true
    _dmg.probes = _dmg.probes + 1
    local n = _dmg.probes
    local scan, why = F._dmg_scan_components(entity)
    -- Image-relative, so the numbers in the log line up with the addresses in
    -- data/symbols.json across launches (ASLR moves the module, not the RVAs).
    local function hex(p)
        local v = F._dmg_img_rel(p)
        return v and string.format("0x%x", v) or "?"
    end
    local slots = I.read_u64(entity + DMG.CPNT_SLOTS_OFF)
    local mask  = I.read_u64(entity + DMG.CPNT_MASK_OFF)
    local set   = I.read_u64(entity + DMG.VICTIM_DEF_OFF)
    R.log(string.format(
        "[rsmm.damage] victim probe #%d: ent=0x%x vft=%s slots=0x%x mask=%s "
        .. "enemy=%s slot=%s vft_ok=%s owner_ok=%s settings=0x%x dmg=%.1f%s",
        n, entity, hex(I.read_u64(entity)), slots or 0, tostring(mask),
        scan and tostring(scan.enemy) or "unknown",
        scan and scan.slot and tostring(scan.slot) or "-",
        scan and scan.slot and tostring(scan.vft_ok) or "-",
        scan and scan.slot and tostring(scan.owner_ok) or "-",
        set or 0, amount or 0, why and (" declined: " .. why) or ""))
    -- Every OCCUPIED slot's class id. These decode offline against
    -- data/class_ids.json, so one log says exactly which components a fence
    -- and a gnoll each carry — the thing round 1 could not answer.
    if scan then
        local line = {}
        for i = 0, scan.count - 1 do
            local slot = slots + i * DMG.CPNT_SLOT_STRIDE
            local id   = I.read_u32(slot)
            if id and id ~= 0 and _ptr_plausible(I.read_u64(slot + DMG.CPNT_SLOT_PTR)) then
                line[#line + 1] = string.format("0x%x", id)
            end
            if #line == 8 then
                R.log(("[rsmm.damage] probe #%d class ids: %s")
                      :format(n, table.concat(line, " ")))
                line = {}
            end
        end
        if #line > 0 then
            R.log(("[rsmm.damage] probe #%d class ids: %s")
                  :format(n, table.concat(line, " ")))
        end
    end
    -- No string dump here. Reading the victim's asset path out of the settings
    -- object was tried in session ec1d and returned noise ("JAT_I", "0cbuJ^"):
    -- the path is not inline at settings+0x70, the engine reaches it through a
    -- resource handle it resolves with a call. The class ids answer the
    -- question anyway — an enemy's map holds EnemyController +
    -- CharacterController + RemoteDamageOwner + ModifierHolder, a prop's holds
    -- oCEntityCpntNetwork and nothing else — so the string hunt has no
    -- remaining job. `settings` is still logged as an identity: victims of the
    -- same TYPE share one settings pointer, which is what makes it usable as a
    -- classification cache key.
end

-- The engine's local/remote test: net component +0x130 is 0 when this machine
-- controls the entity; no net component at all means it is not replicated.
function F._dmg_entity_is_local(e)
    -- The engine's is-local byte — see _dispatcher_is_local for why it is
    -- neither the net component (crashes) nor the HUD mirror (allies have one).
    if not _ptr_plausible(e) then return false end
    return I.read_u8(e + DMG.HERO_ISLOCAL_OFF) == 1
end

-- NO net-id lookup here, deliberately.
--
-- This used to call Entity_GetNetId to key rows by a replication-stable id.
-- It crashed the game (2026-08-15, dump a97c76fe): that function calls
-- Entity_GetNetComponent, which walks the entity's component map with no
-- guard, and a hero object whose store slot holds the -1 sentinel takes the
-- process down. `is_grant_target` accepting an object proves it is a grantable
-- hero — NOT that a different subsystem can traverse it.
--
-- Nothing needed it badly enough to risk that. The replicated path already
-- carries a net id in its own payload (a plain number off the wire, no engine
-- call), the local player is identified by its HUD mirror, and cross-source
-- double counting is caught by the amount+time echo filter.

-- Net id: the identity that survives replication. nil when unavailable.
function F._dmg_net_id(_e)
    -- Intentionally always nil: see the note above. Kept as a seam so the
    -- callers read the same whether or not a SAFE net-id source ever appears.
    return nil
end

function F._dmg_label_for(slot, is_local)
    if _dmg.names[slot] then return _dmg.names[slot] end
    if is_local then
        -- The local player's real name, when Steam can tell us. "You" is the
        -- fallback, not the goal: a scoreboard full of "Player 2" is what this
        -- avoids for at least one row.
        local ok, name = pcall(R.player.name)
        if ok and type(name) == "string" then return name end
        return "You"
    end
    -- A real name from the LOBBY beats "Player 2". Cache-only (R.lobby.members
    -- never scans) because this runs on the MAIN THREAD inside a damage hook.
    -- If the roster is not resolved yet the row gets a placeholder and
    -- F._dmg_relabel fixes it as soon as the background scan lands.
    --
    -- ⚠ A name is only taken here when there is exactly ONE ally it could
    -- belong to and this is the first ally row — that case is exact by
    -- elimination. The old code matched allies in JOIN ORDER (`allies[rank]`),
    -- which is the order they first dealt damage in and has nothing to do with
    -- the lobby's order, so with 3+ players it attached real names to the wrong
    -- damage totals (reported 2026-08-19, 4p co-op: the local row was right and
    -- every ally row was shuffled). A wrong name on a real number is worse than
    -- no name, so everything else waits for the hero-id join in F._dmg_relabel.
    local ok, allies = pcall(R.lobby.allies)
    if ok and type(allies) == "table" and #allies == 1 then
        local others = 0
        for _, row in ipairs(_dmg.order) do
            if not row.is_local then others = others + 1 end
        end
        if others == 0 then return allies[1] end
    end
    return "Player " .. tostring(slot)
end

--- Re-label ally rows once the lobby roster is known.
---
--- Rows are created the instant an ally deals damage, which is usually before
--- the background scan has found the lobby. Without this they would keep the
--- "Player N" placeholder for the whole run even though the name is available
--- seconds later.
--- Find the row-side field that carries the lobby's `RequestedHero` id.
---
--- Names are matched to rows BY POSITION today: `allies[rank]`, i.e. the order
--- allies happened to first deal damage in, which is not the lobby's order and
--- is wrong as often as it is right (rows carry `label_guess` for exactly this
--- reason). The join that would be exact is the hero: every lobby member record
--- carries `RequestedHero` (+0x10), so if the row's own object holds the same
--- id at some offset, name and row line up with no guessing at all.
---
--- Rather than hand-RE that offset over several launches, let one session find
--- it: sweep each row's controller for a dword that equals one of the known
--- hero ids, and keep only the offsets where EVERY row reads a DIFFERENT known
--- id. A field that is constant across players, or that only matches for one of
--- them, is not the hero id — the discriminator is the same "must differ across
--- siblings" trick that finds abstract vtable slots.
---
--- Pure page-guarded reads, once per session, and only when a co-op lobby has
--- actually produced two identified members and two rows.
local HERO_ID_PROBE = { done = false, LO = 0, HI = 0x2000,
                        HOP_HI = 0x800,   -- how far into a hero definition
                        BUDGET = 20000,   -- probes per background tick; the deep scan is ~900k,
                                          -- so this finishes it inside a minute
                        cursor = nil, hits = nil, rows_n = 0, hop = nil,
                        off = nil, w = 4, attempts = 0, MAX_ATTEMPTS = 6,
                        -- Seconds a restart-worthy change has to wait when one
                        -- just happened. The scan restarts whenever the row
                        -- COUNT changes, which is right (a new row is a bigger
                        -- sample and may veto an offset) but was unbounded: a
                        -- board that forks rows -- a transform, a respawn, an
                        -- ally the build cannot identify -- threw the ~900k
                        -- probe scan back to phase 1 as often as rows appeared,
                        -- so it burned its per-tick budget forever and never
                        -- finished. Coalescing costs nothing: `rows_n` is left
                        -- stale while cooling, so the restart still happens,
                        -- just once for a burst instead of once per row.
                        RESTART_EVERY = 30, restarted_at = nil }

--- Read a hero id of width `w` at `va`.
---
--- WIDTH MATTERS. The first version read dwords only, and a hero id is a small
--- number (session ea68's lobby: 2, 4, 5, 6) — exactly the kind of value an
--- engine stores in a BYTE. A dword read over a byte field picks up whatever
--- the next three bytes hold, so the id is invisible unless those happen to be
--- zero. That sweep reported "no offset distinguishes the rows" on a real
--- 4-player run; it was never in a position to see a u8 or u16 field.
function F._dmg_read_id(va, w)
    if w == 1 then return I.read_u8(va) end
    if w == 2 then return I.read_u16 and I.read_u16(va) end
    return I.read_u32(va)
end

--- @param wide  also sweep BYTE and WORD fields. ~3x the reads, so only the
---              background tick asks for it; the boarding path stays dword-only.
function F._dmg_probe_hero_field(wide)
    if HERO_ID_PROBE.done then return end
    local okm, members = pcall(R.lobby.members)
    if not okm or type(members) ~= "table" then return end
    local ids, n = {}, 0
    for _, m in ipairs(members) do
        if m.hero_id and not ids[m.hero_id] then
            ids[m.hero_id] = m.name
            n = n + 1
        end
    end
    if n < 2 then return end
    local rows = {}
    for _, row in ipairs(_dmg.order) do
        -- Rows are keyed by controller, entity OR net id; only the pointer
        -- keys are objects we can read fields out of.
        if _ptr_plausible(row.key) then rows[#rows + 1] = row end
    end
    -- SAMPLE SIZE. Two rows is the minimum that can discriminate anything, but
    -- in a four-player lobby it is also the sample most likely to leave an
    -- unrelated field looking unique — and adopting a wrong offset MERGES two
    -- players (2026-08-18, session 29a8: four players, two rows). So wait for a
    -- third row whenever the lobby says a third player exists; a two-player
    -- lobby still adopts on two, since that is every row there will ever be.
    local need = n >= 3 and 3 or 2
    if #rows < need then return end
    -- A NEW row is new evidence: restart the scan so every offset is judged
    -- against the biggest sample available. Otherwise an offset that looked
    -- unique against three rows is adopted while a fourth would have vetoed it.
    local c = HERO_ID_PROBE.cursor
    -- A WIDER call is new evidence too. The damage path probes u32 only; the
    -- background tick probes u8/u16/u32. Resuming the narrow scan's cursor
    -- would skip the byte and word passes entirely — and a byte-sized hero id
    -- is the case this sweep exists for.
    local churn = (HERO_ID_PROBE.rows_n ~= #rows)
    local now = F._dmg_now()
    local cooling = churn and HERO_ID_PROBE.restarted_at ~= nil
                    and (now - HERO_ID_PROBE.restarted_at) < HERO_ID_PROBE.RESTART_EVERY
    if not c or (churn and not cooling)
       or ((wide and true or false) and not c.wide) then
        c = { phase = 1, wi = 1, off = HERO_ID_PROBE.LO, hop = 0, ptrs = nil,
              wide = wide and true or false }
        HERO_ID_PROBE.cursor, HERO_ID_PROBE.hits = c, {}
        HERO_ID_PROBE.rows_n = #rows
        HERO_ID_PROBE.restarted_at = now
    end

    local hits = HERO_ID_PROBE.hits
    -- Widths, each with its own stride: a byte field can start anywhere, a word
    -- field on any even address.
    local widths = wide and { 1, 2, 4 } or { 4 }

    -- Two phases. DIRECT looks for the id as a field on the controller —
    -- which three live four-player sessions have now reported as "no offset
    -- distinguishes the rows", at every width. HOP looks one pointer deep,
    -- because that is where an engine of this shape actually keeps it: the
    -- controller holds a pointer to the hero DEFINITION, and the id is a field
    -- of the definition. Same evidence test either way, and it is a strong one
    -- — three or more rows reading DISTINCT ids that are all on the roster, at
    -- one offset. Resumable and budgeted: the hop space is ~900k probes, which
    -- is a few minutes of background ticks, not a frame.
    -- One FIELD, not one width. A byte holding 4 reads as 4 through u8, u16 and
    -- u32 whenever the bytes after it happen to be zero, so the same location
    -- was landing in `hits` three times and every deep scan ended "ambiguous"
    -- — the one outcome that adopts nothing. Widths are tried narrowest first
    -- and the narrowest wins: a byte field read as a dword only works while the
    -- neighbours stay zero, which is exactly the trap the wide sweep was added
    -- to escape.
    local function record(off, hop, w, text)
        for _, h in ipairs(hits) do
            if h.off == off and h.hop == hop then return end
        end
        hits[#hits + 1] = { off = off, hop = hop, w = w, text = text }
    end

    -- GROUND TRUTH, free. Row 1 is the local player, Steam already told us who
    -- that is, and their lobby blob carries their RequestedHero — so any offset
    -- claiming to be the hero id MUST read exactly that id on the local row.
    --
    -- Without this the test only asks that the rows read DISTINCT ids that are
    -- on the roster, and a 0x2000-byte controller scanned at strides 1/2/4 is
    -- thousands of small-int fields, plenty of which satisfy that by accident.
    -- Session 174f did exactly that: it adopted `+0x1b60/u32`, and a sweep of
    -- the shipped exe (2026-08-20) finds ZERO reads or writes at +0x1b60 on any
    -- object base — while every offset this meter uses that IS proven in-game
    -- (+0x15c8 HP, +0x1d80 mirror, +0x1d88 is-local, +0x1db0 stats) shows 11 to
    -- 58. The engine never touches +0x1b60; it was uninitialised memory that
    -- happened to hold three roster hero ids, and every ally name on that board
    -- came from it.
    --
    -- The anchor is exactly as sound as the join it guards: `ids` maps
    -- RequestedHero -> name, so if the local row does not read the local
    -- member's RequestedHero, the join is meaningless for every other row too.
    local anchor_row, anchor_id
    do
        local okme, me = pcall(R.player.name)
        if okme and type(me) == "string" and me ~= "" then
            for _, m in ipairs(members) do
                if m.name == me and m.hero_id then anchor_id = m.hero_id break end
            end
            if anchor_id then
                for _, row in ipairs(rows) do
                    if row.is_local then anchor_row = row break end
                end
            end
        end
    end
    HERO_ID_PROBE.anchored = anchor_row ~= nil

    local function judge(read, strict)
        local seen, matched = {}, 0
        for i, row in ipairs(rows) do
            local v = read(i, row)
            -- The anchor is a veto, not a vote: a wrong value here disqualifies
            -- the offset outright, however well every other row reads.
            if anchor_row and row == anchor_row and v ~= anchor_id then
                return false
            end
            if type(v) == "number" and ids[v] then
                if seen[v] then return false end   -- two rows, one player
                seen[v] = true
                matched = matched + 1
            end
        end
        -- `strict` demands EVERY row, not just `need` of them. The deep scan
        -- searches ~900k offsets instead of 24k, so the coincidence rate is
        -- ~40x higher and "three rows agreed" stops being rare — a scan that
        -- ends ambiguous adopts nothing and the run stays on placeholders.
        -- Requiring the whole board to read a distinct roster id is a test
        -- almost nothing passes by accident.
        --
        -- ⚠ UNTESTED BRANCH. It only differs from the quorum once there are
        -- MORE rows than `need` (four players, quorum three), and a four-row
        -- fixture would not board cleanly in the spec harness. The three-row
        -- deep-scan test exercises this path with strict == need.
        return matched >= (strict and #rows or need)
    end

    -- PHASE 1, the field on the controller itself. Runs to completion in this
    -- call: it is ~24k probes, and the rest of the meter depends on the answer
    -- being ready the moment the second row boards.
    if c.phase == 1 then
        for _, w in ipairs(widths) do
            for off = HERO_ID_PROBE.LO, HERO_ID_PROBE.HI, w do
                if judge(function(_, row)
                        return F._dmg_read_id(row.key + off, w)
                    end) then
                    record(off, nil, w, string.format("+0x%x/u%d", off, w * 8))
                    if #hits >= 8 then break end
                end
            end
            if #hits >= 8 then break end
        end
        -- Anything at all here settles it, one way or the other. The deep scan
        -- below is for the case three live four-player sessions actually
        -- produced: nothing on the controller, at any width.
        c.phase = (#hits == 0) and 2 or 3
    end

    -- PHASE 2, one pointer deep. The controller holds a pointer to the hero
    -- DEFINITION and the id is a field of that — which is why every direct
    -- sweep so far reported "no offset distinguishes the rows". ~900k probes,
    -- so it is budgeted and resumable across background ticks; the evidence
    -- test is the same strong one (three or more rows reading DISTINCT roster
    -- ids at one offset).
    -- ⛔ PHASE 2 IS RE-ONLY, gated on `identity_hunt`.
    --
    -- ~900k page-guarded reads, budgeted at 20k per BACKGROUND TICK, i.e. ~45
    -- ticks of solid probing on every single run. It was ungated, and it is the
    -- heaviest thing the SDK does -- the "lags sometimes hard" the board was
    -- blamed for. What makes it waste rather than cost is that the answer is
    -- already known: three live four-player sessions found no hero id on the
    -- controller at any width, and Ghidra (2026-08-20) showed why -- there are
    -- no fixed component slots on oCEntity, so session 7068's chains were heap
    -- coincidence. The peer table now supplies names by a different route.
    --
    -- Phase 1 stays on for everyone: it is a bounded direct sweep and it is
    -- what would notice if a patch ever DID put the id back on the controller.
    if c.phase == 2 and not _dmg.identity_hunt then
        c.phase = 3
        if not HERO_ID_PROBE.deep_said then
            HERO_ID_PROBE.deep_said = true
            R.log("[rsmm.damage] hero-id deep scan skipped (no id on the "
                .. "controller on this build; enable identity_hunt to re-run it)")
        end
    end
    local budget = HERO_ID_PROBE.BUDGET
    while budget > 0 and c.phase == 2 do
        budget = budget - 1
        local w = widths[c.wi]
        -- One pointer read per OFFSET, reused across every hop and width;
        -- per-probe would triple the cost of the phase.
        if not c.ptrs then
            c.ptrs = {}
            local live = 0
            for i, row in ipairs(rows) do
                local ptr = I.read_u64(row.key + c.off)
                c.ptrs[i] = _ptr_plausible(ptr) and ptr or false
                if c.ptrs[i] then live = live + 1 end
            end
            c.live = live
        end
        if c.live >= need
           and c.live == #rows
           and judge(function(i)
                   local ptr = c.ptrs[i]
                   return ptr and F._dmg_read_id(ptr + c.hop, w) or nil
               end, true) then
            record(c.off, c.hop, w, string.format("+0x%x -> +0x%x/u%d",
                                                  c.off, c.hop, w * 8))
        end
        c.hop = c.hop + w
        if c.hop > HERO_ID_PROBE.HOP_HI then
            c.hop, c.wi = 0, c.wi + 1
            if c.wi > #widths then
                c.wi, c.ptrs = 1, nil
                c.off = c.off + 8                  -- pointer slots are aligned
                if c.off > HERO_ID_PROBE.HI then c.phase = 3 end
            end
        end
        if #hits >= 8 then c.phase = 3 end
    end
    -- Still scanning: say nothing. The version that re-ran the whole sweep
    -- every tick logged the same "no offset distinguishes the rows" line each
    -- time, which buried the log without adding one fact.
    if c.phase <= 2 then return end
    HERO_ID_PROBE.cursor = nil

    local known = {}
    for id, nm in pairs(ids) do known[#known + 1] = string.format("%s=%d", nm, id) end
    table.sort(known)
    -- ADOPT the offset, do not just report it. A confirmed hero id is the only
    -- identity a player keeps across a CHAPTER TRANSITION: the engine builds a
    -- fresh hero controller for the next chapter, so rows keyed by the
    -- controller pointer fork — the same player appears twice, the slot counter
    -- runs past the player count ("Player 6", "Player 7"), and the abandoned
    -- rows sit at 0.0 dps for the rest of the run. That is exactly what the
    -- 2026-08-17 evening log shows: seven rows for a four-player lobby, "Juice"
    -- twice, both marked as the local player.
    --
    -- Only an UNAMBIGUOUS sweep is adopted. With two rows several offsets can
    -- coincidentally hold two distinct known ids; keying identity on the wrong
    -- one would merge two different players into one row, which is worse than
    -- the duplicate it fixes. Ambiguity re-arms the probe instead: a later
    -- sweep with more rows narrows it.
    if #hits == 1 then
        HERO_ID_PROBE.off, HERO_ID_PROBE.w = hits[1].off, hits[1].w
        HERO_ID_PROBE.hop = hits[1].hop
        HERO_ID_PROBE.done = true
        HERO_ID_PROBE.text = hits[1].text   -- so a withdrawal can name it
        -- BACKFILL every row that was boarded before the identity existed.
        -- The sweep cannot run until two rows and two named lobby members are
        -- in hand, so the FIRST row — often an ally, since the sweep fires when
        -- the second player deals damage — would otherwise carry no hero id and
        -- fork at the next chapter anyway. That is the residual duplicate the
        -- first version of this fix would still have produced.
        F._dmg_backfill_ids()
    else
        HERO_ID_PROBE.done = false
        HERO_ID_PROBE.attempts = (HERO_ID_PROBE.attempts or 0) + 1
        if HERO_ID_PROBE.attempts >= HERO_ID_PROBE.MAX_ATTEMPTS then
            HERO_ID_PROBE.done = true          -- give up; pointer keys only
        end
    end
    R.log(("[rsmm.damage] hero-id field probe: %d row(s), lobby ids {%s} -> %s")
          :format(#rows, table.concat(known, ", "),
                  #hits == 1 and (hits[1].text .. " ADOPTED as the row identity")
                  or (#hits > 1
                      and ("ambiguous (" .. (function()
                              local ts = {}
                              for _, h in ipairs(hits) do ts[#ts + 1] = h.text end
                              return table.concat(ts, " ")
                          end)() .. "), retrying")
                      or ("no offset distinguishes the rows (widths tried: %s)")
                         :format(wide and "u8 u16 u32" or "u32"))))
end

--- Re-check the adopted hero-id offset against the CURRENT board.
---
--- The probe adopts on the first sample big enough to discriminate (three rows
--- when the lobby seats four) and then sets `done`, whose first act is to make
--- the probe return immediately. So a FOURTH row — the one piece of evidence
--- that could still veto the offset — arrives after the decision and is never
--- consulted. Session 174f: `+0x1b60/u32` adopted at 17:39:54 on three rows,
--- row 4 boarded at 17:40:11, and the offset was never questioned again.
---
--- Withdrawing matters more than mislabelling suggests: `by_hero` is also the
--- chapter-change rebind key, so a wrong identity MERGES two players' rows at
--- the next boundary, which deletes a player's damage rather than misnaming it.
---
--- Cheap: one guarded read per row, on the background tick.
function F._dmg_recheck_hero_field()
    if not HERO_ID_PROBE.off then return end
    local okm, members = pcall(R.lobby.members)
    if not okm or type(members) ~= "table" or #members == 0 then return end
    local ids, anchor_id = {}, nil
    for _, m in ipairs(members) do
        if m.hero_id and m.name then ids[m.hero_id] = m.name end
    end
    local okme, me = pcall(R.player.name)
    if okme and type(me) == "string" and me ~= "" then
        for _, m in ipairs(members) do
            if m.name == me and m.hero_id then anchor_id = m.hero_id break end
        end
    end
    -- Only POSITIVE contradictions count. A row whose fields are not live yet
    -- reads nil, and nil is not evidence against the offset.
    local seen, why = {}, nil
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) then
            local v = F._dmg_hero_id(row.key)
            if type(v) == "number" then
                if row.is_local and anchor_id and v ~= anchor_id then
                    why = ("the local row reads hero %d but this machine's "
                           .. "player is hero %d"):format(v, anchor_id)
                elseif seen[v] then
                    why = ("rows %d and %d both read hero %d"):format(
                        seen[v], row.slot, v)
                elseif not ids[v] then
                    why = ("row %d reads hero %d, which is nobody on the "
                           .. "roster"):format(row.slot, v)
                end
                seen[v] = row.slot
            end
        end
        if why then break end
    end
    if not why then return end

    R.log(("[rsmm.damage] WITHDRAWING the hero-id offset %s: %s. Every name it "
           .. "handed out is unproven, so those rows go back to placeholders.")
          :format(HERO_ID_PROBE.text or "?", why))
    HERO_ID_PROBE.off, HERO_ID_PROBE.hop, HERO_ID_PROBE.w = nil, nil, nil
    HERO_ID_PROBE.text, HERO_ID_PROBE.done = nil, false
    HERO_ID_PROBE.cursor, HERO_ID_PROBE.hits, HERO_ID_PROBE.rows_n = nil, {}, nil
    -- A withdrawal is not row churn; it must not be throttled by the restart
    -- cooldown, or the re-scan it exists to trigger waits up to RESTART_EVERY.
    HERO_ID_PROBE.restarted_at = nil
    _dmg.by_hero = {}
    for _, row in ipairs(_dmg.order) do
        row.hero_id = nil
        -- A name the SWEEP proved (`row.player`) or one the player configured
        -- stands; only the hero-join's guesses are taken back.
        if not row.player and not _dmg.names[row.slot] then
            row.label = F._dmg_label_for(row.slot, row.is_local)
            row.label_guess = false
        end
    end
end

--- Give every row an identity it is missing. Rows boarded before the sweep
--- adopted an offset have none, and a row without one forks at the next
--- chapter — so this runs when the offset lands AND on the tick, because a
--- controller's fields are not always live the first time it is seen.
function F._dmg_backfill_ids()
    if not HERO_ID_PROBE.off then return end
    for _, r in ipairs(_dmg.order) do
        if not r.hero_id and _ptr_plausible(r.key) then
            r.hero_id = F._dmg_hero_id(r.key)
            if r.hero_id then _dmg.by_hero[r.hero_id] = r end
        end
    end
end

--- The player's identity, stable across chapter transitions. nil until the
--- sweep above has confirmed an offset, or when the value read there is not a
--- hero id the lobby knows about (a re-created controller can be read before
--- its fields are live — the same "not live yet" window hero-capture handles).
function F._dmg_hero_id(hero)
    local off = HERO_ID_PROBE.off
    if not off or not _ptr_plausible(hero) then return nil end
    local base = hero
    -- An adopted HOP offset means the id lives in the object the controller
    -- points at (the hero definition), not on the controller itself.
    if HERO_ID_PROBE.hop then
        base = I.read_u64(hero + off)
        if not _ptr_plausible(base) then return nil end
        off = HERO_ID_PROBE.hop
    end
    local id = F._dmg_read_id(base + off, HERO_ID_PROBE.w)
    if type(id) ~= "number" or id <= 0 or id >= 0x1000 then return nil end
    -- Cross-check against the roster when there is one: the offset was chosen
    -- from a two-row sample, so a value that is not a known hero id means the
    -- field has been re-used and the identity must not be trusted.
    local ok, members = pcall(R.lobby.members)
    if ok and type(members) == "table" and #members > 0 then
        for _, m in ipairs(members) do
            if m.hero_id == id then return id end
        end
        return nil
    end
    return id
end

-- Identity by the player's OWN NAME, found in their controller's memory graph.
--
-- The hero-id join needs the lobby's `RequestedHero` to sit as a dword on the
-- hero controller, and a four-player playtest (2026-08-19, session 5a1d) proved
-- it does not: `4 row(s), lobby ids {...} -> no offset distinguishes the rows`,
-- repeated all run, every ally on a "Player N" placeholder. A placeholder is
-- honest but it is not the point of a damage meter — "who did 3252" has to have
-- an answer.
--
-- So stop hunting the id and hunt the thing already in hand: the gamertag. A
-- player's display name appearing inside their own controller — inline, behind
-- a pointer, or as the heap data of an MSVC std::string — is SELF-EVIDENT
-- identity. It needs no cross-row corroboration the way a bare integer does,
-- because no unrelated field coincidentally spells "Keif_Buddings". One row
-- identified also yields the offset chain, which names every later row in two
-- reads.
--
-- Bounded, resumable, background-thread only: a fixed read budget per tick, a
-- cursor that survives across ticks, and page-guarded reads throughout (a bad
-- address returns nil, it does not fault).
-- (a field on `F`, not a local: rsmm.lua sits at Lua's 200-live-locals cap
-- for the module chunk — one more `local` here fails to COMPILE the whole SDK.)
F._own = {
    WIN = 0x2000,        -- how far into an object a name may sit
    HOP = 0x400,         -- and how far into an object one pointer away. 0x100
                         -- was too shallow to reach a name held deep inside the
                         -- HUD mirror (+0x1d80) or the stats block (+0x1db0),
                         -- which are the two objects on a controller most
                         -- likely to carry one.
    STRIDE = 8,
    BUDGET = 24000,      -- probes per tick. A full row is ~264k over both
                         -- bases, so at 6000 a four-player board took ~3
                         -- minutes to even finish its FIRST pass — longer than
                         -- session fb4f's whole run, which is why nothing was
                         -- named. The reads are page-guarded and cheap.
    -- Every { base = 1|2, off = n, hop = n|nil } that has named a row, learned
    -- on THIS board. Deliberately EMPTY at startup.
    --
    -- It was briefly seeded with the two chains session 7068 recorded
    -- (`entity+0x678 -> +0x2d0`, `entity+0xad8 -> +0x1c0`) on the theory that an
    -- offset chain is a property of the build. Ghidra says otherwise, and the
    -- theory was wrong because those are not offsets into anything:
    --
    --   * Across all 65,347 .pdata functions of the shipped exe there is not a
    --     single site that loads [X+0x678] and then reads [+0x2d0], nor one for
    --     [X+0xad8] -> [+0x1c0]. (The same sweep does find real chains, e.g.
    --     [X+0xb8] -> [+0x20], so it is not blind.)
    --   * +0xad8 is never touched on any register that also walks an entity.
    --   * The one qword-pointer write at +0x678 near entity-shaped code belongs
    --     to `oe::dt::EntityCpntRecapBookPageSettings::~dtor` (FUN_140419aa0),
    --     an unrelated UI settings class; the other site stores a FLOAT there.
    --   * There are no fixed component slots on oCEntity to be found anyway:
    --     Entity_GetNetComponent reaches components through a hash map at
    --     entity+0x5e8/+0x5f0/+0x600 keyed by class id. See its symbol note.
    --
    -- So session 7068's two chains were heap COINCIDENCE — a pointer that
    -- happened to sit at that offset in that run's hero entity, landing that
    -- far before a string that happened to hold the id. Seeding a coincidence
    -- makes it a prior that runs BEFORE every corroborating check, on every
    -- board, forever. A chain is only trustworthy once it has been observed on
    -- THIS board and survived the one-owner rule below.
    chains = {},
    addrs = nil,         -- where each roster name lives in memory
    addrs_key = nil,     -- the roster those addresses were scanned for
    MAX_HITS = 20000,    -- copies of one needle worth collecting. Both 24 and
                         -- 512 were CEILINGS, not limits: sessions 314f and
                         -- a84f truncated every needle, and a truncated scan
                         -- keeps whichever copies sit LOWEST in the address
                         -- space — never the game-heap object that owns the
                         -- player. A peer id turns up in hundreds of network
                         -- buffers, so the cap has to be far above that or it
                         -- silently decides the answer.
    -- Bytes of address space one tick may examine. `mem_find`'s own default
    -- is 512 MB, which is a debug-probe figure: it is seconds of wall time and
    -- the player feels it as a stall. The lobby sweep has run at 48 MB a tick
    -- all along without a single report, so this sits beside it. The sweep
    -- takes MINUTES to cross the address space at this rate, and that is the
    -- intended trade — it runs on the background thread against a board the
    -- guessed names have already labelled, so finishing sooner buys nothing a
    -- player can see, while finishing louder costs a frame.
    SLICE_MB = 48,
    cursor_va = 0,       -- resume address for the needle at the head of `queue`
    hits_n = 0,          -- hits collected for THAT needle, across its slices
    PAGE = 12,           -- address index granularity (4 KiB), see _dmg_index
    -- There is no time-based rescan, and the `SCAN_EVERY`/`scan_at` pair that
    -- claimed to be one was set and never read by anything. What actually
    -- bounds the scan is `addrs_key` (the roster) plus the chapter epoch, which
    -- drops the cache in F._dmg_next_epoch — a timer would only reintroduce
    -- the periodic address-space walk this all exists to avoid.
    queue = nil,         -- needles still to scan, one per tick
    -- Full address-space sweeps allowed PER ROSTER before the scan gives up.
    --
    -- Without a bound this never stops, and that is what a player feels as a
    -- constant stutter for a whole co-op run. Two things conspire:
    -- `_dmg_probe_owner_fast` gates on `row.player`, which only a VERIFIED
    -- claim sets — a guessed label (`guess_names`, on by default) leaves it
    -- nil forever — so the board can display four correct names and still be
    -- asking to be scanned. And `_dmg_next_epoch` drops `addrs_key` on every
    -- chapter, which re-arms the whole sweep from cursor 0. A run has several
    -- chapters, so the sweep restarts before it finishes and the address space
    -- is walked at SLICE_MB per second, without pause, for the entire run.
    --
    -- A sweep that crossed the address space and claimed nobody will not claim
    -- anybody on a re-run against the same roster, so retrying it forever buys
    -- nothing at all. Two attempts covers the one case a retry can help: a
    -- sweep aborted mid-way by a chapter boundary. Any successful claim clears
    -- the counter, because then the scan is demonstrably working and the rows
    -- still unnamed deserve the next pass.
    SWEEP_TRIES = 2,
    tries = {},          -- roster key -> sweeps started for it
    gave_up = {},        -- roster key -> true once it is not worth retrying
    TRIES = 4,           -- full sweeps per row before it is given up on
    RETRY_AFTER = 20,    -- seconds between them. A chapter is shorter than
                         -- the old 45s, so a row could miss its whole run.
    cursor = nil,        -- { row = <row>, base = 1, off = 0, hop = nil }
    found = 0, swept = 0,
}

--- Where in the process does each player's identity string actually live?
---
--- The blind sweep asks the wrong question. It walks ~264k offsets PER ROW
--- reading a string at every one, which is ~44s of background ticks per row —
--- session fb4f's whole run finished before the first pass did, and nothing
--- was named. The engine can answer the question directly: `mem_find` is a
--- native scan for a byte pattern, so ONE scan per player yields every address
--- that player's peer id is stored at.
---
--- That turns identification into arithmetic. A row owns a name when one of
--- its pointers lands just before one of that name's addresses — the chain
--- session 7068 found by brute force (`entity+0x678 -> +0x2d0`) is exactly the
--- statement "a pointer at entity+0x678 points 0x2d0 bytes before the string".
--- Testing that costs 2048 pointer reads and some subtraction, not 264k string
--- reads, and it is the same evidence.
---
--- Cached against the roster: re-scanning the address space every tick would
--- be far worse than the sweep it replaces.
function F._dmg_find_needles(names)
    if type(I.mem_find) ~= "function" then return nil end
    -- PEER IDS ONLY. A gamertag turns up in chat, the friends list and every
    -- piece of UI text that mentions the player, so scanning for it doubles
    -- the work to produce the noisiest half of the results. The id is not
    -- human-facing, so its copies are the objects that actually own the
    -- player — and it is what named a row in session 314f.
    local keys = {}
    for needle, m in pairs(names) do
        if needle ~= m.name then keys[#keys + 1] = needle end
    end
    table.sort(keys)
    local key = table.concat(keys, "\1")
    if F._own.addrs_key == key and not F._own.queue then return F._own.addrs end
    if #keys == 0 then return nil end

    -- ONE needle per tick, and ONE SLICE of that needle per tick. Each scan is
    -- a native walk of the whole user address space; eight back to back on a
    -- single tick is the stutter session a84f reported, and even ONE unsliced
    -- call is gigabytes of ReadProcessMemory holding the process VM lock —
    -- session a14f's two hard hitches were this call, at the 512 MB default,
    -- three needles at 11:37:03 and two more at 11:40:01.
    --
    -- Dropping `mem_find`'s second return was also a CORRECTNESS bug, and the
    -- quieter one. That value is the resume address, and the whole reason the
    -- native side has one. Without it the sweep stopped dead at the default
    -- budget and never continued, so it searched the low heap — where Lua's
    -- own strings live — and never reached the game's allocations at all.
    -- `capped` counts hits, not bytes, so the log called that a clean scan.
    -- It is the exact failure NAME_SCAN_MB documents for sessions 5736/274f,
    -- reintroduced one layer up, and it is why this scan has never once
    -- claimed a row.
    -- Already swept this roster to no effect. Answer from the cache (which is
    -- nil after a chapter epoch, and a nil answer costs the caller one loop
    -- over the rows) rather than walking the address space again.
    if F._own.gave_up[key] then
        F._own.addrs_key, F._own.queue = key, nil
        return F._own.addrs
    end
    if F._own.addrs_key ~= key then
        local n = (F._own.tries[key] or 0) + 1
        if n > F._own.SWEEP_TRIES then
            F._own.gave_up[key] = true
            F._own.addrs_key, F._own.addrs, F._own.queue = key, nil, nil
            R.log(("[rsmm.damage] identity scan: %d sweep(s) of this roster "
                   .. "named nobody — standing down for the rest of the "
                   .. "session (the board keeps its lobby names; set "
                   .. "player_1..4 in the mod config for names that are never "
                   .. "guesses)"):format(F._own.SWEEP_TRIES))
            return nil
        end
        F._own.tries[key] = n
        F._own.addrs_key, F._own.addrs = key, {}
        F._own.queue, F._own.capped = {}, 0
        -- The slice cursor belongs to the needle at the head of the queue
        -- being dropped here. Left behind, the first needle of the NEXT
        -- roster resumes from a stranger's address and never scans anything
        -- below it. This is also the chapter-epoch path: `_dmg_next_epoch`
        -- clears `addrs_key`, so the very next call lands in this branch.
        F._own.cursor_va, F._own.hits_n = 0, 0
        for i = #keys, 1, -1 do F._own.queue[#F._own.queue + 1] = keys[i] end
    end
    local q = F._own.queue
    if q and #q > 0 then
        -- PEEK, don't pop: the needle stays at the head until its sweep
        -- reaches the end of the address space. Popping here is what made the
        -- unsliced call look complete.
        local needle = q[#q]
        local left = F._own.MAX_HITS - (F._own.hits_n or 0)
        local nxt = 0
        if left <= 0 then
            F._own.capped = (F._own.capped or 0) + 1
        else
            local ok, hits, resume = pcall(I.mem_find, needle, left,
                                           F._own.SLICE_MB,
                                           F._own.cursor_va or 0)
            if ok and type(hits) == "table" then
                local m = names[needle]
                for _, va in ipairs(hits) do
                    if va and va > 0x10000 then
                        F._own.addrs[#F._own.addrs + 1] = { va = va,
                                                            name = m.name }
                        F._own.hits_n = (F._own.hits_n or 0) + 1
                    end
                end
                nxt = (type(resume) == "number") and resume or 0
                if F._own.hits_n >= F._own.MAX_HITS then
                    F._own.capped, nxt = (F._own.capped or 0) + 1, 0
                end
            end
            -- A raise leaves nxt at 0, which retires the needle. Carrying the
            -- cursor forward instead would re-raise on the same slice every
            -- tick for the rest of the run.
        end
        F._own.cursor_va = nxt
        if nxt == 0 then
            table.remove(q)
            F._own.hits_n = 0
        end
        if #q == 0 then
            F._own.queue = nil
            -- Say when a needle hit the ceiling. A truncated scan looks
            -- exactly like a healthy one in the totals, which is how two
            -- sessions were spent chasing the wrong thing.
            R.log(("[rsmm.damage] identity scan: %d needle(s) -> %d "
                   .. "address(es) in memory%s"):format(
                #keys, #F._own.addrs,
                (F._own.capped or 0) > 0
                    and (", %d TRUNCATED at the %d cap"):format(
                        F._own.capped, F._own.MAX_HITS) or ""))
        end
    end
    return F._own.addrs
end

--- Index the found addresses by page.
---
--- With the cap raised, a four-player lobby can have a couple of thousand
--- addresses, and the naive test (every pointer against every address) is
--- 2048 x 2000 comparisons per row. Bucketing by page makes each test a
--- constant handful: a string within +0x400 of a pointer is on that pointer's
--- page or the next one.
function F._dmg_index(addrs)
    -- MEMOISED on the address list's identity and length. `addrs` is
    -- F._own.addrs, which is append-only while the needle queue drains and
    -- frozen for the rest of the run -- but the caller runs on every
    -- background tick, and with `guess_names` on a row keeps `row.player ==
    -- nil` even once it has a label, so "every tick" means "for the whole
    -- session". Rebuilding a couple of thousand buckets each time is pure
    -- waste, and it is waste that scales with the number of players.
    if F._own.page_src == addrs and F._own.page_n == #addrs then
        return F._own.page_idx
    end
    local by_page = {}
    for _, a in ipairs(addrs) do
        local k = a.va >> F._own.PAGE
        local b = by_page[k]
        if not b then b = {}; by_page[k] = b end
        b[#b + 1] = a
    end
    F._own.page_src, F._own.page_n, F._own.page_idx = addrs, #addrs, by_page
    return by_page
end

--- Every roster name this row's own memory reaches, as a set.
---
--- Direct (the string is inside the row's object) or one hop (a pointer in the
--- row's object lands within +0x%x of it). Both are the same test against a
--- known address, so neither costs a string read.
function F._dmg_row_names(row, by_page)
    local found, n = {}, 0
    -- STRUCTURED, not a log string. `_dmg_chain_name` replays a
    -- {base, off, hop} in two reads and names every later row for free, but it
    -- can only do that if this pass hands the chain back as numbers. Recording
    -- the formatted text alone left that replay unreachable — `if chain.base`
    -- was false for every chain this path found — so a board with one unnamed
    -- row paid for a full address-space scan every tick for the rest of the
    -- session. The names came out right; the game hitched for the whole run.
    local function note(name, how, base, off, hop)
        if not found[name] then
            found[name] = { how = how, base = base, off = off, hop = hop }
            n = n + 1
        end
    end
    -- Every address within `span` bytes after `from`, via the page index.
    -- `mk(d)` returns the human text AND the chain that produced it.
    local function near(from, span, mk)
        local first, last = from >> F._own.PAGE, (from + span) >> F._own.PAGE
        for k = first, last do
            local b = by_page[k]
            if b then
                for _, a in ipairs(b) do
                    if a.va >= from and a.va - from <= span then
                        note(a.name, mk(a.va - from))
                    end
                end
            end
        end
    end
    local bases = { { row.key, "ctrl" } }
    local ent = I.read_u64(row.key + 0x08)
    if _ptr_plausible(ent) then bases[#bases + 1] = { ent, "entity" } end
    -- `bi` IS `chain.base`: 1 = the controller (row.key), 2 = the entity at
    -- row.key+0x08 — the same two bases `_dmg_chain_name` re-derives.
    for bi, b in ipairs(bases) do
        local base, tag = b[1], b[2]
        near(base, F._own.WIN, function(d)
            return ("%s+0x%x"):format(tag, d), bi, d, nil
        end)
        for off = 0, F._own.WIN, 8 do
            local p = I.read_u64(base + off)
            if _ptr_plausible(p) then
                near(p, F._own.HOP, function(d)
                    return ("%s+0x%x -> +0x%x"):format(tag, off, d), bi, off, d
                end)
            end
        end
    end
    return found, n
end

--- Name every row that can be named, in one pass. Background thread only.
---
--- The correctness rule is the same one the whole meter is built on: a name is
--- only used when it can belong to exactly ONE row. A string that several rows
--- reach is a shared table (the lobby roster, a UI list), not an owner — and
--- claiming from it would put a real player's damage under someone else's
--- name, which is the bug this all started with.
function F._dmg_probe_owner_fast()
    -- The user's opt-out. Checked before anything else so turning it off costs
    -- exactly one comparison per tick.
    if not _dmg.identity_scan then return false end
    local names, _ = F._dmg_name_set()
    if not names or not I.read_u64 then return false end

    -- CLAIM THE LOCAL ROW FIRST. Steam already told us who this player is, so
    -- their identity is the one thing on the board that never needs a scan.
    --
    -- This claim used to live ONLY inside `F._dmg_probe_owner`, the blind
    -- sweep — which is opt-in and off by default, so in a normal session it
    -- never ran and `row.player` stayed nil on the local row forever. The
    -- `wanted` gate below reads exactly that field, so every session had at
    -- least one row permanently asking to be identified, and the address scan
    -- ran for the whole run hunting for a name already in hand. Solo escaped
    -- only by accident (no lobby means no needles, so `names` is nil above).
    --
    -- It hid from the spec for the same reason it hid in game, from the other
    -- side: `R.damage.sweep_identity()` — what every test drives — routes
    -- through `_dmg_probe_owner`, so the claim always ran under test and never
    -- ran in play. See spec 2f2c, which drives the default path instead.
    local me = F._dmg_me()
    if me then
        for _, row in ipairs(_dmg.order) do
            if row.is_local and not row.player then
                F._dmg_claim(row, names, me, "steam")
            end
        end
    end

    -- Nothing to identify, nothing to scan for. Without this the address
    -- space is walked again on every roster change of a lobby whose rows are
    -- all already named.
    local wanted = false
    for _, row in ipairs(_dmg.order) do
        if not row.player and _ptr_plausible(row.key) then wanted = true break end
    end
    if not wanted then return false end

    -- MORE ROWS THAN PLAYERS means the board has forked, and a forked board is
    -- one the scan cannot answer: two rows belong to the same person, so every
    -- name they both reach is "shared" under the one-owner rule below and
    -- identifies nobody. Scanning on is pure cost, and cost the player feels --
    -- an ally who keeps swapping hero objects (a transform, a respawn) adds a
    -- row each time and each new row re-opens `wanted` above forever. The local
    -- player cannot fork any more (F._dmg_row_for_entity), but nothing on this
    -- build identifies an ALLY, so their forks are not mergeable and this is
    -- the bound instead. Names already claimed are kept; the rest stay lobby
    -- guesses, which is what they would have been anyway.
    -- ⚠ `#members >= 2`, not `> 0`. A roster this client was never fully sent
    -- is the NORMAL case on this build, not a fork: session c236 saw four rows
    -- against one lobby member all run, and today's 2-player log named its ally
    -- through the raknet join with ZERO members parsed. Comparing rows against
    -- a roster that only ever held this player would call every co-op run
    -- forked and stand the name scan down on all of them -- turning a fix for
    -- a stutter into a regression in ally names. Two members is the same
    -- threshold the rest of this file uses before it believes the roster.
    local members = R.lobby.members()
    if #members >= 2 and #_dmg.order > #members then
        if not _dmg.fork_said then
            _dmg.fork_said = true
            R.log(("[rsmm.damage] %d rows for a %d-player lobby — a hero object "
                   .. "swap forked the board, so the identity scan cannot "
                   .. "answer and stands down (rows keep their lobby names)")
                  :format(#_dmg.order, #members))
        end
        return false
    end

    local addrs = F._dmg_find_needles(names)
    if not addrs or #addrs == 0 then return false end

    local by_page = F._dmg_index(addrs)
    local rows, cand = {}, {}
    for _, row in ipairs(_dmg.order) do
        if not row.player and _ptr_plausible(row.key) then
            local found, n = F._dmg_row_names(row, by_page)
            if n > 0 then
                rows[#rows + 1] = row
                cand[row] = found
            end
        end
    end
    if #rows == 0 then return false end

    -- How many rows reach each name. More than one = shared, so it identifies
    -- nobody.
    local owners = {}
    for _, row in ipairs(rows) do
        for name in pairs(cand[row]) do owners[name] = (owners[name] or 0) + 1 end
    end
    local named = false
    for _, row in ipairs(rows) do
        local only, hit, count = nil, nil, 0
        for name, h in pairs(cand[row]) do
            if owners[name] == 1 then only, hit, count = name, h, count + 1 end
        end
        if count == 1 then
            if F._dmg_claim(row, names, only, hit.how) then
                -- The chain, not just its text. This is the whole point of the
                -- scan: one row identified yields the offsets that name every
                -- later row — and every later RUN — in two reads.
                F._dmg_note_chain(hit.base, hit.off, hit.hop, hit.how)
                named = true
            end
        elseif count > 1 then
            R.log(("[rsmm.damage] row %d reaches %d different players' "
                   .. "identities — shared memory, so it names nobody")
                  :format(row.slot, count))
        end
    end
    return named
end

--- Remember a chain that produced a hit, once.
function F._dmg_note_chain(base, off, hop, text)
    for _, ch in ipairs(F._own.chains) do
        if ch.base == base and ch.off == off and ch.hop == hop
           and ch.text == text then return end
    end
    F._own.chains[#F._own.chains + 1] = { base = base, off = off, hop = hop,
                                          text = text }
end

--- The roster as a printable list of NAMES. (Distinct from
--- _dmg_roster_text, which formats a members table the caller already has.)
---
--- Deliberately not the needle set: the sweep searches for peer ids as well as
--- gamertags, and session 7068's dead-end line printed four raw EOS GUIDs
--- alongside the four players, which reads as a corrupt roster.
function F._dmg_roster_names()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return "?" end
    local t, ids = {}, 0
    for _, m in ipairs(members) do
        t[#t + 1] = tostring(m.name)
        if type(m.eos) == "string" and #m.eos > 0 then ids = ids + 1 end
    end
    table.sort(t)
    -- The COUNT of peer ids, because a sweep with no needle to look for and a
    -- sweep that looked and found nothing are the same log line otherwise —
    -- which is exactly why session fb4f could not be explained. Printing the
    -- ids themselves (the first version) made the roster read as corrupt.
    return ("%s — %d of %d carry a peer id"):format(
        table.concat(t, ", "), ids, #members)
end

--- The lobby names as a lookup set, plus the longest one. nil when the roster
--- is still empty (solo, or names have not arrived yet).
function F._dmg_name_set()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    local set, longest = {}, 0
    local function needle(text, m)
        if type(text) ~= "string" or #text == 0 or #text > 64 then return end
        -- Every needle resolves to the member, and every hit is reported under
        -- the member's NAME — a row must never end up labelled with a peer id.
        set[text] = m
        if #text > longest then longest = #text end
    end
    for _, m in ipairs(members) do
        if type(m.name) == "string" and #m.name > 0 then
            needle(m.name, m)
            needle(m.eos, m)
        end
    end
    if longest == 0 then return nil end
    return set, longest
end

--- Does a known player name start at `va`? Returns the name, or nil.
---
--- One `read_cstr` per address, not one per candidate name: the read stops at
--- the first NUL, so a stored name comes back whole and the set does the rest.
--- That keeps a 70k-probe sweep to 70k reads rather than 70k x roster size.
function F._dmg_name_at(va, names, longest)
    if not I.read_cstr or not _ptr_plausible(va) then return nil end
    local s = I.read_cstr(va, longest + 1)
    -- Return the member's NAME, not the string that matched: the needle may
    -- have been their peer id.
    if type(s) == "string" and names[s] then return names[s].name end
    return nil
end

--- Read the adopted chain on `row`. Two reads once the chain is known.
function F._dmg_chain_name(row, chain, names, longest)
    local base = chain.base == 2 and I.read_u64(row.key + 0x08) or row.key
    if not _ptr_plausible(base) then return nil end
    if not chain.hop then return F._dmg_name_at(base + chain.off, names, longest) end
    local p = I.read_u64(base + chain.off)
    if not _ptr_plausible(p) then return nil end
    return F._dmg_name_at(p + chain.hop, names, longest)
end

--- Would some OTHER unnamed row resolve this same chain to this same name?
---
--- The blind sweep walks ONE row at a time, so on its own it has no way to
--- tell an owner from a shared table — it claimed whatever it reached first,
--- and `_dmg_claim`'s duplicate refusal then only stopped the SECOND row, long
--- after the first had taken a name that may not be its own. That is the same
--- failure `_dmg_probe_owner_fast`'s one-owner rule and the chain replay's both
--- refuse, and the sweep undercut both of them by running after them.
---
--- Costs two pointer reads per other row, and only at the instant of a claim.
function F._dmg_chain_shared(row, chain, name, names, longest, me)
    for _, other in ipairs(_dmg.order) do
        if other ~= row and not other.player and _ptr_plausible(other.key) then
            -- The local row is never a rival claimant for somebody else's name:
            -- Steam already said who is at this keyboard, so a gamertag inside
            -- YOUR object (session 6136) must not make the real owner's name
            -- look shared and strand that player on a placeholder.
            local rival = not (other.is_local and type(me) == "string"
                               and me ~= "" and name ~= me)
            if rival
               and F._dmg_chain_name(other, chain, names, longest) == name then
                return true
            end
        end
    end
    return false
end

--- Bind `row` to the lobby member called `name`.
---
--- Refuses a name another row already holds. Two rows resolving to one player
--- means the chain is reading something shared (a lobby array, the local
--- player's own copy), and merging two players is the one failure that DELETES
--- damage from the board — always fail toward the placeholder.
--- Who is at this keyboard, remembered.
---
--- `R.player.name` is a Steam call and it can come back empty on a background
--- tick even when it answered a moment earlier on the main thread. Session
--- d536 is that window: the local row's LABEL was resolved at boarding (Steam
--- fine), then every sweep tick asked again, got nothing, and so skipped the
--- steam claim -- which left row 1 unclaimed and the duplicate guard with
--- nothing to compare against. An ally then claimed "Ovilli" off a global the
--- engine hangs on every entity, and the board showed two of them.
---
--- So the answer is cached the first time anyone gets it, and the LOCAL ROW's
--- own label is the fallback: it was resolved from Steam already, and it is
--- the one name on the board that was never inferred.
function F._dmg_me()
    if _dmg.me then return _dmg.me end
    local ok, nm = pcall(R.player.name)
    if ok and type(nm) == "string" and nm ~= "" and nm ~= "You" then
        _dmg.me = nm
        return nm
    end
    for _, row in ipairs(_dmg.order) do
        if row.is_local then
            local lbl = row.player or row.label
            if type(lbl) == "string" and lbl ~= "" and lbl ~= "You"
               and not lbl:match("^Player %d+$") then
                _dmg.me = lbl
                return lbl
            end
        end
    end
    return nil
end

function F._dmg_claim(row, names, name, how)
    local m = names[name]
    -- Steam is authoritative for the LOCAL row, and does not depend on the
    -- roster sweep having seen that player. Session d536 is the roster WITHOUT
    -- the local member in it, so `names[me]` was nil, the steam claim never
    -- ran, `row.player` stayed unset on row 1 -- and the duplicate guard below,
    -- which is what stops a second row taking a name, had nothing to compare
    -- against. Two rows finished the run labelled "Ovilli".
    if not m and not (row.is_local and how == "steam") then return false end
    -- The local row is the ONE row whose name is not an inference: Steam told
    -- us. Session 6136 renamed it anyway, off a stack frame masquerading as a
    -- member object. The visible label survived (the local row keeps its Steam
    -- name below), but `row.player` did not — and that CONSUMED a real
    -- player's name: row 3 was refused "Timattttttt" twice as a duplicate and
    -- finished the run as "Player 3". A wrong claim here costs two rows.
    if row.is_local then
        local me = F._dmg_me()
        if me and me ~= name then
            R.log(("[rsmm.damage] refusing row %d -> %q (%s): that row is this "
                   .. "machine's player, and Steam calls them %q")
                  :format(row.slot, name, how, me))
            return false
        end
    end
    -- AND THE MIRROR: an ally may never be named after this machine's player.
    -- There is exactly one local player and Steam names them before any sweep
    -- runs, so a NON-local row resolving to that name is proof the chain is
    -- shared -- the local player's name is reachable from a global the engine
    -- hangs off every entity -- not proof of ownership. Session d536 claimed
    -- `entity+0xcc8 -> +0x39b` for an ally that way and the board showed two
    -- "Ovilli" rows while the ally's real name, InsertCoin2Start, vanished.
    --
    -- This does not depend on the local row having been claimed first, which
    -- is the whole point: the ordering is what failed.
    if not row.is_local then
        local me = F._dmg_me()
        if me and me == name then
            if not _dmg.self_claim_said then
                _dmg.self_claim_said = true
                R.log(("[rsmm.damage] refusing row %d -> %q (%s): that is this "
                       .. "machine's player and this row is not them, so the "
                       .. "chain is shared memory, not ownership")
                      :format(row.slot, name, how))
            end
            return false
        end
    end
    for _, other in ipairs(_dmg.order) do
        if other ~= row and other.player == name then
            R.log(("[rsmm.damage] refusing row %d -> %q (%s): row %d already "
                   .. "holds that name"):format(row.slot, name, how, other.slot))
            return false
        end
    end
    row.player = name
    if m and m.hero_id and not row.hero_id then
        row.hero_id = m.hero_id
        _dmg.by_hero[m.hero_id] = row
    end
    -- The local row keeps the name Steam gave it; they are the same person and
    -- the Steam persona is the one the player recognises as themselves.
    if not row.is_local then
        row.label = name
        row.label_guess = false
    end
    F._own.found = F._own.found + 1
    -- The sweep budget is there to stop a scan that never answers. This one
    -- just answered, so clear it: the rows still unnamed have earned the next
    -- pass, and a roster previously stood down on is worth re-arming.
    F._own.tries, F._own.gave_up = {}, {}
    R.log(("[rsmm.damage] row %d IS %q (%s)%s"):format(
        row.slot, name, how, row.is_local and " [local]" or ""))
    return true
end

--- Advance the owner-name sweep by one budget's worth. Background thread only.
function F._dmg_probe_owner()
    local names, longest = F._dmg_name_set()
    if not names or not I.read_cstr or not I.read_u64 then return end

    -- The local row is not a mystery: Steam named it before the run started.
    -- Leaving it unclaimed made every sweep spend a quarter of its budget, and
    -- four retries, re-deriving a fact already in hand — session 314f swept
    -- row 1 three times for nothing.
    -- No `names[me]` gate. The roster is a SWEEP result and it drops members
    -- that stop being re-parsed, so the local player is routinely absent from
    -- it (session d536, and the two "not in this lobby - dropped" lines in
    -- a14f). Gating the local claim on the roster meant the one name the meter
    -- knows for certain went unclaimed, which in turn disarmed the duplicate
    -- guard in `_dmg_claim`. Steam is the source here, not the roster.
    local me = F._dmg_me()
    if me then
        for _, row in ipairs(_dmg.order) do
            if row.is_local and not row.player then
                F._dmg_claim(row, names, me, "steam")
            end
        end
    end

    -- CHAINS FIRST. A chain is two pointer reads and a string compare; the
    -- scan below is a native walk of the WHOLE address space, and the lobby
    -- sweep above already documents why that is felt even from the background
    -- thread — ReadProcessMemory at that volume saturates memory bandwidth
    -- and the process VM lock, which stalls the game's threads too. Scanning
    -- first meant the cheap answer was only ever consulted after the expensive
    -- one had already been paid for, on every tick with an unnamed row.
    --
    -- ALL of them are tried, not just the last — session 7068 named two rows
    -- through two DIFFERENT chains (`entity+0x678 -> +0x2d0` and
    -- `entity+0xad8 -> +0x1c0`), so a single remembered chain would have been
    -- the wrong one for half the board.
    -- Resolve every chain against every unnamed row FIRST, claim second, under
    -- the same one-owner rule the scan uses. A chain is a GUESS about where a
    -- name lives, and two of them are now SEEDED from an older session rather
    -- than learned on this board — so if two rows resolve a chain to the SAME
    -- name, that chain is reading something shared (the lobby roster, a UI
    -- list) and it identifies nobody. Claiming row-by-row in slot order, which
    -- is what this loop used to do, would hand that name to whichever row came
    -- first: a real player's damage under another player's name, the one
    -- failure the whole meter is built to refuse.
    local cand, hits = {}, 0
    for _, chain in ipairs(F._own.chains) do
        if chain.base then
            for _, row in ipairs(_dmg.order) do
                if not row.player and _ptr_plausible(row.key) then
                    local nm = F._dmg_chain_name(row, chain, names, longest)
                    if nm then
                        local c = cand[row]
                        if not c then c = {}; cand[row] = c end
                        if not c[nm] then c[nm] = chain; hits = hits + 1 end
                    end
                end
            end
        end
    end
    -- The local row is not a claimant for anybody else's name, so it must not
    -- count as an OWNER of one either. Session 6136's gamertag sat inside the
    -- local player's own object; `_dmg_claim` already refuses to rename row 1
    -- off it, but leaving it in the tally makes the real owner's name look
    -- shared, and the player who actually owns it is then stranded on a
    -- placeholder — which is the second half of that same bug.
    if hits > 0 and me then
        for row, c in pairs(cand) do
            if row.is_local then
                for nm in pairs(c) do
                    if nm ~= me then c[nm] = nil; hits = hits - 1 end
                end
            end
        end
    end
    if hits > 0 then
        local owners = {}
        for _, c in pairs(cand) do
            for nm in pairs(c) do owners[nm] = (owners[nm] or 0) + 1 end
        end
        -- Over `_dmg.order`, not `pairs(cand)`: claim order must not depend on
        -- table iteration order, or which row wins an ambiguity changes between
        -- runs and the board stops being reproducible.
        for _, row in ipairs(_dmg.order) do
            local c = cand[row]
            if c then
                local only, chain, n = nil, nil, 0
                for nm, ch in pairs(c) do
                    if owners[nm] == 1 then only, chain, n = nm, ch, n + 1 end
                end
                if n == 1 then
                    -- Name the chain that claimed the row, so the log tells a
                    -- seeded offset that still works apart from one a scan had
                    -- to rediscover.
                    F._dmg_claim(row, names, only,
                                 "chain " .. (chain.text or "?"))
                elseif n > 1 then
                    R.log(("[rsmm.damage] row %d resolves %d different players "
                           .. "through its chains — ambiguous, so it names "
                           .. "nobody"):format(row.slot, n))
                end
            end
        end
    end

    -- Only now ask the process where the names ARE, and check which row owns
    -- each. Costs one native scan per player and 2048 pointer reads per row.
    -- `_dmg_probe_owner_fast` gates itself on there still being an unnamed
    -- row, so a board the chains finished never reaches this at all. The blind
    -- sweep below stays as the fallback for a loader without `mem_find`.
    if F._dmg_probe_owner_fast() then return end

    local c = F._own.cursor
    if not c or c.row.player or c.row.own_done or c.row.dropped then
        -- Pick the next row that has neither an identity nor a completed sweep.
        c = nil
        for _, row in ipairs(_dmg.order) do
            if not row.player and _ptr_plausible(row.key)
               and (not row.own_done
                    or (row.own_retry_at and F._dmg_now() >= row.own_retry_at)) then
                row.own_done, row.own_retry_at = false, nil
                c = { row = row, base = 1, off = 0, hop = nil }
                break
            end
        end
        F._own.cursor = c
        if not c then return end
    end

    local row = c.row
    local budget = F._own.BUDGET
    while budget > 0 do
        local base = c.base == 2 and I.read_u64(row.key + 0x08) or row.key
        if _ptr_plausible(base) then
            if c.hop == nil then
                -- Direct: the name lives in the object itself (an inline
                -- std::string, a fixed char buffer).
                local nm = F._dmg_name_at(base + c.off, names, longest)
                budget = budget - 1
                if nm then
                    local ch = { base = c.base, off = c.off, hop = nil }
                    -- Record it either way: a shared chain is still a fact
                    -- about this build, and the cross-row rule above is where
                    -- it gets judged.
                    F._dmg_note_chain(c.base, c.off, nil)
                    if F._dmg_chain_shared(row, ch, nm, names, longest, me) then
                        R.log(("[rsmm.damage] row %d reaches %q at %s, but so "
                               .. "does another unnamed row — shared memory, "
                               .. "so it names nobody"):format(row.slot, nm,
                            ("%s+0x%x"):format(
                                c.base == 2 and "entity" or "ctrl", c.off)))
                    else
                        F._dmg_claim(row, names, nm,
                            ("%s+0x%x"):format(c.base == 2 and "entity" or "ctrl", c.off))
                    end
                    F._own.cursor = nil
                    return
                end
            else
                -- One hop: the field is a pointer and the name is behind it —
                -- a `char*`, a `std::string*`, or the heap buffer of an MSVC
                -- std::string (whose data pointer sits at +0x8, which this
                -- reaches as hop 0 of that offset).
                local p = I.read_u64(base + c.off)
                if _ptr_plausible(p) then
                    local nm = F._dmg_name_at(p + c.hop, names, longest)
                    budget = budget - 1
                    if nm then
                        local ch = { base = c.base, off = c.off, hop = c.hop }
                        F._dmg_note_chain(c.base, c.off, c.hop)
                        local how = ("%s+0x%x -> +0x%x"):format(
                            c.base == 2 and "entity" or "ctrl", c.off, c.hop)
                        if F._dmg_chain_shared(row, ch, nm, names, longest, me) then
                            R.log(("[rsmm.damage] row %d reaches %q at %s, but "
                                   .. "so does another unnamed row — shared "
                                   .. "memory, so it names nobody")
                                  :format(row.slot, nm, how))
                        else
                            F._dmg_claim(row, names, nm, how)
                        end
                        F._own.cursor = nil
                        return
                    end
                else
                    c.hop = F._own.HOP        -- nothing to walk; skip the hops
                    budget = budget - 1
                end
            end
        else
            budget = budget - 1
            c.off = F._own.WIN                    -- unreadable base: end this pass
        end

        -- Cursor advance: hops, then offsets, then base, then the hop stage.
        if c.hop ~= nil then
            c.hop = c.hop + F._own.STRIDE
            if c.hop > F._own.HOP then c.hop = 0; c.off = c.off + F._own.STRIDE end
        else
            c.off = c.off + F._own.STRIDE
        end
        if c.off > F._own.WIN then
            c.off = 0
            if c.base == 1 then
                c.base = 2
            elseif c.hop == nil then
                c.base, c.hop = 1, 0       -- direct pass done; walk pointers
            else
                -- Both passes done on both bases: this controller does not
                -- reach any lobby name. Say so ONCE, with everything needed to
                -- take it further (the next step is RE, not a wider sweep).
                row.own_done = true
                row.own_tries = (row.own_tries or 0) + 1
                F._own.swept = F._own.swept + 1
                F._own.cursor = nil
                -- RETRY, do not retire. A row is swept the moment it deals its
                -- first damage, and the fields that identify it are not
                -- necessarily populated yet — session 7068 named rows 1 and 2
                -- and dead-ended rows 3 and 4, which had boarded seconds
                -- earlier. Retiring a row after one pass makes that permanent
                -- for the whole run.
                -- ⚠ UNTESTED BRANCH. Reaching it in the spec needs a full
                -- ~264k-probe pass to COMPLETE before the fixture populates
                -- the row, and a shorter pass simply continues instead. The
                -- behaviour it guards (a row is not retired after one dead
                -- end) is covered; the countdown itself is not.
                if row.own_tries < F._own.TRIES then
                    row.own_retry_at = F._dmg_now() + F._own.RETRY_AFTER
                end
                R.log(("[rsmm.damage] owner-name sweep: row %d (%s, ctrl=0x%x) "
                       .. "holds no lobby id within +0x%x, direct or one hop "
                       .. "(attempt %d of %d) — roster was {%s}"):format(
                    row.slot, row.label, row.key, F._own.WIN,
                    row.own_tries, F._own.TRIES, F._dmg_roster_names()))
                return
            end
        end
    end
end

--- Advance the identity sweep by ONE slice.
---
--- The meter already drives this from its background tick; this exists so a
--- diagnostic ("who is row 3?") or a test can push it along without waiting.
--- BACKGROUND THREAD ONLY — it walks thousands of addresses.
function R.damage.sweep_identity()
    -- Re-check FIRST: a withdrawal clears `done`, so the probe below can start
    -- looking again in the same call, with whatever rows have since boarded.
    F._dmg_recheck_hero_field()
    F._dmg_probe_hero_field(true)     -- byte and word widths too
    F._dmg_backfill_ids()
    return F._dmg_probe_owner()
end

--- What the identity sweep has found. For diagnostics and the spec.
--- Mark every row as identified. Spec-only: it makes "there is nothing left
--- to look for" reachable without faking a memory layout for each row.
function R.damage._name_all()
    for _, row in ipairs(_dmg.order) do row.player = row.player or row.label end
end

function R.damage.identity()
    -- `chain` is the FIRST chain this board learned. Nothing is pre-seeded (see
    -- F._own.chains), so a non-nil value here means the scan actually ran and
    -- found something on this build — which is the number worth reading.
    return { chain = F._own.chains[1], chains = F._own.chains,
             found = F._own.found, swept = F._own.swept,
             hero_id_offset = HERO_ID_PROBE.off }
end

function F._dmg_relabel()
    local ok, allies = pcall(R.lobby.allies)
    if not ok or type(allies) ~= "table" or #allies == 0 then return end
    -- Name by HERO when the row's identity is known: each lobby member record
    -- carries its RequestedHero, so this is an exact join.
    --
    -- There is NO positional fallback. `allies[rank]` — the old fallback — ranks
    -- rows by the order allies first dealt damage, which is unrelated to the
    -- lobby's order, so from three players up it printed a real name against
    -- another player's damage. What remains is ELIMINATION: once every row that
    -- has a hero id is named, a single unnamed ally row facing a single unclaimed
    -- ally name can only be that player. Everything else keeps its "Player N"
    -- placeholder until the hero-id probe lands.
    -- HERO IDS ARE NOT UNIQUE. Session 8f36 (2026-08-20) is a four-player
    -- lobby with TWO players on hero 10: "PigGoesQuack(hero 10)" and
    -- "Ovilli(hero 10)". Ravenswatch does not force distinct heroes, so the
    -- whole hero-id join is only ever valid for the ids that happen to be
    -- unique in THIS lobby -- and a duplicate id silently kept the last writer,
    -- which is a real player's damage under another real player's name.
    --
    -- Any id that more than one member claims is dropped outright. The rows
    -- that would have been named from it keep their placeholders, which is the
    -- correct answer: the roster genuinely cannot tell those two apart.
    local by_hero, okm, members = {}, pcall(R.lobby.members)
    if okm then
        local list, dup = members, {}
        if type(list) == "table" then
            for _, m in ipairs(list) do
                if m.hero_id and m.name then
                    if by_hero[m.hero_id] and by_hero[m.hero_id] ~= m.name then
                        dup[m.hero_id] = true
                    end
                    by_hero[m.hero_id] = m.name
                end
            end
            for id in pairs(dup) do
                by_hero[id] = nil
                if not _dmg.dup_hero_said then
                    _dmg.dup_hero_said = true
                    R.log(("[rsmm.damage] hero %d is claimed by more than one "
                           .. "player this run %s the hero id cannot identify "
                           .. "either of them, so it names neither")
                          :format(id, "\u{2014}"))
                end
            end
        end
    end
    -- Pass 1: the exact joins, plus the names they account for. `row.player` is
    -- the owner-name sweep's answer and outranks the hero id — it read the
    -- player's own gamertag out of the player's own object.
    local claimed, ally_rows, pending = {}, {}, {}
    for _, row in ipairs(_dmg.order) do
        if not row.is_local then
            local exact = row.player or (row.hero_id and by_hero[row.hero_id]) or nil
            local entry = { row = row, name = exact, guess = false }
            if exact then claimed[exact] = true else pending[#pending + 1] = entry end
            ally_rows[#ally_rows + 1] = entry
        end
    end
    -- Pass 2: elimination. Guarded on `#ally_rows <= #allies` because a row that
    -- forked at a chapter change is a duplicate player, not a new one, and would
    -- otherwise swallow the name of someone who has not dealt damage yet.
    local unclaimed = {}
    for _, nm in ipairs(allies) do
        if not claimed[nm] then unclaimed[#unclaimed + 1] = nm end
    end
    -- STABLE ORDER. `allies` follows R.lobby.members(), which is sorted by
    -- PARSE RECENCY -- and the engine re-parses every member several times a
    -- second, so that order flips constantly. Session a34f logged 192 renames
    -- in one run, `EvilMurray, fruktik_kiwi` and `fruktik_kiwi, EvilMurray`
    -- alternating once a second, which swapped the two players' names across
    -- their damage totals for the whole match. A guess may be wrong; it must
    -- not be wrong DIFFERENTLY every second.
    table.sort(unclaimed)
    if #pending == 1 and #ally_rows <= #allies and #unclaimed == 1 then
        pending[1].name = unclaimed[1]
        pending[1].guess = true              -- exact by count, not by hero id
    elseif _dmg.guess_names then
        -- Hands the leftover names to the leftover rows in JOIN ORDER, which is
        -- a guess: every row it touches is flagged `label_guess` and a UI that
        -- shows the name must show the flag (the board prints a trailing "?").
        --
        -- ⚠ This branch was made opt-in on 2026-08-20 because the silent
        -- version put a real name on another player's damage. Turning it OFF BY
        -- DEFAULT was the wrong half of that fix: the lobby hook reliably learns
        -- all four names (sessions 6136/5636/0a36/7068/fb4f/314f/a84f/174f/304f/
        -- 8f36/c536/014f/e736/2c36/9e4f all logged a full four-name roster), but
        -- no join on this build can say which row is which -- the hero id is
        -- dead here because players pick duplicate heroes, and the owner-GUID
        -- key has no member bridge yet. So the default produced a board that
        -- KNEW every name and printed "Player 1..4" anyway. A marked guess
        -- beats that; an unmarked one does not. `player_1..player_4` in the
        -- config remain the way to get names that are never guesses.
        -- STICKY. A row keeps the guess it was first given for as long as
        -- that name is still in the lobby, so the board settles instead of
        -- re-dealing the same names on every tick. Cleared per epoch with the
        -- rest of the board.
        _dmg.guessed = _dmg.guessed or {}
        local live, taken = {}, {}
        for _, nm in ipairs(allies) do live[nm] = true end
        for _, entry in ipairs(pending) do
            local prev = _dmg.guessed[entry.row.slot]
            if prev and live[prev] and not claimed[prev] and not taken[prev] then
                entry.name, entry.guess, taken[prev] = prev, true, true
            end
        end
        for _, entry in ipairs(pending) do
            if not entry.name then
                for _, nm in ipairs(unclaimed) do
                    if not taken[nm] then
                        entry.name, entry.guess, taken[nm] = nm, true, true
                        _dmg.guessed[entry.row.slot] = nm
                        break
                    end
                end
            end
        end
    end
    local changed = 0
    for _, entry in ipairs(ally_rows) do
        local row = entry.row
        local nm = _dmg.names[row.slot] or entry.name
        if nm and row.label ~= nm then
            row.label = nm
            row.label_guess = _dmg.names[row.slot] == nil and entry.guess
            changed = changed + 1
        end
    end
    if changed > 0 then
        R.log(("[rsmm.damage] lobby roster: %s (%d row(s) renamed)")
              :format(table.concat(allies, ", "), changed))
    end
end

--- Apply the lobby roster to the board's ally rows.
---
--- Public because the roster resolves asynchronously: a UI that wants names
--- the moment they land can call this instead of waiting for the next tick.
--- Cheap — no scan (see R.lobby.members).
function R.damage.relabel() return F._dmg_relabel() end

--- Resolve the lobby roster on the BACKGROUND thread, then re-label.
---
--- Never call the scan from a gameplay path: it walks the address space and
--- costs seconds. This is the only place allowed to trigger it.
function F._dmg_lobby_refresh()
    if not (R.schedule and R.schedule.every) then return end
    -- One resolver for the whole process, not one per mod state.
    if I.shared_get and I.shared_set then
        local ok, n = pcall(I.shared_get, LOBBY_REFRESH_SLOT)
        if ok and type(n) == "number" and n > 0 then return end
        pcall(I.shared_set, LOBBY_REFRESH_SLOT, 1)
    end
    -- DEMAND-DRIVEN. The scan is only worth its ~4 s when there is actually a
    -- row it could name, which makes the common cases free: a solo run never
    -- scans at all, and a co-op run stops scanning the moment every ally has a
    -- real name.
    --
    -- The previous shape — scan on a 30 s timer, then refuse to rescan for
    -- 120 s — managed to be both wasteful and too slow: its one scan landed
    -- during loading, before anyone had joined, found nothing, and the retry
    -- was still 6 s away when session 1e36 ended. Ticking often but scanning
    -- rarely is the right way round.
    -- One SLICE per tick. `refresh` walks a bounded number of bytes and
    -- returns; the sweep spans many ticks, so nothing ever blocks long enough
    -- to be felt. The demand gate still applies, so a solo run does no work at
    -- all beyond the (free) relabel.
    R.schedule.every(1, function()
        -- METERING OFF MEANS OFF. The detours stay installed (see
        -- R.damage.disable) and cost an early return, but this tick is the
        -- expensive half of the meter -- address-space sweeps, the hero-field
        -- probe, the per-row netid pass -- and it used to keep running for the
        -- rest of the process after `disable()`, because nothing here ever
        -- read `_dmg.on` and the timer is never cancelled. A player who turned
        -- the meter off still paid for it, which is exactly what a user
        -- reported on 2026-08-24 ("background processes still running with the
        -- mod off"). Cancelling the timer instead would be wrong: `enable()`
        -- is idempotent and would not re-arm it.
        --
        -- One consequence, deliberate: the tick is claimed by ONE lua_State
        -- per process (LOBBY_REFRESH_SLOT), so if that state stops metering,
        -- no other state's board gets relabelled either. Releasing the slot
        -- here would let a second state arm its own timer, and then a
        -- re-enable would leave TWO running -- doubling the very scans this
        -- gate exists to stop. One mod owns R.damage in practice, so the
        -- cheaper failure is the right one.
        if not _dmg.on then return end
        local ok, err = pcall(function()
            -- Cheap every time: re-read the known blocks and apply names.
            F._dmg_relabel()
            -- Before the probe, not after: a withdrawal has to clear `done` so
            -- the same tick can start looking again with the bigger sample.
            F._dmg_label_hint()
            F._dmg_recheck_hero_field()
            F._dmg_probe_hero_field(true)     -- background: byte and word too
            F._dmg_backfill_ids()
            -- Bounded and one-shot per row: 0x400 bytes of the row's net
            -- component plus 0x120 at each pointer it holds, looking for a
            -- 32-hex-character session id. Once a locator is adopted this is
            -- two reads per unnamed row. Not gated behind `identity_hunt`,
            -- because unlike the name sweep it cannot answer by coincidence.
            F._dmg_netid_pass()
            -- REAL NAMES, and NOT part of `identity_hunt`.
            --
            -- This asks the process where each player's peer id physically is
            -- (one native `mem_find` per player, ONE needle per tick) and then
            -- checks which row reaches a copy of it, under the one-owner rule.
            -- It is the path that actually produced names, and it is already
            -- rate-limited -- the back-to-back scans that caused session a84f's
            -- stutter were fixed inside it, by spreading the needles.
            --
            -- ⚠ It used to sit INSIDE `F._dmg_probe_owner`, so switching
            -- `identity_hunt` off to stop the blind sweep's stutter switched
            -- this off too and the board went back to "Player 2". That was a
            -- regression, not a decision: the expensive part is the sweep
            -- below, not this.
            --
            -- Self-gating: with no unnamed row it returns immediately, so a
            -- named board and a solo run both cost nothing.
            F._dmg_probe_owner_fast()
            -- The BLIND cursor sweep: hundreds of thousands of probes at every
            -- offset of every row. That is the stutter, and it answered at a
            -- different offset every time it "worked", so it stays opt-in.
            if _dmg.identity_hunt then F._dmg_probe_owner() end
            if F._dmg_wants_lobby() then
                local before = #R.lobby.members()
                local members = R.lobby.refresh()
                if #members ~= before then
                    R.log(("[rsmm.damage] lobby scan: %d member(s)%s")
                          :format(#members, #members > 0
                              and (" — " .. F._dmg_roster_text(members)) or ""))
                end
                F._dmg_relabel()
            end
        end)
        if not ok then
            R.log("[rsmm.damage] lobby refresh failed: " .. tostring(err))
        end
    end)
end

--- "Alice (Aladdin), Bob (Scarlet)" — the roster as one log line.
function F._dmg_roster_text(members)
    local parts = {}
    for _, m in ipairs(members) do
        -- Prefer the hero NAME over the raw id: "Yume (Juliet)" is something a
        -- player can match against what they saw on screen; "Yume (hero 4)" is
        -- not. Display only -- see R.lobby.HERO_NAMES.
        local hero = m.hero or R.lobby.hero_name(m.hero_id)
        parts[#parts + 1] = hero and (m.name .. " (" .. hero .. ")") or m.name
    end
    return table.concat(parts, ", ")
end

--- Record a member's session id without a live lobby. Spec and diagnostics
--- only: in game this comes from the attribute-parser detour, which recovers
--- the member as `blob - 0x28`.
function R.lobby._note_session(name, sid)
    for _, e in ipairs(LOBBY_HOOK.order) do
        if e.name == name then e.session = sid; return true end
    end
    return false
end

--- Record the member OBJECT the hook saw for `name`, and snapshot the pointers
--- it holds (diagnostics and the spec). The hook does both on every parse --
--- and the SNAPSHOT is the part that matters: the member is destroyed after
--- the call, so nothing may read it later.
function R.lobby._note_member(name, addr)
    for _, e in ipairs(LOBBY_HOOK.order) do
        if e.name == name then
            e.member = addr
            if _ptr_plausible(addr) and I.read_u64 then
                local ptrs, n, words = {}, 0, {}
                for off = 0, F._netid.MEMWIN - 8, 8 do
                    local v = I.read_u64(addr + off)
                    if type(v) == "number" and v ~= 0 and v ~= -1 then words[v] = true end
                    if _ptr_plausible(v) and not ptrs[v] then
                        ptrs[v] = true; n = n + 1
                    end
                end
                if n > 0 then e.ptrs, e.nptrs = ptrs, n end
                if next(words) then e.words = words end
            end
            return true
        end
    end
    return false
end

--- Expose the session matcher for the spec and for diagnosing a build where
--- the representations do not line up.
function R.damage._session_matches(n, text)
    return F._dmg_session_matches(n, text)
end

--- Drive the session join directly. Spec and diagnostics only; in game the
--- gameplay bus feeds it (see the R.on("*") handler below).
function R.damage._session_join(entity, session)
    return F._dmg_note_session(entity, session)
end

--- Drive the cheap identity paths by hand, exactly as the 1 Hz tick does
--- (the spec). Does NOT include the blind sweep, which is opt-in.
function R.damage._identity_tick()
    F._dmg_relabel()
    F._dmg_backfill_ids()
    F._dmg_netid_pass()
    return F._dmg_probe_owner_fast()
end

--- Record a member's peer id (the spec); the lobby hook does this from the
--- parsed attribute blob.
function R.lobby._note_eos(name, id)
    for _, e in ipairs(LOBBY_HOOK.order) do
        if e.name == name then e.eos = id; return true end
    end
    return false
end

--- Drive the label hint by hand (the spec); the meter's tick calls it.
function R.damage._label_hint()
    return F._dmg_label_hint()
end

--- Is a string well-formed UTF-8? (test/diagnostic seam for F._utf8_ok.)
function R.damage._utf8_ok(t) return F._utf8_ok(t) end

--- Drive one net-id pass by hand (diagnostics and the spec); the meter's own
--- tick already calls this once a second.
--- The engine's peer table as the join sees it (test/diagnostic seam).
function R.damage._peer_join() return F._dmg_peer_join() end

--- The connection-record join (test/diagnostic seam).
function R.damage._conn_join() return F._dmg_conn_join() end

--- The RakNet remote-system join (test/diagnostic seam).
function R.damage._rak_join() return F._dmg_rak_join() end

--- The RakNet remote-system table as the join reads it (diagnostic seam).
function R.damage._rak_systems() return F._dmg_rak_systems() end

function R.damage._netid_pass()
    return F._dmg_netid_pass()
end

--- The adopted net-id locator, or a table with `off == nil` while discovery is
--- still running. Read-only: a caller must not be able to adopt one by hand.
function R.damage._netid()
    local path
    if F._netid.path then
        path = {}
        for i, v in ipairs(F._netid.path) do path[i] = v end
    end
    -- A COPY of the path: the adopted locator is the one thing a caller must
    -- not be able to edit from outside.
    return { off = F._netid.off, path = path, kind = F._netid.kind }
end

--- Does the int64 session id `n` and the member's session STRING refer to the
--- same session? Exact match against every plausible text form, never a
--- "close enough". The point of this whole path is that it cannot invent an
--- answer; a fuzzy compare would hand that property straight back.
function F._dmg_session_forms(n)
    local hex = ("%016x"):format(n)
    -- Byte-reversed, for a little-endian half of a GUID printed big-endian.
    local swapped = hex:gsub("(%x%x)", function(b) return b end)
    local rev = {}
    for i = 15, 1, -2 do rev[#rev + 1] = hex:sub(i, i + 1) end
    swapped = table.concat(rev)
    return { ("%d"):format(n), ("%x"):format(n), ("%X"):format(n),
             ("0x%x"):format(n), ("0x%X"):format(n),
             hex, hex:upper(), swapped, swapped:upper() }
end

--- Does the member's session id `text` contain this int64 as one of its halves?
---
--- The lobby's session id is a 128-bit GUID STRING, not an int64: session 8f36
--- logged "Ovilli" as "31b1a3aef8ce46e9a4d76be3c7526757", 32 hex characters.
--- The netcode path deals in 8 bytes (NamedEvent_NetSend stores a single
--- qword at ev+0x38), so if the two are the same identity at all, the qword
--- can only be one HALF of that GUID. Both halves and both byte orders are
--- tried; anything else would be a guess, and a guess is what this design
--- exists to refuse.
function F._dmg_session_halves(n, text)
    if type(text) ~= "string" or #text ~= 32 or text:find("[^0-9a-fA-F]") then
        return false
    end
    local lo, hi = text:sub(1, 16):lower(), text:sub(17, 32):lower()
    for _, form in ipairs(F._dmg_session_forms(n)) do
        local f = form:lower()
        if #f == 16 and (f == lo or f == hi) then return true end
    end
    return false
end

function F._dmg_session_matches(n, text)
    if type(n) ~= "number" or type(text) ~= "string" then return false end
    for _, form in ipairs(F._dmg_session_forms(n)) do
        if form == text then return true end
    end
    return F._dmg_session_halves(n, text)
end

--- The lobby member whose session id is `n`, or nil.
---
--- Requires EXACTLY ONE match. Two members answering to one session id means
--- the representation guess is wrong (e.g. a truncated form colliding), and a
--- collision must name nobody -- same rule the rest of the meter runs on.
function F._dmg_session_member(n)
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    local hit, count = nil, 0
    for _, m in ipairs(members) do
        if type(m.session) == "string" and F._dmg_session_matches(n, m.session) then
            hit, count = m, count + 1
        end
    end
    if count == 1 then return hit end
    return nil
end

-- net-component peer id ----------------------------------------------------
--
-- The join the gameplay bus could not give us.
--
-- Sessions c536 and e736 settled ev+0x38: every event the bus dispatched in
-- either run carried the SAME vftable (0xf05aa8), i.e. the base
-- oCGameNamedEvent, and on the base class +0x38 is not a peer. The values it
-- held are handles (0x8146_00xx_00000004, 0x8075_00xx_000y_0004) and in one
-- case a raw code address (0x1463b00a2). So no gameplay event on this build
-- carries a sender, and F._dmg_note_session can never fire from it.
--
-- What DOES have to know the owner is the entity's NET COMPONENT: replication
-- routes by peer, so whatever replicates a remote hero must name the machine
-- driving it. The component is a separate allocation reached through the
-- component map, so the entity+0x2000 sweep never looked at it.
--
-- The needle is the lobby member's session id -- 32 hex characters, the same
-- string LobbyMembers_Local compares to find "everyone but me". A 128-bit
-- value matching by accident is not a risk worth modelling, and that is what
-- makes this different in kind from sweeping memory for a display name.
F._netid = {
    WIN    = 0x800,    -- bytes of the net component to inspect
    HOPWIN = 0x180,    -- bytes at each pointer the component holds
    off    = nil,      -- adopted offset, once a row's own session proves one
    path   = nil,      -- pointer path from the component, or nil for a direct read
    kind   = nil,      -- "string" | "qword-lo" | "qword-hi"
    hits   = {},       -- row.key -> hit list, from the one-shot discovery
    probed = {},       -- row.key -> true
    said   = false,
    counted = false,
    vft_said = false,
    guid_said = false,
    guid_proven = false,
    guid_done = false,   -- a refusal is final for the run: the gates said no
    -- The net component fields NamedEvent_NetSend dereferences by name.
    DEEP    = { 0xb8, 0xc0, 0xc8 },
    -- oCSLNetworkObject::vft[0x18]: *(*(*(C+0xb8)+0x100)+0x28) is the session
    -- this entity replicates to. Read straight off the decompile.
    OWNER_PATH = { 0xb8, 0x100, 0x28 },
    owner_said = 0,
    owner_vft_said = false,
    DEEPWIN = 0x200,   -- bytes of each of those objects to inspect
    MEMWIN = 0x100,    -- bytes of the lobby member object to harvest
    -- Netcode_PeerSlots / Netcode_PeerCount, the engine's own list of the
    -- other machines in the run. Baked VAs, so every read is gated on
    -- _va_ok(): a stale global is a plausible-looking pointer, not a nil.
    --
    -- ⚠ The base is 0x14143f600, NOT 0x14143f650. The tick's `lea rax,
    -- [rip+...]` lands on 0x14143f650 because it indexes slot+0x50 (the
    -- tunnel pointer) directly, so reading the array from there is off by
    -- 0x50 and every string comes back from the NEXT slot. The true base is
    -- what the slot ctor FUN_1402aedf0 zeroes, field by field.
    PEER_SLOTS  = 0x14143f600,
    PEER_COUNT  = 0x14143f780,
    PEER_STRIDE = 0x60,        -- `lea rax,[rax+rax*2]; shl rax,5` in the tick
    PEER_MAX    = 32,          -- refuse an implausible count outright
    -- Slot fields, all decompile-confirmed (FUN_1402aedf0 fills them,
    -- FUN_1402b5db0 frees them, FUN_1402b0170/FUN_1402b0230 look up by them).
    PEER_NAME    = 0x00,       -- PlayerName, straight off the parsed record
    PEER_SESSION = 0x10,       -- the lobby member's +0x00 session id
    PEER_EOS     = 0x20,       -- m_sEosUserId — the engine's "P2P User"
    PEER_HASH    = 0x30,       -- u64 hash of the EOS id (FUN_1402aed50)
    PEER_TUNNEL  = 0x50,       -- the P2P connection: +0xc0 port, +0xcc state
    PEER_STR    = { 0x00, 0x10, 0x20 },
    -- The two fields NamedEvent_NetSendToPeer (0x1407216c0) dereferences to
    -- unicast an event at ONE session, read straight off its disassembly:
    --
    --     rsi = [netcomp + 0xc8]              ; the scene
    --     rcx = [rsi + 0x28]                  ; the session manager
    --     call [[rcx] + 0x88](rcx, &out)      ; out = the LOCAL session id
    --     cmp  out, [target]                  ; skip a send to ourselves
    --     call [[rsi] + 0xc0](rsi, target, m) ; send to that session
    --
    -- So the engine routes by the SAME qword the replica calls
    -- creatingSystemGUID, and scene+0x28 is the object that owns the
    -- session->connection mapping. That is where a guid can become a peer.
    SCENE     = 0xc8,
    SCENE_MGR = 0x28,
    -- Stormancer::RakNetConnection + 0xf8 is the owning RakNetGUID, written
    -- by the ctor as `param_1[0x1f] = *param_2`. The map node the transport
    -- keeps it in is { _Next, _Prev, GUID @+0x10, connection* @+0x18 }.
    -- THE RAKNET REMOTE-SYSTEM TABLE, read exactly where the engine reads it.
    --
    -- oCDtP2PSessionSceneContext::vft[0x88] (0x1408b7550) is one line --
    -- `[this+0x210]->vft[0x190](&out)` -- and that callee (0x140ae3280) is
    -- also one line: `out = {u64 @this+0x7f0, u16 @this+0x7f8}`, i.e. the
    -- LOCAL RakNetGUID. So ctx+0x210 is an oCSLNetPeer, the RakPeer wrapper.
    --
    -- Its vft[0x100] (0x140ae1700) is the enumerator, and it walks members:
    --
    --     for i in 0 .. *(u32*)(peer+0x258):
    --         rs = *(void**)(peer+0x250 + i*8)
    --         if *(char*)rs != 0 and *(int*)(rs+0x2cec) == 7:      -- connected
    --             emit SystemAddress at rs+0x08  (sockaddr: port at +2, ntohs)
    --             emit {u64 @rs+0x2cc8, u16 @rs+0x2cd0}            -- RakNetGUID
    --
    -- which is RakNet::RakPeer::RemoteSystemStruct. That GUID is the same
    -- qword Replica3::creatingSystemGUID puts on a hero's replica, and the
    -- SystemAddress is the UDP endpoint whose PORT Netcode_PeerSlots already
    -- exposes per peer (slot+0x50 -> +0xc0, ntohs'd by FUN_1402aa470). One
    -- table therefore carries both halves of the join, and reading it is
    -- pure loads -- no engine call, no allocation, nothing to free.
    CTX_PEER  = 0x210,
    RS_LIST   = 0x250,
    RS_COUNT  = 0x258,
    RS_ADDR   = 0x08,
    RS_GUID   = 0x2cc8,
    RS_STATE  = 0x2cec,
    RS_CONNECTED = 7,
    RS_MAX    = 64,
    rak_said  = false,
    rak_done  = false,
    rak_idle  = 0,        -- consecutive passes that named nothing new
    -- Three is enough to cover a row boarding a tick or two after its peer
    -- slot appears, without spinning for the rest of the match.
    RAK_IDLE_MAX = 3,
    CONN_GUID = 0xf8,
    NODE_KEY  = 0x10,
    NODE_VAL  = 0x18,
    NODE_NEXT = 0x00,
    MAP_MAX   = 64,      -- refuse to walk a list longer than any real lobby
    MGRWIN    = 0x400,   -- bytes of the session manager to walk for pointers
    NODEWIN   = 0x200,   -- bytes of each object it points at
    conn_said = false,
    conn_done = false,
    conn_hit  = {},      -- row.key -> peer slot, kept once the hunt answers
    peer_said   = false,
    peer_done   = false,
    peer_gen    = nil,   -- #peers the memo below was built for
    peer_scanned = {},   -- row.key -> true: its window has been walked once
    peer_hit    = {},    -- row.key -> peer slot, kept after the one-shot scan
}

--- The lobby MEMBER OBJECTS as pointer needles: every plausible pointer the
--- member holds, plus the member's own address, mapped back to the member.
---
--- Session 2c36 settled the value search: all four rows resolved a real net
--- component and NONE of them held a session id within +0x400, direct or one
--- hop. So the peer is not identified there by its GUID -- which is what you
--- would expect if the engine keys peers by a connection OBJECT rather than by
--- the id string the lobby exposes.
---
--- A pointer both structures hold is a much stronger claim than a matching
--- integer: it says the member and the net component reference the SAME
--- allocation. Combined with the anchor and distinctness gates, a coincidence
--- would have to be a pointer that (a) one member alone holds, (b) one row
--- alone holds, (c) pairs the local row with the local player, and (d) pairs
--- every other row with a different member. Nothing shared satisfies that.
---
--- A value two members share is poisoned, exactly like a session needle.
function F._dmg_member_ptrs()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" or not I.read_u64 then return nil end
    local by, n, total = {}, 0, 0
    for _, m in ipairs(members) do
        if type(m.ptrs) == "table" then
            for v in pairs(m.ptrs) do
                if by[v] == nil then by[v] = m
                elseif by[v] and by[v] ~= m then by[v] = false end
                total = total + 1
            end
            n = n + 1
        end
    end
    -- HOW MANY members contributed, once. Session 9e4f reported 30 hits that
    -- all named one player, and "every row holds a shared pointer" and "only
    -- one member had any needles at all, so nothing could poison one" look
    -- identical in the log without this. They are a different bug each.
    -- Latch on the first NON-EMPTY answer. Session c236 latched on "0 of 0"
    -- five seconds into the process, before a single member had been parsed,
    -- and then never spoke again for the rest of the run -- so the one number
    -- this line exists to report was the one number it could not report.
    if not F._netid.counted and n > 0 then
        F._netid.counted = true
        R.log(("[rsmm.damage] net id: %d of %d lobby member(s) contributed "
               .. "%d pointer needle(s)"):format(n, #members, total))
    end
    if n == 0 then return nil end
    return by
end

--- Both needle sets in one table, so a scan reads each qword once.
function F._dmg_netid_targets()
    local hex = F._dmg_session_needles()
    local ptr = F._dmg_member_ptrs()
    if not hex and not ptr then return nil end
    return { hex = hex or {}, ptr = ptr or {} }
end

--- The lobby's session ids as needles, keyed by the hex text a read would
--- produce. Text, not integers: a GUID half can exceed the signed 64-bit range
--- Lua 5.4 parses, and a float compare would match its neighbours too.
---
--- Both halves and both byte orders, because the netcode deals in qwords and a
--- half stored little-endian prints reversed. A needle two members share is
--- poisoned rather than dropped -- it must never name the first one found.
function F._dmg_session_needles()
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    local function rev(h)
        local t = {}
        for i = 15, 1, -2 do t[#t + 1] = h:sub(i, i + 1) end
        return table.concat(t)
    end
    local by, n = {}, 0
    for _, m in ipairs(members) do
        local s = m.session
        if type(s) == "string" and #s == 32 and not s:find("[^0-9a-fA-F]") then
            s = s:lower()
            local lo, hi = s:sub(1, 16), s:sub(17, 32)
            local add = function(key, kind)
                if by[key] == nil then
                    by[key] = { m = m, kind = kind }
                elseif by[key] and by[key].m ~= m then
                    by[key] = false           -- shared by two members: useless
                end
            end
            add(s, "string")
            add(lo, "qword-lo")
            add(hi, "qword-hi")
            add(rev(lo), "qword-lo")
            add(rev(hi), "qword-hi")
            n = n + 1
        end
    end
    if n == 0 then return nil end
    return by
end

--- Every match for a member needle in `base[0 .. win)`: a session id as a
--- qword or a std::string, or a pointer the member itself holds. Guarded
--- reads only, so an unmapped page costs a nil.
--- `path` is how `base` was reached from the net component: nil for the
--- component itself, {a} for `*(nc+a)`, {a,b} for `*(*(nc+a)+b)`. Recorded on
--- every hit so an adopted locator can be RE-READ on another row -- a hit
--- nobody can reproduce is not a locator.
function F._dmg_scan_session(base, win, targets, path)
    local out = {}
    if not _ptr_plausible(base) or not I.read_u64 then return out end
    for off = 0, win - 8, 8 do
        local q = I.read_u64(base + off)
        if type(q) == "number" then
            local h = targets.hex[("%016x"):format(q)]
            if h then
                out[#out + 1] = { off = off, path = path, kind = h.kind, m = h.m }
            else
                local m = targets.ptr[q]
                if m then out[#out + 1] = { off = off, path = path, kind = "ptr", m = m } end
            end
        end
        -- A std::string read is up to three more guarded reads, and this
        -- loop runs tens of thousands of times per row. Only bother where one
        -- could actually start: the heap form begins with a pointer, and the
        -- inline form begins with hex characters.
        local looks = _ptr_plausible(q)
        if not looks and type(q) == "number" then
            local c = q & 0xff
            looks = (c >= 0x30 and c <= 0x39) or (c >= 0x61 and c <= 0x66)
                    or (c >= 0x41 and c <= 0x46)
        end
        local s = looks and R.debug.stdstring_at and R.debug.stdstring_at(base + off)
        if type(s) == "string" and #s == 32 then
            local h = targets.hex[s:lower()]
            if h then out[#out + 1] = { off = off, path = path, kind = "string", m = h.m } end
        end
    end
    return out
end

--- The owning peer's RakNetGUID for a row, or nil.
---
--- `oCSLNetworkObject::vft[0x18]` (0x1408c0d40) is one line:
---
---     *out = *(*(netobj + 0x100) + 0x28);
---
--- netobj+0x100 is the oCSLNetReplica (set in its ctor, FUN_1408c0890's
--- param_2), and the replica is a RakNet::Replica3 whose +0x28 is
--- `creatingSystemGUID` -- the peer that created it, i.e. the machine whose
--- player owns this hero. Read, never called: three guarded loads.
function F._dmg_owner_guid(row)
    -- STICKY. Session 0e36 read a GUID for rows 1 and 2 at 18:43 and then
    -- reported `row 2 guid=nil, row 3 guid=nil, row 4 guid=nil` five minutes
    -- later: the chain is only walkable while the row's controller still
    -- points at a live entity with a net component, and a death or a chapter
    -- boundary breaks it. The GUID itself is a property of the OWNING MACHINE
    -- and cannot change under a row, so the first answer is the answer -- and
    -- a join that runs later must not lose the key it already had.
    if row.owner_guid then return row.owner_guid end
    if not I.read_u64 or not _ptr_plausible(row.key) then return nil end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return nil end
    local nc = R.net.component(ent)
    if not nc then return nil end
    local inner = F._dmg_netid_walk(nc, { 0xb8, 0x100 })
    if not inner then return nil end
    local g = I.read_u64(inner + 0x28)
    if type(g) ~= "number" or g == 0 or g == -1 then return nil end
    row.owner_guid = g
    return g
end

--- Is `t` well-formed UTF-8?
---
--- Hand-rolled rather than `utf8.len`: the loader's Lua is 5.4 and does have
--- the library, but this runs on every peer-slot read against bytes that may be
--- a stale pointer's contents, and `utf8.len` accepts the over-long and
--- surrogate encodings that a garbage read produces as readily as a real name.
--- Rejecting those is the entire point of the check.
---
--- On `F` rather than a `local`: the main chunk sits at Lua's 200-local
--- ceiling, and one more `local function` here costs the whole SDK its compile.
function F._utf8_ok(t)
    local i, n = 1, #t
    while i <= n do
        local c = t:byte(i)
        local extra, lo, hi
        if c < 0x80 then extra = 0
        elseif c >= 0xc2 and c <= 0xdf then extra, lo, hi = 1, 0x80, 0xbf
        elseif c == 0xe0 then extra, lo, hi = 2, 0xa0, 0xbf   -- no over-long
        elseif c >= 0xe1 and c <= 0xec then extra, lo, hi = 2, 0x80, 0xbf
        elseif c == 0xed then extra, lo, hi = 2, 0x80, 0x9f   -- no surrogates
        elseif c >= 0xee and c <= 0xef then extra, lo, hi = 2, 0x80, 0xbf
        elseif c == 0xf0 then extra, lo, hi = 3, 0x90, 0xbf   -- no over-long
        elseif c >= 0xf1 and c <= 0xf3 then extra, lo, hi = 3, 0x80, 0xbf
        elseif c == 0xf4 then extra, lo, hi = 3, 0x80, 0x8f   -- <= U+10FFFF
        else return false
        end
        for k = 1, extra do
            local b = t:byte(i + k)
            if not b then return false end
            local min = (k == 1) and lo or 0x80
            local max = (k == 1) and hi or 0xbf
            if b < min or b > max then return false end
        end
        i = i + 1 + extra
    end
    return true
end

--- One engine string/buffer descriptor: {void* ptr @+0x0; int32 len @+0x8;
--- uint32 cap @+0xc}. Same shape as LobbyAttributes_Parse's StringDesc, and
--- the shape the peer-slot destructor frees three of.
function F._peer_str(va)
    if not (I.read_u64 and I.read_u32 and I.read_cstr) then return nil end
    local ptr = I.read_u64(va)
    if not _ptr_plausible(ptr) then return nil end
    local len = I.read_u32(va + 8)
    if type(len) ~= "number" then return nil end
    len = len & 0x7fffffff                 -- bit 31 is the "not owned" flag
    if len < 1 or len > 128 then return nil end
    local t = I.read_cstr(ptr, len + 1)
    if type(t) ~= "string" or #t ~= len then return nil end
    -- PRINTABLE, not ASCII. This guard used to be `[^\32-\126]`, which threw
    -- away every player whose name is not plain ASCII -- session 104f's "7♣"
    -- (U+2663, bytes E2 99 A3) came back nil from the peer slot while its
    -- session and EOS ids, being hex, came back fine.
    --
    -- That is not a cosmetic loss. A nameless peer slot is a row that can never
    -- be PROVEN, and "is any row still unnamed?" is the gate on both the raknet
    -- join and the address scan -- so one non-ASCII name in the lobby left both
    -- running for the entire match, re-announcing the same result once a second
    -- (70 identical lines in that log). A run with an accented, CJK or emoji
    -- name in it is the common case, not the exotic one.
    --
    -- The guard's real job is rejecting a garbage read, and what garbage looks
    -- like is CONTROL bytes and malformed sequences, not high bytes. So: no
    -- C0/DEL, and the high bytes must form valid UTF-8.
    if t:find("[%z\1-\31\127]") then return nil end
    if not F._utf8_ok(t) then return nil end
    return t
end

--- The engine's own peer table — one entry per OTHER machine in the run.
---
--- Read-only, no engine call, ~`count` * a handful of guarded loads. This is
--- the only structure that holds one record per remote player, which is what a
--- row->player join has been missing: the board knows every NAME (lobby
--- attributes) and a distinct per-row owner RakNetGUID, and nothing joined them.
---
--- Layout in `Netcode_PeerSlots`'s note. Returns `{}` rather than guessing when
--- the va gate is closed or the count is implausible.
function R.net.peers()
    if not _va_ok("the netcode peer table") then return {} end
    if not (I.module_base and I.read_u32 and I.read_u64) then return {} end
    local base = I.module_base()
    if not base or base == 0 then return {} end
    local slots = base + (F._netid.PEER_SLOTS - 0x140000000)
    local n = I.read_u32(base + (F._netid.PEER_COUNT - 0x140000000))
    if type(n) ~= "number" or n < 1 or n > F._netid.PEER_MAX then return {} end
    local out = {}
    for i = 0, n - 1 do
        local slot = slots + i * F._netid.PEER_STRIDE
        local e = { index = i, slot = slot, text = {} }
        e.name    = F._peer_str(slot + F._netid.PEER_NAME)
        e.session = F._peer_str(slot + F._netid.PEER_SESSION)
        e.eos     = F._peer_str(slot + F._netid.PEER_EOS)
        e.hash    = I.read_u64(slot + F._netid.PEER_HASH)
        if e.hash == 0 or e.hash == -1 then e.hash = nil end
        local ptr = I.read_u64(slot + F._netid.PEER_TUNNEL)
        if _ptr_plausible(ptr) then
            e.peer  = ptr
            -- ntohs'd in FUN_1402aa470 (Ordinal_15 = ntohs), so this is a
            -- UDP PORT in network order, NOT a RakNet system index.
            e.port  = I.read_u16 and I.read_u16(ptr + 0xc0)
            e.state = I.read_u32(ptr + 0xcc)
        end
        for _, off in ipairs(F._netid.PEER_STR) do
            local t = F._peer_str(slot + off)
            if t then e.text[#e.text + 1] = t end
        end
        out[#out + 1] = e
    end
    return out
end

--- The owner GUID's SYSTEM INDEX, the other half of the RakNetGUID.
---
--- `RakNetGUID` is `{uint64 g; uint16 systemIndex}` — the replica ctor
--- initialises 16 bytes at +0x28 — so the index sits at replica+0x30. It is
--- the candidate bridge to the peer table, whose peer objects carry a u16 at
--- +0xc0 that Netcode_DropPeer's finder matches on.
function F._dmg_owner_index(row)
    if not I.read_u16 or not _ptr_plausible(row.key) then return nil end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return nil end
    local nc = R.net.component(ent)
    if not nc then return nil end
    local inner = F._dmg_netid_walk(nc, { 0xb8, 0x100 })
    if not inner then return nil end
    local ix = I.read_u16(inner + 0x30)
    if type(ix) ~= "number" or ix == 0xffff then return nil end
    return ix
end

--- Join rows to players through the ENGINE'S OWN PEER TABLE.
---
--- `Netcode_PeerSlots` is one 0x60-byte slot per other machine in the run, and
--- the slot already carries the player's display NAME (+0x00), their lobby
--- session id (+0x10), their EOS ProductUserId (+0x20) and a 64-bit hash of
--- that id (+0x30). It is a better name source than the lobby roster: the
--- roster is append-only history, this is current membership.
---
--- The unsolved half is which SLOT owns which row. The engine's own join is by
--- the +0x30 hash -- FUN_140272700 walks the slots and matches each against
--- `hash(member.m_sEosUserId)`, logging "No party member found for P2P User"
--- when it cannot -- so that hash is the shape an ownership record would take
--- on the hero side too. This scans each row's controller and entity for it.
---
--- A hit is an EQUALITY on a 64-bit engine-computed id, which is what separates
--- it from `guess_names`. No hit names nobody, and the report below still says
--- what both halves held.
function F._dmg_peer_join()
    if F._netid.peer_done then return false end
    -- Nothing unnamed, nothing to look for. Without this the window walk below
    -- runs on a board that is already fully named, forever.
    local wanted = false
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not row.player and _ptr_plausible(row.key) then
            wanted = true
            break
        end
    end
    if not wanted then return false end
    local peers = R.net.peers()
    if #peers == 0 then return false end
    -- ONE-SHOT PER ROW, re-armed only when the peer set changes.
    --
    -- The scan below is 0x800 bytes of the controller plus 0x800 of the entity,
    -- read a qword at a time through the page guard: ~512 native calls per row.
    -- The first version ran it on EVERY background tick for every unnamed row
    -- and never stopped, because a miss returns false rather than latching --
    -- four rows is ~2000 guarded reads a tick, forever. That is the "lags
    -- sometimes hard" shape: invisible while it happens to match, brutal while
    -- it does not. A row's controller does not sprout the key later, so once is
    -- the right number of times; a NEW peer is the only thing that can change
    -- the answer, so that is what re-arms it.
    local gen = #peers
    if F._netid.peer_gen ~= gen then
        F._netid.peer_gen, F._netid.peer_scanned = gen, {}
    end

    -- The engine's own key. FUN_1402aed50 hashes the EOS id into slot+0x30 and
    -- FUN_140272700 joins a lobby member to a peer by comparing that hash --
    -- so if anything on the hero side records which player owns it, this
    -- 64-bit value is the shape it would take. A value two peers share
    -- identifies neither.
    local by_hash = {}
    for _, e in ipairs(peers) do
        if e.hash then
            by_hash[e.hash] = (by_hash[e.hash] == nil) and e or false
        end
    end

    local hit, found = {}, {}
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) and not F._netid.peer_scanned[row.key] then
            F._netid.peer_scanned[row.key] = true
            row._peer_ix = F._dmg_owner_index(row)
            local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
            for _, obj in ipairs({ row.key, _ptr_plausible(ent) and ent or nil }) do
                for off = 0, F._netid.WIN - 8, 8 do
                    local v = I.read_u64(obj + off)
                    local e = type(v) == "number" and by_hash[v]
                    if e then
                        F._netid.peer_hit = F._netid.peer_hit or {}
                        F._netid.peer_hit[row.key] = e
                        found[#found + 1] = ("row %d +0x%x -> %s"):format(
                            row.slot, off, tostring(e.name))
                    end
                end
            end
        end
        -- Carried across ticks: the scan happened once, its answer has to
        -- outlive it or the join can never act on a row it already solved.
        local e = F._netid.peer_hit and F._netid.peer_hit[row.key]
        if e then hit[row] = e end
    end

    if not F._netid.peer_said then
        F._netid.peer_said = true
        local pp = {}
        for _, e in ipairs(peers) do
            pp[#pp + 1] = ("#%d %s session=%s eos=%s port=%s state=%s hash=%s"):format(
                e.index, tostring(e.name), tostring(e.session), tostring(e.eos),
                tostring(e.port), tostring(e.state),
                e.hash and ("0x%x"):format(e.hash) or "nil")
        end
        local rr = {}
        for _, row in ipairs(_dmg.order) do
            local g = F._dmg_owner_guid(row)
            rr[#rr + 1] = ("row %d guid=%s ix=%s"):format(
                row.slot, g and ("0x%x"):format(g) or "nil",
                tostring(row._peer_ix))
        end
        -- Both halves, always. A silent failure costs a playtest to work out
        -- which side was empty; this line says so outright.
        R.log(("[rsmm.damage] peer table: %d peer(s) [%s]; rows [%s]; hash hits [%s]")
              :format(#peers, table.concat(pp, ", "), table.concat(rr, ", "),
                      #found > 0 and table.concat(found, ", ") or "none"))
    end
    if not next(hit) then return false end

    -- Same two gates as every other join. The anchor is the one that catches a
    -- plausible-but-wrong bridge: if this machine's own row comes back as
    -- somebody else, the mapping is not an identity.
    local me
    local okn, nm = pcall(R.player.name)
    if okn and type(nm) == "string" and nm ~= "" then me = nm end
    for row, e in pairs(hit) do
        if row.is_local and me and e.name and e.name ~= me then
            R.log(("[rsmm.damage] peer join REFUSED: this machine's row resolves "
                   .. "to %q but Steam calls this player %q"):format(e.name, me))
            F._netid.peer_done = true
            return false
        end
    end
    local by = {}
    for row, e in pairs(hit) do
        if e.name then
            if by[e.name] then
                R.log(("[rsmm.damage] peer join REFUSED: rows %d and %d both "
                       .. "resolve to %q"):format(by[e.name].slot, row.slot, e.name))
                F._netid.peer_done = true
                return false
            end
            by[e.name] = row
        end
    end

    local named = 0
    for row, e in pairs(hit) do
        if e.name and not row.is_local and _dmg.names[row.slot] == nil
           and row.label ~= e.name then
            row.label, row.label_guess, row.player = e.name, false, e.name
            named = named + 1
        end
    end
    if named > 0 then
        F._netid.peer_done = true
        R.log(("[rsmm.damage] PEER JOIN PROVEN: %d row(s) named from the engine's "
               .. "own peer table — exact, not a guess"):format(named))
    end
    return named > 0
end

--- Name rows by matching the owner GUID against the lobby members' own words.
---
--- The engine has to know which peer each lobby member is, and a RakNetGUID is
--- a plain 64-bit number, so if it records that anywhere on the member this
--- finds it. Same two gates as everything else: the local row must resolve to
--- the Steam persona, and no two rows may resolve to the same member.
---
--- Costs one table lookup per (row, member) pair. Nothing is searched.
function F._dmg_guid_join()
    if F._netid.guid_done then return false end
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return false end
    -- NOT gated on the roster size. The GUID report below is about the ROWS --
    -- distinct values prove the field is the per-player key whether or not any
    -- member carries one -- and gating the whole function on `#members >= 2`
    -- suppressed it in exactly the sessions where it was worth having.
    if #members < 1 then return false end
    local guid, hit, rows = {}, {}, 0
    for _, row in ipairs(_dmg.order) do
        local g = F._dmg_owner_guid(row)
        if g then
            guid[row] = g
            rows = rows + 1
            local found, count = nil, 0
            for _, m in ipairs(members) do
                if type(m.words) == "table" and m.words[g] then
                    found, count = m, count + 1
                end
            end
            -- A GUID two members claim identifies neither.
            if count == 1 then hit[row] = found end
        end
    end
    if rows == 0 then return false end
    -- Report the GUIDs once, whatever happens. Four different values is the
    -- proof that the field is the owner key even when no member carries it.
    if not F._netid.guid_said and rows > 1 then
        F._netid.guid_said = true
        local seen, n = {}, 0
        local parts = {}
        for _, row in ipairs(_dmg.order) do
            if guid[row] then
                if not seen[guid[row]] then seen[guid[row]] = true; n = n + 1 end
                parts[#parts + 1] = ("row %d = 0x%x%s"):format(
                    row.slot, guid[row], hit[row] and (" -> " .. hit[row].name) or "")
            end
        end
        R.log(("[rsmm.damage] owner GUIDs: %s (%d distinct across %d row(s))")
              :format(table.concat(parts, ", "), n, rows))
    end
    if not next(hit) then return false end
    -- ANCHOR: the local row must resolve to this machine's player.
    local me
    local okn, nm = pcall(R.player.name)
    if okn and type(nm) == "string" and nm ~= "" then me = nm end
    for row, m in pairs(hit) do
        if row.is_local and me and m.name ~= me then
            R.log(("[rsmm.damage] owner GUID join REFUSED: this machine's row "
                   .. "resolves to %q but Steam calls this player %q")
                  :format(m.name, me))
            F._netid.guid_done = true
            return false
        end
    end
    -- DISTINCTNESS: two rows resolving to one member means the match is not an
    -- identity, so it names nobody.
    local by = {}
    for row, m in pairs(hit) do
        if by[m.name] then
            R.log(("[rsmm.damage] owner GUID join REFUSED: rows %d and %d both "
                   .. "resolve to %q"):format(by[m.name].slot, row.slot, m.name))
            F._netid.guid_done = true
            return false
        end
        by[m.name] = row
    end
    local names, named = F._dmg_name_set(), false
    if not names then return false end
    for row, m in pairs(hit) do
        if not row.player and names[m.name] then
            if F._dmg_claim(row, names, m.name, "owner GUID") then named = true end
        end
    end
    if named and not F._netid.guid_proven then
        F._netid.guid_proven = true
        R.log("[rsmm.damage] OWNER GUID JOIN PROVEN: rows are named from "
              .. "RakNet::Replica3::creatingSystemGUID -- the peer the engine "
              .. "itself says created the hero, matched against the lobby "
              .. "member that carries the same GUID.")
    end
    return named
end

--- The object the engine routes sessions through, reached from a live row.
---
--- `netcomp+0xc8` is the scene and `scene+0x28` is the session manager --
--- both read straight out of NamedEvent_NetSendToPeer, which asks that object
--- for the LOCAL session id (vft slot 0x88) before unicasting through the
--- scene's own slot 0xc0. Whatever maps a session qword to a connection lives
--- there, and a row's owner GUID *is* that qword.
---
--- Any row will do: every replicated entity in the run shares one scene.
function F._dmg_conn_mgr()
    if not I.read_u64 then return nil end
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) then
            local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
            if _ptr_plausible(ent) then
                local nc = R.net.component(ent)
                if nc then
                    local scene = I.read_u64(nc + F._netid.SCENE)
                    if _ptr_plausible(scene) then
                        local mgr = I.read_u64(scene + F._netid.SCENE_MGR)
                        if _ptr_plausible(mgr) then return mgr, scene end
                    end
                end
            end
        end
    end
    return nil
end

--- Every 64-bit value that identifies exactly ONE peer slot.
---
--- A value two peers share identifies neither, so it is dropped rather than
--- resolved to whichever was seen last -- the same rule the EOS-hash join
--- uses, for the same reason.
function F._dmg_peer_needles(peers)
    local n = {}
    local function add(v, e)
        if type(v) ~= "number" or v == 0 or v == -1 then return end
        if not _ptr_plausible(v) and v ~= e.hash then return end
        if n[v] ~= nil and n[v] ~= e then n[v] = false else n[v] = e end
    end
    for _, e in ipairs(peers) do
        add(e.hash, e)                                   -- FUN_1402aed50's EOS hash
        for _, off in ipairs(F._netid.PEER_STR) do       -- the three string buffers
            add(I.read_u64(e.slot + off), e)
        end
        add(e.peer, e)                                   -- the P2P tunnel object
        add(e.slot, e)                                   -- the slot itself
    end
    return n
end

--- The RakNet remote-system table for this run: GUID -> UDP port.
---
--- Pure reads off the chain in F._netid's notes, all of it decompiled rather
--- than guessed. Returns a list of `{ guid, port, state }`, or nil when the
--- chain does not resolve -- never a partial guess.
function F._dmg_rak_systems()
    if not (I.read_u64 and I.read_u32 and I.read_u16) then return nil end
    local mgr = F._dmg_conn_mgr()
    if not mgr then return nil end
    local peer = I.read_u64(mgr + F._netid.CTX_PEER)
    if not _ptr_plausible(peer) then return nil end
    local list = I.read_u64(peer + F._netid.RS_LIST)
    local n    = I.read_u32(peer + F._netid.RS_COUNT)
    if not _ptr_plausible(list) then return nil end
    if type(n) ~= "number" or n < 1 or n > F._netid.RS_MAX then return nil end
    local out = {}
    for i = 0, n - 1 do
        local rs = I.read_u64(list + i * 8)
        if _ptr_plausible(rs) then
            local g  = I.read_u64(rs + F._netid.RS_GUID)
            -- sockaddr_in: sin_family @+0, sin_port @+2, network order. The
            -- engine passes it through ntohs (Ordinal_15) and so must we.
            local np = I.read_u16(rs + F._netid.RS_ADDR + 2)
            local st = I.read_u32(rs + F._netid.RS_STATE)
            if type(g) == "number" and g ~= 0 and g ~= -1 and type(np) == "number" then
                out[#out + 1] = {
                    guid  = g,
                    port  = ((np & 0xff) << 8) | ((np >> 8) & 0xff),
                    state = st,
                    rs    = rs,
                }
            end
        end
    end
    if #out == 0 then return nil end
    return out
end

--- The display name for a peer slot, recovering one the slot itself lacks.
---
--- Session 104f, match 2: peer #0 read `nil` for its name while carrying a
--- perfectly good session id AND EOS id — and the lobby roster knew that
--- player as "7♣". One nameless slot is not a cosmetic loss: the row it
--- belongs to can never be proven, so `_dmg_rak_join`'s "is anyone still
--- unnamed?" gate stays open for the rest of the match, re-pairing and
--- re-announcing every OTHER row once a second forever (70 identical PROVEN
--- lines in that log), and the address scan next door reads the same shape and
--- keeps sweeping too.
---
--- The recovery is still READ, not searched: `m_sEosUserId` and the session id
--- are named fields on the lobby member and named fields on the peer slot, so
--- this is the same kind of join as the port match, on a different column.
--- EOS first — it is the account, where a session id is per-connection.
function F._dmg_peer_name(e)
    if type(e) ~= "table" then return nil end
    if type(e.name) == "string" and e.name ~= "" then return e.name end
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return nil end
    for _, key in ipairs({ "eos", "session" }) do
        local want = e[key]
        if type(want) == "string" and #want > 0 then
            for _, m in ipairs(members) do
                if m[key] == want and type(m.name) == "string" and m.name ~= "" then
                    return m.name
                end
            end
        end
    end
    return nil
end

--- Name rows from the RakNet remote-system table, joined on the UDP PORT.
---
--- THE ONLY JOIN HERE THAT IS READ RATHER THAN SEARCHED. Both halves are
--- fields the disassembly names outright:
---
---   * a row's owner GUID is Replica3::creatingSystemGUID (Entity_GetNetId),
---   * RemoteSystemStruct carries that same GUID beside the peer's
---     SystemAddress (oCSLNetPeer::vft[0x100]),
---   * and Netcode_PeerSlots carries the display NAME beside the same UDP
---     port (slot+0x50 -> +0xc0).
---
--- So GUID -> port -> name, with no offset ever adopted by agreement and
--- nothing searched for. The gates below are still here, because a layout can
--- be right and a build can still have moved: this machine must not appear as
--- one of its own remote systems, and two rows may not land on one peer.
function F._dmg_rak_join()
    if F._netid.rak_done then return false end
    local wanted = false
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not row.player and _ptr_plausible(row.key) then
            wanted = true
            break
        end
    end
    if not wanted then return false end

    local peers = R.net.peers()
    if #peers == 0 then return false end
    local systems = F._dmg_rak_systems()
    if not systems then return false end

    -- port -> peer slot. A port two peers share names neither.
    local by_port = {}
    for _, e in ipairs(peers) do
        if type(e.port) == "number" and e.port ~= 0 then
            if by_port[e.port] ~= nil and by_port[e.port] ~= e then by_port[e.port] = false
            else by_port[e.port] = e end
        end
    end
    -- guid -> peer slot, through the remote-system table.
    local by_guid_peer = {}
    for _, sys in ipairs(systems) do
        local e = by_port[sys.port]
        if e then
            if by_guid_peer[sys.guid] ~= nil and by_guid_peer[sys.guid] ~= e then
                by_guid_peer[sys.guid] = false
            else
                by_guid_peer[sys.guid] = e
            end
        end
    end

    local pair, notes = {}, {}
    for _, row in ipairs(_dmg.order) do
        local g = F._dmg_owner_guid(row)
        local e = g and by_guid_peer[g]
        if e then
            pair[row] = e
            notes[#notes + 1] = ("row %d 0x%x:%d <-> %s")
                                :format(row.slot, g, e.port, tostring(e.name))
        end
    end

    if not F._netid.rak_said and #systems > 0 then
        F._netid.rak_said = true
        local ss = {}
        for _, sys in ipairs(systems) do
            ss[#ss + 1] = ("0x%x:%d%s"):format(sys.guid, sys.port,
                sys.state == F._netid.RS_CONNECTED and "" or (" state=" .. tostring(sys.state)))
        end
        -- The whole table, once. If a build moves RemoteSystemStruct this line
        -- is what says so -- implausible ports and zero GUIDs read as garbage
        -- at a glance, where a silent `return false` reads as "no co-op".
        R.log(("[rsmm.damage] raknet systems: %d [%s]; peer ports [%s]; pairs [%s]")
              :format(#systems, table.concat(ss, " "),
                      (function()
                          local t = {}
                          for _, e in ipairs(peers) do
                              t[#t + 1] = ("%s:%s"):format(tostring(e.name), tostring(e.port))
                          end
                          return table.concat(t, " ")
                      end)(),
                      #notes > 0 and table.concat(notes, ", ") or "none"))
    end
    if not next(pair) then return false end

    -- ANCHOR. The remote-system table is the OTHER machines; this one being in
    -- it means the chain is not what the decompile says it is.
    for row, e in pairs(pair) do
        if e and row.is_local then
            R.log(("[rsmm.damage] raknet join REFUSED: this machine's row pairs "
                   .. "with remote system %q"):format(tostring(e.name)))
            F._netid.rak_done = true
            return false
        end
    end
    -- DISTINCTNESS.
    local by = {}
    for row, e in pairs(pair) do
        if e and e.name then
            if by[e.name] then
                R.log(("[rsmm.damage] raknet join REFUSED: rows %d and %d both "
                       .. "pair with %q"):format(by[e.name].slot, row.slot, e.name))
                F._netid.rak_done = true
                return false
            end
            by[e.name] = row
        end
    end

    -- NEWLY named, not pairable. `named` used to count every row the join
    -- COULD pair, which is a constant for the rest of the match — so a single
    -- row it could never pair (a nameless peer slot) meant this block rewrote
    -- the same two labels and logged the same "PROVEN" line every tick for the
    -- whole run. Counting the rows whose name actually CHANGED makes the log
    -- an event again and makes the return value mean "I made progress".
    local named, total = 0, 0
    for row, e in pairs(pair) do
        local nm = F._dmg_peer_name(e)
        if nm and not row.is_local and _dmg.names[row.slot] == nil then
            total = total + 1
            if row.player ~= nm then
                row.label, row.label_guess, row.player = nm, false, nm
                named = named + 1
            end
        end
    end
    if named > 0 then
        R.log(("[rsmm.damage] RAKNET JOIN PROVEN: %d of %d row(s) named by "
               .. "matching Replica3::creatingSystemGUID to RakPeer's "
               .. "remote-system table and its UDP port to the peer slot's "
               .. "tunnel — read, not searched"):format(named, total))
        F._netid.rak_idle = 0
        return true
    end

    -- Nothing new, and the pairing is a pure read of tables that only change
    -- when the lobby does. Stand down rather than re-deriving the same answer
    -- once a second until the run ends; the chapter epoch re-arms it, which is
    -- the only moment a row's controller (and so its owner GUID) can change.
    F._netid.rak_idle = (F._netid.rak_idle or 0) + 1
    if F._netid.rak_idle >= F._netid.RAK_IDLE_MAX then
        F._netid.rak_done = true
        if total < #_dmg.order - 1 then
            R.log(("[rsmm.damage] raknet join: named every row it can (%d); "
                   .. "the rest have no peer slot carrying a name, so they "
                   .. "keep their lobby guess — set player_1..4 in the "
                   .. "damage-meter config for exact labels"):format(total))
        end
    end
    return false
end

--- Is `obj` the Stormancer RakNetConnection whose owner GUID is `g`?
---
--- SELF-VALIDATING, and that is why this join is not another coincidence
--- search. RakNetConnection's constructor (FUN_140b9cd50, reached from the
--- factory FUN_140b287f0) copies the RakNetGUID's 64-bit half into
--- `param_1[0x1f]` -- connection + 0xf8 -- from the `{uint64 g; uint16
--- systemIndex}` the transport was handed. The same qword is what
--- Replica3::creatingSystemGUID holds on the hero's replica. So a candidate
--- pointer either answers with the row's own GUID at that one offset or it is
--- not a connection, and no window size or scan order can fake it.
function F._dmg_is_conn(obj, g)
    if not _ptr_plausible(obj) then return false end
    return I.read_u64(obj + F._netid.CONN_GUID) == g
end

--- Join rows to peers through the ENGINE'S OWN CONNECTION REGISTRY.
---
--- Every earlier join searched the HERO side for something the peer side
--- holds, and the hero side never had it: session 2c36 proved no row's net
--- component reaches a lobby session id, and session 0e36's peer scan found
--- no EOS hash anywhere in a controller or entity. The registry is where the
--- engine itself keeps the two halves together.
---
--- WHAT THE REGISTRY IS (Ghidra, this build, 2026-08-21). The netcode is
--- Stormancer over RakNet -- the RTTI carries `Stormancer::RakNetTransport`,
--- `Stormancer::RakNetConnection`, `Stormancer::ConnectionsRepository`,
--- `RakNet::Replica3`. FUN_140b287f0 builds a RakNetConnection from an
--- incoming `{uint64 g; uint16 systemIndex}` and inserts it into a
--- `std::unordered_map<uint64, ...>` at transport+0x80 via FUN_140b2fd80,
--- which is textbook MSVC `try_emplace`: FNV-1a over the key's 8 bytes
--- (`^0xcbf29ce484222325`, `*0x100000001b3`), compare `*(int64*)key ==
--- node[2]`, 0x38-byte node. So a live node is
---
---     { _Next @+0x00, _Prev @+0x08, GUID @+0x10, RakNetConnection* @+0x18 }
---
--- and the connection it points at repeats that same GUID at +0xf8. Three
--- values that must agree, so one hit is proof rather than evidence.
---
--- WHAT IS STILL A SEARCH: which peer slot a connection belongs to. That is
--- the one unproven half, so it is gated the same way every other locator
--- here is -- a candidate offset must resolve a DIFFERENT peer on every
--- connection, and the run must not name the local machine.
---
--- Bounded and one-shot: 0x400 bytes of each object the net component routes
--- through, then 0x200 at each pointer they hold. Finding ONE node is enough
--- to enumerate every connection in the run, because the map is a linked
--- list -- so the cost does not scale with the lobby.
function F._dmg_conn_join()
    if F._netid.conn_done then return false end
    if not (I.read_u64 and _dmg.order) then return false end
    local wanted = false
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not row.player and _ptr_plausible(row.key) then
            wanted = true
            break
        end
    end
    if not wanted then return false end

    local peers = R.net.peers()
    if #peers == 0 then return false end

    -- Rows keyed by owner GUID. A GUID two rows share names neither -- and two
    -- rows sharing one is itself worth saying, because it would mean the field
    -- is not per-player after all.
    local by_guid, guids, dup = {}, 0, false
    for _, row in ipairs(_dmg.order) do
        local g = F._dmg_owner_guid(row)
        if g then
            guids = guids + 1
            if by_guid[g] and by_guid[g] ~= row then by_guid[g], dup = false, true
            else by_guid[g] = row end
        end
    end
    if guids == 0 then return false end

    local mgr, scene = F._dmg_conn_mgr()
    if not mgr then return false end
    local needles = F._dmg_peer_needles(peers)

    -- The registry, once found, is a linked list: one node reaches all of it.
    local conns, node_at, walked = {}, nil, 0
    local guid_at, peer_at, seen, kids = {}, {}, {}, {}
    local function examine(obj, win, collect)
        if not _ptr_plausible(obj) or seen[obj] then return end
        seen[obj] = true
        for off = 0, win - 8, 8 do
            local q = I.read_u64(obj + off)
            if type(q) == "number" and q ~= 0 then
                local r = by_guid[q]
                if r then
                    guid_at[obj + off] = r
                    -- MAP NODE? The qword after the key is the connection, and
                    -- the connection repeats the key at +0xf8. Three agreeing
                    -- values is proof, not evidence.
                    local val = I.read_u64(obj + off + (F._netid.NODE_VAL - F._netid.NODE_KEY))
                    if F._dmg_is_conn(val, q) then
                        conns[q] = val
                        node_at = node_at or (obj + off - F._netid.NODE_KEY)
                    end
                end
                -- Or the connection itself, held directly.
                if _ptr_plausible(q) then
                    local g = I.read_u64(q + F._netid.CONN_GUID)
                    if type(g) == "number" and by_guid[g] then conns[g] = q end
                end
                local e = needles[q]
                if e then peer_at[obj + off] = e end
                if collect and _ptr_plausible(q) and off < 0x80 then
                    kids[#kids + 1] = q
                end
            end
        end
    end

    -- Every object the net component routes through, not just one: NetSend
    -- reads C+0xc0 for the local session and NetSendToPeer reads
    -- [C+0xc8]+0x28 for the same value, so both are entry points into the
    -- same netcode layer and either may be the one that holds the registry.
    local objs = { mgr }
    if scene then objs[#objs + 1] = scene end
    for off = 0, F._netid.MGRWIN - 8, 8 do
        local p = I.read_u64(mgr + off)
        if _ptr_plausible(p) then objs[#objs + 1] = p end
    end
    if scene then
        for off = 0, F._netid.MGRWIN - 8, 8 do
            local p = I.read_u64(scene + off)
            if _ptr_plausible(p) then objs[#objs + 1] = p end
        end
    end
    for _, o in ipairs(objs) do examine(o, F._netid.NODEWIN, true) end

    if not next(conns) and not next(guid_at) then
        -- Second hop, tighter window, capped.
        local n = 0
        for _, k in ipairs(kids) do
            n = n + 1
            if n > 512 then break end
            examine(k, 0x100, false)
        end
    end

    -- ONE NODE IS THE WHOLE MAP. `_Next` at +0x00 walks the bucket list the
    -- transport keeps every connection in, so the lobby's size costs nothing:
    -- the rows this machine has never scanned near are reached anyway.
    if node_at then
        local n, cur = 0, I.read_u64(node_at + F._netid.NODE_NEXT)
        while _ptr_plausible(cur) and cur ~= node_at and n < F._netid.MAP_MAX do
            local key = I.read_u64(cur + F._netid.NODE_KEY)
            local val = I.read_u64(cur + F._netid.NODE_VAL)
            if type(key) == "number" and F._dmg_is_conn(val, key) then
                conns[key] = val
                walked = walked + 1
            end
            cur = I.read_u64(cur + F._netid.NODE_NEXT)
            n = n + 1
        end
    end

    -- WHICH PEER IS THIS CONNECTION? The only unproven half, so it gets the
    -- locator discipline: a candidate offset must answer with a DIFFERENT
    -- peer on every connection it reads, or it is a shared field and names
    -- nobody. Offsets are relative to the connection object, which makes them
    -- reportable and re-checkable next session instead of being a one-run
    -- coincidence.
    local tally = {}
    local function offer(off, row, e)
        local t = tally[off]
        if t == nil then t = { rows = {}, used = {}, n = 0 }; tally[off] = t end
        if t.rows[row] and t.rows[row] ~= e then t.bad = true
        elseif t.used[e] and t.used[e] ~= row then t.bad = true
        elseif not t.rows[row] then
            t.rows[row], t.used[e], t.n = e, row, t.n + 1
        end
    end
    for g, obj in pairs(conns) do
        local row = by_guid[g]
        if row then
            for off = 0, F._netid.NODEWIN - 8, 8 do
                local q = I.read_u64(obj + off)
                local e = type(q) == "number" and needles[q]
                if e then offer(off, row, e) end
            end
        end
    end
    -- FALLBACK, for the case where no connection was reached at all: the same
    -- rule applied to raw distance between a GUID and a peer value in the
    -- same region. Weaker (it proves a layout, not an identity), so it only
    -- runs when the strong path found nothing.
    if not next(conns) then
        for ga, row in pairs(guid_at) do
            if row then
                for na, e in pairs(peer_at) do
                    local dd = na - ga
                    if dd >= -F._netid.NODEWIN and dd <= F._netid.NODEWIN then
                        offer(dd, row, e)
                    end
                end
            end
        end
    end
    local best, bestd
    for off, t in pairs(tally) do
        if not t.bad and t.n >= 2 and (best == nil or t.n > best.n) then
            best, bestd = t, off
        end
    end

    local pair, notes = {}, {}
    if best then
        for row, e in pairs(best.rows) do
            pair[row] = e
            notes[#notes + 1] = ("row %d <-> %s"):format(row.slot, tostring(e.name))
        end
    end

    -- RE-REPORTED WHEN THE INPUT GROWS. Session 7636 logged this line at
    -- 19:20:44 with ONE row's GUID known, and never again -- by 19:21:28 all
    -- four were known and the run's real answer went unlogged. A one-shot
    -- report on a board that fills in over the first minute reports the
    -- emptiest moment it will ever have.
    if F._netid.conn_said ~= guids then
        F._netid.conn_said = guids
        local gg = {}
        for _, row in ipairs(_dmg.order) do
            gg[#gg + 1] = ("row %d=%s"):format(row.slot,
                row.owner_guid and ("0x%x"):format(row.owner_guid) or "nil")
        end
        local ng, np = 0, 0
        for _ in pairs(guid_at) do ng = ng + 1 end
        for _ in pairs(peer_at) do np = np + 1 end
        -- Every half of the search, always. Which one came back empty is the
        -- whole diagnosis: no GUID hit means the records are not reachable
        -- from the manager, no peer hit means they are reachable but hold
        -- nothing that identifies a slot, and both non-zero with no delta
        -- means they are not one record.
        local nc = 0
        for _ in pairs(conns) do nc = nc + 1 end
        R.log(("[rsmm.damage] connection join: mgr=0x%x%s, %d object(s) walked, "
               .. "rows [%s]%s, %d guid hit(s), %d peer hit(s), %d connection(s) "
               .. "(%d off the map list, node %s), locator %s, pairs [%s]")
              :format(mgr, F._dmg_vft_text(mgr), #objs,
                      table.concat(gg, " "), dup and " (SHARED — not per-player)" or "",
                      ng, np, nc, walked,
                      node_at and ("0x%x"):format(node_at) or "none",
                      bestd and ("%s0x%x"):format(bestd < 0 and "-" or "+",
                                                  bestd < 0 and -bestd or bestd)
                             or "none",
                      #notes > 0 and table.concat(notes, ", ") or "none"))
    end

    -- ANCHOR. This machine is not one of its own peers, so the local row
    -- pairing with a peer slot means the record is shared, not owned.
    for row, e in pairs(pair) do
        if e and row.is_local then
            R.log(("[rsmm.damage] connection join REFUSED: this machine's row "
                   .. "pairs with peer %q, and a peer is by definition another "
                   .. "machine"):format(tostring(e.name)))
            F._netid.conn_done = true
            return false
        end
    end
    -- DISTINCTNESS.
    local by = {}
    for row, e in pairs(pair) do
        if e and e.name then
            if by[e.name] then
                R.log(("[rsmm.damage] connection join REFUSED: rows %d and %d both "
                       .. "pair with %q"):format(by[e.name].slot, row.slot, e.name))
                F._netid.conn_done = true
                return false
            end
            by[e.name] = row
        end
    end

    local named = 0
    for row, e in pairs(pair) do
        if e and e.name and not row.is_local and _dmg.names[row.slot] == nil then
            row.label, row.label_guess, row.player = e.name, false, e.name
            F._netid.conn_hit[row.key] = e
            named = named + 1
        end
    end
    if named > 0 then
        F._netid.conn_done = true
        R.log(("[rsmm.damage] CONNECTION JOIN PROVEN: %d row(s) named from the "
               .. "connection record the engine routes by — the object that "
               .. "holds the hero's creatingSystemGUID also holds the peer "
               .. "slot, so the pairing is an equality, not a guess"):format(named))
    end
    return named > 0
end

--- A heap object's vftable as an RVA, for the log. "" when it has none.
function F._dmg_vft_text(obj)
    local mb = I.module_base and I.module_base()
    local vft = I.read_u64 and I.read_u64(obj)
    if mb and mb ~= 0 and _ptr_plausible(vft) and vft > mb then
        return (" (vftable rva 0x%x)"):format(vft - mb)
    end
    return ""
end

--- One-shot: what session ids does this row's net component reach?
---
--- Logs every hit AND the empty result. "The component holds no session id"
--- and "the probe never ran" are the same silence otherwise, and that
--- ambiguity is what cost session 8f36 a whole playtest.
function F._dmg_probe_netid(row, targets)
    if F._netid.probed[row.key] then return F._netid.hits[row.key] end
    if not targets or not I.read_u64 then return nil end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return nil end
    local nc = R.net.component(ent)
    if not nc then
        if not F._netid.said then
            F._netid.said = true
            R.log(("[rsmm.damage] net id: row %d has no net component — the "
                   .. "peer-id join cannot be probed"):format(row.slot))
        end
        return nil
    end
    F._netid.probed[row.key] = true
    local hits = F._dmg_scan_session(nc, F._netid.WIN, targets, nil)
    for off = 0, F._netid.WIN - 8, 8 do
        local p = I.read_u64(nc + off)
        if _ptr_plausible(p) then
            for _, h in ipairs(F._dmg_scan_session(p, F._netid.HOPWIN, targets, { off })) do
                hits[#hits + 1] = h
            end
        end
    end
    -- TWO hops, but only down the three pointers the disassembly names.
    --
    -- NamedEvent_NetSend (0x140721630) and NamedEvent_NetSendToPeer say where
    -- identity actually lives on this component:
    --
    --     [C+0xc0]->vft[0x88](&out)  -> ptr whose [0] is the LOCAL session
    --     [C+0xb8]->vft[0x18](&out)  -> ptr to the session this entity talks to
    --     [C+0xc8]                   -> the scene that sends to a session
    --
    -- Two things follow. Sessions are compared as a single QWORD
    -- (`local_res20 != *param_3`), so the netcode's session is 8 bytes and the
    -- lobby's is a 32-character string -- they are not the same value, which
    -- is why no scan for the GUID could ever hit. And the value is reached
    -- through a VCALL, so it sits deeper than the one hop above. If that qword
    -- is a pointer to a peer object, the object is where a name or a GUID
    -- would be, and that is exactly two hops down these three fields.
    --
    -- Bounded to the named fields on purpose: this is a read of a known
    -- structure, not a wider sweep.
    for _, field in ipairs(F._netid.DEEP) do
        local obj = I.read_u64(nc + field)
        if _ptr_plausible(obj) then
            for _, h in ipairs(F._dmg_scan_session(obj, F._netid.DEEPWIN, targets, { field })) do
                hits[#hits + 1] = h
            end
            for off = 0, F._netid.DEEPWIN - 8, 8 do
                local p = I.read_u64(obj + off)
                if _ptr_plausible(p) then
                    for _, h in ipairs(F._dmg_scan_session(p, F._netid.HOPWIN,
                                                           targets, { field, off })) do
                        hits[#hits + 1] = h
                    end
                end
            end
        end
    end
-- THE OWNER FIELD, read exactly where the engine reads it.
    --
    -- oCSLNetworkObject::vft[0x18] (0x1408c0d40) is one line:
    --
    --     *out = *(*(netobj + 0x100) + 0x28);
    --
    -- so the session an entity replicates to is `*(*(*(C+0xb8)+0x100)+0x28)`,
    -- a plain three-hop field path. No vcall needed, and nothing here is a
    -- guess about WHICH offsets -- the disassembly names all three.
    --
    -- The qword itself is logged per row whatever it is. If the four rows hold
    -- four different values it is the owner key, and the only open question is
    -- what maps it to a name; if they are all equal it is not.
    do
        local owner = F._dmg_netid_walk(nc, F._netid.OWNER_PATH)
        local raw
        local o = F._dmg_netid_walk(nc, { 0xb8, 0x100 })
        if o then raw = I.read_u64(o + 0x28) end
        if raw and F._netid.owner_said < 4 then
            F._netid.owner_said = F._netid.owner_said + 1
            R.log(("[rsmm.damage] net id: row %d owner session = 0x%x%s")
                  :format(row.slot, raw,
                          _ptr_plausible(raw) and " (a pointer)" or ""))
        end
        -- If it is a pointer, the object behind it is where a session STRING
        -- would live -- one hop past what any earlier pass reached.
        if owner then
            for _, h in ipairs(F._dmg_scan_session(owner, F._netid.DEEPWIN,
                                                   targets, F._netid.OWNER_PATH)) do
                hits[#hits + 1] = h
            end
            if not F._netid.owner_vft_said then
                local mb = I.module_base and I.module_base()
                local vft = I.read_u64(owner)
                if mb and mb ~= 0 and _ptr_plausible(vft) and vft > mb then
                    F._netid.owner_vft_said = true
                    R.log(("[rsmm.damage] net id: owner object vftable rva 0x%x")
                          :format(vft - mb))
                end
            end
        end
    end
    -- The net object's VFTABLE, once. Its slot 0x18 returns the session this
    -- entity replicates to; decompiling that one function statically answers
    -- the whole question, and the RVA is the only thing the exe cannot tell me
    -- without a live instance.
    if not F._netid.vft_said then
        local obj = I.read_u64(nc + 0xb8)
        local mb = I.module_base and I.module_base()
        if _ptr_plausible(obj) and mb and mb ~= 0 then
            local vft = I.read_u64(obj)
            if _ptr_plausible(vft) and vft > mb then
                F._netid.vft_said = true
                R.log(("[rsmm.damage] net id: net object vftable rva 0x%x "
                       .. "(slot 0x18 = the session this entity replicates to)")
                      :format(vft - mb))
            end
        end
    end
    F._netid.hits[row.key] = hits
    -- Cap the per-row detail. Session 9e4f printed thirty of these, which is
    -- a lot of log for one fact ("this row reaches N locators naming M
    -- players"); the counts are what a reader acts on, the first few lines are
    -- enough to see the shape.
    local who, nwho = {}, 0
    for _, h in ipairs(hits) do
        if h.m and not who[h.m.name] then who[h.m.name] = true; nwho = nwho + 1 end
    end
    for i, h in ipairs(hits) do
        if i > 4 then break end
        R.log(("[rsmm.damage] net id: row %d (%s) netcomp%s +0x%x is %q (%s)")
              :format(row.slot, tostring(row.label),
                      F._dmg_netid_path_text(h.path),
                      h.off, tostring(h.m.name), h.kind))
    end
    if #hits > 4 then
        R.log(("[rsmm.damage] net id: row %d has %d locator(s) naming %d "
               .. "player(s) (showing 4)"):format(row.slot, #hits, nwho))
    end
    if #hits == 0 then
        R.log(("[rsmm.damage] net id: row %d (%s) netcomp 0x%x carries no lobby "
               .. "session id and no member pointer within +0x%x, direct or one hop")
              :format(row.slot, tostring(row.label), nc, F._netid.WIN))
    end
    return hits
end

--- Read the ADOPTED locator on one row and claim the member it names.
function F._dmg_apply_netid(row, targets)
    local L = F._netid
    if not L.off or not targets or not I.read_u64 then return false end
    local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
    if not _ptr_plausible(ent) then return false end
    local nc = R.net.component(ent)
    if not nc then return false end
    local base = F._dmg_netid_walk(nc, L.path)
    if not base then return false end
    local m
    if L.kind == "string" then
        local s = R.debug.stdstring_at and R.debug.stdstring_at(base + L.off)
        local hit = (type(s) == "string") and targets.hex[s:lower()] or nil
        m = hit and hit.m or nil
    elseif L.kind == "ptr" then
        local q = I.read_u64(base + L.off)
        -- The member table is rebuilt every pass, so a pointer that has since
        -- become shared stops naming anyone rather than keeping a stale answer.
        m = (type(q) == "number") and targets.ptr[q] or nil
    else
        local q = I.read_u64(base + L.off)
        local hit = (type(q) == "number") and targets.hex[("%016x"):format(q)] or nil
        m = hit and hit.m or nil
    end
    if not m then return false end
    local names = F._dmg_name_set()
    if not names or not names[m.name] then return false end
    return F._dmg_claim(row, names, m.name, ("net id +0x%x (%s)"):format(L.off, L.kind))
end

--- "netcomp +0xb8 -> +0x40 ->" -- the pointer path, for the log.
function F._dmg_netid_path_text(path)
    if not path then return "" end
    local t = {}
    for _, v in ipairs(path) do t[#t + 1] = ("+0x%x ->"):format(v) end
    return " " .. table.concat(t, " ")
end

--- A locator key, so hits from different rows can be compared. The PATH is
--- part of the identity: the same offset reached two different ways is two
--- different locators.
function F._dmg_netid_key(h)
    local p = h.path and table.concat(h.path, ",") or "-"
    return ("%s|%s|%x"):format(p, tostring(h.kind), h.off)
end

--- Walk an adopted locator's pointer path from the net component. Guarded, so
--- a path that no longer resolves returns nil instead of faulting.
function F._dmg_netid_walk(nc, path)
    local base = nc
    if not path then return base end
    for _, v in ipairs(path) do
        base = I.read_u64(base + v)
        if not _ptr_plausible(base) then return nil end
    end
    return base
end

--- Discovery, adoption and use, one pass. Background thread only.
---
--- Adoption needs BOTH gates, and both exist because a single-row agreement is
--- exactly what the hero-id probe had when it adopted +0x1b60, an offset the
--- engine never touches:
---
---   1. ANCHOR. The locator must name the LOCAL player on the local row.
---      Steam already told us who that is, so this is a fact to check against,
---      not another inference.
---   2. DISTINCTNESS. Read on every probed row, the locator must name a
---      DIFFERENT member each time. A field that answers the same on two rows
---      is a lobby-wide pointer, not an owner.
function F._dmg_netid_pass()
    -- The GUID join FIRST: it is the only one of these built on a field the
    -- disassembly names outright, and it costs a table lookup per (row,
    -- member) pair. Everything below is a search.
    if F._dmg_guid_join() then return true end
    -- FIRST, because it is the only one that is read rather than searched.
    if F._dmg_rak_join() then return true end
    -- Then the registry walk, then the hero-side scans.
    if F._dmg_conn_join() then return true end
    if F._dmg_peer_join() then return true end
    local targets = F._dmg_netid_targets()
    if not targets then return false end

    -- Adopted: two reads per unnamed row and nothing else.
    if F._netid.off then
        local named = false
        for _, row in ipairs(_dmg.order) do
            if not row.player and _ptr_plausible(row.key) then
                if F._dmg_apply_netid(row, targets) then named = true end
            end
        end
        return named
    end

    -- Discovery. Every row, once each; rows board over the first minute of a
    -- run, so this keeps running until a candidate survives both gates.
    for _, row in ipairs(_dmg.order) do
        if _ptr_plausible(row.key) then F._dmg_probe_netid(row, targets) end
    end

    local me
    local ok, nm = pcall(R.player.name)
    if ok and type(nm) == "string" and nm ~= "" then me = nm end
    if not me then return false end

    -- The anchor row's candidate locators: those that read the local player.
    local anchor
    for _, row in ipairs(_dmg.order) do
        if row.is_local then anchor = row break end
    end
    if not anchor or not F._netid.hits[anchor.key] then return false end
    local cand = {}
    for _, h in ipairs(F._netid.hits[anchor.key]) do
        if h.m and h.m.name == me then cand[F._dmg_netid_key(h)] = h end
    end
    if next(cand) == nil then return false end

    -- Distinctness across every other probed row.
    local seen = { [me] = true }
    local rows = 0
    for _, row in ipairs(_dmg.order) do
        if row ~= anchor and F._netid.hits[row.key] then
            rows = rows + 1
            local got = {}
            for _, h in ipairs(F._netid.hits[row.key]) do
                got[F._dmg_netid_key(h)] = h
            end
            for key, _ in pairs(cand) do
                local h = got[key]
                if not h or not h.m or seen[h.m.name] then
                    cand[key] = nil
                else
                    seen[h.m.name] = true
                end
            end
        end
    end
    -- One ally row is the minimum: agreeing with itself proves nothing.
    if rows == 0 then return false end

    local key, hit = next(cand)
    if not key then return false end
    if next(cand, key) ~= nil then
        -- Several locators survived. Any of them would work, but picking one
        -- at random makes the log unreproducible; take the lowest offset.
        for k, h in pairs(cand) do
            if h.off < hit.off then key, hit = k, h end
        end
    end
    F._netid.off, F._netid.path, F._netid.kind = hit.off, hit.path, hit.kind
    R.log(("[rsmm.damage] NET ID JOIN PROVEN: netcomp%s +0x%x (%s) holds the "
           .. "owning player's session id — it reads %q on this machine's own "
           .. "row and a different lobby member on every other row. Rows are "
           .. "named from the engine's replication data, not from a search.")
          :format(F._dmg_netid_path_text(hit.path), hit.off, hit.kind, me))
    return F._dmg_netid_pass()
end

--- Learn "this entity is driven by this session" from a networked event.
---
--- SELF-VERIFYING, and that is the entire design. The engine stamps ev+0x38
--- with the session id of the machine that raised the event
--- (NamedEvent_NetSend), and the lobby hands us each member's session id as a
--- string. Whether those two are the same value in different clothes is NOT
--- assumed: this only ever fires when a member's string matches the int64
--- EXACTLY. If the representations never line up, nothing matches, nobody is
--- named, and the board stays on placeholders -- which is the correct failure.
---
--- Contrast with every earlier mechanism: the memory sweep answered at a
--- different offset every time it "worked", and the hero-id probe adopted an
--- offset the engine never touches. Neither could tell you it was wrong. This
--- one is wrong only if it stays silent.
function F._dmg_note_session(entity, session)
    if not _ptr_plausible(entity) or type(session) ~= "number" then return end
    local prev = _dmg.sess_by_entity[entity]
    if prev == session then return end
    _dmg.sess_by_entity[entity] = session
    local m = F._dmg_session_member(session)
    if not m then
        -- Say it ONCE. "The join never matched" and "no events carried a
        -- session" are the same silence otherwise, and telling them apart is
        -- what a playtest is for.
        if not _dmg.sess_warned then
            _dmg.sess_warned = true
            R.log(("[rsmm.damage] event session 0x%x matches no lobby member "
                   .. "session id -- the join is not proven on this build, so "
                   .. "no row will be named from it"):format(session))
        end
        return
    end
    if not _dmg.sess_proven then
        _dmg.sess_proven = true
        R.log(("[rsmm.damage] SESSION JOIN PROVEN: event session 0x%x == lobby "
               .. "member %q. Rows are now named from the engine's own peer "
               .. "id, not from anything found by searching memory.")
              :format(session, m.name))
    end
    -- Bind every row whose controller owns this entity.
    for _, row in ipairs(_dmg.order) do
        if not row.player and _ptr_plausible(row.key) then
            local ent = I.read_u64(row.key + DMG.HERO_ENTITY_OFF)
            if ent == entity then
                local names = F._dmg_name_set()
                if names and names[m.name] then
                    F._dmg_claim(row, names, m.name, "session")
                end
            end
        end
    end
end

--- The ev+0x38 feeder, RETIRED.
---
--- Sessions c536, e736 and 014f all agree: every event the gameplay bus
--- dispatches is the base oCGameNamedEvent (one vftable, 0xf05aa8), and on the
--- base class +0x38 is not a peer -- the values are handles
--- (0x8146_00xx_00000004) and in one case a raw code address. It is the sender
--- only on oCGameNamedEventNetwork subclasses, which this bus never sees.
---
--- So this callback ran on EVERY gameplay event, for a field that could never
--- answer. On the analytics firehose that is the one place per-event Lua work
--- is actually felt, and the meter is the mod that gets blamed for it. The
--- owner lives at *(*(*(netcomp+0xb8)+0x100)+0x28) instead -- read once per
--- row, on the background tick, by F._dmg_probe_netid.
---
--- `R.net.event_session(ev)` is kept: a mod hooking a genuine network event
--- subclass can still read it, and that is where the field IS the sender.


--- Say ONCE how to put real names on this run's board.
---
--- The board cannot work it out on its own. The engine hands us a set of
--- players and a set of hero objects and nothing linking the two: the hero
--- entity carries no hero id, no player id and no name, so every row->player
--- answer the meter ever produced by searching memory was a coincidence (nine
--- "successes", nine different offsets, one of them provably the wrong person).
--- player_1..player_4 IS the mechanism, not a workaround for a missing one.
function F._dmg_label_hint()
    if _dmg.hinted then return end
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return end
    -- MORE ROWS THAN PLAYERS ON THE ROSTER. Session c236: four rows fighting,
    -- one lobby member all run -- this client parsed its OWN attributes three
    -- times and was never sent anybody else's. No join can help there, because
    -- there is no name to assign; the meter is missing the input, not the
    -- link. That case used to fall out of the `#members < 2` guard below and
    -- say nothing at all, which reads exactly like a broken join.
    if #members < 2 then
        local allies = 0
        for _, row in ipairs(_dmg.order) do
            if not row.is_local then allies = allies + 1 end
        end
        if allies > 0 and not _dmg.roster_warned then
            _dmg.roster_warned = true
            R.log(("[rsmm.damage] %d ally row(s) on the board but %d lobby "
                   .. "member(s) known — this client was never sent the other "
                   .. "players' lobby attributes, so no ally NAME exists to "
                   .. "assign this run (set player_1..player_4 in the config "
                   .. "to label them)"):format(allies, #members))
        end
        return
    end
    local unnamed = 0
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not _dmg.names[row.slot] then unnamed = unnamed + 1 end
    end
    if unnamed == 0 then return end
    _dmg.hinted = true
    R.log(("[rsmm.damage] %d row(s) have no proven name. This run's lobby: %s")
          :format(unnamed, F._dmg_roster_text(members)))
    R.log("[rsmm.damage] to label the board, set player_1..player_4 in the "
          .. "damage-meter config, in JOIN ORDER (row N = player_N). Those "
          .. "always win, and they are the only EXACT method: the engine gives "
          .. "the meter nothing that links a hero object to a player.")
end

--- True when a scan could actually change something: some ally row is still
--- wearing a "Player N" placeholder. Solo runs never qualify, so they never
--- pay for a scan.
function F._dmg_wants_lobby()
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and not _dmg.names[row.slot]
            and row.label:find("^Player %d") then
            return true
        end
    end
    return false
end

function F._dmg_new_row(key, is_local)
    local slot = #_dmg.order + 1
    local row = {
        key = key, slot = slot, is_local = is_local or false,
        label = F._dmg_label_for(slot, is_local),
        dealt = 0, taken = 0, hits = 0, best = 0, by_type = {},
        -- Damage the scenery filter dropped. Kept per row so a UI can show
        -- "and 4.2k into the furniture" instead of silently losing it.
        scenery = 0, scenery_hits = 0,
        -- Damage credited even though the victim could NOT be classified. The
        -- filter is fail-open on purpose (never hide a player's damage on a bad
        -- read), which means an unreadable prop family is counted as carry
        -- damage — so the amount that rests on that assumption is counted too,
        -- and a board that looks wrong can be checked against it instead of
        -- argued about.
        unknown = 0, unknown_hits = 0,
        -- Has ANY source ever reported damage taken for this row? `taken` is 0
        -- both for a player who was never hit and for a player this machine
        -- cannot observe, and those are not the same claim (see R.damage.board).
        taken_seen = false,
        first = F._dmg_now(), last = 0, samples = {}, recent = {},
        -- The chapter this row's controller was bound in. See F._dmg_rebind.
        epoch = _dmg.epoch,
    }
    _dmg.actors[key] = row
    _dmg.order[slot] = row
    return row
end

-- A player is reachable under several keys — its hero CONTROLLER (the engine's
-- bookkeeping hands us that), its ENTITY (the attack resolver hands us that),
-- and its NET id (replication hands us that). They must all land on ONE row, or
-- the same player shows up two or three times on the board and every share is
-- wrong. Alias keys point at the row; the net id gets its own index.
function F._dmg_alias(row, key)
    if key and _dmg.actors[key] == nil then _dmg.actors[key] = row end
end

function F._dmg_bind_netid(row, entity)
    if row.netid ~= nil or not entity then return end
    local id = F._dmg_net_id(entity)
    row.netid = id or false
    if id then _dmg.by_netid[id] = row end
end

--- May `prev` be handed to a controller it has never been bound to?
---
--- Only when its own controller cannot still be alive. See F._dmg_rebind for
--- why this is the whole safety of that function.
function F._dmg_may_rebind(prev, why)
    local newer = (prev.epoch or 0) < _dmg.epoch
    -- The exact join may also adopt a row that has gone quiet for longer than a
    -- chapter load; a GUESS may not, because a wrong match would then merge
    -- live allies the moment one of them stops attacking for 45 seconds.
    --
    -- Two reasons are guesses: the is-local byte, and the stale-ally rule
    -- below (which infers "same player" from "exactly one ally row's
    -- controller died over this chapter change"). The stale rule is safe
    -- BECAUSE it needs a chapter boundary -- a player who simply leaves
    -- mid-run also leaves a dead controller, and letting the idle path adopt
    -- that row would hand the next player to join their name and their total.
    local exact = why ~= "local flag" and why ~= DMG.STALE_ALLY
    local idle = exact and prev.last and prev.last > 0
                 and (F._dmg_now() - prev.last) >= DMG.REBIND_IDLE
    if newer or idle then return true end
    -- Say it, but not once per hit: this is the branch that keeps a player on
    -- the board, and a silent refusal looks exactly like the bug it prevents.
    _dmg.refusals = _dmg.refusals + 1
    if _dmg.refusals <= 4 then
        R.log(("[rsmm.damage] refused to merge a new controller into %s (%s) — "
               .. "same chapter (epoch %d) and that row is still active, so this "
               .. "is a DIFFERENT player, not a rebuilt controller")
              :format(prev.label or "?", why or "?", _dmg.epoch))
    end
    return false
end

--- Adopt an existing row for a hero controller we have not seen before.
---
--- The meter used to key rows by the controller pointer alone, which is stable
--- only WITHIN a chapter. Crossing into the next chapter rebuilds every hero
--- controller, so every player forked a second row: the 2026-08-17 evening log
--- shows seven rows for a four-player lobby, "Juice" listed twice (both flagged
--- as the local player), placeholder labels running to "Player 7", and the
--- abandoned rows frozen at 0.0 dps while the run continued. Nothing was lost
--- exactly — it was double-counted into two halves, which is worse, because
--- every `share` on the board is then wrong.
---
--- Two joins, strongest first:
---   1. the HERO ID, when the sweep has confirmed where it lives. Each player
---      in a run has a distinct hero, so this is exact.
---   2. the engine's is-local byte. There is exactly ONE local player, so a
---      second local controller is always the same person. This needs no RE at
---      all and fixes the duplicate that matters most (your own row).
---
--- BOTH joins are gated on the row's controller being GONE, which is the part
--- the first version left out — and a merge is far worse than the fork it
--- replaced. A four-player run (2026-08-18, session 29a8) boarded TWO rows: an
--- unseen controller inside the SAME chapter is another player standing next to
--- you, and this function adopted it as "the same person, new object". A
--- rebuild only happens at a chapter boundary, so that is what is required:
---
---   * hero-id join (exact): a later EPOCH, or a row nothing has credited for
---     REBIND_IDLE seconds (the fallback for a build whose chapter events never
---     arrive — a live player is never silent across a whole chapter load).
---   * is-local join (a guess — one misread byte at +0x1d88 folds every ally
---     onto your row): a later EPOCH, and nothing else.
---
--- Refusing costs a duplicate row, which is visible, self-explanatory and
--- keeps every player's damage. Merging silently deletes a player.
--- Returns the adopted row, or nil to let the caller board a new player.
function F._dmg_rebind(hero, is_local, entity)
    local id = F._dmg_hero_id(hero)
    local prev = id and _dmg.by_hero[id] or nil
    local why = prev and "hero " .. tostring(id) or nil
    -- No fallback scan over the rows here: every path that sets `hero_id` also
    -- writes `by_hero` (see F._dmg_backfill_ids), so a scan could only find what
    -- the index already has. It was written, could not be made to fail in the
    -- spec, and was deleted rather than shipped unexercised.
    if not prev and is_local then
        for _, r in ipairs(_dmg.order) do
            if r.is_local then prev, why = r, "local flag"; break end
        end
    end
    -- STALE-ROW ADOPTION, for the case that has neither key: an ALLY after a
    -- chapter change.
    --
    -- Session a34f, measured against the game's own end-of-run scoreboard:
    -- Ovilli 898436 vs 898071 (exact -- the local row rebinds on the is-local
    -- flag), but the two allies came out as FIVE rows, one player's damage
    -- split across three of them, because an ally has no hero id on this build
    -- and is not local, so every chapter handed them a fresh controller and
    -- `prev` stayed nil.
    --
    -- The rule is deliberately narrow, and refuses rather than guesses:
    -- the new controller must belong to a LATER epoch than the row, the row's
    -- own controller must no longer read as a live hero, and there must be
    -- EXACTLY ONE such row. Two stale rows means two allies respawned and
    -- nothing here can say which is which -- that forks, as before. In a34f
    -- only one ally's controller moved per chapter (the others kept their
    -- address), which is precisely the unambiguous case.
    if not prev and not is_local then
        local stale, n = nil, 0
        for _, r in ipairs(_dmg.order) do
            if not r.is_local and (r.epoch or 0) < _dmg.epoch
               and not (_ptr_plausible(r.key) and F._dmg_is_hero(r.key)) then
                stale, n = r, n + 1
            end
        end
        if n == 1 then
            prev, why = stale, DMG.STALE_ALLY
        elseif n > 1 then
            if not _dmg.stale_said then
                _dmg.stale_said = true
                R.log(("[rsmm.damage] %d ally row(s) went stale over this "
                       .. "chapter change — cannot say which is which, so the "
                       .. "new controller starts its own row"):format(n))
            end
        end
    end
    if not prev then return nil end
    if not F._dmg_may_rebind(prev, why) then return nil end
    _dmg.actors[hero] = prev
    prev.key = hero
    prev.epoch = _dmg.epoch          -- bound HERE now; see F._dmg_may_rebind
    prev.hero_id = id or prev.hero_id
    if prev.hero_id then _dmg.by_hero[prev.hero_id] = prev end
    -- New controller, so a sweep that came up empty on the old one deserves
    -- another go: the name may live on this object even though it did not live
    -- on the last. (A row that already knows who it is keeps that answer.)
    prev.own_done = nil
    F._dmg_alias(prev, entity)
    F._dmg_bind_netid(prev, entity)
    R.log(("[rsmm.damage] rebound %s to controller 0x%x (%s) — chapter change, "
           .. "not a new player"):format(prev.label, hero,
              id and ("hero " .. id) or "local flag"))
    return prev
end

-- Row for a hero CONTROLLER (source 1). The controller is what the SDK already
-- captures for the local player, and its +0x1d88 byte is the engine's own
-- "this is my player" flag — cheaper and more direct than a net lookup.
function F._dmg_row_for_hero(hero)
    if not _ptr_plausible(hero) then return nil end
    local row = _dmg.actors[hero]
    if row then return row end
    local is_local = I.read_u8(hero + DMG.HERO_ISLOCAL_OFF) == 1
    local entity = I.read_u64(hero + DMG.HERO_ENTITY_OFF)
    -- ONE line, once per session. The 2026-08-15 co-op run showed the net-id
    -- lookup refusing this entity, which also explains an empty `taken` column:
    -- if controller+0x8 is not the entity the rest of the SDK recognises, rows
    -- cannot be merged with the resolver's view of the same player. Dump the
    -- raw chain so the next session says which link is wrong instead of
    -- guessing.
    if not _dmg.probed then
        _dmg.probed = true
        R.log(string.format(
            "[rsmm.damage] identity probe: controller=0x%x hero?=%s inner=%s "
            .. "inner_hero?=%s mirror=%s local_byte=%s",
            hero, tostring(F._dmg_is_hero(hero)), tostring(entity),
            tostring(_ptr_plausible(entity) and F._dmg_is_hero(entity) or false),
            tostring(I.read_u64(hero + DMG.HERO_MIRROR_OFF)),
            tostring(I.read_u8(hero + DMG.HERO_ISLOCAL_OFF))))
    end
    -- The resolver may have boarded this player by entity already (it sees
    -- damage TAKEN before the hero deals any). Reuse that row.
    local existing = _ptr_plausible(entity) and _dmg.actors[entity] or nil
    if existing then
        _dmg.actors[hero] = existing
        return existing
    end
    -- A CHAPTER TRANSITION rebuilds every hero controller, so an unknown
    -- pointer usually means "same player, new object" — not a new player.
    -- Adopt the existing row instead of forking a second one for them.
    existing = F._dmg_rebind(hero, is_local, entity)
    if existing then return existing end
    row = F._dmg_new_row(hero, is_local)
    F._dmg_alias(row, entity)
    -- One line per player BOARDED, bounded. Session 29a8 was a four-player run
    -- that produced two rows, and the log could not say which join collapsed
    -- them: whether the is-local byte reads 1 for an ally (it must not — there
    -- is one local player) is a two-byte question that otherwise costs a whole
    -- playtest, in a timezone eight hours away.
    _dmg.boarded = (_dmg.boarded or 0) + 1
    if _dmg.boarded <= 8 then
        R.log(("[rsmm.damage] boarded row %d (%s): controller=0x%x local_byte=%s "
               .. "hero_id=%s epoch=%d"):format(
                  row.slot, row.label or "?", hero,
                  tostring(I.read_u8(hero + DMG.HERO_ISLOCAL_OFF)),
                  tostring(F._dmg_hero_id(hero)), _dmg.epoch))
    end
    -- Sweep for the hero-id field as soon as a SECOND row exists, rather than
    -- waiting for the next tick: the identity is needed by the time the next
    -- chapter loads, and a row boarded in the meantime would be un-rebindable.
    -- Self-gating (needs two rows and two identified lobby members) and
    -- bounded, so this is a no-op on all but a couple of calls per session.
    F._dmg_probe_hero_field()
    row.hero_id = F._dmg_hero_id(hero)
    if row.hero_id then _dmg.by_hero[row.hero_id] = row end
    F._dmg_bind_netid(row, entity)
    if is_local and _dmg.local_id == nil then
        _dmg.local_id = (row.netid ~= false and row.netid) or false
    end
    return row
end

-- Row for an ENTITY seen through the attack resolver (source 2). The negative
-- answer is cached: an enemy attacks hundreds of times a run and each miss
-- would otherwise be an engine lookup.
function F._dmg_row_for_entity(e)
    if not _ptr_plausible(e) then return nil end
    local row = _dmg.actors[e]
    if row then return row end
    if _dmg.seen[e] then return nil end
    if not F._dmg_is_hero(e) then _dmg.seen[e] = true; return nil end
    local id = F._dmg_net_id(e)
    if id and _dmg.by_netid[id] then
        row = _dmg.by_netid[id]
        F._dmg_alias(row, e)
        return row
    end
    local is_local = F._dmg_entity_is_local(e)
    -- THE LOCAL PLAYER IS ONE ROW, whatever object the engine hands us.
    --
    -- F._dmg_row_for_hero adopts an existing local row on the is-local flag
    -- ("same player, new object"); this path never did, so any swap of the
    -- hero OBJECT mid-chapter forked a second row for the same person. Sun
    -- Wukong's transform is the reported case (2026-08-24), and it is not the
    -- only one -- a respawn rebuilds the object too. The fork is not just a
    -- duplicate row: it is a row that can never be named (F._dmg_claim refuses
    -- a name another row already holds), so `wanted` in
    -- F._dmg_probe_owner_fast stays true for the rest of the run and the
    -- address-space sweep keeps running behind it. That is the stutter.
    --
    -- Sound by construction: there is exactly one local player per process,
    -- and the is-local byte is the engine's own answer (see
    -- F._dmg_entity_is_local). Allies get no such rule -- nothing on this
    -- build identifies them (the hero-id join is dead here), so an ally swap
    -- still forks rather than guessing which row it belongs to.
    if is_local then
        for _, r in ipairs(_dmg.order) do
            if r.is_local then
                F._dmg_alias(r, e)
                -- Bounded like the boarding log above. One line per swap is
                -- useful; a hero whose ability spawns a fresh object per cast
                -- would otherwise write one per cast for a whole run, into the
                -- log a player is asked to attach to a bug report.
                _dmg.swaps = (_dmg.swaps or 0) + 1
                if _dmg.swaps <= 8 then
                    R.log(("[rsmm.damage] local hero object changed to 0x%x "
                           .. "(transform or respawn) — reusing row %d, not a "
                           .. "new player%s"):format(e, r.slot,
                              _dmg.swaps == 8 and " (further swaps silent)" or ""))
                end
                return r
            end
        end
    end
    row = F._dmg_new_row(e, is_local)
    row.netid = id or false
    if id then _dmg.by_netid[id] = row end
    if is_local and _dmg.local_id == nil then
        _dmg.local_id = (row.netid ~= false and row.netid) or false
    end
    return row
end

function F._dmg_publish(row, amount, target, source, kind)
    if #_dmg.subs == 0 then return end
    local hit = { label = row.label, slot = row.slot, is_local = row.is_local,
                  amount = amount, target = target, source = source,
                  kind = kind or "dealt" }
    for _, cb in ipairs(_dmg.subs) do pcall(cb, hit) end
end

-- Has this row just been credited the same amount BY THE LOCAL APPLY PATH?
-- Sources 1 and 3 are disjoint in theory (the machine that applies a hit is not
-- the machine that receives its replication), but "in theory" is not a good
-- enough reason to risk double-counting a player's damage, which is the one
-- number this whole feature exists to get right.
--
-- Only cross-source echoes are dropped, never repeats within one source: a
-- multi-hit ability lands several IDENTICAL amounts inside a few frames, and an
-- amount-based filter that ignored the source would silently eat most of a
-- flurry's damage — the exact opposite of the bug it is there to prevent.
function F._dmg_is_echo(row, amount, now)
    local r = row.recent
    for i = #r, 1, -1 do
        if now - r[i].t > DMG.DEDUPE_WINDOW then
            table.remove(r, i)
        elseif math.abs(r[i].a - amount) < 0.01 then
            return true
        end
    end
    return false
end

-- Did ANY player's locally-applied hit just land for this amount?
--
-- Without a net id we cannot ask "is this replicated event about me", so the
-- test widens from one row to all of them: if this machine applied a hit of
-- the same size a moment ago, the event is that hit coming back, and crediting
-- it would invent a phantom player. Four rows and a 0.4s window — cheaper than
-- the engine call it replaces, and it cannot crash the game.
function F._dmg_echo_of_local(amount, now)
    for _, row in ipairs(_dmg.order) do
        if F._dmg_is_echo(row, amount, now) then return true end
    end
    return false
end

function F._dmg_credit(row, amount, target, source, kind)
    local now = F._dmg_now()
    row.dealt = row.dealt + amount
    row.hits  = row.hits + 1
    row.last  = now
    if amount > row.best then row.best = amount end
    if kind then row.by_type[kind] = (row.by_type[kind] or 0) + amount end
    local s = row.samples
    s[#s + 1] = { t = now, a = amount }
    -- Bound the window buffer: a long run at high APM would grow it without
    -- limit. Dropping the oldest half keeps the recent window (all `dps` reads)
    -- honest.
    if #s > DMG.SAMPLE_CAP then
        local keep = {}
        for i = #s // 2, #s do keep[#keep + 1] = s[i] end
        row.samples = keep
    end
    -- Only the local apply path seeds the echo filter; see F._dmg_is_echo.
    if source == "hero-stats" then
        local r = row.recent
        r[#r + 1] = { t = now, a = amount }
        if #r > 32 then table.remove(r, 1) end
    end
    F._dmg_publish(row, amount, target, source, "dealt")
end

-- One resolved hit from the attack resolver. `attacker` may be nil (an enemy
-- swinging), `target` may be nil. Damage landing on a HERO is never carry
-- damage — it is that hero's `taken`, and its attacker does not join the board.
function F._dmg_record(attacker, target, amount, source)
    if type(amount) ~= "number" or amount ~= amount then return end   -- NaN
    if amount <= _dmg.min then return end
    local victim = target and F._dmg_row_for_entity(target) or nil
    if victim then
        victim.taken = victim.taken + amount
        victim.taken_seen = true
        victim.last_hurt = F._dmg_now()
        F._dmg_publish(victim, amount, target, source, "taken")
        return
    end
    if not attacker then return end
    F._dmg_probe_victim(target, amount)
    -- With the hero-stat hook armed, dealt damage is counted there for EVERY
    -- hero (allies included); crediting it here as well would double it.
    if _dmg.stats_hooked then return end
    -- Same scenery filter as the bookkeeping path — this branch is the SOLO
    -- fallback on a build where the stat hook is unresolved, and it would
    -- otherwise keep counting fences on exactly the builds that need it most.
    local cls
    if _dmg.ignore_scenery and target then cls = F._dmg_is_enemy(target) end
    if cls == false then
        attacker.scenery = attacker.scenery + amount
        attacker.scenery_hits = attacker.scenery_hits + 1
        _dmg.scenery = _dmg.scenery + amount
        return
    end
    if _dmg.ignore_scenery and target and cls == nil then
        attacker.unknown = attacker.unknown + amount
        attacker.unknown_hits = attacker.unknown_hits + 1
    end
    F._dmg_credit(attacker, amount, target, source)
end

-- Source 1: the engine's per-hero bookkeeping. Observation only.
function F._dmg_observe_stats(hero, target, pd)
    if not _ptr_plausible(hero) or not _ptr_plausible(pd) then return end
    local valobj = I.read_u64(pd + DMG.PD_VALUE_OFF)
    if not _ptr_plausible(valobj) then return end
    local amount = I.read_f32(valobj + DMG.VALUE_AMOUNT_OFF)
    if type(amount) ~= "number" or amount ~= amount or amount <= _dmg.min then return end
    local row = F._dmg_row_for_hero(hero)
    if not row then return end
    -- What did they hit? The probe reports the first few distinct victims so
    -- the classification can be confirmed from a log rather than trusted.
    F._dmg_probe_victim(target, amount)
    -- Fences, jars, vegetation and mission props inflate a damage board
    -- without meaning anything. `unknown` (nil) counts: never drop a player's
    -- damage on a failed read.
    -- NOT `_dmg.ignore_scenery and F._dmg_is_enemy(target) or nil`: in Lua that
    -- idiom turns a classified `false` (the scenery answer this filter exists
    -- for) into `nil`, which is the fail-open branch.
    local cls
    if _dmg.ignore_scenery then cls = F._dmg_is_enemy(target) end
    if cls == false then
        row.scenery = row.scenery + amount
        row.scenery_hits = row.scenery_hits + 1
        _dmg.scenery = _dmg.scenery + amount
        return
    end
    if _dmg.ignore_scenery and cls == nil then
        -- Counted (fail-open), but counted SEPARATELY as well: this is the only
        -- number that says how much of a row rests on a victim the filter could
        -- not read.
        row.unknown = row.unknown + amount
        row.unknown_hits = row.unknown_hits + 1
    end
    -- Which ability landed it, for the per-ability breakdown. A source object
    -- that does not read back cleanly just means "other" — never a reason to
    -- drop the damage.
    local kind = "other"
    local src = I.read_u64(pd + DMG.PD_SOURCE_OFF)
    if _ptr_plausible(src) then
        local t = I.read_u16(src + DMG.SOURCE_TYPE_OFF)
        if type(t) == "number" and DMG.TYPES[t] then kind = DMG.TYPES[t] end
    end
    F._dmg_credit(row, amount, target, "hero-stats", kind)
end

-- Source 1b: the engine's per-hero damage-RECEIVED bookkeeping.
--
-- The resolver's victim path cannot name a hero on this build (is_grant_target
-- answers false for the controller AND for controller+0x8 — probed live on
-- 2026-08-15), so `taken` was empty for every player. This hook hands the
-- victim over as the same hero object the rows are already keyed by, so it
-- merges with no translation and covers allies too.
function F._dmg_observe_taken(victim, pd)
    if not _ptr_plausible(victim) or not _ptr_plausible(pd) then return end
    -- Same processed-damage record as the dealt side: hit-value object at
    -- +0x10, its f32 at +0x8. The one-shot probe reports the alternative
    -- (+0xa0) too, so a layout difference shows up as data in the log rather
    -- than as another silently empty column.
    local valobj = I.read_u64(pd + DMG.PD_VALUE_OFF)
    local amount = _ptr_plausible(valobj)
        and I.read_f32(valobj + DMG.VALUE_AMOUNT_OFF) or nil
    if not _dmg.probed_taken then
        _dmg.probed_taken = true
        local alt = I.read_u64(pd + DMG.PD_SOURCE_OFF)
        R.log(string.format(
            "[rsmm.damage] taken probe: victim=0x%x local=%s value@+0x10=%s "
            .. "alt@+0xa0=%s",
            victim, tostring(I.read_u8(victim + DMG.HERO_ISLOCAL_OFF)),
            tostring(amount),
            tostring(_ptr_plausible(alt) and I.read_f32(alt + 8) or nil)))
    end
    if type(amount) ~= "number" or amount ~= amount or amount <= 0 then return end
    local row = F._dmg_row_for_hero(victim)
    if not row then return end
    row.taken = row.taken + amount
    row.taken_seen = true
    row.last_hurt = F._dmg_now()
    F._dmg_publish(row, amount, victim, "hero-stats", "taken")
end

function F._dmg_arm_taken()
    if _dmg.taken_hooked then return true end
    if not (R.hook and I.resolve) then return false end
    local va = I.resolve(DMG.TAKEN_SYMBOL)
    if not va or va == 0 then return false end
    -- void(victim, processedDamage). Observation only: return nil without
    -- calling next, and the loader replays the original with the raw arguments.
    local ok, slot, why = pcall(R.hook, va, "vpp", function(victim, pd)
        if _dmg.on then pcall(F._dmg_observe_taken, victim, pd) end
        return nil
    end)
    if not ok then return false end
    if slot == nil and why ~= "already-hooked" then return false end
    _dmg.taken_hooked = true
    return true
end

function F._dmg_arm_stats()
    if _dmg.stats_hooked then return true end
    if not (R.hook and I.resolve) then return false end
    local va = I.resolve(DMG.STATS_SYMBOL)
    if not va or va == 0 then return false end
    -- void(hero, target, processedDamage, char). Read-only: return nil without
    -- calling next, and the loader replays the original with the raw arguments
    -- it received, so the engine's own bookkeeping is bit-for-bit unchanged.
    local ok, slot, why = pcall(R.hook, va, "vpppi", function(hero, target, pd)
        if _dmg.on then pcall(F._dmg_observe_stats, hero, target, pd) end
        return nil
    end)
    if not ok then return false end
    if slot == nil and why ~= "already-hooked" then return false end
    _dmg.stats_hooked = true
    return true
end

-- Source 2: the local attack resolver.
--
-- The signature must carry ALL FIVE arguments ("fpupff", matching the symbol's
-- cabi). The 5th is base damage, which the Windows x64 ABI passes on the
-- STACK; a 4-argument signature would still install, but `next()` would replay
-- the original with whatever happened to be in that stack slot — i.e. a random
-- base damage on every attack in the game.
function F._dmg_observe_attack(ctx, targets, amount)
    if type(amount) ~= "number" or amount <= 0 then return end
    if not _ptr_plausible(ctx) or not _ptr_plausible(targets) then return end
    local attacker = I.read_u64(ctx + DMG.CTX_ENTITY_OFF)
    -- `row` is nil when the attacker is not a hero — an enemy swinging. That is
    -- NOT a reason to stop: the swing may be landing on a hero, and that hero's
    -- `taken` is the other half of the board (and the "I just got hit" signal
    -- other mods subscribe to). F._dmg_record handles a nil attacker.
    local row = F._dmg_row_for_entity(attacker)
    local n = I.read_u32(targets + DMG.TGT_COUNT_OFF)
    local data = I.read_u64(targets + DMG.TGT_DATA_OFF)
    if type(n) ~= "number" or n <= 0 or not _ptr_plausible(data) then
        if row then F._dmg_record(row, nil, amount, "local") end
        return
    end
    if n > DMG.MAX_TARGETS then n = DMG.MAX_TARGETS end
    -- ONE line, once per session, for the other half of the board: `taken`
    -- was 0 for everyone in the 2026-08-15 co-op run, and the two candidate
    -- explanations (enemy attacks never reach this hook / the victim is not
    -- recognised as a hero) look identical from outside. Report the first
    -- swing that is NOT from a boarded hero, with what we make of its target.
    if not _dmg.probed_victim and not row then
        _dmg.probed_victim = true
        local first = I.read_u64(data)
        R.log(string.format(
            "[rsmm.damage] victim probe: attacker=%s target=%s hero?=%s boarded=%s",
            tostring(attacker), tostring(first),
            tostring(F._dmg_is_hero(first)),
            tostring(_dmg.actors[first] ~= nil)))
    end
    for i = 0, n - 1 do
        F._dmg_record(row, I.read_u64(data + i * 8), amount, "local")
    end
end

function F._dmg_arm_resolver()
    if _dmg.hooked then return true end
    if not (R.hook and I.resolve) then return false end
    local va = I.resolve(DMG.ATTACK_SYMBOL)
    if not va or va == 0 then return false end
    local ok, slot, why = pcall(R.hook, va, "fpupff",
        function(ctx, hitdef, targets, mul, base, nxt)
            local dmg = nxt(ctx, hitdef, targets, mul, base)
            if _dmg.on then pcall(F._dmg_observe_attack, ctx, targets, dmg) end
            return dmg
        end)
    if not ok then return false end
    if slot == nil and why ~= "already-hooked" then return false end
    _dmg.hooked = true
    return true
end

-- CHAPTER EPOCH. The engine rebuilds every hero controller when a chapter
-- loads, which is the ONLY moment a row may legitimately change controller (see
-- F._dmg_rebind). Both events are subscribed because neither is guaranteed:
-- GAME_END_NEXT_CHAPTER fires as the old chapter tears down, MAP_GENERATION_DONE
-- as the new one is built, and a build that emits only one of them still gets a
-- bump. Extra bumps are harmless — the epoch only ever UNLOCKS a rebind that a
-- pointer change already asked for.
function F._dmg_next_epoch(name)
    _dmg.epoch = _dmg.epoch + 1
    -- The identity scan's ADDRESSES die with the chapter. Every object it
    -- recorded is torn down here, so holding them is both useless (a rebuilt
    -- controller reaches none of them) and unsafe (freed memory is handed back
    -- out, so a stale address can come to sit next to an unrelated row and name
    -- it wrongly). Nothing else would ever have dropped them: `addrs_key` is
    -- the ROSTER, and a chapter change does not touch the roster, so an ally
    -- still unnamed at the boundary was served a dead cache for the rest of
    -- the run.
    --
    -- The CHAINS are deliberately KEPT. An offset into a rebuilt object is the
    -- one thing about a player that a chapter change does not move, so they are
    -- exactly what names the new controllers — in two reads, with no scan.
    F._own.addrs, F._own.addrs_key, F._own.queue = nil, nil, nil
    -- The net-id DISCOVERY cache dies with them, for the same reason and one
    -- worse: it is keyed by controller ADDRESS, and the allocator hands those
    -- addresses back out. A rebuilt controller landing where a previous row
    -- sat would read as already probed and inherit the OTHER player's hits,
    -- which is precisely how a locator gets adopted against the wrong person.
    -- The ADOPTED locator is kept on purpose -- an offset is what survives a
    -- chapter change; only the per-controller findings are stale.
    F._netid.probed, F._netid.hits = {}, {}
    -- The GUID report is per RUN, and a refusal must not outlive the rows it
    -- was about: new chapter, new controllers, new chance to resolve.
    F._netid.guid_said, F._netid.guid_done = false, false
    F._netid.peer_said, F._netid.peer_done = false, false
    -- A chapter rebuilds every hero controller, so every row's owner GUID is
    -- new — the one moment the raknet join has something it has not already
    -- answered. Without this it stays stood down for the rest of the run.
    F._netid.rak_done, F._netid.rak_idle, F._netid.rak_said = false, 0, false
    F._netid.peer_gen, F._netid.peer_scanned, F._netid.peer_hit = nil, {}, {}
    -- Sticky guesses belong to the board that made them: a chapter change
    -- re-adopts every controller, so slot N is not the same player it was.
    _dmg.guessed = {}
    -- Per RUN, not per process: a later run that also never receives the other
    -- players' attributes deserves to be told so too.
    _dmg.roster_warned = false
    if _dmg.on then
        R.log(("[rsmm.damage] chapter epoch %d (%s) — hero controllers may now "
               .. "be re-adopted"):format(_dmg.epoch, name))
    end
end
R.on("gameplay:GAME_END_NEXT_CHAPTER",
     function() F._dmg_next_epoch("GAME_END_NEXT_CHAPTER") end)
R.on("gameplay:MAP_GENERATION_DONE",
     function() F._dmg_next_epoch("MAP_GENERATION_DONE") end)

-- Source 3: replicated damage. Identity is the net id; the victim is the
-- entity the event was dispatched INTO, which the SDK can reach once it has
-- learned where a dispatcher sits inside its entity (R.give's
-- _learn_dispatcher_offset). Until then the victim is unknown and the hit is
-- credited to the attacker — the right default, since the overwhelming
-- majority of replicated damage is a player hitting an enemy.
R.on("gameplay:NETWORK_DAMAGE", function(ev)
    if not _dmg.on then return end
    local amount = tonumber(ev.value)
    local id = tonumber(ev.source_id or "")
    if not amount or amount <= _dmg.min or not id or id == -1 then return end
    -- Already counted here? Then it is this machine's own hit echoing back via
    -- another peer, not a new player's damage. (There is no net id to compare
    -- against any more — asking the engine for one crashed the game.)
    if F._dmg_echo_of_local(amount, F._dmg_now()) then return end
    -- VICTIM: prefer the payload's own `target_entity` (+0x60 of the embedded
    -- oCEntityHitData, decoded by event_fields.gen.h) over deriving it from the
    -- dispatcher. The derived guess was the only source here, which is part of
    -- why `taken` stayed 0 for every ally: the engine hands us the target
    -- outright and we were reconstructing it.
    local victim
    local target = tonumber(ev.target_entity or "")
    if target and target ~= 0 and _ptr_plausible(target) then victim = target end
    -- Read through the getter, never a captured value: the parent learns this
    -- offset at RUNTIME (it is nil until corroborated), so a load-time copy
    -- would be nil forever and silently drop every derived victim.
    local disp_off = _dispatcher_entity_off()
    if not victim and disp_off and type(ev.dispatcher) == "string" then
        local disp = tonumber(ev.dispatcher)
        if disp then victim = disp - disp_off end
    end
    -- One line, once: does the target we now decode actually correspond to a
    -- player row? If it never does, ally `taken` is not reachable from this
    -- event either and the answer is netcode, not attribution — but that has
    -- been ASSERTED in the symbol note without ever being measured.
    _dmg.net_victim_probes = (_dmg.net_victim_probes or 0) + 1
    if _dmg.net_victim_probes <= 4 then
        -- Lookup and classify ONLY, never create. _dmg_row_for_hero and
        -- _dmg_row_for_entity both CREATE a row for a plausible pointer, and
        -- most NETWORK_DAMAGE targets are enemies — probing with either would
        -- have put enemies on the scoreboard.
        --
        -- `hero?` is the question that decides the whole feature: if a hit on
        -- an ALLY never reaches this machine as NETWORK_DAMAGE, then ally
        -- `taken` is genuinely unavailable here (owner-side only, as the symbol
        -- note claims) and the column should say so rather than read 0. If it
        -- does arrive, the row just needs joining — the ally's row is keyed by
        -- net id, and entity->net-id is dead (see F._dmg_net_id), so that join
        -- has to be built deliberately rather than by creating a second row.
        local known = victim ~= nil and _dmg.actors[victim] or nil
        R.log(string.format(
            "[rsmm.damage] net victim probe #%d: target=%s row=%s hero?=%s",
            _dmg.net_victim_probes,
            target and string.format("0x%x", target) or "nil",
            known and (known.label or "?") or "none",
            tostring(victim ~= nil and F._dmg_is_hero(victim) or false)))
    end
    if victim and _dmg.actors[victim] then
        local row = _dmg.actors[victim]
        row.taken = row.taken + amount
        row.taken_seen = true
        row.last_hurt = F._dmg_now()
        F._dmg_publish(row, amount, victim, "net", "taken")
        return
    end
    local row = _dmg.by_netid[id]
    if not row then
        row = F._dmg_new_row("net:" .. string.format("%x", id), false)
        row.netid = id
        _dmg.by_netid[id] = row
    end
    F._dmg_credit(row, amount, victim, "net")
end)

--- Start metering. Idempotent; safe to call from `ready` or from run:start.
---   opts.window          seconds behind the rolling `dps` figure (default 10)
---   opts.min             ignore hits at or below this value (default 0)
---   opts.names           { [slot] = "Alice", ... } fixed labels by join order
---   opts.ignore_scenery  drop damage dealt to destructible props and mission
---                        objects (fences, jars, dream-shard nodes), counting
---                        only hits on gameplay enemies. Default FALSE, which
---                        is what matches the game's own end-screen total.
---                        Dropped damage is still totalled per row (`scenery`).
---   opts.probe           log the class of the first few distinct victims, so
---                        the enemy test can be confirmed from a log
---   opts.roster_rows     board every lobby member, including those who have
---                        not dealt damage yet, as a zeroed row (default false;
---                        the shipped meter turns it on)
---   opts.identity_scan   run the targeted address scan that puts real names
---                        on ally rows (default TRUE). It is bounded per
---                        roster, but it does read memory in the background
---                        while it runs; turn it off if that is felt. The
---                        board keeps its lobby names, marked as guesses.
function R.damage.enable(opts)
    opts = opts or {}
    if type(opts.window) == "number" and opts.window > 0 then _dmg.window = opts.window end
    if type(opts.min) == "number" then _dmg.min = opts.min end
    if opts.ignore_scenery ~= nil then _dmg.ignore_scenery = opts.ignore_scenery and true or false end
    -- Let unidentified rows borrow the leftover lobby names by join order. OFF
    -- by default: the mapping is a guess, and a wrong name on a real damage
    -- total cannot be spotted from inside the game.
    if opts.guess_names ~= nil then _dmg.guess_names = opts.guess_names and true or false end
    if opts.probe ~= nil then _dmg.probe = opts.probe and true or false end
    if opts.identity_hunt ~= nil then
        _dmg.identity_hunt = opts.identity_hunt and true or false
    end
    if opts.identity_scan ~= nil then
        _dmg.identity_scan = opts.identity_scan and true or false
    end
    if opts.roster_rows ~= nil then
        _dmg.roster_rows = opts.roster_rows and true or false
    end
    -- Seconds before a row whose sweep found nothing is swept again. A row is
    -- swept the moment it first deals damage and the object that identifies it
    -- may not be populated yet, so one pass is not an answer. 0 retries on the
    -- next tick, which is what the spec uses.
    if type(opts.retry_after) == "number" and opts.retry_after >= 0 then
        F._own.RETRY_AFTER = opts.retry_after
    end
    if type(opts.names) == "table" then
        for k, v in pairs(opts.names) do
            if type(k) == "number" and type(v) == "string" then _dmg.names[k] = v end
        end
    end
    if _dmg.on then return true end
    _dmg.on = true
    _dmg.started = F._dmg_now()
    local stats = F._dmg_arm_stats()
    local taken = F._dmg_arm_taken()
    local resolver = F._dmg_arm_resolver()
    R.log(("[rsmm.damage] metering on (window %ds, sources: %s, victims: %s%s)")
          :format(_dmg.window, R.damage.mode(),
                  _dmg.ignore_scenery and "enemies only" or "everything the game counts",
                  _dmg.probe and ", probe on" or ""))
    if _dmg.ignore_scenery and not F._dmg_enemy_vft() then
        R.log("[rsmm.damage] module base unavailable — the enemy test cannot "
              .. "run, so nothing is filtered (damage is never dropped on a "
              .. "failed read)")
    end
    F._dmg_lobby_refresh()
    if not stats then
        R.log("[rsmm.damage] " .. DMG.STATS_SYMBOL .. " unresolved on this game "
              .. "build — ALLY damage will only be counted where the engine "
              .. "replicates it to this machine")
    end
    if not taken then
        R.log("[rsmm.damage] " .. DMG.TAKEN_SYMBOL .. " unresolved on this game "
              .. "build — the `taken` column will stay empty")
    end
    if not resolver then
        R.log("[rsmm.damage] " .. DMG.ATTACK_SYMBOL .. " unresolved — solo "
              .. "damage has no fallback source on this build")
    end
    return true
end

--- Which sources are live, e.g. "hero-stats+resolver+net".
function R.damage.mode()
    local parts = {}
    if _dmg.stats_hooked then parts[#parts + 1] = "hero-stats" end
    if _dmg.taken_hooked then parts[#parts + 1] = "hero-taken" end
    if _dmg.hooked then parts[#parts + 1] = "resolver" end
    parts[#parts + 1] = "net"
    return table.concat(parts, "+")
end

--- Stop counting. The detours stay installed (uninstalling a hook another mod
--- may be using is worse than an early return in a callback) but nothing is
--- recorded while metering is off.
function R.damage.disable() _dmg.on = false end

function R.damage.enabled() return _dmg.on end

--- True when the engine's per-hero bookkeeping is hooked — the source that
--- makes ALLY damage countable. False means ally numbers depend on replication.
function R.damage.tracks_allies() return _dmg.stats_hooked end

--- True when the local attack resolver is hooked (damage taken, solo damage).
function R.damage.resolver_armed() return _dmg.hooked end

--- Is the scenery filter on? Pass a boolean to turn it on or off mid-run
--- (rows keep both totals, so toggling never loses a number).
function R.damage.ignore_scenery(on)
    if on ~= nil then _dmg.ignore_scenery = on and true or false end
    return _dmg.ignore_scenery
end

--- Damage the scenery filter dropped this run, across every player. 0 when
--- the filter is off — nothing is classified unless it is asked for.
function R.damage.scenery_total() return _dmg.scenery end

--- Offset of the controller field that carries the player's hero id, once the
--- sweep has confirmed ONE candidate — the identity that lets a row survive a
--- chapter change. nil while unknown or ambiguous, in which case rows fall back
--- to pointer identity (and the local player to the engine's is-local byte).
--- Worth putting in a bug report: it is the field a game patch is most likely
--- to move.
function R.damage.hero_id_offset() return HERO_ID_PROBE.off end

--- Classify a victim entity: true = gameplay enemy, false = scenery / prop /
--- mission object, nil = could not tell (and therefore never filtered).
function R.damage.is_enemy(entity) return F._dmg_is_enemy(entity) end

--- Per-hit callback: cb{ label, slot, is_local, amount, target, source, kind }.
--- `kind` is "dealt" (they damaged something that is not a hero) or "taken"
--- (they were damaged) — the reliable "I just got hit" signal, since the local
--- resolver sees enemy attacks on heroes too.
function R.damage.on(cb)
    assert(type(cb) == "function", "R.damage.on: cb must be function")
    _dmg.subs[#_dmg.subs + 1] = cb
    return #_dmg.subs
end

--- Name a player by join order (1 = first actor seen). Applies retroactively.
function R.damage.name(slot, label)
    assert(type(slot) == "number", "R.damage.name: slot must be number")
    assert(type(label) == "string", "R.damage.name: label must be string")
    _dmg.names[slot] = label
    local row = _dmg.order[slot]
    if row then row.label = label end
end

--- Clear every counter. Called on run boundaries by the meter mod; call it
--- yourself for per-chapter or per-fight scores.
function R.damage.reset()
    _dmg.actors, _dmg.order, _dmg.seen, _dmg.by_netid = {}, {}, {}, {}
    _dmg.by_hero = {}
    -- Per RUN, like _dmg.roster_warned: a fresh board deserves to be told its
    -- own forking story rather than inheriting the last run's silence.
    _dmg.fork_said = false
    _dmg.swaps = 0
    -- The sweep's CURSOR points at a row that no longer exists; the CHAIN is a
    -- fact about the engine's layout and stays.
    F._own.cursor = nil
    -- Same split for the member link: the cursor and the per-member "already
    -- swept" set point at dead rows, the learned OFFSET is layout and stays.
    -- The candidate table goes too — a hit is only evidence while the row it
    -- named still exists.
    _dmg.local_id, _dmg.started = nil, F._dmg_now()
    -- Victim pointers do not survive a run boundary: the next run reuses the
    -- addresses for different objects, so a kept cache would answer for the
    -- wrong entity. (The per-entry vftable check would catch most of that;
    -- dropping the table is cheaper and exact.)
    _dmg.vclass, _dmg.vclass_n, _dmg.scenery = {}, 0, 0
    -- The TYPE map is dropped with the entity cache: settings objects are
    -- reloaded per run, so a kept answer could be about a different asset.
    _dmg.sclass, _dmg.sclass_n = {}, 0
end

--- Total damage dealt to non-hero targets by everyone on the board.
function R.damage.total()
    local sum = 0
    for _, row in ipairs(_dmg.order) do sum = sum + row.dealt end
    return sum
end

--- The scoreboard, highest damage first — the ranking, recomputed on every
--- call so a caller polling it always shows the current order. Each row:
---   rank, label, slot, is_local, dealt, taken, hits, best, dps, share, by_type
---   scenery, scenery_hits, unknown, unknown_hits, taken_known, dps_window
--- `dps` is over the configured window (`dps_window`) and `share` is the
--- fraction of all damage dealt — the "who is carrying" number.
---
--- Three keys exist so a UI can say what it does NOT know, instead of printing
--- a confident zero: `unknown`/`unknown_hits` (damage counted against a victim
--- the scenery filter could not classify) and `taken_known` (false when nothing
--- has ever reported damage taken for this player, which is the normal state
--- for an ally).
--- Lobby members with no row yet, as zeroed placeholder rows.
---
--- A row is only ever created when damage is first attributed to a player, so
--- until someone lands a counted hit they simply are not on the board. For a
--- support that can be most of a chapter, or all of it: session 104f's "Artur"
--- carried 57% of the team's healing and did not appear until 110s into a 165s
--- chapter, which reads as "the meter lost a player", not as "he had not hit
--- anything yet".
---
--- Derived on every call and never stored in `_dmg.order`. That is the whole
--- safety argument: a placeholder owns no entity key, so it can never absorb a
--- hit, never forks at a chapter change, and vanishes the instant the real row
--- exists — the alternative (seeding a real row per member) would have to guess
--- which controller belongs to whom, which is the join that does not exist.
---
--- @param taken  set of names already on the board, by `player` AND by `label`
---               (a guessed label is still that player's row on screen, and
---               showing them twice is worse than showing them late).
function F._dmg_roster_rows(taken, next_slot)
    local ok, members = pcall(R.lobby.members)
    if not ok or type(members) ~= "table" then return {} end
    -- AN UNIDENTIFIED ROW BLOCKS THIS ENTIRELY. `taken` is a set of names, so a
    -- row still reading "Player 2" matches no member — and every member would
    -- then be added underneath it, including whoever that row already is. The
    -- board would show more rows than there are players and list somebody
    -- twice, which is a worse lie than listing them late. Once the lobby names
    -- land (guess_names, or the raknet join) this clears by itself.
    for _, row in ipairs(_dmg.order) do
        if not row.is_local and type(row.label) == "string"
           and row.label:match("^Player %d+$") then
            return {}
        end
    end
    local me, out = F._dmg_me(), {}
    for _, m in ipairs(members) do
        local nm = m.name
        if type(nm) == "string" and nm ~= "" and not taken[nm] then
            taken[nm] = true
            next_slot = next_slot + 1
            out[#out + 1] = {
                label = nm, slot = next_slot, is_local = (nm == me),
                hero_id = m.hero_id, label_guess = false, player = nil,
                -- Not a measurement of zero: this player has no row at all yet.
                -- A UI that wants to say "waiting" rather than "0" reads this.
                pending = true,
                dealt = 0, taken = 0, hits = 0, best = 0, last = 0,
                by_type = {}, scenery = 0, scenery_hits = 0,
                unknown = 0, unknown_hits = 0,
                taken_known = false,
                dps = 0, dps_window = _dmg.window, share = 0, idle = nil,
            }
        end
    end
    return out
end

function R.damage.board()
    local now = F._dmg_now()
    local cutoff = now - _dmg.window
    local total = R.damage.total()
    local out = {}
    for _, row in ipairs(_dmg.order) do
        local recent, keep = 0, {}
        for _, s in ipairs(row.samples) do
            if s.t >= cutoff then recent = recent + s.a; keep[#keep + 1] = s end
        end
        row.samples = keep
        local by_type = {}
        for k, v in pairs(row.by_type) do by_type[k] = v end
        out[#out + 1] = {
            label = row.label, slot = row.slot, is_local = row.is_local,
            -- The player's hero, when the identity sweep has found it. A UI can
            -- show the character, and it is what makes a row survive a chapter
            -- change, so it is worth surfacing rather than keeping internal.
            hero_id = row.hero_id, label_guess = row.label_guess,
            -- The lobby name this row was PROVEN to be (owner-name sweep), as
            -- opposed to `label`, which may still be a placeholder.
            player = row.player,
            dealt = row.dealt, taken = row.taken, hits = row.hits,
            best = row.best, last = row.last, by_type = by_type,
            scenery = row.scenery, scenery_hits = row.scenery_hits,
            -- Damage credited to a victim the filter could not classify. A UI
            -- that shows `hits` should show this too: it is the part of the row
            -- that may be prop chip damage counted as carry (see F._dmg_is_enemy).
            unknown = row.unknown, unknown_hits = row.unknown_hits,
            -- Is `taken = 0` a MEASUREMENT or an absence of one? On this build
            -- the per-hero damage-RECEIVED bookkeeping only fires for heroes
            -- this machine owns, so an ally reads 0 all run whether or not they
            -- were ever hit — and a scoreboard column that cannot tell the two
            -- apart is a wrong number, not a missing one. False until some
            -- source has actually reported a hit on this player.
            taken_known = row.taken_seen == true,
            dps = recent / _dmg.window,
            -- The window `dps` covers, so a caller can LABEL it. A report
            -- printed every 15s off a 10s window has a 5s blind spot, and a
            -- player who stopped attacking 11s ago reads 0.0 dps in a report
            -- that also shows their damage rising — which reads as a bug.
            dps_window = _dmg.window,
            share = total > 0 and (row.dealt / total) or 0,
            idle = row.last > 0 and (now - row.last) or nil,
        }
    end
    -- Everyone in the lobby appears, whether or not they have hit anything yet.
    -- Zero damage sorts last, so this never displaces a real row.
    if _dmg.roster_rows then
        local taken = {}
        for _, row in ipairs(out) do
            if row.player then taken[row.player] = true end
            if row.label then taken[row.label] = true end
        end
        for _, row in ipairs(F._dmg_roster_rows(taken, #_dmg.order)) do
            out[#out + 1] = row
        end
    end
    table.sort(out, function(a, b)
        if a.dealt ~= b.dealt then return a.dealt > b.dealt end
        return a.slot < b.slot
    end)
    for i, row in ipairs(out) do row.rank = i end
    return out
end

--- The player currently on top (or nil when nothing has been recorded).
function R.damage.leader()
    local board = R.damage.board()
    return board[1]
end

--- The engine's OWN run totals for the local player, straight off the hero's
--- stats record (+0x1db0) — the numbers the end-of-run summary shows. Useful
--- as a cross-check that the meter is counting the same fight the game is.
--- Returns nil when there is no captured hero yet; ally records exist but the
--- engine never fills them, which is the whole reason this module accumulates.
function R.damage.engine_totals()
    local hero = R.entity and R.entity.hero and R.entity.hero()
    if not _ptr_plausible(hero) then return nil end
    local rec = I.read_u64(hero + DMG.HERO_STATS_OFF)
    if not _ptr_plausible(rec) then return nil end
    return {
        dealt = I.read_u32(rec + DMG.STATS_TOTAL_OFF),
        best  = I.read_f32(rec + DMG.STATS_BEST_OFF),
    }
end

end
