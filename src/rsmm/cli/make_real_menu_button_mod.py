#!/usr/bin/env python3
"""
Generate a mod that adds a *real* extra button to Ravenswatch's title menu by:

  1) cloning the Discord-button entity sections (Spawner + Text) inside the
     cooked Title_Menu_Ui resource,
  2) giving each clone a fresh 128-bit GUID,
  3) renaming the internal entity paths ("Discord Button" -> "Mods Button"),
  4) fixing the Text clone's internal back-reference (target GUID + path
     string) so it points to the new Spawner clone,
  5) bumping the "State Init" picker array count from 10 to 12,
  6) appending two new picker entries (Text + Spawner) inside the State
     Init section so the engine actually instantiates the new entities.

Unlike src/rsmm/make_menu_button_clone_mod.py (which only appends sections at
the end of the file and leaves the picker array unchanged), this tool
performs the patch the engine actually needs to render an extra button.

Output: a mod folder at mods/<id>/ containing the patched cooked file at
its decoded path; apply with ./rsmm apply.
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
import uuid
from pathlib import Path


TITLE_MENU_ENC = (
    "MzidisFqiidzyv/KgxqJdv/Srxxrz_Jd!Qdilq_Hqzw_Jd.qzidis.ri."
    "MzidisFqiidzyvLqvrwubq.yqz"
)
TITLE_MENU_DEC = (
    "EntitySettings/GameUis/Common_Ui/"
    "Title_Menu_Ui.entity.ot.EntitySettingsResource.gen"
)

MARK_BEGIN = bytes.fromhex("1111bbaa")
MARK_END = bytes.fromhex("2222bbaa")

ENTITY_PARENT = "Title_Menu_Ui\\Old Menu"


def lpstr(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def lpbytes(b: bytes) -> bytes:
    return struct.pack("<I", len(b)) + b


def find_lprefixed(data: bytes, s: str) -> int:
    needle = lpstr(s)
    return data.find(needle)


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


def find_section_for_internal_name(data: bytes, internal_name: str,
                                   class_table_end: int) -> tuple[int, int]:
    """Locate the top-level section whose payload begins with an inner
    parent-ref block (all-zero 24-byte block) followed by a self-GUID and
    the given internal_name as a length-prefixed string.

    Returns (begin_off, end_off) where begin_off is the file offset of the
    BEGIN marker and end_off is the file offset immediately after the
    matching outer END marker.
    """
    needle = lpstr(internal_name)
    # The internal name string is preceded by 16 bytes of self-GUID, which
    # is preceded by inner END marker (4 bytes), which is preceded by 24
    # zero bytes (null GUID + zero strlen), which is preceded by u32=0x18
    # = 24, which is preceded by inner BEGIN marker (4 bytes). Total: 4 +
    # 4 + 24 + 4 + 16 = 52 bytes between outer BEGIN's payload-start and
    # the internal-name string.
    pos = data.find(needle, class_table_end)
    while pos != -1:
        # Look back 52 bytes for inner-block + self-GUID pattern. Outer
        # BEGIN should sit at pos - 52 - 4 = pos - 56.
        outer_begin = pos - 56
        if outer_begin < class_table_end:
            pos = data.find(needle, pos + 1)
            continue
        if (data[outer_begin:outer_begin + 4] == MARK_BEGIN
                and data[outer_begin + 8:outer_begin + 12] == MARK_BEGIN
                and data[outer_begin + 12:outer_begin + 16] == b"\x18\x00\x00\x00"
                and data[outer_begin + 16:outer_begin + 36] == b"\x00" * 20
                and data[outer_begin + 36:outer_begin + 40] == MARK_END):
            end = find_balanced_end(data, outer_begin + 4)
            if end == -1:
                raise ValueError(f"unterminated section for {internal_name!r}")
            return outer_begin, end
        pos = data.find(needle, pos + 1)
    raise ValueError(f"section not found for internal name {internal_name!r}")


def locate_class_table_end(data: bytes) -> int:
    """Walk header + class table; return file offset just after class
    table's terminating MARK_END.
    """
    p = 0
    p += 4  # header_field_0
    flags = struct.unpack_from("<I", data, p)[0]
    p += 4
    if data[p:p + 4] == MARK_BEGIN:
        # Type B stream (unlikely for this resource, but handle).
        p += 4
    else:
        # Type A: "Cooked" lstr + u32 extra + u8 tag.
        slen = struct.unpack_from("<I", data, p)[0]
        p += 4 + slen
        p += 4   # extra
        p += 1   # tag
        if data[p:p + 4] != MARK_BEGIN:
            raise ValueError(f"expected MARK_BEGIN at 0x{p:x}, got {data[p:p+4].hex()}")
        p += 4
    class_count = struct.unpack_from("<I", data, p)[0]
    p += 4
    for _ in range(class_count):
        nlen = struct.unpack_from("<I", data, p)[0]
        p += 4 + nlen
        p += 16  # class_id, v_major, v_minor, parent_id
    if data[p:p + 4] != MARK_END:
        raise ValueError(f"expected MARK_END at 0x{p:x}, got {data[p:p+4].hex()}")
    p += 4
    return p


def extract_picker_targets(data: bytes, state_init_payload_start: int,
                           state_init_payload_end: int) -> dict[str, bytes]:
    """Walk picker entries inside State Init and return path->target-GUID."""
    out: dict[str, bytes] = {}
    p = state_init_payload_start
    while p + 4 <= state_init_payload_end:
        idx = data.find(MARK_BEGIN, p, state_init_payload_end)
        if idx == -1:
            break
        # picker entry: BEGIN + u32(0x18) + GUID(16) + u32(strlen) + str + END
        u32 = struct.unpack_from("<I", data, idx + 4)[0]
        if u32 != 0x18:
            p = idx + 4
            continue
        guid = data[idx + 8:idx + 24]
        strlen = struct.unpack_from("<I", data, idx + 24)[0]
        if strlen > 4096 or idx + 28 + strlen + 4 > state_init_payload_end:
            p = idx + 4
            continue
        s = data[idx + 28:idx + 28 + strlen].decode("utf-8", errors="replace")
        end_marker = data[idx + 28 + strlen:idx + 28 + strlen + 4]
        if end_marker != MARK_END:
            p = idx + 4
            continue
        if s:  # skip the inner null-parent block (empty string)
            out[s] = guid
        p = idx + 28 + strlen + 4
    return out


def find_state_init_section(data: bytes, class_table_end: int) -> tuple[int, int]:
    return find_section_for_internal_name(data, "State Init", class_table_end)


def slice_section_payload(data: bytes, begin: int, end: int) -> bytes:
    """Return payload bytes between BEGIN(begin..begin+4) and END(end-4..end)."""
    return data[begin + 4:end - 4]


def replace_lprefixed(buf: bytes, old_str: str, new_str: str) -> bytes:
    """Replace every length-prefixed occurrence of old_str with new_str."""
    old_b = lpstr(old_str)
    new_b = lpstr(new_str)
    out = buf
    while True:
        i = out.find(old_b)
        if i == -1:
            break
        out = out[:i] + new_b + out[i + len(old_b):]
    return out


def substitute_in_lpstrings(buf: bytes, old_sub: str, new_sub: str) -> bytes:
    """Walk every plausible length-prefixed UTF-8 string in `buf`; if it
    contains `old_sub`, rewrite it with `new_sub` and refresh the u32
    length prefix. Used to patch substrings inside longer entity paths
    (e.g. "...\\Discord Button Spawner" -> "...\\Mods Button Spawner").
    """
    old_b = old_sub.encode("utf-8")
    new_b = new_sub.encode("utf-8")
    out = bytearray()
    i = 0
    n = len(buf)
    while i + 4 <= n:
        slen = struct.unpack_from("<I", buf, i)[0]
        if 1 <= slen <= 1024 and i + 4 + slen <= n:
            s = buf[i + 4:i + 4 + slen]
            # Heuristic: only treat as a string if it's printable-ish UTF-8
            # and contains the substring we're patching.
            if old_b in s:
                try:
                    decoded = s.decode("utf-8")
                except UnicodeDecodeError:
                    out.append(buf[i])
                    i += 1
                    continue
                if all(0x20 <= b < 0x7f or b in (0x09, 0x0a, 0x0d) for b in s):
                    new_s = decoded.replace(old_sub, new_sub).encode("utf-8")
                    out += struct.pack("<I", len(new_s)) + new_s
                    i += 4 + slen
                    continue
        out.append(buf[i])
        i += 1
    out += buf[i:]
    return bytes(out)


def build_picker_entry(target_guid: bytes, path: str) -> bytes:
    """A picker entry = BEGIN + u32(0x18) + 16-byte target GUID +
    u32(strlen) + utf-8 path + END.
    """
    return (
        MARK_BEGIN
        + struct.pack("<I", 0x18)
        + target_guid
        + lpstr(path)
        + MARK_END
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--mod-id", default="MainMenuModsTab")
    ap.add_argument("--button-name", default="Mods Button",
                    help='Internal entity name prefix; the engine will instantiate '
                         '<name> Spawner and <name> Text entities. Default "Mods Button".')
    ap.add_argument("--from-backup", action="store_true",
                    help="Read original from .rsmm.bak instead of live file. "
                         "Use this if a previous failed mod corrupted the live file.")
    args = ap.parse_args()

    cooked_path = (args.game_dir / COOKING_SUBDIR
                   / TITLE_MENU_ENC)
    if args.from_backup or not cooked_path.exists():
        bak = Path(str(cooked_path) + ".rsmm.bak")
        if not bak.exists():
            print(f"ERROR: cannot find source file at {cooked_path} or {bak}", file=sys.stderr)
            return 1
        cooked_path = bak
    print(f"reading {cooked_path}")
    data = cooked_path.read_bytes()

    class_table_end = locate_class_table_end(data)
    print(f"class table ends at 0x{class_table_end:x}")

    # Resolve Discord Button source sections.
    spawner_begin, spawner_end = find_section_for_internal_name(
        data, "Discord Button Spawner", class_table_end)
    text_begin, text_end = find_section_for_internal_name(
        data, "Discord Button Text", class_table_end)
    print(f"Discord Button Spawner section: [0x{spawner_begin:x}..0x{spawner_end:x})")
    print(f"Discord Button Text section:    [0x{text_begin:x}..0x{text_end:x})")

    spawner_payload = slice_section_payload(data, spawner_begin, spawner_end)
    text_payload = slice_section_payload(data, text_begin, text_end)

    # Self-GUID lives at payload offset 0x24 (after inner null-parent block).
    discord_spawner_guid = spawner_payload[0x24:0x24 + 16]
    discord_text_guid = text_payload[0x24:0x24 + 16]
    print(f"Discord Spawner GUID = {discord_spawner_guid.hex()}")
    print(f"Discord Text    GUID = {discord_text_guid.hex()}")

    # Locate State Init section + picker GUIDs to cross-check.
    si_begin, si_end = find_state_init_section(data, class_table_end)
    print(f"State Init section: [0x{si_begin:x}..0x{si_end:x})")
    si_payload = slice_section_payload(data, si_begin, si_end)
    picker_map = extract_picker_targets(data, si_begin + 4, si_end - 4)
    spawner_path = f"[Entity Spawner] {ENTITY_PARENT}\\Discord Button Spawner"
    text_path = f"[Spawner Value] {ENTITY_PARENT}\\Discord Button Text"
    assert picker_map[spawner_path] == discord_spawner_guid, \
        "Discord Button Spawner picker GUID disagrees with self-GUID"
    assert picker_map[text_path] == discord_text_guid, \
        "Discord Button Text picker GUID disagrees with self-GUID"
    print(f"picker array has {len(picker_map)} entries (expected 10)")
    assert len(picker_map) == 10, \
        f"unexpected picker count {len(picker_map)} (expected 10)"

    # Mint fresh GUIDs for the new clones.
    new_spawner_guid = uuid.uuid4().bytes
    new_text_guid = uuid.uuid4().bytes
    print(f"Mods Spawner GUID = {new_spawner_guid.hex()}")
    print(f"Mods Text    GUID = {new_text_guid.hex()}")

    # Build cloned Spawner payload. Rename "Discord Button" -> "<button>"
    # everywhere it appears inside any length-prefixed string. Then swap
    # the self-GUID across the section.
    spawner_clone = substitute_in_lpstrings(
        spawner_payload, "Discord Button", args.button_name)
    spawner_clone = spawner_clone.replace(discord_spawner_guid, new_spawner_guid)
    assert lpstr(f"{args.button_name} Spawner") in spawner_clone, \
        "rename failed inside Spawner clone"

    # Build cloned Text payload. Same string rename, then swap Text's own
    # GUID and the back-reference GUID that points to the Spawner.
    text_clone = substitute_in_lpstrings(
        text_payload, "Discord Button", args.button_name)
    text_clone = text_clone.replace(discord_text_guid, new_text_guid)
    text_clone = text_clone.replace(discord_spawner_guid, new_spawner_guid)
    assert lpstr(f"{args.button_name} Text") in text_clone, \
        "rename failed inside Text clone"
    assert lpstr(f"[Entity Spawner] {ENTITY_PARENT}\\{args.button_name} Spawner") \
        in text_clone, "back-reference rename failed inside Text clone"

    # Patch State Init payload: bump picker count, append 2 new pickers.
    play_text_anchor = lpstr(f"[Spawner Value] {ENTITY_PARENT}\\Play Button Text")
    si_play_pos = si_payload.find(play_text_anchor)
    assert si_play_pos != -1, "could not anchor on Play Button Text picker"
    # Layout before play-text strlen: -16 GUID, -20 u32(0x18), -24 BEGIN,
    # -28 picker_count u32.
    count_off = si_play_pos - 28
    assert struct.unpack_from("<I", si_payload, count_off)[0] == 10, \
        f"picker_count at 0x{count_off:x} not 10"
    si_new_count = struct.pack("<I", 12)

    exit_spawner_anchor = lpstr(
        f"[Entity Spawner] {ENTITY_PARENT}\\Exit Button Spawner")
    exit_pos = si_payload.find(exit_spawner_anchor)
    assert exit_pos != -1, "could not anchor on Exit Button Spawner picker"
    # End of Exit Spawner picker = exit_pos + 4(strlen) + len(str) + 4(END).
    exit_str_len = len(exit_spawner_anchor) - 4
    last_picker_end = exit_pos + 4 + exit_str_len + 4
    assert si_payload[last_picker_end - 4:last_picker_end] == MARK_END, \
        "Exit picker END marker missing"

    new_text_picker = build_picker_entry(
        new_text_guid,
        f"[Spawner Value] {ENTITY_PARENT}\\{args.button_name} Text",
    )
    new_spawner_picker = build_picker_entry(
        new_spawner_guid,
        f"[Entity Spawner] {ENTITY_PARENT}\\{args.button_name} Spawner",
    )

    si_payload_patched = (
        si_payload[:count_off]
        + si_new_count
        + si_payload[count_off + 4:last_picker_end]
        + new_text_picker
        + new_spawner_picker
        + si_payload[last_picker_end:]
    )

    # Splice: rebuild full file.
    # Original layout: ... [si_begin .. si_end) ... [spawner_begin..) ...
    # We need to substitute si_payload inside its BEGIN/END envelope, then
    # append the two cloned sections after the original file body. Because
    # the engine indexes sections by markers (not absolute offsets), the
    # cloned sections can sit at the very end of the file without
    # disturbing existing references.
    head = data[:si_begin]
    si_envelope = MARK_BEGIN + si_payload_patched + MARK_END
    tail = data[si_end:]
    spawner_envelope = MARK_BEGIN + spawner_clone + MARK_END
    text_envelope = MARK_BEGIN + text_clone + MARK_END
    patched = head + si_envelope + tail + spawner_envelope + text_envelope

    # Validate: parse patched file's class table + section list to make
    # sure markers stay balanced.
    new_class_table_end = locate_class_table_end(patched)
    assert new_class_table_end == class_table_end, \
        "class table boundary moved (should not happen)"

    # Walk top-level sections to confirm count == old + 2.
    pos = new_class_table_end
    n_sections = 0
    while pos + 4 <= len(patched):
        if patched[pos:pos + 4] != MARK_BEGIN:
            break
        end = find_balanced_end(patched, pos + 4)
        if end == -1:
            raise ValueError(f"unterminated section starting at 0x{pos:x}")
        n_sections += 1
        pos = end
    print(f"patched file has {n_sections} top-level sections "
          f"(orig had {n_sections - 2})")

    mod_dir = MODS_DIR / args.mod_id
    asset_path = mod_dir / "assets" / TITLE_MENU_DEC
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(patched)
    manifest = mod_dir / "manifest.toml"
    manifest.write_text("\n".join([
        "[mod]",
        f'id = "{args.mod_id}"',
        'name = "Main Menu Mods Tab"',
        'version = "0.1.0"',
        'author = "rsmm"',
        'description = "Adds an extra entry to the title menu by cloning the '
        'Discord button with a fresh GUID and patching the State Init picker '
        'array to reference it."',
        "enabled = true",
        "",
    ]), encoding="utf-8")
    print(f"wrote mod asset:  {asset_path}")
    print(f"wrote manifest:   {manifest}")
    print()
    print("Next:")
    print("  1. Disable the old experimental mod:")
    print("       sed -i 's/^enabled = true/enabled = false/' "
          "mods/TitleMenuExtraButtonAttempt/manifest.toml")
    print("  2. Apply:")
    print("       ./rsmm apply")
    print("  3. Launch Ravenswatch from Steam and check the title screen for a")
    print("     6th button.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
