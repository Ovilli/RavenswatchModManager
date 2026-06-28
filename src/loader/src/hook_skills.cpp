// Runtime skill (talent) injection — see hook_skills.h for the why.
//
// Detours the herodef deserialiser (FUN_14031e630). After the original runs,
// the herodef instance is fully populated; we inspect (and, when enabled,
// grow) the runtime skill vector at herodef+0x7d0. This avoids editing the
// crash-prone serialized .gen entirely.

#include <windows.h>

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>

#include "MinHook.h"
#include "loader.h"
#include "fn_resolver.h"
#include "hook_skills.h"

namespace rsmm {
namespace {

// herodef instance layout (RE 2026-06-17, docs/_re/kinds/skills-system.md):
//   +0x8d8  TALENT vector  { void* data; u32 count; u32 cap; }
//   Confirmed via [skill-probe]: count==28 on every hero. The vector is a
//   POINTER ARRAY (stride 8) — each element is a SkillController* (all share one
//   vtable, objects spaced 0xe0). cap==count==28 (exact-fit) so adding a 29th
//   needs a realloc, not a spare slot.
//   (The old +0x7d0 vector held only 3-11 small entries — NOT the talent set.)
constexpr std::size_t kTalentVecOff  = 0x8d8;
constexpr std::size_t kVecCountOff   = 0x08;
constexpr std::size_t kVecCapOff     = 0x0c;
constexpr std::size_t kPtrStride     = 0x08;

// Each element is an oe::dt::SkillProfileDataSettings (vftable 0x140efd018, ctor
// FUN_1400c9210). Object size 0xd0; the 16-byte identity GUID lives at +0x10 (the
// engine dedups talents by it — confirmed by host-side byte-diff of two elements).
constexpr std::size_t kSpdsSize      = 0xd0;
constexpr std::size_t kGuidOff       = 0x10;

// The deserialiser: char FUN_14031e630(void* herodef, void* stream). Returns 1
// on success. Pattern lives in data/function_patterns.json.
using Deserialize_t = char (*)(void*, void*);
Deserialize_t g_real_deserialize = nullptr;

bool env_on(const char* name) {
    char buf[8];
    return GetEnvironmentVariableA(name, buf, sizeof(buf)) && buf[0] == '1';
}

// Confirm [addr, addr+size) is committed + readable, so a wrong offset logs/skips
// instead of faulting. (MinGW has no __try/__except.)
bool readable(const void* p, std::size_t size) {
    auto a = reinterpret_cast<std::uintptr_t>(p);
    if (a < 0x10000) return false;
    const DWORD ok = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY |
                     PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    for (std::uintptr_t x = a; x < a + size; ) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (VirtualQuery(reinterpret_cast<void*>(x), &mbi, sizeof(mbi)) == 0) return false;
        if (mbi.State != MEM_COMMIT) return false;
        if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
        x = reinterpret_cast<std::uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
    }
    return true;
}

std::string hex_of(std::uintptr_t v) {
    char b[32];
    snprintf(b, sizeof(b), "0x%llx", static_cast<unsigned long long>(v));
    return b;
}

// One-shot structural probe: the +0x7d0 vector holds only 3-11 elements at
// runtime, but every hero has 28 talent rows (docs/_re/kinds/skills-system.md).
// So the talent collection is at some OTHER offset (doc also names +0x2b8 ->
// SkillProfileData -> +0x30). Rather than guess, scan the herodef for every
// {void* data; u32 count; u32 cap;} triple whose data is a readable pointer and
// count is in a plausible skill range, logging the offset + count. Run once.
void probe_vector_offsets(void* herodef) {
    static bool done = false;
    if (done) return;
    done = true;

    constexpr std::size_t kScanBytes = 0xA00;  // herodef size ~0x908
    if (!readable(herodef, kScanBytes)) {
        Loader::get().log("[skill-probe] herodef not readable for scan");
        return;
    }
    auto* b = reinterpret_cast<std::uint8_t*>(herodef);
    Loader::get().log("[skill-probe] scanning herodef="
                      + hex_of((std::uintptr_t)herodef) + " for vector triples");
    for (std::size_t off = 0; off + 0x10 <= kScanBytes; off += 8) {
        void* data        = *reinterpret_cast<void**>(b + off);
        std::uint32_t cnt = *reinterpret_cast<std::uint32_t*>(b + off + 8);
        std::uint32_t cap = *reinterpret_cast<std::uint32_t*>(b + off + 12);
        if (cnt < 2 || cnt > 64 || cap < cnt || cap > 4096) continue;
        if (!readable(data, 16)) continue;
        // Deref element[0] as a pointer and read its vtable, so each candidate
        // vector is identifiable by element class. The vector the details tab
        // enumerates will hold skill/talent objects with a recognisable vtable.
        std::string et;
        {
            void* e0 = *reinterpret_cast<void**>(data);
            if (readable(e0, 8)) {
                std::uintptr_t vt = *reinterpret_cast<std::uintptr_t*>(e0);
                et = " e0=" + hex_of((std::uintptr_t)e0) + " vt=" + hex_of(vt);
            } else {
                // maybe inline structs (not a pointer array): show first qword
                et = " inline0=" + hex_of(*reinterpret_cast<std::uintptr_t*>(data));
            }
        }
        Loader::get().log("[skill-probe]   +" + hex_of(off)
                          + " data=" + hex_of((std::uintptr_t)data)
                          + " count=" + std::to_string(cnt)
                          + " cap=" + std::to_string(cap) + et);
    }

    // === Talent->ability ref probe ==============================================
    // The grid column = the talent's ability. Abilities don't reference talents
    // (probed), so the link must be talent->ability. Dump each talent's pointer
    // fields and flag any that points INTO the ability array (+0x8e8 region), so
    // a host-side scan finds the column-ref offset. Also dump the +0x8e8 base/range.
    {
        void* tdata2 = *reinterpret_cast<void**>(b + 0x8d8);
        std::uint32_t tcnt2 = *reinterpret_cast<std::uint32_t*>(b + 0x8e0);
        void* adata2 = *reinterpret_cast<void**>(b + 0x8e8);
        std::uint32_t acnt2 = *reinterpret_cast<std::uint32_t*>(b + 0x8f0);
        if (readable(tdata2, 8) && readable(adata2, 8) && tcnt2 <= 64 && acnt2 <= 32) {
            std::uintptr_t abase = (std::uintptr_t)adata2;
            std::uintptr_t aend = abase + (std::size_t)acnt2 * 0x240;
            Loader::get().log("[skill-probe] ability range [" + hex_of(abase) + ","
                              + hex_of(aend) + ") count=" + std::to_string(acnt2));
            auto* tarr2 = reinterpret_cast<std::uintptr_t*>(tdata2);
            for (std::uint32_t i = 0; i < tcnt2; ++i) {
                std::uint8_t* o = reinterpret_cast<std::uint8_t*>(tarr2[i]);
                if (!readable(o, 0xd0)) continue;
                std::string ptrs;
                for (std::size_t off : {(std::size_t)0x50,(std::size_t)0x60,
                        (std::size_t)0x70,(std::size_t)0x78,(std::size_t)0x90,
                        (std::size_t)0xb8}) {
                    std::uintptr_t v = *reinterpret_cast<std::uintptr_t*>(o + off);
                    bool inAbil = (v >= abase && v < aend);
                    int aidx = inAbil ? (int)((v - abase) / 0x240) : -1;
                    ptrs += " +" + hex_of(off) + "=" + hex_of(v)
                          + (aidx >= 0 ? "(ABIL" + std::to_string(aidx) + ")" : "");
                }
                Loader::get().log("[skill-probe] tref t" + std::to_string(i) + ptrs);
            }
        }
    }
    // === Ability->talent mapping probe ===========================================
    // The TALENTS grid is columns=abilities, rows=tiers. The ABILITIES row shows
    // 5+2=7 icons and herodef+0x8e8 is a 7-element vector — likely the abilities,
    // each holding its talents (per tier). Capture the 28 talent pointers
    // (+0x8d8), then scan each of the 7 ability objects (+0x8e8, stride 0x238) for
    // qwords that point at a talent — that link IS the grid's column membership,
    // and the offset where it sits encodes the tier ordering.
    {
        void* tdata = *reinterpret_cast<void**>(b + 0x8d8);
        std::uint32_t tcnt = *reinterpret_cast<std::uint32_t*>(b + 0x8d8 + 8);
        void* adata = *reinterpret_cast<void**>(b + 0x8e8);
        std::uint32_t acnt = *reinterpret_cast<std::uint32_t*>(b + 0x8e8 + 8);
        if (readable(tdata, 8) && readable(adata, 8) && tcnt <= 64 && acnt <= 32) {
            auto* tarr = reinterpret_cast<std::uintptr_t*>(tdata);
            auto talent_index = [&](std::uintptr_t v) -> int {
                for (std::uint32_t i = 0; i < tcnt; ++i) if (tarr[i] == v) return (int)i;
                return -1;
            };
            constexpr std::size_t kAbilityStride = 0x238;
            auto* aarr = reinterpret_cast<std::uintptr_t*>(adata);
            for (std::uint32_t ai = 0; ai < acnt; ++ai) {
                std::uint8_t* ab = reinterpret_cast<std::uint8_t*>(aarr[ai]);
                if (!readable(ab, kAbilityStride)) {
                    // maybe inline array, not pointer array
                    ab = reinterpret_cast<std::uint8_t*>(adata) + (std::size_t)ai * kAbilityStride;
                    if (!readable(ab, kAbilityStride)) continue;
                }
                std::string hits;
                for (std::size_t off = 0; off + 8 <= kAbilityStride; off += 8) {
                    std::uintptr_t v = *reinterpret_cast<std::uintptr_t*>(ab + off);
                    int ti = talent_index(v);
                    if (ti >= 0) hits += " +" + hex_of(off) + "=t" + std::to_string(ti);
                }
                Loader::get().log("[skill-probe] ability[" + std::to_string(ai)
                                  + "] obj=" + hex_of((std::uintptr_t)ab)
                                  + " talent-refs:" + (hits.empty() ? " (none)" : hits));
            }
        }
    }
    // Also probe the +0x2b8 -> SkillProfileData -> +0x30 indirection the doc names.
    void* spd = *reinterpret_cast<void**>(b + 0x2b8);
    if (readable(spd, 0x40)) {
        auto* s = reinterpret_cast<std::uint8_t*>(spd);
        void* data        = *reinterpret_cast<void**>(s + 0x30);
        std::uint32_t cnt = *reinterpret_cast<std::uint32_t*>(s + 0x38);
        std::uint32_t cap = *reinterpret_cast<std::uint32_t*>(s + 0x3c);
        Loader::get().log("[skill-probe] +0x2b8->SPD=" + hex_of((std::uintptr_t)spd)
                          + " +0x30 data=" + hex_of((std::uintptr_t)data)
                          + " count=" + std::to_string(cnt)
                          + " cap=" + std::to_string(cap));
    } else {
        Loader::get().log("[skill-probe] +0x2b8 not a readable pointer");
    }
}

void inspect_and_maybe_inject(void* herodef) {
    probe_vector_offsets(herodef);
    if (!readable(herodef, kTalentVecOff + 0x10)) return;
    auto vec = reinterpret_cast<std::uint8_t*>(herodef) + kTalentVecOff;
    void* data    = *reinterpret_cast<void**>(vec);
    std::uint32_t count = *reinterpret_cast<std::uint32_t*>(vec + kVecCountOff);
    std::uint32_t cap   = *reinterpret_cast<std::uint32_t*>(vec + kVecCapOff);

    Loader::get().log("[skill-hook] herodef=" + hex_of((std::uintptr_t)herodef)
                      + " talentvec(+0x8d8) data=" + hex_of((std::uintptr_t)data)
                      + " count=" + std::to_string(count)
                      + " cap=" + std::to_string(cap));

    if (!env_on("RSMM_ENABLE_SKILL_INJECT")) return;

    // Self-guard: only act when this really looks like the talent vector, so a
    // wrong offset is inert. Talent set is 28 on every hero; allow a small band.
    if (!data || count < 8 || count > 64) {
        Loader::get().log("[skill-hook] inject skip: count out of range");
        return;
    }
    if (!readable(data, (std::size_t)count * kPtrStride)) {
        Loader::get().log("[skill-hook] inject skip: element range not readable");
        return;
    }
    // Each element is a SkillProfileDataSettings* (size 0xd0). Clone the LAST one
    // as a template, then remint its identity GUID at +0x10 so the engine treats
    // it as a DISTINCT talent (an exact-dup GUID would be deduped — same root
    // cause as the magical-object custom-clone grant collision). The clone shares
    // the template's internal sub-buffers (read-only for menu display), so this is
    // a valid, independently-identified 29th talent (visually a copy of the last
    // skill until its text/effect refs are repointed at custom content).
    // Clone element [0], a fully-populated talent. (The LAST element is an empty
    // sentinel — byte-diff showed its +0xb8 ptr and +0xc0 flags are null/zero, so
    // cloning it produced an invisible row.)
    auto* src = reinterpret_cast<void**>(data);
    void* tmpl = src[0];
    if (!readable(tmpl, kSpdsSize)) {
        Loader::get().log("[skill-hook] inject skip: template element not readable");
        return;
    }

    void* clone = std::malloc(kSpdsSize);
    if (!clone) {
        Loader::get().log("[skill-hook] inject skip: clone malloc failed");
        return;
    }
    std::memcpy(clone, tmpl, kSpdsSize);

    // Remint BOTH 16-byte GUIDs (identity +0x10 and skill-ref +0x40) so the engine
    // treats it as a distinct talent and does not dedup/collapse it onto the
    // template. Tag "RSMM" + process-global sequence + herodef pointer = unique.
    static std::uint32_t g_mint = 0;
    std::uint32_t seq = ++g_mint;
    std::uint64_t hd = reinterpret_cast<std::uint64_t>(herodef);
    for (std::size_t goff : { (std::size_t)kGuidOff, (std::size_t)0x40 }) {
        auto* guid = reinterpret_cast<std::uint8_t*>(clone) + goff;
        guid[0] = 'R'; guid[1] = 'S'; guid[2] = 'M'; guid[3] = 'M';
        std::memcpy(guid + 4, &seq, 4);
        std::memcpy(guid + 8, &hd, 8);
    }

    // cap==count (exact-fit), so there is no spare slot: realloc a bigger pointer
    // array, copy the existing pointers, append the clone, and repoint the vector.
    // Buffers are intentionally leaked (engine owns the original via its own
    // allocator; freeing ours through it would mismatch). herodefs persist for the
    // whole session and this vector is not re-grown after load.
    std::uint32_t new_cap = count + 1;
    void** grown = static_cast<void**>(std::malloc((std::size_t)new_cap * sizeof(void*)));
    if (!grown) {
        std::free(clone);
        Loader::get().log("[skill-hook] inject skip: array malloc failed");
        return;
    }
    std::memcpy(grown, src, (std::size_t)count * sizeof(void*));
    // The last element is an empty sentinel; keep it last so any terminator scan
    // still ends correctly. Insert the clone just BEFORE it (index count-1) so it
    // sits among the real, displayed entries rather than after the terminator.
    grown[count]     = src[count - 1];  // move sentinel to the new tail
    grown[count - 1] = clone;           // distinct clone among real talents

    *reinterpret_cast<void**>(vec)               = grown;
    *reinterpret_cast<std::uint32_t*>(vec + kVecCountOff) = count + 1;
    *reinterpret_cast<std::uint32_t*>(vec + kVecCapOff)   = new_cap;
    Loader::get().log("[skill-hook] injected custom talent (clone+remint): count "
                      + std::to_string(count) + " -> " + std::to_string(count + 1)
                      + " clone=" + hex_of((std::uintptr_t)clone)
                      + " seq=" + std::to_string(seq));
}

char hook_herodef_deserialize(void* herodef, void* stream) {
    char ok = g_real_deserialize ? g_real_deserialize(herodef, stream) : 0;
    if (ok == 1 && herodef) inspect_and_maybe_inject(herodef);
    return ok;
}

} // anonymous namespace

