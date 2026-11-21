"""
rsmm run — launch Ravenswatch via Steam with the loader override in place,
so Proton picks up the loader DLL.

Default behavior:
  1. On Windows, hand off to the steam://rungameid URL; nothing else is needed.
  2. On Proton, write "winhttp"="native,builtin" into the game prefix's
     user.reg and launch. Skipped when the prefix doesn't exist yet or a
     wine process holds it.
  3. Otherwise inspect Steam's localconfig.vdf for the app's LaunchOptions.
     If they contain "winhttp=n,b" or "winhttp=native,builtin", launch;
     if not, REFUSE and print the exact text to paste into the Steam
     properties dialog. --set-launch-options writes it for you (Steam
     must be closed; the file is backed up first).

Why not just exec Proton directly: the Flatpak Steam ships Proton
inside its own runtime; running Proton from outside the sandbox skips
the pressure-vessel setup and frequently fails on shared libraries.
We hand off to Steam itself so it can resolve the game launch inside
its own environment.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from rsmm.cli.apply_mods import find_game_dir
from rsmm.engine.paths import BACKUP_SUFFIX, DIST_DIR, REPO_ROOT, self_cmd

RAVENSWATCH_APP_ID = "2071280"
REQUIRED_OVERRIDE = "winhttp=n,b"            # what we want to see
ACCEPTED_OVERRIDES = (
    "winhttp=n,b",
    "winhttp=native,builtin",
)
RECOMMENDED_LAUNCH_OPTIONS = 'WINEDLLOVERRIDES="winhttp=n,b" %command%'

# localconfig.vdf is UTF-8 and full of other people's text (friend nicknames,
# other games' launch options). The locale default (cp1252 on most Windows)
# turned every byte it doesn't define — 0x81, 0x8D, 0x8F, 0x90, 0x9D, all
# common UTF-8 continuation bytes — into "?" on the write-back, corrupting
# every non-ASCII string in the file. surrogateescape round-trips the exact
# bytes, even where the file is not valid UTF-8. Bytes, not read_text/
# write_text: text mode also rewrites every "\n" to "\r\n" on Windows.
def _vdf_read(path: Path) -> str:
    return path.read_bytes().decode("utf-8", "surrogateescape")


def _vdf_write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8", "surrogateescape"))


# --------------------------------------------------------------------------- #
# Proton prefix DLL override (#148)
#
# Wine reads DLL overrides from the prefix registry as well as from the
# WINEDLLOVERRIDES env var (Proton's env list doesn't name winhttp, so the
# registry entry is what applies). Unlike localconfig.vdf, Steam doesn't own
# the prefix's user.reg, so this works while Steam is running — the Steam Deck
# case, where Steam never closes and launch options can't be written.

PREFIX_OVERRIDE_LINE = '"winhttp"="native,builtin"'
_DLLOVERRIDES_HDR = re.compile(r"^\[Software\\\\Wine\\\\DllOverrides\][^\n]*\n", re.M)
_WINHTTP_NATIVE = re.compile(r'^"winhttp"="n(ative)?(,\s*b(uiltin)?)?"\s*$', re.M | re.I)


def prefix_user_reg(game_dir: Path, app_id: str = RAVENSWATCH_APP_ID) -> Path:
    """<lib>/steamapps/common/<game> → <lib>/steamapps/compatdata/<id>/pfx/user.reg"""
    return game_dir.parents[1] / "compatdata" / app_id / "pfx" / "user.reg"


def _dlloverrides_section(text: str) -> tuple[int, int] | None:
    """(start, end) of the DllOverrides section body, or None."""
    m = _DLLOVERRIDES_HDR.search(text)
    if m is None:
        return None
    end = text.find("\n[", m.end())
    return m.end(), (len(text) if end == -1 else end + 1)


def prefix_override_present(reg: Path) -> bool:
    try:
        text = _vdf_read(reg)
    except OSError:
        return False
    span = _dlloverrides_section(text)
    return span is not None and _WINHTTP_NATIVE.search(text, *span) is not None


def _prefix_in_use(pfx: Path) -> bool:
    """A live wineserver for this prefix rewrites user.reg from memory on exit,
    which would drop our line — so don't write while one runs."""
    want = str(pfx).rstrip("/")
    for environ in Path("/proc").glob("[0-9]*/environ"):
        try:
            data = environ.read_bytes()
        except OSError:
            continue
        for var in data.split(b"\0"):
            if var.startswith(b"WINEPREFIX=") and \
                    var[11:].decode(errors="replace").rstrip("/") == want:
                return True
    return False


