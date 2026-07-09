"""In-game mod menu — phase 5: real buttons appended to the Tuto frame page.

EXPERIMENTAL. Phase 3's social-page clone rendered over every page (its
native ``Dt Social Book Page`` controller doesn't participate in the book's
page show/hide flow) and was scrapped. V2 instead appends button components
directly into ``Tuto_Compendim_Page`` — the page frame that already renders
correctly in the Tutorial slot and hosts the phase-1 mod list:

* A button on this page = an ``oCEntityCpntWindowUiSettings`` cpnt (window,
  placement anchors, links the desc BY NAME, registers into the page's
  ``Page Nave Zone``) + an ``oCUIGameButtonDesc`` (position x/y fractions,
  textures). Both are cloned from the page's own ``Next Button`` /
  ``Next_Button`` pair via the component-append primitive
  (``entity_append``) — no foreign controllers, no new assets.
* The page controller doesn't know the cloned buttons, so their press
  listeners are unwired; ``hook_ui.cpp`` skips the native commit for
  listenerless widgets and just emits ``ui:press`` — the generated init.lua
  matches the ``RSMM_*`` desc names in the event's strings.

The 3DBookController's tab PICKER array is hardcoded at 5
(BookController_ResolveSettings), so a data-only 6th tab is out; the page
lives on the Tutorial slot. ``build_bookmark_assets`` (phase 4, opt-in) is
the 6th-physical-bookmark experiment — spawn/position are runtime-indexed by
the book controller, in-game inert so far.
"""

from __future__ import annotations

import struct
from pathlib import Path

from . import cipher, cooked
from . import entity_append as EA
from . import entity_strings as ES

#: The Tutorial tab's frame page (prev/next arrows + sub-page spawners) —
#: donor AND target: we override it with itself plus appended buttons.
FRAME_PAGE_DECODED = ("EntitySettings\\GameUis\\All_Book_Pages\\"
                      "Tuto_Compendim_Page.entity.ot.EntitySettingsResource.gen")

_WINDOW_CLASS = "oCEntityCpntWindowUiSettings"
_DESC_CLASS = "oCUIGameButtonDesc"

#: Lua-facing action names. The desc name is the stable identifier the
#: ui:press payload can carry (init.lua matches these; keep in sync via
#: these constants only).
BUTTON_NEXT = "RSMM_Next_Mod"
BUTTON_PREV = "RSMM_Prev_Mod"
BUTTON_TOGGLE = "RSMM_Toggle_Mod"

#: (window cpnt name, desc name, x fraction) — donor Next arrow sits at
#: x=0.9908/y=0.5; ours line up mid-page, clear of both arrows.
BUTTONS: list[tuple[str, str, float]] = [
    ("RSMM Btn Next", BUTTON_NEXT, 0.68),
    ("RSMM Btn Prev", BUTTON_PREV, 0.55),
    ("RSMM Btn Toggle", BUTTON_TOGGLE, 0.42),
]

#: The donor desc's x-position float (0.99078f) as raw little-endian bytes —
#: unique inside the desc record; replaced per clone to place the button.
_DONOR_X_BYTES = struct.pack("<f", struct.unpack("<f", b"\xa4\x70\x7d\x3f")[0])


class ModsTabError(ValueError):
    pass


def _pristine_bytes(cooking_root: Path, dec2enc: dict[str, str],
                    dec: str) -> bytes:
    enc = dec2enc.get(dec) or cipher.encode(dec.replace("/", "\\"))
    p = cooking_root / Path(*enc.replace("\\", "/").split("/"))
    bak = p.with_name(p.name + ".rsmm.bak")
    if bak.is_file():
        return bak.read_bytes()
    if not p.is_file():
        raise ModsTabError(f"cooked file not found: {p} — wrong game dir?")
    return p.read_bytes()


def build_tab_assets(cooking_root: Path, dec2enc: dict[str, str]) -> dict[str, bytes]:
    """Tuto frame page override with appended RSMM buttons:
    ``{decoded path token: bytes}``. Reads the donor page from the user's
    install so no game-derived bytes ever ship with rsmm."""
    frame_dec = FRAME_PAGE_DECODED.replace("\\", "/")
    if frame_dec not in dec2enc:
        raise ModsTabError(f"asset map is missing {frame_dec!r} — game "
                           f"update? re-run 'rsmm rebuild-asset-map'")
    page = _pristine_bytes(cooking_root, dec2enc, frame_dec)
    cf = cooked.parse(page)
    try:
        win_cls = next(i for i, c in enumerate(cf.classes)
                       if c.name == _WINDOW_CLASS)
        desc_cls = next(i for i, c in enumerate(cf.classes)
                        if c.name == _DESC_CLASS)
    except StopIteration:
        raise ModsTabError("button classes missing from the frame page — "
                           "game update changed its layout?") from None
    donor_win = cf.sections[EA.find_component(cf, b"Next Button",
                                              win_cls)].payload
    donor_desc = cf.sections[EA.find_component(cf, b"Next_Button",
                                               desc_cls)].payload
    if donor_desc.count(_DONOR_X_BYTES) != 1:
        raise ModsTabError("donor button x-position bytes not unique — "
                           "game update moved the Next arrow?")

    records: list[bytes] = []
    for win_name, desc_name, x in BUTTONS:
        win = EA.replace_blob_strings(donor_win, {
            "Next Button": win_name,
            "Next_Button": desc_name,
        })
        records.append(EA.remint_guid(win))
        desc = EA.replace_blob_strings(donor_desc, {"Next_Button": desc_name})
        desc = desc.replace(_DONOR_X_BYTES, struct.pack("<f", x))
        records.append(desc)

    return {frame_dec: EA.append_components(page, records)}


