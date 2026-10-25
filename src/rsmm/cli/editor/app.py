"""The editors' one request handler, independent of how the request arrived.

``handle(method, target, headers, body)`` routes a request to an editor and
returns a :class:`Reply`. Two transports call it: ``server`` (HTTP on
127.0.0.1, for ``rsmm editor``) and ``bridge`` (the web editor, where Pyodide
runs this in the browser and there is no socket). Everything that decides
what a request may do lives here, so the two cannot drift: routing, the
write token, the body rules and how errors become statuses. The transports
add only what belongs to them (the HTTP server's Host check and headers).

An editor is a module with a ``MOUNT`` (its path prefix), a ``PAGE`` (its
file under ``pages/``) and ``ROUTES``: ``(method, path) -> fn(req)``. A path
ending in ``*`` matches by prefix. ``fn`` returns JSON-able data or a
:class:`Raw`, and raises :class:`Fail` for a specific status. Any
``ValueError`` becomes a 400 carrying its message, which is how every
editor's domain errors reach the page.
"""

from __future__ import annotations

import json
import secrets
import struct
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cache, cached_property
from pathlib import Path
from urllib.parse import parse_qs, urlparse

#: Largest POST body accepted, in bytes.
MAX_BODY = 1 << 20

#: Shell tab -> (label, frame URL). Items and Talents are one page on two tabs.
TABS = {
    "items": ("Items", "/content/?tab=items"),
    "talents": ("Talents", "/content/?tab=talents"),
    "scripts": ("Scripts", "/content/?tab=scripts"),
    "abilities": ("Abilities", "/abilities/"),
    "map": ("Map", "/map/"),
    "save": ("Save file", "/save/"),
}

HTML = "text/html; charset=utf-8"
JSON = "application/json"


def asset_dir(name: str) -> Path:
    """``pages`` or ``static`` beside this module. A frozen build places them
    under the bundle's ``src/rsmm/cli/editor`` (see build-sidecar.py), which is
    where ``REPO_ROOT`` points when this module's own folder lacks them."""
    here = Path(__file__).resolve().parent / name
    if here.is_dir():
        return here
    from rsmm.engine.paths import REPO_ROOT
    return REPO_ROOT / "src" / "rsmm" / "cli" / "editor" / name


class Fail(Exception):
    """End the request with ``status`` and ``{"error": message}``."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Raw:
    """A non-JSON reply (a file, an image). ``cache`` marks it immutable for
    the editor's lifetime."""
    data: bytes
    ctype: str
    cache: bool = False


@dataclass
class Reply:
    status: int
    ctype: str
    data: bytes
    cache: bool = False
    headers: dict[str, str] = field(default_factory=dict)


def _json(status: int, obj) -> Reply:
    return Reply(status, JSON, json.dumps(obj).encode("utf-8"))


def _fail(status: int, message: str) -> Reply:
    return _json(status, {"error": message})


@dataclass
class Context:
    """Per-launch state: the write token, where mods are saved, the first tab."""
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    mods: Path | None = None
    start: str = "items"
    #: Keep pure read answers on disk across launches (the local editor; the
    #: web editor's disk is in memory and gone with the page).
    disk_cache: bool = False

    @property
    def mods_dir(self) -> Path:
        if self.mods is not None:
            return self.mods
        from rsmm.engine.paths import mods_dir
        return mods_dir()

    @cached_property
    def game(self) -> dict:
        """:func:`game_status`, once per launch: the scan for an install can be
        slow on Windows, and nothing that decides it changes while it runs."""
        return game_status()


@dataclass
class Request:
    ctx: Context
    method: str
    path: str                                  # inside the mount: "/api/items"
    query: dict[str, str]
    body: dict

    def arg(self, name: str, default: str = "") -> str:
        return self.query.get(name, default)


Route = Callable[[Request], object]


def _editors() -> dict[str, object]:
    from rsmm.cli.editor import abilities, content, maps, saves
    return {m.MOUNT: m for m in (content, abilities, maps, saves)}


@cache
def _read(name: str) -> str:
    return (asset_dir("pages") / name).read_text(encoding="utf-8")


def render(name: str, token: str, **subs: str) -> str:
    """A page with the shared CSS/JS inlined and the launch's token filled in."""
    page = (_read(name).replace("{{common.css}}", _read("common.css"))
            .replace("{{common.js}}", _read("common.js"))
            .replace("{{models.js}}", _read("models.js"))
            .replace("{{tilemode.js}}", _read("tilemode.js"))
            .replace("{{newmod.html}}", _read("newmod.html")))
    for key, value in subs.items():
        page = page.replace(key, value)
    return page.replace("__RSMM_TOKEN__", token)


def game_status() -> dict:
    """Which install the editors read, for the shell to name it or say none was
    found. ``dir`` is that install, else None; ``override`` is ``RSMM_GAME_DIR``
    when set (it is authoritative, so a wrong one is why nothing was found)."""
    import os

    from rsmm.cli.apply_mods import find_game_dir
    game = find_game_dir()
    return {"dir": str(game) if game else None,
            "override": os.environ.get("RSMM_GAME_DIR", "").strip() or None}


def _find(routes: Mapping, method: str, path: str) -> Route | None:
    fn = routes.get((method, path))
    if fn is not None:
        return fn
    for (m, p), f in routes.items():
        if m == method and p.endswith("*") and path.startswith(p[:-1]):
            return f
    return None


