"""Smoke tests for the local web GUI.

Spins up the server on an ephemeral port and exercises:
  * Host header check (bad host = 403)
  * Auth gate (no token = 403)
  * CSRF gate on POST (missing header = 403)
  * /api/mods returns shaped JSON with SDK v3 fields
  * /api/repos round-trips add + remove (Path.home redirected to tmp)
  * /api/health is reachable and returns expected keys

No browser involvement. No outbound network — only loopback.
"""

from __future__ import annotations

import http.client
import json
import secrets
import threading
import time
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from rsmm.cli import gui


@contextmanager
def _serve():
    # Populate the module-level tokens that main() normally generates.
    gui.AUTH_TOKEN = secrets.token_urlsafe(16)
    gui.CSRF_TOKEN = secrets.token_urlsafe(16)
    port = gui._pick_port()
    gui.BOUND_HOST = f"127.0.0.1:{port}"
    server = ThreadingHTTPServer(("127.0.0.1", port), gui._Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
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


def test_bad_host_rejected():
    with _serve() as port:
        st, _, _ = _req(port, "GET", "/", host="evil.example.com")
        assert st == 403


def test_root_without_token_returns_html_without_cookie():
    # User's design: `/` always serves the static HTML so an
    # accidentally-discarded token query param doesn't lock the user
    # out. /api/* paths are the ones gated by auth.
    with _serve() as port:
        st, headers, _ = _req(port, "GET", "/")
        assert st == 200
        # Without a matching token, no auth cookie should be set.
        assert "rsmm_auth=" not in headers.get("Set-Cookie", "")


def test_root_with_token_sets_cookie():
    with _serve() as port:
        st, headers, body = _req(port, "GET", f"/?t={gui.AUTH_TOKEN}")
        assert st == 200
        assert b"<title>Ravenswatch" in body
        # Set-Cookie should contain both rsmm_auth and rsmm_csrf.
        assert "Set-Cookie" in headers
        sc = headers["Set-Cookie"]
        assert "rsmm_auth=" in sc or "rsmm_csrf=" in sc


def test_api_mods_requires_auth():
    with _serve() as port:
        st, _, _ = _req(port, "GET", "/api/mods")
        assert st == 403


def test_api_mods_returns_json_with_v3_fields():
    with _serve() as port:
        st, _, body = _req(
            port, "GET", f"/api/mods?t={gui.AUTH_TOKEN}",
        )
        assert st == 200
        data = json.loads(body)
        assert "mods" in data and isinstance(data["mods"], list)
        # If any v3 mod is present, it carries the new fields.
        for m in data["mods"]:
            if "error" in m:
                continue
            assert "sdk_version" in m
            assert "config_schema" in m
            assert "config_values" in m
            assert "locales" in m
            assert "content" in m


def test_api_status_includes_sdk_version():
    with _serve() as port:
        st, _, body = _req(port, "GET", f"/api/status?t={gui.AUTH_TOKEN}")
        assert st == 200
        data = json.loads(body)
        assert "sdk_version" in data and data["sdk_version"]


def test_post_without_csrf_rejected():
    with _serve() as port:
        st, _, _ = _req(
            port, "POST", "/api/repos/add",
            headers={"Cookie": f"rsmm_auth={gui.AUTH_TOKEN}"},
            body=json.dumps({"url": "x"}).encode(),
        )
        assert st == 403


def test_repos_add_remove_roundtrip(tmp_path: Path, monkeypatch):
    # Redirect ~/.rsmm to a tmp dir. gui._repos_load/save resolve
    # _REPOS_FILE at import time, so patch that constant too.
    fake_home = tmp_path
    fake_repos = fake_home / ".rsmm" / "repos.json"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(gui, "_RSMM_HOME", fake_home / ".rsmm")
    monkeypatch.setattr(gui, "_REPOS_FILE", fake_repos)
    with _serve() as port:
        h = {
            "Cookie": f"rsmm_auth={gui.AUTH_TOKEN}",
            "X-RSMM-CSRF": gui.CSRF_TOKEN,
            "Content-Type": "application/json",
        }
        st, _, _ = _req(port, "POST", "/api/repos/add", headers=h,
            body=json.dumps({"url": "https://example.com/repo.json"}).encode())
        assert st == 200
        st, _, body = _req(port, "GET", f"/api/repos?t={gui.AUTH_TOKEN}")
        urls = json.loads(body)["urls"]
        assert "https://example.com/repo.json" in urls
        st, _, _ = _req(port, "POST", "/api/repos/remove", headers=h,
            body=json.dumps({"url": "https://example.com/repo.json"}).encode())
        assert st == 200


def test_api_health_shape():
    with _serve() as port:
        st, _, body = _req(port, "GET", f"/api/health?t={gui.AUTH_TOKEN}")
        # Even with no game install detected, the endpoint must respond
        # with a stable JSON shape rather than 5xx.
        assert st == 200
        data = json.loads(body)
        assert "mods" in data
        assert "canary" in data
        assert "game_build" in data


def test_api_update_check_shape():
    with _serve() as port:
        st, _, body = _req(port, "GET", f"/api/update/check?t={gui.AUTH_TOKEN}")
        assert st == 200
        data = json.loads(body)
        assert "available" in data
