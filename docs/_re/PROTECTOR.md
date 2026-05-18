# Ravenswatch.exe protector

Reverse-engineering note. Establishes whether `MinHook` / IAT / VEH-style
hooks on the game's own `.text` survive once the game is running, or
whether the protector installs a runtime integrity monitor that
invalidates them.

## Conclusion

The protector is a **one-shot unpacker stub** in section `.bind`. It
runs before the real entry point, validates the binary, optionally
decrypts a small metadata blob, and returns the real entry-point VA.
After it returns, **the protector code is not reentered**:

- no thread is created from inside the protector (no `CreateThread`,
  no `CreateRemoteThread`, no `NtCreateThreadEx`),
- no exception filter is installed (no `SetUnhandledExceptionFilter`,
  no `AddVectoredExceptionHandler`),
- no `.text` page-protection change is performed *after* the unpack
  (the protector itself does not re-VirtualProtect anything periodically),
- the only post-return tear-down zeroes the protector's own working
  buffers on stack — pure anti-forensics, not anti-hook.

This means **`MinHook` on functions inside `.text` of `Ravenswatch.exe`
works** once the loader's worker thread has settled, which is consistent
with the Phase 3 INTERNALS.md evidence (`FUN_1401145b0` and
`FUN_140487040` were hooked successfully).

The `ROADMAP.md #3` claim that an "anti-tamper integrity check"
crashes every hookpoint is **incorrect**. That observation was about
two specific hooks both of which had unrelated failure modes:

- `CreateFileW` via `MH_CreateHook` on `kernel32.dll` exports —
  Wine's `CreateFileW` is a thin forwarder layered on `NtCreateFile`
  and rewriting its prologue corrupts Wine's TEB-tracked state during
  early Vulkan init. `hook_io.cpp` sidesteps this via IAT patching of
  the game's import slot and works.
- `IDXGISwapChain::Present`-equivalent — Ravenswatch uses Vulkan,
  not D3D, so there is no `IDXGISwapChain` for the engine to use.
  The hook target was looking at the wrong API surface.

## Section layout

```
.text     0x140001000  size 0xe91ab4  EXEC|READ        — game + CRT + engine
.rdata    0x140e93000  size 0x429ace  READ
.data     0x1412bd000  size 0x190540  READ|WRITE
.pdata    0x14144e000  size 0xbdaf8   READ
CPADinfo  0x14150c000  size 0x38      READ|WRITE       — CFG cohort
_RDATA    0x14150d000  size 0xf4      READ
.fptable  0x14150e000  size 0x100     READ|WRITE       — CFG fn-pointer table
.rsrc     0x14150f000  size 0x1e260   READ
.reloc    0x14152e000  size 0x2be78   READ|DISCARDABLE
.bind     0x14155a000  size 0x39048   EXEC|READ        — protector stub
```

The PE entry-point `0x14155a310` lands inside `.bind`. The first
instruction is a `call 0x14155a315` to an immediately adjacent
function (the inner-stub) which saves all 15 GPRs, derives the
self-address (`[rsp+0x78] - 5`) and calls the big protector function
`FUN_14155a3d0` (13,788 bytes) with that self-address in `RCX`.

After `FUN_14155a3d0` returns, the inner-stub writes the return
value into `[rsp+0x78]`, restores GPRs, and a `ret` jumps to that
address. **That is the real game entry point.** It lives in `.text`.

## TLS callbacks

The exe registers two TLS callbacks via the standard
`IMAGE_DIRECTORY_ENTRY_TLS` directory:

| VA            | Symbol             | Purpose                                                    |
|---------------|--------------------|------------------------------------------------------------|
| `0x140c93e2c` | `tls_callback_0`   | MSVC `_Init_thread_callback` — walks a fn-ptr table at `rip+0x209701..0x209712` on `DLL_THREAD_ATTACH` (`edx==2`). |
| `0x140c9457c` | `tls_callback_1`   | MSVC per-thread destructor walker — runs the chained dtor list at `gs:[0x58] + N*8 + 0x20` on `DLL_PROCESS_ATTACH` or `DLL_THREAD_DETACH`. |

Both are stock Microsoft Visual C++ runtime. **Neither is part of the
protector.** No code in either callback touches `.text` or `.bind`.

