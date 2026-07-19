"""Interactive home screen — what bare `./rsmm` opens in a terminal.

Deliberately a numbered menu over `input()` rather than a curses/full-screen
TUI: the runtime is stdlib-only, this has to survive SSH, WSL, the Steam
overlay console and CI, and every action here already exists as a subcommand.
The menu dispatches to those, so there is exactly one implementation of each
verb and nothing to keep in sync.

Never reached unless stdin AND stdout are TTYs — piping `rsmm` keeps printing
the help text, so scripts and the desktop app are unaffected.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from rsmm.cli import _keys, _term
from rsmm.cli._keys import termios
from rsmm.engine import paths as P

_ST = _term.Style()

# Hoisted: Python 3.11 forbids backslash escapes inside f-string expressions.
_ARROW = "\u203a"      # ›
_ENTER = "\u21b5"      # ↵
_DOT = "\u00b7"        # ·


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    argv: list[str]
    hint: str = ""
    # Name of a context flag that must be truthy for this action to be worth
    # running. A menu that offers "Apply" with nothing enabled, or hides the
    # fact that the loader is missing, is just a list of words.
    needs: str = ""


@dataclass(frozen=True)
class Context:
    game: bool = False
    loader: bool = False
    mods: int = 0
    enabled: int = 0
    applied: int = 0

    def has(self, flag: str) -> bool:
        return bool(getattr(self, flag, True)) if flag else True


# Browsing, enabling, disabling, applying and restoring are one workflow, not
# five destinations — they all live on the Mods screen (see `_mods_screen`).
ACTIONS: tuple[Action, ...] = (
    Action("1", "Mods",    [],  "browse, toggle, apply, restore"),
    Action("2", "Doctor",  ["doctor"], "health check"),
    Action("3", "Log",     [], "read, scroll and copy loader output"),
    Action("4", "Save",    ["save"], "inspect profile saves"),
    Action("5", "Symbols", [], "browse and filter the engine symbol map"),
)


# The stock winhttp.dll Steam ships is ~713 KB; the loader proxy is several MB.
_STOCK_DLL_MAX = 1_000_000


def probe() -> Context:
    """Gather menu state. Every lookup is individually failure-tolerant: this
    is a header, not a diagnostic, and a missing game must still render a
    usable menu rather than a traceback."""
    game_dir = None
    try:
        game_dir = Path(P.DEFAULT_GAME_DIR)
    except Exception:  # noqa: BLE001
        pass
    game = bool(game_dir and game_dir.is_dir())

    loader = False
    applied = 0
    if game and game_dir is not None:
        dll = game_dir / "winhttp.dll"
        loader = dll.is_file() and dll.stat().st_size > _STOCK_DLL_MAX
        try:
            state = json.loads(
                (game_dir / "DarkTalesResources" / "_Cooking"
                 / ".rsmm_state.json").read_text(encoding="utf-8")
            )
            applied = len(state.get("active") or {})
        except (OSError, ValueError):
            applied = 0

    mods = enabled = 0
    try:
        # Reuse cmd_mods' parser rather than re-sniffing manifests here:
        # they align the value (`enabled     = true`), so a naive
        # "enabled = true" substring check silently reports 0 enabled.
        from rsmm.cli.cmd_mods import _all_mod_ids, _states

        mods_dir = Path(P.mods_dir())
        ids = _all_mod_ids(mods_dir)
        mods = len(ids)
        enabled = sum(1 for on in _states(mods_dir, ids).values() if on)
    except Exception:  # noqa: BLE001
        pass

    return Context(game=game, loader=loader, mods=mods,
                   enabled=enabled, applied=applied)


def status_bits(ctx: Context) -> list[str]:
    """Header fragments. Split from probe() so it is testable without a game."""
    bits = [f"{_ST.dim('game')} " + (_ST.ok("found") if ctx.game
                                     else _ST.err("not found"))]
    if ctx.game:
        bits.append(f"{_ST.dim('loader')} " + (_ST.ok("installed") if ctx.loader
                                               else _ST.warn("not installed")))
    bits.append(f"{_ST.dim('mods')} {ctx.mods} "
                + (_ST.ok(f"({ctx.enabled} on)") if ctx.enabled
                   else _ST.dim("(none on)")))
    if ctx.applied:
        bits.append(f"{_ST.dim('applied')} {_ST.ok(str(ctx.applied))}")
    return bits


def next_step(ctx: Context) -> str:
    """The one thing most worth doing right now, or "" if all is well.

    This is the difference between a list of verbs and something that helps:
    the common failure modes here are silent (loader reverted by a Steam
    update, mods enabled but never applied).
    """
    if not ctx.game:
        return "game not found — check the install, then run `doctor`"
    if not ctx.loader:
        return "loader not installed — run `install-loader` for Lua mods"
    if ctx.enabled and not ctx.applied:
        return (f"{ctx.enabled} mod(s) enabled but nothing applied "
                "— open Mods, then press a")
    return ""


def _version() -> str:
    """Release version for the header. Four files carry it; the desktop
    package.json is the user-facing one (root pyproject stays at 0.1.0)."""
    try:
        pkg = json.loads(
            (P.REPO_ROOT / "apps" / "desktop" / "package.json").read_text(
                encoding="utf-8")
        )
        return str(pkg.get("version") or "")
    except (OSError, ValueError):
        return ""


def _out(line: str = "") -> None:
    """Write one line. Raw mode disables ONLCR, so \n alone would stair-step."""
    sys.stdout.write(line + "\r\n")


def _render(ctx: Context, cursor: int = -1) -> list[int]:
    """Draw the screen. Returns the terminal row of each action, so a mouse
    click can be mapped back to the row it landed on."""
    w = _term.width()
    ver = _version()
    _out()
    _out(_term.panel_top("", _ST, w))
    title = _ST.heading("rsmm") + _ST.dim("  Ravenswatch Mod Manager")
    if ver:
        pad = max(0, w - _term.visible_len(title) - _term.visible_len(ver) - 4)
        title = title + " " * pad + _ST.dim(f"v{ver}")
    _out(_term.panel_row(title, _ST, w))
    _out(_term.panel_row(_ST.dim(" · ").join(status_bits(ctx)), _ST, w))
    step = next_step(ctx)
    if step:
        _out(_term.panel_row(_ST.warn(_ARROW + " ") + _ST.dim(step), _ST, w))
    _out(_term.panel_bottom(_ST, w))
    _out()

    # One column with hints beats two without: the hint is what makes an
    # unfamiliar verb usable, and 9 rows still fit any terminal.
    rows: list[int] = []
    line = 7 if next_step(ctx) else 6          # first action's screen row
    for i, a in enumerate(ACTIONS):
        # Unmet preconditions dim rather than disappear: hiding rows would
        # shift the numbering between renders.
        live = ctx.has(a.needs)
        sel = i == cursor
        key = _ST.accent(a.key) if live else _ST.dim(a.key)
        label = a.label if live else _ST.dim(a.label)
        pad = " " * max(0, 13 - len(a.label))
        marker = _ST.accent(_ARROW) if sel else " "
        body = f"{key}  {label}{pad}{_ST.dim(a.hint)}"
        _out(f" {marker} {body}")
        rows.append(line + i)
    _out(f"   {_ST.accent('q')}  Quit")
    _out()
    return rows


def _run_paged(argv: list[str], title: str) -> int:
    """Run a subcommand, then show its output in the pager.

    On the alternate screen the terminal's own scrollback is unavailable, so a
    long `doctor` or `save` report would scroll off with no way back. Capturing
    and paging keeps it readable (and copyable). Only used for commands that
    do not prompt — anything interactive still owns the terminal directly.
    """
    import io
    from contextlib import redirect_stderr, redirect_stdout

    from rsmm.cli import _dispatch

    buf = io.StringIO()
    saved = sys.argv[:]
    saved_force = os.environ.get("FORCE_COLOR")
    # Subcommands decide colour from stdout.isatty() when their module is
    # first imported. Under capture that is a StringIO, so doctor/lint came
    # out completely uncoloured. FORCE_COLOR is the documented override.
    os.environ["FORCE_COLOR"] = "1"
    rc = 0
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = int(_dispatch.main(argv) or 0)
    except SystemExit as e:
        rc = int(e.code or 0)
    except Exception as e:  # noqa: BLE001 - report, never kill the menu
        buf.write(f"\ncommand failed: {type(e).__name__}: {e}\n")
        rc = 1
    finally:
        sys.argv = saved
        if saved_force is None:
            os.environ.pop("FORCE_COLOR", None)
        else:
            os.environ["FORCE_COLOR"] = saved_force
    pager(title, buf.getvalue().splitlines(), copy_name=title)
    return rc


def _run(argv: list[str]) -> int:
    """Dispatch a subcommand in-process.

    Runs through the same `_dispatch.main` the shell entrypoint uses, so there
    is one routing implementation. In-process rather than re-exec because a
    fresh interpreter per keystroke costs ~200ms and buys nothing: stdout is
    the same TTY either way. Subcommands that call sys.exit() raise
    SystemExit, which is caught here so one bad command cannot kill the menu.
    """
    from rsmm.cli import _dispatch

    _out(_ST.dim(f"$ rsmm {' '.join(argv)}"))
    _out()
    saved = sys.argv[:]
    try:
        return int(_dispatch.main(argv) or 0)
    except SystemExit as e:            # argparse errors, explicit exits
        return int(e.code or 0)
    except KeyboardInterrupt:
        _out()
        return 130
    except Exception as e:             # noqa: BLE001 - never kill the menu
        _out(_ST.err(f"command failed: {type(e).__name__}: {e}"))
        return 1
    finally:
        sys.argv = saved


def _prompt() -> str:
    """Boxed input line. The frame is drawn around the cursor so the prompt
    reads as a widget rather than a bare shell `>`."""
    w = _term.width()
    b = _term.box_chars()
    _out(_term.panel_top("", _ST, w))
    try:
        cursor = _ST.accent(_ARROW)
        reply = input(f"{_ST.dim(b['v'])} {cursor} ").strip()
    finally:
        _out(_term.panel_bottom(_ST, w))
    return reply


def _mods_screen() -> None:
    """The whole mod lifecycle on one screen.

    Toggling writes the manifest immediately (exactly what `rsmm enable
    --no-apply` does) rather than batching into a hidden pending state: the
    file is the source of truth everywhere else in the tool, and a staged
    layer here would be a second one to disagree with it.
    """
    from rsmm.cli.cmd_mods import _all_mod_ids, _states, set_mod_enabled

    mods_dir = Path(P.mods_dir())
    cursor = 0
    note = ""
    with _keys.raw_session():
        while True:
            ids = _all_mod_ids(mods_dir)
            if not ids:
                _out(_ST.warn(f"  no mods under {mods_dir}"))
                return
            cursor = max(0, min(cursor, len(ids) - 1))
            state = _states(mods_dir, ids)
            ctx = probe()
            on = sum(1 for v in state.values() if v)

            sys.stdout.write("\033[2J\033[H")
            w = _term.width()
            _out()
            _out(_term.panel_top("", _ST, w))
            _out(_term.panel_row(
                _ST.heading("mods") + _ST.dim(f"   {len(ids)} installed") +
                _ST.dim(" · ") + (_ST.ok(f"{on} enabled") if on
                                  else _ST.dim("none enabled")) +
                _ST.dim(" · ") + (_ST.ok(f"{ctx.applied} applied") if ctx.applied
                                  else _ST.dim("not applied")), _ST, w))
            _out(_term.panel_bottom(_ST, w))
            _out()

            # Keep the cursor's row on screen without a full pager: show a
            # window around it when the list is longer than the terminal.
            height = max(6, _term.height() - 12)
            start = max(0, min(cursor - height // 2, len(ids) - height))
            visible = ids[start:start + height]
            rows: list[int] = []
            first_row = 6
            for i, mod_id in enumerate(visible):
                idx = start + i
                sel = idx == cursor
                box = _ST.ok("[x]") if state.get(mod_id) else _ST.dim("[ ]")
                name = _ST.bold(mod_id) if sel else mod_id
                marker = _ST.accent(_ARROW) if sel else " "
                _out(f" {marker} {box} {name}")
                rows.append(first_row + i)
            if len(ids) > len(visible):
                _out(_ST.dim(f"    … {len(ids) - len(visible)} more"))
            _out()
            if note:
                _out("  " + note)
                _out()
            _out(_ST.dim(
                f"  \u2191\u2193 move  {_DOT} space/\u21b5 toggle  {_DOT} click"
                f"  {_DOT} a apply  {_DOT} r restore  {_DOT} q back"))
            sys.stdout.flush()

            try:
                ev = _keys.read_key()
            except KeyboardInterrupt:
                return          # ctrl-c leaves the screen, like q
            if ev is None:
                return
            if ev[0] == _keys.MOTION:
                _, _col, row = ev
                for i, r in enumerate(rows):
                    if r == row and cursor != start + i:
                        cursor = start + i
                        break
                else:
                    continue
                continue
            if ev[0] == "click":
                _, _col, row = ev
                for i, r in enumerate(rows):
                    if r == row:
                        cursor = start + i
                        mod_id = ids[cursor]
                        set_mod_enabled(mods_dir, mod_id, not state.get(mod_id))
                        note = ""
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
            elif key in (" ", _keys.ENTER):
                mod_id = ids[cursor]
                set_mod_enabled(mods_dir, mod_id, not state.get(mod_id))
                note = ""
            elif key in ("a", "r"):
                verb = ["apply"] if key == "a" else ["restore"]
                # Drop out of raw mode so the subcommand owns the terminal.
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.flush()
                with _suspend_raw():
                    _run(verb)
                    _pause("back to mods")
                note = ""
            elif key in ("q", _keys.ESC):
                return


def _drain_stdin() -> None:
    """Discard anything already queued on stdin.

    Mouse reporting keeps writing to the input buffer while a subcommand owns
    the screen. Without this the bytes are still there afterwards and the next
    `input()` consumes them as its answer — the prompt appears to answer
    itself and the leftovers land in the menu as phantom keypresses.
    """
    if not termios:
        return
    with contextlib.suppress(OSError, ValueError):
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)


def _pause(label: str) -> bool:
    """"[enter] <label>" prompt, with the input queue drained first.

    A long `apply` gives the user seconds to type or move the mouse; those
    bytes sit in the buffer and would otherwise be swallowed by this prompt,
    which then returns instantly and looks like the UI skipped past itself.

    Returns False if the user pressed ctrl-c / ctrl-d, so callers can keep
    treating that as "leave" rather than "continue".
    """
    _drain_stdin()
    try:
        input(_ST.dim(f"  [enter] {label} "))
        return True
    except (EOFError, KeyboardInterrupt):
        print()
        return False


@contextlib.contextmanager
def _suspend_raw():
    """Temporarily restore cooked mode so a subcommand can print and prompt.

    Uses `_keys._MOUSE_OFF` / `_MOUSE_ON` rather than its own escape literals.
    A hand-written copy here disabled 1006 and 1000 but NOT 1003 (all-motion
    reporting), so while `apply`/`restore` ran, every mouse movement sprayed
    escape sequences onto the now-echoing terminal and into the `[enter]`
    prompt. Deriving both strings from one place makes that drift impossible.
    """
    # No termios (Windows) means no mode juggling to do — and stdin may not
    # even have a fileno(), so don't ask for one.
    fd = sys.stdin.fileno() if termios else -1
    saved = termios.tcgetattr(fd) if termios else None
    try:
        if termios:
            # Restore the REAL cooked attrs captured before tty.setraw. The
            # old shortcut here only OR-ed ECHO|ICANON back into the raw
            # attrs, leaving OPOST off (every print() from apply/restore
            # emitted LF with no CR, so the output stair-stepped down the
            # screen), ICRNL off (Enter arrived as CR and never satisfied
            # input()) and ISIG off (ctrl-c dead). That is what "the whole
            # UI breaks after apply" was.
            cooked = _keys._PRE_RAW
            if cooked is None:
                cooked = termios.tcgetattr(fd)
                cooked[1] |= termios.OPOST | termios.ONLCR    # oflags
                cooked[0] |= termios.ICRNL                    # iflags
                cooked[3] |= termios.ECHO | termios.ICANON | termios.ISIG
            termios.tcsetattr(fd, termios.TCSADRAIN, cooked)
        sys.stdout.write(_keys._MOUSE_OFF + _keys._SHOW_CURSOR)
        sys.stdout.flush()
        _drain_stdin()
        yield
    finally:
        _drain_stdin()
        if termios and saved is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write(_keys._MOUSE_ON + _keys._HIDE_CURSOR)
        sys.stdout.flush()


def pager(title: str, lines: list[str], *, colorize=None,
          copy_name: str = "output") -> None:
    """Scrollable viewer with copy — the one scrolling implementation.

    Needed because the TUI runs on the alternate screen, where the terminal's
    own scrollback is unavailable: anything longer than the window would
    otherwise be unreadable. Used for the loader log, for captured subcommand
    output, and for the symbol map.
    """
    from rsmm.cli import _clip

    if not lines:
        lines = ["(nothing to show)"]
    note = ""
    top = 0
    with _keys.raw_session():
        while True:
            page = max(4, _term.height() - 8)
            top = max(0, min(top, max(0, len(lines) - page)))
            w = _term.width()
            sys.stdout.write("\033[2J\033[H")
            _out()
            _out(_term.panel_top("", _ST, w))
            span = f"{top + 1}-{min(top + page, len(lines))} of {len(lines)}"
            _out(_term.panel_row(_ST.heading(title) + _ST.dim(f"   {span}"),
                                 _ST, w))
            _out(_term.panel_bottom(_ST, w))
            _out()
            for ln in lines[top:top + page]:
                text = colorize(ln) if colorize else ln
                # ANSI-aware: a raw slice would cut inside an escape sequence
                # and bleed colour across the rest of the screen.
                _out("  " + _term.truncate(text, w - 4))
            _out()
            if note:
                _out("  " + note)
                _out()
            _out(_ST.dim(
                f"  \u2191\u2193/PgUp/PgDn/wheel scroll  {_DOT} g/G top/end"
                f"  {_DOT} c copy all  {_DOT} y copy screen  {_DOT} q back"))
            sys.stdout.flush()

            try:
                ev = _keys.read_key()
            except KeyboardInterrupt:
                return          # ctrl-c leaves the pager, like q
            if ev is None:
                return
            if ev[0] == _keys.MOTION:
                continue          # nothing hoverable here; avoid repaint churn
            key = ev[0]
            if key == _keys.UP:
                top -= 1
            elif key == _keys.DOWN:
                top += 1
            elif key == _keys.WHEEL_UP:
                top -= 3
            elif key == _keys.WHEEL_DOWN:
                top += 3
            elif key == _keys.PGUP:
                top -= page
            elif key == _keys.PGDN:
                top += page
            elif key in ("g", _keys.HOME):
                top = 0
            elif key in ("G", _keys.END):
                top = len(lines)
            elif key in ("c", "y"):
                chunk = lines if key == "c" else lines[top:top + page]
                dest = Path(P.REPO_ROOT) / f"rsmm_{copy_name}_copy.txt"
                msg = _clip.copy_or_dump("\n".join(chunk) + "\n", dest)
                if _clip.is_ssh() and "clipboard" not in msg:
                    msg += " (ssh session: no local clipboard)"
                note = _ST.ok(f"{len(chunk)} lines \u2014 ") + _ST.dim(msg)
            elif key in ("q", _keys.ESC):
                return


def _log_screen() -> None:
    """The loader log, scrollable and copyable."""
    # Ask cmd_log where the log is instead of deriving it here — this screen
    # had its own guess (`<game>/rsmm/rsmm_log.txt`), which has never been a
    # real path, so the tab was always empty while `rsmm log` worked.
    from rsmm.cli.cmd_log import log_file

    log_path = log_file()
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        pager("log", [f"no log at {log_path}", f"  {e}",
                      "launch the game once with the loader installed"],
              copy_name="log")
        return
    # Open at the end: the newest lines are what a crash report needs.
    pager("log", lines, colorize=_colorize_log, copy_name="log")


def _colorize_log(line: str) -> str:
    """Reuse cmd_log's line styling so the pager matches `rsmm log`."""
    from rsmm.cli.cmd_log import _style_line
    return _style_line(line)


