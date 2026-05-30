#!/usr/bin/env python3
"""
rsmm cmd — send /commands to the in-game console runtime.

The Lua side (mods/ConsoleRuntime/init.lua) polls
`<game>/mods/_console.txt` every tick (~500 ms), dispatches every
line as a /command, and appends results to `_console_out.txt`. This
CLI writes input and tails output.

Usage:

  rsmm cmd '/help'                    # one-shot: send + read result
  rsmm cmd '/list_items Armor'
  rsmm cmd                            # interactive REPL
  rsmm cmd --tail                     # follow _console_out.txt
  rsmm cmd --refresh-snapshots        # rebuild magic-item / hero
                                      # snapshot files Lua reads from
  rsmm cmd --clear                    # truncate input + output files
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rsmm.engine.paths import DEFAULT_GAME_DIR, MODS_DIR, REPO_ROOT
from rsmm.logging import get_logger, shorten

logger = get_logger(__name__)


CONSOLE_MOD_ID = "ConsoleRuntime"


def _winhttp_installed(game_dir: Path) -> bool:
    return (game_dir / "winhttp.dll").is_file()


def _console_mod_synced(game_dir: Path) -> bool:
    dst = game_dir / "mods" / CONSOLE_MOD_ID
    return (dst / "init.lua").is_file() and (dst / "manifest.toml").is_file()


def _sync_console_mod(game_dir: Path) -> int:
    """Copy mods/ConsoleRuntime/{init.lua,manifest.toml} into the live
    install. Returns file count."""
    src = MODS_DIR / CONSOLE_MOD_ID
    if not src.is_dir():
        logger.error("repo missing %s", src)
        return 0
    dst = game_dir / "mods" / CONSOLE_MOD_ID
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in ("init.lua", "manifest.toml"):
        f = src / name
        if not f.is_file():
            continue
        (dst / name).write_bytes(f.read_bytes())
        n += 1
        logger.info("synced %s -> %s", name, dst / name)
    return n


def _log_recent(game_dir: Path, within_s: float = 60.0) -> bool:
    p = game_dir / "mods" / "_log.txt"
    if not p.is_file():
        return False
    return (time.time() - p.stat().st_mtime) < within_s


def _diagnose(game_dir: Path) -> list[str]:
    """Return a list of likely reasons the Lua side is silent."""
    problems: list[str] = []
    if not _winhttp_installed(game_dir):
        problems.append(
            "loader DLL missing — run `./rsmm install-loader`")
    if not _console_mod_synced(game_dir):
        problems.append(
            f"{CONSOLE_MOD_ID} not in {game_dir / 'mods'} — "
            f"run `./rsmm cmd --install`")
    snaps_dir = game_dir / "mods"
    if not (snaps_dir / "_magic_items.json").is_file():
        problems.append(
            "item/hero snapshots missing — "
            "run `./rsmm cmd --refresh-snapshots` "
            "(needed for /list_items and /list_heroes)")
    if not _log_recent(game_dir, 120):
        problems.append(
            f"loader log {game_dir / 'mods' / '_log.txt'} not touched in 2 min "
            f"— is the game running with WINEDLLOVERRIDES=\"winhttp=n,b\"?")
    return problems


def _game_mods(game_dir: Path) -> Path:
    p = game_dir / "mods"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _send(game_dir: Path, line: str) -> None:
    p = _game_mods(game_dir) / "_console.txt"
    with p.open("a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def _read_output_tail(game_dir: Path, since_size: int,
                      timeout: float = 4.0) -> str:
    """Wait up to `timeout` seconds for new bytes after `since_size`,
    return whatever appeared. The Lua runtime appends on each tick
    (~500 ms), so 4 s comfortably covers a round trip."""
    p = _game_mods(game_dir) / "_console_out.txt"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if p.exists() and p.stat().st_size > since_size:
            time.sleep(0.15)        # let the writer finish flushing
            with p.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(since_size)
                return f.read()
        time.sleep(0.1)
    return ""


def _current_output_size(game_dir: Path) -> int:
    p = _game_mods(game_dir) / "_console_out.txt"
    return p.stat().st_size if p.exists() else 0


def cmd_oneshot(game_dir: Path, line: str, timeout: float) -> int:
    line = line.strip()
    if not line:
        logger.error("empty command")
        return 2
    if not line.startswith("/"):
        line = "/" + line
    # Local client shortcut: handle /clear locally instead of sending
    # it to the game runtime (also available via --clear flag).
    if line == "/clear":
        return cmd_clear(game_dir)
    since = _current_output_size(game_dir)
    _send(game_dir, line)
    out = _read_output_tail(game_dir, since, timeout)
    if not out:
        logger.warning("no response within %.1fs", timeout)
        # Truncate long diagnose lines for compact logs; keep full data
        # available at DEBUG level.
        import shutil

        cols = shutil.get_terminal_size((80, 20)).columns
        for p in _diagnose(game_dir):
            logger.info("diagnose: %s", shorten(p, max_len=cols - 20))
            logger.debug("diagnose.full: %s", p)
        return 1
    sys.stdout.write(out)
    sys.stdout.flush()
    return 0


def cmd_interactive(game_dir: Path, timeout: float) -> int:
    logger.info("rsmm console — type /help, or `exit` to quit")
    while True:
        try:
            line = input("rsmm> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in {"exit", "quit", ":q"}:
            return 0
        # Local client shortcuts
        if line == "/clear":
            cmd_clear(game_dir)
            continue
        if not line.startswith("/"):
            line = "/" + line
        since = _current_output_size(game_dir)
        _send(game_dir, line)
        out = _read_output_tail(game_dir, since, timeout)
        if out:
            sys.stdout.write(out)
        else:
            logger.warning("no response within %.1fs", timeout)


def cmd_tail(game_dir: Path) -> int:
    p = _game_mods(game_dir) / "_console_out.txt"
    logger.info("tailing %s — Ctrl-C to stop", p)
    pos = p.stat().st_size if p.exists() else 0
    try:
        while True:
            if p.exists():
                cur = p.stat().st_size
                if cur < pos:
                    pos = 0     # truncated
                if cur > pos:
                    with p.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(pos)
                        sys.stdout.write(f.read())
                        sys.stdout.flush()
                        pos = cur
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 0


def cmd_clear(game_dir: Path) -> int:
    for n in ("_console.txt", "_console_out.txt"):
        p = _game_mods(game_dir) / n
        if p.exists():
            p.write_text("")
            logger.info("cleared %s", p)
    return 0


def cmd_install(game_dir: Path) -> int:
    """One-shot setup: sync ConsoleRuntime + write snapshots + sanity
    print loader status."""
    logger.info("game_dir: %s", game_dir)
    n = _sync_console_mod(game_dir)
    logger.info("synced %d file(s) into %s", n, game_dir / 'mods' / CONSOLE_MOD_ID)
    cmd_refresh_snapshots(game_dir)
    if not _winhttp_installed(game_dir):
        logger.error("winhttp.dll not in %s — run ./rsmm install-loader next", game_dir)
    if not _log_recent(game_dir, 3600):
        logger.warning("loader log not touched recently — launch the game with ./rsmm run to bring console online")
    return 0


def cmd_status(game_dir: Path) -> int:
    logger.info("game_dir: %s", game_dir)
    checks = [
        ("loader dll",     _winhttp_installed(game_dir)),
        ("ConsoleRuntime", _console_mod_synced(game_dir)),
        ("magic_items snapshot",
         (game_dir / "mods" / "_magic_items.json").is_file()),
        ("heroes snapshot",
         (game_dir / "mods" / "_heroes.json").is_file()),
        ("loader log fresh (<2 min)", _log_recent(game_dir, 120)),
    ]
    for name, ok in checks:
        logger.info("[%s] %s", "ok" if ok else "no", name)
    return 0


def _collect_clones() -> list[dict]:
    """Scan every mod manifest for magic_item_clone patches. Returns
    [{mod_id, new_id, from_id, rarity}, ...]."""
    try:
        from rsmm.cli.merge import _toml_load
    except Exception:
        return []
    out: list[dict] = []
    if not MODS_DIR.is_dir():
        return out
    for entry in sorted(MODS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        if entry.name == "_merged":
            continue
        mf = entry / "manifest.toml"
        if not mf.is_file():
            continue
        try:
            t = _toml_load(mf)
        except Exception:
            continue
        if not t.get("mod", {}).get("enabled", True):
            continue
        mid = t.get("mod", {}).get("id") or entry.name
        for p in t.get("patch", []) or []:
            if p.get("kind") != "magic_item_clone":
                continue
            out.append({
                "mod_id": mid,
                "new_id": str(p.get("new_id", "")),
                "from_id": str(p.get("from_id", "")),
                "rarity": str(p.get("rarity", "")),
            })
    return out


def cmd_refresh_snapshots(game_dir: Path) -> int:
    """Write JSON snapshots the Lua runtime reads when listing items /
    heroes / etc. Lua has no path into the repo's data/, so we
    materialise the relevant slices into <game>/mods/."""
    out = _game_mods(game_dir)

    # Magic items snapshot: vanilla registry + cloned items from any mod
    try:
        from rsmm.engine import magic_items
        reg = magic_items.registry()
        snapshot = [
            {"id": v.id, "rarity": v.rarity,
             "name_key": v.name_key, "icon": v.icon_decoded_path,
             "source": "vanilla"}
            for v in sorted(reg.values(), key=lambda x: (x.rarity, x.id))
        ]
        clones = _collect_clones()
        for c in clones:
            snapshot.append({
                "id": c["new_id"],
                "rarity": c["rarity"],
                "name_key": f"{c['new_id']}_Name",
                "icon": None,
                "source": f"clone:{c['mod_id']} <- {c['from_id']}",
            })
        (out / "_magic_items.json").write_text(
            json.dumps(snapshot, indent=2), encoding="utf-8")
        logger.info("magic_items: %d entries (%d cloned) -> %s",
                    len(snapshot), len(clones), out / '_magic_items.json')
    except Exception:
        logger.exception("magic_items snapshot failed")

    # Heroes snapshot: scan data/uncooked for Hero_*.entity.ot dirs
    heroes: list[str] = []
    heroes_dir = REPO_ROOT / "data" / "uncooked" / "EntitySettings" / "Heroes"
    if heroes_dir.is_dir():
        for d in heroes_dir.iterdir():
            if d.is_dir() and not d.name.startswith("Hero_Common"):
                heroes.append(d.name)
    if heroes:
        (out / "_heroes.json").write_text(
            json.dumps(sorted(heroes), indent=2), encoding="utf-8")
        logger.info("heroes: %d entries -> %s", len(heroes), out / '_heroes.json')
    else:
        logger.warning("heroes: no data/uncooked/EntitySettings/Heroes (skip)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="rsmm cmd",
                                 description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    ap.add_argument("--timeout", type=float, default=4.0,
                    help="seconds to wait for response (default 4.0)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--tail", action="store_true",
                   help="follow _console_out.txt live")
    g.add_argument("--clear", action="store_true",
                   help="truncate console input + output files")
    g.add_argument("--refresh-snapshots", action="store_true",
                   help="rewrite <game>/mods/_magic_items.json + _heroes.json "
                        "from the repo's registries (run once per session)")
    g.add_argument("--install", action="store_true",
                   help="sync ConsoleRuntime into <game>/mods/ + write "
                        "snapshots (one-shot setup)")
    g.add_argument("--status", action="store_true",
                   help="print loader + ConsoleRuntime install state")
    ap.add_argument("line", nargs="*",
                    help="/command to send (omit for interactive REPL)")
    args = ap.parse_args()

    game_dir: Path = args.game_dir
    if not game_dir.exists():
        print(f"game dir not found: {game_dir}", file=sys.stderr)
        return 1

    if args.tail:
        return cmd_tail(game_dir)
    if args.clear:
        return cmd_clear(game_dir)
    if args.refresh_snapshots:
        return cmd_refresh_snapshots(game_dir)
    if args.install:
        return cmd_install(game_dir)
    if args.status:
        return cmd_status(game_dir)

    if args.line:
        return cmd_oneshot(game_dir, " ".join(args.line), args.timeout)
    return cmd_interactive(game_dir, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
