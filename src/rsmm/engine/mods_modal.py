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
from pathlib import Path

from . import cooked
from . import entity_append as EA
from . import entity_strings as ES
from . import text_patches as TP

#: Donor asset (decoded asset-map path, backslash form).
DONOR_DECODED = ("EntitySettings\\GameUis\\Modal\\"
                 "Modal_Model.entity.ot.EntitySettingsResource.gen")
#: Entity name embedded in the donor's component-reference paths.
DONOR_NAME = "Modal_Model"

#: Mod folder for the STANDALONE modal.  Kept fully separate from the legacy
#: ``RSMMMenu`` (which repurposes the Tutorial page): the modal must never
#: touch the tutorial, so it ships as its own mod.
MODAL_MOD_ID = "RSMMModal"

#: Our clone.
MODAL_NAME = "RSMM_Mods_Modal"
MODAL_DECODED = (f"EntitySettings\\GameUis\\Modal\\"
                 f"{MODAL_NAME}.entity.ot.EntitySettingsResource.gen")
#: Resource path the spawner names (no ``.EntitySettingsResource.gen`` tail —
#: spawners reference the ``.entity.ot`` form, as the EULA spawner does).
MODAL_RESOURCE = f"GameUis\\Modal\\{MODAL_NAME}.entity.ot"

_BEGIN = cooked.MARK_BEGIN
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


#: Text bank the clone reads its own labels from.  ``Common~GAM.xls`` is
#: already referenced by the donor's own button labels, so it is certainly
#: loaded wherever the modal is; our keys are appended to it at build time
#: (``text_patches.append_bank_keys``).
BANK_DIR = "Text"
BANK_FILE = "Common~GAM.xls"

#: The bank as an asset-map path.
BANK_DECODED = f"Text\\{BANK_FILE}.LocalText.gen"

#: Component name -> the bank key it should render.  Keys are modal-specific:
#: the phase-1 page menu owns ``RSMM_Menu_*`` in a different bank.
LABEL_KEYS: dict[str, str] = {
    "Title Label": "RSMM_Modal_Title",
    "Description Label": "RSMM_Modal_Body",
}


def build_modal(donor_bytes: bytes, *, name: str = MODAL_NAME,
                labels: dict[str, str] | None = None) -> bytes:
    """Clone the donor modal into a standalone entity called ``name``.

    ``labels`` maps component name -> text-bank key; it defaults to
    :data:`LABEL_KEYS`.  Pass ``{}`` to leave the donor's bindings alone.
    """
    if not name.isascii():
        raise ModsModalError(f"entity name must be ASCII: {name!r}")
    out = rename_entity(donor_bytes, DONOR_NAME, name)
    out = remint_all(out)
    for cpnt, key in (LABEL_KEYS if labels is None else labels).items():
        out = set_component_label(out, cpnt, key=key)
    residual = [s for _, _, s in ES.list_strings(out)
                if DONOR_NAME in s and name not in s]
    if residual:
        raise ModsModalError(f"clone still references the donor: {residual[:3]}")
    return out


#: Inner BEGIN tags are indexes into THE FILE'S OWN class table, not global
#: constants — ``oCEntityCpntValuePicker`` is 0x14 in ``Modal_Model`` but 0x13
#: in ``System_Book_Page``.  They must always be resolved by class name.
_CLS_BOUND = "oCEntityCpntValuePicker"   # wraps an optionally-bound value
_CLS_UNION = "oCEntityValueUnion"        # the value itself
#: Union type for localized text.
_UNION_TEXT = 5
#: Text-source kind: read from a text bank.
_TEXT_FROM_BANK = 3


def _lstr(s: str) -> bytes:
    return struct.pack("<I", len(s)) + s.encode("ascii")


def _matching_end(blob: bytes, begin: int) -> int:
    """Offset just past the END matching the BEGIN at ``begin``."""
    depth, i = 0, begin
    while i < len(blob):
        if blob[i:i + 4] == _BEGIN:
            depth += 1
            i += 8
        elif blob[i:i + 4] == _END:
            depth -= 1
            i += 4
            if depth == 0:
                return i
        else:
            i += 1
    raise ModsModalError("unbalanced BEGIN/END in component record")


def class_index(cf: cooked.CookedFile, name: str) -> int:
    """Index of ``name`` in this file's class table (tags are file-relative)."""
    for i, c in enumerate(cf.classes):
        if c.name == name:
            return i
    raise ModsModalError(f"class {name!r} absent from the file's class table")


