"""Guarantees of the shared archive extractor (`rsmm.sdk.archive`).

These cover the class of bug that motivated consolidating three divergent
copies of the extraction logic: an archive is attacker-controlled input, and
the mod id inside it used to reach `shutil.rmtree` unvalidated.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from rsmm.cli import cmd_install, json_bridge, update_cmd
from rsmm.sdk import archive
from rsmm.sdk.archive import ArchiveError
from rsmm.sdk.repo import RepoError


def _zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


# --- name validation -------------------------------------------------------


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b", "/abs", "C:x", "con", "NUL.txt"])
def test_safe_dir_name_rejects(bad):
    with pytest.raises(ArchiveError):
        archive.safe_dir_name(bad)


@pytest.mark.parametrize("ok", ["MyMod", "my-mod", "my_mod.v2", "Mod123"])
def test_safe_dir_name_accepts(ok):
    assert archive.safe_dir_name(ok) == ok


# --- extraction guards -----------------------------------------------------


def test_safe_extract_rejects_traversal(tmp_path):
    z = _zip(tmp_path / "a.zip", {"../escape.txt": b"x"})
    with zipfile.ZipFile(z) as zf, pytest.raises(ArchiveError, match="traversal"):
        archive.safe_extract(zf, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_rejects_absolute(tmp_path):
    z = _zip(tmp_path / "a.zip", {"/etc/evil": b"x"})
    with zipfile.ZipFile(z) as zf:
        # Some zip writers normalise the leading slash away; either the
        # absolute-path guard fires or the member lands harmlessly inside out/.
        try:
            archive.safe_extract(zf, tmp_path / "out")
        except ArchiveError:
            return
    assert (tmp_path / "out" / "etc" / "evil").is_file()


def test_safe_extract_strips_prefix(tmp_path):
    z = _zip(tmp_path / "a.zip", {"MyMod/manifest.toml": b"x", "MyMod/a/b.bin": b"D"})
    out = tmp_path / "out"
    with zipfile.ZipFile(z) as zf:
        archive.safe_extract(zf, out, strip_prefix="MyMod/")
    assert (out / "manifest.toml").is_file()
    assert (out / "a" / "b.bin").read_bytes() == b"D"


def test_safe_extract_writes_symlink_entry_as_regular_file(tmp_path):
    """A symlink member must never become a real symlink.

    Otherwise a later member writing through it escapes the destination.
    """
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.create_system = 3                      # Unix
        info.external_attr = (0o120777 << 16)       # S_IFLNK
        zf.writestr(info, "/etc/passwd")
    out = tmp_path / "out"
    with zipfile.ZipFile(z) as zf:
        archive.safe_extract(zf, out)
    link = out / "link"
    assert not link.is_symlink()
    assert link.read_bytes() == b"/etc/passwd"


def test_check_limits_rejects_too_many_entries(tmp_path):
    z = _zip(tmp_path / "a.zip", {f"f{i}": b"" for i in range(20)})
    with zipfile.ZipFile(z) as zf, pytest.raises(ArchiveError, match="too many entries"):
        archive.check_limits(zf, "m", max_entries=5)


def test_check_limits_rejects_oversize(tmp_path):
    z = _zip(tmp_path / "a.zip", {"big": b"A" * 5000})
    with zipfile.ZipFile(z) as zf, pytest.raises(ArchiveError, match="exceeds"):
        archive.check_limits(zf, "m", max_total_bytes=1000)


def test_check_limits_rejects_bomb_ratio(tmp_path):
    # Highly compressible payload: ~1 MiB of zeros packs to a few hundred bytes.
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb", b"\0" * (1 << 20))
    with zipfile.ZipFile(z) as zf, pytest.raises(ArchiveError, match="ratio"):
        archive.check_limits(zf, "m", max_ratio=10)


def test_single_top_dir_none_for_flat_archive(tmp_path):
    z = _zip(tmp_path / "a.zip", {"manifest.toml": b"", "a.bin": b""})
    with zipfile.ZipFile(z) as zf:
        assert archive.single_top_dir(zf) is None


def test_scan_dangerous_blocks_executables(tmp_path):
    z = _zip(tmp_path / "a.zip", {"M/manifest.toml": b"", "M/pwn.dll": b"MZ"})
    with zipfile.ZipFile(z) as zf, pytest.raises(ArchiveError, match="blocked file type"):
        archive.scan_dangerous(zf, "M")


def test_scan_dangerous_reports_every_root_overlay(tmp_path):
    """`_root/` members overwrite the game install itself — always warn.

    Regression: the warning was filtered to a "dangerous root extensions" set
    whose every member was also hard-blocked and raised first, so it could
    never fire — and implied `_root/` binaries were merely warned about.
    """
    z = _zip(tmp_path / "a.zip", {
        "M/manifest.toml": b"",
        "M/assets/normal.bin": b"x",                       # not an overlay
        "M/_root/DarkTalesResources/ApplicationSettings.ot": b"x",
    })
    with zipfile.ZipFile(z) as zf:
        assert archive.scan_dangerous(zf, "M") == [
            "DarkTalesResources/ApplicationSettings.ot"
        ]


def test_root_overlay_gets_no_executable_exemption(tmp_path):
    """A downloaded mod may not ship a binary, least of all into the game root."""
    z = _zip(tmp_path / "a.zip", {"M/manifest.toml": b"", "M/_root/winhttp.dll": b"MZ"})
    with zipfile.ZipFile(z) as zf, pytest.raises(ArchiveError, match="blocked file type"):
        archive.scan_dangerous(zf, "M")


# --- rsmm install ----------------------------------------------------------


def test_install_rejects_traversal_mod_id(tmp_path):
    """Regression: `--force` used to rmtree `mods/<top>` where <top> came
    straight from the archive, so an all-`../` zip deleted `mods/`'s parent."""
    z = _zip(tmp_path / "a.zip", {"../evil/x.txt": b"x"})
    with pytest.raises(ArchiveError):
        cmd_install._peek_mod_id(z.read_bytes())


