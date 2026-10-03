"""`rsmm ability-editor`: the local page's server side."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from rsmm.cli.editor import abilities as AE
from rsmm.cli.editor import server as S
from rsmm.engine import corpus

needs = pytest.mark.skipif(
    corpus.read("EntitySettings/Heroes/Hero_Piper/Hero_Piper.entity.ot"
                ".EntitySettingsResource.gen") is None, reason="no hero corpus")


@needs
def test_the_graph_shows_parts_fields_and_the_links_between_them():
    d = AE.graph_payload("Piper", [])
    timer = next(c for c in d["components"] if c["name"] == "Primary Ability Shoot Timer")
    on_tick = next(f for f in timer["fields"] if f["name"] == "on_tick")
    ids = {c["id"] for c in d["components"]}
    assert on_tick["targets"] and on_tick["targets"][0] in ids
    assert d["error"] == "" and "Hero_Piper_FX" in d["entities"]


@needs
def test_steps_are_applied_and_checked_before_the_graph_is_drawn():
    d = AE.graph_payload("Piper", [{"clone": "Ability Secondary", "as": "Echo"}])
    assert any(c["group"] == "Echo" for c in d["components"]) and d["error"] == ""
    bad = AE.graph_payload("Piper", [{"clone": "Ability Secondary", "as": "K", "from": "Juliet"}])
    assert "Hero_Romeo_Juliet_Common" in bad["error"]


@needs
def test_a_changed_field_carries_the_value_it_replaced():
    d = AE.graph_payload("Piper", [{"set": "Primary Ability Shots Delay.value", "value": 0.2}])
    part = next(c for c in d["components"] if c["name"] == "Primary Ability Shots Delay")
    f = next(f for f in part["fields"] if f["name"] == "value")
    assert f["text"] == "f32 0.2" and f["was"] == "f32 0.05"
    assert all(g["was"] is None for c in d["components"] if c is not part for g in c["fields"])


def test_steps_render_as_manifest_toml():
    import tomllib
    steps = [{"set": "A.value", "value": 0.2}, {"link": "B.on_end", "to": ""}]
    assert tomllib.loads(AE.steps_toml(steps))["content"]["abilities"] == steps


def test_writes_need_the_token_and_every_request_a_loopback_host():
    srv = S.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/abilities"
    try:
        req = urllib.request.Request(base + "/api/graph", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 403
        req = urllib.request.Request(base + "/api/heroes", headers={"Host": "evil.example"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 403
        page = urllib.request.urlopen(base + "/").read().decode()
        assert srv.token in page and json.loads(urllib.request.urlopen(base + "/api/heroes").read())
    finally:
        srv.shutdown()
        srv.server_close()


@needs
def test_a_selectors_entry_number_can_be_set():
    """A projectile's stagger is the number in its `Stagger Power Selector`
    entry (Beowulf's fireball: 50, in the fireball's own file). The Numbers
    page lists it as `entries[0]`'s last literal and builds an edit to it."""
    ent = "Hero_Beowulf_Ultimate_2_Fireball"
    if ent not in AE._family("Beowulf"):
        pytest.skip("Beowulf's fireball file is not in this corpus")
    d = AE.graph_payload("Beowulf", [], ent)
    sel = next(c for c in d["components"] if c["name"] == "Stagger Power Selector")
    entries = next(f for f in sel["fields"] if f["name"] == "entries")
    assert entries["itemLits"] == [["bool True", "f32 50"]]
    step = {"set": "Stagger Power Selector.entries[0][1]", "value": 25, "entity": ent}
    d = AE.graph_payload("Beowulf", [step], ent)
    sel = next(c for c in d["components"] if c["name"] == "Stagger Power Selector")
    assert d["error"] == ""
    assert next(f for f in sel["fields"] if f["name"] == "entries")["itemLits"] == [
        ["bool True", "f32 25"]]


@needs
def test_search_finds_a_hit_value_in_the_heros_other_files():
    """The fireball's stagger is not in `Hero_Beowulf`: searching the hero's
    other files finds it, so the page can point there."""
    if "Hero_Beowulf_Ultimate_2_Fireball" not in AE._family("Beowulf"):
        pytest.skip("Beowulf's fireball file is not in this corpus")
    rows = AE.search("stagger", hero="Beowulf", skip="Hero_Beowulf")["rows"]
    assert any(r["entity"] == "Hero_Beowulf_Ultimate_2_Fireball"
               and r["part"] == "Stagger Power Selector" and r["value"] == "50" for r in rows)


def _req(tmp_path, **body):
    from types import SimpleNamespace
    return SimpleNamespace(body=body, ctx=SimpleNamespace(mods_dir=tmp_path))


_STEP = {"set": "Primary Ability Shots Delay.value", "value": 0.5}


