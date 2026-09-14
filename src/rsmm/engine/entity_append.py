"""Additive component append for cooked entity-settings files.

Cooked entity layout (see ``cooked.py`` for the container grammar):

* section 0 = component directory: ``u32 count`` + ``count`` u32 class-table
  indexes, one per component;
* sections 1..count = one self-framed component record each, starting with
  its class-table index (record i's first u32 == directory entry i);
* last section = the ``oCEntitySettings`` object itself, whose first field
  after its class index is a **poly-pointer vector**: ``u32 count`` followed by
  ``count`` u32 SUB-OBJECT IDS. That vector, not section 0, is the entity's
  component list.

Because every record is self-framed and the deserializer walks the directory
sequentially, NEW components can be appended: add the class index to the
directory, bump the count, insert the record before the trailer -- **and add
the new sub-object id to the trailer's component vector**. This is the
entity-file analog of the versiondef MO-vector append proven for custom items
(see docs/_re/kinds/ui-menus.md, phase 4).

⚠ That last step is the whole difference between an appended component and an
INERT one, and leaving it out cost this repo seven playtests of a stock-looking
mod menu and four of a POI with no icon and no prompt. Section 0 is the
serializer's OBJECT TABLE: a record listed there is deserialized, but an object
nothing points at is owned by nobody and never reaches the entity.
``data/symbols.json::Serializer_ReadPolyPtrVector`` states the encoding --
"in cooked files, sub-objects live in their own sections referenced by u32
sub-object id". Measured: all 4699 shipped entities carry the vector and it is
always a contiguous ``0..n-1`` prefix of the component list.

Component records carry a 16-byte instance GUID right after their first inner
``END`` marker; clones must remint it (unique within the file) or the engine
sees two components with one identity.
"""

from __future__ import annotations

import hashlib
import os
import struct

from . import cooked

_END = cooked.MARK_END


class EntityAppendError(ValueError):
    pass


def _directory(cf: cooked.CookedFile) -> tuple[int, list[int]]:
    pl = cf.sections[0].payload
    if len(pl) < 4:
        raise EntityAppendError("section 0 too small to be a component directory")
    count = struct.unpack_from("<I", pl, 0)[0]
    if len(pl) < 4 + 4 * count:
        raise EntityAppendError("component directory shorter than its count")
    idxs = list(struct.unpack_from(f"<{count}I", pl, 4))
    return count, idxs


def component_vector(trailer: bytes) -> tuple[int, list[int]]:
    """``(offset, ids)`` of the entity's component vector in its trailer.

    ``trailer[offset:]`` starts at the vector's ``u32 count``. The ids are
    sub-object ids, i.e. component indexes: id ``i`` is ``cf.sections[1 + i]``.

    Layout from the trailer's nested BEGIN::

        u32 class index
        u32 count, count * u32      <-- the vector

    Raises rather than guessing: an append that cannot find this vector would
    otherwise succeed and produce a file whose new components do nothing.
    """
    i = trailer.find(cooked.MARK_BEGIN)
    if i < 0:
        raise EntityAppendError("entity trailer has no nested BEGIN")
    o = i + 4 + 4                                    # BEGIN, class index
    if o + 4 > len(trailer):
        raise EntityAppendError("entity trailer ends before its component vector")
    (count,) = struct.unpack_from("<I", trailer, o)
    if o + 4 + 4 * count > len(trailer):
        raise EntityAppendError(
            f"component vector claims {count} entries, which runs past the "
            f"trailer — the walk landed in the wrong place")
    return o, list(struct.unpack_from(f"<{count}I", trailer, o + 4))


def _render_vector(offset: int, trailer: bytes, ids: list[int]) -> bytes:
    """`trailer` with its component vector replaced by `ids`."""
    _o, old = component_vector(trailer)
    tail = trailer[offset + 4 + 4 * len(old):]
    return (trailer[:offset] + struct.pack("<I", len(ids))
            + struct.pack(f"<{len(ids)}I", *ids) + tail)


