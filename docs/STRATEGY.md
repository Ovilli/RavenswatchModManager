# RSMM Strategy — 8-area architectural plan

Strategic blueprint for evolving the Ravenswatch Mod Manager from
"functional foundation" to "community-grade modding framework".
Strategy only — implementation details live in code, see `MODDING.md`
+ `SDK.md` (TBD) for usage and `INTERNALS.md` for engine RE.

## Current state (honest)

- **Build-time**: Python CLI rewrites cooked asset bytes under
  `_Cooking/` with per-file backup + restore.
- **Runtime**: Optional `winhttp.dll` proxy hosts per-mod Lua VMs.
  MinHook intercepts on engine functions were prototyped, currently
  pruned to no-op stubs.
- **Multiplayer**: Not addressed. Engine uses Steam P2P. Cooked
  overrides on one peer = silent desync.

What works today informs every section below; gaps are called out
explicitly so the plan stays grounded.

---

## 1. API Scalability & Ergonomics

**Three-layer separation. Modder never crosses layer.**

- **Surface layer** (`rsmm.sdk`): semantic verbs — `m.stat`, `m.texture`,
  `m.register_skin`. Stable across engine RE drift. Versioned:
  `sdk.v1`, `sdk.v2`. Old versions deprecated with one-release grace.
- **Capability layer** (`rsmm.core`): mod-kind primitives — Registry,
  EventBus, OverrideTable, ConflictResolver. Surface composes these.
- **Adapter layer** (`rsmm.engine`): cooked-byte writers, cipher,
  MinHook bindings. Brittle. Replaced on every game patch. Hidden.

**Event dispatch shape.**
- Pub/sub on named topics (strings), never raw offsets. Engine
  resolves topic→callsite once at boot.
- Two callback flavors: **observer** (cannot mutate) vs **mutator**
  (returns new context, framework merges chain).
- Priority field per subscription. Stable sort. Deterministic.
- Cancelable propagation only for observer kind; mutator chain
  always runs full.

**Capability negotiation.**
- Manifest declares `requires.api = ">=1.4"` +
  `requires.features = ["stat", "co-op-event-bus"]`.
- Loader refuses mod whose declared needs exceed runtime offerings.
  Better than load-then-crash.

**Naming.**
- Every modder-created entity carries `<mod_id>:<local_name>`.
  Globally unique by construction. Save files reference these
  strings, not numeric IDs.

---

## 2. Sandboxing & Fault Tolerance

**Lua per-mod isolation (partial today). Harden:**

- One `lua_State` per mod (have it). Add per-state **memory cap** via
  custom allocator. Reject allocation past limit → mod auto-disabled
  before OOM.
- **Instruction count limit** via Lua debug hook on every callback
  entry. Long-running script → terminate callback, mark mod degraded.
- All Lua entries from native side wrapped in `pcall`. Errors →
  structured log line (mod id + topic + Lua traceback). Never
  propagated back to engine stack.
- **Health budget**: N errors in M minutes → auto-disable mod,
  surface red in `rsmm doctor`. User decides re-enable.
- **Capability scoping**: file IO restricted to mod's own dir.
  Network IO denied unless manifest declares `requires.network = true`
  with whitelist.

**For native code mods (future):** in-process C++ mods can't be
sandboxed against segfault. Either don't allow native, or run in
separate process behind RPC. Recommend: modder-facing layer Lua-only.
Native = framework-author territory.

**Hook unwinder.**
- Every `MH_CreateHook` registers a paired `cleanup` callback in a
  global stack. Mod disable / shutdown → unwind LIFO. Failed remove
  → log + carry on, never leak.

**Quarantine on repeat failure.**
- Disk-resident mod-health journal (`mods/_health.json`). Loader
  reads on boot, refuses to start a mod that crashed N times in a
  row without a manifest version change. Forces modder to bump
  version on fix.

---

## 3. Patch Resilience (game updates)

**Three layers of binding, ordered most→least durable:**

1. **String / path anchors.** Engine reads cooked assets by path
   hash; path strings stable across patches. Today's foundation.
2. **Pattern signatures** for native hooks. Each MinHook target by
   byte-pattern with wildcards for register encoding + relocation.
   Resolve VA at boot via memory scan. Survives recompile VA shifts.
