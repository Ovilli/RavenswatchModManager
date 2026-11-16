#pragma once
#include <string>

namespace rsmm {

// Native mod menu: the model behind the Mods page in the game's book.
//
// The page itself is a R.ui.menus page (hook_book_pages.h) registered by
// rsmm/mods_menu.lua in the loader-owned Lua state. The Settings page is not
// laid out in data: its controller (oe::dt::BookOptionsUiControllerEntityCpnt)
// builds every tab and row in code. We detour the last of its tab builders and,
// after it returns, hand over to the book pages, which add the "Mods" entry
// and build the page's categories and rows.
//
// This file owns the data and its persistence: per installed mod, an Off/On
// row (applied by `rsmm apply` on the next launch) and a row per
// config_schema.toml field (written to the mod's config.toml, which
// R.config.on_change picks up). Fields the menu cannot edit (string,
// multiselect, ...) are listed read-only. On by default;
// RSMM_DISABLE_NATIVE_MENU=1 (env or desktop loader-flags file) switches it
// off. Also answers the pause menu's Mods button (rsmm.engine.escape_menu).
bool install_settings_menu_hooks();

// True once the Settings build detour is installed (R.ui.menus needs it).
bool settings_build_hooked();

// The R.ui.menus page id of the Mods page. Must match mods_menu.lua.
constexpr const char* kModsPageId = "rsmm.mods";

// The model as JSON: {"mods":[{"id","name","version","author","description",
// "enabled","wanted","rows":[{"id","label","choices":[...],"value":n,"default":n}
// | {"id","label","readonly":true}]}]}. Indices are 1-based and reflect every set
// made this session. False + *why when the native menu is off / not installed.
bool mods_menu_model_json(std::string* out, std::string* why);

// Record a change: "@enabled" (index 2 = on) or a field (its options[index1-1]).
// Updates the model under its lock and marks it dirty; a watcher thread writes
// the files, so this does no file IO and can run on the game thread. False +
// *why on an unknown mod/row, a read-only row or an out-of-range index.
bool mods_menu_set(const std::string& mod_id, const std::string& row_id, int index1,
                   std::string* why);

// Re-read every mod's config.toml into the model (edits not yet on disk stay) and
// recompute the rows. File reads: call it when a page is built, never under an
// open page. Never throws; on failure the old values stay.
void mods_menu_refresh();

} // namespace rsmm
