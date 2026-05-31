// Ravenswatch Mod Manager — winhttp proxy entry point.
//
// Loader scope after the SDK-pivot cut:
//   * IAT-redirected asset overrides (hook_io)
//   * Lua VM per mod (script_lua), with hot-reload
//   * Generic Lua hook bridge (hook_lua) backing the public rsmm.hook
//   * Pattern-resolved engine baseline verifier (hook_engine), off by default
//
// Removed: in-game ImGui overlay (hook_vk, hook_win32) and Steam vtable
// integration. Reason: the overlay surfaces were never feature-complete
// and we don't ship things that don't work.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <chrono>
#include <filesystem>
#include <thread>

#include "MinHook.h"
#include "loader.h"
#include "hook_io.h"
#include "hook_engine.h"
#include "hook_skins.h"
#include "hook_events.h"
#include "script_lua.h"

namespace fs = std::filesystem;

static HMODULE g_self_module = nullptr;

static fs::path module_dir() {
    wchar_t buf[MAX_PATH];
    GetModuleFileNameW(g_self_module, buf, MAX_PATH);
    return fs::path(buf).parent_path();
}

// C++ exception path. Kept in its own function so the outer SEH wrapper
// below stays free of objects with destructors (MSVC won't compile
// __try/__except in a function that constructs unwindable C++ objects).
static void loader_thread_cxx() {
    try {
        const fs::path game = module_dir();
        auto& L = rsmm::Loader::get();
        L.init(game);
        L.load_asset_map(game / "asset_map.json");
        L.scan_mods(game / "mods");
        L.load_state();
        for (const auto& m : L.mods()) {
            if (!m.enabled) continue;
            rsmm::script_run_mod_init(m.id, m.root);
        }
        // Lifecycle: "setup" fires after every mod's init.lua has run (so
        // cross-mod APIs are registered) but BEFORE overrides are applied,
        // giving handlers a chance to register late asset overrides.
        rsmm::script_emit_event("setup");
        L.apply_overrides();

        if (MH_Initialize() != MH_OK) {
            L.log("MH_Initialize failed; hooks disabled");
            return;
        }

        char buf[8];
        if (GetEnvironmentVariableA("RSMM_ENABLE_IO", buf, sizeof(buf)) && buf[0] == '1') {
            L.log("RSMM_ENABLE_IO=1: installing IO hook (may crash game)");
            rsmm::install_io_hooks();
        } else {
            L.log("IO hook disabled by default (set RSMM_ENABLE_IO=1 to enable)");
        }

        rsmm::install_engine_hooks();
        rsmm::install_skin_hooks();
        rsmm::install_event_hooks();

        rsmm::script_emit_event("ready");
        L.log("loader thread complete");

        // Background ticker: fires "tick" every 500 ms so mods can poll
        // for game state that isn't ready at "ready" time (e.g. the
        // GameOptions struct, which is constructed AFTER our loader
        // thread finishes). Cheap — mods opt in via rsmm.on_event("tick").
        //
        // Same thread also drives hot-reload: every 2nd tick (~1 s) it
        // polls each mod's init.lua mtime; on change it rebuilds the
        // lua_State and replays "ready". Iteration loop is now seconds
        // not minutes — no game restart.
        std::thread([] {
            int n = 0;
            while (true) {
                std::this_thread::sleep_for(std::chrono::milliseconds(500));
                rsmm::script_emit_event("tick");
                if ((++n & 1) == 0) {
                    rsmm::script_reload_changed();
                }
            }
        }).detach();
    } catch (const std::exception& e) {
        OutputDebugStringA(e.what());
    }
}

static void loader_thread() {
#ifdef _MSC_VER
    // SEH wrapper catches access violations / invalid handles / stack
    // overflows the C++ try/catch above cannot. We log and bail rather
    // than letting Windows tear the process down with a vague dialog.
    // MinGW/GCC don't support __try/__except, so the cross-compile path
    // falls back to the C++ exception layer only.
    __try {
        loader_thread_cxx();
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        OutputDebugStringA("rsmm loader: SEH exception in loader thread; aborting init.");
    }
#else
    loader_thread_cxx();
#endif
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_self_module = inst;
        DisableThreadLibraryCalls(inst);
        std::thread(loader_thread).detach();
    } else if (reason == DLL_PROCESS_DETACH) {
        rsmm::script_emit_event("exit");
        rsmm::script_shutdown_all();
        rsmm::remove_engine_hooks();
        rsmm::remove_io_hooks();
        MH_Uninitialize();
        rsmm::Loader::get().shutdown();
    }
    return TRUE;
}
