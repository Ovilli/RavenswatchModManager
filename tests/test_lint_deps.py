"""`rsmm lint` (whole-tree) runs the cross-mod dependency graph, so broken
deps fail the author's pre-flight — not just `doctor` / apply.
"""

from __future__ import annotations

from rsmm.cli import lint


def _write_mod(mods, mod_id: str, body: str = "") -> None:
    d = mods / mod_id
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text(
        f'[mod]\nid = "{mod_id}"\nname = "{mod_id}"\nversion = "1.0.0"\n{body}',
        encoding="utf-8",
    )


def _run_lint(mods, monkeypatch, argv) -> int:
    monkeypatch.setattr(lint, "MODS_DIR", mods)
    monkeypatch.setattr("sys.argv", argv)
    return lint.main()


def test_missing_dep_fails_whole_tree_lint(tmp_path, monkeypatch, capsys):
    mods = tmp_path / "mods"
    _write_mod(mods, "User", 'requires = ["MissingLib >=2.0"]\n')
    rc = _run_lint(mods, monkeypatch, ["lint"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "missing-dep" in out


def test_satisfied_dep_passes(tmp_path, monkeypatch, capsys):
    mods = tmp_path / "mods"
    _write_mod(mods, "Core", "")
    _write_mod(mods, "User", 'requires = ["Core >=1.0 <2.0"]\n')
    rc = _run_lint(mods, monkeypatch, ["lint"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "missing-dep" not in out and "version-mismatch" not in out


def test_recommend_warns_but_does_not_fail(tmp_path, monkeypatch, capsys):
    mods = tmp_path / "mods"
    _write_mod(mods, "User", 'recommends = ["Optional >=1.0"]\n')
    rc = _run_lint(mods, monkeypatch, ["lint"])
    out = capsys.readouterr().out
    assert rc == 0                       # warn never fails the lint
    assert "missing-recommend" in out


def test_single_mod_lint_skips_graph(tmp_path, monkeypatch, capsys):
    """Linting one mod by id must not run the graph (can't resolve deps in
    isolation) — so a dangling requires there is not a graph error."""
    mods = tmp_path / "mods"
    _write_mod(mods, "User", 'requires = ["MissingLib >=2.0"]\n')
    rc = _run_lint(mods, monkeypatch, ["lint", "User"])
    out = capsys.readouterr().out
    assert "missing-dep" not in out
    assert rc == 0
