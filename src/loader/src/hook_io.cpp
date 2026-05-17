// File I/O redirection via IAT (Import Address Table) hooking.
//
// We previously patched kernel32!CreateFileW via MinHook, but Wine's
// CreateFileW is a thin forwarder layered on NtCreateFile, and patching it
// corrupts Wine's internal state -> game crashes during early Vulkan init.
//
// IAT hooking sidesteps Wine entirely: we walk Ravenswatch.exe's import
// directory, find the function-pointer slot that the game uses to call
// CreateFileW, and overwrite that slot to point at our hook. The Wine
// implementation runs untouched; only the game's own calls route through us.
//
// This catches every CreateFileW that the game makes (which is what we want
// for asset overrides). It does NOT see Wine internal calls, helper-process
// calls, or DLL calls — irrelevant for asset modding.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "loader.h"
#include "hook_io.h"

#include <atomic>
#include <string>

namespace rsmm {

using CreateFileW_t = HANDLE (WINAPI*)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES,
                                       DWORD, DWORD, HANDLE);
// Original IAT value captured at install time; kept for diagnostics but NOT
// used for forwarding. Wine's IAT entries can be per-module trampolines and
// calling them out of context crashes. We forward by calling CreateFileW
// directly through our own DLL's normal kernel32 import (which Wine wires
// up correctly because our DLL was loaded normally).
static CreateFileW_t real_CreateFileW = nullptr;

static inline HANDLE forward_CreateFileW(LPCWSTR lpFileName, DWORD dwDesiredAccess,
        DWORD dwShareMode, LPSECURITY_ATTRIBUTES sa, DWORD dwCreationDisposition,
        DWORD dwFlagsAndAttributes, HANDLE hTemplateFile) {
    return CreateFileW(lpFileName, dwDesiredAccess, dwShareMode, sa,
                       dwCreationDisposition, dwFlagsAndAttributes, hTemplateFile);
}

// Diagnostic counters; written from many threads, atomic.
static std::atomic<uint64_t> g_hook_call_count{0};
static std::atomic<uint64_t> g_hook_first_logged{0};

