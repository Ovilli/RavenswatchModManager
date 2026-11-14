-- R.ui — what the game's UI is showing.
--
--     if R.ui.is_open("menu") then return end           -- pause menu, main menu, ...
--     R.on("ui:open",  function(e) R.log(e.kind .. " " .. e.class) end)
--     R.on("ui:close", function(e) ... end)
--
-- WHY THIS EXISTS. Mods kept answering "is a menu up?" from scene flags, and
-- each kept its own list (R.input, keybinds.lua, run_flow.lua). The flags are a
-- poor signal: the pause menu and its social sub-panel both write
-- is_game_menu_open, so closing the sub-panel cleared it while the pause menu
-- was still up. R.ui tracks the UI controllers themselves.
--
-- HOW. Every UI controller is an entity component, shown and hidden by the
-- engine's two component runners. The loader detours both, keeps only the UI
-- controller classes below (matched by vftable, found by RTTI name), and reads
-- each one's own active bit, so nested shows and hides cannot desync it. See
-- src/loader/include/hook_ui_state.h.
--
-- KINDS:
--   menu     pause (EscapeGameMenu), MainMenu, SelectionMenu, SandmanMenu,
--            InventoryMenu, MagicMirrorMenu, SocialOptionsMenu
--   book     the 3D book (BookMenu)
--   modal    Modal, EULAModal, MultiplayerModal, MyNaconModal
--   loading  LoadingScreen
--   page     a page of the book: PlayPage, HeroSelectPage, HeroPage,
--            HeroStoryPage, MerlinAbilitiesPage, CompendiumPage,
--            HeroesCompendiumPage, ItemsCompendiumPage, MemoriesCompendiumPage,
--            TutorialPage, ChallengesPage, SelectChallengePage,
--            CustomizeChallengePage, SocialPage, OptionsPage, RecapPage,
--            ResultStatsPage, ScorePage. R.ui.page() names the one shown.
--
-- EVENTS: `ui:open` / `ui:close` with { kind, class, ptr }. They fire after the
-- engine has finished the show or hide, never in the middle of it.
--
-- ARMED AT STARTUP. The loader installs the detours at init, so controllers
-- opened before any mod asks are tracked; the per-component cost is one vftable
-- compare against ~31 entries. M.arm() is kept as a harmless no-op that reports
-- the result. RSMM_DISABLE_UI_STATE=1 turns it off. When it cannot arm,
-- is_open() returns nil (not false): "unknown" is not "closed".
--
-- ⚠ UNPROVEN IN GAME (PR #110, 2026-11-14). The static RE is done on build
-- b9c3642884a8; still to confirm in a playtest: which thread the runners run
-- on, how menus nest, and whether the book controller stays active in normal
-- play.

local M = {}

local R, I

local KINDS = { menu = true, book = true, modal = true, loading = true, page = true }

local _armed, _why = false, nil

--- Install the detours if not yet done. Returns true, or false + why.
function M.arm()
    if _armed then return true end
    if not I.ui_state_arm then return false, "loader too old for R.ui" end
    local ok, why = I.ui_state_arm()
    _armed, _why = ok and true or false, why
    if not ok then R.log("[R.ui] not armed: " .. tostring(why)) end
    return _armed, why
end

--- Is a `kind` ("menu", "book", "modal", "loading", "page") open now? true/false, or
--- nil + why when R.ui cannot tell (not armed).
function M.is_open(kind)
    assert(KINDS[kind], "R.ui.is_open: kind is menu, book, modal, loading or page")
    local ok, why = M.arm()
    if not ok then return nil, why end
    local n = I.ui_state_count(kind)
    if n == nil then return nil, "not armed" end
    return n > 0
end

--- How many controllers of `kind` are open (nested menus count once each), or
--- nil + why when not armed.
function M.count(kind)
    assert(KINDS[kind], "R.ui.count: kind is menu, book, modal, loading or page")
    local ok, why = M.arm()
    if not ok then return nil, why end
    return I.ui_state_count(kind)
end

--- Every open controller, oldest first: { {kind, class, ptr}, ... }; nil + why
--- when not armed.
function M.open()
    local ok, why = M.arm()
    if not ok then return nil, why end
    return I.ui_state_open()
end

--- Is any of the kinds open? With no argument: menu, book or modal (a loading
--- screen is not "a UI the player is in"). nil + why when not armed.
function M.any(...)
    local kinds = { ... }
    if #kinds == 0 then kinds = { "menu", "book", "modal" } end
    for _, k in ipairs(kinds) do
        local open, why = M.is_open(k)
        if open == nil then return nil, why end
        if open then return true end
    end
    return false
end

--- The book page being shown ("HeroSelectPage", "TutorialPage", ...): the most
--- recently opened page controller still open. nil when no page is open; nil +
--- why when not armed.
function M.page()
    local list, why = M.open()
    if not list then return nil, why end
    for i = #list, 1, -1 do
        if list[i].kind == "page" then return list[i].class end
    end
    return nil
end

--- Armed state: true, or false + why.
function M.status()
    return _armed, _why
end

return function(env)
    R, I = env.R, env.I
    return M
end
