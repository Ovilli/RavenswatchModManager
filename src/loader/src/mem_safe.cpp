#include "mem_safe.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

namespace rsmm {

namespace {
// Highest canonical user-mode address on x64. Anything at or above this is a
// kernel / non-canonical value (the -1 sentinels that appear in half-built
// engine structs land here), and VirtualQuery on it is a waste of a syscall.
constexpr std::uintptr_t kUserMax = 0x0000800000000000ull;

constexpr DWORD kReadable = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY |
                            PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                            PAGE_EXECUTE_WRITECOPY;
constexpr DWORD kWritable = PAGE_READWRITE | PAGE_WRITECOPY |
                            PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
} // namespace

bool mem_accessible(std::uintptr_t addr, std::size_t size, bool need_write) {
    if (addr == 0 || size == 0) return false;
    // Reject the first 64 KiB (never mappable on Windows) and anything that
    // is not a canonical user-space address.
    if (addr < 0x10000) return false;
    if (addr >= kUserMax) return false;
    // Wrap guard: without it a near-max `addr` makes `addr + size` overflow,
    // the loop below runs zero iterations, and the function returns true
    // vacuously — handing the bad pointer straight through.
    if (size > kUserMax - addr) return false;

    const std::uintptr_t end = addr + size;
    for (std::uintptr_t a = addr; a < end; ) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (VirtualQuery(reinterpret_cast<void*>(a), &mbi, sizeof(mbi)) == 0) return false;
        if (mbi.State != MEM_COMMIT) return false;
        // PAGE_GUARD raises a one-shot guard exception on touch (that is how
        // stack growth works) — reading it would fault the caller.
        if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
        if (!(mbi.Protect & kReadable)) return false;
        if (need_write && !(mbi.Protect & kWritable)) return false;
        const auto region_end =
            reinterpret_cast<std::uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
        // A region that doesn't advance past `a` would spin forever, hanging
        // whichever game thread called in. VirtualQuery shouldn't return one,
        // but a hang is a worse failure than a refused read.
        if (region_end <= a) return false;
        a = region_end;
    }
    return true;
}

std::size_t mem_read_cstr(std::uintptr_t addr, char* out, std::size_t cap) {
    if (!out || cap == 0) return 0;
    out[0] = '\0';
    if (cap == 1) return 0;
    std::size_t n = 0;
    while (n < cap - 1) {
        // Probe in chunks rather than per byte: one VirtualQuery per 64 bytes
        // instead of per character. Halve on refusal so a string that ends
        // near a page boundary still copies its readable prefix.
        std::size_t chunk = cap - 1 - n;
        if (chunk > 64) chunk = 64;
        while (chunk > 0 && !mem_accessible(addr + n, chunk, false)) chunk /= 2;
        if (chunk == 0) break;
        const auto* p = reinterpret_cast<const char*>(addr + n);
        for (std::size_t i = 0; i < chunk; ++i) {
            if (p[i] == '\0') { out[n] = '\0'; return n; }
            out[n++] = p[i];
        }
    }
    out[n] = '\0';
    return n;
}

} // namespace rsmm
