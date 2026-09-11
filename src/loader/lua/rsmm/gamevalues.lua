-- R.game — the engine's own answers about the RUN, not about your hero.
--
-- WHAT THIS IS. The engine computes a large set of named gameplay values and
-- files each under a 32-bit key. R.stat already reads the slice that hangs off
-- the hero. This is the rest: 117 values covering the run, the map, the
-- day/night cycle, the session and the active game modifiers -- "Is in sandman
-- shop", "Reroll count", "Current chapter", "Is in overtime", "Is boss
-- awaken", "Active Enemies Count", "Is Session Host", "Revive token".
--
-- WHY IT MATTERS. Every one of these was previously inferred from whichever
-- gameplay event came closest, and those inferences are where mod trackers go
-- wrong. A rule like "never enter the shop twice" was unverifiable; the engine
-- has had a boolean for it all along.
--
-- WHERE THE TABLE CAME FROM. Harvested from the four registration routines in
-- the shipped exe (177 call sites), each of which pairs a key with the display
-- name and category the engine itself gives it. Both are preserved on every
-- entry so a reader can find the value in the game rather than trusting a
-- slug. The full method, and the off-by-one trap that makes the naive harvest
-- confidently wrong, are on the
-- g_GlobalEntityValueSceneContext_Tester_vftable symbol.
--
-- ⚠ THIS CRASHED THE GAME ONCE. READ THIS BEFORE CHANGING THE READER.
--
-- There are TWO different value-store shapes in this engine and they take
-- DIFFERENT readers. They are not distinguishable by "is there a pointer at
-- this offset", and assuming they were is what took the game down on
-- 2026-09-11 (dump 3c3943b7):
--
--   HERO store, reached as *(ctx+0x4c8)
--       keyed map at +0x80, override vector at +0xc0 with count at +0xc8.
--       Read by EntityValue_Get / EntityValue_Lookup. This is R.stat's world.
--
--   SCENE CONTEXT, what GameScene_FindContextByTester returns (ours)
--       keyed map at +0x98, end sentinel *(self+0xb0) + *(self+0x98).
--       Read by SceneContextValue_Find, which returns the union DIRECTLY
--       rather than filling an out-parameter.
--
-- The first version of this file identified our object correctly, by its +0x98
-- map, and then called EntityValue_Lookup on it anyway -- the reader for the
-- OTHER shape. That walks +0xc0/+0xc8, which on this object is not a vector,
-- and the engine faulted reading -1 with the "Is in sandman shop" key still in
-- r8. The lesson is not "probe harder": it is that a value store is not
-- interchangeable with a value store, and the reader must match the shape that
-- was identified.
--
-- So there is exactly ONE shape here now, it is checked positively (both +0x98
-- and +0xb0 present and plausible), and the only reader used is the one that
-- belongs to it. If the shape does not check out, or the reader does not
-- resolve on this build, every read returns nil and says why. No fallback to
-- the other reader exists, because that fallback is the crash.

return function(env)

for _, key in ipairs({ "I", "R", "_ptr_plausible" }) do
    if env[key] == nil then
        error("rsmm.gamevalues: parent did not pass env." .. key, 0)
    end
end

local I, R           = env.I, env.R
local _ptr_plausible = env._ptr_plausible

-- Published by hook_gamevalues.cpp. Slot 16 is the HERO's context; this is a
-- deliberately separate slot because they answer about different subjects and
-- letting one stand in for the other would make a read silently wrong rather
-- than absent.
local GLOBAL_CTX_SLOT = 17

