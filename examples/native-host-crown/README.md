# Native nameplate modding checkpoint

This is a reproducible development path for adding native UI to Ravenswatch.
The immediate target is a gold crown **above the session host's name over their
character**, inside the game's own nameplate. This checkpoint provides reusable
inspection and asset-building code, not a finished host-indicator release.

## What is reusable now

| Surface | Entry point | Contract |
|---|---|---|
| In-process inspection | `R.debug.nameplate_snapshot()` | Opt-in, bounded, guarded reads of the captured hero's life-bar/nameplate chain; no UI writes or new hooks |
| Native asset builder | `ContentRegistry.register("nameplate_crown", ...)` | Experimental content kind that appends a stock crown picture to the native name frame |
| Lower-level cooker | `rsmm.engine.nameplate_crown.add_crown(target, source, ...)` | Pure bytes-to-bytes operation; version checks, stable existing object IDs and component vector |
| Windows capture fallback | `tools/inspect_native_nameplate.py` | Read the specific spawner found in the log; no heap scan, injection, writes, or engine calls |
| Shared engine knowledge | `data/symbols.json` | Three live-confirmed widget vtables and two explicitly unverified serializer candidates |

These are development interfaces. There is no supported `show_host_crown()`
runtime API yet, and the layout cooker is not a general-purpose HUD builder.
Another developer can reuse the native-container approach, inspection entry
point, symbol evidence, and tests without redoing the initial nameplate search.

## Evidence and current limits

The first user-provided co-op case was four players with the user hosting as
Scarlet. Logs established hosting, but no useful UI diagnostic was armed then.
That run did **not** prove which nameplate belonged to the host.

A later **solo** run supplied the successful live UI evidence. Hero capture
identified `Life Bar Spawner`; a guarded external read confirmed its overhead
UI entity, 133 components, native labels, a picture, and their containing windows.
The original diagnostic visited the teammate HUD first and exhausted its read
budget. It was corrected to focus on the overhead UI; success now requires the
overhead label and a complete, untruncated snapshot. Hot reload was attempted
but not acknowledged; the successful fallback is preserved as a reusable tool.

The supported capture build is executable SHA-256
`b9c3642884a8f3a463782f36c9a3a62bc14c88105315220c733fe6c2229ba904`.
The detailed relationships and serializer findings are in
[the shared RE note](../../docs/_re/NATIVE_NAMEPLATE.md).

At this checkpoint:

- The native placement preview was generated and installed locally, and its
  original backup and installed bytes were verified.
- Its visible appearance, size, spacing and texture loading are **not yet
  verified in-game**. The user paused before that visual test.
- `preview=true` intentionally adds a crown to **every applicable nameplate**
  for solo layout testing. Without it the cooker is a no-op.
- Solo network owner/host identities were unknown. Host-only visibility,
  guest behavior, scene changes, and death/revive behavior remain unimplemented
  or untested. Do not publish this preview to the mod registry.

## Reproduce the investigation

Start with this branch and the repository's [development setup](../../apps/docs/src/content/docs/contributing/setup.md).
Use your own installed game resources; the examples contain no game artwork,
cooked overrides, memory dumps, private names, or raw session logs.

### 1. Install the diagnostic from this checkout

Close the game. In PowerShell, from the repository root:

```powershell
$env:RSMM_GAME_DIR = 'F:\SteamLibrary\steamapps\common\Ravenswatch' # your install
$env:RSMM_MODS_DIR = Join-Path $PWD 'mods'
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force mods | Out-Null
if (Test-Path mods/rsmm-nameplate-diagnostic) { throw 'Diagnostic folder already exists' }
Copy-Item -Recurse examples/native-host-crown/diagnostic mods/rsmm-nameplate-diagnostic
python rsmm install-loader
python rsmm lint rsmm-nameplate-diagnostic
python rsmm apply --dry-run
# Review the plan, including any existing mods in this library.
python rsmm apply
```

Create `mods/` first if absent. Do not overwrite an existing diagnostic folder.
Use the source-checkout CLI so it understands this branch's new SDK content.
`install-loader` must install this checkout's Lua SDK, including
`rsmm/nameplate_debug.lua`; the mod itself only calls high-level SDK functions.
The manifest requests `RSMM_ENABLE_HERO_CAPTURE` through the normal apply
pipeline. The diagnostic is conservatively classified as gameplay by lint.

Start a solo run, use one attack to trigger hero capture, and stay in the run
for roughly 25 seconds. Inspect `<game>/mods/_log.txt` for `[nameplate-probe]`.
The example schedules main-thread inspection every ten seconds, stops after
two complete snapshots, and gives up after thirty attempts. It does not draw
anything. No second player is required to establish the UI structure.

### 2. Interpret the result honestly

`R.debug.nameplate_snapshot()` returns a table:

| Field | Meaning |
|---|---|
| `status` | `unavailable`, `partial`, or `captured` |
| `reason` | Why capture could not finish |
| `truncated`, `reads` | Budget exhaustion and charged reads; a truncated snapshot is not success |
| `entities` | Observed UI entities/components and links, for debugging only |
| `session_state`, `host`, `local_owner` | Existing SDK network observations; can be nil in solo |
| `local_is_host` | True only for connected state and matching known identities; false also covers unknown identity |

