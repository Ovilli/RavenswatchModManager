"""Additive component append for cooked entity-settings files.

Cooked entity layout (see ``cooked.py`` for the container grammar):

* section 0 = component directory: ``u32 count`` + ``count`` u32 class-table
  indexes, one per component;
* sections 1..count = one self-framed component record each, starting with
  its class-table index (record i's first u32 == directory entry i);
* last section = entity-level trailer.

Because every record is self-framed and the deserializer walks the directory
sequentially, NEW components can be appended: add the class index to the
directory, bump the count, and insert the record before the trailer. This is
the entity-file analog of the versiondef MO-vector append proven for custom
items (see docs/_re/kinds/ui-menus.md, phase 4).

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


#: The trailer section is ``u32 0 | BEGIN | u32 base | u32 count | count*u32``
#: — an INSTANCE TABLE, and the reason appended components used to do nothing.
#: Its length tracks the number of GUID-bearing components exactly (verified on
#: Book_Mesh_Controller 188, Hero_Display 85, Modal_Model 37,
#: Book_Menu_Table_Model 13), and the entries are the identity sequence
#: ``0..count-1``.  A record that gets a directory entry but no instance slot
#: is parsed and then never constructed: no crash, no activation.
_TRAILER_COUNT_OFF = 12
_TRAILER_ARRAY_OFF = 16


def _extend_instance_table(trailer: bytes, extra: int) -> bytes:
    """Grow the trailer's instance table by ``extra`` slots."""
    if extra <= 0:
        return trailer
    if len(trailer) < _TRAILER_ARRAY_OFF or trailer[4:8] != cooked.MARK_BEGIN:
        raise EntityAppendError("trailer is not an instance table — layout "
                                "changed?")
    n = struct.unpack_from("<I", trailer, _TRAILER_COUNT_OFF)[0]
    end = _TRAILER_ARRAY_OFF + 4 * n
    if end > len(trailer):
        raise EntityAppendError(
            f"instance table claims {n} entries but the trailer holds "
            f"{(len(trailer) - _TRAILER_ARRAY_OFF) // 4}")
    arr = [struct.unpack_from("<I", trailer, _TRAILER_ARRAY_OFF + 4 * i)[0]
           for i in range(n)]
    if arr != list(range(n)):
        raise EntityAppendError("instance table is not the identity sequence; "
                                "refusing to guess how to extend it")
    grown = list(range(n + extra))
    return (trailer[:_TRAILER_COUNT_OFF]
            + struct.pack("<I", len(grown))
            + struct.pack(f"<{len(grown)}I", *grown)
            + trailer[end:])


def _has_instance_guid(record: bytes) -> bool:
    """Whether a record carries an instance GUID, i.e. needs a table slot.

    Descriptor records have no identity and are absent from the table, so
    counting every appended record would over-grow it.
    """
    pos = record.find(_END)
    if pos < 0 or pos + 4 + 16 > len(record):
        return False
    g = record[pos + 4:pos + 20]
    return g != b"\0" * 16 and cooked.MARK_BEGIN not in g and _END not in g


def append_components(cooked_bytes: bytes,
                      records: list[bytes]) -> bytes:
    """Append component records to a cooked entity, returning new bytes.

    Each record must already start with its class-table index u32 (clones of
    existing records keep theirs).

    Both tables that describe a component are updated: the section-0 directory
    (count + class index) AND the trailer's instance table.  Skipping the
    latter is why appended components loaded without error and then never ran.
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
    trailer.payload = _extend_instance_table(
        trailer.payload, sum(1 for r in records if _has_instance_guid(r)))
    cf.sections.append(trailer)
    return cooked.emit(cf)