@needs
def test_saving_into_a_new_mod_makes_it_like_the_other_tabs_do(tmp_path):
    """Save creates the mod from the same details form as the Items and Talents tabs
    (checked by the same rules), with the block the steps go into: by default an
    in-place edit of the shipped hero."""
    import tomllib

    from rsmm.cli.editor import modio

    meta = {"name": "Piper tweak", "author": "me", "version": "1.2.3", "tags": ["heroes"],
            "license": "MIT", "summary": "faster shots"}
    got = AE._save(_req(tmp_path, create=True, mod="piper-tweak", meta=meta, hero="Piper",
                        kind="ability", steps=[_STEP]))
    assert (got["mod"], got["block"]) == ("piper-tweak", "PiperAbilities")
    text = (tmp_path / "piper-tweak" / "manifest.toml").read_text(encoding="utf-8")
    mod = tomllib.loads(text)["mod"]
    assert (mod["name"], mod["author"], mod["version"], mod["license"]) == (
        "Piper tweak", "me", "1.2.3", "MIT")
    assert mod["experimental"] is True                         # the kind is experimental
    assert [(b["id"], b["base"], b["steps"]) for b in modio.hero_blocks(text, "ability")] == [
        ("PiperAbilities", "Piper", [_STEP])]
    assert modio.hero_blocks(text) == []                       # no second hero


@needs
def test_a_refused_new_mod_leaves_nothing_behind(tmp_path):
    """A taken id, a bad version or steps that do not build create no folder."""
    AE._save(_req(tmp_path, create=True, mod="taken", meta={}, hero="Piper", kind="ability",
                  steps=[_STEP]))
    for body, msg in [
        ({"mod": "taken"}, "already exists"),
        ({"mod": "other", "meta": {"version": "x"}}, "not like 1.0.0"),
        ({"mod": "../evil"}, "letters, digits"),
        ({"mod": "bad-steps", "steps": [{"set": "No Such Part.value", "value": 1}]},
         "do not build"),
    ]:
        args = {"create": True, "meta": {}, "hero": "Piper", "kind": "ability",
                "steps": [_STEP], **body}
        with pytest.raises(ValueError, match=msg):
            AE._save(_req(tmp_path, **args))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["taken"]


@needs
def test_a_custom_hero_block_is_a_separate_extra_hero(tmp_path):
    from rsmm.cli.editor import modio

    got = AE._save(_req(tmp_path, create=True, mod="copy", meta={}, hero="Beowulf",
                        kind="hero", mode="custom", steps=[]))
    assert got["block"] == "BeowulfEdit"
    text = (tmp_path / "copy" / "manifest.toml").read_text(encoding="utf-8")
    assert [b["id"] for b in modio.hero_blocks(text)] == ["BeowulfEdit"]
    # A paid hero's copy says the author owns the DLC; a free one's does not, and an
    # in-place edit needs neither.
    paid = AE._save(_req(tmp_path, create=True, mod="m", meta={}, hero="Merlin", kind="hero",
                         mode="custom", steps=[]))
    free = AE._save(_req(tmp_path, create=True, mod="c", meta={}, hero="Carmilla", kind="hero",
                         mode="custom", steps=[]))
    inplace = AE._save(_req(tmp_path, create=True, mod="e", meta={}, hero="Merlin", kind="ability",
                            steps=[]))
    read = lambda g: (tmp_path / g["mod"] / "manifest.toml").read_text(encoding="utf-8")  # noqa: E731
    assert "dlc_owner = true" in read(paid)
    assert "dlc_owner" not in read(free) and "dlc_owner" not in read(inplace)


@needs
def test_an_in_place_block_saves_steps_but_not_a_clone(tmp_path):
    from rsmm.cli.editor import modio

    got = AE._save(_req(tmp_path, create=True, mod="edit", meta={}, hero="Piper", kind="ability",
                        steps=[]))
    AE._save(_req(tmp_path, mod=got["mod"], block=got["block"], kind="ability", hero="Piper",
                  steps=[_STEP]))
    text = (tmp_path / got["mod"] / "manifest.toml").read_text(encoding="utf-8")
    assert modio.hero_blocks(text, "ability")[0]["steps"] == [_STEP]
    with pytest.raises(ValueError, match="custom hero"):
        AE._save(_req(tmp_path, mod=got["mod"], block=got["block"], kind="ability", hero="Piper",
                      steps=[{"clone": "Ability Primary", "as": "Echo"}]))


@needs
def test_another_tabs_save_carries_unsaved_ability_steps_into_its_mod(tmp_path):
    """The Scripts tab's Save writes the Abilities tab's unsaved steps too, into the
    block the mod already has for that hero, or a new one: saving twice never doubles."""
    from rsmm.cli.editor import content as C
    from rsmm.cli.editor import modio

    body = {"edits": [], "mod": "lvl10", "create": True, "meta": {},
            "abilities": {"hero": "Piper", "steps": [_STEP], "mode": "inplace"}}
    C._save(_req(tmp_path, **body))
    path = tmp_path / "lvl10" / "manifest.toml"
    blocks = modio.hero_blocks(path.read_text(encoding="utf-8"), "ability")
    assert [(b["id"], b["steps"]) for b in blocks] == [("PiperAbilities", [_STEP])]
    C._save(_req(tmp_path, **{**body, "create": False}))
    blocks = modio.hero_blocks(path.read_text(encoding="utf-8"), "ability")
    assert [(b["id"], b["steps"]) for b in blocks] == [("PiperAbilities", [_STEP])]
    bad = {**body, "mod": "nope", "abilities": {"hero": "Piper", "mode": "inplace",
           "steps": [{"clone": "Ability Primary", "as": "Echo"}]}}
    with pytest.raises(C.EditorError, match="custom hero"):
        C._save(_req(tmp_path, **bad))
    assert not (tmp_path / "nope").exists()                    # no half-made mod