Call it on the main thread, for example with `R.schedule.next_main`. Do not
retain its pointers across ticks, entity destruction, or scene transitions.
Do not turn a discovered pointer into an engine-call argument: RTTI and readable
memory prove an observation, not an ABI or lifetime contract. The SDK checks
the loader's build-trust gate before probing; revalidate layouts after updates.

If a partial capture found `Life Bar Spawner`, keep that same run open and use
the **Windows-only** fallback from a terminal with permission to read the game:

```powershell
python tools/inspect_native_nameplate.py --game-dir $env:RSMM_GAME_DIR --output "$env:TEMP\nameplate-capture.json"
```

Choose a new output filename each time. It checks the executable hash, the
process image, and the captured object's live RTTI before following +0x88.
An exited run, changed game build, or stale object must stop capture. Keep raw
JSON/logs local; contribute the generalized findings and provenance instead.

### 3. Build the solo placement preview

Close the game. Disable the diagnostic in its manifest when done. Copy the
`layout-preview` directory into the chosen mod library as
`host-crown-layout-preview`, then use this checkout's CLI:

```powershell
python rsmm lint host-crown-layout-preview
python rsmm apply --dry-run
python rsmm apply
```

One experimental-content warning is expected. The actual SDK declaration is:

```toml
[mod]
experimental = true
# ...standard metadata; see layout-preview/manifest.toml...

[[content]]
kind = "nameplate_crown"
id = "overhead_crown"
preview = true
width = 0.20
y = -0.12
```

Or build to an output directory from Python:

```python
from pathlib import Path
from rsmm.sdk.content import ContentRegistry

registry = ContentRegistry("my-ui-test", experimental=True)
registry.register("nameplate_crown", id="crown", preview=True, width=0.20, y=-0.12)
written = registry.emit(Path("build/my-ui-test/assets"))
```

The cooker reads pristine resources through `corpus`, clones the shipped
`Host_Picture` descriptor, preserves its style/aspect flags and texture
reference, adds the new object to the directory, and links it to the name
frame's child list. Existing object IDs and the entity component list remain
unchanged. The game creates and owns the widget through its normal builder.

Test in solo first. Record the game build, hero, display scale, nameplate
visibility settings, and screenshot. If no crown appears, verify the emitted
asset actually landed, then check the parent frame's visibility, texture
resolution/preloading, and live child widget; do not treat successful cooking
or a hook firing as proof of drawing. Disable this preview and apply again
to restore its asset through RSMM's normal backups.

## Route from this checkpoint to a public mod

1. Confirm the native placement visually, including local and peer life-bar
   variants. Correct geometry or preload handling if needed.
2. Map and dynamically validate the native widget lookup/visibility path;
   record symbols, generate artifacts and expose a high-level SDK function.
   Keep all engine pointers and raw memory operations out of mod Lua.
3. For each actual hero entity, compare `R.net.owner(entity)` with
   `R.net.session_host()` in a connected session. Hide on unknown identity.
   Hero choice, first roster slot, and the local player are not host proxies.
4. Run a controlled co-op test on both host and guest. Record expected host,
   observed crown, and behavior after rebuilding the UI, death/revive, and
   session changes. The earlier Scarlet run is a reference case, not proof.
5. Only promote confidence or publish after those end-to-end checks pass.

## Verification commands

```powershell
python -m pytest tests/test_nameplate_crown.py tests/test_manifest_spec.py tests/test_symbols.py -q
lua tests/lua/nameplate_debug_spec.lua
lua tests/lua/rsmm_spec.lua src/loader/lib
python rsmm symbols gen --check
python rsmm symbols check
python rsmm docs-gen --check
```

The asset tests require a local game corpus and skip if absent. The diagnostic
Lua tests use mocked memory and need no game. Passing them checks bounds,
unknown identity, child ownership and byte preservation; it cannot establish
the crown's appearance or multiplayer correctness.

### Checkpoint validation (November 12, 2026)

Based on upstream `2b0592c7` for this checkpoint. The focused Python suite
passed all 86 tests against the installed game resources. Under Lua 5.4 (via
Lupa), the diagnostic passed 10 checks and the existing SDK passed 2,532 checks.
Optional SDK flow checks requiring a local `mods/` directory were skipped.
The standalone Lua/luac pytest wrappers were skipped because those executables
were absent; the SDK's hardcoded-address scan passed. Both source examples
linted with zero errors; only the preview's expected experimental warning
remained. Symbol consistency (383 entries), generated documentation freshness,
and `git diff --check` passed. These checks do not validate runtime rendering.

## Broader QoL mod context

The intended deliverable is one public QoL mod, with gameplay classification
accepted. This branch checkpoints the native crown investigation and reusable
SDK work; it does not claim the full bundle is ready. The requested features
are a co-op downed-player countdown, this overhead host crown, granular sound
controls, removal of overtime tint and banner, and clearer additive versus
multiplicative damage wording. For example, King of Clubs should describe an
additive damage-stat bonus while Voodoo Doll retains multiplicative wording.

The user reported that disabling overtime tint worked. Existing registry mods
[`no-overtime-tint`](https://rsmm.me/registry/no-overtime-tint) and
[`mute-sounds`](https://rsmm.me/registry/mute-sounds) were supplied as starting
points. That report does not validate the other requested features. Keep their
implementation/reuse, licensing, integration and release testing separate from
this crown checkpoint. The immediate next step is the solo crown placement
check above; there is no need to repeat the initial co-op session first.
