"""Standalone RSMM mod-menu modal — a NEW menu entity, not a vanilla edit.

The book's five tabs and five pages are fixed inline arrays filled by
immediate-5 loops (``BookMenuUiController`` at ``+0xf8`` / ``+0x190``), so a
sixth book page is a wall.  Modals are not: ``GameUis/Modal/Modal_*`` entities
are self-contained menus (own ``oCEntityCpntModalUiControllerSettings``, own
buttons, own nav zone) that live entirely OUTSIDE those arrays and are opened
by an ``oCEntityCpntEntitySpawnerSettings`` naming the modal's resource path
on a named event.  ``System_Book_Page``'s "EULA Modal Spawner" is the retail
proof.

So the mod menu is a CLONE of a modal under a new asset path — no vanilla page
is repurposed and no vanilla entity is edited.

Donor: ``Modal_Model`` — the game's own generic modal template.  It carries a
title label, a description label and four buttons already declared in its
controller (``Validate_Button``, ``Cancel_Button``, ``Third_Button``,
``Fourth_Button``), and pulls in none of the social-menu handler classes.

Cloning rules, both load-bearing:

* **Rename** every lstr mentioning the donor entity name.  Intra-file
  component references are ``"[Kind] <Entity>\\<Component>"`` paths, so a
  clone that keeps the donor name resolves against the donor's components.
* **Remint consistently.**  Each component record carries a 16-byte instance
  GUID after its first inner ``END``, and every picker that references that
  component repeats the same GUID next to the path string.  A per-record
  remint therefore breaks every reference; the whole file is rewritten with
  one old->new map instead.
"""

from __future__ import annotations

import os
import struct

from . import cooked
from . import entity_strings as ES

#: Donor asset (decoded asset-map path, backslash form).
DONOR_DECODED = ("EntitySettings\\GameUis\\Modal\\"
                 "Modal_Model.entity.ot.EntitySettingsResource.gen")
#: Entity name embedded in the donor's component-reference paths.
DONOR_NAME = "Modal_Model"

#: Our clone.
MODAL_NAME = "RSMM_Mods_Modal"
MODAL_DECODED = (f"EntitySettings\\GameUis\\Modal\\"
                 f"{MODAL_NAME}.entity.ot.EntitySettingsResource.gen")
#: Resource path the spawner names (no ``.EntitySettingsResource.gen`` tail —
#: spawners reference the ``.entity.ot`` form, as the EULA spawner does).
MODAL_RESOURCE = f"GameUis\\Modal\\{MODAL_NAME}.entity.ot"

_END = cooked.MARK_END


class ModsModalError(ValueError):
    pass


#: A component record opens ``<class u32> BEGIN <base-class u32> <20 zero
#: bytes> END`` and only then carries its instance GUID + name.  Descriptor
#: records (``oC2dElementDesc``, ``oCUIGameButtonDesc``, the test settings)
#: have no instance identity at all, and their first END sits somewhere
#: structural — reading 16 bytes there yields section MARKERS, so blind
#: reminting rewrites framing bytes and merges sections.  Hence the header
#: match below; the base-class u32 is left free rather than pinned to the
#: value this donor happens to use.
_HDR_ZEROS = 20
_HDR_LEN = len(cooked.MARK_BEGIN) + 4 + _HDR_ZEROS + len(_END)


def _has_component_header(record: bytes) -> bool:
    hdr = record[4:4 + _HDR_LEN]
    return (len(hdr) == _HDR_LEN
            and hdr.startswith(cooked.MARK_BEGIN)
            and hdr[8:8 + _HDR_ZEROS] == b"\0" * _HDR_ZEROS
            and hdr.endswith(_END))


