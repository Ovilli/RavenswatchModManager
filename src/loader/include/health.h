#pragma once
// Boot canary + per-mod crash history.
//
// A mod's init.lua runs inside the game process. When it takes the game down
// during load there is nothing left to read: the log's last line is whatever
// happened to flush, and the user sees a game that refuses to start with no
// idea which mod to blame. This is the missing piece — it was declared by the
// Lua side (rsmm/health.lua calls rsmm._internal.health_*) but the native half
// never existed, so every R.health call silently returned 0/nil.
//
// How it works: the loader opens a canary in <game>/mods/_health.json at
// startup and stamps a `step` as it advances (per-mod init, then post-init).
// The canary is closed once the game has demonstrably survived boot. If the
// NEXT launch finds it still open, the previous run died at the recorded step
// — so a crash inside `per_mod:<id>` is attributed to that mod and counted.
//
// Nothing here is auto-destructive: a mod is only skipped when something
// explicitly disables it (R.health.disable, or the user editing the file).

#include <cstdint>
#include <filesystem>
#include <string>

namespace rsmm {
namespace health {

// Load the history, attribute any unclosed canary from the previous launch,
// then re-open the canary for this session. Safe to call once per process.
void init(const std::filesystem::path& mods_dir, const std::string& session);

// Record how far boot has progressed. Cheap (one small atomic file write).
void checkpoint(const std::string& step);

// The game survived boot: close the canary so this launch is not blamed on
// the next one.
void mark_boot_ok();

int         crash_count(const std::string& mod_id);
std::string last_error(const std::string& mod_id);

// Record a NON-fatal failure against a mod: its init.lua raised, an event
// handler was latched off, and so on. Does not touch the crash counter — only
// the boot canary decides that a mod took the game down, and a mod whose init
// fails cleanly has not. Exists because until it did, a mod that simply failed
// to load left no record outside _log.txt, which the next few launches rotate
// away; _health.json is the durable, machine-readable one.
void note_error(const std::string& mod_id, const std::string& msg);

// Flag a mod as skipped-at-load, with a reason. Persists across launches.
void set_disabled(const std::string& mod_id, const std::string& reason);
bool is_disabled(const std::string& mod_id);

} // namespace health
} // namespace rsmm
