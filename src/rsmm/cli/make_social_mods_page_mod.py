#!/usr/bin/env python3
"""Add a 7th page slot ("Mods") to Social_Book_Page by cloning the
existing Friend_List_Recent slot.

Why slot 3 (Recent Player) instead of slot 0 (News):
  - Friend-list pages use a smaller button/list visual style that
    looks more like a settings menu than the News tile layout.
  - The list is empty without recent players, so the resulting Mods
    page is a clean empty Friend-list panel — a much better blank
    canvas than the News-tile heavy clone we used to ship.
  - No cloned entity file is needed: slot 7 points at the existing
    Friend_List_Recent.entity.ot, so we sidestep the cloned-entity
    audio fragility entirely.

Patch steps:

  1. Locate Dt Social Book Page Section 10 inside Social_Book_Page.
  2. Bump the slot count u32 from 6 -> 7.
  3. Take slot 3 (Friend_List_Recent) verbatim and append it after
     slot 5 as the new slot 7.
  4. In the appended copy only, swap the text-key lpstr
     Book_Page_Recent_Player -> Book_Page_DLC and the matching u32
     ID. The slot-level lpstr length can change here because Dt
     Social Book Page tolerates byte-length deltas (proven in
     Phase 1).
  5. MainMenuMods adds Book_Page_DLC=Mods so the tab reads "Mods".

This obsoletes the earlier Phase 2 approach (cloned SocialNewsPage
entity + UsedRscList triplet + texture-hide tricks). The mod folder
only ships the patched Social_Book_Page; nothing else.
"""

from __future__ import annotations

from rsmm.engine.paths import (
    REPO_ROOT as REPO_DIR,
    DATA_DIR,
    MODS_DIR,
    ASSET_MAP_JSON,
    ASSET_MAP_CSV,
    DEFAULT_GAME_DIR as DEFAULT_GAME,
    COOKING_SUBDIR,
)
import argparse
import struct
import sys
from pathlib import Path


SOCIAL_BOOK_PAGE_ENC = (
    "MzidisFqiidzyv/KgxqJdv/Wll_Brrm_Tgyqv!Frbdgl_Brrm_Tgyq."
    "qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz"
)

MARK_BEGIN = bytes.fromhex("1111bbaa")
MARK_END = bytes.fromhex("2222bbaa")

SLOT_MARKER = MARK_BEGIN + b"\x1d\x00\x00\x00"

DT_SOCIAL_BOOK_PAGE_NAME = "Dt Social Book Page"
EXPECTED_SLOT_COUNT = 6

# Slot 3 = Friend_List_Recent ("Recent Player") in the Dt Social Book Page array.
SOURCE_SLOT_INDEX = 3

SOURCE_TEXT_KEY = "Book_Page_Recent_Player"   # 23 chars
MODS_TEXT_KEY = "Book_Page_DLC"               # 13 chars

SOURCE_TEXT_KEY_ID = 0x14b  # 331
MODS_TEXT_KEY_ID = 0x1e3    # 483

# Entity path divergence: the engine's resource hashmap (FUN_140487040)
# caches by path. If slot 7 references the same path as slot 3, both
# slots resolve to the same handle and render the same UI. Swap the
# cloned slot's entity path to a fake one; the live loader hook
# (loader/src/hook_engine.cpp) intercepts the lookup and returns a
# different cached handle so the rendered page can diverge.
SOURCE_ENTITY_PATH = (
    "GameUis\\All_Book_Pages\\Social\\Friend_List_Recent.entity.ot"
)
MODS_ENTITY_PATH = (
    "GameUis\\All_Book_Pages\\Social\\Mods_List.entity.ot"
)


