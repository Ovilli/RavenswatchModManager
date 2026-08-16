"""Tests for rsmm doctor health checks."""

from __future__ import annotations

import json

from rsmm.cli.doctor import (
    Result,
    check_asset_map,
    check_compat_graph,
    check_exe_hash,
    check_game_install,
    check_mods,
    check_patch_conflicts,
    check_state,
    check_usedrsclist,
)


def test_result_kind_must_be_valid():
    r = Result("OK", "test")
    assert r.kind == "OK"
    r = Result("WARN", "test", "detail")
    assert r.detail == "detail"


def test_check_game_install_missing_dir(tmp_path):
    fake = tmp_path / "nonexistent"
    results = check_game_install(fake)
    assert any(r.kind == "FAIL" for r in results)


def test_check_game_install_ok(tmp_path):
    cooking = tmp_path / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    results = check_game_install(tmp_path)
    assert all(r.kind == "OK" for r in results)


def test_check_asset_map_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("rsmm.cli.doctor.ASSET_MAP_JSON", tmp_path / "missing.json")
    results = check_asset_map(tmp_path)
    assert any(r.kind == "FAIL" for r in results)


def test_check_state_corrupt(tmp_path):
    cooking = tmp_path / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    state = cooking / ".rsmm_state.json"
    state.write_text("not json", encoding="utf-8")
    results = check_state(tmp_path)
    assert any(r.kind == "FAIL" for r in results)


def test_check_state_no_state_file(tmp_path):
    results = check_state(tmp_path)
    assert any("no applier state" in r.label for r in results)


def test_check_state_has_active(tmp_path):
    cooking = tmp_path / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    state = cooking / ".rsmm_state.json"
    state.write_text(json.dumps({"active": {"a\\b.bin": "TestMod"}}), encoding="utf-8")
    results = check_state(tmp_path)
    assert any("1 active override" in r.label for r in results)


