// Native, blended camera zoom — see hook_camera.h for the why.

#include <windows.h>

#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>

#include "hook_camera.h"
#include "hook_util.h"
#include "loader.h"
#include "mem_safe.h"
#include "symbols.gen.h"   // GENERATED — Sym::

namespace rsmm {
namespace {

// oCZoomCameraModifier, field for field (CameraModifier_Evaluate /
// CameraModifier_AddChild / the zoom ctor FUN_140667370 in data/symbols.json).
// The game reads and writes the first 0x30 bytes of this through the root's
// child array, so the layout is not ours to change.
struct ZoomMod {
    std::uintptr_t vft;        // +0x00
    std::uint8_t   dir;        // +0x08  1 fading in / held, 0 fading out
    std::uint8_t   in_list;    // +0x09  set by AddChild, cleared when the evaluator unlinks
    std::uint8_t   pad0[2];
    float          elapsed;    // +0x0c
    float          duration;   // +0x10
    float          weight;     // +0x14
    std::uint32_t  curve;      // +0x18  4 = cosine ease in-out
    std::uint32_t  pad1;
    void*          children;   // +0x20  always null: ours have no children
    std::uint32_t  count;      // +0x28
    std::uint32_t  capacity;   // +0x2c
    float          factor;     // +0x30  eye distance multiplier
    std::uint32_t  pad2;
};
static_assert(sizeof(ZoomMod) == 0x38, "oCZoomCameraModifier is 0x38 bytes");
static_assert(offsetof(ZoomMod, elapsed) == 0x0c, "elapsed");
static_assert(offsetof(ZoomMod, weight) == 0x14, "weight");
static_assert(offsetof(ZoomMod, curve) == 0x18, "curve");
static_assert(offsetof(ZoomMod, children) == 0x20, "children");
static_assert(offsetof(ZoomMod, factor) == 0x30, "factor");

constexpr std::uintptr_t kRootInContext = 0x78;  // root modifier embedded in CameraSceneContext
constexpr std::uintptr_t kChildArray = 0x20;
constexpr std::uintptr_t kChildCount = 0x28;
constexpr std::uint32_t kMaxChildren = 4096;     // sanity bound on a live array
constexpr std::uint32_t kCurveCosine = 4;
constexpr float kInstant = 1e-6f;
constexpr float kMinStep = 0.05f, kMaxStep = 20.0f;
constexpr int kSteps = 32;
constexpr int kQueue = 32;
// A different root seen while the adopted one was evaluated within this many
// root evaluations is a second live camera tree; we leave it alone.
constexpr std::uint64_t kRootStale = 30;

struct Req { float step; float seconds; };

using Eval_fn = void (*)(void* mod, const float* dt, void* state, float parent_weight);
using Add_fn = void (*)(void* mod, void* parent, bool instant);
using Remove_fn = void (*)(void* parent, void* mod);
using Activate_fn = void (*)(void* top_down_camera);

Eval_fn g_real_eval = nullptr;
Add_fn g_add = nullptr;
Remove_fn g_remove = nullptr;
Activate_fn g_real_activate = nullptr;
std::uintptr_t g_eval_va = 0;
std::uintptr_t g_vft_base = 0;     // oCCameraModifier
std::uintptr_t g_vft_zoom = 0;     // oCZoomCameraModifier
std::uintptr_t g_vft_ctx = 0;      // CameraSceneContext
std::atomic<bool> g_armed{false};

// --- the top-down cameras' own modifiers -------------------------------------
//
// TopDownCamera_Activate stores the camera's position and near/far modifiers at
// component +0x188 / +0x190 and adds both to the camera root. The zoom keys on
// those two pointers: it is applied only while one of them is in the tree being
// evaluated (a top-down camera is driving the view: not a menu, the hub book or
// an end screen), and ours must come after them, because the position modifier
// at weight 1 overwrites the eye we scale. Anything else added after ours (a
// cinematic's modifiers, a scene camera's: see below) stays after ours, so
// cutscenes are not zoomed.
//
// Only compared as addresses, never dereferenced, so a stale entry after the
// camera is torn down costs nothing: it simply never matches again.
//
// The table is least-recently-SEEN, not a FIFO of activations. A camera that
// stays active for a whole run (Kintaro's mounted camera) activates once, while
// another (his on-foot camera, rebuilt on every dismount; ultimates) activates
// again and again with fresh modifiers. A FIFO evicted the long-lived camera's
// pointers after eight such activations, and from then on the zoom switched off
// whenever that camera was the one driving the view. Every entry found in the
// adopted tree is restamped on each evaluation, so the camera on screen is
// never the one evicted; torn-down cameras' entries age out.
constexpr std::uintptr_t kCamPositionMod = 0x188;
constexpr std::uintptr_t kCamNearFarMod = 0x190;
constexpr int kCamRing = 32;
struct CamEntry { std::uintptr_t mod; std::uint64_t seen; bool scene; };
std::mutex g_cam_mu;
CamEntry g_cam[kCamRing]{};
std::uint64_t g_cam_clock = 0;      // under g_cam_mu
std::atomic<std::uint32_t> g_cam_activations{0};

// --- scene cameras ------------------------------------------------------------
//
// Boss intros and death scenes are top-down cameras too, owned by the level
// rather than the hero ("Boss Zooming Camera", the "... Dying Camera"s; see
// evidence/camera-handoff-2026-11-07/camera-catalogue.md). Their modifiers are
// remembered like any camera's, but they never count as the camera the zoom
// sits behind: ours stay between the player's camera and the scene camera, so
// the scene blends in from the zoomed view, fully overrides it at weight 1,
// and blends back out into the zoom. The component's settings sit at +0x10 and
// carry their name at +0xe8.
constexpr std::uintptr_t kCamSettings = 0x10;
constexpr std::uintptr_t kSettingsName = 0xe8;
constexpr const char* kSceneCameras[] = {
    "Boss Zooming Camera",
    "Boss Dying Camera",
    "Ogre Dying Camera",
};

bool is_scene_camera(const char* name) {
    for (const char* s : kSceneCameras)
        if (std::strcmp(name, s) == 0) return true;
    return false;
}

void remember_camera_mod(std::uintptr_t m, bool scene) {
    if (m == 0) return;
    std::lock_guard<std::mutex> g(g_cam_mu);
    int victim = 0;
    for (int i = 0; i < kCamRing; ++i) {
        if (g_cam[i].mod == m) { g_cam[i].seen = ++g_cam_clock; g_cam[i].scene = scene; return; }
        if (g_cam[i].seen < g_cam[victim].seen) victim = i;   // empty slots have seen 0
    }
    g_cam[victim] = {m, ++g_cam_clock, scene};
}

// Each camera name is logged the first time it activates, so a scene camera
// missing from the list above shows up in the log by name.
constexpr int kNamesSeen = 64;
char g_names_seen[kNamesSeen][48]{};
int g_names_seen_n = 0;              // activate runs on one thread

void log_first_activation(const char* name, bool scene) {
    for (int i = 0; i < g_names_seen_n; ++i)
        if (std::strcmp(g_names_seen[i], name) == 0) return;
    if (g_names_seen_n < kNamesSeen) {
        std::snprintf(g_names_seen[g_names_seen_n], sizeof(g_names_seen[0]), "%s", name);
        ++g_names_seen_n;
    }
    char line[160];
    std::snprintf(line, sizeof(line), "[camera] camera '%s' activated%s", name,
                  scene ? ": a scene camera, the zoom stays under it" : "");
    Loader::get().log(line);
}

// Restamp the entries present in the adopted tree (evaluator thread).
void touch_camera_mods(const std::uintptr_t* present, int n) {
    if (n == 0) return;
    std::lock_guard<std::mutex> g(g_cam_mu);
    const std::uint64_t now = ++g_cam_clock;
    for (int i = 0; i < kCamRing; ++i)
        for (int j = 0; j < n; ++j)
            if (g_cam[i].mod == present[j]) g_cam[i].seen = now;
}

// Whether the zoom was applied last evaluation, for the pause/resume log.
bool g_zoom_on = false;

// --- evaluator-thread state (touched only inside a root's evaluation) ---
alignas(16) ZoomMod g_base{};
alignas(16) ZoomMod g_step[kSteps]{};
bool g_step_live[kSteps]{};        // fading in, ours to fold
float g_settled = 1.0f;            // F: product of every folded step
void* g_root = nullptr;            // adopted root: the tree we zoom
std::uint64_t g_root_tick = 0;     // root evaluations seen
std::uint64_t g_root_last = 0;     // g_root_tick when g_root was last evaluated

// --- shared with Lua (g_mu) ---
std::mutex g_mu;
Req g_queue[kQueue];
int g_queue_n = 0;
float g_target = 1.0f;             // F times every queued / in-flight step
std::atomic<float> g_current{1.0f};

std::uintptr_t image_base() {
    HMODULE h = GetModuleHandleA("Ravenswatch.exe");
    if (!h) h = GetModuleHandleA(nullptr);
    return reinterpret_cast<std::uintptr_t>(h);
}

std::uintptr_t rebase(std::uintptr_t va) {
    return va - Sym::kPreferredBase + image_base();
}

void init_mod(ZoomMod& m, float factor) {
    // Same values as the game's own zoom constructor, plus our curve.
    m = ZoomMod{};
    m.vft = g_vft_zoom;
    m.dir = 1;
    m.duration = 1.0f;
    m.weight = 1.0f;
    m.curve = kCurveCosine;
    m.factor = factor;
}

bool is_ours(const void* p) {
    if (p == &g_base) return true;
    const auto* s = static_cast<const ZoomMod*>(p);
    return s >= &g_step[0] && s < &g_step[kSteps];
}

// Is `mod` the root embedded in a CameraSceneContext? The evaluator dereferences
// `mod` on its first instruction, so its vftable read is as safe as the call; the
// context header 0x78 bytes before it is read guarded.
bool is_camera_root(void* mod) {
    if (mod == g_root) return true;
    const auto a = reinterpret_cast<std::uintptr_t>(mod);
    if (*reinterpret_cast<const std::uintptr_t*>(a) != g_vft_base) return false;
    std::uintptr_t ctx_vft = 0;
    return mem_load(a - kRootInContext, &ctx_vft) && ctx_vft == g_vft_ctx;
}

// Re-add `m` (moving it to the end of the root's children) without restarting
// its blend: AddChild resets `elapsed` unless instant.
void move_to_end(ZoomMod& m, void* root) {
    const float elapsed = m.elapsed, weight = m.weight;
    const std::uint8_t dir = m.dir;
    g_add(&m, root, false);
    m.elapsed = elapsed;
    m.weight = weight;
    m.dir = dir;
}

// Settle a step at its target: its factor moves into the base, and the step
// leaves the tree. Continuous, because a finished step is already at weight 1.
void fold_step(int i, void* root) {
    g_settled *= g_step[i].factor;
    g_base.factor = g_settled;
    if (root != nullptr) g_remove(root, &g_step[i]);
    g_step_live[i] = false;
}

// Read the root's child array. Presence comes from the array itself, never from
// our in_list flags: our objects can be listed in more than one tree, and a new
// context can be allocated at the address of a freed one.
bool read_children(void* root, void* const** kids, std::uint32_t* count) {
    const auto rp = reinterpret_cast<std::uintptr_t>(root);
    std::uintptr_t arr = 0;
    std::uint32_t n = 0;
    if (!mem_load(rp + kChildArray, &arr) || !mem_load(rp + kChildCount, &n)) return false;
    if (n > kMaxChildren) return false;
    if (n == 0) { *kids = nullptr; *count = 0; return true; }
    if (arr == 0 || !mem_readable(reinterpret_cast<const void*>(arr), n * sizeof(void*)))
        return false;
    *kids = reinterpret_cast<void* const*>(arr);
    *count = n;
    return true;
}

// Take every one of ours out of `root`. Collected first: the remove shifts the
// array we are reading.
void remove_ours(void* root) {
    void* const* kids = nullptr;
    std::uint32_t count = 0;
    if (!read_children(root, &kids, &count)) return;
    void* found[kSteps + 1];
    int n = 0;
    for (std::uint32_t i = 0; i < count && n < kSteps + 1; ++i)
        if (is_ours(kids[i])) found[n++] = kids[i];
    for (int i = 0; i < n; ++i) g_remove(root, found[i]);
}

void drain_requests(Req* out, int* n) {
    std::lock_guard<std::mutex> g(g_mu);
    *n = g_queue_n;
    for (int i = 0; i < g_queue_n; ++i) out[i] = g_queue[i];
    g_queue_n = 0;
}

// Settle everything at its target with nothing of ours in `root` (null: a tree
// that is gone). Queued requests apply at once: there is no camera to ease.
void settle_all(void* root) {
    for (int i = 0; i < kSteps; ++i)
        if (g_step_live[i]) fold_step(i, nullptr);
    Req reqs[kQueue];
    int n = 0;
    drain_requests(reqs, &n);
    for (int r = 0; r < n; ++r) g_settled *= reqs[r].step;
    g_base.factor = g_settled;
    if (root != nullptr) remove_ours(root);
}

// Runs inside the evaluation of the adopted root, before the original. Returns
// true when the zoom is in the tree and behind the camera's modifiers, which is
// what the state snapshot relies on.
bool tick(void* root) {
    hook_note_fire(g_eval_va);
    void* const* kids = nullptr;
    std::uint32_t count = 0;
    if (!read_children(root, &kids, &count)) return false;   // cannot see the tree: touch nothing

    std::uintptr_t cams[kCamRing];
    bool scene[kCamRing];
    {
        std::lock_guard<std::mutex> g(g_cam_mu);
        for (int i = 0; i < kCamRing; ++i) { cams[i] = g_cam[i].mod; scene[i] = g_cam[i].scene; }
    }
    // 0: not a camera's modifier; 1: a player camera's; 2: a scene camera's.
    auto cam_kind = [&cams, &scene](const void* p) {
        const auto a = reinterpret_cast<std::uintptr_t>(p);
        for (int i = 0; i < kCamRing; ++i)
            if (cams[i] != 0 && cams[i] == a) return scene[i] ? 2 : 1;
        return 0;
    };

    // 1. Which of ours are in this tree, and where are the camera's modifiers?
    bool base_in = false;
    bool step_in[kSteps]{};
    std::int64_t last_cam = -1, first_ours = -1;
    std::uintptr_t present[kCamRing];
    int n_present = 0;
    for (std::uint32_t i = 0; i < count; ++i) {
        void* k = kids[i];
        if (k == &g_base) {
            base_in = true;
        } else if (is_ours(k)) {
            step_in[static_cast<ZoomMod*>(k) - &g_step[0]] = true;
        } else {
            const int kind = cam_kind(k);
            if (kind != 0 && n_present < kCamRing)
                present[n_present++] = reinterpret_cast<std::uintptr_t>(k);
            if (kind == 1) last_cam = i;   // a scene camera's modifiers stay after ours
            continue;
        }
        if (first_ours < 0) first_ours = i;
    }
    touch_camera_mods(present, n_present);

    const bool on = last_cam >= 0;
    if (on != g_zoom_on) {
        g_zoom_on = on;
        char line[192];
        std::snprintf(line, sizeof(line),
                      on ? "[camera] zoom resumed: top-down camera in the tree (%u children, %u activations)"
                         : "[camera] zoom paused: no top-down camera in the tree (%u children, %u activations)",
                      static_cast<unsigned>(count), static_cast<unsigned>(g_cam_activations.load()));
        Loader::get().log(line);
    }

    // 2. No top-down camera in this tree: a menu, the hub book, an end screen.
    //    Nothing of ours belongs here. The factor is kept for the next camera.
    if (last_cam < 0) {
        if (first_ours >= 0 || base_in) settle_all(root);
        else settle_all(nullptr);
        return false;
    }

    // 3. Steps that have fully faded in are folded into the base; a step that
    //    left the tree some other way is settled at its target.
    for (int i = 0; i < kSteps; ++i) {
        if (!g_step_live[i]) continue;
        if (!step_in[i]) fold_step(i, nullptr);
        else if (g_step[i].elapsed >= g_step[i].duration) fold_step(i, root);
    }

    // 4. The base modifier carries the settled factor at weight 1.
    if (!base_in) {
        g_base.factor = g_settled;
        g_add(&g_base, root, true);
    }

    // 5. New requests. Each takes a free step that eases in with the engine's
    //    cosine curve; with no free step (more notches in flight than the pool
    //    holds) the request is applied to the base at once. New ones are
    //    appended, so they are behind the camera already.
    Req reqs[kQueue];
    int n = 0;
    drain_requests(reqs, &n);
    for (int r = 0; r < n; ++r) {
        int free_i = -1;
        for (int i = 0; i < kSteps; ++i)
            if (!g_step_live[i] && !step_in[i]) { free_i = i; break; }
        if (free_i < 0) {
            g_settled *= reqs[r].step;
            g_base.factor = g_settled;
            continue;
        }
        ZoomMod& m = g_step[free_i];
        init_mod(m, reqs[r].step);
        const bool instant = reqs[r].seconds <= kInstant;
        m.duration = instant ? 1.0f : reqs[r].seconds;
        g_add(&m, root, instant);
        g_step_live[free_i] = true;
    }

    // 6. Keep ours behind the camera's modifiers. A camera that activates
    //    appends its modifiers after ours; checking every frame (not on a flag
    //    raised by the activate) holds whichever tree the camera went into.
    if (first_ours >= 0 && first_ours < last_cam) {
        move_to_end(g_base, root);
        for (int i = 0; i < kSteps; ++i)
            if (g_step_live[i] && step_in[i]) move_to_end(g_step[i], root);
    }
    return true;
}

// --- Keeping the zoom out of the next frame's blend --------------------------
//
// The camera state the root is evaluated on persists from frame to frame, and a
// position modifier below weight 1 (a camera fading in or out) lerps FROM it
// rather than overwriting it. Left alone, the eye we pulled in last frame is the
// starting point of this frame's blend and gets pulled in again: during every
// camera transition the zoom would compound. So after each evaluation we record
// the state and the factor we applied, and before the next one, if the state is
// still exactly what we left (nothing else wrote it), we put back the eye the
// game's own modifiers produced. Anything that wrote the state in between wins.

struct Vec3 { float x, y, z; };
constexpr std::uintptr_t kLook = 0x00, kEye = 0x0c;
constexpr std::uintptr_t kWeight = 0x14;

struct Snap {
    void* state = nullptr;
    Vec3 look{}, eye{};      // as we left it (zoomed)
    Vec3 raw_eye{};          // the eye before our zoom
    bool valid = false;
};
Snap g_snap;

bool same(const Vec3& a, const Vec3& b) { return std::memcmp(&a, &b, sizeof(Vec3)) == 0; }

void unzoom_state(void* state) {
    if (!g_snap.valid || state != g_snap.state) { g_snap.valid = false; return; }
    g_snap.valid = false;
    const auto sp = reinterpret_cast<std::uintptr_t>(state);
    Vec3 look{}, eye{};
    if (!mem_load(sp + kLook, &look) || !mem_load(sp + kEye, &eye)) return;
    if (!same(look, g_snap.look) || !same(eye, g_snap.eye)) return;
    if (!mem_writable(reinterpret_cast<void*>(sp + kEye), sizeof(Vec3))) return;
    std::memcpy(reinterpret_cast<void*>(sp + kEye), &g_snap.raw_eye, sizeof(Vec3));
}

// The factor the evaluator just applied: Apply scales by lerp(1, factor, w) with
// w = root weight x own weight, and only when w > 0.
float applied_factor(void* root) {
    float rw = 1.0f;
    if (!mem_load(reinterpret_cast<std::uintptr_t>(root) + kWeight, &rw)) return 0.0f;
    auto one = [rw](const ZoomMod& m) {
        const float w = rw * m.weight;
        return w > 0.0f ? 1.0f + (m.factor - 1.0f) * w : 1.0f;
    };
    float f = g_base.in_list ? one(g_base) : 1.0f;
    for (int i = 0; i < kSteps; ++i)
        if (g_step_live[i] && g_step[i].in_list) f *= one(g_step[i]);
    return f;
}

void snapshot_state(void* root, void* state) {
    const float f = applied_factor(root);
    g_current.store(f > 0.0f ? f : g_settled, std::memory_order_relaxed);
    // The division below undoes OUR scaling only when ours ran last. A
    // cinematic's modifiers after ours (left there on purpose) wrote the eye
    // after us, and then there is nothing of ours to take back out.
    void* const* kids = nullptr;
    std::uint32_t count = 0;
    if (!read_children(root, &kids, &count)) return;
    bool seen_ours = false;
    for (std::uint32_t i = 0; i < count; ++i) {
        if (is_ours(kids[i])) seen_ours = true;
        else if (seen_ours) return;
    }
    const auto sp = reinterpret_cast<std::uintptr_t>(state);
    Snap s;
    if (!(f > 1e-4f) || !std::isfinite(f)) return;
    if (!mem_load(sp + kLook, &s.look) || !mem_load(sp + kEye, &s.eye)) return;
    s.raw_eye = Vec3{s.look.x + (s.eye.x - s.look.x) / f,
                     s.look.y + (s.eye.y - s.look.y) / f,
                     s.look.z + (s.eye.z - s.look.z) / f};
    s.state = state;
    s.valid = true;
    g_snap = s;
}

void detour_eval(void* mod, const float* dt, void* state, float parent_weight) {
    if (mod == nullptr || !is_camera_root(mod)) {
        g_real_eval(mod, dt, state, parent_weight);
        return;
    }
    ++g_root_tick;
    if (mod != g_root) {
        if (g_root != nullptr && g_root_tick - g_root_last < kRootStale) {
            // A second live camera tree (the menu-side scene stays alive beside
            // a run, and the end-of-run book is drawn through it). Whatever of
            // ours an earlier adoption left in it comes out, on its own
            // evaluation, where its array is safe to change.
            remove_ours(mod);
            g_real_eval(mod, dt, state, parent_weight);
            return;
        }
        // The adopted tree has not been evaluated for a while: switch. In-flight
        // steps settle at their targets; the old tree, if it is still alive, is
        // cleaned the next time it is evaluated.
        settle_all(nullptr);
        g_snap.valid = false;
        g_root = mod;
        char line[160];
        std::snprintf(line, sizeof(line),
                      "[camera] zoom attached to camera root %p (evaluator thread %lu)",
                      mod, static_cast<unsigned long>(GetCurrentThreadId()));
        Loader::get().log(line);
    }
    g_root_last = g_root_tick;
    const bool placed = tick(mod);
    // Put back last frame's unzoomed eye whether or not the zoom is on this
    // frame: when it just switched off, that is exactly the eye to start from.
    if (state != nullptr) unzoom_state(state);
    g_real_eval(mod, dt, state, parent_weight);
    if (placed && state != nullptr) snapshot_state(mod, state);
    else g_snap.valid = false;
}

void detour_activate(void* top_down_camera) {
    g_real_activate(top_down_camera);
    // The camera's two modifiers, built or reused by the call that just ran.
    g_cam_activations.fetch_add(1);
    const auto c = reinterpret_cast<std::uintptr_t>(top_down_camera);
    if (c == 0) return;
    char name[48] = "?";
    std::uintptr_t settings = 0, name_ptr = 0;
    if (mem_load(c + kCamSettings, &settings) && settings != 0 &&
        mem_load(settings + kSettingsName, &name_ptr) && name_ptr != 0)
        mem_read_cstr(name_ptr, name, sizeof(name));
    const bool scene = is_scene_camera(name);
    log_first_activation(name, scene);
    std::uintptr_t pos = 0, nearfar = 0;
    if (mem_load(c + kCamPositionMod, &pos)) remember_camera_mod(pos, scene);
    if (mem_load(c + kCamNearFarMod, &nearfar)) remember_camera_mod(nearfar, scene);
}

bool queue(float step, float seconds) {
    if (!g_armed.load(std::memory_order_acquire)) return false;
    if (!std::isfinite(step) || step < kMinStep || step > kMaxStep) return false;
    if (!std::isfinite(seconds) || seconds < 0.0f) seconds = 0.0f;
    if (seconds > 10.0f) seconds = 10.0f;
    std::lock_guard<std::mutex> g(g_mu);
    if (g_queue_n >= kQueue) {
        // Frames are not being evaluated (loading screen): merge into the
        // newest request instead of growing.
        g_queue[kQueue - 1].step *= step;
    } else {
        g_queue[g_queue_n++] = Req{step, seconds};
    }
    g_target *= step;
    return true;
}

} // namespace

bool camera_zoom_armed() { return g_armed.load(std::memory_order_acquire); }

bool camera_zoom_by(float step, float seconds) { return queue(step, seconds); }

bool camera_zoom_reset(float seconds) {
    float target = 1.0f;
    {
        std::lock_guard<std::mutex> g(g_mu);
        target = g_target;
    }
    if (!(target > 0.0f) || !std::isfinite(target)) return false;
    if (std::fabs(target - 1.0f) < 1e-4f) return true;
    // One step back to 1. Outside the per-step range is possible after many
    // notches, so split it.
    float rest = 1.0f / target;
    bool ok = true;
    while (ok && (rest < kMinStep || rest > kMaxStep)) {
        const float part = rest < kMinStep ? kMinStep : kMaxStep;
        ok = queue(part, seconds);
        rest /= part;
    }
    return ok && queue(rest, seconds);
}

void camera_zoom_factor(float* target, float* current) {
    if (target) {
        std::lock_guard<std::mutex> g(g_mu);
        *target = g_target;
    }
    if (current) *current = g_current.load(std::memory_order_relaxed);
}

bool install_camera_hooks() {
    // Fail closed on an unfingerprinted build: the three vftables that tell the
    // camera root from every other modifier are raw VAs.
    if (!Loader::get().va_globals_trusted()) {
        Loader::get().log("[camera] zoom not arming: VA globals are not trusted on this "
                          "game build, so the camera root cannot be identified");
        return false;
    }
    g_vft_base = rebase(Sym::g_CameraModifier_vftable);
    g_vft_zoom = rebase(Sym::g_ZoomCameraModifier_vftable);
    g_vft_ctx = rebase(Sym::g_CameraSceneContext_vftable);
    std::uintptr_t probe = 0;
    if (!mem_load(g_vft_base, &probe) || !mem_load(g_vft_zoom, &probe) ||
        !mem_load(g_vft_ctx, &probe)) {
        Loader::get().log("[camera] zoom not arming: modifier vftables are not readable");
        return false;
    }
    init_mod(g_base, 1.0f);
    for (auto& m : g_step) init_mod(m, 1.0f);

    void* add = nullptr;
    if (!resolve_checked("camera", "modifier add", Sym::CameraModifier_AddChild_Pattern, &add))
        return false;
    g_add = reinterpret_cast<Add_fn>(add);
    void* remove = nullptr;
    if (!resolve_checked("camera", "modifier remove", Sym::CameraModifier_RemoveChild_Pattern,
                         &remove))
        return false;
    g_remove = reinterpret_cast<Remove_fn>(remove);
    // Without this the zoom never knows which modifiers belong to the camera,
    // so it is required, and installed before the evaluator hook.
    if (!hook_install("camera", "top-down camera activate",
                      Sym::TopDownCamera_Activate_Pattern,
                      reinterpret_cast<void*>(&detour_activate),
                      reinterpret_cast<void**>(&g_real_activate)))
        return false;
    const bool ok = hook_install("camera", "modifier evaluate",
                                 Sym::CameraModifier_Evaluate_Pattern,
                                 reinterpret_cast<void*>(&detour_eval),
                                 reinterpret_cast<void**>(&g_real_eval), &g_eval_va);
    g_armed.store(ok, std::memory_order_release);
    return ok;
}

} // namespace rsmm
