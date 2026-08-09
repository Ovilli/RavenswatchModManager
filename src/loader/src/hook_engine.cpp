// Engine hook baseline verifier.
//
// Phase 3 of INTERNALS.md showed that MinHook on game-internal `.text`
// functions worked end-to-end (FUN_1401145b0 + FUN_140487040 captured
// per-launch resource-handle mappings). That implementation was pruned;
// docs/_re/PROTECTOR.md then confirmed the protector is a one-shot
// unpacker with no runtime integrity monitor, so the prune was scope
// reduction, not a fix for an actual crash.
//
// This minimal restore re-installs ONE hook on FUN_140487040 (the
// FNV-1a + SwissTable-style resource-by-path lookup) and logs the first
// few calls. Purpose: prove the hook path is alive before we wire the
// generic rsmm.hook Lua surface on top.
//
// Off by default. Enable with `RSMM_ENABLE_ENGINE_HOOK=1` in the Steam
// launch environment.

#include "hook_engine.h"
#include "fn_resolver.h"
#include "hook_util.h"
#include "symbols.gen.h"  // GENERATED — Sym::
#include "loader.h"

#include "MinHook.h"

#include <windows.h>

#include <atomic>
#include <cstdint>
#include <string>

namespace rsmm {

namespace {

// FUN_140487040 — resource lookup (entry by-path hashmap). Arity is
// unknown from RE; the Win x64 ABI puts the first 4 args in RCX/RDX/R8/R9
// and additional args on the stack at [rsp+0x28]+. We declare 6 register
// slots so the detour preserves caller state regardless of true arity:
// MinHook's prologue copy preserves the original prologue verbatim, so as
// long as we forward all 4 register args + don't touch stack we're safe.
using ResourceLookup_t = std::uintptr_t (*)(void*, void*, void*, void*);

ResourceLookup_t g_real_resource_lookup = nullptr;
std::uintptr_t   g_lookup_va = 0;
std::atomic<std::uint64_t> g_lookup_calls{0};
std::atomic<std::uint64_t> g_lookup_logged{0};

constexpr std::uint64_t kMaxLogCalls = 5;

std::uintptr_t WINAPI hook_resource_lookup(void* a, void* b, void* c, void* d) {
    const auto n = g_lookup_calls.fetch_add(1, std::memory_order_relaxed) + 1;
    if (n <= kMaxLogCalls) {
        const auto logged = g_lookup_logged.fetch_add(1) + 1;
        Loader::get().log("[engine-hook] FUN_140487040 call #" + std::to_string(n)
                          + " rcx=" + std::to_string(reinterpret_cast<std::uintptr_t>(a))
                          + " rdx=" + std::to_string(reinterpret_cast<std::uintptr_t>(b)));
        (void)logged;
    }
    return g_real_resource_lookup(a, b, c, d);
}

bool env_truthy(const char* name) {
    char buf[8] = {};
    DWORD n = GetEnvironmentVariableA(name, buf, sizeof(buf));
    return n > 0 && n < sizeof(buf) && (buf[0] == '1' || buf[0] == 't' || buf[0] == 'T');
}

// File-based opt-in so iteration doesn't need a Steam-options round-trip.
// Drop `mods/.rsmm_enable_engine_hook` next to the game's mods/ directory
// to arm the hook; remove it to disarm. Env var still wins if set.
bool file_marker_present() {
    char buf[MAX_PATH];
    if (!GetModuleFileNameA(GetModuleHandleA("winhttp.dll"), buf, sizeof(buf))) return false;
    std::string p(buf);
    auto slash = p.find_last_of("\\/");
    if (slash == std::string::npos) return false;
    std::string marker = p.substr(0, slash) + "\\mods\\.rsmm_enable_engine_hook";
    DWORD attr = GetFileAttributesA(marker.c_str());
    return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}

} // namespace

bool install_engine_hooks() {
    const bool by_env = env_truthy("RSMM_ENABLE_ENGINE_HOOK");
    const bool by_file = file_marker_present();
    if (!by_env && !by_file) {
        Loader::get().log("[engine-hook] disabled (set RSMM_ENABLE_ENGINE_HOOK=1 "
                          "or touch mods/.rsmm_enable_engine_hook to verify)");
        return false;
    }
    Loader::get().log(std::string("[engine-hook] arming via ")
                      + (by_env ? "env" : "file marker"));
    // Resolve by SEMANTIC name. This was the literal "FUN_140487040" — the
    // address the routine had two builds ago, alive only as a legacy alias in
    // the pattern DB. hook_install adds the check that literal could never
    // pass on its own: that the resolved address is a .pdata function entry
    // and not the middle of some larger function the routine was merged into.
    if (!hook_install("engine-hook", "resource lookup",
                      Sym::Resource_LookupByPath_Pattern,
                      reinterpret_cast<void*>(&hook_resource_lookup),
                      reinterpret_cast<void**>(&g_real_resource_lookup),
                      &g_lookup_va)) {
        return false;
    }
    Loader::get().log("[engine-hook] will log first "
                      + std::to_string(kMaxLogCalls) + " calls");
    return true;
}

void remove_engine_hooks() {
    if (!g_lookup_va) return;
    // Remove OUR hook only. This used to call MH_DisableHook(MH_ALL_HOOKS),
    // which tore down every other hook in the process — the gameplay bus, the
    // hero capture, and every mod's rsmm.hook slot — on a path that is only
    // supposed to retire one diagnostic detour.
    hook_remove(g_lookup_va);
    g_lookup_va = 0;
    g_real_resource_lookup = nullptr;
    Loader::get().log("[engine-hook] removed (total calls="
                      + std::to_string(g_lookup_calls.load()) + ")");
}

} // namespace rsmm
