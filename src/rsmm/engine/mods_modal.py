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
                labels: dict[str, str] | None = None,
                donor_name: str = DONOR_NAME) -> bytes:
    """Clone the donor entity into a standalone one called ``name``.

    ``labels`` maps component name -> text-bank key; it defaults to
    :data:`LABEL_KEYS`.  Pass ``{}`` to leave the donor's bindings alone.
    """
    if not name.isascii():
        raise ModsModalError(f"entity name must be ASCII: {name!r}")
    out = rename_entity(donor_bytes, donor_name, name)
    out = remint_all(out)
    for cpnt, key in (LABEL_KEYS if labels is None else labels).items():
        out = set_component_label(out, cpnt, key=key)
    residual = [s for _, _, s in ES.list_strings(out)
                if donor_name in s and name not in s]
    if residual:
        raise ModsModalError(f"clone still references the donor: {residual[:3]}")
    return out


#: --- The PAGE clone ---------------------------------------------------------
#:
#: A modal bound into a tab slot renders EMPTY: its ``Modal Ui Controller``
#: keeps the children hidden until something opens the modal as an overlay,
#: and a page slot never does that.  So the tab needs a real BOOK PAGE.
#:
#: Donor: ``Memories_Book_Page`` — of every page carrying reusable labels it
#: has the least coupling (1 spawner, 2 spawned entities, 1 foreign reference;
#: ``Social_Book_Page`` has 10 foreign refs, which is the coupling trap that
#: killed the phase-3 social clone).  Its two labels are already the
#: title/body shape we want.
PAGE_DONOR_DECODED = ("EntitySettings\\GameUis\\All_Book_Pages\\"
                      "Memories_Book_Page.entity.ot.EntitySettingsResource.gen")
PAGE_DONOR_NAME = "Memories_Book_Page"

PAGE_NAME = "RSMM_Mods_Page"
PAGE_DECODED = (f"EntitySettings\\GameUis\\All_Book_Pages\\"
                f"{PAGE_NAME}.entity.ot.EntitySettingsResource.gen")
PAGE_RESOURCE = f"GameUis\\All_Book_Pages\\{PAGE_NAME}.entity.ot"

#: The donor's two labels, repurposed as our title and body.
PAGE_LABEL_KEYS: dict[str, str] = {
    "Hero Name Label": "RSMM_Modal_Title",
    "Hero Unlock Condition Label": "RSMM_Modal_Body",
}


#: Hero content the donor page spawns — the "hero compendium on the other
#: side".  Each is retargeted at our MODAL, which is the one entity proven to
#: load and render NOTHING outside an overlay context: that was the empty-page
#: result, and it makes the modal a perfect blank.  Components can't be
#: removed (appending is a wall, and shrinking would hit the same instance
#: table), so neutralising by retarget is the available move.
PAGE_BLANKED = (
    "GameUis\\All_Book_Pages\\Hero_Miniature.entity.ot",
    "GameUis\\All_Book_Pages\\Hero_Story_Page.entity.ot",
)


def build_page(donor_bytes: bytes, *, name: str = PAGE_NAME,
               labels: dict[str, str] | None = None,
               blank: bool = True) -> bytes:
    """Clone the donor book page into our own page entity."""
    out = build_modal(donor_bytes, name=name, donor_name=PAGE_DONOR_NAME,
                      labels=PAGE_LABEL_KEYS if labels is None else labels)
    if blank:
        present = {s for _, _, s in ES.list_strings(out)}
        swaps = {s: MODAL_RESOURCE for s in PAGE_BLANKED if s in present}
        if swaps:
            out = ES.replace_strings(out, swaps)
        left = [s for _, _, s in ES.list_strings(out) if s in PAGE_BLANKED]
        if left:
            raise ModsModalError(f"hero content still spawned: {left}")
    # The tab binding resolves "<entity>\Game Ui"; without it the tab opens
    # onto nothing, which is exactly the empty page the modal produced.
    if "Game Ui" not in component_names(out):
        raise ModsModalError(f"{name} has no 'Game Ui' component — the tab "
                             f"binding would not resolve")
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


