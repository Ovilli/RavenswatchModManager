#pragma once
namespace rsmm {

// Magical-object pool injection.
//
// Post-detours FUN_140258760 (SpawnAllObjects) after the game processes
// its own item-spawn linked list, then injects EntityResource* pointers
// for Lua-registered custom items into the pool's runtime array at
// DAT_1414365d0 + 0x10 so they appear in hero-item selection.
//
// Entity resources are resolved at spawn time via FUN_140487040
// (pattern-resolved resource-by-path lookup). The decoded path format
// (e.g. "EntitySettings/Objects/Magical_Objects/Common/MyItem...") is
// passed from Lua.
//
// Opt-in: only arms when at least one item was registered via
// rsmm._internal.register_item during mod init.
bool install_item_hooks();

// Called from rsmm._internal.register_item (script_lua.cpp) during mod init.
// Accepts the item id, name, description, base id, entity resource path,
// and rarity. Stores into the C++ registry consumed by the hook at spawn
// time. Thread-safe. Returns false on duplicate id.
bool register_native_item(const char* id,
                          const char* name,
                          const char* description,
                          const char* base,
                          const char* entity_path,
                          int rarity);

// Resolve a registered custom item's runtime identity GUID (the def+0x88/+0x90
// value the engine spawns/grants/dedups on). Looks the item up by id, finds its
// EntitySettingsResource* via the path lookup, then scans the magical-object
// pool's SOURCE list for the entry spawned from that resource and reads its
// GUID. Returns false (and leaves *lo/*hi untouched) until the item's definition
// has loaded into the pool — so a mod polls this after registration before
// binding behaviour with it. Read-only; never calls game code. Thread-safe.
bool resolve_item_guid(const char* id, unsigned long long* lo,
                       unsigned long long* hi);

} // namespace rsmm
