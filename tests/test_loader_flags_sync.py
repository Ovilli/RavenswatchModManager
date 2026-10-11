"""A mod's `loader_flags`: `apply` switches on what enabled mods need.

The camera mod needs hero capture; for every player who had not set it by hand
the mod saved slider changes and never applied one, and the app offered no
switch (bug report 2026-10-06). `apply` now keeps the flags file in step with
the enabled mods without touching the player's own flags.
"""

from __future__ import annotations

import json

from rsmm.engine import loader_flags as LF

HERO = "RSMM_ENABLE_HERO_CAPTURE"
UI = "RSMM_ENABLE_UI_HOOK"


def _file(tmp_path, names=None):
    p = tmp_path / LF.FLAGS_FILE
    if names is not None:
        p.write_text(json.dumps(names))
    return p


def _read(p):
    return json.loads(p.read_text()) if p.exists() else None


def test_hero_capture_is_a_flag_the_app_and_mods_can_switch_on():
    assert HERO in LF.SAFE_FLAG_NAMES
    assert "RSMM_ENABLE_ITEM_INJECT" not in LF.SAFE_FLAG_NAMES   # still locked


def test_a_mods_flag_is_added_and_the_players_kept(tmp_path):
    p = _file(tmp_path, [UI])
    new, added = LF.sync_mod_flags(p, {HERO}, set())
    assert _read(p) == sorted([UI, HERO]) == new
    assert added == {HERO}


def test_a_flag_only_a_disabled_mod_needed_goes_away(tmp_path):
    p = _file(tmp_path, [UI, HERO])
    _new, added = LF.sync_mod_flags(p, set(), {HERO})
    assert _read(p) == [UI] and added == set()


def test_the_players_own_flag_stays_when_no_mod_needs_it(tmp_path):
    p = _file(tmp_path, [HERO])                 # set by the player, not for a mod
    _new, added = LF.sync_mod_flags(p, set(), set())
    assert _read(p) == [HERO] and added == set()


def test_a_flag_the_player_also_set_is_not_recorded_as_the_mods(tmp_path):
    p = _file(tmp_path, [HERO])
    _new, added = LF.sync_mod_flags(p, {HERO}, set())
    assert added == set()                       # disabling the mod later keeps it


def test_unsafe_requests_are_ignored_and_unknown_player_flags_kept(tmp_path):
    p = _file(tmp_path, ["RSMM_SOMETHING_NEWER"])
    LF.sync_mod_flags(p, {"RSMM_ENABLE_ITEM_INJECT"}, set())
    assert _read(p) == ["RSMM_SOMETHING_NEWER"]


def test_nothing_needed_and_nothing_set_leaves_no_file(tmp_path):
    p = _file(tmp_path)
    LF.sync_mod_flags(p, set(), set())
    assert not p.exists()


def test_a_manifest_carries_its_loader_flags(tmp_path):
    from rsmm.cli.apply_mods import Mod
    (tmp_path / "manifest.toml").write_text(
        '[mod]\nid = "cam"\nloader_flags = ["RSMM_ENABLE_HERO_CAPTURE"]\n')
    assert Mod(tmp_path).loader_flags == [HERO]
