"""rsmm schema — list cloneable vanilla content ids.

The typed SDK builders (``m.item``/``m.enemy``/``m.boss``/``m.map``/
``m.hero``) all clone a vanilla ``base``. This command enumerates the
valid ``base`` ids by scanning ``data/uncooked`` so authors don't have to
guess. Ids are the uncooked definition/entity filenames with their
type suffix stripped.

    rsmm schema                 # counts per kind
    rsmm schema hero            # every hero base id
    rsmm schema item --grep Orb # filter
"""

from __future__ import annotations

import sys

from rsmm.engine.paths import DATA_DIR

_UNCOOKED = DATA_DIR / "uncooked"

# kind -> (glob under data/uncooked, suffix to strip from the stem, filter fn)
_SOURCES: dict[str, tuple[str, str]] = {
    "hero":  ("Definitions/Heroes/*.herodef.json",   ".herodef"),
    "enemy": ("Definitions/Enemies/*.enemydef.json", ".enemydef"),
    "boss":  ("Definitions/Enemies/*.enemydef.json", ".enemydef"),
    "map":   ("Definitions/Maps/*.mapdef.json",      ".mapdef"),
    "item":  ("EntitySettings/Objects/Magical_Objects/**/*.entity.entitysettings.json",
              ".entity.entitysettings"),
}

_KINDS = tuple(_SOURCES)

_USAGE = (
    f"usage: rsmm schema [{'|'.join(_KINDS)}] [--grep TEXT]\n"
    "\n"
    "List cloneable vanilla `base` ids for the typed SDK builders.\n"
    "No kind => a per-kind count summary.\n"
)


def _clean(stem: str, strip: str) -> str:
    name = stem
    # ``*.entity.entitysettings.json`` -> Path.stem is ``*.entity.entitysettings``
    if name.endswith(strip):
        name = name[: -len(strip)]
    return name


def ids_for(kind: str) -> list[str]:
    """Sorted base ids for one kind. ``boss`` = enemies whose id contains
    'Boss'; ``enemy`` = the rest."""
    glob, strip = _SOURCES[kind]
    out: set[str] = set()
    for p in _UNCOOKED.glob(glob):
        name = _clean(p.name[: -len(".json")] if p.name.endswith(".json") else p.stem, strip)
        out.add(name)
    if kind == "boss":
        out = {n for n in out if "Boss" in n}
    elif kind == "enemy":
        out = {n for n in out if "Boss" not in n}
    return sorted(out)


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

    if not _UNCOOKED.is_dir():
        print(f"no uncooked data at {_UNCOOKED} — run `rsmm uncook` first?",
              file=sys.stderr)
        return 1

    if kind is None:
        print("Cloneable vanilla base ids (use `rsmm schema <kind>`):\n")
        for k in _KINDS:
            print(f"  {k:6} {len(ids_for(k)):>4}")
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
