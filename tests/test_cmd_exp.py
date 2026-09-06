"""`rsmm exp` — the playtest readout.

A playtest is the expensive step in this project: a human plays the game and a
later session reads the result. `R.exp` exists so one run answers N hypotheses
instead of one, and this module is the half that reads them back.

Two contracts meet here, both across a language boundary. Lua WRITES verdicts
into the mod's kv state file; Python PARSES them. A change on either side that
breaks the other should fail here, not by silently reporting "no data" after a
run that actually measured something.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from rsmm.cli import cmd_exp

REPO = Path(__file__).resolve().parent.parent


def _install(root: Path, mod_id: str, state: str) -> Path:
    d = root / "mods" / mod_id
    d.mkdir(parents=True, exist_ok=True)
    (d / ".rsmm_state").write_text(state, encoding="utf-8")
    return d


STATE = (
    "n\texp._session\t1700000000\n"
    "s\texp.tile_registered.q\tdoes the pool take a mod tile?\n"
    "b\texp.tile_registered.pass\t1\n"
    "s\texp.tile_registered.why\t245 tiledefs\n"
    "n\texp.tile_registered.at\t1700000005\n"
    "n\texp.tile_registered.o.tiledefs\t245\n"
    "s\texp.tile_placed.q\tis a mod tile ever placed?\n"
    "b\texp.tile_placed.pass\t0\n"
    "s\texp.tile_placed.why\tno placement in 3 generations\n"
    "s\texp.seen.q\tdid anyone see it?\n"
)


def test_read_cases_splits_verdicts_evidence_and_open_cases(tmp_path):
    d = _install(tmp_path, "poi", STATE)
    by_id = {c["id"]: c for c in cmd_exp.read_cases(d / ".rsmm_state")}

    assert by_id["tile_registered"]["status"] == cmd_exp.PASS
    assert by_id["tile_registered"]["why"] == "245 tiledefs"
    assert by_id["tile_registered"]["question"] == "does the pool take a mod tile?"
    assert by_id["tile_registered"]["observations"] == {"tiledefs": 245}

    assert by_id["tile_placed"]["status"] == cmd_exp.FAIL

    # The whole point of declaring up front: a case that never resolved is
    # readable, and says the code path never ran. Dropping it would make an
    # unrun measurement indistinguishable from one that was never written.
    assert by_id["seen"]["status"] == cmd_exp.NODATA
    assert by_id["seen"]["question"] == "did anyone see it?"


def test_the_session_stamp_is_not_a_case(tmp_path):
    d = _install(tmp_path, "poi", STATE)
    assert "_session" not in {c["id"] for c in cmd_exp.read_cases(d / ".rsmm_state")}
    [rec] = cmd_exp.discover(tmp_path)
    assert rec["session"] == 1700000000


def test_discover_skips_mods_with_no_results(tmp_path):
    _install(tmp_path, "poi", STATE)
    # A mod using R.kv for something else entirely must not appear as an empty
    # experiment: `rsmm exp` would then list most of the user's mods.
    _install(tmp_path, "meter", "n\tkills\t7\n")
    assert [r["modId"] for r in cmd_exp.discover(tmp_path)] == ["poi"]


def test_a_missing_or_unreadable_state_file_is_not_an_error(tmp_path):
    (tmp_path / "mods" / "empty").mkdir(parents=True)
    assert cmd_exp.discover(tmp_path) == []
    assert cmd_exp.read_cases(tmp_path / "nope" / ".rsmm_state") == []


def test_main_exit_code_answers_no_only_on_a_fail(tmp_path, capsys):
    _install(tmp_path, "poi", STATE)
    assert cmd_exp.main(["--game-dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "tile_registered" in out and "PASS" in out
    assert "FAIL" in out
    assert "declared, never resolved" in out
    # A count reads as a count. parse_kv hands back every `n` line as a float,
    # so an unformatted observation prints "245.0" in the one place a reader is
    # scanning for a number.
    assert "245.0" not in out and "= 245" in out

    # NO-DATA on its own is not a failed hypothesis — nothing was measured.
    _install(tmp_path, "poi", "s\texp.seen.q\tdid anyone see it?\n")
    assert cmd_exp.main(["--game-dir", str(tmp_path)]) == 0


def test_main_with_no_results_explains_instead_of_printing_nothing(tmp_path, capsys):
    (tmp_path / "mods").mkdir()
    assert cmd_exp.main(["--game-dir", str(tmp_path)]) == 0
    assert "R.exp" in capsys.readouterr().out


def test_json_output_is_machine_readable(tmp_path, capsys):
    import json
    _install(tmp_path, "poi", STATE)
    cmd_exp.main(["--game-dir", str(tmp_path), "--json"])
    [rec] = json.loads(capsys.readouterr().out)
    assert rec["modId"] == "poi"
    assert {c["id"] for c in rec["cases"]} == {"tile_registered", "tile_placed", "seen"}


def _lua_bin() -> str | None:
    for name in ("lua5.4", "lua54", "lua"):
        found = shutil.which(name)
        if found:
            return found
    return None


def test_cases_survive_the_real_lua_writer(tmp_path):
    """Parse the exact bytes `R.exp` produced, not a hand-written imitation.

    The Lua side escapes keys and values on the way out and this module
    unescapes them on the way in. Two implementations of one format in two
    languages drift silently: the failure is `rsmm exp` reporting "no data"
    after a playtest that measured everything asked of it, which costs a
    whole run to notice.

    rsmm_spec.lua runs the real R.exp against the real R.kv serializer and,
    with RSMM_SPEC_STATE_OUT set, dumps the resulting state file here.
    """
    lua = _lua_bin()
    if lua is None:
        pytest.skip("no standalone lua interpreter on PATH (lua5.4/lua)")
    dump = tmp_path / "state"
    env = {**os.environ, "RSMM_SPEC_STATE_OUT": str(dump)}
    proc = subprocess.run(
        [lua, str(REPO / "tests" / "lua" / "rsmm_spec.lua"),
         str(REPO / "src" / "loader" / "lib")],
        capture_output=True, text=True, cwd=str(REPO), env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert dump.exists(), "the spec did not dump its state file"

    by_id = {c["id"]: c for c in cmd_exp.read_cases(dump)}
    assert by_id["sync_pass"]["status"] == cmd_exp.PASS
    assert by_id["sync_pass"]["observations"] == {"n": 245}
    assert by_id["sync_pass"]["question"] == "does a synchronous case close?"
    assert by_id["boom"]["status"] == cmd_exp.FAIL
    assert "probe blew up" in by_id["boom"]["why"]
    assert by_id["never_ran"]["status"] == cmd_exp.NODATA


# --- manifest-declared questions --------------------------------------------
#
# A mod with no Lua (a texture override, a field patch) still has something it
# wants a playtest to answer. Declaring it in the manifest is what puts the
# question on the table BEFORE the run, which is the only point at which it can
# still be changed.

MANIFEST = """
[mod]
id = "icons"
name = "Icons"
enabled = true

