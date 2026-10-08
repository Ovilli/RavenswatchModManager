"""Whole-file overrides a `[[patch]]` / `[[content]]` block could replace.

A block is only offered when it is proven: parsed back as TOML and run through
the code apply uses, it must rebuild the mod's file byte for byte. These tests
pin both halves — the offer when it is exact, and silence when it is not.
"""

from __future__ import annotations

import struct
import tomllib
from pathlib import Path

import pytest

from rsmm.cli import doctor
from rsmm.cli import lint as L
from rsmm.cli import patch_suggest as P
from rsmm.engine import corpus
from rsmm.engine import talent_values as TV
from rsmm.engine.stat_schemas import MARK_BEGIN, MARK_END

STAT = ("GlobalValues/Avalon/Mordred_Quest/Mordred_Quest_Boss_Is_Dead"
        ".globalvalue.ot.GlobalEntityValueSettings.gen")
OT = "_root/DarkTalesResources/ApplicationSettings.ot"
WUKONG = ("EntitySettings/Heroes/Hero_SunWukong/"
          "Hero_SunWukong.entity.ot.EntitySettingsResource.gen")
WUKONG_MOD = (Path(__file__).resolve().parent.parent / "docs/ExampleMods/mods-archive"
              / "WukongFasterQuest/assets" / WUKONG)
#: What WukongFasterQuest changes, as (label, vanilla, modded).
WUKONG_EDITS = (
    ("Skill Passive Objects Quest Objective Count", 7, 5),
    ("Skill Trait Awakened Objective Count", 8, 6),
    ("Skill Passive Objects Quest DMG Per Object", 2.0, 3.0),
)

OT_TEXT = "\n".join([
    "//OPROJECT oCTextSaver",
    "SingleObject0=C30",
    "{",
    "m_oDefaultValue=C6",
    "{",
    "f|_GrabFloatValue()=0",
    "}",
    "s|m_sLabel=Merlin DMG Zone",
    "f|m_fFactor=0.5",
    "i|m_eComputerType=3",
    "}",
    "",
])


def _global_float(value: float, tail: bytes = b"\x00" * 7) -> bytes:
    """A cooked float global: header, BEGIN, the 23-byte tagged-union body, END."""
    body = struct.pack("<III", 3, 0, 0) + struct.pack("<f", value) + tail
    return b"HDR" + MARK_BEGIN + body + MARK_END + b"TRL"


@pytest.fixture
def mirror(tmp_path, monkeypatch):
    """A vanilla corpus the test controls, and no game install."""
    root = tmp_path / "uncooked"
    root.mkdir()
    monkeypatch.setattr(corpus, "UNCOOKED", root)
    monkeypatch.setenv("RSMM_GAME_DIR", str(tmp_path / "no-game"))

    def put(rel: str, data: bytes) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return put


def _mod(root: Path, files: dict[str, bytes], extra: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.toml").write_text(
        f'[mod]\nid = "{root.name}"\nversion = "1.0.0"\n{extra}', encoding="utf-8")
    for rel, data in files.items():
        p = root / "assets" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


# --- stat ----------------------------------------------------------------------

def test_stat_override_becomes_the_exact_patch(mirror):
    mirror(STAT, _global_float(1.0))
    s = P.suggest_file(STAT, _global_float(0.1))
    assert s is not None and s.route == "stat" and s.exact
    block = tomllib.loads(s.toml)["patch"][0]
    assert block == {"kind": "stat", "name": "Mordred_Quest_Boss_Is_Dead", "value": 0.1}


def test_stat_override_with_other_bytes_changed_gets_no_offer(mirror):
    mirror(STAT, _global_float(1.0))
    assert P.suggest_file(STAT, _global_float(0.1, tail=b"\x01" * 7)) is None


def test_without_the_game_copy_only_the_route_is_named(mirror):
    s = P.suggest_file(STAT, _global_float(0.1))
    assert s is not None and not s.exact and 'name = "Mordred_Quest_Boss_Is_Dead"' in s.note


# --- ot ------------------------------------------------------------------------

def _game_with_ot(tmp_path: Path, text: str) -> Path:
    game = tmp_path / "game"
    p = game / "DarkTalesResources" / "ApplicationSettings.ot"
    p.parent.mkdir(parents=True)
    p.write_text(text, encoding="utf-8", newline="")   # no CRLF on Windows: the mod side is LF
    return game


