// R.ui: what the game's UI is showing. See hook_ui_state.h for the design;
// RE notes on the two runners are in data/symbols.json
// (EntityComponent_RunActivate / EntityComponent_RunDeactivate).

#include "hook_ui_state.h"

#include <windows.h>

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

#include "fn_resolver.h"
#include "hook_util.h"
#include "loader.h"
#include "mem_safe.h"
#include "script_lua.h"
#include "symbols.gen.h"

namespace rsmm {
namespace {

// The component flags byte the runners keep (see the symbol notes): bit 0x08
// is "active", set by RunActivate and cleared by RunDeactivate.
constexpr std::size_t kFlagsOff = 0x64;
constexpr std::uint8_t kActiveBit = 0x08;

struct UiClass {
    const char* rtti;    // demangled RTTI class name
    const char* label;   // what R.ui reports
    UiKind kind;
    std::uintptr_t vft;  // runtime vftable, 0 = not found on this build
};

// The kinds PR #110 tracks, plus the book's pages. Names from the b9c3642884a8 RTTI corpus
// (docs/_re/out_new/vftables.jsonl). A class missing on a future build is
// skipped, not fatal.
UiClass g_classes[] = {
    {"oCDtEntityCpntEscapeGameMenuUiController",     "EscapeGameMenu",    UiKind::Menu, 0},
    {"oCDtEntityCpntMainMenuUiController",           "MainMenu",          UiKind::Menu, 0},
    {"oCDtEntityCpntSelectionMenuUiController",      "SelectionMenu",     UiKind::Menu, 0},
    {"oCDtEntityCpntSandmanMenuUiController",        "SandmanMenu",       UiKind::Menu, 0},
    {"oe::dt::InventoryMenuUiControllerEntityCpnt",  "InventoryMenu",     UiKind::Menu, 0},
    {"oe::dt::MagicMirrorMenuUiControllerEntityCpnt", "MagicMirrorMenu",  UiKind::Menu, 0},
    {"oe::dt::SocialOptionsMenuUiControllerEntityCpnt", "SocialOptionsMenu", UiKind::Menu, 0},
    {"oCDtEntityCpntBookMenuUiController",           "BookMenu",          UiKind::Book, 0},
    {"oCEntityCpntModalUiController",                "Modal",             UiKind::Modal, 0},
    {"oe::dt::EULAModalUiControllerEntityCpnt",      "EULAModal",         UiKind::Modal, 0},
    {"oe::dt::MultiplayerModalUiControllerEntityCpnt", "MultiplayerModal", UiKind::Modal, 0},
    {"oe::dt::MyNaconModalUiControllerEntityCpnt",   "MyNaconModal",      UiKind::Modal, 0},
    {"oCDtEntityCpntLoadingScreenUiController",      "LoadingScreen",     UiKind::Loading, 0},
    // The book's pages (b9c3 RTTI; most override slot 28 with a show of
    // their own, i.e. the game activates each page as it is shown).
    {"oCDtEntityCpntPlayBookPageUiController",       "PlayPage",          UiKind::Page, 0},
    {"oCDtEntityCpntSelectHeroBookPageUiController", "HeroSelectPage",    UiKind::Page, 0},
    {"oe::dt::EntityCpntHeroMetaBookPageUiController", "HeroPage",        UiKind::Page, 0},
    {"oe::dt::HeroStoryPageUiControllerEntityCpnt",  "HeroStoryPage",     UiKind::Page, 0},
    {"oe::dt::MerlinAbilitiesMetaBookPageUiControllerEntityCpnt", "MerlinAbilitiesPage", UiKind::Page, 0},
    {"oe::dt::EntityCpntCompendiumBookPageUiController", "CompendiumPage", UiKind::Page, 0},
    {"oe::dt::HeroesCompendiumPageUiControllerEntityCpnt", "HeroesCompendiumPage", UiKind::Page, 0},
    {"oe::dt::MagicalObjectsCompendiumPageUiControllerEntityCpnt", "ItemsCompendiumPage", UiKind::Page, 0},
    {"oe::dt::MemoriesCompendiumPageUiControllerEntityCpnt", "MemoriesCompendiumPage", UiKind::Page, 0},
    {"oe::dt::TutoCompendiumPageEntityCpnt",         "TutorialPage",      UiKind::Page, 0},
    {"oe::dt::ChallengesPageUiControllerEntityCpnt", "ChallengesPage",    UiKind::Page, 0},
    {"oe::dt::SelectChallengePageUiControllerEntityCpnt", "SelectChallengePage", UiKind::Page, 0},
    {"oe::dt::CustomizeChallengePageUiControllerEntityCpnt", "CustomizeChallengePage", UiKind::Page, 0},
    {"oe::dt::SocialBookPageEntityCpnt",             "SocialPage",        UiKind::Page, 0},
    {"oe::dt::BookOptionsUiControllerEntityCpnt",    "OptionsPage",       UiKind::Page, 0},
    {"oe::dt::EntityCpntRecapBookPage",              "RecapPage",         UiKind::Page, 0},
    {"oe::dt::EntityCpntPlayerResultStatBookPage",   "ResultStatsPage",   UiKind::Page, 0},
    {"oe::dt::EntityCpntBookScoreUiController",      "ScorePage",         UiKind::Page, 0},
};
constexpr std::size_t kClassCount = sizeof(g_classes) / sizeof(g_classes[0]);

// The vftables found, packed for the hot-path compare (the detour runs for
// every component in the game).
std::uintptr_t g_vfts[kClassCount] = {};
const UiClass* g_vft_class[kClassCount] = {};
std::size_t g_vft_count = 0;

using Run_t = void (*)(void*);
Run_t g_real_activate = nullptr;
Run_t g_real_deactivate = nullptr;

std::mutex g_arm_mu;
std::atomic<bool> g_armed{false};
std::string g_arm_why;

// ---- RTTI: class name -> vftable --------------------------------------------

struct Section { std::uintptr_t lo, hi; };

bool image_sections(std::uintptr_t base, Section* rdata, Section* data) {
    auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    auto* sec = IMAGE_FIRST_SECTION(nt);
    bool got_r = false, got_d = false;
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; ++i) {
        char name[9] = {};
        std::memcpy(name, sec[i].Name, 8);
        Section s{base + sec[i].VirtualAddress,
                  base + sec[i].VirtualAddress + sec[i].Misc.VirtualSize};
        if (std::strcmp(name, ".rdata") == 0) { *rdata = s; got_r = true; }
        if (std::strcmp(name, ".data") == 0)  { *data = s;  got_d = true; }
    }
    return got_r && got_d;
}

// "oe::dt::Foo" -> ".?AVFoo@dt@oe@@" (MSVC type descriptor name).
std::string mangle(std::string_view name) {
    std::vector<std::string_view> parts;
    std::size_t at = 0;
    while (true) {
        std::size_t p = name.find("::", at);
        parts.push_back(name.substr(at, p == std::string_view::npos ? p : p - at));
        if (p == std::string_view::npos) break;
        at = p + 2;
    }
    std::string out = ".?AV";
    out += parts.back();
    for (std::size_t i = parts.size() - 1; i-- > 0;) {
        out += '@';
        out += parts[i];
    }
    out += "@@";
    return out;
}

std::uintptr_t find_bytes(const Section& s, const char* needle, std::size_t n) {
    if (s.hi - s.lo < n) return 0;
    const auto* p = reinterpret_cast<const char*>(s.lo);
    const auto* end = reinterpret_cast<const char*>(s.hi) - n;
    for (; p <= end; ++p) {
        if (*p == needle[0] && std::memcmp(p, needle, n) == 0)
            return reinterpret_cast<std::uintptr_t>(p);
    }
    return 0;
}

// x64 MSVC RTTI: TypeDescriptor {vftable*, spare, char name[]} lives in .data;
// CompleteObjectLocator {u32 signature=1, u32 offset, u32 cdOffset,
// u32 typeDescriptorRVA, u32 classDescriptorRVA, u32 selfRVA} in .rdata; the
// qword just before a vftable points at its COL. Only the primary vftable
// (offset 0) is wanted: a component's first qword.
std::uintptr_t find_vftable(std::uintptr_t base, const Section& rdata, const Section& data,
                            const char* rtti) {
    const std::string name = mangle(rtti);
    // name + its terminator, so "Modal" does not match "ModalFoo"
    std::uintptr_t str = find_bytes(data, name.c_str(), name.size() + 1);
    if (str == 0) return 0;
    const std::uint32_t td_rva = static_cast<std::uint32_t>(str - 0x10 - base);
    std::uintptr_t col = 0;
    for (std::uintptr_t a = rdata.lo; a + 24 <= rdata.hi; a += 4) {
        const auto* u = reinterpret_cast<const std::uint32_t*>(a);
        if (u[3] == td_rva && u[0] == 1 && u[1] == 0 &&
            u[5] == static_cast<std::uint32_t>(a - base)) {
            col = a;
            break;
        }
    }
    if (col == 0) return 0;
    for (std::uintptr_t a = rdata.lo; a + 16 <= rdata.hi; a += 8) {
        if (*reinterpret_cast<const std::uintptr_t*>(a) == col) return a + 8;
    }
    return 0;
}

// ---- state ------------------------------------------------------------------

struct Tracked {
    std::uintptr_t ptr;
    const UiClass* cls;
};

struct Pending {
    bool open;
    std::uintptr_t ptr;
    const UiClass* cls;
};

std::mutex g_mu;                  // guards g_open, g_pending
std::vector<Tracked> g_open;      // oldest first; a handful at most
std::vector<Pending> g_pending;   // events waiting for the outermost runner
// Set when g_pending gains an event: the outermost runner checks it for ANY
// component, because a UI controller is often activated inside a non-UI
// component's activation (a state's listeners), whose runner does not match.
std::atomic<bool> g_dirty{false};

thread_local int t_depth = 0;     // runner nesting on this thread

inline const UiClass* match(void* cpnt) {
    // The runner's first act is to read through `cpnt`, so the component
    // pointer is live; its first qword is the vftable.
    const std::uintptr_t vft = *reinterpret_cast<const std::uintptr_t*>(cpnt);
    for (std::size_t i = 0; i < g_vft_count; ++i)
        if (g_vfts[i] == vft) return g_vft_class[i];
    return nullptr;
}

inline bool is_active(std::uintptr_t ptr) {
    return (*reinterpret_cast<const std::uint8_t*>(ptr + kFlagsOff) & kActiveBit) != 0;
}

// is_active() for a component that may be gone: the memory must still be
// readable and still carry the class's vftable, else it counts as not active.
inline bool is_active_checked(std::uintptr_t ptr, const UiClass* cls) {
    return mem_readable(reinterpret_cast<const void*>(ptr), kFlagsOff + 1) &&
           *reinterpret_cast<const std::uintptr_t*>(ptr) == cls->vft &&
           is_active(ptr);
}

// After a runner returns: compare the component's active bit with our record.
void record(void* cpnt, const UiClass* cls) {
    const auto ptr = reinterpret_cast<std::uintptr_t>(cpnt);
    // The original has returned; the component may have been freed meanwhile.
    const bool active = is_active_checked(ptr, cls);
    std::lock_guard<std::mutex> lk(g_mu);
    std::size_t i = 0;
    while (i < g_open.size() && g_open[i].ptr != ptr) ++i;
    const bool was = i < g_open.size();
    if (active && !was) {
        g_open.push_back({ptr, cls});
        g_pending.push_back({true, ptr, cls});
        g_dirty.store(true, std::memory_order_release);
    } else if (!active && was) {
        g_open.erase(g_open.begin() + static_cast<std::ptrdiff_t>(i));
        g_pending.push_back({false, ptr, cls});
        g_dirty.store(true, std::memory_order_release);
    }
}

std::string payload(const Pending& e) {
    char buf[224];
    std::snprintf(buf, sizeof(buf),
                  "{\"kind\":\"%s\",\"class\":\"%s\",\"ptr\":%llu}",
                  ui_kind_name(e.cls->kind), e.cls->label,
                  static_cast<unsigned long long>(e.ptr));
    return buf;
}

// Emit what the runners queued, once the outermost runner on this thread has
// returned: a mod handler never runs inside the engine's activation.
void flush() {
    std::vector<Pending> out;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        g_dirty.store(false, std::memory_order_relaxed);
        if (g_pending.empty()) return;
        out.swap(g_pending);
    }
    for (const auto& e : out) {
        const char* name = e.open ? "ui:open" : "ui:close";
        if (script_has_handler(name)) script_emit_event_json(name, payload(e));
    }
}

