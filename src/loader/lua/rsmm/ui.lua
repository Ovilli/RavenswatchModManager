-- R.ui — what the game's UI is showing.
--
--     if R.ui.is_open("menu") then return end           -- pause menu, Sandman, inventory, ...
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
--   menu     pause (EscapeGameMenu), SelectionMenu, SandmanMenu,
--            InventoryMenu, MagicMirrorMenu, SocialOptionsMenu
--   root     MainMenu and BookMenu, the session-long controllers: active from
--            boot to shutdown, so NOT a visibility signal.
--   book     the 3D book is shown: BookMenu's mode is main-menu book, Settings
--            from pause, score or credits (not closed). Read from the mode, not
--            from the controller. R.ui.book() names which.
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
-- engine has finished the show or hide, never in the middle of it. Book events
-- (kind "book", class "BookMenu") also carry `which`: "main", "settings",
-- "score" or "credits". They come from a detour on the book's mode setter, so a
-- change of book (e.g. score to main menu) is a close of one and an open of the
-- other.
--
-- ARMED AT STARTUP. The loader installs the detours at init, so controllers
-- opened before any mod asks are tracked; the per-component cost is one vftable
-- compare against ~31 entries. M.arm() is kept as a harmless no-op that reports
-- the result. RSMM_DISABLE_UI_STATE=1 turns it off. When it cannot arm,
-- is_open() returns nil (not false): "unknown" is not "closed".
--
-- PHASE 1 PROBE (2026-11-14). Tracked controllers run on the engine main thread,
-- except MainMenu at boot. MainMenu and BookMenu are activated once near boot and
-- deactivated only at game shutdown, so activation cannot say whether the book is
-- showing: that is what the `book` kind and R.ui.book() read from BookMenu's mode
-- instead. The `page` kind's count and events still follow controller activation:
-- the main-menu book activates all five tab pages at once, so page() is the
-- reliable answer to "which page".

local M = {}

local R, I

local KINDS = { menu = true, book = true, modal = true, loading = true, page = true,
                 root = true }

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

--- Is a `kind` ("menu", "book", "modal", "loading", "page", "root") open now?
--- true/false, or nil + why when R.ui cannot tell (not armed; for "book", an
--- unknown book mode). "book" is true while any book is shown; "root" counts
--- the session-long controllers.
function M.is_open(kind)
    assert(KINDS[kind], "R.ui.is_open: kind is menu, book, modal, loading, page or root")
    local ok, why = M.arm()
    if not ok then return nil, why end
    local n, nwhy = I.ui_state_count(kind)
    if n == nil then return nil, nwhy or "not armed" end
    return n > 0
end

--- How many controllers of `kind` are open (nested menus count once each; book
--- is 1 or 0), or nil + why when not armed or the book mode is unknown.
function M.count(kind)
    assert(KINDS[kind], "R.ui.count: kind is menu, book, modal, loading, page or root")
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
--- screen is not "a UI the player is in"). true as soon as one kind is open,
--- even when another is unknown; nil + why only when none is open and at least
--- one could not be read (not armed, unknown book mode).
function M.any(...)
    local kinds = { ... }
    if #kinds == 0 then kinds = { "menu", "book", "modal" } end
    local unknown
    for _, k in ipairs(kinds) do
        local open, why = M.is_open(k)
        if open then return true end
        if open == nil and unknown == nil then unknown = why or "unknown" end
    end
    if unknown then return nil, unknown end
    return false
end

--- Which book is shown: "main" (the main-menu book), "settings" (Settings opened
--- from the pause menu), "score" or "credits"; nil when no book is shown; nil +
--- why when R.ui cannot tell (not armed, unknown mode).
function M.book()
    local ok, why = M.arm()
    if not ok then return nil, why end
    if not I.ui_state_book then return nil, "loader too old for R.ui.book" end
    return I.ui_state_book()
end

--- The book page being shown ("PlayPage", "OptionsPage", "CreditsPage", ...), or
--- nil when no book is shown; nil + why when not armed. It follows the book's
--- current page and its open child pages, so main-menu tab switches are seen
--- and Credits (a child of the Settings page that shares the Tuto page's class)
--- reads "CreditsPage", not "TutorialPage".
function M.page()
    local ok, why = M.arm()
    if not ok then return nil, why end
    if not I.ui_state_page then return nil, "loader too old for R.ui.page" end
    return I.ui_state_page()
end

--- Armed state: true, or false + why.
function M.status()
    return _armed, _why
end

return function(env)
    R, I = env.R, env.I
    return M
end
