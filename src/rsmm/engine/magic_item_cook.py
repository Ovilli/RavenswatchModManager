"""Clone a vanilla magical-object cooked entity into a new, distinct item.

This is the conservative first item "cooker": it performs **length-preserving**
byte edits only. Every replacement keeps the original byte length, so the
cooked container framing (BEGIN/END markers, per-section lengths) is untouched
and the result is guaranteed byte-compatible with what the engine already
accepts. Variable-length field edits (which require re-emitting the container
and have unproven engine tolerance) are intentionally out of scope here.

Supported edits:
  * :func:`rename_id` — rename the item id across every internal scoped node
    name (``[Value] <id>\\...``) and text-bank key (``<id>_Name`` ...), so the
    clone is a fully independent resource that won't collide with the base.
  * :func:`replace_lstr` — repoint a length-prefixed string (icon path, debug
    name, text key) to an equal-length replacement, anchored on its ``<u32
    len><bytes>`` prefix so it can't hit an unrelated substring.

The id of a magical object is the entity filename stem (e.g. ``Armor_Per_Object``)
and appears verbatim inside the cooked bytes wherever the engine scopes a node
or text key to that item. A plain byte replace of the id token therefore renames
every reference at once — valid precisely because we require equal length.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field


def _require_same_len(old: bytes, new: bytes, what: str) -> None:
    if len(old) != len(new):
        raise ValueError(
            f"{what}: replacement must keep byte length "
            f"({old!r}={len(old)}B vs {new!r}={len(new)}B). The length-preserving "
            f"cooker cannot change framing; pad/trim the value or add a "
            f"variable-length cooker."
        )


def rename_id(data: bytes, base_id: str, new_id: str) -> bytes:
    """Rename the item id everywhere it appears in the cooked bytes.

    ``new_id`` must equal ``base_id`` in byte length. Renames internal scoped
    node names and text-bank keys in one pass (they all embed the id token).
    """
    ob, nb = base_id.encode("utf-8"), new_id.encode("utf-8")
    _require_same_len(ob, nb, "item id")
    if ob not in data:
        raise ValueError(f"item id {base_id!r} not found in cooked bytes")
    return data.replace(ob, nb)


def replace_lstr(data: bytes, old: str, new: str, *, what: str = "string") -> bytes:
    """Replace a length-prefixed string ``<u32 len><bytes>`` in place.

    Anchored on the 4-byte little-endian length prefix so it matches a real
    cooked string slot, not an incidental substring. Length-preserving.
    """
    ob, nb = old.encode("utf-8"), new.encode("utf-8")
    _require_same_len(ob, nb, what)
    pat = struct.pack("<I", len(ob)) + ob
    rep = struct.pack("<I", len(nb)) + nb
    if pat not in data:
        raise ValueError(f"{what}: {old!r} not found as a length-prefixed string")
    return data.replace(pat, rep)


def find_lstrings(data: bytes, *, contains: str | None = None,
                  min_len: int = 3, max_len: int = 256) -> list[tuple[int, str]]:
    """Heuristically list length-prefixed printable strings in cooked bytes.

    For inspection/authoring only (e.g. discovering the icon path or debug
    name to repoint). Returns ``(offset_of_prefix, text)``. A slot qualifies
    when the u32 length is in ``[min_len, max_len]`` and the bytes are all
    printable ASCII. False positives are possible; verify before editing.
    """
    out: list[tuple[int, str]] = []
    n = len(data)
    i = 0
    while i + 4 <= n:
        ln = struct.unpack_from("<I", data, i)[0]
        if min_len <= ln <= max_len and i + 4 + ln <= n:
            chunk = data[i + 4: i + 4 + ln]
            if all(0x20 <= b < 0x7f for b in chunk):
                text = chunk.decode("ascii")
                if contains is None or contains in text:
                    out.append((i, text))
                i += 4 + ln
                continue
        i += 1
    return out


@dataclass
class ItemEdit:
    """Declarative length-preserving edit set for one cloned item."""
    base_id: str
    new_id: str
    #: (old_lstr, new_lstr) pairs — icon path, debug name, etc.
    lstr_swaps: list[tuple[str, str]] = field(default_factory=list)

    def apply(self, cooked: bytes) -> bytes:
        out = rename_id(cooked, self.base_id, self.new_id)
        for old, new in self.lstr_swaps:
            # The id rename may already have rewritten the id token inside
            # these strings; rename both sides so the swap still matches.
            old2 = old.replace(self.base_id, self.new_id)
            new2 = new.replace(self.base_id, self.new_id)
            out = replace_lstr(out, old2, new2, what="lstr swap")
        return out
