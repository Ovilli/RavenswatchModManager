"""``*.UsedRscCache.ot`` — the per-definition preload manifest.

A handful of cooked *definition* kinds ship a sibling file next to them that
lists every resource the definition transitively needs::

    Definitions\\Tiles\\Dark_Hills\\40x40_Dark_Hills_Start_Update3.tiledef.ot.DtTileDefinition.gen
    Definitions\\Tiles\\Dark_Hills\\40x40_Dark_Hills_Start_Update3.tiledef.UsedRscCache.ot   <- this

It is plain UTF-8 text, one resource per line, three ``|``-separated fields::

    EntitySettings|DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot|oCEntitySettingsResource
    3D|Scenery\\DarkHills\\Wall_Ruins_Block_Small_A.fbx|oCGeometry
    Ot|DarkHills\\Tiles\\40x40_DarkHills_Starting_Tile_Update3.level.ot|oCGameStream

``<root>`` is the first component of the decoded cooked path, ``<path>`` the
remainder with the cook suffix stripped, ``<class>`` the engine class.

**Why this module exists.** The cache is NOT registered in ``UsedRscList.ot``
— the engine finds it by convention, appending the literal ``.UsedRscCache.ot``
to the resource path (game_va ``0x140311110``, which also performs the
``\\`` -> ``!`` filename collapse). Because it is absent from the master
manifest it is also absent from ``asset_map.json``, so the corpus mirror needs
a special case exactly like the FMOD sound banks do.

**Why it is load-bearing.** All 237 shipped tiledefs have one — no exceptions.
A new tiledef without a cache has nothing to preload, so it is registered,
never placed, and reports nothing. Worse, a *stale* cache (the definition was
edited to reference an asset the cache does not list) leaves a null in the
preloaded pointer vector, and the engine's teardown loop at ``0x140476f60``
destroys every element of that vector without a null check — an access
violation at ``0x1401273b6`` reading address 0, far from the real mistake.
Both failures were observed in-game on 2026-08-10.

Which kinds need one, measured over the shipped tree (575 caches):
``tiledef`` 237/237, ``entity`` 105 (heroes/enemies only — **not** scenery
props), ``enemydef`` 81, ``Achievementdef`` 45, ``gamemodifierdef`` 22,
``enemytribedef`` 21, ``herodef`` 12, ``melodydef`` 12, ``rewarddef`` 9,
``enemycampdifficultydef`` 6, ``ingredientdef`` 6, ``challengedef`` 5,
``enemycamptierdef`` 4, ``mapdef`` 4, ``dreamsharddef`` 4,
``gamemodedefaultdef`` 1, ``versiondef`` 1. Levels (0/370) and scenery prop
entities (0/733) do not.
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = [
    "CACHE_SUFFIX",
    "COOK_SUFFIXES",
    "CacheError",
    "cache_path_for",
    "entry_for",
    "extend",
    "parse",
    "render",
]

#: Appended to a resource path to name its cache. Matches the literal the
#: engine itself concatenates (16 chars + NUL = the 17-byte copy at
#: ``0x14031165b``).
CACHE_SUFFIX = ".UsedRscCache.ot"

#: Cook suffix -> engine class, mined from all 575 shipped caches cross-
#: referenced against ``asset_map.json`` (271190 lines, no ambiguity: every
#: suffix maps to exactly one class).
#:
#: Several names look truncated (``.hievementDefinition.gen`` for
#: *Achievement*, ``.rsionDefinition.gen`` for *Version*). That is not a typo
#: here — the shipped filenames really are cut that way, the same quirk
#: ``apply_mods.VERSIONDEF_GEN_LEAF`` already carries.
COOK_SUFFIXES: dict[str, str] = {
    ".EntitySettingsResource.gen": "oCEntitySettingsResource",
    ".Texture.dxt": "oCTexture",
    ".Texture.nrm": "oCTexture",
    ".Texture.gen": "oCTexture",
    ".Geometry.gen": "oCGeometry",
    ".Material.gen": "oCMaterial",
    ".ScheduledVfxSettings.gen": "oCScheduledVfxSettings",
    ".Animation.gen": "oCAnimation",
    ".GameStream.gen": "oCGameStream",
    ".DtTileDefinition.gen": "oCDtTileDefinition",
    ".Shader2.dxil": "oCShader2",
    ".DtEnemyDefinition.gen": "oCDtEnemyDefinition",
    ".LocalText.gen": "oCLocalText",
    ".hievementDefinition.gen": "AchievementDefinition",
    ".DtEnemyTribeDefinition.gen": "oCDtEnemyTribeDefinition",
    ".meModifierDefinition.gen": "GameModifierDefinition",
    ".DtHeroDefinition.gen": "oCDtHeroDefinition",
    ".lodyDefinition.gen": "MelodyDefinition",
    ".CollisionMesh.gen": "oCCollisionMesh",
    ".DtRewardDefinition.gen": "oCDtRewardDefinition",
    ".DtEnemyCampDifficultyDefinition.gen": "oCDtEnemyCampDifficultyDefinition",
    ".DtIngredientDefinition.gen": "oCDtIngredientDefinition",
    ".Font.fnb": "oCFont",
    ".allengeDefinition.gen": "ChallengeDefinition",
    ".DtDreamShardDefinition.gen": "oCDtDreamShardDefinition",
    ".DtEnemyCampTierDefinition.gen": "oCDtEnemyCampTierDefinition",
    ".DtMapDefinition.gen": "oCDtMapDefinition",
    ".meModeDefaultDefinition.gen": "GameModeDefaultDefinition",
    ".rsionDefinition.gen": "VersionDefinition",
}

#: Longest-first, so ``.Texture.gen`` can never shadow a longer suffix that
#: happens to end the same way.
_SUFFIXES_BY_LENGTH = sorted(COOK_SUFFIXES, key=len, reverse=True)


class CacheError(ValueError):
    """A cooked path has no known cook suffix, so no cache line can be built."""


def _split_cook(cooked: str) -> tuple[str, str, str]:
    """``(root, resource_path, class)`` for a decoded cooked path.

    ``3D/Scenery/DarkHills/M_x.mat.ot.Material.gen``
    -> ``("3D", "Scenery\\DarkHills\\M_x.mat.ot", "oCMaterial")``
    """
    path = cooked.replace("/", "\\").lstrip("\\")
    for suffix in _SUFFIXES_BY_LENGTH:
        if path.endswith(suffix):
            stem = path[: -len(suffix)]
            break
    else:
        raise CacheError(
            f"{cooked!r} has no recognised cook suffix; add it to "
            f"rsc_cache.COOK_SUFFIXES (mine it with the shipped caches first)."
        )
    root, sep, rest = stem.partition("\\")
    if not sep:
        raise CacheError(f"{cooked!r} has no root directory component")
    return root, rest, COOK_SUFFIXES[suffix]


def entry_for(cooked: str) -> str:
    """The single cache line registering the decoded cooked path ``cooked``."""
    root, rest, cls = _split_cook(cooked)
    return f"{root}|{rest}|{cls}"


def cache_path_for(cooked: str) -> str:
    """Decoded cooked path of the cache belonging to definition ``cooked``.

    The engine builds it from the *resource* name, i.e. the cooked path with
    the cook suffix removed and the trailing ``.ot`` dropped::

        Definitions/Tiles/Dark_Hills/X.tiledef.ot.DtTileDefinition.gen
        -> Definitions/Tiles/Dark_Hills/X.tiledef.UsedRscCache.ot

    Returned with ``/`` separators, matching the rest of the emit pipeline.
    """
    root, rest, _cls = _split_cook(cooked)
    stem = f"{root}\\{rest}"
    if stem.endswith(".ot"):
        stem = stem[: -len(".ot")]
    return f"{stem}{CACHE_SUFFIX}".replace("\\", "/")


def parse(data: bytes) -> list[str]:
    """Cache bytes -> list of non-empty lines, order preserved."""
    return [ln for ln in data.decode("utf-8").split("\n") if ln]


def render(lines: Iterable[str]) -> bytes:
    """Lines -> cache bytes.

    Shipped caches are ``\\n``-separated with a trailing newline and no BOM.
    """
    body = "\n".join(lines)
    return (body + "\n").encode("utf-8") if body else b""


def extend(donor: bytes, cooked_paths: Iterable[str]) -> bytes:
    """``donor`` plus a line for each decoded cooked path not already listed.

    Additive *by design*. A cloned definition's cache starts as its donor's,
    which means it keeps lines for resources the clone replaced — those still
    name real shipped files, so preloading them is wasted work and nothing
    more. Dropping them would mean proving no other reference reaches them,
    which the string-reference graph cannot cheaply establish; a missing line
    crashes the game, a surplus line does not.

    **The result is re-sorted, and that is load-bearing.** All 575 shipped
    caches are in ascending line order, with no exceptions — the engine looks a
    resource up in here rather than scanning, so a line appended after the end
    is a line the lookup never reaches. The failure is silent and total: the
    resource resolves to null, and whatever referenced it fails to build. That
    cost four playtests. It presents two completely different ways depending on
    who was doing the looking, and neither points here:

    * a tiledef appended to a **mapdef's** cache is never preloaded, so the
      tile is registered, pooled, and simply never placed — no error, no crash,
      nothing in the log;
    * an entity appended to a **tile's** cache resolves to null while that
      tile's level deserialises, the level load fails, and the engine's cleanup
      walks the half-built object array and destroys a null pointer — an
      access violation at ``0x1401273b6``, nowhere near the real mistake.

    Sorting is a plain ascending byte order over the whole ``root|path|class``
    line, which is exactly what the shipped files are in.
    """
    lines = parse(donor)
    seen = set(lines)
    for cooked in cooked_paths:
        line = entry_for(cooked)
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return render(sorted(lines))
