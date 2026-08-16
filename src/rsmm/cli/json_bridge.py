"""
rsmm json — machine-readable bridge for the desktop / web UI.

Subcommands:

    rsmm json list                  list installed mods (mods/ dir)
    rsmm json apply [--dry-run]     run apply, return {ok, code, stdout, stderr}
    rsmm json restore-all           restore every active override
    rsmm json build                 build asset map + loader DLL + merge + apply
    rsmm json doctor                run health check, return structured results
    rsmm json run                   launch the game via steam://rungameid
    rsmm json run --vanilla         restore original files, then launch
    rsmm json pack-mod <id>         pack mods/<id>/ → dist/<id>.zip + return
                                    {path, sha256, sizeBytes, slug, version,
                                    manifest} ready for the upload API
    rsmm json upload-bytes <p> <u>  HTTP PUT the bytes at <p> to URL <u>
                                    (used to push a packed zip to the
                                    presigned S3/R2 URL the API hands back)
    rsmm json install-mod <slug>    download latest version from the index
                                    + extract into mods/<slug>/. Hits
                                    the API's `/api/mods/<slug>/<ver>/
                                    download` route, which also bumps
                                    the public download counter.
    rsmm json install-mod-version
        <slug> <version>            download a specific version of a mod
    rsmm json config get <id>       read a mod's config schema + values
    rsmm json config set <id> <js>  replace a mod's config values
    rsmm json uninstall-mod <id>    remove a mod from mods/<id>/
    rsmm json loader-flags get      list loader feature flags + enabled set
    rsmm json loader-flags set <js> write the enabled-flag list (JSON array;
                                    only safe flags are honoured) to
                                    <game>/rsmm_loader_flags.json
    rsmm json update-data [--check] fetch + install the latest function-
                                    pattern DB from the rolling pattern-db
                                    release into <game>/rsmm/data/

All commands emit a single JSON object/array on stdout (UTF-8, no trailing
newline). Stderr is forwarded for diagnostics. Exit code is 0 on success.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from rsmm.cli.apply_mods import clear_runtime_mods, find_game_dir
from rsmm.cli.merge import _ranked, collect_patches
from rsmm.engine import net
from rsmm.engine.paths import DIST_DIR, MODS_DIR, REPO_ROOT, self_cmd
from rsmm.logging import get_logger
from rsmm.sdk import archive
from rsmm.sdk.config import ConfigError, ConfigStore

logger = get_logger(__name__)


def _emit(value: Any) -> int:
    sys.stdout.write(json.dumps(value, default=str, separators=(",", ":")))
    sys.stdout.flush()
    return 0


def _read_manifest(path: Path) -> dict[str, Any] | None:
    # Catch only the failures we can actually get here (missing file,
    # permission, malformed TOML). A bare `except Exception` here
    # swallowed every programmer error too, so a typo in this module
    # would silently return None and look like "manifest missing".
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"warning: could not read manifest {path}: {exc}", file=sys.stderr)
        return None


def _deps_map(manifest: dict[str, Any]) -> dict[str, str]:
    """The store's ``{mod_id: range}`` dependency map, derived from the
    manifest's ``requires`` array (the format the dependency graph + builder
    use). The desktop/store schema expects a dict; the manifest carries an
    array — without this the published dependencies were always empty. A
    legacy ``dependencies`` table, if present, is merged underneath."""
    from rsmm.manifest_graph import split_dep

    out: dict[str, str] = {}
    for spec in manifest.get("requires", []) or []:
        name, rng = split_dep(str(spec))
        if name:
            out[name] = rng or "*"
    legacy = manifest.get("dependencies")
    if isinstance(legacy, dict):
        for k, v in legacy.items():
            out.setdefault(str(k), str(v))
    return out


def cmd_list() -> int:
    """List installed mods.

    An empty array MUST mean "the folder is readable and holds no mods".
    Reporting a read failure as `[]` made the two indistinguishable to the
    desktop app, which then recorded "nothing is installed" from a transient
    permission error and disabled install buttons for mods that were on disk
    all along. A failure now exits non-zero so the caller can tell them apart.
    """
    items: list[dict[str, Any]] = []
    try:
        if not MODS_DIR.is_dir():
            # Not an error: no mods folder yet is a legitimate empty state.
            return _emit([])
    except (OSError, PermissionError) as e:
        print(f"error: could not access mods directory {MODS_DIR}: {e}", file=sys.stderr)
        return 1
    try:
        entries = sorted(MODS_DIR.iterdir())
    except (OSError, PermissionError) as e:
        print(f"error: could not read mods directory {MODS_DIR}: {e}", file=sys.stderr)
        return 1
    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        raw = _read_manifest(entry / "manifest.toml")
        if raw is None:
            continue
        # Manifests use [mod] table for metadata; older ones inline at root.
        manifest = raw.get("mod") if isinstance(raw.get("mod"), dict) else raw
        deps = _deps_map(manifest)
        writes: list[str] = []
        assets_dir = entry / "assets"
        if assets_dir.is_dir():
            for f in assets_dir.rglob("*"):
                if f.is_file():
                    writes.append(f.relative_to(assets_dir).as_posix())
        # `id` and `slug` are both the folder name. The folder name is
        # the canonical identifier post-install — manifest.id is only
        # the upload-time author-supplied id, which may differ from the
        # slug the registry assigned. Keeping these in lockstep prevents
        # the desktop store's installed[]/loadOrder from drifting when
        # syncLocalMods re-runs.
        items.append({
            "id": entry.name,
            "slug": entry.name,
            "name": manifest.get("name", entry.name),
            "version": str(manifest.get("version", "0.0.0")),
            "author": manifest.get("author"),
            "summary": manifest.get("summary") or manifest.get("description"),
            "license": manifest.get("license"),
            "tags": manifest.get("tags") or [],
            "enabled": bool(manifest.get("enabled", True)),
            "path": str(entry),
            "dependencies": {str(k): str(v) for k, v in deps.items()},
            "writes": writes,
        })
    return _emit(items)


def _config_for_mod(mod_id: str) -> ConfigStore | None:
    mod_dir = MODS_DIR / mod_id
    if not mod_dir.is_dir():
        return None
    return ConfigStore(mod_dir)


def cmd_config_get(mod_id: str) -> int:
    try:
        store = _config_for_mod(mod_id)
    except ConfigError as exc:
        return _emit({"ok": False, "error": str(exc)})
    if store is None:
        return _emit({"ok": False, "error": f"no such mod folder: {MODS_DIR / mod_id}"})
    return _emit({
        "ok": True,
        "modId": mod_id,
        "path": str(store.mod_dir),
        "schema": store.schema_as_dict(),
        "values": store.as_dict(),
    })


def cmd_config_set(mod_id: str, values_json: str) -> int:
    try:
        store = _config_for_mod(mod_id)
    except ConfigError as exc:
        return _emit({"ok": False, "error": str(exc)})
    if store is None:
        return _emit({"ok": False, "error": f"no such mod folder: {MODS_DIR / mod_id}"})
    try:
        payload = json.loads(values_json)
    except json.JSONDecodeError as exc:
        return _emit({"ok": False, "error": f"invalid config JSON: {exc}"})
    if not isinstance(payload, dict):
        return _emit({"ok": False, "error": "config payload must be a JSON object"})
    try:
        store.replace(payload)
    except ConfigError as exc:
        return _emit({"ok": False, "error": str(exc)})
    return _emit({
        "ok": True,
        "modId": mod_id,
        "path": str(store.mod_dir),
        "schema": store.schema_as_dict(),
        "values": store.as_dict(),
    })


def cmd_uninstall_mod(mod_id: str) -> int:
    mod_path = (MODS_DIR / mod_id).resolve()
    mods_root = MODS_DIR.resolve()
    try:
        mod_path.relative_to(mods_root)
    except ValueError:
        return _emit({"ok": False, "error": f"invalid mod id: {mod_id!r}"})

    try:
        if mod_path.is_dir():
            shutil.rmtree(mod_path)
            removed = True
        elif mod_path.exists():
            mod_path.unlink()
            removed = True
        else:
            removed = False
    except OSError as exc:
        return _emit({"ok": False, "error": f"failed to remove {mod_path}: {exc}"})

    return _emit({
        "ok": True,
        "modId": mod_id,
        "removed": removed,
        "removedPath": str(mod_path),
    })


def _collect_rsmm(args: list[str]) -> dict[str, Any]:
    cmd = self_cmd(args)
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        return {"ok": False, "code": 127, "stdout": "", "stderr": str(e)}
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _run_rsmm(args: list[str]) -> int:
    """Spawn `./rsmm <args>` and emit {ok, code, stdout, stderr}."""
    return _emit(_collect_rsmm(args))


def cmd_apply(rest: list[str]) -> int:
    return _run_rsmm(["apply", *rest])


def cmd_restore_all() -> int:
    return _run_rsmm(["apply", "--restore-all"])


def cmd_active_overrides() -> int:
    game_dir = find_game_dir()
    if game_dir is None:
        return _emit({
            "ok": True,
            "gameDir": None,
            "cookingDir": None,
            "hasActiveOverrides": False,
            "activeOverrideCount": 0,
        })

    cooking_dir = game_dir / "DarkTalesResources" / "_Cooking"
    state_path = cooking_dir / ".rsmm_state.json"
    if not state_path.exists():
        return _emit({
            "ok": True,
            "gameDir": str(game_dir),
            "cookingDir": str(cooking_dir),
            "hasActiveOverrides": False,
            "activeOverrideCount": 0,
        })

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _emit({
            "ok": False,
            "gameDir": str(game_dir),
            "cookingDir": str(cooking_dir),
            "error": f"failed to read applier state: {exc}",
            "hasActiveOverrides": False,
            "activeOverrideCount": 0,
        })

    active = data.get("active", {}) if isinstance(data, dict) else {}
    if not isinstance(active, dict):
        active = {}

    return _emit({
        "ok": True,
        "gameDir": str(game_dir),
        "cookingDir": str(cooking_dir),
        "hasActiveOverrides": bool(active),
        "activeOverrideCount": len(active),
    })


# Loader feature flags surfaced in the desktop "Loader features" panel.
# The loader reads these from <game_dir>/rsmm_loader_flags.json (a JSON array
# of enabled flag names) OR from a matching environment variable. Only flags
# marked safe=True are user-togglable; the rest are documented but locked so
# the UI can explain why (e.g. RSMM_ENABLE_ITEM_INJECT crashes the game).
LOADER_FLAGS: list[dict[str, Any]] = [
    # Both event buses are ON by default (the loader skips publishing entirely
    # when no mod has subscribed, so an asset-only install pays nothing). These
    # entries are the opt-OUT switches, for isolating a suspected event-bus
    # problem without uninstalling the loader.
    {
        "name": "RSMM_DISABLE_GAMEPLAY_EVENTS",
        "label": "Disable gameplay event bus",
        "description": "Stop bridging the in-game oCGameNamedEvent bus to Lua "
                       "(R.on(\"gameplay:<NAME>\")). Event-driven mods break "
                       "while this is on — troubleshooting only.",
        "safe": True,
    },
    {
        "name": "RSMM_DISABLE_GAME_EVENTS",
        "label": "Disable analytics event bridge",
        "description": "Stop bridging the analytics firehose (run_start, "
                       "enemy_killed, ...) to R.on. Troubleshooting only.",
        "safe": True,
    },
    {
        "name": "RSMM_EVENT_PROBE",
        "label": "Event payload probe",
        "description": "Attach a raw field window (ev.w38..ev.w70) to every "
                       "gameplay event, for reverse-engineering an undecoded "
                       "payload. Verbose; developers only.",
        "safe": True,
    },
    {
        "name": "RSMM_ENABLE_SKILL_HOOK",
        "label": "Skill hook (read-only)",
        "description": "Log the herodef skill vector at load. Experimental; "
                       "may fail to resolve under Proton on some builds.",
        "safe": True,
    },
    {
        "name": "RSMM_ENABLE_SPAWN_HOOK",
        "label": "Spawn trace (read-only)",
        "description": "Log live spawner vtables. Experimental; read-only.",
        "safe": True,
    },
    {
        "name": "RSMM_ENABLE_UI_HOOK",
        "label": "UI button events",
        "description": "Emit R.on(\"ui:press\") when a native UI button is "
                       "clicked. Needed by mods that add in-game menu actions.",
        "safe": True,
    },
    {
        "name": "RSMM_ENABLE_ITEM_INJECT",
        "label": "Item pool injection",
        "description": "Disabled: crashes the game. Custom items already load "
                       "via UsedRscList — no injection needed.",
        "safe": False,
    },
    {
        "name": "RSMM_ENABLE_SKILL_INJECT",
        "label": "Skill injection (proof-of-path)",
        "description": "Disabled: experimental loader path that duplicates a "
                       "skill slot. For development only.",
        "safe": False,
    },
    {
        "name": "RSMM_DUMP_SYMBOLS",
        "label": "Dump resolved symbols (RE/dev)",
        "description": "At boot, write <game>/rsmm/resolved_symbols.json — the "
                       "addresses the loader actually resolved every semantic "
                       "pattern to. Feeds `rsmm symbols audit`. Read-only; adds "
                       "~1s to load. Dev/RE aid.",
        "safe": True,
    },
]

_LOADER_FLAGS_FILE = "rsmm_loader_flags.json"
_SAFE_FLAG_NAMES = frozenset(f["name"] for f in LOADER_FLAGS if f["safe"])
_KNOWN_FLAG_NAMES = frozenset(f["name"] for f in LOADER_FLAGS)


def _read_loader_flags(flags_path: Path) -> list[str]:
    """Read the enabled-flag list, tolerating a missing/garbage file."""
    if not flags_path.exists():
        return []
    try:
        data = json.loads(flags_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, str) and x in _KNOWN_FLAG_NAMES]


def _loader_status(game_dir: Path) -> dict[str, Any]:
    """Whether the native loader is installed + (on Linux/Proton) whether the
    Steam launch options carry the winhttp override the loader needs. On native
    Windows the override is irrelevant (winhttp.dll loads from the game dir
    directly), so launchOptionsPresent is reported as None there."""
    from rsmm.cli.run import (
        RAVENSWATCH_APP_ID,
        _localconfig_paths,
        _override_present,
        _read_launch_options,
        _steam_root,
    )

    loader_installed = (game_dir / "winhttp.dll").exists()

    launch_present: bool | None = None
    if sys.platform != "win32":
        launch_present = False
        steam_root = _steam_root()
        if steam_root is not None:
            for vdf in _localconfig_paths(steam_root):
                lo = _read_launch_options(vdf, RAVENSWATCH_APP_ID)
                if lo and _override_present(lo):
                    launch_present = True
                    break

    return {
        "loaderInstalled": loader_installed,
        "launchOptionsPresent": launch_present,
    }


def cmd_loader_flags_get() -> int:
    game_dir = find_game_dir()
    if game_dir is None:
        return _emit({
            "ok": True,
            "gameDir": None,
            "flagsPath": None,
            "available": LOADER_FLAGS,
            "enabled": [],
            "loaderInstalled": False,
            "launchOptionsPresent": None,
        })
    flags_path = game_dir / _LOADER_FLAGS_FILE
    return _emit({
        "ok": True,
        "gameDir": str(game_dir),
        "flagsPath": str(flags_path),
        "available": LOADER_FLAGS,
        "enabled": _read_loader_flags(flags_path),
        **_loader_status(game_dir),
    })


def cmd_loader_flags_set(names_json: str) -> int:
    try:
        requested = json.loads(names_json)
    except ValueError as exc:
        return _emit({"ok": False, "error": f"invalid JSON: {exc}"})
    if not isinstance(requested, list) or not all(isinstance(x, str) for x in requested):
        return _emit({"ok": False, "error": "expected a JSON array of flag names"})

    # Only safe flags may be enabled through the UI; silently drop anything
    # unknown or locked so a stale frontend can never arm a crashing flag.
    enabled = sorted({n for n in requested if n in _SAFE_FLAG_NAMES})

    game_dir = find_game_dir()
    if game_dir is None:
        return _emit({"ok": False, "error": "Ravenswatch install not found"})
    flags_path = game_dir / _LOADER_FLAGS_FILE
    try:
        if enabled:
            flags_path.write_text(json.dumps(enabled, indent=2) + "\n", encoding="utf-8")
        elif flags_path.exists():
            # Empty selection → remove the file so the loader logs cleanly.
            flags_path.unlink()
    except OSError as exc:
        return _emit({"ok": False, "error": f"failed to write flags file: {exc}"})

    return _emit({
        "ok": True,
        "gameDir": str(game_dir),
        "flagsPath": str(flags_path),
        "available": LOADER_FLAGS,
        "enabled": enabled,
    })


def cmd_build(rest: list[str]) -> int:
    return _run_rsmm(["build", *rest])


def _uninstall_loader_runtime(game_dir: Path) -> tuple[bool, str]:
    """Best-effort cleanup of loader artifacts for a pure vanilla launch."""
    notes: list[str] = []
    loader_dll = game_dir / "winhttp.dll"
    real_dll = game_dir / "winhttp_real.dll"
    asset_map = game_dir / "asset_map.json"
    rsmm_dir = game_dir / "rsmm"

    try:
        if real_dll.exists():
            if loader_dll.exists():
                loader_dll.unlink()
            shutil.move(str(real_dll), str(loader_dll))
            notes.append("restored stock winhttp.dll")
        elif loader_dll.exists():
            loader_dll.unlink()
            notes.append("removed rsmm winhttp.dll")

        if asset_map.exists():
            asset_map.unlink()
            notes.append("removed asset_map.json")

        if rsmm_dir.exists():
            shutil.rmtree(rsmm_dir)
            notes.append("removed rsmm runtime dir")
    except OSError as e:
        return False, str(e)

    if not notes:
        notes.append("loader artifacts already absent")
    return True, ", ".join(notes)


def cmd_run(rest: list[str]) -> int:
    """Launch the game. Always restores first; --vanilla skips apply and
    cleans up loader artifacts."""
    filtered = [a for a in rest if a != "--vanilla"]
    is_vanilla = len(filtered) < len(rest)

    if is_vanilla:
        restore = _collect_rsmm(["apply", "--restore-all"])
        if not restore["ok"]:
            return _emit(restore)
        game_dir = find_game_dir()
        if game_dir is None:
            return _emit({
                "ok": False,
                "code": 1,
                "stdout": "",
                "stderr": "Could not autodetect Ravenswatch install to clear runtime mods.",
            })
        with contextlib.redirect_stdout(sys.stderr):
            cleared = clear_runtime_mods(game_dir)
        if not cleared:
            return _emit({
                "ok": False,
                "code": 1,
                "stdout": "",
                "stderr": f"Failed to clear runtime mods dir: {game_dir / 'mods'}",
            })
        ok, detail = _uninstall_loader_runtime(game_dir)
        if not ok:
            return _emit({
                "ok": False,
                "code": 1,
                "stdout": "",
                "stderr": f"Failed to uninstall loader artifacts: {detail}",
            })
        print(f"Vanilla cleanup: {detail}", file=sys.stderr)
        return _run_rsmm(["run", "--force", "--vanilla", "--clear-launch-options", *filtered])
    return _run_rsmm(["run", "--force", *filtered])


# --------------------------------------------------------------------------- #
# pack-mod / upload-bytes — publish-to-index helpers consumed by the desktop
# Upload page (`apps/desktop/src/routes/upload.tsx`).
# --------------------------------------------------------------------------- #

#: API-side `modSlugSchema` requires `^[a-z0-9][a-z0-9-_]*$`. Reused so the
#: bridge produces a slug the upload endpoint accepts without round-tripping
#: through a 400.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-_]*$")


def _slugify(value: str) -> str:
    """Best-effort slugify matching the API's slug pattern.

    Lower-cases, swaps disallowed characters for ``-``, collapses runs, and
    ensures the leading character is alphanumeric. Returns ``""`` if nothing
    usable survives — callers should treat that as a hard fail.
    """
    s = value.strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-_")
    if s and not s[0].isalnum():
        s = s.lstrip("-_") or ""
    return s


def cmd_pack_mod(mod_id: str) -> int:
    """Pack ``mods/<mod_id>/`` and return upload metadata.

    Output shape (single JSON object on stdout):

    .. code-block:: json

        {
          "ok": true,
          "path": "/abs/path/to/dist/<id>.zip",
          "sha256": "abcd…64hex",
          "sizeBytes": 12345,
          "slug": "examplecontentboss",
          "version": "0.2.0",
          "manifest": { … modManifestSchema-shaped dict … }
        }

    Hard fails (with ``ok=false`` and a human-readable ``error``) when:

    * the mod folder doesn't exist;
    * the manifest is malformed / missing;
    * ``rsmm pack`` refuses (e.g. vanilla-byte safety check);
    * the slugified id can't satisfy the API's slug pattern.
    """
    src = MODS_DIR / mod_id
    if not src.is_dir():
        return _emit({"ok": False, "error": f"no such mod folder: {src}"})

    mf = src / "manifest.toml"
    raw = _read_manifest(mf)
    if raw is None:
        return _emit({"ok": False, "error": f"missing or unreadable {mf}"})
    manifest = raw.get("mod") if isinstance(raw.get("mod"), dict) else raw
    name = str(manifest.get("name") or mod_id)
    version = str(manifest.get("version") or "0.0.0")

    raw_id = str(manifest.get("id") or mod_id)
    slug = _slugify(raw_id)
    if not _SLUG_RE.match(slug):
        return _emit({
            "ok": False,
            "error": (
                f"mod id {raw_id!r} cannot be slugified to match the API's "
                "slug pattern (lowercase alphanumeric, '-' or '_'). Rename "
                "the mod folder or update [mod].id in manifest.toml."
            ),
        })

    # Run the existing `rsmm pack` so the vanilla-byte safety check
    # applies on upload too. Caller is *not* opted into --allow-vanilla;
    # if their mod ships unmodified game bytes they get a clear error
    # before the upload starts, not after a 500MB PUT.
    pack_result = _collect_rsmm(["pack", mod_id])
    if not pack_result["ok"]:
        return _emit({
            "ok": False,
            "error": "pack failed — see stderr",
            "code": pack_result["code"],
            "stdout": pack_result["stdout"],
            "stderr": pack_result["stderr"],
        })

    zip_path = DIST_DIR / f"{mod_id}.zip"
    if not zip_path.is_file():
        return _emit({"ok": False, "error": f"pack succeeded but {zip_path} missing"})

    h = hashlib.sha256()
    size = 0
    with zip_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    sha = h.hexdigest()

    # Coerce manifest to the upload schema's snake_case shape. Anything
    # the schema marks optional gets dropped if absent so we don't ship
    # nulls that fail z.string().optional().
    out_manifest: dict[str, Any] = {
        "id": slug,
        "name": name,
        "version": version,
    }
    for key in ("author", "summary", "description", "license",
                "repo_url", "homepage_url"):
        v = manifest.get(key)
        if isinstance(v, str) and v.strip():
            out_manifest[key] = v.strip()
    tags = manifest.get("tags")
    if isinstance(tags, list):
        out_manifest["tags"] = [str(t) for t in tags if isinstance(t, str)]
    if isinstance(manifest.get("enabled"), bool):
        out_manifest["enabled"] = bool(manifest["enabled"])
    deps = _deps_map(manifest)
    if deps:
        out_manifest["dependencies"] = deps

    return _emit({
        "ok": True,
        "path": str(zip_path),
        "sha256": sha,
        "sizeBytes": size,
        "slug": slug,
        "version": version,
        "manifest": out_manifest,
    })


_UPLOAD_HOST_ALLOWLIST: tuple[str, ...] = (
    "s3-rsmm.me",
    "ravenswatch-mods.s3.amazonaws.com",
)

# Read once at module load so a malicious on_disable.py cannot inject
# exfiltration targets by setting RSMM_UPLOAD_HOST_ALLOW mid-process.
_UPLOAD_HOST_EXTRA = [
    s.strip().lower()
    for s in os.environ.get("RSMM_UPLOAD_HOST_ALLOW", "").split(",")
    if s.strip()
]


def _upload_url_allowed(url: str) -> bool:
    """Restrict outbound PUTs to known mod-storage hostnames.

    Without this, any caller of cmd_upload_bytes (including a malicious
    on_disable.py hook running via the same Python process) could exfil
    arbitrary files to attacker-controlled URLs, or probe cloud-metadata
    endpoints (169.254.169.254, fd00:ec2::254, …) for SSRF.

    The override env var RSMM_UPLOAD_HOST_ALLOW lets dev/staging point
    the uploader at a different S3-compatible host without editing
    source. It is a *strict* allowlist of hostnames, comma-separated.
    """
    try:
        host = urllib.parse.urlparse(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    allowed = list(_UPLOAD_HOST_ALLOWLIST) + _UPLOAD_HOST_EXTRA
    return host.lower() in allowed


def cmd_upload_bytes(path: str, url: str) -> int:
    """HTTP PUT the file at ``path`` to ``url``.

    Used to push a packed zip to the presigned S3/R2 upload URL the API
    hands back from ``POST /api/mods/upload``. Done CLI-side so the
    browser doesn't need bucket-side CORS; the desktop process has the
    file on disk anyway.

    Returns ``{ok, status?}``. Non-2xx responses set ``ok=false`` with
    the status code in ``status`` and the body in ``error``.
    """
    p = Path(path)
    if not p.is_file():
        return _emit({"ok": False, "error": f"not a file: {path}"})
    if not (url.startswith("https://") or url.startswith("http://")):
        return _emit({"ok": False, "error": f"refusing to PUT to non-http(s) URL: {url}"})
    if not _upload_url_allowed(url):
        return _emit({"ok": False, "error": f"refusing to PUT to non-allowlisted host: {url}"})
    data = p.read_bytes()
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "application/zip")
    req.add_header("Content-Length", str(len(data)))
    # Cloudflare's Browser Integrity Check 403's `Python-urllib/3.x` UAs
    # with error 1010 when the bucket sits behind a CF Tunnel. Send a
    # plausible UA — `rsmm` identifies us; the Chrome suffix bypasses
    # the bot-fingerprint heuristic without lying about the client kind.
    req.add_header(
        "User-Agent",
        "rsmm-uploader/1.0 (compatible; Mozilla/5.0; like Chrome/126)",
    )
    try:
        # 10-minute ceiling matches the desktop's LONG_TIMEOUT_MS.
        with urllib.request.urlopen(req, timeout=600) as resp:
            return _emit({"ok": True, "status": resp.status})
    except urllib.error.HTTPError as e:
        body = ""
        with contextlib.suppress(Exception):
            body = e.read().decode("utf-8", errors="replace")
        return _emit({"ok": False, "status": e.code, "error": body or e.reason})
    except urllib.error.URLError as e:
        return _emit({"ok": False, "error": f"network error: {e.reason}"})
    except OSError as e:
        return _emit({"ok": False, "error": str(e)})


_DEFAULT_INDEX_BASE = "https://api.rsmm.me"


def _index_base() -> str:
    """Resolve the public index URL. ``RSMM_INDEX_URL`` overrides for
    self-hosters / local-dev who run the API on a different host.

    The override is checked, not trusted: it decides where mod *archives* come
    from, and the sha256 that would catch a tampered archive is served over the
    same connection. `net.require_safe_url` allows https anywhere and plain
    http only against loopback, which is exactly the local-dev case.
    """
    base = os.environ.get("RSMM_INDEX_URL", _DEFAULT_INDEX_BASE).rstrip("/")
    net.require_safe_url(base)
    return base


def _api_url(*segments: str) -> str:
    """Build an index URL with every caller-supplied segment escaped.

    A slug or version is interpolated straight into the path; unescaped, a `?`
    or `..` in one would re-point the request at a different endpoint.
    """
    return "/".join([_index_base(), *(urllib.parse.quote(s, safe="") for s in segments)])


def _http_get_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    net.require_safe_url(url)
    req = urllib.request.Request(url, method="GET")
    req.add_header(
        "User-Agent",
        "rsmm-installer/1.0 (compatible; Mozilla/5.0; like Chrome/126)",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        # Capped: an index that streams forever otherwise OOMs the sidecar
        # before anything gets a chance to reject the response.
        raw = net.read_capped(resp, url, limit=net.MAX_METADATA_BYTES)
    return json.loads(raw.decode("utf-8"))


def _mod_target(slug: str) -> Path:
    """``mods/<slug>``, with the slug proven to be a plain directory name.

    The slug arrives straight from argv / the desktop bridge and names a
    directory the installer deletes and replaces, so ``..`` or an embedded
    separator would put that deletion outside ``mods/``.
    """
    return MODS_DIR / archive.safe_dir_name(slug, what="mod slug")


def _extract_downloaded_zip(tmp_path: Path, target: Path, slug: str) -> None | dict[str, Any]:
    """Unpack a downloaded mod zip into ``target``, replacing what's there.

    Unpacks into a staging directory first and swaps it in only once the whole
    archive extracted and a manifest was found. The previous version deleted
    ``target`` up front, so a corrupt or hostile download removed the user's
    working install as a side effect of failing.
    """
    import shutil
    import tempfile
    import zipfile

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".rsmm_dl_{slug}_", dir=target.parent) as td:
        staging = Path(td) / "unpack"
        try:
            with zipfile.ZipFile(tmp_path) as zf:
                overlays = archive.scan_dangerous(zf, slug)
                if overlays:
                    print(f"  [WARN] {slug} overwrites files in the game install root:",
                          file=sys.stderr)
                    for f in overlays:
                        print(f"         {f}", file=sys.stderr)
                # A single wrapping top dir is stripped so files land directly
                # under target; a flat zip is taken as-is.
                top = archive.single_top_dir(zf)
                archive.safe_extract(zf, staging, label=slug,
                                     strip_prefix=f"{top}/" if top else "")
        except archive.ArchiveError as exc:
            return {"ok": False, "error": str(exc)}
        except zipfile.BadZipFile as exc:
            return {"ok": False, "error": f"{slug}: corrupt zip ({exc})"}

        if not (staging / "manifest.toml").exists():
            return {
                "ok": False,
                "error": f"{slug} zip does not contain manifest.toml (required for mod detection)",
            }
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        shutil.move(str(staging), str(target))
    return None


def _download_mod_version(slug: str, version: str, expected_sha: str) -> dict[str, Any]:
    import tempfile

    h = hashlib.sha256()
    tmp = tempfile.NamedTemporaryFile(prefix="rsmm-download-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    dl_url = ""
    try:
        # Inside the try: `_api_url` resolves RSMM_INDEX_URL, which is checked,
        # so a bad override must surface as an error payload rather than a
        # traceback out of the JSON bridge.
        dl_url = _api_url("api", "mods", slug, version, "download")
        req = urllib.request.Request(dl_url, method="GET")
        req.add_header(
            "User-Agent",
            "rsmm-installer/1.0 (compatible; Mozilla/5.0; like Chrome/126)",
        )
        with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310
            with tmp as fh:
                # Capped: the digest can only be checked once the whole archive
                # has landed, so without a ceiling a hostile index fills the
                # disk before anything is in a position to reject it.
                size = net.copy_capped(resp, fh, dl_url, hasher=h)
        got_sha = h.hexdigest()
        if got_sha != expected_sha:
            return {
                "ok": False,
                "error": f"sha256 mismatch: expected {expected_sha}, got {got_sha}",
            }
        return {"ok": True, "sizeBytes": size, "tmp_path": tmp_path}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"download failed: HTTP {e.code} {e.reason}"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "error": f"download failed: {e}"}
    finally:
        with contextlib.suppress(Exception):
            tmp.close()


def cmd_install_mod(slug: str) -> int:
    """Fetch the latest version of <slug> from the public index and
    extract its zip into ``mods/<slug>/``.
    """
    try:
        target = _mod_target(slug)
    except archive.ArchiveError as e:
        return _emit({"ok": False, "error": str(e)})
    try:
        detail = _http_get_json(_api_url("api", "mods", slug))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return _emit({"ok": False, "error": f"mod {slug!r} not found in the index"})
        return _emit({"ok": False, "error": f"index lookup failed: HTTP {e.code} {e.reason}"})
    except (urllib.error.URLError, OSError, ValueError) as e:
        return _emit({"ok": False, "error": f"index lookup failed: {e}"})

    versions = detail.get("versions") or []
    if not versions:
        return _emit({"ok": False, "error": f"{slug} has no published versions"})

    versions.sort(key=lambda v: str(v.get("createdAt") or ""), reverse=True)
    latest = versions[0]
    version = str(latest.get("version") or "")
    expected_sha = str(latest.get("sha256") or "").lower()
    if not version or len(expected_sha) != 64:
        return _emit({"ok": False, "error": "version row missing version/sha256"})

    download = _download_mod_version(slug, version, expected_sha)
    if not download["ok"]:
        return _emit(download)
    try:
        extracted = _extract_downloaded_zip(download["tmp_path"], target, slug)
        if extracted is not None:
            return _emit(extracted)
    finally:
        with contextlib.suppress(Exception):
            download["tmp_path"].unlink(missing_ok=True)

    return _emit({
        "ok": True,
        "slug": slug,
        "version": version,
        "sha256": expected_sha,
        "sizeBytes": download["sizeBytes"],
        "installedTo": str(target),
    })


def cmd_install_mod_version(slug: str, version: str) -> int:
    try:
        target = _mod_target(slug)
    except archive.ArchiveError as e:
        return _emit({"ok": False, "error": str(e)})
    try:
        detail = _http_get_json(_api_url("api", "mods", slug))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return _emit({"ok": False, "error": f"mod {slug!r} not found in the index"})
        return _emit({"ok": False, "error": f"index lookup failed: HTTP {e.code} {e.reason}"})
    except (urllib.error.URLError, OSError, ValueError) as e:
        return _emit({"ok": False, "error": f"index lookup failed: {e}"})

    versions = detail.get("versions") or []
    match = next((v for v in versions if str(v.get("version") or "") == version), None)
    if not match:
        return _emit({"ok": False, "error": f"{slug} has no published version {version!r}"})
    expected_sha = str(match.get("sha256") or "").lower()
    if len(expected_sha) != 64:
        return _emit({"ok": False, "error": "version row missing sha256"})

    download = _download_mod_version(slug, version, expected_sha)
    if not download["ok"]:
        return _emit(download)
    try:
        extracted = _extract_downloaded_zip(download["tmp_path"], target, slug)
        if extracted is not None:
            return _emit(extracted)
    finally:
        with contextlib.suppress(Exception):
            download["tmp_path"].unlink(missing_ok=True)

    return _emit({
        "ok": True,
        "slug": slug,
        "version": version,
        "sha256": expected_sha,
        "sizeBytes": download["sizeBytes"],
        "installedTo": str(target),
    })


def cmd_loader_log(lines: int = 400, prev: bool = False, all_sessions: bool = False) -> int:
    """Read the in-game loader log for the desktop Log tab.

    The path comes from `cmd_log.log_file` rather than being rebuilt here —
    the home screen's Log tab derived it independently once and got it wrong
    (`<game>/rsmm/rsmm_log.txt`, which has never existed), so the tab sat
    permanently blank while `rsmm log` worked.

    A missing file is NOT an error: the loader only writes one after the game
    has run once with it installed, which is the common case on a fresh
    install. `exists: false` lets the UI say so instead of showing a failure.
    """
    from rsmm.cli.cmd_log import _SESSION_MARK, log_file

    game_dir = find_game_dir()
    path = log_file(game_dir, prev=prev)
    try:
        exists = path.is_file()
    except OSError:
        exists = False
    if not exists:
        return _emit({
            "path": str(path), "exists": False, "gameDir": str(game_dir or ""),
            "lines": [], "truncated": False, "sessions": 0,
        })
    try:
        with open(path, errors="replace") as f:
            raw = f.read().splitlines()
    except OSError as e:
        print(f"error: could not read loader log {path}: {e}", file=sys.stderr)
        return 1

    sessions = sum(1 for ln in raw if _SESSION_MARK in ln)
    selected = raw
    if not all_sessions:
        # Default to the current run only; the file keeps every session that
        # has been appended since the last rotation.
        for i in range(len(selected) - 1, -1, -1):
            if _SESSION_MARK in selected[i]:
                selected = selected[i:]
                break
    truncated = bool(lines and lines > 0 and len(selected) > lines)
    if truncated:
        selected = selected[-lines:]
    return _emit({
        "path": str(path),
        "exists": True,
        "gameDir": str(game_dir or ""),
        "lines": selected,
        "truncated": truncated,
        "sessions": sessions,
    })


def cmd_overlays() -> int:
    """Every mod-declared overlay, with its live rows — the desktop HUD feed.

    Overlays are declared by MODS (an `[overlay]` block in manifest.toml) and
    filled at runtime through `R.overlay.publish`; the client only draws what
    it is handed. Parsing lives in cmd_overlay so the desktop window and
    `rsmm overlay` can never disagree about what a row means.
    """
    from rsmm.cli.cmd_overlay import discover

    game_dir = find_game_dir()
    return _emit({
        "gameDir": str(game_dir or ""),
        "overlays": discover(game_dir),
    })


def cmd_conflicts() -> int:
    """
    Detect all conflicts among enabled mods:

      - file-path: two+ mods write the same asset file
      - patch-field: two+ mods patch the same stat/texture/url/text field
      - manifest: mods declare hard conflicts via `conflicts = [...]`
    """
    conflicts: list[dict[str, object]] = []

    tracked_paths: dict[str, list[str]] = {}
    try:
        if MODS_DIR.is_dir():
            for entry in sorted(MODS_DIR.iterdir()):
                if not entry.is_dir() or entry.name.startswith(("_", ".")):
                    continue
                raw = _read_manifest(entry / "manifest.toml")
                if raw is None:
                    continue
                manifest = raw.get("mod") if isinstance(raw.get("mod"), dict) else raw
                if not bool(manifest.get("enabled", True)):
                    continue
                mod_id = entry.name
                assets_dir = entry / "assets"
                if assets_dir.is_dir():
                    for f in assets_dir.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(assets_dir).as_posix()
                            tracked_paths.setdefault(rel, []).append(mod_id)
    except (OSError, PermissionError):
        pass
    for path, mod_ids in tracked_paths.items():
        if len(mod_ids) > 1:
            conflicts.append({
                "type": "file",
                "path": path,
                "modIds": mod_ids,
            })

    patches = collect_patches()
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
    for key, owners in by_key.items():
        if len({repr(v) for v in owners.values()}) > 1:
            kind = key[0]
            if kind == "stat":
                field = ".".join(str(k) for k in key[1:])
                conflicts.append({
                    "type": "patch",
                    "patchKind": "stat",
                    "field": field,
                    "modIds": list(owners.keys()),
                    "values": {m: repr(v) for m, v in owners.items()},
                })
            elif kind == "texture":
                conflicts.append({
                    "type": "patch",
                    "patchKind": "texture",
                    "target": key[1],
                    "modIds": list(owners.keys()),
                    "values": {m: repr(v) for m, v in owners.items()},
                })
            else:
                conflicts.append({
                    "type": "patch",
                    "patchKind": kind,
                    "modIds": list(owners.keys()),
                    "values": {m: repr(v) for m, v in owners.items()},
                })

    try:
        if MODS_DIR.is_dir():
            from rsmm.cli.compat import analyze
            rep = analyze()
            for a, b in rep.hard_conflicts:
                conflicts.append({
                    "type": "manifest",
                    "modIds": [a, b],
                })
    except Exception as e:
        # Best-effort: a malformed manifest shouldn't blank the whole
        # conflict panel, but the UI must not silently under-report either.
        logger.warning("conflict analysis incomplete: %s", e)

    return _emit(conflicts)


def cmd_doctor(fix: bool = False, force: bool = False) -> int:
    """
    Run doctor as a subprocess so the UI can display the raw, coloured
    output verbatim, alongside a structured per-finding list.

    Two runs, deliberately: `--json` for the machine-readable findings
    (codes, severities, and whether each has an automated repair) and a
    plain run for the coloured transcript the panel shows. Scraping the
    coloured output for status was the old approach — a wording change
    silently emptied the UI's check list.
    """
    checks: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    argv = ["doctor", "--json"]
    if fix:
        argv.append("--fix")
    if force:
        argv.append("--force")
    try:
        structured = subprocess.run(
            self_cmd(argv), cwd=REPO_ROOT,
            capture_output=True, text=True, check=False,
        )
        payload = json.loads(structured.stdout or "{}")
    except (FileNotFoundError, json.JSONDecodeError):
        payload = {}
    for section in payload.get("sections", []):
        for r in section.get("results", []):
            checks.append({
                "status": r.get("kind"),
                "ok": r.get("kind") == "OK",
                "label": r.get("label", ""),
                "detail": r.get("detail", ""),
                "code": r.get("code", ""),
                "section": section.get("section", ""),
                "fix": r.get("fix"),
                "fixable": bool((r.get("fix") or {}).get("automatic")),
            })
    repairs = payload.get("repairs", [])

    cmd = self_cmd(["doctor"] + (["--fix"] if fix else []) +
                   (["--force"] if force else []))
    try:
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as e:
        return _emit({"ok": False, "code": 127, "stdout": "", "stderr": str(e),
                      "checks": checks, "repairs": repairs})

    # Structured game-update flag so the UI doesn't have to grep doctor's
    # prose. True = the install changed since the last apply (Steam patch
    # or file verify); a plain `apply` auto-recovers.
    game_updated: bool | None = None
    try:
        from rsmm.engine.paths import game_fingerprint, load_stored_fingerprint

        game_dir = find_game_dir()
        if game_dir is not None:
            stored = load_stored_fingerprint(game_dir)
            if stored is not None:
                game_updated = game_fingerprint(game_dir) != stored
    except Exception:  # noqa: BLE001 — diagnostics must never break doctor
        game_updated = None

    return _emit({
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "checks": checks,
        "repairs": repairs,
        "fixable": sum(1 for c in checks if c["fixable"] and not c["ok"]),
        "gameUpdated": game_updated,
    })


def cmd_update_data(check_only: bool) -> int:
    """
    Check for (and by default install) a newer function-pattern DB from
    the rolling `pattern-db` release — lets users pick up regenerated
    engine-function patterns after a game update without a new app release.
    """
    game_dir = find_game_dir()
    if game_dir is None:
        return _emit({"ok": False, "status": "error",
                      "error": "game directory not found"})
    try:
        from rsmm.engine.data_update import apply_update, check

        state = check(game_dir)
        if not check_only and state["status"] in ("update_available", "not_planted"):
            state = apply_update(game_dir, state)
        state.pop("_raw", None)
        meta = state.get("remote_meta") or {}
        return _emit({
            "ok": True,
            "status": state["status"],
            "exeMatch": state["exe_match"],
            "generated": meta.get("generated"),
            "patternCount": meta.get("pattern_count"),
            "plantedPath": state["planted_path"],
        })
    except Exception as e:  # noqa: BLE001 — bridge must always emit JSON
        return _emit({"ok": False, "status": "error", "error": str(e)})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm json",
        description="Machine-readable JSON bridge for the desktop / web UI.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list installed mods")
    p_apply = sub.add_parser("apply", help="run apply")
    p_apply.add_argument("--dry-run", action="store_true")
    p_apply.add_argument("--force", action="store_true")
    p_apply.add_argument("--no-merge", action="store_true")
    sub.add_parser("active-overrides", help="check whether any active overrides exist")
    sub.add_parser("restore-all", help="restore every active override")
    sub.add_parser("build", help="build asset map + loader + merge + apply")
    sub.add_parser("conflicts", help="detect all conflicts among enabled mods")
    sub.add_parser("overlays", help="read every mod-declared overlay + its live rows")
    p_log = sub.add_parser("loader-log", help="read the in-game loader log")
    p_log.add_argument("--lines", type=int, default=400,
                       help="cap on returned lines (0 = no cap)")
    p_log.add_argument("--prev", action="store_true",
                       help="read the previous run's log (_log.prev.txt)")
    p_log.add_argument("--all", action="store_true", dest="all_sessions",
                       help="return every session in the file, not just the latest")
    p_doctor = sub.add_parser("doctor", help="system health check")
    p_doctor.add_argument("--fix", action="store_true",
                          help="run the automated repair for every fixable finding")
    p_doctor.add_argument("--force", action="store_true",
                          help="with --fix, also run destructive repairs")
    p_run = sub.add_parser("run", help="launch the game")
    p_run.add_argument("--vanilla", action="store_true", help="restore originals before launching")
    p_pack = sub.add_parser("pack-mod", help="pack a mod for upload + return metadata")
    p_pack.add_argument("mod_id", help="folder name under mods/")
    p_up = sub.add_parser("upload-bytes", help="HTTP PUT a file to a presigned URL")
    p_up.add_argument("path", help="local file to upload")
    p_up.add_argument("url", help="presigned PUT URL")
    p_inst = sub.add_parser("install-mod", help="download a mod from the index + extract")
    p_inst.add_argument("slug", help="mod slug to install (latest published version)")
    p_inst_v = sub.add_parser("install-mod-version", help="download a specific mod version")
    p_inst_v.add_argument("slug", help="mod slug to install")
    p_inst_v.add_argument("version", help="version to install")
    p_cfg = sub.add_parser("config", help="read or update a mod's config")
    cfg_sub = p_cfg.add_subparsers(dest="config_cmd", required=True)
    p_cfg_get = cfg_sub.add_parser("get", help="read config schema + current values")
    p_cfg_get.add_argument("mod_id", help="folder name under mods/")
    p_cfg_set = cfg_sub.add_parser("set", help="replace config values")
    p_cfg_set.add_argument("mod_id", help="folder name under mods/")
    p_cfg_set.add_argument("values_json", help="JSON object with config values")
    p_uninstall = sub.add_parser("uninstall-mod", help="remove a mod from mods/<id>/")
    p_uninstall.add_argument("mod_id", help="folder name under mods/")
    p_flags = sub.add_parser("loader-flags", help="read or set loader feature flags")
    flags_sub = p_flags.add_subparsers(dest="flags_cmd", required=True)
    flags_sub.add_parser("get", help="list available flags + which are enabled")
    p_flags_set = flags_sub.add_parser("set", help="set the enabled-flag list")
    p_flags_set.add_argument("names_json", help="JSON array of flag names to enable")
    p_upd = sub.add_parser("update-data",
                           help="fetch + install the latest function-pattern DB")
    p_upd.add_argument("--check", action="store_true",
                       help="report status only, do not install")

    args = ap.parse_args(argv)
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "apply":
        rest = []
        if args.dry_run:
            rest.append("--dry-run")
        if args.force:
            rest.append("--force")
        if args.no_merge:
            rest.append("--no-merge")
        return cmd_apply(rest)
    if args.cmd == "overlays":
        return cmd_overlays()
    if args.cmd == "active-overrides":
        return cmd_active_overrides()
    if args.cmd == "restore-all":
        return cmd_restore_all()
    if args.cmd == "build":
        return cmd_build([])
    if args.cmd == "conflicts":
        return cmd_conflicts()
    if args.cmd == "loader-log":
        return cmd_loader_log(lines=args.lines, prev=args.prev,
                              all_sessions=args.all_sessions)
    if args.cmd == "doctor":
        return cmd_doctor(fix=args.fix, force=args.force)
    if args.cmd == "run":
        rest = []
        if args.vanilla:
            rest.append("--vanilla")
        return cmd_run(rest)
    if args.cmd == "pack-mod":
        return cmd_pack_mod(args.mod_id)
    if args.cmd == "upload-bytes":
        return cmd_upload_bytes(args.path, args.url)
    if args.cmd == "install-mod":
        return cmd_install_mod(args.slug)
    if args.cmd == "install-mod-version":
        return cmd_install_mod_version(args.slug, args.version)
    if args.cmd == "config":
        if args.config_cmd == "get":
            return cmd_config_get(args.mod_id)
        if args.config_cmd == "set":
            return cmd_config_set(args.mod_id, args.values_json)
        ap.error(f"unknown config subcommand: {args.config_cmd}")
        return 2
    if args.cmd == "uninstall-mod":
        return cmd_uninstall_mod(args.mod_id)
    if args.cmd == "update-data":
        return cmd_update_data(args.check)
    if args.cmd == "loader-flags":
        if args.flags_cmd == "get":
            return cmd_loader_flags_get()
        if args.flags_cmd == "set":
            return cmd_loader_flags_set(args.names_json)
        ap.error(f"unknown loader-flags subcommand: {args.flags_cmd}")
        return 2
    ap.error(f"unknown subcommand: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
