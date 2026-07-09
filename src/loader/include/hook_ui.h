#pragma once
namespace rsmm {

// Native-UI button press bridge (toward the in-game mod menu).
//
// Every ButtonUi click funnels through one engine routine,
// UiButton_PressCommit (FUN_14069f8e0): the per-frame poll task
// UiButton_InputPoll (FUN_1407d6210) walks all live oCEntityCpntButtonUi
// cpnts and, for each pressed button that passes its visibility/enable/
// focus gates, calls PressCommit(*(cpnt+0x268)) with the widget desc. The
// commit runs the widget press state machine (+0x32c/+0x328) and then
// fires the owning controller's oINavigableListener via a vcall on
// *(widget+0x570). See docs/_re/kinds/ui-menus.md.
//
// We POST-detour PressCommit: forward to the original, then emit the Lua
// event `ui:press` with the widget address and every plausible name
// string found by a bounded scan of the widget struct (the exact name
// offset is pinned empirically from these candidates during playtest).
// Read-only with respect to engine state; the widget is only scanned.
//
// Opt-in via RSMM_ENABLE_UI_HOOK=1 (env or desktop loader-flags file).
bool install_ui_hooks();

} // namespace rsmm
