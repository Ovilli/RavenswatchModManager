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

   - build MSI (Windows), DMG (macOS), AppImage + .deb (Linux),
   - sign each bundle with the private key,
   - publish a draft release with `latest.json` next to the artifacts.

5. **Publish** the draft release. The client now picks up the update on next
   launch (auto-check is silent; failures don't surface to the user).

## How clients consume updates

- `UpdaterBanner` in `routes/__root.tsx` runs a silent check ~1.5 s after
  startup and shows a banner above the main content if a newer version is
  available.
- `UpdaterSettings` in `routes/settings.tsx` lets the user check manually and
  see release notes.
- Selecting **Install & restart** downloads, verifies the signature, swaps
  the binary, and relaunches via `tauri-plugin-process`.

## Cross-platform notes

- **Windows** — installer is MSI. Updater applies a new MSI in-place.
- **macOS** — universal `.app` inside a DMG. Updater swaps the bundle.
- **Linux** — AppImage. Updater rewrites the AppImage on disk; the OS handles
  the rest on next launch.

If `latest.json` is missing or the signature does not match the embedded
public key, the updater returns no update and the banner stays hidden.
