# Settings diagnostics navigation

Before: main at `e24868e2a5ae6445ef45df8ed4b45ee4d9c0d70e`, captured before editing.
After: the implementation in this PR.

The before/after comparison uses the same 1280 × 900 browser viewport,
English locale, default appearance, signed-out session, Library preview
fixtures, and empty launcher log. The preview uses the actual desktop React
components without the native Tauri shell or a game installation.

- `before-diagnostics.png` / `after-diagnostics.png`: Settings → Diagnostics.
- `before-account-menu.png` / `after-signin.png`: the result of activating
  the sidebar's Sign in control from that same page.
- `after-minimum-window.png` / `after-collapsed.png`: 960 × 600 with the
  expanded and collapsed sidebar.
- `after-signed-in.png`: account menu with a local, in-memory fictional
  session (Preview Player, player@example.test).

Browser verification covered both diagnostics destinations, direct sign-in
navigation in both sidebar sizes, loading/offline session states, and the
signed-in account menu's arrow-key navigation and Escape focus restoration.
No real account was signed in or out. Native game commands were not executed.
