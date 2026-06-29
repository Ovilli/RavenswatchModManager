"""
rsmm doctor — system health check.

Walks every layer of the manager and reports OK / WARN / FAIL:

  - asset map exists + matches UsedRscList freshness
  - game install reachable + cooked tree present
  - loader DLL built + installed into game dir
  - each mod's manifest parses + every asset path resolves
  - cross-mod conflicts (raw file overlap, [[patch]] same-field hits)
  - applier state file vs. on-disk reality

Exit code: 0 if every check passed, 1 if any FAIL, 2 if argv invalid.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from rsmm.cli.apply_mods import _LANG_SUFFIXES, is_skippable_asset
from rsmm.cli.merge import _ranked, _toml_load, collect_patches
from rsmm.engine.asset_map import decoded_to_encoded
from rsmm.engine.hashing import sha256_file
from rsmm.engine.paths import (
    ASSET_MAP_JSON,
    COOKING_SUBDIR,
    DATA_DIR,
    DIST_DIR,
    MODS_DIR,
    game_fingerprint,
    load_stored_fingerprint,
)
from rsmm.engine.paths import (
    DEFAULT_GAME_DIR as DEFAULT_GAME,
)


@dataclass
class Result:
    kind: str   # OK | WARN | FAIL
    label: str
    detail: str = ""


def emit(r: Result) -> None:
    glyph = {"OK": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}[r.kind]
    print(f"  {glyph} {r.label}")
    if r.detail:
        for line in r.detail.splitlines():
            print(f"         {line}")


def check_asset_map(game_dir: Path) -> list[Result]:
    out: list[Result] = []
    if not ASSET_MAP_JSON.exists():
        return [Result("FAIL", "asset_map.json missing",
                       "Run: ./rsmm rebuild-asset-map")]
    am_mtime = ASSET_MAP_JSON.stat().st_mtime
    out.append(Result("OK", f"asset_map.json ({ASSET_MAP_JSON.stat().st_size:,} bytes)"))
    used = game_dir / "DarkTalesResources" / "UsedRscList.ot"
    if used.exists() and used.stat().st_mtime > am_mtime + 1:
        out.append(Result("WARN", "UsedRscList.ot newer than asset_map.json",
                          "Game may have updated. Run: ./rsmm rebuild-asset-map"))
    else:
        out.append(Result("OK", "asset_map.json is fresh"))
    return out


def check_game_update(game_dir: Path) -> list[Result]:
    """Warn if the game binary or resource list changed since last apply."""
    current = game_fingerprint(game_dir)
    stored = load_stored_fingerprint(game_dir)
    if stored is None:
        return [Result("OK", "no stored game version (first run)")]
    if current != stored:
        return [Result("WARN", "game version changed since last apply",
                       "Run: rsmm apply  (will auto-recover)")]
    return [Result("OK", "game version unchanged")]


def _is_writable(d: Path) -> bool:
    """Probe-write a temp file in `d`. os.access(W_OK) lies on Windows for
    dirs, so actually attempt the write rsmm's apply will make."""
    probe = d / ".rsmm_write_probe"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def check_game_install(game_dir: Path) -> list[Result]:
    if not game_dir.exists():
        return [Result("FAIL", f"game_dir not found: {game_dir}",
                       "Pass --game-dir to override default.")]
    cooking = game_dir / COOKING_SUBDIR
    if not cooking.is_dir():
        return [Result("FAIL", f"_Cooking missing under {game_dir}",
                       f"Expected: {cooking}")]
    out = [Result("OK", f"game install: {game_dir}")]
    # apply writes into _Cooking — a read-only/locked tree fails mid-apply
    # and leaves the install half-modified. Catch it before apply runs.
    if not _is_writable(cooking):
        out.append(Result("FAIL", f"_Cooking is not writable: {cooking}",
                          "Close the game if it's running, then check folder "
                          "permissions (or run with the rights to write the "
                          "install). apply WILL fail mid-write otherwise."))
    return out


def check_loader(game_dir: Path) -> list[Result]:
    out: list[Result] = []
    dll = DIST_DIR / "winhttp.dll"
    if not dll.exists():
        out.append(Result("WARN", "loader DLL not built (dist/winhttp.dll missing)",
                          "Run: ./rsmm build  (or skip if not using Lua mods)"))
    else:
        out.append(Result("OK", f"loader DLL built ({dll.stat().st_size:,} bytes)"))
    installed = game_dir / "winhttp.dll"
    if installed.exists():
        sz = installed.stat().st_size
        if dll.exists() and installed.stat().st_size == dll.stat().st_size:
            out.append(Result("OK", f"loader installed in game dir ({sz:,} bytes)"))
        else:
            out.append(Result("WARN",
                              "game dir has winhttp.dll but size != built DLL",
                              "Could be Steam/Wine's stock dll. "
                              "Run: ./rsmm install-loader"))
    else:
        out.append(Result("WARN", "loader not installed in game dir",
                          "Run: ./rsmm install-loader (only needed for Lua mods)"))
    return out


