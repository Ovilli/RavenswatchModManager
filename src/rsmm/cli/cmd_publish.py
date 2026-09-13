"""rsmm publish — upload a mod to the store from the command line.

    rsmm publish login              store a personal API token (prompted, never an argument)
    rsmm publish logout             forget the stored token
    rsmm publish whoami             show which account the token publishes as
    rsmm publish <mod> [--no-wait] [--timeout SECONDS]

One command does what the website's publish page does: lint the mod, pack it
(refusing shipped game bytes), ask the API for a presigned upload, PUT the zip
with its checksum, queue the malware scan, and wait until the version is live.
A version is downloadable only once its scan comes back clean — that gate is
server-side and a token cannot skip it.

The token is a personal API token created on the website's account page. It can
publish versions of your own mods and nothing else (see apps/api/src/api-tokens.ts).
It is read from ``RSMM_API_TOKEN`` or from a credentials file written by
``rsmm publish login`` with owner-only permissions. It is never accepted as a
command-line argument, because arguments end up in shell history and in the
process list, and it is never sent anywhere but HTTPS (localhost excepted, for
a local API).
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"^rsmm_pat_[A-Za-z0-9_-]{43}$")
DEFAULT_API = "https://api.rsmm.me"
USER_AGENT = "rsmm-publish/1.0 (compatible; Mozilla/5.0; like Chrome/126)"
LIVE = {"clean", "skipped"}
FAILED = {"flagged", "error"}


class PublishError(Exception):
    """A step failed; the message is what the user should read."""


# --- configuration ------------------------------------------------------------

def api_base() -> str:
    return os.environ.get("RSMM_INDEX_URL", DEFAULT_API).rstrip("/")


def _check_transport(base: str) -> None:
    """Refuse to send a token over plain HTTP to anything but this machine."""
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return
    raise PublishError(
        f"refusing to send an API token to {base}: use https (http is only allowed "
        f"for localhost)")


def credentials_path() -> Path:
    override = os.environ.get("RSMM_CREDENTIALS_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "rsmm" / "credentials.json"


def _read_credentials() -> dict[str, str]:
    p = credentials_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_credentials(data: dict[str, str]) -> Path:
    """Write owner-only (0600), created that way rather than chmod'd after."""
    p = credentials_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, p)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()
    with contextlib.suppress(OSError):
        os.chmod(p, 0o600)
    return p


def resolve_token() -> str:
    token = os.environ.get("RSMM_API_TOKEN", "").strip()
    if not token:
        token = str(_read_credentials().get(api_base(), "")).strip()
    if not token:
        raise PublishError(
            "no API token. Create one on your account page (rsmm.me/account), then run "
            "`rsmm publish login` or set RSMM_API_TOKEN")
    if not TOKEN_RE.match(token):
        raise PublishError("the stored API token is malformed; run `rsmm publish login` again")
    return token


def mask(token: str) -> str:
    return token[:13] + "…"


# --- HTTP ---------------------------------------------------------------------

def _request(method: str, path: str, token: str, body: dict | None = None,
             timeout: float = 60) -> tuple[int, Any]:
    base = api_base()
    _check_transport(base)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        payload: Any = {}
        with contextlib.suppress(Exception):
            payload = json.loads(e.read() or b"{}")
        return e.code, payload
    except urllib.error.URLError as e:
        raise PublishError(f"cannot reach {base}: {e.reason}") from e


