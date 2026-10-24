// Native mod menu — see hook_settings_menu.h for the why.
//
// Every engine call below mirrors what the vanilla builder FUN_1403f4870 does
// for one of its multi-choice rows, in the same order (RE notes on each symbol
// in data/symbols.json, category "ui"):
//   cat  = OptionsMenu_AddCategory(ctrl, page, parent, &title, type)
//   row  = OptionsMenu_SpawnMultiChoice(ctrl+0x228, settings+0x3a8, cat+0x08)
//   OptionsMenu_AppendRow(&ctrl, cat, row)
//   row+0x98 = &value; labels -> row+0xa0; row+0xb0 = null (not locked)
//   OptionsMenuElement_SetTitle(row, &text)   // re-reads row+0x98
// Strings are passed with the 0x80000000 "literal" bit, which the engine
// aliases instead of copying, so every string lives for the whole session.
//
// The tab holds, per installed mod, an Off/On row and
// one row per bool / enum / int / float field of its config_schema.toml. The
// game writes the chosen index straight into our memory on the main thread; a
// watcher thread notices and persists it:
//   * On/Off -> <game>/mods/_menu_requests.json, which `rsmm apply` carries
//     into the library manifest before the next launch (the loader cannot see
//     the library);
//   * a field -> the mod's config.toml, whose mtime the Lua side already polls
//     to fire R.config.on_change.
// The page is built once at boot, so the rows are too.

#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <string>
#include <vector>

#include "json.hpp"   // single-header nlohmann::json (vendored)
#include "toml.hpp"   // single-header toml++ (vendored)

#include "loader.h"
#include "mem_safe.h"
#include "fn_resolver.h"
#include "hook_util.h"
#include "symbols.gen.h"
#include "symbols_api.gen.h"
#include "hook_settings_menu.h"

