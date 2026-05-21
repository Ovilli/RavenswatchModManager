---
title: Installation
description: Install the Ravenswatch Mod Manager on Windows, macOS, or Linux.
---

RSMM is a **cross-platform** mod manager. Download the desktop app for your operating system — no terminal required for everyday use.

## Desktop app (recommended)

The desktop app gives you a graphical interface to browse, install, and manage mods. No command line needed.

### Windows

1. Download [`RSMM-x64.msi`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) from the latest release
2. Double-click the `.msi` file and follow the installer steps
3. Launch **Ravenswatch Mod Manager** from the Start Menu
4. Point the app to your Ravenswatch installation (auto-detected for Steam)

### macOS

1. Download [`RSMM-universal.dmg`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) from the latest release
2. Open the `.dmg` and drag **Ravenswatch Mod Manager** to your Applications folder
3. Launch from Applications (right-click → Open the first time to bypass Gatekeeper)
4. Point the app to your Ravenswatch installation

> **macOS Gatekeeper**: The first launch may show "Ravenswatch Mod Manager is from an unidentified developer." Right-click the app → Open, then click Open in the dialog. This only happens once.

### Linux

- **AppImage** (universal): Download [`RSMM-x86_64.AppImage`](https://github.com/Ovilli/RavenswatchModManager/releases/latest), make it executable (`chmod +x`), and run it
- **Debian/Ubuntu**: Download [`rsmm_amd64.deb`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) and install it
- **Arch Linux**: [Install from AUR](https://aur.archlinux.org/packages/rsmm) (`yay -S rsmm`)
- **Other distros**: Install via [`pipx`](#pipx-install-linux-macos-windows) or build from source

### First run

When you launch the desktop app for the first time:

1. **Set your game path** — the app will try to find your Ravenswatch install automatically. If it can't, browse to the folder containing `Ravenswatch.exe`
2. **Run health check** — click the Doctor button to verify everything is set up correctly
3. **Browse mods** — visit the Registry tab to discover and install mods from the community
4. **Apply changes** — click Apply to install your selected mods into the game

## CLI (advanced users)

If you prefer the command line or want to author mods, install the Python CLI:

### Prerequisites

- **Python 3.11 or newer**
- **Git** (to clone the repository)
- **Ravenswatch** installed (Steam or other)

### Quick install

```sh
# Clone the repository
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager

# Set up Python environment
python3 -m venv .venv

# Linux / macOS
source .venv/bin/activate
# Windows
# venv\Scripts\activate

pip install -e .

# Verify
./rsmm doctor
```

### Platform-specific setup

#### Windows

```cmd
python -m venv venv
venv\Scripts\activate
pip install -e .
rsmm doctor
```

#### macOS

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
./rsmm doctor
```

#### Linux

```sh
sudo apt install build-essential cmake pkg-config  # build deps
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
./rsmm doctor
```

## pipx install (Linux, macOS, Windows)

```sh
pipx install git+https://github.com/Ovilli/RavenswatchModManager.git
rsmm doctor
```

## Lua scripting (Windows only; experimental on Steam Proton)

Lua mods require the loader DLL (`winhttp.dll`) placed next to `Ravenswatch.exe`. This primarily works on Windows because it hooks into the game process. On Linux with Steam Proton, it may work with additional Wine configuration.

```sh
# Build from source (requires MinGW or Visual Studio)
cd src/loader
./build.sh           # Linux / macOS cross-compile
# or build.bat       # Windows

# Install into the game
rsmm install-loader
```

For Steam Proton on Linux, add this launch option:
```
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

## Next steps

- [Your first mod](/getting-started/first-mod/) — create and apply a mod in minutes
- [CLI reference](/reference/cli/) — every command explained
- [GitHub](https://github.com/Ovilli/RavenswatchModManager) — source code and issues
