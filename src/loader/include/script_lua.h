#pragma once
#include <cstdint>
#include <filesystem>
#include <string>

namespace rsmm {

// Per-mod Lua runtime. Each mod gets its own lua_State; the loader owns
// them and tears them down on shutdown.
//
// Exposed Lua API (see script_lua.cpp for details):
//   rsmm.log(msg)
//   rsmm.register_asset_override(decoded_path, src_path)
//   rsmm.commit()
//   rsmm.mod_dir()                     -- returns this mod's root folder
//   rsmm.game_dir()                    -- absolute install dir
//   rsmm.is_in_main_menu()             -- bool
//   rsmm.list_mods()                   -- {id, name, version, author, enabled}[]
//   rsmm.encoded_path(decoded)         -- decoded -> encoded or nil
//   rsmm.decoded_path(encoded)         -- encoded -> decoded or nil
//   rsmm.on_event(name, fn)            -- "setup"|"ready"|"tick"|"exit"|...
//   rsmm.tags([mod_id])                -- parsed tags.json table
//
// Event handlers receive one argument: a payload table (empty for events
// with no payload). Lifecycle order: "setup" -> "ready" -> "tick"*.

bool script_run_mod_init(const std::string& mod_id,
                         const std::filesystem::path& mod_root);
// Emit an event to every mod. The no-payload form passes an empty table;
// the `_json` form parses `payload_json` (a JSON object string) and passes
// it as the handler's argument table. Keeping the payload as a string keeps
// this header free of the JSON dependency.
void script_emit_event(const std::string& name);
void script_emit_event_json(const std::string& name, const std::string& payload_json);
void script_reload_changed();   // re-run init.lua for any mod whose file changed
void script_shutdown_all();

// True when at least one mod has registered an event handler. The engine-event
// detours sit on very hot paths (the gameplay bus fires hundreds of times a
// second in combat), so they check this before building a payload nobody will
// read — that is what makes it safe to arm the buses by default.
bool script_any_subscribers();

// Process-global key/value slots (0..15) shared across every mod's lua_State
// and the native loader. Backs rsmm._internal.shared_get/shared_set; also used
// by native infrastructure that must publish a handle to all Lua states (e.g.
// the once-installed hero-capture writes the hero pointer here). Atomic.
void     shared_set(int slot, std::uint64_t value);
std::uint64_t shared_get(int slot);

} // namespace rsmm
