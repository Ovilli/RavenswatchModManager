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
#include <cstring>

#include "MinHook.h"
#include "loader.h"
#include "mem_safe.h"
#include "hook_util.h"
#include "symbols.gen.h"  // GENERATED — Sym::
#include "hook_resource.h"

namespace rsmm {
namespace {

constexpr std::size_t kRefNameOff     = 0x00;  // char* name
constexpr std::size_t kRefFlagOff     = 0x28;  // u8: 0 = resolve, non-0 = release
constexpr std::size_t kObjStateOff    = 0x38;  // the dword LevelStream_LoadStep demands == 1
constexpr std::size_t kObjRefCountOff = 0x08;  // refcount the release path decrements

// How much to say. Resolves are frequent (a chapter load is thousands), so the
// budget is spent on the two things worth seeing: what NORMAL looks like, and
// every ANOMALY.
constexpr int kSampleLines   = 12;   // first few resolves, to show the shape
constexpr int kAnomalyLines  = 64;   // every state != 1, capped
constexpr long kSummaryEvery = 2000; // periodic histogram

using ResolveFn = void (*)(void*, void*, void**, void*);
ResolveFn g_real_resolve = nullptr;

std::atomic<long> g_resolves{0};      // flag clear: actual resolves
std::atomic<long> g_releases{0};      // flag set: release path
std::atomic<long> g_state_ok{0};      // state == 1
std::atomic<long> g_state_other{0};   // state != 1
std::atomic<long> g_null_out{0};      // resolve produced no object
std::atomic<int>  g_sampled{0};
std::atomic<int>  g_anomalies{0};
std::atomic<long> g_next_summary{kSummaryEvery};

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

void log_summary(const char* why) {
    char line[256];
    std::snprintf(line, sizeof(line),
                  "[rsc-trace] %s: %ld resolve(s) / %ld release(s); "
                  "state==1: %ld, state!=1: %ld, no object: %ld",
                  why, g_resolves.load(), g_releases.load(),
                  g_state_ok.load(), g_state_other.load(), g_null_out.load());
    Loader::get().log(line);
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
    }

    // ANOMALY: the exact condition LevelStream_LoadStep refuses on. This is the
    // line the whole trace exists to produce.
    if (have && state != 1 && g_anomalies.fetch_add(1) < kAnomalyLines) {
        char name[256];
        ref_name(ref, name, sizeof(name));
        char line[512];
        std::snprintf(line, sizeof(line),
                      "[rsc-trace] STATE!=1 obj=%p state=%u refcount=%u  \"%s\"  "
                      "(this is what LevelStream_LoadStep refuses on)",
                      obj, state, obj_refcount(obj), name);
        Loader::get().log_warn(line);
        return;
    }

    // A resolve that produced nothing readable is its own anomaly.
    if (!have && obj != nullptr && g_anomalies.fetch_add(1) < kAnomalyLines) {
        char name[256];
        ref_name(ref, name, sizeof(name));
        char line[512];
        std::snprintf(line, sizeof(line),
                      "[rsc-trace] resolved object %p is not readable at +0x38  \"%s\"",
                      obj, name);
        Loader::get().log_warn(line);
        return;
    }

    // Sample the first few so the log shows what NORMAL looks like — without
    // it, "no anomalies" is indistinguishable from "the hook never fired".
    if (g_sampled.fetch_add(1) < kSampleLines) {
        char name[256];
        ref_name(ref, name, sizeof(name));
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
        log_summary("progress");
    }
}

}  // anonymous namespace

bool install_resource_hooks() {
    if (!flag_enabled("RSMM_ENABLE_RESOURCE_TRACE")) {
        // Not armed is not a fault — plain log(), per the severity rule.
        Loader::get().log("[rsc-trace] disabled (set RSMM_ENABLE_RESOURCE_TRACE=1 "
                          "to trace resource resolves + their +0x38 state)");
        return false;
    }
    Loader::get().log("[rsc-trace] arming ResourceRef_Resolve trace — READ-ONLY; "
                      "logs the first few resolves, then only state != 1");
    return hook_install("rsc-trace", "resource ref resolve",
                        Sym::ResourceRef_Resolve_Pattern,
                        reinterpret_cast<void*>(&detour_resolve),
                        reinterpret_cast<void**>(&g_real_resolve));
}

}  // namespace rsmm