3. **Version-pinned offsets** as last resort. Disabled unless exe
   hash matches.

**Exe-hash gate.**
- On loader init, hash `Ravenswatch.exe`. Compare against known-good
  catalog (`data/exe_catalog.json`).
- Match → enable native hooks.
- Drift → run runtime "schema drift detector": re-resolve path
  anchors, open known cooked file, sanity-check class table. Pass
  → degraded mode (asset-only, native hooks off). Fail → refuse
  loader; asset-only mods still work.

**CI watchdog.**
- Weekly: pull public game depot, rebuild asset map, diff. Diff size
  over threshold → opens issue. Catches breakage upstream before
  users notice.

**Never persist absolute offsets.** Resolve fresh per boot.

---

## 4. Multiplayer State Synchronization

**Most critical gap. Today: undefined behavior under any non-cosmetic mod.**

**Scope taxonomy.** Manifest field `multiplayer_scope`:

- **cosmetic** — textures, audio, UI strings. Local-only.
- **deterministic-shared** — stat tweaks. MUST be identical on every
  peer. Framework enforces via mod-set hash exchange at lobby join.
- **host-authoritative** — difficulty mods, custom enemies, new items.
  Host enforces; clients receive results.
- **local-only** — HUD overlays, personal trackers. Per-peer; no
  engine state touched.

**Lobby handshake.**
- On lobby join, peers exchange a manifest digest (sorted hash of
  enabled `deterministic-shared` + `host-authoritative` mod IDs +
  versions + content hashes).
- Mismatch → host kicks or joiner refuses. Friendly "mod mismatch"
  dialog, not crash.
- Steam matchmaking lobby metadata is the cheap transport (string KV,
  already in-use).

**Determinism rules for shared mods.**
- No `math.random` in gameplay paths unless from host-seeded RNG the
  framework exposes.
- No system clock, no per-peer file IO, no network IO mid-frame.
- SDK provides `rsmm.rng(seed_topic)` returning deterministic stream.
- Lint check static-analyzes Lua AST for forbidden globals.

**Host-authoritative bridge.**
- Framework owns one synthetic network channel (piggyback on existing P2P).
- Mutator events on `host-authoritative` topics: client emits proposal,
  host computes authoritative result, broadcasts back, every peer
  applies. Single round-trip latency.
- High-frequency events (OnDamage): batch per game-tick. One packet
  per tick max.

**Reality check.** Engine network hook points unknown today. Phase:
identify Steam Networking call sites in `Ravenswatch.exe`, add
MinHook intercepts. Until then: framework refuses non-cosmetic mod
in a lobby. Surface clearly in UI.

---

## 5. Simplified Content Injection (Manager pattern)

**One registry per content kind. Modder hands data; manager owns IDs + injection.**

Registries:
- `Items` — ingredients, dream shards, rewards
- `Heroes` — skins, alt-abilities, stat profiles (not whole new heroes
  until re-encoder lands)
- `Enemies` — skin + stat variants of existing enemies
- `Modifiers` — custom difficulty modifiers
- `Localization` — text-bank additions
- `Sounds` — FMOD bank swaps

**Modder contract:**
- Modder declares content via SDK call:
  `m.register_item("RavenFeather", category="ingredient", stats={...})`.
- Manager allocates mod-prefixed namespaced ID
  (`MyMod:RavenFeather`).
- Manager translates to engine-format insertion (cooked-byte
  mutation OR runtime engine table augmentation).
- Modder never sees encoded path, never touches cooked binary.

**Save-file stability.**
- All registered content keyed by namespaced ID, never numeric slot.
- Mod uninstall → save loads with placeholder (item missing, not
  crash).
- Migration hook: modder registers `on_save_load(old_id) -> new_id`.

**Today's constraint.** True new content needs text-`.ot` →
binary-`.gen` re-encoder (deferred). Pragmatic interim:
- Registry layer DESIGNED + SDK API SHIPPED today, returns "not yet
  supported on this engine version" until re-encoder lands.
- Modders write against the stable API. When re-encoder ships,
  their mods work without rewrite.

This preserves authoring effort across the re-encoder gap.

---

## 6. Co-op Safe Hooks

**Event taxonomy per topic.** Each framework event carries metadata:

