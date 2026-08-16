"""`rsmm overlay` — mod-declared HUDs.

Two contracts meet here and both cross a language boundary: a mod DECLARES the
shape in TOML, and its Lua PUBLISHES rows into the kv state file this module
parses. A change on either side that breaks the other should fail here, not in
a co-op session with an empty overlay on screen.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from rsmm.cli import cmd_overlay

SPEC = """
[mod]
id = "meter"
name = "Meter"
enabled = true

[overlay]
title = "Damage"
icon = "swords"
sort = { key = "dealt", dir = "desc" }
highlight = "mine"
empty = "Waiting for a run."

[[overlay.columns]]
key = "label"
label = "Player"
type = "text"

[[overlay.columns]]
key = "dealt"
label = "Damage"
type = "number"
format = "compact"

[[overlay.columns]]
key = "share"
type = "bar"
"""

ROWS = [
    {"label": "Ada", "dealt": 31904, "share": 0.38, "mine": False},
    {"label": "You", "dealt": 48210, "share": 0.57, "mine": True},
]


@pytest.fixture(autouse=True)
def _isolated_library(tmp_path, monkeypatch):
    """Point the AUTHORING tree at an empty dir.

    `discover` also scans `RSMM_MODS_DIR` so an unapplied mod's overlay still
    shows up in the client; without this the repo's own `mods/` would leak into
    every assertion here. Env var, never `setattr` on paths.MODS_DIR — that
    permanently shadows the lazy attribute (see tests/conftest.py).
    """
    empty = tmp_path / "library"
    empty.mkdir()
    monkeypatch.setenv("RSMM_MODS_DIR", str(empty))


def _install(root, *, mod_id="meter", spec=SPEC, rows=ROWS, meta=None, updated=None):
    d = root / "mods" / mod_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.toml").write_text(spec, encoding="utf-8")
    if rows is not None:
        payload = json.dumps(rows, separators=(",", ":"))
        state = f"s\toverlay.rows\t{payload}\n"
        state += f"s\toverlay.meta\t{json.dumps(meta or {}, separators=(',', ':'))}\n"
        state += f"n\toverlay.updated\t{updated or int(time.time())}\n"
        (d / ".rsmm_state").write_text(state, encoding="utf-8")
    return d


def test_parse_spec_normalises_defaults():
    spec = cmd_overlay.parse_spec(
        {"columns": [{"key": "a"}]},
        mod_id="m",
    )
    assert spec["title"] == "m"
    assert spec["icon"] == "list"
    assert spec["sort"] is None
    assert spec["columns"] == [
        {"key": "a", "label": "a", "type": "text", "format": "plain", "suffix": ""}
    ]


@pytest.mark.parametrize(
    ("raw", "needle"),
    [
        ({}, "at least one column"),
        ({"columns": []}, "at least one column"),
        ({"columns": [{}]}, "has no `key`"),
        ({"columns": [{"key": "a", "type": "sparkline"}]}, "unknown type"),
        ({"columns": [{"key": "a", "format": "hex"}]}, "unknown format"),
        ({"columns": [{"key": "a"}], "sort": {"key": "b"}}, "not one of the columns"),
        ({"columns": [{"key": "a"}], "sort": {"key": "a", "dir": "up"}}, "'asc' or 'desc'"),
        ({"columns": [{"key": "a"}], "icon": "unicorn"}, "not available"),
        ({"columns": [{"key": str(i)} for i in range(9)]}, "max 8"),
    ],
)
def test_parse_spec_rejects_malformed_declarations(raw, needle):
    with pytest.raises(cmd_overlay.OverlayError) as e:
        cmd_overlay.parse_spec(raw, mod_id="m")
    assert needle in str(e.value)


def test_discover_joins_declaration_with_live_rows(tmp_path):
    _install(tmp_path, meta={"total": 84169})
    [record] = cmd_overlay.discover(tmp_path)
    assert record["modId"] == "meter"
    assert record["title"] == "Damage"
    assert record["exists"] is True
    assert record["meta"] == {"total": 84169}
    # Sorted by the declared key, descending — the client renders the order it
    # is given rather than re-deriving it.
    assert [r["label"] for r in record["rows"]] == ["You", "Ada"]


def test_discover_reports_a_broken_declaration_instead_of_hiding_it(tmp_path):
    _install(tmp_path, spec=SPEC.replace('type = "bar"', 'type = "sparkline"'))
    [record] = cmd_overlay.discover(tmp_path)
    assert "unknown type" in record["error"]
    assert record["rows"] == []


def test_discover_skips_mods_without_a_declaration(tmp_path):
    d = tmp_path / "mods" / "plain"
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text('[mod]\nid = "plain"\n', encoding="utf-8")
    assert cmd_overlay.discover(tmp_path) == []


def test_declared_but_never_published_is_idle_not_broken(tmp_path):
    _install(tmp_path, rows=None)
    [record] = cmd_overlay.discover(tmp_path)
    assert record["exists"] is False
    assert record["rows"] == []
    assert record["error"] is None if "error" in record else True


def test_row_payload_survives_the_lua_writer_format(tmp_path):
    """The kv file is written by Lua; parse the exact bytes it produces."""
    d = tmp_path / "mods" / "meter"
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text(SPEC, encoding="utf-8")
    # Tab-delimited, one record per line. A tab inside a value is escaped
    # TWICE on the way out — once by the JSON encoder (tab -> \t) and once by
    # R.kv, which escapes that backslash (\ -> \\) so the tab-delimited line
    # format survives. The file therefore holds `A\\tB`, and a reader that
    # unescapes only one layer gets invalid JSON and an empty overlay.
    (d / ".rsmm_state").write_text(
        's\toverlay.rows\t[{"dealt":10,"label":"A\\\\tB","share":0.5}]\n'
        's\toverlay.meta\t{"total":10}\n'
        "n\toverlay.updated\t1700000000\n",
        encoding="utf-8",
    )
    [record] = cmd_overlay.discover(tmp_path)
    assert record["rows"][0]["label"] == "A\tB"
    assert record["updated"] == 1700000000


def test_garbage_rows_degrade_to_empty_rather_than_raising(tmp_path):
    d = _install(tmp_path)
    (d / ".rsmm_state").write_text("s\toverlay.rows\tnot json\n", encoding="utf-8")
    [record] = cmd_overlay.discover(tmp_path)
    assert record["exists"] is False


def test_render_lays_out_the_declared_columns(tmp_path):
    _install(tmp_path, meta={"total": 84169})
    [record] = cmd_overlay.discover(tmp_path)
    out = "\n".join(cmd_overlay.render(record))
    assert "Damage" in out
    assert "Player" in out          # the declared column label
    assert "48k" in out             # compact format applied
    assert "total 84169" in out


def test_main_lists_then_shows(tmp_path, capsys):
    _install(tmp_path)
    assert cmd_overlay.main(["--game-dir", str(tmp_path)]) == 0
    assert "meter" in capsys.readouterr().out
    assert cmd_overlay.main(["meter", "--game-dir", str(tmp_path)]) == 0
    assert "Player" in capsys.readouterr().out


def test_main_unknown_mod_is_an_error(tmp_path, capsys):
    _install(tmp_path)
    assert cmd_overlay.main(["nope", "--game-dir", str(tmp_path)]) == 1
    assert "declares an [overlay]" in capsys.readouterr().out


def test_main_json(tmp_path, capsys):
    _install(tmp_path)
    assert cmd_overlay.main(["meter", "--game-dir", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["columns"][0]["key"] == "label"


def test_piped_output_carries_no_ansi(tmp_path):
    """Style() decides colour from the stream, so a redirect must be plain."""
    _install(tmp_path)
    # No check=True: it raises CalledProcessError carrying only the exit
    # status, so a CI failure here reported "returned non-zero exit status 1"
    # and threw away the traceback that said why. Assert on the code and put
    # stderr in the message instead.
    #
    # RSMM_MODS_DIR is pinned for the same reason the in-process tests pin it:
    # a bare subprocess inherits the developer's real `mods/`, which exists
    # locally and not on a fresh checkout, so this test would otherwise pass
    # and fail for reasons that have nothing to do with what it checks.
    env = {**os.environ, "RSMM_MODS_DIR": str(tmp_path / "library")}
    proc = subprocess.run(
        [sys.executable, "-m", "rsmm.cli.cmd_overlay", "meter", "--game-dir", str(tmp_path)],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, f"exit {proc.returncode}\n{proc.stderr}"
    assert "\033" not in proc.stdout


def test_an_unapplied_mod_still_lists_its_overlay(tmp_path, monkeypatch):
    """Dev loop: the declaration exists in the authoring tree before `apply`.

    The desktop app in dev mode points at the repo's `mods/`, so a mod whose
    manifest has just gained an `[overlay]` block must be listed — with no
    rows, because only the installed tree is ever written to by the loader.
    """
    library = tmp_path / "library"
    _install(library, mod_id="meter")           # authoring tree only
    monkeypatch.setenv("RSMM_MODS_DIR", str(library / "mods"))
    game = tmp_path / "game"
    (game / "mods").mkdir(parents=True)

    [record] = cmd_overlay.discover(game)
    assert record["source"] == "library"
    assert record["title"] == "Damage"
    assert record["rows"] == []                  # nothing published yet
    assert record["exists"] is False


def test_the_installed_copy_wins_over_the_authoring_one(tmp_path, monkeypatch):
    library = tmp_path / "library"
    _install(library, mod_id="meter", spec=SPEC.replace('title = "Damage"',
                                                        'title = "Old title"'))
    monkeypatch.setenv("RSMM_MODS_DIR", str(library / "mods"))
    game = tmp_path / "game"
    _install(game, mod_id="meter")

    [record] = cmd_overlay.discover(game)
    assert record["source"] == "game"
    assert record["title"] == "Damage"           # the installed manifest
    assert record["exists"] is True              # and its rows