def lpstr(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def find_balanced_end(data: bytes, start: int) -> int:
    depth = 1
    p = start
    n = len(data)
    while p + 4 <= n:
        t = data[p:p + 4]
        if t == MARK_BEGIN:
            depth += 1
            p += 4
            continue
        if t == MARK_END:
            depth -= 1
            p += 4
            if depth == 0:
                return p
            continue
        p += 1
    return -1


def locate_class_table_end(data: bytes) -> int:
    p = 0
    p += 4  # header_field_0
    p += 4  # flags
    if data[p:p + 4] == MARK_BEGIN:
        p += 4
    else:
        slen = struct.unpack_from("<I", data, p)[0]
        p += 4 + slen
        p += 4
        p += 1
        if data[p:p + 4] != MARK_BEGIN:
            raise ValueError(
                f"expected MARK_BEGIN at 0x{p:x}, got {data[p:p+4].hex()}"
            )
        p += 4
    class_count = struct.unpack_from("<I", data, p)[0]
    p += 4
    for _ in range(class_count):
        nlen = struct.unpack_from("<I", data, p)[0]
        p += 4 + nlen
        p += 16
    if data[p:p + 4] != MARK_END:
        raise ValueError(
            f"expected MARK_END at 0x{p:x}, got {data[p:p+4].hex()}"
        )
    p += 4
    return p


def find_section_for_internal_name(
    data: bytes, internal_name: str, class_table_end: int
) -> tuple[int, int]:
    needle = lpstr(internal_name)
    pos = data.find(needle, class_table_end)
    while pos != -1:
        for window in range(48, 80):
            outer = pos - window
            if outer < class_table_end:
                continue
            if data[outer:outer + 4] != MARK_BEGIN:
                continue
            if data[outer + 8:outer + 12] != MARK_BEGIN:
                continue
            if data[outer + 16:outer + 36] != b"\x00" * 20:
                continue
            if data[outer + 36:outer + 40] != MARK_END:
                continue
            if outer + 56 == pos:
                end = find_balanced_end(data, outer + 4)
                if end == -1:
                    raise ValueError(
                        f"unterminated section for {internal_name!r}"
                    )
                return outer, end
        pos = data.find(needle, pos + 1)
    raise ValueError(
        f"section not found for internal name {internal_name!r}"
    )


def find_slot_starts(payload: bytes) -> list[int]:
    starts = []
    p = 0
    while True:
        idx = payload.find(SLOT_MARKER, p)
        if idx == -1:
            break
        starts.append(idx)
        p = idx + len(SLOT_MARKER)
    return starts


def replace_lpstr_exact(buf: bytes, old: str, new: str) -> bytes:
    old_b = lpstr(old)
    new_b = lpstr(new)
    out = buf
    while True:
        i = out.find(old_b)
        if i == -1:
            break
        out = out[:i] + new_b + out[i + len(old_b):]
    return out


def replace_u32_after_xls(buf: bytes, old_id: int, new_id: int) -> bytes:
    xls_lpstr = lpstr("Common~GAM.xls")
    i = buf.find(xls_lpstr)
    if i == -1:
        raise ValueError("Common~GAM.xls lpstr not found in slot")
    after = i + len(xls_lpstr)
    cur_id = struct.unpack_from("<I", buf, after)[0]
    if cur_id != old_id:
        raise ValueError(
            f"slot text-key u32 = 0x{cur_id:x}, expected 0x{old_id:x}"
        )
    out = bytearray(buf)
    struct.pack_into("<I", out, after, new_id)
    return bytes(out)


def replace_entity_path(buf: bytes, old: str, new: str) -> bytes:
    """Swap an lpstr entity path inside the cloned slot. Required occurs
    >= 1 (engine slots may carry the path more than once across pickers);
    we replace every occurrence inside the slot bytes only.
    """
    old_b = lpstr(old)
    new_b = lpstr(new)
    occurrences = 0
    out = buf
    while True:
        i = out.find(old_b)
        if i == -1:
            break
        out = out[:i] + new_b + out[i + len(old_b):]
        occurrences += 1
    if occurrences == 0:
        raise ValueError(
            f"entity path {old!r} not found in cloned slot bytes"
        )
    print(f"  swapped entity path {old!r} -> {new!r} "
          f"({occurrences} occurrence(s))")
    return out


def build_mods_slot(source_slot_bytes: bytes) -> bytes:
    """Take a verbatim slot copy (here: slot 3, Friend_List_Recent) and
    repurpose it as the new slot 7. Swap (a) the text-bank reference so
    the tab label is sourced from Book_Page_DLC, and (b) the entity-path
    lpstr so the resource hashmap resolves to a different cache slot.
    Picker GUIDs and internal structure are kept intact.
    """
    out = source_slot_bytes
    out = replace_u32_after_xls(out, SOURCE_TEXT_KEY_ID, MODS_TEXT_KEY_ID)
    out = replace_lpstr_exact(out, SOURCE_TEXT_KEY, MODS_TEXT_KEY)
    out = replace_entity_path(out, SOURCE_ENTITY_PATH, MODS_ENTITY_PATH)
    return out


def patch_social_book_page(data: bytes) -> tuple[bytes, bytes]:
    cte = locate_class_table_end(data)
    sec_begin, sec_end = find_section_for_internal_name(
        data, DT_SOCIAL_BOOK_PAGE_NAME, cte
    )
    payload = data[sec_begin + 4:sec_end - 4]
    plen = len(payload)
    slot_starts = find_slot_starts(payload)
    if len(slot_starts) != EXPECTED_SLOT_COUNT:
        raise RuntimeError(
            f"expected {EXPECTED_SLOT_COUNT} slots, got {len(slot_starts)}"
        )
    count_off = slot_starts[0] - 4
    count = struct.unpack_from("<I", payload, count_off)[0]
    if count != EXPECTED_SLOT_COUNT:
        raise RuntimeError(f"count = {count}, expected {EXPECTED_SLOT_COUNT}")

    src_start = slot_starts[SOURCE_SLOT_INDEX]
    src_end = (
        slot_starts[SOURCE_SLOT_INDEX + 1]
        if SOURCE_SLOT_INDEX + 1 < len(slot_starts)
        else plen
    )
    src_bytes = bytes(payload[src_start:src_end])
    print(f"  source slot {SOURCE_SLOT_INDEX} = "
          f"payload[0x{src_start:x}..0x{src_end:x}) "
          f"len={src_end - src_start} bytes")
    mods_slot = build_mods_slot(src_bytes)
    print(f"  built slot 7 (Mods) = {len(mods_slot)} bytes "
          f"({len(mods_slot) - (src_end - src_start)} byte delta vs source)")

    new_payload = bytearray(payload)
    struct.pack_into("<I", new_payload, count_off, count + 1)
    insertion_off = plen
    new_payload[insertion_off:insertion_off] = mods_slot
    new_payload = bytes(new_payload)

    new_section = (
        data[sec_begin:sec_begin + 4] + new_payload + data[sec_end - 4:sec_end]
    )
    new_data = data[:sec_begin] + new_section + data[sec_end:]
    return new_data, mods_slot


def read_source(cooked: Path, from_backup: bool) -> tuple[bytes, Path]:
    bak = Path(str(cooked) + ".rsmm.bak")
    if from_backup and bak.exists():
        return bak.read_bytes(), bak
    if cooked.exists():
        return cooked.read_bytes(), cooked
    if bak.exists():
        return bak.read_bytes(), bak
    raise FileNotFoundError(f"no source at {cooked} or {bak}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--mod-id", default="SocialModsPage")
    ap.add_argument("--from-backup", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cooking = args.game_dir / COOKING_SUBDIR
    sbp_cooked = cooking / SOCIAL_BOOK_PAGE_ENC.replace("/", "/")

    print(f"reading {sbp_cooked}")
    sbp_bytes, sbp_src = read_source(sbp_cooked, args.from_backup)
    print(f"  src = {sbp_src}  size = {len(sbp_bytes)} bytes")

    new_sbp, mods_slot = patch_social_book_page(sbp_bytes)
    print(f"new Social_Book_Page size = {len(new_sbp)} "
          f"(grew {len(new_sbp) - len(sbp_bytes)} bytes)")

    if args.dry_run:
        print("(dry-run) no files written")
        return 0

    mod_dir = MODS_DIR / args.mod_id
    assets = mod_dir / "assets"

    # Clean up artifacts from the Phase 2 cloned-SocialNewsPage approach.
    # NOTE: do NOT remove _root/DarkTalesResources/UsedRscList.ot — that
    # is now Stage B's UsedRscList patch (written by
    # rsmm mods-list) and the engine needs it to index
    # the new Mods_List encoded path.
    legacy_paths = [
        mod_dir / "assets" / "_root" / "DarkTalesResources" / "_Cooking",
    ]
    for p in legacy_paths:
        if p.is_dir():
            import shutil
            shutil.rmtree(p)
            print(f"  removed legacy dir {p}")
        elif p.is_file():
            p.unlink()
            print(f"  removed legacy file {p}")

    sbp_dest = (
        assets / "EntitySettings" / "GameUis" / "All_Book_Pages"
        / "Social_Book_Page.entity.ot.EntitySettingsResource.gen"
    )
    sbp_dest.parent.mkdir(parents=True, exist_ok=True)
    sbp_dest.write_bytes(new_sbp)
    print(f"wrote {sbp_dest}")

    manifest = mod_dir / "manifest.toml"
    manifest.write_text(
        "[mod]\n"
        f'id = "{args.mod_id}"\n'
        f'name = "Social Mods Page"\n'
        'version = "0.4.0"\n'
        'author = "rsmm"\n'
        'description = "Adds a 7th page (Mods) to the in-game Social tab '
        'by cloning the Friend_List_Recent slot, retargeted at a fake '
        'entity path (Mods_List.entity.ot). The live winhttp loader '
        'redirects that lookup at runtime; without the loader the slot '
        'is empty. Reuses Book_Page_DLC text key for the tab label."\n'
        'enabled = true\n'
    )
    print(f"wrote {manifest}")

    print("Next steps:")
    print("  1) ./rsmm text --mod-id MainMenuMods --lang ALL "
          "--force 'Common~ALL:Book_Page_DLC=Mods'")
    print("  2) ./rsmm apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
