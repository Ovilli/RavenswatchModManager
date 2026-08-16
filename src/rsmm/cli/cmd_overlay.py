"""rsmm overlay — read the live HUD data a mod publishes.

An overlay is a **mod-declared** capability, not a feature of the client. A mod
describes the shape of its HUD in `manifest.toml`:

    [overlay]
    title = "Damage"
    icon  = "swords"
    sort  = { key = "dealt", dir = "desc" }
    highlight = "is_local"

    [[overlay.columns]]
    key = "label"
    label = "Player"
    type = "text"

...and publishes rows at runtime with `R.overlay.publish{ rows = ... }`, which
land in the mod's own state file. This module joins the two: declaration plus
live rows, for `rsmm overlay` here and for the desktop app's overlay window
through `rsmm json overlays`.

Shape is data, never code. A mod cannot hand markup or script to the desktop
webview — that webview can spawn the CLI, so mod-supplied code in it would be
arbitrary code execution on the player's machine.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

from rsmm.cli import _term
from rsmm.engine.paths import DEFAULT_GAME_DIR

_ST = _term.Style()

#: Column renderers the client knows how to draw. A manifest asking for
#: anything else is rejected at lint time rather than silently ignored.
COLUMN_TYPES = ("text", "number", "percent", "bar")
#: Number presentation. "compact" = 48.2k / 1.3m.
NUMBER_FORMATS = ("plain", "compact")
#: Icons the desktop app ships (lucide). Kept to an allowlist so a manifest
#: cannot name an icon the client has never bundled and get a blank header.
ICONS = ("swords", "activity", "flame", "heart", "shield", "skull", "star",
         "timer", "trophy", "zap", "list", "gauge")

MAX_COLUMNS = 8
MAX_ROWS = 64


class OverlayError(ValueError):
    """A malformed `[overlay]` declaration."""


def parse_spec(raw: Any, *, mod_id: str) -> dict[str, Any]:
    """Validate a manifest's `[overlay]` table into a normalised declaration.

    Raises `OverlayError` with an author-readable message. Every field has a
    default except the columns: an overlay with no columns has nothing to draw
    and is far more likely a typo than an intention.
    """
    if not isinstance(raw, dict):
        raise OverlayError(f"{mod_id}: [overlay] must be a table")
    cols_raw = raw.get("columns")
    if not isinstance(cols_raw, list) or not cols_raw:
        raise OverlayError(f"{mod_id}: [overlay] needs at least one column")
    if len(cols_raw) > MAX_COLUMNS:
        raise OverlayError(
            f"{mod_id}: [overlay] has {len(cols_raw)} columns (max {MAX_COLUMNS}) — "
            "a HUD that wide stops being glanceable"
        )
    columns: list[dict[str, Any]] = []
    for i, col in enumerate(cols_raw):
        if not isinstance(col, dict):
            raise OverlayError(f"{mod_id}: [overlay] column {i + 1} must be a table")
        key = str(col.get("key", "")).strip()
        if not key:
            raise OverlayError(f"{mod_id}: [overlay] column {i + 1} has no `key`")
        ctype = str(col.get("type", "text"))
        if ctype not in COLUMN_TYPES:
            raise OverlayError(
                f"{mod_id}: [overlay] column {key!r} has unknown type {ctype!r} "
                f"(one of {', '.join(COLUMN_TYPES)})"
            )
        fmt = str(col.get("format", "plain"))
        if fmt not in NUMBER_FORMATS:
            raise OverlayError(
                f"{mod_id}: [overlay] column {key!r} has unknown format {fmt!r} "
                f"(one of {', '.join(NUMBER_FORMATS)})"
            )
        columns.append({
            "key": key,
            "label": str(col.get("label", key))[:24],
            "type": ctype,
            "format": fmt,
            "suffix": str(col.get("suffix", ""))[:8],
        })

    sort_raw = raw.get("sort") or {}
    if not isinstance(sort_raw, dict):
        raise OverlayError(f"{mod_id}: [overlay].sort must be a table")
    sort_key = str(sort_raw.get("key", "")).strip()
    sort_dir = str(sort_raw.get("dir", "desc"))
    if sort_dir not in ("asc", "desc"):
        raise OverlayError(f"{mod_id}: [overlay].sort.dir must be 'asc' or 'desc'")
    if sort_key and sort_key not in {c["key"] for c in columns}:
        raise OverlayError(
            f"{mod_id}: [overlay].sort.key {sort_key!r} is not one of the columns"
        )

    icon = str(raw.get("icon", "list"))
    if icon not in ICONS:
        raise OverlayError(
            f"{mod_id}: [overlay].icon {icon!r} is not available "
            f"(one of {', '.join(ICONS)})"
        )
    return {
        "title": str(raw.get("title", mod_id))[:40],
        "icon": icon,
        "columns": columns,
        "sort": {"key": sort_key, "dir": sort_dir} if sort_key else None,
        "highlight": str(raw.get("highlight", "")).strip() or None,
        "empty": str(raw.get("empty", "No data yet."))[:120],
    }


def mods_dir(game_dir: Path | str | None = None) -> Path:
    """The INSTALLED mods tree: what the game (and the loader) actually see."""
    return Path(game_dir or DEFAULT_GAME_DIR) / "mods"


def library_dir() -> Path | None:
    """The AUTHORING mods tree (`RSMM_MODS_DIR`, the repo's `mods/` in dev).

    Declarations are read from here as well as from the install, so an overlay
    shows up in the client the moment it is written — before `rsmm apply` has
    copied the manifest into the game. Live rows still only ever come from the
    install, because that is the only tree the loader writes to.
    """
    from rsmm.engine import paths

    # MODS_DIR is a PEP 562 lazy attribute: reading it scans for the mods tree
    # and can raise if nothing is configured. An overlay listing is not worth
    # failing over.
    try:
        d = Path(paths.MODS_DIR)
    except (OSError, ValueError, AttributeError):
        return None
    return d if d.is_dir() else None


def state_file(game_dir: Path | str | None, mod_id: str) -> Path:
    """Where a mod's `R.kv` state (and therefore its overlay data) lives."""
    return mods_dir(game_dir) / mod_id / ".rsmm_state"


def _unescape(s: str) -> str:
    """Mirror of the SDK's R.kv line escaping (rsmm.lua ``_unesc``)."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append({"\\": "\\", "n": "\n", "t": "\t"}.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_kv(text: str) -> dict[str, object]:
    """Parse the ``<type>\\t<key>\\t<value>`` store R.kv writes."""
    out: dict[str, object] = {}
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        kind, key, value = parts
        key = _unescape(key)
        if kind == "s":
            out[key] = _unescape(value)
        elif kind == "n":
            try:
                out[key] = float(value)
            except ValueError:
                continue
        elif kind == "b":
            out[key] = value == "1"
    return out


def _sorted_rows(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    sort = spec.get("sort")
    if not sort:
        return rows
    key, reverse = sort["key"], sort["dir"] == "desc"

    def sort_value(row: dict[str, Any]) -> tuple[int, float | str]:
        v = row.get(key)
        # Rows missing the sort key go last in either direction rather than
        # blowing up on a str/float comparison.
        if isinstance(v, bool) or v is None:
            return (1, 0.0)
        if isinstance(v, (int, float)):
            return (0, -float(v) if reverse else float(v))
        return (0, str(v))

    return sorted(rows, key=sort_value)


def read_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], int] | None:
    """`(rows, meta, updated)` from a mod's state file, or None if it has none."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    kv = parse_kv(text)
    raw_rows = kv.get("overlay.rows")
    if not isinstance(raw_rows, str):
        return None
    try:
        rows = json.loads(raw_rows)
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    meta: dict[str, Any] = {}
    raw_meta = kv.get("overlay.meta")
    if isinstance(raw_meta, str):
        try:
            parsed = json.loads(raw_meta)
            if isinstance(parsed, dict):
                meta = parsed
        except ValueError:
            pass
    clean = [r for r in rows if isinstance(r, dict)][:MAX_ROWS]
    return clean, meta, int(kv.get("overlay.updated") or 0)


def discover(game_dir: Path | str | None = None, *,
             include_library: bool = True) -> list[dict[str, Any]]:
    """Every mod that declares an overlay, with its live rows.

    Two trees are scanned. The INSTALLED one (`<game>/mods`) is what the player
    is running and the only place rows exist, because the loader writes there.
    The AUTHORING one (`RSMM_MODS_DIR` — the repo's `mods/` in dev) is scanned
    second so a freshly written declaration appears before `rsmm apply` has
    copied it across; the overlay opens and sits empty until the mod is applied
    and the game has run, which beats "your overlay does not exist".

    A mod present in both is reported once, from the install. A malformed
    declaration is reported on its own entry rather than dropped — a silent
    disappearance is the hardest kind of bug to chase.
    """
    installed = mods_dir(game_dir)
    roots: list[tuple[Path, str]] = [(installed, "game")]
    if include_library:
        library = library_dir()
        if library and library.resolve() != installed.resolve():
            roots.append((library, "library"))

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root, source in roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith(("_", ".")):
                continue
            mf = entry / "manifest.toml"
            if not mf.is_file():
                continue
            record = _read_one(entry, mf, game_dir, source)
            if record is None or record["modId"] in seen:
                continue
            seen.add(record["modId"])
            out.append(record)
    return out


def _read_one(entry: Path, mf: Path, game_dir: Path | str | None,
              source: str) -> dict[str, Any] | None:
    """One mod's overlay record, or None when the mod declares no overlay."""
    try:
        data = tomllib.loads(mf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = data.get("overlay")
    if raw is None:
        return None
    mod_meta = data.get("mod", {}) if isinstance(data.get("mod"), dict) else {}
    mod_id = str(mod_meta.get("id") or entry.name)
    record: dict[str, Any] = {
        "modId": mod_id,
        "modName": str(mod_meta.get("name") or mod_id),
        "enabled": bool(mod_meta.get("enabled", True)),
        # Which tree the DECLARATION came from. "library" means the mod has not
        # been applied yet, so it will have no rows until it is.
        "source": source,
    }
    try:
        spec = parse_spec(raw, mod_id=mod_id)
    except OverlayError as e:
        # A `title` even on the failure path. Every consumer treats it as the
        # one key always present — `render` indexes it directly — so omitting
        # it turned "report the malformed declaration" into a KeyError that
        # took the whole command down, which is the opposite of the intent.
        record.update({"title": record["modName"], "error": str(e),
                       "rows": [], "meta": {}, "updated": 0, "exists": False})
        return record
    record.update(spec)
    live = read_rows(state_file(game_dir, entry.name))
    if live is None:
        record.update({"rows": [], "meta": {}, "updated": 0, "exists": False})
    else:
        rows, meta, updated = live
        record.update({"rows": _sorted_rows(rows, spec), "meta": meta,
                       "updated": updated, "exists": True})
    return record



def _compact(n: float) -> str:
    a = abs(n)
    if a >= 1_000_000:
        return f"{n / 1_000_000:.1f}m"
    if a >= 10_000:
        return f"{n / 1000:.0f}k"
    if a >= 1000:
        return f"{n / 1000:.1f}k"
    return f"{n:.0f}"


def _cell(row: dict[str, Any], col: dict[str, Any]) -> str:
    v = row.get(col["key"])
    if v is None:
        return ""
    if col["type"] == "text":
        return str(v)
    if col["type"] == "bar":
        try:
            return _term.bar(float(v), size=14, s=_ST)
        except (TypeError, ValueError):
            return ""
    try:
        num = float(v)
    except (TypeError, ValueError):
        return str(v)
    if col["type"] == "percent":
        return f"{num * 100:.0f}%"
    body = _compact(num) if col["format"] == "compact" else f"{num:,.0f}"
    return body + col["suffix"]


def _age(updated: int) -> str:
    if not updated:
        return "never"
    secs = max(0, int(time.time()) - updated)
    if secs < 90:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    return f"{secs // 3600}h ago"


def render(record: dict[str, Any]) -> list[str]:
    # Belt and braces: a record should always carry a title (see _read_one),
    # but rendering is the last thing standing between a bad manifest and the
    # user, and it must degrade rather than raise.
    title = record.get("title") or record.get("modName") or record.get("modId")
    out = [_ST.heading(f"  {title}"), ""]
    if record.get("error"):
        out.append("  " + _ST.err(str(record["error"])))
        return out
    meta_bits = [f"{k} {v}" for k, v in sorted(record.get("meta", {}).items())]
    meta_bits.append(f"updated {_age(int(record.get('updated') or 0))}")
    out.append("  " + _ST.dim("   ".join(meta_bits)))
    out.append("")
    rows = record.get("rows") or []
    if not rows:
        out.append("  " + _ST.dim(str(record.get("empty") or "No data yet.")))
        return out

    columns = record["columns"]
    # Width per column from the widest cell, so a mod's own column set lays
    # itself out. Pad the PLAIN string: padding a styled one counts the escape
    # bytes as width and mis-aligns every row.
    cells = [[_cell(r, c) for c in columns] for r in rows]
    widths = [
        max(len(c["label"]), *(_term.visible_len(row[i]) for row in cells))
        for i, c in enumerate(columns)
    ]
    header = "  " + "  ".join(c["label"].ljust(widths[i]) for i, c in enumerate(columns))
    out.append(_ST.dim(header))
    highlight = record.get("highlight")
    for row, line_cells in zip(rows, cells, strict=True):
        parts = []
        for i, text in enumerate(line_cells):
            pad = " " * max(0, widths[i] - _term.visible_len(text))
            # Numbers (and percentages) read as a column when right-aligned;
            # text and bars read as one when left-aligned.
            right = columns[i]["type"] in ("number", "percent")
            parts.append(pad + text if right else text + pad)
        line = "  " + "  ".join(parts)
        out.append(_ST.bold(line) if highlight and row.get(highlight) else line)
    return out


def _list_lines(records: list[dict[str, Any]]) -> list[str]:
    out = [_ST.heading("  overlays declared by installed mods"), ""]
    if not records:
        out.append("  " + _ST.dim("none — a mod declares one with an [overlay] "
                                  "block in its manifest.toml"))
        return out
    for r in records:
        state = _ST.err("invalid") if r.get("error") else (
            _ST.ok("live") if r.get("exists") else _ST.dim("idle"))
        out.append(f"  {r['modId']:<24}{r.get('title', ''):<20}{state}")
    return out


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    ap = argparse.ArgumentParser(
        prog="rsmm overlay",
        description="show the live HUD data a mod publishes (see its "
                    "[overlay] manifest block)",
    )
    ap.add_argument("mod_id", nargs="?", default=None,
                    help="mod to show; omit to list every declared overlay")
    ap.add_argument("--game-dir", default=None, help="game install directory")
    ap.add_argument("-w", "--watch", action="store_true", help="refresh until interrupted")
    ap.add_argument("-i", "--interval", type=float, default=2.0,
                    help="seconds between refreshes with --watch (default 2)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    def pick() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        records = discover(args.game_dir)
        if not args.mod_id:
            return records, None
        for r in records:
            if r["modId"] == args.mod_id:
                return records, r
        return records, None

    if args.json:
        records, one = pick()
        print(json.dumps(one if args.mod_id else records, indent=2))
        return 0 if (one or not args.mod_id) else 1

    def draw() -> int:
        records, one = pick()
        if args.mod_id and one is None:
            print(_ST.warn(f"  no installed mod {args.mod_id!r} declares an [overlay]"))
            return 1
        lines = render(one) if one else _list_lines(records)
        print("\n".join(lines))
        return 0

    if not args.watch:
        return draw()

    from rsmm.cli import _keys
    interval = max(0.2, args.interval)
    try:
        if _keys.available():
            # Alternate screen: without it every refresh is appended to
            # scrollback and the terminal grows for the whole session.
            with _keys.alt_screen():
                while True:
                    sys.stdout.write("\033[H\033[2J")
                    draw()
                    print()
                    print("  " + _ST.dim("ctrl-c to quit"))
                    sys.stdout.flush()
                    time.sleep(interval)
        else:
            while True:
                draw()
                time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