# --- phase 4: 6th physical bookmark on the 3D book (EXPERIMENTAL) ----------

#: Book scene entity holding the tab 3d-nodes, tab spawners and the
#: Dt Book Controller component.
BOOK_SCENE_DECODED = ("EntitySettings\\Book_Menu\\"
                      "Book_Mesh_Controller.entity.ot.EntitySettingsResource.gen")
#: Donor bookmark entity (tab plane mesh + Dt Book Tab Controller).
TUTO_TAB_DECODED = ("EntitySettings\\Book_Menu\\"
                    "Book_Tuto_Tab_Mesh_Controller.entity.ot"
                    ".EntitySettingsResource.gen")
#: Our bookmark clone ships as a NEW asset next to the donors.
RSMM_TAB_DECODED = ("EntitySettings\\Book_Menu\\"
                    "RSMM_Tab_Mesh_Controller.entity.ot"
                    ".EntitySettingsResource.gen")

_NODE_CLASS = "oCEntityCpnt3dNodeSettings"
_SPAWNER_CLASS = "oCEntityCpntEntitySpawnerSettings"

#: Donor tab uses the compendium art; give ours the pad-input art so the new
#: bookmark is visually distinct in the proof playtest.
_TAB_MATERIAL_SWAP = {
    "Mechas\\BookMenu\\M_Book_Compendium_Tab.mat.ot":
        "Mechas\\BookMenu\\M_Book_Input_Tab.mat.ot",
}

_NODE_SWAPS = {"Tuto Tab 3d Node": "RSMM Tab 3d Node"}
_SPAWNER_SWAPS = {
    "Tuto Tab Spawner": "RSMM Tab Spawner",
    "Book_Menu\\Book_Tuto_Tab_Mesh_Controller.entity.ot":
        "Book_Menu\\RSMM_Tab_Mesh_Controller.entity.ot",
    "[Entity 3d Node] Book_Mesh_Controller\\Tabs\\Tuto Tab 3d Node":
        "[Entity 3d Node] Book_Mesh_Controller\\Tabs\\RSMM Tab 3d Node",
}


def _class_index(cf: cooked.CookedFile, name: str) -> int:
    for i, c in enumerate(cf.classes):
        if c.name == name:
            return i
    raise ModsTabError(f"class {name!r} not in entity class table — "
                       f"game update changed the book scene?")


def build_bookmark_assets(cooking_root: Path,
                          dec2enc: dict[str, str]) -> dict[str, bytes]:
    """6th physical bookmark: ``{decoded path token: bytes}``.

    Appends a cloned tab 3d-node + tab spawner to the book scene
    (component-append primitive) and ships the spawned bookmark entity as a
    new asset. Proof-of-path: the bookmark is spawn-tested visual-only —
    the book controller's 5-slot picker array can't reference it, so it is
    not clickable until the Nav_Zone click chain is wired.
    """
    scene_dec = BOOK_SCENE_DECODED.replace("\\", "/")
    tuto_dec = TUTO_TAB_DECODED.replace("\\", "/")

    def _pristine(dec: str) -> bytes:
        # The Book_Menu scene files are not all in the shipped asset map —
        # the cipher is fixed, so encode the decoded path directly.
        enc = dec2enc.get(dec) or cipher.encode(dec.replace("/", "\\"))
        p = cooking_root / Path(*enc.replace("\\", "/").split("/"))
        bak = p.with_name(p.name + ".rsmm.bak")
        if bak.is_file():
            return bak.read_bytes()
        if not p.is_file():
            raise ModsTabError(f"cooked file not found: {p} — wrong game dir?")
        return p.read_bytes()

    scene_bytes = _pristine(scene_dec)
    cf = cooked.parse(scene_bytes)
    EA.validate_layout(cf)
    node_cls = _class_index(cf, _NODE_CLASS)
    spawner_cls = _class_index(cf, _SPAWNER_CLASS)

    node = cf.sections[EA.find_component(cf, b"Tuto Tab 3d Node",
                                         node_cls)].payload
    spawner = cf.sections[EA.find_component(cf, b"Tuto Tab Spawner",
                                            spawner_cls)].payload
    node = EA.remint_guid(EA.replace_blob_strings(node, _NODE_SWAPS))
    spawner = EA.remint_guid(EA.replace_blob_strings(spawner, _SPAWNER_SWAPS))
    scene = EA.append_components(scene_bytes, [node, spawner])

    bookmark = ES.replace_strings(_pristine(tuto_dec), dict(_TAB_MATERIAL_SWAP))

    return {
        scene_dec: scene,
        RSMM_TAB_DECODED.replace("\\", "/"): bookmark,
    }
