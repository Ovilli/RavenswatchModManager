#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <atomic>
#include <cstdint>

namespace rsmm {

struct ModFile {
    std::string decoded_path;   // logical asset path (decoded via Caesar map)
    std::filesystem::path src;  // absolute path to override file on disk
};

struct Mod {
    std::string id;
    std::string name;
    std::string version;
    std::string author;
    std::filesystem::path root;
    std::vector<ModFile> files;
    bool enabled = false;
    int load_order = 0;
    // Raw contents of <mod>/tags.json (empty if absent). Parsed lazily into a
    // Lua table by the `rsmm.tags()` binding so authors can read cross-mod
    // tag groups at runtime. See src/rsmm/sdk builder.tag().
    std::string tags_json;
};

class Loader {
public:
    static Loader& get();

    void init(const std::filesystem::path& game_dir);
    void shutdown();

    // Asset map: encoded (cooked filename) ↔ decoded (logical path).
    bool load_asset_map(const std::filesystem::path& json_path);
    const std::string* encoded_to_decoded(const std::string& encoded) const;
    const std::string* decoded_to_encoded(const std::string& decoded) const;

    // Mods.
    void scan_mods(const std::filesystem::path& mods_dir);
    void apply_overrides();
    const std::vector<Mod>& mods() const { return mods_; }
    std::vector<Mod>& mods_mut() { return mods_; }
    void persist_state() const;
    void load_state();

    // Asset redirection lookup. Returns nullptr if no override.
    const std::filesystem::path* lookup_override(const std::wstring& original_path_w) const;

    // Menu-state tracking. The file-IO hook calls note_asset_read() with
    // the encoded leaf filename on every CreateFileW; we infer "currently
    // on main menu" from the recency of MainMenu-prefixed reads. The
    // overlay polls is_in_main_menu() each frame for auto-show.
    void note_asset_read(const std::string& encoded_leaf);
    bool is_in_main_menu() const;
    bool game_ever_drew() const { return ever_drew_.load(); }
    void note_present() { ever_drew_.store(true); }

    // Logging.
    void log(const std::string& msg);

    // False when the installed game build does not match the build the
    // symbol map's absolute data addresses (status=va globals) were derived
    // for — any feature reading a Sym:: data VA must degrade instead of
    // dereferencing what is now arbitrary memory (a game patch moving .data
    // crashed the loader this way on 2026-07-10). Pattern-resolved function
    // symbols are unaffected; they re-scan the binary by bytes.
    bool va_globals_trusted() const { return va_trusted_; }

    const std::filesystem::path& game_dir() const { return game_dir_; }
    const std::filesystem::path& mods_dir() const { return mods_dir_; }
    // Short per-process token stamped on every log line; also used to label a
    // crash-canary entry so a post-mortem can find the run in the log.
    const std::string& session() const { return log_session_; }

private:
    Loader() = default;

    // Copy a finished run's log into <game>/rsmm/logs/ before the new run
    // takes over _log.txt, keeping the newest few and pruning the rest.
    // Returns the archive's filename, or "" if nothing was archived.
    std::string archive_log(const std::filesystem::path& src);

    std::filesystem::path game_dir_;
    std::filesystem::path mods_dir_;
    std::filesystem::path log_path_;
    std::string log_archived_;      // filename of the run archived at startup
    std::filesystem::path state_path_;

    std::unordered_map<std::string, std::string> enc_to_dec_;
    std::unordered_map<std::string, std::string> dec_to_enc_;

    std::vector<Mod> mods_;

    // Active override table: encoded-basename -> on-disk file.
    std::unordered_map<std::string, std::filesystem::path> override_by_encoded_;

    mutable std::mutex log_mu_;
    // Held open across log() calls (see loader.cpp) and rotated past the cap.
    mutable std::ofstream log_stream_;
    mutable std::uint64_t log_lines_ = 0;
    static constexpr std::uint64_t kMaxLogBytes = 32ull * 1024 * 1024;
    unsigned long log_pid_ = 0;
    // Short per-process token (e.g. "a3f1") stamped on every line so old and
    // new sessions in the shared log are trivially told apart / grep-filtered.
    std::string log_session_;
    // Host exe basename (Ravenswatch.exe, crashpad_handler.exe, ...) — used to
    // tag lines and to decide whether this process rotates the log on init.
    std::string log_host_;
    bool va_trusted_ = true;

    // Menu detection.
    std::atomic<int64_t> last_menu_read_ms_{0};
    std::atomic<int64_t> last_gameplay_read_ms_{0};
    std::atomic<bool>    ever_drew_{false};
};

// Loader feature gate. Returns true if the named flag is enabled either via
// environment variable (==1/t/T — the Linux/Proton launch-options path) or by
// being listed in <game_dir>/rsmm_loader_flags.json (a JSON array of flag
// names, written by the desktop app / `rsmm json loader-flags set`). The file
// path makes the toggles work on native Windows too, where Steam launch
// options cannot inject environment variables. Result is cached on first call.
bool flag_enabled(const char* name);

} // namespace rsmm
