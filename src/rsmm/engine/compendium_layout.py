"""Keep the book's item compendium inside its frames when mods add items.

The Objects tab (``GameUis/All_Book_Pages/MagicalObjects_Compendium_Page``) is
one native controller, ``MagicalObjectsCompendiumPageUiController``, with a
frame per tier (``Common_Content_Frame`` .. ``Cursed_Content_Frame``) and, in
its settings at ``+0x218``, an ``int[6]`` of COLUMNS per tier (slot = the
item's Quality, see ``magic_item_cook.QUALITY``; slot 5 has no frame). Read
from the 2026-10 build:

* ``FUN_14042b2f0`` fills a frame from the item pool: item ``i`` goes to
  column ``i % cols``, row ``i / cols``;
* ``FUN_14042b960`` lays it out: a cell is ``frame width / cols`` SQUARE, the
  icon ``cell * 0.9``, row ``r`` at ``y = r * cell``.

The frame's height is fixed by the window layout and every tier ships 10
columns, sized for its vanilla pool (Common/Rare/Epic 10 items = one row,
Legendary/Cursed 14 = two). An eleventh Common item opens a second row the
frame has no room for, and it draws over the next tier.

So when a tier outgrows its vanilla rows, it gets the fewest columns whose
grid is no taller than vanilla's: ``cols0 * ceil(n / c) <= rows0 * c`` in units
of the frame width. More columns means smaller icons, never overflow. The
frame sizes themselves were not readable statically (the layout stores no
frame name), so the vanilla grid is the only height this can trust.
"""

from __future__ import annotations

import math
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path

from . import entity_fields as EF
from . import entity_graph as EG
from . import versiondef as VD
from .paths import BACKUP_SUFFIX

PAGE_DECODED = ("EntitySettings/GameUis/All_Book_Pages/"
                "MagicalObjects_Compendium_Page.entity.ot.EntitySettingsResource.gen")
_CONTROLLER = "MagicalObjectsCompendiumPageUiControllerEntityCpntSettings"
#: Column slot per tier folder: the order of the frames and of the Quality int.
TIERS = ("Common", "Rare", "Epic", "Legendary", "Cursed")


def _columns_field(data: bytes) -> tuple[EG.Component, EF.Field]:
    hits = [c for c in EG.parse(data).components if c.cls == _CONTROLLER]
    if len(hits) != 1:
        raise ValueError(f"{len(hits)} compendium controllers; expected 1")
    c = hits[0]
    # The int[6] is the raw run right after the six frame pickers: a u32 count
    # (6) then six u32s. Found by shape, not by position, so a reordered
    # build fails closed.
    for f in EF.fields(c):
        if f.kind == "bytes" and f.size >= 28:
            raw = c.body[f.offset:f.offset + 28]
            if struct.unpack_from("<I", raw)[0] == 6:
                return c, f
    raise ValueError("compendium column array not found")


def read_columns(data: bytes) -> list[int]:
    c, f = _columns_field(data)
    return list(struct.unpack_from("<6I", c.body, f.offset + 4))


def set_columns(data: bytes, cols: list[int]) -> bytes:
    from .entity_graph_edit import EntityFile
    c, f = _columns_field(data)
    ef = EntityFile(data)
    p = ef.objects[c.index - 1]
    struct.pack_into("<6I", p, len(p) - len(c.body) + f.offset + 4, *cols)
    out = ef.to_bytes()
    if read_columns(out) != list(cols):
        raise ValueError("compendium columns did not take")
    return out


def fit_columns(n: int, cols0: int, n0: int) -> int:
    """The fewest columns (never fewer than ``cols0``) that lay ``n`` items out
    no taller than ``n0`` items took at ``cols0``."""
    if cols0 <= 0:
        return cols0
    rows0 = max(1, math.ceil(n0 / cols0))
    c = cols0
    while cols0 * math.ceil(n / c) > rows0 * c:
        c += 1
    return c


def tier_counts(versiondef_gen: bytes) -> Counter:
    loc = VD._find_mo_vector(versiondef_gen)
    if loc is None:
        raise ValueError("magical-object vector not found in the versiondef")
    co, _end, cnt = loc
    return Counter(VD._mo_entry_rarity(e[2])
                   for e in VD._mo_vector_entries(versiondef_gen, co, cnt))


def fitted(page: bytes, vanilla: Counter, now: Counter) -> list[int]:
    cols = read_columns(page)
    for i, tier in enumerate(TIERS):
        cols[i] = fit_columns(now[tier], cols[i], vanilla[tier])
    return cols


def sync_compendium_columns(game_dir: Path, dry_run: bool, page: Path | None,
                            page_owner: str | None = None) -> int:
    """Widen the compendium's per-tier grids to fit the installed item pool.

    Runs after :func:`versiondef.sync_versiondef` (it reads the pool that wrote)
    and follows its rule: the page is backed up once and rebuilt from the
    pristine copy each apply; with nothing to widen the pristine copy goes
    back. ``restore --all`` returns it through its stale-backup sweep. A mod
    that overrides the page owns it, and it is left alone. Under ``--dry-run``
    the pool is the one the last apply wrote. Returns files changed (0/1).
    """
    gen = VD._locate_cooked_by_leaf(game_dir, VD.VERSIONDEF_GEN_LEAF)
    if gen is None or page is None or not page.exists():
        return 0
    if page_owner:
        print(f"  [warn] {page_owner} replaces the item compendium page; its "
              f"grids are not widened for added items", file=sys.stderr)
        return 0
    vd_bak = gen.with_name(gen.name + BACKUP_SUFFIX)
    bak = page.with_name(page.name + BACKUP_SUFFIX)
    pristine = (bak if bak.exists() else page).read_bytes()
    try:
        vanilla = tier_counts((vd_bak if vd_bak.exists() else gen).read_bytes())
        now = tier_counts(gen.read_bytes())
        base = read_columns(pristine)
        cols = fitted(pristine, vanilla, now)
    except ValueError as e:
        print(f"  [warn] item compendium layout not adjusted: {e}", file=sys.stderr)
        return 0
    if cols == base:
        if bak.exists():
            if not dry_run:
                shutil.copy2(bak, page)
                bak.unlink()
            print("  [compendium] restored the vanilla item grid")
            return 1
        return 0
    patched = set_columns(pristine, cols)
    if patched == page.read_bytes():
        return 0
    wider = ", ".join(f"{t} {base[i]}->{cols[i]}" for i, t in enumerate(TIERS)
                      if cols[i] != base[i])
    print(f"  [compendium] widening item grids to fit added items ({wider} columns)")
    if not dry_run:
        if not bak.exists():
            shutil.copy2(page, bak)
        page.write_bytes(patched)
    return 1
