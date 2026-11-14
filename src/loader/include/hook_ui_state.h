#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace rsmm {

// What the game's UI is showing (R.ui, PR #110).
//
// Every UI controller is an entity component, and every component is shown
// and hidden by the engine's two component runners: EntityComponent_RunActivate
// (calls vftable slot 28 = UiController_OnShow) and EntityComponent_RunDeactivate
// (slot 29 = OnHide). Both are detoured. They run for EVERY component in the
// game (states, timers, effects), so the detour rejects anything whose vftable
// is not one of the UI controller classes below before doing any other work.
//
// Open/closed is the component's own active bit (flags byte +0x64, bit 0x08),
// read after the original returns and compared with our record. The runners
// recurse through each other (a pending deactivate inside an activate), so
// counting calls would drift; reading the bit cannot.
//
// The classes are found by RTTI NAME at arm time (type descriptor -> complete
// object locator -> vftable), not by address, so a game patch that moves the
// vtables does not need a new symbol. A class whose RTTI is missing is skipped
// and logged; none found = not armed.
//
// Armed lazily: the first R.ui call or R.on("ui:open"/"ui:close") from Lua
// installs the hooks, so a session where no mod asks pays nothing.
// RSMM_DISABLE_UI_STATE=1 refuses to arm.

// Page = a page of the 3D book (hero selection, hero page, compendium tabs,
// tutorial, challenges, options, ...): one controller per page, so which one is
// active says where in the book the player is.
enum class UiKind : int { Menu = 0, Book = 1, Modal = 2, Loading = 3, Page = 4, Count = 5 };

// Install the runner detours (idempotent). False + why when not armed.
bool ui_state_arm(std::string* why = nullptr);
bool ui_state_armed();

// How many controllers of `kind` are open now; -1 when not armed. Prunes any
// tracked controller whose memory is gone or that is no longer active, so a
// controller destroyed without a deactivate cannot leave a kind stuck open.
int ui_state_count(UiKind kind);

struct UiOpen {
    std::uintptr_t ptr;
    UiKind kind;
    const char* label;   // "EscapeGameMenu", "Modal", ... (static storage)
};
// Every open controller, oldest first.
std::vector<UiOpen> ui_state_open();

// "menu" / "book" / "modal" / "loading" / "page"; nullptr when out of range.
const char* ui_kind_name(UiKind kind);
// Inverse of ui_kind_name; false for an unknown name.
bool ui_kind_from_name(const char* name, UiKind* out);

} // namespace rsmm
