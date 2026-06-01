"""Canonical paths for the repo + the live Ravenswatch install.

Everything else imports REPO_ROOT / ASSET_MAP_JSON from here. Never
hardcode paths in CLI subcommands or SDK modules.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from functools import cache
from pathlib import Path


def _find_repo_root() -> Path:
    """Find the directory that contains `data/asset_map.json`.

    Resolution order:
    1) Explicit `RSMM_REPO_ROOT` override.
    2) Frozen-runtime locations (`_MEIPASS`, executable dir, cwd).
    3) Source-tree walk-up from this file.

    In frozen mode we avoid crashing at import time if `asset_map.json`
    is missing by returning the best available runtime root; subcommands
    that require the map perform their own existence checks and emit a
    user-facing error.
    """
    def _has_asset_map(root: Path) -> bool:
        return (root / "data" / "asset_map.json").exists()

    override = os.environ.get("RSMM_REPO_ROOT", "").strip()
    if override:
        try:
            root = Path(override).expanduser().resolve()
            if _has_asset_map(root):
                return root
        except OSError:
            pass

    frozen_candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            frozen_candidates.append(Path(meipass).resolve())
        frozen_candidates.append(Path(sys.executable).resolve().parent)
        frozen_candidates.append(Path.cwd())

    for cand in frozen_candidates:
        if _has_asset_map(cand):
            return cand

    here = Path(__file__).resolve()
    for cand in [here.parent, *here.parents]:
        if _has_asset_map(cand):
            return cand

    if frozen_candidates:
        # Last resort for frozen binaries: keep importable and let
        # command-level checks report missing data files.
        return frozen_candidates[0]

    # Source tree without `data/asset_map.json` (e.g. fresh clone before
    # first build, or a partial install). Don't crash at import; let
    # whatever subcommand actually needs the asset map report a clear
    # error when it opens the file.
    print(
        f"warning: rsmm repo root not found: data/asset_map.json missing "
        f"in any parent of {here}; falling back to {here.parents[2]}",
        file=sys.stderr,
    )
    return here.parents[2]


COOKING_SUBDIR: str = "DarkTalesResources/_Cooking"

_RAVENSWATCH_SUBPATH = Path("steamapps/common/Ravenswatch")
_VDF_PATH_RE = re.compile(r'"path"\s*"([^"]+)"', re.IGNORECASE)


def _parse_libraryfolders_vdf(vdf: Path) -> list[Path]:
    """Extract `path` entries from a Steam libraryfolders.vdf file.

    The VDF text format used by Steam has many shapes across versions
    (flat list, nested {"0": {...}, "1": {...}}, etc.). We only need the
    library root strings — a regex over the `"path"` keys handles every
    variant we've seen without pulling in a VDF dependency.
    """
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    roots: list[Path] = []
    for match in _VDF_PATH_RE.finditer(text):
        raw = match.group(1)
        # VDF escapes \\ \" \n \t — mirror run.py's unescape so any
        # library root with a literal newline / quote / tab in its
        # name resolves the same on both code paths.
        try:
            raw = raw.encode("latin-1").decode("unicode_escape", errors="replace")
        except (UnicodeDecodeError, UnicodeEncodeError):
            # Pure-ASCII fallback. Better to skip the unescape than
            # to lose a library root because a single byte tripped us.
            raw = raw.replace("\\\\", "\\")
        roots.append(Path(raw))
    return roots


def _steam_roots() -> list[Path]:
    """Locations where Steam's libraryfolders.vdf may live, per platform."""
    home = Path.home()
    if sys.platform == "win32":
        return [
            Path(r"C:\Program Files (x86)\Steam"),
            Path(r"C:\Program Files\Steam"),
        ]
    if sys.platform == "darwin":
        return [home / "Library/Application Support/Steam"]
    return [
        home / ".steam/steam",
        home / ".local/share/Steam",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ]


def _steam_library_candidates() -> list[Path]:
    """Resolve Ravenswatch install candidates from Steam's libraryfolders.vdf.

    Discovers custom library locations that the hardcoded list misses
    (e.g. `E:\\Games\\MySteamLib`).
    """
    cands: list[Path] = []
    for steam in _steam_roots():
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if not vdf.is_file():
            continue
        for lib in _parse_libraryfolders_vdf(vdf):
            cands.append(lib / _RAVENSWATCH_SUBPATH)
    return cands


def _game_dir_candidates() -> list[Path]:
    """Per-platform Ravenswatch install candidates. Order = preference.

    Steam-discovered roots come first; hardcoded fallbacks follow.
    """
    def _safe_exists(path: Path) -> bool:
        try:
            return path.exists()
        except OSError:
            return False

    home = Path.home()
    cands: list[Path] = list(_steam_library_candidates())
    if sys.platform == "win32":
        drives = [d for d in "CDEFGHIJKLMNOPQRSTUVWXYZ" if _safe_exists(Path(f"{d}:\\"))]
        for d in drives:
            drive_root = Path(f"{d}:\\")
            if not _safe_exists(drive_root):
                continue
            cands += [
                Path(f"{d}:\\Program Files (x86)\\Steam\\steamapps\\common\\Ravenswatch"),
                Path(f"{d}:\\Program Files\\Steam\\steamapps\\common\\Ravenswatch"),
                Path(f"{d}:\\Steam\\steamapps\\common\\Ravenswatch"),
                Path(f"{d}:\\SteamLibrary\\steamapps\\common\\Ravenswatch"),
                Path(f"{d}:\\Games\\Steam\\steamapps\\common\\Ravenswatch"),
            ]
        pf86 = os.environ.get("ProgramFiles(x86)")
        if pf86:
            cands.append(Path(pf86) / "Steam" / "steamapps" / "common" / "Ravenswatch")
        pf = os.environ.get("ProgramFiles")
        if pf:
            cands.append(Path(pf) / "Steam" / "steamapps" / "common" / "Ravenswatch")
    elif sys.platform == "darwin":
        cands += [
            home / "Library/Application Support/Steam/steamapps/common/Ravenswatch",
            home / "Library/Application Support/Steam/steamapps/common/Ravenswatch/Ravenswatch.app",
        ]
        volumes = Path("/Volumes")
        if volumes.is_dir():
            for vol in volumes.iterdir():
                if vol.is_dir():
                    cands.append(vol / "SteamLibrary" / "steamapps" / "common" / "Ravenswatch")
    else:
        cands += [
            home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
                   "/steamapps/common/Ravenswatch",
            home / ".steam/steam/steamapps/common/Ravenswatch",
            home / ".local/share/Steam/steamapps/common/Ravenswatch",
            Path("/mnt") / "Steam/steamapps/common/Ravenswatch",
        ]
    # De-dupe while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


