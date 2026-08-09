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
//
// Value convention: each arg slot holds the RAW register bits — 'd' is the
// double's 64 bits, 'f' is the float's 32 bits in the low half (where the ABI
// puts it). hook_lua.cpp marshals hook arguments the same way, so a value can
// travel between a hook callback and a call without re-encoding.

#include <cstdint>
#include <cstdarg>
#include <string_view>

namespace rsmm {

// Raw call assuming an integer/pointer/void return: pass argtypes string + a
// contiguous u64 array of arg values (string-typed args pass pointers).
// Returns the raw 64-bit register result.
std::uint64_t fn_call_raw(std::uintptr_t target_va,
                          std::string_view argtypes,
                          const std::uint64_t* args);

// Same, but for a target whose return type is known. A float/double return
// arrives in XMM0, not RAX, so the caller's prototype has to say so — calling
// a float-returning function through fn_call_raw yields whatever happened to
// be in RAX. Returns the raw bits per the convention above.
std::uint64_t fn_call_raw_ret(std::uintptr_t target_va,
                              char ret_code,
                              std::string_view argtypes,
                              const std::uint64_t* args);

} // namespace rsmm