def _symbols_screen() -> None:
    """Browse the engine symbol map.

    `rsmm symbols list` prints 155 entries in one shot, which is unusable
    inside a fixed window. This groups by category, colours by status (the
    field that actually matters: `unverified` means the loader fails closed
    on it) and supports a filter.
    """
    from rsmm.engine.symbols import load_symbol_map

    try:
        smap = load_symbol_map()
    except Exception as e:  # noqa: BLE001
        pager("symbols", [f"could not load the symbol map: {e}"],
              copy_name="symbols")
        return

    query = ""
    while True:
        rows: list[str] = []
        counts = {"ok": 0, "va": 0, "unverified": 0}
        for cat in smap.categories:
            syms = [x for x in sorted(smap.by_category(cat), key=lambda s: s.name)
                    if not query or query.lower() in x.name.lower()
                    or query.lower() in (x.status or "").lower()]
            if not syms:
                continue
            rows.append("")
            rows.append(f"# {cat}")
            for sym in syms:
                counts[sym.status] = counts.get(sym.status, 0) + 1
                addr = sym.preferred_addr(smap.preferred_base)
                rows.append(f"  [{sym.status:<10}] 0x{addr:09x}  {sym.name}")
                if sym.signature:
                    rows.append(f"               {sym.signature}")

        title = "symbols"
        if query:
            title += f"  /{query}"
        summary = "  ".join(f"{k}={v}" for k, v in counts.items() if v)
        rows.insert(0, summary)
        pager(title, rows, colorize=_colorize_symbol, copy_name="symbols")
        # pager returns on q; offer a filter round-trip rather than exiting
        # straight to the menu, which would make searching a two-step dance.
        with _suspend_raw():
            try:
                query = input(_ST.dim("  filter (blank = clear, q = back) > ")).strip()
            except (EOFError, KeyboardInterrupt):
                return
        if query.lower() == "q":
            return


