---
title: CLI reference
description: rsmm subcommands.
---

| Command | What it does |
|---|---|
| `rsmm build` | Build asset map + loader DLL + merge + apply |
| `rsmm apply` | Install mods/ into the game |
| `rsmm doctor` | Health check |
| `rsmm run` | Launch Ravenswatch |
| `rsmm watch` | Auto-reapply on every mods/ change |
| `rsmm new <id>` | Scaffold a new mod folder |
| `rsmm pack <id>` | Bundle a mod into `dist/<id>.zip` |
| `rsmm restore --all` | Roll back every applied override |

All commands accept `--json` for machine output (consumed by the desktop UI).
