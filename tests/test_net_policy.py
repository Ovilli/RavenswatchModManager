"""Transport policy shared by every command that fetches mod data.

`rsmm install`, `rsmm update` and the desktop bridge all pull bytes off the
network. The rules about which URLs are acceptable and how much data to accept
live in one module so the three cannot drift; these pin them.
"""

from __future__ import annotations

import hashlib
import io

import pytest

from rsmm.engine import net

# --- scheme policy ---------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://example.test/m.zip",
    "https://example.test:8443/m.zip",
    "http://localhost:3001/api",
    "http://127.0.0.1:3001/api",
    "http://[::1]:3001/api",
])
def test_safe_urls_accepted(url):
    net.require_safe_url(url)


@pytest.mark.parametrize("url", [
    "http://example.test/m.zip",     # plaintext to a remote host
    "http://169.254.169.254/latest", # cloud metadata, the classic SSRF probe
    "ftp://example.test/m.zip",
    "gopher://example.test",
    "/not/a/url",
])
def test_unsafe_urls_rejected(url):
    with pytest.raises(net.UnsafeURL):
        net.require_safe_url(url)


def test_file_scheme_is_opt_in():
    """`install` supports offline archives; the registry client must not."""
    net.require_safe_url("file:///tmp/m.zip", allow_file=True)
    with pytest.raises(net.UnsafeURL):
        net.require_safe_url("file:///tmp/m.zip")


def test_http_to_a_host_that_merely_looks_local_is_rejected():
    """`localhost.evil.test` is a remote host with a reassuring name."""
    with pytest.raises(net.UnsafeURL):
        net.require_safe_url("http://localhost.evil.test/m.zip")


# --- byte ceilings ---------------------------------------------------------


def test_read_capped_returns_everything_under_the_limit():
    assert net.read_capped(io.BytesIO(b"abc"), "src", limit=10) == b"abc"


def test_read_capped_fails_rather_than_truncating():
    """Truncating would surface as a checksum mismatch — an attack disguised
    as a corrupt mirror."""
    with pytest.raises(net.TooLarge, match="exceeds"):
        net.read_capped(io.BytesIO(b"x" * 100), "src", limit=10)


def test_copy_capped_streams_and_hashes_in_one_pass(tmp_path):
    payload = b"y" * 5000
    h = hashlib.sha256()
    dest = tmp_path / "out.bin"
    with dest.open("wb") as fh:
        written = net.copy_capped(io.BytesIO(payload), fh, "src", hasher=h)
    assert written == len(payload)
    assert dest.read_bytes() == payload
    assert h.hexdigest() == hashlib.sha256(payload).hexdigest()


def test_copy_capped_stops_at_the_limit(tmp_path):
    dest = tmp_path / "out.bin"
    with dest.open("wb") as fh, pytest.raises(net.TooLarge):
        net.copy_capped(io.BytesIO(b"z" * 10_000), fh, "src", limit=1000, chunk=256)


# --- wiring ----------------------------------------------------------------


def test_index_base_rejects_a_plaintext_override(monkeypatch):
    """RSMM_INDEX_URL decides where archives come from, and the sha256 that
    would catch a tampered one is served over the same connection."""
    from rsmm.cli import json_bridge

    monkeypatch.setenv("RSMM_INDEX_URL", "http://evil.test")
    with pytest.raises(net.UnsafeURL):
        json_bridge._index_base()

    monkeypatch.setenv("RSMM_INDEX_URL", "http://localhost:3001")
    assert json_bridge._index_base() == "http://localhost:3001"


def test_api_url_escapes_caller_supplied_segments(monkeypatch):
    """Unescaped, a `?` or `..` in a slug re-points the request."""
    from rsmm.cli import json_bridge

    monkeypatch.setenv("RSMM_INDEX_URL", "https://api.test")
    url = json_bridge._api_url("api", "mods", "../../admin?x=1")
    assert url == "https://api.test/api/mods/..%2F..%2Fadmin%3Fx%3D1"


def test_install_and_update_share_the_policy():
    """Both commands must reject the same URLs the shared module does."""
    from rsmm.cli import cmd_install, update_cmd
    from rsmm.sdk.repo import RepoError

    with pytest.raises(RepoError, match="refusing to fetch"):
        cmd_install._check_url("http://evil.test/m.zip")
    with pytest.raises(RepoError, match="refusing to fetch"):
        update_cmd._fetch("http://evil.test/repo.json")
    # `install` allows file://; `update` never does.
    cmd_install._check_url("file:///tmp/m.zip")
    with pytest.raises(RepoError, match="refusing to fetch"):
        update_cmd._fetch("file:///tmp/repo.json")
