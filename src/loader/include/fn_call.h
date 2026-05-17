#pragma once
// Generic function caller. Lets Lua mods invoke arbitrary game
// functions resolved by name via fn_resolver.
//
// Windows x64 calling convention only — we don't support cdecl/stdcall
// because the game's PE doesn't use them.
//
// Arg types (single-char codes):
//   'i'  int32_t   (sign-extended into 64-bit register)
//   'u'  uint32_t
//   'l'  int64_t / pointer
//   'f'  float    (xmm0..xmm3)
//   'd'  double   (xmm0..xmm3)
//   'p'  void*    (alias for 'l')
//   'v'  void     (rettype only)
//   's'  const char* (Lua string, kept alive for the call)
//
// First 4 args go in RCX/RDX/R8/R9 or XMM0..XMM3 (whichever matches
// the position by type). Remaining args spill to the stack at +0x20.

#include <cstdint>
#include <cstdarg>
#include <string_view>

namespace rsmm {

// Raw call: pass argtypes string + a contiguous u64 array of arg
// values (string-typed args pass pointers). Returns the raw 64-bit
// register result.
std::uint64_t fn_call_raw(std::uintptr_t target_va,
                          std::string_view argtypes,
                          const std::uint64_t* args);

} // namespace rsmm
