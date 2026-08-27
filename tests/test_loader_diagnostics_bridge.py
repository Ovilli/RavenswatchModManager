"""The desktop app's read-only window onto what the loader recorded.

Three bridge commands back the Log screen: the archived-run listing, reading
one of those runs, and the boot canary / crash history. All three hand the
frontend data it previously could not reach at all, and the first two take a
run NAME from the UI — so the resolver's refusal to leave the archive
directory is a contract, not an implementation detail.
"""

import json

import pytest

from rsmm.cli import cmd_log, json_bridge


def _emit_json(capsys):
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def game(tmp_path, monkeypatch):
    """A game install with two archived runs and a live log."""
    root = tmp_path / "game"
    (root / "DarkTalesResources" / "_Cooking").mkdir(parents=True)
    mods = root / "mods"
    mods.mkdir()
    (mods / "_log.txt").write_text("== SESSION aaaa\nlive one\nlive two\n")
    logs = root / "rsmm" / "logs"
    logs.mkdir(parents=True)
    (logs / "2026-08-01_101010_aa11.log").write_text("== SESSION aa11\nold run\n")
    (logs / "2026-08-02_202020_bb22.log").write_text("== SESSION bb22\nnewer run\n")
    monkeypatch.setenv("RSMM_GAME_DIR", str(root))
    return root


# --- archived runs ---------------------------------------------------------

def test_runs_are_listed_newest_first(game, capsys):
    assert json_bridge.cmd_loader_runs() == 0
    out = _emit_json(capsys)
    # Sorted by NAME, which leads with the run's own start stamp, so lexical
    # order is chronological even though archiving rewrites mtime.
    assert [r["name"] for r in out["runs"]] == [
        "2026-08-02_202020_bb22.log",
        "2026-08-01_101010_aa11.log",
    ]
    assert all(r["bytes"] > 0 for r in out["runs"])


def test_missing_archive_dir_is_an_empty_list_not_an_error(tmp_path, monkeypatch, capsys):
    root = tmp_path / "game"
    (root / "DarkTalesResources" / "_Cooking").mkdir(parents=True)
    monkeypatch.setenv("RSMM_GAME_DIR", str(root))
    assert json_bridge.cmd_loader_runs() == 0
    assert _emit_json(capsys)["runs"] == []


# --- resolve_run -----------------------------------------------------------

def test_a_unique_prefix_resolves(game):
    assert cmd_log.resolve_run("2026-08-01", game).name == "2026-08-01_101010_aa11.log"


def test_an_ambiguous_prefix_is_refused_rather_than_guessed(game):
    with pytest.raises(cmd_log.RunNotFound):
        cmd_log.resolve_run("2026-08", game)


@pytest.mark.parametrize("name", [
    "../../mods/_log.txt",
    "/etc/passwd",
    "..",
    "",
])
def test_traversal_cannot_escape_the_archive_directory(game, name):
    """The name arrives from the desktop UI. Candidates come only from the
    archive listing, so nothing outside it is reachable by construction."""
    with pytest.raises(cmd_log.RunNotFound):
        cmd_log.resolve_run(name, game)


def test_bridge_reads_an_archived_run(game, capsys):
    assert json_bridge.cmd_loader_log(run="2026-08-01") == 0
    out = _emit_json(capsys)
    assert out["exists"] is True
    assert out["path"].endswith("2026-08-01_101010_aa11.log")
    assert "old run" in out["lines"]


def test_bridge_reports_a_bad_run_name_as_a_failure(game, capsys):
    assert json_bridge.cmd_loader_log(run="nope") == 1


def test_live_log_read_reports_its_byte_size(game, capsys):
    """The desktop seeds its incremental tail offset from this; without it the
    first poll re-reads the whole file."""
    assert json_bridge.cmd_loader_log() == 0
    out = _emit_json(capsys)
    assert out["bytes"] == (game / "mods" / "_log.txt").stat().st_size


# --- health ----------------------------------------------------------------

def test_health_reports_an_open_canary_and_who_it_blames(game, capsys):
    (game / "mods" / "_health.json").write_text(json.dumps({
        "version": 1,
        "canary": {"open": True, "step": "per_mod:crashy", "session": "ab12"},
        "mods": {
            "crashy": {"crashes": 2, "last_error": "lua error", "disabled": False,
                       "disabled_reason": ""},
            "fine": {"crashes": 0, "last_error": "", "disabled": False,
                     "disabled_reason": ""},
        },
    }))
    assert json_bridge.cmd_loader_health() == 0
    out = _emit_json(capsys)
    assert out["canary"]["blamedMod"] == "crashy"
    assert out["threshold"] == 3
    # A clean mod is the normal case and would bury the ones that crashed.
    assert [m["id"] for m in out["mods"]] == ["crashy"]


def test_a_crash_before_any_mod_ran_blames_nobody(game, capsys):
    (game / "mods" / "_health.json").write_text(json.dumps({
        "version": 1,
        "canary": {"open": True, "step": "boot", "session": "ab12"},
        "mods": {},
    }))
    assert json_bridge.cmd_loader_health() == 0
    assert _emit_json(capsys)["canary"]["blamedMod"] is None


def test_a_closed_canary_is_not_a_signal(game, capsys):
    (game / "mods" / "_health.json").write_text(json.dumps({
        "version": 1,
        "canary": {"open": False, "step": "boot_ok", "session": "ab12"},
        "mods": {},
    }))
    assert json_bridge.cmd_loader_health() == 0
    assert _emit_json(capsys)["canary"] is None


def test_no_health_file_reads_as_absent(game, capsys):
    assert json_bridge.cmd_loader_health() == 0
    out = _emit_json(capsys)
    assert out["exists"] is False
    assert out["mods"] == []


def test_reset_clears_the_quarantine(game, capsys):
    (game / "mods" / "_health.json").write_text(json.dumps({
        "version": 1,
        "canary": {"open": False, "step": "boot_ok", "session": "ab12"},
        "mods": {"crashy": {"crashes": 3, "last_error": "boom", "disabled": True,
                            "disabled_reason": "failed to boot 3 times in a row"}},
    }))
    assert json_bridge.cmd_loader_health_reset("crashy") == 0
    capsys.readouterr()
    assert json_bridge.cmd_loader_health() == 0
    assert _emit_json(capsys)["mods"] == []
    # The canary node belongs to the loader and must survive a CLI write.
    doc = json.loads((game / "mods" / "_health.json").read_text())
    assert doc["canary"]["step"] == "boot_ok"
