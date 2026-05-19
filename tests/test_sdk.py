"""Unit tests for the SDK v3 surfaces. Pure host-side; no game required."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from rsmm.sdk.api import API_VERSION, satisfies, sdk_export, registry
from rsmm.sdk.config import ConfigSchema, ConfigStore, ConfigError
from rsmm.sdk.content import ContentRegistry, ContentError, SchemaNotMined
from rsmm.sdk.health import Health, DEFAULT_THRESHOLD
from rsmm.sdk.i18n import I18nBundle, merge_bundles
from rsmm.sdk.intermod import InterModRegistry, InterModError
from rsmm.sdk.transaction import ApplyTransaction
from rsmm.sdk.versioning import check_compat, GameBuildPin


# ---------------------------------------------------------------------------
# api: semver
# ---------------------------------------------------------------------------


def test_satisfies():
    assert satisfies("1.2.3", ">=1.0,<2")
    assert satisfies("1.2.3", "1.2.3")
    assert not satisfies("2.0.0", "<2")
    assert not satisfies("1.0.0", ">=1.1")
    assert satisfies("1.0", ">=1.0,<2")


def test_sdk_export_registry():
    @sdk_export("test_export_xx")
    def f():
        return 1
    assert "test_export_xx" in registry()


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def test_health_record_and_disable(tmp_path: Path):
    h = Health(tmp_path)
    for _ in range(DEFAULT_THRESHOLD):
        h.record_crash("Foo", "boom")
    assert "Foo" in h.disabled_mods()
    h.re_enable("Foo")
    assert "Foo" not in h.disabled_mods()


def test_health_canary(tmp_path: Path):
    h = Health(tmp_path)
    assert h.read_canary() is None
    (tmp_path / ".rsmm_boot.json").write_text(json.dumps({
        "started_at": 1, "last_step": "per_mod:Bar",
    }))
    c = h.read_canary()
    assert c and h.attribute_crash(c) == "Bar"
    h.clear_canary()
    assert h.read_canary() is None


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def test_config_schema_validation():
    s = ConfigSchema.from_dict({"fields": {
        "x": {"type": "int", "min": 0, "max": 10, "default": 1},
        "m": {"type": "enum", "choices": ["a", "b"], "default": "a"},
    }})
    assert s.fields["x"].coerce("5") == 5
    with pytest.raises(ConfigError):
        s.fields["x"].coerce(100)
    with pytest.raises(ConfigError):
        s.fields["m"].coerce("c")


def test_config_store_roundtrip(tmp_path: Path):
    (tmp_path / "config_schema.toml").write_text(
        '[fields.flag]\ntype = "bool"\ndefault = true\n'
        '[fields.count]\ntype = "int"\nmin = 0\nmax = 100\ndefault = 1\n',
        encoding="utf-8",
    )
    store = ConfigStore(tmp_path)
    assert store.get("flag") is True
    assert store.get("count") == 1
    store.set("count", 42)
    # New store reads the persisted value back.
    store2 = ConfigStore(tmp_path)
    assert store2.get("count") == 42
    with pytest.raises(ConfigError):
        store.set("count", 9999)
    with pytest.raises(ConfigError):
        store.set("unknown", 1)


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------


def test_i18n_namespaced(tmp_path: Path):
    lang = tmp_path / "lang"
    lang.mkdir()
    (lang / "EN.toml").write_text('[strings]\ngreet = "Hi"\n', encoding="utf-8")
    (lang / "DE.toml").write_text('[strings]\ngreet = "Hallo"\n', encoding="utf-8")
    b = I18nBundle.load("MyMod", tmp_path)
    assert b.namespaced("EN") == {"RSMM_MyMod_greet": "Hi"}
    assert b.namespaced("DE") == {"RSMM_MyMod_greet": "Hallo"}
    # Unknown locale falls back to EN.
    assert b.namespaced("JA") == {"RSMM_MyMod_greet": "Hi"}


def test_i18n_coverage_warnings(tmp_path: Path):
    lang = tmp_path / "lang"
    lang.mkdir()
    (lang / "EN.toml").write_text('[strings]\na = "1"\nb = "2"\n', encoding="utf-8")
    (lang / "DE.toml").write_text('[strings]\na = "1"\n', encoding="utf-8")
    b = I18nBundle.load("M", tmp_path)
    warns = b.coverage_warnings()
    assert any("DE missing key 'b'" in w for w in warns)


def test_i18n_merge_no_collision(tmp_path: Path):
    def _mk(modid: str, key: str, val: str) -> I18nBundle:
        d = tmp_path / modid
        (d / "lang").mkdir(parents=True)
        (d / "lang" / "EN.toml").write_text(
            f'[strings]\n{key} = "{val}"\n', encoding="utf-8"
        )
        return I18nBundle.load(modid, d)
    a = _mk("A", "x", "1")
    b = _mk("B", "x", "2")
    merged = merge_bundles([a, b])
    assert merged["EN"]["RSMM_A_x"] == "1"
    assert merged["EN"]["RSMM_B_x"] == "2"


# ---------------------------------------------------------------------------
# intermod
# ---------------------------------------------------------------------------


def test_intermod_expose_require():
    r = InterModRegistry()
    r.expose("ItemPack", {"add": lambda x: x + 1}, version="1.0.0",
             api_name="itempack")
    p = r.require("itempack", ">=1.0")
    assert p.add(2) == 3
    with pytest.raises(InterModError):
        r.require("itempack", ">=2")
    with pytest.raises(InterModError):
        r.require("missing")


def test_intermod_proxy_catches():
    def boom(*_):
        raise RuntimeError("oops")
    r = InterModRegistry()
    r.expose("X", {"go": boom}, version="0.1.0", api_name="x")
    p = r.require("x")
    with pytest.raises(InterModError):
        p.go()
    with pytest.raises(InterModError):
        p.something = 1


# ---------------------------------------------------------------------------
# content
# ---------------------------------------------------------------------------


def test_content_register_and_emit(tmp_path: Path):
    cr = ContentRegistry(mod_id="MM")
    cr.register("item", id="FrostBlade", base="VanillaSword",
                stats={"damage": 50})
    out = tmp_path / "out"
    out.mkdir()
    written = cr.emit(out)
    assert any(p.name == "FrostBlade.json" for p in written)


def test_content_unknown_kind_rejected():
    cr = ContentRegistry(mod_id="MM")
    with pytest.raises(ContentError):
        cr.register("widget", id="X")


def test_content_missing_base_fails_loudly(tmp_path: Path):
    cr = ContentRegistry(mod_id="MM")
    cr.register("item", id="X")  # no base
    with pytest.raises(SchemaNotMined):
        cr.emit(tmp_path)


# ---------------------------------------------------------------------------
# transaction
# ---------------------------------------------------------------------------


def test_transaction_commit_atomic(tmp_path: Path):
    cooking = tmp_path / "cooking"
    cooking.mkdir()
    src = tmp_path / "src.bin"
    src.write_bytes(b"new")
    dest = cooking / "sub" / "asset"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old")

    tx = ApplyTransaction(cooking)
    tx.stage_write("sub/asset", src, dest)
    committed = tx.commit()
    assert committed == ["sub/asset"]
    assert dest.read_bytes() == b"new"
    bak = dest.parent / (dest.name + ".rsmm.bak")
    assert bak.exists()
    assert bak.read_bytes() == b"old"
    assert not tx.stage_root.exists()


def test_transaction_recover_discards_orphan(tmp_path: Path):
    cooking = tmp_path / "cooking"
    cooking.mkdir()
    (cooking / ".rsmm_stage" / "x").mkdir(parents=True)
    (cooking / ".rsmm_stage" / "x" / "y").write_bytes(b"junk")
    tx = ApplyTransaction(cooking)
    assert tx.recover() == "discarded"
    assert not (cooking / ".rsmm_stage").exists()


def test_transaction_rejects_path_escape(tmp_path: Path):
    cooking = tmp_path / "cooking"
    cooking.mkdir()
    src = tmp_path / "x"
    src.write_bytes(b"")
    tx = ApplyTransaction(cooking)
    with pytest.raises(ValueError):
        tx.stage_write("../oops", src, cooking / "x")


# ---------------------------------------------------------------------------
# versioning
# ---------------------------------------------------------------------------


def test_versioning_pin_first_then_match(tmp_path: Path):
    cooking = tmp_path / "cooking"
    cooking.mkdir()
    exe = tmp_path / "exe.bin"
    exe.write_bytes(b"GAME")
    ok, msg = check_compat(exe, cooking)
    assert ok and "pinned" in msg
    ok, msg = check_compat(exe, cooking)
    assert ok and "unchanged" in msg
    exe.write_bytes(b"PATCHED")
    ok, msg = check_compat(exe, cooking)
    assert not ok and "game updated" in msg


# ---------------------------------------------------------------------------
# repo (optional cryptography dep — tests skip if not installed)
# ---------------------------------------------------------------------------


def test_repo_index_roundtrip():
    from rsmm.sdk.repo import RepoIndex, RepoEntry
    idx = RepoIndex(name="t", updated_at="x",
                    mods=[RepoEntry(id="A", version="1.2.3",
                                    url="u", sha256="0" * 64, size=10)])
    re_idx = RepoIndex.load(idx.dump())
    assert re_idx.mods[0].id == "A"
    found = re_idx.find("A", ">=1.0")
    assert found and found.version == "1.2.3"
    assert re_idx.find("A", ">=2") is None


def test_repo_sha256(tmp_path: Path):
    from rsmm.sdk.repo import sha256_file
    p = tmp_path / "f"
    p.write_bytes(b"abc")
    # sha256("abc") = ba7816...
    assert sha256_file(p).startswith("ba7816bf8f01")


def test_all_repo_mods_are_v3(tmp_path: Path):
    """Every example mod under mods/ must declare sdk_version >=3 + use v3 conventions."""
    import tomllib
    from rsmm.engine.paths import MODS_DIR
    if not MODS_DIR.is_dir():
        pytest.skip("no mods/ dir")
    bad: list[str] = []
    for entry in MODS_DIR.iterdir():
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        mf = entry / "manifest.toml"
        if not mf.exists():
            continue
        body = tomllib.loads(mf.read_text(encoding="utf-8"))
        meta = body.get("mod", {})
        spec = str(meta.get("sdk_version", ""))
        # Accept ">=3.0" or "3.x" or "3" — anything that mentions 3.
        if "3" not in spec:
            bad.append(f"{entry.name}: sdk_version={spec!r}")
    assert not bad, "non-v3 manifests still present: " + ", ".join(bad)


def test_content_block_emission_via_applier(tmp_path: Path, monkeypatch):
    """`[[content]]` blocks in a manifest produce per-kind emit markers."""
    import tomllib
    mods_dir = tmp_path / "mods"
    mod = mods_dir / "T"
    mod.mkdir(parents=True)
    (mod / "manifest.toml").write_text(
        '[mod]\nid = "T"\nname = "T"\nversion = "1"\nenabled = true\n'
        'sdk_version = ">=3.0,<4"\n\n'
        '[[content]]\nkind = "item"\nid = "X"\nbase = "Common/Foo"\n',
        encoding="utf-8",
    )
    from rsmm.cli.apply_mods import Mod, emit_content_blocks
    m = Mod(mod)
    assert m.content_blocks and m.content_blocks[0]["id"] == "X"
    emit_content_blocks([m])
    assert (mod / "assets" / "_pending_items" / "X.json").exists()
    # Filtered from the asset walk.
    assert m.files() == []


def test_docs_gen_writes_per_module(tmp_path: Path):
    from rsmm.sdk.docs_gen import generate
    written = generate(tmp_path)
    assert written
    # README index always written.
    assert any(p.name == "README.md" for p in written)
    # At least one per-module file from the @sdk_export decorations.
    assert any(p.suffix == ".md" and p.stem != "README" for p in written)
    # Index lists each module page.
    idx = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "SDK v3 API reference" in idx


def test_migrations_no_chain_returns_empty():
    from rsmm.sdk.migrations import chain
    assert chain("item", 1, 1) == [1]
    assert chain("item", 2, 1) == []
    # No migrations on disk -> jumping versions yields empty chain.
    assert chain("item", 1, 5) == []


def test_migrations_runs_when_present(tmp_path: Path, monkeypatch):
    """Drop a synthetic migration into the package and run it."""
    import rsmm.sdk.kinds as k
    migr_dir = Path(k.__file__).parent / "item" / "migrations"
    migr_dir.mkdir(parents=True, exist_ok=True)
    (migr_dir / "__init__.py").write_text("", encoding="utf-8")
    (migr_dir.parent / "__init__.py").touch()
    f = migr_dir / "1_to_2.py"
    f.write_text(
        "def migrate(d):\n"
        "    d = dict(d)\n"
        "    d['migrated'] = True\n"
        "    return d\n",
        encoding="utf-8",
    )
    try:
        from rsmm.sdk.migrations import migrate
        out = migrate("item", {"x": 1}, from_v=1, to_v=2)
        assert out == {"x": 1, "migrated": True}
    finally:
        # Cleanup so the synthetic migration doesn't leak into other runs.
        f.unlink()


def test_update_plan_skips_when_up_to_date(monkeypatch, tmp_path: Path):
    from rsmm.cli import update_cmd
    fake_index = {
        "schema": "rsmm.repo.v1",
        "name": "t",
        "updated_at": "x",
        "mods": [{"id": "Foo", "version": "1.0.0", "url": "u",
                  "sha256": "0" * 64}],
    }
    monkeypatch.setattr(update_cmd, "_load_repos", lambda: ["http://x"])
    monkeypatch.setattr(update_cmd, "_installed_mods", lambda: {"Foo": "1.0.0"})
    monkeypatch.setattr(update_cmd, "_fetch",
                        lambda url, timeout=30.0: json.dumps(fake_index).encode())
    rc = update_cmd.main(["--check"])
    assert rc == 0


def test_repo_sign_verify_roundtrip(tmp_path: Path):
    try:
        from rsmm.sdk.repo import keygen, sign_file, verify_file
        priv_b64, pub_b64 = keygen()
    except Exception:
        pytest.skip("cryptography not installed")
    f = tmp_path / "blob"
    f.write_bytes(b"payload")
    priv = tmp_path / "k.key"
    priv.write_text(priv_b64, encoding="utf-8")
    pub = tmp_path / "k.pub"
    pub.write_text(pub_b64, encoding="utf-8")
    sig = sign_file(f, priv)
    assert verify_file(f, sig, pub)
    # Tamper detection.
    f.write_bytes(b"tampered")
    assert not verify_file(f, sig, pub)