@cache
def default_game_dir() -> Path:
    """First candidate whose `_Cooking` tree exists; otherwise the first
    candidate. Autodetects on Windows/macOS/Linux without `--game-dir`.

    Cached: the filesystem scan only runs on first access.
    """
    cands = _game_dir_candidates()
    for c in cands:
        try:
            if (c / COOKING_SUBDIR).is_dir():
                return c
        except OSError:
            continue
    if not cands:
        cands = [Path()]
    return cands[0]


def mods_dir() -> Path:
    """Resolve the mods directory. Honors the `RSMM_MODS_DIR` env override
    at call time so the desktop UI can repoint rsmm after launch.
    """
    override = os.environ.get("RSMM_MODS_DIR", "").strip()
    if override:
        path = Path(os.path.expandvars(override)).expanduser().resolve()
    else:
        path = REPO_ROOT / "mods"
    path.mkdir(parents=True, exist_ok=True)
    return path


REPO_ROOT: Path     = _find_repo_root()
DATA_DIR: Path      = REPO_ROOT / "data"
DIST_DIR: Path      = REPO_ROOT / "dist"
ASSET_MAP_JSON: Path = DATA_DIR / "asset_map.json"
ASSET_MAP_CSV: Path  = DATA_DIR / "asset_map.csv"
GAME_VERSION_FINGERPRINT: str = ".rsmm_game_version.json"


def self_cmd(args: list[str]) -> list[str]:
    """Build a subprocess argv that re-invokes rsmm itself.

    In a PyInstaller-frozen bundle there is no `rsmm` script next to the
    executable — `sys.executable` IS the bundled rsmm. In a source tree,
    re-invoke the python wrapper script via the current interpreter.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(REPO_ROOT / "rsmm"), *args]

# `MODS_DIR` and `DEFAULT_GAME_DIR` are resolved lazily via PEP 562
# `__getattr__` so `import rsmm.engine.paths` does not trigger the
# Ravenswatch-install disk scan (slow on Windows with network drives).


def __getattr__(name: str) -> Path:
    if name == "MODS_DIR":
        return mods_dir()
    if name == "DEFAULT_GAME_DIR":
        return default_game_dir()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_FINGERPRINT_BINARIES: tuple[str, ...] = (
    "Ravenswatch.exe",
    "Ravenswatch/Binaries/Win64/Ravenswatch-Win64-Shipping.exe",
    "Ravenswatch.app/Contents/MacOS/Ravenswatch",
)

_FINGERPRINT_HEAD_BYTES = 4096


def _hash_head(h: hashlib._Hash, label: str, p: Path) -> None:
    """Mix the first `_FINGERPRINT_HEAD_BYTES` of a file into `h`.

    Content-based so the fingerprint is portable across machines (Steam
    re-touches mtimes on validate/update).
    """
    try:
        with p.open("rb") as f:
            chunk = f.read(_FINGERPRINT_HEAD_BYTES)
    except OSError:
        return
    h.update(f"{label}:{len(chunk)}:".encode())
    h.update(chunk)


def game_fingerprint(game_dir: Path) -> str:
    """Compute a deterministic fingerprint of the game install version.

    Hashes the first 4 KB of key game binaries + UsedRscList.ot so we can
    detect game updates that invalidate mod overrides. Content-based, not
    mtime-based, so the same install hashes the same on every machine.
    """
    h = hashlib.sha256()
    for rel in _FINGERPRINT_BINARIES:
        p = game_dir / rel
        if p.exists():
            _hash_head(h, rel, p)
    used = game_dir / "DarkTalesResources" / "UsedRscList.ot"
    # When the applier has registered custom assets it appends lines to
    # UsedRscList.ot and keeps the pristine original as a `.rsmm.bak`
    # sibling. Hash that pristine copy when present so our own managed
    # edits are never mistaken for a game update (which would wipe state
    # and backups on the next apply).
    used_pristine = used.with_name(used.name + ".rsmm.bak")
    src = used_pristine if used_pristine.exists() else used
    if src.exists():
        _hash_head(h, "UsedRscList.ot", src)
    return h.hexdigest()


def load_stored_fingerprint(game_dir: Path) -> str | None:
    fp = game_dir / COOKING_SUBDIR / GAME_VERSION_FINGERPRINT
    if not fp.exists():
        return None
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
        return str(raw.get("fingerprint", ""))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def save_fingerprint(game_dir: Path, fingerprint: str) -> None:
    fp = game_dir / COOKING_SUBDIR / GAME_VERSION_FINGERPRINT
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(fp.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"fingerprint": fingerprint, "ts": time.time()}, indent=2),
        encoding="utf-8",
    )
    tmp.replace(fp)
