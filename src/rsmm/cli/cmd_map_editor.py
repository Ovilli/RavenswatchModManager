#!/usr/bin/env python3
"""`rsmm map-editor` — edit a chapter's map-generation recipe in the browser.

Starts a small server on localhost and opens the editor. It shows every tile
slot of a chapter on a 3D (or top-down) view of the chapter's own terrain, read
from your install at request time, and lets you change how many of
each kind of tile the generator places, how far apart, which footprints each
kind fits, the per-flag quotas, and which kinds a slot may hold. Saving writes a
normal mod — `mods/<id>/manifest.toml` with one `tilegen` declaration — which
`rsmm apply` cooks onto the shipped recipe like any other content.

  rsmm map-editor                  # open the editor
  rsmm map-editor --port 9000      # pick the port
  rsmm map-editor --no-browser     # just print the URL

Only localhost is served, and every write must carry a token that exists only
in the page this process handed out, so another site open in the same browser
cannot write into your mods folder.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from rsmm.engine import map_editor as ME
from rsmm.engine import tilegen as TG
from rsmm.engine.paths import DATA_DIR, REPO_ROOT, mods_dir

MAX_BODY = 1 << 20
#: three.js, vendored so the page works offline. REPO_ROOT is PyInstaller's
#: bundle dir in a frozen build, where build-sidecar.py places this folder.
STATIC_DIR = REPO_ROOT / "src" / "rsmm" / "cli" / "map_editor_static"
STATIC_FILES = {"three.module.min.js": "text/javascript; charset=utf-8"}
#: What /api/file serves: locally extracted meshes and textures, nothing else.
FILE_ROOT = "3D"
FILE_TYPES = {".glb": "model/gltf-binary", ".png": "image/png"}
NEXT_STEP = "rsmm restore --all && rsmm apply"


def _editor_mods(root: Path) -> list[dict]:
    """Mods this editor wrote, with the chapter each one edits."""
    out = []
    if not root.is_dir():
        return out
    for man in sorted(root.glob("*/manifest.toml")):
        try:
            text = man.read_text(encoding="utf-8")
            if not text.startswith(ME.EDITOR_MARK):
                continue
            got = ME.read_manifest_edits(text)
        except (OSError, ValueError):
            continue
        if got:
            out.append({"id": man.parent.name, "chapter": got[0]})
    return out


class EditorServer(ThreadingHTTPServer):
    """Holds the per-launch token and the mods directory the handlers use."""

    daemon_threads = True

    def __init__(self, addr, token: str, root: Path):
        super().__init__(addr, Handler)
        self.token = token
        self.root = root


class Handler(BaseHTTPRequestHandler):
    server: EditorServer

    def log_message(self, fmt, *args):  # quiet: the page reports status itself
        pass

    # -- plumbing -------------------------------------------------------------

    def _host_ok(self) -> bool:
        """Only answer requests addressed to this server by a loopback name.

        A page on any site can point a hostname it controls at 127.0.0.1 (DNS
        rebinding) and then read this server as same-origin. Its requests still
        carry that hostname in Host, which this refuses.
        """
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _send(self, code: int, body: bytes, ctype: str, cache: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Meshes, textures and three.js never change while the editor runs.
        self.send_header("Cache-Control", "private, max-age=3600" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' blob:")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def _fail(self, code: int, msg: str) -> None:
        self._json(code, {"error": msg})

    # -- GET --------------------------------------------------------------------

    def do_GET(self):  # noqa: N802 (http.server naming)
        if not self._host_ok():
            return self._fail(403, "wrong host")
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/":
                from rsmm.cli.map_editor_page import PAGE

                page = PAGE.replace("__RSMM_TOKEN__", self.server.token)
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if url.path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if url.path == "/api/state":
                return self._json(200, {
                    "chapters": [{"key": c.key, "label": c.label} for c in ME.chapters()],
                    "mods": _editor_mods(self.server.root),
                })
            if url.path == "/api/recipe":
                ch = ME.find_chapter(q.get("chapter", ""))
                return self._json(200, {"chapter": {"key": ch.key, "label": ch.label},
                                        "recipe": ME.to_json(ME.load(ch))})
            if url.path.startswith("/static/"):
                name = url.path.removeprefix("/static/")
                f = STATIC_DIR / name
                if name not in STATIC_FILES or not f.is_file():
                    return self._fail(404, "not found")
                return self._send(200, f.read_bytes(), STATIC_FILES[name], cache=True)
            if url.path == "/api/file":
                return self._file(q.get("path", ""))
            if url.path in ("/api/terrain", "/api/scene", "/api/tiles", "/api/tile"):
                # All read from the user's own install or local mirror on
                # request; a 404 just means the page draws less.
                ch = ME.find_chapter(q.get("chapter", ""))
                try:
                    if url.path == "/api/terrain":
                        g = q.get("grid", "")
                        grid = int(g) if g.isdigit() else ME.TERRAIN_GRID
                        if grid not in ME.TERRAIN_GRIDS:
                            return self._fail(400, "bad grid")
                        return self._json(200, ME.terrain_json(ch, grid))
                    if url.path == "/api/scene":
                        return self._json(200, ME.scene_json(ch))
                    if url.path == "/api/tiles":
                        return self._json(200, {"tiles": ME.tile_pool_json(ch)})
                    return self._json(200, ME.tile_json(ch, q.get("path", "")))
                except ME.MapEditError as e:
                    return self._fail(404, str(e))
            if url.path == "/api/mod":
                mod_id = q.get("id", "")
                if not ME.valid_mod_id(mod_id):
                    return self._fail(400, "bad mod id")
                man = self.server.root / mod_id / "manifest.toml"
                text = man.read_text(encoding="utf-8") if man.is_file() else ""
                got = ME.read_manifest_edits(text) if text.startswith(ME.EDITOR_MARK) else None
                if not got:
                    return self._fail(404, f"{mod_id} is not a map-editor mod")
                import tomllib

                name = tomllib.loads(text).get("mod", {}).get("name", "")
                return self._json(200, {"chapter": got[0], "edits": got[1], "name": name})
        except (ME.MapEditError, TG.TileGenError) as e:
            return self._fail(400, str(e))
        return self._fail(404, "not found")

    def _file(self, rel: str):
        """A locally extracted mesh or texture under data/uncooked/3D, or 404."""
        parts = rel.split("/")
        ctype = FILE_TYPES.get(Path(rel).suffix.lower())
        if (not ctype or parts[0] != FILE_ROOT or len(parts) < 2 or "\\" in rel
                or any(s in ("", ".", "..") for s in parts)):
            return self._fail(404, "not found")
        base = (DATA_DIR / "uncooked" / FILE_ROOT).resolve()
        f = (DATA_DIR / "uncooked").joinpath(*parts).resolve()
        if not f.is_relative_to(base) or not f.is_file():
            return self._fail(404, "not found")
        return self._send(200, f.read_bytes(), ctype, cache=True)

    # -- POST -------------------------------------------------------------------

    def do_POST(self):  # noqa: N802
        if not self._host_ok():
            return self._fail(403, "wrong host")
        if not secrets.compare_digest(self.headers.get("X-RSMM-Token", ""), self.server.token):
            return self._fail(403, "missing or wrong editor token")
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._fail(415, "expected application/json")
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._fail(400, "bad content length")
        if not 0 < n <= MAX_BODY:
            return self._fail(413, "request body missing or too large")
        try:
            body = json.loads(self.rfile.read(n))
        except (ValueError, UnicodeDecodeError):
            return self._fail(400, "body is not JSON")
        if not isinstance(body, dict):
            return self._fail(400, "body must be an object")
        url = urlparse(self.path)
        try:
            ch = ME.find_chapter(str(body.get("chapter", "")))
            edits = body.get("edits") or {}
            if url.path == "/api/check":
                _level, changes = ME.build_level(ch, edits)
                return self._json(200, {"changes": changes})
            if url.path == "/api/save":
                return self._save(ch, body, edits)
        except (ME.MapEditError, TG.TileGenError) as e:
            return self._fail(400, str(e))
        return self._fail(404, "not found")

    def _save(self, ch: ME.Chapter, body: dict, edits: dict):
        mod_id = str(body.get("mod_id", "")).strip().lower()
        if not ME.valid_mod_id(mod_id):
            return self._fail(400, "mod id: use 2-64 lower-case letters, digits, '-' or '_'")
        _level, changes = ME.build_level(ch, edits)   # prove it cooks before writing
        if not changes:
            return self._fail(400, "nothing to save: every value matches the shipped recipe")
        name = str(body.get("name", "")).strip()[:80]
        text = ME.manifest_toml(mod_id, name, ch, edits)
        folder = self.server.root / mod_id
        man = folder / "manifest.toml"
        if man.is_file() and not man.read_text(encoding="utf-8").startswith(ME.EDITOR_MARK):
            return self._fail(409, f"mods/{mod_id} already exists and was not made by the map "
                                   f"editor; pick another id")
        folder.mkdir(parents=True, exist_ok=True)
        tmp = man.with_name(f"manifest.toml.{secrets.token_hex(4)}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(man)
        return self._json(200, {"path": f"mods/{mod_id}/manifest.toml",
                                "changes": changes, "next": NEXT_STEP})


def serve(port: int, root: Path) -> EditorServer:
    """Bind the editor on 127.0.0.1. Port 0 picks a free one."""
    return EditorServer(("127.0.0.1", port), token=secrets.token_urlsafe(24), root=root)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm map-editor",
                                 description="edit a chapter's map-generation recipe")
    ap.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default 8765)")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    if not ME.chapters():
        print("map-editor: no tile-generated chapters in the asset map "
              "(run `rsmm build` first)", file=sys.stderr)
        return 1
    try:
        srv = serve(args.port, mods_dir())
    except OSError:
        srv = serve(0, mods_dir())   # the default port is taken: take any free one
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"map editor: {url}")
    print(f"mods are saved under {mods_dir()}; install with: {NEXT_STEP}")
    print("Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
