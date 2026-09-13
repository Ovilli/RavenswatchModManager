"""`rsmm publish`: the CLI half of token publishing, against a fake local API.

Packing, linting and the S3 PUT are stubbed — they have their own tests — so
these exercise the protocol and the security rules: where the token may be
sent, where it is stored, and that it never reaches the output.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rsmm.cli import cmd_publish as P

TOKEN = "rsmm_pat_" + "A" * 43
VERSION_ID = "0b8f5f5e-3c1a-4f7e-9a0b-6d2c8e1f4a77"


class FakeApi(BaseHTTPRequestHandler):
    """Records requests; answers the publish flow. `server.plan` tunes replies."""

    def log_message(self, *args):  # keep pytest output clean
        pass

    def _reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method: str) -> None:
        srv = self.server
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else None
        srv.calls.append((method, self.path, self.headers.get("Authorization"), body))
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._reply(401, {"error": "unauthorized"})
        if (method, self.path) == ("GET", "/api/me"):
            return self._reply(200, {"id": "user-1", "name": "Modder"})
        if (method, self.path) == ("POST", "/api/mods/upload"):
            status = srv.plan.get("upload_status", 200)
            if status != 200:
                return self._reply(status, {"error": "nope"})
            return self._reply(200, {"uploadUrl": "https://s3-rsmm.me/x", "versionId": VERSION_ID,
                                     "publicUrl": "https://s3-rsmm.me/x", "expiresIn": 900})
        if self.path == f"/api/mods/versions/{VERSION_ID}/scan":
            return self._reply(200, {"ok": True, "status": "queued", "position": 1})
        if self.path == f"/api/mods/versions/{VERSION_ID}/scan-status":
            states = srv.plan.setdefault("states", ["queued", "clean"])
            state = states.pop(0) if len(states) > 1 else states[0]
            return self._reply(200, {"status": state, "position": 0})
        return self._reply(404, {"error": "not found"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


@pytest.fixture
def api(monkeypatch, tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
    srv.calls, srv.plan = [], {}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("RSMM_INDEX_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setenv("RSMM_CREDENTIALS_FILE", str(tmp_path / "creds.json"))
    monkeypatch.delenv("RSMM_API_TOKEN", raising=False)
    # Packing and the S3 PUT have their own tests; stub them here.
    import rsmm.cli.json_bridge as JB
    monkeypatch.setattr(P, "_lint", lambda mod_id: None)
    monkeypatch.setattr(JB, "pack_mod_metadata", lambda mod_id: {
        "ok": True, "path": str(tmp_path / "m.zip"), "sha256": "a" * 64, "sizeBytes": 10,
        "slug": "my-mod", "version": "1.0.0", "manifest": {"id": "my-mod", "name": "M",
                                                          "version": "1.0.0"}})
    srv.puts = []
    monkeypatch.setattr(JB, "put_bytes", lambda path, url: srv.puts.append(url) or {"ok": True})
    yield srv
    srv.shutdown()


def test_publish_runs_the_whole_flow_and_waits_until_live(api, monkeypatch):
    monkeypatch.setenv("RSMM_API_TOKEN", TOKEN)
    lines: list[str] = []
    assert P.publish("my-mod", poll=0.01, out=lines.append) == 0
    paths = [(m, p) for m, p, _a, _b in api.calls]
    assert paths[:3] == [("GET", "/api/me"), ("POST", "/api/mods/upload"),
                         ("POST", f"/api/mods/versions/{VERSION_ID}/scan")]
    assert ("GET", f"/api/mods/versions/{VERSION_ID}/scan-status") in paths
    assert api.puts == ["https://s3-rsmm.me/x"]
    assert api.calls[1][3]["sha256"] == "a" * 64
    assert lines[-1] == "Live: my-mod 1.0.0"
    assert all(TOKEN not in line for line in lines), "the token must never be printed"


@pytest.mark.parametrize("status, match", [
    (409, "already published"),
    (403, "nope"),
    (429, "rate limit"),
])
def test_upload_refusals_are_explained(api, monkeypatch, status, match):
    monkeypatch.setenv("RSMM_API_TOKEN", TOKEN)
    api.plan["upload_status"] = status
    with pytest.raises(P.PublishError, match=match):
        P.publish("my-mod", poll=0.01, out=lambda _l: None)
    assert api.puts == []


def test_a_flagged_scan_fails_the_publish(api, monkeypatch):
    monkeypatch.setenv("RSMM_API_TOKEN", TOKEN)
    api.plan["states"] = ["flagged"]
    with pytest.raises(P.PublishError, match="flagged"):
        P.publish("my-mod", poll=0.01, out=lambda _l: None)


def test_a_rejected_token_stops_before_packing(api, monkeypatch):
    monkeypatch.setenv("RSMM_API_TOKEN", "rsmm_pat_" + "B" * 43)
    with pytest.raises(P.PublishError, match="rejected"):
        P.publish("my-mod", out=lambda _l: None)
    assert [p for _m, p, _a, _b in api.calls] == ["/api/me"]


def test_token_is_never_sent_over_plain_http_to_a_remote_host(monkeypatch):
    monkeypatch.setenv("RSMM_INDEX_URL", "http://api.example.com")
    monkeypatch.setenv("RSMM_API_TOKEN", TOKEN)
    with pytest.raises(P.PublishError, match="https"):
        P.whoami(TOKEN)


def test_missing_or_malformed_token(monkeypatch, tmp_path):
    monkeypatch.setenv("RSMM_CREDENTIALS_FILE", str(tmp_path / "none.json"))
    monkeypatch.delenv("RSMM_API_TOKEN", raising=False)
    with pytest.raises(P.PublishError, match="no API token"):
        P.resolve_token()
    monkeypatch.setenv("RSMM_API_TOKEN", "hunter2")
    with pytest.raises(P.PublishError, match="malformed"):
        P.resolve_token()


def test_login_stores_the_token_owner_only(api, monkeypatch):
    monkeypatch.setattr(sys, "stdin", type("S", (), {
        "isatty": lambda self: False, "readline": lambda self: TOKEN + "\n"})())
    lines: list[str] = []
    assert P._login(out=lines.append) == 0
    path = P.credentials_path()
    assert json.loads(path.read_text())[P.api_base()] == TOKEN
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert P.resolve_token() == TOKEN
    assert all(TOKEN not in line for line in lines)
    assert P._logout(out=lines.append) == 0
    with pytest.raises(P.PublishError, match="no API token"):
        P.resolve_token()


def test_the_token_is_not_accepted_as_an_argument(capsys):
    # There is no --token flag: arguments land in shell history and `ps`.
    with pytest.raises(SystemExit):
        P.main(["my-mod", "--token", TOKEN])
