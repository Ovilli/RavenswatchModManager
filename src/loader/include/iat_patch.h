#pragma once
// One path for patching a module's import address table. Used by hook_io
// (CreateFileW) and hook_backend (EOS / Steam API imports).
//
// An IAT patch redirects the calls ONE module makes to an imported function,
// without touching the function itself: no detour, no .pdata question, and it
// works on functions living in another DLL (EOS SDK, steam_api64).

#include <windows.h>

#include <cstdint>
#include <string_view>

namespace rsmm {

// Point `mod`'s import of `target_fn` from `target_dll` at `new_fn`.
//   out_old  receives the previous slot value, only if *out_old is still null
//            (so a second patch of the same import keeps the true original).
//   tag      subsystem name for the log line if the slot cannot be made writable.
// Returns the patched slot, or nullptr when the import is absent or the slot
// could not be written. Keep the slot if you need to undo the patch.
std::uintptr_t* iat_patch(HMODULE mod, const char* target_dll, const char* target_fn,
                          void* new_fn, void** out_old, std::string_view tag);

// Put `original` back into `slot`, but only while it still holds `ours`: if
// something hooked the same slot after us, clobbering it would unhook them too.
// Returns true when the slot was restored.
bool iat_restore(std::uintptr_t* slot, std::uintptr_t original, std::uintptr_t ours);

} // namespace rsmm
