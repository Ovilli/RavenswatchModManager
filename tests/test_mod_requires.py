"""`[requires]` in a manifest: parse, refuse on an older CLI / loader, and name the
CLI version in a content emit failure."""

from __future__ import annotations

import pytest

from rsmm.cli import apply_mods as A
from rsmm.engine import mod_requires as R


def _write(tmp_path, body: str, name="m"):
    root = tmp_path / name
    root.mkdir()
    (root / "manifest.toml").write_text(
        f'[mod]\nid = "{name}"\n{body}', encoding="utf-8")
    return root


@pytest.fixture
def versions(monkeypatch):
    monkeypatch.setattr(R, "running_cli_version", lambda: 30)
    monkeypatch.setattr(R, "loader_install",
                        lambda _g: {"state": "release", "version": 57})


def test_parse_accepts_both_keys_and_absence():
    assert R.parse_requires(None) == {}
    assert R.parse_requires({"cli": 31, "loader": 58}) == {"cli": 31, "loader": 58}
    assert R.parse_requires({"loader": 2}) == {"loader": 2}


@pytest.mark.parametrize("bad, text", [
    ({"clu": 3}, "unknown key"),
    ({"cli": "31"}, "positive integer"),
    ({"cli": 0}, "positive integer"),
    ({"cli": True}, "positive integer"),
    ({"loader": 1.5}, "positive integer"),
    ([1], "must be a table"),
])
def test_parse_rejects(bad, text):
    with pytest.raises(ValueError, match=text):
        R.parse_requires(bad)


def test_mod_reads_requires_and_bad_manifest_raises(tmp_path):
    ok = _write(tmp_path, "\n[requires]\ncli = 31\n", "ok")
    assert A.Mod(ok).requires == {"cli": 31}
    assert A.Mod(_write(tmp_path, "", "none")).requires == {}
    bad = _write(tmp_path, "\n[requires]\ncli = \"x\"\n", "bad")
    with pytest.raises(ValueError):
        A.Mod(bad)


def test_cli_too_old_is_refused_with_both_numbers(tmp_path, versions, capsys):
    m = A.Mod(_write(tmp_path, "\n[requires]\ncli = 31\n"))
    out = A.apply_requires_gate([m], tmp_path)
    assert out[0].enabled is False
    assert ("m: needs RSMM CLI v31 or newer, this is v30 - update RSMM"
            in capsys.readouterr().err)


def test_loader_too_old_is_refused(tmp_path, versions, capsys):
    m = A.Mod(_write(tmp_path, "\n[requires]\nloader = 58\n"))
    A.apply_requires_gate([m], tmp_path)
    assert m.enabled is False
    assert ("needs loader v58 or newer, the installed loader is v57 - "
            "run rsmm update-loader" in capsys.readouterr().err)


def test_satisfied_and_other_mods_still_apply(tmp_path, versions):
    ok = A.Mod(_write(tmp_path, "\n[requires]\ncli = 30\nloader = 57\n", "ok"))
    old = A.Mod(_write(tmp_path, "\n[requires]\ncli = 99\n", "old"))
    plain = A.Mod(_write(tmp_path, "", "plain"))
    A.apply_requires_gate([ok, old, plain], tmp_path)
    assert (ok.enabled, old.enabled, plain.enabled) == (True, False, True)


def _install(game, dll: bytes | None, manifest_dll: bytes | None = None, version=57):
    import hashlib
    import json
    game.mkdir(parents=True, exist_ok=True)
    if dll is not None:
        (game / "winhttp.dll").write_bytes(dll)
    if manifest_dll is not None:
        (game / "rsmm").mkdir(exist_ok=True)
        (game / "rsmm" / "loader.manifest.json").write_text(json.dumps({
            "loader_version": version,
            "files": [{"path": "winhttp.dll",
                       "sha256": hashlib.sha256(manifest_dll).hexdigest()}]}))


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """This CLI's bundled loader: DLL bytes b"bundled", stamp v50."""
    from rsmm.engine import loader_update as LU
    dll = tmp_path / "bundled.dll"
    dll.write_bytes(b"bundled")
    monkeypatch.setattr(LU, "bundled_loader_dll", lambda: dll)
    monkeypatch.setattr(LU, "bundled_version", lambda: 50)


def test_install_none_without_a_dll(tmp_path, bundle):
    assert R.loader_install(tmp_path / "g") == {"state": "none", "version": None}
    assert R.effective_loader_version(tmp_path / "g") is None


def test_install_release_trusts_a_manifest_that_matches_the_dll(tmp_path, bundle):
    g = tmp_path / "g"
    _install(g, b"dll", b"dll", version=57)
    assert R.loader_install(g) == {"state": "release", "version": 57}
    assert R.effective_loader_version(g) == 57


def test_install_without_manifest_is_the_bundle_only_if_the_dll_is(tmp_path, bundle):
    ok, other = tmp_path / "ok", tmp_path / "other"
    _install(ok, b"bundled")
    _install(other, b"old dll with no manifest")
    assert R.loader_install(ok) == {"state": "release", "version": 50}
    assert R.loader_install(other)["state"] == "dev"
    assert R.effective_loader_version(other) is None


