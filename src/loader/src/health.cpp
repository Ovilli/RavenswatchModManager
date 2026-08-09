#include "health.h"
#include "loader.h"

#include "json.hpp"

#include <cstring>
#include <fstream>
#include <mutex>

namespace fs = std::filesystem;

namespace rsmm {
namespace health {
namespace {

// Consecutive failed boots before a mod is skipped at load.
constexpr int kStrikeLimit = 3;

std::mutex g_mu;
bool       g_ready = false;
fs::path   g_path;
std::string g_session;
nlohmann::json g_doc;

nlohmann::json& mods_node() {
    if (!g_doc.contains("mods") || !g_doc["mods"].is_object()) {
        g_doc["mods"] = nlohmann::json::object();
    }
    return g_doc["mods"];
}

nlohmann::json& mod_node(const std::string& id) {
    auto& mods = mods_node();
    if (!mods.contains(id) || !mods[id].is_object()) {
        mods[id] = nlohmann::json{{"crashes", 0}, {"last_error", ""},
                                  {"disabled", false}, {"disabled_reason", ""}};
    }
    return mods[id];
}

// Temp-file + rename: the whole point of this file is to survive a process
// that dies at an arbitrary instant, so it must never be observed truncated.
void save_locked() {
    if (g_path.empty()) return;
    const auto tmp = g_path.string() + ".tmp";
    {
        std::ofstream f(tmp, std::ios::trunc);
        if (!f) return;
        f << g_doc.dump(2) << "\n";
        if (!f.good()) return;
    }
    std::error_code ec;
    fs::rename(tmp, g_path, ec);
    if (ec) fs::remove(tmp, ec);
}

void set_canary_locked(bool open, const std::string& step) {
    g_doc["canary"] = nlohmann::json{
        {"open", open}, {"step", step}, {"session", g_session}};
    save_locked();
}

} // namespace

void init(const fs::path& mods_dir, const std::string& session) {
    std::lock_guard<std::mutex> g(g_mu);
    if (g_ready) return;
    g_ready  = true;
    g_path   = mods_dir / "_health.json";
    g_session = session;

    std::error_code ec;
    if (fs::exists(g_path, ec)) {
        try {
            std::ifstream f(g_path);
            f >> g_doc;
        } catch (const std::exception& e) {
            Loader::get().log(std::string("[health] history unreadable, starting "
                                          "fresh: ") + e.what());
            g_doc = nlohmann::json::object();
        }
    }
    if (!g_doc.is_object()) g_doc = nlohmann::json::object();
    g_doc["version"] = 1;

    // An open canary means the previous launch never reached "boot survived".
    const auto canary = g_doc.value("canary", nlohmann::json::object());
    if (canary.is_object() && canary.value("open", false)) {
        const std::string step = canary.value("step", std::string("unknown"));
        const std::string prev_session = canary.value("session", std::string("?"));
        std::string culprit = "_loader";
        constexpr const char* kPrefix = "per_mod:";
        if (step.rfind(kPrefix, 0) == 0) culprit = step.substr(std::strlen(kPrefix));
        auto& node = mod_node(culprit);
        node["crashes"] = node.value("crashes", 0) + 1;
        node["last_error"] = "previous launch (session " + prev_session
                           + ") did not survive boot; last step was '" + step + "'";
        const int n = node.value("crashes", 0);
        Loader::get().log("[health] previous launch did not finish booting at step '"
                          + step + "' -> attributed to '" + culprit + "' (crash #"
                          + std::to_string(n) + ")");
        // Three consecutive failed boots is a mod that reliably bricks the
        // game — the user cannot reach any in-game UI to turn it off, so the
        // loader does it and says so loudly. Recoverable: clear the flag in
        // mods/_health.json (or re-enable from the manager) to try again.
        if (n >= kStrikeLimit && culprit != "_loader" && !node.value("disabled", false)) {
            node["disabled"] = true;
            node["disabled_reason"] =
                "failed to boot " + std::to_string(n) + " times in a row";
            Loader::get().log("[health] '" + culprit + "' DISABLED after "
                              + std::to_string(n) + " failed boots; edit "
                              "mods/_health.json to re-enable");
        }
    }
    set_canary_locked(true, "boot");
}

void checkpoint(const std::string& step) {
    std::lock_guard<std::mutex> g(g_mu);
    if (!g_ready) return;
    set_canary_locked(true, step);
}

void mark_boot_ok() {
    std::lock_guard<std::mutex> g(g_mu);
    if (!g_ready) return;
    const auto canary = g_doc.value("canary", nlohmann::json::object());
    if (!canary.value("open", false)) return;   // already closed this session
    // The strike counter measures CONSECUTIVE failed boots, so a launch that
    // got through resets it — otherwise unrelated crashes months apart would
    // eventually add up to an auto-disable. last_error is kept for diagnosis.
    auto& mods = mods_node();
    for (auto it = mods.begin(); it != mods.end(); ++it) {
        if (it.value().is_object()) it.value()["crashes"] = 0;
    }
    set_canary_locked(false, "boot_ok");
    Loader::get().log("[health] boot canary closed (game survived load)");
}

namespace {
// Read-only lookup. `g_doc[key]` would INSERT a null on a missing key, which
// on a const-looking getter is both surprising and a silent file mutation.
const nlohmann::json* find_mod(const std::string& mod_id) {
    auto it = g_doc.find("mods");
    if (it == g_doc.end() || !it->is_object()) return nullptr;
    auto m = it->find(mod_id);
    if (m == it->end() || !m->is_object()) return nullptr;
    return &(*m);
}
} // namespace

int crash_count(const std::string& mod_id) {
    std::lock_guard<std::mutex> g(g_mu);
    if (!g_ready) return 0;
    const auto* node = find_mod(mod_id);
    return node ? node->value("crashes", 0) : 0;
}

std::string last_error(const std::string& mod_id) {
    std::lock_guard<std::mutex> g(g_mu);
    if (!g_ready) return {};
    const auto* node = find_mod(mod_id);
    return node ? node->value("last_error", std::string{}) : std::string{};
}

void set_disabled(const std::string& mod_id, const std::string& reason) {
    std::lock_guard<std::mutex> g(g_mu);
    if (!g_ready) return;
    auto& node = mod_node(mod_id);
    node["disabled"] = true;
    node["disabled_reason"] = reason;
    save_locked();
    Loader::get().log("[health] '" + mod_id + "' marked disabled: " + reason);
}

bool is_disabled(const std::string& mod_id) {
    std::lock_guard<std::mutex> g(g_mu);
    if (!g_ready) return false;
    const auto* node = find_mod(mod_id);
    return node && node->value("disabled", false);
}

} // namespace health
} // namespace rsmm