def _state_entry(game_dir, enc, content: bytes | None, src_sha: str,
                 orig_sha: str = "") -> None:
    """Write a state file with one active entry; optionally materialize the
    installed file with `content`."""
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True, exist_ok=True)
    if content is not None:
        dest = cooking.joinpath(*enc.split("\\"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    (cooking / ".rsmm_state.json").write_text(json.dumps({
        "version": 1,
        "active": {enc: {"mod": "TestMod",
                         "src_sha256": src_sha,
                         "orig_sha256": orig_sha}},
    }), encoding="utf-8")


def test_check_state_flags_missing_override(tmp_path):
    _state_entry(tmp_path, "a\\b.bin", None, "0" * 64)
    results = check_state(tmp_path)
    assert any(r.kind == "WARN" and "missing on disk" in r.label for r in results)


def test_check_state_flags_hash_drift(tmp_path):
    # Installed bytes don't match the recorded mod hash -> drift WARN.
    _state_entry(tmp_path, "a\\b.bin", b"VANILLA CONTENT", "f" * 64)
    results = check_state(tmp_path)
    assert any(r.kind == "WARN" and "no longer match" in r.label for r in results)


def test_check_state_clean_when_hash_matches(tmp_path):
    import hashlib
    content = b"MOD CONTENT"
    _state_entry(tmp_path, "a\\b.bin", content,
                 hashlib.sha256(content).hexdigest())
    results = check_state(tmp_path)
    assert all(r.kind == "OK" for r in results)


def test_check_state_flags_lost_backup(tmp_path):
    # orig_sha256 recorded (an original was backed up) but no .rsmm.bak.
    import hashlib
    content = b"MOD CONTENT"
    _state_entry(tmp_path, "a\\b.bin", content,
                 hashlib.sha256(content).hexdigest(), orig_sha="a" * 64)
    results = check_state(tmp_path)
    assert any(r.kind == "WARN" and ".rsmm.bak" in r.label for r in results)


def _write_usedrsc(game_dir, lines: list[str], suffix: str = "") -> None:
    p = game_dir / "DarkTalesResources" / ("UsedRscList.ot" + suffix)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(["1", *lines]) + "\n", encoding="utf-8")


def test_check_usedrsclist_missing(tmp_path):
    results = check_usedrsclist(tmp_path)
    assert any(r.kind == "WARN" and "not found" in r.label for r in results)


def test_check_usedrsclist_aligned_ok(tmp_path):
    _write_usedrsc(tmp_path, ["t", "n", "p"] * 4)
    results = check_usedrsclist(tmp_path)
    assert all(r.kind == "OK" for r in results)


def test_check_usedrsclist_desync_fails(tmp_path):
    _write_usedrsc(tmp_path, ["t", "n", "p", "orphan"])
    results = check_usedrsclist(tmp_path)
    assert any(r.kind == "FAIL" and "desync" in r.label for r in results)


def test_check_usedrsclist_reports_custom_records(tmp_path):
    _write_usedrsc(tmp_path, ["t", "n", "p"] * 3)
    _write_usedrsc(tmp_path, ["t", "n", "p"] * 2, suffix=".rsmm.bak")
    results = check_usedrsclist(tmp_path)
    assert any("1 custom resource record" in r.label for r in results)


def test_check_usedrsclist_shorter_than_backup_warns(tmp_path):
    _write_usedrsc(tmp_path, ["t", "n", "p"])
    _write_usedrsc(tmp_path, ["t", "n", "p"] * 2, suffix=".rsmm.bak")
    results = check_usedrsclist(tmp_path)
    assert any(r.kind == "WARN" and "SHORTER" in r.label for r in results)


def test_check_exe_hash_no_patterns(tmp_path, monkeypatch):
    monkeypatch.setattr("rsmm.cli.doctor.DATA_DIR", tmp_path)
    results = check_exe_hash(tmp_path)
    assert any("function_patterns.json missing" in r.label for r in results)


def test_check_mods_no_mods_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("rsmm.cli.doctor.MODS_DIR", tmp_path / "mods")
    results = check_mods()
    assert any("mods/ missing" in r.label for r in results)


def test_check_patch_conflicts_no_patches():
    results = check_patch_conflicts()
    assert not results or all(r.kind != "FAIL" for r in results)


def _write_mod(mods: object, mod_id: str, body: str) -> None:
    from pathlib import Path
    d = Path(mods) / mod_id
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text(
        f'[mod]\nid = "{mod_id}"\nname = "{mod_id}"\nversion = "1.0.0"\n{body}',
        encoding="utf-8",
    )


def test_compat_graph_no_mods(tmp_path, monkeypatch):
    monkeypatch.setenv("RSMM_MODS_DIR", str(tmp_path / "mods"))
    rs = check_compat_graph()
    assert len(rs) == 1 and rs[0].kind == "OK"


def test_compat_graph_clean(tmp_path, monkeypatch):
    mods = tmp_path / "mods"
    _write_mod(mods, "core", "")
    _write_mod(mods, "user", 'requires = ["core >=1.0 <2.0"]\n')
    monkeypatch.setenv("RSMM_MODS_DIR", str(mods))
    rs = check_compat_graph()
    assert all(r.kind == "OK" for r in rs)


def test_compat_graph_recommend_warns_not_fails(tmp_path, monkeypatch):
    mods = tmp_path / "mods"
    _write_mod(mods, "user", 'recommends = ["sidekick >=1.0"]\n')  # sidekick absent
    monkeypatch.setenv("RSMM_MODS_DIR", str(mods))
    rs = check_compat_graph()
    assert any(r.kind == "WARN" and "missing-recommend" in r.label for r in rs)
    assert all(r.kind != "FAIL" for r in rs)


def test_compat_graph_missing_requires_fails(tmp_path, monkeypatch):
    mods = tmp_path / "mods"
    _write_mod(mods, "user", 'requires = ["missing-lib >=2.0"]\n')
    monkeypatch.setenv("RSMM_MODS_DIR", str(mods))
    rs = check_compat_graph()
    assert any(r.kind == "FAIL" and "missing-dep" in r.label for r in rs)


# ---------------------------------------------------------------- loader tree

def _fake_install(tmp_path):
    (tmp_path / "DarkTalesResources" / "_Cooking").mkdir(parents=True)
    return tmp_path


def test_loader_runtime_tree_missing_is_reported(tmp_path, monkeypatch):
    """A planted DLL with no <game>/rsmm/lib is a non-working loader.

    Regression: doctor called this install healthy, because it only ever
    looked at winhttp.dll — but the Lua SDK is disk-loaded, so every Lua mod
    silently failed to load.
    """
    from rsmm.cli import doctor as doc

    game = _fake_install(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "winhttp.dll").write_bytes(b"loader-bytes")
    (game / "winhttp.dll").write_bytes(b"loader-bytes")
    monkeypatch.setattr(doc, "DIST_DIR", dist)

    results = doc.check_loader(game)
    codes = {r.code for r in results}
    assert "loader.runtime-missing" in codes
    runtime = next(r for r in results if r.code == "loader.runtime-missing")
    assert runtime.fix is not None
    assert runtime.fix.argv == ["install-loader"]


def test_loader_complete_install_is_ok(tmp_path, monkeypatch):
    from rsmm.cli import doctor as doc

    game = _fake_install(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "winhttp.dll").write_bytes(b"loader-bytes")
    (game / "winhttp.dll").write_bytes(b"loader-bytes")
    lib = game / "rsmm" / "lib"
    lib.mkdir(parents=True)
    for name in doc._LOADER_LIB_FILES:
        # Some entries are submodules under rsmm/, not flat files.
        (lib / name).parent.mkdir(parents=True, exist_ok=True)
        (lib / name).write_text("-- sdk")
    (game / "rsmm" / "data").mkdir()
    (game / "rsmm" / "data" / "function_patterns.json").write_text("{}")
    monkeypatch.setattr(doc, "DIST_DIR", dist)

    assert all(r.kind == "OK" for r in doc.check_loader(game))


def test_loader_detects_replaced_dll_by_hash(tmp_path, monkeypatch):
    """Steam's stock winhttp.dll must be caught even at a matching size."""
    from rsmm.cli import doctor as doc

    game = _fake_install(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "winhttp.dll").write_bytes(b"ours-1234")
    (game / "winhttp.dll").write_bytes(b"steam-999")  # same length, other bytes
    monkeypatch.setattr(doc, "DIST_DIR", dist)

    results = doc.check_loader(game)
    stale = next(r for r in results if r.code == "loader.stale-dll")
    assert stale.kind == "WARN"
    assert stale.fix is not None and stale.fix.argv == ["install-loader"]


# ---------------------------------------------------------------- loader flags

def test_dangerous_loader_flag_is_flagged(tmp_path, monkeypatch):
    from rsmm.cli import doctor as doc

    monkeypatch.delenv("RSMM_ENABLE_ITEM_INJECT", raising=False)
    (tmp_path / "rsmm_loader_flags.json").write_text(
        json.dumps(["RSMM_ENABLE_GAMEPLAY_EVENTS", "RSMM_ENABLE_ITEM_INJECT"]))
    results = doc.check_loader_flags(tmp_path)
    assert any(r.code == "loaderflags.dangerous"
               and "ITEM_INJECT" in r.label for r in results)


def test_safe_loader_flags_are_ok(tmp_path, monkeypatch):
    from rsmm.cli import doctor as doc

    for name in doc._DANGEROUS_FLAGS:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "rsmm_loader_flags.json").write_text(
        json.dumps(["RSMM_ENABLE_GAMEPLAY_EVENTS"]))
    assert all(r.kind == "OK" for r in doc.check_loader_flags(tmp_path))