## Protector flow (decompiled summary)

`FUN_14155a3d0(self_va)`:

1. Reads a small metadata header (`local_378`) somewhere
   relative to the call site (via `param_1 - 5`).
2. Decrypts the header with a rolling XOR loop:
   ```
   key = local_378[0]
   for i in 0..0xec/4:
       tmp = buf[i]
       buf[i] ^= key
       key = tmp
   ```
3. Validates a magic at `header[1] == 0xC0DEC0DF` (signed
   `-0x3f213f21`). On mismatch goes to the error sink
   `LAB_14155cfde` which zeroes its scratch buffers and triggers
   `int3` — game dies with a debug-trap.
4. Parses an embedded string table of 0x22 (34) null-terminated
   strings. These are API names (Win32 kernel32 / kernelbase) that
   the protector will resolve dynamically.
5. Resolves `kernel32.dll` itself — but does so **without leaving a
   literal `"kernel32.dll"` string in `.rdata`**. The string is
   assembled on stack:
   ```
   local_a90='k', uStack_a8e='e', uStack_a8c='r', uStack_a8a='n',
   uStack_a88='e', uStack_a86='l', uStack_a84='3', uStack_a82='2',
   uStack_a80='.', uStack_a7e='d',uStack_a7c='l', uStack_a7a='l',
   uStack_a78=0
   ```
   then passed to a previously-resolved `GetModuleHandleA`-style
   pointer.
6. Walks the table of API names and stores each function pointer
   into `local_5xx` slots — this is the protector's private import
   table.
7. Optionally invokes Steam-DRM / packaging integration via
   `CreateFileMappingA` + `MapViewOfFile` (the `(*local_580)(0x100000,
   0, name)` and `(*local_578)(2, 0, name)` calls at lines 1155-1157).
   The mapped region at offsets 0x90..0xb4 is written with a small
   inter-process struct — likely the same kind of handshake that the
   Microsoft Store / Steam wrapper uses to sign per-process state.
   This **does not affect `.text` integrity**.
8. On the success path (line 1104):
   ```
   return local_b70 + local_358;
   ```
   That sum is the real entry-point VA inside `.text`.
9. On any error path the protector ends in `TerminateProcess(-1,
   exit_code)` at line 1260 (`local_5c8` is the resolved
   `TerminateProcess`).

There is no follow-on thread spin-up. There is no `.text` checksum
loop scheduled to run later. The protector vacates the stage.

## Implications for the Hook API

We can build `rsmm.hook(name_or_va, "sig", callback)` on top of
`MinHook` directly against `.text`. The existing fn_resolver
(pattern DB) gives us name -> runtime VA at any time after Wine's ASLR
settles, and MinHook installs a 5- or 14-byte detour at the resolved
VA without triggering any further reaction from the protector.

Constraints to respect:

- **Install hooks after the loader's worker thread has done its
  initial `VirtualQuery` retry loop** (`hook_engine.cpp` already waits
  up to 5s for `.text` to be mapped). The protector finishes before
  the engine's first `oCString` allocation, so by the time the
  loader's `script_emit_event("ready")` fires, the unpacker is gone.
- **Avoid Wine syscall-forwarder targets**: `kernel32!CreateFileW`,
  `kernelbase!NtOpenFile`, etc. Use IAT patching (already in
  `hook_io.cpp`) when you need to filter game I/O.
- The protector's success path returns an `entry_point + offset_const`
  computed from a metadata header that is decrypted at boot. **A game
  patch may shift this constant**, so do not hardcode the real
  entry-point VA anywhere — let the protector compute it and resolve
  hooks by pattern.

## Verification plan

1. Restore a minimal `MinHook` trampoline targeting `FUN_140487040`
   in `hook_engine.cpp` behind an opt-in env var
   (`RSMM_ENABLE_ENGINE_HOOK=1`).
2. Run the game. The hook should fire on the first resource lookup
   without any crash. Compare against the Phase 3 INTERNALS evidence
   (same hookpoint, same captured handles).
3. If clean for one minute of normal play, the hypothesis above is
   confirmed and we lift the gate; `rsmm.hook` proceeds.
