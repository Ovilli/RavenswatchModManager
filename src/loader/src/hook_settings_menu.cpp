// Native mod menu model + the Settings hooks — see hook_settings_menu.h for the why.
//
// The Mods page itself is drawn by the book-page machinery (hook_book_pages.cpp)
// from a page registered in Lua (rsmm/mods_menu.lua, in the loader-owned state).
// This file keeps what only the loader can do:
//   * the model: every installed mod's Off/On state plus one row per
//     config_schema.toml field, handed to Lua as JSON (mods_menu_model_json);
//   * mods_menu_set: Lua reports a change, the model is updated under a lock
//     (no file IO: it can run on the game thread);
//   * persistence, on a watcher thread that notices dirty state every 200 ms:
//       - On/Off -> <game>/mods/_menu_requests.json, which `rsmm apply` carries
//         into the library manifest before the next launch (the loader cannot
//         see the library);
//       - a field -> the mod's config.toml, whose mtime the Lua side already
//         polls to fire R.config.on_change;
//   * the OptionsMenu_BuildLastCategory detour that lets the book pages add
//     their entries and build their categories after the vanilla builder;
//   * the pause menu's Mods button, which opens the page.
// The model is read from disk once; it reflects every set made this session.

#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <string>
#include <vector>

#include "json.hpp"   // single-header nlohmann::json (vendored)
#include "toml.hpp"   // single-header toml++ (vendored)

#include "loader.h"
#include "fn_resolver.h"
#include "hook_util.h"
#include "symbols.gen.h"
#include "hook_settings_menu.h"
#include "hook_book_pages.h"