def test_install_rejects_flat_archive(tmp_path):
    z = _zip(tmp_path / "a.zip", {"readme.txt": b"x"})
    with pytest.raises(ArchiveError, match="exactly one top-level"):
        cmd_install._peek_mod_id(z.read_bytes())


def test_install_blocks_dangerous_extension(tmp_path, monkeypatch):
    z = _zip(tmp_path / "a.zip", {"M/manifest.toml": b"", "M/pwn.exe": b"MZ"})
    mods = tmp_path / "mods"
    monkeypatch.setattr(cmd_install, "MODS_DIR", mods)
    with pytest.raises(ArchiveError, match="blocked file type"):
        cmd_install._safe_extract(z.read_bytes(), mods)
    assert not (mods / "M").exists()


def test_install_leaves_no_partial_dir_on_failure(tmp_path):
    """A rejected member must not leave a half-written mod behind."""
    z = _zip(tmp_path / "a.zip", {"M/manifest.toml": b"x", "M/hook.ps1": b"x"})
    mods = tmp_path / "mods"
    with pytest.raises(ArchiveError):
        cmd_install._safe_extract(z.read_bytes(), mods)
    assert not mods.exists() or not any(mods.iterdir())


def test_install_extracts_into_named_dir(tmp_path):
    z = _zip(tmp_path / "a.zip", {"M/manifest.toml": b"id", "M/a/b.bin": b"D"})
    mods = tmp_path / "mods"
    assert cmd_install._safe_extract(z.read_bytes(), mods) == "M"
    assert (mods / "M" / "manifest.toml").read_bytes() == b"id"
    assert (mods / "M" / "a" / "b.bin").read_bytes() == b"D"
    # Staging dir cleaned up.
    assert [p.name for p in mods.iterdir()] == ["M"]