#: The label is a fixed-size box on a book page with no scroll and no clipping
#: — an unbounded list overflows straight off the page (49 mods did exactly
#: that in-game). Cap the rows and summarise the remainder.
MAX_ROWS = 14
#: Long names push rows past the page width, so they are ellipsised.
MAX_NAME = 34

_DISABLED_GLYPH = "\u25e6"


def _row(m: dict) -> str:
    on = m.get("enabled", True)
    name = str(m.get("name") or m["id"])
    if len(name) > MAX_NAME:
        name = name[:MAX_NAME - 1] + "…"
    ver = str(m.get("version", "")).strip()
    return f"{'•' if on else '◦'} {name}" + (f" {ver}" if ver else "")


def modal_texts(mods: list[dict]) -> dict[str, str]:
    """Bank key -> display text for the modal's two labels."""
    enabled = [m for m in mods if m.get("enabled", True)]
    # Enabled first, so a truncated list shows what is actually active.
    ordered = sorted(mods, key=lambda m: (not m.get("enabled", True),
                                          str(m.get("name") or m["id"]).lower()))
    lines = [_row(m) for m in ordered[:MAX_ROWS]]
    if len(ordered) > MAX_ROWS:
        lines.append(f"… and {len(ordered) - MAX_ROWS} more")
    body = "\n".join(lines) if lines else "(no mods installed)"
    return {
        LABEL_KEYS["Title Label"]: "MODS",
        LABEL_KEYS["Description Label"]: (
            f"{len(mods)} installed, {len(enabled)} enabled."
            # A legend beats repeating "[disabled]" on every row: the page is
            # width-constrained and the glyph already carries the state.
            + (f"   {_DISABLED_GLYPH} = disabled" if len(enabled) < len(mods)
               else "")
            + f"\n\n{body}"),
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
                       trigger: bool = True,
                       probe: bool = False,
                       probe_append: bool = False,
                       blank: bool = True) -> dict[str, bytes]:
    """Every asset of the mod modal: ``{decoded path token: bytes}``.

    The donor is read from the user's own install, so no game-derived bytes
    ever ship with rsmm.  The modal itself is a NEW asset — ``apply`` registers
    it through ``UsedRscList`` — and the bank keys are appended to the existing
    ``Common~GAM.xls`` across all its language siblings.

    ``trigger`` also emits the ``Main_Book_Menu`` override that points the
    book's Tuto tab at our modal; pass ``False`` to ship the modal asset alone
    (nothing then opens it).
    """
    donor_dec = DONOR_DECODED.replace("\\", "/")
    page_donor_dec = PAGE_DONOR_DECODED.replace("\\", "/")
    bank_dec = BANK_DECODED.replace("\\", "/")
    checked = [donor_dec, page_donor_dec, bank_dec]
    if trigger:
        checked.append(PAGE_HOST_DECODED.replace("\\", "/"))
    for dec in checked:
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

    out = {
        # The page is what the Tuto tab opens.
        PAGE_DECODED.replace("\\", "/"):
            build_page(_pristine(page_donor_dec).read_bytes(), blank=blank),
        # The modal ships too: its four declared buttons are the surface the
        # intent protocol will hang off, once the page renders.
        MODAL_DECODED.replace("\\", "/"):
            build_modal(_pristine(donor_dec).read_bytes()),
    }

    if trigger:
        host_dec = PAGE_HOST_DECODED.replace("\\", "/")
        out[host_dec] = retarget_tuto_tab(
            _pristine(host_dec).read_bytes(),
            resource=PAGE_RESOURCE, entity=PAGE_NAME)

    # append_bank_keys resolves .rsmm.bak per language sibling itself, so it
    # needs the LIVE path for its sibling discovery to work.
    bank_path = cooking_root / Path(*dec2enc[bank_dec].replace("\\", "/").split("/"))
    if not bank_path.is_file():
        raise ModsModalError(f"cooked file not found: {bank_path} — wrong game dir?")
    for token, blob in TP.append_bank_keys(bank_path, modal_texts(mods)).items():
        out[bank_dec if token == "__base__" else f"{bank_dec}{token}"] = blob
    return out


