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
    monkeypatch.setattr(R, "effective_loader_version", lambda _g: 57)


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


def test_loader_version_prefers_planted_stamp(tmp_path, monkeypatch):
    from rsmm.engine import loader_update as LU
    monkeypatch.setattr(LU, "bundled_version", lambda: 50)
    assert R.effective_loader_version(tmp_path) == 50
    (tmp_path / "rsmm").mkdir()
    (tmp_path / "rsmm" / "loader.manifest.json").write_text(
        '{"loader_version": 57}', encoding="utf-8")
    assert R.effective_loader_version(tmp_path) == 57


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
