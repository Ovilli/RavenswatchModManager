// TLS-callback pre-entry-point hook hoist.
//
// Anti-tamper integrity sweeps run very early in `Ravenswatch.exe`'s
// startup, before our `DllMain` finishes spinning up the loader thread.
// By the time MinHook tries to patch a target, AT has already snapshotted
// the .text section and any later overwrite trips an integrity check.
//
// TLS callbacks fire EARLIER than `DllMain` for the EXE's own entry, and
// EARLIER than DllMain for loaded DLLs at `DLL_PROCESS_ATTACH` as well —
// they're the first user code to run after the loader maps the image.
//
// We use a TLS callback in our `winhttp.dll` to install MinHook + queue
// any pre-hooks BEFORE the EXE's `_DllMainCRTStartup` runs. The actual
// hook installation is gated by RSMM_TLS_HOOK=1 so we can ship the
// scaffold without flipping the switch by default.
//
// Build wiring: this object must be linked into the DLL such that the
// `.CRT$XLB` section is preserved. MSVC handles that via the `#pragma`
// directives at the bottom; MinGW with LLD typically keeps the section
// because of the `__USED__` attribute.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "MinHook.h"

namespace rsmm {

// Called from our normal DllMain after the loader thread is up. The
// queued hooks installed by the TLS path are also re-armed here for
// safety in case some early path bypassed us.
void tls_replay_pending_hooks();

}  // namespace rsmm

extern "C" {

// Single shared flag: 0 = TLS path skipped (default), 1 = MinHook init
// happened in the TLS phase, 2 = TLS phase errored.
volatile LONG rsmm_tls_status = 0;

static bool _env_truthy(const char* name) {
    char buf[8] = {0};
    DWORD n = GetEnvironmentVariableA(name, buf, sizeof(buf));
    return n > 0 && buf[0] == '1';
}

static void NTAPI rsmm_tls_callback(PVOID /*DllHandle*/, DWORD reason, PVOID /*Reserved*/) {
    if (reason != DLL_PROCESS_ATTACH) return;

    // Gate: opt-in only during the trial period. We don't want the
    // default install to take a less-tested code path.
    if (!_env_truthy("RSMM_TLS_HOOK")) {
        InterlockedExchange(&rsmm_tls_status, 0);
        return;
    }

    // MinHook is safe to call before CRT init: it does no global
    // construction beyond a few atomics, and its `MH_Initialize` only
    // touches the heap via VirtualAlloc.
    MH_STATUS s = MH_Initialize();
    if (s != MH_OK && s != MH_ERROR_ALREADY_INITIALIZED) {
        InterlockedExchange(&rsmm_tls_status, 2);
        return;
    }
    InterlockedExchange(&rsmm_tls_status, 1);

    // We DO NOT actually arm hooks here yet. The TLS-phase value is in
    // running ahead of anti-tamper; the hooks themselves are still
    // installed by `loader_thread()` in dllmain.cpp once the loader
    // has scanned mods and knows what to patch. Once a target list is
    // computed before the TLS phase (e.g. via an env var or sidecar
    // JSON), patch installation moves here.
}

}  // extern "C"

// --- Section placement (so the linker keeps the callback) -------------

#if defined(_MSC_VER)
// MSVC: register via the CRT's TLS dispatcher table. The CRT looks for a
// non-null entry in `.CRT$XLB`; we add one of our own.
#  pragma section(".CRT$XLB", long, read)
extern "C" __declspec(allocate(".CRT$XLB"))
    PIMAGE_TLS_CALLBACK rsmm_tls_xlb = rsmm_tls_callback;
#elif defined(__MINGW32__) || defined(__MINGW64__)
// MinGW: same .CRT$XLB section, but with a GCC attribute so the linker
// (LLD or BFD) doesn't strip it.
__attribute__((section(".CRT$XLB"), used))
PIMAGE_TLS_CALLBACK rsmm_tls_xlb = rsmm_tls_callback;
#else
// Unknown toolchain: leave the symbol but warn loudly at build time.
#  warning "RSMM TLS callback won't be linked on this toolchain. R.hook will degrade."
PIMAGE_TLS_CALLBACK rsmm_tls_xlb = rsmm_tls_callback;
#endif

namespace rsmm {

void tls_replay_pending_hooks() {
    // Hook target queueing not implemented in this scaffold; see the
    // TLS-callback section in docs/SDK_V3.md for the planned design.
    // Today, the loader thread's normal install path runs regardless.
}

}  // namespace rsmm
