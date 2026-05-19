"""Smoke tests for the local web GUI.

These tests spin up the GUI server on an ephemeral port and exercise:
  * auth gate (no token = 401, bad host = 400)
  * CSRF gate on POST (missing header = 403)
  * /api/mods returns JSON shaped right
  * /api/repos round-trips add + remove (token + CSRF supplied)
  * HTML root carries the CSRF meta + sets the cookie

No browser involvement. No network — only loopback.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from rsmm.cli import gui


@contextmanager
def _serve():
    port = gui._free_port()
    gui.ALLOWED_HOSTS.update({f"127.0.0.1:{port}", f"localhost:{port}"})
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", port), gui.GuiHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    # Tiny delay so the listener is fully ready.
    time.sleep(0.05)
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


def _req(port: int, method: str, path: str, *, host: str | None = None,
         headers: dict | None = None, body: bytes | None = None
         ) -> tuple[int, dict, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    h = dict(headers or {})
    if host is None:
        host = f"127.0.0.1:{port}"
    h.setdefault("Host", host)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    out_h = {k: v for k, v in r.getheaders()}
    conn.close()
    return r.status, out_h, data


def test_root_requires_token():
    with _serve() as port:
        st, _, _ = _req(port, "GET", "/")
        assert st == 401


def test_bad_host_rejected():
    with _serve() as port:
        st, _, _ = _req(port, "GET", "/", host="evil.example.com")
        assert st == 400


def test_root_with_token_sets_cookie():
    with _serve() as port:
        st, headers, body = _req(port, "GET", f"/?token={gui.AUTH_TOKEN}")
        assert st == 200
        assert b"<title>RSMM</title>" in body
        assert b'name="csrf"' in body
        assert "Set-Cookie" in headers
        assert "rsmm_token=" in headers["Set-Cookie"]


def test_api_mods_requires_auth():
    with _serve() as port:
        st, _, _ = _req(port, "GET", "/api/mods")
        assert st == 401


def test_api_mods_returns_json():
    with _serve() as port:
        st, _, body = _req(
            port, "GET", "/api/mods",
            headers={"Cookie": f"rsmm_token={gui.AUTH_TOKEN}"},
        )
        assert st == 200
        data = json.loads(body)
        assert "mods" in data and isinstance(data["mods"], list)


def test_post_without_csrf_rejected():
    with _serve() as port:
        st, _, body = _req(
            port, "POST", "/api/repos/add",
            headers={"Cookie": f"rsmm_token={gui.AUTH_TOKEN}"},
            body=json.dumps({"url": "x"}).encode(),
        )
        assert st == 403


def test_repos_add_remove_roundtrip(tmp_path: Path, monkeypatch):
    # Redirect ~/.rsmm to a temp dir so we don't pollute the dev's config.
    # gui._load_repos / _save_repos both resolve Path.home() at call time,
    # so patching the classmethod is sufficient.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with _serve() as port:
        # Add
        st, _, body = _req(
            port, "POST", "/api/repos/add",
            headers={
                "Cookie": f"rsmm_token={gui.AUTH_TOKEN}",
                "X-CSRF-Token": gui.CSRF_TOKEN,
                "Content-Type": "application/json",
            },
            body=json.dumps({"url": "https://example.com/repo.json"}).encode(),
        )
        assert st == 200
        # List
        st, _, body = _req(
            port, "GET", "/api/repos",
            headers={"Cookie": f"rsmm_token={gui.AUTH_TOKEN}"},
        )
        urls = json.loads(body)["urls"]
        assert "https://example.com/repo.json" in urls
        # Remove
        st, _, body = _req(
            port, "POST", "/api/repos/remove",
            headers={
                "Cookie": f"rsmm_token={gui.AUTH_TOKEN}",
                "X-CSRF-Token": gui.CSRF_TOKEN,
                "Content-Type": "application/json",
            },
            body=json.dumps({"url": "https://example.com/repo.json"}).encode(),
        )
        assert st == 200
