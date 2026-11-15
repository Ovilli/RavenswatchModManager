// R.ui.menus: mod pages in the game's book. See hook_book_pages.h.
//
// A mod page is a real BookOptions page, opened with the game's own
// BookPage_OpenChild(parent, desc) (what the Credits row on Settings does).
// The page's slot-7 build runs INSIDE that call. The Graphics/Audio
// tab builders are detoured here to do nothing on our controller (Keyboard/
// Controller are gated in hook_keybinds.cpp);
// hook_settings_menu.cpp's hook_build (the Miscellaneous builder) hands OUR
// controller to book_pages_build, which adds our categories and rows the same
// way add_mods_tab does. When OpenChild returns we hide the trailing
// Credits/EULA/Privacy entries and select our first category. Offsets are for
// build b9c3 (see data/symbols.json, category "ui").
//
// Event flow mirrors hook_ui_state.cpp: events are queued and emitted by the
// outermost detour on the thread, so a mod handler never runs inside the
// engine's call. The two exceptions are ui:_menus_refresh and ui:_menus_back,
// which are synchronous on purpose (Lua pushes a fresh snapshot / vetoes Back
// before the engine continues).

#include "hook_book_pages.h"
#include "hook_settings_menu.h"

#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <deque>
#include <list>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <vector>

#include "json.hpp"   // single-header nlohmann::json (vendored)

#include "fn_resolver.h"
#include "hook_menu_common.h"
#include "hook_util.h"
#include "loader.h"
#include "mem_safe.h"
#include "script_lua.h"
#include "symbols.gen.h"
#include "symbols_api.gen.h"

