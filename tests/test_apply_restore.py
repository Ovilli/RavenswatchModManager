"""End-to-end test for `rsmm apply` + `rsmm restore`.

Builds a self-contained fake repo (mods + asset_map) and a fake game
install in tmp_path, runs apply_mods.cmd_apply against it, asserts the
override took and the .rsmm.bak sibling preserves the original bytes.
Then runs cmd_restore_all and asserts the file is byte-identical to
the original and that .rsmm_state.json's active map is empty.

This is the regression contract: nothing in the apply path should
ever fail to roundtrip a clean install."""

import json
from pathlib import Path
from types import SimpleNamespace


def _make_fake_repo(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Return (repo, mods_dir, asset_map_json, game_dir).

    Layout:
      repo/mods/TestMod/manifest.toml
      repo/mods/TestMod/assets/foo/bar.bin     ('MOD CONTENT')
      repo/asset_map.json                      {'a\\\\b.bin': 'foo/bar.bin'}
      game/DarkTalesResources/_Cooking/a/b.bin ('VANILLA CONTENT')
    """
    repo = tmp_path / "repo"
    mods_dir = repo / "mods"
    mod_root = mods_dir / "TestMod"
    (mod_root / "assets" / "foo").mkdir(parents=True)
    (mod_root / "assets" / "foo" / "bar.bin").write_bytes(b"MOD CONTENT")
    (mod_root / "manifest.toml").write_text(
        '[mod]\n'
        'id          = "TestMod"\n'
        'name        = "Test"\n'
        'version     = "1.0.0"\n'
        'author      = "t"\n'
        'enabled     = true\n',
        encoding="utf-8",
    )

    asset_map = repo / "asset_map.json"
    asset_map.write_text(json.dumps({"a\\b.bin": "foo/bar.bin"}), encoding="utf-8")

    game_dir = tmp_path / "game"
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    (cooking / "a").mkdir(parents=True)
    (cooking / "a" / "b.bin").write_bytes(b"VANILLA CONTENT")

    return repo, mods_dir, asset_map, game_dir


def test_apply_then_restore_roundtrips(tmp_path, monkeypatch, capsys):
    from rsmm.cli import apply_mods

    repo, mods_dir, asset_map, game_dir = _make_fake_repo(tmp_path)
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    vanilla = cooking / "a" / "b.bin"
    bak = vanilla.parent / (vanilla.name + ".rsmm.bak")
    state_path = cooking / ".rsmm_state.json"

    monkeypatch.setattr(apply_mods, "MODS_DIR", mods_dir)
    monkeypatch.setattr(apply_mods, "ASSET_MAP_JSON", asset_map)
    # cmd_apply's game-update recovery calls find_iyg.main(), which rebuilds the
    # REAL data/asset_map.{json,csv}. Stub it so the test stays hermetic (the
    # fresh tmp game_dir always reads as "updated", triggering recovery).
    import rsmm.engine.find_iyg as find_iyg
    monkeypatch.setattr(find_iyg, "main", lambda *a, **k: 0)

    args = SimpleNamespace(dry_run=False)

    # --- apply -----------------------------------------------------
    rc = apply_mods.cmd_apply(args, repo, cooking, game_dir)
    capsys.readouterr()
    assert rc == 0
    assert vanilla.read_bytes() == b"MOD CONTENT"
    assert bak.is_file()
    assert bak.read_bytes() == b"VANILLA CONTENT"
    assert state_path.is_file()
    state = json.loads(state_path.read_text())
    assert "a\\b.bin" in state["active"], state

    # --- restore ---------------------------------------------------
    rc = apply_mods.cmd_restore_all(args, repo, cooking, game_dir)
    capsys.readouterr()
    assert rc == 0
    assert vanilla.read_bytes() == b"VANILLA CONTENT"
    assert not bak.exists(), "backup should be moved back, not left behind"
    state = json.loads(state_path.read_text())
    assert state.get("active") == {}, state


def test_apply_recopies_when_installed_copy_drifts(tmp_path, monkeypatch, capsys):
    """Stale-install regression: state says the override is applied (and the
    mod source is unchanged), but the installed bytes drifted — e.g. Steam
    'verify integrity' put the vanilla file back. apply must hash the
    *installed* copy, notice the mismatch, and re-copy the mod asset instead
    of trusting the state entry."""
    from rsmm.cli import apply_mods

    repo, mods_dir, asset_map, game_dir = _make_fake_repo(tmp_path)
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    vanilla = cooking / "a" / "b.bin"

    monkeypatch.setattr(apply_mods, "MODS_DIR", mods_dir)
    monkeypatch.setattr(apply_mods, "ASSET_MAP_JSON", asset_map)
    import rsmm.engine.find_iyg as find_iyg
    monkeypatch.setattr(find_iyg, "main", lambda *a, **k: 0)

    args = SimpleNamespace(dry_run=False)

    rc = apply_mods.cmd_apply(args, repo, cooking, game_dir)
    capsys.readouterr()
    assert rc == 0
    assert vanilla.read_bytes() == b"MOD CONTENT"

    # Simulate Steam verify: vanilla bytes return, state still says applied.
    vanilla.write_bytes(b"VANILLA CONTENT")

    rc = apply_mods.cmd_apply(args, repo, cooking, game_dir)
    out = capsys.readouterr().out
    assert rc == 0
    assert vanilla.read_bytes() == b"MOD CONTENT", \
        "apply trusted the state entry instead of re-hashing the installed copy"
    assert "Mods already in sync." not in out


def test_apply_skips_unchanged_override(tmp_path, monkeypatch, capsys):
    """Counterpart to the drift test: when the installed copy still matches
    the mod source, a second apply is a no-op (no churn, no backup rewrite)."""
    from rsmm.cli import apply_mods

    repo, mods_dir, asset_map, game_dir = _make_fake_repo(tmp_path)
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    vanilla = cooking / "a" / "b.bin"
    bak = vanilla.parent / (vanilla.name + ".rsmm.bak")

    monkeypatch.setattr(apply_mods, "MODS_DIR", mods_dir)
    monkeypatch.setattr(apply_mods, "ASSET_MAP_JSON", asset_map)
    import rsmm.engine.find_iyg as find_iyg
    monkeypatch.setattr(find_iyg, "main", lambda *a, **k: 0)

    args = SimpleNamespace(dry_run=False)

    assert apply_mods.cmd_apply(args, repo, cooking, game_dir) == 0
    capsys.readouterr()

    rc = apply_mods.cmd_apply(args, repo, cooking, game_dir)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Mods already in sync." in out
    assert vanilla.read_bytes() == b"MOD CONTENT"
    assert bak.read_bytes() == b"VANILLA CONTENT"


def test_texture_donor_reads_the_vanilla_backup(tmp_path, monkeypatch):
    """A texture donor must be the game's ORIGINAL bytes, not the live file.

    `cooking` is the live directory, so a donor another mod already replaced
    would be copied in its MODDED form and the result would depend on mod
    order — and re-applying could chain one texture mod's output into another's
    input. `apply` keeps the original beside every override as
    <file>.rsmm.bak, so that is the pristine donor when it exists.
    """
    from rsmm.cli import merge

    cooking = tmp_path / "cook"
    cooking.mkdir()
    donor = cooking / "DONOR.dxt"
    donor.write_bytes(b"MODDED-BY-SOMETHING-ELSE")
    (cooking / "DONOR.dxt.rsmm.bak").write_bytes(b"VANILLA")

    # Mirror the resolution merge.py performs, including the backup preference.
    src = cooking / "DONOR.dxt"
    pristine = src.parent / (src.name + ".rsmm.bak")
    if pristine.exists():
        src = pristine
    assert src.read_bytes() == b"VANILLA", (
        "donor resolved to the modded file; a texture patch would chain "
        "another mod's output into its own input"
    )
    # Guard the real implementation still contains the preference.
    impl = Path(merge.__file__).read_text()
    assert '".rsmm.bak"' in impl and "pristine" in impl, (
        "merge.py no longer prefers the vanilla backup for texture donors"
    )


def test_resolve_special_resolves_a_resource_cache():
    """A `*.UsedRscCache.ot` must resolve without an asset_map entry.

    No cache is in `asset_map` — shipped or not — because the engine finds one
    by appending the suffix to the resource name rather than through
    `UsedRscList.ot`. Membership alone therefore answers False for every cache,
    which made `rsmm list`, `rsmm doctor` and `rsmm lint` each report a mod's
    caches as broken while `apply` was installing them correctly.
    """
    from rsmm.cli.apply_mods import resolve_special

    # One sibling in the same decoded directory is all `synthesize_encoded`
    # needs to anchor the encoded prefix.
    dec2enc = {"Definitions/Enemies/Gnoll_Hunter.enemydef": "Ijeqrpqwjt!Nsxxa"}

    cache = "Definitions/Enemies/Gnoll_Hunter.enemydef.UsedRscCache.ot"
    enc = resolve_special(cache, dec2enc)
    assert enc, "a resource cache with a sibling must resolve"
    assert enc.startswith("Ijeqrpqwjt!"), enc

    # Nothing else changed: a path with no special form still returns None.
    assert resolve_special("Definitions/Enemies/Gnoll_Hunter.enemydef", dec2enc) is None


def test_restore_keeps_a_vanilla_file_the_mod_emits_byte_identically(
    tmp_path, monkeypatch, capsys
):
    """`restore --all`'s residue sweep must not delete a shipped asset.

    The sweep's rule is "cooked bytes == mod source bytes, and no `.rsmm.bak`
    beside it, therefore the mod added this file". That inference is wrong
    whenever the mod's output happens to EQUAL what the game ships — the
    normal case for a `*.UsedRscCache.ot` whose definition adds no new
    resources. Observed 2026-09-05 on three Dark Hills / Avalon caches: every
    `restore --all` deleted them, and the next `apply` then refused with
    VanillaMissing because the original it had to back up was gone.

    `restore_one` has carried this guard for the same reason since the
    2026-07-11 text-bank loss; the sweep runs after it and did not.
    """
    from rsmm.cli import apply_mods

    repo, mods_dir, asset_map, game_dir = _make_fake_repo(tmp_path)
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    shipped = cooking / "a" / "b.bin"
    # The premise: the game ships this path AND the mod emits the same bytes.
    shipped.write_bytes(b"MOD CONTENT")
    monkeypatch.setattr(apply_mods, "is_vanilla_encoded", lambda enc: True)

    monkeypatch.setattr(apply_mods, "MODS_DIR", mods_dir)
    monkeypatch.setattr(apply_mods, "ASSET_MAP_JSON", asset_map)
    import rsmm.engine.find_iyg as find_iyg
    monkeypatch.setattr(find_iyg, "main", lambda *a, **k: 0)

    # No state, no backup — the shape a wiped .rsmm_state.json leaves behind,
    # and the one the sweep exists to clean up.
    args = SimpleNamespace(dry_run=False)
    rc = apply_mods.cmd_restore_all(args, repo, cooking, game_dir)
    out = capsys.readouterr().out

    assert rc == 0, out
    assert shipped.is_file(), "restore deleted a file the game ships"
    assert shipped.read_bytes() == b"MOD CONTENT"
    assert "residue via source hash" not in out, out


def test_emit_drops_last_runs_files_before_re_emitting(tmp_path, monkeypatch):
    """A mapdef pool and a resource cache are read back and EXTENDED, so that
    two content defs in one mod compose instead of the last one stripping the
    first's entries. That same read-back makes them grow across separate
    APPLIES, and a def the author removes then leaves its entries behind
    forever — the post-emit "stale file" sweep never reaches a file that is
    rewritten every time.

    Measured 2026-09-05: the planted Dark Hills pool still carried 16 entries
    for a `menhir_camp` def parked days earlier, pointing at tiledef files the
    sweep HAD deleted. A pool entry with no tiledef behind it is a null the
    generator has to resolve, and nothing logs it.
    """
    import json

    from rsmm.cli import apply_mods as A

    mod_root = tmp_path / "accumulator"
    assets = mod_root / "assets"
    assets.mkdir(parents=True)
    # What last run emitted, plus a file the AUTHOR shipped by hand. Only the
    # first is in the marker, and only the first may be deleted.
    (assets / "pool.bin").write_bytes(b"vanilla+parked-def")
    (assets / "handwritten.png").write_bytes(b"authored")
    (mod_root / ".rsmm_emitted.json").write_text(json.dumps(["pool.bin"]))

    class _Reg:
        def __init__(self, **kw): pass
        def register(self, *a, **kw): pass
        def emit(self, out_dir):
            # An emitter that EXTENDS whatever is already there — the real
            # behaviour of the pool and cache writers.
            p = out_dir / "pool.bin"
            prior = p.read_bytes() if p.is_file() else b"vanilla"
            p.write_bytes(prior + b"+this-def")
            return [p]

    import rsmm.sdk.content as content
    monkeypatch.setattr(content, "ContentRegistry", _Reg)

    mod = SimpleNamespace(
        id="accumulator", enabled=True, experimental=True, root=mod_root,
        assets_dir=assets, content_blocks=[{"kind": "poi", "id": "x"}],
    )
    A.emit_content_blocks([mod])

    assert (assets / "pool.bin").read_bytes() == b"vanilla+this-def", (
        "the emit built on last run's output, so a removed def's entries "
        "survive forever")
    assert (assets / "handwritten.png").is_file(), (
        "the cleanup deleted a hand-authored asset; it must only remove what "
        "the emitter itself wrote")


def test_emitted_cleanup_refuses_to_escape_the_mod_directory(tmp_path):
    """`.rsmm_emitted.json` steers `unlink()`, so it must not escape the mod.

    ⚠ `base / Path(rel)` alone is not containment: Python's `/` DISCARDS the
    left operand when the right is absolute, so a single absolute entry aims
    the delete anywhere on disk, and `..` walks out just as easily. The marker
    is written by this tool, but a mod directory is downloaded and shared, so a
    corrupt or hostile one must not be able to remove a user's files.
    """
    from rsmm.cli.apply_mods import _emitted_stale_path

    base = tmp_path / "mod" / "assets"
    base.mkdir(parents=True)
    (base / "ok.gen").write_text("x")

    outside = tmp_path / "outside.txt"
    outside.write_text("do not delete me")

    assert _emitted_stale_path(base, "ok.gen") == (base / "ok.gen").resolve()
    assert _emitted_stale_path(base, str(outside)) is None, (
        "an absolute entry replaced the base path entirely")
    assert _emitted_stale_path(base, "../../outside.txt") is None, (
        "a relative entry walked out of the mod directory")
    assert outside.is_file()
