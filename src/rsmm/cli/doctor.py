"""
rsmm doctor — system health check, and the repair path for what it finds.

Walks every layer of the manager and reports OK / WARN / FAIL:

  - asset map exists + matches UsedRscList freshness
  - game install reachable + cooked tree present
  - loader DLL built + installed into game dir, with its runtime tree
    (`<game>/rsmm/lib`, `<game>/rsmm/data`) and launch options intact
  - each mod's manifest parses + every asset path resolves
  - cross-mod conflicts (raw file overlap, [[patch]] same-field hits)
  - applier state file vs. on-disk reality

A finding may carry a `Fix`: the exact rsmm subcommand that repairs it.
`--fix` runs those, then re-runs the check to prove the repair landed.
Fixes are ordinary rsmm subcommands — doctor never reimplements a repair, so
there is one code path for "apply" whether a human or doctor invokes it.

Repairs are opt-in. A health check that silently rewrites a game install on
every invocation is a footgun, so plain `doctor` stays read-only; `--fix`
runs the safe repairs, and the destructive ones (anything that rolls back or
deletes installed files) additionally need `--force`.

Exit code: 0 if every check passed, 1 if any FAIL, 2 if argv invalid.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from rsmm.cli import _term
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

_ST = _term.Style()

#: Per-kind colouring for the emitted glyph + label. Glyphs are pre-padded to
#: a common width as PLAIN text before styling — colouring first would make the
#: ANSI bytes count toward the column width and skew every row.
_GLYPHS = {"OK": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}
_PAINT = {"OK": _ST.ok, "WARN": _ST.warn, "FAIL": _ST.err}


@dataclass(frozen=True)
class Fix:
    """A repair doctor can run for a finding.

    `argv` is an rsmm subcommand, re-invoked through `self_cmd` so it works
    identically from a source checkout and a frozen sidecar. Repairs are
    expressed as existing commands on purpose: doctor should never grow a
    second, subtly different implementation of apply or install-loader.

    `risk="destructive"` marks a repair that can remove installed files or
    roll the install back; those need `--force` on top of `--fix`.
    """
    label: str
    argv: list[str]
    risk: str = "safe"          # safe | destructive
    #: Set when the repair can't be automated (needs Steam closed, a rebuild
    #: toolchain, a human decision). Reported, never run.
    manual: str = ""
    #: False for subcommands with no `--game-dir` (e.g. `run`, which finds the
    #: install itself). Appending it anyway is an argparse error, i.e. a repair
    #: that always fails on a non-default install.
    accepts_game_dir: bool = True


@dataclass
class Result:
    kind: str   # OK | WARN | FAIL
    label: str
    detail: str = ""
    #: Stable identifier for the finding, e.g. "loader.runtime-missing".
    #: Lets `--only` target a check and gives the desktop app a key to
    #: match on that doesn't break when wording changes.
    code: str = ""
    fix: Fix | None = None


@dataclass
class Check:
    """One section of the report."""
    name: str
    section: str
    run: Callable[[Path], list[Result]]
    #: Checks that read only the repo, not the install — still meaningful
    #: when --game-dir points somewhere that doesn't exist.
    needs_game: bool = True
    tags: list[str] = field(default_factory=list)


def emit(r: Result) -> None:
    glyph = _GLYPHS[r.kind]
    paint = _PAINT[r.kind]
    # OK rows are the common case — leave their label unstyled so the WARN /
    # FAIL rows are what the eye lands on.
    label = r.label if r.kind == "OK" else paint(r.label)
    print(f"  {paint(glyph)} {label}")
    if r.detail:
        for line in r.detail.splitlines():
            print(f"         {_ST.dim(line)}")
    if r.fix and r.kind != "OK":
        if r.fix.manual:
            print(f"         {_ST.dim('manual fix: ' + r.fix.manual)}")
        else:
            tag = "" if r.fix.risk == "safe" else " (needs --force)"
            print(f"         {_ST.accent('fixable:')} "
                  f"{_ST.dim(r.fix.label + tag)}")


def check_asset_map(game_dir: Path) -> list[Result]:
    out: list[Result] = []
    if not ASSET_MAP_JSON.exists():
        return [Result("FAIL", "asset_map.json missing",
                       "Run: ./rsmm rebuild-asset-map",
                       code="assetmap.missing",
                       fix=Fix("rsmm rebuild-asset-map", ["rebuild-asset-map"]))]
    am_mtime = ASSET_MAP_JSON.stat().st_mtime
    out.append(Result("OK", f"asset_map.json ({ASSET_MAP_JSON.stat().st_size:,} bytes)"))
    used = game_dir / "DarkTalesResources" / "UsedRscList.ot"
    if used.exists() and used.stat().st_mtime > am_mtime + 1:
        out.append(Result("WARN", "UsedRscList.ot newer than asset_map.json",
                          "Game may have updated. Run: ./rsmm rebuild-asset-map",
                          code="assetmap.stale",
                          fix=Fix("rsmm rebuild-asset-map", ["rebuild-asset-map"])))
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
                       "Run: rsmm apply  (will auto-recover)",
                       code="game.version-changed",
                       fix=Fix("rsmm apply", ["apply"]))]
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


#: Files `install-loader` plants under `<game>/rsmm/lib`. The Lua SDK is
#: disk-loaded, not embedded in the DLL, so a present DLL proves nothing
#: about whether the loader can actually run a mod.
# The entrypoint plus one submodule. rsmm.lua require-merges rsmm/*.lua and
# DEGRADES SILENTLY when one is absent (`R.schedule` simply becomes nil), so a
# half-planted tree looks healthy from the outside while every timer-driven
# feature quietly does nothing. Checking a submodule too makes that visible.
_LOADER_LIB_FILES = ("rsmm.lua", "engine_gen.lua", "rsmm/schedule.lua")


def check_loader(game_dir: Path) -> list[Result]:
    out: list[Result] = []
    dll = DIST_DIR / "winhttp.dll"
    if not dll.exists():
        out.append(Result("WARN", "loader DLL not built (dist/winhttp.dll missing)",
                          "Run: ./rsmm build  (or skip if not using Lua mods)",
                          code="loader.not-built",
                          fix=Fix("src/loader/build.sh", [],
                                  manual="src/loader/build.sh (Linux→Win, MinGW) "
                                         "or src\\loader\\build.bat (Windows)")))
    else:
        out.append(Result("OK", f"loader DLL built ({dll.stat().st_size:,} bytes)"))
    installed = game_dir / "winhttp.dll"
    install_fix = Fix("rsmm install-loader", ["install-loader"])
    if not installed.exists():
        out.append(Result("WARN", "loader not installed in game dir",
                          "Run: ./rsmm install-loader (only needed for Lua mods)",
                          code="loader.not-installed", fix=install_fix))
        return out

    sz = installed.stat().st_size
    if not dll.exists():
        out.append(Result("OK", f"game dir has a winhttp.dll ({sz:,} bytes)",
                          "No built DLL to compare it against."))
    elif sha256_file(installed) == sha256_file(dll):
        # Hash, not size: a stale build of our own DLL can match on size while
        # being a different binary, and that reads as "installed" forever.
        out.append(Result("OK", f"loader installed in game dir ({sz:,} bytes)"))
    else:
        same_size = sz == dll.stat().st_size
        detail = ("Bytes differ from the built DLL. This is what Steam leaves "
                  "behind after an update or a file verify: the depot ships "
                  "its own winhttp.dll, which silently replaces ours.")
        if same_size:
            detail = ("Same size as the built DLL but different bytes — a stale "
                      "loader build is installed.")
        out.append(Result("WARN", "game dir winhttp.dll is not the built loader",
                          detail, code="loader.stale-dll", fix=install_fix))

    # The DLL alone is not a working loader: it disk-loads the Lua SDK and the
    # pattern DB from <game>/rsmm/. Steam's update wipes that tree while
    # leaving a winhttp.dll in place, so "installed" must mean both.
    runtime = game_dir / "rsmm"
    missing = [n for n in _LOADER_LIB_FILES if not (runtime / "lib" / n).is_file()]
    if missing:
        out.append(Result("WARN", "loader runtime tree incomplete: "
                                  f"<game>/rsmm/lib is missing {', '.join(missing)}",
                          "The Lua SDK is loaded from disk, not embedded in the "
                          "DLL — without it every Lua mod fails to load even "
                          "though winhttp.dll is present.",
                          code="loader.runtime-missing", fix=install_fix))
    else:
        out.append(Result("OK", "loader runtime tree present (<game>/rsmm/lib)"))
    # A plant older than what this build carries. The DLL hash check above does
    # not catch it (the DLL can match while the Lua SDK beside it is older), and
    # `update-loader` reports "up to date" because its eligibility figure folds
    # in the bundled stamp — so nothing else in the tool says this out loud.
    from rsmm.engine.loader_update import bundled_version, planted_manifest_version
    planted_v = planted_manifest_version(game_dir)
    if planted_v is not None and planted_v < bundled_version():
        out.append(Result("WARN", f"planted loader is v{planted_v}, this build "
                                  f"bundles v{bundled_version()}",
                          "The game loads the planted copy, so a newer SDK in "
                          "this build is not in the process. `update-loader` "
                          "will not fix it — only re-planting will.",
                          code="loader.stale-plant", fix=install_fix))
    if not (runtime / "data" / "function_patterns.json").is_file():
        out.append(Result("WARN", "planted pattern DB missing "
                                  "(<game>/rsmm/data/function_patterns.json)",
                          "The running game reads the planted copy, not the "
                          "repo's. Symbol resolution fails closed without it.",
                          code="loader.patterns-missing",
                          fix=Fix("rsmm update-data", ["update-data"])))
    return out


#: Loader feature flags that are known-broken and crash the game. Kept here so
#: doctor flags an install that was left armed after a debugging session.
_DANGEROUS_FLAGS = {
    "RSMM_ENABLE_ITEM_INJECT":
        "resource-by-path lookup mis-resolves on current builds → crash at "
        "load. Custom items don't need it; they register via UsedRscList.",
    "RSMM_ENABLE_SKILL_INJECT":
        "unverified skill-table detour; crashes on current builds.",
    "RSMM_ENABLE_IO":
        "IAT-patches CreateFileW in the main exe to trace asset loads. The "
        "loader itself logs \"may crash game\" when it arms this, and asset "
        "overrides do not need it — they are install-time file replacement. "
        "Debugging only.",
}


def check_loader_flags(game_dir: Path) -> list[Result]:
    """Flag dangerous loader feature flags left armed in the flags file or env."""
    out: list[Result] = []
    armed: list[str] = []
    flags_file = game_dir / "rsmm_loader_flags.json"
    if flags_file.is_file():
        try:
            data = json.loads(flags_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            out.append(Result("WARN", "rsmm_loader_flags.json unreadable",
                              f"{e}\nThe loader ignores a malformed flags file.",
                              code="loaderflags.unreadable"))
            data = []
        if isinstance(data, list):
            armed += [str(f) for f in data if str(f) in _DANGEROUS_FLAGS]
    armed += [name for name in _DANGEROUS_FLAGS
              if os.environ.get(name, "").strip() in ("1", "true", "yes", "on")]
    for name in sorted(set(armed)):
        out.append(Result("WARN", f"dangerous loader flag armed: {name}",
                          _DANGEROUS_FLAGS[name] +
                          "\nRemove it from rsmm_loader_flags.json / the Steam "
                          "launch options before playing.",
                          code="loaderflags.dangerous"))
    if not out:
        out.append(Result("OK", "no dangerous loader flags armed"))
    return out


def check_launch_options(game_dir: Path) -> list[Result]:
    """On Proton/Wine the DLL only loads if Steam passes WINEDLLOVERRIDES.

    Planting winhttp.dll is half the install; without the override Wine loads
    its own builtin and the loader never runs — with no error anywhere, which
    reads as "the loader is broken" rather than "the loader isn't loaded".
    `rsmm restore` and Steam both clear this field.
    """
    if sys.platform == "win32":
        return [Result("OK", "native Windows — no DLL override needed")]
    if not (game_dir / "winhttp.dll").exists():
        # Nothing planted yet; check_loader already says so.
        return []
    from rsmm.cli.run import (
        RAVENSWATCH_APP_ID,
        _localconfig_paths,
        _override_present,
        _read_launch_options,
        _steam_root,
    )
    # --no-launch matters: without it the repair starts the game, and Steam
    # then owns localconfig.vdf and rewrites it on exit.
    fix = Fix("rsmm run --set-launch-options --no-launch",
              ["run", "--set-launch-options", "--no-launch"],
              accepts_game_dir=False)
    root = _steam_root()
    if root is None:
        return [Result("OK", "Steam config not found — cannot check launch options")]
    seen: str | None = None
    seen_in: Path | None = None
    for vdf in _localconfig_paths(root):
        lo = _read_launch_options(vdf, RAVENSWATCH_APP_ID)
        if lo is None:
            continue
        seen, seen_in = lo, vdf
        if _override_present(lo):
            return [Result("OK", "Steam launch options carry the winhttp override")]
    if seen is None:
        return [Result("WARN", "no Steam launch options recorded for Ravenswatch",
                       "The loader needs WINEDLLOVERRIDES to load under Proton.",
                       code="launchopts.missing", fix=fix)]
    if not seen and seen_in is not None and _has_orphaned_launch_value(
            seen_in, RAVENSWATCH_APP_ID):
        # An empty parse over a non-empty line means the stored value is
        # malformed — a truncated rewrite leaves the tail of the old value
        # stranded outside the quoted string. Steam keeps loading the file,
        # so nothing else ever complains.
        return [Result("FAIL", "Steam launch options are corrupt",
                       f"{seen_in}\nThe LaunchOptions value parses as empty but "
                       "the line is not. Steam will pass nothing to the game, so "
                       "the loader never loads.\nRe-set it (Steam closed) to "
                       'restore: WINEDLLOVERRIDES="winhttp=n,b" %command%',
                       code="launchopts.corrupt", fix=fix)]
    return [Result("WARN", "Steam launch options lack the winhttp override",
                   f"current: {seen or '(empty)'}\n"
                   "Without it Wine loads its own winhttp and the loader never "
                   "runs — no error, it simply does nothing.",
                   code="launchopts.no-override", fix=fix)]


def _has_orphaned_launch_value(vdf: Path, app_id: str) -> bool:
    """True if RAVENSWATCH's LaunchOptions line carries text the parser can't see.

    Distinguishes "the user cleared their launch options" (an empty line,
    fine) from "a bad rewrite mangled them" (a line with leftover payload).

    Scoped to the app's own block on purpose. Scanning the whole file matched
    the LaunchOptions of EVERY installed game, so one unrelated title with
    `gamemoderun %command%` was enough to report Ravenswatch's own, correctly
    cleared, options as corrupt — a FAIL pointing at a repair for a file that
    was fine. That is exactly the state `restore` leaves behind by design.
    """
    try:
        text = vdf.read_text(errors="replace")
    except OSError:
        return False
    depth = 0
    inside = False           # within the app_id block
    inside_depth = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not inside and line == f'"{app_id}"':
            inside, inside_depth = True, depth
            continue
        if line == "{":
            depth += 1
            continue
        if line == "}":
            depth -= 1
            if inside and depth <= inside_depth:
                return False   # left the app block without finding residue
            continue
        if inside and line.startswith('"LaunchOptions"'):
            rest = line[len('"LaunchOptions"'):].lstrip()
            # A well-formed value is ONE quoted string and nothing else. Match
            # the opening quote to its first unescaped partner; any non-space
            # tail after that is the stranded remains of a truncated rewrite.
            # Checking only `startswith('"') and endswith('"')` is not enough —
            # the real corruption (`""winhttp=n,b\" %command%"`) satisfies both.
            if not rest.startswith('"'):
                return True
            i, n = 1, len(rest)
            while i < n:
                if rest[i] == "\\":
                    i += 2
                    continue
                if rest[i] == '"':
                    break
                i += 1
            else:
                return True                    # never closed
            if rest[i + 1:].strip():
                return True
    return False


def check_crash_dumps(game_dir: Path) -> list[Result]:
    """Surface recent crash dumps — a crash the user hasn't mentioned yet is
    still the most useful thing doctor can point at."""
    reports = game_dir / "CrashDB" / "reports"
    if not reports.is_dir():
        return [Result("OK", "no crash-dump directory")]
    dumps = sorted((p for p in reports.glob("*.dmp") if p.is_file()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not dumps:
        return [Result("OK", "no crash dumps recorded")]
    import datetime as _dt
    newest = dumps[0]
    when = _dt.datetime.fromtimestamp(newest.stat().st_mtime)
    age_days = (_dt.datetime.now() - when).days
    detail = (f"newest: {newest.name} ({when:%Y-%m-%d %H:%M})\n"
              f"{len(dumps)} dump(s) total. Triage with: "
              "python scripts/triage_dump.py")
    # Old dumps are history, not news — and reading a stale dump as "the
    # current crash" wastes a debugging session.
    kind = "WARN" if age_days <= 2 else "OK"
    label = (f"{len(dumps)} crash dump(s), newest {age_days} day(s) old"
             if age_days else f"{len(dumps)} crash dump(s), newest today")
    return [Result(kind, label, detail, code="crash.dumps")]


def check_mods() -> list[Result]:
    out: list[Result] = []
    if not MODS_DIR.is_dir():
        return [Result("WARN", "mods/ missing")]
    try:
        dec2enc = decoded_to_encoded()
    except (OSError, ValueError) as e:
        return [Result("FAIL", "cannot load asset_map.json",
                       f"{e}\nRun: ./rsmm rebuild-asset-map",
                       code="assetmap.unreadable",
                       fix=Fix("rsmm rebuild-asset-map", ["rebuild-asset-map"]))]
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
                       "Run: rsmm update-data",
                       code="patterns.missing",
                       fix=Fix("rsmm update-data", ["update-data"]))]

    exe_candidates = [
        game_dir / "Ravenswatch.exe",
        game_dir / "Ravenswatch-Win64-Shipping.exe",
        game_dir / "Ravenswatch" / "Binaries" / "Win64" / "Ravenswatch-Win64-Shipping.exe",
    ]
    exe = next((e for e in exe_candidates if e.exists()), None)
    if not exe:
        return [Result("WARN", "game executable not found (may be on different OS)",
                       "Cannot verify pattern DB freshness without the game exe")]

    exe_hash = sha256_file(exe)
    exe_size = exe.stat().st_size
    result = [Result("OK", f"game exe: {exe.name} ({exe_size:,} bytes, "
                           f"hash={exe_hash[:12]})")]

    # Precise check: the pattern DB actually consulted by the loader is the
    # planted copy; its meta records which game build it was built against.
    from rsmm.engine.data_update import bundled_meta, planted_dir, planted_meta
    meta = planted_meta(game_dir) or bundled_meta()
    if meta and meta.get("game_exe_sha256"):
        which = ("planted" if (planted_dir(game_dir) / "function_patterns.meta.json").exists()
                 else "bundled")
        if meta["game_exe_sha256"] == exe_hash:
            result.append(Result("OK", f"pattern DB ({which}) matches this game build"))
        else:
            result.append(Result(
                "WARN", f"pattern DB ({which}) was generated against a different game build",
                "Game likely updated. Run: rsmm update-data "
                "(devs: python scripts/gen_function_patterns.py)",
                code="patterns.stale",
                fix=Fix("rsmm update-data", ["update-data"])))
        return result

    # Fallback for pre-meta DBs: mtime heuristic.
    if exe.stat().st_mtime > patterns.stat().st_mtime + 1:
        result.append(Result("WARN", "game exe newer than function_patterns.json",
                             "Game may have updated. Run: rsmm update-data "
                             "(devs: python scripts/gen_function_patterns.py)",
                             code="patterns.stale-mtime",
                             fix=Fix("rsmm update-data", ["update-data"])))
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
                       "residue sweep), then: ./rsmm apply",
                       code="state.corrupt",
                       fix=Fix("rsmm restore --all", ["restore", "--all"],
                               risk="destructive"))]
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
                          _listing(missing) + "\nRun: ./rsmm apply  (re-installs them)",
                          code="state.missing-override",
                          fix=Fix("rsmm apply", ["apply"])))
    if drifted:
        out.append(Result("WARN",
                          f"{len(drifted)} installed override(s) no longer match "
                          "their mod source hash",
                          _listing(drifted) +
                          "\nLikely a Steam file verify or game update. "
                          "Run: ./rsmm apply  (re-copies stale files)",
                          code="state.drifted",
                          fix=Fix("rsmm apply", ["apply"])))
    if lost_backups:
        out.append(Result("WARN",
                          f"{len(lost_backups)} override(s) lost their .rsmm.bak backup",
                          _listing(lost_backups) +
                          "\nRestore for these falls back to the residue sweep; "
                          "verify game files in Steam to be safe.",
                          code="state.lost-backup",
                          fix=Fix("verify game files in Steam", [],
                                  manual="Steam → Properties → Installed Files "
                                         "→ Verify integrity, then rsmm apply")))
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
                          "manifest), or verify game files in Steam.",
                          code="usedrsclist.desync",
                          fix=Fix("rsmm restore --all", ["restore", "--all"],
                                  risk="destructive")))
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
                              "(game update mid-state?). Run: ./rsmm apply",
                              code="usedrsclist.shorter",
                              fix=Fix("rsmm apply", ["apply"])))
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


#: The report, in order. Each entry is one section; `main` walks this list
#: instead of hand-sequencing calls, so adding a check is one line here and
#: `--only` / `--json` / `--fix` pick it up for free.
def _checks() -> list[Check]:
    return [
        Check("game-install", "game install", check_game_install),
        Check("asset-map", "asset map", check_asset_map),
        Check("game-version", "game version", check_game_update),
        Check("loader", "loader DLL", check_loader),
        Check("loader-flags", "loader feature flags", check_loader_flags),
        Check("launch-options", "Steam launch options", check_launch_options),
        Check("mods", "mods", lambda _g: check_mods()),
        Check("patch-conflicts", "patch conflicts",
              lambda _g: check_patch_conflicts() or
              [Result("OK", "no [[patch]] blocks in any mod")]),
        Check("compat-graph", "compatibility graph", lambda _g: check_compat_graph()),
        Check("exe-hash", "game executable", check_exe_hash),
        Check("state", "applier state", check_state),
        Check("usedrsclist", "resource manifest (UsedRscList.ot)", check_usedrsclist),
        Check("crash-dumps", "crash dumps", check_crash_dumps),
    ]


def _run_check(chk: Check, game_dir: Path) -> list[Result]:
    """Run one check, converting a crash into a finding.

    A doctor that dies on its third section tells the user nothing about the
    other ten — and the checks parse game-derived files, so a malformed one is
    exactly the situation where the report matters most.
    """
    try:
        return chk.run(game_dir)
    except Exception as e:  # noqa: BLE001 - a crashing check must not end the run
        return [Result("WARN", f"check {chk.name!r} crashed",
                       f"{type(e).__name__}: {e}", code=f"{chk.name}.crashed")]


def _apply_fix(r: Result, game_dir: Path, *, force: bool) -> tuple[str, str]:
    """Run a finding's repair. Returns (outcome, detail).

    outcome: fixed | failed | skipped
    """
    fix = r.fix
    if fix is None:
        return "skipped", "no automated fix"
    if fix.manual or not fix.argv:
        return "skipped", f"manual: {fix.manual or fix.label}"
    if fix.risk != "safe" and not force:
        return "skipped", f"{fix.label} is destructive — re-run with --force"
    from rsmm.engine.paths import REPO_ROOT, self_cmd
    argv = list(fix.argv)
    # Every repair targets the install under test, not the default one.
    if (fix.accepts_game_dir and "--game-dir" not in argv
            and str(game_dir) != str(DEFAULT_GAME)):
        argv += ["--game-dir", str(game_dir)]
    try:
        proc = subprocess.run(self_cmd(argv), cwd=REPO_ROOT,
                              capture_output=True, text=True, check=False)
    except OSError as e:
        return "failed", str(e)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return "failed", (tail[-1] if tail else f"exit {proc.returncode}")
    return "fixed", fix.label


def _as_json(sections: list[tuple[str, list[Result]]],
             repairs: list[dict[str, str]]) -> dict:
    return {
        "ok": not any(r.kind == "FAIL" for _s, rs in sections for r in rs),
        "sections": [
            {
                "section": name,
                "results": [
                    {
                        "kind": r.kind, "label": r.label, "detail": r.detail,
                        "code": r.code,
                        "fix": (None if not r.fix else {
                            "label": r.fix.label, "argv": r.fix.argv,
                            "risk": r.fix.risk, "manual": r.fix.manual,
                            "automatic": bool(r.fix.argv and not r.fix.manual),
                        }),
                    }
                    for r in rs
                ],
            }
            for name, rs in sections
        ],
        "repairs": repairs,
        "counts": {
            kind.lower(): sum(1 for _s, rs in sections for r in rs if r.kind == kind)
            for kind in ("OK", "WARN", "FAIL")
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm doctor", description="System health check + repair")
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--fix", action="store_true",
                    help="run the repair for every fixable finding, then "
                         "re-check to confirm it landed")
    ap.add_argument("--force", action="store_true",
                    help="with --fix, also run destructive repairs "
                         "(restore --all and friends)")
    ap.add_argument("--only", metavar="CHECK", action="append",
                    help="run only these checks (repeatable); "
                         "--only list prints the names")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable report on stdout")
    args = ap.parse_args()

    checks = _checks()
    if args.only and "list" in args.only:
        for c in checks:
            print(f"{c.name:<16} {c.section}")
        return 0
    if args.only:
        wanted = set(args.only)
        unknown = wanted - {c.name for c in checks}
        if unknown:
            print(f"unknown check(s): {', '.join(sorted(unknown))}\n"
                  f"known: {', '.join(c.name for c in checks)}", file=sys.stderr)
            return 2
        checks = [c for c in checks if c.name in wanted]

    quiet = args.json
    if not quiet:
        print(_ST.bold("rsmm doctor — system health") + "\n")

    sections: list[tuple[str, list[Result]]] = []
    for chk in checks:
        rs = _run_check(chk, args.game_dir)
        if not rs:
            continue
        if not quiet:
            if sections:
                print()
            print(_ST.heading(chk.section + ":"))
            for r in rs:
                emit(r)
        sections.append((chk.section, rs))
        # A missing or unwritable install invalidates every later check, so
        # stop rather than emit a page of misleading follow-on failures.
        if chk.name == "game-install" and any(r.kind == "FAIL" for r in rs):
            break

    repairs: list[dict[str, str]] = []
    if args.fix:
        fixable = [(name, r) for name, rs in sections for r in rs
                   if r.kind != "OK" and r.fix is not None]
        if not quiet:
            print("\n" + _ST.heading("repairs:"))
            if not fixable:
                print(f"  {_ST.dim('nothing to fix')}")
        # De-dup: several findings share one remedy (apply fixes drift AND
        # missing overrides), and running apply three times helps nobody.
        done: dict[str, str] = {}
        for _name, r in fixable:
            assert r.fix is not None
            key = " ".join(r.fix.argv) or r.fix.label
            if key in done:
                outcome, detail = "skipped", f"already ran {r.fix.label}"
            else:
                outcome, detail = _apply_fix(r, args.game_dir, force=args.force)
                done[key] = outcome
            repairs.append({"code": r.code or r.label, "fix": r.fix.label,
                            "outcome": outcome, "detail": detail})
            if not quiet:
                paint = {"fixed": _ST.ok, "failed": _ST.err}.get(outcome, _ST.dim)
                # Pad the PLAIN text before styling: colouring first makes the
                # ANSI bytes count toward the column width.
                tag = f"{outcome.upper():<8}"
                print(f"  {paint(tag)} {r.code or r.label} — {_ST.dim(detail)}")

        if any(rep["outcome"] == "fixed" for rep in repairs):
            # Re-run everything: a repair proves itself by the check going
            # green, not by the subcommand exiting 0.
            if not quiet:
                print("\n" + _ST.heading("re-check after repairs:"))
            sections = []
            for chk in checks:
                rs = _run_check(chk, args.game_dir)
                if not rs:
                    continue
                if not quiet:
                    for r in rs:
                        if r.kind != "OK":
                            emit(r)
                sections.append((chk.section, rs))
            if not quiet and not any(r.kind != "OK"
                                     for _s, rs in sections for r in rs):
                print(f"  {_ST.ok('all checks pass')}")

    fail = sum(1 for _s, rs in sections for r in rs if r.kind == "FAIL")
    warn = sum(1 for _s, rs in sections for r in rs if r.kind == "WARN")
    ok = sum(1 for _s, rs in sections for r in rs if r.kind == "OK")

    if args.json:
        print(json.dumps(_as_json(sections, repairs), indent=2))
        return 1 if fail else 0

    # A zero count is good news — render it dim so only the non-zero WARN /
    # FAIL tallies carry colour.
    parts = [
        _ST.ok(f"{ok} OK"),
        (_ST.warn if warn else _ST.dim)(f"{warn} WARN"),
        (_ST.err if fail else _ST.dim)(f"{fail} FAIL"),
    ]
    print("\n" + _ST.bold("summary:") + " " + ", ".join(parts))
    if not args.fix:
        n_fixable = sum(1 for _s, rs in sections for r in rs
                        if r.kind != "OK" and r.fix is not None
                        and r.fix.argv and not r.fix.manual)
        if n_fixable:
            print(_ST.dim(f"{n_fixable} finding(s) have an automated repair — "
                          "run: rsmm doctor --fix"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
