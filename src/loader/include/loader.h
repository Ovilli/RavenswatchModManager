#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include <filesystem>
#include <mutex>
#include <atomic>

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

    const std::filesystem::path& game_dir() const { return game_dir_; }
    const std::filesystem::path& mods_dir() const { return mods_dir_; }

private:
    Loader() = default;

    std::filesystem::path game_dir_;
    std::filesystem::path mods_dir_;
    std::filesystem::path log_path_;
    std::filesystem::path state_path_;

    std::unordered_map<std::string, std::string> enc_to_dec_;
    std::unordered_map<std::string, std::string> dec_to_enc_;

    std::vector<Mod> mods_;

    // Active override table: encoded-basename -> on-disk file.
    std::unordered_map<std::string, std::filesystem::path> override_by_encoded_;

    mutable std::mutex log_mu_;

    // Menu detection.
    std::atomic<int64_t> last_menu_read_ms_{0};
    std::atomic<int64_t> last_gameplay_read_ms_{0};
    std::atomic<bool>    ever_drew_{false};
};

} // namespace rsmm