class _Gate:
    """One slow game-data answer at a time, NEWEST request first.

    Clicking through heroes or tabs while they load used to start every one of
    them at once; they shared the CPU (one GIL) and the per-function cache
    locks, so the hero the user actually stopped on was shown only after all
    the ones clicked past (three quick picks: ~2.1 s, all finishing together).
    A running answer cannot be interrupted, but everything still waiting is
    served last-in-first-out, and a waiter whose browser has hung up (an
    aborted pick) leaves without doing the work.
    """

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._busy = False
        self._waiting: list[object] = []

    def enter(self, alive: Callable[[], bool] | None) -> bool:
        me = object()
        with self._cv:
            self._waiting.append(me)
            while self._busy or self._waiting[-1] is not me:
                self._cv.wait(0.2)
                if alive is not None and not alive():
                    self._waiting.remove(me)
                    self._cv.notify_all()
                    return False
            self._waiting.pop()
            self._busy = True
            return True

    def leave(self) -> None:
        with self._cv:
            self._busy = False
            self._cv.notify_all()


_gate = _Gate()


def handle(ctx: Context, method: str, target: str, headers: Mapping[str, str],
           body: bytes = b"", alive: Callable[[], bool] | None = None) -> Reply:
    """``alive`` reports whether the client still wants the answer (the local
    server checks its socket); a slow read is skipped once it says no."""
    method = method.upper()
    url = urlparse(target)
    path = url.path
    if method not in ("GET", "POST"):
        return _fail(405, "method not allowed")
    if path == "/favicon.ico":
        return Reply(204, "image/x-icon", b"")
    if path == "/":
        if method != "GET":
            return _fail(405, "method not allowed")
        page = render("shell.html", ctx.token, __RSMM_TABS__=json.dumps(TABS),
                      __RSMM_TAB__=ctx.start if ctx.start in TABS else "items",
                      # "<" escaped: a folder named "</script>" must not end the shell's script.
                      __RSMM_GAME__=json.dumps(ctx.game).replace("<", "\\u003c"))
        return Reply(200, HTML, page.encode("utf-8"))

    mount, _, rest = path.lstrip("/").partition("/")
    editor = _editors().get(mount)
    if editor is None:
        return _fail(404, "not found")
    if path == f"/{mount}":
        # Relative URLs in the page resolve under the mount only with the slash.
        return Reply(301, "text/plain", b"", headers={"Location": f"/{mount}/"})
    if rest == "" and method == "GET":
        return Reply(200, HTML, render(editor.PAGE, ctx.token).encode("utf-8"))

    data: dict = {}
    if method == "POST":
        if not secrets.compare_digest(_header(headers, "X-RSMM-Token"), ctx.token):
            return _fail(403, "missing or wrong editor token")
        if not _header(headers, "Content-Type").startswith(JSON):
            return _fail(415, "expected application/json")
        if not 0 < len(body) <= MAX_BODY:
            return _fail(413, "request body missing or too large")
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return _fail(400, "body is not JSON")
        if not isinstance(data, dict):
            return _fail(400, "body must be an object")

    fn = _find(editor.ROUTES, method, "/" + rest)
    if fn is None:
        return _fail(404, "not found")
    # Pure game-data reads, kept across launches (see diskcache).
    # The header lets the web editor keep the same answers in the browser.
    cacheable = method == "GET" and "/" + rest in getattr(editor, "CACHED", ())
    key = None
    if ctx.disk_cache and cacheable:
        from rsmm.cli.editor import diskcache
        key = f"{mount}{target[len('/' + mount):]}"
        hit = diskcache.get(key)
        if hit is not None:
            return Reply(200, JSON, hit, headers=dict(GAME_DATA))
        if not _gate.enter(alive):
            return Reply(499, JSON, b"")       # the client left; nobody reads this
        try:
            # Made by another request while this one waited its turn.
            hit = diskcache.get(key)
            if hit is not None:
                return Reply(200, JSON, hit, headers=dict(GAME_DATA))
            return _run(fn, ctx, method, rest, url, data, key, cacheable)
        finally:
            _gate.leave()
    return _run(fn, ctx, method, rest, url, data, key, cacheable)


#: Marks an answer that depends only on the game data and the rsmm build.
GAME_DATA = {"X-RSMM-Cache": "game"}


def _run(fn, ctx: Context, method: str, rest: str, url, data: dict, key: str | None,
         cacheable: bool = False) -> Reply:
    req = Request(ctx, method, "/" + rest, {k: v[0] for k, v in parse_qs(url.query).items()},
                  data)
    try:
        out = fn(req)
    except Fail as e:
        return _fail(e.status, str(e))
    except (ValueError, KeyError, TypeError, struct.error) as e:
        return _fail(400, str(e))
    if isinstance(out, Raw):
        return Reply(200, out.ctype, out.data, cache=out.cache)
    reply = _json(200, out)
    if cacheable:
        reply.headers.update(GAME_DATA)
    if key is not None:
        from rsmm.cli.editor import diskcache
        diskcache.put(key, reply.data)
    return reply


def _header(headers: Mapping[str, str], name: str) -> str:
    """Case-insensitive lookup that works for dicts and ``email.message``."""
    value = headers.get(name)
    if value is None:
        low = name.lower()
        value = next((v for k, v in headers.items() if k.lower() == low), "")
    return value or ""
