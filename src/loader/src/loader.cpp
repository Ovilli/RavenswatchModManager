#include "loader.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <fstream>
#include <iostream>
#include <chrono>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <algorithm>
#include <cstdlib>
#include <cstdio>
#include <unordered_set>

#include "fs_iter.h"

#include "json.hpp"   // single-header nlohmann::json (vendored)
#include "toml.hpp"   // single-header toml++ (vendored)

namespace fs = std::filesystem;

namespace rsmm {

Loader& Loader::get() {
    static Loader inst;
    return inst;
}

namespace {
// "YYYY-MM-DD HH:MM:SS.mmm" wall-clock stamp. Shared by the per-line prefix and
// the session banner so both read identically. msvcrt's strftime has no %F/%T,
// so the format is spelled out.
std::string format_ts_now() {
    using clock = std::chrono::system_clock;
    const auto now = clock::now();
    const auto t   = clock::to_time_t(now);
    const auto ms  = std::chrono::duration_cast<std::chrono::milliseconds>(
                         now.time_since_epoch()).count() % 1000;
    char ts[32] = {0};
    if (std::tm* tm = std::localtime(&t)) {
        std::strftime(ts, sizeof(ts), "%Y-%m-%d %H:%M:%S", tm);
    }
    char out[40] = {0};
    std::snprintf(out, sizeof(out), "%s.%03d", ts, static_cast<int>(ms));
    return out;
}
}  // namespace

namespace {
// Keep this many archived runs. A long co-op session writes a few hundred KB,
// so twenty is a couple of evenings of play and still bounded — the point of a
// cap is that an archive nobody prunes eventually IS the bug it was added to
// prevent.
constexpr std::size_t kLogArchiveKeep = 20;
}  // namespace

std::string Loader::archive_log(const fs::path& src) {
    // Rotation used to be a single rename onto _log.prev.txt, so every launch
    // destroyed the run before last: reproduce a bug, relaunch to test a fix,
    // and the log you actually needed was already gone. Keep them.
    std::error_code ec;
    const fs::path dir = game_dir_ / "rsmm" / "logs";
    fs::create_directories(dir, ec);
    if (ec) return {};                    // no archive dir: rotation still works

    // Name the file after the run it CONTAINS, not the moment we archive it.
    // The session banner carries that run's own token and start time; falling
    // back to "now" would stamp every archive with the START of the next run.
    std::string stamp, sid;
    {
        // The banner is NOT line 1: the file opens with a blank line and a
        // rule, so it lands on line 3 — and the loader writes CRLF, so the
        // trailing \r has to come off before the last field is parsed. Reading
        // only the first line named every archive "unknown".
        std::ifstream in(src);
        std::string line;
        for (int i = 0; i < 10 && std::getline(in, line); ++i) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.rfind("== SESSION ", 0) != 0) continue;
            // "== SESSION fd1d  2026-08-16 16:23:21.657  pid 320  host ..."
            std::istringstream ss(line);
            std::string eq, kw, date, tod;
            if ((ss >> eq >> kw >> sid >> date >> tod)
                && date.size() == 10 && tod.size() >= 8) {
                stamp = date + "_" + tod.substr(0, 2) + tod.substr(3, 2)
                        + tod.substr(6, 2);
            } else {
                sid.clear();
            }
            break;
        }
    }
    if (stamp.empty()) {
        stamp = format_ts_now().substr(0, 10);
        sid   = "unknown";
    }

    fs::path dest = dir / (stamp + "_" + sid + ".log");
    for (int n = 2; fs::exists(dest, ec) && n < 100; ++n) {
        dest = dir / (stamp + "_" + sid + "." + std::to_string(n) + ".log");
    }
    fs::copy_file(src, dest, fs::copy_options::overwrite_existing, ec);
    if (ec) return {};

    // Prune oldest-first by NAME: the stamp leads, so lexical order is
    // chronological, and unlike last_write_time it does not lie after a copy.
    std::vector<fs::path> kept;
    for_each_in_dir(dir, [&](const fs::directory_entry& e) {
        std::error_code eec;
        if (e.is_regular_file(eec) && !eec && e.path().extension() == ".log") {
            kept.push_back(e.path());
        }
        return true;
    });
    if (kept.size() > kLogArchiveKeep) {
        std::sort(kept.begin(), kept.end());
        for (std::size_t i = 0; i + kLogArchiveKeep < kept.size(); ++i) {
            fs::remove(kept[i], ec);
        }
    }
    return dest.filename().string();
}

