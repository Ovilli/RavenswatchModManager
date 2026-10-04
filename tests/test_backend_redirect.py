"""`rsmm backend` - pointing the game at a self-hosted backend."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from rsmm.cli import cmd_backend
from rsmm.cli.apply_mods import clear_runtime_mods
from rsmm.engine import backend_redirect as br

REDIRECT_DLL = b"MZ" + b"\0" * 100 + b"RSMM_BACKEND_URL" + b"\0" * 5000


@pytest.fixture
def game(tmp_path: Path) -> Path:
    """A game folder with a loader that can redirect."""
    (tmp_path / "Ravenswatch.exe").write_bytes(b"MZ")
    (tmp_path / "winhttp.dll").write_bytes(REDIRECT_DLL)
    (tmp_path / "mods").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def no_ambient_override(monkeypatch):
    # A developer who ran `setx` on their own machine must not change the results.
    monkeypatch.delenv(br.ENV_VAR, raising=False)


# --- the URL rules -----------------------------------------------------------

@pytest.mark.parametrize("raw, want", [
    ("http://85.214.117.164:8090", "http://85.214.117.164:8090"),
    ("85.214.117.164:8090", "http://85.214.117.164:8090"),          # pasted from a chat
    ("http://85.214.117.164:8090/", "http://85.214.117.164:8090"),  # trailing slash
    ("  http://example.org:8090  ", "http://example.org:8090"),
    ("HTTP://Example.ORG:8090", "http://example.org:8090"),          # loader is case-sensitive
    ("http://example.org", "http://example.org"),                    # port 80
    ("localhost:8090", "http://localhost:8090"),
    ("http://my-server.example.org:1", "http://my-server.example.org:1"),
])
def test_normalize_accepts_and_canonicalises(raw, want):
    assert br.normalize_url(raw) == want


@pytest.mark.parametrize("raw, fragment", [
    ("", "empty"),
    ("   ", "empty"),
    ("https://example.org:8090", "plain http"),
    ("http://example.org:8090/_federation", "no path"),
    ("http://example.org:8090/?x=1", "no path"),
    ("http://user:pw@example.org:8090", "user name"),
    ("http://[::1]:8090", "IPv6"),
    ("http://example.org:0", "out of range"),
    ("http://example.org:99999", "valid address"),
    ("http://exa mple.org", "usable host"),
])
def test_normalize_rejects_what_the_loader_would_silently_ignore(raw, fragment):
    # The loader does not fail on these, it logs one line and does nothing, so a
    # wrong URL looks exactly like a broken loader. The reason has to be said here.
    with pytest.raises(br.BackendUrlError, match=fragment):
        br.normalize_url(raw)


# --- the marker file ---------------------------------------------------------

def test_marker_is_ascii_without_a_byte_order_mark(game):
    br.write_marker(game, "http://example.org:8090")

    # A BOM would become part of the URL and break the loader's "http://" prefix check.
    assert (game / "mods" / ".rsmm_backend").read_bytes() == b"http://example.org:8090\n"


def test_marker_round_trips_and_clears(game):
    assert br.read_marker(game) is None
    br.write_marker(game, "http://example.org:8090")
    assert br.read_marker(game) == "http://example.org:8090"
    assert br.clear_marker(game) is True
    assert br.read_marker(game) is None
    assert br.clear_marker(game) is False


def test_marker_creates_the_mods_folder(tmp_path):
    br.write_marker(tmp_path, "http://example.org:8090")
    assert br.read_marker(tmp_path) == "http://example.org:8090"


def test_read_marker_uses_only_the_first_line(game):
    (game / "mods" / ".rsmm_backend").write_text("http://a:1\nhttp://b:2\n", encoding="ascii")
    assert br.read_marker(game) == "http://a:1"


def test_an_empty_marker_reads_as_unset(game):
    (game / "mods" / ".rsmm_backend").write_text("\n  \n", encoding="ascii")
    assert br.read_marker(game) is None


def test_apply_keeps_the_backend_setting(game):
    # `apply` empties <game>/mods/. Wiping the player's own setting there silently
    # sent the game back to the official servers.
    (game / "mods" / ".rsmm_backend").write_text("http://example.org:8090\n", encoding="ascii")
    (game / "mods" / "some-mod").mkdir()
    (game / "mods" / "some-mod" / "init.lua").write_text("-- mod", encoding="utf-8")

    assert clear_runtime_mods(game) == 1

    assert br.read_marker(game) == "http://example.org:8090"
    assert not (game / "mods" / "some-mod").exists()


# --- is the loader able to redirect at all -----------------------------------

def test_loader_that_can_redirect(game):
    state = br.inspect_loader(game)
    assert state.can_redirect


def test_no_dll_means_no_loader(tmp_path):
    state = br.inspect_loader(tmp_path)
    assert not state.can_redirect
    assert "install-loader" in state.summary


def test_stock_dll_is_recognised_by_its_size(game):
    (game / "winhttp.dll").write_bytes(b"\0" * br.STOCK_WINHTTP_SIZE)
    state = br.inspect_loader(game)
    assert not state.can_redirect
    assert "stock" in state.summary


def test_loader_older_than_the_redirect_is_reported_as_such(game):
    # The case that cost a tester an evening: a loader is installed, it just
    # predates the redirect, so the setting does nothing and the log never shows
    # a [backend] line.
    (game / "winhttp.dll").write_bytes(b"MZ" + b"\x01" * 4000)
    state = br.inspect_loader(game)
    assert not state.can_redirect
    assert "too old" in state.summary


# --- asking the server -------------------------------------------------------

class _Fed(BaseHTTPRequestHandler):
    body = b"{}"
    status = 200

    def do_GET(self):
        self.send_response(self.status)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


def _serve(body: bytes, status: int = 200):
    handler = type("H", (_Fed,), {"body": body, "status": status})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_probe_reads_the_advertised_endpoints():
    body = json.dumps({"current": {"endpoints": ["http://203.0.113.5:8090"]}}).encode()
    server, url = _serve(body)
    try:
        fed = br.probe_federation(url)
    finally:
        server.shutdown()
    assert fed.reachable
    assert fed.endpoints == ("http://203.0.113.5:8090",)


def test_probe_reports_a_server_error():
    server, url = _serve(b"{}", status=500)
    try:
        fed = br.probe_federation(url)
    finally:
        server.shutdown()
    assert not fed.reachable
    assert "500" in fed.error


def test_probe_reports_an_address_that_is_not_a_stormancer_backend():
    server, url = _serve(b"<html>not json</html>")
    try:
        fed = br.probe_federation(url)
    finally:
        server.shutdown()
    assert not fed.reachable
    assert "not like a Stormancer" in fed.error


def test_probe_reports_nothing_listening():
    server, url = _serve(b"{}")
    server.shutdown()
    server.server_close()
    fed = br.probe_federation(url, timeout=2)
    assert not fed.reachable
    assert fed.error


def test_a_remote_server_that_advertises_localhost_is_flagged():
    # publicIp / loadBalancedIp left at their default: HTTP works, then the game
    # dials localhost for the real connection and fails.
    fed = br.Federation(True, ("http://localhost:8090",))
    assert br.advertises_loopback("http://203.0.113.5:8090", fed)


def test_localhost_advertising_localhost_is_fine():
    fed = br.Federation(True, ("http://localhost:8090",))
    assert not br.advertises_loopback("http://127.0.0.1:8090", fed)


def test_a_properly_configured_server_is_not_flagged():
    fed = br.Federation(True, ("http://203.0.113.5:8090",))
    assert not br.advertises_loopback("http://203.0.113.5:8090", fed)


# --- the loader's own report -------------------------------------------------

def test_last_backend_log_skips_identity_noise_and_keeps_the_latest(game):
    (game / "mods" / "_log.txt").write_text("\n".join([
        "[t] loader build Oct 2",
        "[t] [backend] Passtech backend requests go to http://a:1",
        '[t] [backend] Steam web-ticket identity: "Ravenswatch"',
        "[t] [backend] redirected dt-live.passtechgames.com -> http://a:1",
        '[t] [backend] Steam web-ticket identity: "Ravenswatch"',
    ]), encoding="utf-8")

    log = br.last_backend_log(game)

    assert log.exists
    assert log.lines == (
        "[t] [backend] Passtech backend requests go to http://a:1",
        "[t] [backend] redirected dt-live.passtechgames.com -> http://a:1",
    )
    assert log.modified is not None


def test_last_backend_log_when_there_is_no_log(game):
    log = br.last_backend_log(game)
    assert not log.exists
    assert log.path == game / "mods" / "_log.txt"


# --- the command -------------------------------------------------------------

def run(game: Path, *args: str, capsys) -> tuple[int, str]:
    code = cmd_backend.main([*args, "--game-dir", str(game)])
    return code, capsys.readouterr().out


def test_setting_an_address_writes_it_and_reports(game, capsys):
    code, out = run(game, "85.214.117.164:8090/", "--no-check", capsys=capsys)

    assert code == 0
    assert br.read_marker(game) == "http://85.214.117.164:8090"
    assert "http://85.214.117.164:8090" in out
    assert "able to redirect" in out


def test_a_bad_address_changes_nothing_and_exits_2(game, capsys):
    code, out = run(game, "https://example.org:8090", "--no-check", capsys=capsys)

    assert code == 2
    assert br.read_marker(game) is None
    assert "plain http" in out


def test_off_removes_the_address(game, capsys):
    br.write_marker(game, "http://example.org:8090")

    code, out = run(game, "off", capsys=capsys)

    assert code == 0
    assert br.read_marker(game) is None
    assert "official servers" in out


def test_showing_the_state_changes_nothing(game, capsys):
    br.write_marker(game, "http://example.org:8090")

    code, out = run(game, "--no-check", capsys=capsys)

    assert code == 0
    assert br.read_marker(game) == "http://example.org:8090"
    assert "http://example.org:8090" in out


def test_an_old_loader_is_a_failure_even_though_the_file_was_written(game, capsys):
    (game / "winhttp.dll").write_bytes(b"MZ" + b"\x01" * 4000)

    code, out = run(game, "example.org:8090", "--no-check", capsys=capsys)

    assert code == 1
    assert "[FAIL] loader" in out
    assert "update-loader" in out
    assert br.read_marker(game) == "http://example.org:8090"


def test_an_environment_variable_that_wins_is_called_out(game, capsys, monkeypatch):
    monkeypatch.setenv(br.ENV_VAR, "http://old.example:8090")

    code, out = run(game, "example.org:8090", "--no-check", capsys=capsys)

    assert code == 0
    assert "takes priority" in out
    assert "reg delete" in out


def test_the_same_address_in_the_environment_is_not_a_warning(game, capsys, monkeypatch):
    monkeypatch.setenv(br.ENV_VAR, "http://example.org:8090/")

    _, out = run(game, "example.org:8090", "--no-check", capsys=capsys)

    assert "takes priority" not in out


def test_a_missing_game_folder_is_reported_not_created(tmp_path, capsys):
    ghost = tmp_path / "does-not-exist"

    code, out = run(ghost, "example.org:8090", capsys=capsys)

    assert code == 1
    assert "does not exist" in out
    assert not ghost.exists()


def test_the_game_folder_and_where_it_came_from_are_shown(game, capsys):
    _, out = run(game, "--no-check", capsys=capsys)
    assert f"game folder: {game}" in out
    assert "(--game-dir)" in out


def test_game_folder_origin_is_the_environment_variable_when_that_is_the_source(
        game, capsys, monkeypatch):
    # Two Steam libraries is enough for auto-detection to pick the other install, so the
    # origin is part of the output.
    monkeypatch.setenv("RSMM_GAME_DIR", str(game))

    code = cmd_backend.main(["--no-check"])
    out = capsys.readouterr().out

    assert code == 0
    assert "(RSMM_GAME_DIR)" in out


def test_a_server_that_advertises_localhost_fails_the_check(game, capsys, monkeypatch):
    # The server's publicIp / loadBalancedIp were left at their default: the HTTP leg works,
    # then the game dials localhost for the real connection. Seen from the player's side that
    # looks like their own network, so the command has to say it is the server.
    monkeypatch.setattr(
        br, "probe_federation",
        lambda url, timeout=5.0: br.Federation(True, ("http://localhost:8090",)))

    code, out = run(game, "203.0.113.9:8090", capsys=capsys)

    assert code == 1
    assert "[FAIL] server" in out
    assert "publicIp" in out


def test_an_unreachable_server_is_a_warning_not_a_failure(game, capsys, monkeypatch):
    # The address was written correctly; whether the server is up is not ours to fail on.
    monkeypatch.setattr(
        br, "probe_federation",
        lambda url, timeout=5.0: br.Federation(False, error="connection refused"))

    code, out = run(game, "203.0.113.9:8090", capsys=capsys)

    assert code == 0
    assert "[warn] server: not reachable (connection refused)" in out