def _find_text_block(record: bytes, bound: int, union_tag: int) -> tuple[int, int]:
    """Span of the label's bound-value block holding its text union.

    A label carries exactly one type-5 union; every other union on the record
    is a float/colour/bool, which is what makes this an unambiguous anchor.
    """
    hits = []
    needle = _BEGIN + struct.pack("<I", bound)
    pos = record.find(needle)
    while pos >= 0:
        end = _matching_end(record, pos)
        union = record.find(_BEGIN + struct.pack("<I", union_tag), pos, end)
        if union >= 0 and struct.unpack_from("<I", record, union + 8)[0] == _UNION_TEXT:
            hits.append((pos, end))
        pos = record.find(needle, pos + 4)
    if len(hits) != 1:
        raise ModsModalError(
            f"expected exactly one text union on the record, found {len(hits)}")
    return hits[0]


def _bank_text_block(bound: int, union_tag: int, bank_dir: str,
                     bank_file: str, key: str) -> bytes:
    """A static bound-value block resolving its text from a text-bank key."""
    union = (struct.pack("<I", _UNION_TEXT) + b"\0" * 8
             + struct.pack("<I", _TEXT_FROM_BANK)
             + _lstr(bank_dir) + _lstr(bank_file)
             + struct.pack("<I", 1) + _lstr(key))
    return (_BEGIN + struct.pack("<I", bound) + b"\0"
            + _BEGIN + struct.pack("<I", union_tag) + union + _END
            + _END)


def set_label_text(record: bytes, *, bound: int, union_tag: int,
                   bank_dir: str, bank_file: str, key: str) -> bytes:
    """Re-point a label component at a text-bank key.

    ``Modal_Model``'s title and description labels bind their text to an
    ``oCEntityCpntValueSettings`` that the modal's controller fills in, so a
    clone opened by a plain spawner renders empty.  Swapping the bound block
    for the static bank form — the shape the donor's own button labels use —
    makes the clone carry its own text.
    """
    for part in (bank_dir, bank_file, key):
        if not part.isascii():
            raise ModsModalError(f"bank reference must be ASCII: {part!r}")
    start, end = _find_text_block(record, bound, union_tag)
    block = _bank_text_block(bound, union_tag, bank_dir, bank_file, key)
    return record[:start] + block + record[end:]


def label_text_binding(record: bytes, *, bound: int,
                       union_tag: int) -> tuple[str, str, str] | None:
    """``(bank_dir, bank_file, key)`` a label reads its text from, if static."""
    start, end = _find_text_block(record, bound, union_tag)
    union = record.find(_BEGIN + struct.pack("<I", union_tag), start, end)
    off = union + 8 + 4 + 8
    if struct.unpack_from("<I", record, off)[0] != _TEXT_FROM_BANK:
        return None
    off += 4
    parts = []
    for _ in range(2):
        n = struct.unpack_from("<I", record, off)[0]
        parts.append(record[off + 4:off + 4 + n].decode("ascii"))
        off += 4 + n
    off += 4
    n = struct.unpack_from("<I", record, off)[0]
    parts.append(record[off + 4:off + 4 + n].decode("ascii"))
    return tuple(parts) if all(parts) else None


def modal_texts(mods: list[dict]) -> dict[str, str]:
    """Bank key -> display text for the modal's two labels."""
    enabled = [m for m in mods if m.get("enabled", True)]
    lines = [
        ("• " if m.get("enabled", True) else "◦ ")
        + f"{m.get('name') or m['id']} {m.get('version', '')}".strip()
        + ("" if m.get("enabled", True) else "  [disabled]")
        for m in sorted(mods, key=lambda m: str(m.get("name") or m["id"]).lower())
    ]
    body = "\n".join(lines) if lines else "(no mods installed)"
    return {
        LABEL_KEYS["Title Label"]: "MODS",
        LABEL_KEYS["Description Label"]: (
            f"{len(mods)} installed, {len(enabled)} enabled.\n\n{body}"),
    }


def manifest_toml(mod_count: int) -> str:
    return f"""[mod]
id          = "{MODAL_MOD_ID}"
name        = "RSMM Mods Modal"
version     = "0.1.0"
author      = "rsmm"
description = "Standalone in-game mods modal ({mod_count} mods), opened on \
BOOK_MENU_OPEN. Does NOT touch the Tutorial page. Regen: rsmm menu modal."
enabled     = true
sdk_version = ">=3.0,<4"
# Ships a NEW menu entity + a host-entity override + a text-bank append;
# not yet in-game confirmed.
experimental = true
"""


