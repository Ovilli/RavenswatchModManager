// Native-UI button press bridge — see hook_ui.h for the why.
//
// Post-detours UiButton_PressCommit (FUN_14069f8e0), the single choke point
// every ButtonUi click funnels through, and emits `ui:press` to Lua with
// candidate name strings scanned from the widget desc. RE background in
// docs/_re/kinds/ui-menus.md.

#include <windows.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include "MinHook.h"
#include "loader.h"
#include "fn_resolver.h"
#include "script_lua.h"
#include "symbols.gen.h"
#include "hook_ui.h"

namespace rsmm {
namespace {

using PressCommit_t = void (*)(void*);
PressCommit_t g_real_press_commit = nullptr;

// Confirm [p, p+size) is committed + readable (MinGW has no __try/__except).
bool readable(const void* p, std::size_t size) {
    auto a = reinterpret_cast<std::uintptr_t>(p);
    if (a < 0x10000) return false;
    // Reject non-canonical / wrapping ranges: sentinel values like
    // 0xffffffffffffffff appear in UI list qwords, and `a + size` wrapping
    // to a tiny number made the VirtualQuery loop run ZERO times and fall
    // through to `return true` (the 2026-07-06 in-book crash).
    if (a >= 0x0000800000000000ull || size > 0x0000800000000000ull - a) return false;
    for (std::uintptr_t x = a; x < a + size; ) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (VirtualQuery(reinterpret_cast<void*>(x), &mbi, sizeof(mbi)) == 0) return false;
        if (mbi.State != MEM_COMMIT) return false;
        if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
        x = reinterpret_cast<std::uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
    }
    return true;
}

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

// The real commit vcalls slot 2 on *(widget+0x570) (the press listener).
// Widgets we add from mod data (cloned button descs the page controller
// doesn't know) can have no listener — running the original would call
// through null. Skip it for those; the Lua event is the whole point.
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
    if (widget && !has_press_listener(widget)) {
        static int g_skipped = 0;
        if (g_skipped < 8) {
            ++g_skipped;
            Loader::get().log("[ui-hook] press on listenerless widget - "
                              "skipping native commit, emitting event only");
        }
        emit_press_event(widget);
        return;
    }
    if (g_real_press_commit) g_real_press_commit(widget);
    if (widget) emit_press_event(widget);
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

    const auto target = reinterpret_cast<LPVOID>(va);
    auto rc = MH_CreateHook(target,
                            reinterpret_cast<LPVOID>(&hook_press_commit),
                            reinterpret_cast<LPVOID*>(&g_real_press_commit));
    if (rc != MH_OK) {
        Loader::get().log("[ui-hook] MH_CreateHook failed rc="
                          + std::to_string(static_cast<int>(rc)));
        return false;
    }
    if (MH_EnableHook(target) != MH_OK) {
        Loader::get().log("[ui-hook] MH_EnableHook failed");
        return false;
    }
    char b[32];
    std::snprintf(b, sizeof(b), "0x%llx", static_cast<unsigned long long>(va));
    Loader::get().log(std::string("[ui-hook] installed on UiButton_PressCommit @ ") + b
                      + " -> R.on('ui:press')");
    return true;
}

} // namespace rsmm