def validate_layout(cf: cooked.CookedFile) -> int:
    """Sanity-check directory↔record correspondence; return component count."""
    count, idxs = _directory(cf)
    # directory + records + trailer
    if len(cf.sections) != count + 2:
        raise EntityAppendError(
            f"expected {count + 2} sections for {count} components, "
            f"got {len(cf.sections)}")
    for i, want in enumerate(idxs):
        got = struct.unpack_from("<I", cf.sections[1 + i].payload, 0)[0]
        if got != want:
            raise EntityAppendError(
                f"component {i}: directory says class {want}, record says {got}")
    # The vector is what the entity actually reads. A record present in the
    # object table but absent from it is an ORPHAN: it deserializes, it is
    # byte-stable, and it does nothing.
    _off, ids = component_vector(cf.sections[-1].payload)
    stray = [i for i in ids if not 0 <= i < count]
    if stray:
        raise EntityAppendError(
            f"component vector names sub-object(s) {stray} outside the "
            f"{count} components in the file")
    return count


def find_component(cf: cooked.CookedFile, name: bytes,
                   class_idx: int | None = None) -> int:
    """Section index of the unique component record containing ``name``."""
    hits = []
    for i, sec in enumerate(cf.sections[1:-1], start=1):
        if name not in sec.payload:
            continue
        if class_idx is not None and \
                struct.unpack_from("<I", sec.payload, 0)[0] != class_idx:
            continue
        hits.append(i)
    if len(hits) != 1:
        raise EntityAppendError(
            f"expected exactly one component containing {name!r}"
            + (f" with class {class_idx}" if class_idx is not None else "")
            + f", found {len(hits)}")
    return hits[0]


def replace_blob_strings(blob: bytes, swaps: dict[str, str]) -> bytes:
    """Whole-string replacement of u32-length-prefixed strings inside one
    component record (same lstr surgery as ``entity_strings`` but without the
    outer file container)."""
    out = blob
    for old, new in swaps.items():
        if not new.isascii():
            raise EntityAppendError(f"replacement must be ASCII: {new!r}")
        needle = struct.pack("<I", len(old)) + old.encode("ascii")
        if out.count(needle) == 0:
            raise EntityAppendError(f"string not present in record: {old!r}")
        repl = struct.pack("<I", len(new)) + new.encode("ascii")
        out = out.replace(needle, repl)
    return out


def remint_guid(blob: bytes) -> bytes:
    """Replace the record's 16-byte instance GUID (right after the first
    inner END marker) with fresh random bytes."""
    pos = blob.find(_END)
    if pos < 0 or pos + 4 + 16 > len(blob):
        raise EntityAppendError("no inner END marker — not a component record?")
    g = pos + 4
    return blob[:g] + os.urandom(16) + blob[g + 16:]


def _lstr(text: str) -> bytes:
    return struct.pack("<I", len(text)) + text.encode("ascii")


def _header_name_at(payload: bytes) -> int | None:
    """Offset of a component record's own name lstr, or None.

    A named component opens ``u32 class, BEGIN, u32, 16B, END, 16B GUID,
    lstr name`` -- the GUID right after the first inner END is the node's
    identity (what every picker that targets it stores), and the name follows.
    """
    pos = payload.find(_END)
    if pos < 0:
        return None
    at = pos + 4 + 16
    return at if at + 4 <= len(payload) else None


def node_section(cf: cooked.CookedFile, name: str) -> int:
    """Section index of the component whose OWN name is exactly ``name``.

    Unlike :func:`find_component` this ignores records that merely mention the
    name in a reference label, so a node is found even when other components
    point at it.
    """
    want = _lstr(name)
    hits = []
    for i, sec in enumerate(cf.sections[1:-1], start=1):
        at = _header_name_at(sec.payload)
        if at is not None and sec.payload[at:at + len(want)] == want:
            hits.append(i)
    if len(hits) != 1:
        raise EntityAppendError(
            f"expected exactly one component named {name!r}, found {len(hits)}")
    return hits[0]


def node_guid(cf: cooked.CookedFile, name: str) -> bytes:
    """The 16-byte identity of the component named ``name``."""
    payload = cf.sections[node_section(cf, name)].payload
    at = _header_name_at(payload)
    return payload[at - 16:at]


