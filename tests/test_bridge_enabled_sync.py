"""`json apply --enabled-json`: the desktop profile decides what is installed.

The Library keeps enabled/disabled in its own store while `apply` reads each
mod's `manifest.toml`, so a mod switched off in the app was still installed
(bug report 2026-10-06). The bridge now makes the manifests match the profile's
list before applying.
"""

from __future__ import annotations

import json

from rsmm.cli import json_bridge as B


def _mod(root, name, enabled=True, aligned=False):
    d = root / name
    d.mkdir()
    flag = "true" if enabled else "false"
    key = "enabled     =" if aligned else "enabled ="
    (d / "manifest.toml").write_text(f'[mod]\nid = "{name}"\n{key} {flag}\n', encoding="utf-8")
    return d / "manifest.toml"


def _on(path) -> bool:
    import tomllib
    return tomllib.loads(path.read_text(encoding="utf-8"))["mod"]["enabled"]


def test_the_manifests_follow_the_profile(tmp_path):
    a = _mod(tmp_path, "a")                       # enabled on disk, off in the profile
    b = _mod(tmp_path, "b", enabled=False)        # disabled on disk, on in the profile
    c = _mod(tmp_path, "c", aligned=True)         # on in both, aligned like shipped manifests
    d = _mod(tmp_path, "d")                       # on disk, not in the profile at all
    changed = B.sync_enabled(tmp_path, ["b", "c", "gone"])
    assert (_on(a), _on(b), _on(c), _on(d)) == (False, True, True, False)
    assert sorted(changed) == ["a: off", "b: on", "d: off"]


def test_folders_that_are_not_mods_are_left_alone(tmp_path):
    (tmp_path / "_merged").mkdir()
    (tmp_path / "_merged" / "manifest.toml").write_text("[mod]\nenabled = true\n")
    (tmp_path / "notes").mkdir()
    assert B.sync_enabled(tmp_path, []) == []
    assert "enabled = true" in (tmp_path / "_merged" / "manifest.toml").read_text()


def test_a_bad_list_is_refused_before_anything_changes(tmp_path, monkeypatch, capsys):
    a = _mod(tmp_path, "a")
    monkeypatch.setattr(B, "MODS_DIR", tmp_path)
    called = []
    monkeypatch.setattr(B, "_collect_rsmm", lambda args: called.append(args) or {})
    for bad in ("not json", json.dumps({"a": 1}), json.dumps([1, 2])):
        assert B.cmd_apply([], bad) == 0              # emits {ok: false}; the bridge exits 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False and "enabled-json" in out["stderr"]
    assert _on(a) and not called


def test_apply_reports_what_it_matched(tmp_path, monkeypatch, capsys):
    _mod(tmp_path, "a")
    monkeypatch.setattr(B, "MODS_DIR", tmp_path)
    monkeypatch.setattr(B, "_collect_rsmm", lambda args: {
        "ok": True, "code": 0, "stdout": "applied\n", "stderr": "", "args": args})
    B.cmd_apply(["--force"], json.dumps([]))
    out = json.loads(capsys.readouterr().out)
    assert out["args"] == ["apply", "--force"]
    assert out["stdout"] == "Matched the profile: a: off\napplied\n"


def test_a_matching_manifest_is_left_byte_for_byte(tmp_path):
    from rsmm.cli.cmd_mods import set_mod_enabled
    m = _mod(tmp_path, "a")
    text = "[mod]\nenabled = true\n\n[[content]]\nkind = \"x\"\n"
    m.write_text(text, encoding="utf-8")
    assert set_mod_enabled(tmp_path, "a", True) == "unchanged"
    assert m.read_text(encoding="utf-8") == text
    assert set_mod_enabled(tmp_path, "a", False) == "ok"
    assert m.read_text(encoding="utf-8") == text.replace("enabled = true", "enabled = false")
