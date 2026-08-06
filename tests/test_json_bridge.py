"""Characterization tests for the desktop/web JSON bridge.

These pin the JSON contract the desktop app depends on (so the planned
split into cli/json_* modules cannot change behaviour) and lock the two
security guards: the upload SSRF allowlist and the download zip extractor
(zip-slip + dangerous-extension blocking).
"""

import json
import zipfile
from pathlib import Path

import pytest

from rsmm.cli import json_bridge


def _emit_json(capsys):
    """Parse the single JSON blob cmd_* writes to stdout via _emit."""
    return json.loads(capsys.readouterr().out)


# --- _slugify --------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("My Cool Mod", "my-cool-mod"),
    ("  Trailing--Dashes  ", "trailing-dashes"),
    ("UPPER_under", "upper_under"),
    ("--leading", "leading"),
    ("!!!", ""),
    ("a.b.c", "a-b-c"),
])
def test_slugify(raw, want):
    assert json_bridge._slugify(raw) == want


# --- _upload_url_allowed (SSRF allowlist) ----------------------------------

@pytest.mark.parametrize("url", [
    "https://s3-rsmm.me/bucket/key",
    "https://ravenswatch-mods.s3.amazonaws.com/x",
])
def test_upload_url_allowed_known_hosts(url):
    assert json_bridge._upload_url_allowed(url) is True


@pytest.mark.parametrize("url", [
    "https://evil.example.com/x",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata SSRF
    "https://s3-rsmm.me.evil.com/x",  # suffix trick
    "not a url",
    "",
])
def test_upload_url_allowed_rejects(url):
    assert json_bridge._upload_url_allowed(url) is False


def test_upload_url_allowlist_extra_is_module_load_only(monkeypatch):
    # Mutating the env after import must NOT widen the allowlist (the guard
    # snapshots RSMM_UPLOAD_HOST_ALLOW at load to defeat mid-process injection).
    monkeypatch.setenv("RSMM_UPLOAD_HOST_ALLOW", "attacker.test")
    assert json_bridge._upload_url_allowed("https://attacker.test/x") is False


# --- _extract_downloaded_zip (zip-slip + dangerous ext) --------------------

def _make_zip(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    z = tmp_path / "mod.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return z


def test_extract_blocks_dangerous_extension(tmp_path):
    z = _make_zip(tmp_path, {"manifest.toml": b"", "payload.exe": b"MZ"})
    res = json_bridge._extract_downloaded_zip(z, tmp_path / "out", "evilmod")
    assert res and res["ok"] is False and "blocked file type" in res["error"]


def test_extract_refuses_zip_slip(tmp_path):
    z = _make_zip(tmp_path, {"manifest.toml": b"", "../escape.txt": b"x"})
    res = json_bridge._extract_downloaded_zip(z, tmp_path / "out", "slip")
    assert res and res["ok"] is False
    assert "traversal" in res["error"] or "escapes target" in res["error"]


def test_extract_requires_manifest(tmp_path):
    z = _make_zip(tmp_path, {"readme.txt": b"hi"})
    res = json_bridge._extract_downloaded_zip(z, tmp_path / "out", "nomani")
    assert res and res["ok"] is False and "manifest.toml" in res["error"]


def test_extract_happy_path_strips_single_top_dir(tmp_path):
    # A single wrapping top dir is stripped; files land directly under target.
    z = _make_zip(tmp_path, {
        "MyMod/manifest.toml": b"[mod]\nname='x'\n",
        "MyMod/assets/a.bin": b"DATA",
    })
    out = tmp_path / "out"
    res = json_bridge._extract_downloaded_zip(z, out, "mymod")
    assert res is None  # success
    assert (out / "manifest.toml").is_file()
    assert (out / "assets" / "a.bin").read_bytes() == b"DATA"


# --- cmd_list / _read_manifest (JSON contract) -----------------------------

def _write_mod(mods: Path, mod_id: str, body: str, assets: dict[str, bytes] | None = None):
    d = mods / mod_id
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text(body, encoding="utf-8")
    for rel, data in (assets or {}).items():
        f = d / "assets" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)


def test_cmd_list_shape(tmp_path, monkeypatch, capsys):
    mods = tmp_path / "mods"
    _write_mod(
        mods, "CoolMod",
        '[mod]\nname = "Cool"\nversion = "1.2.3"\nauthor = "me"\nenabled = true\n',
        assets={"foo/bar.bin": b"x"},
    )
    _write_mod(mods, "_skipme", '[mod]\nname = "hidden"\n')  # underscore -> skipped
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)

    assert json_bridge.cmd_list() == 0
    items = _emit_json(capsys)
    assert [i["id"] for i in items] == ["CoolMod"]
    it = items[0]
    assert it["slug"] == "CoolMod" and it["version"] == "1.2.3"
    assert it["enabled"] is True
    assert it["writes"] == ["foo/bar.bin"]


def test_cmd_list_empty_when_no_mods_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(json_bridge, "MODS_DIR", tmp_path / "nope")
    assert json_bridge.cmd_list() == 0
    assert _emit_json(capsys) == []


def test_cmd_list_fails_loudly_when_the_folder_cannot_be_read(tmp_path, monkeypatch):
    """An unreadable mods folder must NOT look like "no mods installed".

    Regression: both cases emitted `[]`, so the desktop app recorded "nothing
    is installed" from a transient permission error, then refused to install
    mods it believed were already there.
    """
    mods = tmp_path / "mods"
    mods.mkdir()
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)

    def boom(*_a, **_k):
        raise PermissionError("nope")

    monkeypatch.setattr(json_bridge.Path, "iterdir", boom)
    assert json_bridge.cmd_list() == 1


# --- cmd_uninstall_mod (path-traversal guard) ------------------------------

def test_uninstall_rejects_traversal(tmp_path, monkeypatch, capsys):
    mods = tmp_path / "mods"
    mods.mkdir()
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)
    json_bridge.cmd_uninstall_mod("../secrets")
    res = _emit_json(capsys)
    assert res["ok"] is False and "invalid mod id" in res["error"]


def test_uninstall_removes_existing(tmp_path, monkeypatch, capsys):
    mods = tmp_path / "mods"
    _write_mod(mods, "Doomed", '[mod]\nname = "d"\n')
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)
    json_bridge.cmd_uninstall_mod("Doomed")
    res = _emit_json(capsys)
    assert res["ok"] is True and res["removed"] is True
    assert not (mods / "Doomed").exists()
