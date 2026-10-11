---
title: Troubleshooting
description: Fixes for the most common problems, sorted by what you're seeing.
---

Find what you're seeing below. Each answer starts with the most likely fix.

## Try this first: the health check

Most problems are found by RSMM's own health check.

- **In the app:** open **Commands** and press **Doctor**. If it finds problems it
  can fix, press **Doctor + repair**.
- **With the modding tools:** run `rsmm doctor`, or `rsmm doctor --fix` to repair
  what it safely can.

Each line it prints is `OK`, `WARN` (worth reading) or `FAIL` (needs fixing), and
a failing line usually says how to fix it.

## The app

### The app won't open (Windows)

Install [Microsoft WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
(the *Evergreen Bootstrapper*) and try again. Windows 11 and most Windows 10
computers already have it.

### The app won't open, or the window is gray (Linux)

If the window is **gray or empty** (common on Debian and Ubuntu), start the app
from a terminal with these settings:

```sh
WEBKIT_DISABLE_DMABUF_RENDERER=1 WEBKIT_DISABLE_COMPOSITING_MODE=1 ./Ravenswatch.Mod.Manager_*.AppImage
```

If that fixes it, the cause is your graphics driver or desktop, not RSMM.

If the app **doesn't open at all**, make sure WebKitGTK 4.1 is installed:

```sh
sudo apt install libwebkit2gtk-4.1-0     # Debian / Ubuntu
sudo dnf install webkit2gtk4.1           # Fedora
sudo pacman -S webkit2gtk-4.1            # Arch
```

### The app can't find my game

1. In Steam, right-click **Ravenswatch** → **Manage** → **Browse local files**.
   Copy the address of the folder that opens.
2. In the app, open **Settings → General** and paste it into **Game install**.

If Ravenswatch has never been started, start it once through Steam first.

### "Permission denied" (Linux)

RSMM can't write to the game folder. This happens most often with a Steam library
on a second drive. Give your user ownership of the game folder:

```sh
sudo chown -R $USER "/path/to/Ravenswatch"
```

### An error mentions Python

The app carries its own copy of everything it needs, so you never install Python
for it. An error like this means the app's files are damaged. Reinstall the app.

### The PC freezes or blue-screens while the app is open (Windows)

The app draws with your graphics card, like a web browser does. That's enough to
expose a broken **graphics driver**, and a driver crash takes down the whole
computer, not just the app.

1. **Reinstall your graphics driver** from NVIDIA, AMD or Intel. If the crashes
   started after a driver update, go back to the previous version.
2. **Close overlays** that hook into graphics, such as Discord's overlay,
   GeForce Experience or MSI Afterburner, while you test.
3. **As a workaround**, open **Settings → Game** and tick **Disable GPU
   acceleration (software rendering)**, then restart the app. The app stops using
   your graphics card. This hides the problem in RSMM, but the driver is still
   broken for other programs.

<details>
<summary>Want to confirm it's the driver?</summary>

Run this in PowerShell:

```powershell
Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,1001,6008} -MaxEvents 5 | Format-List
```

A crash named `VIDEO_SCHEDULER_INTERNAL_ERROR` (`0x119`), `VIDEO_TDR_FAILURE`
(`0x116`) or `DPC_WATCHDOG_VIOLATION` comes from the display driver. Normal
programs can't cause these by themselves. To see which driver, open
`C:\Windows\Minidump\*.dmp` in WinDbg and run `!analyze -v`: `IMAGE_NAME` names it.

</details>

## Mods

### My mods don't show up in the game

Check these in order:

1. **Did you start the game with Launch Modded?** If you start Ravenswatch from
   Steam, you get the normal game, because RSMM takes the mods out again when the
   game closes. (Want mods when starting from Steam? Use **Commands → Apply
   mods**.)
2. **Are you in the right profile?** The profile name is at the top left. The
   **Default** profile is always the plain game. Switch to the profile that has
   your mods.
3. **Is the mod switched on?** Check its switch in the **Library**.
4. **Did you change a mod's settings while the game was running?** Quit the game
   completely and press **Launch Modded** again.
5. **Run the health check:** **Commands → Doctor**.

### The game crashes or won't start

1. **Press Launch Vanilla.** If the plain game also crashes, the problem isn't a
   mod. Verify the game in Steam: right-click Ravenswatch → **Properties** →
   **Installed Files** → **Verify integrity of game files**.
2. **Find the mod that causes it.** Switch off half your mods and try again. If
   the crash is gone, the culprit is in the half you switched off. Keep halving
   until you find it.
3. **Check the Log page.** If a script mod crashes the game three times in a row
   while it's starting, RSMM skips it on the next start and the **Log** page says
   which mod. Press **Try again** once it's fixed.

With the modding tools, `rsmm safe-mode` switches off every mod and re-applies, so
you can start from a clean slate.

### "Conflicts" appeared in the sidebar

Two of your switched-on mods change the same part of the game. Open the
**Conflicts** page to see which. Only one can win (the one that loads later), so
switch off the one you want less.

### A mod shows "missing deps"

The mod needs another mod to work. Its page names the missing one. Install it from
**Browse**.

### The game updated and my mods stopped working

A game update replaces files and switches your mods off. The app shows **Ravenswatch
updated — your mods were disabled by the game update**. Press **Repair**, then
**Launch Modded**.

Still broken? The mod may need an update from its author. Check the **Library**
for updates.

With the modding tools: `rsmm restore --all`, verify the game files in Steam,
then `rsmm apply`.

### I want the plain game back

- **For one session:** press **Launch Vanilla**.
- **For good:** **Commands → Restore originals**, or `rsmm restore --all`.
- **To be extra sure:** verify the game files in Steam.

`rsmm restore --all` is safe to run as often as you like. If you see leftover
files ending in `.rsmm.bak` in the game folder, a restore was interrupted; run it
again.

## Script (Lua) mods

### Script mods don't do anything

Script mods need the **loader**, a file called `winhttp.dll` that sits next to
`Ravenswatch.exe`.

- **Windows, with the app:** the app installs and updates the loader each time it
  starts. Run **Commands → Doctor** to check it's there.
- **With the modding tools:** run `rsmm install-loader`. Note that
  `rsmm restore --all` removes the loader, so install it again afterwards.
- **Linux and Steam Deck:** Steam needs a launch option to load it. See
  [Script mods on Linux and Steam Deck](/getting-started/install/#script-mods-on-linux-and-steam-deck).

Then check the **Log** page for errors from the mod.

### Reading the log

The **Log** page shows what script mods wrote while the game was running.

- **problems only** shows just the lines where something failed (`err`) or looked
  wrong (`warn`). A line without a tag isn't necessarily fine; it just wasn't
  sorted.
- **Earlier sessions:** the drop-down lists the last 20 game sessions, so a crash
  from a few launches ago is still there.

With the modding tools: `rsmm log` shows the latest log, `rsmm log -f` follows it
live, `rsmm log --errors` shows only problems, and `rsmm log --list` lists earlier
sessions.

### Share your log

Logs are long. Pasting one into Discord or a GitHub issue cuts it off and scrambles
it. Share a link instead:

1. Open **Log**.
2. Press **Share link**.
3. Write what went wrong, check the preview, and press **Upload and get link**.
4. Paste the link where you're asking for help.

The upload always starts with a short header naming your app version and
operating system, because those are the first things anyone helping you will
ask. Three switches in that window are on by default:

- **include mod list** adds which mods are installed and switched on.
- **include app log** adds the app's own log, which matters when the app itself
  misbehaves rather than the game.
- **hide personal details** replaces your Windows user name, home folder, email
  addresses, IP addresses, Steam IDs and player names with placeholders.

**Read the preview before uploading.** Hiding personal details works by searching
the text for patterns, so it's a good safety net, not a guarantee. Anyone with
the link can read the page, so treat it as public. It's deleted automatically
after 30 days.

## Modding tools

### `'python' is not recognized`, or typing `python` opens the Microsoft Store

Python isn't installed, or Windows can't find it. Reinstall Python from
[python.org](https://www.python.org/downloads/) and **tick "Add python.exe to
PATH"** on the first screen. Then close the terminal and open a new one.

If the Microsoft Store still opens, go to **Windows Settings → Apps → Advanced app
settings → App execution aliases** and switch off the two **python** entries.

### `'rsmm' is not recognized` or `rsmm: command not found`

The terminal isn't in the right folder, or the environment isn't switched on. Do
the [every-time steps](/getting-started/modding-tools/#every-time-you-come-back)
again. The line should start with `(.venv)`.

### `running scripts is disabled on this system` (PowerShell)

Use **Command Prompt** instead, or run this once in PowerShell:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### `error: externally-managed-environment` (Linux)

You ran `pip install` without switching the environment on. Run
`source .venv/bin/activate` in the `RavenswatchModManager` folder, then try again.

### `ensurepip is not available` or `No module named venv` (Linux)

Install Python's environment support, then create the environment again:

```sh
sudo apt install python3-venv
python3 -m venv .venv
```

### `rsmm` can't find the game

Tell it where the game is with the `RSMM_GAME_DIR` setting, as shown in
[Set up the modding tools](/getting-started/modding-tools/#5-check-that-it-works).
For a single command you can also add `--game-dir "path\to\Ravenswatch"`, for
example `rsmm doctor --game-dir "D:\Games\Ravenswatch"`.

### `rsmm lint` shows `[FAIL]`

Read the line: it says what's wrong and often suggests the right spelling
(`did you mean 'value'?`). `[WARN]` lines are only suggestions and don't stop
your mod from working.

### `rsmm apply` can't resolve a path

The file path in your mod doesn't match a file the game has. Check the spelling
and use forward slashes (`/`). `rsmm assets search <word>` finds the right path,
for example `rsmm assets search Juliet`.

### Two of my own mods overwrite each other

When two mods replace the same file, the later one wins. `rsmm diff MyMod` lists
the game files a mod changes and which other mods touch them too. Mods that use
`[[patch]]` blocks can change different values in the same file without clashing;
see [Two override strategies](/guides/modding/#two-override-strategies).

## Still stuck?

Open an issue on [GitHub](https://github.com/Ovilli/RavenswatchModManager/issues)
and include:

- your operating system,
- your RSMM version (**Settings → About**),
- your Ravenswatch version,
- what you did and what happened,
- a [shared log link](#share-your-log), which is far more useful than a pasted
  excerpt,
- any error messages or screenshots.