def _colorize_symbol(line: str) -> str:
    if line.startswith("# "):
        return _ST.heading(line)
    if "[ok" in line:
        return line.replace("[ok        ]", _ST.ok("[ok        ]"))
    if "[unverified" in line:
        return line.replace("[unverified]", _ST.warn("[unverified]"))
    if "[va" in line:
        return line.replace("[va        ]", _ST.accent("[va        ]"))
    return _ST.dim(line)


SCREENS = {
    "Mods": _mods_screen,
    "Log": _log_screen,
    "Symbols": _symbols_screen,
}

# What the same action does when raw mode is unavailable and the user is on
# the plain numbered prompt.
TYPED_EQUIVALENT = {
    "Mods": ["list"],
    "Log": ["log", "--lines", "40"],
    "Symbols": ["symbols", "list"],
}


def _navigate(ctx: Context) -> Action | str | None:
    """Arrow-key + mouse loop. Returns the chosen Action, "type" to drop into
    the typed prompt, or None to quit.

    Only entered when `_keys.available()`. Unsupported terminals fall back to
    the numbered prompt: they lose the highlight, not any capability.
    """
    live = [i for i, a in enumerate(ACTIONS) if ctx.has(a.needs)] or [0]
    cursor = live[0]
    with _keys.raw_session():
        while True:
            # Full clear + redraw each keypress: simpler and more robust than
            # cursor arithmetic, which desyncs the moment a line wraps.
            sys.stdout.write("\033[2J\033[H")
            rows = _render(ctx, cursor)
            sys.stdout.write(_ST.dim(
                f"  \u2191\u2193 move  {_DOT} \u21b5 run  {_DOT} click a row"
                f"  {_DOT} / to type  {_DOT} q quit\r\n"))
            sys.stdout.flush()

            try:
                ev = _keys.read_key()
            except KeyboardInterrupt:
                return None     # ctrl-c quits the menu cleanly
            if ev is None:
                return None
            if ev[0] == _keys.MOTION:
                # Hover moves the highlight. Only redraw when the row actually
                # changes: motion events arrive per pixel-row of movement and
                # repainting on every one flickers and burns CPU.
                _, _col, row = ev
                for i, r in enumerate(rows):
                    if r == row and ctx.has(ACTIONS[i].needs) and cursor != i:
                        cursor = i
                        break
                else:
                    continue
                continue
            if ev[0] == "click":
                _, _col, row = ev
                for i, r in enumerate(rows):
                    if r == row and ctx.has(ACTIONS[i].needs):
                        return ACTIONS[i]
                continue

            key = ev[0]
            if key in (_keys.UP, _keys.DOWN):
                step = -1 if key == _keys.UP else 1
                idx = live.index(cursor) if cursor in live else 0
                cursor = live[(idx + step) % len(live)]
            elif key == _keys.ENTER:
                return ACTIONS[cursor]
            elif key in ("q", _keys.ESC):
                return None
            elif key.isdigit():
                for a in ACTIONS:
                    if a.key == key and ctx.has(a.needs):
                        return a
            elif key in ("/", ":"):
                return "type"


