// Native-UI button press bridge — see hook_ui.h for the why.
//
// There is NO click-only choke-point function on this build (the old
// FUN_14069f8e0 was inlined away). UiButton_PressCommit (FUN_1406a08a0) is a
// generic widget STATE-COMMIT driver with 35 callers — hover, focus, release,
// everything funnels through it. Detouring it naively was playtest #6's
// in-menu crash: ui:press fired per state change, and skipping the original
// for listenerless widgets suppressed real state transitions.
//
// The press discriminator is the CALLER, not the callee: UiButton_InputPoll's
// press branch calls the driver from exactly one site, only after the full
// pressed-gate (input flags, visibility, widget state != 4). So the detour
// compares _ReturnAddress() against that site (UiButton_PressReturnSite) and
// treats everything else as pass-through. Emits `ui:press` to Lua with
// candidate name strings scanned from the widget desc. RE background in
// docs/_re/kinds/ui-menus.md.

#include <windows.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include "MinHook.h"
#include "loader.h"
#include "mem_safe.h"
#include "fn_resolver.h"
#include "hook_util.h"
#include "script_lua.h"
#include "symbols.gen.h"
#include "hook_ui.h"

#if defined(_MSC_VER)
#include <intrin.h>
#define RSMM_RETURN_ADDRESS() _ReturnAddress()
#else
#define RSMM_RETURN_ADDRESS() __builtin_return_address(0)
#endif

namespace rsmm {
namespace {

using PressCommit_t = void (*)(void*);
PressCommit_t g_real_press_commit = nullptr;

// Runtime VA of UiButton_PressReturnSite (poll press-branch return address),
// slide-adjusted at install. 0 = filter unavailable => hook stays disabled.
std::uintptr_t g_press_ra = 0;

// Confirm [p, p+size) is committed + readable (MinGW has no __try/__except).
// Shared implementation in mem_safe.cpp — it also rejects wrapping ranges
// (sentinel qwords like 0xffffffffffffffff appear in UI list slots, and
// `a + size` wrapping made the old local loop return true vacuously: the
// 2026-07-06 in-book crash) and pages without a readable protection bit.
inline bool readable(const void* p, std::size_t size) { return mem_readable(p, size); }

// Plausible widget/entity identifier: printable ASCII, 2..63 chars.
int ident_len(const char* s) {
    int n = 0;
    while (n < 64) {
        char c = s[n];
        if (c == '\0') break;
        if (c < 0x20 || c > 0x7e) return 0;
        ++n;
    }
    return (n >= 2 && n < 64) ? n : 0;
}

void append_json_escaped(std::string& out, const char* s, int len) {
    for (int i = 0; i < len; ++i) {
        char c = s[i];
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else out += c;
    }
}

// Pinned by the 2026-07-06 playtest (candidate-offset capture):
//   widget+0x1e8 -> char* localized LABEL text ("Quit to desktop")
//   widget+0x280 -> char* widget NAME ("OPTION_BUTTON", "Next_Button", ...)
constexpr std::size_t kLabelOff = 0x1e8;
constexpr std::size_t kNameOff  = 0x280;

// Scan the widget struct's first kScanQwords pointer slots for C strings.
// Kept alongside the pinned fields: widget subclasses may move the slots,
// and the candidate list is what pinned them in the first place.
constexpr std::size_t kScanQwords = 0xc0;  // 0x600 bytes; widget vcall sits at +0x570

// Returns the identifier-looking C string at *(widget+off), or nullptr.
const char* string_field(void* widget, std::size_t off, int& len) {
    auto* q = reinterpret_cast<std::uint8_t*>(widget);
    auto* s = *reinterpret_cast<const char**>(q + off);
    if (!readable(s, 64)) return nullptr;
    len = ident_len(s);
    return len ? s : nullptr;
}

void emit_press_event(void* widget) {
    std::string payload = "{\"widget\":\"";
    char hex[32];
    std::snprintf(hex, sizeof(hex), "0x%llx",
                  static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(widget)));
    payload += hex;
    payload += '"';
    if (readable(widget, kNameOff + 8)) {
        int len = 0;
        if (const char* s = string_field(widget, kNameOff, len)) {
            payload += ",\"name\":\"";
            append_json_escaped(payload, s, len);
            payload += '"';
        }
        if (const char* s = string_field(widget, kLabelOff, len)) {
            payload += ",\"label\":\"";
            append_json_escaped(payload, s, len);
            payload += '"';
        }
    }
    payload += ",\"strings\":[";

