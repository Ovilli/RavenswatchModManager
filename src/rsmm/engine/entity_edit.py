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

_BEGIN = b"\x11\x11\xbb\xaa"
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

    def find_lstrings_containing(self, substr: str) -> list[tuple[int, str]]:
        """Every length-prefixed string whose text *contains* ``substr``.

        Returns ``(offset, full_text)`` pairs (offset points at the u32 length
        prefix). Used to locate a component by a node-name fragment when the
        full cooked label carries a variable ``[State]/[Value Operation]/…``
        path prefix."""
        out: list[tuple[int, str]] = []
        needle = substr.encode("utf-8")
        i = 0
        c = self.concat
        n = len(c)
        while i + 4 <= n:
            ln = struct.unpack_from("<I", c, i)[0]
            if 0 < ln < 4096 and i + 4 + ln <= n:
                blob = c[i + 4:i + 4 + ln]
                if needle in blob:
                    try:
                        out.append((i, blob.decode("utf-8")))
                    except UnicodeDecodeError:
                        pass
            i += 1
        return out

    # -- high-level edits ----------------------------------------------------

    def _picker_classid(self) -> int | None:
        """Class-table index of ``oCEntityCpntPicker`` in THIS file.

        The u32 after a BEGIN marker indexes the file's own class table, so the
        picker is 0x42 in Red and Piper but 0x40 in Snow Queen. Hardcoding one
        of those rejects a perfectly good rewire on the other heroes.
        """
        names = [c.name for c in self._cf.classes]
        return (names.index("oCEntityCpntPicker")
                if "oCEntityCpntPicker" in names else None)

    def _node_guid(self, name: str) -> bytes | None:
        """Identity GUID of the one node DEFINED as ``name`` (its record opens
        with ``END, 16B GUID, lstr name``), or None when not exactly one."""
        hits = [o for o in self.find_lstrings(name)
                if o >= 20 and self.concat[o - 20:o - 16] == _END]
        return self.concat[hits[0] - 16:hits[0]] if len(hits) == 1 else None

    def _subtest_ranges(self, tester: str) -> list[tuple[int, int]]:
        """Concat ranges of every sub-test the tester node ``tester`` evaluates.

        A tester keeps its conditions out of line: an inline
        ``oCCombinerCpntTestSettings`` holds ``u8, u8 op, u32 n, n * u32``
        sub-object ids, and sub-object id ``i`` is section ``1 + i``. A sub-test
        that is itself a combiner (a section opening with that class index)
        contributes its own sub-tests, recursively. Raises rather than guessing
        when the tester or its combiner cannot be found.
        """
        names = [c.name for c in self._cf.classes]
        if "oCCombinerCpntTestSettings" not in names:
            raise ValueError("this file has no combiner test class")
        comb = names.index("oCCombinerCpntTestSettings")
        pat = struct.pack("<I", len(tester)) + tester.encode("utf-8")
        defs = [o for o in self.find_lstrings(tester)
                if o >= 20 and self.concat[o - 20:o - 16] == _END]
        if len(defs) != 1:
            raise ValueError(f"subtest_of: expected one node named {tester!r}, "
                             f"found {len(defs)}")
        bounds, lo = [], 0
        for n in self._section_lens:
            bounds.append((lo, lo + n))
            lo += n
        sec = next(i for i, (a, b) in enumerate(bounds) if a <= defs[0] < b)
        a, b = bounds[sec]
        payload = self.concat[a:b]
        at = payload.find(_BEGIN + struct.pack("<I", comb), defs[0] - a + len(pat))
        if at < 0:
            raise ValueError(f"subtest_of: {tester!r} has no combiner")

        def ids_at(buf: bytes, off: int) -> list[int]:
            n = struct.unpack_from("<I", buf, off + 2)[0]
            if n > 64 or off + 6 + 4 * n > len(buf):
                raise ValueError(f"subtest_of: {tester!r} combiner is not readable")
            return list(struct.unpack_from(f"<{n}I", buf, off + 6))

        out: list[tuple[int, int]] = []
        todo = ids_at(payload, at + 8)
        seen: set[int] = set()
        while todo:
            sid = todo.pop()
            if sid in seen or not 0 <= sid < len(bounds) - 2:
                continue
            seen.add(sid)
            a, b = bounds[1 + sid]
            body = self.concat[a:b]
            if struct.unpack_from("<I", body, 0)[0] == comb:
                todo += ids_at(body, 4)
            else:
                out.append((a, b))
        if not out:
            raise ValueError(f"subtest_of: {tester!r} evaluates no sub-tests")
        return out

    def rewire_ref(self, from_label: str, to_label: str,
                   *, expect_classid: int | None = None,
                   count: int | None = 1, exact: bool = False,
                   within: str | None = None, within_span: int = 2048,
                   subtest_of: str | None = None) -> int:
        """Repoint a component reference ("picker") at a different target node.

        Cross-references inside a cooked entity are 16-byte GUID handles, not
        string keys: a picker record is ``1111bbaa`` + ``u32 classid`` (66 =
        ``0x42`` for ``oCEntityCpntPicker``) + ``16B GUID`` + a redundant
        length-prefixed ``"[State] Path\\Name"`` label, so the GUID sits exactly
        16 bytes before its label. The target node is referenced elsewhere by
        the SAME GUID, so we read it from any picker that already points at
        ``to_label`` and write it into the picker that points at ``from_label``.
        Name-based and length-preserving — no hard-coded GUIDs or offsets, and
        it survives game updates that shift the file layout.

        Both labels are matched as substrings against the ``[State]`` picker
        labels (e.g. ``"Event Trait Ability Spawn Pets"``). ``expect_classid``
        guards the record's class; it defaults to whatever index
        ``oCEntityCpntPicker`` has in THIS file (0x42 in Red, 0x40 in Snow
        Queen). ``count`` limits how many matching references are repointed
        (``None`` = all — a tier-gated selector carries one per rarity).
        Returns the number rewritten.

        ``exact`` matches a whole label instead of a substring, and ``within``
        restricts the SOURCE side to references in the ``within_span`` bytes
        after the first node named ``within``. Both exist because substring
        matching once picked the wrong record: repointing a talent controller's
        ``[State] ...Skill Secondary Quick Bombs`` hit ``[Modifier] ...Skill
        Secondary Quick Bombs CD Reduction Modifier`` first, which contains the
        same text and sits earlier in the file.
        """
        want = expect_classid if expect_classid is not None else self._picker_classid()

        scope: list[tuple[int, int]] | None = None
        if within is not None:
            anchors = self.find_lstrings(within)
            if not anchors:
                raise ValueError(f"rewire scope {within!r} not found")
            scope = [(anchors[0], anchors[0] + within_span)]
        if subtest_of is not None:
            ranges = self._subtest_ranges(subtest_of)
            scope = ranges if scope is None else [
                (max(a, c), min(b, d)) for a, b in scope for c, d in ranges
                if max(a, c) < min(b, d)]

        def _picker_guid_offs(substr: str, scoped: bool = False) -> list[int]:
            hits = [(o, t) for (o, t) in self.find_lstrings_containing(substr)
                    if t.startswith("[")  # picker refs carry a [Type] prefix
                    and (not exact or t == substr)
                    and (not scoped or scope is None
                         or any(lo <= o < hi for lo, hi in scope))]
            if not hits:
                raise ValueError(f"no picker reference matching {substr!r}")
            offs = []
            for lstr_off, _t in hits:
                guid_off = lstr_off - 16
                if guid_off < 4:
                    continue
                classid = struct.unpack_from("<I", self.concat, guid_off - 4)[0]
                if want is not None and classid != want:
                    continue
                offs.append(guid_off)
            if not offs:
                raise ValueError(
                    f"picker {substr!r}: no reference record with classid "
                    f"{want:#x}" if want is not None else
                    f"picker {substr!r}: no reference record found")
            return offs

        # All refs to one node share its GUID, so any of the target's is fine.
        # A node nothing references yet (one added by `clone_nodes`) has no
        # such label, so fall back to its own definition: END, GUID, name.
        try:
            target_guid = self.concat[_picker_guid_offs(to_label)[0]:][:16]
        except ValueError:
            target_guid = self._node_guid(to_label.rsplit("\\", 1)[-1])
            if target_guid is None:
                raise
        dsts = _picker_guid_offs(from_label, scoped=True)
        if count is not None:
            dsts = dsts[:count]
        todo = [o for o in dsts if self.concat[o:o + 16] != target_guid]
        if not todo:
            raise ValueError(
                f"rewire {from_label!r} -> {to_label!r}: already points there")
        # A picker inside a value picker is read through an accessor that depends
        # on the target's class and value type (see entity_append's accessor
        # notes); repointing across either without updating it reads garbage.
        from . import entity_append as EA
        accessors = EA._Accessors(self._cf)
        for o in todo:
            self.queue(o, 16, target_guid)
            n = struct.unpack_from("<I", self.concat, o + 16)[0]
            label_end = o + 20 + n
            off = EA._accessor_off(self.concat, label_end, accessors.union)
            if off is None:
                continue
            try:
                old_label = self.concat[o + 20:label_end].decode("utf-8", "replace")
                fixed = EA.fix_accessor(self.concat, label_end, self.concat[o:o + 16],
                                        target_guid, accessors, old_label, to_label)
            except EA.EntityAppendError as e:
                raise ValueError(f"rewire {from_label!r} -> {to_label!r}: {e}") from e
            fixed = EA.fix_format_slot(fixed, o - 8, label_end, target_guid, accessors)
            if fixed[off:off + 16] != self.concat[off:off + 16]:
                self.queue(off, 16, fixed[off:off + 16])
            if fixed[off + 32:off + 36] != self.concat[off + 32:off + 36]:
                self.queue(off + 32, 4, fixed[off + 32:off + 36])
            entry = EA.format_slot_at(self.concat, o - 8, accessors)
            fmt = slice(entry + 8, entry + 12) if entry is not None else None
            if fmt is not None and fixed[fmt] != self.concat[fmt]:
                self.queue(entry + 8, 4, fixed[fmt])
        return len(todo)

    def set_int_before_nth_end(self, label: str, end_index: int, new: int,
                               *, expect: int | None = None) -> int:
        """Length-preserving write of the int32 sitting just before the
        ``end_index``-th END marker (0-based) after the node named ``label``.

        Selector / value-union entries (``oCEntityCpntValueUnionSettings``
        type=1) store one int32 each immediately before their END marker, so a
        node holding several tiers exposes them as successive END markers. The
        flat ``set_value_before_end`` only reaches the first; this targets a
        specific entry by its END ordinal (discover ordinals with the entity
        decode). Returns the concat offset written. ``expect`` asserts the
        current value so a drifted layout fails loudly instead of corrupting a
        neighbour."""
        pat = struct.pack("<I", len(label)) + label.encode("utf-8")
        base = self.concat.find(pat)
        if base < 0:
            raise ValueError(f"node label {label!r} not found")
        o = base + len(pat)
        end = -1
        for _ in range(end_index + 1):
            end = self.concat.find(_END, o)
            if end < 0:
                raise ValueError(
                    f"{label!r}: fewer than {end_index + 1} END markers")
            o = end + 4
        cur = struct.unpack_from("<i", self.concat, end - 4)[0]
        if expect is not None and cur != expect:
            raise ValueError(
                f"{label!r} END#{end_index}: expected int {expect}, found {cur} "
                f"(at {end - 4:#x}) — layout drifted")
        self.queue(end - 4, 4, struct.pack("<i", int(new)))
        return end - 4


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
