"""Pointing the game at a self-hosted online backend (services/stormancer/).

The loader (`src/loader/src/hook_backend.cpp`) rewrites the host of the game's
Stormancer HTTP requests when it is given a backend URL, from either:

* the environment variable ``RSMM_BACKEND_URL`` (wins when both are set), or
* the first line of ``<game>/mods/.rsmm_backend``.

The environment variable is awkward for the people who need this most: on
Windows it means ``setx`` plus a full Steam restart, and Steam launch options
cannot set it at all. The file is read at every game start and needs neither,
so `rsmm backend` writes the file and checks everything that can silently stop
it working.

Every rule in :func:`normalize_url` mirrors the loader's ``parse_target``. A
URL the loader refuses is not an error there, it is *ignored* (one log line, no
redirect), so a wrong URL looks exactly like a broken loader. Rejecting it here
with a reason is the whole point.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from rsmm.engine.safeio import atomic_write_text

#: File the loader reads, relative to the game folder.
MARKER_REL = Path("mods") / ".rsmm_backend"

#: Environment variable the loader reads first.
ENV_VAR = "RSMM_BACKEND_URL"

#: Size of Proton's / Windows' own winhttp.dll that the loader proxies. A
#: winhttp.dll of exactly this size is the stock one, i.e. no loader installed.
STOCK_WINHTTP_SIZE = 713160

#: A loader that can redirect carries this string (the env var it reads). An
#: older loader has no such string, and for it the setting does nothing.
_REDIRECT_MARKER = b"RSMM_BACKEND_URL"

_HOST_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class BackendUrlError(ValueError):
    """The URL is one the loader would ignore. The message says why."""


def normalize_url(raw: str) -> str:
    """The canonical ``http://host[:port]`` the loader accepts, or raise.

    Lenient where the loader's meaning is unambiguous (a missing ``http://``, a
    trailing slash, upper case) and strict where it would silently do the wrong
    thing (``https``, a path, IPv6, credentials).
    """
    text = (raw or "").strip()
    if not text:
        raise BackendUrlError("the address is empty")

    if "://" not in text:
        # People paste "85.214.117.164:8090" straight from a chat message.
        text = "http://" + text

    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise BackendUrlError(f"not a valid address ({exc})") from exc

    if parts.scheme.lower() != "http":
        raise BackendUrlError(
            f"only plain http:// is supported, not {parts.scheme}://. The loader "
            "clears the TLS flag on redirected requests because the replacement "
            "backend has no certificate for passtechgames.com")
    if parts.username is not None or parts.password is not None:
        raise BackendUrlError("the address must not contain a user name or password")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise BackendUrlError(
            "give just the host and port, e.g. http://85.214.117.164:8090 "
            "(no path - the loader keeps the game's own paths)")

    host = parts.hostname or ""
    if ":" in host:
        raise BackendUrlError(
            "IPv6 addresses are not supported, use a host name or an IPv4 address")
    if not host or not _HOST_RE.match(host):
        raise BackendUrlError(f"{host or text!r} is not a usable host name or IPv4 address")
    if port is not None and not 1 <= port <= 65535:
        raise BackendUrlError(f"port {port} is out of range (1-65535)")

    return f"http://{host}" + (f":{port}" if port is not None else "")


def marker_path(game_dir: Path) -> Path:
    return Path(game_dir) / MARKER_REL


def read_marker(game_dir: Path) -> str | None:
    """The first line of the marker file, or None when it is absent or empty."""
    try:
        text = marker_path(game_dir).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    first = text.splitlines()[0].strip() if text.strip() else ""
    return first or None


def write_marker(game_dir: Path, url: str) -> Path:
    """Write the (already normalized) URL where the loader reads it.

    ASCII with no byte-order mark on purpose: the loader reads the first line
    byte for byte, and a BOM at the start would be part of the URL and make the
    ``http://`` prefix check fail.
    """
    path = marker_path(game_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, url + "\n", encoding="ascii")
    return path


def clear_marker(game_dir: Path) -> bool:
    """Remove the marker. True if there was one."""
    try:
        marker_path(game_dir).unlink()
        return True
    except FileNotFoundError:
        return False


@dataclass(frozen=True)
class LoaderState:
    """Whether the installed winhttp.dll can honour a backend URL at all."""

    can_redirect: bool
    summary: str


def inspect_loader(game_dir: Path) -> LoaderState:
    dll = Path(game_dir) / "winhttp.dll"
    try:
        size = dll.stat().st_size
    except OSError:
        return LoaderState(False, "no winhttp.dll in the game folder - run `rsmm install-loader`")
    if size == STOCK_WINHTTP_SIZE:
        return LoaderState(False, "only the stock winhttp.dll is there, the loader is not "
                                  "installed - run `rsmm update-loader`")
    try:
        data = dll.read_bytes()
    except OSError as exc:
        return LoaderState(False, f"cannot read winhttp.dll ({exc})")
    if _REDIRECT_MARKER not in data:
        return LoaderState(False, "the installed loader is too old to redirect "
                                  "(it predates loader v26) - run `rsmm update-loader`")
    return LoaderState(True, "installed and able to redirect")


@dataclass(frozen=True)
class Federation:
    reachable: bool
    endpoints: tuple[str, ...] = ()
    error: str = ""


def probe_federation(url: str, timeout: float = 5.0) -> Federation:
    """Ask the backend what the game would ask first: ``/_federation``."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/_federation", timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        endpoints = tuple(str(e) for e in (body.get("current") or {}).get("endpoints") or ())
        return Federation(True, endpoints)
    except urllib.error.HTTPError as exc:
        return Federation(False, error=f"the server answered HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return Federation(False, error=str(reason))
    except (ValueError, AttributeError):
        return Federation(False, error="the address answered, but not like a Stormancer backend")


def advertises_loopback(url: str, federation: Federation) -> bool:
    """True when we reached a remote host that tells players to use localhost.

    That is the server's ``publicIp`` / ``loadBalancedIp`` left at their
    default: the HTTP leg works, then the game dials localhost for the real
    connection and fails, which looks like a network problem on the player's end.
    """
    target = urlsplit(url).hostname or ""
    if target.lower() in _LOOPBACK:
        return False
    return any((urlsplit(e).hostname or "").lower() in _LOOPBACK for e in federation.endpoints)


def env_override() -> str | None:
    """The environment variable's value when it is set (it beats the file)."""
    value = os.environ.get(ENV_VAR, "").strip()
    return value or None


def remove_user_env_var() -> str | None:
    """Delete a ``setx RSMM_BACKEND_URL`` from the user's registry; return what it held.

    That variable is what testers were told to set before `rsmm backend`
    existed, and because it beats the file, a stale one silently pins the game
    to an old address. Removing it is part of setting the address, not a
    separate chore. Windows only (no-op elsewhere). Once removed it is also
    dropped from this process, so the report does not warn about it.

    Steam keeps the environment it started with, so a Steam that was running
    when `setx` was used still hands the old value to the game until it is
    restarted; the caller says so.
    """
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            old, _ = winreg.QueryValueEx(key, ENV_VAR)
            winreg.DeleteValue(key, ENV_VAR)
    except OSError:
        return None
    os.environ.pop(ENV_VAR, None)
    return str(old)


def other_installs(game_dir: Path) -> list[Path]:
    """Every *other* Ravenswatch install the autodetector can see.

    With two Steam libraries, rsmm can configure one copy while Steam launches
    the other - which is exactly "the setting does nothing and the log never
    updates".
    """
    from rsmm.engine.paths import COOKING_SUBDIR, _game_dir_candidates

    here = Path(game_dir).resolve()
    found = []
    for cand in _game_dir_candidates():
        try:
            if (cand / COOKING_SUBDIR).is_dir() and cand.resolve() != here:
                found.append(cand)
        except OSError:
            continue
    return found


@dataclass(frozen=True)
class LogInfo:
    path: Path
    exists: bool
    modified: float | None = None
    lines: tuple[str, ...] = ()


def last_backend_log(game_dir: Path, limit: int = 3) -> LogInfo:
    """The loader's own report of what the redirect did on the last launch.

    Read from the same file `rsmm log` reads, so a player who cannot tell
    whether the log is current can see its path and age here.
    """
    path = Path(game_dir) / "mods" / "_log.txt"
    try:
        stat = path.stat()
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return LogInfo(path, False)
    wanted = [
        line.strip() for line in text.splitlines()
        if "[backend]" in line and "web-ticket identity" not in line
    ]
    return LogInfo(path, True, stat.st_mtime, tuple(wanted[-limit:]))
