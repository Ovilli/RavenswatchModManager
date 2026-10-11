"""Forgiving names: resolve what the user meant, or say "did you mean …?".

A typo used to cost a screenful or a guess. An unknown subcommand dumped the
whole command listing, and each command that takes a mod id answered a
mis-cased one (`rsmm lint mymod` for `MyMod`) with its own wording: some
listed every installed id, some printed a path, none said which one was
close. Shell tab completion made it worse, because it hands over `MyMod/`
with a trailing slash that no command stripped.

Every mod-taking command now goes through :func:`resolve_mod`, so they all
accept the same spellings and fail the same way.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from pathlib import Path

#: Known ids printed when nothing is close enough to suggest.
_KNOWN_SHOWN = 8


class UnknownMod(LookupError):
    """No mod folder matches; the message says what is close, if anything."""


def suggest(word: str, choices: Iterable[str], n: int = 3) -> list[str]:
    """The choices closest to `word`, best first, ignoring case."""
    by_lower: dict[str, str] = {}
    for c in choices:
        by_lower.setdefault(c.lower(), c)
    hits = difflib.get_close_matches(word.lower(), list(by_lower), n=n, cutoff=0.6)
    return [by_lower[h] for h in hits]


def did_you_mean(word: str, choices: Iterable[str]) -> str:
    """`" (did you mean X?)"`, `" (did you mean X or Y?)"`, or `""`."""
    near = suggest(word, choices)
    if not near:
        return ""
    if len(near) == 1:
        return f" (did you mean {near[0]}?)"
    return f" (did you mean {', '.join(near[:-1])} or {near[-1]}?)"


def _children(mods_root: Path) -> list[str]:
    try:
        return sorted(p.name for p in mods_root.iterdir() if p.is_dir())
    except OSError:
        return []


def mod_folders(mods_root: Path) -> list[str]:
    """Folder names under mods/ a user means by a mod id: everything except
    the `_`/`.`-prefixed ones apply skips (`_merged`, `.git`, …)."""
    return [c for c in _children(mods_root) if not c.startswith(("_", "."))]


def resolve_mod(arg: str, mods_root: Path) -> str:
    """The mod folder name under `mods_root` that `arg` means.

    Accepts the exact folder name, the same name in any case when only one
    folder matches it, and a path to the folder (`mods/MyMod`, or `MyMod/`
    as tab completion writes it). Raises :class:`UnknownMod` otherwise.
    """
    name = arg.rstrip("/\\")
    if "/" in name or "\\" in name:
        p = Path(name)
        try:
            # The parent, not the folder, is resolved: a symlinked mod folder
            # keeps its own name.
            if p.is_dir() and p.parent.resolve() == mods_root.resolve():
                name = p.name
        except OSError:
            pass
    # An exact folder name always wins, even an underscored one nobody would
    # be offered (`rsmm lint _merged` keeps working). Matching against the
    # listing rather than testing `(mods_root / name).is_dir()` keeps `..`
    # and other paths out: only a real child of mods/ can come back.
    children = _children(mods_root)
    if name in children:
        return name
    folders = [c for c in children if not c.startswith(("_", "."))]
    same = [f for f in folders if f.lower() == name.lower()]
    if len(same) == 1:
        return same[0]

    msg = f"no mod '{arg}' in {mods_root}"
    hint = did_you_mean(name, folders)
    if hint:
        raise UnknownMod(msg + hint)
    if not folders:
        raise UnknownMod(msg + " (it has no mods yet; `rsmm new <id>` makes one)")
    shown = ", ".join(folders[:_KNOWN_SHOWN])
    more = f", +{len(folders) - _KNOWN_SHOWN} more" if len(folders) > _KNOWN_SHOWN else ""
    raise UnknownMod(f"{msg} (installed: {shown}{more})")