@pytest.mark.parametrize("url", ["http://evil.test/m.zip", "ftp://x/m.zip", "gopher://x"])
def test_install_refuses_insecure_url(url):
    with pytest.raises(RepoError, match="refusing to fetch"):
        cmd_install._check_url(url)


@pytest.mark.parametrize("url", [
    "https://example.test/m.zip",
    "file:///tmp/m.zip",
    "http://localhost:8000/m.zip",
    "http://127.0.0.1:8000/m.zip",
])
def test_install_allows_safe_url(url):
    cmd_install._check_url(url)  # must not raise


# --- rsmm update -----------------------------------------------------------


def test_update_install_zip_handles_flat_archive(tmp_path, monkeypatch):
    """Regression: a flat zip used to replace the installed mod with an empty
    directory, because the `staging.exists()` fallback could never fire."""
    mods = tmp_path / "mods"
    (mods / "M").mkdir(parents=True)
    (mods / "M" / "old.txt").write_text("old")
    monkeypatch.setattr(update_cmd, "MODS_DIR", mods)
    z = _zip(tmp_path / "a.zip", {"manifest.toml": b"new", "a.bin": b"D"})
    update_cmd._install_zip(z, "M", dry_run=False)
    assert (mods / "M" / "manifest.toml").read_bytes() == b"new"
    assert not (mods / "M" / "old.txt").exists()


def test_update_install_zip_handles_wrapped_archive(tmp_path, monkeypatch):
    mods = tmp_path / "mods"
    mods.mkdir()
    monkeypatch.setattr(update_cmd, "MODS_DIR", mods)
    z = _zip(tmp_path / "a.zip", {"M/manifest.toml": b"new"})
    update_cmd._install_zip(z, "M", dry_run=False)
    assert (mods / "M" / "manifest.toml").read_bytes() == b"new"


def test_update_install_zip_rejects_unsafe_mod_id(tmp_path, monkeypatch):
    monkeypatch.setattr(update_cmd, "MODS_DIR", tmp_path / "mods")
    z = _zip(tmp_path / "a.zip", {"manifest.toml": b"x"})
    with pytest.raises(ArchiveError):
        update_cmd._install_zip(z, "..", dry_run=False)


# --- desktop bridge --------------------------------------------------------


def test_bridge_keeps_existing_install_when_zip_is_bad(tmp_path):
    """Regression: the target was deleted before extraction, so a hostile or
    corrupt download destroyed a working mod as a side effect of failing."""
    target = tmp_path / "mods" / "M"
    target.mkdir(parents=True)
    (target / "manifest.toml").write_text("keep me")
    z = _zip(tmp_path / "a.zip", {"manifest.toml": b"", "pwn.exe": b"MZ"})
    res = json_bridge._extract_downloaded_zip(z, target, "M")
    assert res and res["ok"] is False
    assert (target / "manifest.toml").read_text() == "keep me"


def test_bridge_rejects_unsafe_slug():
    with pytest.raises(ArchiveError):
        json_bridge._mod_target("../evil")


# --- rsmm pack (producer side of the same policy) --------------------------

