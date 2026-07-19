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


# --- interactive picker ----------------------------------------------------


def test_states_parses_the_aligned_manifest_form(mods_dir):
    """Manifests ship the value aligned; a naive substring check reads them
    all as disabled, which silently made the home screen report 0 enabled."""
    (mods_dir / "Aligned").mkdir()
    (mods_dir / "Aligned" / "manifest.toml").write_text(
        "[mod]\nenabled     = true\n", encoding="utf-8")
    _write_manifest(mods_dir, "Off", enabled=False)

    st = CM._states(mods_dir)
    assert st == {"Aligned": True, "Off": False}


def test_states_survives_an_unreadable_manifest(mods_dir):
    """_states runs on every menu redraw; one bad manifest must render as a
    disabled row, not take the whole screen down."""
    _write_manifest(mods_dir, "A", enabled=True)
    # Explicit id list, so a mod whose manifest vanished between the listing
    # and the read (or was never a readable file) still gets an entry.
    assert CM._states(mods_dir, ["A", "Gone"]) == {"A": True, "Gone": False}


def test_states_honours_an_explicit_id_list(mods_dir):
    _write_manifest(mods_dir, "A")
    _write_manifest(mods_dir, "B")
    assert CM._states(mods_dir, ["A"]) == {"A": True}


def test_resolve_ids_prefers_explicit_ids_over_the_picker(mods_dir, monkeypatch):
    monkeypatch.setattr(CM, "_pick", lambda *a: pytest.fail("picker used"))
    args = type("A", (), {"all": False, "ids": ["B", "A", "B"]})()
    # Duplicates collapse, order preserved.
    assert CM._resolve_ids(args, None, mods_dir, ["A", "B"], "enable") == ["B", "A"]


def test_resolve_ids_expands_all(mods_dir, monkeypatch):
    monkeypatch.setattr(CM, "_pick", lambda *a: pytest.fail("picker used"))
    args = type("A", (), {"all": True, "ids": []})()
    assert CM._resolve_ids(args, None, mods_dir, ["A", "B"], "enable") == ["A", "B"]


def test_resolve_ids_errors_when_not_a_tty(mods_dir, monkeypatch):
    """Scripted use must keep failing loudly instead of blocking on a menu."""
    monkeypatch.setattr(CM.sys.stdin, "isatty", lambda: False, raising=False)
    calls = []
    ap = type("AP", (), {"error": lambda self, m: calls.append(m)})()
    args = type("A", (), {"all": False, "ids": []})()
    CM._resolve_ids(args, ap, mods_dir, ["A"], "enable")
    assert calls and "at least one mod id" in calls[0]


def test_resolve_ids_opens_the_picker_on_a_tty(mods_dir, monkeypatch):
    monkeypatch.setattr(CM.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(CM.sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(CM, "_pick", lambda md, ids, verb: ["A"])
    args = type("A", (), {"all": False, "ids": []})()
    assert CM._resolve_ids(args, None, mods_dir, ["A", "B"], "enable") == ["A"]


def test_pick_falls_back_to_a_numeric_prompt_without_raw_mode(mods_dir, monkeypatch):
    _write_manifest(mods_dir, "A")
    _write_manifest(mods_dir, "B")
    monkeypatch.setattr(CM._keys, "available", lambda *a, **k: False)
    monkeypatch.setattr("builtins.input", lambda *a: "2")
    assert CM._pick(mods_dir, ["A", "B"], "enable") == ["B"]


def test_pick_prompt_accepts_all_and_cancels_on_blank(mods_dir, monkeypatch):
    monkeypatch.setattr(CM._keys, "available", lambda *a, **k: False)
    monkeypatch.setattr("builtins.input", lambda *a: "all")
    assert CM._pick(mods_dir, ["A", "B"], "enable") == ["A", "B"]
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert CM._pick(mods_dir, ["A", "B"], "enable") is None


def test_pick_prompt_rejects_out_of_range(mods_dir, monkeypatch):
    monkeypatch.setattr(CM._keys, "available", lambda *a, **k: False)
    monkeypatch.setattr("builtins.input", lambda *a: "3")
    assert CM._pick(mods_dir, ["A", "B"], "enable") is None


def test_cancelling_the_picker_changes_nothing(mods_dir, monkeypatch):
    _write_manifest(mods_dir, "A", enabled=True)
    monkeypatch.setattr(CM.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(CM.sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(CM, "_pick", lambda *a: None)
    rc = _run("disable", "--no-apply", "--mods-dir", str(mods_dir))
    assert rc == 1
    assert _enabled(mods_dir, "A")
