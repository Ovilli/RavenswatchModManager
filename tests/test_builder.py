"""Tests for the SDK ModBuilder."""

from __future__ import annotations

from pathlib import Path

import pytest


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
    b.text("UI/title", "Hello")
    b.commit()
    mf = (tmp_path / "PatchMod" / "manifest.toml").read_text()
    assert "[[patch]]" in mf
    assert 'kind = "stat"' in mf
    assert 'kind = "text"' in mf
    assert "Health" in mf
    assert "Hello" in mf