namespace rsmm {
using namespace menu;   // hook_menu_common.h: OcStr, lit, clip, offsets, row spawn

namespace {

using json = nlohmann::json;

// Page controller
constexpr std::uintptr_t kPageBm        = 0xd0;
constexpr std::uintptr_t kPageChild     = 0xd8;
// BookOptions controller (the shared offsets are in hook_menu_common.h)
constexpr std::uintptr_t kCtrlSelected  = 0x218;
constexpr std::uintptr_t kCtrlApply     = 0x268;   // the Graphics tab's Apply element
constexpr std::uintptr_t kButtonIndex   = 0x238;   // u64 index AddCategory stamps
constexpr std::uintptr_t kSetCreditsDesc = 0x740;  // settings: the Credits child descriptor
// BookMenu
constexpr std::uintptr_t kBmSettings    = 0x10;
constexpr std::uintptr_t kBmPage        = 0x1e0;
constexpr std::uintptr_t kBmDescBase    = 0x2d8;   // settings: child descriptors, stride 0xd8
constexpr std::size_t    kDescSize      = 0xd8;
constexpr std::size_t    kDescSystem    = 2;       // the System page's descriptor
constexpr std::size_t    kDescClearFrom = 0x70;    // +0x70 arg, +0x78 manager, +0x80 invoker
constexpr std::size_t    kDescClearLen  = 0x18;
constexpr std::size_t    kBmReadSize    = 0x80;

constexpr std::uint32_t kEntryType      = 10;      // "open child page" (Credits)
constexpr int           kMaxDepth       = 8;
constexpr std::uint32_t kMaxTabs        = 64;
constexpr ULONGLONG     kLeafFreshMs    = 1000;
constexpr ULONGLONG     kRequestTtlMs   = 5000;

inline std::uintptr_t A(const void* p) { return reinterpret_cast<std::uintptr_t>(p); }

// Guarded load / store at base + off (base is a pointer or an address).
template <class T>
bool load_at(const void* base, std::uintptr_t off, T* out) { return mem_load(A(base) + off, out); }
template <class T>
bool load_at(std::uintptr_t base, std::uintptr_t off, T* out) { return mem_load(base + off, out); }

bool store_ptr(void* base, std::uintptr_t off, void* v) {
    void* at = reinterpret_cast<std::uint8_t*>(base) + off;
    if (!mem_writable(at, sizeof(void*))) return false;
    *static_cast<void**>(at) = v;
    return true;
}

// --- snapshots (what Lua set) ----------------------------------------------------

struct RowSnap {
    std::string id, label;
    std::vector<std::string> choices;
    std::uint32_t value = 0, def = 0;     // 0-based here, 1-based in the JSON
    bool readonly = false;
};
struct CatSnap {
    std::string id, label, h_title, h_sub, h_text;
    std::vector<RowSnap> rows;
};
struct PageSnap {
    std::string title;
    std::vector<CatSnap> cats;
};
struct EntrySnap {
    std::string id, title, page, after;
};

// --- live state ----------------------------------------------------------------

struct LiveRow {
    std::string id, title;
    std::vector<std::string> texts;
    std::vector<OcStr> labels;
    std::uint32_t value = 0, seen = 0, def = 0;   // the game writes `value`
    bool editable = false;
    void* row = nullptr;                          // the game's row object
};

struct Record {
    void* ctrl = nullptr;
    void* parent = nullptr;
    std::string page_id, ctx;                     // ctx: raw JSON text or ""
    int depth = 1;
    bool building = true;
    struct Cat {
        std::uint32_t entry_index = 0;
        std::string id;
        std::vector<LiveRow*> rows;               // editable rows only
    };
    std::vector<Cat> cats;
    std::map<std::uint32_t, std::string> nested;  // entry index -> entry id
    const Cat* cat_at(std::uint32_t i) const {
        for (const auto& c : cats) if (c.entry_index == i) return &c;
        return nullptr;
    }
    bool ours_index(std::uint32_t i) const { return nested.count(i) || cat_at(i); }
};

struct Event { std::string name, payload; };
struct Request {
    bool open = true;
    std::string page, ctx;
    ULONGLONG at = 0;
};

std::mutex g_mu;   // guards everything down to g_armed
std::map<std::string, PageSnap> g_pages;
std::map<std::string, EntrySnap> g_entries;
struct SavedTitle { std::uintptr_t label; const std::string* orig; };
struct OurPage {
    // Child windows we hid. Pooled entities keep a child window's visible bit across
    // release and reuse (activation re-shows only the root), so teardown shows them
    // again before the entity goes back to its pool.
    std::vector<void*> hidden;
    SavedTitle title{};                          // heading label + its original text
};
std::map<void*, OurPage> g_ours;                 // controllers our build produced
std::list<Record> g_records;                     // open order: parents before children
std::deque<LiveRow> g_live_rows;                 // never freed: the game holds &value
std::deque<std::string> g_strs;                  // never freed: literal strings
std::vector<Event> g_events;
std::deque<Request> g_reqs;
void* g_settings_ctrl = nullptr;                 // the vanilla Settings controller
std::map<std::uint32_t, std::string> g_settings_idx;   // its entry index -> entry id
bool g_settings_built = false;

std::atomic<bool> g_armed{false};
std::atomic<bool> g_dirty{false};
std::atomic<bool> g_veto{false};
std::atomic<void*> g_last_leaf{nullptr};
std::atomic<ULONGLONG> g_last_tick{0};
std::mutex g_arm_mu;
constexpr const char* kNotInstalled = "not installed";
std::string g_why = kNotInstalled;

thread_local int t_depth = 0;
// OUR page's controller being built inside OpenChild.
thread_local bool t_building = false;
thread_local void* t_build_ctrl = nullptr;
thread_local void* t_build_parent = nullptr;
thread_local int t_build_depth = 1;
thread_local std::string t_build_page, t_build_ctx;

// --- engine side -----------------------------------------------------------------

MenuFns g_menu;
engine::GameUi_SetVisible_fn            g_set_visible  = nullptr;
engine::BookMenu_GetMode_fn             g_get_mode     = nullptr;

engine::BookPage_OpenChild_fn           g_real_open    = nullptr;
engine::BookPage_CloseChild_fn          g_real_close   = nullptr;
engine::BookMenu_OnBackPressed_fn       g_real_back    = nullptr;
engine::OptionsMenu_ResetPressed_fn     g_real_reset   = nullptr;
engine::OptionsMenu_SelectCategory_fn   g_real_select  = nullptr;
engine::OptionsMenu_Update_fn           g_real_update  = nullptr;
engine::OptionsMenu_BuildGraphics_fn    g_real_build_gfx   = nullptr;
engine::OptionsMenu_BuildAudio_fn       g_real_build_audio = nullptr;
engine::OptionsMenu_Teardown_fn         g_real_teardown    = nullptr;

// --- events ----------------------------------------------------------------------

std::string dumps(const json& j) { return j.dump(-1, ' ', false, json::error_handler_t::replace); }

json ctx_value(const std::string& raw) {
    if (raw.empty()) return nullptr;
    json j = json::parse(raw, nullptr, false);
    return j.is_discarded() ? json(nullptr) : j;
}

std::string page_payload(const std::string& page, const std::string& ctx, int depth) {
    return dumps(json{{"page", page}, {"ctx", ctx_value(ctx)}, {"depth", depth}});
}

void queue_locked(const char* name, std::string payload) {
    g_events.push_back({name, std::move(payload)});
    g_dirty.store(true, std::memory_order_release);
}

void queue(const char* name, std::string payload) {
    std::lock_guard<std::mutex> lk(g_mu);
    queue_locked(name, std::move(payload));
}

void flush() {
    std::vector<Event> out;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        g_dirty.store(false, std::memory_order_relaxed);
        if (g_events.empty()) return;
        out.swap(g_events);
    }
    for (const auto& e : out) {
        if (script_has_handler(e.name.c_str())) script_emit_event_json(e.name, e.payload);
    }
}

void flush_if_outermost() {
    if (t_depth == 0 && g_dirty.load(std::memory_order_acquire)) flush();
}

void emit_sync(const char* name, const std::string& payload) {
    if (script_has_handler(name)) script_emit_event_json(name, payload);
}

struct DepthGuard {
    DepthGuard() { ++t_depth; }
    ~DepthGuard() { --t_depth; }
};

// --- records ---------------------------------------------------------------------

// Queues ui:menus_change for every editable row whose value moved since the last
// look. Loader-owned values only. g_mu held.
void emit_row_changes_locked(Record& rec) {
    for (auto& c : rec.cats) {
        for (LiveRow* r : c.rows) {
            const std::uint32_t now = *static_cast<volatile std::uint32_t*>(&r->value);
            if (now == r->seen) continue;
            r->seen = now;
            queue_locked("ui:menus_change",
                         dumps(json{{"page", rec.page_id}, {"category", c.id},
                                    {"row", r->id}, {"index", now + 1}}));
        }
    }
}

// Drop records whose page is no longer the child of its parent (and their
// children), queueing ui:menus_close, deepest first. A row change not yet seen by
// the watcher is emitted first. The parent of the shallowest dead record becomes
// the current leaf before any close event flushes. g_mu held.
void prune_locked() {
    std::vector<std::list<Record>::iterator> dead;
    std::set<void*> dead_ctrls;
    for (auto it = g_records.begin(); it != g_records.end(); ++it) {
        if (it->building) continue;
        std::uintptr_t child = 0;
        const bool open = load_at(it->parent, kPageChild, &child) && child == A(it->ctrl);
        if (!open || dead_ctrls.count(it->parent)) {
            dead.push_back(it);
            dead_ctrls.insert(it->ctrl);
        }
    }
    void* new_leaf = nullptr;
    int new_leaf_depth = 0;
    for (auto d = dead.rbegin(); d != dead.rend(); ++d) {
        if (!new_leaf || (*d)->depth < new_leaf_depth) {
            new_leaf = (*d)->parent;
            new_leaf_depth = (*d)->depth;
        }
        emit_row_changes_locked(**d);
        queue_locked("ui:menus_close", page_payload((*d)->page_id, (*d)->ctx, (*d)->depth));
        g_records.erase(*d);
    }
    if (new_leaf) {
        g_last_leaf.store(new_leaf);
        g_last_tick.store(GetTickCount64());
    }
}

// Lookups are loader-side state only. find_record, depth_no_prune and is_tracked
// never prune or read game memory, so the Lua-facing functions and the detour
// gates can call them from any thread; record_of, depth_of and is_host prune and
// stay on the game-thread paths.
const Record* find_locked(void* ctrl) {   // g_mu held
    for (const auto& r : g_records) if (r.ctrl == ctrl) return &r;
    return nullptr;
}

bool find_record(void* ctrl, Record* out) {
    if (!ctrl) return false;
    std::lock_guard<std::mutex> lk(g_mu);
    const Record* r = find_locked(ctrl);
    if (r && out) *out = *r;
    return r != nullptr;
}

int depth_no_prune(void* ctrl) {
    if (!ctrl) return 0;
    std::lock_guard<std::mutex> lk(g_mu);
    const Record* r = find_locked(ctrl);
    return r ? r->depth : 0;
}

bool record_of(void* ctrl, Record* out) {
    if (!ctrl) return false;
    std::lock_guard<std::mutex> lk(g_mu);
    prune_locked();
    const Record* r = find_locked(ctrl);
    if (r && out) *out = *r;
    return r != nullptr;
}

bool is_tracked(void* ctrl) {   // the vanilla Settings ctrl or one of our records
    if (!ctrl) return false;
    std::lock_guard<std::mutex> lk(g_mu);
    return ctrl == g_settings_ctrl || find_locked(ctrl) != nullptr;
}

bool any_records() {
    std::lock_guard<std::mutex> lk(g_mu);
    return !g_records.empty();
}

bool is_host(void* ctrl) {
    if (!ctrl) return false;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        if (ctrl == g_settings_ctrl) return true;
    }
    return record_of(ctrl, nullptr);
}

