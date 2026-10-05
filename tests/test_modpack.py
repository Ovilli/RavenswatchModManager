"""Identity of an install's applied mod set (`rsmm.engine.modpack`)."""

from __future__ import annotations

import json

import pytest

from rsmm.engine.modpack import (
    ID_LENGTH,
    applied_mod_ids,
    modpack_id,
    modpack_label,
    read_modpack,
)
from rsmm.engine.paths import COOKING_SUBDIR


def entry(sha: str) -> dict:
    return {"mod": "some-mod", "src_sha256": sha, "orig_sha256": "0" * 64}


A = "a" * 64
B = "b" * 64


def test_vanilla_install_has_no_id():
    assert modpack_id({}) is None


def test_id_is_short_hex():
    got = modpack_id({"path/one": entry(A)})
    assert got is not None
    assert len(got) == ID_LENGTH
    assert all(c in "0123456789abcdef" for c in got)


def test_same_applied_set_gives_the_same_id():
    first = {"path/one": entry(A), "path/two": entry(B)}
    second = {"path/one": entry(A), "path/two": entry(B)}
    assert modpack_id(first) == modpack_id(second)


def test_insertion_order_does_not_change_the_id():
    # `apply` walks mods in whatever order the directory yields, which differs
    # between machines that applied the very same set.
    forward = {"path/one": entry(A), "path/two": entry(B)}
    backward = {"path/two": entry(B), "path/one": entry(A)}
    assert modpack_id(forward) == modpack_id(backward)


def test_different_content_changes_the_id():
    # The case the fingerprint exists for: same mod, different bytes.
    assert modpack_id({"path/one": entry(A)}) != modpack_id({"path/one": entry(B)})


def test_different_path_changes_the_id():
    assert modpack_id({"path/one": entry(A)}) != modpack_id({"path/two": entry(A)})


def test_an_extra_override_changes_the_id():
    one = {"path/one": entry(A)}
    two = {"path/one": entry(A), "path/two": entry(B)}
    assert modpack_id(one) != modpack_id(two)


def test_mod_id_is_not_part_of_the_identity():
    # A renamed mod with identical content is the same pack: matching is about
    # bytes, not about what the author called the mod.
    named = {"path/one": {"mod": "one-name", "src_sha256": A}}
    renamed = {"path/one": {"mod": "another-name", "src_sha256": A}}
    assert modpack_id(named) == modpack_id(renamed)


def test_fields_cannot_be_shifted_across_the_separator():
    # Without a separator that cannot occur in either field, "ab" + "c" and
    # "a" + "bc" would hash the same.
    left = {"ab": {"src_sha256": "c"}}
    right = {"a": {"src_sha256": "bc"}}
    assert modpack_id(left) != modpack_id(right)


@pytest.mark.parametrize(
    "bad",
    [
        {"mod": "m", "src_sha1": A},          # pre-0.1.12 journal
        {"mod": "m"},                          # no digest at all
        {"mod": "m", "src_sha256": ""},        # empty digest
        {"mod": "m", "src_sha256": None},      # null digest
        {"mod": "m", "src_sha256": 12345},     # not a string
    ],
)
def test_an_unhashable_entry_makes_the_whole_id_unknown(bad):
    # Hashing the rest and calling it a fingerprint would claim two installs
    # match when this entry was never compared.
    assert modpack_id({"path/one": entry(A), "path/two": bad}) is None


def test_a_non_mapping_entry_makes_the_id_unknown():
    assert modpack_id({"path/one": "not-an-entry"}) is None


def test_label_is_none_without_mods():
    assert modpack_label([]) is None
    assert modpack_label(["", ""]) is None


def test_label_names_a_small_set_in_sorted_order():
    assert modpack_label(["beta", "alpha"]) == "alpha, beta"


def test_label_summarises_a_large_set():
    assert modpack_label(["e", "d", "c", "b", "a"]) == "a, b, c +2 more"


def test_label_deduplicates():
    assert modpack_label(["a", "a", "b"]) == "a, b"


def write_state(game_dir, data) -> None:
    cooking = game_dir / COOKING_SUBDIR
    cooking.mkdir(parents=True, exist_ok=True)
    (cooking / ".rsmm_state.json").write_text(json.dumps(data), encoding="utf-8")


def test_read_modpack_reads_id_and_label(tmp_path):
    write_state(tmp_path, {
        "version": 1,
        "active": {"path/one": {"mod": "my-mod", "src_sha256": A}},
        "enabled_mods": ["my-mod"],
    })

    pack = read_modpack(tmp_path)

    assert pack.id == modpack_id({"path/one": {"mod": "my-mod", "src_sha256": A}})
    assert pack.label == "my-mod"
    assert pack.status == "ok"
    assert pack.matchable


def test_label_describes_what_is_applied_not_what_is_enabled(tmp_path):
    # The post-`restore --all` install: every mod still enabled, nothing on
    # disk. Reporting those mods in the label while the id says vanilla told
    # the player two different things about the same install.
    write_state(tmp_path, {
        "version": 1,
        "active": {},
        "enabled_mods": ["one", "two", "three"],
    })

    pack = read_modpack(tmp_path)

    assert pack.status == "vanilla"
    assert pack.id is None
    assert pack.label is None


def test_label_names_the_mods_that_own_the_applied_files(tmp_path):
    write_state(tmp_path, {
        "version": 1,
        "active": {
            "path/one": {"mod": "b-mod", "src_sha256": A},
            "path/two": {"mod": "a-mod", "src_sha256": B},
            "path/three": {"mod": "a-mod", "src_sha256": A},
        },
        "enabled_mods": ["unrelated"],
    })

    assert read_modpack(tmp_path).label == "a-mod, b-mod"


