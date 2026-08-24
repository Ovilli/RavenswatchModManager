"""Release-notes channel: parsing bounds, cache behaviour, fallbacks."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from rsmm.engine import changelog_feed as cf
from rsmm.engine.changelog_feed import ChangelogError, parse

GOOD = {
    "generated": "2026-08-22",
    "entries": [
        {
            "version": "5.0.2",
            "date": "2026-08-20",
            "summary": "A summary.",
            "highlights": ["One thing.", "Another thing."],
        }
    ],
}


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Keep every test off the developer's real cache directory."""
    monkeypatch.setenv("RSMM_DATA_DIR", str(tmp_path / "userdata"))
    return tmp_path


def _serve(tmp_path, payload: object, name: str = cf.ASSET_NAME) -> None:
    """Publish `payload` at a file:// base the module will fetch from."""
    remote = tmp_path / "remote"
    remote.mkdir(exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (remote / name).write_text(text, encoding="utf-8")


def _use_remote(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RSMM_CHANGELOG_BASE", (tmp_path / "remote").as_uri())


def test_parse_accepts_a_well_formed_feed():
    feed = cf.parse(json.dumps(GOOD).encode())
    assert feed["generated"] == "2026-08-22"
    assert feed["entries"][0]["version"] == "5.0.2"
    assert feed["entries"][0]["summary"] == "A summary."


def test_parse_rejects_non_json():
    with pytest.raises(cf.ChangelogError):
        cf.parse(b"not json at all")


def test_parse_rejects_a_feed_with_no_entries_list():
    with pytest.raises(cf.ChangelogError):
        cf.parse(json.dumps({"generated": "x"}).encode())


def test_parse_drops_entries_with_no_version_or_no_highlights():
    doc = {
        "entries": [
            {"version": "", "highlights": ["x"]},
            {"version": "1.0.0", "highlights": []},
            {"version": "1.0.0", "highlights": ["kept"]},
        ]
    }
    assert [e["version"] for e in cf.parse(json.dumps(doc).encode())["entries"]] == ["1.0.0"]


def test_parse_caps_entry_and_highlight_counts():
    doc = {
        "entries": [
            {"version": f"1.0.{i}", "highlights": ["x"] * (cf.MAX_HIGHLIGHTS + 5)}
            for i in range(cf.MAX_ENTRIES + 10)
        ]
    }
    feed = cf.parse(json.dumps(doc).encode())
    assert len(feed["entries"]) == cf.MAX_ENTRIES
    assert len(feed["entries"][0]["highlights"]) == cf.MAX_HIGHLIGHTS


def test_parse_truncates_overlong_text():
    doc = {"entries": [{"version": "1.0.0", "highlights": ["x" * (cf.MAX_TEXT + 500)]}]}
    assert len(cf.parse(json.dumps(doc).encode())["entries"][0]["highlights"][0]) == cf.MAX_TEXT


def test_parse_strips_control_characters():
    """An ANSI escape in a highlight would repaint the terminal rendering it."""
    doc = {"entries": [{"version": "1.0.0", "highlights": ["safe\x1b[2Jwiped​"]}]}
    line = cf.parse(json.dumps(doc).encode())["entries"][0]["highlights"][0]
    assert "\x1b" not in line and "​" not in line
    assert line == "safe[2Jwiped"


def test_check_fetches_and_caches(tmp_path, monkeypatch):
    _serve(tmp_path, GOOD)
    _use_remote(tmp_path, monkeypatch)

    first = cf.check()
    assert first["status"] == "fetched"
    assert cf.cache_path().is_file()

    # Second call inside the TTL must not touch the network at all.
    monkeypatch.setenv("RSMM_CHANGELOG_BASE", (tmp_path / "gone").as_uri())
    second = cf.check()
    assert second["status"] == "cached"
    assert second["entries"] == first["entries"]


def test_check_refetches_once_the_ttl_expires(tmp_path, monkeypatch):
    _serve(tmp_path, GOOD)
    _use_remote(tmp_path, monkeypatch)
    cf.check()

    stale = json.loads(cf.cache_path().read_text())
    stale["fetched_at"] = time.time() - cf.CACHE_TTL - 1
    cf.cache_path().write_text(json.dumps(stale))

    updated = {"entries": [{"version": "9.9.9", "date": "2026-09-01", "highlights": ["new"]}]}
    _serve(tmp_path, updated)
    assert cf.check()["entries"][0]["version"] == "9.9.9"


def test_check_serves_a_stale_cache_when_the_channel_is_down(tmp_path, monkeypatch):
    _serve(tmp_path, GOOD)
    _use_remote(tmp_path, monkeypatch)
    cf.check()

    monkeypatch.setenv("RSMM_CHANGELOG_BASE", (tmp_path / "gone").as_uri())
    state = cf.check(force=True)
    assert state["status"] == "cached"
    assert state["entries"][0]["version"] == "5.0.2"
    # Usable content, but the caller is told the refresh failed.
    assert state["error"]


def test_check_falls_back_to_the_bundled_copy_with_no_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("RSMM_CHANGELOG_BASE", (tmp_path / "gone").as_uri())
    state = cf.check()
    assert state["status"] == "bundled"
    # data/changelog.json is the file the publish script uploads.
    assert state["entries"]


def test_check_reports_unavailable_when_even_the_bundled_copy_is_gone(tmp_path, monkeypatch):
    monkeypatch.setenv("RSMM_CHANGELOG_BASE", (tmp_path / "gone").as_uri())
    monkeypatch.setattr(cf, "bundled_path", lambda: tmp_path / "nope.json")
    state = cf.check()
    assert state["status"] == "unavailable"
    assert state["entries"] == []
    assert state["error"]


def test_check_rejects_a_non_https_remote(monkeypatch):
    """The only non-HTTPS scheme allowed is file://, for these tests."""
    monkeypatch.setenv("RSMM_CHANGELOG_BASE", "http://example.invalid/feed")
    monkeypatch.setattr(cf, "bundled_path", lambda: cf.cache_path())
    assert cf.check()["status"] == "unavailable"


def test_shipped_feed_survives_its_own_parser():
    """data/changelog.json must be publishable as-is (publish_changelog.sh gate)."""
    feed = cf.parse(cf.bundled_path().read_bytes())
    source = json.loads(cf.bundled_path().read_text(encoding="utf-8"))
    assert len(feed["entries"]) == len(source["entries"]), "an entry would be dropped as unusable"
    versions = [e["version"] for e in feed["entries"]]
    assert len(versions) == len(set(versions)), "duplicate version in the shipped feed"
    assert all(e["date"] for e in feed["entries"]), "every shipped entry needs a date"


# --- loader-channel notes --------------------------------------------------
#
# The loader ships out of band, so a scripting fix reaches users with no app
# release in between. Every entry used to be keyed by an APP version, and the
# desktop dialog clamps those to the version the user is running — so a note
# about a loader build had to be filed under a release it was not part of, or
# go unread.

def test_a_loader_note_needs_no_app_version():
    feed = parse(json.dumps({
        "generated": "2026-08-24",
        "entries": [{
            "loader_version": 8,
            "date": "2026-08-24",
            "summary": "Stutter fixes.",
            "highlights": ["The identity probes no longer syscall per value."],
        }],
    }).encode())
    entry = feed["entries"][0]
    assert entry["loader_version"] == 8
    assert entry["version"] == ""
    assert entry["summary"] == "Stutter fixes."


def test_an_app_entry_may_also_name_a_loader_build():
    feed = parse(json.dumps({
        "entries": [{
            "version": "5.1.1",
            "loader_version": 8,
            "highlights": ["Both at once."],
        }],
    }).encode())
    assert feed["entries"][0]["version"] == "5.1.1"
    assert feed["entries"][0]["loader_version"] == 8


def test_an_entry_identified_by_nothing_is_still_dropped():
    with pytest.raises(ChangelogError):
        parse(json.dumps({"entries": [{"highlights": ["orphan"]}]}).encode())


@pytest.mark.parametrize("bad", [0, -3, 100_001, "8", 8.0, True, None])
def test_an_implausible_loader_version_is_ignored(bad):
    """Bounded like every other field on this untrusted payload. A rejected
    loader_version does not poison the entry — it just stops identifying it,
    so an entry with an app version survives and one without is dropped."""
    feed = parse(json.dumps({
        "entries": [{"version": "5.1.0", "loader_version": bad, "highlights": ["x"]}],
    }).encode())
    assert "loader_version" not in feed["entries"][0]


def test_add_loader_changelog_writes_and_replaces(tmp_path):
    """The publish-side helper: idempotent, because re-publishing a loader
    version should update its note rather than stack another one."""
    import subprocess

    feed = tmp_path / "changelog.json"
    feed.write_text(json.dumps({
        "generated": "2026-08-01",
        "entries": [{"version": "5.1.0", "date": "2026-08-01", "highlights": ["old"]}],
    }), encoding="utf-8")
    script = Path(__file__).resolve().parent.parent / "scripts" / "add_loader_changelog.py"

    def run(summary: str):
        return subprocess.run(
            [sys.executable, str(script), "--loader-version", "8",
             "--summary", summary, "--highlight", "did a thing",
             "--date", "2026-08-24", "--feed", str(feed)],
            capture_output=True, text=True,
        )

    assert run("first").returncode == 0
    doc = json.loads(feed.read_text(encoding="utf-8"))
    assert doc["entries"][0]["loader_version"] == 8
    assert doc["entries"][0]["summary"] == "first"
    assert len(doc["entries"]) == 2          # the app entry is untouched

    assert run("second").returncode == 0
    doc = json.loads(feed.read_text(encoding="utf-8"))
    assert [e.get("loader_version") for e in doc["entries"]].count(8) == 1
    assert doc["entries"][0]["summary"] == "second"
    assert len(doc["entries"]) == 2