#: Where the working modal chain is CLONED from.  ``Hero_Display`` is the only
#: non-social-singleton entity that carries a full
#: listener -> methods -> handler -> spawner modal chain.
CHAIN_SRC_DECODED = ("EntitySettings\\GameUis\\All_Book_Pages\\"
                     "Hero_Display.entity.ot.EntitySettingsResource.gen")
CHAIN_SRC_ENTITY = "Hero_Display"

#: Where the chain is APPENDED.  Named events are dispatched through a
#: PER-ENTITY dispatcher (verified: the loader's ``NamedEvent_Dispatch`` hook
#: takes a dispatcher at ``entity+0x4d8``), so a listener only fires for events
#: delivered to ITS entity.  ``BOOK_MENU_OPEN`` fires (confirmed live) but is
#: dispatched in the book-mesh scene, not to the GameUis book pages — so the
#: host must be the entity that NATIVELY receives it.  ``Book_Mesh_Controller``
#: both sends and listens ``BOOK_MENU_OPEN`` (its ``Book Open Event Listener``),
#: is loaded whenever the book scene exists, and is missing only two chain
#: classes.
HOST_DECODED = ("EntitySettings\\Book_Menu\\"
                "Book_Mesh_Controller.entity.ot.EntitySettingsResource.gen")
HOST_NAME = "Book_Mesh_Controller"
#: Component group the appended chain lives in (part of every reference path).
#: Any consistent label works; ``UI Social`` matches most donor components so
#: it minimises the group renames.
HOST_GROUP = "UI Social"

#: The named event our listener subscribes to.  ``BOOK_MENU_OPEN`` is fired by
#: ``Book_Mesh_Controller`` every time the player opens the book — and since we
#: host on that same entity, its dispatcher delivers the event to our listener.
TRIGGER_EVENT = "BOOK_MENU_OPEN"

#: Our component names.
_C_LISTENER = "RSMM Open Menu Listener"
_C_METHODS = "RSMM Open Menu Methods"
_C_HANDLER = "RSMM Mods Modal Handler"
_C_SPAWNER = "RSMM Mods Modal Spawner"


#: --- Tab retarget (the mechanism that actually works) ------------------------
#:
#: Appending components to a cooked entity is a WALL: the engine never
#: constructs them (directory bumped alone = inert), and forcing the trailer's
#: instance count to match crashes on a garbage pointer walk at 0x1406e0b8e.
#: See the phase 6j/6k notes.  What DOES work is editing a component that
#: already exists — proven in-game by renaming a native sender's event.
#:
#: ``Main_Book_Menu`` names each tab's page by resource path, so pointing the
#: Tuto tab at our own entity is exactly that kind of edit: two strings, no new
#: components, no class-table surgery.  The Tutorial tab becomes the mod menu.
#: The vanilla ``Tuto_Compendim_Page`` asset is left untouched on disk — this
#: changes which page the tab OPENS, it does not rewrite the tutorial.
PAGE_HOST_DECODED = ("EntitySettings\\GameUis\\All_Book_Pages\\"
                     "Main_Book_Menu.entity.ot.EntitySettingsResource.gen")
PAGE_HOST_NAME = "Main_Book_Menu"

#: The tab we take over, as named by the host.
TUTO_PAGE_ENTITY = "Tuto_Compendim_Page"
TUTO_PAGE_RESOURCE = f"GameUis\\All_Book_Pages\\{TUTO_PAGE_ENTITY}.entity.ot"


def retarget_tuto_tab(host_bytes: bytes, *, resource: str = MODAL_RESOURCE,
                      entity: str = MODAL_NAME) -> bytes:
    """Point the book's Tuto tab at ``entity`` instead of the tutorial page.

    Two strings carry the binding: the page's resource path, and a
    ``"[Game Ui] <Entity>\\Game Ui"`` reference into it.  Our modal clone
    carries a ``Game Ui`` component (it comes from ``Modal_Model``), so the
    second resolves as-is.
    """
    swaps = {TUTO_PAGE_RESOURCE: resource,
             f"[Game Ui] {TUTO_PAGE_ENTITY}\\Game Ui": f"[Game Ui] {entity}\\Game Ui"}
    present = {s for _, _, s in ES.list_strings(host_bytes)}
    missing = [s for s in swaps if s not in present]
    if missing:
        raise ModsModalError(
            f"{PAGE_HOST_NAME} does not name {missing} — game update changed "
            f"the tab bindings?")
    out = ES.replace_strings(host_bytes, swaps)
    # Nothing may still point at the tutorial page, or the tab would open it.
    left = [s for _, _, s in ES.list_strings(out) if TUTO_PAGE_ENTITY in s]
    if left:
        raise ModsModalError(f"tutorial page still referenced: {left}")
    return out


