# Gameplay events — engine emitter → Lua event bus

> 📖 Prose version on the docs site: **https://docs.rsmm.me/reverse-engineering/event-systems/** (`apps/docs/src/content/docs/reverse-engineering/event-systems.md`).
> This file stays as the raw RE field notes.


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

**ON BY DEFAULT** (opt out with `RSMM_DISABLE_GAME_EVENTS=1`). The addresses
in the table above are from the build these notes were written against;
`data/symbols.json` (`Event_LevelUp` / `Event_RunEnd`, `kind="event"`) is the
source of truth. To validate `level_up` after a remap: the loader log must
print `[game-events]` without a `resolve`/`verify`/`mid-function` failure for
`Event_LevelUp`, and an `R.on("level_up", …)` handler must fire once per
level-up with `{ level }` matching the HUD — not per frame.

## Adding a typed emitter

Add a `kind="event"` symbol (with `lua_event`, `cabi`, optional `payload`) to
`data/symbols.json` and run `rsmm symbols gen`. That is the whole change:
`event_table.gen.h` grows a row and `arm_all` folds over the actual table
length, minting one `detour<N>` per slot. There is no hand-unrolled `arm<N>`
list any more.

## Closed: the old per-emitter TODO list (2026-10-13)

The three emitters this file used to list as "not yet done" are each already
delivered by one of the two buses, so none gets a dedicated detour. A new
detour costs a fresh RE pass on every game patch and is a crash risk if it
mis-resolves:

| Wanted | Already delivered by |
|--------|----------------------|
| `level_reached` | Not an event. `level_reached` is a **field** of analytics `chapter_end` (proven 2026-10-10) and of `level_up_book` (`hero_name`, `level_reached`). Per-level-up timing is the typed `level_up` → `{ level }`. The old `0x140f13c20` string anchor was the field-name literal. |
| `hero_pick` | No solo emitter exists. The pick is in the lobby blob (`RequestedHero`, via the `LobbyAttributes_Parse` hook) and in analytics `run_start.player_heroes` (online only, unconfirmed). The old anchor (`"Skill selected"`) was the **talent** pick, now analytics `skill_selected`. If a solo `hero_pick` is ever needed, `HeroSelect_ConfirmPressed` is the candidate, but it is unproven and fires on refused presses too. |
| `damage` | `R.damage` (per-player meter) and `gameplay:NETWORK_DAMAGE` (`value`, `source_id`; co-op only, because solo damage is a direct call). For totals, use analytics `chapter_end.damage_dealt` / `damage_received`. |

## Analytics firehose — every named event from one hook

The per-emitter table above is no longer the only path. All the lowercase
snake_case analytics events funnel through **one central sink**,
`Analytics_SubmitNamedEvent` (`FUN_1401fa470`): each of its ~37 callers builds
a key-value payload then submits it as JSON (`projectId "passtech-ravenswatch"`)
to Passtech's analytics backend over an authenticated HTTP POST. The event
name is `arg3`, a `StringDesc { const char* ptr @+0x0; uint32 len|0x80000000 @+0x8 }`.

`install_analytics_firehose()` (in `hook_events.cpp`) detours that single sink,
reads the name, and `script_emit_event_json("<name>", …)` — so **one hook
exposes every named event** to `R.on("<name>", cb)`, and any name the game adds
in a patch shows up automatically (no new table row). It skips `"run_end"` to
avoid double-firing the typed `Event_RunEnd` table hook.

Confirmed names (cluster `0x140f13a00`–`0x140f13f00`):
`game_start` `run_start` `matchmaking_start` `matchmaking_end` `run_end`
`chapter_end` `level_up_reach` `level_up_book` `enemy_killed` `unlock_skill`
`unlock_object` `unlock_hero` `unlock_level_nightmare` `event_start` `event_end`.
(The UPPER_CASE strings nearby — `GAME_START`, `BOSS_FIGHTING_START`, … — are a
separate game-state-machine enum, **not** analytics events.)

**Observation-grade, not a gameplay bus.** These fire *after* the action and
carry analytics KV, not a live entity handle — perfect for "when X happens, do
Y" triggers, useless for mutating the actor. For entity-context gameplay events
(damage, give-item) the real bus is the `oCGameNamedEvent` family
(`NETWORK_DAMAGE`, `NETWORK_DAMAGE_RESPONSE`, `GIVE_MAGICAL_OBJECT`) reached via
`Netcode_Channel_LookupById` + `Netcode_Channel_Subscribe` — the next surface
to map (those two symbols are present but `unverified`; re-confirm their
addresses, then subscribe + decode the per-event payload struct).
