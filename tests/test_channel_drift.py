"""Channel drift helper and the doctor line built on it.

Every test builds its own throwaway git repo; the real history and tracked
data/ are never touched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from rsmm.cli import doctor
from rsmm.dev import channel_drift

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True,
    )


def _commit(repo: Path, rel: str, text: str, msg: str) -> None:
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)


def _stamp(repo: Path, kind: str, n: int) -> None:
    _commit(repo, f"data/{kind}_version.json",
            json.dumps({f"{kind}_version": n}), f"chore({kind}): publish v{n}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _commit(r, "src/loader/a.cpp", "1", "initial")
    _stamp(r, "loader", 5)
    _stamp(r, "cli", 7)
    return r


def _by_name(states: list[dict]) -> dict[str, dict]:
    return {s["channel"]: s for s in states}


def test_current_when_nothing_since_publish(repo: Path) -> None:
    s = _by_name(channel_drift.drift(repo))
    assert s["loader"]["status"] == "current"
    assert s["loader"]["version"] == 5
    assert s["cli"]["status"] == "current"
    assert s["cli"]["version"] == 7
    assert "matches main" in channel_drift.summary_line(s["loader"])


def test_counts_only_each_channels_paths(repo: Path) -> None:
    _commit(repo, "src/loader/hook.cpp", "x", "loader one")
    _commit(repo, "src/rsmm/x.py", "x", "cli one")
    _commit(repo, "src/loader/lib/y.lua", "x", "loader two")
    _commit(repo, "docs/readme.md", "x", "docs only")
    s = _by_name(channel_drift.drift(repo))
    assert s["loader"]["status"] == "behind"
    assert s["loader"]["count"] == 2
    assert [c.split(" ", 1)[1] for c in s["loader"]["commits"]] == [
        "loader two", "loader one"]
    assert s["cli"]["count"] == 1
    assert "2 commits behind main (src/loader)" in channel_drift.summary_line(
        s["loader"])


def test_new_publish_resets_that_channel_only(repo: Path) -> None:
    _commit(repo, "src/loader/hook.cpp", "x", "loader one")
    _commit(repo, "src/rsmm/x.py", "x", "cli one")
    _stamp(repo, "loader", 6)
    s = _by_name(channel_drift.drift(repo))
    assert s["loader"]["status"] == "current"
    assert s["loader"]["version"] == 6
    assert s["cli"]["count"] == 1


def test_shallow_clone_is_unknown(repo: Path, tmp_path: Path) -> None:
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", repo.as_uri(), str(clone)],
                   check=True, capture_output=True)
    s = _by_name(channel_drift.drift(clone))
    assert s["loader"]["status"] == "unknown"
    assert "unknown (shallow clone)" in channel_drift.summary_line(s["loader"])


def test_cli_json_and_markdown_exit_zero(repo: Path, capsys) -> None:
    _commit(repo, "src/rsmm/x.py", "x", "cli one")
    assert channel_drift.main(["--repo", str(repo), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {c["channel"] for c in data["channels"]} == {"loader", "cli"}
    assert channel_drift.main(["--repo", str(repo), "--markdown"]) == 0
    assert "CLI channel v7 is 1 commit behind main" in capsys.readouterr().out


def test_not_a_repo_exits_zero(tmp_path: Path, capsys) -> None:
    assert channel_drift.main(["--repo", str(tmp_path)]) == 0


def test_doctor_line_silent_without_git_checkout(tmp_path, monkeypatch) -> None:
    import rsmm.engine.paths as paths

    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path)
    assert doctor.check_channel_drift() == []


def test_doctor_line_silent_when_frozen(repo: Path, monkeypatch) -> None:
    import sys

    import rsmm.engine.paths as paths

    monkeypatch.setattr(paths, "REPO_ROOT", repo)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert doctor.check_channel_drift() == []


def test_doctor_line_warns_in_git_checkout(repo: Path, monkeypatch) -> None:
    import rsmm.engine.paths as paths

    _commit(repo, "src/loader/hook.cpp", "x", "loader one")
    monkeypatch.setattr(paths, "REPO_ROOT", repo)
    res = {r.code: r for r in doctor.check_channel_drift()}
    assert res["channel-drift.loader"].kind == "WARN"
    assert "newer than published loader v5" in res["channel-drift.loader"].label
    assert res["channel-drift.cli"].kind == "OK"