local EV_INLINE_OFF = 0x08
local EV_VALUE_OFF  = 0x10
local EV_INLINE     = 4
-- The positive signature of a scene context. The engine's own reader does
-- `lea rbx,[self+0x98]` and then reads [rbx] and [rbx+0x18], so the keyed map
-- is an object EMBEDDED at +0x98 whose first field is the bucket array and
-- whose +0x18 (i.e. self+0xb0) is the extent added to that pointer to form the
-- end sentinel.
--
-- ⚠ +0xb0 IS A LENGTH, NOT A POINTER. The first version of this guard required
-- `map + extent` to be a plausible aligned pointer, and a live context was
-- refused for the whole session with +0x98=0xbdc8d80 (a perfectly good bucket
-- array) and +0xb0=0x1ff (511 -- a mask/extent). Their sum is not 8-aligned
-- and never will be. Check each field for what it actually is.
local SC_MAP_OFF    = 0x98
local SC_EXTENT_OFF = 0xb0
-- An extent far past this is not a hash map, it is a mis-read: the whole
-- registry is ~117 values, and the shipped contexts run to a few hundred.
local SC_EXTENT_MAX = 0x1000000
local EV_UNION_INLINE_OFF = 0x08   -- on the union the reader RETURNS
local EV_UNION_VALUE_OFF  = 0x10

local M = {}

R.game = {}

