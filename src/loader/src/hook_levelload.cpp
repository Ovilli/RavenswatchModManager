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
// slot IS level+0x100, the resolvedPtr @+0x30 of the ref block at level+0xd0.
constexpr std::size_t kRefBlockBack = 0x30;
constexpr std::size_t kProbeBytes   = 48;

// The ref block opens with TWO {char* ptr, u32 len, u32 cap} strings, not one:
// the resource ROOT ("Ot", "Definitions", "EntitySettings") and then its PATH.
// Reading only the first is why six playtests of this trace reported the
// resource as `"Ot"` — a root shared by every level in the game, which names
// nothing. The root is what the `UsedRscCache` lines call the first field, so
// the pair together is exactly a cache line's `<Root>|<Path>`.
constexpr std::size_t kRefRootOff = 0x00;
constexpr std::size_t kRefPathOff = 0x10;

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

    // `obj+0x68` comes back null in practice, and a step nobody can name is a
    // step nobody can act on: this trace reported "<no name>" through six
    // playtests while one step per placed mod tile came back incomplete. So
    // fall back to the REF BLOCK. LevelStream_LoadStep's `rdx` is the level's
    // resolved-pointer field (level+0x100), and ResourceRef_Resolve documents
    // that field at +0x30 of a 0x38-byte ref block — so the block starts at
    // slot-0x30 and opens with TWO strings, root then path (see kRefRootOff).
    // Guarded like everything else here: a half-built slot is the state this
    // trace exists to catch.
    char root[64], path[256];
    root[0] = path[0] = '\0';
    if (slot) {
        const auto ref = reinterpret_cast<std::uintptr_t>(slot) - kRefBlockBack;
        auto lstr = [&](std::size_t off, char* out, std::size_t cap) {
            char* sp = nullptr;
            std::uint32_t slen = 0;
            if (mem_load(ref + off, &sp) && sp
                && mem_load(ref + off + sizeof(void*), &slen)
                && slen > 0 && slen < cap) {
                mem_read_cstr(reinterpret_cast<std::uintptr_t>(sp), out, cap);
            }
        };
        lstr(kRefRootOff, root, sizeof(root));
        lstr(kRefPathOff, path, sizeof(path));
    }

    // First failure only: raw bytes of both candidates, so if neither guess is
    // where the name lives it can be found without another build.
    if (n == 1) {
        char hex[3 * kProbeBytes + 1];
        auto dump = [&](std::uintptr_t at, const char* what) {
            hex[0] = '\0';
            for (std::size_t i = 0; i < kProbeBytes; ++i) {
                std::uint8_t b = 0;
                if (!mem_load(at + i, &b)) { std::snprintf(hex, sizeof(hex), "<unreadable>"); return; }
                std::snprintf(hex + i * 3, 4, "%02x ", b);
            }
            char l[512];
            std::snprintf(l, sizeof(l), "[lvl-trace] probe %s @%#llx: %s", what,
                          static_cast<unsigned long long>(at), hex);
            Loader::get().log(l);
        };
        if (obj) dump(reinterpret_cast<std::uintptr_t>(obj), "object");
        // 48 bytes covers the whole block up to resolvedPtr, so if the PATH is
        // not at +0x10 the correct offset is visible here without a rebuild.
        if (slot) dump(reinterpret_cast<std::uintptr_t>(slot) - kRefBlockBack, "refblock");
    }

    if (name[0] == '\0' && path[0] != '\0') {
        if (root[0] != '\0') std::snprintf(name, sizeof(name), "%s|%s", root, path);
        else                  std::snprintf(name, sizeof(name), "%s", path);
    }
    if (name[0] == '\0') std::snprintf(name, sizeof(name), "<no name>");

    // WHAT THIS LINE MAY AND MAY NOT CLAIM.
    //
    // A `false` return from this step is "did not complete", and on this build
    // that is ordinarily a DEFERRAL: the step is a frame budget and the loader
    // is called again next frame (see the `levelload-abort-is-a-deferral`
    // finding). The previous wording called any `state == 1` failure
    // "ABORT PREDICATE ... this contradicts the inert-abort finding, record
    // it", which is an inference this detour cannot make — it sees a bool, not
    // which branch produced it. It fired once per placed mod tile on every run
    // for six playtests and was recorded as a contradiction each time, while
    // the resource stayed unnamed and nothing could be concluded either way.
    //
    // So: report the observable (state, flags, and now the RESOURCE) and let
    // the resource identity carry the finding. A step that keeps deferring on
    // one named resource while the rest of the level finishes is the shape
    // worth chasing, and that is legible from the name.
    const char* why = !have_state ? "slot/object unreadable"
                    : state != 1  ? "resource state != 1"
                                  : "incomplete with state 1 (deferral, or the abort "
                                    "predicate — this detour cannot tell them apart)";

    char st[16], fl[16];
    if (have_state) std::snprintf(st, sizeof(st), "%u", state);
    else            std::snprintf(st, sizeof(st), "<unread>");
    if (have_flags) std::snprintf(fl, sizeof(fl), "%#x", flags);
    else            std::snprintf(fl, sizeof(fl), "<unread>");

    char line[512];
    std::snprintf(line, sizeof(line),
                  "[lvl-trace] level load step INCOMPLETE #%ld: %s | obj=%p state=%s "
                  "flags=%s step=%ld  \"%s\"",
                  n, why, obj, st, fl, g_steps.load(), name);
    // Severity is earned. An unreadable slot is a genuine fault; a step that
    // has not finished is the ordinary case this trace was armed to sample, and
    // tagging it [err] is what buried `rsmm log --errors` under six lines a run.
    if (have_state) Loader::get().log(line);
    else            Loader::get().log_err(line);
    if (n == kMaxFailLines) {
        Loader::get().log("[lvl-trace] log capped. Incomplete steps are usually "
                          "deferrals; what is worth reading is which RESOURCE "
                          "keeps appearing, not the count");
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
                      "INCOMPLETE level-load steps and the resource each one was "
                      "on. A step that has not finished is normally a deferral, so "
                      "read the resource names, not the count");
    return hook_install("lvl-trace", "level load step",
                        Sym::LevelStream_LoadStep_Pattern,
                        reinterpret_cast<void*>(&detour_step),
                        reinterpret_cast<void**>(&g_real_step));
}

}  // namespace rsmm