int depth_of(void* ctrl) {
    Record r;
    return record_of(ctrl, &r) ? r.depth : 0;
}

// --- building our page -----------------------------------------------------------

void hide_window(void* ctrl, void* w) {
    g_set_visible(w, false, false);
    std::lock_guard<std::mutex> lk(g_mu);
    g_ours[ctrl].hidden.push_back(w);
}

bool spawn_row(void* ctrl, void* settings, void* factory, void* cat, void* row_parent,
               LiveRow& r) {
    auto& L = Loader::get();
    build_labels(r.texts, r.labels);
    void* row = spawn_menu_row(g_menu, ctrl, settings, factory, cat, row_parent, &r.value,
                               r.labels, r.title);
    if (!row) {
        L.log_err("[ui-menus] row spawn failed at '" + r.title + "'");
        return false;
    }
    auto* p = reinterpret_cast<std::uint8_t*>(row);
    r.row = row;
    // A pooled row may carry hidden arrows from an earlier page: set both explicitly.
    for (std::uintptr_t off : {kRowArrowL, kRowArrowR}) {
        void* arrow = nullptr;
        if (!load_at(p, off, &arrow) || !arrow) continue;
        if (r.editable) g_set_visible(arrow, true, true);
        else hide_window(ctrl, arrow);   // a single choice: hide both arrows
    }
    return true;
}

// The game keeps pointers to the strings we hand it, so they live in g_strs for good.
const std::string* keep_str(const std::string& s) {
    std::lock_guard<std::mutex> lk(g_mu);
    g_strs.push_back(s);
    return &g_strs.back();
}

// Adds a tab to a controller; *index is its entry index. nullptr when the tab count
// is unreadable (*unreadable set) or the game refuses.
void* add_tab(void* ctrl, void* page, void* parent, const std::string& label,
              std::uint32_t type, std::uint32_t* index, bool* unreadable = nullptr) {
    if (!load_at(ctrl, kCtrlTabCount, index)) {
        if (unreadable) *unreadable = true;
        return nullptr;
    }
    OcStr t = lit(*keep_str(clip(label)));
    return g_menu.add_category(ctrl, page, parent, &t, type);
}

LiveRow* new_row(const std::string& id, const std::string& title) {
    g_live_rows.emplace_back();
    LiveRow* r = &g_live_rows.back();
    r->id = id;
    r->title = clip(title);
    return r;
}

// ---- hooks ------------------------------------------------------------------------

// The BM System-page descriptor copy handed to the original OpenChild. Loader
// owned. BookPage_OpenChild and its spawner only write into the descriptor for the
// duration of the synchronous spawn and keep no pointer to it, and opens never
// overlap (Lua opens are queued and run from hook_update), so one copy is safe to
// reuse across opens, nested ones included.
std::uint8_t g_desc[kDescSize];

enum class Target { NotOurs, Ours, Gone };

Target entry_target(void* parent, std::uint32_t idx, std::string* page, int* depth) {
    std::lock_guard<std::mutex> lk(g_mu);
    prune_locked();
    std::string entry;
    bool found = false;
    int d = 0;
    for (const auto& r : g_records) {
        if (r.ctrl != parent) continue;
        d = r.depth;
        auto it = r.nested.find(idx);
        if (it != r.nested.end()) { entry = it->second; found = true; }
        break;
    }
    if (!found && parent == g_settings_ctrl) {
        auto it = g_settings_idx.find(idx);
        if (it != g_settings_idx.end()) { entry = it->second; found = true; }
    }
    if (!found) return Target::NotOurs;
    auto e = g_entries.find(entry);
    if (e == g_entries.end()) return Target::Gone;
    *page = e->second.page;
    *depth = d + 1;
    return Target::Ours;
}

// Tab count of a controller, clamped to kMaxTabs; 0 when the tab vector is unreadable.
std::uint32_t tab_count(void* ctrl) {
    std::uintptr_t tabs = 0;
    std::uint32_t count = 0;
    if (!load_at(ctrl, kCtrlTabs, &tabs) || !tabs || !load_at(ctrl, kCtrlTabCount, &count)) return 0;
    return std::min(count, kMaxTabs);
}

// Hides every entry that is not ours: with the vanilla tab builders skipped on
// our page that is only the trailing Credits/EULA/Privacy.
void hide_foreign_tabs(void* child, const Record& rec) {
    const std::uint32_t count = tab_count(child);
    for (std::uint32_t i = 0; i < count; ++i) {
        if (rec.ours_index(i)) continue;
        if (void* btn = tab_button(child, i)) hide_window(child, btn);
    }
}

// Pooled tab buttons keep a hidden child window from an earlier page.
void show_our_tabs(void* child, const Record& rec) {
    for (const auto& c : rec.cats)
        if (void* btn = tab_button(child, c.entry_index)) g_set_visible(btn, true, true);
    for (const auto& n : rec.nested)
        if (void* btn = tab_button(child, n.first)) g_set_visible(btn, true, true);
}

// Ravenswatch.exe's image range, for validating vtable and RTTI pointers.
bool image_range(std::uintptr_t* base, std::uintptr_t* size) {
    static std::uintptr_t b = 0, sz = 0;
    if (!b) {
        const std::uintptr_t m = reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
        std::uint32_t pe = 0, img = 0;
        if (m && load_at(m, 0x3c, &pe) && load_at(m, pe + 24 + 56, &img)) { b = m; sz = img; }
    }
    *base = b;
    *size = sz;
    return b && sz;
}

