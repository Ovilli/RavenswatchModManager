"""A "Mods" button in the game's pause menu, next to Settings.

The pause menu's buttons are data: `Escape_Menu_Model`'s
`ButtonListUiControllerEntityCpnt` holds a count and one inline item per button
(Continue, Settings, Bug report, Abandon, Quit to main menu, Quit to desktop).
Each item carries its label (a text value), the value that shows or hides it,
and a callback: the pause menu controller plus an action key. The controller's
vtable slot 19 maps the six keys 0x1b4ab3b6..bb to its six handlers.

The Mods item is the Settings item with a plain "Mods" label (the Continue
item's shape: no localisation bank, index -1) and the action key
`MODS_ACTION`, which only the loader knows (hook_settings_menu.cpp): it runs
the Settings handler, then switches the page to the Mods tab. So the button is
only installed while a loader that answers the key is in the game and its
native menu is not switched off (RSMM_DISABLE_NATIVE_MENU); without it the key
would resolve to nothing. `apply` runs before `install-loader` plants the DLL
in the restore -> apply -> install-loader cycle, so install-loader runs the
same sync (`sync_installed`).

Applied like the compendium grids (`compendium_layout`): the file is backed up
once and rebuilt from the pristine copy each apply, the pristine copy goes back
when the menu is off, and `restore --all` returns it through its stale-backup
sweep. Measured on the 2026-10 build.
"""

from __future__ import annotations

import shutil
import struct
import sys
from pathlib import Path

from . import entity_fields as EF
from . import entity_graph as EG
from .entity_graph_edit import EntityFile
from .paths import BACKUP_SUFFIX

MENU_DECODED = ("EntitySettings/GameUis/Common_Ui/"
                "Escape_Menu_Model.entity.ot.EntitySettingsResource.gen")
FLAG = "RSMM_DISABLE_NATIVE_MENU"
#: A string the native-menu loader carries (its log tag); older DLLs do not.
LOADER_MARKER = b"[native-menu] pause menu Mods button armed"
#: Must match kModsAction in src/loader/src/hook_settings_menu.cpp.
MODS_ACTION = 0x52534D4D
_LIST = "Button List Ui Controller"
_SETTINGS_ACTION = 0x1B4AB3B7
LABEL = "Mods"


class EscapeMenuError(ValueError):
    pass


def _items(ef: EntityFile) -> tuple[EG.Component, EF.Field, list[EF.Field]]:
    """The button list component, its count field and its items (in order)."""
    c = ef.component(_LIST)
    fields = EF.fields(c)
    for i, f in enumerate(fields):
        if f.kind != "bytes" or f.size != 4:
            continue
        n = struct.unpack_from("<I", c.body, f.offset)[0]
        items = fields[i + 1:i + 1 + n]
        if n and len(items) == n and all(x.kind == "obj" for x in items):
            return c, f, items
    raise EscapeMenuError(f"{_LIST}: no counted button list")


def _action_at(c: EG.Component, f: EF.Field, key: int) -> int:
    return c.body.find(struct.pack("<I", key), f.offset, f.offset + f.size)


def _label_span(c: EG.Component, f: EF.Field) -> tuple[int, int]:
    """Body offsets of an item's label (its only `text` value)."""
    sub = EG.Component(0, c.cls, "", "", b"", None,
                       body=c.body[f.offset:f.offset + f.size], classes=c.classes)
    texts = [t for t in EG.tokens(sub) if t.kind == "value" and t.text.startswith("text ")]
    if len(texts) != 1:
        raise EscapeMenuError(f"{f.name}: {len(texts)} text values, expected the label")
    return f.offset + texts[0].offset, f.offset + texts[0].offset + texts[0].size


def _plain_label(label: bytes, text: str) -> bytes:
    """``label`` (a localised text value) re-written as an unlocalised one, the
    Continue item's shape: text, kind 3, empty sheet/bank, index -1, empty key."""
    if label[:4] != EG._BEGIN or len(label) < 24:
        raise EscapeMenuError("label is not a text value")
    t = text.encode("utf-8")
    # Keep MARK_BEGIN, class index, union type and pad; keep MARK_END.
    return (label[:16] + struct.pack("<I", len(t)) + t
            + struct.pack("<IIIiI", 3, 0, 0, -1, 0) + label[-4:])


