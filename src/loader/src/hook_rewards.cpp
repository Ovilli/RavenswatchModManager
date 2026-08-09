// Reward-roll diagnostic dump — see hook_rewards.h for the why.
//
// Detours the reward roll FUN_1401e9800 (the fill/distribute fn; carries the
// strings "Distribute", "Fill remaining rewards on random slot", "Reward type
// {}"). On the first fire it enumerates the reward-def registry and the
// scene-context def and logs each def's reward_types shape, so the def that
// actually carries the (still-spawning) basic chests can be identified. It never
// edits anything.
//
// Layout (RE 2026-07-12, docs/_re/kinds/rewards.md):
//   registry: begin ptr @ g_RewardDefRegistry_Begin, end ptr @ ..._End; the
//     half-open [begin,end) is an array of 8-byte def-holder slots.
//   oCDtRewardDefinition: reward_types vector ptr @+0x288, count @+0x290; the
//     vector data is an array of pointers to type entries.
//   reward_type entry: items vec @+0x08 (ptr) / +0x10 (count); min @+0x18;
//     max @+0x1c.
//   scene context: the guaranteed-path def is at ctx+0xa8 (param_1[0x15]).

#include <windows.h>

#include <cstdint>
#include <string>

#include "MinHook.h"
#include "loader.h"
#include "mem_safe.h"
#include "fn_resolver.h"
#include "hook_util.h"
#include "symbols.gen.h"  // GENERATED — Sym::
#include "hook_rewards.h"

