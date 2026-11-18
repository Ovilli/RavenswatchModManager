"""`rsmm.cli.editor.tomlblock`: one manifest block written back, every line the
edit did not touch kept as it was (comments, alignment, inline layout)."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path

import pytest

from rsmm.cli.editor import tomlblock as T

REPO = Path(__file__).resolve().parents[1]

MANIFEST = '''[mod]
id      = "m"
enabled = true

# The hero, by hand.
[[content]]
kind        = "hero"
id          = "Nyx"
name        = "Nyx"   # shown in game

[content.frame]
rig      = "Hero_Kintaro"
mesh     = "Characters\\\\Heroes\\\\Kintaro\\\\Kintaro_GEO.fbx"   # the boy, not the bear

# --- cards ---
[content.frame.ultimates."Ultimate Power 1"]
title = "Fall"

[content.frame.abilities.power]
cooldown = 6
# hits, one per line
hits     = [
    { at = 0.45, radius = 3.5, damage = 350 },
    { at = 0.9, radius = 5, damage = 100 },
]
indicator = { radius = 3, color = [0.5, 0.9, 0.3, 1] }

[content.frame.abilities.attack]
combo = [ { clip = "a", hit_at = 0.3, hits = [ { radius = 2 } ] }, { clip = "b", hit_at = 0.3 } ]

[[content.frame.talents]]
name  = "Attack One"   # first
title = "One"

[[content.frame.talents]]
name  = "Power Two"
title = "Two"

[[content.memoirs]]
title = "Page"
text  = "Once."


# Another block, with its own comment.
[[content]]
kind = "item"
id   = "x"
'''


def _hero(text: str) -> dict:
    return next(c for c in tomllib.loads(text)["content"] if c["kind"] == "hero")


def _edit(fn) -> tuple[str, dict]:
    b = copy.deepcopy(_hero(MANIFEST))
    fn(b)
    return T.set_block(MANIFEST, "hero", "Nyx", b), b


def test_an_unchanged_block_is_written_back_byte_for_byte():
    assert T.set_block(MANIFEST, "hero", "Nyx", _hero(MANIFEST)) == MANIFEST


@pytest.mark.parametrize("path", sorted(
    p.relative_to(REPO).as_posix() for p in REPO.glob("examples/**/manifest.toml")))
def test_every_example_block_round_trips(path):
    text = (REPO / path).read_text(encoding="utf-8")
    seen = set()
    for b in tomllib.loads(text).get("content", []):
        key = (b.get("kind"), b.get("id"))
        if not b.get("id") or key in seen:
            continue
        seen.add(key)
        assert T.set_block(text, b["kind"], b["id"], copy.deepcopy(b)) == text, key


def test_a_changed_key_is_rewritten_in_place_and_nothing_else_moves():
    out, b = _edit(lambda b: b["frame"]["abilities"]["power"].update(cooldown=7))
    assert _hero(out) == b
    changed = [(x, y) for x, y in zip(MANIFEST.splitlines(), out.splitlines(), strict=True)
               if x != y]
    assert changed == [("cooldown = 6", "cooldown = 7")]


def test_a_rewritten_key_keeps_its_alignment_and_its_comment():
    out, _ = _edit(lambda b: b["frame"].update(mesh="Characters\\Heroes\\X\\X_GEO.fbx"))
    assert 'mesh     = "Characters\\\\Heroes\\\\X\\\\X_GEO.fbx"   # the boy, not the bear' in out
    out, _ = _edit(lambda b: b["frame"]["abilities"]["power"].update(charges=2))
    assert "\ncharges  = 2\n" in out     # added after the last key, aligned like its section


def test_removed_keys_and_tables_go_with_nothing_else():
    def drop(b):
        del b["frame"]["abilities"]["power"]["indicator"]
        del b["frame"]["ultimates"]
    out, b = _edit(drop)
    assert _hero(out) == b
    assert "indicator" not in out and "Ultimate Power 1" not in out
    assert "# hits, one per line" in out and "# The hero, by hand." in out


def test_talents_are_matched_by_name_so_one_edit_keeps_the_others_lines():
    def edit(b):
        ts = b["frame"]["talents"]
        ts[1]["title"] = "Deux"
        ts.insert(1, {"name": "Special New", "title": "New"})
    out, b = _edit(edit)
    assert _hero(out) == b
    assert 'name  = "Attack One"   # first' in out            # untouched element, verbatim
    assert 'title = "Deux"' in out                            # patched in place, aligned
    assert out.index("Special New") < out.index("Power Two")  # in the new order


def test_a_key_written_inline_stays_inline_and_a_new_table_gets_a_header():
    def edit(b):
        b["frame"]["abilities"]["attack"]["combo"][0]["hit_at"] = 0.25
        b["frame"]["abilities"]["dash"] = {"clip": "anim:Dash", "intangible": 0.3}
        b["frame"]["effects"] = {"Glow": {"layers": [{"light": 3, "burst": 1}]}}
    out, b = _edit(edit)
    assert _hero(out) == b
    assert "\ncombo = [" in out and "[[content.frame.abilities.attack.combo]]" not in out
    assert "[content.frame.abilities.dash]" in out and "[content.frame.effects.Glow]" in out
    # a new table sits with its parent's others, before the memoirs
    assert out.index("[content.frame.abilities.dash]") < out.index("[[content.memoirs]]")


def test_a_bool_is_never_taken_for_a_number():
    text = '[[content]]\nkind = "hero"\nid = "A"\nflag = 1\n'
    out = T.set_block(text, "hero", "A", {"kind": "hero", "id": "A", "flag": True})
    assert tomllib.loads(out)["content"][0]["flag"] is True


def test_the_blank_lines_and_the_next_blocks_comment_stay():
    out, _ = _edit(lambda b: b.update(name="Nyx!"))
    assert '\n\n\n# Another block, with its own comment.\n[[content]]\nkind = "item"' in out


def test_add_and_find_refuse_what_they_cannot_do_cleanly():
    with pytest.raises(T.BlockError, match="already has"):
        T.add_block(MANIFEST, {"kind": "hero", "id": "Nyx"})
    with pytest.raises(T.BlockError, match="no hero block"):
        T.set_block(MANIFEST, "hero", "Nope", {"kind": "hero", "id": "Nope"})
    new = T.add_block(MANIFEST, {"kind": "hero", "id": "B", "frame": {
        "rig": "Hero_Juliet", "abilities": {"power": {"clip": "c", "hits": [{"at": 0.1}]}}}})
    assert tomllib.loads(new)["content"][-1]["frame"]["abilities"]["power"]["clip"] == "c"
    assert "[content.frame.abilities.power]" in new


def test_a_renamed_block_keeps_its_place():
    out, _ = _edit(lambda b: b.update(id="Vex"))
    assert [c["id"] for c in tomllib.loads(out)["content"]] == ["Vex", "x"]
