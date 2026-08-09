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
#include <atomic>
#include <chrono>
#include <cwchar>
#include <filesystem>
#include <thread>

#include "MinHook.h"
#include "loader.h"
#include "health.h"
#include "fn_resolver.h"
#include "hook_io.h"
#include "hook_engine.h"
#include "hook_skins.h"
#include "hook_skills.h"
#include "hook_ui.h"
#include "hook_spawn.h"
#include "hook_items.h"
#include "hook_rewards.h"
#include "hook_events.h"
#include "hook_netcode.h"
#include "script_lua.h"

namespace fs = std::filesystem;

static HMODULE g_self_module = nullptr;
static HANDLE g_loader_guard_event = nullptr;
static bool g_loader_started = false;
// Ticker shutdown handshake (dynamic-unload path only). g_ticker_stop tells
// the loop to exit; g_ticker_idle is set while the loop is parked between
// ticks and reset while a tick is executing Lua, so the unload path can wait
// until the VM is quiescent before lua_close.
static std::atomic<bool> g_ticker_stop{false};
static HANDLE g_ticker_idle = nullptr;

static fs::path module_dir() {
    wchar_t buf[MAX_PATH];
    GetModuleFileNameW(g_self_module, buf, MAX_PATH);
    return fs::path(buf).parent_path();
}

static bool acquire_loader_guard() {
    wchar_t name[128];
    if (std::swprintf(name, sizeof(name) / sizeof(name[0]),
                      L"Local\\RavenswatchModManager.Loader.%lu",
                      static_cast<unsigned long>(GetCurrentProcessId())) < 0) {
        OutputDebugStringA("rsmm loader: failed to format guard name; continuing.");
        return true;
    }

    HANDLE event = CreateEventW(nullptr, TRUE, TRUE, name);
    if (!event) {
        OutputDebugStringA("rsmm loader: failed to create guard event; continuing.");
        return true;
    }
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        CloseHandle(event);
        OutputDebugStringA("rsmm loader: duplicate loader instance ignored.");
        return false;
    }
    g_loader_guard_event = event;
    return true;
}