def _ref(kind: str, name: str) -> str:
    return f"[{kind}] {HOST_NAME}\\{HOST_GROUP}\\{name}"


#: The retail modal the chain's donor spawner already points at.  Leaving the
#: spawner on it turns the chain into a pure trigger probe: if this modal shows
#: up on book open, the appended chain fires and any silence is our own modal's
#: fault, not the trigger's.
PROBE_RESOURCE = "GameUis\\Modal\\Modal_Warning.entity.ot"


def _chain(event: str, modal_resource: str) -> tuple[tuple[str, dict[str, str]], ...]:
    """Donor component -> the string swaps that retarget its clone.

    Swap KEYS name the donor's own strings (entity ``Hero_Display``); VALUES
    relocate them onto ``HOST_NAME``.  Donors are picked for MINIMAL coupling:
    the Report handler is the only one with no social-handler, state or
    bank-key references, and the Blacklist spawner the only one that names no
    spawner value.
    """
    src = CHAIN_SRC_ENTITY
    return (
    ("Spawn Blacklist Modal Event Listener", {
        "Spawn Blacklist Modal Event Listener": _C_LISTENER,
        "SPAWN_BLACKLIST_MODAL": event,
        f"[Executing Methods] {src}\\{HOST_GROUP}\\Blacklist Methods":
            _ref("Executing Methods", _C_METHODS),
    }),
    ("Blacklist Methods", {
        "Blacklist Methods": _C_METHODS,
        f"[Modal Handler] {src}\\Blacklist Modal\\Blacklist Modal Handler":
            _ref("Modal Handler", _C_HANDLER),
    }),
    ("Report Modal Handler", {
        "Report Modal Handler": _C_HANDLER,
        f"[Entity Spawner] {src}\\{HOST_GROUP}\\Report Modal Entity Spawner":
            _ref("Entity Spawner", _C_SPAWNER),
    }),
    ("Blacklist Modal Entity Spawner", {
        "Blacklist Modal Entity Spawner": _C_SPAWNER,
        # The spawner's group is part of every path that names it, so it has
        # to move into the group the rest of the chain lives in.
        "Blacklist Modal": HOST_GROUP,
        # Identity when probing: the donor already names the retail modal, and
        # a same-for-same swap would be a no-op the string rewriter rejects.
        **({} if modal_resource == PROBE_RESOURCE
           else {PROBE_RESOURCE: modal_resource}),
    }),
)


def _class_index_of(cf: cooked.CookedFile, name: str) -> int | None:
    for i, c in enumerate(cf.classes):
        if c.name == name:
            return i
    return None


def extend_class_table(host_cf: cooked.CookedFile, donor_cf: cooked.CookedFile,
                       needed: set[str]) -> None:
    """Add any ``needed`` classes missing from ``host_cf``, copied by name from
    ``donor_cf``.  Their parent classes must already exist in the host (every
    entity carries the ``oIEntityCpntSettings`` / ``oISerializable`` bases)."""
    for name in sorted(needed):
        if _class_index_of(host_cf, name) is not None:
            continue
        donor = donor_cf.classes[_class_index_of(donor_cf, name)]
        if not any(c.class_id == donor.parent_id for c in host_cf.classes):
            raise ModsModalError(
                f"cannot add {name!r}: its parent {donor.parent_id} is absent "
                f"from the host")
        host_cf.classes.append(cooked.ClassDef(
            donor.name, donor.class_id, donor.version_major,
            donor.version_minor, donor.parent_id))


