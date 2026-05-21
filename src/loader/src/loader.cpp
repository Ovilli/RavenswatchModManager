#include "loader.h"

#include <fstream>
#include <iostream>
#include <chrono>
#include <iomanip>
#include <sstream>
#include <algorithm>

#include "json.hpp"   // single-header nlohmann::json (vendored)
#include "toml.hpp"   // single-header toml++ (vendored)

namespace fs = std::filesystem;

namespace rsmm {

Loader& Loader::get() {
    static Loader inst;
    return inst;
}

void Loader::init(const fs::path& game_dir) {
    game_dir_  = game_dir;
    mods_dir_  = game_dir / "mods";
    log_path_  = game_dir / "mods" / "_log.txt";
    state_path_ = game_dir / "mods" / "_state.json";
    std::error_code ec;
    fs::create_directories(mods_dir_, ec);
    log("=== RavenswatchModManager init ===");
    log("game_dir=" + game_dir_.string());
}

void Loader::shutdown() {
    log("shutdown");
}

namespace {
int64_t now_ms() {
    using clock = std::chrono::steady_clock;
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        clock::now().time_since_epoch()).count();
}
}

void Loader::note_asset_read(const std::string& leaf) {
    // Main-menu assets are emitted from cooked names whose encoded path
    // contains the prefix HgdzHqzw (decoded "MainMenu") or Jd\HgdzHqzw
    // (decoded "Ui\MainMenu"). Treat any opened file containing that token
    // as a menu read; everything else as gameplay.
    if (leaf.find("HgdzHqzw") != std::string::npos) {
        last_menu_read_ms_.store(now_ms());
    } else if (leaf.size() > 8) {
        last_gameplay_read_ms_.store(now_ms());
    }
}

bool Loader::is_in_main_menu() const {
    if (!ever_drew_.load()) return false; // still booting; don't pop UI yet
    const int64_t menu = last_menu_read_ms_.load();
    const int64_t game = last_gameplay_read_ms_.load();
    if (menu == 0) return false;
    // Recent menu reads + no fresher gameplay reads -> on the menu.
    const int64_t now = now_ms();
    return (now - menu) < 5000 && menu >= game - 500;
}

void Loader::log(const std::string& msg) {
    std::lock_guard<std::mutex> g(log_mu_);
    using clock = std::chrono::system_clock;
    auto now = clock::to_time_t(clock::now());
    std::ostringstream ts;
    ts << std::put_time(std::localtime(&now), "%F %T");
    std::ofstream f(log_path_, std::ios::app);
    f << "[" << ts.str() << "] " << msg << "\n";
}

bool Loader::load_asset_map(const fs::path& json_path) {
    if (!fs::exists(json_path)) {
        log("asset_map.json missing at " + json_path.string());
        return false;
    }
    std::ifstream f(json_path);
    nlohmann::json j;
    try {
        f >> j;
    } catch (const std::exception& e) {
        log(std::string("asset_map parse error: ") + e.what());
        return false;
    }
    enc_to_dec_.reserve(j.size());
    dec_to_enc_.reserve(j.size());
    for (auto it = j.begin(); it != j.end(); ++it) {
        const std::string enc = it.key();
        const std::string dec = it.value().get<std::string>();
        enc_to_dec_.emplace(enc, dec);
        dec_to_enc_.emplace(dec, enc);
    }
    log("asset_map loaded entries=" + std::to_string(enc_to_dec_.size()));
    return true;
}

const std::string* Loader::encoded_to_decoded(const std::string& enc) const {
    auto it = enc_to_dec_.find(enc);
    return it == enc_to_dec_.end() ? nullptr : &it->second;
}

const std::string* Loader::decoded_to_encoded(const std::string& dec) const {
    // Normalise forward slashes to backslashes (asset_map.json uses \).
    std::string normalized = dec;
    for (auto& c : normalized) {
        if (c == '/') c = '\\';
    }
    auto it = dec_to_enc_.find(normalized);
    return it == dec_to_enc_.end() ? nullptr : &it->second;
}

