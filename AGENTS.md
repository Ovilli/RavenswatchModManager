# Agent instructions

## Pull requests that impact UX

Every PR that impacts user experience, including a draft PR, **MUST include before and after screenshots at the top of its description**, before the summary, rationale, or testing notes. This applies to visual changes, user-facing copy, interactions, and user flows.

- Capture the **Before** state from the PR's base branch and the **After** state from the proposed changes. Use comparable data, UI states, and viewport sizes so reviewers can see the effect of the change.
- Embed the actual screenshots in the PR description with clear **Before** and **After** labels. The images must render on GitHub; local file paths, placeholders, and text-only descriptions do not satisfy this requirement.
- For interaction or flow changes, show the affected states or steps. A recording may supplement the screenshots but does not replace them.
- Capture and upload the screenshots before opening the PR, including when opening it as a draft. If capture is blocked, report the blocker instead of opening a UX PR without the required images.

PRs with no UX impact do not require screenshots and should omit the screenshot section.

## Review guidelines

Reviews here look for bugs a player or a maintainer would hit, not style. Biome, ruff, `rsmm lint` and the `ci ok` check already cover formatting, lint and generated-file drift, so leave those to CI. Read [SECURITY.md](SECURITY.md) before reviewing; its "Review focus" section lists the security triggers, and any hit there is P0 or P1.

Flag as P1 when a change:

- Hardcodes an engine address in the loader, the SDK or a mod instead of adding a symbol to `data/symbols.json` and going through `Sym::Name` / `ADDR["Name"]`, or edits `data/symbols.json` without the regenerated artifacts (`rsmm symbols gen`).
- Passes a probed or baked pointer to `R.engine.call` without validating the structure the callee walks. Every in-game loader crash so far was this. Expect `R.engine.call_safe` or an `R.ptr.*` validator in front of the call.
- Lets mod Lua reach engine internals: literal game VAs, `_internal`, `peek`/`poke`, `read_*`/`write_*`, `call_raw` or `engine.resolve` in a mod's `*.lua`. New capability belongs in the SDK (`src/loader/lib/rsmm.lua` and `src/loader/lua/rsmm/`), and each `R.*` submodule owns one concern.
- Ships a mod as a script. Any `*.py` in a mod other than `on_disable.py` is a defect; the capability goes into `rsmm.sdk` and the mod becomes a `manifest.toml`.
- Writes to `<game>/_Save/Profile_*.ob`, or replaces a cooked asset without the `.rsmm.bak` backup and the `.rsmm_state.json` entry that `rsmm restore --all` depends on.
- Adds a data file the frozen CLI needs without adding it to `BUNDLE` in `scripts/build-sidecar.py`.
- Adds a clone path to the `reward` or `melody` kinds. They are override-only on purpose.
- Registers a content kind as `confirmed` in `KIND_CONFIDENCE` without in-game proof, or flips a rating without updating the docs confidence table.

Flag as P2 when a test:

- Mutates a tracked file under `data/`, or runs `cmd_apply` without stubbing `rsmm.engine.find_iyg.main`.
- Uses `monkeypatch.setattr` on `rsmm.engine.paths.MODS_DIR` or `DEFAULT_GAME_DIR`. Use `monkeypatch.setenv("RSMM_MODS_DIR" / "RSMM_GAME_DIR", ...)`.
- Changes an `rsmm.lua` engine-call path without extending `tests/lua/rsmm_spec.lua`.

Core paths (the SDK surface, `src/rsmm/engine/`, `src/loader/` and the desktop design system) need an owner's review. When a PR touches them and changes more than a couple of lines, say so in the review summary so the author requests one.