# -- picker accessors ---------------------------------------------------------
#
# A picker that sits inside an `oCEntityCpntValuePicker` is followed, after its
# label's END, by a 4-byte ACCESSOR and then the value's `oCEntityValueUnion`:
#
#     BEGIN picker, 16B GUID, lstr label, END, u32 accessor, BEGIN union, u32 type, ...
#
# The accessor is the method the engine calls on the target to read a value,
# and it depends on the target's COMPONENT CLASS and VALUE TYPE: a value or
# value selector is read with 0x0fd2c964 + type (f32 64c9d20f, int 65c9d20f,
# vector 67c9d20f, string 69c9d20f), a value operation with 8586d20f / 8686d20f,
# a state with 2a83d20f, a tester with af053b10, and a skill controller with a
# different accessor per rarity tier (f96bfc15 / f16bfc15 / f76bfc15). Measured
# over every value picker in Hero_Piper.
#
# Repointing such a picker at a node of another class, or of another value type,
# while keeping the old accessor makes the engine read the new target with the
# wrong method. It does not fail: it returns garbage. That is what made a cloned
# count switch spawn ~22 rats at once and a talent card print "every 0 notes".
# A picker with NO accessor (a state's child list, an event's actions) is a
# plain link and is left alone.

def _accessor_off(buf: bytes, label_end: int, union_idx: int) -> int | None:
    """Offset of the accessor following a picker label ending at ``label_end``,
    or None when the picker is not inside a value picker."""
    if (buf[label_end:label_end + 4] == _END
            and buf[label_end + 8:label_end + 12] == cooked.MARK_BEGIN
            and label_end + 20 <= len(buf)
            and struct.unpack_from("<I", buf, label_end + 12)[0] == union_idx):
        return label_end + 4
    return None


class _Accessors:
    """What accessor and value type each target is read with, learned from the
    file's own value pickers."""

    def __init__(self, cf: cooked.CookedFile) -> None:
        from collections import Counter

        names = [c.name for c in cf.classes]
        self._cf = cf
        self._names = names
        # A file with no value unions has no accessors to learn or fix: -1
        # never matches a class index, so every picker reads as a plain link.
        self.picker = names.index("oCEntityCpntPicker") if "oCEntityCpntPicker" in names else -1
        self.union = names.index("oCEntityValueUnion") if "oCEntityValueUnion" in names else -1
        self.cls_of: dict[bytes, str] = {}
        self._section_of: dict[bytes, int] = {}
        self.by_target: dict[bytes, Counter] = {}
        self.by_class: dict[str, Counter] = {}
        self.format_entry = (names.index("oCStringFormatEntryPicker")
                             if "oCStringFormatEntryPicker" in names else -1)
        self.value_picker = (names.index("oCEntityCpntValuePicker")
                             if "oCEntityCpntValuePicker" in names else -1)
        #: display option of every String Format slot that reads a target
        self.slot_option: dict[bytes, Counter] = {}
        if self.picker < 0 or self.union < 0:
            return
        for i, sec in enumerate(cf.sections[1:-1], start=1):
            at = _header_name_at(sec.payload)
            if at is not None and len(sec.payload) >= 4:
                g = sec.payload[at - 16:at]
                self.cls_of[g] = names[struct.unpack_from("<I", sec.payload, 0)[0]] \
                    if struct.unpack_from("<I", sec.payload, 0)[0] < len(names) else "?"
                self._section_of[g] = i
        pat = cooked.MARK_BEGIN + struct.pack("<I", self.picker)
        for sec in cf.sections:
            p = sec.payload
            i = p.find(pat)
            while i != -1:
                if i + 28 <= len(p):
                    g = p[i + 8:i + 24]
                    n = struct.unpack_from("<I", p, i + 24)[0]
                    acc = _accessor_off(p, i + 28 + n, self.union) if n < 4096 else None
                    if acc is not None and g != bytes(16):
                        pair = (p[acc:acc + 4], struct.unpack_from("<I", p, acc + 12)[0])
                        # Record every target, including nodes inherited from a
                        # parent entity, which have no record in this file but
                        # are read here all the same.
                        self.by_target.setdefault(g, Counter())[pair] += 1
                        if g in self.cls_of:
                            self.by_class.setdefault(self.cls_of[g], Counter())[pair] += 1
                        if format_slot_at(p, i, self) is not None:
                            opt = struct.unpack_from("<I", p, acc + 32)[0]
                            self.slot_option.setdefault(g, Counter())[opt] += 1
                i = p.find(pat, i + 1)

    def value_type(self, guid: bytes) -> int | None:
        """The numeric type a value node holds: the most common non-bool union
        type in its own record (a selector's per-tier values, a value's number)."""
        from collections import Counter

        k = self._section_of.get(guid)
        if k is None:
            return None
        p = self._cf.sections[k].payload
        pat = cooked.MARK_BEGIN + struct.pack("<I", self.union)
        seen: Counter = Counter()
        i = p.find(pat)
        while i != -1:
            if i + 12 <= len(p):
                seen[struct.unpack_from("<I", p, i + 8)[0]] += 1
            i = p.find(pat, i + 1)
        numeric = [(n, t) for t, n in seen.items() if t != 2]
        return max(numeric)[1] if numeric else (2 if seen else None)

    def resolve(self, guid: bytes) -> tuple[bytes, int]:
        """(accessor, type) to read ``guid`` with, or raise."""
        if guid in self.by_target:
            return self.by_target[guid].most_common(1)[0][0]
        cls = self.cls_of.get(guid)
        pairs = self.by_class.get(cls)
        if not pairs:
            raise EntityAppendError(
                f"no value picker in this file reads a {cls} — cannot choose "
                f"an accessor for it")
        types = {t for _acc, t in pairs}
        if len(types) > 1:
            want = self.value_type(guid)
            pairs = {pt: n for pt, n in pairs.items() if pt[1] == want}
            if not pairs:
                raise EntityAppendError(
                    f"no value picker in this file reads a {cls} of type {want}")
            return max(pairs.items(), key=lambda kv: kv[1])[0]
        return pairs.most_common(1)[0][0]