namespace rsmm {

namespace {

namespace fs = std::filesystem;

constexpr int         kSteps = 20;     // number fields: steps between min and max

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

struct Field {
    std::string id, label;
    bool readonly = false;
    std::vector<Value> options;            // value per choice
    std::vector<std::string> texts;        // label per choice
    std::size_t value = 0;                 // 0-based
    std::size_t def = 0;
};

struct ModInfo {
    std::string id, name, version, author, description;
    fs::path root;
    bool enabled = false;    // what this launch runs with
    bool wanted = false;     // what the menu asks for next launch
    std::map<std::string, Value> values;   // config.toml [config]
    std::vector<Field> fields;
    bool values_dirty = false;
};

std::mutex g_mu;                 // guards g_mods, g_requests_dirty, g_pending_logs
std::vector<ModInfo> g_mods;
bool g_requests_dirty = false;
std::vector<std::string> g_pending_logs;
std::once_flag g_model_once;
std::atomic<bool> g_off{false};  // the native menu failed to install

Value from_node(const toml::node& n) {
    Value v;
    if (auto b = n.as_boolean()) { v.kind = Value::Bool; v.b = **b; }
    else if (auto i = n.as_integer()) { v.kind = Value::Int; v.i = **i; }
    else if (auto f = n.as_floating_point()) { v.kind = Value::Float; v.f = **f; }
    else if (auto s = n.as_string()) { v.kind = Value::Str; v.s = **s; }
    return v;
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

// A numeric value that is not one of the stepped choices is kept as one, in
// sorted position, so opening the menu never changes it.
void ensure_choice(std::vector<Value>& opts, const Value& v) {
    if (v.kind != Value::Int && v.kind != Value::Float) return;
    for (const auto& o : opts) if (o.same(v)) return;
    auto at = std::find_if(opts.begin(), opts.end(),
                           [&](const Value& o) { return o.num() > v.num(); });
    opts.insert(at, v);
}

// Index of `v` in `opts`, or 0 when it is not a choice.
std::size_t find_choice(const std::vector<Value>& opts, const Value& v) {
    for (std::size_t k = 0; k < opts.size(); ++k) {
        if (opts[k].same(v)) return k;
    }
    return 0;
}

void add_setting_rows(ModInfo& m) {
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
        Field f;
        f.id = key;
        f.label = t["label"].value_or(key);
        std::vector<Value> opts = options_for(t, type);
        if (opts.empty()) {   // string / multiselect / item-grid: the desktop app's job
            f.readonly = true;
            m.fields.push_back(std::move(f));
            continue;
        }
        Value cur, def;
        bool has_def = false;
        if (const toml::node* d = t.get("default")) { def = from_node(*d); has_def = true; }
        if (auto it = m.values.find(key); it != m.values.end()) cur = it->second;
        else if (has_def) cur = def;
        if (!has_def) def = cur;
        ensure_choice(opts, cur);
        ensure_choice(opts, def);
        f.value = find_choice(opts, cur);
        f.def = find_choice(opts, def);
        f.options = std::move(opts);
        for (const auto& o : f.options) f.texts.push_back(label_of(o));
        m.fields.push_back(std::move(f));
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
    std::vector<ModInfo> mods;
    for (const auto& src : Loader::get().mods()) {
        ModInfo m;
        m.id = src.id;
        m.name = src.name.empty() ? src.id : src.name;
        m.version = src.version;
        m.author = src.author;
        m.description = src.description;
        m.root = src.root;
        m.enabled = src.enabled;
        auto it = requested.find(m.id);
        m.wanted = it != requested.end() ? it->second : m.enabled;
        load_values(m);
        add_setting_rows(m);   // a disabled mod's config still applies once it is on
        mods.push_back(std::move(m));
    }
    std::sort(mods.begin(), mods.end(),
              [](const ModInfo& a, const ModInfo& b) { return a.name < b.name; });
    std::size_t rows = 0;
    for (const auto& m : mods) rows += m.fields.size() + 1;
    Loader::get().log("[native-menu] " + std::to_string(mods.size()) + " mod(s), "
                      + std::to_string(rows) + " row(s)");
    std::lock_guard<std::mutex> lk(g_mu);
    g_mods = std::move(mods);
}

// --- persistence (watcher thread) ---------------------------------------------

struct RequestRow { std::string id; bool enabled, wanted; };

void write_requests(const std::vector<RequestRow>& rows) {
    nlohmann::json enable = nlohmann::json::object();
    for (const auto& m : rows) {
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

struct ValuesCopy {
    std::string id;
    fs::path root;
    std::map<std::string, Value> values;
};

// Same shape the loader's config_write_file produces: a `[config]` table,
// temp file + rename. Keys the menu does not know are kept.
void write_values(const ValuesCopy& m) {
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

// ponytail: polling, because mods_menu_set must not do file IO (it can run on
// the game thread); 200 ms is below what a click can notice.
DWORD WINAPI watch_dirty(LPVOID) {
    for (;;) {
        Sleep(200);
        std::vector<RequestRow> requests;
        bool write_req = false;
        std::vector<ValuesCopy> values;
        std::vector<std::string> logs;
        {
            std::lock_guard<std::mutex> lk(g_mu);
            if (g_requests_dirty) {
                g_requests_dirty = false;
                write_req = true;
                for (const auto& m : g_mods) requests.push_back({m.id, m.enabled, m.wanted});
            }
            for (auto& m : g_mods) {
                if (!m.values_dirty) continue;
                m.values_dirty = false;
                values.push_back({m.id, m.root, m.values});
            }
            logs.swap(g_pending_logs);
        }
        if (write_req) write_requests(requests);
        for (const auto& v : values) write_values(v);
        for (const auto& l : logs) Loader::get().log(l);
    }
}

void ensure_model() {
    std::call_once(g_model_once, [] {
        build_model();
        if (HANDLE t = CreateThread(nullptr, 0, watch_dirty, nullptr, 0, nullptr)) CloseHandle(t);
    });
}

// --- engine side ----------------------------------------------------------------

using build_fn = void (*)(void*, void*, void*);
build_fn g_real_build = nullptr;

void hook_build(void* ctrl, void* page, void* parent) {
    g_real_build(ctrl, page, parent);
    if (book_pages_building(ctrl)) {   // one of our pages
        book_pages_build(ctrl, page, parent);
        return;
    }
    book_pages_add_entries(ctrl, page, parent);
}

// --- the pause menu's Mods button ----------------------------------------------
//
// rsmm.engine.escape_menu adds a pause menu item naming the pause controller
// and kModsAction. The controller's action lookup (vtable slot 19) only knows
// its six keys, so we answer ours: the Settings callback, its thunk swapped
// for one that runs it and then opens the Mods page. A callback is
// {this, 0, thunk}; the game calls thunk(arg, &callback).

constexpr std::uint32_t kModsAction     = 0x52534D4D;   // = escape_menu.MODS_ACTION
constexpr std::uint32_t kSettingsAction = 0x1B4AB3B7;

using thunk_fn = void (*)(void*, void*);
thunk_fn g_settings_thunk = nullptr;

void mods_thunk(void* arg, void* callback) {
    if (g_settings_thunk) g_settings_thunk(arg, callback);
    std::string why;
    if (!book_pages_open(kModsPageId, nullptr, &why, false)) {
        Loader::get().log_warn("[native-menu] Mods page not opened: " + why);
    }
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

std::atomic<bool> g_build_hooked{false};

} // anonymous namespace

bool settings_build_hooked() { return g_build_hooked.load(std::memory_order_acquire); }

// --- Lua-facing model ------------------------------------------------------------

bool mods_menu_model_json(std::string* out, std::string* why) {
    if (flag_enabled("RSMM_DISABLE_NATIVE_MENU") || g_off.load()) {
        if (why) *why = "native menu is off";
        return false;
    }
    ensure_model();
    nlohmann::json mods = nlohmann::json::array();
    {
        std::lock_guard<std::mutex> lk(g_mu);
        for (const auto& m : g_mods) {
            nlohmann::json rows = nlohmann::json::array();
            // The state that is NOT running now says so, so On/Off never claims a
            // change took effect before the restart that applies it.
            rows.push_back({{"id", "@enabled"}, {"label", "Enabled"},
                            {"choices", nlohmann::json::array({
                                std::string("Off") + (m.enabled ? " (next launch)" : ""),
                                std::string("On") + (m.enabled ? "" : " (next launch)")})},
                            {"value", m.wanted ? 2 : 1}, {"default", m.wanted ? 2 : 1}});
            for (const auto& f : m.fields) {
                if (f.readonly) {
                    rows.push_back({{"id", f.id}, {"label", f.label}, {"readonly", true}});
                } else {
                    rows.push_back({{"id", f.id}, {"label", f.label}, {"choices", f.texts},
                                    {"value", f.value + 1}, {"default", f.def + 1}});
                }
            }
            mods.push_back({{"id", m.id}, {"name", m.name}, {"version", m.version},
                            {"author", m.author}, {"description", m.description},
                            {"enabled", m.enabled}, {"wanted", m.wanted}, {"rows", rows}});
        }
    }
    if (out) {
        *out = nlohmann::json{{"mods", mods}}.dump(
            -1, ' ', false, nlohmann::json::error_handler_t::replace);
    }
    return true;
}

bool mods_menu_set(const std::string& mod_id, const std::string& row_id, int index1,
                   std::string* why) {
    if (flag_enabled("RSMM_DISABLE_NATIVE_MENU") || g_off.load()) {
        if (why) *why = "native menu is off";
        return false;
    }
    ensure_model();
    std::lock_guard<std::mutex> lk(g_mu);
    auto mit = std::find_if(g_mods.begin(), g_mods.end(),
                            [&](const ModInfo& m) { return m.id == mod_id; });
    if (mit == g_mods.end()) { if (why) *why = "unknown mod '" + mod_id + "'"; return false; }
    ModInfo& m = *mit;
    if (row_id == "@enabled") {
        if (index1 < 1 || index1 > 2) { if (why) *why = "index out of range"; return false; }
        const bool want = index1 == 2;
        if (want != m.wanted) {
            m.wanted = want;
            g_requests_dirty = true;
            g_pending_logs.push_back("[native-menu] " + m.id + " -> " + (want ? "on" : "off")
                                     + " next launch");
        }
        return true;
    }
    auto fit = std::find_if(m.fields.begin(), m.fields.end(),
                            [&](const Field& f) { return f.id == row_id; });
    if (fit == m.fields.end()) { if (why) *why = "unknown row '" + row_id + "'"; return false; }
    Field& f = *fit;
    if (f.readonly) { if (why) *why = "row '" + row_id + "' is read-only"; return false; }
    if (index1 < 1 || std::size_t(index1) > f.options.size()) {
        if (why) *why = "index out of range";
        return false;
    }
    const std::size_t k = std::size_t(index1 - 1);
    if (k != f.value) {
        f.value = k;
        m.values[f.id] = f.options[k];
        m.values_dirty = true;
        g_pending_logs.push_back("[native-menu] " + m.id + "." + f.id + " = " + f.texts[k]);
    }
    return true;
}

bool install_settings_menu_hooks() {
    if (flag_enabled("RSMM_DISABLE_NATIVE_MENU")) {
        Loader::get().log("[native-menu] off (RSMM_DISABLE_NATIVE_MENU is set)");
        return false;
    }
    if (!fn_resolver_init()) {
        Loader::get().log_err("[native-menu] fn_resolver_init failed");
        g_off.store(true);
        return false;
    }
    if (!hook_install("native-menu", "last Settings tab builder",
                      Sym::OptionsMenu_BuildLastCategory_Pattern,
                      reinterpret_cast<void*>(&hook_build),
                      reinterpret_cast<void**>(&g_real_build))) {
        g_off.store(true);
        return false;
    }
    g_build_hooked.store(true, std::memory_order_release);
    // The pause menu button is extra: without it the page still opens from Settings.
    if (hook_install("native-menu", "pause menu action lookup",
                     Sym::PauseMenu_GetActionCallback_Pattern,
                     reinterpret_cast<void*>(&hook_get_callback),
                     reinterpret_cast<void**>(&g_real_get_callback))) {
        Loader::get().log("[native-menu] pause menu Mods button armed");
    }
    Loader::get().log("[native-menu] armed: Mods page via Settings");
    return true;
}

} // namespace rsmm