def build_modal_assets(cooking_root: Path, dec2enc: dict[str, str],
                       mods: list[dict], *,
                       trigger: bool = True) -> dict[str, bytes]:
    """Every asset of the mod modal: ``{decoded path token: bytes}``.

    The donor is read from the user's own install, so no game-derived bytes
    ever ship with rsmm.  The modal itself is a NEW asset — ``apply`` registers
    it through ``UsedRscList`` — and the bank keys are appended to the existing
    ``Common~GAM.xls`` across all its language siblings.

    ``trigger`` also emits the host override carrying the ``RSMM_OPEN_MENU``
    chain; pass ``False`` to ship the modal asset alone (it is then only
    reachable by something else firing the event).
    """
    donor_dec = DONOR_DECODED.replace("\\", "/")
    bank_dec = BANK_DECODED.replace("\\", "/")
    for dec in (donor_dec, bank_dec):
        if dec not in dec2enc:
            raise ModsModalError(f"asset map is missing {dec!r} — game update? "
                                 f"re-run 'rsmm rebuild-asset-map'")

    def _pristine(dec: str) -> Path:
        """The un-modded cooked file: prefer apply's backup so a rebuild after
        ``rsmm apply`` doesn't re-edit its own output."""
        p = cooking_root / Path(*dec2enc[dec].replace("\\", "/").split("/"))
        bak = p.with_name(p.name + ".rsmm.bak")
        if bak.is_file():
            return bak
        if not p.is_file():
            raise ModsModalError(f"cooked file not found: {p} — wrong game dir?")
        return p

    out = {MODAL_DECODED.replace("\\", "/"):
           build_modal(_pristine(donor_dec).read_bytes())}

    if trigger:
        host_dec = HOST_DECODED.replace("\\", "/")
        if host_dec not in dec2enc:
            raise ModsModalError(f"asset map is missing {host_dec!r} — game "
                                 f"update? re-run 'rsmm rebuild-asset-map'")
        out[host_dec] = build_open_trigger(_pristine(host_dec).read_bytes())

    # append_bank_keys resolves .rsmm.bak per language sibling itself, so it
    # needs the LIVE path for its sibling discovery to work.
    bank_path = cooking_root / Path(*dec2enc[bank_dec].replace("\\", "/").split("/"))
    if not bank_path.is_file():
        raise ModsModalError(f"cooked file not found: {bank_path} — wrong game dir?")
    for token, blob in TP.append_bank_keys(bank_path, modal_texts(mods)).items():
        out[bank_dec if token == "__base__" else f"{bank_dec}{token}"] = blob
    return out


#: The host we append the open-trigger chain to.  It must already carry every
#: class the chain uses — ``append_components`` cannot invent class-table
#: entries — and only ``Hero_Display`` and ``MyNacon`` do.  ``Hero_Display``
#: also runs this exact chain three times already, so every wiring precedent
#: is in front of us.
HOST_DECODED = ("EntitySettings\\GameUis\\All_Book_Pages\\"
                "Hero_Display.entity.ot.EntitySettingsResource.gen")
HOST_NAME = "Hero_Display"
#: Component group the appended chain lives in (part of every reference path).
HOST_GROUP = "UI Social"

#: The named event our listener subscribes to.  Named events in this engine
#: are BROADCAST, so subscribing does not steal the event from its existing
#: listeners — it rides alongside them.  ``BOOK_MENU_OPEN`` is fired by
#: ``Book_Menu\Book_Mesh_Controller`` every time the player opens the book, so
#: it needs no new sender and no button (no host has the button + sender
#: classes without extending its class table).  The mod modal therefore opens
#: with the book.  This is a v1 trigger: a dedicated opener is future work.
TRIGGER_EVENT = "BOOK_MENU_OPEN"

#: Our component names.
_C_LISTENER = "RSMM Open Menu Listener"
_C_METHODS = "RSMM Open Menu Methods"
_C_HANDLER = "RSMM Mods Modal Handler"
_C_SPAWNER = "RSMM Mods Modal Spawner"


def _ref(kind: str, name: str) -> str:
    return f"[{kind}] {HOST_NAME}\\{HOST_GROUP}\\{name}"