def ensure_prefix_override(game_dir: Path) -> bool:
    """Make the game's Proton prefix load winhttp.dll native-first.

    True when the override is (now) in place. False when there is no prefix
    yet (game never run under Proton), the prefix is in use, or the write
    failed — the caller falls back to Steam launch options.
    """
    reg = prefix_user_reg(game_dir)
    if prefix_override_present(reg):
        return True
    if not reg.is_file() or _prefix_in_use(reg.parent):
        return False
    try:
        text = _vdf_read(reg)
        span = _dlloverrides_section(text)
        if span is None:
            text = (text.rstrip("\n") + "\n\n"
                    f"[Software\\\\Wine\\\\DllOverrides] {int(time.time())}\n"
                    f"{PREFIX_OVERRIDE_LINE}\n")
        else:
            # Values go after the header's "#time="/"#class=" comment lines;
            # drop any non-native winhttp entry the user had.
            start, end = span
            lines = text[start:end].splitlines(keepends=True)
            lines = [ln for ln in lines if not ln.lower().startswith('"winhttp"=')]
            at = next((i for i, ln in enumerate(lines) if not ln.startswith("#")), len(lines))
            lines.insert(at, PREFIX_OVERRIDE_LINE + "\n")
            text = text[:start] + "".join(lines) + text[end:]
        bak = reg.with_name(reg.name + BACKUP_SUFFIX)
        if not bak.exists():
            shutil.copy2(reg, bak)
        tmp = reg.with_name(reg.name + ".rsmm.tmp")
        _vdf_write(tmp, text)
        os.replace(tmp, reg)
    except OSError as e:
        print(f"could not write the Proton prefix override: {e}", file=sys.stderr)
        return False
    return prefix_override_present(reg)


def _steam_root() -> Path | None:
    """Locate Steam install dir across Linux (Flatpak/native) and Windows."""
    home = Path.home()
    cands: list[Path] = []
    if sys.platform == "win32":
        from rsmm.engine.paths import _registry_steam_roots
        cands += _registry_steam_roots()
        pf86 = os.environ.get("ProgramFiles(x86)")
        pf = os.environ.get("ProgramFiles")
        if pf86:
            cands.append(Path(pf86) / "Steam")
        if pf:
            cands.append(Path(pf) / "Steam")
        for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{d}:\\")
            # Some drive letters refer to unreadable media (empty card
            # readers, dismounted volumes). `Path.exists()` re-raises any
            # OSError other than ENOENT — e.g. WinError 1005 "The volume
            # does not contain a recognized file system" — so we must
            # swallow them explicitly or the whole rsmm command aborts.
            try:
                if not root.exists():
                    continue
            except OSError:
                continue
            cands += [
                Path(f"{d}:\\Program Files (x86)\\Steam"),
                Path(f"{d}:\\Program Files\\Steam"),
                Path(f"{d}:\\Steam"),
            ]
    else:
        cands += [
            home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
            home / ".steam/steam",
            home / ".local/share/Steam",
        ]
    for c in cands:
        try:
            if (c / "steamapps").is_dir():
                return c
        except OSError:
            continue
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
        text = _vdf_read(vdf_path)
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


#: `NAME=value` before %command%: a double-quoted value (escapes allowed), a
#: single-quoted one, or a bare word.
_ENV_TOKEN = re.compile(
    r"""(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<val>"(?:[^"\\]|\\.)*"|'[^']*'|\S*)""")


