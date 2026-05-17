// Minimal engine hook stubs — removed heavy tracing / Mods-menu logic.
// The original implementation provided runtime tracing, synthetic Steam
// IDs, and Steam vtable hooks to support the in-engine Mods menu. That
// functionality has been removed; keep simple no-op stubs so callers in
// `dllmain.cpp` remain valid.

#include "hook_engine.h"
#include "loader.h"

#include <windows.h>

namespace rsmm {

bool install_engine_hooks() {
    Loader::get().log("engine hooks pruned: install_engine_hooks no-op");
    return false;
}

void remove_engine_hooks() {
    Loader::get().log("engine hooks pruned: remove_engine_hooks no-op");
}

bool install_steam_hooks() {
    Loader::get().log("engine hooks pruned: install_steam_hooks no-op");
    return false;
}

void remove_steam_hooks() {
    Loader::get().log("engine hooks pruned: remove_steam_hooks no-op");
}

} // namespace rsmm