// MSVC RTTI class name (".?AV...@@") of a window, "?" when anything is off.
std::string rtti_name(std::uintptr_t w) {
    std::uintptr_t base = 0, size = 0, vt = 0, col = 0;
    std::uint32_t tdrva = 0;
    if (!image_range(&base, &size) || !mem_load(w, &vt) || vt < base + 8 || vt >= base + size
        || !mem_load(vt - 8, &col) || col < base || col >= base + size
        || !load_at(col, 12, &tdrva) || tdrva >= size) return "?";
    std::string out;
    for (int k = 0; k < 120; ++k) {
        std::uint8_t ch = 0;
        if (!load_at(base, tdrva + 16 + k, &ch) || !ch) break;
        out += (ch >= 0x20 && ch < 0x7f) ? char(ch) : '.';
    }
    return out.empty() ? "?" : out;
}

// The page heading is the only oCUILabel that is a direct child of the page's root
// window. Its displayed text is the oCString at +0x1e8; vtable slot +0x60 is
// SetText(label, const oCString*).
constexpr std::uintptr_t kCtrlBmx = 0x68;          // controller -> its BookMenu-side object
constexpr std::uintptr_t kBmxRoot = 0x88;          // ... -> the page's root window
constexpr std::uintptr_t kRootChildren = 0x2a8;    // root window -> first child
constexpr std::uintptr_t kWindowNext = 0x08;       // window -> next sibling
constexpr std::uintptr_t kLabelText = 0x1e8;
constexpr std::uintptr_t kLabelSetTextSlot = 0x60;
using SetTextFn = void (*)(void*, const OcStr*);

std::uintptr_t find_heading_label(void* ctrl) {
    std::uintptr_t bmx = 0, root = 0, c = 0;
    if (!load_at(ctrl, kCtrlBmx, &bmx) || !bmx || !load_at(bmx, kBmxRoot, &root) || !root
        || !load_at(root, kRootChildren, &c)) return 0;
    for (int n = 0; c && c != ~std::uintptr_t(0) && n < 400; ++n) {
        if (rtti_name(c) == ".?AVoCUILabel@@") return c;
        if (!load_at(c, kWindowNext, &c)) break;
    }
    return 0;
}

bool label_set_text(std::uintptr_t label, const OcStr* text) {
    std::uintptr_t base = 0, size = 0, vt = 0, fn = 0;
    if (!image_range(&base, &size) || !mem_load(label, &vt) || vt < base || vt >= base + size
        || !load_at(vt, kLabelSetTextSlot, &fn) || fn < base || fn >= base + size) return false;
    reinterpret_cast<SetTextFn>(fn)(reinterpret_cast<void*>(label), text);
    return true;
}

// Retitle our page's heading, remembering the original text: the page entity is
// pooled per template, so vanilla Settings pages reuse it (restored in hook_teardown).
void set_page_title(void* ctrl, const std::string& title) {
    static bool warned = false;
    const std::uintptr_t label = find_heading_label(ctrl);
    std::uintptr_t optr = 0;
    std::uint32_t olen = 0;
    if (!label || !load_at(label, kLabelText, &optr)
        || !load_at(label, kLabelText + 8, &olen)) {
        if (!warned) { warned = true; Loader::get().log_warn("[ui-menus] page heading label not found; title unchanged"); }
        return;
    }
    olen &= 0x7fffffff;
    std::string orig;
    if (olen > 0) {
        if (olen > 256 || !mem_readable(reinterpret_cast<void*>(optr), olen)) return;
        orig.assign(reinterpret_cast<const char*>(optr), olen);
    }
    const std::string* orig_keep = keep_str(orig);
    OcStr t = lit(*keep_str(clip(title)));
    if (!label_set_text(label, &t)) return;
    std::lock_guard<std::mutex> lk(g_mu);
    g_ours[ctrl].title = {label, orig_keep};
}

// Open our page `page` under `parent` at `depth`: refresh, build via the real OpenChild,
// then show and select. Shared by hook_open_child (a click) and run_request (Lua).
void open_ours(void* parent, const std::string& page, const std::string& ctx, int depth) {
    auto& L = Loader::get();
    // hook_back walks at most kMaxDepth child links, so a deeper page would make
    // Back consult the wrong record.
    if (depth > kMaxDepth) {
        L.log_warn("[ui-menus] page '" + page + "' not opened: too deep (max "
                   + std::to_string(kMaxDepth) + ")");
        return;
    }

    emit_sync("ui:_menus_refresh", dumps(json{{"page", page}, {"ctx", ctx_value(ctx)}}));
    {
        std::lock_guard<std::mutex> lk(g_mu);
        if (!g_pages.count(page)) {
            L.log_warn("[ui-menus] page '" + page + "' has no snapshot; nothing opened");
            return;
        }
    }
    std::uintptr_t bm = 0, bms = 0;
    if (!load_at(parent, kPageBm, &bm) || !bm
        || !load_at(bm, kBmSettings, &bms) || !bms
        || !mem_readable(reinterpret_cast<void*>(bms + kBmDescBase + kDescSystem * kDescSize),
                         kDescSize)) {
        L.log_err("[ui-menus] BookMenu layout not as expected; page '" + page + "' not opened");
        return;
    }
    std::memcpy(g_desc, reinterpret_cast<void*>(bms + kBmDescBase + kDescSystem * kDescSize),
                kDescSize);
    std::memset(g_desc + kDescClearFrom, 0, kDescClearLen);

    t_building = true;
    t_build_ctrl = nullptr;
    t_build_parent = parent;
    t_build_depth = depth;
    t_build_page = page;
    t_build_ctx = ctx;
    {
        DepthGuard g;
        g_real_open(parent, g_desc);
    }
    t_building = false;
    void* built = t_build_ctrl;
    t_build_ctrl = nullptr;

    std::uintptr_t child = 0;
    load_at(parent, kPageChild, &child);
    void* const child_ctrl = reinterpret_cast<void*>(child);
    Record rec;
    bool have = false;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        for (auto it = g_records.begin(); it != g_records.end();) {
            if (!it->building) { ++it; continue; }
            if (child != 0 && it->ctrl == child_ctrl) {
                it->building = false;
                rec = *it;
                have = true;
                ++it;
            } else {
                it = g_records.erase(it);   // a build that did not end up as the child
            }
        }
    }
    if (child == 0) {
        L.log_err("[ui-menus] OpenChild left no child page for '" + page + "'");
    } else if (!have) {
        L.log_err("[ui-menus] page '" + page + "' opened but its build did not reach us "
                  "(built ctrl " + std::string(built ? "seen" : "missing") + ")");
    } else {
        show_our_tabs(child_ctrl, rec);
        std::string title;
        {
            std::lock_guard<std::mutex> lk(g_mu);
            auto pit = g_pages.find(rec.page_id);
            if (pit != g_pages.end()) title = pit->second.title;
        }
        if (!title.empty()) set_page_title(child_ctrl, title);
        g_last_leaf.store(child_ctrl);   // current() inside the open handler
        g_last_tick.store(GetTickCount64());
        hide_foreign_tabs(child_ctrl, rec);
        if (!rec.cats.empty()) {
            if (void* btn = tab_button(child_ctrl, rec.cats[0].entry_index))
                g_real_select(child_ctrl, btn);
        }
        queue("ui:menus_open", page_payload(rec.page_id, rec.ctx, rec.depth));
    }
    flush_if_outermost();
}

