"""scripts/release_notes.py: the GitHub release body of a tag and of a rolling
channel publish, written from git and data/changelog.json."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _mod():
    spec = importlib.util.spec_from_file_location("release_notes",
                                                  ROOT / "scripts" / "release_notes.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _has(ref: str) -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=ROOT,
                          capture_output=True).returncode == 0


needs_tags = pytest.mark.skipif(not (_has("v5.9.30") and _has("v5.9.29")),
                                reason="release tags not fetched")


@needs_tags
def test_a_release_lists_its_note_prs_commits_and_authors():
    rn = _mod()
    assert rn.previous_tag("v5.9.30") == "v5.9.29"
    body = rn.render("v5.9.30", "Ovilli/RavenswatchModManager")
    assert body.startswith("Mute any in-game sound")            # the feed's summary
    assert "## Pull requests" in body and "(#78, " in body          # a PR, by number
    assert "## Commits" in body and "by Ovilli" in body             # direct commits, authors
    assert "/commit/" in body
    assert "compare/v5.9.29...v5.9.30" in body
    assert "chore(release): bump" not in body                       # machinery is left out


def test_merge_and_squash_titles_name_their_pr():
    rn = _mod()
    assert rn._MERGE.match("Merge pull request #129 from Ovilli/feat/x")[1] == "129"
    assert rn._SQUASH.search("Update header controls (#127)")[1] == "127"
    assert rn._MACHINERY.match("chore(loader): publish loader channel v59")
    assert rn._MACHINERY.match("chore(release): bump to 5.9.32")
    assert not rn._MACHINERY.match("chore(release): tidy the workflow")


@needs_tags
def test_a_channel_publish_stacks_on_the_previous_ones():
    rn = _mod()
    head = rn.git("rev-parse", "HEAD").strip()
    since = rn.git("rev-parse", "v5.9.29").strip()
    first = rn.render_channel("cli", 40, since, head, "first", "", "O/R", "2026-01-01")
    assert first.startswith(rn.CHANNEL_INTRO["cli"])
    assert "## cli v40 (2026-01-01)" in first and "first" in first
    second = rn.render_channel("cli", 41, since, head, "second", first, "O/R", "2026-01-02")
    assert second.index("## cli v41") < second.index("## cli v40")
    again = rn.render_channel("cli", 41, since, head, "redo", second, "O/R", "2026-01-02")
    assert again.count("## cli v41") == 1                           # a re-run replaces itself
    many = first
    for v in range(41, 41 + rn.CHANNEL_KEEP + 5):
        many = rn.render_channel("cli", v, since, head, "", many, "O/R", "2026-01-03")
    assert many.count("\n## cli v") == rn.CHANNEL_KEEP
