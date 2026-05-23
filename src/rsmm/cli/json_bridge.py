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
from rsmm.engine.paths import DIST_DIR, MODS_DIR, REPO_ROOT, self_cmd


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


def cmd_list() -> int:
    items: list[dict[str, Any]] = []
    if not MODS_DIR.is_dir():
        return _emit([])
    for entry in sorted(MODS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        raw = _read_manifest(entry / "manifest.toml")
        if raw is None:
            continue
        # Manifests use [mod] table for metadata; older ones inline at root.
        manifest = raw.get("mod") if isinstance(raw.get("mod"), dict) else raw
        items.append({
            "id": manifest.get("id", entry.name),
            "slug": entry.name,
            "name": manifest.get("name", entry.name),
            "version": str(manifest.get("version", "0.0.0")),
            "author": manifest.get("author"),
            "summary": manifest.get("summary") or manifest.get("description"),
            "license": manifest.get("license"),
            "tags": manifest.get("tags") or [],
            "enabled": bool(manifest.get("enabled", True)),
            "path": str(entry),
        })
    return _emit(items)


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
    """Launch the game. --vanilla restores originals first."""
    args = ["run", "--force"]
    filtered = [a for a in rest if a != "--vanilla"]
    if len(filtered) < len(rest):
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
        args.extend(["--force", "--clear-launch-options"])
    return _run_rsmm([*args, *filtered])


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
    deps = manifest.get("dependencies")
    if isinstance(deps, dict) and deps:
        out_manifest["dependencies"] = {str(k): str(v) for k, v in deps.items()}

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
    "s3-ravenswatch.ovilli.de",
    "ravenswatch-mods.s3.amazonaws.com",
)


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
    extra = os.environ.get("RSMM_UPLOAD_HOST_ALLOW", "")
    allowed = list(_UPLOAD_HOST_ALLOWLIST) + [
        s.strip().lower() for s in extra.split(",") if s.strip()
    ]
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


_DEFAULT_INDEX_BASE = "https://api.ravenswatch.ovilli.de"


def _index_base() -> str:
    """Resolve the public index URL. ``RSMM_INDEX_URL`` overrides for
    self-hosters / local-dev who run the API on a different host."""
    return os.environ.get("RSMM_INDEX_URL", _DEFAULT_INDEX_BASE).rstrip("/")


