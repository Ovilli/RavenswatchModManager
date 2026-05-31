# Gameplay events — engine emitter → Lua event bus

> Status: Tier-1 RE backing `src/loader/src/hook_events.cpp`. Emitter
> addresses verified by **string-xref against the shipped Ravenswatch.exe**
> (image base 0x140000000), not from the `docs/_re/out` corpus — the corpus
> is rebased relative to the installed build for the `0x1401f5xxx` region,
> so its `FUN_1401f2c80`/`FUN_1401f3b90` addresses do **not** match. Always
> re-verify by string-xref before adding an emitter.

## How an emitter is located (the safe recipe)

1. Find the event-name C-string in `.rdata` (e.g. `"level_up_reach\0"`).
2. Scan `.text` for a RIP-relative `lea reg,[rip+disp]` whose target is that
   string address — that instruction is *inside* the emitter.
3. Walk back to the function start (preceding `int3` padding run).
4. Confirm a clean standard prologue, then pattern it for `fn_resolver`.

A POST-detour that calls the original and then fires the Lua event is
**argument-layout-agnostic and crash-safe** — no need to know the arg
struct. Reading args for a payload requires confirming the signature first
(not yet done; payloads are currently empty `{}`).

## Verified emitters (this build)

| Lua event  | name string      | string VA    | xref site     | fn start (hooked) | prologue |
|------------|------------------|--------------|---------------|-------------------|----------|
| `level_up` | `level_up_reach` | 0x140f13d00  | 0x1401f64a4   | **0x1401f6410**   | `48 89 5c 24 10 48 89 7c 24 18 55 …` |
| `run_end`  | `run_end`        | 0x140f13ba8  | 0x1401f5347   | **0x1401f51e0**   | `48 89 5c 24 10 48 89 74 24 18 55 57 …` |

Patterns added to `data/function_patterns.json` + `docs/_re/out/symbols.json`
as `FUN_1401f6410` / `FUN_1401f51e0` (both resolve uniquely, match_index 0).

## Wiring

`install_event_hooks()` (dllmain) detours both via MinHook, `fn_verify`'s the
pattern first, and calls `script_emit_event_json("<event>", "{}")` after the
original returns. The Lua bus delivers it to every mod's
`rsmm.on_event("<event>", fn)` handler (handlers get a payload table arg —
empty for now). See `src/loader/src/script_lua.cpp::script_emit_event_json`.

**OPT-IN:** gated behind `RSMM_ENABLE_GAME_EVENTS=1` — string-verified but
not yet validated against a live game (can't run Windows/game on the dev
box). Flip the env var in the Steam launch options to test; confirm the
loader log prints `[game-events] 'level_up' -> FUN_1401f6410 hooked` and that
handlers fire at the expected cadence (once per level-up, not per frame).

## TODO (same recipe, not yet done)

| Event       | name string anchor              | notes |
|-------------|---------------------------------|-------|
| `level_reached` | `level_reached` @ 0x140f13c20 (xref 0x1401f5c93/0x1401f742c) | two xref sites — pick the emitter, find start |
| `hero_pick` | `Skill selected` via registry `FUN_1401d1850` (HOOKPOINTS.md) | find the selection consumer, extract hero/skin from args |
| `damage`    | not yet string-anchored         | search decomp for the damage-apply function |

Add a row to `g_hooks[]` in `hook_events.cpp` + a pattern entry, and bump the
`arm<N>` calls in `install_event_hooks()`.
