# Installation

> **Already have RSMM?** Jump to the [quick start](#quick-start) or [CLI reference](CLI_USAGE.md).

RSMM has two parts:

1. **Python CLI** (`rsmm`) — applies mods, manages assets. Cross-platform. Required for everything.
2. **Loader DLL** (`winhttp.dll`) — runs Lua scripts inside the game. Windows only. Optional.

You only need the Python CLI for cooked-asset mods (textures, stats, text). Add the loader DLL if you want Lua scripting.

---

## Quick start

```sh
# 1. Install Python 3.11+ and clone
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager

# 2. Set up Python environment
python3 -m venv .venv
source .venv/bin/activate      # Linux
# venv\Scripts\activate        # Windows

pip install -e .

# 3. Verify
./rsmm --version
./rsmm doctor

# 4. Create and apply a test mod
./rsmm new TestMod
./rsmm apply
```

If `./rsmm doctor` passes, you're ready. See [Mod Authoring](MODDING.md) for what to do next.

---

## Prerequisites

- **Python 3.11 or newer**
- **Ravenswatch** installed (Steam or other)
- **Git** (to clone the repository)

---

## Linux

### 1. Install build dependencies

```bash
sudo apt install build-essential cmake pkg-config
```

### 2. Set up Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Verify

```bash
./rsmm --version
./rsmm doctor
```

### 4. (Optional) Build the loader DLL for Lua mods

```bash
cd src/loader
./build.sh
# Binary appears in dist/winhttp.dll (cross-compiled for Windows via MinGW)
```

### 5. (Optional) Install the loader into the game

```bash
./rsmm install-loader
```

For Steam + Proton, add this launch option:
```
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

---

## Windows

### Option A: Quick start (recommended)

```cmd
:: 1. Install Python 3.11+ from python.org (check "Add to PATH")

:: 2. Clone and set up
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager
python -m venv venv
venv\Scripts\activate
pip install -e .

:: 3. Verify
rsmm --version
rsmm doctor
```

### Option B: Build from source (for Lua mods)

Requires Visual Studio 2019+ with C++ workload or MinGW-w64.

```cmd
:: Same Python setup as Option A
python -m venv venv
venv\Scripts\activate
pip install -e .

:: Build the loader
cd src\loader
fetch_deps.bat
build.bat

:: Install into the game
rsmm install-loader
```

---

## Verify your setup

```sh
rsmm doctor          # Health check — should pass with no errors
rsmm new TestMod     # Create a test mod
rsmm apply           # Apply all enabled mods
rsmm run             # Launch the game
```

See [CLI Reference](CLI_USAGE.md) for all available commands.

---

## Troubleshooting

### `rsmm: command not found`

Activate your virtual environment:

```cmd
:: Windows
venv\Scripts\activate

:: Linux/macOS
source .venv/bin/activate
```

### Loader DLL not loading in-game

1. Verify the file exists next to `Ravenswatch.exe`:
   ```cmd
   dir "C:\path\to\Ravenswatch\winhttp.dll"
   ```
2. Check the loader log:
   ```sh
   ./rsmm log
   ```
3. Ensure Steam launch options include the DLL override (see above).

### Python version mismatch

Ensure Python 3.11+ is active:

```sh
python --version
```

### CMake not found (Windows)

1. Download from [cmake.org](https://cmake.org/download/)
2. Add to PATH during installation, or manually:
   ```cmd
   setx PATH "%PATH%;C:\Program Files\CMake\bin"
   ```

### Mods not applying

Run the health check:

```sh
./rsmm doctor
```

### Still stuck

Open an issue at [github.com/Ovilli/RavenswatchModManager/issues](https://github.com/Ovilli/RavenswatchModManager/issues) with your OS, game version, and steps to reproduce.

---

## Next steps

- [Mod Authoring Guide](MODDING.md) — create your first mod
- [CLI Reference](CLI_USAGE.md) — every command explained
- [Documentation Home](README.md) — all guides
