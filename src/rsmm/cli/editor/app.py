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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

#: Largest POST body accepted, in bytes.
MAX_BODY = 1 << 20

#: Shell tab -> (label, frame URL). Items and Talents are one page on two tabs.
TABS = {
    "items": ("Items", "/content/?tab=items"),
    "talents": ("Talents", "/content/?tab=talents"),
    "abilities": ("Abilities", "/abilities/"),
    "map": ("Map", "/map/"),
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

    @property
    def mods_dir(self) -> Path:
        if self.mods is not None:
            return self.mods
        from rsmm.engine.paths import mods_dir
        return mods_dir()


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
    from rsmm.cli.editor import abilities, content, maps
    return {m.MOUNT: m for m in (content, abilities, maps)}


@cache
def _read(name: str) -> str:
    return (asset_dir("pages") / name).read_text(encoding="utf-8")


def render(name: str, token: str, **subs: str) -> str:
    """A page with the shared CSS/JS inlined and the launch's token filled in."""
    page = (_read(name).replace("{{common.css}}", _read("common.css"))
            .replace("{{common.js}}", _read("common.js")))
    for key, value in subs.items():
        page = page.replace(key, value)
    return page.replace("__RSMM_TOKEN__", token)


def _find(routes: Mapping, method: str, path: str) -> Route | None:
    fn = routes.get((method, path))
    if fn is not None:
        return fn
    for (m, p), f in routes.items():
        if m == method and p.endswith("*") and path.startswith(p[:-1]):
            return f
    return None


def handle(ctx: Context, method: str, target: str, headers: Mapping[str, str],
           body: bytes = b"") -> Reply:
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
                      __RSMM_TAB__=ctx.start if ctx.start in TABS else "items")
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
    return _json(200, out)


def _header(headers: Mapping[str, str], name: str) -> str:
    """Case-insensitive lookup that works for dicts and ``email.message``."""
    value = headers.get(name)
    if value is None:
        low = name.lower()
        value = next((v for k, v in headers.items() if k.lower() == low), "")
    return value or ""
