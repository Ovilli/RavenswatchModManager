// Level-build trace — see hook_levelbuild.h for the why.

#include <windows.h>

#include <atomic>
#include <cstdint>
#include <cstdio>

#include "MinHook.h"
#include "loader.h"
#include "mem_safe.h"
#include "hook_util.h"
#include "symbols.gen.h"  // GENERATED — Sym::
#include "hook_levelbuild.h"
#include "hook_resource.h"

namespace rsmm {
namespace {

// ⚠ THE FIRST VERSION OF THIS TRACE READ A GUESSED OFFSET AND LIED.
// It took the count from `level + 0xc8` — the field the gate's own loop reads —
// and reported `objects=0` for EVERY level in the game, vanilla ones included.
// A number that is zero for levels which demonstrably build is a wrong offset,
// not a finding. The gate loads that pointer from a stack slot it fills itself,
// so it is not the `level` argument at all.
//
// So the primary measurement here depends on NO struct offset: count the calls
// to `LevelObject_LoadOrCreate`, which is literally "how many objects did this
// level instantiate". `LevelObject_LoadOrCreate`'s own note gives the layout
// for the cross-check — the container is at `level+0x10` and its object vector
// at `+0x90` with the count at `+0x98` — and that is reported beside the call
// count so a disagreement between them is visible instead of silent.
// ⚠ THE OFFSETS WERE RIGHT ALL ALONG; THE TIMING WAS WRONG.
//
// The gate walks `level+0xc8` (count) and `level+0xc0` (array, stride 0x38).
// Reading them BEFORE the real call reported zero for every level in the game,
// vanilla ones included, and that read as "the offset is wrong". It is not:
// `[rbp+0x6f]`, the pointer the loop dereferences, is never written inside the
// function — with eight pushes and `lea rbp,[rsp-0x1f]` it resolves to the home
// slot of argument 2, i.e. `level` itself. The fields are simply EMPTY on entry
// and filled during the gate, so the only correct time to read them is AFTER it
// returns.
//
// Safe to read after only because the gate KEPT the level; on a false verdict
// the engine destroys it, and anything read then is freed memory.
constexpr std::size_t kLevelObjCount = 0xc8;  // u32: objects, filled by the gate
constexpr std::size_t kLevelObjArray = 0xc0;  // void*: base of the 0x38 stride
constexpr std::size_t kElemStride    = 0x38;  // == sizeof(a resource ref block)
constexpr std::size_t kElemField     = 0x30;  // what the database mask is ANDed with
constexpr std::size_t kDbMask        = 0xa0;  // u32: the database's filter

// WHICH LEVEL. Without this the trace prints `level=0x43810980` and a run
// cannot tell a mod tile from a vanilla one — which would have made the very
// next playtest ambiguous all over again, for the fourth time in this
// investigation. `LevelObject_LoadOrCreate`'s note pins the layout:
// ResourceRef_Resolve is called with the ref block at `level+0xd0` and the out
// pointer at `level+0x100`, and 0xd0 + 0x30 == 0x100 — so level+0xd0 IS a
// standard 0x38-byte resource ref block. The level-load trace already proved
// such a block holds {char* root, u32 len, u32 cap} at +0x00 and the PATH at
// +0x10, by dumping one and reading the 52-char level path out of it.
constexpr std::size_t kLevelRefBlock = 0xd0;
constexpr std::size_t kRefPathOff    = 0x10;

using GateFn = bool (*)(void*, void*, bool);
GateFn g_real_gate = nullptr;
using LoadFn = bool (*)(void*, void*, void**, char, char, void*, void*);
LoadFn g_real_load = nullptr;

// Instantiations, counted globally. The gate reads it either side of the real
// call, so the delta is exactly what THIS level built.
std::atomic<long> g_loads{0};

bool detour_load(void* mgr, void* key, void** out, char link, char flag,
                 void* lvlId, void* registry) {
    g_loads.fetch_add(1);
    return g_real_load ? g_real_load(mgr, key, out, link, flag, lvlId, registry)
                       : false;
}

std::atomic<long> g_calls{0};
// ⚠ THIS WAS 40, AND 40 IS EXACTLY HOW MANY LEVELS A DARK HILLS MAP BUILDS.
// The cap was reached before the mod's own level was ever reached, so the one
// line the whole trace existed to print was the one it dropped — and the run
// read as "our level never reaches the gate". A budget tuned to hide repetition
// hid the signal instead. A map builds tens of levels, not thousands, so the
// honest budget is "all of them".
constexpr long kMaxLines = 400;
std::atomic<long> g_lines{0};

// The level's resource PATH, or "" when it does not read. Guarded like every
// other field here: a half-built level is the state worth catching.
void level_name(void* level, char* out, std::size_t cap) {
    out[0] = '\0';
    if (!level) return;
    const auto ref = reinterpret_cast<std::uintptr_t>(level) + kLevelRefBlock;
    char* p = nullptr;
    std::uint32_t len = 0;
    if (mem_load(ref + kRefPathOff, &p) && p
            && mem_load(ref + kRefPathOff + sizeof(void*), &len)
            && len > 0 && len < cap) {
        mem_read_cstr(reinterpret_cast<std::uintptr_t>(p), out, cap);
    }
}

// How many objects the level ended up carrying, and how many of them pass the
// database's mask. Guarded: an unreadable field degrades to -1, never a fault
// (MinGW has no __try/__except).
long level_objects(void* level) {
    if (!level) return -1;
    std::uint32_t n = 0;
    if (!mem_load(reinterpret_cast<std::uintptr_t>(level) + kLevelObjCount, &n)) return -1;
    return (n > 100000) ? -1 : static_cast<long>(n);
}

// ⚠ `test` clears CF, so the engine's `jbe` is really `je`: an object is SKIPPED
// when the AND is zero. This counts the ones that survive that test — the
// objects the engine will actually try to build.
long passing_mask(void* level, std::uint32_t mask, long count) {
    if (!level || count <= 0) return -1;
    void* base = nullptr;
    if (!mem_load(reinterpret_cast<std::uintptr_t>(level) + kLevelObjArray, &base)
            || !base) {
        return -1;
    }
    long live = 0;
    for (long i = 0; i < count; ++i) {
        std::uint32_t field = 0;
        const auto at = reinterpret_cast<std::uintptr_t>(base)
                      + static_cast<std::size_t>(i) * kElemStride + kElemField;
        if (!mem_load(at, &field)) return -1;
        if ((mask & field) != 0) ++live;
    }
    return live;
}

bool detour_gate(void* db, void* level, bool flag) {
    // BEFORE the call: the engine destroys the level on a false verdict, so
    // anything read afterwards may be freed memory.
    std::uint32_t mask = 0;
    const bool have_mask = db && mem_load(
        reinterpret_cast<std::uintptr_t>(db) + kDbMask, &mask);
    const long before = g_loads.load();
    const long res_before = resolve_count();

    const bool kept = g_real_gate ? g_real_gate(db, level, flag) : false;

    // TWO measurements, because the first one was wrong twice.
    //
    // `built` counts LevelObject_LoadOrCreate, which despite the name allocates
    // a LEVEL, not a per-object instance — it reads 0 for every level in the
    // game, vanilla ones included, so it is kept only as a tell-tale.
    //
    // `fetched` is the real one: resource resolves during this build. Every
    // object a level instantiates resolves its entity, so a level that fetches
    // nothing built nothing. It needs no struct offset at all.
    const long built = g_loads.load() - before;
    const long fetched = resolve_count() - res_before;
    // AFTER the gate, and only when it kept the level: these fields are empty
    // on entry and filled while it runs.
    const long declared = kept ? level_objects(level) : -1;
    const long passing = (kept && have_mask) ? passing_mask(level, mask, declared) : -1;
    const long n = g_calls.fetch_add(1) + 1;

    // Worth a line: anything that leaves a level empty, plus the first few of
    // whatever normal looks like on this build.
    // The resource trace owns the counter, so say so instead of reporting a
    // flat zero as if it were a finding.
    const bool can_count = resolve_count() > 0;
    const bool empty = !kept || declared == 0 || passing == 0
                    || (can_count && fetched == 0);
    if (g_lines.fetch_add(1) >= kMaxLines) return kept;

    char name[256];
    level_name(level, name, sizeof(name));
    char msk[24], dec[24], pas[24];
    if (have_mask) std::snprintf(msk, sizeof(msk), "%#x", mask);
    else           std::snprintf(msk, sizeof(msk), "<unread>");
    if (declared >= 0) std::snprintf(dec, sizeof(dec), "%ld", declared);
    else               std::snprintf(dec, sizeof(dec), "<unread>");
    if (passing >= 0)  std::snprintf(pas, sizeof(pas), "%ld", passing);
    else               std::snprintf(pas, sizeof(pas), "<unread>");

    // Name the CONCLUSION, not just the numbers. Three silent paths that look
    // identical from outside the engine is exactly why this hook exists, so the
    // line has to say which one it is or it repeats the ambiguity in the log.
    const char* verdict =
        !kept          ? "REFUSED — the level is destroyed and the slot nulled"
      : declared == 0  ? "kept, but it carries ZERO objects — nothing to build"
      : passing == 0   ? "kept, but EVERY object fails the mask and is skipped"
      : !can_count     ? "kept (arm RSMM_ENABLE_RESOURCE_TRACE to count fetches)"
      : fetched == 0   ? "kept, objects pass the mask, but NOTHING was fetched"
                       : "kept, and it built its objects";

    char line[512];
    std::snprintf(line, sizeof(line),
                  "[lvl-build] #%ld objects=%s pass=%s fetched=%ld mask=%s "
                  "\"%s\" -> %s",
                  n, dec, pas, fetched, msk,
                  name[0] ? name : "<unnamed>", verdict);
    // Severity is earned. A level that builds nothing is a real finding; a
    // healthy build is the baseline this trace prints to prove it is alive.
    // Severity is earned, and "every level is an error" is the same wall of
    // noise the severity rule exists to prevent. Only a level that was kept and
    // fetched nothing is a finding.
    if (empty) Loader::get().log_err(line);
    else       Loader::get().log(line);
    return kept;
}

}  // anonymous namespace

bool install_levelbuild_hooks() {
    if (!flag_enabled("RSMM_ENABLE_LEVEL_BUILD_TRACE")) {
        // Not armed is not a fault — plain log(), per the severity rule.
        Loader::get().log("[lvl-build] disabled (set RSMM_ENABLE_LEVEL_BUILD_TRACE=1 "
                          "to report why a level ends up with no objects in it)");
        return false;
    }
    Loader::get().log("[lvl-build] arming LevelDatabase_BuildAndRegister trace — "
                      "READ-ONLY; reports, per level built, how many objects it "
                      "carries and whether the gate kept it");
    // Both, or neither: the gate's number is a DELTA of the load counter, so a
    // gate without the counter would silently report "nothing was built" for
    // every level — which is exactly the false negative this rewrite exists to
    // remove.
    if (!hook_install("lvl-build", "level object load",
                      Sym::LevelObject_LoadOrCreate_Pattern,
                      reinterpret_cast<void*>(&detour_load),
                      reinterpret_cast<void**>(&g_real_load))) {
        Loader::get().log_err("[lvl-build] LevelObject_LoadOrCreate did not hook; "
                              "not arming the gate, because its count would read "
                              "zero for every level and mean nothing");
        return false;
    }
    return hook_install("lvl-build", "level build gate",
                        Sym::LevelDatabase_BuildAndRegister_Pattern,
                        reinterpret_cast<void*>(&detour_gate),
                        reinterpret_cast<void**>(&g_real_gate));
}

}  // namespace rsmm
