---
title: Troubleshooting
description: Common issues and how to fix them.
---

## Desktop app won't open

**Windows**: Make sure you have [WebView2](https://learn.microsoft.com/en-us/microsoft-edge/webview2/) installed (it ships with Windows 11 and most Windows 10 installations).

**Linux**: Make sure your system has WebKit2GTK:
```sh
# Debian/Ubuntu
sudo apt install libwebkit2gtk-4.1-dev

# Fedora
sudo dnf install webkit2gtk4.1

# Arch
sudo pacman -S webkit2gtk-4.1
```

If the app opens to a gray screen on Debian/Ubuntu, try launching it with the
software/compositing fallback enabled:

```sh
WEBKIT_DISABLE_DMABUF_RENDERER=1 WEBKIT_DISABLE_COMPOSITING_MODE=1 rsmm
```

If that fixes it, the issue is usually a WebKitGTK or GPU compositing quirk on
the local machine.

## "Game not found"

The app couldn't auto-detect your Ravenswatch installation.

- **Steam (Windows)**: Try launching Ravenswatch through Steam once, then restart RSMM
- **Steam (Linux)**: Make sure the game is installed in your Steam library
- **Custom install**: Browse to the folder containing `Ravenswatch.exe` manually

## "Permission denied" on Linux

If RSMM can't write to the game directory, you may need to adjust permissions:

```sh
# If the game is in a Steam library on a different drive
sudo chown -R $USER /path/to/Ravenswatch
```

## "Python not found" error

The desktop app bundles Python internally. If you see this error, the bundle may be corrupted — try reinstalling RSMM.

## Mods not applying

Run the **Doctor** from the app toolbar. It will check:

1. The game directory exists
2. The asset map is generated
3. All mod files are valid
4. No file conflicts between mods

If the doctor reports errors, follow its suggestions.

## Rollback

If a mod causes issues in-game:

1. Open the **Installed** tab
2. Disable or uninstall the problematic mod
3. Click **Apply** to restore the original game files
4. Launch the game — it's back to vanilla

## "Loader DLL not loading" (Lua mods, Windows only)

1. Verify `winhttp.dll` exists next to `Ravenswatch.exe`
2. Check the loader log from the app's Debug menu
3. Ensure your Steam launch options include the DLL override

## PC freezes or blue-screens while RSMM is open (Windows)

RSMM draws through your GPU like any browser window, and browsing mods loads
images and video players. That is ordinary work — but it is enough to expose a
broken display driver, and a driver fault takes the whole machine down, not
just the app.

Check what actually crashed, in PowerShell:

```powershell
Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,1001,6008} -MaxEvents 5 | Format-List
```

A bug check such as `VIDEO_SCHEDULER_INTERNAL_ERROR` (`0x119`),
`VIDEO_TDR_FAILURE` (`0x116`) or `DPC_WATCHDOG_VIOLATION` is a **display
driver** fault. No user-space program can raise one directly.

What to do, in order:

1. Clean-install your GPU driver (or roll it back, if the crashes started after
   an update). Open `C:\Windows\Minidump\*.dmp` in WinDbg and run
   `!analyze -v` — `IMAGE_NAME` names the driver.
2. Disable GPU-hooking overlays (Discord, GeForce Experience, MSI Afterburner)
   while you test.
3. In RSMM: **Settings → Graphics → Disable GPU acceleration**. RSMM then
   renders in software and stops touching the GPU at all. Restart the app for
   it to take effect. This is a workaround, not a fix — the driver is still
   broken for everything else on the machine.

Mod gallery videos are click-to-play precisely so that opening a mod page does
not start a video pipeline you did not ask for.

## CLI diagnostics

If you use the command line, these help pin down problems:

```sh
./rsmm doctor        # full health check — run this first
./rsmm log           # tail the loader log (Lua mods)
```

For merge conflicts or asset collisions, inspect `mods/_merged/asset_map.json`
and `asset_map.csv` for duplicate entries, then resolve by renaming or adjusting
the offending manifests.

## Reading the log

The desktop app's **Log** screen shows what the script loader wrote inside the
game. Three things worth knowing:

- **Problems only.** The loader tags the lines where something actually failed
  (`err`) or went sideways (`warn`); tick *problems only* to see just those. A
  capability that is switched off because you did not arm it is not an error
  and is deliberately not tagged — so an unflagged line means "not classified",
  not "fine".
- **Older runs.** The dropdown lists the last 20 finished runs, archived under
  `<game>/rsmm/logs`. A crash three launches ago is still there; you no longer
  need the CLI to read it.
- **Startup crashes.** If a mod kills the game during startup, the loader
  cannot be told to stop loading it from inside the game — so it skips the mod
  after three failed launches in a row. When that happens the Log screen says
  which mod, why, and offers *Try again* once you think it is fixed.

From the command line the same filters are `rsmm log --errors`,
`rsmm log --list` and `rsmm log --run <name>`.

## Share your log instead of pasting it

A loader log runs to thousands of lines, and pasting it into Discord or a
GitHub issue truncates it, mangles the alignment, and drops the session banners
that say which run it came from. The desktop app can upload it instead:

1. Open **Log**.
2. Press **Share link**.
3. Say what went wrong, check the preview, press **Upload and get link**.
4. Paste the link into your issue or support thread.

The upload includes a short header — app version, OS, and which mods were
installed and enabled — because those are the first three questions anyone
helping you will ask. Tick *include app log* to add the desktop app's own log
as well, which is what you want when the app itself misbehaves rather than the
game.

**Read the preview.** The dialog shows the exact text that will be uploaded.
Your Windows account name, home folder, e-mail addresses, IP addresses, Steam
IDs and player names are replaced with placeholders before upload, but that is
pattern matching on a log we do not control — a strong default, not a promise.
The page is unlisted rather than private: anyone with the link can read it, so
treat it as public. It is deleted automatically 30 days after upload.

## Still stuck?

Open an issue on [GitHub](https://github.com/Ovilli/RavenswatchModManager/issues) with:

- Your operating system
- RSMM version (shown in About)
- Ravenswatch version
- Steps to reproduce the problem
- A shared log link (see above) — far more useful than a pasted excerpt
- Any error messages or screenshots
