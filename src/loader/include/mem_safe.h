#pragma once
// One page-state guard for the whole loader.
//
// Every detour in here reads game memory at offsets derived by RE. When an
// offset is stale (game patch) or a captured pointer is garbage, an unguarded
// read access-violates and takes the whole game down — and MinGW has no
// __try/__except, so there is no cheap recovery. The rule is therefore: probe
// with VirtualQuery first, and treat "can't prove it's readable" as "don't
// read it".
//
// This used to be five near-copies of the same helper (hook_ui, hook_skills,
// hook_spawn, hook_rewards, hook_events, script_lua), and they had drifted:
// three never checked the protection bits at all (so a PAGE_EXECUTE-only page
// passed), two never checked for address wrap (so `addr + size` overflowing
// made the loop run zero times and return true — the 2026-07-06 in-book
// crash), and one had a `need_write` branch with an empty body. Single
// implementation, single set of guards.

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace rsmm {

// True when the whole range [addr, addr+size) is committed and readable
// (and writable too, when `need_write`). Cheap enough for detour paths:
// one VirtualQuery per distinct memory region, which for a struct read is 1.
bool mem_accessible(std::uintptr_t addr, std::size_t size, bool need_write = false);

inline bool mem_readable(const void* p, std::size_t size) {
    return mem_accessible(reinterpret_cast<std::uintptr_t>(p), size, false);
}
inline bool mem_writable(const void* p, std::size_t size) {
    return mem_accessible(reinterpret_cast<std::uintptr_t>(p), size, true);
}

// Guarded typed load. Returns false (leaving `out` untouched) when the source
// range isn't provably readable, so callers can write
// `if (!mem_load(p, &v)) return;` instead of an unguarded deref.
template <typename T>
inline bool mem_load(std::uintptr_t addr, T* out) {
    if (!mem_accessible(addr, sizeof(T), false)) return false;
    std::memcpy(out, reinterpret_cast<const void*>(addr), sizeof(T));
    return true;
}
template <typename T>
inline bool mem_load(const void* p, T* out) {
    return mem_load(reinterpret_cast<std::uintptr_t>(p), out);
}

// Guarded typed load with a fallback, for the common "read or default" shape.
template <typename T>
inline T mem_load_or(std::uintptr_t addr, T fallback) {
    T v{};
    return mem_load(addr, &v) ? v : fallback;
}

// Copy a NUL-terminated string out of possibly-unmapped memory into `out`
// (always NUL-terminated). Stops at the first byte that isn't provably
// readable, so a non-terminated string at a page boundary can't fault.
// Returns the number of characters written (excluding the terminator).
std::size_t mem_read_cstr(std::uintptr_t addr, char* out, std::size_t cap);

} // namespace rsmm
