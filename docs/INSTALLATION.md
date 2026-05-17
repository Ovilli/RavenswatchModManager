Installation
============

Platform-agnostic notes and installation steps for Linux and Windows.

## Quick Overview

The mod manager consists of two parts:
1. **Python CLI tool** (`rsmm`) — cross-platform, manages mod installation and patching
2. **Native loader DLL** (`winhttp.dll`) — Windows only, injects Lua runtime into the game

For **modding without Lua scripting**, you only need the Python tool. For **Lua mods with hot-reload**, you also need the loader DLL.

---

## Common Prerequisites

- **Python 3.10+** (for `rsmm` tools)
- **Ravenswatch** installed on your system

---

## Linux Installation

### 1. Install Build Dependencies

```bash
sudo apt install build-essential cmake pkg-config
```

### 2. Build the Loader (Optional, only needed for Lua mods)

```bash
cd src/loader
./build.sh
# Binary appears in dist/winhttp.dll (cross-compiled for Windows via MinGW)
```

### 3. Set Up Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### 4. Verify Installation

```bash
./rsmm --version
./rsmm doctor
```

---

## Windows Installation

### Option A: Quick Start (Prebuilt Loader)

**Best for modders who just want to start modding quickly.**

1. **Install Python 3.10+**
   - Download from [python.org](https://www.python.org/downloads/) (Windows installer)
   - During installation, **check "Add Python to PATH"**
   - Verify: Open `cmd` and run:
     ```cmd
     python --version
     ```

2. **Clone the repository and set up Python environment**
   ```cmd
   git clone https://github.com/Ovilli/RavenswatchModManager.git
   cd RavenswatchModManager
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   pip install -e .
   ```

3. **Download prebuilt loader**
   - Check the [Releases](../../releases) page for `winhttp.dll`
   - Place it in `dist/` folder (or let the manager download it automatically)

4. **Verify installation**
   ```cmd
   rsmm --version
   rsmm doctor
   ```

### Option B: Build from Source on Windows

#### Using Visual Studio (Recommended)

**Prerequisites:**
- Visual Studio 2019+ with C++ workload (download from [visualstudio.microsoft.com](https://visualstudio.microsoft.com/))
- CMake (included with Visual Studio or install separately from [cmake.org](https://cmake.org/download/))
- Python 3.10+ (see Option A, step 1)

**Build steps:**

1. Open **Developer Command Prompt for VS** (search in Windows Start menu)

2. Set up Python environment:
   ```cmd
   cd RavenswatchModManager
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   pip install -e .
   ```

3. Build the loader:
   ```cmd
   cd src\loader
   mkdir build
   cd build
   cmake .. -G "Visual Studio 17 2022" -A x64
   cmake --build . --config Release
   ```
   
   The compiled `winhttp.dll` will be in `build\Release\` (or `build\bin\Release\`).

4. Copy to distribution folder:
   ```cmd
   copy Release\winhttp.dll ..\..\dist\
   ```

#### Using MinGW (Alternative)

**Prerequisites:**
- MinGW-w64 with GCC 11+ (download from [mingw-w64.org](https://www.mingw-w64.org/))
- CMake (from [cmake.org](https://cmake.org/download/))

**Build steps:**

1. Open **MinGW Shell** or a terminal with MinGW in PATH

2. Set up Python and navigate to repo:
   ```bash
   cd RavenswatchModManager
   python -m venv venv
   source venv/Scripts/activate  # (or venv\Scripts\activate on cmd)
   pip install -r requirements.txt
   pip install -e .
   ```

3. Build the loader:
   ```bash
   cd src/loader
   mkdir build
   cd build
   cmake .. -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
   cmake --build .
   ```

4. Copy to distribution folder:
   ```bash
   cp winhttp.dll ../../dist/
   ```

---

## Testing Your Installation

### 1. Verify Python CLI works

```cmd
rsmm --version
rsmm doctor
```

Expected: No errors, all checks pass.

### 2. Create a test mod

```cmd
rsmm new TestMod
cd mods\TestMod
```

Edit `manifest.toml` and set `enabled = true`.

### 3. Apply mods to the game

```cmd
rsmm apply
```

### 4. Install the loader (for Lua mods only)

```cmd
rsmm install-loader
```

This copies `winhttp.dll` into the Ravenswatch game installation directory.

### 5. Configure Steam launch options (if using Steam)

Right-click **Ravenswatch** in your Steam library → **Properties** → **Launch Options**:

**For native Windows:**
```
(leave blank, or add custom mods)
```

**For Proton on Linux/Steam Deck:**
```
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

### 6. Launch the game

```cmd
rsmm run
```

Or manually launch via Steam/the launcher.

---

## Troubleshooting

### "rsmm: command not found"

Make sure you activated the virtual environment:

```cmd
venv\Scripts\activate
```

If using PowerShell and it complains about execution policy:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
venv\Scripts\Activate.ps1
```

### CMake not found

1. Download CMake from [cmake.org](https://cmake.org/download/) (Windows installer)
2. Add CMake to PATH during installation, or manually:
   ```cmd
   setx PATH "%PATH%;C:\Program Files\CMake\bin"
   ```
3. Restart your terminal and retry

### Loader DLL not loading in-game

1. Verify the file exists:
   ```cmd
   dir "C:\path\to\Ravenswatch\winhttp.dll"
   ```

2. Check the log file:
   ```cmd
   rsmm log
   ```

3. If using Steam, ensure launch options include the DLL override (see step 5 above)

### Python version mismatch

Ensure you're using Python 3.10+:
```cmd
python --version
```

If wrong version, uninstall and reinstall from [python.org](https://www.python.org/downloads/).

---

## Next Steps

- See [MOD_AUTHORING.md](MOD_AUTHORING.md) for how to create a mod
- See [MODDING.md](MODDING.md) for full authoring recipes and hot-reload workflow
- See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues
