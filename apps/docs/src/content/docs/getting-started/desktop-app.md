---
title: Using the desktop app
description: A complete guide to RSMM's graphical interface.
---

The RSMM desktop app lets you browse, install, and manage mods entirely through a graphical interface.

## Overview

The window is organized into several tabs:

| Tab | What it does |
|---|---|
| **Registry** | Browse and search mods uploaded by the community |
| **Installed** | View, enable, disable, or uninstall your local mods |
| **Browse** | (Coming soon) Explore mods by category |
| **About** | Version info, links, and app credits |

## Game path

The first time you launch RSMM, it tries to auto-detect your Ravenswatch installation:

- **Steam (Windows)**: `C:\Program Files (x86)\Steam\steamapps\common\Ravenswatch`
- **Steam (Linux/Proton)**: Detected from Steam library
- **Other**: Point the app to the folder containing `Ravenswatch.exe`

If auto-detection fails, you can set the path manually in Settings.

## Installing a mod

1. Open the **Registry** tab
2. Browse or search for a mod
3. Click on a mod card to see full details
4. Click **Install** to download the mod
5. Switch to the **Installed** tab to see it
6. Click **Apply** in the toolbar to copy mod files into the game

## Managing mods

In the **Installed** tab:

- **Enable/Disable** — toggle a mod on or off without uninstalling it
- **Uninstall** — remove a mod completely
- **View details** — click a mod to see its description, version history, and files

After any change, click **Apply** to sync your selection to the game.

## Health check

Click the **Doctor** button to verify:

- Your game installation is found and accessible
- The asset map is up to date
- All installed mods have valid files
- No conflicts between mods

If anything is wrong, the Doctor will show warnings and suggest fixes.

## Running the game

Click **Play** to launch Ravenswatch directly from RSMM. The app applies any pending changes before starting the game.

## Profiles

You can create multiple profiles — separate sets of enabled mods for different playthroughs. Switch between them from the profile dropdown.

## Cross-platform notes

RSMM works identically on **Windows, macOS, and Linux**. The interface, features, and workflow are the same on all platforms.

### Platform-specific differences

| Feature | Windows | macOS | Linux |
|---|---|---|---|
| Desktop app | ✅ MSI installer | ✅ DMG (Intel + Apple Silicon) | ✅ AppImage / DEB |
| CLI | ✅ via Python | ✅ via Python | ✅ via Python |
| Lua scripting | ✅ Native DLL | ❌ Not supported | ❌ Not supported (Proton: partial) |
| Texture/stat/text mods | ✅ | ✅ | ✅ |
| Steam auto-detect | ✅ Comprehensive | ✅ Standard library | ✅ Flatpak + native + /mnt |
| Apple Silicon | N/A | ✅ Native (Tauri universal) | N/A |

### Lua scripting

Lua-based mods that run code inside the game process are **Windows-only**. The desktop app will show these as "not supported on this platform" if you're on macOS or Linux. Texture swaps, stat edits, and text overrides work on all platforms.

For Steam Proton on Linux, Lua mods can work with additional setup (Wine DLL overrides), but this is experimental.

### Game path detection

The app searches for Ravenswatch in these locations:

- **Windows**: `Program Files (x86)`, `Program Files`, `Steam`, `SteamLibrary`, `Games/Steam` on all drives (C: through Z:)
- **macOS**: `~/Library/Application Support/Steam/steamapps/common/Ravenswatch` and external volume Steam libraries
- **Linux**: Flatpak Steam, native Steam (`~/.steam`, `~/.local/share/Steam`), and `/mnt` for externally mounted libraries

If your game isn't found automatically, set the path manually in Settings.
