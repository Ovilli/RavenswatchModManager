---
title: Contributing
description: How to contribute to RSMM.
---

Thanks for helping. Bug reports, mods, docs fixes and reverse-engineering findings
are all welcome.

- **Set up:** [Development setup](/contributing/setup/) covers the
  Python CLI, the desktop app, the website and the loader.
- **How it fits together:** [Architecture](/architecture/overview/).
  `CLAUDE.md` is a dense technical brief of the whole repo.
- **Before you open a PR:**
  ```sh
  ruff check .                 # Python lint
  pnpm test:python:fast        # Python tests (~2 s)
  pnpm test:ts                 # TypeScript tests
  lua tests/lua/rsmm_spec.lua  # Lua SDK, if you touched src/loader/lib or src/loader/lua
  ```
  Edited `data/symbols.json`? Run `rsmm symbols gen`. CI runs all of the above.
- **Keep PRs small** and say how you tested. In-game changes need a note on what you
  saw in game.

## Ground rules

- **No game files in the repo.** Commit code, manifests and your own assets only.
  Never commit anything extracted from Ravenswatch.
- **Nothing that unlocks paid content.** DLC heroes, outfits and other bought content
  stay behind their ownership check. PRs or mods that open them are closed.
- **Mods ship data, not code.** New capability goes into the SDK; mods consume it
  through a `manifest.toml` and high-level `R.*` calls. `rsmm lint` enforces this.
- **No hardcoded engine addresses.** Add a symbol to `data/symbols.json` instead.

Be kind, see the [code of conduct](https://github.com/Ovilli/RavenswatchModManager/blob/main/CODE_OF_CONDUCT.md). Security issues go through
the [security policy](https://github.com/Ovilli/RavenswatchModManager/blob/main/SECURITY.md), not public issues.

## Report issues

Search existing issues first. Use the bug report form and include your OS, RSMM
version and the `rsmm doctor` output.

## Support the project

RSMM is free and MIT-licensed; there is no paid tier and nothing is held back for
donors. If you would rather chip in than file a PR: [ko-fi.com/ovilli](https://ko-fi.com/W7W41FW3YE).
