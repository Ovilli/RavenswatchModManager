# Security policy

## Reporting a vulnerability

Please **don't** open a public issue. Report it privately instead:

- [Open a private security advisory](https://github.com/Ovilli/RavenswatchModManager/security/advisories/new), or
- email [contact@rsmm.me](mailto:contact@rsmm.me) with "security" in the subject.

Include what you found, how to reproduce it and which part is affected (desktop app,
CLI, loader, rsmm.me or the API). We'll acknowledge within a few days and keep you
updated until it's fixed.

## Scope

- The desktop app and its updater, the `rsmm` CLI, the Lua loader (`winhttp.dll`).
- rsmm.me, its API and the mod registry, including the upload scan pipeline.
- Mod archives that escape their sandbox (path traversal, writes outside the game
  folder, code that runs without the loader).

Only the latest release is supported. How RSMM treats mods as untrusted input is
described in the [security reference](https://docs.rsmm.me/reference/security/).
