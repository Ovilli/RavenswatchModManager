# Desktop auto-updater

The desktop app uses the official Tauri v2 updater plugin. Releases built by
`.github/workflows/release.yml` ship signed bundles plus a `latest.json`
manifest that the client polls for new versions.

## One-time setup (release maintainer)

1. **Generate a signing key.** From the repo root, run:

   ```bash
   pnpm --filter desktop tauri signer generate -w ~/.tauri/rsmm.key
   ```

   This produces two files. Keep `~/.tauri/rsmm.key` private; the matching
   `.pub` file goes into the app config.

2. **Set the public key in `tauri.conf.json`.** Replace the empty
   `plugins.updater.pubkey` value with the contents of the `.pub` file.

3. **Add GitHub repo secrets:**

   - `TAURI_SIGNING_PRIVATE_KEY` — contents of `~/.tauri/rsmm.key`
   - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` — the password chosen at generation
     time (empty string if no password)

4. **Tag a release.** Push a tag matching `v*` and the workflow will:

   - build MSI (Windows), AppImage + .deb (Linux),
   - sign each bundle with the private key,
   - publish a draft release with `latest.json` next to the artifacts.

5. **Publish** the draft release. The client now picks up the update on next
   launch. Check failures are not silent: a banner with the failure reason
   and a Retry button is shown, and the error is written to the launcher log
   (Settings → Launcher Log).

## How clients consume updates

- `UpdaterBanner` (`components/updater.tsx`, mounted in `routes/__root.tsx`)
  runs a check ~1.5 s after startup. A newer version auto-downloads and then
  prompts the user to restart; download progress is shown in a compact bar.
- If the check or the download fails, an error banner with the reason and a
  Retry button is rendered, and the failure is appended to the launcher log.
- `UpdaterSettings` in `routes/settings.tsx` lets the user check manually,
  see release notes, and shows the same check/download errors inline.
- Selecting **Restart & update** verifies the signature, swaps the binary,
  and relaunches via `tauri-plugin-process`. A failed relaunch tells the
  user to restart manually (the new version is already installed by then).

## Cross-platform notes

- **Windows** — NSIS installer. The updater runs the new installer in place.
- **Linux** — AppImage. The updater rewrites the AppImage on disk; the OS
  handles the rest on next launch.

### Linux installs the updater cannot write to

The updater only ever rewrites the *running* binary, so two Linux cases
dead-end: a `.deb` install (the binary is `/usr/bin/...`, root-owned, and
`$APPIMAGE` is unset) and an AppImage parked somewhere root-owned (`/opt`, an
AppImageLauncher store). Before this was handled, both meant a manual reinstall
on **every** release.

`src-tauri/src/update_env.rs` detects the state up front — the plugin otherwise
only reports `Permission denied (os error 13)` after a full download — and
`src-tauri/src/update_migrate.rs` provides the way out:

1. The pending update is downloaded through `Update::download()`, so its
   minisign signature is verified against the same embedded pubkey as any
   other update. Nothing unsigned is ever written.
2. The payload is checked for the AppImage type-2 marker, staged under a
   PID-qualified name, `chmod 0755`, and renamed to
   `~/Applications/RavenswatchModManager.AppImage`.
3. The system `.desktop` entry (found by matching `Exec=` against the running
   binary, not by guessing its name) is copied to
   `~/.local/share/applications` under the **same file name** — which shadows
   `/usr/share/applications` — with only `Exec=` repointed and `TryExec=`
   dropped. `Name`, `Icon`, `StartupWMClass` and the
   `x-scheme-handler/rsmm` registration the OAuth deep link needs all survive;
   themed icons are copied into `~/.local/share/icons` so they outlive the
   package.
4. The app queues the new AppImage on a 2-second delay and quits through
   `quitApp()`. The delay is load-bearing: `tauri-plugin-single-instance` would
   otherwise hand the new process's argv to the dying one and the new copy
   would exit immediately.

Nothing outside `$HOME` is touched — the old system copy stays where the
package manager put it, and the UI reports the `apt remove` line for it. From
the next launch `$APPIMAGE` is set, so the ordinary in-place updater takes over
and the migration never runs again.

If the feed reports no newer version, the banner stays hidden. If
`latest.json` is missing/unreachable or the signature does not match the
embedded public key, the check errors and the failure banner explains why
(the same reason is logged to the launcher log for bug reports).
