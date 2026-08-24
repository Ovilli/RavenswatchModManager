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

// True when some mod has a handler for THIS event name (or a wildcard "*"
// handler). `script_any_subscribers` is far too coarse for the buses: one mod
// with one handler makes it true forever, after which every gameplay dispatch
// paid for a name read, a 768-byte snprintf, a JSON parse and a per-state
// table walk — for an event nobody had subscribed to. The damage meter listens
// to 3 of the ~150 catalogued names, so ~98% of that work was waste, on the
// main thread, in combat.
//
// Over-approximates on purpose: names are remembered process-wide and never
// removed, so a mod that unsubscribes (or is hot-reloaded away) costs one
// wasted emit that finds no handlers — exactly what happened before. It never
// under-approximates, which would silently drop a mod's event.
bool script_has_handler(const char* name);

// True when some state holds an R.on("*") handler. The SDK itself registers
// one in every mod state (it is how main-thread work is pumped off the
// gameplay bus), so this is effectively always true in practice — which is
// why the buses tier their work instead of skipping it: a wildcard subscriber
// gets the envelope, and only an event someone subscribed to BY NAME pays for
// the typed payload decode.
bool script_has_wildcard();

// Process-global key/value slots (0..15) shared across every mod's lua_State
// and the native loader. Backs rsmm._internal.shared_get/shared_set; also used
// by native infrastructure that must publish a handle to all Lua states (e.g.
// the once-installed hero-capture writes the hero pointer here). Atomic.
void     shared_set(int slot, std::uint64_t value);
std::uint64_t shared_get(int slot);

} // namespace rsmm
