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


def append_components(cooked_bytes: bytes,
                      records: list[bytes]) -> bytes:
    """Append component records to a cooked entity, returning new bytes.

    Each record must already start with its class-table index u32 (clones of
    existing records keep theirs).

    The new sub-object ids are also appended to the trailer's component vector,
    which is what attaches them to the entity. Without that the records are
    orphans -- see the module docstring.
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
    trailer.payload = _render_vector(
        off, trailer.payload, ids + list(range(count, count + len(records))))
    cf.sections.append(trailer)
    out = cooked.emit(cf)
    # Re-walk what we just wrote: the only cheap proof the vector stayed framed.
    validate_layout(cooked.parse(out))
    return out
