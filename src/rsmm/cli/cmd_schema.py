"""rsmm schema — list the vanilla ids a content kind's ``base`` accepts.

Every kind that clones or edits a shipped definition names it with ``base``.
This command lists the valid values so authors don't have to guess, and
`rsmm lint` checks ``base`` against the same lists.

The ids come from the same lookups the kinds use, read through
`rsmm.engine.corpus` — the ``data/uncooked`` mirror on an authoring checkout,
the game install everywhere else. (This command used to read only the mirror's
decoded ``*.json`` files, so on a player's machine it listed nothing.)

    rsmm schema                 # counts per kind
    rsmm schema hero            # every hero base id
    rsmm schema item --grep Orb # filter
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from rsmm.engine import corpus

_MO_DIR = "EntitySettings/Objects/Magical_Objects/"
_MO_SUFFIX = ".entity.ot.EntitySettingsResource.gen"


def _heroes() -> list[str]:
    return corpus.stems("Definitions/Heroes", ".herodef.ot.DtHeroDefinition.gen")


def _bosses() -> list[str]:
    from rsmm.sdk.kinds import bosses
    return sorted(bosses._boss_defs())


def _enemies() -> list[str]:
    from rsmm.engine import enemy_pools as EP
    return sorted(set(EP.enemy_index()) - set(_bosses()))


def _maps() -> list[str]:
    from rsmm.sdk.kinds import maps
    return sorted(maps.BASES)


def _items() -> list[str]:
    return sorted({r.rsplit("/", 1)[-1][: -len(_MO_SUFFIX)]
                   for r in corpus.rels(_MO_DIR, _MO_SUFFIX)})


def _tiles() -> list[str]:
    from rsmm.sdk.kinds import poi
    return poi.known_tiles()


def _stems(directory: str, suffix: str) -> Callable[[], list[str]]:
    return lambda: corpus.stems(directory, suffix)


#: kind -> the ids its ``base`` field accepts.
SOURCES: dict[str, Callable[[], list[str]]] = {
    "hero": _heroes,
    "enemy": _enemies,
    "boss": _bosses,
    "map": _maps,
    "item": _items,
    "poi": _tiles,
    "game_mode": _stems("Definitions/GameModes",
                        ".gamemodedefaultdef.ot.meModeDefaultDefinition.gen"),
    "reward": _stems("Definitions/Rewards", ".rewarddef.ot.DtRewardDefinition.gen"),
    "melody": _stems("Definitions/Melodies", ".melodydef.ot.lodyDefinition.gen"),
    "modifier": _stems("Definitions/GameModifiers",
                       ".gamemodifierdef.ot.meModifierDefinition.gen"),
}

_KINDS = tuple(SOURCES)

_USAGE = (
    f"usage: rsmm schema [{'|'.join(_KINDS)}] [--grep TEXT]\n"
    "\n"
    "List the vanilla ids each content kind's `base` accepts.\n"
    "No kind => a per-kind count summary.\n"
)


def ids_for(kind: str) -> list[str]:
    """Sorted valid ``base`` ids for one kind; empty when neither the game
    install nor the mirror is readable."""
    return SOURCES[kind]()


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0

    kind: str | None = None
    grep: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--grep":
            i += 1
            grep = argv[i] if i < len(argv) else None
        elif a in _KINDS:
            kind = a
        else:
            print(f"unknown arg {a!r}\n\n{_USAGE}", file=sys.stderr)
            return 2
        i += 1

    if corpus.source() == "none":
        print("no game install found (and no data/uncooked mirror) — set "
              "RSMM_GAME_DIR to your Ravenswatch folder.", file=sys.stderr)
        return 1

    if kind is None:
        print("Valid `base` ids per content kind (use `rsmm schema <kind>`):\n")
        for k in _KINDS:
            print(f"  {k:9} {len(ids_for(k)):>4}")
        return 0

    ids = ids_for(kind)
    if grep:
        g = grep.lower()
        ids = [x for x in ids if g in x.lower()]
    for x in ids:
        print(x)
    if not ids:
        suffix = f" matching {grep!r}" if grep else ""
        print(f"(no {kind} ids{suffix})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