def format_slot_at(buf: bytes, picker_begin: int, acc: _Accessors) -> int | None:
    """Offset of the `oCStringFormatEntryPicker` a picker is the value of, or None.

    A talent card's slot is ``BEGIN entry, u32 class, u32 FORMAT TYPE, BEGIN
    value picker, u32 class, u16 flags, BEGIN picker ...`` and, after the value
    union, ``END, END, u32 DISPLAY OPTION, END``. The format type is how the
    number is printed (0 decimal, 1 integer, 5 text) and is independent of the
    value's own type: an integer printed through a decimal slot came out as
    6.7263e-44 on a card. The display option varies with what the slot shows
    (flat counts, percents, damage) and is left to the slots that already show
    a value.
    """
    if acc.format_entry < 0 or acc.value_picker < 0 or picker_begin < 22:
        return None
    at = picker_begin - 22
    if (buf[at:at + 4] == cooked.MARK_BEGIN
            and struct.unpack_from("<I", buf, at + 4)[0] == acc.format_entry
            and buf[at + 12:at + 16] == cooked.MARK_BEGIN
            and struct.unpack_from("<I", buf, at + 16)[0] == acc.value_picker):
        return at
    return None


def fix_format_slot(buf: bytes, picker_begin: int, label_end: int, new_target: bytes,
                    acc: _Accessors) -> bytes:
    """If the repointed picker is a talent-card slot, give the slot the format
    type of the value it now reads, and the display option a shipped slot uses
    for that same value (kept as-is when no shipped slot shows it)."""
    entry = format_slot_at(buf, picker_begin, acc)
    off = _accessor_off(buf, label_end, acc.union)
    if entry is None or off is None:
        return buf
    vtype = struct.unpack_from("<I", buf, off + 12)[0]
    if vtype not in (0, 1):
        return buf
    out = buf[:entry + 8] + struct.pack("<I", vtype) + buf[entry + 12:]
    opts = acc.slot_option.get(new_target)
    if opts:
        out = (out[:off + 32] + struct.pack("<I", opts.most_common(1)[0][0])
               + out[off + 36:])
    return out


