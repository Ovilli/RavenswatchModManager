"""One hardened ZIP extractor for every path that unpacks a downloaded mod.

Three call sites used to carry three near-identical copies of this logic
(``cli/cmd_install.py``, ``cli/update_cmd.py``, ``cli/json_bridge.py``) and
they had drifted: only two of them blocked executable payloads, none of them
capped the decompressed size, and one derived a directory name to ``rmtree``
straight from attacker-controlled archive bytes. Same reasoning as
``engine/hashing.py`` — a security primitive that exists in three copies is a
primitive that is only as strong as its weakest copy.

What every extraction through here is guaranteed:

* **No path escape.** Member names are normalised (backslashes, ``.``/``..``,
  drive letters, absolute paths) and the resolved destination must stay under
  the destination root. The check compares path *components*
  (``is_relative_to``), not string prefixes — a bare ``startswith`` lets an
  entry escape into a sibling dir sharing the prefix (``mods/`` ->
  ``mods-evil/``).
* **No symlink escape.** Members are read with ``ZipFile.open`` and written as
  regular files, so a symlink entry lands as a file whose contents are the
  link target string. Nothing that could later redirect a write is created.
* **No decompression bomb.** Entry count, declared uncompressed size and
  compression ratio are checked from the central directory before the first
  byte is written. The real byte count is also metered *during* the copy —
  defence in depth, since ``ZipExtFile`` already truncates at the declared
  size, but the meter is what bounds the total across members.
* **No executable payloads.** Mods ship data, not binaries;
  :data:`DANGEROUS_EXTENSIONS` is refused outright.

Stdlib only: the CLI ships frozen with no runtime dependencies.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

from .repo import RepoError

#: Subclassing ``RepoError`` keeps every existing ``except RepoError`` at the
#: call sites working while letting new code catch archive faults precisely.


class ArchiveError(RepoError):
    """An archive was rejected before, or part-way through, extraction."""


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

#: File types a mod may never ship. Mods are data (assets, TOML, Lua); an
#: executable in the payload is either malware or a mistake. ``.py`` is
#: deliberately absent — the sanctioned lifecycle hooks (``on_disable.py``,
#: build hooks) are Python and are separately gated by ``rsmm lint``.
DANGEROUS_EXTENSIONS = frozenset({
    ".exe", ".dll", ".sys", ".drv", ".scr", ".cpl",
    ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
    ".ps1", ".psm1", ".psd1", ".ps1xml",
    ".sh", ".bash", ".zsh",
    ".bat", ".cmd",
    ".jar",
    ".pyc", ".pyd",
    ".wasm", ".php", ".asp", ".aspx", ".jsp",
})

#: Prefix marking an overlay copied into the game install root rather than
#: into the cooked-asset tree. There is deliberately no executable exemption
#: here: a locally authored mod may drop a binary in its own game dir and is
#: only warned about it at apply time (``apply_mods.apply_one``), but a mod
#: arriving over the network may not ship one at all, and ``_root/`` is exactly
#: the path that would put it somewhere Windows will load from.
ROOT_OVERLAY_PREFIX = "_root/"

#: Ceilings. Generous enough that no honest mod hits them — the largest
#: shipped mods are tens of MB of cooked assets — and tight enough that a
#: malicious archive cannot exhaust memory or disk.
MAX_ENTRIES = 20_000
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024      # 2 GiB uncompressed
MAX_COMPRESSION_RATIO = 200                    # 42.zip is ~10^9:1

_CHUNK = 1 << 16  # 64 KiB — keeps memory flat on large assets.

# Windows refuses these as filenames regardless of extension; rejecting them
# up front turns a confusing mid-extract OSError into a clear diagnostic.
_WIN_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

_BAD_NAME_CHARS = frozenset('/\\:*?"<>|\0')


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------


def safe_dir_name(name: str, *, what: str = "mod id") -> str:
    """Return `name` if it is safe to join onto a root directory, else raise.

    Guards the class of bug where a directory name taken from untrusted input
    (a zip's top-level entry, a registry slug typed on the command line) is
    joined onto ``mods/`` and then *deleted*: ``mods/".."`` resolves to the
    repo root and ``mods/""`` resolves to ``mods/`` itself, so an
    ``--force`` install of a crafted archive could ``rmtree`` either one.
    """
    if not isinstance(name, str) or not name:
        raise ArchiveError(f"empty {what}")
    if name in (".", ".."):
        raise ArchiveError(f"unsafe {what}: {name!r}")
    if set(name) & _BAD_NAME_CHARS:
        raise ArchiveError(f"unsafe {what} (path separator or reserved char): {name!r}")
    if os.path.isabs(name) or os.path.normpath(name) != name:
        raise ArchiveError(f"unsafe {what} (not a plain directory name): {name!r}")
    if name.split(".", 1)[0].lower() in _WIN_RESERVED:
        raise ArchiveError(f"unsafe {what} (reserved device name on Windows): {name!r}")
    return name


def contained_path(root: Path, rel: str) -> Path:
    """Resolve `rel` under `root`, raising if it escapes.

    ``root`` itself is resolved first so a symlinked ``mods/`` does not make
    every member look like an escape.
    """
    root_res = Path(root).resolve()
    target = (root_res / rel).resolve()
    if target != root_res and not target.is_relative_to(root_res):
        raise ArchiveError(f"unsafe path in archive: {rel!r}")
    return target


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def _norm(name: str) -> str:
    return name.replace("\\", "/")


def _file_names(zf: zipfile.ZipFile) -> list[str]:
    return [_norm(n) for n in zf.namelist() if n and not n.endswith("/")]


def single_top_dir(zf: zipfile.ZipFile) -> str | None:
    """Return the archive's one top-level directory, or ``None``.

    ``None`` means the members are not all inside a single directory — either
    the archive is flat, is empty, or has several roots.
    """
    names = _file_names(zf)
    if not names:
        return None
    if not all("/" in n for n in names):
        return None
    tops = {n.split("/", 1)[0] for n in names}
    if len(tops) != 1:
        return None
    return tops.pop()


def require_single_top_dir(zf: zipfile.ZipFile, *, what: str = "mod id") -> str:
    """Return the validated single top-level dir name, or raise."""
    top = single_top_dir(zf)
    if top is None:
        tops = sorted({n.split("/", 1)[0] for n in _file_names(zf)})
        raise ArchiveError(
            f"archive must contain exactly one top-level mod dir, got {tops}")
    return safe_dir_name(top, what=what)


def scan_dangerous(zf: zipfile.ZipFile, label: str) -> list[str]:
    """Reject blocked file types; return the ``_root/`` overlay paths.

    Raises :class:`ArchiveError` listing every blocked member. The extension
    test runs on the path *inside* the mod dir, so a mod whose id happens to
    end in ``.sh`` is not self-blocking.

    The returned list is what the caller should warn about: every ``_root/``
    member overwrites a file in the game install itself, which is worth saying
    out loud whatever its extension. It used to be filtered to a set of
    "dangerous root extensions" — but every extension in that set was also in
    :data:`DANGEROUS_EXTENSIONS`, which is checked first and raises, so the
    warning could never fire and implied a leniency for ``_root/`` binaries
    that does not exist.
    """
    blocked: list[str] = []
    overlays: list[str] = []
    for entry in zf.infolist():
        if entry.is_dir():
            continue
        name = _norm(entry.filename)
        parts = name.split("/", 1)
        inner = parts[1] if len(parts) > 1 else parts[0]
        if Path(inner).suffix.lower() in DANGEROUS_EXTENSIONS:
            blocked.append(entry.filename)
        if inner.startswith(ROOT_OVERLAY_PREFIX):
            overlays.append(inner[len(ROOT_OVERLAY_PREFIX):])
    if blocked:
        raise ArchiveError(
            f"{label} contains blocked file type(s):\n  " + "\n  ".join(blocked[:20])
        )
    return overlays


def check_limits(zf: zipfile.ZipFile, label: str, *,
                 max_entries: int = MAX_ENTRIES,
                 max_total_bytes: int = MAX_TOTAL_BYTES,
                 max_ratio: int = MAX_COMPRESSION_RATIO) -> None:
    """Reject decompression bombs from the central directory alone.

    Cheap pre-flight: no member is opened. The declared sizes are attacker
    controlled, so :func:`safe_extract` re-checks the real byte count while
    copying — this only avoids starting work that is obviously hostile.
    """
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ArchiveError(
            f"{label}: too many entries ({len(infos)} > {max_entries})")
    declared = sum(i.file_size for i in infos)
    packed = sum(i.compress_size for i in infos)
    if declared > max_total_bytes:
        raise ArchiveError(
            f"{label}: uncompressed size {declared} bytes exceeds the "
            f"{max_total_bytes}-byte limit")
    if packed > 0 and declared // packed > max_ratio:
        raise ArchiveError(
            f"{label}: compression ratio {declared // packed}:1 exceeds the "
            f"{max_ratio}:1 limit (decompression bomb?)")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _member_rel(info: zipfile.ZipInfo, strip_prefix: str, label: str) -> str | None:
    """Normalised, escape-checked path of `info` relative to the dest root.

    Returns ``None`` for members outside `strip_prefix` (nothing to write).
    """
    name = _norm(info.filename)
    if strip_prefix:
        if not name.startswith(strip_prefix):
            return None
        name = name[len(strip_prefix):]
    if not name:
        return None
    rel = os.path.normpath(name)
    if os.path.isabs(rel) or os.path.splitdrive(rel)[0]:
        raise ArchiveError(f"{label}: refusing absolute path in archive: "
                           f"{info.filename!r}")
    if rel == os.curdir:
        return None
    if rel.startswith(os.pardir + os.sep) or rel == os.pardir:
        raise ArchiveError(f"{label}: refusing traversal path in archive: "
                           f"{info.filename!r}")
    return rel


def _copy_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo,
                 target: Path, budget: int, label: str) -> int:
    """Stream one member to `target`, aborting if it exceeds `budget` bytes."""
    written = 0
    with zf.open(info) as src, target.open("wb") as out:
        while True:
            chunk = src.read(_CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > budget:
                raise ArchiveError(
                    f"{label}: entry {info.filename!r} is larger than its "
                    "declared size and blew the extraction budget")
            out.write(chunk)
    return written


def safe_extract(zf: zipfile.ZipFile, dest_root: Path, *,
                 strip_prefix: str = "", label: str = "archive",
                 max_entries: int = MAX_ENTRIES,
                 max_total_bytes: int = MAX_TOTAL_BYTES,
                 max_ratio: int = MAX_COMPRESSION_RATIO) -> int:
    """Extract every member of `zf` under `dest_root`. Returns bytes written.

    `strip_prefix` (e.g. ``"MyMod/"``) is removed from each member name, which
    is how an archive packed as ``<id>/...`` is unpacked *into* an already
    named directory. Members outside the prefix are skipped.

    Callers that care about atomicity should extract into a staging directory
    and ``os.replace``/``shutil.move`` it into place: a failure part-way
    through leaves whatever was already written.
    """
    check_limits(zf, label, max_entries=max_entries,
                 max_total_bytes=max_total_bytes, max_ratio=max_ratio)
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    written = 0
    for info in zf.infolist():
        rel = _member_rel(info, strip_prefix, label)
        if rel is None:
            continue
        target = contained_path(dest_root, rel)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        written += _copy_member(zf, info, target,
                                max_total_bytes - written, label)
    return written