bool install_skill_hooks() {
    // OPT-IN: detouring the herodef deserialiser is experimental and, in a
    // Proton/Wine env where MinHook detours can resolve to bad addresses (the
    // item hook already logs MH_CreateHook rc=7), arming it can crash the game at
    // boot. Off by default so the loader always launches; enable to test.
    if (!env_on("RSMM_ENABLE_SKILL_HOOK")) {
        Loader::get().log("[skill-hook] disabled (set RSMM_ENABLE_SKILL_HOOK=1 to arm)");
        return false;
    }
    if (!fn_resolver_init()) {
        Loader::get().log("[skill-hook] fn_resolver_init failed");
        return false;
    }
    std::uintptr_t va = fn_resolve("FUN_14031e630");
    if (va == 0 || va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log("[skill-hook] FUN_14031e630 pattern not found; disabled");
        return false;
    }
    if (!fn_verify("FUN_14031e630", va)) {
        Loader::get().log("[skill-hook] FUN_14031e630 verify failed (game patched?)");
        return false;
    }
    Loader::get().log("[skill-hook] herodef deserialize @ " + hex_of(va));

    const auto target = reinterpret_cast<LPVOID>(va);
    auto rc = MH_CreateHook(target,
                            reinterpret_cast<LPVOID>(&hook_herodef_deserialize),
                            reinterpret_cast<LPVOID*>(&g_real_deserialize));
    if (rc != MH_OK) {
        Loader::get().log("[skill-hook] MH_CreateHook failed rc="
                          + std::to_string(static_cast<int>(rc)));
        return false;
    }
    if (MH_EnableHook(target) != MH_OK) {
        Loader::get().log("[skill-hook] MH_EnableHook failed");
        return false;
    }
    Loader::get().log("[skill-hook] installed on FUN_14031e630 (herodef deserialize)");
    return true;
}

} // namespace rsmm