def has_mods_button(gen: bytes) -> bool:
    ef = EntityFile(gen, "Escape_Menu_Model")
    c, _count, items = _items(ef)
    return any(_action_at(c, f, MODS_ACTION) >= 0 for f in items)


def add_mods_button(gen: bytes) -> bytes:
    """``gen`` (the pause menu model) with a Mods item right after Settings."""
    ef = EntityFile(gen, "Escape_Menu_Model")
    c, count, items = _items(ef)
    if any(_action_at(c, f, MODS_ACTION) >= 0 for f in items):
        return gen
    src = next((f for f in items if _action_at(c, f, _SETTINGS_ACTION) >= 0), None)
    if src is None:
        raise EscapeMenuError("no Settings button to copy")
    a, b = _label_span(c, src)
    k = _action_at(c, src, _SETTINGS_ACTION)
    if not a < b <= k:
        raise EscapeMenuError("Settings item: label is not before its action key")
    body = c.body
    item = (body[src.offset:a] + _plain_label(body[a:b], LABEL)
            + body[b:k] + struct.pack("<I", MODS_ACTION) + body[k + 4:src.offset + src.size])
    end = src.offset + src.size          # the list order is the menu's order
    p = ef.objects[c.index - 1]
    at = len(p) - len(body)
    p[at + end:at + end] = item
    struct.pack_into("<I", p, at + count.offset, len(items) + 1)
    out = ef.to_bytes()
    # Prove it: the file re-reads with one more button, ours right after Settings.
    c2, _c, items2 = _items(EntityFile(out, "Escape_Menu_Model"))
    after = items.index(src) + 1
    if len(items2) != len(items) + 1 or _action_at(c2, items2[after], MODS_ACTION) < 0:
        raise EscapeMenuError("the Mods button did not read back")
    return out


def loader_answers(game_dir: Path) -> bool:
    """Is a loader that knows MODS_ACTION installed?"""
    try:
        return LOADER_MARKER in (game_dir / "winhttp.dll").read_bytes()
    except OSError:
        return False


def sync_installed(game_dir: Path) -> int:
    """`install-loader`'s pass: find the installed pause menu itself and sync
    it, unless a mod owns it (per apply's state file)."""
    import json

    from .paths import COOKING_REL
    from .versiondef import _locate_cooked_by_leaf
    menu = _locate_cooked_by_leaf(game_dir, MENU_DECODED.rsplit("/", 1)[1])
    if menu is None:
        return 0
    try:
        state = json.loads((game_dir / COOKING_REL / ".rsmm_state.json").read_text("utf-8"))
        active = state.get("active", {})
    except (OSError, ValueError, AttributeError):
        active = {}
    owner = next((v.get("mod") for k, v in active.items()
                  if isinstance(v, dict) and k.replace("/", "\\").endswith(menu.name)), None)
    return sync_escape_menu(game_dir, False, menu, owner)


def sync_escape_menu(game_dir: Path, dry_run: bool, menu: Path | None,
                     menu_owner: str | None = None) -> int:
    """Install or remove the pause menu's Mods button to match the loader in
    the game and its native menu flag. Returns files changed (0/1)."""
    from .loader_flags import FLAGS_FILE, read_flags

    if menu is None or not menu.exists():
        return 0
    if menu_owner:
        print(f"  [warn] {menu_owner} replaces the pause menu; no Mods button "
              f"is added to it", file=sys.stderr)
        return 0
    bak = menu.with_name(menu.name + BACKUP_SUFFIX)
    if FLAG in read_flags(game_dir / FLAGS_FILE) or not loader_answers(game_dir):
        if bak.exists():
            if not dry_run:
                shutil.copy2(bak, menu)
                bak.unlink()
            print("  [pause menu] removed the Mods button")
            return 1
        return 0
    pristine = (bak if bak.exists() else menu).read_bytes()
    try:
        patched = add_mods_button(pristine)
    except ValueError as e:
        print(f"  [warn] pause menu Mods button not added: {e}", file=sys.stderr)
        return 0
    if patched == menu.read_bytes():
        return 0
    print("  [pause menu] adding a Mods button next to Settings")
    if not dry_run:
        if not bak.exists():
            shutil.copy2(menu, bak)
        menu.write_bytes(patched)
    return 1
