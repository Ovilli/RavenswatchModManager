---
title: Troubleshooting
description: Common issues and how to fix them.
---

## Desktop app won't open

**Windows**: Make sure you have [WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) installed (it ships with Windows 11 and most Windows 10 installations).

**macOS**: Right-click the app → Open, then click Open in the dialog. This is needed for unsigned apps on macOS.

**Linux**: Make sure your system has WebKit2GTK:
```sh
# Debian/Ubuntu
sudo apt install libwebkit2gtk-4.1-dev

# Fedora
sudo dnf install webkit2gtk4.1

# Arch
sudo pacman -S webkit2gtk-4.1
```

## "Game not found"

The app couldn't auto-detect your Ravenswatch installation.

- **Steam (Windows)**: Try launching Ravenswatch through Steam once, then restart RSMM
- **Steam (macOS/Linux)**: Make sure the game is installed in your Steam library
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

## Still stuck?

Open an issue on [GitHub](https://github.com/Ovilli/RavenswatchModManager/issues) with:

- Your operating system
- RSMM version (shown in About)
- Ravenswatch version
- Steps to reproduce the problem
- Any error messages or screenshots