def check_mods() -> list[Result]:
    out: list[Result] = []
    if not MODS_DIR.is_dir():
        return [Result("WARN", "mods/ missing")]
    try:
        dec2enc = decoded_to_encoded()
    except (OSError, ValueError) as e:
        return [Result("FAIL", "cannot load asset_map.json",
                       f"{e}\nRun: ./rsmm rebuild-asset-map")]
    found = 0
    enabled = 0
    file_owners: dict[str, list[str]] = {}
    for entry in sorted(MODS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        mf = entry / "manifest.toml"
        if not mf.exists():
            out.append(Result("FAIL", f"{entry.name}: missing manifest.toml"))
            continue
        found += 1
        try:
            t = _toml_load(mf)
        except OSError as e:
            out.append(Result("FAIL", f"{entry.name}: bad manifest", str(e)))
            continue
        mod_meta = t.get("mod", {})
        raw_enabled = mod_meta.get("enabled", True)
        is_on = (
            raw_enabled if isinstance(raw_enabled, bool)
            else str(raw_enabled).lower() in ("1", "true", "yes", "on")
        )
        if is_on:
            enabled += 1
        # Raw asset paths
        assets = entry / "assets"
        if assets.is_dir():
            for f in assets.rglob("*"):
                if not f.is_file():
                    continue
                dec = f.relative_to(assets).as_posix()
                # _root/ files bypass asset_map (top-level).
                if dec.startswith("_root/") or "/_root/" in dec:
                    continue
                if is_skippable_asset(dec):
                    continue
                # Translation Lang* files are special-cased in apply_mods.
                if dec.endswith(_LANG_SUFFIXES):
                    continue
                if dec not in dec2enc:
                    # Only surface for mods the user has actually enabled
                    # in the manifest — disabled mods can't break a run, so
                    # noisy warnings about them are user-hostile.
                    if is_on:
                        out.append(Result("WARN",
                                          f"{entry.name}: asset path not in asset_map",
                                          dec))
                if is_on:
                    file_owners.setdefault(dec, []).append(entry.name)
    out.append(Result("OK", f"mods discovered: {found} ({enabled} enabled)"))
    for path, owners in file_owners.items():
        if len(owners) > 1:
            out.append(Result("WARN",
                              f"raw-file conflict on {path}",
                              "owners: " + ", ".join(owners) +
                              "  (last alphabetical wins; "
                              "use [[patch]] blocks for per-field merge)"))
    return out


def check_patch_conflicts() -> list[Result]:
    out: list[Result] = []
    patches = collect_patches()
    if not patches:
        return []
    by_key: dict[tuple, dict[str, object]] = {}
    for p in _ranked(patches):
        if p.kind == "stat":
            for fn in p.data:
                if fn == "name":
                    continue
                key = ("stat", str(p.data.get("name", "")).lower(), fn)
                by_key.setdefault(key, {})[p.mod_id] = p.data[fn]
        elif p.kind == "texture":
            key = ("texture", str(p.data.get("target", "")).replace("\\", "/"))
            by_key.setdefault(key, {})[p.mod_id] = p.data.get("donor")
        elif p.kind in {"url", "text"}:
            key = (p.kind,) + tuple(
                str(p.data.get(k, "")) for k in
                (["field"] if p.kind == "url" else ["bank", "lang", "key"]))
            by_key.setdefault(key, {})[p.mod_id] = p.data.get("value")
    n_total = sum(1 for v in by_key.values() if len({repr(x) for x in v.values()}) > 1)
    if n_total == 0:
        out.append(Result("OK", f"{len(patches)} [[patch]] block(s), no same-field conflicts"))
    else:
        out.append(Result("WARN",
                          f"{n_total} same-field conflict(s) across [[patch]] blocks",
                          "Resolve with load_order in mod manifest; "
                          "or accept that the later mod wins."))
        for key, owners in by_key.items():
            if len({repr(v) for v in owners.values()}) > 1:
                out.append(Result("WARN",
                                  ".".join(str(k) for k in key),
                                  ", ".join(f"{m}={v}" for m, v in owners.items())))
    return out


def check_exe_hash(game_dir: Path) -> list[Result]:
    """Hash the game executable and warn if function_patterns.json is stale."""
    patterns = DATA_DIR / "function_patterns.json"
    if not patterns.exists():
        return [Result("WARN", "function_patterns.json missing",
                       "Run: python scripts/gen_function_patterns.py")]

    exe_candidates = [
        game_dir / "Ravenswatch.exe",
        game_dir / "Ravenswatch-Win64-Shipping.exe",
        game_dir / "Ravenswatch" / "Binaries" / "Win64" / "Ravenswatch-Win64-Shipping.exe",
    ]
    exe = next((e for e in exe_candidates if e.exists()), None)
    if not exe:
        return [Result("WARN", "game executable not found (may be on different OS)",
                       "Cannot verify pattern DB freshness without the game exe")]

    patterns_mtime = patterns.stat().st_mtime
    exe_mtime = exe.stat().st_mtime

    exe_hash = sha256_file(exe)[:12]
    exe_size = exe.stat().st_size
    result = [Result("OK", f"game exe: {exe.name} ({exe_size:,} bytes, hash={exe_hash})")]

    if exe_mtime > patterns_mtime + 1:
        result.append(Result("WARN", "game exe newer than function_patterns.json",
                             "Game may have updated. Run: python scripts/gen_function_patterns.py"))
    else:
        result.append(Result("OK", "function_patterns.json is fresh relative to game exe"))

    return result


def check_state(game_dir: Path) -> list[Result]:
    state = game_dir / COOKING_SUBDIR / ".rsmm_state.json"
    if not state.exists():
        return [Result("OK", "no applier state on disk (nothing applied yet)")]
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [Result("FAIL", "state file is corrupt",
                       f"{e}\nRun: ./rsmm restore --all  (recovers via backups + "
                       "residue sweep), then: ./rsmm apply")]
    active = data.get("active", {}) or {}
    out = [Result("OK", f"applier state: {len(active)} active override(s)")]

    # State-vs-disk desync: state says a file is overridden, but the
    # installed copy is gone (game update / manual delete) or its bytes no
    # longer match the recorded mod hash (Steam "verify integrity" restored
    # vanilla content). Either way `rsmm apply` self-heals.
    from rsmm.cli.apply_mods import BACKUP_SUFFIX, ROOT_PREFIX, encoded_to_dest
    cooking = game_dir / COOKING_SUBDIR
    missing: list[str] = []
    drifted: list[str] = []
    lost_backups: list[str] = []
    for enc, entry in active.items():
        if not isinstance(entry, dict):
            continue
        try:
            dest = encoded_to_dest(enc, cooking, game_dir)
        except ValueError:
            continue
        if not dest.exists():
            missing.append(enc)
            continue
        want = entry.get("src_sha256")
        if want and sha256_file(dest) != want:
            drifted.append(enc)
        if entry.get("orig_sha256") and not enc.startswith(ROOT_PREFIX):
            bak = dest.parent / (dest.name + BACKUP_SUFFIX)
            if not bak.exists():
                lost_backups.append(enc)

    def _listing(items: list[str], cap: int = 5) -> str:
        shown = "\n".join(f"- {e}" for e in items[:cap])
        if len(items) > cap:
            shown += f"\n... and {len(items) - cap} more"
        return shown

    if missing:
        out.append(Result("WARN",
                          f"{len(missing)} override(s) in state but missing on disk",
                          _listing(missing) + "\nRun: ./rsmm apply  (re-installs them)"))
    if drifted:
        out.append(Result("WARN",
                          f"{len(drifted)} installed override(s) no longer match "
                          "their mod source hash",
                          _listing(drifted) +
                          "\nLikely a Steam file verify or game update. "
                          "Run: ./rsmm apply  (re-copies stale files)"))
    if lost_backups:
        out.append(Result("WARN",
                          f"{len(lost_backups)} override(s) lost their .rsmm.bak backup",
                          _listing(lost_backups) +
                          "\nRestore for these falls back to the residue sweep; "
                          "verify game files in Steam to be safe."))
    if not (missing or drifted or lost_backups) and active:
        out.append(Result("OK", "state matches installed files (hash-verified)"))
    return out


def check_usedrsclist(game_dir: Path) -> list[Result]:
    """Sanity-check the engine's master resource manifest.

    The engine parses UsedRscList.ot in fixed 3-line records; a record-count
    desync (e.g. a partial write or hand-edit) hard-crashes the game at boot.
    Also reports how many custom record lines rsmm has registered on top of
    the pristine backup, and flags drift that rsmm did not produce."""
    from rsmm.cli.apply_mods import BACKUP_SUFFIX, USEDRSCLIST_REL, _read_usedrsclist
    path = game_dir / USEDRSCLIST_REL
    if not path.exists():
        return [Result("WARN", f"UsedRscList.ot not found: {path}",
                       "Game install may be incomplete; verify files in Steam.")]
    try:
        _header, lines = _read_usedrsclist(path)
    except (OSError, ValueError) as e:
        return [Result("FAIL", "UsedRscList.ot unreadable", str(e))]
    out: list[Result] = []
    if len(lines) % 3 != 0:
        out.append(Result("FAIL",
                          f"UsedRscList.ot record desync ({len(lines)} lines, "
                          "not a multiple of 3) — the game WILL crash at boot",
                          "Run: ./rsmm restore --all  (restores the pristine "
                          "manifest), or verify game files in Steam."))
    bak = path.with_name(path.name + BACKUP_SUFFIX)
    if bak.exists():
        try:
            _bh, base = _read_usedrsclist(bak)
        except (OSError, ValueError) as e:
            return out + [Result("WARN", "UsedRscList.ot backup unreadable", str(e))]
        extra = len(lines) - len(base)
        if extra < 0:
            out.append(Result("WARN",
                              "UsedRscList.ot is SHORTER than its rsmm backup",
                              "The live manifest lost lines rsmm didn't remove "
                              "(game update mid-state?). Run: ./rsmm apply"))
        elif extra:
            out.append(Result("OK",
                              f"UsedRscList.ot: {extra // 3} custom resource "
                              "record(s) registered by rsmm"))
        else:
            out.append(Result("OK", "UsedRscList.ot matches pristine backup "
                                    "(no custom registrations active)"))
    elif not out:
        out.append(Result("OK", f"UsedRscList.ot OK ({len(lines) // 3:,} records, "
                                "no rsmm modifications)"))
    return out


#: GraphIssue severity -> doctor Result kind. info never fails the run.
_GRAPH_KIND = {"error": "FAIL", "warn": "WARN", "info": "OK"}


def check_compat_graph() -> list[Result]:
    """Dependency-graph health from `manifest_graph.validate_graph` — the full
    Fabric-style model: hard `requires` (+ semver ranges), soft `recommends`
    (warn) / `suggests` (info), hard `conflicts`, `replaces`, cycles, dup-id.
    Richer than the apply gate (`compat.analyze`), which this complements."""
    from rsmm.engine.paths import MODS_DIR
    from rsmm.manifest_graph import load_manifests, validate_graph

    records = load_manifests(MODS_DIR)
    if not records:
        return [Result("OK", "no mods to graph")]
    issues = validate_graph(records)
    if not issues:
        return [Result("OK", f"{len(records)} mod(s), dependency graph clean")]
    out: list[Result] = []
    for it in issues:
        out.append(Result(_GRAPH_KIND.get(it.severity, "WARN"),
                          f"{it.code}: {it.message}", it.fix or ""))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="System health check")
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    args = ap.parse_args()

    print("rsmm doctor — system health\n")
    results: list[Result] = []
    print("game install:")
    rs = check_game_install(args.game_dir)
    for r in rs:
        emit(r)
    results.extend(rs)
    if any(r.kind == "FAIL" for r in rs):
        return 1

    print("\nasset map:")
    rs = check_asset_map(args.game_dir)
    for r in rs:
        emit(r)
    results.extend(rs)

    print("\ngame version:")
    rs = check_game_update(args.game_dir)
    for r in rs:
        emit(r)
    results.extend(rs)

    print("\nloader DLL:")
    rs = check_loader(args.game_dir)
    for r in rs:
        emit(r)
    results.extend(rs)

    print("\nmods:")
    rs = check_mods()
    for r in rs:
        emit(r)
    results.extend(rs)

    print("\npatch conflicts:")
    rs = check_patch_conflicts()
    if not rs:
        emit(Result("OK", "no [[patch]] blocks in any mod"))
    else:
        for r in rs:
            emit(r)
        results.extend(rs)

    print("\ncompatibility graph:")
    try:
        crs = check_compat_graph()
    except Exception as e:
        crs = [Result("WARN", "compat analysis failed", str(e))]
    for r in crs:
        emit(r)
    # Only non-OK rows count toward the run's pass/fail tally.
    results.extend(r for r in crs if r.kind != "OK")

    print("\ngame executable:")
    rs = check_exe_hash(args.game_dir)
    for r in rs:
        emit(r)
    results.extend(rs)

    print("\napplier state:")
    rs = check_state(args.game_dir)
    for r in rs:
        emit(r)
    results.extend(rs)

    print("\nresource manifest (UsedRscList.ot):")
    rs = check_usedrsclist(args.game_dir)
    for r in rs:
        emit(r)
    results.extend(rs)

    fail = sum(1 for r in results if r.kind == "FAIL")
    warn = sum(1 for r in results if r.kind == "WARN")
    ok   = sum(1 for r in results if r.kind == "OK")
    print(f"\nsummary: {ok} OK, {warn} WARN, {fail} FAIL")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
