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

- **Windows** — installer is MSI. Updater applies a new MSI in-place.
- **Linux** — AppImage. Updater rewrites the AppImage on disk; the OS handles
  the rest on next launch.

If the feed reports no newer version, the banner stays hidden. If
`latest.json` is missing/unreachable or the signature does not match the
embedded public key, the check errors and the failure banner explains why
(the same reason is logged to the launcher log for bug reports).
