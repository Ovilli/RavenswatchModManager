"""Shared helpers for SDK content-kind builders.

Centralizes the bits every kind needs so the per-kind modules stay
focused on their own schema:

* schema sentinels (``EMPTY_STRING_SENTINEL``, ``UNRESOLVED_NAME_HASH``)
  read by the ctors documented in ``docs/_re/MOD_HOOKS.md`` and the
  per-kind pages.
* ``name_hash`` — FNV-1a-32 placeholder for ``oCResourcePath::hash``.
  The game's exact constants live in ``oCResourcePath::Set``; until
  the RE team confirms the algorithm, every kind uses FNV-1a so the
  manifest hash is stable + non-sentinel. A single implementation
  keeps the items / enemies / heroes builders from drifting.
* ``validate_id`` / ``slug_id`` — ASCII identifier guards (the game's
  resource-path parser rejects anything outside ``[A-Za-z0-9_]``).
* ``write_json`` — deterministic JSON writer (sorted keys, LF
  newlines, UTF-8) so manifests are byte-identical on Linux, macOS,
  and Windows. This matters for repro builds and content-hash gates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final

# --------------------------------------------------------------------------- #
# Schema sentinels — referenced by every kind's ctor (see docs/_re).
# --------------------------------------------------------------------------- #

#: Global empty-string sentinel written into unresolved "named slots" by
#: every ``oCDtDefinition``-derived ctor. The asset loader replaces it
#: with the pooled string once the name resolves.
EMPTY_STRING_SENTINEL: Final[int] = 0x140EB46D0

#: ``oCResourcePath::hash`` sentinel that means "not yet resolved". Any
#: real hash colliding with this value is perturbed by ``name_hash`` so
#: the loader doesn't treat the slot as unresolved.
UNRESOLVED_NAME_HASH: Final[int] = 0x80000000

#: Default ``oCDtDefinition`` flags word (set by every kind ctor).
DEFINITION_DEFAULT_FLAGS: Final[int] = 0x0101


# --------------------------------------------------------------------------- #
# Identifier guards.
# --------------------------------------------------------------------------- #

#: Resource-name validator. The game's resource-path parser is strict
#: enough that anything outside this charset gets rejected at load time.
ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_]+$")


def validate_id(kind: str, value: str) -> None:
    """Raise ``ValueError`` if ``value`` is not a legal resource id."""
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        raise ValueError(
            f"{kind}: id {value!r} must match {ID_PATTERN.pattern} so the "
            "game's resource-path parser accepts it."
        )


def slug_id(value: str) -> str:
    """Filesystem-safe slug for fields that aren't already validated.

    Keeps ``[A-Za-z0-9_-]``, maps everything else to ``_``. Used by
    kinds that emit per-id directories so the names work on every OS
    (Windows in particular rejects ``< > : " / \\ | ? *``).
    """
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in value)


# --------------------------------------------------------------------------- #
# Hashing.
# --------------------------------------------------------------------------- #

_FNV1A_OFFSET_32: Final[int] = 0x811C9DC5
_FNV1A_PRIME_32: Final[int] = 0x01000193


def name_hash(name: str) -> int:
    """32-bit FNV-1a, matching what every SDK kind writes into ``hash`` slots.

    The game's exact algorithm hasn't been confirmed yet (it lives in
    ``oCResourcePath::Set``); FNV-1a is a placeholder that keeps the
    manifest deterministic across hosts. The apply layer replaces this
    with the real value once the in-binary hash function is identified.

    If FNV-1a happens to produce ``UNRESOLVED_NAME_HASH`` the result is
    perturbed (``^1``) so the loader can't mistake a real hash for the
    "not yet resolved" marker.
    """
    h = _FNV1A_OFFSET_32
    for b in name.encode("utf-8"):
        h ^= b
        h = (h * _FNV1A_PRIME_32) & 0xFFFFFFFF
    if h == UNRESOLVED_NAME_HASH:
        h ^= 1
    return h


# --------------------------------------------------------------------------- #
# Deterministic JSON writer.
# --------------------------------------------------------------------------- #

def write_json(path: Path, payload: Any) -> Path:
    """Write ``payload`` to ``path`` as deterministic JSON.

    * Sorted keys so the same input always produces the same bytes.
    * LF newlines via ``write_bytes`` regardless of host OS line ending.
    * UTF-8 with no BOM, matching every other text artifact in the project.
    * Creates parent directories as needed.
    * Trailing newline so POSIX tools (``diff``, ``cat``) behave.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(
        payload, indent=2, sort_keys=True, ensure_ascii=False,
    ).encode("utf-8") + b"\n"
    path.write_bytes(blob)
    return path
