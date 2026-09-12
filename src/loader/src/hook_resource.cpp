// Resource-resolve trace — see hook_resource.h for the why.
//
// Detours ResourceRef_Resolve, whose ref block is documented (0x38 bytes):
//   +0x00 char* name    +0x08 u32 hash      +0x10 char* parentPath
//   +0x18 u32 hash2     +0x20 classDesc     +0x28 u8 flag
//   +0x30 void* resolvedPtr
// and whose param_3 is `&refBlock->resolvedPtr` — confirmed independently at
// the one call site we care about: LevelObject_LoadOrCreate passes
// refBlock = level+0xd0 and out = level+0x100, and 0xd0 + 0x30 == 0x100.
//
// ⚠ The function is DUAL-PURPOSE, which the log has to reflect or the numbers
// lie. With the flag at +0x28 clear it RESOLVES (loads the target and writes
// resolvedPtr). With it set it RELEASES: decrements the refcount at obj+0x08,
// runs the deleter when it hits zero, and nulls the slot. A release therefore
// legitimately leaves *out == 0, and counting that as "resolve produced null"
// would invent a fault that is not there.

#include <windows.h>

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "MinHook.h"
#include "loader.h"
#include "mem_safe.h"
#include "hook_util.h"
#include "symbols.gen.h"  // GENERATED — Sym::
#include "hook_resource.h"

