"""`rsmm rebuild-fn-patterns`: the steps run in order, a failure puts the old DB back."""

from __future__ import annotations

import json

import pytest

from rsmm.cli import cmd_rebuild_patterns as R

_STEPS = ["generate patterns", "sync semantic entries", "verify symbols resolve",
          "resolve every entry"]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fake checkout with a DB stamped for one exe, and a fake game install."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "gen_function_patterns.py").write_text("")
    (tmp_path / "data").mkdir()
    game = tmp_path / "game"
    game.mkdir()
    (game / "Ravenswatch.exe").write_bytes(b"exe-bytes")
    (tmp_path / "data" / "function_patterns.json").write_text('["old"]')
    (tmp_path / "data" / "function_patterns.meta.json").write_text(
        json.dumps({"game_exe_sha256": R._sha256(game / "Ravenswatch.exe"), "pattern_count": 1}))
    monkeypatch.setattr(R, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(R, "_python", lambda: "python-with-capstone")
    return tmp_path, game


def _fake_run(calls, fail=None, wrong=0, interrupt=None):
    def run(label, argv):
        calls.append((label, argv[0]))
        if label == interrupt:
            raise KeyboardInterrupt
        if label == fail:
            return 1, ""
        if label.startswith("generate"):
            (R.REPO_ROOT / "data" / "function_patterns.json").write_text('["new"]')
        if label.startswith("resolve every"):
            return 0, f"ALL DONE ok={10 - wrong} fail={wrong} ({100 - 10 * wrong:.2f}%)"
        return 0, ""
    return run


def _db(root):
    return (root / "data" / "function_patterns.json").read_text()


def test_a_db_already_built_for_this_exe_is_left_alone(repo, monkeypatch):
    _root, game = repo
    calls: list = []
    monkeypatch.setattr(R, "_run", _fake_run(calls))
    assert R.main(["--game-dir", str(game)]) == 0
    assert calls == []


def test_a_missing_db_is_rebuilt_even_when_the_stamp_matches(repo, monkeypatch):
    root, game = repo
    (root / "data" / "function_patterns.json").unlink()
    calls: list = []
    monkeypatch.setattr(R, "_run", _fake_run(calls))
    assert R.main(["--game-dir", str(game)]) == 0
    assert [label for label, _py in calls] == _STEPS


def test_force_runs_every_step_with_the_chosen_python_and_keeps_the_old_db(repo, monkeypatch):
    root, game = repo
    calls: list = []
    monkeypatch.setattr(R, "_run", _fake_run(calls))
    assert R.main(["--game-dir", str(game), "--force"]) == 0
    assert calls == [(label, "python-with-capstone") for label in _STEPS]
    assert _db(root) == '["new"]'
    assert (root / "data" / "function_patterns.json.prev").read_text() == '["old"]'


@pytest.mark.parametrize("step", _STEPS)
def test_a_failing_step_puts_the_old_db_back(repo, monkeypatch, step):
    root, game = repo
    monkeypatch.setattr(R, "_run", _fake_run([], fail=step))
    assert R.main(["--game-dir", str(game), "--force"]) == 1
    assert _db(root) == '["old"]'
    assert not list((root / "data").glob("*.prev"))


def test_an_entry_that_resolves_wrong_fails_the_build(repo, monkeypatch, capsys):
    root, game = repo
    monkeypatch.setattr(R, "_run", _fake_run([], wrong=1))
    assert R.main(["--game-dir", str(game), "--force"]) == 1
    assert _db(root) == '["old"]' and "1 of 10 entries" in capsys.readouterr().err


def test_an_interrupted_build_puts_the_old_db_back(repo, monkeypatch):
    root, game = repo
    monkeypatch.setattr(R, "_run", _fake_run([], interrupt="sync semantic entries"))
    assert R.main(["--game-dir", str(game), "--force"]) == 1
    assert _db(root) == '["old"]'


def test_a_failed_first_build_leaves_no_half_made_db(repo, monkeypatch):
    root, game = repo
    for name in ("function_patterns.json", "function_patterns.meta.json"):
        (root / "data" / name).unlink()
    monkeypatch.setattr(R, "_run", _fake_run([], fail="sync semantic entries"))
    assert R.main(["--game-dir", str(game)]) == 1
    assert not list((root / "data").iterdir())


def test_a_symbol_gate_that_cannot_run_is_reported_not_treated_as_bad_symbols(repo, monkeypatch):
    _root, game = repo
    run = _fake_run([])

    def gate_cannot_run(label, argv):
        return (R.EXIT_CANNOT_RUN, "") if label.startswith("verify") else run(label, argv)

    monkeypatch.setattr(R, "_run", gate_cannot_run)
    assert R.main(["--game-dir", str(game), "--force"]) == 0


def test_skip_validate_runs_only_the_build_steps(repo, monkeypatch):
    _root, game = repo
    calls: list = []
    monkeypatch.setattr(R, "_run", _fake_run(calls))
    assert R.main(["--game-dir", str(game), "--force", "--skip-validate"]) == 0
    assert [label for label, _py in calls] == _STEPS[:2]


def test_dry_run_a_missing_exe_and_no_capstone_change_nothing(repo, monkeypatch, tmp_path,
                                                             capsys):
    root, game = repo
    calls: list = []
    monkeypatch.setattr(R, "_run", _fake_run(calls))
    assert R.main(["--game-dir", str(game), "--force", "--dry-run"]) == 0
    assert calls == [] and "plan:" in capsys.readouterr().out
    assert R.main(["--game-dir", str(tmp_path / "nowhere")]) == 2
    monkeypatch.setattr(R, "_python", lambda: None)
    assert R.main(["--game-dir", str(game), "--force"]) == 2
    assert calls == [] and _db(root) == '["old"]'