def test_ot_override_becomes_one_patch_per_changed_field(tmp_path):
    game = _game_with_ot(tmp_path, OT_TEXT)
    modded = OT_TEXT.replace("m_fFactor=0.5", "m_fFactor=0.25").replace(
        "m_eComputerType=3", "m_eComputerType=1")
    s = P.suggest_file(OT, modded.encode(), game_dir=game)
    assert s is not None and s.exact
    blocks = tomllib.loads(s.toml)["patch"]
    assert [(b["selector"], b["field"], b["value"]) for b in blocks] == [
        ("Merlin DMG Zone", "m_fFactor", 0.25),
        ("Merlin DMG Zone", "m_eComputerType", 1),
    ]
    assert all("file" not in b for b in blocks)      # the default file


def test_ot_override_that_adds_a_line_or_edits_an_unlabelled_block_is_left_alone(tmp_path):
    game = _game_with_ot(tmp_path, OT_TEXT)
    added = OT_TEXT.replace("i|m_eComputerType=3", "i|m_eComputerType=3\ni|m_eNew=1")
    nested = OT_TEXT.replace("_GrabFloatValue()=0", "_GrabFloatValue()=2")
    assert P.suggest_file(OT, added.encode(), game_dir=game) is None
    assert P.suggest_file(OT, nested.encode(), game_dir=game) is None


# --- talent --------------------------------------------------------------------

def _wukong_vanilla() -> bytes:
    data = WUKONG_MOD.read_bytes()
    for label, vanilla, _modded in WUKONG_EDITS:
        data = TV.set_talent_value(data, label, vanilla)
    return data


def test_hero_entity_value_edits_become_a_talent_block(mirror):
    mirror(WUKONG, _wukong_vanilla())
    s = P.suggest_file(WUKONG, WUKONG_MOD.read_bytes(), mod_id="WukongFasterQuest")
    assert s is not None and s.route == "talent" and s.exact
    block = tomllib.loads(s.toml)["content"][0]
    assert block["hero"] == "SunWukong" and block["file"] == "Hero_SunWukong.entity"
    assert sorted(map(tuple, block["value_patches"])) == sorted(
        (label, vanilla, modded) for label, vanilla, modded in WUKONG_EDITS)


def test_hero_entity_with_a_non_value_edit_gets_no_offer(mirror):
    mirror(WUKONG, _wukong_vanilla())
    cur = bytearray(WUKONG_MOD.read_bytes())
    cur[10] ^= 0xFF                               # outside any value node
    assert P.suggest_file(WUKONG, bytes(cur), mod_id="m") is None


# --- per mod -------------------------------------------------------------------

def test_files_the_mods_own_content_emitted_are_not_raw_overrides(mirror, tmp_path):
    mirror(WUKONG, _wukong_vanilla())
    mirror(STAT, _global_float(1.0))
    files = {WUKONG: WUKONG_MOD.read_bytes(), STAT: _global_float(0.1)}
    assert {s.route for s in P.suggest_for_mod(_mod(tmp_path / "raw", files))} == {
        "stat", "talent"}
    talent = '[[content]]\nkind = "talent"\nid = "x"\nhero = "SunWukong"\n'
    assert [s.route for s in P.suggest_for_mod(
        _mod(tmp_path / "declared", files, talent))] == ["stat"]
    marked = _mod(tmp_path / "marked", files)
    (marked / ".rsmm_emitted.json").write_text(f'["{STAT}"]', encoding="utf-8")
    assert [s.route for s in P.suggest_for_mod(marked)] == ["talent"]


def test_lint_prints_the_block_and_doctor_names_the_mod(mirror, tmp_path, monkeypatch,
                                                         capsys):
    mirror(STAT, _global_float(1.0))
    mods = tmp_path / "mods"
    entry = _mod(mods / "nudged", {STAT: _global_float(0.1)})
    assert L._lint_patchable("nudged", entry) == 1
    out = capsys.readouterr().out
    assert "whole-file override" in out and 'name = "Mordred_Quest_Boss_Is_Dead"' in out

    _mod(mods / "off", {STAT: _global_float(0.2)}, "enabled = false\n")
    monkeypatch.setattr(doctor, "MODS_DIR", mods)
    (r,) = doctor.check_raw_overrides()
    assert r.kind == "WARN" and r.label.startswith("nudged:")
    assert "rsmm lint nudged" in r.detail
