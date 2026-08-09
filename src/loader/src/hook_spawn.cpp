// Spawn-system dynamic trace — see hook_spawn.h for the why.
//
// Detours the selector prepare virtual FUN_140330c30(spawnerCpnt). After the
// original runs (the picker has rebuilt the candidate list), we read the
// component and log its structure. The goal is to capture, in a live play
// session, the runtime vtable of the spawner component + each candidate
// template, so the still-unlocated instantiator (a vtable slot on the runtime
// component, statically unreachable) can be mapped against the live module.
//
// Component layout (RE 2026-06-17, docs/_re/kinds/spawn-system.md):
//   +0x00  vftable (identifies the runtime component class)
//   +0x10  owner sub-object  ([+0x10]+0x108 = a gate byte read by prepare)
//   +0x68  candidate vector  { void* data; u32 count; u32 cap; }  (stride 8,
//          each element an oCEntitySettingsRootPtr; resolved template @entry+0x18)
//   +0x80  parallel array (resized to count) { data; count; cap }
//   +0xa0  parallel array (resized to count) { data; count; cap }
//   +0xb8  RNG seed

#include <windows.h>

#include <cstdint>
#include <string>

#include "MinHook.h"
#include "loader.h"
#include "mem_safe.h"
#include "fn_resolver.h"
#include "hook_spawn.h"