def _label_kind(label: str | None) -> str | None:
    """The ``[Type]`` prefix every reference label carries, e.g. ``[State]``."""
    if label and label.startswith("[") and "]" in label:
        return label[:label.index("]") + 1]
    return None


def fix_accessor(buf: bytes, label_end: int, old_target: bytes, new_target: bytes,
                 acc: _Accessors, old_label: str | None = None,
                 new_label: str | None = None) -> bytes:
    """``buf`` with the accessor after a repointed picker made right for its new
    target. Unchanged when the picker has no accessor, or when the target keeps
    both its kind and its value type (the accessor may encode a method, such
    as a skill controller's per-tier check, that must survive).

    Kind is the target's component class when both records are in this file;
    for a node inherited from a parent entity, which has no record here, it is
    the ``[Type]`` prefix of the reference labels."""
    off = _accessor_off(buf, label_end, acc.union)
    if off is None:
        return buf
    cur_type = struct.unpack_from("<I", buf, off + 12)[0]
    old_cls, new_cls = acc.cls_of.get(old_target), acc.cls_of.get(new_target)
    if old_cls is not None and new_cls is not None:
        same_kind = old_cls == new_cls
    else:
        same_kind = (_label_kind(old_label) is not None
                     and _label_kind(old_label) == _label_kind(new_label))
    if same_kind:
        new_type = acc.value_type(new_target)
        if new_type is None or new_type == acc.value_type(old_target):
            return buf
    accessor, vtype = acc.resolve(new_target)
    # union layout from `off`: accessor, BEGIN, class, type, sub-type, value
    if vtype != cur_type and buf[off + 20:off + 24] != bytes(4):
        # A sourced picker's inline number is dead, but refuse to reinterpret a
        # non-zero one rather than silently change what it would mean.
        raise EntityAppendError("repointed picker carries a non-zero inline value "
                                "of a different type")
    return (buf[:off] + accessor + buf[off + 4:off + 12]
            + struct.pack("<I", vtype) + buf[off + 16:])


# -- sub-objects a copied record owns ------------------------------------------
#
# Some records own objects stored as their own sections and referenced by u32
# sub-object id (see the module docstring). Across 529 shipped files no two
# references ever share one sub-object, so a copy must get its own. The two
# carriers handled here are the ones talent wiring copies: a collector
# (`oCEntityCollectorSelectorSettings`: u32 count, ids — e.g. the
# `oCSelfEntityCollectorSettings` a modifier or event sender targets) and a
# combiner test (`oCCombinerCpntTestSettings`: u8, u8 op, u32 count, ids).
# Animation keys, effect setups and spawner retrievers use other carriers and
# are NOT duplicated; do not clone records that hold those.

_CARRIERS = {"oCEntityCollectorSelectorSettings": 0, "oCCombinerCpntTestSettings": 2}


def _carrier_refs(buf: bytes, names: list[str], owned: set[int],
                  standalone: bool = False) -> list[int]:
    """Offsets of every sub-object id inside ``buf`` held by a known carrier.

    Only ids naming a sub-object (``owned``: records that are not components)
    count, which keeps a stray byte pattern from being read as a reference."""
    offs: list[int] = []
    for cls, skip in _CARRIERS.items():
        if cls not in names:
            continue
        ci = names.index(cls)
        starts = []
        if standalone and len(buf) >= 4 and struct.unpack_from("<I", buf, 0)[0] == ci:
            starts.append(4 + skip)
        pat = cooked.MARK_BEGIN + struct.pack("<I", ci)
        i = buf.find(pat)
        while i != -1:
            starts.append(i + 8 + skip)
            i = buf.find(pat, i + 1)
        for o in starts:
            if o + 4 > len(buf):
                continue
            n = struct.unpack_from("<I", buf, o)[0]
            if not 0 < n <= 64 or o + 4 + 4 * n > len(buf):
                continue
            ids = struct.unpack_from(f"<{n}I", buf, o + 4)
            if all(x in owned for x in ids):
                offs.extend(o + 4 + 4 * k for k in range(n))
    return offs