void hook_activate(void* cpnt) {
    const UiClass* cls = cpnt ? match(cpnt) : nullptr;
    ++t_depth;
    g_real_activate(cpnt);
    --t_depth;
    if (cls) record(cpnt, cls);
    if (t_depth == 0 && g_dirty.load(std::memory_order_acquire)) flush();
}

void hook_deactivate(void* cpnt) {
    const UiClass* cls = cpnt ? match(cpnt) : nullptr;
    ++t_depth;
    g_real_deactivate(cpnt);
    --t_depth;
    if (cls) record(cpnt, cls);
    if (t_depth == 0 && g_dirty.load(std::memory_order_acquire)) flush();
}

// Drop tracked controllers that are gone or no longer active (destroyed
// without a deactivate, or a missed transition). Each one queues its ui:close,
// emitted by the next outermost runner: prune runs inside Lua calls that hold
// the script lock, so it must not flush here.
void prune_locked() {
    for (std::size_t i = 0; i < g_open.size();) {
        const Tracked t = g_open[i];
        if (is_active_checked(t.ptr, t.cls)) { ++i; continue; }
        g_open.erase(g_open.begin() + static_cast<std::ptrdiff_t>(i));
        g_pending.push_back({false, t.ptr, t.cls});
        g_dirty.store(true, std::memory_order_release);
    }
}

} // namespace

