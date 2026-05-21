# Installation

RSMM runs on **Windows, macOS, and Linux**. Pick your platform below.

## Desktop app (recommended)

The desktop app provides a graphical interface — no terminal needed for everyday use.

### Windows

1. Download [`RSMM-x64.msi`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) from the latest release
2. Double-click the installer and follow the prompts
3. Launch from the Start Menu

### macOS

1. Download [`RSMM-universal.dmg`](https://github.com/Ovilli/RavenswatchModManager/releases/latest)
2. Open the `.dmg` and drag the app to Applications
3. Right-click → Open on first launch (macOS Gatekeeper)

### Linux

| Distro | Package |
|---|---|
| Any (AppImage) | [`RSMM-x86_64.AppImage`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) — `chmod +x` and run |
| Debian / Ubuntu | [`rsmm_amd64.deb`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) |
| Arch Linux | `yay -S rsmm` |
| Other | See CLI install below |

### First run

1. Launch RSMM — it auto-detects your Ravenswatch installation (Steam or other)
2. Click **Doctor** to verify the setup
3. Browse the Registry tab and install mods
4. Click **Apply** to sync mods into the game
5. Click **Play** to launch Ravenswatch

---

## CLI (advanced)

Install from source if you want to author mods, use the command line, or run on a platform without pre-built packages.

### Prerequisites

- **Python 3.11 or newer**
- **Git** (to clone the repository)
- **Ravenswatch** installed

### Linux

```bash
# Build dependencies
sudo apt install build-essential cmake pkg-config

# Clone and install
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Verify
./rsmm doctor

# Create and apply a test mod
./rsmm new TestMod
./rsmm apply
```

### macOS

```bash
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Verify
./rsmm doctor
```

### Windows

```cmd
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager
python -m venv venv
venv\Scripts\activate
pip install -e .

:: Verify
rsmm doctor
```

### pipx (any OS)

```sh
pipx install git+https://github.com/Ovilli/RavenswatchModManager.git
rsmm doctor
```

---

## Lua scripting (Windows only)

Lua mods that run inside the game process require the loader DLL (`winhttp.dll`).

```sh
# Build from source (MinGW or Visual Studio)
cd src/loader
./build.sh           # Linux / macOS cross-compile
# or build.bat       # Windows

# Install into the game
rsmm install-loader
```

For Steam Proton on Linux:
```
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

---

## Verify your setup

```sh
rsmm doctor          # Health check — should pass with no errors
rsmm new TestMod     # Create a test mod
rsmm apply           # Apply all enabled mods
rsmm run             # Launch the game
```

---

## Troubleshooting

### Desktop app won't open
- **Windows**: Install [WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
- **macOS**: Right-click → Open (Gatekeeper bypass)
- **Linux**: `sudo apt install libwebkit2gtk-4.1-dev` (Debian/Ubuntu)

### "Game not found"
Run Ravenswatch through Steam once, then restart RSMM. Or manually set the game path.

### "Permission denied" (Linux)
```sh
sudo chown -R $USER /path/to/Ravenswatch
```

### Still stuck?
Open an issue at [github.com/Ovilli/RavenswatchModManager/issues](https://github.com/Ovilli/RavenswatchModManager/issues) with your OS, game version, and steps.

---

## Next steps

- [Desktop app guide](https://rsmm.dev/getting-started/desktop-app/) — full interface walkthrough
- [Mod Authoring Guide](docs/MODDING.md) — create your first mod
- [CLI Reference](docs/CLI_USAGE.md) — every command explained
