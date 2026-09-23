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

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .paths import DATA_DIR

UNCOOKED: Final = DATA_DIR / "uncooked"


def cooking_dir() -> Path | None:
    """``<install>/DarkTalesResources/_Cooking``, or None without an install."""
    from ..cli.apply_mods import find_game_dir
    from .paths import COOKING_SUBDIR

    game = find_game_dir()
    if game is None:
        return None
    d = Path(game) / COOKING_SUBDIR
    return d if d.is_dir() else None


def install_path(rel: str) -> Path | None:
    """Where a decoded cooked path lives in the install, pristine copy first."""
    from ..cli.apply_mods import resolve_special
    from .asset_map import decoded_to_encoded

    cooking = cooking_dir()
    if cooking is None:
        return None
    dec2enc = decoded_to_encoded()
    enc = dec2enc.get(rel) or resolve_special(rel, dec2enc)
    if not enc:
        return None
    p = cooking / enc.replace("\\", "/")
    bak = p.with_name(p.name + ".rsmm.bak")
    if bak.is_file():
        return bak
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
    from the install; None when neither has it."""
    rel = rel.replace("\\", "/")
    p = UNCOOKED / Path(*rel.split("/"))
    if p.is_file():
        return p.read_bytes()
    src = install_path(rel)
    try:
        return src.read_bytes() if src is not None else None
    except OSError:
        return None


def exists(rel: str) -> bool:
    """Does the game ship this decoded path (mirror or install)?"""
    rel = rel.replace("\\", "/")
    return (UNCOOKED / Path(*rel.split("/"))).is_file() or install_path(rel) is not None


def rels(prefix: str = "", suffix: str = "") -> list[str]:
    """Every decoded cooked path in the corpus under ``prefix`` ending in
    ``suffix``.

    From the mirror's own tree when it has ``prefix``, otherwise from the
    shipped `asset_map` — which is derived from `UsedRscList.ot` and therefore
    lists every asset the engine can load. Caches (`*.UsedRscCache.ot`) are the
    one family absent from it; they are read by name, never listed.
    """
    base = UNCOOKED / Path(*prefix.split("/")) if prefix else UNCOOKED
    if base.is_dir():
        return sorted(
            p.relative_to(UNCOOKED).as_posix()
            for p in base.rglob(f"*{suffix}") if p.is_file()
        )
    from .asset_map import decoded_to_encoded

    if cooking_dir() is None:
        return []
    return sorted(k for k in decoded_to_encoded()
                  if k.startswith(prefix) and k.endswith(suffix))


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
    prefix = directory.rstrip("/") + "/"
    return sorted({r[len(prefix):].split("/", 1)[0]
                   for r in rels(prefix) if "/" in r[len(prefix):]})


def files(directory: str, suffix: str = "") -> list[CorpusFile]:
    """The files directly in ``directory`` ending in ``suffix``, sorted."""
    prefix = directory.rstrip("/") + "/"
    return [CorpusFile(r) for r in rels(prefix, suffix) if "/" not in r[len(prefix):]]
