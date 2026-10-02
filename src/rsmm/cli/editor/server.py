"""`rsmm editor` over HTTP: 127.0.0.1 only, one token per launch.

A thin transport around ``app.handle``. It adds what only HTTP needs: the
Host check against DNS rebinding, the body cap before reading, and the
response headers (the one content-security policy every page runs under).
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rsmm.cli.editor import app

#: What the pages need: inline scripts and styles, three.js served from this
#: origin, blob: icons and textures, and the shell's same-origin frames.
CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
       "connect-src 'self'; img-src 'self' blob:; frame-src 'self'; frame-ancestors 'self'")


def _warm() -> None:
    """Fill the item, stat and hero-list caches before the page asks: ~350 ms
    of cooked-file parsing the page's first four requests would otherwise wait
    on. Talents are not warmed: all twelve heroes are ~9 s of CPU that would
    compete with the page's own requests. Best effort: a missing install just
    leaves the caches to fill on demand, as before."""
    try:
        from rsmm.cli.editor import content
        content.items()
        content.stats()
        content.heroes()
    except Exception:  # noqa: BLE001 -- warming is optional; the real request reports any error
        pass


class EditorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, ctx: app.Context):
        super().__init__(addr, Handler)
        self.ctx = ctx
        threading.Thread(target=_warm, daemon=True).start()

    @property
    def token(self) -> str:
        return self.ctx.token


class Handler(BaseHTTPRequestHandler):
    server: EditorServer

    def log_message(self, fmt, *args):  # quiet: the page reports status itself
        pass

    def _host_ok(self) -> bool:
        """Only answer requests addressed to this server by a loopback name.

        A page on any site can point a hostname it controls at 127.0.0.1 (DNS
        rebinding) and then read this server as same-origin. Its requests still
        carry that hostname in Host, which this refuses.
        """
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _reply(self, r: app.Reply) -> None:
        self.send_response(r.status)
        self.send_header("Content-Type", r.ctype)
        self.send_header("Content-Length", str(len(r.data)))
        # three.js and meshes never change while the editor runs.
        self.send_header("Cache-Control", "private, max-age=3600" if r.cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in r.headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(r.data)

    def _drain(self) -> None:
        """Read a refused request's body (within the cap) before replying:
        closing with unread bytes makes Windows reset the connection, and the
        client sees WinError 10053 instead of the refusal."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if 0 < n <= app.MAX_BODY:
            self.rfile.read(n)

    def _serve(self, method: str) -> None:
        if not self._host_ok():
            if method == "POST":
                self._drain()
            return self._reply(app._fail(403, "wrong host"))
        body = b""
        if method == "POST":
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._reply(app._fail(400, "bad content length"))
            if n > app.MAX_BODY:
                return self._reply(app._fail(413, "request body missing or too large"))
            body = self.rfile.read(n)
        return self._reply(app.handle(self.server.ctx, method, self.path, self.headers, body))

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")


def serve(port: int, *, tab: str = "items", mods: Path | None = None) -> EditorServer:
    """Bind the editor on 127.0.0.1. Port 0 picks a free one."""
    return EditorServer(("127.0.0.1", port), app.Context(mods=mods, start=tab))


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm editor",
        description="edit items, talents, abilities and maps in one local page")
    ap.add_argument("--tab", choices=list(app.TABS), default="items", help="tab to open on")
    ap.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default 8765)")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        srv = serve(args.port, tab=args.tab)
    except OSError:
        srv = serve(0, tab=args.tab)         # the default port is taken: take any free one
    url = f"http://127.0.0.1:{srv.server_address[1]}/#{args.tab}"
    print(f"rsmm editor: {url}")
    print(f"mods are saved under {srv.ctx.mods_dir}; install them with: rsmm apply")
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