def _packable(mods: Path, mod_id: str, extra: dict[str, bytes] | None = None) -> Path:
    d = mods / mod_id
    (d / "assets").mkdir(parents=True)
    (d / "manifest.toml").write_text(f'[mod]\nid = "{mod_id}"\n', encoding="utf-8")
    (d / "assets" / "a.bin").write_bytes(b"my own bytes")
    for rel, data in (extra or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return d


def _run_pack(tmp_path, monkeypatch, mod_id: str) -> int:
    from rsmm.cli import cmd_pack

    monkeypatch.setattr(cmd_pack, "MODS_DIR", tmp_path / "mods")
    monkeypatch.setattr(cmd_pack, "DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr(cmd_pack, "_vanilla_offenders", lambda _d: [])
    return cmd_pack.main([mod_id])


def test_pack_refuses_what_install_would_reject(tmp_path, monkeypatch, capsys):
    """Producer and consumer share one policy.

    Otherwise an author packs and publishes a mod that every user's
    `rsmm install` refuses, and only finds out from bug reports.
    """
    _packable(tmp_path / "mods", "PackMe", {"hook.ps1": b"evil"})
    assert _run_pack(tmp_path, monkeypatch, "PackMe") == 1
    assert "blocked file type" in capsys.readouterr().err
    assert not (tmp_path / "dist" / "PackMe.zip").exists()   # no artifact


def test_pack_warns_about_root_overlays_but_still_packs(tmp_path, monkeypatch, capsys):
    _packable(tmp_path / "mods", "Overlay",
              {"_root/DarkTalesResources/Settings.ot": b"x"})
    assert _run_pack(tmp_path, monkeypatch, "Overlay") == 0
    assert "overwrites game install root file" in capsys.readouterr().err
    assert (tmp_path / "dist" / "Overlay.zip").is_file()


def test_packed_archive_installs_cleanly(tmp_path, monkeypatch):
    """The round trip the two halves exist to guarantee."""
    _packable(tmp_path / "mods", "RoundTrip")
    assert _run_pack(tmp_path, monkeypatch, "RoundTrip") == 0
    data = (tmp_path / "dist" / "RoundTrip.zip").read_bytes()

    assert cmd_install._peek_mod_id(data) == "RoundTrip"
    dest = tmp_path / "installed"
    assert cmd_install._safe_extract(data, dest) == "RoundTrip"
    assert (dest / "RoundTrip" / "assets" / "a.bin").read_bytes() == b"my own bytes"


# --- rsmm pack: the enabled flag is the AUTHOR's state, not the mod's ------
#
# A mod packed while switched off installs, applies, and then does nothing:
# `_sync_mod_manifests` copies the manifest and DELETES init.lua for a
# disabled mod, so the loader logs `scan_mods found=1` with no init line.
# That is indistinguishable from a broken mod from inside the game, and it
# cost three restarts to diagnose on damage-meter 1.2.2 (2026-08-24).

def _pack_manifest(tmp_path, monkeypatch, mod_id: str, manifest: str) -> str:
    d = tmp_path / "mods" / mod_id
    (d / "assets").mkdir(parents=True)
    (d / "manifest.toml").write_text(manifest, encoding="utf-8")
    (d / "assets" / "a.bin").write_bytes(b"my own bytes")
    assert _run_pack(tmp_path, monkeypatch, mod_id) == 0
    with zipfile.ZipFile(tmp_path / "dist" / f"{mod_id}.zip") as zf:
        return zf.read(f"{mod_id}/manifest.toml").decode("utf-8")


def test_pack_stamps_a_disabled_mod_as_enabled(tmp_path, monkeypatch, capsys):
    packed = _pack_manifest(
        tmp_path, monkeypatch, "Offish",
        '[mod]\nid = "Offish"\nenabled     = false\nload_order  = 60\n')
    # Alignment is preserved: the manifest is a file authors read and edit.
    assert "enabled     = true" in packed
    assert "false" not in packed
    assert "packed as enabled" in capsys.readouterr().out


def test_pack_leaves_other_tables_alone(tmp_path, monkeypatch):
    """`enabled` is a plausible key in a mod's own config or overlay block,
    and rewriting one of those changes what the mod DOES."""
    packed = _pack_manifest(
        tmp_path, monkeypatch, "Tables",
        '[mod]\nid = "Tables"\nenabled = false\n\n[overlay]\nenabled = false\n')
    mod, _, overlay = packed.partition("[overlay]")
    assert "enabled = true" in mod
    assert "enabled = false" in overlay


def test_pack_does_not_rewrite_an_already_enabled_manifest(tmp_path, monkeypatch, capsys):
    src = '[mod]\nid = "OnAlready"\nenabled = true\n'
    assert _pack_manifest(tmp_path, monkeypatch, "OnAlready", src) == src
    assert "packed as enabled" not in capsys.readouterr().out