- `scope`: cosmetic / shared / host-only
- `cadence`: tick / event / one-shot
- `mutability`: observer / mutator
- `latency_budget_us`: per-callback wall time cap

**Dispatcher behavior:**
- Observer + cosmetic: fire local; no network, no host coordination.
- Observer + shared: fire on every peer; each peer's mod observes
  identical context (framework computes centrally, broadcasts).
- Mutator + host-only: fire on host; broadcast result; clients apply
  read-only.
- Mutator + shared: forbidden unless mod proves determinism via a
  static signature in manifest (`pure = true`).

**Latency control.**
- Per-tick aggregate Lua budget (e.g. 1 ms / frame across all mods).
  Exceed → frame drops the lowest-priority mod's callbacks for that
  frame, logs warning.
- Long-running computation goes to background coroutine; SDK exposes
  `rsmm.defer(fn)`.
- High-frequency events auto-coalesced: framework batches and
  delivers one summary per tick, not one call per instance.

**Concrete event surface (proposed, not all wired today):**
- `on_ready`, `on_exit` (live)
- `on_frame`, `on_menu_enter`, `on_menu_exit`
- `on_run_start`, `on_run_end`
- `on_hero_spawn`, `on_hero_death`
- `on_enemy_damaged` (mutator, host-only)
- `on_item_picked_up`, `on_skill_used`
- `on_chapter_complete`

Each needs an identified engine entry point. Roadmap entry, not
deliverable today.

---

## 7. Modder Onboarding Flow

**Goal: first-success in < 5 minutes.**

**Scaffolder with templates.**
- `rsmm new <id> --template <name>` writes a working starter:
  - `texture-swap` — donor-swap one cooked texture.
  - `stat-tweak` — change one balance number via SDK `[[patch]]`.
  - `lua-behavior` — `init.lua` skeleton with one event handler.
  - `composite` — multi-patch starter.
- Each template includes inline comments pointing at SDK docs.

**Canonical folder.**
- One layout, never two. `manifest.toml` + `assets/` + optional
  (`init.lua`, `build.py`, `README.md`, `LICENSE`).
- `rsmm lint <id>` validates structure, surfaces missing fields.

**Discoverability.**
- `rsmm sdk list` enumerates every SDK verb with one-line doc.
- `rsmm sdk show texture` prints full signature + example.
- Auto-generated SDK reference at `docs/SDK.md` from docstrings,
  regenerated in CI on every release.

**Documentation tiers** (in place, refine):
- **README.md** — landing, quickstart only.
- **docs/MODDING.md** — recipe book, one section per content kind.
- **docs/SDK.md** — API reference, auto-generated.
- **docs/INTERNALS.md** — engine RE notes, quarantined for the curious.
- **docs/ROADMAP.md** — open work + version targets.

Modder reads README → succeeds with template → opens MODDING →
graduates to SDK reference. Never forced to read INTERNALS.

**First-class debugging.**
- `rsmm doctor --mod <id>` scoped check.
- `rsmm trace <id>` runs with `RSMM_TRACE=1` and surfaces log inline.
- `rsmm diff <id>` shows which cooked files this mod would change.

**Empty-state UX.**
- Fresh checkout + `rsmm doctor` → green or actionable WARNs only.
- Every WARN has a one-line fix command.

---

## 8. Safe Overrides (conflict resolution)

**Conflict tiers, framework response per tier:**

| Tier | What | Default response |
|---|---|---|
| 1 | Same file, different fields | Merge (live today for stat + texture) |
| 2 | Same file, same field | Sort by `load_order`, ties by id; later wins. Log. |
| 3 | Same record, semantic conflict | Framework can't reconcile. Surface, suggest pick-one. |
| 4 | Logical contradiction across records | Tier 2 + warning. |

**Manifest compatibility graph.**
- `requires = ["other-mod-id >= 1.2"]` — hard dep.
- `conflicts = ["incompatible-id"]` — hard refuse.
- `replaces = ["older-version-id"]` — supersedes; loader auto-disables.
- `priority = N` — secondary sort within same `load_order`.
- Loader pre-validates graph: cycle, conflict, missing-dep. Failure
  surfaces in `rsmm doctor` and refuses apply.