void hook_open_child(void* parent, void* desc) {
    auto& L = Loader::get();
    std::string page;
    int depth = 1;
    bool ours = false;
    if (!is_tracked(parent)) { g_real_open(parent, desc); return; }
    std::uint32_t idx = 0;
    if (parent && load_at(parent, kCtrlSelected, &idx)) {
        const Target t = entry_target(parent, idx, &page, &depth);
        if (t == Target::Gone) {
            L.log_warn("[ui-menus] the selected entry was removed; nothing opened");
            return;
        }
        ours = t == Target::Ours;
    }
    if (!ours) { g_real_open(parent, desc); return; }
    open_ours(parent, page, std::string(), depth);
}

// Our page skips the vanilla tab builders; anyone else's build runs untouched.
void hook_build_graphics(void* ctrl, void* page, void* parent) {
    if (book_pages_building(ctrl)) return;
    g_real_build_gfx(ctrl, page, parent);
}

void hook_build_audio(void* ctrl, void* page, void* parent) {
    if (book_pages_building(ctrl)) return;
    g_real_build_audio(ctrl, page, parent);
}

// The skipped Graphics builder leaves no Apply element, yet teardown reads it
// unchecked; a zeroed block stands in so its listener lists read as empty.
alignas(16) std::uint8_t g_apply_placeholder[0x110] = {};

void hook_teardown(void* ctrl) {
    OurPage ours;
    bool is_ours = false;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        auto it = g_ours.find(ctrl);
        if (it != g_ours.end()) {
            is_ours = true;
            ours.hidden = std::move(it->second.hidden);
            ours.title = it->second.title;
        }
    }
    if (!is_ours) { g_real_teardown(ctrl); return; }
    if (ours.title.label) {   // the pooled page entity must not keep our heading
        OcStr o = lit(*ours.title.orig);
        label_set_text(ours.title.label, &o);
    }
    // Pooled entities keep child-window visibility; re-show before they return to the pool.
    for (void* w : ours.hidden)
        if (mem_readable(w, 0x238)) g_set_visible(w, true, true);
    std::uintptr_t cur = 0;
    if (load_at(ctrl, kCtrlApply, &cur) && cur == 0) store_ptr(ctrl, kCtrlApply, g_apply_placeholder);
    g_real_teardown(ctrl);   // still in g_ours: the ctrl counts as ours until it returns
    {
        std::lock_guard<std::mutex> lk(g_mu);
        g_ours.erase(ctrl);
    }
    if (load_at(ctrl, kCtrlApply, &cur) && cur == A(g_apply_placeholder))
        store_ptr(ctrl, kCtrlApply, nullptr);
}

bool close_and_prune(void* page) {
    bool r;
    {
        DepthGuard g;
        r = g_real_close(page);
    }
    std::lock_guard<std::mutex> lk(g_mu);
    prune_locked();
    return r;
}

bool hook_close_child(void* page) {
    if (!any_records()) return g_real_close(page);
    const bool r = close_and_prune(page);
    flush_if_outermost();
    return r;
}

// True unless a Lua handler vetoed Back.
bool allow_back(const Record& rec) {
    g_veto.store(false);
    emit_sync("ui:_menus_back", page_payload(rec.page_id, rec.ctx, rec.depth));
    return !g_veto.load();
}

void hook_back(void* bm) {
    if (!any_records()) { g_real_back(bm); return; }
    std::uintptr_t leaf = 0;
    if (bm && mem_readable(bm, kBmReadSize) && load_at(bm, kBmPage, &leaf) && leaf) {
        for (int i = 0; i < kMaxDepth; ++i) {
            std::uintptr_t next = 0;
            if (!load_at(leaf, kPageChild, &next) || next == 0) break;
            leaf = next;
        }
        Record rec;
        if (record_of(reinterpret_cast<void*>(leaf), &rec)) {
            if (!allow_back(rec)) { flush_if_outermost(); return; }
            std::uintptr_t cur = 0;
            if (load_at(bm, kBmPage, &cur) && cur && g_get_mode(bm) == 1) {
                // Settings opened from pause: the vanilla Back would leave the book.
                close_and_prune(reinterpret_cast<void*>(cur));
                flush_if_outermost();
                return;
            }
        }
    }
    {
        DepthGuard g;
        g_real_back(bm);
    }
    flush_if_outermost();
}

void hook_reset(void* ctrl) {
    if (!find_record(ctrl, nullptr)) { g_real_reset(ctrl); return; }
    Record rec;
    if (!record_of(ctrl, &rec)) { g_real_reset(ctrl); return; }
    std::uint32_t sel = 0;
    if (load_at(ctrl, kCtrlSelected, &sel)) {
        if (const auto* c = rec.cat_at(sel)) {
            for (LiveRow* r : c->rows) {
                r->value = r->def;
                r->seen = r->def;
                if (r->row) { OcStr t = lit(r->title); g_menu.set_title(r->row, &t); }
            }
            queue("ui:menus_reset", dumps(json{{"page", rec.page_id}, {"category", c->id}}));
        }
    }
    flush_if_outermost();
}

