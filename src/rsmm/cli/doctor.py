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
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from rsmm.cli.apply_mods import _LANG_SUFFIXES, is_skippable_asset
from rsmm.cli.merge import _ranked, _toml_load, collect_patches
from rsmm.engine.asset_map import decoded_to_encoded
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


def check_game_install(game_dir: Path) -> list[Result]:
    if not game_dir.exists():
        return [Result("FAIL", f"game_dir not found: {game_dir}",
                       "Pass --game-dir to override default.")]
    cooking = game_dir / COOKING_SUBDIR
    if not cooking.is_dir():
        return [Result("FAIL", f"_Cooking missing under {game_dir}",
                       f"Expected: {cooking}")]
    return [Result("OK", f"game install: {game_dir}")]


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
    dec2enc = decoded_to_encoded()
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
        game_dir / "Ravenswatch.app" / "Contents" / "MacOS" / "Ravenswatch",
    ]
    exe = next((e for e in exe_candidates if e.exists()), None)
    if not exe:
        return [Result("WARN", "game executable not found (may be on different OS)",
                       "Cannot verify pattern DB freshness without the game exe")]

    patterns_mtime = patterns.stat().st_mtime
    exe_mtime = exe.stat().st_mtime

    h = hashlib.sha256()
    with exe.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    exe_hash = h.hexdigest()[:12]
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
        return [Result("FAIL", "state file is corrupt", str(e))]
    active = data.get("active", {}) or {}
    return [Result("OK", f"applier state: {len(active)} active override(s)")]


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
        from rsmm.cli.compat import analyze
        rep = analyze()
        crs: list[Result] = []
        for mid, why in rep.auto_disabled.items():
            crs.append(Result("WARN", f"auto-disabled {mid}", why))
        for mid, msg in rep.unmet_requires:
            crs.append(Result("FAIL", f"{mid}: unmet dep", msg))
        for a, b in rep.hard_conflicts:
            crs.append(Result("FAIL", "hard conflict",
                              f"{a} <-> {b} (drop one)"))
        for c in rep.cycles:
            crs.append(Result("FAIL", "requires cycle", " -> ".join(c)))
        if not crs:
            emit(Result("OK", f"{len(rep.summaries)} mod(s), graph clean"))
        else:
            for r in crs:
                emit(r)
            results.extend(crs)
    except Exception as e:
        emit(Result("WARN", "compat analysis failed", str(e)))

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

    fail = sum(1 for r in results if r.kind == "FAIL")
    warn = sum(1 for r in results if r.kind == "WARN")
    ok   = sum(1 for r in results if r.kind == "OK")
    print(f"\nsummary: {ok} OK, {warn} WARN, {fail} FAIL")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