namespace rsmm {
namespace {

constexpr std::uintptr_t kImgBase           = 0x140000000ull;
constexpr std::uintptr_t kRegistryBeginVA   = 0x141440420ull;  // reward-def registry begin ptr
constexpr std::uintptr_t kRegistryEndVA     = 0x141440428ull;  // reward-def registry end ptr
constexpr std::size_t    kCtxDefOff         = 0xa8;            // guaranteed-path def on the ctx
constexpr std::size_t    kTypesPtrOff       = 0x288;           // reward_types vector data ptr
constexpr std::size_t    kTypesCountOff     = 0x290;           // reward_types count
constexpr std::size_t    kTypeItemsCountOff = 0x10;            // items count on a type entry
constexpr std::size_t    kTypeMinOff        = 0x18;
constexpr std::size_t    kTypeMaxOff        = 0x1c;

using RollFn = void (*)(void*);
RollFn g_real_roll = nullptr;

bool env_on(const char* name) { return flag_enabled(name); }

// Confirm [p, p+size) is committed + readable so a wrong offset logs/skips
// instead of faulting (MinGW has no __try/__except). Shared implementation.
inline bool readable(const void* p, std::size_t size) { return mem_readable(p, size); }

std::string hex_of(std::uintptr_t v) {
    char b[32];
    snprintf(b, sizeof(b), "0x%llx", static_cast<unsigned long long>(v));
    return b;
}

std::uintptr_t image_base() {
    HMODULE h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    return reinterpret_cast<std::uintptr_t>(h);
}

// Rebase a static VA (preferred base 0x140000000) onto the live image.
std::uintptr_t reloc(std::uintptr_t static_va) {
    const std::uintptr_t b = image_base();
    if (b == 0) return 0;
    return static_va - kImgBase + b;
}

template <typename T>
T rd(const void* base, std::size_t off) {
    return *reinterpret_cast<const T*>(reinterpret_cast<const std::uint8_t*>(base) + off);
}

// If `cand` looks like an oCDtRewardDefinition (readable, plausible reward_types
// vector), log its type shape and return true. Otherwise return false.
bool dump_def_if_reward(void* cand, const std::string& label) {
    if (!readable(cand, kTypesCountOff + 4)) return false;
    void* types = rd<void*>(cand, kTypesPtrOff);
    std::uint32_t n = rd<std::uint32_t>(cand, kTypesCountOff);
    if (n == 0 || n > 64) return false;
    if (!readable(types, static_cast<std::size_t>(n) * 8)) return false;

    std::string line = "[reward-dump] " + label + " def=" + hex_of((std::uintptr_t)cand)
                       + " types=" + std::to_string(n) + " {";
    auto* arr = reinterpret_cast<void**>(types);
    for (std::uint32_t i = 0; i < n; ++i) {
        void* t = arr[i];
        if (!readable(t, kTypeMaxOff + 4)) { line += "?,"; continue; }
        std::uint32_t items = rd<std::uint32_t>(t, kTypeItemsCountOff);
        std::uint32_t mn = rd<std::uint32_t>(t, kTypeMinOff);
        std::uint32_t mx = rd<std::uint32_t>(t, kTypeMaxOff);
        line += "(min=" + std::to_string(mn) + ",max=" + std::to_string(mx)
                + ",items=" + std::to_string(items) + ")";
        if (i + 1 < n) line += ",";
    }
    line += "}";
    Loader::get().log(line);
    return true;
}

void dump_registry_and_context(void* ctx) {
    if (image_base() == 0) { Loader::get().log("[reward-dump] no module base"); return; }

    // --- reward-def registry: [begin, end) array of 8-byte def-holder slots.
    void** pbegin = reinterpret_cast<void**>(reloc(kRegistryBeginVA));
    void** pend   = reinterpret_cast<void**>(reloc(kRegistryEndVA));
    if (readable(pbegin, 8) && readable(pend, 8)) {
        auto* begin = *reinterpret_cast<std::uint8_t**>(pbegin);
        auto* end   = *reinterpret_cast<std::uint8_t**>(pend);
        std::ptrdiff_t span = end - begin;
        if (begin && end > begin && span < 0x40000 && (span % 8) == 0
                && readable(begin, static_cast<std::size_t>(span))) {
            std::uint32_t count = static_cast<std::uint32_t>(span / 8);
            Loader::get().log("[reward-dump] registry [" + hex_of((std::uintptr_t)begin) + ","
                              + hex_of((std::uintptr_t)end) + ") slots=" + std::to_string(count));
            int shown = 0;
            for (std::uint32_t i = 0; i < count && shown < 128; ++i) {
                void* slot = *reinterpret_cast<void**>(begin + i * 8);
                if (!slot) continue;
                // The slot may be the def directly, or a one-level holder.
                std::string lbl = "reg[" + std::to_string(i) + "]";
                if (dump_def_if_reward(slot, lbl)) { ++shown; continue; }
                if (readable(slot, 8)) {
                    void* inner = *reinterpret_cast<void**>(slot);
                    if (dump_def_if_reward(inner, lbl + "->*")) { ++shown; continue; }
                }
            }
            if (shown == 0)
                Loader::get().log("[reward-dump] registry held no recognizable reward defs "
                                  "(holder layout differs) — begin/end interpretation may be off");
        } else {
            Loader::get().log("[reward-dump] registry begin/end implausible (begin="
                              + hex_of((std::uintptr_t)begin) + " end=" + hex_of((std::uintptr_t)end)
                              + ") — globals may have shifted");
        }
    }

    // --- guaranteed-path def on the scene context (ctx+0xa8).
    if (readable(ctx, kCtxDefOff + 8)) {
        void* ctxdef = rd<void*>(ctx, kCtxDefOff);
        if (!dump_def_if_reward(ctxdef, "ctx+0xa8"))
            Loader::get().log("[reward-dump] ctx+0xa8 def=" + hex_of((std::uintptr_t)ctxdef)
                              + " has no +0x288 reward_types (guaranteed path uses a different"
                                " layout @+0xe0/+0xf0)");
    }
}

void hook_reward_roll(void* ctx) {
    static bool done = false;
    if (!done) {
        done = true;
        Loader::get().log("[reward-dump] roll fired; dumping reward-def registry + context def");
        if (ctx) dump_registry_and_context(ctx);
    }
    if (g_real_roll) g_real_roll(ctx);
}

} // anonymous namespace

bool install_reward_hooks() {
    if (!env_on("RSMM_ENABLE_REWARD_DUMP")) {
        Loader::get().log("[reward-dump] disabled (set RSMM_ENABLE_REWARD_DUMP=1 to arm)");
        return false;
    }
    // Semantic name, not the build-specific "FUN_1401e9800" literal this used
    // to carry (see hook_util.h for why a literal is unsafe even when it
    // resolves and verifies).
    return hook_install("reward-dump", "reward roll",
                        Sym::Reward_InitAllRewards_Pattern,
                        reinterpret_cast<void*>(&hook_reward_roll),
                        reinterpret_cast<void**>(&g_real_roll));
}

} // namespace rsmm