def _component_guid(record: bytes) -> bytes | None:
    """The 16-byte instance GUID of a real component record, else ``None``.

    Validated, not guessed: the record must open with the component header,
    and the GUID must be followed by the component's length-prefixed ASCII
    name.  A candidate containing a section marker is refused outright.
    """
    if not _has_component_header(record):
        return None
    g = record[4 + _HDR_LEN:4 + _HDR_LEN + 16]
    if len(g) != 16 or g == b"\0" * 16:
        return None
    if cooked.MARK_BEGIN in g or _END in g:
        return None
    off = 4 + _HDR_LEN + 16
    if off + 4 > len(record):
        return None
    n = struct.unpack_from("<I", record, off)[0]
    if not 0 < n <= 128 or off + 4 + n > len(record):
        return None
    name = record[off + 4:off + 4 + n]
    return g if name.isascii() and name.decode().isprintable() else None


def _guid_map(cf: cooked.CookedFile) -> dict[bytes, bytes]:
    """old -> fresh GUID for every component instance in the file."""
    out: dict[bytes, bytes] = {}
    for sec in cf.sections[1:-1]:
        g = _component_guid(sec.payload)
        # An all-zero field is a null GUID, not an identity — never remint it.
        if g is None or g == b"\0" * 16 or g in out:
            continue
        out[g] = os.urandom(16)
    return out


def remint_all(cooked_bytes: bytes) -> bytes:
    """Give every component a fresh GUID, rewriting references in lockstep.

    Applied file-wide (payloads only) so the ``GUID + "[Kind] Entity\\Cpnt"``
    picker pairs keep pointing at the components they named.
    """
    cf = cooked.parse(cooked_bytes)
    mapping = _guid_map(cf)
    if not mapping:
        raise ModsModalError("no component GUIDs found — not an entity file?")
    for sec in cf.sections:
        payload = sec.payload
        for old, new in mapping.items():
            payload = payload.replace(old, new)
        sec.payload = payload
    out = cooked.emit(cf)
    # Fail closed: a remint that disturbs framing shows up as a section-count
    # change (that is exactly how the marker-collision bug presented).
    if len(cooked.parse(out).sections) != len(cf.sections):
        raise ModsModalError("remint changed the section count — GUID collided "
                             "with container framing")
    return out


def rename_entity(cooked_bytes: bytes, old: str, new: str) -> bytes:
    """Rewrite every lstr mentioning entity ``old`` to name ``new``.

    ``entity_strings.replace_strings`` matches whole strings, so the mapping
    is built by scanning: component references embed the entity name as a
    substring (``"[State] Modal_Model\\State Ready"``).
    """
    seen = sorted({s for _, _, s in ES.list_strings(cooked_bytes) if old in s})
    if not seen:
        raise ModsModalError(f"entity name {old!r} not present — wrong donor?")
    return ES.replace_strings(cooked_bytes, {s: s.replace(old, new) for s in seen})


def build_modal(donor_bytes: bytes, *, name: str = MODAL_NAME) -> bytes:
    """Clone the donor modal into a standalone entity called ``name``."""
    if not name.isascii():
        raise ModsModalError(f"entity name must be ASCII: {name!r}")
    out = rename_entity(donor_bytes, DONOR_NAME, name)
    out = remint_all(out)
    residual = [s for _, _, s in ES.list_strings(out)
                if DONOR_NAME in s and name not in s]
    if residual:
        raise ModsModalError(f"clone still references the donor: {residual[:3]}")
    return out


def component_names(cooked_bytes: bytes) -> list[str]:
    """Each record's component name in directory order — the clone's inventory.

    Descriptor records have no instance identity and yield ``""``.
    """
    cf = cooked.parse(cooked_bytes)
    names: list[str] = []
    off = 4 + _HDR_LEN + 16
    for sec in cf.sections[1:-1]:
        if _component_guid(sec.payload) is None:
            names.append("")
            continue
        n = struct.unpack_from("<I", sec.payload, off)[0]
        names.append(sec.payload[off + 4:off + 4 + n].decode("ascii"))
    return names