def _copy_subobjects(blob: bytes, cf: cooked.CookedFile,
                     first_new_id: int) -> tuple[bytes, list[bytes]]:
    """``blob`` with every owned sub-object replaced by a fresh copy, plus the
    copies in id order (``first_new_id``, ``first_new_id + 1``, ...)."""
    names = [c.name for c in cf.classes]
    count, _ = _directory(cf)
    _o, vector = component_vector(cf.sections[-1].payload)
    owned = set(range(count)) - set(vector)
    copies: list[bytes] = []

    def rewrite(buf: bytes, standalone: bool) -> bytes:
        for off in _carrier_refs(buf, names, owned, standalone):
            old = struct.unpack_from("<I", buf, off)[0]
            body = rewrite(cf.sections[1 + old].payload, True)
            new = first_new_id + len(copies)
            copies.append(body)
            buf = buf[:off] + struct.pack("<I", new) + buf[off + 4:]
        return buf

    return rewrite(blob, False), copies


def modifier_stat_off(payload: bytes, names: list[str]) -> int:
    """Offset of a modifier record's 4-byte STAT key.

    `oCEntityCpntModifierSettings` opens ``name, u32 flag, lstr folder, 7
    bytes, u32 stat, BEGIN ...`` (all 496 shipped modifiers). The stat is the
    enum the engine modifies: 845db415 POWER cooldown, 865db415 SPECIAL,
    885db415 DEFENSE, 8a5db415 TRAIT cooldown, and so on."""
    if names[struct.unpack_from("<I", payload, 0)[0]] != "oCEntityCpntModifierSettings":
        raise EntityAppendError("not a modifier record")
    at = _header_name_at(payload)
    n = struct.unpack_from("<I", payload, at)[0]
    folder = at + 4 + n + 4
    m = struct.unpack_from("<I", payload, folder)[0]
    off = folder + 4 + m + 7
    if payload[off + 4:off + 8] != cooked.MARK_BEGIN:
        raise EntityAppendError("modifier record does not have the expected layout")
    return off


def modifier_stat(cooked_bytes: bytes, node: str) -> bytes:
    """The stat key of the modifier named ``node`` in a cooked entity."""
    cf = cooked.parse(cooked_bytes)
    payload = cf.sections[node_section(cf, node)].payload
    off = modifier_stat_off(payload, [c.name for c in cf.classes])
    return payload[off:off + 4]


