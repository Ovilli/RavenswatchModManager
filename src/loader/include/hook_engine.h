#pragma once
namespace rsmm {

// Minimal MinHook trampoline on FUN_140487040 (engine resource-by-path
// lookup). Logs first 5 calls then stays passive. Used to validate the
// .text-hook path is live; not relied on by anything else.
//
// Off by default; arm via env RSMM_ENABLE_ENGINE_HOOK=1 or by creating
// the marker file `mods/.rsmm_enable_engine_hook` next to the loader.
bool install_engine_hooks();
void remove_engine_hooks();

} // namespace rsmm
