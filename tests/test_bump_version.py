"""The release bump must commit the four version files and nothing else.

9f5a0f8 ("chore(release): bump to 5.4.4") also carried 343 deleted lines of
`src/loader/lib/rsmm.lua`, because `git commit -m` commits the whole index and
that file happened to be staged. The SDK regression rode into the release under
a subject line that says "bump", CI went red on main, and a desktop build
shipped from it. This pins the pathspec that stops it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts/bump-version.py"

# The four files the script rewrites, with just enough content to be parseable.
FIXTURES = {
    "apps/desktop/src-tauri/tauri.conf.json": '{\n  "version": "0.1.0"\n}\n',
    "apps/desktop/src-tauri/Cargo.toml": '[package]\nname = "rsmm-desktop"\nversion = "0.1.0"\n',
    "apps/desktop/src-tauri/Cargo.lock": (
        '[[package]]\nname = "rsmm-desktop"\nversion = "0.1.0"\n'
    ),
    "apps/desktop/package.json": '{\n  "name": "desktop",\n  "version": "0.1.0"\n}\n',
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repo holding the four version files plus one other file."""
    for rel, body in FIXTURES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    (tmp_path / "src/loader/lib").mkdir(parents=True)
    (tmp_path / "src/loader/lib/rsmm.lua").write_text("-- the SDK\nreturn {}\n")
    shutil.copytree(REPO_ROOT / "scripts", tmp_path / "scripts", dirs_exist_ok=True)

    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def test_staged_unrelated_file_stays_out_of_the_release_commit(repo: Path) -> None:
    # Someone edits the SDK and stages it, then bumps the version — exactly the
    # sequence behind 9f5a0f8.
    sdk = repo / "src/loader/lib/rsmm.lua"
    sdk.write_text("-- the SDK, minus a capability\n")
    git(repo, "add", "src/loader/lib/rsmm.lua")

    out = subprocess.run(
        ["python3", str(repo / "scripts/bump-version.py"), "0.2.0"],
        cwd=repo, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr

    committed = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert "src/loader/lib/rsmm.lua" not in committed, (
        f"the release commit swept in a staged SDK change: {committed}"
    )
    assert sorted(committed) == sorted(FIXTURES), committed

    # And the change is not silently discarded either: it is still staged, and
    # the run said so.
    assert "src/loader/lib/rsmm.lua" in git(repo, "diff", "--cached", "--name-only")
    assert "leaving these staged files OUT" in out.stdout

    # The bump itself still happened in all four files.
    conf = json.loads((repo / "apps/desktop/src-tauri/tauri.conf.json").read_text())
    assert conf["version"] == "0.2.0"
