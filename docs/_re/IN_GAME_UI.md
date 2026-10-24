# In-game mod UI — recon (2026-10-24, build b9c3642884a8)

> **SUPERSEDED 2026-10-24 — the ImGui overlay below was removed.** It worked,
> but painting our own book over the Settings page was too complicated and
> looked wrong. The mod menu is now a **Mods tab inside the game's own Settings
> page** (`src/loader/src/hook_settings_menu.cpp`, on unless `RSMM_DISABLE_NATIVE_MENU`, plus a pause menu Mods button via
> `rsmm.engine.escape_menu`):
> the page is built in code by `oe::dt::BookOptionsUiControllerEntityCpnt`
> (vtable slot 7 calls five tab builders), so one detour on the last builder
> plus the game's own add-tab / add-row functions (`OptionsMenu_*` in
> `data/symbols.json`) gives rows the game draws, navigates and sounds itself.
> A multi-choice row only holds a `uint32_t*` to its current index, so rows
> point at loader memory. Proven in game the same day. The recon below is kept
> for the DXGI/input findings; the overlay code is in git history (f951f0c9 ..
> 15e2a9f9).

**PROVEN IN GAME 2026-10-24 (Proton, GE-Proton10-34, vkd3d-proton, 3440x1440):**
`hook_overlay.cpp` hooked Present/Present1/ResizeBuffers/ResizeBuffers1 and
ExecuteCommandLists, captured the DIRECT queue ~1 s after boot, drew the panel,
and took 16 clicks on its test button. Native Windows is untested.

- The toggle had to be POLLED in Present. A WM_KEYDOWN check in the subclass
  never fired: the first input message the subclass saw was 0x201
  (WM_LBUTTONDOWN). Mouse messages do arrive, which is what the panel's
  clicks run on.
- The buffer size changed between launches (3440x1440, then 3440x1407
  windowed); the renderer reads it from the swapchain each init.

The rest of this file is the static recon that led there.

## Why the old overlay never drew

The loader once shipped an ImGui overlay (`hook_vk.cpp` + `hook_win32.cpp`,
deleted in 843a6c84 as "never feature-complete"). It hooked
`vkGetInstanceProcAddr` in `vulkan-1.dll`. Ravenswatch never imports Vulkan:

| Import | Present |
|--------|---------|
| `dxgi.dll` | `CreateDXGIFactory1` |
| `d3d12.dll` | `D3D12SerializeRootSignature` + 1 by ordinal |
| `vulkan-1.dll` | **no** (not imported, no string) |
| IID `IDXGISwapChain3` / `ID3D12Device` / `ID3D12CommandQueue` | yes, in .rdata |

So the hook could never fire on native Windows. Under Proton, vkd3d-proton
talks to winevulkan directly, so it does not go through that path either.
The right surface is the DXGI swapchain: `IDXGISwapChain::Present` (vtable
slot 8), `ResizeBuffers` (13), plus `ID3D12CommandQueue::ExecuteCommandLists`
(slot 10) to capture the DIRECT queue that imgui_impl_dx12 needs.

## How the game reads keyboard and mouse

DirectInput8 is created, but `GUID_SysMouse`/`GUID_SysKeyboard` are absent
from the image, so DInput is gamepad-only (with XInput + GameInput + libScePad).
Keyboard and mouse are plain Win32:

- **Window proc `FUN_14057ac80`** (installed with `SetWindowLongPtrA`, chains
  with `CallWindowProcA(param_1[0], ...)`; window object in `param_1[1]`):
  `WM_CHAR` → text input into the input manager (`FUN_14067ec40(DAT_14146f8e8, ch)`);
  `WM_MOUSEMOVE` → cursor at window+0xa8/+0xac; `WM_MOUSEWHEEL` → input
  manager +0xa0 (±1); `WM_LBUTTONDBLCLK`/`WM_RBUTTONDBLCLK` → `FUN_14067d4a0`.
  It does **not** handle `WM_*BUTTONDOWN/UP`.
- **Input poll `FUN_14067ddd0`** (per frame): 85 mapped keys
  (`FUN_1406815d0(i)` → VK) and mouse buttons VK 1/2/4/5/6, all through
  `GetAsyncKeyState`. Button state lands in `DAT_14146704c..094`.
  Both loops are skipped when the function pointer `DAT_141436bf8` (an
  "accept input?" predicate) returns false.
- Other `GetCursorPos` readers: `FUN_14055cea0` (UI drag; it also
  `SetCursorPos`es back), `FUN_140459e00`.

Mouse buttons are polled, not message-driven. That is consistent with the
2026-10-04 finding that the `ui:press` hook never sees clicks.

## Consequence: a symbol-free in-game UI

Every piece an overlay needs is a Windows or DXGI interface, not an engine
function:

1. Render: vtable-hook `Present`/`ResizeBuffers`/`ExecuteCommandLists` on a
   throwaway device + swapchain; take the HWND from `GetDesc().OutputWindow`.
2. Input in: subclass the game window *after* it has subclassed itself, and
   feed `ImGui_ImplWin32_WndProcHandler`.
3. Input blocked from the game while the overlay has focus: IAT-hook
   `GetAsyncKeyState` in the game module and return 0 while
   `io.WantCaptureMouse` / `WantCaptureKeyboard`; swallow `WM_CHAR`,
   `WM_MOUSEWHEEL` and `WM_MOUSEMOVE` in the subclass.

No `data/symbols.json` entries are needed, so a game patch cannot break it.
The engine functions above are reference only and are not mapped as symbols.

Vendored ImGui is 1.92.8 with `imgui_impl_dx12` + `imgui_impl_win32`;
the MinGW toolchain ships `d3d12.h`/`dxgi1_4.h`.

## Questions the first launches answered (see top) and still open

- Does the Present hook fire and draw under vkd3d-proton (and on native Windows)?
- Which thread calls Present? Lua must not be touched from it
  ([[loader-thread-model]]): the overlay renders a retained widget snapshot
  and queues events back to the Lua thread.
- Does masking `GetAsyncKeyState` fully stop clicks reaching the game, or does
  `DAT_141436bf8` / another path also need handling?
- Cursor: the game hides or replaces it during play; `io.MouseDrawCursor`
  may be needed while the overlay is open.

## The escape menu (2026-10-24, static)

The escape/pause menu is a game state, `oe::dt::InGameMenuGs` (one of four
`Gs` classes: GameSessionGs, InGameMenuGs, LevelGs, LobbyGs). Its vtable
(0x140f0a488 on b9c3) has the family's shape: every Gs overrides slots
2/4/5/12 and leaves 6-11, 13 and 14 on the base stub 0x1400b9df0.

| Slot | b9c3 address | Role |
|------|--------------|------|
| 2 | 0x140247990 | destructor (restores `oIGameState::vftable`) |
| 4 | 0x140292740 | **enter**: scene-context bool `0x162b18c9` = 1, encyclopedia counter +0xc50 += 1 |
| 5 | 0x1402929e0 | **leave**: bool `0x162b18c9` = 0, counter -= 1 |
| 12 | 0x140292bb0 | per-frame update |

Mapped as `InGameMenuGs_OnEnter` / `InGameMenuGs_OnLeave`. The overlay hooks
both to show a Mods button while the escape menu is open. Its buttons
(Resume, Quit to desktop, ...) belong to `oCDtEntityCpntInGameMenuUiController`
("Escape Menu Ui Controller"). Their screen rects are not read, so the Mods
button sits below the menu instead of in its column.