const char* ui_kind_name(UiKind kind) {
    switch (kind) {
        case UiKind::Menu: return "menu";
        case UiKind::Book: return "book";
        case UiKind::Modal: return "modal";
        case UiKind::Loading: return "loading";
        case UiKind::Page: return "page";
        default: return nullptr;
    }
}

bool ui_kind_from_name(const char* name, UiKind* out) {
    if (!name) return false;
    for (int k = 0; k < static_cast<int>(UiKind::Count); ++k) {
        if (std::strcmp(name, ui_kind_name(static_cast<UiKind>(k))) == 0) {
            *out = static_cast<UiKind>(k);
            return true;
        }
    }
    return false;
}

bool ui_state_armed() { return g_armed.load(std::memory_order_acquire); }

bool ui_state_arm(std::string* why) {
    std::lock_guard<std::mutex> lk(g_arm_mu);
    if (g_armed.load()) return true;
    auto fail = [&](const std::string& reason, bool error) {
        g_arm_why = reason;
        if (why) *why = reason;
        if (error) Loader::get().log_err("[ui-state] " + reason);
        else Loader::get().log("[ui-state] " + reason);
        return false;
    };
    if (!g_arm_why.empty()) {            // a failed arm is not retried every call
        if (why) *why = g_arm_why;
        return false;
    }
    if (flag_enabled("RSMM_DISABLE_UI_STATE"))
        return fail("disabled by RSMM_DISABLE_UI_STATE", false);
    if (!fn_resolver_init()) return fail("fn_resolver_init failed", true);

    const auto base = reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
    Section rdata{}, data{};
    if (!image_sections(base, &rdata, &data))
        return fail("could not read the game's .rdata/.data sections", true);
    std::string found, missing;
    for (auto& c : g_classes) {
        c.vft = find_vftable(base, rdata, data, c.rtti);
        if (c.vft) {
            g_vfts[g_vft_count] = c.vft;
            g_vft_class[g_vft_count] = &c;
            ++g_vft_count;
            found += found.empty() ? c.label : std::string(",") + c.label;
        } else {
            missing += missing.empty() ? c.label : std::string(",") + c.label;
        }
    }
    if (g_vft_count == 0)
        return fail("no UI controller vftable found by RTTI (game patched?)", true);
    if (!missing.empty())
        Loader::get().log_warn("[ui-state] RTTI not found for: " + missing);

    std::uintptr_t act_va = 0, deact_va = 0;
    if (!hook_install("ui-state", "EntityComponent_RunActivate",
                      Sym::EntityComponent_RunActivate_Pattern,
                      reinterpret_cast<void*>(&hook_activate),
                      reinterpret_cast<void**>(&g_real_activate), &act_va))
        return fail("could not hook EntityComponent_RunActivate", true);
    if (!hook_install("ui-state", "EntityComponent_RunDeactivate",
                      Sym::EntityComponent_RunDeactivate_Pattern,
                      reinterpret_cast<void*>(&hook_deactivate),
                      reinterpret_cast<void**>(&g_real_deactivate), &deact_va)) {
        hook_remove(act_va);
        return fail("could not hook EntityComponent_RunDeactivate", true);
    }
    g_armed.store(true, std::memory_order_release);
    Loader::get().log("[ui-state] armed: " + std::to_string(g_vft_count) + " UI classes (" +
                      found + ") -> R.ui, R.on('ui:open'/'ui:close')");
    return true;
}

bool install_ui_state_hooks() {
    // Armed at loader startup so controllers opened later are all seen and a
    // mod's first R.ui call already knows what is open. A refusal (disabled,
    // game patched) is logged by ui_state_arm and costs only this capability.
    return ui_state_arm();
}

int ui_state_count(UiKind kind) {
    if (!ui_state_armed()) return -1;
    std::lock_guard<std::mutex> lk(g_mu);
    prune_locked();
    int n = 0;
    for (const auto& t : g_open)
        if (t.cls->kind == kind) ++n;
    return n;
}

std::vector<UiOpen> ui_state_open() {
    std::vector<UiOpen> out;
    if (!ui_state_armed()) return out;
    std::lock_guard<std::mutex> lk(g_mu);
    prune_locked();
    for (const auto& t : g_open) out.push_back({t.ptr, t.cls->kind, t.cls->label});
    return out;
}

} // namespace rsmm
