"""The vanilla corpus: what the game ships, from the mirror or the install.

Two places hold the same cooked bytes, and only one of them exists on a
player's machine.

`data/uncooked/` is the authoring mirror: 7.3 GB, gitignored, built by
`scripts/extract_uncooked.py` from an install. It is NOT bundled into the
PyInstaller sidecar and never will be, so for every downloaded copy of the app
it simply is not there. A content kind that reads the mirror directly therefore
works on the developer's checkout and raises `SchemaNotMined` — or emits nothing
— on exactly the machines its mod is for. Measured 2026-09-23: with the mirror
moved aside, 34 of the 42 content blocks in the repo's own mods failed.

The install has the same bytes. `extract_uncooked` COPIES non-texture cooked
files verbatim, so `data/uncooked/<decoded>` is byte-identical to
`<install>/DarkTalesResources/_Cooking/<encoded>`. `data/asset_map.json` IS
bundled, so the decoded -> encoded direction is available everywhere.

**Every reader of vanilla bytes goes through this module**, never through a
`DATA_DIR / "uncooked"` path. The mirror's derived files (`*.json` decodes,
`*.glb` geometry, texture `.png`s) have no install twin; read the cooked
`.gen` and decode it instead.

Two rules, both silent when broken:

1. **Read the pristine copy.** `apply` overwrites cooked files in place and
   leaves `<file>.rsmm.bak` beside them. This module answers "what does the
   game ship", so a `.bak` — when one exists — IS the answer; reading the live
   file would make an applied override look like vanilla and compound edit on
   top of edit at the next apply.
2. **Never write here.** Everything below opens the install read-only. The only
   writer of the game directory is the apply pipeline.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Final

from rsmm.engine.paths import BACKUP_SUFFIX

from .paths import DATA_DIR

UNCOOKED: Final = DATA_DIR / "uncooked"


# A read costs a handful of stats, and a sweep makes tens of thousands of reads;
# on Windows a stat is 0.2-0.4 ms, so re-proving "the install / mirror is still
# there" on every read dominated the time. Both answers are therefore remembered
# for _TTL seconds, keyed on every input that selects them (env override,
# resolver functions, mirror path), so switching input is seen on the next call.
# Only "same input, directory created/removed underneath us within _TTL" can be
# stale, and only for hits: a miss is never remembered. Files are never cached.
_TTL: Final = 0.25
_cooking_memo: tuple[object, float, Path] | None = None
_mirror_memo: tuple[object, float, bool] | None = None


def cooking_dir() -> Path | None:
    """``<install>/DarkTalesResources/_Cooking``, or None without an install."""
    global _cooking_memo
    from ..cli import apply_mods
    from . import paths
    from .paths import COOKING_SUBDIR

    key = (os.environ.get("RSMM_GAME_DIR"), apply_mods.find_game_dir, paths._game_dir_candidates)
    now = time.monotonic()
    memo = _cooking_memo
    if memo is not None and memo[0] == key and now - memo[1] < _TTL:
        return memo[2]
    game = apply_mods.find_game_dir()
    if game is None:
        return None
    d = Path(game) / COOKING_SUBDIR
    if not d.is_dir():
        return None
    _cooking_memo = (key, now, d)
    return d


def _mirror_exists() -> bool:
    """Is the `UNCOOKED` directory there? (A miss is remembered per `_TTL`,
    keyed on the path so a monkeypatched `UNCOOKED` is seen at once.)"""
    global _mirror_memo
    key = UNCOOKED
    now = time.monotonic()
    memo = _mirror_memo
    if memo is not None and memo[0] == key and now - memo[1] < _TTL:
        return memo[2]
    ok = UNCOOKED.is_dir()
    # Only a miss is remembered: a present mirror is re-proven by each file's own
    # stat anyway, and a mirror that appears is seen within _TTL.
    _mirror_memo = None if ok else (key, now, False)
    return ok


def install_path(rel: str) -> Path | None:
    """Where a decoded cooked path lives in the install, pristine copy first."""
    found = install_copies(rel)
    return found[-1] if found else None


def install_copies(rel: str) -> list[Path]:
    """Every copy of a decoded cooked path in the install: the live file, then
    rsmm's pristine backup of it. A backup made before a game update is older
    than the live file, so two files read one by one through `install_path`
    can come from different game builds; a reader whose files must agree
    (a font's glyph table and its page) tries the copies itself."""
    return [c for c in _install_candidates(rel) if c.is_file()]


def _install_candidates(rel: str) -> list[Path]:
    """Where the live file and its backup would be (live first), unchecked."""
    from ..cli.apply_mods import resolve_special
    from .asset_map import decoded_to_encoded

    cooking = cooking_dir()
    if cooking is None:
        return []
    dec2enc = decoded_to_encoded()
    enc = dec2enc.get(rel) or resolve_special(rel, dec2enc)
    if not enc:
        return []
    p = cooking / enc.replace("\\", "/")
    return [p, p.with_name(p.name + BACKUP_SUFFIX)]


def mirror_path(rel: str) -> Path | None:
    """The mirror's copy of a decoded cooked path, if it has one."""
    if not _mirror_exists():
        return None
    p = UNCOOKED / Path(*rel.replace("\\", "/").split("/"))
    return p if p.is_file() else None


def source() -> str:
    """Which store is answering: ``"mirror"``, ``"install"`` or ``"none"``."""
    if UNCOOKED.is_dir():
        return "mirror"
    return "install" if cooking_dir() is not None else "none"


def root() -> Path:
    """Directory whose fingerprint decides whether a cached sweep is stale."""
    if UNCOOKED.is_dir():
        return UNCOOKED
    return cooking_dir() or UNCOOKED


def read(rel: str) -> bytes | None:
    """Cooked bytes for a decoded path (forward slashes), from the mirror or
    from the install; None when neither has it.

    When the pristine install copy is newer than the default `data/uncooked`
    mirror (a game update landed after `extract_uncooked` last ran), the
    install copy wins so mods never patch stale entity files."""
    rel = rel.replace("\\", "/")
    p = UNCOOKED / Path(*rel.split("/"))
    if _mirror_exists() and p.is_file():
        if UNCOOKED == DATA_DIR / "uncooked":
            src = install_path(rel)
            try:
                if src is not None and src.stat().st_mtime > p.stat().st_mtime:
                    return src.read_bytes()
            except OSError:
                pass
        return p.read_bytes()
    # Pristine copy first (backup, else live), opened directly: one syscall per
    # copy instead of an is_file() stat plus the open.
    for c in reversed(_install_candidates(rel)):
        try:
            return c.read_bytes()
        except OSError:
            continue
    return None


def exists(rel: str) -> bool:
    """Does the game ship this decoded path (mirror or install)?"""
    rel = rel.replace("\\", "/")
    return (
        (_mirror_exists() and (UNCOOKED / Path(*rel.split("/"))).is_file())
        or install_path(rel) is not None
    )


def rels(prefix: str = "", suffix: str = "") -> list[str]:
    """Every decoded cooked path in the corpus under ``prefix`` ending in
    ``suffix``.

    From the mirror's own tree when it has ``prefix``, otherwise from the
    shipped `asset_map` — which is derived from `UsedRscList.ot` and therefore
    lists every asset the engine can load. Caches (`*.UsedRscCache.ot`) are the
    one family absent from it; they are read by name, never listed.
    """
    return list(_rels(prefix, suffix, str(UNCOOKED), source(), str(cooking_dir())))


@cache
def _rels(prefix: str, suffix: str, _mirror: str, _store: str, _cooking: str) -> tuple[str, ...]:
    # Filtering the ~80k asset_map keys costs ~15 ms and callers ask hundreds of
    # times per run. Mirror, store and install dir are in the key, so a test that
    # swaps or hides the mirror, or an install that appears later, gets its own answer.
    base = UNCOOKED / Path(*prefix.split("/")) if prefix else UNCOOKED
    out: set[str] = set()
    if base.is_dir():
        out.update(
            p.relative_to(UNCOOKED).as_posix()
            for p in base.rglob(f"*{suffix}") if p.is_file()
        )
        if UNCOOKED != DATA_DIR / "uncooked":
            return tuple(sorted(out))
    from .asset_map import decoded_to_encoded

    if cooking_dir() is not None:
        out.update(k for k in decoded_to_encoded()
                   if k.startswith(prefix) and k.endswith(suffix))
    return tuple(sorted(out))


def stems(directory: str, suffix: str) -> list[str]:
    """File-name stems of every ``<directory>/<stem><suffix>`` the game ships
    (not recursive) — the valid ``base`` ids of a definition kind."""
    prefix = directory.rstrip("/") + "/"
    out = []
    for r in rels(prefix, suffix):
        name = r[len(prefix):]
        if "/" not in name:
            out.append(name[: -len(suffix)])
    return sorted(out)


@dataclass(frozen=True, order=True)
class CorpusFile:
    """One shipped file, addressed by decoded path — a drop-in for the
    ``Path`` a mirror glob used to return (``.name``, ``.read_bytes()``), so a
    caller written against the mirror reads the install unchanged."""

    rel: str

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    def is_file(self) -> bool:
        return exists(self.rel)

    def read_bytes(self) -> bytes:
        data = read(self.rel)
        if data is None:
            raise FileNotFoundError(self.rel)
        return data


def subdirs(directory: str) -> list[str]:
    """Names of the immediate sub-directories of ``directory``."""
    return list(_subdirs(directory.rstrip("/") + "/", str(UNCOOKED), source()))


@cache
def _subdirs(prefix: str, _mirror: str, _store: str) -> tuple[str, ...]:
    # Walking a directory is ~35 ms for the heroes tree and one card's icon
    # asks for it each time (26 per hero). The mirror and the store are in the
    # key, so a test that swaps or hides the mirror gets its own answer; the
    # mirror itself is only rewritten by scripts, in their own process.
    return tuple(sorted({r[len(prefix):].split("/", 1)[0]
                         for r in rels(prefix) if "/" in r[len(prefix):]}))


def files(directory: str, suffix: str = "") -> list[CorpusFile]:
    """The files directly in ``directory`` ending in ``suffix``, sorted."""
    prefix = directory.rstrip("/") + "/"
    return [CorpusFile(r) for r in rels(prefix, suffix) if "/" not in r[len(prefix):]]