void Loader::scan_mods(const fs::path& mods_dir) {
    mods_.clear();
    if (!fs::exists(mods_dir)) return;

    for (const auto& entry : fs::directory_iterator(mods_dir)) {
        if (!entry.is_directory()) continue;
        const fs::path manifest = entry.path() / "manifest.toml";
        if (!fs::exists(manifest)) continue;

        Mod m;
        m.root = entry.path();
        m.id   = entry.path().filename().string();
        try {
            auto tbl = toml::parse_file(manifest.string());
            m.id         = tbl["mod"]["id"].value_or(m.id);
            m.name       = tbl["mod"]["name"].value_or(m.id);
            m.version    = tbl["mod"]["version"].value_or("0.0.0");
            m.author     = tbl["mod"]["author"].value_or("");
            m.enabled    = tbl["mod"]["enabled"].value_or(true);
            m.load_order = tbl["mod"]["load_order"].value_or(0);
        } catch (const std::exception& e) {
            log("manifest parse fail " + manifest.string() + ": " + e.what());
            continue;
        }

        // Discover override files under <mod>/assets/<decoded_path>.
        const fs::path assets = entry.path() / "assets";
        if (fs::exists(assets)) {
            for (auto& f : fs::recursive_directory_iterator(assets)) {
                if (!f.is_regular_file()) continue;
                ModFile mf;
                mf.src = f.path();
                mf.decoded_path = fs::relative(f.path(), assets).generic_string();
                m.files.push_back(std::move(mf));
            }
        }
        mods_.push_back(std::move(m));
    }
    std::sort(mods_.begin(), mods_.end(),
              [](const Mod& a, const Mod& b){ return a.load_order < b.load_order; });
    log("scan_mods found=" + std::to_string(mods_.size()));
}

void Loader::apply_overrides() {
    override_by_encoded_.clear();
    for (const auto& m : mods_) {
        if (!m.enabled) continue;
        for (const auto& f : m.files) {
            // Look up encoded basename for this decoded path.
            // Mod authors write decoded paths; we resolve to the encoded
            // filename that the game actually opens.
            auto enc = decoded_to_encoded(f.decoded_path);
            if (!enc) {
                log("[" + m.id + "] no encoded match for " + f.decoded_path);
                continue;
            }
            // lookup_override extracts the leaf (basename) from the game's
            // file path, so we key by leaf too.
            auto slash = enc->find_last_of("\\/");
            std::string leaf = (slash == std::string::npos) ? *enc : enc->substr(slash + 1);
            override_by_encoded_[leaf] = f.src;
        }
    }
    log("active overrides=" + std::to_string(override_by_encoded_.size()));
}

const fs::path* Loader::lookup_override(const std::wstring& path_w) const {
    if (override_by_encoded_.empty()) return nullptr;
    // Extract basename (the game opens by absolute path; we key on the encoded
    // leaf filename which matches asset_map keys).
    auto slash = path_w.find_last_of(L"\\/");
    std::wstring leaf_w = (slash == std::wstring::npos) ? path_w : path_w.substr(slash + 1);
    std::string leaf(leaf_w.begin(), leaf_w.end());
    auto it = override_by_encoded_.find(leaf);
    return it == override_by_encoded_.end() ? nullptr : &it->second;
}

void Loader::persist_state() const {
    nlohmann::json j;
    for (const auto& m : mods_) {
        j[m.id] = { {"enabled", m.enabled}, {"load_order", m.load_order} };
    }
    std::ofstream f(state_path_);
    f << j.dump(2);
}

void Loader::load_state() {
    if (!fs::exists(state_path_)) return;
    std::ifstream f(state_path_);
    nlohmann::json j;
    try { f >> j; } catch (...) { return; }
    for (auto& m : mods_) {
        if (j.contains(m.id)) {
            m.enabled    = j[m.id].value("enabled", false);
            m.load_order = j[m.id].value("load_order", 0);
        }
    }
}

} // namespace rsmm