    bool first = true;
    if (readable(widget, kScanQwords * 8)) {
        auto* q = reinterpret_cast<std::uintptr_t*>(widget);
        int emitted = 0;
        for (std::size_t i = 0; i < kScanQwords && emitted < 12; ++i) {
            auto* s = reinterpret_cast<const char*>(q[i]);
            if (!readable(s, 64)) continue;
            int len = ident_len(s);
            if (len == 0) continue;
            if (!first) payload += ',';
            first = false;
            std::snprintf(hex, sizeof(hex), "0x%llx",
                          static_cast<unsigned long long>(i * 8));
            payload += "{\"off\":\"";
            payload += hex;
            payload += "\",\"s\":\"";
            append_json_escaped(payload, s, len);
            payload += "\"}";
            ++emitted;
        }
    }
    payload += "]}";
    // Log the first presses so the widget name offset can be pinned from the
    // loader log alone (no subscriber mod needed), then go quiet.
    static int g_logged = 0;
    if (g_logged < 24) {
        ++g_logged;
        Loader::get().log("[ui-hook] press " + payload);
    }
    script_emit_event_json("ui:press", payload);
}

// On the press path the driver vcalls slot 2 on *(widget+0x570) (the press
// listener) with NO null check. Widgets we add from mod data (cloned button
// descs the page controller never wired) can have a null listener — running
// the original on a confirmed press of one would deref null. Those are the
// ONLY calls the detour may skip; suppressing the driver for native widgets
// is what corrupted menu state in playtest #6.
constexpr std::size_t kListenerOff = 0x570;

bool has_press_listener(void* widget) {
    auto* q = reinterpret_cast<std::uint8_t*>(widget);
    if (!readable(q + kListenerOff, 8)) return false;
    auto* listener = *reinterpret_cast<void**>(q + kListenerOff);
    if (!readable(listener, 8)) return false;
    auto* vft = *reinterpret_cast<void**>(listener);
    return readable(vft, 3 * 8);
}

void hook_press_commit(void* widget) {
    // MinHook patches the callee, so our frame's return address IS the
    // engine caller's return site. Only the poll's press branch counts as
    // a confirmed ButtonUi press; the driver's other 34 callers (hover /
    // focus / release fan-out) pass through untouched.
    const bool press =
        reinterpret_cast<std::uintptr_t>(RSMM_RETURN_ADDRESS()) == g_press_ra;
    if (press && widget && !has_press_listener(widget)) {
        static int g_skipped = 0;
        if (g_skipped < 8) {
            ++g_skipped;
            Loader::get().log("[ui-hook] press on listenerless widget - "
                              "skipping native commit (null listener vcall), "
                              "emitting event only");
        }
        emit_press_event(widget);
        return;
    }
    if (g_real_press_commit) g_real_press_commit(widget);
    if (press && widget) emit_press_event(widget);
}

} // anonymous namespace

bool install_ui_hooks() {
    if (!flag_enabled("RSMM_ENABLE_UI_HOOK")) {
        Loader::get().log("[ui-hook] disabled (set RSMM_ENABLE_UI_HOOK=1 to arm)");
        return false;
    }
    if (!fn_resolver_init()) {
        Loader::get().log("[ui-hook] fn_resolver_init failed");
        return false;
    }
    std::uintptr_t va = fn_resolve(Sym::UiButton_PressCommit_Pattern);
    if (va == 0 || va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log("[ui-hook] UiButton_PressCommit pattern not found; disabled");
        return false;
    }
    if (!fn_verify(Sym::UiButton_PressCommit_Pattern, va)) {
        Loader::get().log("[ui-hook] UiButton_PressCommit verify failed (game patched?)");
        return false;
    }

    // The press discriminator: the return site of the poll's press-branch
    // call. Resolved as poll + fixed internal offset (the anchor-symbol
    // convention, see hook_items.cpp) and then PROVEN before arming: the five
    // bytes ending at the site must be `e8 rel32` whose target is the
    // resolved driver. Any drift after a game patch fails closed here instead
    // of mis-classifying presses at runtime.
    constexpr std::uintptr_t kPressRaOff =
        Sym::UiButton_PressReturnSite - Sym::UiButton_InputPoll;
    static_assert(kPressRaOff == 0xe2,
                  "symbol map press-site offset drifted from the poll's press branch");
    std::uintptr_t poll = fn_resolve(Sym::UiButton_InputPoll_Pattern);
    if (poll == 0 || poll == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log("[ui-hook] UiButton_InputPoll pattern not found; disabled");
        return false;
    }
    const std::uintptr_t press_ra = poll + kPressRaOff;
    const auto* site = reinterpret_cast<const std::uint8_t*>(press_ra - 5);
    if (!readable(site, 5) || site[0] != 0xE8) {
        Loader::get().log("[ui-hook] press site is not a call instruction "
                          "(game patched?); disabled");
        return false;
    }
    std::int32_t rel = 0;
    std::memcpy(&rel, site + 1, sizeof(rel));
    if (press_ra + rel != va) {
        Loader::get().log("[ui-hook] press-site call does not target "
                          "UiButton_PressCommit (game patched?); disabled");
        return false;
    }
    g_press_ra = press_ra;

    if (!hook_install_at("ui-hook", "UiButton_PressCommit", va,
                         reinterpret_cast<void*>(&hook_press_commit),
                         reinterpret_cast<void**>(&g_real_press_commit))) {
        return false;
    }
    char b[80];
    std::snprintf(b, sizeof(b), "0x%llx (press-site ra 0x%llx)",
                  static_cast<unsigned long long>(va),
                  static_cast<unsigned long long>(press_ra));
    Loader::get().log(std::string("[ui-hook] installed on UiButton_PressCommit @ ") + b
                      + " -> R.on('ui:press')");
    return true;
}

} // namespace rsmm