def clone_component(cooked_bytes: bytes, source: str, name: str,
                    retarget: list[tuple[str, str]] | None = None,
                    rename: list[tuple[str, str]] | None = None,
                    stat: bytes | None = None) -> bytes:
    """Append a copy of the component ``source`` under the new name ``name``.

    The copy gets a new identity GUID, derived from ``name`` so re-emitting a
    mod produces the same bytes. Each ``(old_label, new_label)`` in
    ``retarget`` repoints one reference inside the copy: the picker whose
    label is exactly ``old_label`` gets the GUID of the node named by the last
    path segment of ``new_label``, and its label is rewritten to match. Every
    reference carrying ``old_label`` moves: a per-rarity selector names the
    same controller once per tier.

    Each ``(old, new)`` in ``rename`` then replaces a whole string inside the
    copy -- how a counter or named-event sender gets an event name of its own
    instead of sharing the source's (a counter listens by name, so a copy that
    kept the name would count the source's events too).

    ``stat`` (4 bytes, see :func:`modifier_stat`) makes a copied modifier change
    a different stat. Sub-objects the copy owns through a collector or combiner
    are copied as well, so the copy never shares one with its source.

    The copy is attached through :func:`append_components`, so it lands in the
    entity's component vector rather than as an orphan. Nothing points at it
    yet -- repoint an existing reference at ``name`` to use it.
    """
    cf = cooked.parse(cooked_bytes)
    validate_layout(cf)
    try:
        node_section(cf, name)
    except EntityAppendError:
        pass
    else:
        raise EntityAppendError(f"a component named {name!r} already exists")

    src = cf.sections[node_section(cf, source)].payload
    at = _header_name_at(src)
    old_name = _lstr(source)
    blob = src[:at] + _lstr(name) + src[at + len(old_name):]

    guid = hashlib.sha256(f"rsmm-clone:{name}".encode("ascii")).digest()[:16]
    if any(guid in sec.payload for sec in cf.sections):
        raise EntityAppendError(f"derived GUID for {name!r} collides in this file")
    blob = blob[:at - 16] + guid + blob[at:]

    accessors = _Accessors(cf) if retarget else None
    for old_label, new_label in retarget or []:
        needle = _lstr(old_label)
        if needle not in blob:
            raise EntityAppendError(
                f"clone of {source!r}: no reference labelled {old_label!r}")
        target = node_guid(cf, new_label.rsplit("\\", 1)[-1])
        i = blob.find(needle)
        while i != -1:
            # A picker reference is BEGIN, u32 class, 16B GUID, then the label.
            if i < 24 or blob[i - 24:i - 20] != cooked.MARK_BEGIN:
                raise EntityAppendError(
                    f"clone of {source!r}: {old_label!r} is not a picker reference")
            old_target = blob[i - 16:i]
            repl = target + _lstr(new_label)
            blob = blob[:i - 16] + repl + blob[i + len(needle):]
            try:
                blob = fix_accessor(blob, i + 4 + len(new_label), old_target,
                                    target, accessors, old_label, new_label)
                blob = fix_format_slot(blob, i - 24, i + 4 + len(new_label),
                                       target, accessors)
            except EntityAppendError as e:
                raise EntityAppendError(
                    f"clone of {source!r}: {old_label!r} -> {new_label!r}: {e}") from e
            i = blob.find(needle, i - 16 + len(repl))

    if rename:
        blob = replace_blob_strings(blob, dict(rename))

    if stat is not None:
        if len(stat) != 4:
            raise EntityAppendError("stat must be 4 bytes")
        off = modifier_stat_off(blob, [c.name for c in cf.classes])
        blob = blob[:off] + stat + blob[off + 4:]

    count, _ = _directory(cf)
    blob, subs = _copy_subobjects(blob, cf, count + 1)
    return append_components(cooked_bytes, [blob, *subs], [True] + [False] * len(subs))


def append_components(cooked_bytes: bytes,
                      records: list[bytes],
                      attach: list[bool] | None = None) -> bytes:
    """Append component records to a cooked entity, returning new bytes.

    Each record must already start with its class-table index u32 (clones of
    existing records keep theirs).

    The new sub-object ids are also appended to the trailer's component vector,
    which is what attaches them to the entity. Without that the records are
    orphans -- see the module docstring. ``attach`` (one flag per record,
    default all True) leaves a record OUT of that vector: a sub-object owned by
    another record through its own id reference is not a component of the
    entity, and listing it there would make it one.
    """
    cf = cooked.parse(cooked_bytes)
    count = validate_layout(cf)
    _, idxs = _directory(cf)
    for rec in records:
        cls = struct.unpack_from("<I", rec, 0)[0]
        if cls >= len(cf.classes):
            raise EntityAppendError(f"record class index {cls} out of range")
        idxs.append(cls)
    new_dir = struct.pack("<I", len(idxs)) + struct.pack(f"<{len(idxs)}I", *idxs)
    tail = cf.sections[0].payload[4 + 4 * count:]
    cf.sections[0].payload = new_dir + tail
    trailer = cf.sections.pop()
    for rec in records:
        cf.sections.append(cooked.Section(payload=rec))
    # Sub-object id of record k is its component index: the records land at
    # component indexes `count`..`count + len(records) - 1`.
    off, ids = component_vector(trailer.payload)
    flags = attach if attach is not None else [True] * len(records)
    if len(flags) != len(records):
        raise EntityAppendError("attach needs one flag per record")
    new_ids = [count + k for k, keep in enumerate(flags) if keep]
    trailer.payload = _render_vector(off, trailer.payload, ids + new_ids)
    cf.sections.append(trailer)
    out = cooked.emit(cf)
    # Re-walk what we just wrote: the only cheap proof the vector stayed framed.
    validate_layout(cooked.parse(out))
    return out
