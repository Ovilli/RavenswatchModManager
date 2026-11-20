"""Shared helpers for SDK content-kind builders.

Centralizes the bits every kind needs so the per-kind modules stay
focused on their own schema:

* schema sentinels (``EMPTY_STRING_SENTINEL``, ``UNRESOLVED_NAME_HASH``)
  read by the ctors documented in ``https://docs.rsmm.me/reverse-engineering/mod-hooks/`` and the
  per-kind pages.
* ``validate_id`` / ``slug_id`` — ASCII identifier guards (the game's
  resource-path parser rejects anything outside ``[A-Za-z0-9_]``).
"""

from __future__ import annotations

import re
from typing import Final

# --------------------------------------------------------------------------- #
# Schema sentinels — referenced by every kind's ctor (see docs/_re).
# --------------------------------------------------------------------------- #

#: Global empty-string sentinel written into unresolved "named slots" by
#: every ``oCDtDefinition``-derived ctor. The asset loader replaces it
#: with the pooled string once the name resolves.
EMPTY_STRING_SENTINEL: Final[int] = 0x140EB46D0

#: ``oCResourcePath::hash`` sentinel that means "not yet resolved".
UNRESOLVED_NAME_HASH: Final[int] = 0x80000000


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


def list_entry(field: str, entry, n: int, shape: str) -> tuple:
    """The first ``n`` elements of a list-form manifest entry (``[label, old,
    new]``...), or a ``ContentError`` naming ``shape``.

    An entry that is too short or not a list at all (a bare string, a number)
    otherwise raised IndexError/TypeError out of the kind, which apply does not
    catch: one typo in one mod aborted the apply for every mod."""
    from ..content import ContentError
    if not isinstance(entry, (list, tuple)) or len(entry) < n:
        raise ContentError(f"{field} entry must be {shape} or a table, got {entry!r}")
    return tuple(entry[:n])