namespace rsmm {
namespace {

constexpr std::size_t kRefNameOff     = 0x00;  // char* name
constexpr std::size_t kRefPathOff     = 0x10;  // char* path (the real identity)
constexpr std::size_t kRefFlagOff     = 0x28;  // u8: 0 = resolve, non-0 = release
constexpr std::size_t kObjStateOff    = 0x38;  // the dword LevelStream_LoadStep demands == 1
constexpr std::size_t kObjRefCountOff = 0x08;  // refcount the release path decrements

// How much to say. Resolves are frequent (a chapter load is thousands), so the
// budget is spent on the two things worth seeing: what NORMAL looks like, and
// every ANOMALY.
constexpr int  kSampleLines   = 12;   // first few resolves, to show the shape
constexpr long kSummaryEvery  = 2000; // window size for the histogram
// Lines per WINDOW, not per session. The first version spent a flat 64-line
// budget first-come and burned every one of them inside the first SECOND of
// boot, on shader resolves — so the run that mattered (the chapter-2
// transition, 100 seconds later) produced nothing at all. That is precisely
// the failure diagnosed in the HP-field scan and then repeated here: any
// budget that is not tied to the phase you want to measure gets spent by
// whatever happens to run first. A per-window allowance keeps coverage across
// the whole session, including every chapter load.
constexpr int  kLinesPerWindow = 4;

using ResolveFn = void (*)(void*, void*, void**, void*);
ResolveFn g_real_resolve = nullptr;

std::atomic<long> g_resolves{0};      // flag clear: actual resolves
std::atomic<long> g_releases{0};      // flag set: release path
std::atomic<long> g_state_ok{0};      // state == 1
std::atomic<long> g_state_other{0};   // state != 1
std::atomic<long> g_null_out{0};      // resolve produced no object
// Filter hits. An ABSENCE of MATCH lines is the answer this trace is
// usually asked for ("did my entity resolve at all?"), and an absence is
// exactly what a broken read looks like too. Counting makes the summary
// say "filter: 0 hit(s)" instead of saying nothing.
std::atomic<long> g_matches{0};
std::atomic<int>  g_sampled{0};
std::atomic<int>  g_window_lines{0};  // reset every window
std::atomic<long> g_next_summary{kSummaryEvery};

// Distinct state values seen, with counts. ⚠ MEASURED 2026-08-31: state != 1
// is ROUTINE — 7113 of 90000 resolves (~8%) across a session whose chapter 1
// was perfectly healthy. So "state != 1" is NOT a fault and must not be logged
// as a warning; what is worth seeing is WHICH values occur and whether a new
// one shows up at a transition that fails.
constexpr int kStateSlots = 8;
std::atomic<std::uint32_t> g_state_val[kStateSlots];
std::atomic<long>          g_state_cnt[kStateSlots];
std::atomic<long>          g_state_overflow{0};

void note_state(std::uint32_t v) {
    for (int i = 0; i < kStateSlots; ++i) {
        auto cur = g_state_val[i].load();
        if (cur == v && g_state_cnt[i].load() > 0) { g_state_cnt[i].fetch_add(1); return; }
        if (g_state_cnt[i].load() == 0) {
            std::uint32_t expect = 0;
            // Claim the slot; if someone beat us to it, fall through and retry.
            if (g_state_val[i].compare_exchange_strong(expect, v) || g_state_val[i].load() == v) {
                g_state_cnt[i].fetch_add(1);
                return;
            }
        }
    }
    g_state_overflow.fetch_add(1);
}

// The ref block's name, or a placeholder. Never trusts the pointer: a stale or
// half-built block is exactly what this trace exists to catch, so an unreadable
// name must degrade to a log line, not a fault (MinGW has no __try/__except).
void ref_name(void* ref, char* out, std::size_t cap) {
    out[0] = '\0';
    auto addr = reinterpret_cast<std::uintptr_t>(ref);
    if (!ref || !mem_readable(reinterpret_cast<const void*>(addr + kRefNameOff),
                              sizeof(void*))) {
        std::snprintf(out, cap, "<unreadable ref>");
        return;
    }
    auto name = *reinterpret_cast<char**>(addr + kRefNameOff);
    if (!name || mem_read_cstr(reinterpret_cast<std::uintptr_t>(name), out, cap) == 0
            || out[0] == '\0') {
        std::snprintf(out, cap, "<no name>");
    }
}

// The ref block's PATH (+0x10), which is the field that actually identifies the
// resource. `ref_name` reads +0x00, and that is the resource ROOT — a name
// filter built on THAT matches nothing, because it only ever says "shaders" /
// "Ot" / "EntitySettings". Both fields are {char* ptr, u32 len, u32 cap}; the
// level-load trace's refblock dump showed the 39-char level path at +0x10
// beside the 2-char "Ot" at +0x00.
//
// ✅ CONFIRMED WORKING 2026-09-11. This function carried a warning that it had
// "never once been seen working", which mattered because the MATCH filter is
// built on it: while the path read was in doubt, "my entity resolved ZERO
// times" and "the path read is broken" were indistinguishable, and a session
// was spent acting on the first reading. The session-e636 log settles it —
// sampled lines print `shaders|Static3DVertexShader.osl`,
// `shaders|FX\Dt_FX_TexMul.px.ot` and similar, i.e. a real filename after the
// pipe, not a repeat of the root. A zero-hit filter is now a TRUSTWORTHY
// answer about the resource, not a possible bug in this reader.
void ref_path(void* ref, char* out, std::size_t cap) {
    out[0] = '\0';
    auto addr = reinterpret_cast<std::uintptr_t>(ref);
    if (!ref || !mem_readable(reinterpret_cast<const void*>(addr + kRefPathOff),
                              sizeof(void*))) {
        std::snprintf(out, cap, "<unreadable ref>");
        return;
    }
    auto path = *reinterpret_cast<char**>(addr + kRefPathOff);
    if (!path || mem_read_cstr(reinterpret_cast<std::uintptr_t>(path), out, cap) == 0
            || out[0] == '\0') {
        std::snprintf(out, cap, "<no path>");
    }
}

// "<root>|<path>", the pair that identifies a resource — the same rendering
// the level-load trace settled on. Printing BOTH is what makes each sample line
// its own proof that the path read is live: see ref_path, where the ambiguity
// this rendering exists to remove is described, and its resolution.
void ref_ident(void* ref, char* out, std::size_t cap) {
    char root[64], path[256];
    ref_name(ref, root, sizeof(root));
    ref_path(ref, path, sizeof(path));
    std::snprintf(out, cap, "%s|%s", root, path);
}

// Read the state dword off a resolved object. Returns false when the object or
// the field is not readable, which is itself worth reporting.
//
// Every guarded read here is a VirtualQuery, which is a syscall and is NOT
// cached — and this runs on the game's main thread on a hot path. That matters
// more than usual: the thing being investigated is load TIMING, so a trace that
// slows loads down is a trace that moves its own measurement. Hence exactly one
// query per resolve on the common path; the refcount is read lazily, only when
// a line is actually about to be logged.
bool obj_state(void* obj, std::uint32_t* state) {
    auto addr = reinterpret_cast<std::uintptr_t>(obj);
    if (!obj || (addr & 7)) return false;
    return mem_load(addr + kObjStateOff, state);
}

// Refcount, for log lines only. Never on the counting path.
std::uint32_t obj_refcount(void* obj) {
    auto addr = reinterpret_cast<std::uintptr_t>(obj);
    if (!obj || (addr & 7)) return 0;
    std::uint32_t rc = 0;
    return mem_load(addr + kObjRefCountOff, &rc) ? rc : 0;
}

const char* rsc_trace_match();

void log_summary(const char* why) {
    char hist[192];
    int n = 0;
    hist[0] = '\0';
    for (int i = 0; i < kStateSlots && n < (int)sizeof(hist) - 24; ++i) {
        const long c = g_state_cnt[i].load();
        if (c == 0) continue;
        n += std::snprintf(hist + n, sizeof(hist) - n, " %u:%ld",
                           g_state_val[i].load(), c);
    }
    if (g_state_overflow.load()) {
        std::snprintf(hist + n, sizeof(hist) - n, " (+%ld other)",
                      g_state_overflow.load());
    }
    char line[384];
    std::snprintf(line, sizeof(line),
                  "[rsc-trace] %s: %ld resolve(s) / %ld release(s); "
                  "state==1: %ld, state!=1: %ld, no object: %ld; states:%s",
                  why, g_resolves.load(), g_releases.load(),
                  g_state_ok.load(), g_state_other.load(), g_null_out.load(),
                  hist[0] ? hist : " none");
    Loader::get().log(line);
    // A filter's HIT COUNT, said out loud. "No MATCH lines" and "the filter
    // never ran" look identical in a log, and one of them is a finding.
    if (const char* want = rsc_trace_match(); want != nullptr && want[0] != '\0') {
        std::snprintf(line, sizeof(line), "[rsc-trace] filter \"%s\": %ld hit(s)",
                      want, g_matches.load());
        Loader::get().log(line);
    }
}

// The trace filter, from the environment or from a file beside winhttp.dll.
//
// The file exists because the env var only reaches the game through Steam's
// launch options, and Steam rewrites localconfig.vdf from memory while it is
// running — so every change to what is traced meant quitting Steam entirely,
// and one botched edit (an unquoted space in a name) stopped the game booting
// at all. `<game>/rsmm_rsc_match.txt` is one line of comma-separated
// substrings and can be rewritten between runs with the launcher untouched.
const char* rsc_trace_match() {
    // ⚠ Read once, via a function-local static, NOT a mutex taken per call.
    // This runs on the game's main thread for EVERY resolve — thousands per
    // chapter load — and the thing being investigated is load timing, so a
    // lock here would move the measurement it exists to take. C++11 statics
    // are initialised exactly once and thread-safely, which is all this needs.
    static const std::string value = [] {
        std::string v;
        if (const char* env = std::getenv("RSMM_RSC_TRACE_MATCH"); env && env[0]) {
            v = env;
        } else if (FILE* f = std::fopen(
                       (Loader::get().game_dir() / "rsmm_rsc_match.txt")
                           .string().c_str(), "rb")) {
            char buf[512];
            if (std::fgets(buf, sizeof(buf), f)) v = buf;
            std::fclose(f);
            while (!v.empty() && (v.back() == '\n' || v.back() == '\r'
                                  || v.back() == ' '))
                v.pop_back();
        }
        if (!v.empty()) {
            Loader::get().log(("[rsc-trace] name filter: " + v).c_str());
        }
        return v;
    }();
    return value.empty() ? nullptr : value.c_str();
}

void detour_resolve(void* ref, void* class_desc, void** out, void* policy) {
    // Read the mode BEFORE the call: the release path clears the flag and the
    // slot, so reading it afterwards would classify every release as a resolve.
    bool releasing = false;
    bool mode_known = false;
    auto ref_addr = reinterpret_cast<std::uintptr_t>(ref);
    if (ref && mem_readable(reinterpret_cast<const void*>(ref_addr + kRefFlagOff), 1)) {
        releasing = *reinterpret_cast<std::uint8_t*>(ref_addr + kRefFlagOff) != 0;
        mode_known = true;
    }

    if (g_real_resolve) g_real_resolve(ref, class_desc, out, policy);

    if (mode_known && releasing) {
        g_releases.fetch_add(1);
        return;  // a release legitimately leaves *out null; nothing to read
    }
    const long n = g_resolves.fetch_add(1) + 1;

    void* obj = nullptr;
    if (out && mem_readable(out, sizeof(void*))) obj = *out;

    std::uint32_t state = 0;
    const bool have = obj_state(obj, &state);

    if (!have) {
        g_null_out.fetch_add(1);
    } else if (state == 1) {
        g_state_ok.fetch_add(1);
    } else {
        g_state_other.fetch_add(1);
        note_state(state);
    }

    // A resolve that produced a non-null object we cannot read at +0x38 is a
    // genuine oddity — unlike state != 1, which is routine (see note_state).
    if (!have && obj != nullptr && g_window_lines.fetch_add(1) < kLinesPerWindow) {
        char name[320];
        ref_ident(ref, name, sizeof(name));
        char line[512];
        std::snprintf(line, sizeof(line),
                      "[rsc-trace] resolved object %p is not readable at +0x38  \"%s\"",
                      obj, name);
        Loader::get().log_warn(line);
        return;
    }

    // An explicit NAME FILTER, which bypasses both the sample budget and the
    // per-window allowance. Sampling is right for "what does a resolve look
    // like" and useless for "did MY three entities resolve": the trace prints
    // a few lines per window out of thousands of resolves, so the one resource
    // the question is about is almost certain never to be printed. With
    // RSMM_RSC_TRACE_MATCH=Dolmen_A every resolve of that name is logged — and
    // a name that never appears at all is itself the answer.
    if (const char* want = rsc_trace_match(); want != nullptr && want[0] != '\0') {
        char name[320];
        ref_path(ref, name, sizeof(name));
        // Comma-separated, so ONE run can ask about several names at once —
        // here the three entities swapped IN and the three swapped OUT. The
        // second set is the load-bearing half: if the originals still resolve,
        // the engine is reading the vanilla level and the edit never landed.
        bool hit = false;
        const char* tok = want;
        while (*tok && !hit) {
            const char* end = std::strchr(tok, ',');
            const std::size_t len = end ? (std::size_t)(end - tok) : std::strlen(tok);
            if (len > 0 && len < 128) {
                char needle[128];
                std::memcpy(needle, tok, len);
                needle[len] = '\0';
                hit = std::strstr(name, needle) != nullptr;
            }
            tok = end ? end + 1 : tok + len;
        }
        if (hit) {
            g_matches.fetch_add(1);
            char st[24];
            if (have) std::snprintf(st, sizeof(st), "%u", state);
            else      std::snprintf(st, sizeof(st), "<unreadable>");
            char line[512];
            std::snprintf(line, sizeof(line),
                          "[rsc-trace] MATCH obj=%p state=%s refcount=%u  \"%s\"",
                          obj, st, obj_refcount(obj), name);
            Loader::get().log(line);
        }
    }

    // A few lines per WINDOW, so every phase — including the chapter load that
    // matters — gets some. Prefer a non-1 state when one turns up in this
    // window, because that is the value in question; otherwise show a normal
    // one so "quiet" stays distinguishable from "hook dead".
    const bool interesting = have && state != 1;
    if ((interesting || g_sampled.fetch_add(1) < kSampleLines)
            && g_window_lines.fetch_add(1) < kLinesPerWindow) {
        char name[320];
        ref_ident(ref, name, sizeof(name));
        char st[24];
        if (have) std::snprintf(st, sizeof(st), "%u", state);
        else      std::snprintf(st, sizeof(st), "<unreadable>");
        char line[512];
        std::snprintf(line, sizeof(line),
                      "[rsc-trace] #%ld obj=%p state=%s refcount=%u  \"%s\"",
                      n, obj, st, obj_refcount(obj), name);
        Loader::get().log(line);
    }

    if (n >= g_next_summary.load()) {
        g_next_summary.fetch_add(kSummaryEvery);
        g_window_lines.store(0);   // refresh the per-window line allowance
        log_summary("progress");
    }
}


// --- resource-cache submit trace -------------------------------------------
//
// WHY A SECOND HOOK. The ResourceRef_Resolve trace answers "did this resource
// RESOLVE, and to what". It cannot answer "was my entity ever ASKED FOR",
// and on 2026-09-11 that difference mattered: a mod's geometry and textures
// resolved with live objects while its mod-added ENTITY produced zero hits
// from a filter that included it. Never-resolved and never-requested are
// different failures, and the recorded conclusion ("a mod-added entity
// resolves to null") cannot be trusted until they are told apart.
//
// A definition's dependency closure arrives through its .UsedRscCache.ot, not
// through ResourceRef_Resolve: Definition_PreloadResourceCache parses the
// cache into 0x38-stride entries and hands the vector here. So this is the
// point where a cache LINE becomes a load REQUEST, and it is the only place
// the question can be asked.
//
// Argument 2 is {u32 count; u32 _pad; void* data} — the shape the caller
// builds on its stack before the call.
constexpr std::size_t kSubmitCountOff = 0x00;
constexpr std::size_t kSubmitDataOff  = 0x08;
constexpr std::size_t kSubmitStride   = 0x38;   // == a resource ref block
constexpr std::uint32_t kSubmitMaxEntries = 4096;

using Submit_t = void (*)(void*, void*);
Submit_t g_submit_real = nullptr;

// Does `path` contain any comma-separated token of the active filter?
bool match_filter(const char* path) {
    const char* want = rsc_trace_match();
    if (!want || !want[0] || !path || !path[0]) return false;
    const char* tok = want;
    while (*tok) {
        const char* end = std::strchr(tok, ',');
        const std::size_t len = end ? (std::size_t)(end - tok) : std::strlen(tok);
        if (len > 0 && len < 128) {
            char needle[128];
            std::memcpy(needle, tok, len);
            needle[len] = '\0';
            if (std::strstr(path, needle) != nullptr) return true;
        }
        tok = end ? end + 1 : tok + len;
    }
    return false;
}

void WINAPI cache_submit_detour(void* sink, void* vec) {
    // Read BEFORE forwarding: the callee owns the vector afterwards and frees
    // it, so anything read on the way out is a read of freed memory.
    if (vec && rsc_trace_match() && rsc_trace_match()[0]) {
        std::uint32_t count = 0;
        std::uintptr_t data = 0;
        const auto v = reinterpret_cast<std::uintptr_t>(vec);
        if (mem_load(v + kSubmitCountOff, &count) && mem_load(v + kSubmitDataOff, &data)
                && count > 0 && count <= kSubmitMaxEntries && data != 0
                && mem_accessible(data, (std::size_t)count * kSubmitStride, false)) {
            for (std::uint32_t i = 0; i < count; ++i) {
                char path[256];
                ref_path(reinterpret_cast<void*>(data + (std::uintptr_t)i * kSubmitStride),
                         path, sizeof(path));
                if (!match_filter(path)) continue;
                char line[400];
                std::snprintf(line, sizeof(line),
                              "[rsc-trace] CACHE-SUBMIT entry %u/%u  \"%s\"",
                              i + 1, count, path);
                Loader::get().log(line);
            }
        }
    }
    g_submit_real(sink, vec);
}

}  // anonymous namespace

long resolve_count() { return g_resolves.load(); }

const char* resource_trace_filter() {
    const char* v = rsc_trace_match();
    return v ? v : "";
}

bool install_resource_hooks() {
    if (!flag_enabled("RSMM_ENABLE_RESOURCE_TRACE")) {
        // Not armed is not a fault — plain log(), per the severity rule.
        Loader::get().log("[rsc-trace] disabled (set RSMM_ENABLE_RESOURCE_TRACE=1 "
                          "to trace resource resolves + their +0x38 state)");
        return false;
    }
    Loader::get().log("[rsc-trace] arming ResourceRef_Resolve trace — READ-ONLY; "
                      "logs the first few resolves, then only state != 1");
    const bool resolve_ok = hook_install("rsc-trace", "resource ref resolve",
                        Sym::ResourceRef_Resolve_Pattern,
                        reinterpret_cast<void*>(&detour_resolve),
                        reinterpret_cast<void**>(&g_real_resolve));

    // The cache-submit trace is a SEPARATE question and fails independently:
    // a build where only one of the two resolves still answers half of it.
    const bool submit_ok = hook_install("rsc-trace", "resource cache submit",
                                        Sym::ResourceCache_Submit_Pattern,
                                        reinterpret_cast<void*>(&cache_submit_detour),
                                        reinterpret_cast<void**>(&g_submit_real));
    if (submit_ok) {
        Loader::get().log("[rsc-trace] cache-submit trace armed — logs every "
                          "resource-cache entry whose path matches the filter, "
                          "which is what tells 'never requested' from "
                          "'resolved to null'");
    }
    return resolve_ok || submit_ok;
}

}  // namespace rsmm
