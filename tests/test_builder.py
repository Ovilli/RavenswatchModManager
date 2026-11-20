"""Tests for the SDK ModBuilder."""

from __future__ import annotations


def test_builder_creates_manifest(tmp_path, monkeypatch):
    from rsmm.sdk.builder import ModBuilder
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path)
    b = ModBuilder("TestMod", version="1.0.0", author="tester", name="Test Mod")
    dst = b.commit()
    assert dst == tmp_path / "TestMod"
    mf = dst / "manifest.toml"
    assert mf.exists()
    content = mf.read_text(encoding="utf-8")
    assert 'id = "TestMod"' in content
    assert 'version = "1.0.0"' in content


def test_builder_config(tmp_path, monkeypatch):
    from rsmm.sdk.builder import ModBuilder
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path)
    b = ModBuilder("CfgMod", version="0.1.0", author="t", name="Cfg")
    b.config({"fields": {"enabled": {"type": "bool", "default": True}}})
    b.commit()
    schema = tmp_path / "CfgMod" / "config_schema.toml"
    assert schema.exists()
    assert "enabled" in schema.read_text()


def test_builder_i18n(tmp_path, monkeypatch):
    from rsmm.sdk.builder import ModBuilder
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path)
    b = ModBuilder("I18nMod", version="0.1.0", author="t", name="I18n")
    b.i18n("EN", {"greet": "Hello"})
    b.i18n("DE", {"greet": "Hallo"})
    b.commit()
    assert (tmp_path / "I18nMod" / "lang" / "EN.toml").exists()
    assert (tmp_path / "I18nMod" / "lang" / "DE.toml").exists()


def test_builder_requires(tmp_path, monkeypatch):
    from rsmm.sdk.builder import ModBuilder
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path)
    b = ModBuilder("DepMod", version="1.0.0", author="t", name="Dep")
    b.requires("BaseMod", ">=1.0")
    b.requires("Utils", "")
    b.commit()
    mf = (tmp_path / "DepMod" / "manifest.toml").read_text()
    assert "BaseMod" in mf
    assert "Utils" in mf


def test_builder_provides_api(tmp_path, monkeypatch):
    from rsmm.sdk.builder import ModBuilder
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path)
    b = ModBuilder("ApiMod", version="1.0.0", author="t", name="API")
    b.provides_api("myapi")
    b.commit()
    mf = (tmp_path / "ApiMod" / "manifest.toml").read_text()
    assert 'api = "myapi"' in mf


def test_builder_patch_blocks(tmp_path, monkeypatch):
    from rsmm.sdk.builder import ModBuilder
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path)
    b = ModBuilder("PatchMod", version="1.0.0", author="t", name="Patch")
    b.stat("Health", value=100, min=0, max=200)
    b.commit()
    mf = (tmp_path / "PatchMod" / "manifest.toml").read_text()
    assert "[[patch]]" in mf
    assert 'kind = "stat"' in mf
    assert "Health" in mf


def test_builder_texture_asset(tmp_path, monkeypatch):
    from rsmm.sdk.builder import ModBuilder
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path)
    src = tmp_path / "skin.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\nstub")
    b = ModBuilder("TexMod", version="0.1.0", author="t", name="Tex")
    b.texture("3D/Characters/Heroes/Melusine/Textures/T_Melusine_ALB.png", src)
    b.commit()
    staged = (tmp_path / "TexMod" / "assets"
              / "3D/Characters/Heroes/Melusine/Textures/T_Melusine_ALB.png")
    assert staged.is_file()
    assert staged.read_bytes() == src.read_bytes()


def test_builder_model_rejects_non_mesh_ext(tmp_path):
    from rsmm.sdk.builder import ModBuilder
    src = tmp_path / "x.png"
    src.write_bytes(b"x")
    b = ModBuilder("M", version="0.1.0", author="t", name="M")
    try:
        b.model("a/b.glb", src)
    except ValueError:
        return
    raise AssertionError("model() should reject .png")


def test_builder_asset_rejects_traversal_and_dupes(tmp_path):
    from rsmm.sdk.builder import ModBuilder
    src = tmp_path / "f.dds"
    src.write_bytes(b"DDS")
    b = ModBuilder("M", version="0.1.0", author="t", name="M")
    for bad in ("../evil.dds", "/abs/evil.dds", "a/../../evil.dds"):
        try:
            b.texture(bad, src)
        except ValueError:
            continue
        raise AssertionError(f"expected rejection of {bad!r}")
    b.texture("ok/path.dds", src)
    try:
        b.texture("ok/path.dds", src)
    except ValueError:
        return
    raise AssertionError("expected duplicate rejection")


