"""The Hero tab's starter files and uploads (`rsmm.cli.editor.herostarter`):
something real to open for every file field, and a whole hero that builds."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from rsmm.cli.editor import herobuilder as HB
from rsmm.cli.editor import herostarter as HS
from rsmm.engine import image
from rsmm.sdk.kinds import heros

needs_corpus = pytest.mark.skipif(not heros.shipped_heroes(), reason="no hero corpus")


@pytest.fixture
def mods(tmp_path):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "manifest.toml").write_text('[mod]\nid = "m"\n', encoding="utf-8")
    return tmp_path


def _req(mods, **body):
    return SimpleNamespace(ctx=SimpleNamespace(mods_dir=mods), body={"mod": "m", **body},
                           arg=lambda k, d="": d)


@pytest.mark.parametrize("shape", HS.SHAPES)
def test_every_shape_is_a_white_sprite_with_its_shape_in_the_alpha(shape):
    w, h, px = image.decode_png(HS.shape_png(shape, 32))
    assert (w, h) == (32, 32)
    alphas = px[3::4]
    assert set(px[0::4]) == {255} and max(alphas) > 150 and min(alphas) == 0


def test_an_upload_lands_in_art_under_a_free_name(mods):
    png = HS.shape_png("dot", 8)
    data = base64.b64encode(png).decode()
    first = HS.upload(_req(mods, folder="art/ui", name="My Icon!.png", data=data))
    again = HS.upload(_req(mods, folder="art/ui", name="My Icon!.png", data=data))
    assert first == {"path": "art/ui/My_Icon.png"} and again == {"path": "art/ui/My_Icon_2.png"}
    assert (mods / "m" / "art" / "ui" / "My_Icon.png").read_bytes() == png


@pytest.mark.parametrize(("folder", "name", "data", "why"), [
    ("../..", "x.png", HS.shape_png("dot", 4), "art/"),
    ("art", "x.exe", b"MZ", "not 'x.exe'"),
    ("art", "x.png", b"glTF....", "not a .png file inside"),
])
def test_an_upload_refuses_what_is_not_art(mods, folder, name, data, why):
    with pytest.raises(HS.StarterError, match=why):
        HS.upload(_req(mods, folder=folder, name=name, data=base64.b64encode(data).decode()))


def test_the_body_cap_is_raised_for_uploads_only():
    from rsmm.cli.editor import app
    assert app.body_limit("/hero/api/upload") == app.MAX_UPLOAD > app.MAX_BODY
    assert app.body_limit("/hero/api/save") == app.MAX_BODY


def test_each_button_gets_a_move_named_for_it():
    here = "Characters\\Heroes\\X\\Animations"
    names = ["X_BasicAttack01", "X_BasicAttack02", "X_Power_In", "X_PowerHold_In", "X_Special_In",
             "X_Defense", "X_Trait", "X_Ultimate1_In", "X_Run_Loop", "X_Dash", "XProp_Attack_1"]
    got = HS.pick_clips([f"{here}\\{n}.fbx" for n in names])
    leaf = {k: v.rsplit("\\", 1)[-1] for k, v in got.items()}
    assert leaf == {"attack1": "X_BasicAttack01.fbx", "attack2": "X_BasicAttack02.fbx",
                    "power": "X_Power_In.fbx", "special": "X_Special_In.fbx",
                    "defense": "X_Defense.fbx", "trait": "X_Trait.fbx",
                    "ultimate": "X_Ultimate1_In.fbx"}


@needs_corpus
def test_starters_from_the_game_are_real_files(mods):
    rig = HB.rig("Hero_Kintaro")
    root = mods / "m"
    got = HS.body(root, rig["mesh"], rig["material"])
    assert (root / got["model"]).read_bytes()[:4] == b"glTF"
    assert (root / got["albedo"]).read_bytes()[:8] == HS.UPLOAD_KINDS[".png"]
    clip = HS.anim(root, rig["mesh"], "Kintaro_BasicAttack01")
    assert clip["clip"] == clip["template"] == "Kintaro_BasicAttack01"
    assert (root / clip["source"]).read_bytes()[:4] == b"glTF"
    assert (root / HS.picture(root, "", "icon")["path"]).is_file()
    assert (root / HS.projectile(root)["model"]).is_file()


@needs_corpus
def test_a_starter_hero_has_every_button_and_no_problems(mods):
    got = HS.hero(_req(mods, rig="Hero_Juliet"))
    hero = {"kind": "hero", "id": "Starter", "name": "Starter", **got}
    assert set(hero["frame"]["abilities"]) == {"attack", "power", "special", "defense",
                                              "trait", "ultimate"}
    assert HB.problems(hero, mods / "m") == []
    assert (mods / "m" / hero["frame"]["portrait"]).is_file()
    # Merlin is a paid DLC hero: never offered as a rig
    assert "Hero_Merlin" not in HB.rigs() and "Hero_Sun_Wukong" in HB.rigs()


def test_files_made_before_the_mod_wait_in_a_draft_and_move_in_on_save(tmp_path, monkeypatch):
    """Use the rig's texture on "New mod…" must not ask for a mod first: the
    file waits in the page's draft folder and the first save moves it in."""
    monkeypatch.setattr(HB, "schema", lambda: {"rigs": ["Hero_Juliet"]})
    req = SimpleNamespace(ctx=SimpleNamespace(mods_dir=tmp_path), arg=lambda k, d="": d,
                          body={"mod": "", "draft": "abcdef123456", "what": "shape",
                                "shape": "ring"})
    got = HS.starter(req)
    draft = tmp_path / HS.DRAFTS / "abcdef123456"
    assert got == {"path": "art/fx/ring.png"} and (draft / "art/fx/ring.png").is_file()
    assert not (tmp_path / "abcdef123456").exists()            # no mod was made
    hero = {"id": "Vex", "name": "Vex", "frame": {"rig": "Hero_Juliet", "mesh": "a\\b.fbx",
            "material": "a\\m.mat.ot", "portrait": "art/fx/ring.png"}}
    req.body = {"mod": "newmod", "create": True, "block": "", "hero": hero,
                "draft": "abcdef123456", "meta": {"name": "New"}}
    out = HB._save(req)
    assert out["problems"] == []                              # the file is where it says
    assert (tmp_path / "newmod" / "art/fx/ring.png").is_file() and not draft.exists()
    with pytest.raises(ValueError, match="draft"):
        HB._files(SimpleNamespace(ctx=req.ctx, body={}, arg=lambda k, d="": {"mod": ""}.get(k, d)))


@needs_corpus
def test_a_game_hero_rebuilt_from_scratch_owns_every_file_it_names(mods, install_only):
    # install_only: the web editor has only the player's install, no mirror
    got = HS.recreate(_req(mods, rig="Hero_Juliet"))
    f = got["frame"]
    hero = {"kind": "hero", "id": got["hero"]["id"], "name": got["hero"]["name"],
            "frame": f, "memoirs": got["memoirs"]}
    assert HB.problems(hero, mods / "m") == []
    # every move a button plays is the mod's own clip, written out
    plays = [a["clip"] for a in f["abilities"].values() if a.get("clip")] + \
        [s["clip"] for s in f["abilities"]["attack"]["combo"]]
    assert plays and all(p.startswith("anim:") and p[5:] in f["animations"] for p in plays)
    for path in [f["model"], f["albedo"], f["portrait"], f["banner"],
                 *(a["icon"] for a in f["abilities"].values()),
                 *(t["icon"] for t in f["talents"]),
                 *(a["source"] for a in f["animations"].values())]:
        assert (mods / "m" / path).is_file(), path
    assert len(f["talents"]) == 22 and len(got["memoirs"]) == 7
    assert f["abilities"]["special"]["name"] == "Passionate Kiss"    # the game's own card name
