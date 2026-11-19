# Library browser preview

Run `pnpm --filter desktop dev:library`, or open
[the preview](http://localhost:1420/?preview=library) on an existing Vite dev server.
No game installation, Tauri shell, or RSMM CLI is needed.

The preview uses the real Library UI with 16 fictional mods across eight
categories. There are four profiles, including an empty one, plus enabled and
disabled mods, two updates, a conflict, a missing dependency, and editable
sample settings. Edit `library-preview.ts` to change the fixtures.

Search, filters, list/config views, selection, toggles, load order,
uninstall, and profile management work against memory. Reload to restore the
fixtures. The preview remains enabled while navigating in the same browser
tab; **Exit preview** returns to ordinary browser mode.

Saved profiles and settings use an isolated memory store. No sample action
downloads or installs files. Browse still reads the public registry; arbitrary
registry installs, game launches, and other native actions are not simulated.
The preview is disabled in Tauri and production builds, and the fixture module
is omitted from the production bundle.
