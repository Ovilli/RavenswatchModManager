#pragma once
// Mod key bindings as native rows in the game's Controls menu (R.input.keybinds).
//
// WHY THIS EXISTS
// ---------------
// The game's own key actions are fixed inline arrays whose counts are baked
// into a dozen functions, so they cannot grow. But the settings file is driven
// by a registry, not by those arrays: GameOptionsManager_Register puts any
// InputKeyGameOption into a category, and GameSettings.ini then saves and loads
// it BY NAME with no further work. And a key row in the Controls menu writes
// the captured key through a pointer (row+0x98), so it never needs to know
// which option it edits. A mod binding is therefore:
//   * two InputKeyGameOption objects in loader memory (keyboard, pad), named
//     "<mod id>::<id>", registered in categories 4 / 5;
//   * one row per tab, spawned by the game's own Explo key-row spawner and
//     then pointed at our option (value pointer and title);
//   * the duplicate-key resolver extended to clear our options too;
//   * a press check in the input poll on each binding's current key.
//
// WHEN THINGS RUN
// ---------------
// The game reads GameSettings.ini during boot, before any loader hook can be
// relied on to be in place, so registration does not race it: the first input
// poll (the game's main thread, the thread that posts every settings request)
// registers everything mods declared from init.lua and then asks the game to
// read the file again (GameOptionsManager_RequestLoad), which fills in saved
// keys. The settings job queue is single-producer, which is why that request
// is only ever made from the poll. A binding declared after that point is
// refused: the re-read would not cover it.
//
// Registering hands the game pointers into this DLL (the option objects, the
// strings their names alias, the rows' key pointers) and the game has no way
// to take them back, so registration pins the loader module: once a mod has
// keybinds, a dynamic unload no longer unmaps it.
//
// Presses are read from the key table's "pressed this frame" bit after the
// poll and delivered as the Lua event "input:keybind" {mod, id, presses, key,
// blocked}. Delivery never blocks the game thread; presses wait for the next
// frame when the Lua lock is busy. A rebind (including one from the pause
// menu mid-run) takes effect on the next frame, since the poll reads the
// option's current key every time.
#include <cstdint>
#include <string>

namespace rsmm {

// Detours the two controls-tab builders and the duplicate-key resolver, and
// resolves the engine calls. Gated on va_globals_trusted() (the option vtable,
// the manager and the key table are VA globals). Needs install_input_hooks()
// to be live for registration and presses.
bool install_keybind_hooks();

// True once the menu and resolver hooks are installed.
bool keybinds_armed();

// True once the declared bindings have been registered with the game.
bool keybinds_registered();

// True when registration gave up for the session (the options manager could
// not be read): no rows and no presses will appear.
bool keybinds_failed();

// Declare a binding for `mod`. Returns its index (>= 0), or -1 with `err` set.
// Re-declaring the same mod + id returns the existing index (hot reload).
// kb is a keyboard / mouse key id (1-93), pad a gamepad key id (94-255);
// 0 = unbound for either.
int keybind_add(const std::string& mod, const std::string& id, const std::string& label,
                std::uint32_t kb, std::uint32_t pad, std::string* err);

// Current keys of binding `index`, from a snapshot the input poll publishes
// every frame (the defaults until registration). Safe from any thread. False
// when the index is unknown.
bool keybind_keys(int index, std::uint32_t* kb, std::uint32_t* pad);

// Called by the input poll detour after the original poll, on the game thread.
void keybinds_on_poll();

} // namespace rsmm