void hook_select(void* ctrl, void* button) {
    if (!find_record(ctrl, nullptr)) { g_real_select(ctrl, button); return; }
    Record rec;
    if (!record_of(ctrl, &rec)) { g_real_select(ctrl, button); return; }
    std::uint64_t idx = 0;
    if (!button || !load_at(button, kButtonIndex, &idx) || !rec.ours_index(std::uint32_t(idx)))
        return;   // a hidden foreign entry (Credits/EULA/Privacy)
    {
        DepthGuard g;
        g_real_select(ctrl, button);
    }
    const auto* c = rec.cat_at(std::uint32_t(idx));
    if (c && c->entry_index == idx)
        queue("ui:menus_select", dumps(json{{"page", rec.page_id}, {"category", c->id}}));
    flush_if_outermost();
}

void run_request(void* ctrl) {
    Request rq;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        const ULONGLONG now = GetTickCount64();
        while (!g_reqs.empty() && now - g_reqs.front().at > kRequestTtlMs) g_reqs.pop_front();
        if (g_reqs.empty()) return;
        rq = g_reqs.front();
        g_reqs.pop_front();
    }
    if (rq.open) {
        if (depth_of(ctrl) + 1 > kMaxDepth) {
            Loader::get().log_warn("[ui-menus] cannot open '" + rq.page + "': too deep (max "
                                   + std::to_string(kMaxDepth) + ")");
            return;
        }
        std::uintptr_t settings = 0;
        if (!load_at(ctrl, kCtrlSettings, &settings) || !settings
            || !mem_readable(reinterpret_cast<void*>(settings + kSetCreditsDesc), 8)) {
            Loader::get().log_err("[ui-menus] cannot open '" + rq.page
                                  + "': settings object unreadable");
            return;
        }
        open_ours(ctrl, rq.page, rq.ctx, depth_of(ctrl) + 1);
    } else {
        Record rec;
        if (!record_of(ctrl, &rec)) return;
        if (!allow_back(rec)) return;
        close_and_prune(rec.parent);
    }
}

void hook_update(void* ctrl) {
    if (!is_tracked(ctrl)) { g_real_update(ctrl); return; }
    {
        DepthGuard g;
        g_real_update(ctrl);
    }
    std::uintptr_t child = 1;
    if (load_at(ctrl, kPageChild, &child) && child == 0 && is_host(ctrl)) {
        g_last_leaf.store(ctrl);
        g_last_tick.store(GetTickCount64());
        run_request(ctrl);
    }
    flush_if_outermost();
}

// ---- change watcher -----------------------------------------------------------

DWORD WINAPI watch_rows(LPVOID) {
    for (;;) {
        Sleep(200);
        {
            // Loader-owned values only: no game-memory read here. Pruning stays
            // in the game-thread detours.
            std::lock_guard<std::mutex> lk(g_mu);
            for (auto& rec : g_records) emit_row_changes_locked(rec);
        }
        if (g_dirty.load(std::memory_order_acquire)) flush();
    }
}

// ---- snapshot parsing -----------------------------------------------------------

std::string str_of(const json& j, const char* key) {
    auto it = j.find(key);
    return (it != j.end() && it->is_string()) ? it->get<std::string>() : std::string();
}

bool parse_snapshot(const std::string& text, PageSnap* out, std::string* why) {
    try {
        json j = json::parse(text, nullptr, false);
        if (j.is_discarded() || !j.is_object()) { *why = "snapshot is not a JSON object"; return false; }
        out->title = str_of(j, "title");
        // A missing or empty-object `categories` is an empty page: a Lua table with no
        // entries crosses the boundary as {}, not [].
        auto cats = j.find("categories");
        if (cats != j.end() && !cats->is_array() && !(cats->is_object() && cats->empty())) {
            *why = "snapshot has no categories array";
            return false;
        }
        for (const auto& cj : (cats != j.end() && cats->is_array() ? *cats : json::array())) {
            CatSnap c;
            c.id = str_of(cj, "id");
            c.label = str_of(cj, "label");
            if (c.id.empty()) { *why = "a category has no id"; return false; }
            if (c.label.empty()) c.label = c.id;
            auto h = cj.find("header");
            if (h != cj.end() && h->is_object()) {
                c.h_title = str_of(*h, "title");
                c.h_sub = str_of(*h, "subtitle");
                c.h_text = str_of(*h, "text");
            }
            auto rows = cj.find("rows");
            if (rows != cj.end() && rows->is_array()) {
                for (const auto& rj : *rows) {
                    RowSnap r;
                    r.id = str_of(rj, "id");
                    r.label = str_of(rj, "label");
                    if (r.id.empty()) { *why = "a row in '" + c.id + "' has no id"; return false; }
                    if (r.label.empty()) r.label = r.id;
                    r.readonly = rj.value("readonly", false);
                    if (r.readonly) {
                        r.choices = {str_of(rj, "readonly_text")};
                    } else {
                        auto ch = rj.find("choices");
                        if (ch != rj.end() && ch->is_array()) {
                            for (const auto& s : *ch)
                                r.choices.push_back(s.is_string() ? s.get<std::string>() : dumps(s));
                        }
                        if (r.choices.empty()) { *why = "row '" + r.id + "' has no choices"; return false; }
                        const auto n = std::int64_t(r.choices.size());
                        const std::int64_t v = std::clamp<std::int64_t>(rj.value("value", 1), 1, n);
                        const std::int64_t d = std::clamp<std::int64_t>(rj.value("default", 1), 1, n);
                        r.value = std::uint32_t(v - 1);
                        r.def = std::uint32_t(d - 1);
                    }
                    c.rows.push_back(std::move(r));
                }
            }
            out->cats.push_back(std::move(c));
        }
        return true;
    } catch (const std::exception& e) {
        *why = std::string("snapshot rejected: ") + e.what();
        return false;
    }
}

struct CallSpec { const char* what; const char* pattern; void** slot; };
struct HookSpec { const char* name; const char* pattern; void* detour; void** tramp; };

} // anonymous namespace

// --- exports -----------------------------------------------------------------------

bool book_pages_available(std::string* why) {
    if (g_armed.load(std::memory_order_acquire)) return true;
    std::lock_guard<std::mutex> lk(g_arm_mu);
    if (why) *why = g_why;
    return false;
}

