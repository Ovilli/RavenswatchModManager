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

- **Enable/Disable** — toggle a mod on or off without uninstalling it (the same
  switch is on the mod's own page, with the same dependency prompts)
- **Configure** — appears only on mods that declare config fields; opens that
  mod's settings on its page. The library's config view lists every
  configurable mod at once
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
whatever the mod measures. A mod that ships one gets an **Overlay** button on
its own library card, list row, and mod page — click it to open the window,
click again (**Hide overlay**) to close it. The command palette has an entry
per overlay too. A mod with no overlay shows no button.

- Drag it by its header; drag the **bottom-right corner** to resize. It sizes
  itself to its contents until you resize it by hand, after which it stays put.
  Each overlay remembers its own position and size; **shift-click** the Overlay
  button to reopen it at the default position if it lands off-screen.
- **Compact** hides the footer.
- **Click-through** lets clicks pass to the game. Undo it with
  **Ctrl+Alt+O** without leaving the game — a click-through window cannot
  receive the click that would disable it, which is why the shortcut exists.
- An overlay can only sit on top of Ravenswatch if the game runs **borderless
  windowed** rather than exclusive fullscreen.

The client draws the shape the mod declared and fills it with the rows the mod
published; it never runs mod code. `rsmm overlay <mod>` shows the same data in
a terminal.

## Profiles

You can create multiple profiles — separate sets of enabled mods for different playthroughs. Switch between them from the profile dropdown.

## Language

Settings → Appearance → **Language** switches the interface between English and
简体中文 (Simplified Chinese). The change applies immediately — no restart — and
is remembered per machine.

On a fresh install the language is picked from the languages your OS reports:
anything Chinese (`zh`, `zh-Hans`, `zh-TW`, …) starts in Simplified Chinese,
everything else starts in English. After that it is whatever you chose, and is
never re-detected.

Three kinds of text stay in their own language by design, because RSMM does not
author them:

- output from the `rsmm` command-line tool (the Commands page, doctor findings,
  the raw text behind an error),
- anything a mod supplies — an overlay's columns, a config field's label, a
  mod's store description,
- the game's own strings.

Selecting a CJK language also appends a CJK font stack to every typeface preset,
so Chinese text renders in a coherent face while Latin text keeps the preset you
chose.

Adding a language means adding a catalog under `apps/desktop/src/locales/`; the
`coverage.test.ts` suite fails the build if a catalog is missing an entry, keeps
one nothing renders any more, drops a `{placeholder}`, or lets a glossary term
drift (profile 方案, overlay 悬浮窗, loader 加载器, mod 模组, …).

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