namespace rsmm {
namespace {

namespace fs = std::filesystem;

struct OcStr {           // oCString: {char*, u32 len | 0x80000000 literal, u32 cap}
    const char* p;
    std::uint32_t len;
    std::uint32_t cap;
};
constexpr std::uint32_t kLiteral = 0x80000000u;
OcStr lit(const std::string& s) { return {s.c_str(), std::uint32_t(s.size()) | kLiteral, 0}; }

// Offsets read from the Settings build (b9c3), see the symbol notes.
constexpr std::uintptr_t kCtrlSettings   = 0x10;   // controller -> settings object
constexpr std::uintptr_t kCtrlFactory    = 0x228;  // controller -> element factory
constexpr std::uintptr_t kSetStringItem  = 0x3a8;  // settings: Option_StringItem template
constexpr std::uintptr_t kCatRowParent   = 0x08;
constexpr std::uintptr_t kRowValue       = 0x98;
constexpr std::uintptr_t kRowLabels      = 0xa0;
constexpr std::uintptr_t kRowLocked      = 0xb0;
constexpr std::uint32_t  kCategoryType   = 5;      // what the plain multi-choice tab uses
constexpr std::size_t    kMaxTitle       = 32;     // longer runs into the row's arrows
constexpr int            kSteps          = 20;     // number fields: steps between min and max

const char* kMenuRequests = "_menu_requests.json";  // read by rsmm.cli.cmd_mods

// --- model -------------------------------------------------------------------

struct Value {
    enum Kind { None, Bool, Int, Float, Str } kind = None;
    bool b = false;
    std::int64_t i = 0;
    double f = 0;
    std::string s;
    double num() const { return kind == Int ? double(i) : kind == Float ? f : 0.0; }
    bool same(const Value& o) const {
        if (kind == Str || o.kind == Str) return kind == o.kind && s == o.s;
        if (kind == Bool || o.kind == Bool) return kind == o.kind && b == o.b;
        return std::fabs(num() - o.num()) < 1e-6;
    }
};

struct ModInfo {
    std::string id, name;
    fs::path root;
    bool enabled = false;    // what this launch runs with
    bool wanted = false;     // what the menu asks for next launch
    std::map<std::string, Value> values;   // config.toml [config]
};

struct Row {
    bool toggle = false;
    std::size_t mod = 0;
    std::string key;                       // config field (not a toggle)
    std::string title;
    std::vector<std::string> texts;        // label storage
    std::vector<OcStr> labels;
    std::vector<Value> options;            // value per label (not a toggle)
    std::uint32_t value = 0;               // the game writes this
    std::uint32_t seen = 0;
};

std::vector<ModInfo> g_mods;
std::deque<Row> g_rows;      // deque: rows never move, the game holds &value
std::once_flag g_model_once;

const std::string kTabTitle = "Mods";

Value from_node(const toml::node& n) {
    Value v;
    if (auto b = n.as_boolean()) { v.kind = Value::Bool; v.b = **b; }
    else if (auto i = n.as_integer()) { v.kind = Value::Int; v.i = **i; }
    else if (auto f = n.as_floating_point()) { v.kind = Value::Float; v.f = **f; }
    else if (auto s = n.as_string()) { v.kind = Value::Str; v.s = **s; }
    return v;
}

std::string clip(std::string s) {
    if (s.size() > kMaxTitle) s = s.substr(0, kMaxTitle - 2) + "..";
    return s;
}

void load_values(ModInfo& m) {
    const fs::path p = m.root / "config.toml";
    std::error_code ec;
    if (!fs::exists(p, ec)) return;
    try {
        toml::table doc = toml::parse_file(p.string());
        const toml::table* section = doc["config"].as_table();
        if (!section) section = &doc;
        for (auto&& [key, node] : *section) {
            const Value v = from_node(node);
            if (v.kind != Value::None) m.values[std::string(key.str())] = v;
        }
    } catch (const std::exception& e) {
        Loader::get().log_warn("[native-menu] " + m.id + ": config.toml unreadable: " + e.what());
    }
}

// The choices a field offers, as values. Numbers step from min to max (every
// integer when the span is small); the current value is kept as a choice so
// opening the menu never changes it.
// ponytail: stepped choices stand in for the game's slider row (Option_GaugeItem),
// which is not RE'd yet.
std::vector<Value> options_for(const toml::table& t, const std::string& type) {
    std::vector<Value> out;
    if (type == "bool") {
        Value off, on;
        off.kind = on.kind = Value::Bool;
        on.b = true;
        return {off, on};
    }
    if (type == "enum") {
        const toml::array* c = t["choices"].as_array();
        if (!c) c = t["values"].as_array();
        if (c) {
            for (auto&& e : *c) {
                if (auto s = e.value<std::string>()) {
                    Value v; v.kind = Value::Str; v.s = *s; out.push_back(v);
                }
            }
        }
        return out;
    }
    if (type != "int" && type != "float") return out;
    const auto lo = t["min"].value<double>();
    const auto hi = t["max"].value<double>();
    if (!lo || !hi || *hi <= *lo) return out;
    const bool integer = type == "int";
    const int n = integer && *hi - *lo <= 40 ? int(*hi - *lo) : kSteps;
    for (int k = 0; k <= n; ++k) {
        Value v;
        const double d = *lo + (*hi - *lo) * k / n;
        if (integer) { v.kind = Value::Int; v.i = std::llround(d); }
        else { v.kind = Value::Float; v.f = d; }
        if (out.empty() || !out.back().same(v)) out.push_back(v);
    }
    return out;
}

std::string label_of(const Value& v) {
    char b[32];
    switch (v.kind) {
        case Value::Bool: return v.b ? "On" : "Off";
        case Value::Int: std::snprintf(b, sizeof(b), "%lld", static_cast<long long>(v.i)); return b;
        case Value::Float: std::snprintf(b, sizeof(b), "%.4g", v.f); return b;
        case Value::Str: return v.s;
        case Value::None: break;
    }
    return "?";
}

void finish_labels(Row& r) {
    r.labels.clear();
    for (const auto& s : r.texts) r.labels.push_back(lit(s));
}

void add_setting_rows(std::size_t mi) {
    ModInfo& m = g_mods[mi];
    const fs::path p = m.root / "config_schema.toml";
    std::error_code ec;
    if (!fs::exists(p, ec)) return;
    toml::table doc;
    try {
        doc = toml::parse_file(p.string());
    } catch (const std::exception& e) {
        Loader::get().log_warn("[native-menu] " + m.id + ": config_schema.toml unreadable: "
                               + e.what());
        return;
    }
    const toml::table* fields = doc["fields"].as_table();
    if (!fields) return;
    // toml++ tables are key-sorted; the author's order is the file's order.
    std::vector<std::pair<std::uint32_t, std::string>> order;
    for (auto&& [key, node] : *fields) {
        if (node.is_table()) order.emplace_back(node.source().begin.line, std::string(key.str()));
    }
    std::sort(order.begin(), order.end());
    for (const auto& [line, key] : order) {
        const toml::table& t = *fields->get(key)->as_table();
        const std::string type = t["type"].value_or(std::string("string"));
        std::vector<Value> opts = options_for(t, type);
        if (opts.empty()) continue;   // string / multiselect / item-grid: the desktop app's job
        Value cur;
        if (auto it = m.values.find(key); it != m.values.end()) cur = it->second;
        else if (const toml::node* d = t.get("default")) cur = from_node(*d);
        std::uint32_t idx = 0;
        bool found = false;
        for (std::uint32_t k = 0; k < opts.size(); ++k) {
            if (opts[k].same(cur)) { idx = k; found = true; break; }
        }
        if (!found && (cur.kind == Value::Int || cur.kind == Value::Float)) {
            auto at = std::find_if(opts.begin(), opts.end(),
                                   [&](const Value& o) { return o.num() > cur.num(); });
            idx = std::uint32_t(at - opts.begin());
            opts.insert(at, cur);
        }
        Row& r = g_rows.emplace_back();
        r.mod = mi;
        r.key = key;
        r.title = clip("- " + t["label"].value_or(key));
        r.options = std::move(opts);
        for (const auto& o : r.options) r.texts.push_back(label_of(o));
        finish_labels(r);
        r.value = r.seen = idx;
    }
}

void build_model() {
    std::map<std::string, bool> requested;
    try {
        std::ifstream f(Loader::get().mods_dir() / kMenuRequests);
        if (f) {
            nlohmann::json j;
            f >> j;
            const nlohmann::json enable = j.value("enable", nlohmann::json::object());
            for (auto& [id, on] : enable.items()) {
                if (on.is_boolean()) requested[id] = on.get<bool>();
            }
        }
    } catch (const std::exception&) {
    }
    for (const auto& src : Loader::get().mods()) {
        ModInfo m;
        m.id = src.id;
        m.name = src.name.empty() ? src.id : src.name;
        m.root = src.root;
        m.enabled = src.enabled;
        auto it = requested.find(m.id);
        m.wanted = it != requested.end() ? it->second : m.enabled;
        load_values(m);
        g_mods.push_back(std::move(m));
    }
    std::sort(g_mods.begin(), g_mods.end(),
              [](const ModInfo& a, const ModInfo& b) { return a.name < b.name; });
    for (std::size_t i = 0; i < g_mods.size(); ++i) {
        Row& r = g_rows.emplace_back();
        r.toggle = true;
        r.mod = i;
        r.title = clip(g_mods[i].name);
        r.texts = {"Off", "On"};
        // The state that is NOT running now says so, so On/Off never claims a
        // change took effect before the restart that applies it.
        r.texts[g_mods[i].enabled ? 0 : 1] += " (next launch)";
        finish_labels(r);
        r.value = r.seen = g_mods[i].wanted ? 1 : 0;
        add_setting_rows(i);   // a disabled mod's config still applies once it is on
    }
    Loader::get().log("[native-menu] " + std::to_string(g_mods.size()) + " mod(s), "
                      + std::to_string(g_rows.size()) + " row(s)");
}

// --- persistence (watcher thread) ---------------------------------------------

void write_requests() {
    nlohmann::json enable = nlohmann::json::object();
    for (const auto& m : g_mods) {
        if (m.wanted != m.enabled) enable[m.id] = m.wanted;
    }
    const fs::path dst = Loader::get().mods_dir() / kMenuRequests;
    std::error_code ec;
    if (enable.empty()) { fs::remove(dst, ec); return; }
    const fs::path tmp = dst.string() + ".tmp";
    {
        std::ofstream f(tmp, std::ios::trunc);
        if (!f) return;
        f << nlohmann::json{{"enable", enable}}.dump(2) << "\n";
    }
    fs::rename(tmp, dst, ec);
    if (ec) fs::remove(tmp, ec);
}

// Same shape the loader's config_write_file produces: a `[config]` table,
// temp file + rename. Keys the menu does not know are kept.
void write_values(const ModInfo& m) {
    const fs::path dst = m.root / "config.toml";
    const fs::path tmp = m.root / "config.toml.tmp";
    toml::table doc;
    std::error_code ec;
    if (fs::exists(dst, ec)) {
        try { doc = toml::parse_file(dst.string()); } catch (const std::exception&) {}
    }
    toml::table section;
    if (const toml::table* c = doc["config"].as_table()) {
        section = *c;
    } else {
        for (auto&& [k, n] : doc) {   // a flat file: keep its values
            if (!n.is_table()) section.insert(k, n);
        }
    }
    for (const auto& [key, v] : m.values) {
        switch (v.kind) {
            case Value::Bool: section.insert_or_assign(key, v.b); break;
            case Value::Int: section.insert_or_assign(key, v.i); break;
            case Value::Float: section.insert_or_assign(key, v.f); break;
            case Value::Str: section.insert_or_assign(key, v.s); break;
            case Value::None: break;
        }
    }
    toml::table out;
    out.insert("config", std::move(section));
    {
        std::ofstream f(tmp, std::ios::trunc);
        if (!f) return;
        f << out << "\n";
    }
    fs::rename(tmp, dst, ec);
    if (ec) {
        fs::remove(tmp, ec);
        Loader::get().log_warn("[native-menu] " + m.id + ": could not write config.toml");
    }
}

// ponytail: polling, because the row writes our uint32_t directly and calls
// nothing we could hook cheaply; 200 ms is below what a click can notice.
DWORD WINAPI watch_rows(LPVOID) {
    for (;;) {
        Sleep(200);
        for (Row& r : g_rows) {
            const std::uint32_t now = *static_cast<volatile std::uint32_t*>(&r.value);
            if (now == r.seen) continue;
            r.seen = now;
            ModInfo& m = g_mods[r.mod];
            if (r.toggle) {
                m.wanted = now != 0;
                write_requests();
                Loader::get().log("[native-menu] " + m.id + " -> "
                                  + (m.wanted ? "on" : "off") + " next launch");
            } else if (now < r.options.size()) {
                m.values[r.key] = r.options[now];
                write_values(m);
                Loader::get().log("[native-menu] " + m.id + "." + r.key + " = "
                                  + r.texts[now]);
            }
        }
    }
}

// --- engine side ----------------------------------------------------------------

using build_fn = void (*)(void*, void*, void*);
build_fn g_real_build = nullptr;

engine::OptionsMenu_AddCategory_fn      g_add_category = nullptr;
engine::OptionsMenu_SpawnMultiChoice_fn g_spawn_row    = nullptr;
engine::OptionsMenu_AppendRow_fn        g_append_row   = nullptr;
engine::OptionsMenuElement_SetTitle_fn  g_set_title    = nullptr;
engine::StringVector_AssignFromArray_fn g_set_labels   = nullptr;
engine::OptionsMenu_SelectCategory_fn   g_select_tab   = nullptr;

// Where our tab lives, for the pause menu's Mods button. An index, not the
// entry: the build adds more tabs after ours, which can move the vector.
constexpr std::uintptr_t kCtrlTabs     = 0x208;   // tab entries, stride 0x48
constexpr std::uintptr_t kCtrlTabCount = 0x210;
constexpr std::uintptr_t kTabStride    = 0x48;
constexpr std::uintptr_t kTabButton    = 0x10;
void* g_ctrl = nullptr;
std::uint32_t g_tab_index = UINT32_MAX;

void select_mods_tab() {
    auto& L = Loader::get();
    const auto c = reinterpret_cast<std::uintptr_t>(g_ctrl);
    std::uintptr_t tabs = 0;
    std::uint32_t count = 0;
    void* button = nullptr;
    if (!g_ctrl || !g_select_tab || !mem_load(c + kCtrlTabs, &tabs)
        || !mem_load(c + kCtrlTabCount, &count) || g_tab_index >= count
        || !mem_load(tabs + g_tab_index * kTabStride + kTabButton, &button) || !button) {
        L.log_warn("[native-menu] Mods tab not found; Settings opened on its first tab");
        return;
    }
    g_select_tab(g_ctrl, button);
}

void add_mods_tab(void* ctrl, void* page, void* parent) {
    auto& L = Loader::get();
    const auto c = reinterpret_cast<std::uintptr_t>(ctrl);
    void* settings = nullptr;
    void* factory = nullptr;
    if (!mem_load(c + kCtrlSettings, &settings) || !mem_load(c + kCtrlFactory, &factory)
        || !settings || !factory
        || !mem_readable(reinterpret_cast<std::uint8_t*>(settings) + kSetStringItem, 8)) {
        L.log_err("[native-menu] controller layout not as expected; no Mods tab");
        return;
    }
    std::call_once(g_model_once, [] {
        build_model();
        if (HANDLE t = CreateThread(nullptr, 0, watch_rows, nullptr, 0, nullptr)) CloseHandle(t);
    });
    if (g_rows.empty()) return;
    std::uint32_t index = 0;
    if (mem_load(c + kCtrlTabCount, &index)) {
        g_ctrl = ctrl;
        g_tab_index = index;    // AddCategory stamps this on the tab's button
    }
    OcStr tab = lit(kTabTitle);
    void* cat = g_add_category(ctrl, page, parent, &tab, kCategoryType);
    void* row_parent = nullptr;
    if (!cat || !mem_load(reinterpret_cast<std::uintptr_t>(cat) + kCatRowParent, &row_parent)
        || !row_parent) {
        L.log_err("[native-menu] add category returned nothing; no rows");
        return;
    }
    void* ctx = ctrl;
    for (Row& r : g_rows) {
        void* row = g_spawn_row(factory, reinterpret_cast<std::uint8_t*>(settings) + kSetStringItem,
                                row_parent);
        if (!row || !mem_writable(reinterpret_cast<std::uint8_t*>(row) + kRowValue, 0x20)) {
            L.log_err("[native-menu] row spawn failed at '" + r.title + "'");
            return;
        }
        g_append_row(&ctx, cat, row);
        auto* p = reinterpret_cast<std::uint8_t*>(row);
        *reinterpret_cast<std::uint32_t**>(p + kRowValue) = &r.value;
        g_set_labels(p + kRowLabels, r.labels.data(), std::uint32_t(r.labels.size()));
        *reinterpret_cast<void**>(p + kRowLocked) = nullptr;
        OcStr title = lit(r.title);   // the label aliases r.title, which g_rows keeps alive
        g_set_title(row, &title);
    }
    L.log("[native-menu] Mods tab built with " + std::to_string(g_rows.size()) + " row(s)");
}

void hook_build(void* ctrl, void* page, void* parent) {
    g_real_build(ctrl, page, parent);
    add_mods_tab(ctrl, page, parent);
}

// --- the pause menu's Mods button ----------------------------------------------
//
// rsmm.engine.escape_menu adds a pause menu item naming the pause controller
// and kModsAction. The controller's action lookup (vtable slot 19) only knows
// its six keys, so we answer ours: the Settings callback, its thunk swapped
// for one that runs it and then selects the Mods tab. A callback is
// {this, 0, thunk}; the game calls thunk(arg, &callback).

constexpr std::uint32_t kModsAction     = 0x52534D4D;   // = escape_menu.MODS_ACTION
constexpr std::uint32_t kSettingsAction = 0x1B4AB3B7;

using thunk_fn = void (*)(void*, void*);
thunk_fn g_settings_thunk = nullptr;

void mods_thunk(void* arg, void* callback) {
    if (g_settings_thunk) g_settings_thunk(arg, callback);
    select_mods_tab();
}

using get_callback_fn = void* (*)(void*, void**, std::uint64_t, void*);
get_callback_fn g_real_get_callback = nullptr;

void* hook_get_callback(void* self, void** out, std::uint64_t key, void* extra) {
    if (static_cast<std::uint32_t>(key) != kModsAction || !out) {
        return g_real_get_callback(self, out, key, extra);
    }
    void* r = g_real_get_callback(self, out, kSettingsAction, extra);
    if (out[2]) {
        g_settings_thunk = reinterpret_cast<thunk_fn>(out[2]);
        out[2] = reinterpret_cast<void*>(&mods_thunk);
    }
    return r;
}

template <typename F>
bool need(const char* what, const char* pattern, F* out) {
    return resolve_checked("native-menu", what, pattern, reinterpret_cast<void**>(out));
}

} // anonymous namespace

bool install_settings_menu_hooks() {
    if (flag_enabled("RSMM_DISABLE_NATIVE_MENU")) {
        Loader::get().log("[native-menu] off (RSMM_DISABLE_NATIVE_MENU is set)");
        return false;
    }
    if (!fn_resolver_init()) {
        Loader::get().log_err("[native-menu] fn_resolver_init failed");
        return false;
    }
    if (!need("add category", Sym::OptionsMenu_AddCategory_Pattern, &g_add_category)
        || !need("spawn row", Sym::OptionsMenu_SpawnMultiChoice_Pattern, &g_spawn_row)
        || !need("append row", Sym::OptionsMenu_AppendRow_Pattern, &g_append_row)
        || !need("set title", Sym::OptionsMenuElement_SetTitle_Pattern, &g_set_title)
        || !need("set labels", Sym::StringVector_AssignFromArray_Pattern, &g_set_labels)) {
        return false;
    }
    if (!hook_install("native-menu", "last Settings tab builder",
                      Sym::OptionsMenu_BuildLastCategory_Pattern,
                      reinterpret_cast<void*>(&hook_build),
                      reinterpret_cast<void**>(&g_real_build))) {
        return false;
    }
    // The pause menu button is extra: without it the tab still works.
    if (need("select tab", Sym::OptionsMenu_SelectCategory_Pattern, &g_select_tab)
        && hook_install("native-menu", "pause menu action lookup",
                        Sym::PauseMenu_GetActionCallback_Pattern,
                        reinterpret_cast<void*>(&hook_get_callback),
                        reinterpret_cast<void**>(&g_real_get_callback))) {
        Loader::get().log("[native-menu] pause menu Mods button armed");
    }
    Loader::get().log("[native-menu] armed: open Settings for the Mods tab");
    return true;
}

} // namespace rsmm
