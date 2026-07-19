"""`rsmm enable` / `rsmm disable` — toggle mods from the terminal.

    rsmm enable  <id>... [--only] [--no-apply] [--mods-dir DIR]
    rsmm enable  --all   [--no-apply] [--mods-dir DIR]
    rsmm disable <id>... [--no-apply] [--mods-dir DIR]
    rsmm disable --all   [--no-apply] [--mods-dir DIR]

Flips `enabled` in each mod's `manifest.toml` (same edit the in-game mod
menu performs via `rsmm intents apply`), then re-runs `rsmm apply` so the
game install reflects the change. `--no-apply` skips that final step.

`rsmm enable <id> --only` is the "test exactly this mod" shortcut: it
enables the listed mods and disables every other mod in one pass.

Mod ids are the directory names under `mods/` (case-sensitive).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from ..engine import paths as P
from . import _keys, _term
from .cmd_intents import set_mod_enabled

_ST = _term.Style()

# Hoisted: Python 3.11 forbids backslash escapes inside f-string expressions.
_ARROW = "›"      # ›
_DOT = "·"        # ·

#: Manifests are written with the value aligned (`enabled     = true`), so a
#: naive `"enabled = true" in text` check reports every mod as disabled.
_ENABLED_TRUE = re.compile(r"^\s*enabled\s*=\s*true\s*$", re.MULTILINE)


def _all_mod_ids(mods_dir: Path) -> list[str]:
    """Every directory under mods/ that carries a manifest.toml."""
    if not mods_dir.is_dir():
        return []
    return sorted(
        d.name for d in mods_dir.iterdir()
        if d.is_dir() and (d / "manifest.toml").is_file()
    )


def _states(mods_dir: Path, ids: list[str] | None = None) -> dict[str, bool]:
    """Map mod id -> whether its manifest currently says ``enabled = true``.

    Deliberately a regex over the raw text rather than a tomllib parse: this
    runs on every menu redraw, and a manifest that fails to parse must still
    render as a row (disabled) instead of taking the whole screen down.
    """
    out: dict[str, bool] = {}
    for mod_id in (_all_mod_ids(mods_dir) if ids is None else ids):
        try:
            text = (mods_dir / mod_id / "manifest.toml").read_text(encoding="utf-8")
        except OSError:
            out[mod_id] = False
            continue
        out[mod_id] = bool(_ENABLED_TRUE.search(text))
    return out


def _pick_raw(mods_dir: Path, ids: list[str], verb: str) -> list[str] | None:
    """Arrow-key multi-select over `ids`. Returns None if the user aborted.

    Only called when the terminal supports raw mode; `_pick` falls back to a
    numeric prompt otherwise.
    """
    state = _states(mods_dir, ids)
    chosen: set[str] = set()
    cursor = 0
    with _keys.alt_screen(), _keys.raw_session():
        while True:
            cursor = max(0, min(cursor, len(ids) - 1))
            height = max(6, _term.height() - 8)
            start = max(0, min(cursor - height // 2, len(ids) - height))
            visible = ids[start:start + height]

            sys.stdout.write("\033[2J\033[H")
            w = _term.width()
            print(_term.panel_top("", _ST, w))
            print(_term.panel_row(
                _ST.heading(verb) + _ST.dim(f"   {len(chosen)} selected "
                                            f"of {len(ids)}"), _ST, w))
            print(_term.panel_bottom(_ST, w))
            print()
            rows: list[int] = []
            first_row = 5
            for i, mod_id in enumerate(visible):
                idx = start + i
                sel = idx == cursor
                box = _ST.ok("[x]") if mod_id in chosen else _ST.dim("[ ]")
                cur = _ST.dim("on") if state.get(mod_id) else _ST.dim("off")
                name = _ST.bold(mod_id) if sel else mod_id
                marker = _ST.accent(_ARROW) if sel else " "
                print(f" {marker} {box} {name}  {cur}")
                rows.append(first_row + i)
            if len(ids) > len(visible):
                print(_ST.dim(f"    … {len(ids) - len(visible)} more"))
            print()
            print(_ST.dim(
                f"  ↑↓ move  {_DOT} space/click select  {_DOT} a all"
                f"  {_DOT} ↵ confirm  {_DOT} q cancel"))
            sys.stdout.flush()

            try:
                ev = _keys.read_key()
            except KeyboardInterrupt:
                return None
            if ev is None:
                return None

            if ev[0] == _keys.MOTION:
                _, _col, row = ev
                for i, r in enumerate(rows):
                    if r == row:
                        cursor = start + i
                        break
                continue
            if ev[0] == "click":
                _, _col, row = ev
                for i, r in enumerate(rows):
                    if r == row:
                        cursor = start + i
                        mod_id = ids[cursor]
                        chosen.symmetric_difference_update({mod_id})
                        break
                continue

            key = ev[0]
            if key == _keys.UP:
                cursor = (cursor - 1) % len(ids)
            elif key == _keys.DOWN:
                cursor = (cursor + 1) % len(ids)
            elif key == _keys.WHEEL_UP:
                cursor = max(0, cursor - 3)
            elif key == _keys.WHEEL_DOWN:
                cursor = min(len(ids) - 1, cursor + 3)
            elif key == _keys.PGUP:
                cursor = max(0, cursor - height)
            elif key == _keys.PGDN:
                cursor = min(len(ids) - 1, cursor + height)
            elif key in ("g", _keys.HOME):
                cursor = 0
            elif key in ("G", _keys.END):
                cursor = len(ids) - 1
            elif key == " ":
                chosen.symmetric_difference_update({ids[cursor]})
            elif key == "a":
                chosen = set() if len(chosen) == len(ids) else set(ids)
            elif key == _keys.ENTER:
                return sorted(chosen)
            elif key in ("q", _keys.ESC):
                return None


def _pick(mods_dir: Path, ids: list[str], verb: str) -> list[str] | None:
    """Choose mods interactively. Raw-mode picker when the terminal allows
    it, numeric prompt otherwise (SSH without a TTY, CI, Windows w/o termios)."""
    if _keys.available():
        return _pick_raw(mods_dir, ids, verb)

    state = _states(mods_dir, ids)
    for i, mod_id in enumerate(ids, 1):
        print(f"  {i:>3}  [{'x' if state.get(mod_id) else ' '}]  {mod_id}")
    try:
        raw = input(f"{verb} which? (numbers, 'all', blank to cancel) ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not raw:
        return None
    if raw.lower() == "all":
        return list(ids)
    out: list[str] = []
    for tok in raw.replace(",", " ").split():
        if not tok.isdigit() or not (1 <= int(tok) <= len(ids)):
            print(f"error: not a listed number: {tok}", file=sys.stderr)
            return None
        out.append(ids[int(tok) - 1])
    return list(dict.fromkeys(out))


def _resolve_ids(args, ap, mods_dir: Path, known: list[str],
                 verb: str) -> list[str] | None:
    """Turn the parsed args into the concrete mod list to act on.

    `rsmm enable` with no ids is an error when scripted but an invitation
    when a human runs it, so an interactive terminal gets the picker instead
    of a usage message.
    """
    if args.all:
        return list(known)
    if args.ids:
        return list(dict.fromkeys(args.ids))
    if sys.stdin.isatty() and sys.stdout.isatty():
        return _pick(mods_dir, known, verb)
    ap.error("give at least one mod id, or --all")
    return None  # unreachable; ap.error exits


def _flip(mods_dir: Path, mod_id: str, enabled: bool) -> bool:
    """Toggle one mod, print the outcome, return True unless it failed."""
    status = set_mod_enabled(mods_dir, mod_id, enabled)
    verb = "enable" if enabled else "disable"
    print(f"{verb:<8} {mod_id}: {status}")
    return status in ("ok", "unchanged")


def _run_apply() -> int:
    cmd = P.self_cmd(["apply"])
    print(f"running: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=P.REPO_ROOT, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Dispatch passes the verb through as argv[0] (like `rsmm repo`).
    prog_verb = sys.argv[0] if sys.argv else "enable"
    verb = argv[0] if argv and argv[0] in ("enable", "disable") else prog_verb

    ap = argparse.ArgumentParser(
        prog=f"rsmm {verb}",
        description=f"{verb} mods by flipping `enabled` in their manifest.toml",
    )
    ap.add_argument("ids", nargs="*", metavar="mod-id",
                    help="mod directory name(s) under mods/")
    ap.add_argument("--all", action="store_true",
                    help=f"{verb} every mod under mods/")
    if verb == "enable":
        ap.add_argument("--only", action="store_true",
                        help="also disable every mod NOT listed")
    ap.add_argument("--no-apply", action="store_true",
                    help="flip manifests but skip the final `rsmm apply`")
    ap.add_argument("--mods-dir", help="mods directory (default: repo mods/)")

    args = ap.parse_args(argv[1:] if argv and argv[0] == verb else argv)
    enabled = verb == "enable"
    only = bool(getattr(args, "only", False))

    if args.all and (args.ids or only):
        ap.error("--all cannot be combined with mod ids or --only")

    mods_dir = Path(args.mods_dir) if args.mods_dir else P.mods_dir()
    known = _all_mod_ids(mods_dir)
    if not known:
        print(f"error: no mods found under {mods_dir}", file=sys.stderr)
        return 2

    targets = _resolve_ids(args, ap, mods_dir, known, verb)
    if not targets:
        print("nothing selected", file=sys.stderr)
        return 1

    unknown = [i for i in targets if i not in known]
    if unknown:
        print(f"error: unknown mod id(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"known: {', '.join(known)}", file=sys.stderr)
        return 2

    failures = 0
    for mod_id in targets:
        failures += 0 if _flip(mods_dir, mod_id, enabled) else 1
    if only:
        for mod_id in known:
            if mod_id not in targets:
                failures += 0 if _flip(mods_dir, mod_id, False) else 1

    if failures:
        print(f"{failures} mod(s) failed; skipping apply", file=sys.stderr)
        return 1
    if args.no_apply:
        return 0
    rc = _run_apply()
    if rc != 0:
        print(f"error: rsmm apply exited {rc}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
