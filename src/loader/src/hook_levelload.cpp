// Level-load failure trace — see hook_levelload.h for the why.

#include <windows.h>

#include <atomic>
#include <cstdint>
#include <cstdio>

#include "MinHook.h"
#include "loader.h"
#include "mem_safe.h"
#include "hook_util.h"
#include "symbols.gen.h"  // GENERATED — Sym::
#include "hook_levelload.h"

namespace rsmm {
namespace {

// Field map for the object the slot resolves to, read off LevelStream_LoadStep
// and its two callees (LevelBinary_Load / LevelText_Load).
constexpr std::size_t kObjFlagsOff = 0x28;  // bit 5 tested by the dispatch
constexpr std::size_t kObjStateOff = 0x38;  // must be 1 or the step bails
constexpr std::size_t kObjNameOff  = 0x68;  // char* resource name

using LoadStepFn = bool (*)(void*, void**, void*, void*);
LoadStepFn g_real_step = nullptr;

std::atomic<long> g_steps{0};
std::atomic<long> g_fails{0};
// A failing load usually fails for every remaining step of that transition, so
// an uncapped log would bury the FIRST failure — the only one whose resource
// is the cause rather than a consequence.
constexpr long kMaxFailLines = 24;

bool detour_step(void* container, void** slot, void* lvl_id, void* links) {
    const bool ok = g_real_step ? g_real_step(container, slot, lvl_id, links) : false;
    g_steps.fetch_add(1);
    if (ok) return ok;

    const long n = g_fails.fetch_add(1) + 1;
    if (n > kMaxFailLines) return ok;

    // Everything below is guarded: a half-built or already-freed slot is
    // exactly the state this trace exists to catch, so an unreadable field
    // must degrade to a log line, never to a fault.
    void* obj = nullptr;
    if (slot && mem_readable(slot, sizeof(void*))) obj = *slot;

    std::uint32_t state = 0, flags = 0;
    const bool have_state = obj && mem_load(
        reinterpret_cast<std::uintptr_t>(obj) + kObjStateOff, &state);
    const bool have_flags = obj && mem_load(
        reinterpret_cast<std::uintptr_t>(obj) + kObjFlagsOff, &flags);

    char name[256];
    name[0] = '\0';
    char* np = nullptr;
    if (obj && mem_load(reinterpret_cast<std::uintptr_t>(obj) + kObjNameOff, &np) && np) {
        mem_read_cstr(reinterpret_cast<std::uintptr_t>(np), name, sizeof(name));
    }
    if (name[0] == '\0') std::snprintf(name, sizeof(name), "<no name>");

    // Which branch refused. state != 1 is the reachable one; a failure WITH
    // state == 1 means LevelLoad_AbortPredicate fired, which would overturn
    // the "the abort path is inert on this build" finding — so say so
    // explicitly rather than letting it read as the state branch.
    const char* why = !have_state ? "slot/object unreadable"
                    : state != 1  ? "resource state != 1"
                                  : "ABORT PREDICATE (state was 1) — this contradicts the "
                                    "inert-abort finding, record it";

    char st[16], fl[16];
    if (have_state) std::snprintf(st, sizeof(st), "%u", state);
    else            std::snprintf(st, sizeof(st), "<unread>");
    if (have_flags) std::snprintf(fl, sizeof(fl), "%#x", flags);
    else            std::snprintf(fl, sizeof(fl), "<unread>");

    char line[512];
    std::snprintf(line, sizeof(line),
                  "[lvl-trace] level load step FAILED #%ld: %s | obj=%p state=%s flags=%s "
                  "step=%ld  \"%s\"",
                  n, why, obj, st, fl, g_steps.load(), name);
    Loader::get().log_err(line);
    if (n == kMaxFailLines) {
        Loader::get().log("[lvl-trace] failure log capped; the FIRST line above is the "
                          "one whose resource caused the load to fail");
    }
    return ok;
}

}  // anonymous namespace

bool install_levelload_hooks() {
    if (!flag_enabled("RSMM_ENABLE_LEVEL_TRACE")) {
        // Not armed is not a fault — plain log(), per the severity rule.
        Loader::get().log("[lvl-trace] disabled (set RSMM_ENABLE_LEVEL_TRACE=1 to report "
                          "which resource makes a level load fail)");
        return false;
    }
    Loader::get().log("[lvl-trace] arming LevelStream_LoadStep trace — READ-ONLY; logs "
                      "FAILED level-load steps only, so silence means loads are fine");
    return hook_install("lvl-trace", "level load step",
                        Sym::LevelStream_LoadStep_Pattern,
                        reinterpret_cast<void*>(&detour_step),
                        reinterpret_cast<void**>(&g_real_step));
}

}  // namespace rsmm