// The model takes pages and entries before the hooks install: mods' init.lua
// runs before install_guarded("ui-menus"). Refused only once install failed.
bool model_accepts(std::string* why) {
    if (g_armed.load(std::memory_order_acquire)) return true;
    std::lock_guard<std::mutex> lk(g_arm_mu);
    if (g_why == kNotInstalled) return true;
    if (why) *why = g_why;
    return false;
}

bool book_pages_building(void* ctrl) {
    if (!t_building || !ctrl) return false;
    if (!t_build_ctrl) t_build_ctrl = ctrl;
    return ctrl == t_build_ctrl;
}

void book_pages_build(void* ctrl, void* page, void* parent) {
    auto& L = Loader::get();
    PageSnap snap;
    std::vector<EntrySnap> nested;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        auto it = g_pages.find(t_build_page);
        if (it == g_pages.end()) { L.log_err("[ui-menus] no snapshot for '" + t_build_page + "'"); return; }
        snap = it->second;
        for (const auto& [id, e] : g_entries)
            if (e.after == t_build_page) nested.push_back(e);
    }
    const auto c = A(ctrl);
    void* settings = nullptr;
    void* factory = nullptr;
    if (!load_at(c, kCtrlSettings, &settings) || !load_at(c, kCtrlFactory, &factory)
        || !settings || !factory
        || !mem_readable(reinterpret_cast<std::uint8_t*>(settings) + kSetStringItem, 8)) {
        L.log_err("[ui-menus] controller layout not as expected; page '" + t_build_page + "' empty");
        return;
    }
    Record rec;
    rec.ctrl = ctrl;
    rec.parent = t_build_parent;
    rec.page_id = t_build_page;
    rec.ctx = t_build_ctx;
    rec.depth = t_build_depth;

    for (const auto& cs : snap.cats) {
        Record::Cat rc;
        rc.id = cs.id;
        void* cat = add_tab(ctrl, page, parent, cs.label, kCatType, &rc.entry_index);
        void* row_parent = nullptr;
        if (!cat || !load_at(cat, kCatRowParent, &row_parent) || !row_parent) {
            L.log_err("[ui-menus] add category '" + cs.id + "' returned nothing");
            continue;
        }
        auto readonly_row = [&](const std::string& id, const std::string& label,
                                const std::string& text) {
            LiveRow* r = new_row(id, label);
            r->texts = {text};
            return spawn_row(ctrl, settings, factory, cat, row_parent, *r);
        };
        bool ok = true;
        if (!cs.h_title.empty()) ok = readonly_row("", cs.h_title, "");
        if (ok && !cs.h_sub.empty()) ok = readonly_row("", cs.h_sub, "");
        for (std::size_t at = 0; ok && !cs.h_text.empty() && at <= cs.h_text.size();) {
            const std::size_t nl = cs.h_text.find('\n', at);
            const std::string line = cs.h_text.substr(at, nl == std::string::npos ? nl : nl - at);
            ok = readonly_row("", line, "");
            if (nl == std::string::npos) break;
            at = nl + 1;
        }
        for (const auto& rs : cs.rows) {
            if (!ok) break;
            LiveRow* r = new_row(rs.id, rs.label);
            r->texts = rs.choices;
            r->editable = !rs.readonly;
            r->value = r->seen = rs.value;
            r->def = rs.def;
            if (!spawn_row(ctrl, settings, factory, cat, row_parent, *r)) { ok = false; break; }
            if (r->editable) rc.rows.push_back(r);
        }
        rec.cats.push_back(std::move(rc));
    }
    for (const auto& e : nested) {
        std::uint32_t index = 0;
        if (add_tab(ctrl, page, parent, e.title, kEntryType, &index)) rec.nested[index] = e.id;
        else L.log_err("[ui-menus] nested entry '" + e.id + "' not added");
    }
    std::lock_guard<std::mutex> lk(g_mu);
    g_ours.try_emplace(ctrl);
    g_records.push_back(std::move(rec));
}

void book_pages_add_entries(void* ctrl, void* page, void* parent) {
    if (!g_armed.load(std::memory_order_acquire) || !ctrl) return;
    auto& L = Loader::get();
    std::vector<EntrySnap> entries;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        g_settings_ctrl = ctrl;       // the host for Lua opens, with or without entries
        g_settings_idx.clear();
        g_settings_built = true;
        for (const auto& [id, e] : g_entries)
            if (e.after == "settings") entries.push_back(e);
    }
    for (const auto& e : entries) {
        std::uint32_t index = 0;
        bool unreadable = false;
        if (!add_tab(ctrl, page, parent, e.title, kEntryType, &index, &unreadable)) {
            if (unreadable) return;
            L.log_err("[ui-menus] Settings entry '" + e.id + "' not added");
            continue;
        }
        std::lock_guard<std::mutex> lk(g_mu);
        g_settings_idx[index] = e.id;
    }
}

bool book_pages_set_page(const std::string& id, const std::string& snapshot_json, std::string* why) {
    std::string w;
    if (!model_accepts(&w)) { if (why) *why = w; return false; }
    PageSnap snap;
    if (!parse_snapshot(snapshot_json, &snap, &w)) { if (why) *why = w; return false; }
    std::lock_guard<std::mutex> lk(g_mu);
    g_pages[id] = std::move(snap);
    return true;
}

void book_pages_remove_page(const std::string& id) {
    std::lock_guard<std::mutex> lk(g_mu);
    g_pages.erase(id);
}

bool book_pages_set_entry(const std::string& id, const std::string& title,
                          const std::string& page_id, const std::string& after, std::string* why) {
    std::string w;
    if (!model_accepts(&w)) { if (why) *why = w; return false; }
    if (id.empty() || after.empty()) { if (why) *why = "entry needs an id and an 'after'"; return false; }
    bool late = false;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        g_entries[id] = {id, title, page_id, after};
        late = after == "settings" && g_settings_built;
    }
    if (late) Loader::get().log("[ui-menus] entry " + id +
                                " registered after Settings was built: shows next launch");
    return true;
}

void book_pages_remove_entry(const std::string& id) {
    std::lock_guard<std::mutex> lk(g_mu);
    g_entries.erase(id);
}