def test_stale_manifest_after_a_dll_swap_is_not_trusted(tmp_path, bundle):
    g = tmp_path / "g"
    _install(g, b"hand built", b"dll", version=57)
    assert R.loader_install(g)["state"] == "dev"
    assert R.effective_loader_version(g) is None


def test_stale_manifest_but_dll_is_the_bundled_one(tmp_path, bundle):
    g = tmp_path / "g"
    _install(g, b"bundled", b"dll", version=57)
    assert R.loader_install(g) == {"state": "release", "version": 50}


def test_loader_requirement_against_no_loader_skips(tmp_path, bundle, capsys):
    m = A.Mod(_write(tmp_path, "\n[requires]\nloader = 58\n"))
    skipped = A.requires_gate([m], tmp_path / "g")
    assert m.enabled is False
    assert skipped == [{"id": "m", "needs": {"loader": 58},
                        "reason": "needs loader v58, no loader is installed - "
                                  "run rsmm install-loader"}]
    assert "no loader is installed - run rsmm install-loader" in capsys.readouterr().err


def test_loader_requirement_against_dev_build_applies_with_a_warning(
        tmp_path, bundle, capsys):
    g = tmp_path / "g"
    _install(g, b"hand built")
    m = A.Mod(_write(tmp_path, "\n[requires]\nloader = 58\n"))
    assert A.requires_gate([m], g) == []
    assert m.enabled is True
    assert ("m: the installed loader is a dev or unrecognized build - can't "
            "confirm it has loader v58" in capsys.readouterr().err)


def test_release_loader_too_old_still_skips(tmp_path, bundle):
    g = tmp_path / "g"
    _install(g, b"dll", b"dll", version=57)
    m = A.Mod(_write(tmp_path, "\n[requires]\nloader = 58\n"))
    skipped = A.requires_gate([m], g)
    assert skipped[0]["needs"] == {"loader": 58}
    assert "the installed loader is v57" in skipped[0]["reason"]


def test_skipped_entry_for_a_cli_requirement(tmp_path, versions):
    m = A.Mod(_write(tmp_path, "\n[requires]\ncli = 31\n"))
    assert A.requires_gate([m], tmp_path) == [{
        "id": "m", "needs": {"cli": 31},
        "reason": "needs RSMM CLI v31 or newer, this is v30 - update RSMM"}]


def test_apply_records_skipped_for_the_bridge(tmp_path, monkeypatch):
    import json
    out = tmp_path / "skipped.json"
    monkeypatch.setenv("RSMM_SKIPPED_FILE", str(out))
    A._write_skipped([{"id": "m", "reason": "r", "needs": {"cli": 3}}])
    assert json.loads(out.read_text()) == [{"id": "m", "reason": "r", "needs": {"cli": 3}}]


def test_bridge_apply_returns_the_skipped_list(monkeypatch, capsys):
    import json
    import os

    from rsmm.cli import json_bridge as B

    def fake(args):
        with open(os.environ["RSMM_SKIPPED_FILE"], "w") as f:
            json.dump([{"id": "m", "reason": "r", "needs": {"loader": 9}}], f)
        return {"ok": True, "code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(B, "_collect_rsmm", fake)
    B.cmd_apply([])
    out = json.loads(capsys.readouterr().out)
    assert out["skipped"] == [{"id": "m", "reason": "r", "needs": {"loader": 9}}]
    assert "RSMM_SKIPPED_FILE" not in os.environ


def test_bridge_apply_skipped_is_empty_when_none(monkeypatch, capsys):
    import json

    from rsmm.cli import json_bridge as B
    monkeypatch.setattr(B, "_collect_rsmm", lambda a: {"ok": False, "code": 1, "stdout": ""})
    B.cmd_apply([])
    assert json.loads(capsys.readouterr().out)["skipped"] == []


def test_lint_flags_a_bad_requires(tmp_path, capsys):
    from rsmm.cli import lint
    root = _write(tmp_path, "version = \"1.0.0\"\n\n[requires]\nclu = 3\n")
    errs, _ = lint.lint_one(root)
    assert errs >= 1
    assert "unknown key" in capsys.readouterr().out


def test_emit_failure_names_the_cli_version(tmp_path, monkeypatch, versions, capsys):
    import rsmm.sdk.content as content

    class _Reg:
        def __init__(self, **kw): pass
        def register(self, *a, **kw): pass
        def emit(self, out_dir):
            raise ValueError("hero X: frame is a table of abilities")

    monkeypatch.setattr(content, "ContentRegistry", _Reg)
    root = tmp_path / "p"
    (root / "assets").mkdir(parents=True)
    from types import SimpleNamespace
    mod = SimpleNamespace(id="p", enabled=True, experimental=False, root=root,
                          assets_dir=root / "assets",
                          content_blocks=[{"kind": "hero", "id": "x"}])
    A.emit_content_blocks([mod])
    err = capsys.readouterr().err
    assert ("emit failed: hero X: frame is a table of abilities (RSMM CLI v30 - "
            "a field this CLI doesn't know may need a newer RSMM)") in err
