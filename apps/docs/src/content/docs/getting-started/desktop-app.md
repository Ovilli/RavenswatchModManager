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

## Overlays

Mods can publish a small always-on-top window — a damage meter, a run timer,
whatever the mod measures. **Settings → Overlays** lists every installed mod
that declares one, with an Open/Close button each; the command palette has an
entry per overlay too.

- Drag it by its header; drag the **bottom-right corner** to resize. It sizes
  itself to its contents until you resize it by hand, after which it stays put.
  Each overlay remembers its own position and size; **Recentre** puts it back
  if it opens off-screen.
- **Compact** hides the footer.
- **Click-through** lets clicks pass to the game. Undo it with
  **Ctrl+Alt+O** without leaving the game (or the button in Settings) — a
  click-through window cannot receive the click that would disable it, which
  is why the shortcut exists.
- An overlay can only sit on top of Ravenswatch if the game runs **borderless
  windowed** rather than exclusive fullscreen.

The client draws the shape the mod declared and fills it with the rows the mod
published; it never runs mod code. `rsmm overlay <mod>` shows the same data in
a terminal.

## Profiles

You can create multiple profiles — separate sets of enabled mods for different playthroughs. Switch between them from the profile dropdown.

## Cross-platform notes

RSMM works identically on **Windows and Linux**. The interface, features, and workflow are the same on both platforms. (macOS is not supported.)

### Platform-specific differences

| Feature | Windows | Linux |
|---|---|---|
| Desktop app | ✅ MSI installer | ✅ AppImage / DEB |
| CLI | ✅ via Python | ✅ via Python |
| Lua scripting | ✅ Native DLL | ❌ Not supported (Proton: partial) |
| Texture/stat/text mods | ✅ | ✅ |
| Steam auto-detect | ✅ Comprehensive | ✅ Flatpak + native + /mnt |

### Lua scripting

Lua-based mods that run code inside the game process are **Windows-only**. The desktop app will show these as "not supported on this platform" if you're on Linux. Texture swaps, stat edits, and text overrides work on both platforms.

For Steam Proton on Linux, Lua mods can work with additional setup (Wine DLL overrides), but this is experimental.

### Game path detection

The app searches for Ravenswatch in these locations:

- **Windows**: `Program Files (x86)`, `Program Files`, `Steam`, `SteamLibrary`, `Games/Steam` on all drives (C: through Z:)
- **Linux**: Flatpak Steam, native Steam (`~/.steam`, `~/.local/share/Steam`), and `/mnt` for externally mounted libraries

If your game isn't found automatically, set the path manually in Settings.
