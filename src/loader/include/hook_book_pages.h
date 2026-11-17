#pragma once
#include <string>

namespace rsmm {

// R.ui.menus: mod-made pages in the game's book, and entries on its Settings
// page (design: docs/2026-11-12-r-ui-menus.md in the RSMM workspace). A page
// is a real BookOptions page: we open it with the game's own BookPage_OpenChild
// (the call Credits uses), let the vanilla builders run, hide their tabs and
// add our categories and rows through the same helpers hook_settings_menu.cpp
// uses. No Lua-side drawing, no page cook.
//
// Armed at startup; RSMM_DISABLE_UI_MENUS=1 (env or desktop loader-flags file)
// switches it off. Lua reaches it through rsmm._internal.ui_menus_*.
bool install_book_page_hooks();

bool book_pages_available(std::string* why);

// Called from hook_settings_menu.cpp's tab-builder detour, after the original.
// True while OUR page's controller is being built.
bool book_pages_building(void* ctrl);
// Add our categories (and nested entries) to our page.
void book_pages_build(void* ctrl, void* page, void* parent);
// Add the "settings" entries to the vanilla Settings page.
void book_pages_add_entries(void* ctrl, void* page, void* parent);

// Lua side. Each returns false and sets *why on refusal.
bool book_pages_set_page(const std::string& id, const std::string& snapshot_json,
                         std::string* why);
void book_pages_remove_page(const std::string& id);
bool book_pages_set_entry(const std::string& id, const std::string& title,
                          const std::string& page_id, const std::string& after,
                          std::string* why);
void book_pages_remove_entry(const std::string& id);
// ctx_json: nullptr = no context. Queued; runs on the game thread.
// need_open_leaf = false: for loader callers that open the page together with
// Settings (the pause-menu Mods button): skips the "a page is open" check and
// depth is the Settings page's (0); the request waits for the next host Update.
bool book_pages_open(const std::string& page_id, const std::string* ctx_json,
                     std::string* why, bool need_open_leaf = true);
bool book_pages_back(std::string* why);
bool book_pages_current(std::string* page, std::string* ctx_json, int* depth);
void book_pages_veto_back();

} // namespace rsmm
