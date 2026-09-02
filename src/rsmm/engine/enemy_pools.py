"""Biome spawn pools and the enemy-definition index they gate.

Two independent data gates decide whether an enemy can appear in a biome, and
a mod that edits one without respecting the other produces an enemy that
loads, registers, and never spawns (or worse, a null at level build). This
module is the read side of both.

**Gate 1 — the biome entity pool.** Each biome ships an ``oCGameStream``
``Map_<Biome>_EntityPooling_Settings.level`` asset whose ``asset_refs`` list
every entity streamed for that biome. An enemy definition's ``entity_ref``
must be in the pool of the biome the player is in, or the entity is simply not
there to instantiate. The pools partition cleanly — no entity appears in two —
so "which pool is this entity in" is a total function, which is what makes
:func:`pool_of_entity` safe to build a mod on.

**Gate 2 — the tribe roster.** The camp tier selector builds its candidate
list from the tribe's *runtime* roster vector
(``oCDtEnemyTribeDefinition+0x2b8``, builder ``FUN_14032de90`` → Stage-3 filter
``FUN_1403194c0``), populated at load from each enemy's ``tribe_ref``. The
cooked tribe file's own vector ships empty in all 25 tribes, so it is not the
one to patch. See ``docs/_re/kinds/enemies.md``.

The pools also carry entities that are **not** enemies — projectiles, attack
zones, VFX trails (``Projectile_Witches_Poison_Apple``,
``Gargoyle_Fire_Attack_Zone``, ``Dullahan_Gallop_Trail``). Never treat a raw
pool entry as a spawnable monster; cross-reference it against
:func:`enemy_index`, which only knows entities some ``oCDtEnemyDefinition``
actually points at.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from . import cooked, corpus_cache
from .cooked_schemas import definitions as _defs
from .paths import DATA_DIR

__all__ = [
    "BOSS_ARENA_POOLS",
    "ENEMY_DIR",
    "GEN_SUFFIX",
    "cooked_rel_for",
    "corpus_read",
    "corpus_rels",
    "corpus_source",
    "enemy_index",
    "pool_cooked_rel",
    "pool_rels",
    "spawnable_entities",
    "pool_files",
    "pool_of_entity",
    "pools",
]

UNCOOKED: Final = DATA_DIR / "uncooked"
OT_DIR: Final = UNCOOKED / "Ot"
ENEMY_DIR: Final = UNCOOKED / "Definitions" / "Enemies"
POOL_GLOB: Final = "*EntityPooling_Settings.level.ot.GameStream.gen"
GEN_SUFFIX: Final = ".enemydef.ot.DtEnemyDefinition.gen"
ENEMY_ASSET_SUBDIR: Final = "Definitions/Enemies"

#: Pools belonging to a scripted boss arena rather than to open-world camps.
#: Their contents are boss phase-adds (Baba Yaga's skulls, her summoned
#: tentacle) placed by the encounter script, not rolled by a camp selector.
#: Rewriting one changes a boss fight rather than the wandering population, so
#: mods that mean "the monsters out in the world" exclude these by default.
BOSS_ARENA_POOLS: Final = frozenset({"Baba_Yaga_Map"})


def cooked_rel_for(enemy_id: str) -> str:
    """Decoded cooked path of an enemy definition, forward-slashed."""
    return f"{ENEMY_ASSET_SUBDIR}/{enemy_id}{GEN_SUFFIX}"


# --------------------------------------------------------------------------- #
# Corpus source. Two places hold the same cooked bytes, and only one of them
# exists on a player's machine.
#
# `data/uncooked/` is the authoring mirror: 7.3 GB, gitignored, built by
# `scripts/extract_uncooked.py` from an install. It is NOT bundled into the
# PyInstaller sidecar and never will be, so for every downloaded copy of the
# app it simply is not there — which used to mean the `enemy` kind raised
# `SchemaNotMined` and emitted nothing on exactly the machines the mod is for.
#
# The install has the same bytes. `extract_uncooked` COPIES non-texture cooked
# files verbatim, so `data/uncooked/<decoded>` is byte-identical to
# `<install>/DarkTalesResources/_Cooking/<encoded>` (verified per file below by
# construction: same bytes, different name). `data/asset_map.json` IS bundled,
# so the decoded -> encoded direction is available everywhere.
#
# Two rules this indirection has to hold, both of which are silent when broken:
#
# 1. **Read the pristine copy.** `apply` overwrites cooked files in place and
#    leaves `<file>.rsmm.bak` beside them. This module answers "what does the
#    game ship", so a `.bak` — when one exists — IS the answer; reading the
#    live file would make an already-applied override look like vanilla and
#    compound edit on top of edit at the next apply.
# 2. **Never write here.** Everything below opens the install read-only. The
#    only writer of the game directory is the apply pipeline.
# --------------------------------------------------------------------------- #

def _cooking_dir() -> Path | None:
    """``<install>/DarkTalesResources/_Cooking``, or None without an install."""
    from ..cli.apply_mods import find_game_dir
    from .paths import COOKING_SUBDIR

    game = find_game_dir()
    if game is None:
        return None
    d = Path(game) / COOKING_SUBDIR
    return d if d.is_dir() else None


def _install_path(rel: str) -> Path | None:
    """Where a decoded cooked path lives in the install, pristine copy first."""
    from ..cli.apply_mods import resolve_special
    from .asset_map import decoded_to_encoded

    cooking = _cooking_dir()
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


def corpus_source() -> str:
    """Which store is answering: ``"mirror"``, ``"install"`` or ``"none"``."""
    if ENEMY_DIR.is_dir():
        return "mirror"
    return "install" if _cooking_dir() is not None else "none"


def corpus_root() -> Path:
    """Directory whose fingerprint decides whether a cached sweep is stale."""
    if ENEMY_DIR.is_dir():
        return UNCOOKED
    return _cooking_dir() or UNCOOKED


def corpus_read(rel: str) -> bytes | None:
    """Cooked bytes for a decoded path, from the mirror or from the install."""
    p = UNCOOKED / Path(*rel.split("/"))
    if p.is_file():
        return p.read_bytes()
    src = _install_path(rel)
    try:
        return src.read_bytes() if src is not None else None
    except OSError:
        return None


def corpus_rels(prefix: str = "", suffix: str = "") -> list[str]:
    """Every decoded cooked path in the corpus under ``prefix`` ending in
    ``suffix``.

    From the mirror's own tree when it exists, otherwise from the shipped
    `asset_map` — which is derived from `UsedRscList.ot` and therefore lists
    every asset the engine can load. Caches (`*.UsedRscCache.ot`) are the one
    family absent from it; they are read by name, never listed.
    """
    if ENEMY_DIR.is_dir() or UNCOOKED.is_dir():
        base = UNCOOKED / Path(*prefix.split("/")) if prefix else UNCOOKED
        if base.is_dir():
            return sorted(
                p.relative_to(UNCOOKED).as_posix()
                for p in base.rglob(f"*{suffix}") if p.is_file()
            )
    from .asset_map import decoded_to_encoded

    if _cooking_dir() is None:
        return []
    return sorted(k for k in decoded_to_encoded()
                  if k.startswith(prefix) and k.endswith(suffix))


def pool_files() -> list[tuple[str, Path]]:
    """``(biome, path)`` for every EntityPooling asset in the corpus."""
    if not OT_DIR.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for p in sorted(OT_DIR.rglob(POOL_GLOB)):
        biome = p.name.split("_EntityPooling", 1)[0]
        if biome.startswith("Map_"):
            biome = biome[len("Map_"):]
        out.append((biome, p))
    return out


def pool_entities(path: Path) -> list[str]:
    """Enemy entity refs listed in one pooling asset, in file order.

    Filtered to ``Enemies\\...`` because a pool also streams the biome's props
    and VFX; everything outside that prefix is not a spawn candidate under any
    reading.
    """
    return _pool_entities_bytes(path.read_bytes())


def _pool_entities_bytes(raw: bytes) -> list[str]:
    from .cooked_schemas.asset_refs import _decode

    doc = _decode(raw, "oCGameStream")
    return [r for r in doc["asset_refs"] if r.lower().startswith("enemies\\")]


def _biome_of_pool_rel(rel: str) -> str:
    biome = rel.rsplit("/", 1)[-1].split("_EntityPooling", 1)[0]
    return biome[len("Map_"):] if biome.startswith("Map_") else biome


def pool_rels() -> dict[str, str]:
    """``biome -> decoded cooked path`` of its EntityPooling asset.

    Source-agnostic replacement for :func:`pool_files`, which can only speak
    in mirror paths and therefore answers nothing on a player's install.
    """
    return {_biome_of_pool_rel(rel): rel
            for rel in corpus_rels(suffix=POOL_GLOB.lstrip("*"))}


def pools() -> dict[str, list[str]]:
    """``biome -> [entity ref, ...]``, cached against the corpus fingerprint."""

    def build() -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for biome, rel in sorted(pool_rels().items()):
            raw = corpus_read(rel)
            if raw is not None:
                out[biome] = _pool_entities_bytes(raw)
        return out

    return corpus_cache.load_or_build("enemy_pools", corpus_root(), build)


def pool_of_entity() -> dict[str, str]:
    """``entity ref (lowercased) -> biome``.

    The shipped pools are disjoint, so this is unambiguous. If a future patch
    breaks that, first-listed wins and the ambiguity is invisible — which is
    why callers that *change* an entity_ref should stay inside one biome's
    group rather than trusting a global lookup to keep them safe.
    """
    out: dict[str, str] = {}
    for biome, ents in pools().items():
        for e in ents:
            out.setdefault(e.lower(), biome)
    return out


def enemy_index() -> dict[str, dict[str, Any]]:
    """``enemy id -> {entity, tribe, weight, biome}`` over the whole corpus.

    ``biome`` is the pool holding the enemy's ``entity_ref``, or ``None`` for
    the definitions no pool streams — bosses, summons and quest enemies, which
    are placed by script rather than rolled by a camp selector. That ``None``
    is the cheapest reliable "is this a wandering monster?" test available
    without re-deriving the encounter graph, and it is derived from shipped
    data rather than from a name convention.
    """

    def build() -> dict[str, dict[str, Any]]:
        rels = corpus_rels(prefix=ENEMY_ASSET_SUBDIR, suffix=GEN_SUFFIX)
        if not rels:
            return {}
        spec = _defs._SPECS["oCDtEnemyDefinition"]
        by_entity = pool_of_entity()
        out: dict[str, dict[str, Any]] = {}
        for rel in rels:
            enemy_id = rel.rsplit("/", 1)[-1][: -len(GEN_SUFFIX)]
            raw = corpus_read(rel)
            if raw is None:
                continue
            try:
                body = spec.decode_body(cooked.parse(raw).sections[-1].payload)
            except (ValueError, IndexError, KeyError):
                # A def this codec version cannot read is not one a mod may
                # safely rewrite either — leave it out of the index entirely.
                continue
            entity = body["entity_ref"][1] or ""
            tribe_ref = body["tribe_ref"][1] or ""
            tribe = tribe_ref.replace("/", "\\").split("\\")[-1].split(".", 1)[0] or None
            out[enemy_id] = {
                "entity": entity,
                "tribe": tribe,
                "weight": body.get("spawn_weight"),
                "biome": by_entity.get(entity.lower()),
            }
        return out

    return corpus_cache.load_or_build("enemy_index", corpus_root(), build)


def pool_cooked_rel(biome: str) -> str:
    """Decoded cooked path of a biome's EntityPooling asset, forward-slashed.

    Derived from the corpus path rather than composed from the biome name: the
    directory and the filename disagree (``Ot/DarkHills/Map_Dark_Hills_...``),
    so a composed path silently misses and the override lands nowhere.
    """
    rel = pool_rels().get(biome)
    if rel is None:
        raise KeyError(biome)
    return rel


def spawnable_entities() -> list[str]:
    """Every prefab a camp selector can roll, across all open-world biomes.

    Excludes definitions no pool streams (bosses, summons, quest enemies) and
    the boss-arena pools. This is the candidate set for cross-biome mixing —
    the answer to "which creatures exist in the whole game".
    """
    idx = enemy_index()
    return sorted({r["entity"] for r in idx.values()
                   if r["biome"] is not None and r["biome"] not in BOSS_ARENA_POOLS})
