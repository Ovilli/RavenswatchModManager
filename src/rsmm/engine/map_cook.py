"""Cook a cloned **map** (``oCDtMapDefinition``) and point a chapter at it.

Two cooked files decide which map a chapter plays, and this module edits both:

* the **mapdef** (``*.mapdef.ot``): the map's root level, its enemy tribe and
  its tile pool. A clone copies the base's bytes under a new name. Identity is
  the file name, the same as the enemy clone that loads in game: a def is found
  by the path it was loaded from, and a mapdef carries no GUID of its own.
* the **game mode** (``All_Chapters.gamemodedefaultdef.ot``): an ordered list of
  ``Chapter`` records. Each is a discriminated union (``Chapter_Serialize``,
  0x1403254d0)::

      u32 class index   (the section's leading class id)
      u8  more           one more chapter follows
      u8  discriminator  0 = built-in biome index, 1 = resource reference
      u32 biome index        | lstr type tag + lstr asset path

  Neither branch is version-gated. A biome index is shorthand: the engine's
  chapter lookup (0x140325a90) takes the ``index``-th resource ref of the
  LiveOps version definition, whose four refs are exactly the four shipped
  mapdefs in chapter order. The resref branch names the mapdef directly, and
  ``GameModeDefaultDef_PostLoad`` resolves it (loading it on demand). So a
  resref chapter must name a MAPDEF, and that is what this writes.

The base's tile-generation level is reused (the clone keeps ``level_ref``), so
a clone is a remix of a shipped chapter, not a new terrain.
"""

from __future__ import annotations

import struct

from . import cooked
from .cooked_schemas import definitions as _defs

MAP_CLASS = "oCDtMapDefinition"
MAP_GEN_SUFFIX = ".mapdef.ot.DtMapDefinition.gen"
MODE_GEN_SUFFIX = ".gamemodedefaultdef.ot.meModeDefaultDefinition.gen"
RESREF_TYPE = "Definitions"


class MapCookError(ValueError):
    pass


def mapdef_asset_path(stem: str) -> str:
    """The resref path a chapter uses for ``<stem>.mapdef.ot``."""
    return f"Maps\\{stem}.mapdef.ot"


# --------------------------------------------------------------------------- #
# mapdef
# --------------------------------------------------------------------------- #

def read_mapdef(cooked_bytes: bytes) -> dict:
    cf = cooked.parse(cooked_bytes)
    if not cf.sections:
        raise MapCookError("mapdef has no sections")
    return _defs._SPECS[MAP_CLASS].decode_body(cf.sections[-1].payload)


def clone_mapdef(base: bytes, *, tribe: str | None = None,
                 level: str | None = None) -> bytes:
    """``base`` re-emitted, optionally with ``tribe_ref`` and/or ``level_ref``
    repointed (``level`` is an ``Ot`` path such as ``DarkHills\\X.level.ot``).

    Without edits the result is byte-identical to ``base``; the new identity is
    the file name the caller writes it under.
    """
    if tribe is None and level is None:
        return base
    cf = cooked.parse(base)
    spec = _defs._SPECS[MAP_CLASS]
    body = spec.decode_body(cf.sections[-1].payload)
    if tribe is not None:
        kind = (body.get("tribe_ref") or ["Definitions", ""])[0] or "Definitions"
        body["tribe_ref"] = [kind, f"EnemyTribes\\{tribe}.enemytribedef.ot"]
    if level is not None:
        body["level_ref"] = [body["level_ref"][0], level]
    cf.sections[-1] = cooked.Section(payload=spec.encode_body(body))
    return cooked.emit(cf)


# --------------------------------------------------------------------------- #
# game mode chapters
# --------------------------------------------------------------------------- #

def _lstr(s: str) -> bytes:
    b = s.encode("latin1")
    return struct.pack("<I", len(b)) + b


def _read_lstr(p: bytes, o: int) -> tuple[str, int]:
    if o + 4 > len(p):
        raise MapCookError("chapter resref overruns its payload")
    n = struct.unpack_from("<I", p, o)[0]
    if o + 4 + n > len(p):
        raise MapCookError("chapter resref string overruns its payload")
    return p[o + 4:o + 4 + n].decode("latin1"), o + 4 + n


def _chapter_sections(cf: cooked.CookedFile) -> list[int]:
    """Section indices of the Chapter records, in object-id order.

    The container is an object table (section 0: u32 count + one class index per
    object), one payload per object, then the root. Anything else is a layout
    this module has not seen, and it refuses rather than guess.
    """
    if len(cf.sections) < 3:
        raise MapCookError("game mode has too few sections to hold chapters")
    table = cf.sections[0].payload
    count = struct.unpack_from("<I", table, 0)[0]
    if len(table) != 4 + 4 * count or len(cf.sections) != count + 2:
        raise MapCookError(
            f"game mode object table lists {count} objects across "
            f"{len(cf.sections)} sections; expected table + {count} + root")
    cls = set(struct.unpack_from(f"<{count}I", table, 4))
    if len(cls) != 1:
        raise MapCookError("game mode objects are not all one class (Chapter)")
    return list(range(1, count + 1))


def read_chapters(mode: bytes) -> list[dict]:
    """Each chapter as ``{"more", "biome"}`` or ``{"more", "map": (type, path)}``."""
    cf = cooked.parse(mode)
    out = []
    for i in _chapter_sections(cf):
        p = cf.sections[i].payload
        if len(p) < 6:
            raise MapCookError(f"chapter {i - 1} payload is {len(p)} bytes")
        more, disc = p[4], p[5]
        if disc == 0:
            if len(p) != 10:
                raise MapCookError(f"chapter {i - 1}: enum branch is {len(p)} bytes, not 10")
            out.append({"more": more, "biome": struct.unpack_from("<I", p, 6)[0]})
        else:
            kind, o = _read_lstr(p, 6)
            path, o = _read_lstr(p, o)
            if o != len(p):
                raise MapCookError(f"chapter {i - 1}: {len(p) - o} trailing bytes")
            out.append({"more": more, "map": (kind, path)})
    return out


def set_chapter_map(mode: bytes, chapter: int, mapdef_stem: str) -> bytes:
    """``mode`` with chapter object ``chapter`` naming ``<mapdef_stem>.mapdef.ot``.

    ``chapter`` is the chapter OBJECT (0..3 in All_Chapters: Dark Hills, Storm
    Island, Avalon, Baba Yaga), not a position in the run order, so it keeps
    meaning the same thing when a game_mode edit reorders the run.
    """
    cf = cooked.parse(mode)
    secs = _chapter_sections(cf)
    if not 0 <= chapter < len(secs):
        raise MapCookError(f"chapter {chapter} does not exist (0..{len(secs) - 1})")
    old = cf.sections[secs[chapter]].payload
    payload = (old[:4] + bytes([old[4], 1])
               + _lstr(RESREF_TYPE) + _lstr(mapdef_asset_path(mapdef_stem)))
    cf.sections[secs[chapter]] = cooked.Section(payload=payload)
    return cooked.emit(cf)