void Loader::init(const fs::path& game_dir) {
    game_dir_  = game_dir;
    mods_dir_  = game_dir / "mods";
    log_path_  = game_dir / "mods" / "_log.txt";
    state_path_ = game_dir / "mods" / "_state.json";
    log_pid_   = GetCurrentProcessId();
    std::error_code ec;
    fs::create_directories(mods_dir_, ec);

    // Host exe path + basename.
    char exe[MAX_PATH] = {0};
    GetModuleFileNameA(nullptr, exe, MAX_PATH);
    const std::string exe_path(exe);
    {
        const auto slash = exe_path.find_last_of("\\/");
        log_host_ = (slash == std::string::npos) ? exe_path
                                                 : exe_path.substr(slash + 1);
    }

    // Per-process session token: 4 hex chars mixed from the tick count and pid.
    // Stamped on every line so successive/concurrent injections never blur
    // together — grep one token to isolate a single run.
    {
        const unsigned long long mix =
            (static_cast<unsigned long long>(GetTickCount64()) << 16) ^
            (static_cast<unsigned long long>(log_pid_) * 2654435761ull);
        char sid[8] = {0};
        std::snprintf(sid, sizeof(sid), "%04x",
                      static_cast<unsigned>((mix >> 8) & 0xffffu));
        log_session_ = sid;
    }

    // Rotate the shared log so each real game launch starts clean and the
    // previous run survives in _log.prev.txt — this is what makes old vs new
    // sessions separable. ONLY the game process rotates; helper injections
    // (crashpad_handler.exe & friends) append into the current file with their
    // host tag, so they can never wipe the game's own log.
    bool is_game_host = false;
    {
        std::string h = log_host_;
        std::transform(h.begin(), h.end(), h.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        is_game_host = h.find("ravenswatch") != std::string::npos;
    }
    if (is_game_host) {
        std::error_code rec;
        if (fs::exists(log_path_, rec)) {
            log_archived_ = archive_log(log_path_);
            // _log.prev.txt stays as the "one run back" alias every existing
            // reader knows (rsmm log --prev, the desktop Log tab). It is a COPY
            // of what was just archived, so the archive is the durable record
            // and this remains the cheap shortcut.
            fs::copy_file(log_path_, mods_dir_ / "_log.prev.txt",
                          fs::copy_options::overwrite_existing, rec);
            fs::remove(log_path_, rec);
        }
    }

    // Session banner: a strong, greppable ("SESSION") separator between runs.
    {
        std::lock_guard<std::mutex> g(log_mu_);
        std::ofstream f(log_path_, std::ios::app);
        f << "\n"
          << "================================================================\n"
          << "== SESSION " << log_session_ << "  " << format_ts_now()
          << "  pid " << log_pid_ << "  host " << log_host_
          << (is_game_host ? "" : "  (helper inject)") << "\n"
          << "================================================================\n";
    }
    // Build stamp, first thing in every session. A pasted log is otherwise
    // indistinguishable from one produced by a loader that predates the change
    // being tested — which cost three playtests on 2026-08-16, twice because
    // `restore` had put the stock DLL back and once because the log was simply
    // older than the build. __DATE__/__TIME__ are the DLL's own compile time,
    // so this cannot drift out of sync with the binary that printed it.
    log(std::string("loader build ") + __DATE__ " " __TIME__);
    // Say where the previous run went. Without this the archive is invisible
    // until someone thinks to go looking for the directory, and a naming
    // fallback ("unknown") would never be noticed at all.
    if (!log_archived_.empty()) {
        log("previous run archived -> rsmm/logs/" + log_archived_);
    }
    // The other half of the stamp. The Lua SDK is disk-loaded and ships
    // INDEPENDENTLY of this DLL (a Lua-only change needs no rebuild), so the
    // two can legitimately disagree and a log has to say which pair produced
    // it. Its byte size changes on every edit, so nothing needs bumping by
    // hand. Printed from here rather than from Lua on purpose: apply_sandbox()
    // removes `debug` and `io` from a mod state, and reaching for them there
    // broke every mod at load.
    {
        std::error_code ec;
        const auto sdk = game_dir_ / "rsmm" / "lib" / "rsmm.lua";
        const auto sz = std::filesystem::file_size(sdk, ec);
        log("sdk build: rsmm.lua "
            + (ec ? std::string("MISSING - loader runtime not installed")
                  : std::to_string(sz) + " bytes"));
    }
    log("game_dir=" + game_dir_.string());
    log(std::string("host=") + exe_path);

    // Build-fingerprint gate for absolute data addresses. The planted
    // pattern-DB meta records the exact game exe (size + sha) the current
    // symbol map was derived from. Function symbols self-heal via byte
    // scanning, but status=va data globals are absolute — after a game patch
    // they point into arbitrary memory, which at best reads garbage (every
    // R.options value nil) and at worst crashes (deferred_inject_poll AV,
    // 2026-07-10). Size mismatch = different build = fail those features
    // closed until `rsmm update-data` plants a matching DB.
    {
        const fs::path meta = game_dir_ / "rsmm" / "data"
                              / "function_patterns.meta.json";
        // Named `game_exe`, not `exe`: the enclosing scope already has an
        // `exe` (the char[MAX_PATH] holding the HOST process path, which for a
        // helper inject is not Ravenswatch at all). Shadowing the two made the
        // gate read as if it were fingerprinting the running process.
        const fs::path game_exe = game_dir_ / "Ravenswatch.exe";
        std::error_code mec;
        const auto exe_size = fs::file_size(game_exe, mec);
        if (mec || !fs::exists(meta)) {
            log("[va-gate] no pattern-DB meta or game exe to compare — "
                "keeping va-globals enabled (unverified)");
        } else {
            try {
                std::ifstream mf(meta);
                nlohmann::json mj;
                mf >> mj;
                const auto want = mj.value("game_exe_size", std::uint64_t{0});
                if (want != 0 && want != exe_size) {
                    va_trusted_ = false;
                    log("[va-gate] game exe size " + std::to_string(exe_size)
                        + " != symbol-map build " + std::to_string(want)
                        + " — the game updated; absolute data addresses are "
                          "DISABLED (run `rsmm update-data`, then re-verify "
                          "va globals). Pattern-resolved features still work.");
                }
            } catch (const std::exception& e) {
                log(std::string("[va-gate] meta parse error: ") + e.what());
            }
        }
    }
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

void Loader::note_asset_read(std::string_view leaf) {
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

void Loader::log_warn(const std::string& msg) { log("[warn] " + msg); }

void Loader::log_err(const std::string& msg) { log("[err] " + msg); }

void Loader::log(const std::string& msg) {
    std::lock_guard<std::mutex> g(log_mu_);
    // Prefix: [timestamp | session | pid]. The session token isolates one run
    // in the shared, multi-launch log; pid is kept for cross-referencing the OS.
    //
    // The stream is kept OPEN across calls and flushed per line. Re-opening the
    // file for every line meant a filesystem open+close inside detours that run
    // on the game's own thread (the hero-capture and UI hooks log per fire),
    // and under Proton that is a syscall round trip through the Wine FS layer.
    // Flushing each line keeps the crash-time tail intact, which is the whole
    // point of the log.
    if (!log_stream_.is_open()) {
        log_stream_.open(log_path_, std::ios::app);
        if (!log_stream_.is_open()) return;
    }
    log_stream_ << "[" << format_ts_now() << " " << log_session_ << " " << log_pid_
                << "] " << msg << std::endl;
    // A log that grows without bound across a long session (the spawn trace
    // and the analytics firehose are chatty) eventually fills the user's disk.
    // Cap it: once past the limit, roll to _log.prev.txt and start clean.
    if (++log_lines_ % 512 == 0) {
        std::error_code ec;
        const auto sz = std::filesystem::file_size(log_path_, ec);
        if (!ec && sz > kMaxLogBytes) {
            log_stream_.close();
            std::filesystem::rename(log_path_, mods_dir_ / "_log.prev.txt", ec);
            log_stream_.open(log_path_, std::ios::app);
            if (log_stream_.is_open()) {
                log_stream_ << "[" << format_ts_now() << " " << log_session_ << " "
                            << log_pid_ << "] (log rotated at " << sz
                            << " bytes; previous part in _log.prev.txt)"
                            << std::endl;
            }
        }
    }
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
    if (!j.is_object()) {
        log("asset_map.json is not a JSON object; ignoring");
        return false;
    }
    enc_to_dec_.reserve(j.size());
    dec_to_enc_.reserve(j.size());
    std::size_t skipped = 0;
    for (auto it = j.begin(); it != j.end(); ++it) {
        // Skip non-string values rather than letting get<std::string>() throw:
        // one bad entry used to abort the whole load, and with no asset map
        // EVERY file override silently stops working.
        if (!it.value().is_string()) { ++skipped; continue; }
        const std::string& enc = it.key();
        const std::string& dec = it.value().get_ref<const std::string&>();
        enc_to_dec_.emplace(enc, dec);
        dec_to_enc_.emplace(dec, enc);
    }
    log("asset_map loaded entries=" + std::to_string(enc_to_dec_.size())
        + (skipped ? " (skipped " + std::to_string(skipped) + " non-string)" : ""));
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
    std::error_code scan_ec;
    if (!fs::exists(mods_dir, scan_ec)) return;

    // Non-throwing walk: this used to be a bare directory_iterator, so a single
    // unreadable entry threw out of scan_mods and the loader's outer catch
    // reported "no mods" — with the reason only in OutputDebugString.
    for_each_in_dir(mods_dir, [&](const fs::directory_entry& entry) {
        std::error_code eec;
        if (!entry.is_directory(eec) || eec) return true;
        const fs::path manifest = entry.path() / "manifest.toml";
        if (!fs::exists(manifest, eec)) return true;

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
            return true;
        }

        // Stash tags.json verbatim (parsed lazily by the rsmm.tags() binding).
        const fs::path tags_path = entry.path() / "tags.json";
        if (fs::exists(tags_path, eec)) {
            std::ifstream tf(tags_path);
            std::stringstream ss;
            ss << tf.rdbuf();
            m.tags_json = ss.str();
        }

        // Discover override files under <mod>/assets/<decoded_path>.
        const fs::path assets = entry.path() / "assets";
        for_each_in_tree(assets, [&](const fs::directory_entry& f) {
            std::error_code fec;
            if (!f.is_regular_file(fec) || fec) return true;
            ModFile mf;
            mf.src = f.path();
            mf.decoded_path = fs::relative(f.path(), assets, fec).generic_string();
            if (fec || mf.decoded_path.empty()) return true;
            m.files.push_back(std::move(mf));
            return true;
        });
        // Ids key the script table, the state file and the health history, so
        // a duplicate would silently make one mod shadow the other everywhere.
        bool dup = false;
        for (const auto& existing : mods_) {
            if (existing.id == m.id) { dup = true; break; }
        }
        if (dup) {
            log("duplicate mod id '" + m.id + "' in " + entry.path().string()
                + "; ignoring this copy (ids must be unique)");
            return true;
        }
        mods_.push_back(std::move(m));
        return true;
    });
    std::sort(mods_.begin(), mods_.end(),
              [](const Mod& a, const Mod& b){ return a.load_order < b.load_order; });
    log("scan_mods found=" + std::to_string(mods_.size()));
}

void Loader::apply_overrides() {
    override_by_encoded_.clear();
    for (const auto& m : mods_) {
        if (!m.enabled) continue;
        for (const auto& f : m.files) {
            // `_root/` assets are NOT cooked and are never opened through the
            // _Cooking path this map redirects: `rsmm apply` installs them
            // straight into the install root (ApplicationSettings.ot and the
            // like), backing the original up beside it. So they have no
            // encoded name by construction, and reporting that as "no encoded
            // match" claimed a mod was broken while its bytes were already
            // live -- printed next to "active overrides=0", which made a
            // working ot patch look like it had done nothing.
            if (f.decoded_path.rfind("_root/", 0) == 0) continue;
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
            // Last writer wins (load_order decides, and mods_ is sorted by it),
            // but say so: two mods overriding the same asset silently produced
            // whichever one happened to sort later.
            auto prev = override_by_encoded_.find(leaf);
            if (prev != override_by_encoded_.end() && prev->second != f.src) {
                log("[conflict] " + f.decoded_path + " overridden by ["
                    + m.id + "]; previous source " + prev->second.string()
                    + " is shadowed (raise its load_order to win)");
            }
            override_by_encoded_[leaf] = f.src;
        }
    }
    // Say WHICH table this is. `lookup_override` has exactly one caller --
    // the IO hook, which is off unless RSMM_ENABLE_IO=1 -- and this counts
    // files found under <game>/mods/<id>/assets/, which `rsmm apply`
    // deliberately never populates (it syncs only a mod's top-level files and
    // writes the assets themselves into DarkTalesResources/_Cooking). So the
    // normal, fully-applied install reports ZERO here, and a bare
    // "active overrides=0" reads as "none of your mods are doing anything".
    // It cost a support thread exactly that misdiagnosis. Whether a data mod
    // is applied is answered by .rsmm_state.json / `rsmm doctor`, never here.
    log("IO-hook override table: " + std::to_string(override_by_encoded_.size())
        + " file(s) under mods/*/assets (unused unless RSMM_ENABLE_IO=1; NOT a"
          " count of applied mods -- see `rsmm doctor`)");
}

const fs::path* Loader::lookup_override(const wchar_t* path_w) const {
    if (!path_w || override_by_encoded_.empty()) return nullptr;
    // Extract basename (the game opens by absolute path; we key on the encoded
    // leaf filename which matches asset_map keys). Scanned in place: this runs
    // on every file the game opens.
    const wchar_t* leaf_w = path_w;
    for (const wchar_t* p = path_w; *p; ++p) {
        if (*p == L'\\' || *p == L'/') leaf_w = p + 1;
    }
    // Encoded cooked names are pure ASCII (the cipher maps letters to letters),
    // so anything outside ASCII cannot be one of our keys. Bail instead of
    // truncating each wchar_t to a char, which folds distinct code points onto
    // the same byte and could match the WRONG override.
    std::string leaf;
    for (const wchar_t* p = leaf_w; *p; ++p) {
        if (*p > 0x7f) return nullptr;
        leaf.push_back(static_cast<char>(*p));
    }
    auto it = override_by_encoded_.find(leaf);
    return it == override_by_encoded_.end() ? nullptr : &it->second;
}

void Loader::persist_state() const {
    nlohmann::json j;
    for (const auto& m : mods_) {
        j[m.id] = { {"enabled", m.enabled}, {"load_order", m.load_order} };
    }
    // Temp-file + rename: a direct write truncates the existing state first,
    // so a crash mid-write (or the process being killed) left an empty
    // _state.json and every mod's enabled/load_order silently reset.
    const auto tmp = state_path_.string() + ".tmp";
    {
        std::ofstream f(tmp, std::ios::trunc);
        if (!f) return;
        f << j.dump(2) << "\n";
        if (!f.good()) return;
    }
    std::error_code ec;
    fs::rename(tmp, state_path_, ec);
    if (ec) fs::remove(tmp, ec);
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

bool flag_enabled(const char* name) {
    // 1. Environment variable — the original launch-options path. Works on
    //    Linux/Proton where Steam launch options like `RSMM_ENABLE_X=1
    //    %command%` set the game process environment.
    if (const char* v = std::getenv(name); v && (v[0] == '1' || v[0] == 't' || v[0] == 'T'))
        return true;

    // 2. Flags file next to winhttp.dll, written by the desktop app. Parsed
    //    once and cached; a missing or malformed file means "no flags set".
    static std::mutex mu;
    static bool loaded = false;
    static std::unordered_set<std::string> enabled;
    std::lock_guard<std::mutex> lk(mu);
    if (!loaded) {
        loaded = true;
        const fs::path fp = Loader::get().game_dir() / "rsmm_loader_flags.json";
        if (fs::exists(fp)) {
            try {
                std::ifstream f(fp);
                nlohmann::json j;
                f >> j;
                if (j.is_array()) {
                    for (auto& e : j)
                        if (e.is_string()) enabled.insert(e.get<std::string>());
                }
            } catch (...) {
                Loader::get().log_warn("rsmm_loader_flags.json parse error; ignoring");
            }
        }
    }
    return enabled.count(name) != 0;
}

} // namespace rsmm