def _error(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return payload["error"]
    return fallback


def whoami(token: str) -> dict[str, Any]:
    status, payload = _request("GET", "/api/me", token)
    if status == 401:
        raise PublishError(
            "the API token was rejected: it is revoked, expired, or the account is not "
            "verified. Create a new one on your account page")
    if status != 200 or not isinstance(payload, dict):
        raise PublishError(_error(payload, f"identity check failed (HTTP {status})"))
    return payload


# --- steps --------------------------------------------------------------------

def _lint(mod_id: str) -> None:
    from rsmm.cli.json_bridge import _collect_rsmm

    result = _collect_rsmm(["lint", mod_id])
    if not result["ok"]:
        sys.stderr.write(result.get("stdout") or "")
        sys.stderr.write(result.get("stderr") or "")
        raise PublishError(f"`rsmm lint {mod_id}` failed; fix the errors above first")


def publish(mod_id: str, *, wait: bool = True, timeout: float = 900,
            poll: float = 5.0, out=print) -> int:
    token = resolve_token()
    me = whoami(token)
    out(f"Publishing {mod_id} as {me.get('name') or me.get('id')} ({mask(token)})")

    out("  linting…")
    _lint(mod_id)

    from rsmm.cli.json_bridge import pack_mod_metadata, put_bytes

    out("  packing…")
    pack = pack_mod_metadata(mod_id)
    if not pack.get("ok"):
        if pack.get("stderr"):
            sys.stderr.write(str(pack["stderr"]))
        raise PublishError(str(pack.get("error") or "pack failed"))
    out(f"  {pack['slug']} {pack['version']} — {pack['sizeBytes']:,} bytes")

    status, up = _request("POST", "/api/mods/upload", token, {
        "slug": pack["slug"], "version": pack["version"], "manifest": pack["manifest"],
        "sha256": pack["sha256"], "sizeBytes": pack["sizeBytes"],
    })
    if status == 409:
        raise PublishError(
            f"version {pack['version']} is already published; bump [mod].version in "
            f"manifest.toml")
    if status == 403:
        raise PublishError(_error(up, "this mod slug belongs to another account"))
    if status == 429:
        raise PublishError("upload rate limit reached (5 per hour); try again later")
    if status != 200 or not isinstance(up, dict) or "uploadUrl" not in up:
        raise PublishError(_error(up, f"upload request failed (HTTP {status})"))

    out("  uploading…")
    put = put_bytes(pack["path"], up["uploadUrl"])
    if not put.get("ok"):
        raise PublishError(f"upload failed: {put.get('error') or put.get('status')}")

    version_id = up["versionId"]
    status, scan = _request("POST", f"/api/mods/versions/{version_id}/scan", token)
    if status != 200 or not isinstance(scan, dict):
        raise PublishError(_error(scan, f"could not queue the malware scan (HTTP {status})"))

    state = scan.get("status")
    if state in LIVE:
        out(f"Live: {pack['slug']} {pack['version']}")
        return 0
    if not wait:
        out(f"Uploaded. Scan {state}; the version goes live when it comes back clean.")
        return 0

    out("  waiting for the malware scan (the version goes live when it is clean)…")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll)
        status, info = _request("GET", f"/api/mods/versions/{version_id}/scan-status", token)
        if status != 200 or not isinstance(info, dict):
            continue
        state = info.get("status")
        if state in LIVE:
            out(f"Live: {pack['slug']} {pack['version']}")
            return 0
        if state in FAILED:
            raise PublishError(
                f"the malware scan came back {state}; the version is not downloadable")
        pos = info.get("position")
        if pos is not None:
            out(f"    queued, position {pos}")
    out(f"Still scanning after {int(timeout)}s. It will go live on its own once clean.")
    return 0


# --- CLI ----------------------------------------------------------------------

def _login(out=print) -> int:
    if sys.stdin.isatty():
        token = getpass.getpass("Paste your API token (input hidden): ").strip()
    else:
        token = sys.stdin.readline().strip()
    if not TOKEN_RE.match(token):
        raise PublishError("that does not look like an rsmm API token (rsmm_pat_…)")
    me = whoami(token)
    creds = _read_credentials()
    creds[api_base()] = token
    path = _write_credentials(creds)
    out(f"Saved token for {me.get('name') or me.get('id')} to {path}")
    return 0


def _logout(out=print) -> int:
    creds = _read_credentials()
    if creds.pop(api_base(), None) is None:
        out("No stored token for this API.")
        return 0
    _write_credentials(creds)
    out("Forgot the stored token. Revoke it on your account page if it may have leaked.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="rsmm publish", description=__doc__.split("\n\n")[0])
    ap.add_argument("target", help="login | logout | whoami | <mod id>")
    ap.add_argument("--no-wait", action="store_true",
                    help="return once uploaded instead of waiting for the scan")
    ap.add_argument("--timeout", type=float, default=900,
                    help="seconds to wait for the scan (default 900)")
    args = ap.parse_args(argv)
    try:
        if args.target == "login":
            return _login()
        if args.target == "logout":
            return _logout()
        if args.target == "whoami":
            token = resolve_token()
            me = whoami(token)
            print(f"{me.get('name') or '?'} ({me.get('id')}) via {mask(token)} on {api_base()}")
            return 0
        return publish(args.target, wait=not args.no_wait, timeout=args.timeout)
    except PublishError as e:
        print(f"rsmm publish: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
