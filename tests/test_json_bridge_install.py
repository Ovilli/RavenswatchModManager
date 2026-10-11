"""Installing a mod from the registry through the desktop bridge.

The whole path runs against a fake index: the version lookup, the download,
the sha256 check and the unpack. What is pinned is what a user depends on: a
good archive installs, a tampered one is refused and leaves the working
install alone, and a failed download leaves nothing behind in the temp dir.
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import urllib.error
import zipfile

import pytest

from rsmm.cli import json_bridge


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


GOOD = _zip({"coolmod/manifest.toml": b'[mod]\nid = "coolmod"\n',
             "coolmod/init.lua": b"-- hi\n"})
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    mods = tmp_path / "mods"
    mods.mkdir()
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    monkeypatch.delenv("RSMM_INDEX_URL", raising=False)
    calls: list[str] = []
    routes: dict[str, object] = {}

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls.append(url)
        for suffix, body in routes.items():
            if url.endswith(suffix):
                if isinstance(body, Exception):
                    raise body
                return _Resp(body if isinstance(body, bytes) else json.dumps(body).encode())
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return {"mods": mods, "tmp": tmp, "calls": calls, "routes": routes}


def _out(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _index(env, versions):
    env["routes"]["/api/mods/coolmod"] = {"versions": versions}


def test_installs_the_latest_version(env, capsys):
    _index(env, [
        {"version": "1.0.0", "sha256": "0" * 64, "createdAt": "2026-01-01"},
        {"version": "1.1.0", "sha256": GOOD_SHA.upper(), "createdAt": "2026-02-01"},
    ])
    env["routes"]["/api/mods/coolmod/1.1.0/download"] = GOOD
    json_bridge.cmd_install_mod("coolmod")
    out = _out(capsys)
    assert out["ok"] is True and out["version"] == "1.1.0"
    assert out["sha256"] == GOOD_SHA and out["sizeBytes"] == len(GOOD)
    # The single wrapping folder is stripped: files land in mods/coolmod/.
    assert (env["mods"] / "coolmod" / "manifest.toml").is_file()
    assert (env["mods"] / "coolmod" / "init.lua").is_file()
    assert list(env["tmp"].iterdir()) == []                 # download cleaned up


def test_installs_a_pinned_version(env, capsys):
    _index(env, [{"version": "2.0.0", "sha256": GOOD_SHA, "createdAt": "2026-03-01"},
                 {"version": "1.0.0", "sha256": GOOD_SHA, "createdAt": "2026-01-01"}])
    env["routes"]["/api/mods/coolmod/1.0.0/download"] = GOOD
    json_bridge.cmd_install_mod_version("coolmod", "1.0.0")
    assert _out(capsys)["version"] == "1.0.0"
    assert any(c.endswith("/1.0.0/download") for c in env["calls"])


def test_a_tampered_archive_is_refused_and_the_install_is_kept(env, capsys):
    old = env["mods"] / "coolmod"
    old.mkdir()
    (old / "manifest.toml").write_text("old install")
    _index(env, [{"version": "1.0.0", "sha256": GOOD_SHA, "createdAt": "2026-01-01"}])
    env["routes"]["/api/mods/coolmod/1.0.0/download"] = GOOD + b"tampered"
    json_bridge.cmd_install_mod("coolmod")
    out = _out(capsys)
    assert out["ok"] is False and "sha256 mismatch" in out["error"]
    assert (old / "manifest.toml").read_text() == "old install"
    # The rejected archive must not stay behind in the temp dir.
    assert list(env["tmp"].iterdir()) == []


def test_a_failed_download_leaves_nothing_behind(env, capsys):
    _index(env, [{"version": "1.0.0", "sha256": GOOD_SHA, "createdAt": "2026-01-01"}])
    env["routes"]["/api/mods/coolmod/1.0.0/download"] = urllib.error.HTTPError(
        "u", 503, "Service Unavailable", {}, None)
    json_bridge.cmd_install_mod("coolmod")
    out = _out(capsys)
    assert out["ok"] is False and "HTTP 503" in out["error"]
    assert list(env["tmp"].iterdir()) == []


@pytest.mark.parametrize("versions, message", [
    ([], "no published versions"),
    ([{"version": "1.0.0", "sha256": "abc", "createdAt": "x"}], "missing version/sha256"),
    ([{"version": "", "sha256": GOOD_SHA, "createdAt": "x"}], "missing version/sha256"),
])
def test_a_bad_index_row_is_reported(env, capsys, versions, message):
    _index(env, versions)
    json_bridge.cmd_install_mod("coolmod")
    out = _out(capsys)
    assert out["ok"] is False and message in out["error"]
    assert not any("/download" in c for c in env["calls"])     # nothing downloaded


def test_an_unknown_mod_is_not_found(env, capsys):
    json_bridge.cmd_install_mod("coolmod")
    out = _out(capsys)
    assert out["ok"] is False and "not found in the index" in out["error"]


def test_an_unknown_pinned_version_is_reported(env, capsys):
    _index(env, [{"version": "1.0.0", "sha256": GOOD_SHA, "createdAt": "x"}])
    json_bridge.cmd_install_mod_version("coolmod", "9.9.9")
    out = _out(capsys)
    assert out["ok"] is False and "no published version '9.9.9'" in out["error"]


@pytest.mark.parametrize("slug", ["../escape", "a/b", ".."])
def test_a_slug_that_leaves_mods_is_refused_before_any_network(env, capsys, slug):
    json_bridge.cmd_install_mod(slug)
    assert _out(capsys)["ok"] is False
    assert env["calls"] == []


def test_an_archive_without_a_manifest_is_refused(env, capsys):
    bad = _zip({"coolmod/init.lua": b"-- no manifest\n"})
    _index(env, [{"version": "1.0.0", "sha256": hashlib.sha256(bad).hexdigest(),
                  "createdAt": "x"}])
    env["routes"]["/api/mods/coolmod/1.0.0/download"] = bad
    json_bridge.cmd_install_mod("coolmod")
    out = _out(capsys)
    assert out["ok"] is False and "manifest.toml" in out["error"]
    assert not (env["mods"] / "coolmod").exists()
    assert list(env["tmp"].iterdir()) == []


def test_a_plain_http_index_override_is_refused(env, capsys, monkeypatch):
    monkeypatch.setenv("RSMM_INDEX_URL", "http://evil.example.com")
    json_bridge.cmd_install_mod("coolmod")
    assert _out(capsys)["ok"] is False
    assert env["calls"] == []
