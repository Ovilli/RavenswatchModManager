"""Unit tests for `rsmm enable` / `rsmm disable`."""

from __future__ import annotations

import pytest

from rsmm.cli import cmd_mods as CM


@pytest.fixture()
def mods_dir(tmp_path):
    d = tmp_path / "mods"
    d.mkdir()
    return d


def _write_manifest(mods_dir, mod_id, enabled=True):
    root = mods_dir / mod_id
    root.mkdir()
    lines = [
        "[mod]",
        f'id = "{mod_id}"',
        'name = "T"',
        'version = "0.1.0"',
        f"enabled = {'true' if enabled else 'false'}",
    ]
    (root / "manifest.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _enabled(mods_dir, mod_id) -> bool:
    text = (mods_dir / mod_id / "manifest.toml").read_text(encoding="utf-8")
    return "enabled = true" in text


def _run(verb, *args):
    return CM.main([verb, *args])


def test_disable_single(mods_dir):
    _write_manifest(mods_dir, "A", enabled=True)
    rc = _run("disable", "A", "--no-apply", "--mods-dir", str(mods_dir))
    assert rc == 0
    assert not _enabled(mods_dir, "A")


def test_enable_single(mods_dir):
    _write_manifest(mods_dir, "A", enabled=False)
    rc = _run("enable", "A", "--no-apply", "--mods-dir", str(mods_dir))
    assert rc == 0
    assert _enabled(mods_dir, "A")


def test_enable_only_disables_the_rest(mods_dir):
    _write_manifest(mods_dir, "Keep", enabled=False)
    _write_manifest(mods_dir, "Off1", enabled=True)
    _write_manifest(mods_dir, "Off2", enabled=True)
    rc = _run("enable", "Keep", "--only", "--no-apply", "--mods-dir", str(mods_dir))
    assert rc == 0
    assert _enabled(mods_dir, "Keep")
    assert not _enabled(mods_dir, "Off1")
    assert not _enabled(mods_dir, "Off2")


def test_disable_all(mods_dir):
    _write_manifest(mods_dir, "A", enabled=True)
    _write_manifest(mods_dir, "B", enabled=True)
    rc = _run("disable", "--all", "--no-apply", "--mods-dir", str(mods_dir))
    assert rc == 0
    assert not _enabled(mods_dir, "A")
    assert not _enabled(mods_dir, "B")


def test_unknown_id_rejected_before_any_change(mods_dir):
    _write_manifest(mods_dir, "A", enabled=True)
    rc = _run("disable", "A", "Nope", "--no-apply", "--mods-dir", str(mods_dir))
    assert rc == 2
    assert _enabled(mods_dir, "A")  # nothing flipped


def test_all_with_ids_is_an_error(mods_dir):
    _write_manifest(mods_dir, "A")
    with pytest.raises(SystemExit):
        _run("enable", "A", "--all", "--no-apply", "--mods-dir", str(mods_dir))