bool book_pages_open(const std::string& page_id, const std::string* ctx_json, std::string* why) {
    std::string w;
    if (!book_pages_available(&w)) { if (why) *why = w; return false; }
    Request rq;
    rq.page = page_id;
    if (ctx_json) {
        json j = json::parse(*ctx_json, nullptr, false);
        if (j.is_discarded()) { if (why) *why = "ctx is not valid JSON"; return false; }
        rq.ctx = dumps(j);
    }
    rq.at = GetTickCount64();
    if (!g_last_leaf.load() || rq.at - g_last_tick.load() > kLeafFreshMs) {
        if (why) *why = "no Settings or R.ui.menus page is open";
        return false;
    }
    {
        // Loader-side depth only: the current leaf's record, else the Settings page (0).
        const int d = depth_no_prune(g_last_leaf.load());
        if (d + 1 > kMaxDepth) {
            if (why) *why = "too deep (max " + std::to_string(kMaxDepth) + ")";
            return false;
        }
    }
    std::lock_guard<std::mutex> lk(g_mu);
    if (!g_pages.count(page_id)) { if (why) *why = "unknown page"; return false; }
    g_reqs.push_back(std::move(rq));
    return true;
}

bool book_pages_back(std::string* why) {
    std::string w;
    if (!book_pages_available(&w)) { if (why) *why = w; return false; }
    void* leaf = g_last_leaf.load();
    const ULONGLONG now = GetTickCount64();
    if (!leaf || now - g_last_tick.load() > kLeafFreshMs || !find_record(leaf, nullptr)) {
        if (why) *why = "no R.ui.menus page is open";
        return false;
    }
    Request rq;
    rq.open = false;
    rq.at = now;
    std::lock_guard<std::mutex> lk(g_mu);
    g_reqs.push_back(std::move(rq));
    return true;
}

bool book_pages_current(std::string* page, std::string* ctx_json, int* depth) {
    void* leaf = g_last_leaf.load();
    if (!g_armed.load() || !leaf || GetTickCount64() - g_last_tick.load() > kLeafFreshMs) return false;
    Record rec;
    if (!find_record(leaf, &rec)) return false;
    if (page) *page = rec.page_id;
    if (ctx_json) *ctx_json = rec.ctx;
    if (depth) *depth = rec.depth;
    return true;
}

void book_pages_veto_back() { g_veto.store(true); }

bool install_book_page_hooks() {
    auto& L = Loader::get();
    std::lock_guard<std::mutex> lk(g_arm_mu);
    auto fail = [&](const std::string& why) {
        g_why = why;
        L.log_err("[ui-menus] " + why);
        return false;
    };
    if (flag_enabled("RSMM_DISABLE_UI_MENUS")) {
        g_why = "disabled by RSMM_DISABLE_UI_MENUS";
        L.log("[ui-menus] off (RSMM_DISABLE_UI_MENUS is set)");
        return false;
    }
    // Our pages are built from the Settings build hook (dllmain installs native-menu first).
    if (!settings_build_hooked())
        return fail("needs the Settings build hook (native-menu is off or failed to install)");
    if (!fn_resolver_init()) return fail("fn_resolver_init failed");
    const CallSpec calls[] = {
        {"set visible", Sym::GameUi_SetVisible_Pattern, reinterpret_cast<void**>(&g_set_visible)},
        {"book mode", Sym::BookMenu_GetMode_Pattern, reinterpret_cast<void**>(&g_get_mode)},
    };
    for (const auto& c : calls)
        if (!resolve_checked("ui-menus", c.what, c.pattern, c.slot))
            return fail("a call target did not resolve");
    if (!resolve_menu_fns("ui-menus", g_menu)) return fail("a call target did not resolve");

    const HookSpec hooks[] = {
        {"BookPage_OpenChild", Sym::BookPage_OpenChild_Pattern,
         reinterpret_cast<void*>(&hook_open_child), reinterpret_cast<void**>(&g_real_open)},
        {"BookPage_CloseChild", Sym::BookPage_CloseChild_Pattern,
         reinterpret_cast<void*>(&hook_close_child), reinterpret_cast<void**>(&g_real_close)},
        {"BookMenu_OnBackPressed", Sym::BookMenu_OnBackPressed_Pattern,
         reinterpret_cast<void*>(&hook_back), reinterpret_cast<void**>(&g_real_back)},
        {"OptionsMenu_ResetPressed", Sym::OptionsMenu_ResetPressed_Pattern,
         reinterpret_cast<void*>(&hook_reset), reinterpret_cast<void**>(&g_real_reset)},
        {"OptionsMenu_SelectCategory", Sym::OptionsMenu_SelectCategory_Pattern,
         reinterpret_cast<void*>(&hook_select), reinterpret_cast<void**>(&g_real_select)},
        {"OptionsMenu_Update", Sym::OptionsMenu_Update_Pattern,
         reinterpret_cast<void*>(&hook_update), reinterpret_cast<void**>(&g_real_update)},
        {"OptionsMenu_BuildGraphics", Sym::OptionsMenu_BuildGraphics_Pattern,
         reinterpret_cast<void*>(&hook_build_graphics), reinterpret_cast<void**>(&g_real_build_gfx)},
        {"OptionsMenu_BuildAudio", Sym::OptionsMenu_BuildAudio_Pattern,
         reinterpret_cast<void*>(&hook_build_audio), reinterpret_cast<void**>(&g_real_build_audio)},
        {"OptionsMenu_Teardown", Sym::OptionsMenu_Teardown_Pattern,
         reinterpret_cast<void*>(&hook_teardown), reinterpret_cast<void**>(&g_real_teardown)},
    };
    std::vector<std::uintptr_t> vas;   // installed prefix, for the rollback
    bool ok = true;
    for (const auto& h : hooks) {
        std::uintptr_t va = 0;
        if (!hook_install("ui-menus", h.name, h.pattern, h.detour, h.tramp, &va)) { ok = false; break; }
        vas.push_back(va);
    }
    if (!ok) {
        for (std::uintptr_t va : vas) hook_remove(va);
        return fail("could not install every detour; R.ui.menus is off");
    }
    if (HANDLE t = CreateThread(nullptr, 0, watch_rows, nullptr, 0, nullptr)) CloseHandle(t);
    g_armed.store(true, std::memory_order_release);
    L.log("[ui-menus] armed");
    return true;
}

} // namespace rsmm
