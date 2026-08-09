#include "hook_util.h"

#include "fn_resolver.h"
#include "loader.h"

#include "MinHook.h"

#include <string>

namespace rsmm {
namespace {

std::string hex_of(std::uintptr_t v) {
    char b[32];
    snprintf(b, sizeof(b), "0x%llx", static_cast<unsigned long long>(v));
    return b;
}

std::string prefix(std::string_view tag) {
    return "[" + std::string(tag) + "] ";
}

// Shared tail: .pdata entry-point check + create + enable. `va` must already
// be resolved and (where a pattern exists) verified.
bool arm(std::string_view tag, std::string_view what, std::uintptr_t va,
         void* detour, void** trampoline, EntryCheck check) {
    if (!fn_is_function_start(va)) {
        if (check == EntryCheck::Require) {
            Loader::get().log(prefix(tag) + "REFUSING to hook " + std::string(what)
                              + " @ " + hex_of(va) + ": not a function start "
                              "(.pdata). A detour here would splice a jump into "
                              "the middle of a live function instead of "
                              "intercepting a call.");
            return false;
        }
        Loader::get().log(prefix(tag) + "WARNING " + std::string(what) + " @ "
                          + hex_of(va) + " is not listed in .pdata. That is "
                          "normal for a true leaf function and WRONG for "
                          "anything else — if the game crashes, this address "
                          "is the first suspect.");
    }
    auto* target = reinterpret_cast<LPVOID>(va);
    const auto rc = MH_CreateHook(target, detour,
                                  reinterpret_cast<LPVOID*>(trampoline));
    if (rc != MH_OK) {
        Loader::get().log(prefix(tag) + "MH_CreateHook " + std::string(what)
                          + " failed rc=" + std::to_string(static_cast<int>(rc)));
        return false;
    }
    if (MH_EnableHook(target) != MH_OK) {
        // Leaving a created-but-disabled hook registered keeps MinHook holding
        // a pointer into this DLL's .text across a dynamic unload, so retire it
        // rather than reporting a half-installed success.
        Loader::get().log(prefix(tag) + "MH_EnableHook " + std::string(what)
                          + " failed");
        MH_RemoveHook(target);
        return false;
    }
    Loader::get().log(prefix(tag) + "hooked " + std::string(what) + " @ "
                      + hex_of(va));
    return true;
}

// resolve + verify, shared by the hook and call-only paths.
bool resolve_and_verify(std::string_view tag, std::string_view what,
                        std::string_view pattern_name, std::uintptr_t* out) {
    if (!fn_resolver_init()) {
        Loader::get().log(prefix(tag) + "fn_resolver_init failed");
        return false;
    }
    const auto va = fn_resolve(pattern_name);
    if (va == 0 || va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log(prefix(tag) + "resolve " + std::string(pattern_name)
                          + " failed (" + std::string(what)
                          + "); capability disabled");
        return false;
    }
    if (!fn_verify(pattern_name, va)) {
        Loader::get().log(prefix(tag) + "verify " + std::string(pattern_name)
                          + " @ " + hex_of(va) + " mismatch (game patched?)");
        return false;
    }
    *out = va;
    return true;
}

} // namespace

bool hook_install(std::string_view tag, std::string_view what,
                  std::string_view pattern_name, void* detour,
                  void** trampoline, std::uintptr_t* out_va) {
    std::uintptr_t va = 0;
    if (!resolve_and_verify(tag, what, pattern_name, &va)) return false;
    if (!arm(tag, what, va, detour, trampoline, EntryCheck::Require)) return false;
    if (out_va) *out_va = va;
    return true;
}

bool hook_install_at(std::string_view tag, std::string_view what,
                     std::uintptr_t va, void* detour, void** trampoline,
                     EntryCheck check) {
    if (va == 0 || va == static_cast<std::uintptr_t>(-1)) {
        Loader::get().log(prefix(tag) + "null target for " + std::string(what));
        return false;
    }
    return arm(tag, what, va, detour, trampoline, check);
}

bool resolve_checked(std::string_view tag, std::string_view what,
                     std::string_view pattern_name, void** out) {
    std::uintptr_t va = 0;
    if (!resolve_and_verify(tag, what, pattern_name, &va)) return false;
    if (!fn_is_function_start(va)) {
        Loader::get().log(prefix(tag) + "REFUSING to call " + std::string(what)
                          + " @ " + hex_of(va) + ": not a function start "
                          "(.pdata); the pattern matches mid-function, so this "
                          "is not the routine it claims to be.");
        return false;
    }
    *out = reinterpret_cast<void*>(va);
    Loader::get().log(prefix(tag) + "resolved " + std::string(what) + " @ "
                      + hex_of(va));
    return true;
}

bool hook_entry_warn(std::string_view tag, std::string_view what,
                     std::uintptr_t va) {
    if (va == 0 || va == static_cast<std::uintptr_t>(-1)) return false;
    if (fn_is_function_start(va)) return true;
    Loader::get().log(prefix(tag) + "WARNING " + std::string(what) + " @ "
                      + hex_of(va) + " is not listed in .pdata. That is normal "
                      "for a true leaf function and WRONG for anything else — "
                      "if the game crashes, this address is the first suspect.");
    return true;
}

void hook_remove(std::uintptr_t va) {
    if (!va) return;
    auto* p = reinterpret_cast<LPVOID>(va);
    MH_DisableHook(p);
    MH_RemoveHook(p);
}

} // namespace rsmm