[[experiment]]
id = "icon_replaced"
question = "do teleporter minimap icons become the shrine icon?"
"""


def _declare(root: Path, mod_id: str = "icons", manifest: str = MANIFEST) -> Path:
    d = root / "mods" / mod_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.toml").write_text(manifest, encoding="utf-8")
    return d


def test_a_mod_with_no_lua_still_shows_its_questions(tmp_path):
    _declare(tmp_path)
    [rec] = cmd_exp.discover(tmp_path)
    [case] = rec["cases"]
    assert case["id"] == "icon_replaced"
    assert case["status"] == cmd_exp.NODATA
    assert case["question"].startswith("do teleporter")


@pytest.mark.parametrize(
    ("raw", "needle"),
    [
        ({"id": "a"}, "must be a list"),
        (["not a table"], "is not a table"),
        ([{"question": "q"}], "has no `id`"),
        ([{"id": "a"}], "has no `question`"),
        ([{"id": "a.b", "question": "q"}], "may not contain"),
        ([{"id": "a", "question": "q"}, {"id": "a", "question": "r"}],
         "duplicate experiment id"),
        ([{"id": str(i), "question": "q"} for i in range(cmd_exp.MAX_CASES + 1)],
         "too many"),
    ],
)
def test_malformed_declarations_are_rejected(raw, needle):
    with pytest.raises(cmd_exp.ExpError) as e:
        cmd_exp.parse_declarations(raw, mod_id="m")
    assert needle in str(e.value)


def test_a_broken_manifest_does_not_hide_everyone_elses_results(tmp_path):
    _declare(tmp_path, "broken", "[mod]\nid='broken'\n[[experiment]]\nid='x'\n")
    _install(tmp_path, "poi", STATE)
    # Reported by `rsmm lint`, which is where an author looks. Refusing to print
    # any results because one manifest is malformed would be the worse trade.
    assert [r["modId"] for r in cmd_exp.discover(tmp_path)] == ["poi"]


# --- verdicts a person observed ---------------------------------------------


def test_answer_records_a_human_verdict_and_says_so(tmp_path, capsys):
    _declare(tmp_path)
    assert cmd_exp.main(["answer", "icons", "icon_replaced", "pass",
                         "-m", "shrine icon on every teleporter",
                         "--game-dir", str(tmp_path)]) == 0
    capsys.readouterr()

    [rec] = cmd_exp.discover(tmp_path)
    [case] = rec["cases"]
    assert case["status"] == cmd_exp.PASS
    assert case["by"] == cmd_exp.BY_HUMAN
    # The manifest's wording survives — the author phrased the question, the
    # player only answered it.
    assert case["question"].startswith("do teleporter")

    cmd_exp.main(["--game-dir", str(tmp_path)])
    assert "reported by you" in capsys.readouterr().out


def test_answer_preserves_the_rest_of_the_mods_state(tmp_path):
    """The state file is also the mod's R.kv counters and its overlay rows."""
    _declare(tmp_path)
    (tmp_path / "mods" / "icons" / ".rsmm_state").write_text(
        "n\truns_played\t7\ns\toverlay.rows\t[]\n", encoding="utf-8"
    )
    cmd_exp.answer(tmp_path, "icons", "icon_replaced", False, "nothing changed")
    from rsmm.cli.cmd_overlay import parse_kv
    store = parse_kv((tmp_path / "mods" / "icons" / ".rsmm_state").read_text())
    assert store["runs_played"] == 7
    assert store["overlay.rows"] == "[]"
    assert store["exp.icon_replaced.pass"] is False


def test_answer_round_trips_through_the_lua_codec(tmp_path):
    """A typed verdict has to survive the mod's NEXT launch reading the file.

    The escaping is the trap: a tab or newline in the reason would split the
    line format and silently truncate the store the loader reads back.
    """
    _declare(tmp_path)
    messy = "saw it\ton the\nsecond run \\ maybe"
    cmd_exp.answer(tmp_path, "icons", "icon_replaced", True, messy)
    [rec] = cmd_exp.discover(tmp_path)
    assert rec["cases"][0]["why"] == messy


def test_answer_refuses_an_unknown_mod_or_a_dotted_case_id(tmp_path, capsys):
    _declare(tmp_path)
    assert cmd_exp.main(["answer", "nope", "c", "pass",
                         "--game-dir", str(tmp_path)]) == 1
    assert "no installed mod" in capsys.readouterr().out
    with pytest.raises(cmd_exp.ExpError):
        cmd_exp.answer(tmp_path, "icons", "a.b", True)