def strip_rsmm_launch_options(value: str) -> str:
    """`value` with only what the mod manager put there taken out.

    Removed: the `winhttp` entry of WINEDLLOVERRIDES (other DLL overrides in
    the same variable are kept) and any `RSMM_*` loader-flag variable. Kept:
    everything else — the player's own variables (a PRIME-offload set that is
    the only thing letting DX12 start on a hybrid laptop, `gamemoderun`, ...)
    and the game arguments after %command%. A value left holding nothing but
    `%command%` becomes "" (Steam's own default), as before.

    `restore --all` used to write "" unconditionally, which wiped those player
    settings along with ours; on 2026-10-11 that took a working launch back
    to "DX12 Error 0x80004005".
    """
    head, sep, tail = value.partition("%command%")
    if not sep:
        head, tail = value, ""
    kept: list[str] = []
    pos = 0
    for m in _ENV_TOKEN.finditer(head):
        kept.append(head[pos:m.start()])
        pos = m.end()
        name, val = m.group("name"), m.group("val")
        if name.startswith("RSMM_"):
            continue
        if name == "WINEDLLOVERRIDES":
            inner = val[1:-1] if val[:1] in "\"'" and len(val) >= 2 else val
            rest = [e for e in inner.split(";")
                    if e.strip() and not e.strip().lower().startswith("winhttp=")]
            if not rest:
                continue
            kept.append(f'WINEDLLOVERRIDES="{";".join(rest)}"')
            continue
        kept.append(m.group(0))
    kept.append(head[pos:])
    out = " ".join("".join(kept).split())
    if sep:
        out = f"{out} %command%{tail}".strip()
    return "" if out == "%command%" else out


def add_rsmm_launch_options(value: str) -> str:
    """`value` with the loader override added, everything else kept.

    The override goes into an existing WINEDLLOVERRIDES when there is one,
    else at the very front (before any wrapper such as gamemoderun). Options
    with no %command% are game ARGUMENTS to Steam, so they move after it.

    This used to REPLACE anything without the override with the bare
    recommended string; on 2026-10-11 that dropped a player's PRIME-offload
    variables and the game failed DX12 init again.
    """
    value = (value or "").strip()
    if not value:
        return RECOMMENDED_LAUNCH_OPTIONS
    if _override_present(value):
        return value
    head, sep, tail = value.partition("%command%")
    if not sep:
        return f"{RECOMMENDED_LAUNCH_OPTIONS} {value}"
    for m in _ENV_TOKEN.finditer(head):
        if m.group("name") == "WINEDLLOVERRIDES":
            val = m.group("val")
            inner = val[1:-1] if val[:1] in "\"'" and len(val) >= 2 else val
            merged = f'WINEDLLOVERRIDES="{inner};{REQUIRED_OVERRIDE}"'
            return (head[:m.start()] + merged + head[m.end():] + sep + tail).strip()
    # At the FRONT: an assignment only sets the environment before the first
    # word, so `gamemoderun VAR=x %command%` would try to run "VAR=x".
    prefix = " ".join(f'WINEDLLOVERRIDES="{REQUIRED_OVERRIDE}" {head.strip()}'.split())
    return f"{prefix} %command%{tail}".strip()


def _is_steam_running() -> bool:
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
                # OEM-codepage banner; see engine/game_proc.py::_run.
                capture_output=True, text=True, errors="replace",
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


