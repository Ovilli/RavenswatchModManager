# Sidecar binaries

Tauri runs the bundled Python CLI (`rsmm`) as an external process. The
desktop bundle ships one platform-suffixed binary alongside the app
binary. Filenames must match exactly what Tauri's bundler looks for
based on the host's Rust target triple.

| Platform        | Filename                              |
|-----------------|---------------------------------------|
| Linux (x86_64)  | `rsmm-x86_64-unknown-linux-gnu`       |
| Windows (x64)   | `rsmm-x86_64-pc-windows-msvc.exe`     |
| macOS (Intel)   | `rsmm-x86_64-apple-darwin`            |
| macOS (ARM)     | `rsmm-aarch64-apple-darwin`           |
| macOS (univ.)   | `rsmm-universal-apple-darwin`         |

## Release builds

GitHub Actions (`.github/workflows/release.yml`) compiles the sidecar
with PyInstaller on each matrix runner and drops it next to the Tauri
project before invoking `tauri-action`. No manual steps required on
tagged releases.

## Local development

`tauri dev` and `tauri build` look for a binary matching the host's
target triple. If yours is missing, build it once:

```bash
# from the repo root, with Python 3.11+ on PATH
python -m pip install --upgrade pip pyinstaller
pip install -e .
TRIPLE=$(rustc -vV | sed -n 's/host: //p')   # e.g. x86_64-pc-windows-msvc
pyinstaller --onefile --name "rsmm-${TRIPLE}" \
  --collect-submodules rsmm.cli \
  --collect-submodules rsmm.engine \
  --collect-submodules rsmm.sdk \
  --distpath apps/desktop/src-tauri/binaries \
  ./rsmm
```

On macOS prefer the universal binary so a single build serves both
Intel and Apple Silicon hosts:

```bash
pyinstaller --onefile --name rsmm-universal-apple-darwin \
  --target-arch universal2 \
  --collect-submodules rsmm.cli \
  --collect-submodules rsmm.engine \
  --collect-submodules rsmm.sdk \
  --distpath apps/desktop/src-tauri/binaries \
  ./rsmm
```

The committed `rsmm-x86_64-unknown-linux-gnu` is only there so a fresh
clone on Linux can `pnpm desktop:dev` without first building the
sidecar; regenerate it whenever the Python sources change.
