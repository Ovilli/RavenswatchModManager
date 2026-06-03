"""Variable-length editing of cooked entity files (the "re-emit cooker").

Cooked ``oCEntitySettingsResource`` files are a header + class table + a list of
BEGIN/END bracketed *sections*. The component-value tree is split arbitrarily
across sections (a node name can straddle a boundary), so all editing happens on
the **concatenation** of section payloads; on re-emit the concat is re-split by
the (adjusted) section lengths and the container is rebuilt.

Crucially, the container has **no per-block byte-size fields** that depend on
string content — only the section lengths, which we recompute. So a string can
be renamed to a different length and the file stays valid, as long as each
edit's length delta is added back to the section that contained it. This is the
same mechanism :mod:`rsmm.engine.cooked_schemas.entity_settings` uses to edit
``entity_path``; this module generalises it to arbitrary concat edits (renames,
value writes, ref swaps).

Typical use::

    ed = EntityEdit(cooked_bytes)
    ed.replace_lstring("Damage Value", "Attack Speed Value")   # variable length
    ed.set_value_before_end("Crit Chance Value", 0.15)          # length-preserving
    out = ed.emit()

All edits are queued against the *original* concat offsets and applied together
on :meth:`emit`, so queueing order does not matter (overlaps raise).
"""

from __future__ import annotations

import struct

from . import cooked

_END = b"\x22\x22\xbb\xaa"


class EntityEdit:
    """Mutable view of a cooked entity for variable-length edits."""

    def __init__(self, cooked_bytes: bytes) -> None:
        self._cf = cooked.parse(cooked_bytes)
        self._section_lens = [len(s.payload) for s in self._cf.sections]
        self.concat = b"".join(s.payload for s in self._cf.sections)
        # queued edits: (offset, old_len, replacement) on the original concat
        self._edits: list[tuple[int, int, bytes]] = []

    # -- low-level -----------------------------------------------------------

    def queue(self, offset: int, old_len: int, replacement: bytes) -> None:
        """Queue a raw byte edit on the original concat. ``old_len`` may differ
        from ``len(replacement)`` (that delta is absorbed on emit)."""
        if offset < 0 or offset + old_len > len(self.concat):
            raise ValueError(f"edit {offset}+{old_len} out of range")
        self._edits.append((offset, old_len, replacement))

    def find_lstrings(self, text: str) -> list[int]:
        """Offsets in the concat of every ``<u32 len><text>`` length-prefixed
        occurrence of ``text``."""
        pat = struct.pack("<I", len(text)) + text.encode("utf-8")
        out, i = [], 0
        while True:
            j = self.concat.find(pat, i)
            if j < 0:
                return out
            out.append(j)
            i = j + 1

    # -- high-level edits ----------------------------------------------------

    def replace_lstring(self, old: str, new: str, *, count: int | None = None) -> int:
        """Rename every length-prefixed ``old`` string to ``new`` (variable
        length). Returns how many were replaced; raises if none. ``count`` caps
        the number replaced."""
        offs = self.find_lstrings(old)
        if not offs:
            raise ValueError(f"lstring {old!r} not found")
        if count is not None:
            offs = offs[:count]
        repl = struct.pack("<I", len(new)) + new.encode("utf-8")
        for o in offs:
            self.queue(o, 4 + len(old.encode("utf-8")), repl)
        return len(offs)

    def set_value_before_end(self, label: str, new_value: float,
                             *, as_int: bool = False) -> None:
        """Length-preserving write of the f32/int32 value sitting just before
        the END marker of the node named ``label`` (the talent/entity value
        layout). For pure value edits prefer
        :func:`rsmm.engine.talent_values.set_talent_value`; this is here so a
        single :class:`EntityEdit` can mix value writes with renames."""
        pat = struct.pack("<I", len(label)) + label.encode("utf-8")
        o = self.concat.find(pat)
        if o < 0:
            raise ValueError(f"value label {label!r} not found")
        end = self.concat.find(_END, o + len(pat))
        if end < 0:
            raise ValueError(f"no END marker after {label!r}")
        packed = (struct.pack("<i", int(round(new_value))) if as_int
                  else struct.pack("<f", new_value))
        self.queue(end - 4, 4, packed)

    def swap_refs(self, off_a: int, off_b: int, size: int = 16) -> None:
        """Swap two equal-size fields (e.g. 16-byte GUID refs) in place."""
        a = self.concat[off_a:off_a + size]
        b = self.concat[off_b:off_b + size]
        self.queue(off_a, size, b)
        self.queue(off_b, size, a)

    # -- emit ----------------------------------------------------------------

    def emit(self) -> bytes:
        """Apply all queued edits and rebuild the cooked container, absorbing
        each edit's length delta into the section that contained it."""
        edits = sorted(self._edits)
        # validate non-overlapping
        for (o1, l1, _), (o2, _, _) in zip(edits, edits[1:], strict=False):
            if o1 + l1 > o2:
                raise ValueError(f"overlapping edits at {o1} and {o2}")

        starts, acc = [], 0
        for sl in self._section_lens:
            starts.append(acc)
            acc += sl
        deltas = [0] * len(self._section_lens)

        out = bytearray()
        cur = 0
        for off, old_len, rep in edits:
            out += self.concat[cur:off]
            out += rep
            cur = off + old_len
            sidx = max(i for i, s in enumerate(starts) if s <= off)
            deltas[sidx] += len(rep) - old_len
        out += self.concat[cur:]
        new_concat = bytes(out)

        new_lens = [sl + deltas[i] for i, sl in enumerate(self._section_lens)]
        assert sum(new_lens) == len(new_concat), "section length bookkeeping off"

        sections, o = [], 0
        for sl in new_lens:
            sections.append(cooked.Section(payload=new_concat[o:o + sl]))
            o += sl
        cf = cooked.CookedFile(
            variant=self._cf.variant, hdr_a=self._cf.hdr_a, flags=self._cf.flags,
            extra=self._cf.extra, type_tag=self._cf.type_tag,
            classes=self._cf.classes, sections=sections,
        )
        return cooked.emit(cf)
