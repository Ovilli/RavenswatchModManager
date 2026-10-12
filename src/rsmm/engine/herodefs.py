"""Hero name -> the herodef the game actually loads.

A content update re-ships a hero under a suffixed name and deletes the old
file: Update 6 (2026-10-12) replaced ``Piper.herodef.ot`` with
``Piper_Update6.herodef.ot`` for every hero except Merlin (and added
``Kintaro``). The LiveOps versiondef names the suffixed ones. Mods, the
editors and the schema keep naming the HERO (``Piper``), so every lookup from
a name to a file goes through :func:`stem` and every list of names through
:func:`names` — a name is never glued onto a path directly, or the next
``_Update7`` breaks them all again.
"""

from __future__ import annotations

import re

from . import corpus

HERODEF_DIR = "Definitions/Heroes"
HERODEF_SUFFIX = ".herodef.ot.DtHeroDefinition.gen"

_UPDATE = re.compile(r"_Update(\d+)$")


def hero_name(herodef_stem: str) -> str:
    """``Piper_Update6`` -> ``Piper``; an unsuffixed stem is its own name."""
    return _UPDATE.sub("", herodef_stem)


def _rank(herodef_stem: str) -> int:
    m = _UPDATE.search(herodef_stem)
    return int(m.group(1)) if m else -1


def stems() -> dict[str, str]:
    """Hero name -> current herodef stem, for every shipped herodef.

    Should two revisions of one hero ever ship together, the highest
    ``_Update<N>`` wins: that is the one a newer versiondef names."""
    out: dict[str, str] = {}
    for s in corpus.stems(HERODEF_DIR, HERODEF_SUFFIX):
        name = hero_name(s)
        if name not in out or _rank(s) > _rank(out[name]):
            out[name] = s
    return out


def names() -> list[str]:
    """Every shipped hero, by name (``Piper``, ``Sun_Wukong``)."""
    return sorted(stems())


def _key(s: str) -> str:
    # `Sun_Wukong`, `Sun Wukong` and the folder spelling `SunWukong` are one hero.
    return s.lower().replace(" ", "").replace("_", "")


def stem(hero: str) -> str | None:
    """The herodef stem for a hero name, or None if no such hero ships.

    Accepts the name in any spelling the repo uses, and a full stem
    (``Piper_Update6``) as-is."""
    want = _key(hero_name(hero))
    return next((s for n, s in stems().items() if _key(n) == want), None)


def rel(hero: str) -> str | None:
    """Decoded corpus path of a hero's current herodef, or None."""
    s = stem(hero)
    return f"{HERODEF_DIR}/{s}{HERODEF_SUFFIX}" if s else None
