#!/usr/bin/env python3
"""Process click events captured by the live engine hook (selection model).

The loader writes one line per in-game click of the Mods tab to
`mods/_clicks.log`. Each line carries an `event=<action>` field. The
in-game UI maps to a selection model:

   event=invite   -> ROW CLICK: select the mod that this row labels
   event=add      -> ENABLE selected mod
   event=block    -> DISABLE selected mod
   event=report   -> BROWSE MODS (placeholder)
   event=unblock  -> BROWSE MODS (fallback)
   event=remove   -> BROWSE MODS (fallback)
   event=mods_row_clicked -> legacy fallback, no-op

Selection is the SteamID -> mod_name resolved via `mods/_persona_map.json`
(written by the loader's GetFriendPersonaName hook). The loader emits one
JSON dict mapping each row's underlying SteamID to the mod_name that the
row was rebound to. process_clicks.py reads this map to know which mod a
selection-click points at.

State files (under repo-side `mods/`):
   _clicks.state           - consumed-event counter (durable)
   _clicks_selection.json  - last selection
   _browse_requests.log    - browse-mod intents (append-only)
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
import json
import re
import sys
from pathlib import Path


GAME_DIR_DEFAULT = Path.home() / (
    ".var/app/com.valvesoftware.Steam/.local/share/Steam/"
    "steamapps/common/Ravenswatch"
)

BROWSE_URL_DEFAULT = "https://example.com/ravenswatch-mods"

EVENT_RE = re.compile(
    r"^ts=(\d+)\s+event=(\S+)\s+count=(\d+)(?:\s+steam_id=(\d{17}))?\s*$"
)

# Selection-model action set.
SELECT_EVENTS = {"invite"}
ENABLE_EVENTS = {"add"}
DISABLE_EVENTS = {"block"}
BROWSE_EVENTS = {"report", "unblock", "remove"}


def read_clicks(log_path: Path) -> list[tuple[int, str, int, str | None]]:
    if not log_path.is_file():
        return []
    out: list[tuple[int, str, int, str | None]] = []
    for line in log_path.read_text().splitlines():
        m = EVENT_RE.match(line)
        if not m:
            continue
        out.append((int(m.group(1)), m.group(2), int(m.group(3)),
                    m.group(4)))
    return out


def read_state(p: Path) -> int:
    if not p.is_file():
        return 0
    try:
        return int(p.read_text().strip())
    except ValueError:
        return 0


def write_state(p: Path, consumed: int) -> None:
    p.write_text(f"{consumed}\n")


def read_json(p: Path) -> dict:
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def write_json(p: Path, m: dict) -> None:
    p.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")


def list_mods(mods_dir: Path) -> list[Path]:
    return sorted(
        p for p in mods_dir.iterdir()
        if p.is_dir() and (p / "manifest.toml").is_file()
    )


def set_enabled(manifest: Path, enabled: bool) -> bool:
    text = manifest.read_text()
    pat = re.compile(r"^(enabled\s*=\s*)(true|false)\s*$", re.MULTILINE)
    m = pat.search(text)
    if not m:
        print(f"  ! no `enabled = true/false` line in {manifest}",
              file=sys.stderr)
        return False
    cur = m.group(2)
    new = "true" if enabled else "false"
    if cur == new:
        print(f"  {manifest.parent.name}: already {new}")
        return True
    new_text = pat.sub(rf"\g<1>{new}", text, count=1)
    manifest.write_text(new_text)
    print(f"  {manifest.parent.name}: {cur} -> {new}")
    return True


def find_mod(mods: list[Path], name: str) -> Path | None:
    for m in mods:
        if m.name == name:
            return m
    return None


def resolve_selection(
    event: str,
    steam_id: str | None,
    persona_map: dict[str, str],
    mods: list[Path],
    select_idx: int,
) -> tuple[Path | None, str]:
    """For a SELECT event, choose which mod the row points at."""
    if not mods:
        return None, "no-mods"

    # Persona map written by loader: SteamID -> mod_name.
    if steam_id is not None and steam_id in persona_map:
        mod_name = persona_map[steam_id]
        target = find_mod(mods, mod_name)
        if target:
            return target, f"persona_map[{steam_id}] -> {mod_name}"

    # Fallback: alphabetical index by select-event order.
    target = mods[select_idx % len(mods)]
    return target, f"alphabetical[{select_idx}] -> {target.name}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", type=Path, default=GAME_DIR_DEFAULT)
    ap.add_argument("--mods-dir", type=Path, default=MODS_DIR)
    ap.add_argument("--reset", action="store_true",
                    help="discard unprocessed clicks and clear selection")
    ap.add_argument("--browse-url", default=BROWSE_URL_DEFAULT,
                    help="URL emitted for BROWSE events")
    args = ap.parse_args()

    game_clicks_log = args.game_dir / "mods" / "_clicks.log"
    game_persona_map = args.game_dir / "mods" / "_persona_map.json"
    state_path = args.mods_dir / "_clicks.state"
    selection_path = args.mods_dir / "_clicks_selection.json"
    browse_log_path = args.mods_dir / "_browse_requests.log"

    events = read_clicks(game_clicks_log)
    consumed = read_state(state_path)
    total_seen = len(events)
    unprocessed = max(0, total_seen - consumed)
    persona_map = read_json(game_persona_map)
    selection = read_json(selection_path)

    print(f"clicks log    : {game_clicks_log}")
    print(f"  events seen : {total_seen}")
    print(f"  consumed    : {consumed}")
    print(f"  unprocessed : {unprocessed}")
    print(f"persona_map   : {len(persona_map)} entries from {game_persona_map}")
    print(f"selection     : {selection or '(none)'}")

    if args.reset:
        write_state(state_path, total_seen)
        if selection_path.is_file():
            selection_path.unlink()
        print("reset: cleared selection and state")
        return 0

    if unprocessed == 0:
        print("no new clicks; nothing to do.")
        return 0

    mods = list_mods(args.mods_dir)
    if not mods:
        print(f"no mods found in {args.mods_dir}", file=sys.stderr)
        return 1
    print(f"mods (alphabetical): {[m.name for m in mods]}")

    select_seq = 0
    for i in range(unprocessed):
        ts, event, _, steam_id = events[consumed + i]
        idx = consumed + i

        if event in SELECT_EVENTS:
            target, tag = resolve_selection(
                event, steam_id, persona_map, mods, select_seq
            )
            select_seq += 1
            if not target:
                print(f"  click {idx} SELECT: skip ({tag})")
                continue
            selection = {
                "selected_steam_id": steam_id or "",
                "selected_mod": target.name,
                "selected_at_ts": ts,
                "source": tag,
            }
            print(f"  click {idx} SELECT: {tag}")

        elif event in ENABLE_EVENTS:
            mod_name = selection.get("selected_mod")
            target = find_mod(mods, mod_name) if mod_name else None
            if not target:
                print(f"  click {idx} ENABLE: skip (no selection)")
                continue
            print(f"  click {idx} ENABLE: {target.name}")
            set_enabled(target / "manifest.toml", True)

        elif event in DISABLE_EVENTS:
            mod_name = selection.get("selected_mod")
            target = find_mod(mods, mod_name) if mod_name else None
            if not target:
                print(f"  click {idx} DISABLE: skip (no selection)")
                continue
            print(f"  click {idx} DISABLE: {target.name}")
            set_enabled(target / "manifest.toml", False)

        elif event in BROWSE_EVENTS:
            line = f"ts={ts} url={args.browse_url}\n"
            with browse_log_path.open("a") as fh:
                fh.write(line)
            print(f"  click {idx} BROWSE: {args.browse_url}")

        else:
            print(f"  click {idx} {event}: ignored (legacy)")

    write_state(state_path, total_seen)
    write_json(selection_path, selection)
    print(f"state updated: consumed = {total_seen}")
    print()
    print("next: ./rsmm apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