-- key table: slug -> { key, kind, name, group }. `name` and `group` are the
-- ENGINE's own strings, kept so R.game.describe can answer "what is this".
R.game.keys = {
    active_enemies_count                        = { key = 0x18c3664a, kind = "int", name = "Active Enemies Count", group = "Game" },
    ally_death_door                             = { key = 0x193c6829, kind = "f32", name = "Ally death door", group = "Cannot be revived (goto observer mode)" },
    ally_kill_streak                            = { key = 0x193c75ab, kind = "f32", name = "Ally kill streak", group = "Can still be revived (token, friend...)" },
    boss_sleep_duration                         = { key = 0x1cc8c666, kind = "f32", name = "Boss sleep duration", group = "Day/Night cycle" },
    boss_time_warning_duration                  = { key = 0x17de260d, kind = "f32", name = "Boss time warning duration", group = "Day/Night cycle" },
    boss_time_warning_ratio                     = { key = 0x1896a549, kind = "f32", name = "Boss time warning ratio", group = "Day/Night cycle" },
    build_version                               = { key = 0x147d2a83, kind = "int", name = "Build version", group = "System" },
    camp_difficulty_modifier                    = { key = 0x187aaecf, kind = "f32", name = "Camp Difficulty Modifier", group = "New Game Plus" },
    camp_difficulty_modifier_chance_to_apply    = { key = 0x187ab36e, kind = "f32", name = "Camp Difficulty Modifier Chance To Apply", group = "New Game Plus" },
    can_minimap_ping                            = { key = 0x19d94870, kind = "int", name = "Can minimap ping", group = "Game" },
    cheat_version                               = { key = 0x1b80cf17, kind = "int", name = "Cheat version", group = "Platform" },
    current_chapter                             = { key = 0x181d17fd, kind = "int", name = "Current chapter", group = "Player location" },
    current_cycle_ratio                         = { key = 0x17d8d89f, kind = "f32", name = "Current cycle ratio", group = "Day/Night cycle" },
    current_day_ratio                           = { key = 0x6b7e633e, kind = "f32", name = "Current day ratio", group = "Day/Night cycle" },
    current_dream_shards_count                  = { key = 0x171c27b5, kind = "int", name = "Current dream shards count", group = "Game" },
    current_hourglass_time                      = { key = 0x1e533557, kind = "f32", name = "Current hourglass time", group = "Day/Night cycle" },
    current_hourglass_time_ratio                = { key = 0x1e5c3007, kind = "f32", name = "Current hourglass time ratio", group = "Day/Night cycle" },
    current_night_ratio                         = { key = 0x75cc8184, kind = "f32", name = "Current night ratio", group = "Day/Night cycle" },
    cycle_playing                               = { key = 0x189e4ed5, kind = "f32", name = "Cycle playing", group = "Day/Night cycle" },
    damage_received_editor_icon_gooey_impact_png= { key = 0x17fdac33, kind = "f32", name = "Editor\\Icon\\gooey-impact.png", group = "Damage received" },
    dawn_and_dusk_half_duration                 = { key = 0x17d8d8a0, kind = "f32", name = "Dawn and dusk half duration (Duration of [Sunrise|Sunset|Moonrise|Moonset])", group = "Day/Night cycle" },
    day_duration                                = { key = 0x1859c278, kind = "f32", name = "Day duration", group = "Day/Night cycle" },
    day_night_phase_as_fmod_param               = { key = 0x8ae3fefe, kind = "f32", name = "Day/Night phase as FMod param (0.0=day, 1.0=night)", group = "Day/Night cycle" },
    deathdoor_hero_count                        = { key = 0x1a124d8d, kind = "int", name = "Deathdoor hero Count", group = "Multiplayer" },
    difficulty_xp_modifier                      = { key = 0x19bddb2e, kind = "f32", name = "Difficulty Xp Modifier", group = "Game" },
    dream_shard_costs_modifier                  = { key = 0x187310ec, kind = "f32", name = "Dream Shard Costs Modifier", group = "New Game Plus" },
    dream_shards_purchase_editor_icon_dt_shard_loss_png= { key = 0x1b5e6883, kind = "f32", name = "Editor\\Icon\\dt_shard_loss.png", group = "Dream shards purchase" },
    editor_icon_dt_damage_png                   = { key = 0x17df7d9e, kind = "f32", name = "Editor\\Icon\\dt_damage.png", group = "Bonus stat changed" },
    editor_icon_dt_ingredient_png               = { key = 0x1883f309, kind = "f32", name = "Editor\\Icon\\dt_ingredient.png", group = "Total Dream shards purchase" },
    editor_icon_dt_shard_gain_png               = { key = 0x12e831f3, kind = "f32", name = "Editor\\Icon\\dt_shard_gain.png", group = "Ally permadeath" },
    editor_icon_dt_shard_loss_png               = { key = 0x12e831f4, kind = "f32", name = "Editor\\Icon\\dt_shard_loss.png", group = "Gain dream shards" },
    editor_icon_gooey_impact_png                = { key = 0x17df7da0, kind = "f32", name = "Editor\\Icon\\gooey-impact.png", group = "Damage dealt" },
    gain_ingredient_editor_icon_dt_ingredient_png= { key = 0x1883f30a, kind = "f32", name = "Editor\\Icon\\dt_ingredient.png", group = "Gain ingredient(s)" },
    game_chrono_started                         = { key = 0x189512bc, kind = "int", name = "Game Chrono Started", group = "Game" },
    game_difficulty                             = { key = 0x18700873, kind = "f32", name = "Game Difficulty", group = "Game" },
    game_session_size                           = { key = 0x186c0ec3, kind = "f32", name = "Game Session Size", group = "Multiplayer" },
    game_ui_is_hidden                           = { key = 0x186332c8, kind = "f32", name = "Game Ui Is Hidden (F7)", group = "System" },
    gamemodifier_all_same_heroes                = { key = 0x1ab58780, kind = "f32", name = "GameModifier : All same heroes", group = "New Game Plus" },
    gamemodifier_day_only                       = { key = 0x1a8b53b4, kind = "f32", name = "GameModifier : Day only", group = "New Game Plus" },
    gamemodifier_less_day_night_half_cycle      = { key = 0x1a77d42d, kind = "f32", name = "GameModifier : Less day/night half cycle", group = "New Game Plus" },
    gamemodifier_more_experience                = { key = 0x1a77e2e4, kind = "f32", name = "GameModifier : More experience (from any source)", group = "New Game Plus" },
    gamemodifier_night_only                     = { key = 0x1a8b53bc, kind = "f32", name = "GameModifier : Night only", group = "New Game Plus" },
    gamemodifier_no_boss_timer                  = { key = 0x1a7945fc, kind = "f32", name = "GameModifier : No boss timer", group = "New Game Plus" },
    gamemodifier_no_minimap                     = { key = 0x99f27eac, kind = "f32", name = "GameModifier : No minimap", group = "New Game Plus" },
    gamemodifier_no_revive_token                = { key = 0x1a793d1a, kind = "int", name = "GameModifier : No revive token", group = "New Game Plus" },
    gamemodifier_one_chapter                    = { key = 0x1a8a3688, kind = "int", name = "GameModifier : One chapter", group = "New Game Plus" },
    gamemodifier_random_hero_at_map_start       = { key = 0x1ab183ab, kind = "f32", name = "GameModifier : Random hero at map start", group = "New Game Plus" },
    global_xp_modifier                          = { key = 0x187afd1d, kind = "f32", name = "Global Xp Modifier", group = "Game" },
    half_cycle_count_before_boss_awakens_modifier= { key = 0x187443de, kind = "int", name = "Half Cycle Count Before Boss Awakens Modifier", group = "New Game Plus" },
    hero_count                                  = { key = 0x1599ae4c, kind = "int", name = "Hero Count", group = "Multiplayer" },
    hero_death_door                             = { key = 0x18829b99, kind = "f32", name = "Hero death door", group = "Can still be revived (token, friend...)" },
    hero_permadeath                             = { key = 0x18829b9a, kind = "f32", name = "Hero permadeath", group = "Cannot be revived (goto observer mode)" },
    is_book_open                                = { key = 0x1c2c3925, kind = "int", name = "Is book open", group = "Player location" },
    -- Four values whose CATEGORY string the harvest could not recover (the
    -- register holding it was not re-assigned in their call blocks, so the
    -- parser saw nil and failed closed rather than inheriting the previous
    -- family's name). The NAMES are from the same argument slot that produced
    -- every other row and are as trustworthy; only the grouping is unknown.
    -- `reroll_count` is doubly attested: the reroll writer at 0x1403aaa47
    -- loads this exact key immediately after incrementing the counter.
    defeated_tumors                             = { key = 0xfc212e6d, kind = "int", name = "Defeated_Tumors", group = "(category not recovered)" },
    current_map_id                              = { key = 0x193495b8, kind = "int", name = "Current map id", group = "(category not recovered)" },
    reroll_count                                = { key = 0x1a922cd6, kind = "int", name = "Reroll count", group = "(category not recovered)" },
    bleed_duration                              = { key = 0x1aa7419b, kind = "f32", name = "Bleed duration", group = "(category not recovered)" },
    is_boss_awaken                              = { key = 0x17de260e, kind = "int", name = "Is boss awaken", group = "Day/Night cycle" },
    is_christmas_play_test_date                 = { key = 0x1c05eff2, kind = "int", name = "Is Christmas play test date", group = "System" },
    is_connected_to_session                     = { key = 0x15dbeb54, kind = "int", name = "Is Connected to Session", group = "Multiplayer" },
    is_day                                      = { key = 0x17d8d89b, kind = "int", name = "Is day", group = "Day/Night cycle" },
    is_game_menu_open                           = { key = 0x18ab4599, kind = "int", name = "Is game menu open", group = "Player location" },
    is_in_book_scene                            = { key = 0x1859c621, kind = "int", name = "Is in book scene", group = "Player location" },
    is_in_boss_fighting                         = { key = 0xf122efd2, kind = "int", name = "Is in boss fighting", group = "Player location" },
    is_in_cinematic                             = { key = 0x165e8282, kind = "int", name = "Is in cinematic", group = "Game" },
    is_in_defeat_sequence                       = { key = 0x18ab42db, kind = "int", name = "Is in defeat sequence", group = "Player location" },
    is_in_edition                               = { key = 0x16f76b02, kind = "int", name = "Is in edition", group = "System" },
    is_in_end_credits                           = { key = 0x1b6fc1fc, kind = "int", name = "Is in end credits", group = "Player location" },
    is_in_exploration                           = { key = 0x181d1800, kind = "int", name = "Is in exploration (OutDoor)", group = "Player location" },
    is_in_game_scene                            = { key = 0x1859c61f, kind = "int", name = "Is in game scene", group = "Player location" },
    is_in_loading_screen                        = { key = 0x181d17ff, kind = "int", name = "Is in loading screen", group = "Player location" },
    is_in_main_menu                             = { key = 0x181d17fe, kind = "int", name = "Is in main menu", group = "Player location" },
    is_in_overtime                              = { key = 0x1cd79255, kind = "int", name = "Is in overtime", group = "Day/Night cycle" },
    is_in_pause                                 = { key = 0x1e408ac5, kind = "int", name = "Is in pause", group = "Game" },
    is_in_play_game                             = { key = 0x16f76afa, kind = "int", name = "Is in play game (F5 or F6)", group = "System" },
    is_in_play_test                             = { key = 0x17e9a843, kind = "int", name = "Is in play test (F6)", group = "System" },
    is_in_safe_zone                             = { key = 0x18ab57ca, kind = "int", name = "Is in safe zone", group = "Player location" },
    is_in_sandman_shop                          = { key = 0xd53e08e5, kind = "int", name = "Is in sandman shop", group = "Player location" },
    is_in_tumor_fighting                        = { key = 0x181d1801, kind = "int", name = "Is in tumor fighting", group = "Player location" },
    is_in_victory_sequence                      = { key = 0x18ab42d9, kind = "int", name = "Is in victory sequence", group = "Player location" },
    is_last_game_win                            = { key = 0x18759e35, kind = "int", name = "Is last game win", group = "Game" },
    is_menu_open                                = { key = 0x162b18c9, kind = "int", name = "Is menu open", group = "Game" },
    is_mos_menu_open                            = { key = 0x1b4aab3e, kind = "int", name = "Is MOs menu open", group = "Game" },
    is_night                                    = { key = 0x17d8d89c, kind = "int", name = "Is night", group = "Day/Night cycle" },
    is_session_host                             = { key = 0x15dbeb6a, kind = "int", name = "Is Session Host", group = "Multiplayer" },
    is_skill_menu_open                          = { key = 0x162b18c8, kind = "int", name = "Is skill menu open", group = "Game" },
    keyboard_and_mouse_control                  = { key = 0x17147b56, kind = "f32", name = "Keyboard and mouse control", group = "Game" },
    last_game_exceptional_loot_count            = { key = 0x187ef021, kind = "int", name = "Last Game Exceptional Loot Count", group = "Game" },
    last_map_hourglass_time_ratio               = { key = 0x25c606ac, kind = "f32", name = "Last map hourglass time ratio", group = "Day/Night cycle" },
    last_second_damage_ratio_received           = { key = 0x17081d0b, kind = "f32", name = "Last second damage ratio received", group = "Game" },
    lastgame_standard_loot_count                = { key = 0x187ef01f, kind = "int", name = "LastGame Standard Loot Count", group = "Game" },
    local_peer_index                            = { key = 0x18bc7252, kind = "int", name = "Local peer index", group = "Game" },
    lose_dream_shards_editor_icon_dt_shard_loss_png= { key = 0x1a9cac95, kind = "f32", name = "Editor\\Icon\\dt_shard_loss.png", group = "Lose dream shards" },
    map_loading_description                     = { key = 0x19a5e99c, kind = "f32", name = "Map Loading Description", group = "Loading Screen" },
    map_loading_progress_ratio                  = { key = 0x19a60066, kind = "f32", name = "Map Loading Progress Ratio", group = "Loading Screen" },
    map_loading_sub_description                 = { key = 0x19a5e9a0, kind = "f32", name = "Map Loading Sub Description", group = "Loading Screen" },
    max_physic_anim_count                       = { key = 0x18e036a2, kind = "int", name = "Max physic anim count", group = "System" },
    melody_notes_in_spawning_tile               = { key = 0x1dfeeafa, kind = "int", name = "Melody notes in spawning tile", group = "Game" },
    melody_power_up_level_max_catchup           = { key = 0x70f3a3ae, kind = "f32", name = "Melody power up level max catchup", group = "Game" },
    night_and_day_cycle_phase                   = { key = 0x81c945ca, kind = "f32", name = "Night_And_Day_Cycle_Phase", group = "Day/Night cycle" },
    night_duration                              = { key = 0x1859c279, kind = "f32", name = "Night duration", group = "Day/Night cycle" },
    overtime_duration                           = { key = 0x1cd7923b, kind = "f32", name = "Overtime duration", group = "Day/Night cycle" },
    overtime_ratio                              = { key = 0x1ce9bb1a, kind = "f32", name = "Overtime ratio", group = "Day/Night cycle" },
    pad_control                                 = { key = 0x18a8c3b5, kind = "f32", name = "Pad control", group = "Game" },
    perma_death_hero_count                      = { key = 0x1a124d8e, kind = "int", name = "Perma-death hero Count", group = "Multiplayer" },
    play_time                                   = { key = 0x189e4b06, kind = "f32", name = "Play Time (s)", group = "Day/Night cycle" },
    player_location_is_in_exploration           = { key = 0x181d180d, kind = "int", name = "Is in exploration (InDoor)", group = "Player location" },
    random_seed                                 = { key = 0x17a117c6, kind = "int", name = "Random seed", group = "Game" },
    rank_meta_progression_level                 = { key = 0x18b0f2ab, kind = "f32", name = "Rank = Meta progression level", group = "Rank = Meta progression level" },
    rare_skill_chance_modifier                  = { key = 0x1871c2fa, kind = "f32", name = "Rare Skill Chance Modifier", group = "New Game Plus" },
    remaining_cycle_before_boss_awakens         = { key = 0x17de260c, kind = "f32", name = "Remaining cycle before boss awakens", group = "Day/Night cycle" },
    remaining_cycle_before_overtime             = { key = 0x1cdf6e8e, kind = "f32", name = "Remaining cycle before Overtime", group = "Day/Night cycle" },
    remaining_time_before_boss_awakens          = { key = 0x18ab6b3b, kind = "f32", name = "Remaining time before boss awakens", group = "Day/Night cycle" },
    remaining_time_before_overtime              = { key = 0x1cdf6e90, kind = "f32", name = "Remaining time before Overtime", group = "Day/Night cycle" },
    revive_token                                = { key = 0x1633db76, kind = "int", name = "Revive token", group = "Game" },
    screenshot_mode                             = { key = 0x18633ac4, kind = "f32", name = "Screenshot Mode", group = "System" },
    skip_cinematic                              = { key = 0x1984fd23, kind = "f32", name = "Skip cinematic", group = "Game" },
    slow_hourglass_ratio                        = { key = 0x2fd2db08, kind = "f32", name = "Slow hourglass ratio", group = "Day/Night cycle" },
    stormancer_app                              = { key = 0x1906600b, kind = "f32", name = "Stormancer App", group = "Multiplayer" },
    stormancer_server_endpoint                  = { key = 0x190648b4, kind = "f32", name = "Stormancer Server Endpoint", group = "Multiplayer" },
    stormancer_server_is_live                   = { key = 0x190648b0, kind = "f32", name = "Stormancer Server Is Live", group = "Multiplayer" },
}

-- Cached per pointer: the probe is several reads and a HUD mod polls often.
local _ok_for, _refused_for, _why = nil, nil, "no pointer published yet"

-- Is `p` a scene context? Both fields the engine's own reader uses must be
-- present and plausible. This is a positive test for ONE shape, not a choice
-- between two -- see the header for why that distinction is load-bearing.
local function _is_scene_context(p)
    local map = I.read_u64(p + SC_MAP_OFF)
    if not (map and map ~= 0 and _ptr_plausible(map)) then return false end
    local extent = I.read_u64(p + SC_EXTENT_OFF)
    if extent == nil or extent <= 0 or extent > SC_EXTENT_MAX then return false end
    -- The end sentinel must land in readable memory. That is the real test
    -- that these two fields belong together, and it says nothing about
    -- alignment, because an extent has no reason to preserve it.
    --
    -- Written out rather than chained: `a and b or c` silently falls through
    -- to `c` whenever b is false, which here would turn a FAILED bounds probe
    -- into a pass — the exact class of mistake this file already paid for.
    if I.read_u8(map + extent - 1) == nil then return false end
    return I.read_u32(map) ~= nil
end

local function _accept(p)
    if _ok_for == p then return true end
    _ok_for = nil
    if not _ptr_plausible(p) then
        _why = string.format("published pointer 0x%x is not plausible", p)
        return false
    end
    if not _is_scene_context(p) then
        _why = string.format(
            "published pointer 0x%x is not a scene context (+0x%x=0x%x, +0x%x=0x%x)",
            p, SC_MAP_OFF, I.read_u64(p + SC_MAP_OFF) or 0,
            SC_EXTENT_OFF, I.read_u64(p + SC_EXTENT_OFF) or 0)
        -- ONCE per pointer. A HUD mod polls every three seconds and asks for
        -- more than one value per poll, so an unthrottled refusal printed the
        -- same two lines forever and buried everything else in the file.
        if _refused_for ~= p then
            _refused_for = p
            R.log("[rsmm.game] REFUSING — " .. _why .. ". No engine read attempted.")
        end
        return false
    end
    _ok_for, _why = p, nil
    R.log(string.format("[rsmm.game] scene context 0x%x accepted "
                        .. "(keyed map at +0x%x); reading via SceneContextValue_Find",
                        p, SC_MAP_OFF))
    return true
end

local function _ctx()
    if not I.shared_get then
        _why = "this loader is too old to publish a global value context"
        return nil
    end
    local ok, p = pcall(I.shared_get, GLOBAL_CTX_SLOT)
    if not (ok and type(p) == "number" and p ~= 0) then
        _why = "slot empty — see the [game-values] lines in the loader log"
        return nil
    end
    if not _accept(p) then return nil end
    return p
end

--- Why the last read returned nil, or nil when the last read worked.
function R.game.why() return _why end

--- Read one registered value by slug. Returns a number (or boolean for an
--- `is_`/`can_` value), or nil when the context is unavailable or the value is
--- not held inline. Never raises.
function R.game.get(name)
    local spec = R.game.keys[name]
    if not spec then
        R.log("[rsmm.game] unknown value: " .. tostring(name))
        return nil
    end
    local p = _ctx()
    if not p then return nil end
    -- Returns the union POINTER, or 0 when this context does not hold the key.
    -- No out-buffer: that is the other shape's reader, and using it here is the
    -- crash this file exists to not repeat.
    local ok, u = pcall(R.engine.call, "SceneContextValue_Find", p, spec.key)
    if not ok then
        -- Two different causes, and saying only one of them sent the last
        -- debugging session down the wrong path: the symbol may not resolve on
        -- this build, or the call itself may have been rejected. Name both.
        _why = string.format(
            "the engine read for %q failed — SceneContextValue_Find either does "
            .. "not resolve on this build or refused the call: %s",
            name, tostring(u))
        return nil
    end
    if type(u) ~= "number" or u == 0 or not _ptr_plausible(u) then
        _why = string.format("%q is not held by this scene context", name)
        return nil
    end
    if I.read_u32(u + EV_UNION_INLINE_OFF) ~= EV_INLINE then
        _why = string.format("%q did not come back inline", name)
        return nil
    end
    _why = nil
    return (spec.kind == "int") and I.read_u32(u + EV_UNION_VALUE_OFF)
                                 or I.read_f32(u + EV_UNION_VALUE_OFF)
end

--- Same as get, but returns a boolean. For the many `Is ...` / `Can ...`
--- values, which the engine stores as 0/1.
function R.game.flag(name)
    local v = R.game.get(name)
    if v == nil then return nil end
    return v ~= 0
end

--- The engine's own name and category for a slug, so a mod can show the value
--- the way the game's own tooling names it.
function R.game.describe(name)
    local s = R.game.keys[name]
    if not s then return nil end
    return s.name, s.group, s.kind
end

--- Every known slug, sorted.
function R.game.names()
    local t = {}
    for k in pairs(R.game.keys) do t[#t + 1] = k end
    table.sort(t)
    return t
end

--- Whether a read can land right now, without performing one.
function R.game.ready() return (_ctx()) ~= nil end

return M

end