static HANDLE WINAPI hook_CreateFileW(LPCWSTR lpFileName, DWORD dwDesiredAccess,
                                      DWORD dwShareMode, LPSECURITY_ATTRIBUTES sa,
                                      DWORD dwCreationDisposition, DWORD dwFlagsAndAttributes,
                                      HANDLE hTemplateFile) {
    // Record that the hook was reached at all. We can't reliably read state
    // (Loader, mutexes) on the very first call if the loader thread is mid-
    // init, so do nothing here except forward.
    g_hook_call_count.fetch_add(1, std::memory_order_relaxed);

    // RSMM_IO_PASSTHROUGH=1 -> pure passthrough, no logic, no logging.
    // RSMM_IO_LOGONLY=1     -> log first call then passthrough.
    // (default)             -> full asset redirection (current behavior).
    static const bool passthrough = []{
        char b[4]; return GetEnvironmentVariableA("RSMM_IO_PASSTHROUGH", b, sizeof(b)) && b[0]=='1';
    }();
    static const bool logonly = []{
        char b[4]; return GetEnvironmentVariableA("RSMM_IO_LOGONLY", b, sizeof(b)) && b[0]=='1';
    }();

    if (passthrough) {
        return forward_CreateFileW(lpFileName, dwDesiredAccess, dwShareMode, sa,
                                dwCreationDisposition, dwFlagsAndAttributes, hTemplateFile);
    }

    if (logonly) {
        if (g_hook_first_logged.exchange(1) == 0) {
            Loader::get().log("LOGONLY: first CreateFileW hook fired");
        }
        return forward_CreateFileW(lpFileName, dwDesiredAccess, dwShareMode, sa,
                                dwCreationDisposition, dwFlagsAndAttributes, hTemplateFile);
    }

    if (lpFileName) {
        auto& L = Loader::get();
        std::wstring w(lpFileName);
        auto slash = w.find_last_of(L"\\/");
        std::wstring leaf_w = (slash == std::wstring::npos) ? w : w.substr(slash + 1);
        std::string leaf(leaf_w.begin(), leaf_w.end());
        L.note_asset_read(leaf);

        if (const auto* override_path = L.lookup_override(lpFileName)) {
            std::wstring repl = override_path->wstring();
            HANDLE h = forward_CreateFileW(repl.c_str(), GENERIC_READ, FILE_SHARE_READ,
                                        nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
            if (h != INVALID_HANDLE_VALUE) return h;
        }
    }
    return forward_CreateFileW(lpFileName, dwDesiredAccess, dwShareMode, sa,
                            dwCreationDisposition, dwFlagsAndAttributes, hTemplateFile);
}

// --- IAT walker ---------------------------------------------------------

static bool patch_iat_entry(HMODULE mod, const char* target_dll,
                            const char* target_fn, void* new_fn, void** out_old) {
    auto base = reinterpret_cast<BYTE*>(mod);
    auto* dh = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dh->e_magic != IMAGE_DOS_SIGNATURE) return false;
    auto* nh = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dh->e_lfanew);
    if (nh->Signature != IMAGE_NT_SIGNATURE) return false;

    auto& impdir = nh->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (impdir.VirtualAddress == 0) return false;

    auto* imp = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + impdir.VirtualAddress);
    for (; imp->Name; ++imp) {
        const char* name = reinterpret_cast<const char*>(base + imp->Name);
        if (_stricmp(name, target_dll) != 0) continue;

        auto* thunk     = reinterpret_cast<IMAGE_THUNK_DATA*>(base + imp->FirstThunk);
        auto* nameThunk = reinterpret_cast<IMAGE_THUNK_DATA*>(
                              base + (imp->OriginalFirstThunk ? imp->OriginalFirstThunk
                                                              : imp->FirstThunk));
        for (; thunk->u1.Function; ++thunk, ++nameThunk) {
            if (nameThunk->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;
            auto* iname = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(
                              base + nameThunk->u1.AddressOfData);
            if (strcmp(reinterpret_cast<const char*>(iname->Name), target_fn) != 0) continue;

            DWORD oldprot;
            VirtualProtect(&thunk->u1.Function, sizeof(uintptr_t),
                           PAGE_READWRITE, &oldprot);
            if (out_old && !*out_old) {
                *out_old = reinterpret_cast<void*>(thunk->u1.Function);
            }
            thunk->u1.Function = reinterpret_cast<uintptr_t>(new_fn);
            VirtualProtect(&thunk->u1.Function, sizeof(uintptr_t), oldprot, &oldprot);
            return true;
        }
    }
    return false;
}

static bool patch_module(HMODULE mod) {
    bool any = false;
    // Capture the original IAT value the FIRST time we patch it so our hook
    // calls the same target Wine wired the game up to. Using GetProcAddress
    // would give a different (and on Wine, broken) entry point.
    const char* dlls[] = { "kernel32.dll", "KERNEL32.dll",
                           "kernelbase.dll", "KERNELBASE.dll" };
    for (const char* d : dlls) {
        if (patch_iat_entry(mod, d, "CreateFileW",
                            (void*)hook_CreateFileW, (void**)&real_CreateFileW)) {
            any = true;
        }
    }
    return any;
}

void install_io_hooks() {
    // We do NOT pre-resolve real_CreateFileW. patch_iat_entry captures the
    // original slot value the first time it patches an entry; subsequent
    // patches reuse it. Only Ravenswatch.exe needs patching for asset
    // overrides — patching DLLs we ship (or Wine's winhttp clone) risks
    // routing wine-internal file IO through us, which we already saw crashes.
    HMODULE exe = GetModuleHandleW(nullptr);
    if (!exe) {
        Loader::get().log("GetModuleHandleW(NULL) returned NULL");
        return;
    }
    const bool ok = patch_module(exe);
    if (!ok || !real_CreateFileW) {
        Loader::get().log("no CreateFileW IAT entry patched in exe");
        return;
    }
    Loader::get().log("io hooks installed (IAT patched main exe, real_CreateFileW="
                      + std::to_string(reinterpret_cast<uintptr_t>(real_CreateFileW)) + ")");
}

void remove_io_hooks() {
    // IAT patching is not reversed at shutdown; the process is dying and
    // the OS reclaims memory. Leaving the slots patched is harmless.
}

} // namespace rsmm
