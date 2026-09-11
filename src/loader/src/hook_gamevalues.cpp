// Global entity-value context capture — see hook_gamevalues.h for the why.

#include <windows.h>

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "MinHook.h"
#include "loader.h"
#include "mem_safe.h"
#include "hook_util.h"
#include "script_lua.h"    // shared_set / shared_get
#include "symbols.gen.h"   // GENERATED — Sym::
#include "hook_gamevalues.h"

namespace rsmm {
namespace {

// Slot 16 is the hero's value context; 17 is the first free one (24 total).
// Deliberately a SEPARATE slot rather than a fallback for 16: they are
// different contexts holding different keys, and letting a global context
// stand in for a missing hero one would make every R.stat read silently
// answer about the wrong subject.
constexpr int kGlobalValueCtxSlot = 17;

// The tester that identifies the lookup we care about. The game stack-builds
// one of these per call, so its vftable is the first qword.
//
// This VA is BUILD-SPECIFIC, which is why the whole capability is gated on
// va_globals_trusted(): on a game build we have not fingerprinted, this
// address names some other class's vftable, the comparison below matches the
// wrong lookups, and we would publish a pointer to a context of entirely the
// wrong type.
std::uintptr_t image_base() {
    HMODULE h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    return reinterpret_cast<std::uintptr_t>(h);
}

std::uintptr_t tester_vftable() {
    return Sym::g_GlobalEntityValueSceneContext_Tester_vftable
           - Sym::kPreferredBase + image_base();
}

using FindCtx_fn = void* (*)(void*, void*);
FindCtx_fn g_real = nullptr;
std::atomic<std::uint32_t> g_logged{0};
std::atomic<std::uint32_t> g_seen{0};
constexpr std::uint32_t kLogCap = 3;

// A published context must at least be a readable, aligned heap object. This
// is a SHAPE check and nothing more: it cannot tell a live context from a
// recycled page, and it deliberately does not try to decide whether the object
// is a context (store at +0x4c8) or a store itself (+0x98 map) — that question
// is answered on the Lua side, where a wrong answer costs a refusal instead of
// the engine walking an unbounded hash map. See the header.
bool ctx_plausible(void* p) {
    auto a = reinterpret_cast<std::uintptr_t>(p);
    if (a == 0 || (a & 7) != 0) return false;
    if (!mem_readable(p, 0x100)) return false;
    // Every one of these objects is polymorphic, so slot 0 is a vftable and
    // must point into a readable page of its own.
    std::uintptr_t vft = 0;
    if (!mem_load(a, &vft)) return false;
    return vft != 0 && (vft & 7) == 0 && mem_accessible(vft, sizeof(void*), false);
}

void* detour_find_ctx(void* scene, void* tester) {
    void* ctx = g_real(scene, tester);
    if (ctx == nullptr) return ctx;

    // Identify the lookup by the tester's vftable. Cheap and exact: a tester is
    // stack-built immediately before the call, so this read is of live stack.
    std::uintptr_t vft = 0;
    if (!mem_load(reinterpret_cast<std::uintptr_t>(tester), &vft)) return ctx;
    if (vft != tester_vftable()) return ctx;

    g_seen.fetch_add(1);
    if (shared_get(kGlobalValueCtxSlot) == reinterpret_cast<std::uint64_t>(ctx))
        return ctx;                                  // already published, no churn
    if (!ctx_plausible(ctx)) {
        if (g_logged.fetch_add(1) < kLogCap) {
            char line[160];
            std::snprintf(line, sizeof(line),
                          "[game-values] rejected ctx=%p (not a readable polymorphic object)",
                          ctx);
            Loader::get().log(line);
        }
        return ctx;
    }
    shared_set(kGlobalValueCtxSlot, reinterpret_cast<std::uint64_t>(ctx));
    if (g_logged.fetch_add(1) < kLogCap) {
        char line[200];
        std::snprintf(line, sizeof(line),
                      "[game-values] PUBLISHED global entity-value ctx=%p (slot %d) — "
                      "R.game can now read the ~117 registered values",
                      ctx, kGlobalValueCtxSlot);
        Loader::get().log(line);
    }
    return ctx;
}

} // namespace

// The context belongs to the scene it was found in. On teardown the scene goes
// away and the pointer dangles — the same failure that cost dump 434d75a5 on
// the hero context, where a recycled page still read as plausible and the
// engine walked 393,568 entries off the end of an array. Dropping it costs
// nothing: the game looks the context up constantly, so the very next write to
// any of these values republishes it.
void drop_global_value_ctx(const char* ev_name) {
    // ⚠ THE NAME FILTER IS THE WHOLE FUNCTION. The first version took no
    // argument and was called from the gameplay dispatch next to the hero
    // context's drop -- which does its OWN filtering internally, so the call
    // sites look identical and this one silently dropped on EVERY dispatched
    // event. Measured on the first playtest: 1126 drop/republish lines in
    // ninety seconds, and a slot that spent much of its life at zero.
    if (!ev_name) return;
    if (std::strcmp(ev_name, "GAME_END_NEXT_CHAPTER") != 0 &&
        std::strcmp(ev_name, "GAME_END_SUCCESS") != 0 &&
        std::strcmp(ev_name, "GAME_END_SUCCESS_SKIP_NEXT") != 0 &&
        std::strcmp(ev_name, "GAME_END_FAILED") != 0) {
        return;
    }
    if (shared_get(kGlobalValueCtxSlot) == 0) return;
    shared_set(kGlobalValueCtxSlot, 0);
    // Deliberately NOT resetting the log cap. Resetting it made the cap
    // meaningless the moment anything dropped repeatedly, which is precisely
    // how the flood above stayed invisible in review and obvious in the log.
    Loader::get().log("[game-values] global entity-value ctx dropped on scene teardown; "
                      "the next lookup republishes it");
}

bool install_gamevalue_capture() {
    // Fail closed on an unfingerprinted build: the tester vftable is the only
    // thing that tells our lookup from the dozens of others routed through the
    // same function, and it is a raw VA.
    if (!Loader::get().va_globals_trusted()) {
        Loader::get().log("[game-values] not arming: VA globals are not trusted on this "
                          "game build, so the tester vftable cannot be identified");
        return false;
    }
    return hook_install("game-values", "scene-context lookup",
                        Sym::GameScene_FindContextByTester_Pattern,
                        reinterpret_cast<void*>(&detour_find_ctx),
                        reinterpret_cast<void**>(&g_real));
}

} // namespace rsmm