def _chain(event: str) -> tuple[tuple[str, dict[str, str]], ...]:
    """Donor component -> the string swaps that retarget its clone.

    Donors are picked for MINIMAL coupling: the Report handler is the only one
    with no social-handler, state or bank-key references, and the Blacklist
    spawner the only one that names no spawner value.
    """
    return (
    ("Spawn Blacklist Modal Event Listener", {
        "Spawn Blacklist Modal Event Listener": _C_LISTENER,
        "SPAWN_BLACKLIST_MODAL": event,
        f"[Executing Methods] {HOST_NAME}\\{HOST_GROUP}\\Blacklist Methods":
            _ref("Executing Methods", _C_METHODS),
    }),
    ("Blacklist Methods", {
        "Blacklist Methods": _C_METHODS,
        f"[Modal Handler] {HOST_NAME}\\Blacklist Modal\\Blacklist Modal Handler":
            _ref("Modal Handler", _C_HANDLER),
    }),
    ("Report Modal Handler", {
        "Report Modal Handler": _C_HANDLER,
        f"[Entity Spawner] {HOST_NAME}\\{HOST_GROUP}\\Report Modal Entity Spawner":
            _ref("Entity Spawner", _C_SPAWNER),
    }),
    ("Blacklist Modal Entity Spawner", {
        "Blacklist Modal Entity Spawner": _C_SPAWNER,
        # The spawner's group is part of every path that names it, so it has
        # to move into the group the rest of the chain lives in.
        "Blacklist Modal": HOST_GROUP,
        "GameUis\\Modal\\Modal_Warning.entity.ot": MODAL_RESOURCE,
    }),
)


def build_open_trigger(host_bytes: bytes, *, event: str = TRIGGER_EVENT) -> bytes:
    """Append the ``event`` -> spawn-the-mod-modal chain to the host.

    Four components, cloned from the host's own working social-modal chain:
    a named-event listener (subscribed to ``event``), an executing-methods
    relay, a modal handler and an entity spawner pointed at
    :data:`MODAL_RESOURCE`.  The listener does not reach the spawner directly —
    ``ModalHandlerEntityCpntSettings`` sits between them — but that class is
    generic, driving all three retail modals.
    """
    if not event.isascii() or not event:
        raise ModsModalError(f"event name must be non-empty ASCII: {event!r}")
    chain = _chain(event)
    cf = cooked.parse(host_bytes)
    names = component_names(host_bytes)
    records, guids = [], {}
    for donor, _ in chain:
        if names.count(donor) != 1:
            raise ModsModalError(
                f"expected exactly one {donor!r} on {HOST_NAME} — game update "
                f"changed its layout?")
        record = cf.sections[1 + names.index(donor)].payload
        guid = _component_guid(record)
        if guid is None:
            raise ModsModalError(f"{donor!r} carries no instance GUID")
        records.append(record)
        guids[guid] = os.urandom(16)

    clones = []
    for record, (donor, swaps) in zip(records, chain, strict=True):
        # GUIDs first, so references BETWEEN the clones land on the clones
        # rather than on the components they were copied from.  References
        # out of the set keep the original GUID, which is what we want.
        for old, new in guids.items():
            record = record.replace(old, new)
        try:
            clones.append(EA.replace_blob_strings(record, swaps))
        except EA.EntityAppendError as e:
            raise ModsModalError(f"retargeting {donor!r}: {e}") from None

    out = EA.append_components(host_bytes, clones)
    added = set(component_names(out)) - set(names)
    expected = {_C_LISTENER, _C_METHODS, _C_HANDLER, _C_SPAWNER}
    if added != expected:
        raise ModsModalError(f"appended {sorted(added)}, expected "
                             f"{sorted(expected)}")
    return out


def _named_section(cf: cooked.CookedFile, cooked_bytes: bytes,
                   cpnt_name: str) -> cooked.Section:
    matches = [i for i, n in enumerate(component_names(cooked_bytes))
               if n == cpnt_name]
    if len(matches) != 1:
        raise ModsModalError(
            f"expected exactly one component named {cpnt_name!r}, "
            f"found {len(matches)}")
    return cf.sections[1 + matches[0]]


def component_label_binding(cooked_bytes: bytes,
                            cpnt_name: str) -> tuple[str, str, str] | None:
    """Text-bank binding of a named label, resolving tags from the file."""
    cf = cooked.parse(cooked_bytes)
    return label_text_binding(_named_section(cf, cooked_bytes, cpnt_name).payload,
                              bound=class_index(cf, _CLS_BOUND),
                              union_tag=class_index(cf, _CLS_UNION))


def set_component_label(cooked_bytes: bytes, cpnt_name: str, *, key: str,
                        bank_dir: str = BANK_DIR,
                        bank_file: str = BANK_FILE) -> bytes:
    """Point the named label component at ``key`` in a text bank."""
    cf = cooked.parse(cooked_bytes)
    sec = _named_section(cf, cooked_bytes, cpnt_name)
    sec.payload = set_label_text(
        sec.payload, bound=class_index(cf, _CLS_BOUND),
        union_tag=class_index(cf, _CLS_UNION),
        bank_dir=bank_dir, bank_file=bank_file, key=key)
    return cooked.emit(cf)


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
