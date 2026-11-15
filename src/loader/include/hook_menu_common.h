#pragma once
// Helpers shared by the detours that build in-game Settings UI:
// hook_settings_menu.cpp (the Mods tab), hook_book_pages.cpp (R.ui.menus pages)
// and hook_keybinds.cpp (mod rows on the Controls tabs).
//
// Each of those files used to carry its own copy of the oCString literal
// wrapper, the title clip, the controller / row offsets, the tab readers and
// the row-spawn sequence. Offsets are read from the Settings build, see the
// symbol notes in data/symbols.json (category "ui").

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "hook_util.h"
#include "mem_safe.h"
#include "symbols.gen.h"
#include "symbols_api.gen.h"

namespace rsmm::menu {

// oCString: {char*, u32 len | 0x80000000 literal, u32 cap}. The literal bit makes
// the engine alias the bytes instead of copying them, so the string handed to
// lit() has to outlive whatever the engine does with the result.
struct OcStr {
    const char* p;
    std::uint32_t len;
    std::uint32_t cap;
};
constexpr std::uint32_t kLiteral = 0x80000000u;
inline OcStr lit(const std::string& s) {
    return {s.c_str(), std::uint32_t(s.size()) | kLiteral, 0};
}

// Longer titles run into the row's arrows.
constexpr std::size_t kMaxTitle = 32;
inline std::string clip(std::string s) {
    if (s.size() > kMaxTitle) s = s.substr(0, kMaxTitle - 2) + "..";
    return s;
}

// Options controller
constexpr std::uintptr_t kCtrlSettings   = 0x10;    // controller -> settings object
constexpr std::uintptr_t kCtrlTabs       = 0x208;   // POINTER to the tab-entry vector
constexpr std::uintptr_t kCtrlTabCount   = 0x210;
constexpr std::uintptr_t kCtrlFactory    = 0x228;   // controller -> element factory
constexpr std::uintptr_t kTabStride      = 0x48;
constexpr std::uintptr_t kTabButton      = 0x10;
// Settings object
constexpr std::uintptr_t kSetStringItem  = 0x3a8;   // Option_StringItem template
// Category and row
constexpr std::uintptr_t kCatRowParent   = 0x08;
constexpr std::uintptr_t kRowArrowL      = 0x50;
constexpr std::uintptr_t kRowArrowR      = 0x58;
constexpr std::uintptr_t kRowValue       = 0x98;
constexpr std::uintptr_t kRowLabels      = 0xa0;
constexpr std::uintptr_t kRowLocked      = 0xb0;
constexpr std::uint32_t  kCatType        = 5;       // plain multi-choice tab

// The engine calls the multi-choice row builders go through.
struct MenuFns {
    engine::OptionsMenu_AddCategory_fn      add_category = nullptr;
    engine::OptionsMenu_SpawnMultiChoice_fn spawn_row    = nullptr;
    engine::OptionsMenu_AppendRow_fn        append_row   = nullptr;
    engine::OptionsMenuElement_SetTitle_fn  set_title    = nullptr;
    engine::StringVector_AssignFromArray_fn set_labels   = nullptr;
};

// Resolve all five; stops at the first one that does not.
inline bool resolve_menu_fns(std::string_view tag, MenuFns& f) {
    return resolve_checked(tag, "add category", Sym::OptionsMenu_AddCategory_Pattern, &f.add_category)
        && resolve_checked(tag, "spawn row", Sym::OptionsMenu_SpawnMultiChoice_Pattern, &f.spawn_row)
        && resolve_checked(tag, "append row", Sym::OptionsMenu_AppendRow_Pattern, &f.append_row)
        && resolve_checked(tag, "set title", Sym::OptionsMenuElement_SetTitle_Pattern, &f.set_title)
        && resolve_checked(tag, "set labels", Sym::StringVector_AssignFromArray_Pattern, &f.set_labels);
}

// One literal oCString per text. `texts` has to outlive `labels`.
inline void build_labels(const std::vector<std::string>& texts, std::vector<OcStr>& labels) {
    labels.clear();
    for (const auto& s : texts) labels.push_back(lit(s));
}

// Mirrors the vanilla builder for one multi-choice row, in its order:
//   row = SpawnMultiChoice(factory, settings+kSetStringItem, row_parent)
//   AppendRow(&ctrl, cat, row)
//   row+kRowValue = value; labels -> row+kRowLabels; row+kRowLocked = null
//   SetTitle(row, &title)     // re-reads row+kRowValue
// `value`, `labels` and `title` are aliased by the game, so the caller keeps them
// alive. Returns the row, or nullptr when the engine hands back nothing usable.
inline void* spawn_menu_row(const MenuFns& fn, void* ctrl, void* settings, void* factory,
                            void* cat, void* row_parent, std::uint32_t* value,
                            std::vector<OcStr>& labels, const std::string& title) {
    void* row = fn.spawn_row(factory, reinterpret_cast<std::uint8_t*>(settings) + kSetStringItem,
                             row_parent);
    if (!row || !mem_writable(reinterpret_cast<std::uint8_t*>(row) + kRowValue, 0x20)) {
        return nullptr;
    }
    void* ctx = ctrl;
    fn.append_row(&ctx, cat, row);
    auto* p = reinterpret_cast<std::uint8_t*>(row);
    *reinterpret_cast<std::uint32_t**>(p + kRowValue) = value;
    fn.set_labels(p + kRowLabels, labels.data(), std::uint32_t(labels.size()));
    *reinterpret_cast<void**>(p + kRowLocked) = nullptr;
    OcStr t = lit(title);
    fn.set_title(row, &t);
    return row;
}

// The tab count as the controller holds it. False (leaving *out alone) when the
// field is not readable.
inline bool read_tab_count(void* ctrl, std::uint32_t* out) {
    return mem_load(reinterpret_cast<std::uintptr_t>(ctrl) + kCtrlTabCount, out);
}

// The button of tab `idx`, nullptr when the tab vector or the entry is unreadable.
inline void* tab_button(void* ctrl, std::uint32_t idx) {
    const auto c = reinterpret_cast<std::uintptr_t>(ctrl);
    std::uintptr_t tabs = 0;
    std::uint32_t count = 0;
    void* btn = nullptr;
    if (!mem_load(c + kCtrlTabs, &tabs) || !tabs
        || !mem_load(c + kCtrlTabCount, &count) || idx >= count
        || !mem_load(tabs + idx * kTabStride + kTabButton, &btn)) return nullptr;
    return btn;
}

} // namespace rsmm::menu
