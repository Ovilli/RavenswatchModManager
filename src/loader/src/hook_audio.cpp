// Selective + master audio mute through FMOD's exports — see hook_audio.h.

#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstdint>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "MinHook.h"
#include "loader.h"
#include "hook_util.h"
#include "hook_audio.h"

namespace rsmm {
namespace {

// FMOD's C++ API is a set of thin handle classes: every method is
// `FMOD_RESULT method(this, ...)`, so on x64 they are called exactly like free
// functions taking the handle first. FMOD_RESULT is an int enum, 0 = FMOD_OK.
constexpr int kFmodOk = 0;
constexpr int kFmodErrInvalidHandle = 30;

// ---- Core (fmod.dll) -------------------------------------------------------
using CoreUpdateFn   = int (*)(void* system);
using GetMasterCgFn  = int (*)(void* system, void** out_group);
using CgSetMuteFn    = int (*)(void* control, bool mute);
using CgGetMuteFn    = int (*)(void* control, bool* out_mute);

// ---- Studio (fmodstudio.dll) -----------------------------------------------
using StudioUpdateFn = int (*)(void* system);
using GetBusFn       = int (*)(void* system, const char* path, void** out_bus);
using BusSetMuteFn   = int (*)(void* bus, bool mute);
using BusGetMuteFn   = int (*)(void* bus, bool* out_mute);
using StartFn        = int (*)(void* inst);
using SetVolumeFn    = int (*)(void* inst, float volume);
using GetDescFn      = int (*)(void* inst, void** out_desc);
using GetPathFn      = int (*)(void* desc, char* path, int size, int* retrieved);
using InstValidFn    = bool (*)(void* inst);

CoreUpdateFn   g_orig_core_update = nullptr;
GetMasterCgFn  g_get_master = nullptr;
CgSetMuteFn    g_cg_set_mute = nullptr;
CgGetMuteFn    g_cg_get_mute = nullptr;

StudioUpdateFn g_orig_studio_update = nullptr;
GetBusFn       g_get_bus = nullptr;
BusSetMuteFn   g_bus_set_mute = nullptr;
BusGetMuteFn   g_bus_get_mute = nullptr;
StartFn        g_orig_start = nullptr;
SetVolumeFn    g_orig_set_volume = nullptr;
GetDescFn      g_get_desc = nullptr;
GetPathFn      g_get_path = nullptr;
InstValidFn    g_inst_valid = nullptr;

std::atomic<bool>               g_hooked{false};
std::atomic<bool>               g_studio_hooked{false};
std::atomic<int>                g_last_error{0};

void note_err(int r) {
    if (r != kFmodOk) g_last_error.store(r, std::memory_order_relaxed);
}

std::string lower(std::string s) {
    for (auto& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    while (s.size() > 1 && s.back() == '/') s.pop_back();
    return s;
}

// =========================================================================
// Grain 1: Core master ("all")
// =========================================================================

std::atomic<bool>               g_want_mute{false};
// Bumped on every request change. Each system remembers the generation it
// last applied, which is what lets an UN-mute happen exactly once per system
// and then leave the flag to the game.
std::atomic<unsigned>           g_gen{0};
std::atomic<unsigned long long> g_updates{0};

constexpr int kMaxSystems = 8;
struct SysSlot {
    std::atomic<void*> sys{nullptr};
    unsigned           applied_gen = ~0u;  // touched only on that system's update thread
};
SysSlot g_sys[kMaxSystems];
std::atomic<int> g_sys_n{0};
std::mutex g_sys_add;

SysSlot* slot_for(void* sys) {
    const int n = g_sys_n.load(std::memory_order_acquire);
    for (int i = 0; i < n; ++i)
        if (g_sys[i].sys.load(std::memory_order_relaxed) == sys) return &g_sys[i];
    std::lock_guard<std::mutex> lk(g_sys_add);
    const int m = g_sys_n.load(std::memory_order_relaxed);
    for (int i = 0; i < m; ++i)
        if (g_sys[i].sys.load(std::memory_order_relaxed) == sys) return &g_sys[i];
    if (m >= kMaxSystems) return nullptr;
    g_sys[m].sys.store(sys, std::memory_order_relaxed);
    g_sys_n.store(m + 1, std::memory_order_release);
    Loader::get().log("[audio] FMOD core system #" + std::to_string(m + 1) + " seen");
    return &g_sys[m];
}

void apply_master(void* sys) {
    const unsigned gen = g_gen.load(std::memory_order_acquire);
    if (gen == 0) return;  // never requested: stay out of the game's way
    const bool want = g_want_mute.load(std::memory_order_acquire);
    SysSlot* s = slot_for(sys);
    if (!s) return;
    if (!want && s->applied_gen == gen) return;

    void* master = nullptr;
    int r = g_get_master(sys, &master);
    if (r != kFmodOk || !master) { note_err(r); return; }
    bool cur = false;
    r = g_cg_get_mute(master, &cur);
    if (r != kFmodOk) { note_err(r); return; }
    if (cur != want) note_err(g_cg_set_mute(master, want));
    s->applied_gen = gen;
}

int detour_core_update(void* sys) {
    g_updates.fetch_add(1, std::memory_order_relaxed);
    if (sys) apply_master(sys);
    return g_orig_core_update(sys);
}

// =========================================================================
// Grains 2 + 3: Studio buses and events
// =========================================================================
//
// LOCKING RULE: g_mx is never held across an FMOD call. FMOD takes its own
// API lock, and game code reached from inside FMOD (event callbacks) calls
// start/setVolume, i.e. our detours; holding g_mx into FMOD from one thread
// while another sits in FMOD waiting for g_mx would deadlock. So every path
// below snapshots under the lock, calls FMOD unlocked, then writes back.

std::mutex g_mx;                          // guards everything below
std::vector<std::string> g_bus_targets;   // lower-cased "bus:/..."
std::vector<std::string> g_bus_release;   // un-selected: unmute once
std::vector<std::string> g_bus_mine;      // buses we currently hold muted
std::vector<std::string> g_event_targets; // lower-cased "event:/..." prefixes
unsigned g_target_gen = 0;                // bumped by audio_set_targets
unsigned g_applied_gen = 0;               // last gen the update applied
std::atomic<bool> g_tracking{false};      // a selection was ever made

struct Inst { float game_vol = 1.0f; bool muted = false; void* desc = nullptr; };
std::unordered_map<void*, Inst> g_inst;   // live (or recently live) instances
std::unordered_map<void*, bool> g_desc;   // description -> muted, this gen
unsigned long long g_studio_updates = 0;  // touched only on the update thread

// Caller holds g_mx.
bool path_selected(const std::string& path_lc) {
    for (const auto& t : g_event_targets) {
        if (path_lc.size() < t.size() || path_lc.compare(0, t.size(), t) != 0) continue;
        if (path_lc.size() == t.size() || path_lc[t.size()] == '/') return true;
    }
    return false;
}

// Must NOT be called with g_mx held.
bool desc_muted(void* desc) {
    if (!desc) return false;
    {
        std::lock_guard<std::mutex> lk(g_mx);
        if (g_event_targets.empty()) return false;
        auto it = g_desc.find(desc);
        if (it != g_desc.end()) return it->second;
    }
    char buf[512];
    int got = 0;
    const int r = g_get_path(desc, buf, static_cast<int>(sizeof(buf)), &got);
    std::string path;
    if (r == kFmodOk) { buf[sizeof(buf) - 1] = '\0'; path = lower(buf); }
    else note_err(r);
    std::lock_guard<std::mutex> lk(g_mx);
    const bool m = !path.empty() && path_selected(path);
    g_desc[desc] = m;
    return m;
}

int detour_start(void* inst) {
    if (inst && g_tracking.load(std::memory_order_acquire)) {
        void* desc = nullptr;
        if (g_get_desc(inst, &desc) != kFmodOk) desc = nullptr;
        const bool m = desc_muted(desc);
        {
            std::lock_guard<std::mutex> lk(g_mx);
            Inst& e = g_inst[inst];
            e.desc = desc;
            e.muted = m;
        }
        if (m) note_err(g_orig_set_volume(inst, 0.0f));
    }
    return g_orig_start(inst);
}

int detour_set_volume(void* inst, float v) {
    {
        std::lock_guard<std::mutex> lk(g_mx);
        auto it = g_inst.find(inst);
        if (it != g_inst.end()) {
            it->second.game_vol = v;
            if (it->second.muted) v = 0.0f;
        }
    }
    return g_orig_set_volume(inst, v);
}

void apply_buses(void* sys, bool force) {
    std::vector<std::string> release, targets;
    {
        std::lock_guard<std::mutex> lk(g_mx);
        release.swap(g_bus_release);
        if (force || (g_studio_updates % 15) == 0) targets = g_bus_targets;
    }
    for (const auto& p : release) {
        void* bus = nullptr;
        if (g_get_bus(sys, p.c_str(), &bus) == kFmodOk && bus)
            note_err(g_bus_set_mute(bus, false));
    }
    std::vector<std::string> found;
    for (const auto& p : targets) {
        void* bus = nullptr;
        if (g_get_bus(sys, p.c_str(), &bus) != kFmodOk || !bus) continue;  // bank not loaded yet
        bool cur = false;
        if (g_bus_get_mute(bus, &cur) != kFmodOk) continue;
        if (!cur) note_err(g_bus_set_mute(bus, true));
        found.push_back(p);
    }
    if (found.empty()) return;
    std::lock_guard<std::mutex> lk(g_mx);
    for (const auto& p : found) {
        // Still selected? A set_targets may have raced in while we were in FMOD.
        if (std::find(g_bus_targets.begin(), g_bus_targets.end(), p) == g_bus_targets.end()) {
            g_bus_release.push_back(p);
        } else if (std::find(g_bus_mine.begin(), g_bus_mine.end(), p) == g_bus_mine.end()) {
            g_bus_mine.push_back(p);
        }
    }
}

struct Snap { void* inst; void* desc; bool muted; float vol; };

// Re-decide every tracked instance after a selection change.
void reapply_instances() {
    std::vector<Snap> snap;
    {
        std::lock_guard<std::mutex> lk(g_mx);
        g_desc.clear();
        snap.reserve(g_inst.size());
        for (const auto& kv : g_inst)
            snap.push_back({kv.first, kv.second.desc, kv.second.muted, kv.second.game_vol});
    }
    std::vector<void*> dead;
    std::vector<std::pair<void*, bool>> now;
    for (const auto& s : snap) {
        const bool m = desc_muted(s.desc);
        if (m == s.muted) continue;
        const int r = g_orig_set_volume(s.inst, m ? 0.0f : s.vol);
        if (r == kFmodErrInvalidHandle) { dead.push_back(s.inst); continue; }
        note_err(r);
        now.emplace_back(s.inst, m);
    }
    std::lock_guard<std::mutex> lk(g_mx);
    for (void* d : dead) g_inst.erase(d);
    for (const auto& [inst, m] : now) {
        auto it = g_inst.find(inst);
        if (it != g_inst.end()) it->second.muted = m;
    }
}

// Drop instances FMOD has already destroyed.
void prune_instances() {
    std::vector<void*> keys;
    {
        std::lock_guard<std::mutex> lk(g_mx);
        keys.reserve(g_inst.size());
        for (const auto& kv : g_inst) keys.push_back(kv.first);
    }
    std::vector<void*> dead;
    for (void* k : keys) if (!g_inst_valid(k)) dead.push_back(k);
    std::lock_guard<std::mutex> lk(g_mx);
    for (void* d : dead) g_inst.erase(d);
}

int detour_studio_update(void* sys) {
    if (sys && g_tracking.load(std::memory_order_acquire)) {
        ++g_studio_updates;
        bool changed = false;
        unsigned gen = 0;
        {
            std::lock_guard<std::mutex> lk(g_mx);
            gen = g_target_gen;
            changed = g_applied_gen != gen;
            g_applied_gen = gen;
        }
        if (changed) reapply_instances();
        apply_buses(sys, changed);
        if ((g_studio_updates % 120) == 0) prune_instances();
    }
    return g_orig_studio_update(sys);
}

template <class Fn>
bool resolve(HMODULE m, const char* name, Fn* out) {
    *out = reinterpret_cast<Fn>(reinterpret_cast<void*>(GetProcAddress(m, name)));
    if (!*out)
        Loader::get().log_err(std::string("[audio] FMOD export missing: ") + name);
    return *out != nullptr;
}

template <class Fn>
bool hook(const char* what, Fn target, void* detour, Fn* orig) {
    // AnyModule: the target lives in an FMOD DLL, whose own exception table is
    // the one that can vouch for it being a function entry.
    return hook_install_at("audio", what,
                           reinterpret_cast<std::uintptr_t>(reinterpret_cast<void*>(target)),
                           detour, reinterpret_cast<void**>(orig), EntryCheck::AnyModule);
}

bool install_core() {
    HMODULE m = GetModuleHandleA("fmod.dll");
    if (!m) { Loader::get().log_warn("[audio] fmod.dll is not loaded"); return false; }
    CoreUpdateFn update = nullptr;
    if (!resolve(m, "?update@System@FMOD@@QEAA?AW4FMOD_RESULT@@XZ", &update)
        || !resolve(m, "?getMasterChannelGroup@System@FMOD@@QEAA?AW4FMOD_RESULT@@PEAPEAVChannelGroup@2@@Z", &g_get_master)
        || !resolve(m, "?setMute@ChannelControl@FMOD@@QEAA?AW4FMOD_RESULT@@_N@Z", &g_cg_set_mute)
        || !resolve(m, "?getMute@ChannelControl@FMOD@@QEAA?AW4FMOD_RESULT@@PEA_N@Z", &g_cg_get_mute))
        return false;
    if (!hook("FMOD System::update", update,
              reinterpret_cast<void*>(&detour_core_update), &g_orig_core_update))
        return false;
    g_hooked.store(true, std::memory_order_release);
    return true;
}

bool install_studio() {
    HMODULE m = GetModuleHandleA("fmodstudio.dll");
    if (!m) { Loader::get().log_warn("[audio] fmodstudio.dll is not loaded"); return false; }
    StudioUpdateFn update = nullptr;
    StartFn start = nullptr;
    SetVolumeFn set_volume = nullptr;
    if (!resolve(m, "?update@System@Studio@FMOD@@QEAA?AW4FMOD_RESULT@@XZ", &update)
        || !resolve(m, "?getBus@System@Studio@FMOD@@QEBA?AW4FMOD_RESULT@@PEBDPEAPEAVBus@23@@Z", &g_get_bus)
        || !resolve(m, "?setMute@Bus@Studio@FMOD@@QEAA?AW4FMOD_RESULT@@_N@Z", &g_bus_set_mute)
        || !resolve(m, "?getMute@Bus@Studio@FMOD@@QEBA?AW4FMOD_RESULT@@PEA_N@Z", &g_bus_get_mute)
        || !resolve(m, "?start@EventInstance@Studio@FMOD@@QEAA?AW4FMOD_RESULT@@XZ", &start)
        || !resolve(m, "?setVolume@EventInstance@Studio@FMOD@@QEAA?AW4FMOD_RESULT@@M@Z", &set_volume)
        || !resolve(m, "?getDescription@EventInstance@Studio@FMOD@@QEBA?AW4FMOD_RESULT@@PEAPEAVEventDescription@23@@Z", &g_get_desc)
        || !resolve(m, "?getPath@EventDescription@Studio@FMOD@@QEBA?AW4FMOD_RESULT@@PEADHPEAH@Z", &g_get_path)
        || !resolve(m, "?isValid@EventInstance@Studio@FMOD@@QEBA_NXZ", &g_inst_valid))
        return false;
    // setVolume before start: start's mute calls the ORIGINAL setVolume through
    // the trampoline, which must exist first.
    if (!hook("FMOD Studio EventInstance::setVolume", set_volume,
              reinterpret_cast<void*>(&detour_set_volume), &g_orig_set_volume))
        return false;
    if (!hook("FMOD Studio EventInstance::start", start,
              reinterpret_cast<void*>(&detour_start), &g_orig_start))
        return false;
    if (!hook("FMOD Studio System::update", update,
              reinterpret_cast<void*>(&detour_studio_update), &g_orig_studio_update))
        return false;
    g_studio_hooked.store(true, std::memory_order_release);
    return true;
}

} // namespace

bool install_audio_hooks() {
    const bool core = install_core();
    const bool studio = install_studio();
    if (!core && !studio) Loader::get().log_err("[audio] no FMOD hook armed; R.audio is unavailable");
    return core || studio;
}

void audio_set_mute(bool on) {
    const bool prev = g_want_mute.exchange(on, std::memory_order_acq_rel);
    if (prev != on) {
        g_gen.fetch_add(1, std::memory_order_acq_rel);
        Loader::get().log(std::string("[audio] master mute ") + (on ? "on" : "off"));
    }
}

void audio_set_targets(const std::vector<std::string>& paths) {
    std::vector<std::string> buses, events;
    for (const auto& raw : paths) {
        std::string p = lower(raw);
        if (p.rfind("bus:/", 0) == 0) buses.push_back(p);
        else if (p.rfind("event:/", 0) == 0) events.push_back(p);
    }
    std::lock_guard<std::mutex> lk(g_mx);
    for (const auto& p : g_bus_mine)
        if (std::find(buses.begin(), buses.end(), p) == buses.end())
            g_bus_release.push_back(p);
    g_bus_mine.erase(std::remove_if(g_bus_mine.begin(), g_bus_mine.end(), [&](const std::string& p) {
        return std::find(buses.begin(), buses.end(), p) == buses.end();
    }), g_bus_mine.end());
    g_bus_targets = std::move(buses);
    g_event_targets = std::move(events);
    ++g_target_gen;
    g_tracking.store(true, std::memory_order_release);
    Loader::get().log("[audio] muting " + std::to_string(g_bus_targets.size()) + " bus(es), "
                      + std::to_string(g_event_targets.size()) + " event group(s)");
}

AudioStatus audio_status() {
    AudioStatus st{};
    st.hooked = g_hooked.load(std::memory_order_acquire);
    st.studio_hooked = g_studio_hooked.load(std::memory_order_acquire);
    st.muted = g_want_mute.load(std::memory_order_acquire);
    st.systems = g_sys_n.load(std::memory_order_acquire);
    st.updates = g_updates.load(std::memory_order_relaxed);
    st.last_error = g_last_error.load(std::memory_order_relaxed);
    std::lock_guard<std::mutex> lk(g_mx);
    st.buses = static_cast<int>(g_bus_targets.size());
    st.buses_muted = static_cast<int>(g_bus_mine.size());
    st.events = static_cast<int>(g_event_targets.size());
    st.instances = static_cast<int>(g_inst.size());
    for (const auto& kv : g_inst) st.instances_muted += kv.second.muted ? 1 : 0;
    return st;
}

} // namespace rsmm
