"""Field-level edits to the game's PLAINTEXT `.ot` files.

A handful of `oCTextSaver` files ship uncooked beside the executable —
`DarkTalesResources/ApplicationSettings.ot` is the one mods care about, and it
carries the friendly-fire factors, the forced-seed option and the entity-value
modifier descriptors. `apply` has always been able to install a replacement for
them through the `_root/` channel, but a mod could only do that by shipping the
WHOLE file: a copy of a game asset, and one that silently reverts every unrelated
change the next game patch makes to it.

This module edits the game's own copy instead: locate the block whose selector
field holds a given value, rewrite ONE field inside that block, leave every other
byte alone. It backs `[[patch]] kind="ot"`.

Format, as much of it as this needs::

    SingleObject27=C30       <- block header, class after the '='
    {
    m_oDefaultValue=C6       <- nested block; its fields are NOT this block's
    {
    u|u16Type=0
    }
    u|m_uMaxStackSize=0
    s|m_sLabel=Merlin DMG Zone
    i|m_eComputerType=3
    }

Field lines are ``<type>|<name>=<value>`` where the type letter is one of
`s` (string), `i` (int), `u` (unsigned), `f` (float), `b` (bool). The type
prefix is the file's, never the patch's: an edit REPLACES a value that is
already there, and refuses when the field does not exist in the matched block.
That is what keeps a typo from silently adding a field the engine ignores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: `<type>|<name>=<value>`. The name may contain dots and parens
#: (`f|a_rColor.m_fR=1`, `b|_GrabBoolValue()=0`), so it is matched lazily up to
#: the first `=`.
_FIELD_RE = re.compile(r"^(?P<prefix>[a-z])\|(?P<name>[^=]+)=(?P<value>.*)$")

#: Field name a selector defaults to. Every descriptor block in
#: ApplicationSettings.ot carries one and it is what a human calls the thing.
DEFAULT_SELECTOR = "m_sLabel"


class OtPatchError(ValueError):
    """A patch that cannot be applied to this file, with the reason."""


@dataclass(frozen=True)
class Edit:
    """One applied edit, for reporting. `old` is what the file said before."""
    selector: str
    field: str
    old: str
    new: str
    line: int          # 1-based, for a message that points at the file


def _block_of(lines: list[str]) -> list[int]:
    """Map each line index to the index of its enclosing block's `{`.

    -1 for a line at file level. Brace tracking is line-based because the
    format puts `{` and `}` on lines of their own; a line that is not exactly a
    brace never changes depth, so a value containing a brace cannot desync this.
    """
    owner: list[int] = []
    stack: list[int] = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == "{":
            # The brace itself belongs to the enclosing block, not to its own.
            owner.append(stack[-1] if stack else -1)
            stack.append(i)
            continue
        if s == "}":
            if stack:
                stack.pop()
            owner.append(stack[-1] if stack else -1)
            continue
        owner.append(stack[-1] if stack else -1)
    return owner


def _format(prefix: str, value) -> str:
    """Render `value` the way the file writes that type.

    Floats are `%.9g` because that is the precision the shipped file uses
    (`0.250000119`, `0.5`, `1`) — enough to round-trip a float32 and no trailing
    zeros.
    """
    if prefix in ("i", "u"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise OtPatchError(f"field type '{prefix}|' needs an integer, got {value!r}")
        if prefix == "u" and value < 0:
            raise OtPatchError(f"field type 'u|' is unsigned, got {value!r}")
        return str(value)
    if prefix == "b":
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, int) and value in (0, 1):
            return str(value)
        raise OtPatchError(f"field type 'b|' needs a boolean, got {value!r}")
    if prefix == "f":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise OtPatchError(f"field type 'f|' needs a number, got {value!r}")
        return f"{float(value):.9g}"
    if prefix == "s":
        text = str(value)
        if "\n" in text or "\r" in text:
            raise OtPatchError("a string value may not contain a newline")
        return text
    raise OtPatchError(f"unsupported field type {prefix!r}|")


def set_field(text: str, *, selector: str, field: str, value,
              selector_field: str = DEFAULT_SELECTOR) -> tuple[str, Edit]:
    """Set `field` inside the block whose `selector_field` equals `selector`.

    Returns the new text and the :class:`Edit` describing what changed. Raises
    :class:`OtPatchError` when the block is missing, ambiguous, or has no such
    field — never a silent no-op, because a patch that quietly does nothing is
    indistinguishable from one the game ignored.
    """
    lines = text.split("\n")
    owner = _block_of(lines)

    hits = [
        i for i, ln in enumerate(lines)
        if (m := _FIELD_RE.match(ln.strip()))
        and m.group("name") == selector_field
        and m.group("value") == selector
    ]
    if not hits:
        raise OtPatchError(
            f"no block with {selector_field}={selector!r}")
    if len(hits) > 1:
        raise OtPatchError(
            f"{selector_field}={selector!r} matches {len(hits)} blocks "
            f"(lines {', '.join(str(h + 1) for h in hits)}); "
            f"it must identify exactly one")

    block = owner[hits[0]]
    for i, ln in enumerate(lines):
        # Fields of a NESTED block belong to that block, not to this one —
        # `m_oDefaultValue`'s `u16Type` must never be mistaken for the
        # descriptor's own field.
        if owner[i] != block:
            continue
        m = _FIELD_RE.match(ln.strip())
        if not m or m.group("name") != field:
            continue
        prefix, old = m.group("prefix"), m.group("value")
        new = _format(prefix, value)
        indent = ln[: len(ln) - len(ln.lstrip())]
        lines[i] = f"{indent}{prefix}|{field}={new}"
        return "\n".join(lines), Edit(selector, field, old, new, i + 1)

    raise OtPatchError(
        f"block {selector_field}={selector!r} has no field {field!r} "
        f"(a patch may only change a field the file already has)")


def apply_edits(text: str, edits: list[dict]) -> tuple[str, list[Edit]]:
    """Apply `edits` in order. Each is a dict with `selector`, `field`,
    `value` and optionally `selector_field`."""
    done: list[Edit] = []
    for e in edits:
        text, ed = set_field(
            text,
            selector=str(e["selector"]),
            field=str(e["field"]),
            value=e["value"],
            selector_field=str(e.get("selector_field") or DEFAULT_SELECTOR),
        )
        done.append(ed)
    return text, done