// C++ exception path. Kept in its own function so the outer SEH wrapper
// below stays free of objects with destructors (MSVC won't compile
// __try/__except in a function that constructs unwindable C++ objects).
static void loader_thread_cxx() {
    try {
        const fs::path game = module_dir();
        auto& L = rsmm::Loader::get();
        L.init(game);
        // Before any mod code runs: attribute an unclosed canary from the
        // previous launch (i.e. a boot crash) and open one for this session.
        rsmm::health::init(L.mods_dir(), L.session());
        L.load_asset_map(game / "asset_map.json");
        L.scan_mods(game / "mods");
        L.load_state();

        // MinHook must be live BEFORE mod init runs: a mod's init.lua can
        // install a hook via rsmm.hook (e.g. rsmm.lua arms the hero-capture
        // hooks at module load), and MH_CreateHook returns
        // MH_ERROR_NOT_INITIALIZED if the library isn't up yet.
        // ALREADY_INITIALIZED is tolerated so a re-entered loader thread
        // (or a second injection) doesn't disable hooks outright.
        {
            MH_STATUS s = MH_Initialize();
            if (s != MH_OK && s != MH_ERROR_ALREADY_INITIALIZED) {
                L.log("MH_Initialize failed; hooks disabled");
                return;
            }
        }

        for (const auto& m : L.mods()) {
            if (!m.enabled) continue;
            rsmm::script_run_mod_init(m.id, m.root);
        }
        // Lifecycle: "setup" fires after every mod's init.lua has run (so
        // cross-mod APIs are registered) but BEFORE overrides are applied,
        // giving handlers a chance to register late asset overrides.
        rsmm::script_emit_event("setup");
        L.apply_overrides();

        char buf[8];
        if (GetEnvironmentVariableA("RSMM_ENABLE_IO", buf, sizeof(buf)) && buf[0] == '1') {
            L.log("RSMM_ENABLE_IO=1: installing IO hook (may crash game)");
            rsmm::install_io_hooks();
        } else {
            L.log("IO hook disabled by default (set RSMM_ENABLE_IO=1 to enable)");
        }

        rsmm::install_engine_hooks();
        rsmm::install_skin_hooks();
        rsmm::install_skill_hooks();
        rsmm::install_ui_hooks();
        rsmm::install_spawn_hooks();
        rsmm::install_item_hooks();
        rsmm::install_reward_hooks();
        rsmm::install_event_hooks();
        // Hero-capture must install in the SAME phase as the other engine hooks
        // (after the gameplay bus). Installing it earlier — before mod init —
        // made MH_CreateHook fail on a fresh launch (and the game crashed on
        // load). Mods touching R.entity during init just fall back to the
        // legacy per-state path until this arms; harmless.
        rsmm::install_hero_capture();
        rsmm::install_netcode_patches();

        // Ground-truth symbol dump (opt-in, dev/RE). Force-resolves every
        // semantic pattern against the live exe and writes
        // <game>/rsmm/resolved_symbols.json {name, va, prologue} — the
        // authoritative record `rsmm symbols audit` diffs against symbols.json,
        // so a mis-resolve is caught from the RUNNING game. ~140 full .text
        // scans, so gated behind a flag and run here on the loader thread
        // (already off the main thread) rather than every boot.
        if (rsmm::flag_enabled("RSMM_DUMP_SYMBOLS")) {
            const auto dump_path =
                (L.game_dir() / "rsmm" / "resolved_symbols.json").string();
            rsmm::fn_resolver_dump_resolved(dump_path);
        }

        rsmm::script_emit_event("ready");
        rsmm::health::checkpoint("ready");
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
        g_ticker_idle = CreateEventW(nullptr, TRUE, TRUE, nullptr);
        std::thread([] {
            int n = 0;
            while (!g_ticker_stop.load(std::memory_order_acquire)) {
                // Sleep in short slices so a dynamic unload isn't stalled
                // for a full tick interval.
                for (int i = 0; i < 5 && !g_ticker_stop.load(std::memory_order_acquire); ++i) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                }
                if (g_ticker_stop.load(std::memory_order_acquire)) break;
                if (g_ticker_idle) ResetEvent(g_ticker_idle);
                rsmm::script_emit_event("tick");
                if ((++n & 1) == 0) {
                    rsmm::script_reload_changed();
                }
                // Four ticks (~2 s) of the pump running after "ready" is the
                // definition of "this launch booted": mod init and the whole
                // hook install phase are behind us. Close the canary so the
                // NEXT launch doesn't blame this one for a later crash.
                if (n == 4) rsmm::health::mark_boot_ok();
                if (g_ticker_idle) SetEvent(g_ticker_idle);
            }
            if (g_ticker_idle) SetEvent(g_ticker_idle);
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

// Only run the mod loader inside the game itself. Other executables in the
// game directory also import WinHTTP — crashpad_handler.exe does, for crash
// uploads — and pick up our proxy DLL via the app-dir search path. Running
// the full loader there is pure noise: none of the game's code exists in
// that process, so every pattern resolve fails, and each launch used to log
// a confusing second init block whose resolves all failed. The proxy's
// winhttp export forwarding still works in those hosts; we just never start
// the loader thread.
static bool host_is_game() {
    char exe[MAX_PATH] = {0};
    if (!GetModuleFileNameA(nullptr, exe, MAX_PATH)) return true;
    const char* base = exe;
    for (const char* p = exe; *p; ++p) {
        if (*p == '\\' || *p == '/') base = p + 1;
    }
    return _stricmp(base, "Ravenswatch.exe") == 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_self_module = inst;
        DisableThreadLibraryCalls(inst);
        if (!host_is_game()) {
            OutputDebugStringA("rsmm loader: non-game host process; "
                               "winhttp proxy only, loader not started.");
            return TRUE;
        }
        if (!acquire_loader_guard()) return TRUE;
        g_loader_started = true;
        std::thread(loader_thread).detach();
    } else if (reason == DLL_PROCESS_DETACH) {
        if (!g_loader_started) return TRUE;
        // Process termination (reserved != nullptr): every other thread has
        // already been killed by ExitProcess — possibly MID-Lua-tick, leaving
        // the VM internally inconsistent. Running lua_close / emit("exit") /
        // MH_Uninitialize here executed freed or half-mutated state and
        // crashed every quit (execute-AV at a garbage pointer, dump
        // 223f5e95 2026-07-17). The OS reclaims memory, hooks, and handles
        // wholesale at this point — correct behavior is to do NOTHING.
        if (reserved != nullptr) {
            rsmm::Loader::get().shutdown();   // log line only
            return TRUE;
        }
        // Dynamic unload (FreeLibrary): threads are still alive. Stop the
        // ticker and wait until it's parked outside the VM before tearing
        // the Lua states down. (Waiting on an event, not joining — joining
        // a thread from DllMain deadlocks on the loader lock.)
        g_ticker_stop.store(true, std::memory_order_release);
        if (g_ticker_idle) {
            HANDLE idle = g_ticker_idle;
            // Clear the global BEFORE closing so the ticker (which checks it
            // each iteration) can't SetEvent on a closed handle.
            g_ticker_idle = nullptr;
            WaitForSingleObject(idle, 2000);
            CloseHandle(idle);
        }
        rsmm::script_emit_event("exit");
        rsmm::script_shutdown_all();
        // Every detour lives in this DLL's .text, which is about to be
        // unmapped — retire them all, not just the two that used to be here.
        rsmm::remove_event_hooks();
        rsmm::remove_engine_hooks();
        rsmm::remove_io_hooks();
        MH_Uninitialize();
        rsmm::Loader::get().shutdown();
        if (g_loader_guard_event) {
            CloseHandle(g_loader_guard_event);
            g_loader_guard_event = nullptr;
        }
    }
    return TRUE;
}