def _vdf_escape(value: str) -> str:
    """Escape a value for inclusion in a VDF string (\\ → \\\\, " → \\")."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _write_launch_options(vdf_path: Path, app_id: str, new_value: str) -> bool:
    """Insert / replace LaunchOptions inside the app block. Backs up
    the original to <path>.rsmm.bak before writing. Returns True on
    success. NEVER call this with Steam running — Steam rewrites the
    file on exit and would clobber our edit.
    """
    text = _vdf_read(vdf_path)
    found = _find_app_block(text, app_id)
    if not found:
        print(f"  no '{app_id}' app block found in {vdf_path}",
              file=sys.stderr)
        return False
    open_brace, body_start, body_end = found
    body = text[body_start:body_end]
    escaped = _vdf_escape(new_value)
    # Must be the SAME escape-aware pattern the reader uses. A plain
    # `"[^"]*"` stops at the first *escaped* quote, so replacing an existing
    # `WINEDLLOVERRIDES=\"winhttp=n,b\" …` value matched only up to `\"` and
    # left the rest of the old value stranded after the new one — the file
    # kept parsing, but the app's launch options were silently mangled.
    existing = re.compile(r'"LaunchOptions"\s*"(?:[^"\\]|\\.)*"')
    if existing.search(body):
        new_body = existing.sub(
            lambda _m: f'"LaunchOptions"\t\t"{escaped}"',
            body,
            count=1,
        )
    else:
        indent_match = re.search(r'\n(\s+)"', body)
        indent = indent_match.group(1) if indent_match else "\t\t\t\t\t\t"
        new_body = f'\n{indent}"LaunchOptions"\t\t"{escaped}"' + body
    new_text = (text[:open_brace] + '{' + new_body + '}' + text[body_end + 1:])

    bak = vdf_path.with_suffix(vdf_path.suffix + BACKUP_SUFFIX)
    if not bak.exists():
        _vdf_write(bak, text)
    # Atomic write: a Steam crash mid-write was previously enough to
    # leave localconfig.vdf truncated, which Steam then refused to load.
    tmp = vdf_path.with_suffix(vdf_path.suffix + ".rsmm.tmp")
    _vdf_write(tmp, new_text)
    tmp.replace(vdf_path)
    return True


def _rsmm_subcommand(args: list[str], /) -> bool:
    """Run `rsmm <args...>` and return True on success. Output is
    passed through to the terminal."""
    cmd = self_cmd(args)
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
        return proc.returncode == 0
    except FileNotFoundError as e:
        print(f"Could not run rsmm: {e}", file=sys.stderr)
        return False


#: How long a launcher gets to fail before it counts as started. `flatpak run`
#: and `steam` hand off to a running Steam and exit 0 within a second; when
#: Steam was not running they BECOME Steam and keep running, which is success.
#: A broken environment fails in milliseconds (exit 127, symbol lookup error).
_LAUNCHER_GRACE_S = 4.0


def _spawn_launcher(argv: list[str]) -> str | None:
    """Start one launcher. None when it started; otherwise why it did not.

    Started in its own session with the host environment: it may become Steam
    itself, which must outlive this process and the desktop app that spawned
    it, and must not load the AppImage's libraries (see rsmm.engine.host_env).
    """
    import tempfile

    from rsmm.engine.host_env import host_env

    with tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=err,
                                    env=host_env(), start_new_session=True)
        except OSError as e:
            return str(e)
        try:
            code = proc.wait(timeout=_LAUNCHER_GRACE_S)
        except subprocess.TimeoutExpired:
            return None  # still running: it is Steam now
        if code == 0:
            return None
        err.seek(0)
        detail = err.read().decode("utf-8", errors="replace").strip().splitlines()
        return f"exit {code}" + (f": {detail[-1]}" if detail else "")


def _linux_launchers(app_id: str, url: str) -> list[list[str]]:
    """Ways to reach Steam, most direct first."""
    out = []
    if shutil.which("steam"):
        out.append(["steam", "-applaunch", app_id])
    if shutil.which("flatpak"):
        out.append(["flatpak", "run", "com.valvesoftware.Steam", "-applaunch", app_id])
    if Path("/.flatpak-info").exists() and shutil.which("flatpak-spawn"):
        # rsmm itself sandboxed: only the host can start the Steam flatpak.
        out.append(["flatpak-spawn", "--host", "flatpak", "run",
                    "com.valvesoftware.Steam", "-applaunch", app_id])
    if shutil.which("xdg-open"):
        out.append(["xdg-open", url])
    return out


def _open_steam_url(url: str) -> int:
    if sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined]
        return 0
    app_id = url.rsplit("/", 1)[-1]
    failures = []
    for argv in _linux_launchers(app_id, url):
        print(f"==> {' '.join(argv)}", flush=True)
        why = _spawn_launcher(argv)
        if why is None:
            return 0
        failures.append(f"{argv[0]}: {why}")
        print(f"    failed ({why}), trying the next way", file=sys.stderr)
    if failures:
        print("Could not start Steam:\n  " + "\n  ".join(failures), file=sys.stderr)
    print(f"Open this URL manually: {url}", file=sys.stderr)
    return 1


def _outside_appimage(cmd: list[str]) -> list[str]:
    """`cmd` re-pointed at a copy of this binary outside the AppImage mount.

    The AppImage's squashfs is mounted only while the app runs. A watcher
    started from `/tmp/.mount_*/usr/bin/rsmm` survives the app closing (it
    unpacked itself to its own temp dir), but its restore re-invokes
    `sys.executable` — the mount path — and every attempt failed with "No such
    file or directory" (measured 2026-11-21 on the v6.0.1 AppImage). So a
    player who closed the app while playing kept a modded install, and the
    next Steam launch ran modded. The copy is a self-contained onefile binary;
    it is rewritten only when its bytes differ.
    """
    if not getattr(sys, "frozen", False):
        return cmd
    exe = Path(sys.executable)
    appdir = (os.environ.get("APPDIR") or "").rstrip("/")
    in_mount = (bool(appdir) and str(exe).startswith(appdir + "/")) \
        or str(exe).startswith("/tmp/.mount_")
    if not in_mount:
        return cmd
    from rsmm.engine.hashing import sha256_file
    from rsmm.engine.paths import user_data_dir

    dst = user_data_dir() / "watcher" / exe.name
    try:
        current = dst.is_file() and dst.stat().st_size == exe.stat().st_size \
            and sha256_file(dst) == sha256_file(exe)
        if not current:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f"{dst.name}.{os.getpid()}.tmp")
            shutil.copyfile(exe, tmp)
            tmp.chmod(0o755)
            os.replace(tmp, dst)  # an older watcher running the old copy keeps its inode
    except OSError as e:
        print(f"note: could not copy rsmm out of the AppImage for the restore "
              f"watcher ({e}); run `rsmm restore` if mods stay applied.",
              file=sys.stderr)
        return cmd
    return [str(dst), *cmd[1:]]


def _spawn_restore_watcher() -> None:
    """Start `rsmm watch-restore` detached, so it outlives this process and the
    desktop app and puts the install back to vanilla once the game exits.

    A spawn failure only warns: the launch itself already succeeded.
    """
    from rsmm.engine.host_env import host_env

    cmd = _outside_appimage(self_cmd(["watch-restore"]))
    # A frozen onefile child started with the inherited environment reuses
    # THIS process's unpacked _MEI dir, which is deleted the moment we exit —
    # so the watcher died before its first line and the install stayed modded
    # (a later Steam launch was still modded). Reset makes it unpack its own.
    env = dict(host_env() or os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL, "cwd": REPO_ROOT, "env": env}
    try:
        if sys.platform == "win32":
            flags = (subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
                     | subprocess.CREATE_NEW_PROCESS_GROUP)  # type: ignore[attr-defined]
            try:
                # Leave the launcher's job object (the desktop app's), or the
                # watcher dies with it. 0x01000000 = CREATE_BREAKAWAY_FROM_JOB.
                subprocess.Popen(cmd, creationflags=flags | 0x01000000, **kw)
            except OSError:
                # A job that forbids breakaway rejects the flag.
                subprocess.Popen(cmd, creationflags=flags, **kw)
        else:
            subprocess.Popen(cmd, start_new_session=True, **kw)
    except OSError as e:
        print(f"Could not start the restore watcher: {e}. Run `rsmm restore` "
              "after the game closes.", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch Ravenswatch via Steam")
    ap.add_argument("--vanilla", action="store_true",
                    help="restore original files and launch without mods")
    ap.add_argument("--app-id", default=RAVENSWATCH_APP_ID,
                    help="Steam app id (default: Ravenswatch)")
    ap.add_argument("--set-launch-options", action="store_true",
                    help="write WINEDLLOVERRIDES into Steam's localconfig.vdf "
                         "(requires Steam to be closed; original backed up "
                         "as localconfig.vdf.rsmm.bak)")
    ap.add_argument("--clear-launch-options", action="store_true",
                    help="clear Steam LaunchOptions for Ravenswatch before launching")
    ap.add_argument("--no-launch", action="store_true",
                    help="with --set-launch-options, write the options and stop "
                         "(don't start the game)")
    ap.add_argument("--force", action="store_true",
                    help="launch even if launch options are missing the override")
    ap.add_argument("--no-watch", action="store_true",
                    help="don't start the background watcher that restores the "
                         "original files when the game exits")
    args = ap.parse_args()

    def launch(url: str) -> int:
        rc = _open_steam_url(url)
        if rc == 0 and not (args.vanilla or args.no_launch or args.no_watch):
            _spawn_restore_watcher()
        return rc

    if not (args.vanilla or args.no_launch):
        # Before apply: a watcher still holding the previous session must see
        # this launch before it decides to restore (see watch_restore).
        from rsmm.cli.watch_restore import bump_launch_generation
        bump_launch_generation()

    if args.vanilla:
        if not _rsmm_subcommand(["restore"]):
            print("Failed to restore original files; aborting launch.", file=sys.stderr)
            return 1
    elif not args.no_launch:
        # --no-launch is the repair-only path (doctor --fix, the desktop's
        # "set it for me"): applying mods there would leave the install
        # modded with no game running and nothing to restore it.
        game_dir = find_game_dir()
        if game_dir is not None:
            built_dll = DIST_DIR / "winhttp.dll"
            installed_dll = game_dir / "winhttp.dll"
            real_dll = game_dir / "winhttp_real.dll"
            loader_ok = (
                built_dll.exists()
                and installed_dll.exists()
                and installed_dll.stat().st_size == built_dll.stat().st_size
                and real_dll.exists()
            )
            if not loader_ok:
                print("Loader DLL not properly installed. Installing...", flush=True)
                from rsmm.cli.install_loader import main as install_loader
                rc = install_loader([str(game_dir)])
                if rc != 0:
                    print("Failed to install loader DLL; aborting launch.", file=sys.stderr)
                    return 1
                print("Loader installed.", flush=True)

        if not _rsmm_subcommand(["apply", "--for-launch"]):
            print("Failed to apply mods; aborting launch.", file=sys.stderr)
            # Apply writes UsedRscList.ot / the versiondef before its file
            # transaction, and its rollback only covers the cooked files: put
            # the install back, or a plain Steam launch runs half-modded.
            print("Restoring original files...", file=sys.stderr)
            _rsmm_subcommand(["restore"])
            return 1

    url = f"steam://rungameid/{args.app_id}"

    # Native Windows: the game loads winhttp.dll from its own directory
    # by default, so no WINEDLLOVERRIDES is needed. Just launch.
    if sys.platform == "win32":
        return launch(url)

    # Proton: put the override in the game's prefix registry. It needs no Steam
    # restart, so it works on a Steam Deck where Steam is always running. The
    # explicit launch-option flags keep their old meaning.
    if not (args.vanilla or args.set_launch_options or args.clear_launch_options):
        game_dir = find_game_dir()
        if game_dir is not None and ensure_prefix_override(game_dir):
            print("loader override set in the Proton prefix")
            return launch(url)

    steam_root = _steam_root()
    if steam_root is None:
        print("Steam install not found — launching URL anyway.", file=sys.stderr)
        return launch(url)

    vdfs = _localconfig_paths(steam_root)
    if not vdfs:
        print(f"No localconfig.vdf under {steam_root / 'userdata'}; "
              "launch options can't be verified.", file=sys.stderr)
        return launch(url)

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
                # Only OUR part comes out; the player's own options stay.
                current = _read_launch_options(vdf, args.app_id) or ""
                if _write_launch_options(vdf, args.app_id, strip_rsmm_launch_options(current)):
                    changed += 1
            except (OSError, ValueError) as e:
                print(f"Failed to clear launch options in {vdf}: {e}", file=sys.stderr)
        print(f"cleared launch options in {changed}/{len(vdfs)} Steam user config(s)")
        return launch(url)

    lo = _read_launch_options(primary, args.app_id)

    if lo is not None and _override_present(lo):
        print(f"launch options OK: {lo!r}")
        return launch(url)

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
        merged = add_rsmm_launch_options(lo or "")
        if _write_launch_options(primary, args.app_id, merged):
            print(f"wrote launch options into {primary}")
            print(f"backup: {primary}.rsmm.bak")
            if args.no_launch:
                # Repair-only mode. Launching here also starts Steam, which
                # takes ownership of localconfig.vdf and rewrites it on exit —
                # so a caller that only wanted to fix the options (doctor
                # --fix) would boot the game as a side effect.
                return 0
            return launch(url)
        return 1

    if args.force:
        # Best-effort: try to write the launch option so the loader
        # actually works on Linux/Wine. If Steam is running or the
        # write fails, warn but proceed.
        if lo is None or not _override_present(lo):
            merged = add_rsmm_launch_options(lo or "")
            try:
                if _write_launch_options(primary, args.app_id, merged):
                    print(f"wrote launch options into {primary}")
                else:
                    print("could not write launch options; loader may not load.",
                          file=sys.stderr)
            except (OSError, ValueError) as e:
                print(f"failed to write launch options: {e}; loader may not load.",
                      file=sys.stderr)
        return launch(url)

    print("Re-run with --set-launch-options to have rsmm write it for you "
          "(Steam must be closed).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