def _remap_class_tags(record: bytes, donor_cf: cooked.CookedFile,
                      host_cf: cooked.CookedFile) -> bytes:
    """Rewrite a cloned record's class-table indices from donor to host.

    Every inner ``BEGIN <u32>`` tag and the record's leading directory u32 is
    an index into the file's OWN class table (verified: in the chain records
    every such position resolves to a valid class).  Each is rewritten to the
    host index of the SAME class name; a name mismatch fails closed.
    """
    def _host_index(donor_idx: int) -> int:
        name = donor_cf.classes[donor_idx].name
        hi = _class_index_of(host_cf, name)
        if hi is None:
            raise ModsModalError(f"class {name!r} absent from host after extend")
        return hi

    out = bytearray(record)
    # Leading directory class index.
    struct.pack_into("<I", out, 0, _host_index(struct.unpack_from("<I", out, 0)[0]))
    # Every post-BEGIN class tag.
    i = 0
    while i + 4 <= len(out):
        if out[i:i + 4] == _BEGIN and i + 8 <= len(out):
            struct.pack_into("<I", out, i + 4,
                             _host_index(struct.unpack_from("<I", out, i + 4)[0]))
            i += 8
            continue
        i += 1
    return bytes(out)


def build_open_trigger(host_bytes: bytes, *, chain_src_bytes: bytes,
                       event: str = TRIGGER_EVENT,
                       modal_resource: str = MODAL_RESOURCE) -> bytes:
    """Append the ``event`` -> spawn-the-mod-modal chain to ``host_bytes``.

    The chain (listener -> executing-methods -> modal handler -> entity
    spawner) is cloned from ``chain_src_bytes`` (``Hero_Display``) and relocated
    onto the host: GUIDs reminted, reference paths moved from the source entity
    onto :data:`HOST_NAME`, the modal resource retargeted to
    :data:`MODAL_RESOURCE`, and — because inner ``BEGIN`` tags index the file's
    own class table — every class index remapped from the source table to the
    host's (extended by one class where needed).
    """
    if not event.isascii() or not event:
        raise ModsModalError(f"event name must be non-empty ASCII: {event!r}")
    chain = _chain(event, modal_resource)
    src_cf = cooked.parse(chain_src_bytes)
    src_names = component_names(chain_src_bytes)

    # Gather the source records + the set of classes they use.
    records, guids, used = [], {}, set()
    for donor, _ in chain:
        if src_names.count(donor) != 1:
            raise ModsModalError(
                f"expected exactly one {donor!r} on {CHAIN_SRC_ENTITY} — game "
                f"update changed its layout?")
        record = src_cf.sections[1 + src_names.index(donor)].payload
        guid = _component_guid(record)
        if guid is None:
            raise ModsModalError(f"{donor!r} carries no instance GUID")
        records.append(record)
        guids[guid] = os.urandom(16)
        used.add(src_cf.classes[struct.unpack_from("<I", record, 0)[0]].name)
        i = 0
        while i + 4 <= len(record):
            if record[i:i + 4] == _BEGIN and i + 8 <= len(record):
                used.add(src_cf.classes[
                    struct.unpack_from("<I", record, i + 4)[0]].name)
                i += 8
                continue
            i += 1

    # Extend the host's class table with whatever the chain needs.
    host_cf = cooked.parse(host_bytes)
    extend_class_table(host_cf, src_cf, used)
    host_extended = cooked.emit(host_cf)
    host_cf = cooked.parse(host_extended)  # re-parse so indices are final

    clones = []
    for record, (donor, swaps) in zip(records, chain, strict=True):
        # GUIDs first, so references BETWEEN the clones land on the clones
        # rather than on the components they were copied from.
        for old, new in guids.items():
            record = record.replace(old, new)
        try:
            record = EA.replace_blob_strings(record, swaps)
        except EA.EntityAppendError as e:
            raise ModsModalError(f"retargeting {donor!r}: {e}") from None
        clones.append(_remap_class_tags(record, src_cf, host_cf))

    out = EA.append_components(host_extended, clones)
    added = set(component_names(out)) - set(component_names(host_bytes))
    expected = {_C_LISTENER, _C_METHODS, _C_HANDLER, _C_SPAWNER}
    if added != expected:
        raise ModsModalError(f"appended {sorted(added)}, expected "
                             f"{sorted(expected)}")

    # Fail closed: the relocation must not have created a reference that
    # resolves to nothing.  Main_Book_Menu is much larger than the chain, so a
    # remap slip would surface here as a dangling path.
    before = _dangling_refs(host_bytes)
    if _dangling_refs(out) - before:
        raise ModsModalError("open-trigger relocation introduced a dangling "
                             "component reference")
    return out


