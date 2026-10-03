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


@needs
def test_a_new_mod_comes_with_a_block_to_save_into(tmp_path):
    """Saving ability changes needs a block: by default an in-place edit of the
    shipped hero; or, as "custom", a separate hero built on it (a paid hero's copy
    is marked `dlc_owner`)."""
    from types import SimpleNamespace

    from rsmm.cli.editor import modio

    def req(**body):
        return SimpleNamespace(body=body, ctx=SimpleNamespace(mods_dir=tmp_path))

    def text(got):
        return (tmp_path / got["mod"] / "manifest.toml").read_text(encoding="utf-8")

    got = AE._new_mod(req(name="Pam Fireball Nerf", hero="Beowulf"))
    assert got == {"mod": "pam-fireball-nerf", "block": "BeowulfAbilities"}
    blocks = modio.hero_blocks(text(got), "ability")
    assert [(b["id"], b["base"]) for b in blocks] == [("BeowulfAbilities", "Beowulf")]
    assert modio.hero_blocks(text(got)) == []                  # no second hero
    # a second mod of the same name gets its own folder
    assert AE._new_mod(req(name="Pam Fireball Nerf", hero="Beowulf"))["mod"] \
        == "pam-fireball-nerf-2"
    # a custom hero is a separate, extra one
    custom = AE._new_mod(req(name="Beowulf copy", hero="Beowulf", mode="custom"))
    assert custom["block"] == "BeowulfEdit"
    assert [b["id"] for b in modio.hero_blocks(text(custom))] == ["BeowulfEdit"]
    # A paid hero's copy says the author owns the DLC; a free one's does not, and an
    # in-place edit needs neither.
    paid = AE._new_mod(req(name="Merlin copy", hero="Merlin", mode="custom"))
    free = AE._new_mod(req(name="Carmilla copy", hero="Carmilla", mode="custom"))
    assert "dlc_owner = true" in text(paid) and "dlc_owner" not in text(free)
    assert "dlc_owner" not in text(AE._new_mod(req(name="Merlin edit", hero="Merlin")))


@needs
def test_an_in_place_block_saves_steps_but_not_a_clone(tmp_path):
    from types import SimpleNamespace

    from rsmm.cli.editor import modio

    def req(**body):
        return SimpleNamespace(body=body, ctx=SimpleNamespace(mods_dir=tmp_path))

    got = AE._new_mod(req(name="Edit", hero="Piper"))
    step = {"set": "Primary Ability Shots Delay.value", "value": 0.5}
    AE._save(req(mod=got["mod"], block=got["block"], kind="ability", hero="Piper",
                 steps=[step]))
    text = (tmp_path / got["mod"] / "manifest.toml").read_text(encoding="utf-8")
    assert modio.hero_blocks(text, "ability")[0]["steps"] == [step]
    with pytest.raises(ValueError, match="custom hero"):
        AE._save(req(mod=got["mod"], block=got["block"], kind="ability", hero="Piper",
                     steps=[{"clone": "Ability Primary", "as": "Echo"}]))