# ---------------------------------------------------------------- crash dumps

def test_recent_crash_dump_warns_old_one_does_not(tmp_path):
    import os
    import time

    from rsmm.cli import doctor as doc

    reports = tmp_path / "CrashDB" / "reports"
    reports.mkdir(parents=True)
    dump = reports / "recent.dmp"
    dump.write_bytes(b"x")
    assert doc.check_crash_dumps(tmp_path)[0].kind == "WARN"

    old = time.time() - 60 * 60 * 24 * 30
    os.utime(dump, (old, old))
    # A month-old dump is history — reading it as "the current crash" is how
    # a debugging session gets wasted.
    assert doc.check_crash_dumps(tmp_path)[0].kind == "OK"


# ------------------------------------------------------------- launch options

APP = "2071280"


def _vdf(*apps: tuple[str, str]) -> str:
    """A localconfig fragment: one `apps` map holding (app_id, launch_options)."""
    out = ['"apps"', "{"]
    for app_id, opts in apps:
        out += [f'\t"{app_id}"', "\t{", f'\t\t"LaunchOptions"\t\t"{opts}"',
                '\t\t"LastPlayed"\t\t"0"', "\t}"]
    out.append("}")
    return "\n".join(out) + "\n"


def test_orphaned_launch_value_detected(tmp_path):
    """The exact corruption a truncating rewrite leaves behind."""
    from rsmm.cli.doctor import _has_orphaned_launch_value

    good = tmp_path / "good.vdf"
    good.write_text(_vdf((APP, "")))
    assert _has_orphaned_launch_value(good, APP) is False

    corrupt = tmp_path / "bad.vdf"
    corrupt.write_text(
        '"apps"\n{\n\t"2071280"\n\t{\n'
        '\t\t"LaunchOptions"\t\t""winhttp=n,b\\" %command%"\n\t}\n}\n')
    assert _has_orphaned_launch_value(corrupt, APP) is True


