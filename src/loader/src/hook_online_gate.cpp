// Online gate: a client running GAMEPLAY mods may not enter public matchmaking.
//
// Which mods are gameplay is decided CLI-side (rsmm.engine.mod_scope, derived
// from what each mod contains, never from the author's claim). `rsmm apply`
// writes the verdict to <game>/mods/.rsmm_gameplay — one `<id>: <reason>` line
// per gameplay mod — and removes it when only client-only mods (textures,
// sounds, HUDs, camera) run. `restore --all` wipes mods/ and this loader.
//
// The hook sits on Sym::Stormancer_StartMatchmaking, the one routine that
// starts a Stormancer GameFinder search ("Book_Page_Public_Search"). Joining
// or hosting a party by code never reaches it, so modded co-op with friends
// keeps working. Refusing the call leaves the menu searching forever; the
// menu tick retries it every frame until the player cancels, so the log line
// is written once per session.
//
// This is client-side and the source is public: it keeps an ordinary RSMM
// install honest, it is not anti-cheat.

#include "hook_online_gate.h"
#include "hook_util.h"
#include "loader.h"
#include "symbols.gen.h"

#include <windows.h>

#include <atomic>
#include <fstream>
#include <sstream>
#include <string>

namespace rsmm {
namespace {

using StartMatchmakingFn = void (*)(void* scene_ctx);
StartMatchmakingFn g_orig = nullptr;
std::uintptr_t g_va = 0;
std::string g_reason;               // marker contents, for the log
std::atomic<bool> g_logged{false};

// <game>/mods/.rsmm_gameplay contents; empty when absent.
std::string read_marker() {
    char buf[MAX_PATH];
    if (!GetModuleFileNameA(GetModuleHandleA("winhttp.dll"), buf, sizeof(buf))) return {};
    std::string p(buf);
    auto slash = p.find_last_of("\\/");
    if (slash == std::string::npos) return {};
    std::ifstream f(p.substr(0, slash) + "\\mods\\.rsmm_gameplay");
    if (!f) return {};
    std::stringstream ss;
    ss << f.rdbuf();
    std::string s = ss.str();
    if (s.empty()) s = "(unnamed gameplay mod)";
    return s;
}

void detour_start_matchmaking(void* /*scene_ctx*/) {
    hook_note_fire(g_va);
    if (!g_logged.exchange(true)) {
        Loader::get().log_warn(
            "[online-gate] public matchmaking BLOCKED: gameplay mods are "
            "active. Play them solo or in a party-code game, or disable them "
            "and run `rsmm apply`. Mods:\n" + g_reason);
    }
    // Never call g_orig: no GameFinder search starts.
}

} // namespace

bool install_online_gate() {
    g_reason = read_marker();
    if (g_reason.empty()) {
        Loader::get().log("[online-gate] no gameplay mods; public matchmaking allowed");
        return false;
    }
    if (!hook_install("online-gate", "matchmaking start",
                      Sym::Stormancer_StartMatchmaking_Pattern,
                      reinterpret_cast<void*>(&detour_start_matchmaking),
                      reinterpret_cast<void**>(&g_orig), &g_va)) {
        Loader::get().log_err("[online-gate] gameplay mods active but the "
                              "matchmaking hook did not install (game patched? "
                              "run `rsmm update-data`); public matchmaking is "
                              "NOT blocked");
        return false;
    }
    Loader::get().log("[online-gate] gameplay mods active; public matchmaking "
                      "will be refused (party-code games unaffected)");
    return true;
}

} // namespace rsmm
