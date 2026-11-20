# Settings diagnostics

Before: main at `e24868e2a5ae6445ef45df8ed4b45ee4d9c0d70e`.
After: the implementation in this PR.

Comparisons use 1280 × 900 viewports, English, default appearance, the same
Library preview fixtures, a signed-out session, and empty logs. Before images
were captured from the base implementation. The browser preview uses the actual
desktop React components without a native Tauri shell or game installation.
The temporary base preview only extends Vite's file allowlist to serve the
shared dependency installation and its bundled fonts.

- `before-diagnostics.png` / `after-diagnostics.png`: Diagnostics now starts
  with the full Game log, followed by Launcher log.
- `before-game-log.png` / `after-diagnostics.png`: the standalone Log page's
  controls now live in the Game log section.
- `before-commands.png` / `after-commands.png`: all command actions and output
  now live below the two logs in Diagnostics.
- `after-privacy.png`: command output followed by Privacy at the bottom.
- `before-account-menu.png` / `after-signin.png`: activating Sign in opens the
  sign-in page directly instead of a menu.
- `after-minimum-window.png` / `after-collapsed.png`: Diagnostics at 960 × 600
  with the expanded and collapsed sidebar.

Browser checks covered the section order, independent log searches, game-log
pause and source selection, List local mods against preview fixtures, canceling
Restore originals, legacy route redirects, and command-palette navigation from
another Settings tab. The initial PR also checked direct sign-in in both
sidebar sizes, loading/offline session states, and signed-in account menu keys.
Native game commands, log-file operations, and public sharing were not executed.
