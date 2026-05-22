"""
rsmm run — launch Ravenswatch via Steam, ensuring the WINEDLLOVERRIDES
launch option is set so the loader DLL gets picked up.

Default behavior:
  1. Inspect Steam's localconfig.vdf for the app's LaunchOptions.
  2. If it already contains "winhttp=n,b" or "winhttp=native,builtin",
     hand off to the steam://rungameid URL — Steam respects the options.
  3. Otherwise REFUSE to launch and print the exact text to paste into
     the Steam properties dialog. The user can also pass --set-launch-
     options to have us write it ourselves (Steam must be closed; we
     back the file up first).

Why not just exec Proton directly: the Flatpak Steam ships Proton
inside its own runtime; running Proton from outside the sandbox skips
the pressure-vessel setup and frequently fails on shared libraries.
The Steam URL path is the most reliable invocation.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAVENSWATCH_APP_ID = "2071280"
REQUIRED_OVERRIDE = "winhttp=n,b"            # what we want to see
ACCEPTED_OVERRIDES = (
    "winhttp=n,b",
    "winhttp=native,builtin",
)
RECOMMENDED_LAUNCH_OPTIONS = 'WINEDLLOVERRIDES="winhttp=n,b" %command%'


def _steam_root() -> Path | None:
    """Locate Steam install dir across Linux (Flatpak/native), macOS,
    Windows."""
    home = Path.home()
    cands: list[Path] = []
    if sys.platform == "win32":
        pf86 = os.environ.get("ProgramFiles(x86)")
        pf = os.environ.get("ProgramFiles")
        if pf86:
            cands.append(Path(pf86) / "Steam")
        if pf:
            cands.append(Path(pf) / "Steam")
        for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{d}:\\")
            if not root.exists():
                continue
            cands += [
                Path(f"{d}:\\Program Files (x86)\\Steam"),
                Path(f"{d}:\\Program Files\\Steam"),
                Path(f"{d}:\\Steam"),
            ]
    elif sys.platform == "darwin":
        cands += [home / "Library/Application Support/Steam"]
    else:
        cands += [
            home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
            home / ".steam/steam",
            home / ".local/share/Steam",
        ]
    for c in cands:
        if (c / "steamapps").is_dir():
            return c
    return None


def _localconfig_paths(steam_root: Path) -> list[Path]:
    base = steam_root / "userdata"
    if not base.is_dir():
        return []
    return sorted(base.glob("*/config/localconfig.vdf"))


def _read_launch_options(vdf_path: Path, app_id: str) -> str | None:
    """Scan localconfig.vdf for the LaunchOptions of the given app.

    localconfig.vdf has MULTIPLE blocks keyed by the same app_id (under
    Software/Valve/Steam/apps, under Software/Valve/Steam/Apps, inside
    friend recent-played records, etc.). Most are stubs. We want the
    one under Software/Valve/Steam/apps which holds LaunchOptions —
    that's the only block that ever contains the key, so we search
    ALL same-id blocks and return the LaunchOptions from whichever
    block has it. Returns "" if every block is a stub without
    LaunchOptions, None if no block exists at all.
    """
    try:
        text = vdf_path.read_text(errors="replace")
    except OSError:
        return None
    # Use a balanced-brace scanner instead of a fixed regex: the app
    # block may itself contain nested objects (e.g. "cloud", "autocloud"),
    # so we can't trust a non-greedy "}" match.
    needle = f'"{app_id}"'
    found_any = False
    pos = 0
    while True:
        idx = text.find(needle, pos)
        if idx < 0:
            break
        pos = idx + len(needle)
        # The block may be a value (e.g. "HintAppsToPreload" = "2071280"
        # — no {). Skip past whitespace and look for '{'.
        j = pos
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        if j >= len(text) or text[j] != '{':
            continue
        # Scan balanced braces (ignoring strings).
        depth = 0
        k = j
        body_start = j + 1
        in_string = False
        escape = False
        while k < len(text):
            ch = text[k]
            if in_string:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        break
            k += 1
        if depth != 0:
            break
        body = text[body_start:k]
        found_any = True
        lo = re.search(r'"LaunchOptions"\s*"((?:[^"\\]|\\.)*)"', body)
        if lo:
            # Unescape the VDF string: it's stored with \\ and \" escapes.
            return lo.group(1).encode("latin-1").decode("unicode_escape", errors="replace")
        pos = k + 1
    return "" if found_any else None


def _override_present(launch_options: str) -> bool:
    lo = launch_options.lower()
    return any(o in lo for o in ACCEPTED_OVERRIDES)


def _is_steam_running() -> bool:
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
                capture_output=True, text=True,
            )
            return "steam.exe" in (r.stdout or "").lower()
        except FileNotFoundError:
            return False
    try:
        r = subprocess.run(["pgrep", "-x", "steam"], capture_output=True)
        if r.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    try:
        r = subprocess.run(["pgrep", "-f", "steamwebhelper"], capture_output=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _find_app_block(text: str, app_id: str) -> tuple[int, int, int] | None:
    """Scan for `app_id { ... }` using balanced-brace matching.
    Returns (open_brace_idx, body_start, body_end) or None."""
    needle = f'"{app_id}"'
    pos = 0
    while True:
        idx = text.find(needle, pos)
        if idx < 0:
            return None
        pos = idx + len(needle)
        j = pos
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        if j >= len(text) or text[j] != '{':
            continue
        depth = 0
        k = j
        body_start = j + 1
        in_string = False
        escape = False
        while k < len(text):
            ch = text[k]
            if in_string:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return (j, body_start, k)
            k += 1
        return None


def _write_launch_options(vdf_path: Path, app_id: str, new_value: str) -> bool:
    """Insert / replace LaunchOptions inside the app block. Backs up
    the original to <path>.rsmm.bak before writing. Returns True on
    success. NEVER call this with Steam running — Steam rewrites the
    file on exit and would clobber our edit.
    """
    text = vdf_path.read_text(errors="replace")
    found = _find_app_block(text, app_id)
    if not found:
        print(f"  no '{app_id}' app block found in {vdf_path}",
              file=sys.stderr)
        return False
    open_brace, body_start, body_end = found
    body = text[body_start:body_end]
    if re.search(r'"LaunchOptions"\s*"[^"]*"', body):
        new_body = re.sub(
            r'"LaunchOptions"\s*"[^"]*"',
            f'"LaunchOptions"\t\t"{new_value}"',
            body,
            count=1,
        )
    else:
        indent_match = re.search(r'\n(\s+)"', body)
        indent = indent_match.group(1) if indent_match else "\t\t\t\t\t\t"
        new_body = f'\n{indent}"LaunchOptions"\t\t"{new_value}"' + body
    new_text = (text[:open_brace] + '{' + new_body + '}' + text[body_end + 1:])

    bak = vdf_path.with_suffix(vdf_path.suffix + ".rsmm.bak")
    if not bak.exists():
        bak.write_text(text)
    vdf_path.write_text(new_text)
    return True


def _open_steam_url(url: str) -> int:
    if sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined]
        return 0
    if sys.platform == "darwin":
        if shutil.which("open"):
            try:
                subprocess.Popen(["open", url],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return 0
            except OSError as e:
                print(f"Could not launch via open: {e}", file=sys.stderr)
                return 1
        print("Could not find 'open' command on macOS. "
              f"Open this URL manually: {url}", file=sys.stderr)
        return 1
    # Linux
    if shutil.which("steam"):
        print(f"==> steam {url}")
        try:
            subprocess.Popen(["steam", url],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return 0
        except OSError as e:
            print(f"Could not launch via steam: {e}", file=sys.stderr)
            return 1
    if shutil.which("flatpak"):
        print(f"==> flatpak run com.valvesoftware.Steam {url}")
        try:
            subprocess.Popen(["flatpak", "run", "com.valvesoftware.Steam", url],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return 0
        except OSError as e:
            print(f"Could not launch via flatpak Steam: {e}", file=sys.stderr)
            return 1
    if shutil.which("xdg-open"):
        print(f"==> xdg-open {url}")
        try:
            subprocess.Popen(["xdg-open", url],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return 0
        except OSError as e:
            print(f"Could not launch via xdg-open: {e}", file=sys.stderr)
            return 1
    print(f"Could not find a Steam launcher. Open this URL manually: {url}",
          file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch Ravenswatch via Steam")
    ap.add_argument("--app-id", default=RAVENSWATCH_APP_ID,
                    help="Steam app id (default: Ravenswatch)")
    ap.add_argument("--set-launch-options", action="store_true",
                    help="write WINEDLLOVERRIDES into Steam's localconfig.vdf "
                         "(requires Steam to be closed; original backed up "
                         "as localconfig.vdf.rsmm.bak)")
    ap.add_argument("--clear-launch-options", action="store_true",
                    help="clear Steam LaunchOptions for Ravenswatch before launching")
    ap.add_argument("--force", action="store_true",
                    help="launch even if launch options are missing the override")
    args = ap.parse_args()

    url = f"steam://rungameid/{args.app_id}"

    # Native Windows: the game loads winhttp.dll from its own directory
    # by default, so no WINEDLLOVERRIDES is needed. Just launch.
    if sys.platform == "win32":
        return _open_steam_url(url)

    steam_root = _steam_root()
    if steam_root is None:
        print("Steam install not found — launching URL anyway.", file=sys.stderr)
        return _open_steam_url(url)

    vdfs = _localconfig_paths(steam_root)
    if not vdfs:
        print(f"No localconfig.vdf under {steam_root / 'userdata'}; "
              "launch options can't be verified.", file=sys.stderr)
        return _open_steam_url(url)

    # If multiple users share this Steam install, all of them need the
    # override or the active one does. We check the most recently
    # touched config first.
    vdfs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    primary = vdfs[0]

    if args.clear_launch_options:
        if _is_steam_running():
            print("Steam appears to be running; launch-options edits may be overwritten.",
                  file=sys.stderr)
        changed = 0
        for vdf in vdfs:
            try:
                if _write_launch_options(vdf, args.app_id, ""):
                    changed += 1
            except Exception as e:
                print(f"Failed to clear launch options in {vdf}: {e}", file=sys.stderr)
        print(f"cleared launch options in {changed}/{len(vdfs)} Steam user config(s)")
        return _open_steam_url(url)

    lo = _read_launch_options(primary, args.app_id)

    if lo is not None and _override_present(lo):
        print(f"launch options OK: {lo!r}")
        return _open_steam_url(url)

    print()
    print("=" * 64)
    print("Ravenswatch launch options are missing the loader override.")
    print("=" * 64)
    print(f"  config:           {primary}")
    print(f"  current options:  {lo!r}" if lo is not None
          else "  current options:  (no LaunchOptions set)")
    print(f"  required snippet: {REQUIRED_OVERRIDE}")
    print()
    print("Steam properties → Ravenswatch → General → Launch Options:")
    print(f"    {RECOMMENDED_LAUNCH_OPTIONS}")
    print()
    if args.set_launch_options:
        if _is_steam_running():
            print("Refusing to write while Steam is running — close Steam, "
                  "then re-run with --set-launch-options.", file=sys.stderr)
            return 1
        existing = lo or ""
        merged = (existing + " " + RECOMMENDED_LAUNCH_OPTIONS).strip() \
                 if existing and "%command%" not in existing else RECOMMENDED_LAUNCH_OPTIONS
        if _write_launch_options(primary, args.app_id, merged):
            print(f"wrote launch options into {primary}")
            print(f"backup: {primary}.rsmm.bak")
            return _open_steam_url(url)
        return 1

    if args.force:
        print("--force given; launching anyway. Loader DLL may not load.")
        return _open_steam_url(url)

    print("Re-run with --set-launch-options to have rsmm write it for you "
          "(Steam must be closed).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