def test_another_games_launch_options_are_not_ravenswatchs(tmp_path):
    """A neighbouring app's options must not make ours look corrupt.

    Regression: the scan ran over the whole file, so one unrelated title with
    `gamemoderun %command%` turned Ravenswatch's correctly-cleared options into
    a FAIL telling the user to repair a file that was fine. `restore` clears
    those options on purpose, so this fired on a completely normal state.
    """
    from rsmm.cli.doctor import _has_orphaned_launch_value

    vdf = tmp_path / "localconfig.vdf"
    vdf.write_text(_vdf(("440", "gamemoderun %command%"), (APP, "")))
    assert _has_orphaned_launch_value(vdf, APP) is False

    # ...and our own residue is still caught when a neighbour is present.
    vdf.write_text(
        '"apps"\n{\n\t"440"\n\t{\n\t\t"LaunchOptions"\t\t"gamemoderun %command%"\n\t}\n'
        '\t"2071280"\n\t{\n\t\t"LaunchOptions"\t\t""winhttp=n,b\\" %command%"\n\t}\n}\n')
    assert _has_orphaned_launch_value(vdf, APP) is True


# ------------------------------------------------------------------- registry

def test_every_check_has_a_unique_name():
    from rsmm.cli.doctor import _checks

    names = [c.name for c in _checks()]
    assert len(names) == len(set(names))


def test_a_crashing_check_becomes_a_finding(tmp_path):
    """One exploding check must not cost the user the other twelve."""
    from rsmm.cli.doctor import Check, _run_check

    def boom(_game_dir):
        raise RuntimeError("kaboom")

    results = _run_check(Check("boom", "boom", boom), tmp_path)
    assert len(results) == 1
    assert results[0].kind == "WARN"
    assert "kaboom" in results[0].detail
    assert results[0].code == "boom.crashed"


def test_destructive_fix_needs_force(tmp_path, monkeypatch):
    from rsmm.cli import doctor as doc

    called = []
    monkeypatch.setattr(doc.subprocess, "run",
                        lambda *a, **k: called.append(a) or None)
    r = doc.Result("FAIL", "boom", code="x",
                   fix=doc.Fix("rsmm restore --all", ["restore", "--all"],
                               risk="destructive"))

    outcome, detail = doc._apply_fix(r, tmp_path, force=False)
    assert outcome == "skipped"
    assert "--force" in detail
    assert called == [], "destructive repair must not run without --force"


def test_manual_fix_is_never_executed(tmp_path, monkeypatch):
    from rsmm.cli import doctor as doc

    called = []
    monkeypatch.setattr(doc.subprocess, "run",
                        lambda *a, **k: called.append(a) or None)
    r = doc.Result("WARN", "boom", code="x",
                   fix=doc.Fix("close Steam", [], manual="close Steam first"))

    outcome, _detail = doc._apply_fix(r, tmp_path, force=True)
    assert outcome == "skipped"
    assert called == []


def test_json_report_shape():
    from rsmm.cli.doctor import Fix, Result, _as_json

    sections = [
        ("loader DLL", [
            Result("OK", "fine"),
            Result("WARN", "broken", "detail", code="loader.stale-dll",
                   fix=Fix("rsmm install-loader", ["install-loader"])),
        ]),
    ]
    payload = _as_json(sections, [])
    assert payload["ok"] is True          # WARN alone doesn't fail the run
    assert payload["counts"] == {"ok": 1, "warn": 1, "fail": 0}
    entry = payload["sections"][0]["results"][1]
    assert entry["code"] == "loader.stale-dll"
    assert entry["fix"]["automatic"] is True
    assert entry["fix"]["argv"] == ["install-loader"]


def test_game_dir_is_not_appended_to_commands_that_reject_it(tmp_path, monkeypatch):
    """`rsmm run` has no --game-dir; appending it makes the repair always fail."""
    from rsmm.cli import doctor as doc

    seen = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **_kw):
        seen["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(doc.subprocess, "run", fake_run)
    r = doc.Result("WARN", "opts", code="launchopts.no-override",
                   fix=doc.Fix("rsmm run --set-launch-options --no-launch",
                               ["run", "--set-launch-options", "--no-launch"],
                               accepts_game_dir=False))

    outcome, _detail = doc._apply_fix(r, tmp_path / "elsewhere", force=False)
    assert outcome == "fixed"
    assert "--game-dir" not in seen["cmd"]


def test_game_dir_is_appended_for_commands_that_take_it(tmp_path, monkeypatch):
    from rsmm.cli import doctor as doc

    seen = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(doc.subprocess, "run",
                        lambda cmd, **_kw: (seen.update(cmd=cmd), _Proc())[1])
    r = doc.Result("WARN", "drift", code="state.drifted",
                   fix=doc.Fix("rsmm apply", ["apply"]))

    outcome, _detail = doc._apply_fix(r, tmp_path / "elsewhere", force=False)
    assert outcome == "fixed"
    assert "--game-dir" in seen["cmd"]