namespace rsmm {
namespace {

constexpr std::size_t kCandVecOff = 0x68;  // candidate template vector
constexpr std::size_t kOwnerOff   = 0x10;  // owner sub-object
constexpr std::size_t kArrA_Off   = 0x80;  // parallel array A
constexpr std::size_t kArrB_Off   = 0xa0;  // parallel array B
constexpr std::size_t kEntryTmpl  = 0x18;  // resolved template ptr in an entry
constexpr std::size_t kPtrStride  = 0x08;

// void FUN_140330c30(void* spawnerCpnt). Pattern in data/function_patterns.json.
using Prepare_t = void (*)(void*);
Prepare_t g_real_prepare = nullptr;

bool env_on(const char* name) {
    // Honour both the env var and the desktop-written flags file.
    return flag_enabled(name);
}

// Confirm [addr, addr+size) is committed + readable so a wrong offset logs/skips
// instead of faulting (MinGW has no __try/__except). Shared implementation: this
// copy never applied its own readable-protection mask and had no wrap guard, so
// a -1 sentinel in a spawner slot passed straight through.
inline bool readable(const void* p, std::size_t size) { return mem_readable(p, size); }

std::string hex_of(std::uintptr_t v) {
    char b[32];
    snprintf(b, sizeof(b), "0x%llx", static_cast<unsigned long long>(v));
    return b;
}

// Read the vftable of an object (its first qword), or 0 if unreadable. The
// vftable VA, captured live, is the key the dynamic trace needs: subtract the
// live module base to get the static RVA and find the instantiator slot.
std::uintptr_t vtable_of(void* obj) {
    if (!readable(obj, 8)) return 0;
    return *reinterpret_cast<std::uintptr_t*>(obj);
}

// Read a { void* data; u32 count; u32 cap; } triple at base+off. Returns false
// if the triple is unreadable.
bool read_vec(void* base, std::size_t off, void** data, std::uint32_t* count,
              std::uint32_t* cap) {
    auto* p = reinterpret_cast<std::uint8_t*>(base) + off;
    if (!readable(p, 0x10)) return false;
    *data  = *reinterpret_cast<void**>(p);
    *count = *reinterpret_cast<std::uint32_t*>(p + 0x08);
    *cap   = *reinterpret_cast<std::uint32_t*>(p + 0x0c);
    return true;
}

void trace_spawner(void* cpnt) {
    // prepare fires on every spawner tick; cap the volume so the log stays
    // useful. The first calls already carry the vtable we need.
    static int calls = 0;
    if (calls > 32) return;
    if (++calls == 32) {
        Loader::get().log("[spawn-trace] muting further prepare calls (>32)");
    }

    std::uintptr_t cvt = vtable_of(cpnt);
    void* owner = readable(reinterpret_cast<std::uint8_t*>(cpnt) + kOwnerOff, 8)
                      ? *reinterpret_cast<void**>(reinterpret_cast<std::uint8_t*>(cpnt) + kOwnerOff)
                      : nullptr;
    std::uintptr_t ovt = vtable_of(owner);

    void* cdata = nullptr;
    std::uint32_t ccount = 0, ccap = 0;
    bool have_cand = read_vec(cpnt, kCandVecOff, &cdata, &ccount, &ccap);

    Loader::get().log("[spawn-trace] cpnt=" + hex_of((std::uintptr_t)cpnt)
                      + " vt=" + hex_of(cvt)
                      + " owner=" + hex_of((std::uintptr_t)owner)
                      + " owner.vt=" + hex_of(ovt)
                      + " cand{data=" + hex_of((std::uintptr_t)cdata)
                      + " count=" + std::to_string(ccount)
                      + " cap=" + std::to_string(ccap) + "}");

    // Parallel arrays the prepare step resizes to the candidate count — likely
    // the per-candidate transforms (0x40 matrix) and spawned-instance slots.
    for (auto [off, tag] : { std::pair<std::size_t, const char*>{kArrA_Off, "+0x80"},
                             std::pair<std::size_t, const char*>{kArrB_Off, "+0xa0"} }) {
        void* d = nullptr; std::uint32_t c = 0, cp = 0;
        if (read_vec(cpnt, off, &d, &c, &cp)) {
            Loader::get().log(std::string("[spawn-trace]   par ") + tag
                              + "{data=" + hex_of((std::uintptr_t)d)
                              + " count=" + std::to_string(c)
                              + " cap=" + std::to_string(cp) + "}");
        }
    }

    if (!env_on("RSMM_SPAWN_TRACE_VERBOSE")) return;
    if (!have_cand || !cdata || ccount == 0 || ccount > 256) return;
    if (!readable(cdata, (std::size_t)ccount * kPtrStride)) return;

    // Each candidate is an oCEntitySettingsRootPtr*; the resolved entity
    // template sits at entry+0x18. Logging the template VA + its vtable per
    // candidate identifies what each spawner is configured to produce.
    auto* arr = reinterpret_cast<void**>(cdata);
    for (std::uint32_t i = 0; i < ccount; ++i) {
        void* entry = arr[i];
        void* tmpl = (readable(reinterpret_cast<std::uint8_t*>(entry) + kEntryTmpl, 8))
                         ? *reinterpret_cast<void**>(reinterpret_cast<std::uint8_t*>(entry) + kEntryTmpl)
                         : nullptr;
        Loader::get().log("[spawn-trace]   cand[" + std::to_string(i) + "] entry="
                          + hex_of((std::uintptr_t)entry)
                          + " tmpl=" + hex_of((std::uintptr_t)tmpl)
                          + " tmpl.vt=" + hex_of(vtable_of(tmpl)));
    }
}

void hook_prepare(void* cpnt) {
    if (g_real_prepare) g_real_prepare(cpnt);  // run picker first: builds candidates
    if (cpnt) trace_spawner(cpnt);
}

} // anonymous namespace

bool install_spawn_hooks() {
    // OPT-IN: like the skill hook, detouring an engine virtual is experimental
    // and can fail to resolve under Proton/Wine, so it is off by default and the
    // loader always launches without it.
    if (!env_on("RSMM_ENABLE_SPAWN_HOOK")) {
        Loader::get().log("[spawn-trace] disabled (set RSMM_ENABLE_SPAWN_HOOK=1 to arm)");
        return false;
    }
    if (!fn_resolver_init()) {
        Loader::get().log("[spawn-trace] fn_resolver_init failed");
        return false;
    }
    std::uintptr_t va = fn_resolve("FUN_140330c30");
    if (va == 0 || va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log("[spawn-trace] FUN_140330c30 pattern not found; disabled");
        return false;
    }
    if (!fn_verify("FUN_140330c30", va)) {
        Loader::get().log("[spawn-trace] FUN_140330c30 verify failed (game patched?)");
        return false;
    }
    Loader::get().log("[spawn-trace] selector prepare @ " + hex_of(va));

    const auto target = reinterpret_cast<LPVOID>(va);
    auto rc = MH_CreateHook(target, reinterpret_cast<LPVOID>(&hook_prepare),
                            reinterpret_cast<LPVOID*>(&g_real_prepare));
    if (rc != MH_OK) {
        Loader::get().log("[spawn-trace] MH_CreateHook failed rc="
                          + std::to_string(static_cast<int>(rc)));
        return false;
    }
    if (MH_EnableHook(target) != MH_OK) {
        Loader::get().log("[spawn-trace] MH_EnableHook failed");
        return false;
    }
    Loader::get().log("[spawn-trace] installed on FUN_140330c30 (selector prepare)");
    return true;
}

} // namespace rsmm