def _http_get_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    req.add_header(
        "User-Agent",
        "rsmm-installer/1.0 (compatible; Mozilla/5.0; like Chrome/126)",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


_DANGEROUS_EXTENSIONS = frozenset({
    ".exe", ".dll", ".sys", ".drv", ".scr", ".cpl",
    ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
    ".ps1", ".psm1", ".psd1", ".ps1xml",
    ".sh", ".bash", ".zsh",
    ".bat", ".cmd",
    ".jar", ".py", ".pyc", ".pyd",
    ".wasm", ".php", ".asp", ".aspx", ".jsp",
})

_DANGEROUS_ROOT_EXTENSIONS = frozenset({
    ".exe", ".dll", ".sys", ".drv", ".scr", ".cpl",
    ".vbs", ".vbe", ".ps1", ".bat", ".cmd", ".sh",
})


def cmd_install_mod(slug: str) -> int:
    """Fetch the latest version of <slug> from the public index and
    extract its zip into ``mods/<slug>/``.
    """
    import shutil
    import tempfile
    import zipfile

    base = _index_base()
    try:
        detail = _http_get_json(f"{base}/api/mods/{slug}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return _emit({"ok": False, "error": f"mod {slug!r} not found in the index"})
        return _emit({"ok": False, "error": f"index lookup failed: HTTP {e.code} {e.reason}"})
    except (urllib.error.URLError, OSError, ValueError) as e:
        return _emit({"ok": False, "error": f"index lookup failed: {e}"})

    versions = detail.get("versions") or []
    if not versions:
        return _emit({"ok": False, "error": f"{slug} has no published versions"})

    # Detail endpoint returns versions in insertion order. Sort by
    # createdAt descending so the *newest* wins regardless of API order.
    versions.sort(key=lambda v: str(v.get("createdAt") or ""), reverse=True)
    latest = versions[0]
    version = str(latest.get("version") or "")
    expected_sha = str(latest.get("sha256") or "").lower()
    if not version or len(expected_sha) != 64:
        return _emit({"ok": False, "error": "version row missing version/sha256"})

    # Stream the download. Following 30x to the storage URL also bumps
    # the API's download-count tracker (see /:slug/:version/download).
    dl_url = f"{base}/api/mods/{slug}/{version}/download"
    h = hashlib.sha256()
    tmp = tempfile.NamedTemporaryFile(prefix=f"rsmm-{slug}-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    try:
        req = urllib.request.Request(dl_url, method="GET")
        req.add_header(
            "User-Agent",
            "rsmm-installer/1.0 (compatible; Mozilla/5.0; like Chrome/126)",
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            with tmp as fh:
                size = 0
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
                    size += len(chunk)
                    fh.write(chunk)
        got_sha = h.hexdigest()
        if got_sha != expected_sha:
            return _emit({
                "ok": False,
                "error": f"sha256 mismatch: expected {expected_sha}, got {got_sha}",
            })

        target = MODS_DIR / slug
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(tmp_path) as zf:
            blocked: list[str] = []
            root_danger: list[str] = []
            for entry in zf.infolist():
                name = entry.filename
                parts = name.replace("\\", "/").split("/", 1)
                inner = parts[1] if len(parts) > 1 else parts[0]
                ext = Path(inner).suffix.lower()
                if ext in _DANGEROUS_EXTENSIONS:
                    blocked.append(name)
                if inner.startswith("_root/"):
                    rel = inner[len("_root/"):]
                    if Path(rel).suffix.lower() in _DANGEROUS_ROOT_EXTENSIONS:
                        root_danger.append(rel)
            if blocked:
                return _emit({
                    "ok": False,
                    "error": f"{slug} contains blocked file type(s):\n  "
                    + "\n  ".join(blocked[:20]),
                })
            if root_danger:
                print(
                    f"  [WARN] {slug} overwrites game root files:",
                    file=sys.stderr,
                )
                for f in root_danger:
                    print(f"         {f}", file=sys.stderr)
            # If every member shares the same top-level dir, strip it so
            # files land directly under `mods/<slug>/`. Matches the
            # shape `rsmm pack` produces (`<mod_id>/manifest.toml`, ...).
            names = [n for n in zf.namelist() if not n.endswith("/")]
            top_dirs = {n.split("/", 1)[0] for n in names if "/" in n}
            strip = (
                len(top_dirs) == 1 and all("/" in n for n in names)
            )
            stripped_prefix = next(iter(top_dirs)) + "/" if strip else ""
            for member in zf.infolist():
                name = member.filename
                if name.endswith("/"):
                    continue
                rel = (
                    name[len(stripped_prefix):]
                    if strip and name.startswith(stripped_prefix)
                    else name
                )
                # Defense in depth — zip slip protection. `normpath` does
                # not collapse symlinks and does not catch Windows UNC
                # paths such as `\\server\share\foo`. Resolve the final
                # destination and confirm it sits under `target` before
                # any open() call.
                rel_norm = os.path.normpath(rel)
                if rel_norm.startswith("..") or os.path.isabs(rel_norm):
                    return _emit({
                        "ok": False,
                        "error": f"refusing zip entry with traversal/abs path: {name!r}",
                    })
                dest = (target / rel_norm).resolve()
                target_resolved = target.resolve()
                try:
                    dest.relative_to(target_resolved)
                except ValueError:
                    return _emit({
                        "ok": False,
                        "error": f"refusing zip entry that escapes target: {name!r}",
                    })
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    finally:
        with contextlib.suppress(Exception):
            tmp_path.unlink(missing_ok=True)

    return _emit({
        "ok": True,
        "slug": slug,
        "version": version,
        "sha256": expected_sha,
        "sizeBytes": size,
        "installedTo": str(target),
    })


def cmd_doctor() -> int:
    """
    Run doctor as a subprocess so the UI can display the raw, coloured
    output verbatim, but also parse a coarse OK/WARN/FAIL line tally
    from the printed summary for at-a-glance status.
    """
    cmd = self_cmd(["doctor"])
    try:
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as e:
        return _emit({"ok": False, "code": 127, "stdout": "", "stderr": str(e),
                      "checks": []})

    checks: list[dict[str, Any]] = []
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        for tag in ("OK", "WARN", "FAIL"):
            prefix = f"[{tag}]"
            if line.startswith(prefix):
                checks.append({
                    "status": tag,
                    "ok": tag == "OK",
                    "label": line[len(prefix):].strip(),
                })
                break

    return _emit({
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "checks": checks,
    })


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
    sub.add_parser("restore-all", help="restore every active override")
    sub.add_parser("build", help="build asset map + loader + merge + apply")
    sub.add_parser("doctor", help="system health check")
    p_run = sub.add_parser("run", help="launch the game")
    p_run.add_argument("--vanilla", action="store_true", help="restore originals before launching")
    p_pack = sub.add_parser("pack-mod", help="pack a mod for upload + return metadata")
    p_pack.add_argument("mod_id", help="folder name under mods/")
    p_up = sub.add_parser("upload-bytes", help="HTTP PUT a file to a presigned URL")
    p_up.add_argument("path", help="local file to upload")
    p_up.add_argument("url", help="presigned PUT URL")
    p_inst = sub.add_parser("install-mod", help="download a mod from the index + extract")
    p_inst.add_argument("slug", help="mod slug to install (latest published version)")

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
    if args.cmd == "restore-all":
        return cmd_restore_all()
    if args.cmd == "build":
        return cmd_build([])
    if args.cmd == "doctor":
        return cmd_doctor()
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
    ap.error(f"unknown subcommand: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