def test_read_modpack_on_a_vanilla_install(tmp_path):
    write_state(tmp_path, {"version": 1, "active": {}, "enabled_mods": []})

    pack = read_modpack(tmp_path)

    assert pack.id is None
    assert pack.status == "vanilla"
    # A vanilla install matches other vanilla installs, so it is matchable.
    assert pack.matchable


def test_read_modpack_with_no_journal_at_all(tmp_path):
    # An install the manager never touched is vanilla, not unknown.
    pack = read_modpack(tmp_path)

    assert pack.status == "vanilla"
    assert pack.matchable


@pytest.mark.parametrize("corrupt", ["not json at all", "[]", '"a string"', "null"])
def test_read_modpack_on_a_corrupt_journal(tmp_path, corrupt):
    # Distinct from vanilla: something may well be applied, we just cannot say
    # what, and telling the player "vanilla" would be a lie.
    cooking = tmp_path / COOKING_SUBDIR
    cooking.mkdir(parents=True, exist_ok=True)
    (cooking / ".rsmm_state.json").write_text(corrupt, encoding="utf-8")

    pack = read_modpack(tmp_path)

    assert pack.id is None
    assert pack.status == "unknown"
    assert not pack.matchable


def test_read_modpack_reports_unknown_for_an_unhashable_journal(tmp_path):
    # A pre-0.1.12 journal: entries are there, but recorded with src_sha1.
    write_state(tmp_path, {
        "version": 1,
        "active": {"path/one": {"mod": "m", "src_sha1": A}},
        "enabled_mods": ["m"],
    })

    pack = read_modpack(tmp_path)

    assert pack.id is None
    assert pack.status == "unknown"
    assert not pack.matchable
    # The label still works, so the player can be told which mods are involved.
    assert pack.label == "m"


def test_read_modpack_tolerates_wrong_types_in_the_journal(tmp_path):
    # `active` a list: a shape the journal should never hold, which must not
    # raise on the launch path.
    write_state(tmp_path, {"active": ["nope"], "enabled_mods": "also-nope"})

    pack = read_modpack(tmp_path)

    assert pack.id is None
    assert pack.label is None


def test_a_bare_string_is_one_name_not_a_list_of_characters():
    # str is a Sequence, so an unguarded label renders "abc" as "a, b, c".
    assert modpack_label("abc") == "abc"
    assert modpack_label([]) is None


def test_applied_mod_ids_ignores_entries_with_no_usable_mod_id():
    active = {
        "p1": {"mod": "real", "src_sha256": A},
        "p2": {"mod": "", "src_sha256": A},
        "p3": {"src_sha256": A},
        "p4": {"mod": 42, "src_sha256": A},
        "p5": "not-a-mapping",
    }

    assert applied_mod_ids(active) == ["real"]


# --- client-only vs gameplay (rsmm.engine.mod_scope) --------------------------

def runtime_mod(game_dir, name: str, lua: str) -> None:
    d = game_dir / "mods" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.toml").write_text(f'[mod]\nid = "{name}"\nversion = "1.0.0"\n',
                                     encoding="utf-8")
    (d / "init.lua").write_text('local R = require "rsmm"\n' + lua, encoding="utf-8")


def test_a_lua_gameplay_mod_is_not_vanilla(tmp_path):
    # Before 2026-10-05 Lua mods never reached the fingerprint: an install
    # running a stat mod reported itself as vanilla.
    write_state(tmp_path, {"version": 1, "active": {}, "enabled_mods": ["sprint"]})
    runtime_mod(tmp_path, "sprint", 'R.stat.modify(h, "move_speed", 2)')

    pack = read_modpack(tmp_path)

    assert pack.status == "ok"
    assert pack.id is not None
    assert not pack.public_matchmaking_ok
    assert [m for m, _ in pack.gameplay] == ["sprint"]


def test_only_client_only_mods_is_matched_like_vanilla(tmp_path):
    from rsmm.engine.cipher import encode

    texture = encode("3D/X/T_A_ALB.tga.Texture.dxt")
    write_state(tmp_path, {"version": 1, "enabled_mods": [],
                           "active": {texture: {"mod": "skin", "src_sha256": A}}})
    runtime_mod(tmp_path, "damage-meter", "R.damage.enable()\nR.overlay.publish({})")

    pack = read_modpack(tmp_path)

    assert pack.status == "client-only"
    assert pack.id is None
    assert pack.matchable and pack.public_matchmaking_ok
    assert pack.client_only == ("damage-meter", "skin")


def test_client_only_mods_do_not_change_the_fingerprint(tmp_path):
    write_state(tmp_path, {"version": 1, "enabled_mods": [],
                           "active": {"path/one": {"mod": "m", "src_sha256": A}}})
    without = read_modpack(tmp_path).id
    runtime_mod(tmp_path, "damage-meter", "R.damage.enable()")

    assert read_modpack(tmp_path).id == without


def test_editing_a_gameplay_lua_mod_changes_the_fingerprint(tmp_path):
    write_state(tmp_path, {"version": 1, "active": {}, "enabled_mods": []})
    runtime_mod(tmp_path, "sprint", "R.stat.modify(h, 'move_speed', 2)")
    before = read_modpack(tmp_path).id
    runtime_mod(tmp_path, "sprint", "R.stat.modify(h, 'move_speed', 3)")

    assert read_modpack(tmp_path).id != before


def test_a_disabled_lua_mod_does_not_count(tmp_path):
    # `apply` keeps a disabled mod's manifest but removes its init.lua.
    write_state(tmp_path, {"version": 1, "active": {}, "enabled_mods": []})
    d = tmp_path / "mods" / "sprint"
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text('[mod]\nid = "sprint"\n', encoding="utf-8")

    assert read_modpack(tmp_path).status == "vanilla"
