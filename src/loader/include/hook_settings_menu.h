#pragma once
namespace rsmm {

// Native mod menu: a "Mods" tab inside the game's own Settings page.
//
// The Settings page is not laid out in data: its controller
// (oe::dt::BookOptionsUiControllerEntityCpnt) builds every tab and row in
// code from row templates (Option_CategButton, Option_StringItem, ...). We
// detour the last of its five tab builders and, after it returns, call the
// same add-tab / add-row helpers it uses, so the game draws, navigates and
// sounds our rows exactly like its own. A multi-choice row only holds a
// uint32_t* to its current index (vanilla points it at a GameOption's
// value), so our rows point at loader memory instead.
//
// Rows: Off/On per installed mod (applied by `rsmm apply` on the next launch)
// and each mod's bool/enum/int/float config fields (written to its
// config.toml, which R.config.on_change picks up). Proven in game 2026-10-24.
// On by default; RSMM_DISABLE_NATIVE_MENU=1 (env or desktop loader-flags file)
// switches it off. Also answers the pause menu's Mods button
// (rsmm.engine.escape_menu).
bool install_settings_menu_hooks();

} // namespace rsmm
