#pragma once
// The in-game mod menu drawn by hook_overlay, laid out like the game's own
// Settings book: installed mods on the left page, the selected mod's details
// and its config_schema.toml fields on the right, edited live through
// config.toml, which R.config already reloads. Styled with the game's own UI
// art and bitmap fonts from the UI pack `rsmm install-loader` decodes into
// <game>/rsmm/ui/ (rsmm.engine.ui_pack); without a pack it draws plain stand-ins.
//
// Threads: menu_init runs on the loader thread before any Present; every
// other call is made from Present under hook_overlay's render lock.

#include <cstdint>
#include <filesystem>

#include "imgui.h"

namespace rsmm::overlay {

// Uploads straight RGBA8 rows and returns the texture for ImGui, or 0.
// Only valid inside menu_upload (the renderer owns the resource).
using UploadFn = ImTextureID (*)(int w, int h, const std::uint8_t* rgba);

// Read the UI pack and every installed mod's manifest, schema and values.
void menu_init(const std::filesystem::path& game_dir);
// After ImGui::CreateContext: add the game fonts and the game's colours.
void menu_setup_imgui(float scale);
// After each renderer (re)creation: upload the pack's textures.
void menu_upload(UploadFn upload);
// Before the renderer is torn down: the uploaded textures are about to go.
void menu_forget_textures();
// The UI pack's pixels for `key` (RGBA8 straight alpha), or nullptr.
const std::uint8_t* menu_texture_pixels(const char* key, int* w, int* h);
// Draw one frame of the flat book over the screen (no game book to paint on).
// Returns false when the menu asked to close.
bool menu_draw();
// Draw both pages, `page` x `page` pixels each side by side from (0, 0), for
// painting onto the game's own book (book_warp). Returns false on close.
bool menu_draw_pages(float page);
// While the game's escape menu is open: draw only the Mods button that opens
// the menu, in the escape menu's own button art, as the next entry of its
// column below `vanilla_buttons` buttons. Returns true when clicked.
bool menu_escape_button(int vanilla_buttons);

} // namespace rsmm::overlay