def main(argv: list[str] | None = None) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("rsmm: interactive menu needs a terminal; run `rsmm help`",
              file=sys.stderr)
        return 2

    by_key = {a.key: a for a in ACTIONS}
    typed_mode = not _keys.available()
    if typed_mode:
        return _loop(by_key, typed_mode)
    # Alternate screen: every redraw would otherwise be appended to the
    # scrollback, so a session leaves the terminal thousands of lines longer.
    # On exit the previous screen is restored exactly as it was.
    with _keys.alt_screen():
        return _loop(by_key, typed_mode)


def _loop(by_key: dict[str, Action], typed_mode: bool) -> int:
    while True:
        ctx = probe()

        if typed_mode:
            _render(ctx)
            print(_ST.dim(f"  number to run {_DOT} any rsmm command works "
                          f"{_DOT} q to quit"))
            try:
                reply = _prompt()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not reply:
                continue
            if reply.lower() in ("q", "quit", "exit"):
                return 0
            action = by_key.get(reply)
            if action is not None and not action.argv:
                # Typed fallback has no raw-mode screens; use the plain command.
                _run(TYPED_EQUIVALENT.get(action.label, ["list"]))
            else:
                _run(action.argv if action else reply.split())
        else:
            try:
                choice = _navigate(ctx)
            except KeyboardInterrupt:
                print()
                return 0
            if choice is None:
                return 0
            if choice == "type":
                # Escape hatch: run any command the menu does not list.
                try:
                    reply = _prompt()
                except (EOFError, KeyboardInterrupt):
                    print()
                    continue
                if not reply:
                    continue
                if reply.lower() in ("q", "quit", "exit"):
                    return 0
                _run(reply.split())
            elif not choice.argv:
                screen = SCREENS.get(choice.label)
                if screen:
                    screen()
                continue
            else:
                _run_paged(choice.argv, choice.label.lower())

        print()
        # ctrl-c / ctrl-d at this prompt still means "leave", as before.
        if not _pause("back to menu"):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
