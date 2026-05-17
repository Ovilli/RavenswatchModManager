#pragma once
namespace rsmm {

// Install MinHook inline patches on engine-internal functions inside
// Ravenswatch.exe (not imported DLLs). Logs to mods/_engine_trace.log.
//
// Used to trace what the engine does at runtime so we can identify the
// page-build / button-spawn functions to hook for real.
//
// Enable: env RSMM_ENGINE_TRACE=1 in Steam launch options.
bool install_engine_hooks();
void remove_engine_hooks();

// Steam SDK invite-function suppression. When the Mods slot is armed
// (redirect cache populated or owned cooked file resolved), forward
// nothing into the real Steam SDK invite function — clicks in slot 7
// still fire the engine-side modal flow (for click-signal capture),
// but no party invite reaches the user's Steam friends list. Off by
// default; enable via RSMM_BLOCK_STEAM_INVITE=1.
bool install_steam_hooks();
void remove_steam_hooks();

} // namespace rsmm
