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
// Armed at loader startup (install_ui_state_hooks), so controllers that open
// before any mod asks are still tracked. The per-component cost is one vftable
// compare against ~31 entries. RSMM_DISABLE_UI_STATE=1 refuses to arm.

// Page = a page of the 3D book (hero selection, hero page, compendium tabs,
// tutorial, challenges, options, ...): one controller per page, so which one is
// active says where in the book the player is.
// Root = session-long controllers (MainMenu, BookMenu) active from boot to
// shutdown; NOT a visibility signal. Book = BookMenu's mode state machine
// (BM+0x68): the book is shown when its mode is main-menu / Settings / score /
// credits, not when closed. No controller class maps to Book; it is read from
// the mode (BookMenu_GetMode) and its changes come from a detour on
// BookMenu_SetModeState, which emits ui:open / ui:close kind "book" with a
// `which` ("main", "settings", "score", "credits").
enum class UiKind : int { Menu = 0, Book = 1, Modal = 2, Loading = 3, Page = 4, Root = 5, Count = 6 };

// Install the runner detours (idempotent). False + why when not armed.
bool ui_state_arm(std::string* why = nullptr);
// Loader-init entry point (dllmain's install_guarded list): ui_state_arm().
bool install_ui_state_hooks();
bool ui_state_armed();

// How many controllers of `kind` are open now; -1 when not armed. Book is 1
// when the book's mode is 0..3, else 0 (it has no controller class of its own). Prunes any
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

// The book's mode (BookMenu_GetMode): 0 main-menu book, 1 Settings from pause,
// 2 Score, 3 Credits, 4 closed, 5 unknown handler. -1 when not armed, or no
// BookMenu is tracked, or the symbol is unresolved. Safe from any thread: the
// BookMenu pointer is checked (readable, vftable) before the engine call.
int ui_state_book_mode();
// "main" / "settings" / "score" / "credits" for modes 0..3, else nullptr.
const char* ui_book_mode_name(int mode);

// The book page being shown: BookMenu's current page (BM+0x1e0) followed down
// its child chain (+0xd8) to the leaf, mapped to a Page-kind label. Static
// string, or nullptr (not armed, book closed, no page, unknown class). Every
// read is guarded; safe from any thread.
const char* ui_state_page();

// "menu" / "book" / "modal" / "loading" / "page" / "root"; nullptr when out of range.
const char* ui_kind_name(UiKind kind);
// Inverse of ui_kind_name; false for an unknown name.
bool ui_kind_from_name(const char* name, UiKind* out);

} // namespace rsmm