**Override granularity ladder.** Nudge modders down the ladder:
- Worst: raw cooked-file drop in `assets/<path>`. One owner. No merge.
- Better: `[[patch]]` block declarative. Field-level merge.
- Best: registry call via SDK (`m.register_*`). Conflict-free by
  namespacing.

`rsmm doctor` should nudge: "MyMod ships raw `Aladdin.gen` — consider
switching to `m.stat(...)` to allow merging."

**Lua mutator chains.**
- All chain handlers run, ordered by priority.
- Each handler receives current accumulated value, returns new value.
  Pure functional pipeline.
- Handler may declare `final = true` — chain terminates after it.
  Framework warns if two handlers both want `final`.

---

## SDK improvements (continued)

**Static validation at build time.**
- SDK `Mod.__exit__` runs a validation pass: every `m.stat(name)`
  checked against asset_map; every `m.texture(donor)` checked for
  existence; every text key checked against bank.
- Errors raised BEFORE manifest is written. Modder catches typos at
  `python3 build.py`, not at `rsmm apply`.

**IDE autocomplete via type stubs.**
- Ship `.pyi` stub files for `rsmm.sdk`. Modders get hover docs +
  autocomplete in VS Code / PyCharm. Zero runtime cost.
- Catalog of friendly aliases (hero names, enemy names, item names)
  exposed as typed enums — autocomplete drives discovery.

**High-level composite recipes.**
- `m.rebalance_hero("Aladdin", damage_mult=1.2, hp_mult=0.9)` →
  expands internally to N `[[patch]]` blocks across the right files.
- `m.replace_skin("Aladdin", from_pack="my_textures/")` → batches a
  directory of donor PNGs.
- Compositions inspectable: `rsmm explain MyMod` prints the expanded
  patch list.

**Dry-run mode.**
- `sdk.dry_run()` context manager: SDK records calls, returns the
  patch plan, writes nothing. Useful in tests + tooling.

**Test harness.**
- `rsmm test <mod_id>` runs SDK build in dry-run, applies merge,
  decodes the result, diffs against an expected fixture. Modders
  ship fixtures; CI verifies their mod still produces expected
  output as framework evolves.

**Versioning + migration.**
- Manifest field `sdk_version`. Loader maps old SDK calls to new
  ones via shims. Two-version overlap window. Old SDK calls emit
  deprecation in `rsmm doctor`.
- Content registry: save-file migration hooks. Mod author registers
  `migrate("old_id", "new_id")` in init code.

**Live SDK in Python REPL.**
- `python3 -m rsmm.sdk` launches interactive shell pre-imported.
  Exploration friction zero — list assets, try aliases, build a mod
  incrementally.

**Telemetry (opt-in, anonymized).**
- One toggle, off by default. Sends: SDK verbs called per session,
  exception fingerprints, mod-set size. Never mod content. Helps
  prioritize which verbs to optimize, which conflict patterns to
  design around.

**Hot-reload for Lua mods.**
- Today: relaunch game to pick up Lua changes. Cost: 30+ seconds
  per iteration.
- Improvement: loader watches `mods/<id>/init.lua` mtime; on change,
  tears down + recreates that mod's lua_State without restarting
  the game. ~95% iteration cycle reduction.

**Modder-facing event recorder.**
- `rsmm record <session>` captures every event the loader fires +
  every mod callback that subscribes. Replays deterministically.
  Modders debug intermittent bugs without re-running the game 50
  times.

---

## What to build first, what to research

**Build now (1–2 weeks each):**
- SDK static validation pass.
- `requires` / `conflicts` / `replaces` graph in manifest + doctor
  enforcement.
- SDK type stubs (.pyi).
- Composite recipes (rebalance_hero, replace_skin).
- Hot-reload for Lua mods.
- `rsmm test` harness.

**Research / multi-week:**
- Engine event hooks (OnDamage, OnHeroSpawn, …) — needs MinHook on
  identified call sites.
- Multiplayer manifest handshake — needs Steam Networking hook surface.
- Content registry backing — needs text-`.ot` → binary-`.gen`
  re-encoder.

**Defer until engine RE matures:**
- True new heroes / enemies / items.
- Custom 3D mesh import.
- Determinism static analyzer for Lua mutator chains.

The architecture above is future-proof against the engine work being
slow: modders write against the stable SDK surface today, deeper
features light up incrementally as engine RE lands. No author
rewrite at any milestone.
