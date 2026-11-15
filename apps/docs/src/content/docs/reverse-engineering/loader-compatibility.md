---
title: Loader compatibility
description: Why the optional Lua loader's hooks are stable, and the two targets it avoids.
---

Asset mods never touch the running game: they replace data files before
launch. Only Lua mods need the optional loader (`winhttp.dll` next to the
game), which hooks a small set of game functions in memory. This page records
why those hooks are stable and which targets to avoid.

## Hooks are stable once the game has started

Ravenswatch's startup code finishes before the loader installs anything, and
nothing re-checks function bodies afterwards. A detour installed by MinHook
from the loader's worker thread therefore stays in place for the session.
`Ravenswatch.exe` is never modified on disk.

An early note in this repo claimed that every hook crashed the game because of
an integrity check. That was wrong. The two hooks that failed had unrelated
causes:

- **`kernel32!CreateFileW` prologue rewrite.** Under Wine, `CreateFileW` is a
  thin forwarder over `NtCreateFile`; rewriting its prologue during early
  graphics start-up corrupts Wine's per-thread state. `hook_io.cpp` patches the
  game's import slot instead, which works.
- **A swapchain `Present` hook** aimed at the wrong graphics API. The game
  renders through DirectX 12.

## Rules for new hooks

- Install hooks after the loader's worker thread has settled
  (`hook_engine.cpp` waits for the game's code pages to be mapped), never from
  a TLS callback or `DllMain`.
- Don't rewrite prologues of OS forwarders (`kernel32!CreateFileW`,
  `kernelbase!NtOpenFile`, …). Use import-table patching when you need to
  filter the game's file I/O.
- Never hardcode addresses. Resolve every target through `data/symbols.json`
  (`Sym::Name` / `ADDR["Name"]`) so a game patch is a remap, not a crash.
- Hooks go through `hook_util.h`, which refuses any target that isn't a real
  function entry.