def test_builder_missing_asset_source_raises(tmp_path):
    from rsmm.sdk.builder import ModBuilder
    b = ModBuilder("M", version="0.1.0", author="t", name="M")
    try:
        b.asset("a/b.png", tmp_path / "nope.png")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


def test_mod_facade_forwards_every_public_builder_method():
    """`sdk.Mod` is a hand-written facade over ModBuilder; a builder method it
    forgets is one the docs can show and an author cannot call (`m.ot` was
    missing while the guide used it)."""
    from rsmm import sdk
    from rsmm.sdk.builder import ModBuilder
    internal = {"commit"}          # Mod.__exit__ calls it
    public = {n for n in vars(ModBuilder)
              if not n.startswith("_") and callable(getattr(ModBuilder, n))}
    missing = sorted(public - internal - set(dir(sdk.Mod)))
    assert not missing, f"sdk.Mod does not forward: {missing}"


def test_builder_output_parses(tmp_path, monkeypatch):
    """Generated TOML and Lua parse, with values that need escaping, and the
    defs land as [[content]] blocks apply can re-emit. JSON in init.lua was a
    Lua syntax error; raw f-strings broke the manifest on a quote and turned
    lists into strings."""
    import json
    import shutil
    import subprocess
    import tomllib
    import types

    import pytest

    from rsmm.sdk import content as content_mod
    from rsmm.sdk.builder import ModBuilder

    def emit(mod_id, defn, out_dir):
        dest = out_dir / "Items" / f"{defn.id}.gen"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return [dest]

    monkeypatch.setattr(content_mod, "_load_kind", lambda kind: types.SimpleNamespace(emit=emit))
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path)
    odd = 'Bob "X" \\ Mod\nline2'
    b = ModBuilder("Odd", version="1.0.0", author=odd, name=odd)
    b.config({"fields": {"pick": {"type": "multiselect", "choices": [1, 2], "default": [1]}}})
    b.stat("Health", value=100, tags=["a", "b"])
    b.item("Ring", base="Armor_Per_Object", name=odd)
    dst = b.commit()

    mf = tomllib.loads((dst / "manifest.toml").read_text(encoding="utf-8"))
    assert mf["mod"]["name"] == odd and mf["mod"]["author"] == odd
    assert mf["patch"][0]["tags"] == ["a", "b"]
    assert mf["content"] == [{"kind": "item", "id": "Ring",
                              "base": "Armor_Per_Object", "name": odd}]
    cfg = tomllib.loads((dst / "config_schema.toml").read_text(encoding="utf-8"))
    assert cfg["fields"]["pick"]["default"] == [1]
    assert json.loads((dst / ".rsmm_emitted.json").read_text()) == ["Items/Ring.gen"]

    luac = shutil.which("luac5.4") or shutil.which("luac")
    if luac is None:
        pytest.skip("no luac to syntax-check init.lua")
    subprocess.run([luac, "-p", str(dst / "init.lua")], check=True)

    # A hand-written init.lua survives the next build.
    (dst / "init.lua").write_text("print('mine')\n", encoding="utf-8")
    b.commit()
    assert (dst / "init.lua").read_text(encoding="utf-8") == "print('mine')\n"


def test_item_init_compiles_with_hundreds_of_items(tmp_path, monkeypatch):
    """#229 review: every item declared its own `local ok`, and Lua allows
    200 locals per function, so a 200-item mod's init.lua did not compile."""
    import shutil
    import subprocess
    import types

    import pytest

    from rsmm.sdk import content as content_mod
    from rsmm.sdk.builder import ModBuilder

    luac = shutil.which("luac5.4") or shutil.which("luac")
    if luac is None:
        pytest.skip("no luac to syntax-check init.lua")
    monkeypatch.setattr(content_mod, "_load_kind",
                        lambda kind: types.SimpleNamespace(emit=lambda *a: []))
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path)
    b = ModBuilder("Many", version="1.0.0", author="a", name="Many")
    for i in range(250):
        b.item(f"Ring{i}", base="Armor_Per_Object")
    subprocess.run([luac, "-p", str(b.commit() / "init.lua")], check=True)