def _dangling_refs(cooked_bytes: bytes) -> set[str]:
    alive = set(component_names(cooked_bytes)) - {""}
    return {s for _, _, s in ES.list_strings(cooked_bytes)
            if s.startswith("[") and "\\" in s
            and s.split("\\")[-1] not in alive}


def _named_section(cf: cooked.CookedFile, cooked_bytes: bytes,
                   cpnt_name: str) -> cooked.Section:
    matches = [i for i, n in enumerate(component_names(cooked_bytes))
               if n == cpnt_name]
    if len(matches) != 1:
        raise ModsModalError(
            f"expected exactly one component named {cpnt_name!r}, "
            f"found {len(matches)}")
    return cf.sections[1 + matches[0]]


#: A native sender on the host whose event we rename to prove the override is
#: read at all.  It must be one that RELIABLY FIRES: the first pick was a
#: HIDE_TAB sender, and HIDE_TAB never fires during startup at all, so the
#: probe proved nothing.  SHOW_TAB fires 7x every launch as the book builds
#: its tabs, giving a countable baseline (6 + the token).  Worst case the
#: compendium tab stops appearing, which `rsmm apply` undoes.
LOADED_PROBE_CPNT = "Show Compendium Tab Event"
LOADED_PROBE_EVENT = "RSMM_HOST_LOADED"


def probe_host_loaded(host_bytes: bytes,
                      event: str = LOADED_PROBE_EVENT) -> bytes:
    """Rename one NATIVE sender's event so the log proves the host override
    is actually loaded.

    Every inert-chain result so far assumes the game reads our file. Nothing
    has tested that. This edits a component the game has always driven, so if
    ``event`` shows up on the event bus the override is live and the fault is
    in our appended chain; if it never fires, the file is not being read and
    the chain was never the problem.
    """
    cf = cooked.parse(host_bytes)
    sec = _named_section(cf, host_bytes, LOADED_PROBE_CPNT)
    sec.payload = EA.replace_blob_strings(sec.payload, {"SHOW_TAB": event})
    return cooked.emit(cf)


#: Native spawner we clone to test appending on its own.
APPEND_PROBE_DONOR = "Compendium Tab Spawner"
APPEND_PROBE_CPNT = "RSMM Append Probe Spawner"
_APPEND_PROBE_FROM = "Book_Menu\\Book_Compendium_Tab_Mesh_Controller.entity.ot"
_APPEND_PROBE_TO = "Book_Menu\\Book_Tuto_Tab_Mesh_Controller.entity.ot"


def probe_append_native(host_bytes: bytes) -> bytes:
    """Append ONE component built only from classes the host already has.

    Separates two causes that the modal chain conflates.  That chain both
    appends components AND injects two classes the host never had
    (``ExecutingMethodsEntityCpntSettings``, ``ModalHandlerEntityCpntSettings``)
    via :func:`extend_class_table`, so its silence indicts either appending or
    the class-table extension — no way to tell which.

    This clones a NATIVE tab spawner, so the class table is untouched and only
    appending is under test.  The clone spawns the Tuto tab controller into the
    Compendium tab's 3d node: if the compendium tab renders as a tuto tab,
    appending works and the extended classes are the real problem.  If the book
    looks stock, appending itself is inert on this host.
    """
    cf = cooked.parse(host_bytes)
    record = _named_section(cf, host_bytes, APPEND_PROBE_DONOR).payload
    guid = _component_guid(record)
    if guid is None:
        raise ModsModalError(f"{APPEND_PROBE_DONOR!r} carries no instance GUID")
    record = record.replace(guid, os.urandom(16))
    record = EA.replace_blob_strings(record, {
        APPEND_PROBE_DONOR: APPEND_PROBE_CPNT,
        _APPEND_PROBE_FROM: _APPEND_PROBE_TO,
    })
    return EA.append_components(host_bytes, [record])


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
